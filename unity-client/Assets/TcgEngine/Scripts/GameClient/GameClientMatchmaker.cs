using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Unity.Netcode;
using UnityEngine.Events;
using TcgEngine.UI;
using System.Threading.Tasks;

namespace TcgEngine.Client
{
    /// <summary>
    /// Main client script for the matchmaker
    /// Will send requests to server and receive a response when a matchmaking succeed or fail
    /// </summary>

    public class GameClientMatchmaker : MonoBehaviour
    {
        public UnityAction<MatchmakingResult> onMatchmaking;
        public UnityAction<MatchmakingList> onMatchmakingList;
        public UnityAction<MatchList> onMatchList;

        private bool matchmaking = false;
        private float timer = 0f;
        private float match_timer = 0f;
        private string matchmaking_group;
        private int matchmaking_players;
        private UnityAction<bool> connect_callback;

        private static GameClientMatchmaker _instance;

        void Awake()
        {
            _instance = this;
        }

        private void Start()
        {
            TcgNetwork.Get().onConnect += OnConnect;
            TcgNetwork.Get().onDisconnect += OnDisconnect;
            Messaging.ListenMsg("matchmaking", ReceiveMatchmaking);
            Messaging.ListenMsg("matchmaking_list", ReceiveMatchmakingList);
            Messaging.ListenMsg("match_list", ReceiveMatchList);
        }

        private void OnDestroy()
        {
            if (TcgNetwork.Get() != null)
            {
                TcgNetwork.Get().onConnect -= OnConnect;
                TcgNetwork.Get().onDisconnect -= OnDisconnect;
                TcgNetwork.Get().Disconnect();
                Messaging.UnListenMsg("matchmaking");
                Messaging.UnListenMsg("matchmaking_list");
                Messaging.UnListenMsg("match_list");
            }
        }

        void Update()
        {
            if (matchmaking)
            {
                timer += Time.deltaTime;
                match_timer += Time.deltaTime;

                //Send periodic request
                if (IsConnected() && timer > 2f)
                {
                    timer = 0f;
                    SendMatchRequest(true, matchmaking_group, matchmaking_players);
                }

                //Disconnected, stop
                if (!IsConnected() && !IsConnecting() && timer > 5f)
                {
                    StopMatchmaking();
                }
            }
        }

        public void StartMatchmaking(string group, int nb_players)
        {
            if (matchmaking)
                StopMatchmaking();

            Debug.Log("Start Matchmaking!");
            matchmaking_group = group;
            matchmaking_players = nb_players;
            matchmaking = true;
            match_timer = 0f;
            timer = 0f;

            Connect(NetworkData.Get().url, NetworkData.Get().port, (bool success) =>
            {
                if (success)
                {
                    SendMatchRequest(false, group, nb_players);
                }
                else
                {
                    StopMatchmaking();
                }
            });
        }

        public void StopMatchmaking()
        {
            if (matchmaking)
            {
                Debug.Log("Stop Matchmaking!");
                onMatchmaking?.Invoke(null);
                matchmaking_group = "";
                matchmaking_players = 0;
                matchmaking = false;
            }
        }

        public void RefreshMatchmakingList()
        {
            Connect(NetworkData.Get().url, NetworkData.Get().port, (bool success) =>
            {
                if(success)
                    SendMatchmakingListRequest();
            });
        }

        public void RefreshMatchList(string username_filter = "")
        {
            Connect(NetworkData.Get().url, NetworkData.Get().port, (bool success) =>
            {
                if (success)
                    SendMatchListRequest(username_filter);
            });
        }

        public async void Connect(string url, ushort port, UnityAction<bool> callback=null)
        {
            //Must be logged in to API to connect
            if(!Authenticator.Get().IsSignedIn())
            {
                callback?.Invoke(false);
                return;
            }

            if (IsConnecting())
            {
                await TcgNetwork.Get().WaitUntilConnected(5);
            }

            //Check if already connected
            if (IsConnected() || IsConnecting())
            {
                callback?.Invoke(IsConnected());
                return;
            }

            connect_callback = callback;
            TcgNetwork.Get().StartClient(url, port);
        }

        public void Disconnect()
        {
            TcgNetwork.Get()?.Disconnect();
        }

        private void OnConnect()
        {
            Debug.Log("Connected to server!");
            connect_callback?.Invoke(true);
            connect_callback = null;
        }

        private void OnDisconnect()
        {
            StopMatchmaking(); //Stop if currently running
            connect_callback?.Invoke(false);
            connect_callback = null;
            matchmaking = false;
        }

        private void SendMatchRequest(bool refresh, string group, int nb_players)
        {
            MsgMatchmaking msg_match = new MsgMatchmaking();
            UserData udata = Authenticator.Get().GetUserData();
            msg_match.user_id = Authenticator.Get().GetUserId();
            msg_match.username = Authenticator.Get().GetUsername();
            msg_match.group = group;
            msg_match.players = nb_players;
            msg_match.elo = udata.elo;
            msg_match.time = match_timer;
            msg_match.refresh = refresh;
            Messaging.SendObject("matchmaking", ServerID, msg_match, NetworkDelivery.Reliable);
        }

        private void SendMatchmakingListRequest()
        {
            MsgMatchmakingList msg_match = new MsgMatchmakingList();
            msg_match.username = ""; //Return all users
            Messaging.SendObject("matchmaking_list", ServerID, msg_match, NetworkDelivery.Reliable);
        }

        private void SendMatchListRequest(string username)
        {
            MsgMatchmakingList msg_match = new MsgMatchmakingList();
            msg_match.username = username;
            Messaging.SendObject("match_list", ServerID, msg_match, NetworkDelivery.Reliable);
        }

        private void ReceiveMatchmaking(ulong client_id, FastBufferReader reader)
        {
            reader.ReadNetworkSerializable(out MatchmakingResult msg);

            if (IsConnected() && matchmaking && matchmaking_group == msg.group)
            {
                matchmaking = !msg.success; //Stop matchmaking if success
                onMatchmaking?.Invoke(msg);
            }
        }

        private void ReceiveMatchmakingList(ulong client_id, FastBufferReader reader)
        {
            reader.ReadNetworkSerializable(out MatchmakingList list);
            onMatchmakingList?.Invoke(list);
        }

        private void ReceiveMatchList(ulong client_id, FastBufferReader reader)
        {
            reader.ReadNetworkSerializable(out MatchList list);
            onMatchList?.Invoke(list);
        }

        public bool IsMatchmaking()
        {
            return matchmaking;
        }

        public string GetGroup()
        {
            return matchmaking_group;
        }

        public int GetNbPlayers()
        {
            return matchmaking_players;
        }

        public float GetTimer()
        {
            return match_timer;
        }

        public bool IsConnected()
        {
            return TcgNetwork.Get().IsConnected();
        }

        public bool IsConnecting()
        {
            return TcgNetwork.Get().IsConnecting();
        }

        public ulong ServerID { get { return TcgNetwork.Get().ServerID; } }
        public NetworkMessaging Messaging { get { return TcgNetwork.Get().Messaging; } }

        public static GameClientMatchmaker Get()
        {
            return _instance;
        }
    }

}