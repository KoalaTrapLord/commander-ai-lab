using System;
using System.Runtime.InteropServices;
using UnityEngine;

namespace CommanderAILab.Services
{
    /// <summary>
    /// WebGL-specific bridge: reads server URL from URL query params,
    /// provides JS interop for file input (camera fallback on WebGL),
    /// handles browser security restrictions (HTTPS in prod),
    /// and loading screen progress.
    /// </summary>
    public class WebGLBridge : MonoBehaviour
    {
        public static WebGLBridge Instance { get; private set; }

#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")] private static extern string GetURLParam(string key);
        [DllImport("__Internal")] private static extern void OpenFileDialog(string accept, string callbackObject, string callbackMethod);
        [DllImport("__Internal")] private static extern void SetLoadingProgress(float progress);
#else
        private static string GetURLParam(string key) => "";
        private static void OpenFileDialog(string accept, string obj, string method) { }
        private static void SetLoadingProgress(float progress) { }
#endif

        private Action<byte[]> _fileCallback;

        private void Awake()
        {
            if (Instance != null) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);
        }

        /// <summary>
        /// Read server URL from ?server= query param.
        /// Falls back to http://localhost:8080 if not set.
        /// </summary>
        public string GetServerUrl()
        {
            string url = "";
#if UNITY_WEBGL && !UNITY_EDITOR
            try { url = GetURLParam("server"); } catch { }
#endif
            if (string.IsNullOrEmpty(url)) url = "http://localhost:8080";

            // Browser security: enforce HTTPS in production
            if (IsProductionBuild() && url.StartsWith("http://"))
            {
                Debug.LogWarning("[WebGLBridge] Production build should use HTTPS. Upgrading URL.");
                url = url.Replace("http://", "https://");
            }
            return url;
        }

        /// <summary>
        /// Open a file picker dialog (WebGL camera fallback).
        /// On WebGL, WebCamTexture is not available so we use
        /// an HTML file input element instead.
        /// </summary>
        public void PickImageFile(Action<byte[]> callback)
        {
            _fileCallback = callback;
#if UNITY_WEBGL && !UNITY_EDITOR
            OpenFileDialog("image/*", gameObject.name, "OnFileSelected");
#else
            Debug.LogWarning("[WebGLBridge] File picker is only available in WebGL builds.");
#endif
        }

        /// <summary>Called from JavaScript when file is selected.</summary>
        public void OnFileSelected(string base64Data)
        {
            if (string.IsNullOrEmpty(base64Data)) return;
            try
            {
                byte[] data = Convert.FromBase64String(base64Data);
                _fileCallback?.Invoke(data);
            }
            catch (Exception e)
            {
                Debug.LogError($"[WebGLBridge] File parse error: {e.Message}");
            }
        }

        /// <summary>Update the loading screen progress bar (0–1).</summary>
        public void UpdateLoadingProgress(float progress)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            SetLoadingProgress(Mathf.Clamp01(progress));
#endif
        }

        private bool IsProductionBuild()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            // Check if running on localhost
            string host = Application.absoluteURL;
            return !host.Contains("localhost") && !host.Contains("127.0.0.1");
#else
            return false;
#endif
        }
    }
}
