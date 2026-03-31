using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System;
using UnityEngine.Events;
using Unity.Netcode;

namespace TcgEngine.Server
{
    /// <summary>
    /// Top-level server script, that manages new connection, and assign players to the right match
    /// Will also receive game actions and send them to the appropirate game
    /// Can contain multiple games at once (GameServer)
    /// </summary>

    public class ServerManager : MonoBehaviour
    {
        [Header("API")]
        public string api_username;
        public string api_password;

        private Dictionary<ulong, ClientData> client_list = new Dictionary<ulong, ClientData>();  //List of clients
        private Dictionary<string, GameServer> game_list = new Dictionary<string, GameServer>(); //List of games
        private List<string> game_remove_list = new List<string>();

        private float login_timer = 0f;

        protected virtual void Awake()
        {
            Application.runInBackground = true;
            Application.targetFrameRate = 200; //Limit server frame rate to prevent using 100% cpu
        }

        protected virtual void Start()
        {
            TcgNetwork network = TcgNetwork.Get();
            network.onClientJoin += OnClientConnected;
            network.onClientQuit += OnClientDisconnected;
            Messaging.ListenMsg("connect", ReceiveConnectPlayer);
            Messaging.ListenMsg("action", ReceiveGameAction);

            if (!network.IsActive())
            {
                network.StartServer(NetworkData.Get().port);
            }

            Login();
        }

        protected virtual void Update()
        {
            //Update games and Destroy games with no players
            foreach (KeyValuePair<string, GameServer> pair in game_list)
            {
                GameServer gserver = pair.Value;
                gserver.Update();

                if (gserver.IsGameExpired())
                    game_remove_list.Add(pair.Key);
            }

            foreach (string key in game_remove_list)
            {
                game_list.Remove(key);

                if (ServerMatchmaker.Get())
                    ServerMatchmaker.Get().EndMatch(key);
            }
            game_remove_list.Clear();

            //Re login
            login_timer += Time.deltaTime;
            if (login_timer > 5f && !Authenticator.Get().IsConnected())
            {
                login_timer = 0f;
                Login();
            }
        }

        protected virtual async void Login()
        {
            await Authenticator.Get().Login(api_username, api_password);

            bool success = Authenticator.Get().IsConnected();
            int permission = Authenticator.Get().GetPermission();
            string api = Authenticator.Get().IsApi() ? "API" : "Local";

            Debug.Log(api + " authentication: " + success + " (" + permission + ")");
        }
        
        protected virtual void OnClientConnected(ulong client_id)
        {
            ClientData iclient = new ClientData(client_id);
            client_list[client_id] = iclient;
        }

        protected virtual void OnClientDisconnected(ulong client_id)
        {
            ClientData iclient = GetClient(client_id);
            client_list.Remove(client_id);
            ReceiveDisconnectPlayer(iclient);
        }

        protected virtual void ReceiveConnectPlayer(ulong client_id, FastBufferReader reader)
        {
            ClientData iclient = GetClient(client_id);
            reader.ReadNetworkSerializable(out MsgPlayerConnect msg);

            if (iclient != null && msg != null)
            {
                if (string.IsNullOrWhiteSpace(msg.username))
                    return;

                if (string.IsNullOrWhiteSpace(msg.game_uid))
                    return;

                Debug.Log("Client " + client_id + " connecting to game: " + msg.game_uid);

                //Connect to game as player or observer
                if (msg.observer)
                    ConnectObserverToGame(iclient, msg.user_id, msg.username, msg.game_uid);
                else
                    ConnectPlayerToGame(iclient, msg.user_id, msg.username, msg.game_uid, msg.nb_players);

                GameServer gserver = GetGame(msg.game_uid);
                if(gserver != null)
                    gserver.RefreshAll();
            }
        }

        protected virtual void ReceiveDisconnectPlayer(ClientData iclient)
        {
            if (iclient == null)
                return;

            GameServer gserver = GetGame(iclient.game_uid);
            if (gserver != null)
            {
                gserver.RemoveClient(iclient);
            }
        }

