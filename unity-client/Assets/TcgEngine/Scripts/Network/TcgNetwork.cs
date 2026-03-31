using System.Collections;
using System.Collections.Generic;
using System.Threading.Tasks;
using Unity.Collections;
using Unity.Netcode;
using UnityEngine;
using UnityEngine.Events;

namespace TcgEngine
{
    /// <summary>
    /// Main script handling network connection betweeen server and client
    /// It's one of the few scripts in this asset that needs to be on a DontDestroyOnLoad object
    /// </summary>

    [DefaultExecutionOrder(-10)]
    [RequireComponent(typeof(NetworkManager))]
    [RequireComponent(typeof(TcgTransport))]
    public class TcgNetwork : MonoBehaviour
    {
        public NetworkData data;

        //Server & Client events
        public UnityAction onTick; //Every network tick
        public UnityAction onConnect;  //Event when self connect, happens before onReady, before sending any data
        public UnityAction onDisconnect; //Event when self disconnect

        //Server only events
        public UnityAction<ulong> onClientJoin; //Server event when any client connect
        public UnityAction<ulong> onClientQuit; //Server event when any client disconnect
        public UnityAction<ulong> onClientReady; //Server event when any client become ready

        public delegate bool ApprovalEvent(ulong client_id, ConnectionData connect_data);
        public ApprovalEvent checkApproval; //Additional approval validations for when a client connects

        //---------

        private NetworkManager network;
        private TcgTransport transport;
        private NetworkMessaging messaging;
        private Authenticator auth;
        private ConnectionData connection;

        [System.NonSerialized]
        private static bool inited = false;
        private static TcgNetwork instance;

        private const int msg_size = 1024 * 1024;
        private bool offline_mode = false;
        private bool connected = false;

        void Awake()
        {
            if (instance != null && instance != this)
            {
                Destroy(gameObject);
                return; //Manager already exists, destroy this one
            }

            Init();
            DontDestroyOnLoad(gameObject);
        }

        public void Init()
        {
            if (!inited || transport == null)
            {
                instance = this;
                inited = true;
                network = GetComponent<NetworkManager>();
                transport = GetComponent<TcgTransport>();
                messaging = new NetworkMessaging(this);
                connection = new ConnectionData();
                transport.Init();

                network.ConnectionApprovalCallback += ApprovalCheck;
                network.OnClientConnectedCallback += OnClientConnect;
                network.OnClientDisconnectCallback += OnClientDisconnect;

                InitAuth();
            }
        }

        void Update()
        {

        }

        //Start a host (client + server)
        public void StartHost(ushort port)
        {
            Debug.Log("Host Server Port " + port);
            transport.SetServer(port);
            connection.user_id = auth.UserID;
            connection.username = auth.Username;
            network.NetworkConfig.ConnectionData = NetworkTool.NetSerialize(connection);
            offline_mode = false;
            network.StartHost();
            AfterConnected();
        }

        //Start a dedicated server
        public void StartServer(ushort port)
        {
            Debug.Log("Start Server Port " + port);
            transport.SetServer(port);
            connection.user_id = "";
            connection.username = "";
            network.NetworkConfig.ConnectionData = NetworkTool.NetSerialize(connection);
            offline_mode = false;
            network.StartServer();
            AfterConnected();
            Debug.Log("Server listening on port: " + transport.GetPort()); //Some settings can override port set by script, make sure its correct one
        }

        //If is_host is set to true, it means this player created the game on a dedicated server
        //so its still a client (not server) but is the one who selected game settings
        public void StartClient(string server_url, ushort port)
        {
            Debug.Log("Join Server: " + server_url + " " + port);
            transport.SetClient(server_url, port);
            connection.user_id = auth.UserID;
            connection.username = auth.Username;
            network.NetworkConfig.ConnectionData = NetworkTool.NetSerialize(connection);
            offline_mode = false;
            network.StartClient();
        }

        //Start simulated host with all networking turned off
        public void StartHostOffline()
        {
            Debug.Log("Host Offline");
            Disconnect();
            offline_mode = true;
            AfterConnected();
        }

        public void Disconnect()
        {
            if (!IsClient && !IsServer)
                return;

            Debug.Log("Disconnect");
            network.Shutdown();
            AfterDisconnected();
        }

        public async Task WaitUntilConnected(int seconds_max = 10)
        {
            int count = 0;
            while (!IsConnected() && IsConnecting() && count < (seconds_max * 5))
            {
                await TimeTool.Delay(200);
                count++;
            }
        }

        public async Task WaitUntilDisconnected(int seconds_max = 10)
        {
            int count = 0;
            while (IsConnected() && count < (seconds_max * 5))
            {
                await TimeTool.Delay(200);
                count++;
            }
        }

        public void SetConnectionExtraData(byte[] bytes)
        {
            connection.extra = bytes;
        }

        public void SetConnectionExtraData(string data)
        {
            connection.extra = NetworkTool.SerializeString(data);
        }

        public void SetConnectionExtraData<T>(T data) where T : INetworkSerializable, new()
        {
            connection.extra = NetworkTool.NetSerialize(data);
        }

        private async void InitAuth()
        {
            auth = Authenticator.Create(data.auth_type);
            await auth.Initialize();
        }

        private void AfterConnected()
        {
            if (connected)
                return;

            if (network.NetworkTickSystem != null)
                network.NetworkTickSystem.Tick += OnTick;
            connected = true;
            onConnect?.Invoke();
        }

