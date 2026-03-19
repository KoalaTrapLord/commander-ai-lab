using System;
using System.Collections;
using System.Collections.Generic;
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

        // -- Generic Helpers ------------------------------------------------

        public Coroutine Get<T>(string path, Action<T> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetCoroutine(path, onSuccess, onError));
        }

        public Coroutine Post<TReq, TRes>(string path, TReq body, Action<TRes> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(PostCoroutine(path, body, onSuccess, onError));
        }

        public Coroutine PostRaw(string path, string json, Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(PostRawCoroutine(path, json, onSuccess, onError));
        }

        public Coroutine GetRaw(string path, Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetRawCoroutine(path, onSuccess, onError));
        }

        public Coroutine PatchRaw(string path, string json, Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(PatchRawCoroutine(path, json, onSuccess, onError));
        }

        public Coroutine Delete(string path, Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(DeleteCoroutine(path, onSuccess, onError));
        }

        // -- Coroutine implementations --------------------------------------

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

        private IEnumerator PostRawCoroutine(string path, string json, Action<string> onSuccess, Action<string> onError)
        {
            var url = $"{baseUrl}{path}";
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
            onSuccess?.Invoke(request.downloadHandler.text);
        }

        private IEnumerator PatchRawCoroutine(string path, string json, Action<string> onSuccess, Action<string> onError)
        {
            var url = $"{baseUrl}{path}";
            using var request = new UnityWebRequest(url, "PATCH");
            request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ApiClient] PATCH {path} failed: {request.error}");
                onError?.Invoke(request.error);
                yield break;
            }
            onSuccess?.Invoke(request.downloadHandler.text);
        }

        private IEnumerator DeleteCoroutine(string path, Action<string> onSuccess, Action<string> onError)
        {
            var url = $"{baseUrl}{path}";
            using var request = UnityWebRequest.Delete(url);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ApiClient] DELETE {path} failed: {request.error}");
                onError?.Invoke(request.error);
                yield break;
            }
            onSuccess?.Invoke(request.downloadHandler.text);
        }

        // -- Raw GET helper (returns JSON string) ---------------------------

        private IEnumerator GetRawCoroutine(string path, Action<string> onSuccess, Action<string> onError)
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
            onSuccess?.Invoke(request.downloadHandler.text);
        }

        // -- Health Check ---------------------------------------------------

        public Coroutine HealthCheck(Action<bool> callback)
        {
            return StartCoroutine(HealthCheckCoroutine(callback));
        }

        private IEnumerator HealthCheckCoroutine(Action<bool> callback)
        {
            using var request = UnityWebRequest.Get($"{baseUrl}/api/health");
            request.timeout = 5;
            yield return request.SendWebRequest();
            callback?.Invoke(request.result == UnityWebRequest.Result.Success);
        }

        // -- Collection -----------------------------------------------------

        public Coroutine GetCollection(Action<string> onSuccess, Action<string> onError = null, string search = null)
        {
            var path = string.IsNullOrEmpty(search)
                ? "/api/collection"
                : $"/api/collection?search={UnityWebRequest.EscapeURL(search)}";
            return StartCoroutine(GetRawCoroutine(path, onSuccess, onError));
        }

        // -- Decks ----------------------------------------------------------

        public Coroutine GetDecks(Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetRawCoroutine("/api/decks", onSuccess, onError));
        }

        public Coroutine CreateDeck(string deckJson, Action<string> onSuccess, Action<string> onError = null)
        {
            return PostRaw("/api/decks", deckJson, onSuccess, onError);
        }

        // -- Simulator ------------------------------------------------------

        public Coroutine StartSim(string configJson, Action<string> onSuccess, Action<string> onError = null)
        {
            return PostRaw("/api/lab/start", configJson, onSuccess, onError);
        }

        public Coroutine GetSimStatus(string simId, Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetRawCoroutine($"/api/lab/status/{simId}", onSuccess, onError));
        }

        public Coroutine GetSimResults(string simId, Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetRawCoroutine($"/api/lab/results/{simId}", onSuccess, onError));
        }

        // -- Coach ----------------------------------------------------------

        public Coroutine CoachChat(string messageJson, Action<string> onSuccess, Action<string> onError = null)
        {
            return PostRaw("/api/coach/chat", messageJson, onSuccess, onError);
        }

        // -- Deck Generator -------------------------------------------------

        public Coroutine GenerateDeck(string requestJson, Action<string> onSuccess, Action<string> onError = null)
        {
            return PostRaw("/api/deckgen/v3", requestJson, onSuccess, onError);
        }

        // -- Meta -----------------------------------------------------------

        public Coroutine GetCommanders(Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetRawCoroutine("/api/lab/meta/commanders", onSuccess, onError));
        }

        public Coroutine GetPrecons(Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(GetRawCoroutine("/api/lab/precons", onSuccess, onError));
        }

        // -- Scanner --------------------------------------------------------

        public Coroutine ScanCard(byte[] imageBytes, Action<string> onSuccess, Action<string> onError = null)
        {
            return StartCoroutine(ScanCardCoroutine(imageBytes, onSuccess, onError));
        }

        private IEnumerator ScanCardCoroutine(byte[] imageBytes, Action<string> onSuccess, Action<string> onError)
        {
            var url = $"{baseUrl}/api/scanner/scan";
            var form = new WWWForm();
            form.AddBinaryData("file", imageBytes, "card.jpg", "image/jpeg");
            using var request = UnityWebRequest.Post(url, form);
            request.timeout = (int)timeoutSeconds;
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ApiClient] POST /api/scanner/scan failed: {request.error}");
                onError?.Invoke(request.error);
                yield break;
            }
            onSuccess?.Invoke(request.downloadHandler.text);
        }
    }
}
