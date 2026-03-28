using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace CommanderAILab.Services
{
    /// <summary>
    /// Singleton texture cache for card images.
    /// Downloads and caches Scryfall card art as Sprite or Texture2D.
    /// </summary>
    public class ImageCache : MonoBehaviour
    {
        public static ImageCache Instance { get; private set; }

        private readonly Dictionary<string, Sprite>    _spriteCache  = new();
        private readonly Dictionary<string, Texture2D> _textureCache = new();
        [SerializeField] private int maxCacheSize = 500;

        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);
        }

        // ── Sprite (existing usage) ───────────────────────────────────────────
        public void GetSprite(string url, Action<Sprite> callback)
        {
            if (string.IsNullOrEmpty(url)) { callback?.Invoke(null); return; }
            if (_spriteCache.TryGetValue(url, out var cached)) { callback?.Invoke(cached); return; }
            StartCoroutine(DownloadSprite(url, callback));
        }

        private IEnumerator DownloadSprite(string url, Action<Sprite> callback)
        {
            using var req = UnityWebRequestTexture.GetTexture(url);
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ImageCache] Sprite failed {url}: {req.error}");
                callback?.Invoke(null);
                yield break;
            }
            var tex    = DownloadHandlerTexture.GetContent(req);
            var sprite = Sprite.Create(tex, new Rect(0, 0, tex.width, tex.height), Vector2.one * 0.5f);
            if (_spriteCache.Count >= maxCacheSize) _spriteCache.Clear();
            _spriteCache[url] = sprite;
            callback?.Invoke(sprite);
        }

        // ── RawImage / Texture2D (battleground CardView + CommanderZoneWidget) ───
        /// <summary>Load a card image URL directly into a RawImage component.</summary>
        public IEnumerator LoadCard(string url, RawImage target)
        {
            if (target == null || string.IsNullOrEmpty(url)) yield break;
            if (_textureCache.TryGetValue(url, out var cached)) { target.texture = cached; yield break; }
            yield return DownloadTexture(url, tex => { if (target != null) target.texture = tex; });
        }

        /// <summary>
        /// Load Scryfall art_crop into a RawImage by card name.
        /// URL: https://api.scryfall.com/cards/named?exact={name}&format=image&version=art_crop
        /// </summary>
        public IEnumerator LoadArtCrop(string cardName, RawImage target)
        {
            if (target == null || string.IsNullOrEmpty(cardName)) yield break;
            string url = $"https://api.scryfall.com/cards/named?exact={Uri.EscapeDataString(cardName)}&format=image&version=art_crop";
            yield return LoadCard(url, target);
        }

        private IEnumerator DownloadTexture(string url, Action<Texture2D> callback)
        {
            using var req = UnityWebRequestTexture.GetTexture(url);
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ImageCache] Texture failed {url}: {req.error}");
                callback?.Invoke(null);
                yield break;
            }
            var tex = DownloadHandlerTexture.GetContent(req);
            if (_textureCache.Count >= maxCacheSize) _textureCache.Clear();
            _textureCache[url] = tex;
            callback?.Invoke(tex);
        }

        public void ClearCache() { _spriteCache.Clear(); _textureCache.Clear(); }
    }
}
