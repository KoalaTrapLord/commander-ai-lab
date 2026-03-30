using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace CommanderAILab.Services
{
    /// <summary>
    /// Lightweight WebSocket client for the Commander AI Lab tabletop.
    /// Uses Unity's built-in UnityWebRequest for the HTTP upgrade handshake,
    /// then falls back to a polling REST pattern until a true WS package
    /// (NativeWebSocket or WebSocketSharp) is imported via the Asset Store.
    ///
    /// Phase 0 usage: validates connectivity to the FastAPI backend via
    /// a HTTP ping to /api/health before the full WS protocol is wired.
    ///
    /// To upgrade to full WebSocket:
    ///   1. Import NativeWebSocket from https://github.com/endel/NativeWebSocket
    ///      (add to manifest.json as a git URL dependency)
    ///   2. Replace the polling coroutine below with NativeWebSocket.WebSocket
    ///   3. Wire OnMessage to GameSessionService.HandleServerMessage()
    /// </summary>
    public class WebSocketClient : MonoBehaviour
    {
        public static WebSocketClient Instance { get; private set; }

        [Header("Connection")]
        [SerializeField] private string baseUrl = "http://localhost:8080";
        [SerializeField] private float reconnectDelay = 3f;
        [SerializeField] private float pollInterval = 0.5f;

        // Connection state
        public bool IsConnected { get; private set; } = false;
        public string SessionId { get; private set; }

        // Events
        public event Action OnConnected;
        public event Action OnDisconnected;
        public event Action<string> OnMessage;      // raw JSON string
        public event Action<string> OnError;

        private bool _running = false;
        private Coroutine _pollCoroutine;

        // ── Lifecycle ──────────────────────────────────────────────

        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);

            // Sync base URL from ApiClient if available
            if (ApiClient.Instance != null)
                baseUrl = ApiClient.Instance.BaseUrl;
            else
                baseUrl = PlayerPrefs.GetString("ApiBaseUrl", baseUrl);
        }

        private void Start()
        {
            StartCoroutine(ConnectWithRetry());
        }

        private void OnDestroy()
        {
            _running = false;
            if (_pollCoroutine != null)
                StopCoroutine(_pollCoroutine);
        }

        // ── Connection ─────────────────────────────────────────────

        /// <summary>
        /// Attempts to reach the FastAPI backend. On success, marks
        /// IsConnected = true and fires OnConnected.
        /// Phase 0: HTTP health-check only.
        /// Phase 2: Replace with NativeWebSocket upgrade handshake.
        /// </summary>
        private IEnumerator ConnectWithRetry()
        {
            _running = true;
            while (_running)
            {
                yield return StartCoroutine(PingServer());
                if (!IsConnected)
                {
                    Debug.LogWarning($"[WSClient] Cannot reach {baseUrl}. Retrying in {reconnectDelay}s...");
                    yield return new WaitForSeconds(reconnectDelay);
                }
                else
                {
                    // Connected — start polling loop (Phase 0 stub)
                    _pollCoroutine = StartCoroutine(PollLoop());
                    yield break;
                }
            }
        }

        private IEnumerator PingServer()
        {
            using var req = UnityWebRequest.Get($"{baseUrl}/api/health");
            req.timeout = 5;
            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                IsConnected = true;
                Debug.Log($"[WSClient] ✅ Connected to Commander AI Lab backend at {baseUrl}");
                OnConnected?.Invoke();
            }
            else
            {
                IsConnected = false;
                Debug.LogWarning($"[WSClient] ❌ Health check failed: {req.error}");
            }
        }

        /// <summary>
        /// Phase 0 polling stub — polls /api/play/state every pollInterval seconds
        /// when a session is active. Replace entire method with NativeWebSocket
        /// OnMessage handler in Phase 2.
        /// </summary>
        private IEnumerator PollLoop()
        {
            while (_running && IsConnected)
            {
                if (!string.IsNullOrEmpty(SessionId))
                {
                    using var req = UnityWebRequest.Get(
                        $"{baseUrl}/api/play/state?session_id={SessionId}");
                    req.timeout = 5;
                    yield return req.SendWebRequest();

                    if (req.result == UnityWebRequest.Result.Success)
                    {
                        OnMessage?.Invoke(req.downloadHandler.text);
                    }
                    else
                    {
                        IsConnected = false;
                        OnDisconnected?.Invoke();
                        OnError?.Invoke(req.error);
                        Debug.LogWarning($"[WSClient] Lost connection: {req.error}");
                        // Attempt reconnect
                        StartCoroutine(ConnectWithRetry());
                        yield break;
                    }
                }
                yield return new WaitForSeconds(pollInterval);
            }
        }

        // ── Public API ─────────────────────────────────────────────

        /// <summary>Registers a session ID so the poll loop fetches its state.</summary>
        public void SetSession(string sessionId)
        {
            SessionId = sessionId;
            Debug.Log($"[WSClient] Session set: {sessionId}");
        }

        /// <summary>
        /// Send a JSON message to the server.
        /// Phase 0: POST to /api/play/action via UnityWebRequest.
        /// Phase 2: Replace with ws.SendText(json).
        /// </summary>
        public void Send(string json)
        {
            StartCoroutine(SendPost(json));
        }

        private IEnumerator SendPost(string json)
        {
            using var req = new UnityWebRequest($"{baseUrl}/api/play/action", "POST");
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 10;
            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
                OnMessage?.Invoke(req.downloadHandler.text);
            else
                OnError?.Invoke(req.error);
        }

        /// <summary>Gracefully disconnect (Phase 2: call ws.Close()).</summary>
        public void Disconnect()
        {
            _running = false;
            IsConnected = false;
            if (_pollCoroutine != null) StopCoroutine(_pollCoroutine);
            OnDisconnected?.Invoke();
            Debug.Log("[WSClient] Disconnected.");
        }
    }
}