        private void AfterDisconnected()
        {
            if (!connected)
                return;

            if (network.NetworkTickSystem != null)
                network.NetworkTickSystem.Tick -= OnTick;
            offline_mode = false;
            connected = false;
            onDisconnect?.Invoke();
        }

        private void OnClientConnect(ulong client_id)
        {
            if (IsServer && client_id != ServerID)
            {
                Debug.Log("Client Connected: " + client_id);
                onClientJoin?.Invoke(client_id);
            }

            if (!IsServer)
                AfterConnected(); //AfterConnected wasn't called yet for client
        }

        private void OnClientDisconnect(ulong client_id)
        {
            if (IsServer && client_id != ServerID)
            {
                Debug.Log("Client Disconnected: " + client_id);
                onClientQuit?.Invoke(client_id);
            }

            if (ClientID == client_id || client_id == ServerID)
                AfterDisconnected();
        }

        private void OnTick()
        {
            onTick?.Invoke();
        }

        private void ApprovalCheck(NetworkManager.ConnectionApprovalRequest req, NetworkManager.ConnectionApprovalResponse res)
        {
            ConnectionData connect = NetworkTool.NetDeserialize<ConnectionData>(req.Payload);
            bool approved = ApproveClient(req.ClientNetworkId, connect);
            res.Approved = approved;
        }

        private bool ApproveClient(ulong client_id, ConnectionData connect)
        {
            if (client_id == ServerID)
                return true; //Server always approve itself

            if (offline_mode)
                return false;

            if (connect == null)
                return false; //Invalid data

            if (string.IsNullOrEmpty(connect.username) || string.IsNullOrEmpty(connect.user_id))
                return false; //Invalid username

            if (checkApproval != null && !checkApproval.Invoke(client_id, connect))
                return false; //Custom approval condition

            return true; //New Client approved
        }

        public IReadOnlyList<ulong> GetClientsIds()
        {
            return network.ConnectedClientsIds;
        }

        public int CountClients()
        {
            if (offline_mode)
                return 1;
            if (IsServer && IsConnected())
                return network.ConnectedClientsIds.Count;
            return 0;
        }

        public bool IsConnecting()
        {
            return IsActive() && !IsConnected(); //Trying to connect but not yet
        }

        public bool IsConnected()
        {
            return offline_mode || network.IsServer || network.IsConnectedClient;
        }

        public bool IsActive()
        {
            return offline_mode || network.IsServer || network.IsClient;
        }

        public string Address
        {
            get { return transport.GetAddress(); }
        }

        public ushort Port
        {
            get { return transport.GetPort(); }
        }

        public ulong ClientID { get { return offline_mode ? ServerID : network.LocalClientId; } } //ID of this client (if host, will be same than ServerID), changes for every reconnection, assigned by Netcode
        public ulong ServerID { get { return NetworkManager.ServerClientId; } } //ID of the server

        public bool IsServer { get { return offline_mode || network.IsServer; } }
        public bool IsClient { get { return offline_mode || network.IsClient; } }
        public bool IsHost { get { return IsClient && IsServer; } }     //Host is both a client and server
        public bool IsOnline { get { return !offline_mode && IsActive(); } }

        public NetworkTime LocalTime { get { return network.LocalTime; } }
        public NetworkTime ServerTime { get { return network.ServerTime; } }
        public float DeltaTick { get { return 1f / network.NetworkTickSystem.TickRate; } }

        public NetworkManager NetworkManager { get { return network; } }
        public TcgTransport Transport { get { return transport; } }
        public NetworkMessaging Messaging { get { return messaging; } }
        public Authenticator Auth { get { return auth; } }

        public static int MsgSizeMax { get { return msg_size; } }
        public static int MsgSize => MsgSizeMax; //Old name

        public static TcgNetwork Get()
        {
            if (instance == null)
            {
                TcgNetwork net = FindObjectOfType<TcgNetwork>();
                net?.Init();
            }
            return instance;
        }
    }

    [System.Serializable]
    public class ConnectionData : INetworkSerializable
    {
        public string user_id = "";
        public string username = "";

        public byte[] extra = new byte[0];

        //If you add extra data, make sure the total size of ConnectionData doesn't exceed Netcode max unfragmented msg (1400 bytes)
        //Fragmented msg are not possible for connection data, since connection is done in a single request

        public string GetExtraString()
        {
            return NetworkTool.DeserializeString(extra);
        }

        public T GetExtraData<T>() where T : INetworkSerializable, new()
        {
            return NetworkTool.NetDeserialize<T>(extra);
        }

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref user_id);
            serializer.SerializeValue(ref username);
            serializer.SerializeValue(ref extra);
        }
    }

    public class SerializedData
    {
        private FastBufferReader reader;
        private INetworkSerializable data;
        private byte[] bytes;

        public SerializedData(FastBufferReader r) { reader = r; data = null; }
        public SerializedData(INetworkSerializable d) { data = d; }

        public string GetString()
        {
            reader.ReadValueSafe(out string msg);
            return msg;
        }

        public T Get<T>() where T : INetworkSerializable, new()
        {
            if (data != null)
            {
                return (T)data;
            }
            else if (bytes != null)
            {
                data = NetworkTool.NetDeserialize<T>(bytes);
                return (T)data;
            }
            else
            {
                reader.ReadNetworkSerializable(out T val);
                data = val;
                return val;
            }
        }

        //PreRead in advance without knowing the object type, since FastBufferReader will get disposed by netcode
        public void PreRead()
        {
            int size = reader.Length - reader.Position;
            bytes = new byte[size];
            reader.ReadBytesSafe(ref bytes, size);
        }
    }
}
