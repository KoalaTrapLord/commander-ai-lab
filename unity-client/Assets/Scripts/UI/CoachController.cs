using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using UnityEngine.Networking;
using TMPro;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Coach scene — AI chat + analytics charts.
    /// Chat bubble UI, deck selector, "Ask Coach" button,
    /// deck analytics panel (mana curve, color distribution, card types),
    /// streaming token-by-token response display,
    /// "Export to Simulator" button, precon refresh tab,
    /// mobile-responsive layout (fullscreen chat / swipe analytics).
    /// </summary>
    public class CoachController : MonoBehaviour
    {
        [Header("Navigation")]
        [SerializeField] private Button backButton;

        [Header("Deck Selector")]
        [SerializeField] private TMP_Dropdown deckDropdown;
        [SerializeField] private Button refreshDecksButton;

        [Header("Chat UI")]
        [SerializeField] private ScrollRect chatScrollRect;
        [SerializeField] private Transform chatContent;
        [SerializeField] private GameObject userBubblePrefab;
        [SerializeField] private GameObject coachBubblePrefab;
        [SerializeField] private TMP_InputField chatInput;
        [SerializeField] private Button sendButton;
        [SerializeField] private Button askCoachButton;
        [SerializeField] private TMP_Text typingIndicator;

        [Header("Analytics Panel")]
        [SerializeField] private GameObject analyticsPanel;
        [SerializeField] private TMP_Text manaCurveText;
        [SerializeField] private TMP_Text colorDistText;
        [SerializeField] private TMP_Text cardTypeText;
        [SerializeField] private TMP_Text avgCmcText;
        [SerializeField] private TMP_Text landCountText;

        [Header("Mana Curve Chart")]
        [SerializeField] private RectTransform manaCurveChartRect;

        [Header("Actions")]
        [SerializeField] private Button exportToSimButton;

        [Header("Precon Refresh")]
        [SerializeField] private GameObject preconPanel;
        [SerializeField] private TMP_Text preconCompareText;
        [SerializeField] private Button preconRefreshButton;
        [SerializeField] private TMP_Dropdown preconDropdown;

        [Header("Mobile Layout")]
        [SerializeField] private GameObject chatFullscreenPanel;
        [SerializeField] private GameObject analyticsSwipePanel;
        [SerializeField] private Button toggleViewButton;
        [SerializeField] private TMP_Text toggleViewLabel;

        [Header("Error")]
        [SerializeField] private GameObject errorPanel;
        [SerializeField] private TMP_Text errorText;

        private readonly List<DeckSummary> _decks = new();
        private readonly List<ChatMessage> _chatHistory = new();
        private readonly List<PreconEntry> _precons = new();
        private string _selectedDeckId;
        private bool _isWaiting = false;
        private bool _isMobile = false;
        private bool _showingChat = true;
        private GameObject _streamingBubble;
        private TMP_Text _streamingText;
        private StringBuilder _streamingBuffer = new();

        private void Start()
        {
            backButton.onClick.AddListener(OnBack);
            sendButton.onClick.AddListener(OnSend);
            askCoachButton.onClick.AddListener(OnAskCoach);
            refreshDecksButton.onClick.AddListener(LoadDecks);
            exportToSimButton.onClick.AddListener(OnExportToSim);
            deckDropdown.onValueChanged.AddListener(OnDeckSelected);
            preconRefreshButton.onClick.AddListener(OnPreconRefresh);
            preconDropdown.onValueChanged.AddListener(OnPreconSelected);
            if (toggleViewButton != null)
                toggleViewButton.onClick.AddListener(ToggleMobileView);

            chatInput.onSubmit.AddListener(_ => OnSend());
            errorPanel.SetActive(false);
            typingIndicator.gameObject.SetActive(false);
            if (preconPanel != null) preconPanel.SetActive(false);

            DetectMobileLayout();
            LoadDecks();
            LoadPrecons();
            AddCoachBubble("Hello! Select a deck and ask me anything about your strategy.");
        }

        // ── Mobile Layout ────────────────────────────────────────────
        private void DetectMobileLayout()
        {
            _isMobile = (Screen.width < 800 || Application.isMobilePlatform);
            if (_isMobile)
            {
                if (chatFullscreenPanel != null) chatFullscreenPanel.SetActive(true);
                if (analyticsSwipePanel != null) analyticsSwipePanel.SetActive(false);
                if (toggleViewButton != null) toggleViewButton.gameObject.SetActive(true);
                if (toggleViewLabel != null) toggleViewLabel.text = "Analytics";
                _showingChat = true;
            }
            else
            {
                if (chatFullscreenPanel != null) chatFullscreenPanel.SetActive(true);
                if (analyticsSwipePanel != null) analyticsSwipePanel.SetActive(true);
                if (toggleViewButton != null) toggleViewButton.gameObject.SetActive(false);
            }
        }

        private void ToggleMobileView()
        {
            _showingChat = !_showingChat;
            if (chatFullscreenPanel != null) chatFullscreenPanel.SetActive(_showingChat);
            if (analyticsSwipePanel != null) analyticsSwipePanel.SetActive(!_showingChat);
            if (toggleViewLabel != null)
                toggleViewLabel.text = _showingChat ? "Analytics" : "Chat";
        }

        // ── Deck Loading ────────────────────────────────────────────
        private void LoadDecks()
        {
            ApiClient.Instance.GetRaw("/api/decks",
                json =>
                {
                    try
                    {
                        _decks.Clear();
                        var decks = JsonConvert.DeserializeObject<List<DeckSummary>>(json);
                        deckDropdown.ClearOptions();
                        var opts = new List<string> { "-- Select Deck --" };
                        foreach (var d in decks)
                        {
                            _decks.Add(d);
                            opts.Add(d.name);
                        }
                        deckDropdown.AddOptions(opts);
                    }
                    catch (Exception e) { ShowError($"Deck load error: {e.Message}"); }
                },
                err => ShowError($"Failed to load decks: {err}"));
        }

        private void OnDeckSelected(int index)
        {
            if (index <= 0 || index > _decks.Count)
            {
                _selectedDeckId = null;
                analyticsPanel.SetActive(false);
                if (preconPanel != null) preconPanel.SetActive(false);
                return;
            }
            _selectedDeckId = _decks[index - 1].id;
            LoadDeckAnalytics(_selectedDeckId);
        }

        // ── Analytics ───────────────────────────────────────────────
        private void LoadDeckAnalytics(string deckId)
        {
            ApiClient.Instance.GetRaw($"/api/decks/{deckId}",
                json =>
                {
                    try
                    {
                        var deck = JsonConvert.DeserializeObject<DeckDetail>(json);
                        analyticsPanel.SetActive(true);
                        avgCmcText.text = $"Avg CMC: {deck.avg_cmc:F2}";
                        landCountText.text = $"Lands: {deck.land_count}/100";
                        manaCurveText.text = FormatManaCurve(deck.mana_curve);
                        colorDistText.text = FormatColorDist(deck.color_distribution);
                        cardTypeText.text = FormatCardTypes(deck.card_types);
                        RenderManaCurveChart(deck.mana_curve);
                    }
                    catch (Exception e) { ShowError($"Analytics error: {e.Message}"); }
                },
                err => ShowError($"Analytics load failed: {err}"));
        }

        private string FormatManaCurve(Dictionary<string, int> curve)
        {
            if (curve == null) return "";
            var parts = new List<string>();
            for (int i = 0; i <= 7; i++)
            {
                string key = i == 7 ? "7+" : i.ToString();
                curve.TryGetValue(key, out int count);
                parts.Add($"{key}:{count}");
            }
            return string.Join(" | ", parts);
        }

        private string FormatColorDist(Dictionary<string, int> colors)
        {
            if (colors == null) return "";
            var parts = new List<string>();
            foreach (var kvp in colors) parts.Add($"{kvp.Key}:{kvp.Value}");
            return string.Join(" ", parts);
        }

        private string FormatCardTypes(Dictionary<string, int> types)
        {
            if (types == null) return "";
            var parts = new List<string>();
            foreach (var kvp in types) parts.Add($"{kvp.Key}: {kvp.Value}");
            return string.Join(", ", parts);
        }

        private void RenderManaCurveChart(Dictionary<string, int> curve)
        {
            foreach (Transform t in manaCurveChartRect) Destroy(t.gameObject);
            if (curve == null) return;
            int max = 1;
            foreach (var v in curve.Values) if (v > max) max = v;
            float w = manaCurveChartRect.rect.width;
            float h = manaCurveChartRect.rect.height;
            int barCount = 8;
            float barW = w / barCount * 0.7f;
            float gap = w / barCount;
            for (int i = 0; i <= 7; i++)
            {
                string key = i == 7 ? "7+" : i.ToString();
                curve.TryGetValue(key, out int count);
                float barH = (float)count / max * h * 0.85f;
                var bar = new GameObject($"Bar_{key}");
                bar.transform.SetParent(manaCurveChartRect, false);
                var img = bar.AddComponent<Image>();
                img.color = new Color(0.3f, 0.5f, 0.9f);
                var rt = bar.GetComponent<RectTransform>();
                rt.pivot = new Vector2(0.5f, 0f);
                rt.sizeDelta = new Vector2(barW, barH);
                rt.anchoredPosition = new Vector2(i * gap - w * 0.5f + gap * 0.5f, -h * 0.5f);
            }
        }

        // ── Chat (Streaming) ─────────────────────────────────────────
        private void OnSend()
        {
            string msg = chatInput.text.Trim();
            if (string.IsNullOrEmpty(msg) || _isWaiting) return;
            chatInput.text = "";
            AddUserBubble(msg);
            SendToCoachStreaming(msg);
        }

        private void OnAskCoach()
        {
            if (_selectedDeckId == null)
            {
                AddCoachBubble("Please select a deck first.");
                return;
            }
            string msg = "Analyze my deck and suggest improvements.";
            AddUserBubble(msg);
            SendToCoachStreaming(msg);
        }

        private void SendToCoachStreaming(string userMessage)
        {
            _isWaiting = true;
            sendButton.interactable = false;
            typingIndicator.gameObject.SetActive(true);
            typingIndicator.text = "Coach is thinking...";

            _chatHistory.Add(new ChatMessage { role = "user", content = userMessage });

            var messages = new List<object>();
            foreach (var m in _chatHistory)
                messages.Add(new { role = m.role, content = m.content });

            var payload = new {
                deck_id = _selectedDeckId ?? "",
                messages = messages,
                stream = true
            };
            string body = JsonConvert.SerializeObject(payload);

            // Create streaming bubble
            _streamingBuffer.Clear();
            _streamingBubble = Instantiate(coachBubblePrefab, chatContent);
            _streamingText = _streamingBubble.GetComponentInChildren<TMP_Text>();
            if (_streamingText != null) _streamingText.text = "";
            ScrollToBottom();

            StartCoroutine(StreamChatResponse(body));
        }

        private IEnumerator StreamChatResponse(string jsonBody)
        {
            string url = ApiClient.Instance.BaseUrl + "/api/coach/chat";
            byte[] bodyBytes = Encoding.UTF8.GetBytes(jsonBody);

            using var request = new UnityWebRequest(url, "POST");
            request.uploadHandler = new UploadHandlerRaw(bodyBytes);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.SetRequestHeader("Accept", "text/event-stream");

            var op = request.SendWebRequest();
            int lastProcessed = 0;

            while (!op.isDone)
            {
                string partial = request.downloadHandler?.text ?? "";
                if (partial.Length > lastProcessed)
                {
                    ProcessSSEChunk(partial.Substring(lastProcessed));
                    lastProcessed = partial.Length;
                }
                yield return null;
            }

            // Process remaining data
            string final_ = request.downloadHandler?.text ?? "";
            if (final_.Length > lastProcessed)
                ProcessSSEChunk(final_.Substring(lastProcessed));

            if (request.result != UnityWebRequest.Result.Success)
            {
                if (_streamingBuffer.Length == 0)
                {
                    // Fallback: try non-streaming
                    Destroy(_streamingBubble);
                    SendToCoachFallback(_chatHistory[_chatHistory.Count - 1].content);
                    yield break;
                }
            }

            // Finalize streaming
            string fullReply = _streamingBuffer.ToString();
            if (!string.IsNullOrEmpty(fullReply))
                _chatHistory.Add(new ChatMessage { role = "assistant", content = fullReply });

            _isWaiting = false;
            sendButton.interactable = true;
            typingIndicator.gameObject.SetActive(false);
            _streamingBubble = null;
            _streamingText = null;
        }

        private void ProcessSSEChunk(string chunk)
        {
            var lines = chunk.Split('\n');
            foreach (var line in lines)
            {
                var trimmed = line.Trim();
                if (!trimmed.StartsWith("data: ")) continue;
                var data = trimmed.Substring(6);
                if (data == "[DONE]") continue;
                try
                {
                    var obj = JObject.Parse(data);
                    string content = obj["content"]?.ToString() ?? "";
                    if (!string.IsNullOrEmpty(content))
                    {
                        _streamingBuffer.Append(content);
                        if (_streamingText != null)
                            _streamingText.text = _streamingBuffer.ToString();
                        typingIndicator.gameObject.SetActive(false);
                        ScrollToBottom();
                    }
                }
                catch (JsonException) { }
            }
        }

        // ── Non-streaming fallback ───────────────────────────────────
        private void SendToCoachFallback(string userMessage)
        {
            var messages = new List<object>();
            foreach (var m in _chatHistory)
                messages.Add(new { role = m.role, content = m.content });

            var payload = new {
                deck_id = _selectedDeckId ?? "",
                messages = messages,
                stream = false
            };
            string body = JsonConvert.SerializeObject(payload);

            StartCoroutine(ApiClient.Instance.PostRaw("/api/coach/chat", body,
                json =>
                {
                    _isWaiting = false;
                    sendButton.interactable = true;
                    typingIndicator.gameObject.SetActive(false);
                    try
                    {
                        var obj = JObject.Parse(json);
                        string reply = obj["content"]?.ToString() ?? "";
                        _chatHistory.Add(new ChatMessage { role = "assistant", content = reply });
                        AddCoachBubble(reply);
                    }
                    catch (Exception e) { ShowError($"Chat parse error: {e.Message}"); }
                },
                err =>
                {
                    _isWaiting = false;
                    sendButton.interactable = true;
                    typingIndicator.gameObject.SetActive(false);
                    ShowError($"Chat failed: {err}");
                }));
        }

        private void AddUserBubble(string text)
        {
            var bubble = Instantiate(userBubblePrefab, chatContent);
            var tmp = bubble.GetComponentInChildren<TMP_Text>();
            if (tmp) tmp.text = text;
            ScrollToBottom();
        }

        private void AddCoachBubble(string text)
        {
            var bubble = Instantiate(coachBubblePrefab, chatContent);
            var tmp = bubble.GetComponentInChildren<TMP_Text>();
            if (tmp) tmp.text = text;
            ScrollToBottom();
        }

        private void ScrollToBottom()
        {
            Canvas.ForceUpdateCanvases();
            chatScrollRect.verticalNormalizedPosition = 0f;
        }

        // ── Precon Refresh ───────────────────────────────────────────
        private void LoadPrecons()
        {
            ApiClient.Instance.GetRaw("/api/lab/precons",
                json =>
                {
                    try
                    {
                        var result = JObject.Parse(json);
                        var preconArray = result["precons"] as JArray;
                        _precons.Clear();
                        preconDropdown.ClearOptions();
                        var opts = new List<string> { "-- Compare to Precon --" };
                        if (preconArray != null)
                        {
                            foreach (var p in preconArray)
                            {
                                var entry = new PreconEntry
                                {
                                    fileName = p["fileName"]?.ToString() ?? "",
                                    name = p["name"]?.ToString() ?? p["fileName"]?.ToString() ?? "",
                                    commander = p["commander"]?.ToString() ?? ""
                                };
                                _precons.Add(entry);
                                opts.Add(entry.name);
                            }
                        }
                        preconDropdown.AddOptions(opts);
                    }
                    catch (Exception e) { Debug.LogWarning($"Precon load: {e.Message}"); }
                },
                err => Debug.LogWarning($"Precon load failed: {err}"));
        }

        private void OnPreconSelected(int index)
        {
            if (index <= 0 || index > _precons.Count || _selectedDeckId == null)
            {
                if (preconPanel != null) preconPanel.SetActive(false);
                return;
            }
            var precon = _precons[index - 1];
            CompareToPrecon(precon);
        }

        private void CompareToPrecon(PreconEntry precon)
        {
            if (preconPanel != null) preconPanel.SetActive(true);
            if (preconCompareText != null)
                preconCompareText.text = $"Comparing to: {precon.name}\nCommander: {precon.commander}\nLoading comparison...";

            // Load deck report for comparison
            ApiClient.Instance.GetRaw($"/api/coach/decks/{_selectedDeckId}/report",
                json =>
                {
                    try
                    {
                        var report = JObject.Parse(json);
                        var structure = report["structure"];
                        int landCount = structure?["landCount"]?.Value<int>() ?? 0;
                        var buckets = structure?["curveBuckets"];
                        string curveStr = buckets != null ? string.Join(", ", buckets) : "N/A";

                        if (preconCompareText != null)
                            preconCompareText.text =
                                $"Precon Baseline: {precon.name}\n" +
                                $"Commander: {precon.commander}\n" +
                                $"\nYour Deck Analysis:\n" +
                                $"  Lands: {landCount}\n" +
                                $"  Curve: [{curveStr}]\n" +
                                $"\nSelect a precon above to compare structure.";
                    }
                    catch
                    {
                        if (preconCompareText != null)
                            preconCompareText.text = $"Precon: {precon.name}\nDeck report not available. Run a coaching session first.";
                    }
                },
                err =>
                {
                    if (preconCompareText != null)
                        preconCompareText.text = $"Precon: {precon.name}\nCould not load deck report: {err}";
                });
        }

        private void OnPreconRefresh()
        {
            if (preconCompareText != null)
                preconCompareText.text = "Refreshing precon database...";

            string body = JsonConvert.SerializeObject(new { });
            StartCoroutine(ApiClient.Instance.PostRaw("/api/lab/precons/refresh", body,
                json =>
                {
                    if (preconCompareText != null)
                        preconCompareText.text = "Precon database refreshed!";
                    LoadPrecons();
                },
                err => ShowError($"Precon refresh failed: {err}")));
        }

        // ── Export to Simulator ───────────────────────────────────────
        private void OnExportToSim()
        {
            if (_selectedDeckId == null)
            {
                AddCoachBubble("Select a deck before exporting to simulator.");
                return;
            }
            PlayerPrefs.SetString("SimDeckId", _selectedDeckId);
            PlayerPrefs.Save();
            SceneManager.LoadScene("Simulator");
        }

        private void OnBack()
        {
            SceneManager.LoadScene("MainMenu");
        }

        private void ShowError(string msg)
        {
            errorText.text = msg;
            errorPanel.SetActive(true);
            Debug.LogWarning($"[CoachController] {msg}");
        }

        // ── Data Models ──────────────────────────────────────────────
        [Serializable]
        private class DeckSummary
        {
            public string id;
            public string name;
            public string commander;
        }

        [Serializable]
        private class DeckDetail
        {
            public float avg_cmc;
            public int land_count;
            public Dictionary<string, int> mana_curve;
            public Dictionary<string, int> color_distribution;
            public Dictionary<string, int> card_types;
        }

        [Serializable]
        private class ChatMessage
        {
            public string role;
            public string content;
        }

        [Serializable]
        private class PreconEntry
        {
            public string fileName;
            public string name;
            public string commander;
        }
    }
}
