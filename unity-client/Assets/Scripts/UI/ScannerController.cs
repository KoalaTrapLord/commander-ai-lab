using System;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using TMPro;
using Newtonsoft.Json;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Scanner scene — live camera feed, capture frame, POST /api/scanner/scan,
    /// display result card overlay, add to collection or deck.
    /// WebGL fallback: file upload when camera is unavailable.
    /// </summary>
    public class ScannerController : MonoBehaviour
    {
        [Header("Navigation")]
        [SerializeField] private Button backButton;

        [Header("Camera Feed")]
        [SerializeField] private RawImage    cameraFeedImage;
        [SerializeField] private Button      captureButton;
        [SerializeField] private Button      toggleCameraButton;
        [SerializeField] private TMP_Text    cameraStatusText;
        [SerializeField] private GameObject  scanOverlay;        // animated scan line

        [Header("WebGL File Upload Fallback")]
        [SerializeField] private GameObject  fileUploadPanel;
        [SerializeField] private Button      fileUploadButton;
        [SerializeField] private TMP_Text    fileUploadStatusText;
        [SerializeField] private RawImage    uploadPreviewImage;

        [Header("Result Panel")]
        [SerializeField] private GameObject  resultPanel;
        [SerializeField] private Image       resultCardImage;
        [SerializeField] private TMP_Text    resultCardName;
        [SerializeField] private TMP_Text    resultManaCost;
        [SerializeField] private TMP_Text    resultType;
        [SerializeField] private TMP_Text    resultSet;
        [SerializeField] private TMP_Text    resultOracleText;
        [SerializeField] private TMP_Text    resultConfidence;
        [SerializeField] private Button      addToCollectionButton;
        [SerializeField] private Button      addToDeckButton;
        [SerializeField] private Button      scanAgainButton;

        [Header("Scan History")]
        [SerializeField] private Transform   historyParent;
        [SerializeField] private GameObject  historyRowPrefab;

        [Header("Error")]
        [SerializeField] private GameObject  errorPanel;
        [SerializeField] private TMP_Text    errorText;
        [SerializeField] private Button      retryButton;

        private WebCamTexture _webcam;
        private int _cameraIndex = 0;
        private CardModel _scannedCard;
        private bool _isScanning = false;
        private bool _isWebGL = false;
        private readonly List<CardModel> _history = new();
        private readonly List<GameObject> _historyRows = new();

        // WebGL JS interop for file upload
#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")]
        private static extern void WebGLFileUploadInit(string objectName, string methodName);

        [DllImport("__Internal")]
        private static extern void WebGLFileUploadClick();
#else
        private static void WebGLFileUploadInit(string objectName, string methodName) { }
        private static void WebGLFileUploadClick() { }
#endif

        private void Start()
        {
            backButton.onClick.AddListener(OnBack);
            captureButton.onClick.AddListener(OnCapture);
            toggleCameraButton.onClick.AddListener(ToggleCamera);
            addToCollectionButton.onClick.AddListener(OnAddToCollection);
            addToDeckButton.onClick.AddListener(OnAddToDeck);
            scanAgainButton.onClick.AddListener(OnScanAgain);
            retryButton.onClick.AddListener(OnCapture);
            if (fileUploadButton != null)
                fileUploadButton.onClick.AddListener(OnFileUploadClick);

            resultPanel.SetActive(false);
            errorPanel.SetActive(false);
            scanOverlay.SetActive(false);

            // Detect WebGL and show appropriate UI
#if UNITY_WEBGL && !UNITY_EDITOR
            _isWebGL = true;
#endif
            if (_isWebGL)
                InitWebGLFallback();
            else
                StartCamera(_cameraIndex);
        }

        private void OnDestroy()
        {
            if (_webcam != null && _webcam.isPlaying) _webcam.Stop();
        }

        // ── WebGL File Upload Fallback ──────────────────────────────
        private void InitWebGLFallback()
        {
            // Hide camera UI, show file upload panel
            cameraFeedImage.gameObject.SetActive(false);
            toggleCameraButton.gameObject.SetActive(false);
            captureButton.gameObject.SetActive(false);
            if (fileUploadPanel != null) fileUploadPanel.SetActive(true);
            if (fileUploadStatusText != null)
                fileUploadStatusText.text = "Camera not available in browser.\nUpload a card image to scan.";
            cameraStatusText.text = "WebGL Mode: File Upload";

            // Initialize JS file input
            WebGLFileUploadInit(gameObject.name, "OnWebGLFileUploaded");
        }

        private void OnFileUploadClick()
        {
            if (_isScanning) return;
#if UNITY_WEBGL && !UNITY_EDITOR
            WebGLFileUploadClick();
#else
            // Editor/standalone fallback: use a test image or show message
            if (fileUploadStatusText != null)
                fileUploadStatusText.text = "File upload only available in WebGL builds.";
#endif
        }

        /// <summary>
        /// Called from JavaScript when user selects a file.
        /// Receives base64-encoded image data.
        /// </summary>
        public void OnWebGLFileUploaded(string base64Data)
        {
            if (_isScanning) return;
            _isScanning = true;
            errorPanel.SetActive(false);
            resultPanel.SetActive(false);
            scanOverlay.SetActive(true);

            if (fileUploadStatusText != null)
                fileUploadStatusText.text = "Scanning uploaded image...";

            try
            {
                byte[] imageBytes = Convert.FromBase64String(base64Data);

                // Show preview
                if (uploadPreviewImage != null)
                {
                    var tex = new Texture2D(2, 2);
                    tex.LoadImage(imageBytes);
                    uploadPreviewImage.texture = tex;
                    uploadPreviewImage.gameObject.SetActive(true);
                }

                // Send to scanner API
                ApiClient.Instance.ScanCard(imageBytes,
                    json =>
                    {
                        scanOverlay.SetActive(false);
                        _isScanning = false;
                        try
                        {
                            var result = JsonConvert.DeserializeObject<ScanResult>(json);
                            if (result?.card != null)
                            {
                                ShowResult(result.card, result.confidence);
                                if (fileUploadStatusText != null)
                                    fileUploadStatusText.text = "Card detected! Upload another to scan.";
                            }
                            else
                            {
                                ShowError("Card not recognized. Try a clearer image.");
                                if (fileUploadStatusText != null)
                                    fileUploadStatusText.text = "Not recognized. Try another image.";
                            }
                        }
                        catch (Exception e) { ShowError($"Parse error: {e.Message}"); }
                    },
                    err =>
                    {
                        scanOverlay.SetActive(false);
                        _isScanning = false;
                        ShowError($"Scan failed:\n{err}");
                        if (fileUploadStatusText != null)
                            fileUploadStatusText.text = "Scan failed. Try again.";
                    });
            }
            catch (Exception e)
            {
                scanOverlay.SetActive(false);
                _isScanning = false;
                ShowError($"Invalid image data: {e.Message}");
            }
        }

        // ── Camera ──────────────────────────────────────────────────
        private void StartCamera(int idx)
        {
            if (fileUploadPanel != null) fileUploadPanel.SetActive(false);
            if (_webcam != null && _webcam.isPlaying) _webcam.Stop();
            var devices = WebCamTexture.devices;
            if (devices.Length == 0)
            {
                cameraStatusText.text = "No camera found";
                captureButton.interactable = false;
                // Fall back to file upload even on desktop
                if (fileUploadPanel != null)
                {
                    fileUploadPanel.SetActive(true);
                    if (fileUploadStatusText != null)
                        fileUploadStatusText.text = "No camera detected.\nUpload a card image instead.";
                }
                return;
            }
            idx = Mathf.Clamp(idx, 0, devices.Length - 1);
            _webcam = new WebCamTexture(devices[idx].name, 1280, 720, 30);
            _webcam.Play();
            cameraFeedImage.texture = _webcam;
            cameraStatusText.text = $"Camera: {devices[idx].name}";
            captureButton.interactable = true;
        }

        private void ToggleCamera()
        {
            var devices = WebCamTexture.devices;
            if (devices.Length < 2) return;
            _cameraIndex = (_cameraIndex + 1) % devices.Length;
            StartCamera(_cameraIndex);
        }

        // ── Capture & Scan ──────────────────────────────────────────
        private void OnCapture()
        {
            if (_isScanning || _webcam == null || !_webcam.isPlaying) return;
            _isScanning = true;
            errorPanel.SetActive(false);
            resultPanel.SetActive(false);
            scanOverlay.SetActive(true);
            captureButton.interactable = false;

            var tex = new Texture2D(_webcam.width, _webcam.height);
            tex.SetPixels(_webcam.GetPixels());
            tex.Apply();
            byte[] jpegBytes = tex.EncodeToJPG(85);
            Destroy(tex);

            ApiClient.Instance.ScanCard(jpegBytes,
                json =>
                {
                    scanOverlay.SetActive(false);
                    _isScanning = false;
                    captureButton.interactable = true;
                    try
                    {
                        var result = JsonConvert.DeserializeObject<ScanResult>(json);
                        if (result?.card != null)
                            ShowResult(result.card, result.confidence);
                        else
                            ShowError("Card not recognized. Try again.");
                    }
                    catch (Exception e) { ShowError($"Parse error: {e.Message}"); }
                },
                err =>
                {
                    scanOverlay.SetActive(false);
                    _isScanning = false;
                    captureButton.interactable = true;
                    ShowError($"Scan failed:\n{err}");
                });
        }

        // ── Result ──────────────────────────────────────────────────
        private void ShowResult(CardModel card, float confidence)
        {
            _scannedCard = card;
            resultPanel.SetActive(true);
            resultCardName.text = card.name;
            resultManaCost.text = card.manaCost;
            resultType.text = card.typeLine;
            resultSet.text = card.set;
            resultOracleText.text = card.oracleText;
            resultConfidence.text = $"Confidence: {confidence:P0}";
            if (!string.IsNullOrEmpty(card.imageUri))
                ImageCache.Instance.GetSprite(card.imageUri, s => { if (resultCardImage != null) resultCardImage.sprite = s; });
            AddToHistory(card);
        }

        private void AddToHistory(CardModel card)
        {
            _history.Add(card);
            var row = Instantiate(historyRowPrefab, historyParent);
            _historyRows.Add(row);
            var lbl = row.GetComponentInChildren<TMP_Text>();
            if (lbl) lbl.text = card.name;
            var btn = row.GetComponentInChildren<Button>();
            var captured = card;
            if (btn) btn.onClick.AddListener(() => ShowResult(captured, 1f));
        }

        private void OnScanAgain()
        {
            resultPanel.SetActive(false);
            _scannedCard = null;
        }

        // ── Add to Collection / Deck ────────────────────────────────
        private void OnAddToCollection()
        {
            if (_scannedCard == null) return;
            var body = JsonConvert.SerializeObject(new { card_id = _scannedCard.id, qty = 1 });
            ApiClient.Instance.PostRaw("/api/collection/add", body,
                _ => cameraStatusText.text = $"Added {_scannedCard.name} to collection",
                err => ShowError($"Add to collection failed:\n{err}"));
        }

        private void OnAddToDeck()
        {
            if (_scannedCard == null) return;
            PlayerPrefs.SetString("PendingAddCard", JsonConvert.SerializeObject(_scannedCard));
            PlayerPrefs.Save();
            SceneManager.LoadScene("DeckBuilder");
        }

        private void OnBack()
        {
            if (_webcam != null && _webcam.isPlaying) _webcam.Stop();
            SceneManager.LoadScene("MainMenu");
        }

        private void ShowError(string msg)
        {
            errorText.text = msg;
            errorPanel.SetActive(true);
            Debug.LogWarning($"[ScannerController] {msg}");
        }

        [Serializable]
        private class ScanResult
        {
            public CardModel card;
            public float confidence;
        }
    }
}
