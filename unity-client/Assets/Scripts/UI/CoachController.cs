using System;
using System.Collections;
using System.Collections.Generic;
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
    /// Coach scene — AI chat + analytics charts.
    /// Chat bubble UI, deck selector, "Ask Coach" button,
    /// deck analytics panel (mana curve, color distribution, card types),
    /// "Export to Simulator" button, precon refresh tab.
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

        [Header("Error")]
        [SerializeField] private GameObject errorPanel;
        [SerializeField] private TMP_Text errorText;

        private readonly List<DeckSummary> _decks = new();
        private readonly List<ChatMessage> _chatHistory = new();
        private string _selectedDeckId;
        private bool _isWaiting = false;

        private void Start()
        {
            backButton.onClick.AddListener(OnBack);
            sendButton.onClick.AddListener(OnSend);
            askCoachButton.onClick.AddListener(OnAskCoach);
            refreshDecksButton.onClick.AddListener(LoadDecks);
            exportToSimButton.onClick.AddListener(OnExportToSim);
            deckDropdown.onValueChanged.AddListener(OnDeckSelected);

            chatInput.onSubmit.AddListener(_ => OnSend());
            errorPanel.SetActive(false);
            typingIndicator.gameObject.SetActive(false);

            LoadDecks();
            AddCoachBubble("Hello! Select a deck and ask me anything about your strategy.");
        }

        // ── Deck Loading ───────────────────────────────────────────────
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
                return;
            }
            _selectedDeckId = _decks[index - 1].id;
            LoadDeckAnalytics(_selectedDeckId);
        }

        // ── Analytics ─────────────────────────────────────────────────
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

        // ── Chat ────────────────────────────────────────────────────────
        private void OnSend()
        {
            string msg = chatInput.text.Trim();
            if (string.IsNullOrEmpty(msg) || _isWaiting) return;
            chatInput.text = "";
            AddUserBubble(msg);
            SendToCoach(msg);
        }

        private void OnAskCoach()
        {
            if (_selectedDeckId == null)
            {
                AddCoachBubble("Please select a deck first.");
                return;
            }
            string msg = $"Analyze my deck and suggest improvements.";
            AddUserBubble(msg);
            SendToCoach(msg);
        }

        private void SendToCoach(string userMessage)
        {
            _isWaiting = true;
            sendButton.interactable = false;
            typingIndicator.gameObject.SetActive(true);
            typingIndicator.text = "Coach is thinking...";

            var payload = new ChatRequest
            {
                message = userMessage,
                deck_id = _selectedDeckId,
                history = _chatHistory
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
                        var resp = JsonConvert.DeserializeObject<ChatResponse>(json);
                        _chatHistory.Add(new ChatMessage { role = "user", content = userMessage });
                        _chatHistory.Add(new ChatMessage { role = "assistant", content = resp.reply });
                        AddCoachBubble(resp.reply);
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

        // ── Data Models ───────────────────────────────────────────────
        [Serializable] private class DeckSummary
        {
            public string id;
            public string name;
            public string commander;
        }

        [Serializable] private class DeckDetail
        {
            public float avg_cmc;
            public int land_count;
            public Dictionary<string, int> mana_curve;
            public Dictionary<string, int> color_distribution;
            public Dictionary<string, int> card_types;
        }

        [Serializable] private class ChatMessage
        {
            public string role;
            public string content;
        }

        [Serializable] private class ChatRequest
        {
            public string message;
            public string deck_id;
            public List<ChatMessage> history;
        }

        [Serializable] private class ChatResponse
        {
            public string reply;
        }
    }
}
