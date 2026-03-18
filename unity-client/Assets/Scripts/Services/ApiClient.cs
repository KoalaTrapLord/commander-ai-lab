using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace CommanderAILab.Services
{
    /// <summary>
    /// Singleton HTTP client for Commander AI Lab FastAPI backend.
    /// All REST calls go through this service.
    /// </summary>
    public class ApiClient : MonoBehaviour
    {
        public static ApiClient Instance { get; private set; }

        [SerializeField] private string baseUrl = "http://localhost:8080";
        [SerializeField] private float timeoutSeconds = 30f;

        public string BaseUrl
        {
            get => baseUrl;
            set
            {
                baseUrl = value.TrimEnd('/');
                PlayerPrefs.SetString("ApiBaseUrl", baseUrl);
            }
        }

        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);
            baseUrl = PlayerPrefs.GetString("ApiBaseUrl", baseUrl);
        }

        // ── Generic Helpers ──────────────────────────────────────

        public Coroutine Get<T>(string path, Action<T> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetCoroutine(path, onSuccess, onError));
        }

        public Coroutine Post<TReq, TRes>(string path, TReq body, Action<TRes> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(PostCoroutine(path, body, onSuccess, onError));
        }

        private IEnumerator GetCoroutine<T>(string path, Action<T> onSuccess, Action<string> onError)
        {
            var url = $"{baseUrl}{path}";
            using var request = UnityWebRequest.Get(url);
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ApiClient] GET {path} failed: {request.error}");
                onError?.Invoke(request.error);
                yield break;
            }
            var obj = JsonUtility.FromJson<T>(request.downloadHandler.text);
            onSuccess?.Invoke(obj);
        }

        private IEnumerator PostCoroutine<TReq, TRes>(string path, TReq body, Action<TRes> onSuccess, Action<string> onError)
        {
            var url = $"{baseUrl}{path}";
            var json = JsonUtility.ToJson(body);
            using var request = new UnityWebRequest(url, "POST");
            request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ApiClient] POST {path} failed: {request.error}");
                onError?.Invoke(request.error);
                yield break;
            }
            var obj = JsonUtility.FromJson<TRes>(request.downloadHandler.text);
            onSuccess?.Invoke(obj);
        }

        // ── Health Check ─────────────────────────────────────────

        public Coroutine HealthCheck(Action<bool> callback)
        {
            return StartCoroutine(HealthCheckCoroutine(callback));
        }

        private IEnumerator HealthCheckCoroutine(Action<bool> callback)
        {
            using var request = UnityWebRequest.Get($"{baseUrl}/docs");
            request.timeout = 5;
            yield return request.SendWebRequest();
            callback?.Invoke(request.result == UnityWebRequest.Result.Success);
        }

        // ── Collection ───────────────────────────────────────────
        // GET /api/collection
        // GET /api/collection?search=...

        // ── Decks ────────────────────────────────────────────────
        // GET  /api/decks
        // POST /api/decks
        // GET  /api/decks/{id}
        // PATCH /api/decks/{id}
        // DELETE /api/decks/{id}

        // ── Simulator ────────────────────────────────────────────
        // POST /api/lab/start
        // GET  /api/lab/status/{id}
        // GET  /api/lab/results/{id}

        // ── Coach ────────────────────────────────────────────────
        // POST /api/coach/chat

        // ── Deck Generator ───────────────────────────────────────
        // POST /api/deckgen/v3

        // ── Scanner ──────────────────────────────────────────────
        // POST /api/scanner/scan

        // ── Meta ─────────────────────────────────────────────────
        // GET /api/lab/meta/commanders
        // GET /api/lab/meta/search?q=...
        // GET /api/lab/precons
    }
}
