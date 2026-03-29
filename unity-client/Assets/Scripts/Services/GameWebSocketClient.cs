using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using Newtonsoft.Json;
using CommanderAILab.UI;

namespace CommanderAILab.Services
{
    /// <summary>
    /// WebSocket client for the live game backend.
    /// Connects to ws://{serverHost}/ws/game/{gameId}.
    ///
    /// game_id is written to PlayerPrefs["GameId"] by LobbySetupModal
    /// after a successful POST /api/game/start response.
    ///
    /// ServerUrl PlayerPref should be the HTTP base URL, e.g.
    /// "http://localhost:8080" — this client converts it to ws://.
    /// </summary>
    public class GameWebSocketClient : MonoBehaviour
    {
        [SerializeField] private string defaultServerUrl   = "http://localhost:8080";
        [SerializeField] private float  reconnectDelay     = 3f;
        [SerializeField] private float  pingIntervalSec    = 15f;

        private System.Net.WebSockets.ClientWebSocket _ws;
        private CancellationTokenSource _cts;
        private readonly ConcurrentQueue<(string type, string payload)> _mainThreadQueue = new();
        private bool _running;
        private float _pingTimer;
        private string _wsUrl;

        // ── Lifecycle ────────────────────────────────────────────────────────
        private void Start()
        {
            _wsUrl = BuildWsUrl();
            if (string.IsNullOrEmpty(_wsUrl))
            {
                Debug.LogError("[GameWebSocketClient] Could not build WS URL — PlayerPrefs 'GameId' is missing. " +
                               "LobbySetupModal must set it after /api/game/start.");
                return;
            }

            _running = true;
            StartCoroutine(ConnectLoop());
        }

        private void Update()
        {
            // Drain main-thread queue
            while (_mainThreadQueue.TryDequeue(out var msg))
                GameStateManager.Instance?.ApplyServerEvent(msg.type, msg.payload);

            // Ping
            _pingTimer += Time.deltaTime;
            if (_pingTimer >= pingIntervalSec)
            {
                _pingTimer = 0f;
                _ = SendRawAsync("{\"type\":\"ping\"}");
            }
        }

        private void OnDestroy()
        {
            _running = false;
            _cts?.Cancel();
            _ws?.Dispose();
        }

        // ── URL construction ────────────────────────────────────────────────
        /// <summary>
        /// Builds ws://{host}/ws/game/{gameId} from PlayerPrefs.
        /// ServerUrl pref stores the HTTP base URL (e.g. http://localhost:8080).
        /// GameId pref stores the game_id returned by /api/game/start.
        /// </summary>
        private string BuildWsUrl()
        {
            string gameId = PlayerPrefs.GetString("GameId", "");
            if (string.IsNullOrEmpty(gameId))
                return string.Empty;

            string httpBase = PlayerPrefs.GetString("ServerUrl", defaultServerUrl).TrimEnd('/');

            // Convert http(s):// to ws(s)://
            string wsBase = httpBase
                .Replace("https://", "wss://")
                .Replace("http://",  "ws://");

            return $"{wsBase}/ws/game/{gameId}";
        }

        // ── Connection loop ──────────────────────────────────────────────────
        private IEnumerator ConnectLoop()
        {
            while (_running)
            {
                _cts = new CancellationTokenSource();
                _ws  = new System.Net.WebSockets.ClientWebSocket();

                bool connected = false;
                var connectTask = _ws.ConnectAsync(new Uri(_wsUrl), _cts.Token);

                yield return new WaitUntil(() => connectTask.IsCompleted);

                if (!connectTask.IsFaulted && !connectTask.IsCanceled)
                {
                    connected = true;
                    Debug.Log("[GameWebSocketClient] Connected to " + _wsUrl);
                    _ = ReceiveLoop();
                }
                else
                {
                    Debug.LogWarning($"[GameWebSocketClient] Connect failed ({_wsUrl}): {connectTask.Exception?.Message}");
                }

                if (!connected)
                {
                    yield return new WaitForSeconds(reconnectDelay);
                }
                else
                {
                    yield return new WaitUntil(() =>
                        _ws.State != System.Net.WebSockets.WebSocketState.Open);

                    Debug.Log("[GameWebSocketClient] Disconnected — reconnecting...");
                    yield return new WaitForSeconds(reconnectDelay);
                }
            }
        }

        // ── Receive loop (background thread) ────────────────────────────────
        private async Task ReceiveLoop()
        {
            var buffer = new byte[8192];
            try
            {
                while (_ws.State == System.Net.WebSockets.WebSocketState.Open)
                {
                    var sb = new StringBuilder();
                    System.Net.WebSockets.WebSocketReceiveResult result;
                    do
                    {
                        result = await _ws.ReceiveAsync(
                            new ArraySegment<byte>(buffer), _cts.Token);
                        sb.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                    } while (!result.EndOfMessage);

                    if (result.MessageType ==
                        System.Net.WebSockets.WebSocketMessageType.Close)
                        break;

                    ParseAndEnqueue(sb.ToString());
                }
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                Debug.LogWarning($"[GameWebSocketClient] ReceiveLoop error: {ex.Message}");
            }
        }

        // ── Parse incoming JSON envelope ─────────────────────────────────────
        private void ParseAndEnqueue(string raw)
        {
            try
            {
                var env = JsonConvert.DeserializeObject<WsEnvelope>(raw);
                if (env == null) return;
                if (env.type == "pong") return;
                _mainThreadQueue.Enqueue((env.type, env.payload ?? raw));
            }
            catch
            {
                Debug.LogWarning($"[GameWebSocketClient] Failed to parse: {raw}");
            }
        }

        // ── Send (public for external callers) ───────────────────────────────
        public async Task SendRawAsync(string json)
        {
            if (_ws == null ||
                _ws.State != System.Net.WebSockets.WebSocketState.Open) return;
            try
            {
                var bytes = Encoding.UTF8.GetBytes(json);
                await _ws.SendAsync(new ArraySegment<byte>(bytes),
                    System.Net.WebSockets.WebSocketMessageType.Text,
                    true, _cts?.Token ?? CancellationToken.None);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[GameWebSocketClient] Send error: {ex.Message}");
            }
        }

        // ── POCO ────────────────────────────────────────────────────────────────
        [Serializable]
        private class WsEnvelope
        {
            [JsonProperty("type")]    public string type;
            [JsonProperty("payload")] public string payload;
        }
    }
}
