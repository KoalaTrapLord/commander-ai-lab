using System.Collections;
using System.Collections.Generic;
using Unity.Netcode;
using UnityEngine;
using TcgEngine.Client;

namespace TcgEngine.Server
{
    /// <summary>
    /// Local server running on the client to play in solo mode against AI
    /// Contains only one GameServer
    /// </summary>

    public class ServerManagerLocal : MonoBehaviour
    {

        private GameServer server;

        private Dictionary<ulong, ClientData> client_list = new Dictionary<ulong, ClientData>();  //List of clients

        protected virtual void Start()
        {
            if (GameClient.game_settings.IsHost())
            {
                StartServer(); //Start local server if not playing online
            }
        }

        protected virtual void StartServer()
        {
            TcgNetwork network = TcgNetwork.Get();
            network.onClientJoin += OnClientJoin;
            network.onClientQuit += OnClientQuit;
            network.Messaging.ListenMsg("connect", ReceiveConnectPlayer);
            network.Messaging.ListenMsg("action", ReceiveGameAction);

            client_list[network.ServerID] = new ClientData(network.ServerID); //Add yourself
            server = new GameServer(GameClient.game_settings.game_uid, GameClient.game_settings.nb_players, false);
        }

        protected virtual void OnDestroy()
        {
            TcgNetwork network = TcgNetwork.Get();
            if (network != null)
            {
                network.onClientJoin -= OnClientJoin;
                network.onClientQuit -= OnClientQuit;
                network.Messaging.UnListenMsg("connect");
                network.Messaging.UnListenMsg("action");
            }
        }

        protected virtual void OnClientJoin(ulong client_id)
        {
            client_list[client_id] = new ClientData(client_id);
        }

        protected virtual void OnClientQuit(ulong client_id)
        {
            ClientData client = GetClient(client_id);
            server?.RemoveClient(client);
            client_list.Remove(client_id);
        }

        protected virtual void Update()
        {
            if (server != null)
                server.Update();
        }

        protected virtual void ReceiveConnectPlayer(ulong client_id, FastBufferReader reader)
        {
            reader.ReadNetworkSerializable(out MsgPlayerConnect msg);

            if (msg != null)
            {
                if (string.IsNullOrWhiteSpace(msg.username))
                    return;

                if (string.IsNullOrWhiteSpace(msg.game_uid))
                    return;

                ClientData client = GetClient(client_id);
                if (client == null)
                    return;

                bool can_connect = server.IsPlayer(msg.user_id) || server.CountPlayers() < server.nb_players;
                if (can_connect)
                {
                    client.game_uid = msg.game_uid;
                    client.user_id = msg.user_id;
                    client.username = msg.username;
                    server.AddClient(client);

                    int player_id = server.AddPlayer(client);

                    //Send back result
                    MsgAfterConnected msg_data = new MsgAfterConnected();
                    msg_data.success = true;
                    msg_data.player_id = player_id;
                    msg_data.game_data = server.GetGameData();
                    SendToClient(client_id, GameAction.Connected, msg_data, NetworkDelivery.ReliableFragmentedSequenced);
                }
            }
        }

        protected virtual void ReceiveGameAction(ulong client_id, FastBufferReader reader)
        {
            ClientData client = GetClient(client_id);
            if (client != null)
            {
                if (server.IsConnectedPlayer(client.user_id))
                    server.ReceiveAction(client_id, reader);
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

        public ClientData GetClient(ulong client_id)
        {
            if (client_list.ContainsKey(client_id))
                return client_list[client_id];
            return null;
        }

        public ulong ServerID { get { return TcgNetwork.Get().ServerID; } }
        public NetworkMessaging Messaging { get { return TcgNetwork.Get().Messaging; } }
    }
}
