using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Unity.Netcode;

namespace TcgEngine.Server
{
    /// <summary>
    /// Main server script for the matchmaker
    /// will receive player request and then match players together and send them the game uid and game url to connect to
    /// </summary>

    public class ServerMatchmaker : MonoBehaviour
    {
        [Header("Matchmaker")]
        public string[] servers;

        private Dictionary<ulong, ClientData> client_list = new Dictionary<ulong, ClientData>();  //List of clients
        private Dictionary<string, MatchPlayerData> matchmaking_players = new Dictionary<string, MatchPlayerData>(); //Get deleted every 20 sec
        private Dictionary<string, string> matched_players = new Dictionary<string, string>(); //user_id -> uid
        private Dictionary<string, MatchData> started_matches = new Dictionary<string, MatchData>(); //UID => match
        private List<MatchPlayerData> valid_users = new List<MatchPlayerData>(); //temporary array
        private float matchmake_timer = 0f;

        private static ServerMatchmaker _instance;

        protected virtual void Awake()
        {
            _instance = this;
            Application.runInBackground = true;
        }

        protected virtual void Start()
        {
            TcgNetwork network = TcgNetwork.Get();
            network.onClientJoin += OnClientConnected;
            network.onClientQuit += OnClientDisconnected;

            Messaging.ListenMsg("matchmaking", ReceiveMatchmaking);
            Messaging.ListenMsg("matchmaking_list", ReceiveMatchmakingList);
            Messaging.ListenMsg("match_list", ReceiveMatchList);

            if (!network.IsActive())
            {
                network.StartServer(NetworkData.Get().port);
            }
        }

        protected virtual void Update()
        {
            //Matchmaking
            matchmake_timer += Time.deltaTime;
            if (matchmake_timer > 20f)
            {
                matchmake_timer = 0f;
                matchmaking_players.Clear(); //Delete and restart, to make sure you only keep recent players
            }
        }

        protected virtual void OnClientConnected(ulong client_id)
        {
            ClientData iclient = new ClientData(client_id);
            client_list[client_id] = iclient;
        }

        protected virtual void OnClientDisconnected(ulong client_id)
        {
            if (client_list.ContainsKey(client_id))
            {
                ClientData iclient = client_list[client_id];
                if (iclient.username != null)
                    matchmaking_players.Remove(iclient.user_id);
                client_list.Remove(client_id);
            }
        }

        protected virtual void ReceiveMatchmaking(ulong client_id, FastBufferReader reader)
        {
            ClientData iclient = GetClient(client_id);
            reader.ReadNetworkSerializable(out MsgMatchmaking msg);

            if (iclient == null || string.IsNullOrWhiteSpace(msg.user_id) || string.IsNullOrWhiteSpace(msg.username))
                return;

            string user_id = msg.user_id;
            bool is_refresh = msg.refresh;

            iclient.user_id = msg.user_id;
            iclient.username = msg.username;

            //Restart matching
            if (!is_refresh)
                RemoveUserFromMatches(user_id, msg.username);

            //Check if already matched
            MatchData match = GetUserMatch(user_id);
            if (match != null && !match.ended)
            {
                SendMatchmakingResponse(iclient, match, msg.group, match.players.Length); //Was already matched, return saved result!
                return;
            }

            //Data
            MatchPlayerData pdata = new MatchPlayerData();
            pdata.user_id = msg.user_id;
            pdata.username = msg.username;
            pdata.group = msg.group;
            pdata.elo_rank = msg.elo;
            pdata.nb_players = msg.players;

            //Add to matchking players
            if (!matchmaking_players.ContainsKey(user_id))
                matchmaking_players.Add(user_id, pdata);

            //Start searching for other valid players
            float wait_max = 20f;
            int variance_max = 2000;

            bool friendly = msg.group.StartsWith("u_");
            float wait_timer = msg.time;
            float wait_value = Mathf.Clamp01(wait_timer / wait_max);
            int elo_variance = Mathf.RoundToInt(wait_value * variance_max);

            valid_users.Clear();
            valid_users.Add(pdata); //Add self

            foreach (KeyValuePair<string, MatchPlayerData> opair in matchmaking_players)
            {
                string auser_id = opair.Key;
                MatchPlayerData adata = opair.Value;
                int diff = Mathf.Abs(adata.elo_rank - msg.elo);
                bool same_group = adata.group == msg.group;
                bool same_players = adata.nb_players == msg.players;
                bool valid_elo = friendly || diff < elo_variance;
                if (auser_id != user_id && valid_elo && same_group && same_players)
                {
                    valid_users.Add(adata);
                }
            }

            //Not enough players found, send current count
            if (valid_users.Count < msg.players)
            {
                SendMatchmakingResponse(iclient, null, msg.group, valid_users.Count);
                return; //Not enough valid users
            }

            //Match success, send result
            string prefix = msg.group.Length >= 2 ? msg.group.Substring(0, 2) : "";
            string game_code = prefix + GameTool.GenerateRandomID(12, 15);
            string game_url = ""; //Empty url means it will use the default NetworkData url set on the client
            if (servers.Length > 0)
                game_url = servers[Random.Range(0, servers.Length)];

            //Add Match
            MatchData nmatch = AddMatch(msg.group, game_code, game_url, msg.players, valid_users);

            //Send response to current request
            if (matched_players.ContainsKey(user_id))
            {
                SendMatchmakingResponse(iclient, nmatch, nmatch.group, nmatch.players.Length); //Just matched to new player!
            }
        }

