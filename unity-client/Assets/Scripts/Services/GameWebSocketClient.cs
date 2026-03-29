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
    /// WebSocket client for the live game backend (ws://localhost:8080/ws/game).
    /// - Connects on Start and auto-reconnects on disconnect.
    /// - Sends a ping every 15 s to keep the connection alive.
    /// - All GameStateManager.ApplyServerEvent calls are dispatched
    ///   on the Unity main thread via a thread-safe queue.
    /// </summary>
    public class GameWebSocketClient : MonoBehaviour
    {
        [SerializeField] private string serverUrl = "ws://localhost:8080/ws/game";
        [SerializeField] private float  reconnectDelay  = 3f;
        [SerializeField] private float  pingIntervalSec = 15f;

        private System.Net.WebSockets.ClientWebSocket _ws;
        private CancellationTokenSource _cts;
        private readonly ConcurrentQueue<(string type, string payload)> _mainThreadQueue = new();
        private bool _running;
        private float _pingTimer;

        // ── Lifecycle ────────────────────────────────────────────────────────
        private void Start()
        {
            // Allow override via PlayerPrefs so users can point at a remote server
            string saved = PlayerPrefs.GetString("ServerUrl", "");
            if (!string.IsNullOrEmpty(saved)) serverUrl = saved.TrimEnd('/') + "/ws/game";

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

        // ── Connection loop ──────────────────────────────────────────────────
        private IEnumerator ConnectLoop()
        {
            while (_running)
            {
                _cts = new CancellationTokenSource();
                _ws  = new System.Net.WebSockets.ClientWebSocket();

                bool connected = false;
                var connectTask = _ws.ConnectAsync(new Uri(serverUrl), _cts.Token);

                yield return new WaitUntil(() => connectTask.IsCompleted);

                if (!connectTask.IsFaulted && !connectTask.IsCanceled)
                {
                    connected = true;
                    Debug.Log("[GameWebSocketClient] Connected to " + serverUrl);
                    _ = ReceiveLoop();
                }
                else
                {
                    Debug.LogWarning($"[GameWebSocketClient] Connect failed: {connectTask.Exception?.Message}");
                }

                if (!connected)
                {
                    yield return new WaitForSeconds(reconnectDelay);
                }
                else
                {
                    // Stay here until the WS closes
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

                    string raw = sb.ToString();
                    ParseAndEnqueue(raw);
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

                if (env.type == "pong") return;  // ignore keepalive responses

                _mainThreadQueue.Enqueue((env.type, env.payload ?? raw));
            }
            catch
            {
                Debug.LogWarning($"[GameWebSocketClient] Failed to parse: {raw}");
            }
        }

        // ── Send (public for HumanActionBar fallback) ────────────────────────
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

        // ── POCO ─────────────────────────────────────────────────────────────
        [Serializable]
        private class WsEnvelope
        {
            [JsonProperty("type")]    public string type;
            [JsonProperty("payload")] public string payload;
        }
    }
}