        protected virtual void ReceiveGameAction(ulong client_id, FastBufferReader reader)
        {
            ClientData client = GetClient(client_id);
            if (client != null)
            {
                GameServer gserver = GetGame(client.game_uid);
                if (gserver != null && gserver.IsConnectedPlayer(client.user_id))
                    gserver.ReceiveAction(client_id, reader);
            }
        }

        //Player wants to connect to game_uid
        protected virtual void ConnectPlayerToGame(ClientData client, string user_id, string username, string game_uid, int nb_players)
        {
            //Create game
            GameServer gserver = GetGame(game_uid);

            if (gserver == null)
                gserver = CreateGame(game_uid, nb_players);

            bool can_connect = gserver.IsPlayer(user_id) || gserver.CountPlayers() < gserver.nb_players;
            if (gserver != null && can_connect)
            {
                //Add player to game
                client.game_uid = game_uid;
                client.user_id = user_id;
                client.username = username;
                gserver.AddClient(client);

                int player_id = gserver.AddPlayer(client);

                //Send back result
                MsgAfterConnected msg_data = new MsgAfterConnected();
                msg_data.success = true;
                msg_data.player_id = player_id;
                msg_data.game_data = gserver.GetGameData();
                SendToClient(client.client_id, GameAction.Connected, msg_data, NetworkDelivery.ReliableFragmentedSequenced);
            }
        }

        //Player wants to connect to game_uid as observer
        protected virtual void ConnectObserverToGame(ClientData client, string user_id, string username, string game_uid)
        {
            GameServer gserver = GetGame(game_uid);
            if (gserver != null && client != null)
            {
                //Set client data
                client.game_uid = game_uid;
                client.user_id = user_id;
                client.username = username;
                gserver.AddClient(client);

                //Return request
                MsgAfterConnected msg_data = new MsgAfterConnected();
                msg_data.success = true;
                msg_data.player_id = -1;
                msg_data.game_data = gserver.GetGameData();
                SendToClient(client.client_id, GameAction.Connected, msg_data, NetworkDelivery.ReliableFragmentedSequenced);
            }
        }
        
        public void SendToClient(ulong client_id, ushort tag, INetworkSerializable data, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(128, Unity.Collections.Allocator.Temp, TcgNetwork.MsgSizeMax);
            writer.WriteValueSafe(tag);
            writer.WriteNetworkSerializable(data);
            Messaging.Send("refresh", client_id, writer, delivery);
            writer.Dispose();
        }

        public void SendMsgToClient(ushort client_id, string msg)
        {
            FastBufferWriter writer = new FastBufferWriter(128, Unity.Collections.Allocator.Temp, TcgNetwork.MsgSizeMax);
            writer.WriteValueSafe(GameAction.ServerMessage);
            writer.WriteValueSafe(msg);
            Messaging.Send("refresh", client_id, writer, NetworkDelivery.Reliable);
            writer.Dispose();
        }

        public GameServer CreateGame(string uid, int nb_players)
        {
            GameServer game = new GameServer(uid, nb_players, true);
            game_list[game.game_uid] = game;
            return game;
        }

        public void RemoveGame(string game_id)
        {
            game_list.Remove(game_id);
        }

        public GameServer GetGame(string game_uid)
        {
            if (string.IsNullOrEmpty(game_uid))
                return null;
            if (game_list.ContainsKey(game_uid))
                return game_list[game_uid];
            return null;
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
    }

    public class ClientData
    {
        public ulong client_id; //index of the connection
        public string user_id; //Player user_id, in auth system
        public string username; //Player username
        public string game_uid; //Unique id for the game

        public ClientData(ulong id) { client_id = id; }
    }

    public class CommandEvent
    {
        public ushort tag;
        public UnityAction<ClientData, SerializedData> callback;
    }
}