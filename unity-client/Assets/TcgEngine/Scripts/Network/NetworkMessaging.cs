using System.Collections;
using System.Collections.Generic;
using Unity.Collections;
using Unity.Netcode;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Base class for sending and receiving network messages
    /// </summary>

    public class NetworkMessaging
    {
        private TcgNetwork network;

        private Dictionary<string, System.Action<ulong, FastBufferReader>> msg_dict = new Dictionary<string, System.Action<ulong, FastBufferReader>>();

        public NetworkMessaging(TcgNetwork network)
        {
            this.network = network;
            network.onConnect += OnConnect;
        }

        private void OnConnect()
        {
            foreach (KeyValuePair<string, System.Action<ulong, FastBufferReader>> pair in msg_dict)
            {
                RegisterNetMsg(pair.Key, pair.Value);
            }
        }

        public void ListenMsg(string type, System.Action<ulong, FastBufferReader> callback)
        {
            msg_dict[type] = callback;
            RegisterNetMsg(type, callback);
        }

        public void UnListenMsg(string type)
        {
            msg_dict.Remove(type);

            if (network.NetworkManager.CustomMessagingManager != null)
                network.NetworkManager.CustomMessagingManager.UnregisterNamedMessageHandler(type);
        }

        private void RegisterNetMsg(string type, System.Action<ulong, FastBufferReader> callback)
        {
            if (IsOnline)
            {
                network.NetworkManager.CustomMessagingManager.RegisterNamedMessageHandler(type, (ulong client_id, FastBufferReader reader) =>
                {
                    ReceiveNetMessage(type, client_id, reader);
                });
            }
        }

        private void ReceiveNetMessage(string type, ulong client_id, FastBufferReader reader)
        {
            bool valid = msg_dict.TryGetValue(type, out System.Action<ulong, FastBufferReader> callback);
            if (valid && IsOnline)
            {
                callback(client_id, reader);
            }
        }

        //--------- Send Single ----------

        public void SendEmpty(string type, ulong target, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(0, Allocator.Temp);
            Send(type, target, writer, delivery);
            writer.Dispose();
        }

        public void SendBytes(string type, ulong target, byte[] msg, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(msg.Length, Allocator.Temp);
            writer.WriteBytesSafe(msg, msg.Length);
            Send(type, target, writer, delivery);
            writer.Dispose();
        }

        public void SendString(string type, ulong target, string msg, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(msg.Length, Allocator.Temp, TcgNetwork.MsgSizeMax);
            writer.WriteValueSafe(msg);
            Send(type, target, writer, delivery);
            writer.Dispose();
        }

        public void SendInt(string type, ulong target, int data, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(4, Allocator.Temp);
            writer.WriteValueSafe(data);
            Send(type, target, writer, delivery);
            writer.Dispose();
        }

        public void SendUInt64(string type, ulong target, ulong data, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(8, Allocator.Temp);
            writer.WriteValueSafe(data);
            Send(type, target, writer, delivery);
            writer.Dispose();
        }

        public void SendFloat(string type, ulong target, float data, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(4, Allocator.Temp);
            writer.WriteValueSafe(data);
            Send(type, target, writer, delivery);
            writer.Dispose();
        }
        
        public void SendObject<T>(string type, ulong target, T data, NetworkDelivery delivery) where T : INetworkSerializable
        {
            FastBufferWriter writer = new FastBufferWriter(256, Allocator.Temp, TcgNetwork.MsgSizeMax);
            writer.WriteNetworkSerializable(data);
            Send(type, target, writer, delivery);
            writer.Dispose();
        }

        //--------- Send Multi ----------

        public void SendEmpty(string type, IReadOnlyList<ulong> targets, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(0, Allocator.Temp);
                Send(type, targets, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendBytes(string type, IReadOnlyList<ulong> targets, byte[] msg, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(msg.Length, Allocator.Temp);
                writer.WriteBytesSafe(msg, msg.Length);
                Send(type, targets, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendString(string type, IReadOnlyList<ulong> targets, string msg, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(msg.Length, Allocator.Temp, TcgNetwork.MsgSizeMax);
                writer.WriteValueSafe(msg);
                Send(type, targets, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendInt(string type, IReadOnlyList<ulong> targets, int data, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(4, Allocator.Temp);
                writer.WriteValueSafe(data);
                Send(type, targets, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendUInt64(string type, IReadOnlyList<ulong> targets, ulong data, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(8, Allocator.Temp);
                writer.WriteValueSafe(data);
                Send(type, targets, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendFloat(string type, IReadOnlyList<ulong> targets, float data, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(4, Allocator.Temp);
                writer.WriteValueSafe(data);
                Send(type, targets, writer, delivery);
                writer.Dispose();
            }
        }
        
        public void SendObject<T>(string type, IReadOnlyList<ulong> targets, T data, NetworkDelivery delivery) where T : INetworkSerializable
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(256, Allocator.Temp, TcgNetwork.MsgSizeMax);
                writer.WriteNetworkSerializable(data);
                Send(type, targets, writer, delivery);
                writer.Dispose();
            }
        }

        //--------- Send All ----------

        public void SendEmptyAll(string type, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(0, Allocator.Temp);
                SendAll(type, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendStringAll(string type, string msg, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(msg.Length, Allocator.Temp, TcgNetwork.MsgSizeMax);
                writer.WriteValueSafe(msg);
                SendAll(type, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendIntAll(string type, int data, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(4, Allocator.Temp);
                writer.WriteValueSafe(data);
                SendAll(type, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendUInt64All(string type, ulong data, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(8, Allocator.Temp);
                writer.WriteValueSafe(data);
                SendAll(type, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendFloatAll(string type, float data, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(4, Allocator.Temp);
                writer.WriteValueSafe(data);
                SendAll(type, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendBytesAll(string type, byte[] msg, NetworkDelivery delivery)
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(msg.Length, Allocator.Temp);
                writer.WriteBytesSafe(msg, msg.Length);
                SendAll(type, writer, delivery);
                writer.Dispose();
            }
        }

        public void SendObjectAll<T>(string type, T data, NetworkDelivery delivery) where T : INetworkSerializable
        {
            if (IsServer)
            {
                FastBufferWriter writer = new FastBufferWriter(256, Allocator.Temp, TcgNetwork.MsgSizeMax);
                writer.WriteNetworkSerializable(data);
                SendAll(type, writer, delivery);
                writer.Dispose();
            }
        }

        //-------- Generic Send ----------

        public void Send(string type, ulong target, FastBufferWriter writer, NetworkDelivery delivery)
        {
            if (IsOnline)
                SendOnline(type, target, writer, delivery);
            else if(target == ClientID)
                SendOffline(type, writer);
        }

        public void Send(string type, IReadOnlyList<ulong> targets, FastBufferWriter writer, NetworkDelivery delivery)
        {
            if (IsOnline)
                SendOnline(type, targets, writer, delivery);
            else if (Contains(targets, ClientID))
                SendOffline(type, writer);
        }

        public void SendAll(string type, FastBufferWriter writer, NetworkDelivery delivery)
        {
            Send(type, ClientList, writer, delivery);
        }

        private void SendOnline(string type, ulong target, FastBufferWriter writer, NetworkDelivery delivery)
        {
            network.NetworkManager.CustomMessagingManager.SendNamedMessage(type, target, writer, delivery);
        }

        private void SendOnline(string type, IReadOnlyList<ulong> targets, FastBufferWriter writer, NetworkDelivery delivery)
        {
            network.NetworkManager.CustomMessagingManager.SendNamedMessage(type, targets, writer, delivery);
        }

        //Just copy the message from writer to reader locally and call the callback immediately
        private void SendOffline(string type, FastBufferWriter writer)
        {
            bool found = msg_dict.TryGetValue(type, out System.Action<ulong, FastBufferReader> callback);
            if (found)
            {
                FastBufferReader reader = new FastBufferReader(writer, Allocator.Temp);
                callback?.Invoke(ClientID, reader);
                reader.Dispose();
            }
        }

        //--------- Forward msgs ----------
		
		//Forward a client message to one client
        //Make sure you finished reading the reader before forwarding
        public void Forward(string type, ulong target, FastBufferReader reader, NetworkDelivery delivery)
        {
            if (IsServer && IsOnline)
            {
                reader.Seek(0); //Reset reader
                reader.ReadValueSafe(out ulong header); //Ignore header
                byte[] bytes = new byte[reader.Length - reader.Position];
                reader.ReadBytesSafe(ref bytes, reader.Length - reader.Position);
                FastBufferWriter writer = new FastBufferWriter(bytes.Length, Allocator.Temp);
                writer.WriteBytesSafe(bytes, bytes.Length);
                network.NetworkManager.CustomMessagingManager.SendNamedMessage(type, target, writer, delivery);
                writer.Dispose();
            }
        }

        //Forward a client message to all target clients
        //Make sure you finished reading the reader before forwarding
        public void Forward(string type, IReadOnlyList<ulong> targets, FastBufferReader reader, NetworkDelivery delivery)
        {
            if (IsServer && IsOnline)
            {
                reader.Seek(0); //Reset reader
                reader.ReadValueSafe(out ulong header); //Ignore header
                byte[] bytes = new byte[reader.Length - reader.Position];
                reader.ReadBytesSafe(ref bytes, reader.Length - reader.Position);
                FastBufferWriter writer = new FastBufferWriter(bytes.Length, Allocator.Temp);
                writer.WriteBytesSafe(bytes, bytes.Length);
                network.NetworkManager.CustomMessagingManager.SendNamedMessage(type, targets, writer, delivery);
                writer.Dispose();
            }
        }

        //Forward a client message to all other clients (other than the source)
        //Make sure you finished reading the reader before forwarding
        public void ForwardAll(string type, ulong source_client, FastBufferReader reader, NetworkDelivery delivery)
        {
            if (IsServer && IsOnline)
            {
                reader.Seek(0); //Reset reader
                reader.ReadValueSafe(out ulong header); //Ignore header
                byte[] bytes = new byte[reader.Length - reader.Position];
                reader.ReadBytesSafe(ref bytes, reader.Length - reader.Position);
                FastBufferWriter writer = new FastBufferWriter(bytes.Length, Allocator.Temp);
                writer.WriteBytesSafe(bytes, bytes.Length);

                foreach (ulong client in ClientList)
                {
                    if(client != source_client && client != ClientID)
                        network.NetworkManager.CustomMessagingManager.SendNamedMessage(type, client, writer, delivery);
                }
                writer.Dispose();
            }
        }

        private bool Contains(IReadOnlyList<ulong> list, ulong client_id)
        {
            foreach (ulong cid in list)
            {
                if (cid == client_id)
                    return true;
            }
            return false;
        }

        public IReadOnlyList<ulong> ClientList { get { return network.GetClientsIds(); } }
        public bool IsOnline { get { return network.IsOnline; } }
        public bool IsServer { get { return network.IsServer; } }
        public ulong ServerID { get { return network.ServerID; } }
        public ulong ClientID { get { return network.ClientID; } }


        public static NetworkMessaging Get()
        {
            return TcgNetwork.Get().Messaging;
        }
    }
}
