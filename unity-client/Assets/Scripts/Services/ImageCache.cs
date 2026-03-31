using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

namespace CommanderAILab.Services
{
    /// <summary>
    /// Singleton texture cache for card images.
    /// Downloads and caches Scryfall card art as Sprite objects.
    /// Creates owned copies of textures so they survive request disposal.
    /// </summary>
    public class ImageCache : MonoBehaviour
    {
        public static ImageCache Instance { get; private set; }

        private readonly Dictionary<string, Sprite> cache = new();
        [SerializeField] private int maxCacheSize = 500;

        // Track in-flight downloads to avoid duplicate requests
        private readonly HashSet<string> downloading = new();
        private readonly Dictionary<string, List<System.Action<Sprite>>> pendingCallbacks = new();

        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);
        }

        public void GetSprite(string url, System.Action<Sprite> callback)
        {
            if (string.IsNullOrEmpty(url)) { callback?.Invoke(null); return; }
            if (cache.TryGetValue(url, out var cached)) { callback?.Invoke(cached); return; }

            // If already downloading this URL, queue the callback
            if (downloading.Contains(url))
            {
                if (!pendingCallbacks.ContainsKey(url))
                    pendingCallbacks[url] = new List<System.Action<Sprite>>();
                pendingCallbacks[url].Add(callback);
                return;
            }

            downloading.Add(url);
            pendingCallbacks[url] = new List<System.Action<Sprite>> { callback };
            StartCoroutine(DownloadImage(url));
        }

        private IEnumerator DownloadImage(string url)
        {
            var request = UnityWebRequestTexture.GetTexture(url);
            yield return request.SendWebRequest();

            Sprite sprite = null;

            if (request.result == UnityWebRequest.Result.Success)
            {
                // Get the downloaded texture (owned by request)
                var downloadedTex = DownloadHandlerTexture.GetContent(request);

                // Create an owned copy so it survives request disposal
                var tex = new Texture2D(downloadedTex.width, downloadedTex.height, downloadedTex.format, false);
                Graphics.CopyTexture(downloadedTex, tex);
                tex.name = $"Card_{url.GetHashCode()}";

                sprite = Sprite.Create(tex, new Rect(0, 0, tex.width, tex.height), Vector2.one * 0.5f);

                if (cache.Count >= maxCacheSize) cache.Clear();
                cache[url] = sprite;
            }
            else
            {
                Debug.LogWarning($"[ImageCache] Failed to load {url}: {request.error}");
            }

            // Dispose the request now that we have our copy
            request.Dispose();

            // Notify all waiting callbacks
            downloading.Remove(url);
            if (pendingCallbacks.TryGetValue(url, out var callbacks))
            {
                foreach (var cb in callbacks)
                    cb?.Invoke(sprite);
                pendingCallbacks.Remove(url);
            }
        }

        public void ClearCache() => cache.Clear();
    }
}