        protected virtual MatchData AddMatch(string group, string uid, string url, int players, List<MatchPlayerData> valid_users)
        {
            int pindex = 0;
            MatchData nmatch = new MatchData(group, uid, url, players);
            foreach (MatchPlayerData vuser in valid_users)
            {
                if (pindex < nmatch.players.Length)
                {
                    matchmaking_players.Remove(vuser.user_id);
                    matched_players[vuser.user_id] = uid;
                    nmatch.players[pindex] = vuser.username;
                    pindex++;
                }
            }

            started_matches[uid] = nmatch;
            return nmatch;
        }

        protected virtual void RemoveUserFromMatches(string user_id, string username)
        {
            if (matched_players.ContainsKey(user_id))
            {
                string guid = matched_players[user_id];
                matched_players.Remove(user_id);

                if (started_matches.ContainsKey(guid))
                {
                    MatchData match = started_matches[guid];

                    List<string> players = new List<string>(match.players);
                    players.Remove(username);
                    match.players = players.ToArray();

                    if (match.players.Length == 0)
                    {
                        started_matches.Remove(guid);
                    }
                }
            }
        }

        protected virtual MatchData GetUserMatch(string user_id)
        {
            if (matched_players.ContainsKey(user_id))
            {
                string guid = matched_players[user_id];
                if (started_matches.ContainsKey(guid))
                {
                    MatchData match = started_matches[guid];
                    return match;
                }
            }
            return null;
        }

        protected virtual void SendMatchmakingResponse(ClientData iclient, MatchData match, string group, int players)
        {
            MatchmakingResult msg_match = new MatchmakingResult();
            msg_match.success = match != null;
            msg_match.players = players;
            msg_match.group = group;
            msg_match.game_uid = match != null ? match.game_uid : "";
            msg_match.server_url = match != null ? match.server_url : "";

            Messaging.SendObject("matchmaking", iclient.client_id, msg_match, NetworkDelivery.Reliable);
        }

        protected virtual void ReceiveMatchmakingList(ulong client_id, FastBufferReader reader)
        {
            reader.ReadNetworkSerializable(out MsgMatchmakingList msg);

            List<MatchmakingListItem> items = new List<MatchmakingListItem>();

            foreach (KeyValuePair<string, MatchPlayerData> pair in matchmaking_players)
            {
                if (string.IsNullOrEmpty(msg.username) || pair.Key == msg.username)
                {
                    MatchPlayerData pdata = pair.Value;
                    MatchmakingListItem item = new MatchmakingListItem();
                    item.group = pdata.group;
                    item.user_id = pdata.user_id;
                    item.username = pdata.username;
                    items.Add(item);
                }
            }

            MatchmakingList msg_list = new MatchmakingList();
            msg_list.items = items.ToArray();
            Messaging.SendObject("matchmaking_list", client_id, msg_list, NetworkDelivery.Reliable);
        }

        protected virtual void ReceiveMatchList(ulong client_id, FastBufferReader reader)
        {
            reader.ReadNetworkSerializable(out MsgMatchmakingList msg);

            List<MatchListItem> items = new List<MatchListItem>();

            foreach (KeyValuePair<string, MatchData> pair in started_matches)
            {
                if (!pair.Value.ended && pair.Value.players.Length >= 2)
                {
                    if (string.IsNullOrEmpty(msg.username) || Contains(pair.Value.players, msg.username))
                    {
                        MatchData pdata = pair.Value;
                        MatchListItem item = new MatchListItem();
                        item.group = pair.Value.group;
                        item.game_uid = pdata.game_uid;
                        item.game_url = pdata.server_url;
                        item.usernames = pair.Value.players;
                        items.Add(item);
                    }
                }
            }

            MatchList msg_list = new MatchList();
            msg_list.items = items.ToArray();

            Messaging.SendObject("match_list", client_id, msg_list, NetworkDelivery.Reliable);
        }

        private bool Contains(string[] users, string user)
        {
            foreach (string auser in users)
            {
                if (auser == user)
                    return true;
            }
            return false;
        }

        public void EndMatch(string uid)
        {
            foreach (KeyValuePair<string, MatchData> pair in started_matches)
            {
                if (pair.Value.game_uid == uid)
                    pair.Value.ended = true;
            }
        }

        public ClientData GetClient(ulong client_id)
        {
            if (client_list.ContainsKey(client_id))
                return client_list[client_id];
            return null;
        }

        public ClientData GetClientByUser(string username)
        {
            foreach (KeyValuePair<ulong, ClientData> pair in client_list)
            {
                if (pair.Value.username == username)
                    return pair.Value;
            }
            return null;
        }

        public ulong ServerID { get { return TcgNetwork.Get().ServerID; } }
        public NetworkMessaging Messaging { get { return TcgNetwork.Get().Messaging; } }

        public static ServerMatchmaker Get()
        {
            return _instance;
        }
    }

    public class MatchPlayerData
    {
        public string user_id;
        public string username;
        public string group;
        public int elo_rank;
        public int nb_players;
    }

    public class MatchData
    {
        public string group;
        public string game_uid;
        public string server_url;
        public bool ended = false;
        public string[] players;

        public MatchData(string grp, string uid, string url, int players) { group = grp; game_uid = uid; server_url = url; this.players = new string[players]; }
    }

}
