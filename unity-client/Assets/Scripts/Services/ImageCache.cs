using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

namespace CommanderAILab.Services
{
    /// <summary>
    /// Singleton texture cache for card images.
    /// Downloads and caches Scryfall card art as Sprite objects.
    /// </summary>
    public class ImageCache : MonoBehaviour
    {
        public static ImageCache Instance { get; private set; }

        private readonly Dictionary<string, Sprite> cache = new();
        [SerializeField] private int maxCacheSize = 500;

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
            StartCoroutine(DownloadImage(url, callback));
        }

        private IEnumerator DownloadImage(string url, System.Action<Sprite> callback)
        {
            using var request = UnityWebRequestTexture.GetTexture(url);
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ImageCache] Failed to load {url}: {request.error}");
                callback?.Invoke(null);
                yield break;
            }

            var tex = DownloadHandlerTexture.GetContent(request);
            var sprite = Sprite.Create(tex, new Rect(0, 0, tex.width, tex.height), Vector2.one * 0.5f);

            if (cache.Count >= maxCacheSize) cache.Clear();
            cache[url] = sprite;
            callback?.Invoke(sprite);
        }

        public void ClearCache() => cache.Clear();
    }
}
