using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;
using CommanderAILab.Models;

namespace CommanderAILab.Services
{
    /// <summary>
    /// REST client for the /api/play/* interactive game endpoints.
    /// Works alongside ApiClient (which handles collection/deck/sim routes).
    /// </summary>
    public class GameSessionService : MonoBehaviour
    {
        public static GameSessionService Instance { get; private set; }

        [Header("Connection")]
        [SerializeField] private string baseUrl = "http://localhost:8080";
        [SerializeField] private float timeoutSeconds = 30f;

        /// <summary>Current game session ID (set after NewGame).</summary>
        public string SessionId { get; private set; }

        /// <summary>Latest game state snapshot.</summary>
        public GameStateResponse CurrentState { get; private set; }

        // Events for UI/board updates
        public event Action<GameStateResponse> OnStateUpdated;
        public event Action<string> OnError;
        public event Action<string> OnGameLog;

        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);

            // Sync with ApiClient base URL if available
            if (ApiClient.Instance != null)
                baseUrl = ApiClient.Instance.BaseUrl;
            else
                baseUrl = PlayerPrefs.GetString("ApiBaseUrl", baseUrl);
        }

        // ── Public API ──────────────────────────────────────────────

        /// <summary>Create a new game session on the server.</summary>
        public void NewGame(NewGameRequest request, Action<GameStateResponse> callback = null)
        {
            StartCoroutine(PostJson("/api/play/new", request, (GameStateResponse state) =>
            {
                SessionId = state.sessionId;
                UpdateState(state);
                callback?.Invoke(state);
            }));
        }

        /// <summary>Fetch current game state.</summary>
        public void RefreshState(Action<GameStateResponse> callback = null)
        {
            StartCoroutine(GetJson<GameStateResponse>(
                $"/api/play/state?session_id={SessionId}", state =>
                {
                    UpdateState(state);
                    callback?.Invoke(state);
                }));
        }

        /// <summary>Play a card from hand or command zone.</summary>
        public void PlayCard(int cardId, Action<ActionResult> callback = null)
        {
            var req = new PlayActionRequest
            {
                sessionId = SessionId,
                actionType = "play_card",
                cardId = cardId
            };
            StartCoroutine(PostJson("/api/play/action", req, (ActionResult result) =>
            {
                UpdateState(result.state);
                OnGameLog?.Invoke(result.result);
                callback?.Invoke(result);
            }));
        }

        /// <summary>Declare an attack with a creature against a target player.</summary>
        public void Attack(int cardId, int targetSeat, Action<ActionResult> callback = null)
        {
            var req = new PlayActionRequest
            {
                sessionId = SessionId,
                actionType = "attack",
                cardId = cardId,
                targetSeat = targetSeat
            };
            StartCoroutine(PostJson("/api/play/action", req, (ActionResult result) =>
            {
                UpdateState(result.state);
                OnGameLog?.Invoke(result.result);
                callback?.Invoke(result);
            }));
        }

        /// <summary>Pass priority.</summary>
        public void Pass(Action<ActionResult> callback = null)
        {
            var req = new PlayActionRequest
            {
                sessionId = SessionId,
                actionType = "pass"
            };
            StartCoroutine(PostJson("/api/play/action", req, (ActionResult result) =>
            {
                UpdateState(result.state);
                callback?.Invoke(result);
            }));
        }

        /// <summary>Advance to the next game phase.</summary>
        public void NextPhase(Action<PhaseResult> callback = null)
        {
            StartCoroutine(PostEmpty<PhaseResult>(
                $"/api/play/next-phase?session_id={SessionId}", result =>
                {
                    UpdateState(result.state);
                    callback?.Invoke(result);
                }));
        }

        /// <summary>Let the current AI player take their full turn.</summary>
        public void AITurn(Action<AITurnResult> callback = null)
        {
            StartCoroutine(PostEmpty<AITurnResult>(
                $"/api/play/ai-turn?session_id={SessionId}", result =>
                {
                    UpdateState(result.state);
                    if (result.actions != null)
                        foreach (var a in result.actions)
                            OnGameLog?.Invoke(a);
                    callback?.Invoke(result);
                }));
        }

        /// <summary>Get legal moves for the active player.</summary>
        public void GetLegalMoves(Action<LegalMove[]> callback)
        {
            StartCoroutine(GetRaw(
                $"/api/play/legal-moves?session_id={SessionId}", json =>
                {
                    var moves = JsonConvert.DeserializeObject<LegalMove[]>(json);
                    callback?.Invoke(moves);
                }));
        }

        // ── Internals ───────────────────────────────────────────────

        private void UpdateState(GameStateResponse state)
        {
            if (state == null) return;
            CurrentState = state;
            OnStateUpdated?.Invoke(state);
        }

        private IEnumerator PostJson<TRes>(string path, object body, Action<TRes> onSuccess)
        {
            var url = $"{baseUrl}{path}";
            var json = JsonConvert.SerializeObject(body);
            using var request = new UnityWebRequest(url, "POST");
            request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[GameSession] POST {path} failed: {request.error}");
                OnError?.Invoke(request.error);
                yield break;
            }
            var obj = JsonConvert.DeserializeObject<TRes>(request.downloadHandler.text);
            onSuccess?.Invoke(obj);
        }

        private IEnumerator PostEmpty<TRes>(string path, Action<TRes> onSuccess)
        {
            var url = $"{baseUrl}{path}";
            using var request = new UnityWebRequest(url, "POST");
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes("{}"));
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[GameSession] POST {path} failed: {request.error}");
                OnError?.Invoke(request.error);
                yield break;
            }
            var obj = JsonConvert.DeserializeObject<TRes>(request.downloadHandler.text);
            onSuccess?.Invoke(obj);
        }

        private IEnumerator GetJson<T>(string path, Action<T> onSuccess)
        {
            var url = $"{baseUrl}{path}";
            using var request = UnityWebRequest.Get(url);
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[GameSession] GET {path} failed: {request.error}");
                OnError?.Invoke(request.error);
                yield break;
            }
            var obj = JsonConvert.DeserializeObject<T>(request.downloadHandler.text);
            onSuccess?.Invoke(obj);
        }

        private IEnumerator GetRaw(string path, Action<string> onSuccess)
        {
            var url = $"{baseUrl}{path}";
            using var request = UnityWebRequest.Get(url);
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[GameSession] GET {path} failed: {request.error}");
                OnError?.Invoke(request.error);
                yield break;
            }
            onSuccess?.Invoke(request.downloadHandler.text);
        }
    }
}
