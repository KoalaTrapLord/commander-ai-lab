using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
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
    /// Simulator scene — configure and run multi-player simulations,
    /// poll status, display results per deck.
    /// </summary>
    public class SimulationController : MonoBehaviour
    {
        // ── Navigation ───────────────────────────────────────────────────────
        [Header("Navigation")]
        [SerializeField] private Button backButton;
        [SerializeField] private Button startSimButton;

        // ── Config Panel ──────────────────────────────────────────────────────
        [Header("Config")]
        [SerializeField] private TMP_Dropdown deckDropdown0;
        [SerializeField] private TMP_Dropdown deckDropdown1;
        [SerializeField] private TMP_Dropdown deckDropdown2;
        [SerializeField] private TMP_Dropdown deckDropdown3;
        [SerializeField] private TMP_InputField numGamesInput;
        [SerializeField] private Slider numPlayersSlider;
        [SerializeField] private TMP_Text numPlayersLabel;
        [SerializeField] private TMP_InputField threadsInput;
        [SerializeField] private TMP_Dropdown aiProfileDropdown;

        // ── Status Panel ──────────────────────────────────────────────────────
        [Header("Status")]
        [SerializeField] private TMP_Text statusText;
        [SerializeField] private Slider progressBar;
        [SerializeField] private TMP_Text progressText;
        [SerializeField] private TMP_Text elapsedText;
        [SerializeField] private TMP_Text simsPerSecText;

        // ── Results Panel ─────────────────────────────────────────────────────
        [Header("Results")]
        [SerializeField] private Transform resultsParent;
        [SerializeField] private GameObject resultRowPrefab;
        [SerializeField] private TMP_Text winnerText;
        [SerializeField] private Button historyButton;

        // ── Error ─────────────────────────────────────────────────────────────
        [Header("Error")]
        [SerializeField] private GameObject errorPanel;
        [SerializeField] private TMP_Text errorText;
        [SerializeField] private Button retryButton;

        // ── State ─────────────────────────────────────────────────────────────
        private ApiClient _api;
        private List<LabDeckEntry> _decks = new();
        private List<AiProfile> _profiles = new();
        private string _currentBatchId;
        private bool _isPolling;

        private readonly List<GameObject> _resultRowObjects = new();

        // ── Lifecycle ─────────────────────────────────────────────────────────
        private void Start()
        {
            _api = FindObjectOfType<ApiClient>();

            backButton.onClick.AddListener(() => SceneManager.LoadScene("MainMenu"));
            startSimButton.onClick.AddListener(OnStartSim);
            retryButton.onClick.AddListener(OnStartSim);

            numPlayersSlider.minValue = 2;
            numPlayersSlider.maxValue = 4;
            numPlayersSlider.wholeNumbers = true;
            numPlayersSlider.value = 2;
            numPlayersSlider.onValueChanged.AddListener(OnNumPlayersChanged);
            OnNumPlayersChanged(numPlayersSlider.value);

            errorPanel.SetActive(false);

            // Check for a deck exported from DeckBuilder
            string simDeck = PlayerPrefs.GetString("SimDeck", "");
            if (!string.IsNullOrEmpty(simDeck))
            {
                PlayerPrefs.DeleteKey("SimDeck");
                // Pre-populate deck dropdown 0 after decks load — stored for later
                PlayerPrefs.SetString("_SimDeckPending", simDeck);
            }

            LoadDecks();
            LoadAiProfiles();
        }

        // ── Player Count ──────────────────────────────────────────────────────
        private void OnNumPlayersChanged(float value)
        {
            int count = Mathf.RoundToInt(value);
            if (numPlayersLabel != null)
                numPlayersLabel.text = $"Players: {count}";

            // Show/hide optional deck dropdowns based on count
            if (deckDropdown2 != null) deckDropdown2.gameObject.SetActive(count >= 3);
            if (deckDropdown3 != null) deckDropdown3.gameObject.SetActive(count >= 4);
        }

        // ── Deck List ─────────────────────────────────────────────────────────
        private void LoadDecks()
        {
            _api.GetDecks(
                json =>
                {
                    try
                    {
                        var wrapper = JsonConvert.DeserializeObject<DecksWrapper>(json);
                        _decks = wrapper?.decks ?? new List<LabDeckEntry>();
                    }
                    catch { _decks = new List<LabDeckEntry>(); }
                    PopulateDeckDropdowns();
                },
                err => ShowError($"Failed to load decks:\n{err}"));
        }

        private void PopulateDeckDropdowns()
        {
            var options = new List<string> { "-- Select Deck --" };
            foreach (var d in _decks) options.Add(d.name);

            void Fill(TMP_Dropdown dd)
            {
                if (dd == null) return;
                dd.ClearOptions();
                dd.AddOptions(options);
                dd.value = 0;
            }

            Fill(deckDropdown0);
            Fill(deckDropdown1);
            Fill(deckDropdown2);
            Fill(deckDropdown3);

            // Apply any pending deck from DeckBuilder export
            string pending = PlayerPrefs.GetString("_SimDeckPending", "");
            if (!string.IsNullOrEmpty(pending))
            {
                PlayerPrefs.DeleteKey("_SimDeckPending");
                try
                {
                    // Try to match by name from the JSON
                    var exported = JsonConvert.DeserializeObject<LabDeckEntry>(pending);
                    if (exported != null && !string.IsNullOrEmpty(exported.name))
                    {
                        int idx = options.IndexOf(exported.name);
                        if (idx >= 0 && deckDropdown0 != null)
                            deckDropdown0.value = idx;
                    }
                }
                catch { }
            }
        }

        // ── AI Profiles ───────────────────────────────────────────────────────
        private void LoadAiProfiles()
        {
            _api.GetProfiles(
                json =>
                {
                    try
                    {
                        var wrapper = JsonConvert.DeserializeObject<ProfilesWrapper>(json);
                        _profiles = wrapper?.profiles ?? new List<AiProfile>();
                    }
                    catch { _profiles = new List<AiProfile>(); }
                    PopulateProfileDropdown();
                },
                err =>
                {
                    // Non-fatal: profiles may not be available yet
                    _profiles = new List<AiProfile>();
                    PopulateProfileDropdown();
                });
        }

        private void PopulateProfileDropdown()
        {
            if (aiProfileDropdown == null) return;
            aiProfileDropdown.ClearOptions();
            var options = new List<string>();
            foreach (var p in _profiles) options.Add(p.name);
            if (options.Count == 0) options.Add("Default");
            aiProfileDropdown.AddOptions(options);
            aiProfileDropdown.value = 0;
        }

        // ── Start Simulation ──────────────────────────────────────────────────
        private void OnStartSim()
        {
            errorPanel.SetActive(false);

            int numPlayers = Mathf.RoundToInt(numPlayersSlider.value);

            // Collect selected deck names (index 0 = "-- Select Deck --")
            var selectedDecks = new List<string>();
            void TryAdd(TMP_Dropdown dd)
            {
                if (dd == null || !dd.gameObject.activeSelf) return;
                if (dd.value <= 0) return;
                int deckIdx = dd.value - 1;
                if (deckIdx < _decks.Count)
                    selectedDecks.Add(_decks[deckIdx].name);
            }

            TryAdd(deckDropdown0);
            TryAdd(deckDropdown1);
            TryAdd(deckDropdown2);
            TryAdd(deckDropdown3);

            if (selectedDecks.Count < 2)
            {
                ShowError("Please select at least 2 decks to simulate.");
                return;
            }
            if (selectedDecks.Count < numPlayers)
            {
                ShowError($"Please select {numPlayers} decks for {numPlayers}-player simulation.");
                return;
            }

            if (!int.TryParse(numGamesInput.text, out int numGames) || numGames <= 0)
                numGames = 100;

            if (!int.TryParse(threadsInput.text, out int threads) || threads <= 0)
                threads = 4;

            string policyStyle = aiProfileDropdown != null && _profiles.Count > 0
                ? _profiles[Mathf.Clamp(aiProfileDropdown.value, 0, _profiles.Count - 1)].name
                : "Default";

            var request = new StartRequest
            {
                decks = selectedDecks,
                numGames = numGames,
                threads = threads,
                useLearnedPolicy = false,
                policyStyle = policyStyle,
                seed = 0,
                clock = 0
            };

            string json = JsonConvert.SerializeObject(request);

            SetStatusPanelVisible(true);
            SetResultsPanelVisible(false);
            if (statusText) statusText.text = "Starting simulation...";
            if (progressBar) progressBar.value = 0f;
            if (progressText) progressText.text = "0%";
            startSimButton.interactable = false;

            _api.StartSim(json,
                respJson =>
                {
                    SimStartResponse resp;
                    try { resp = JsonConvert.DeserializeObject<SimStartResponse>(respJson); }
                    catch { ShowError("Failed to parse start response."); startSimButton.interactable = true; return; }

                    if (resp == null || string.IsNullOrEmpty(resp.batchId))
                    {
                        ShowError("Invalid response from server.");
                        startSimButton.interactable = true;
                        return;
                    }

                    _currentBatchId = resp.batchId;
                    if (!_isPolling)
                        StartCoroutine(PollStatus(_currentBatchId));
                },
                err => { ShowError($"Failed to start simulation:\n{err}"); startSimButton.interactable = true; });
        }

        // ── Poll Status ───────────────────────────────────────────────────────
        private IEnumerator PollStatus(string batchId)
        {
            _isPolling = true;

            while (true)
            {
                yield return new WaitForSeconds(1.5f);

                bool done = false;
                string errorMsg = null;
                SimStatusModel latestStatus = null;

                _api.GetSimStatus(batchId,
                    json =>
                    {
                        try
                        {
                            var status = JsonConvert.DeserializeObject<SimStatusModel>(json);
                            if (status == null) { done = true; errorMsg = "Empty status response."; return; }
                            latestStatus = status;

                            if (!string.IsNullOrEmpty(status.error))
                            {
                                done = true;
                                errorMsg = status.error;
                                return;
                            }

                            int total = status.total > 0 ? status.total
                                      : status.totalGames > 0 ? status.totalGames : 1;
                            int completed = status.completed > 0 ? status.completed
                                          : status.gamesCompleted;

                            float progress = total > 0 ? (float)completed / total : 0f;
                            if (progressBar) progressBar.value = progress;
                            if (progressText) progressText.text = $"{Mathf.RoundToInt(progress * 100)}%";
                            if (statusText)   statusText.text = $"Running... {completed}/{total} games";
                            if (elapsedText)  elapsedText.text = $"Elapsed: {status.elapsedMs / 1000f:F1}s";
                            if (simsPerSecText) simsPerSecText.text = $"{status.simsPerSec:F1} sims/s";

                            if (!status.running) done = true;
                        }
                        catch (Exception ex)
                        {
                            done = true;
                            errorMsg = $"Status parse error: {ex.Message}";
                        }
                    },
                    err => { done = true; errorMsg = err; });

                // Wait one frame so callbacks have fired
                yield return null;

                if (!string.IsNullOrEmpty(errorMsg))
                {
                    ShowError($"Simulation error:\n{errorMsg}");
                    startSimButton.interactable = true;
                    _isPolling = false;
                    yield break;
                }

                if (done)
                {
                    if (statusText) statusText.text = "Simulation complete!";
                    if (progressBar) progressBar.value = 1f;
                    if (progressText) progressText.text = "100%";
                    startSimButton.interactable = true;
                    _isPolling = false;
                    LoadResults(batchId);
                    yield break;
                }
            }
        }

        // ── Load Results ──────────────────────────────────────────────────────
        private void LoadResults(string batchId)
        {
            _api.GetSimResults(batchId,
                json =>
                {
                    SimResult result;
                    try { result = JsonConvert.DeserializeObject<SimResult>(json); }
                    catch { ShowError("Failed to parse results."); return; }

                    if (result?.summary?.perDeck == null) { ShowError("No result data returned."); return; }

                    SetResultsPanelVisible(true);
                    BuildResultRows(result.summary.perDeck);
                },
                err => ShowError($"Failed to load results:\n{err}"));
        }

        private void BuildResultRows(List<ResultEntry> entries)
        {
            foreach (var go in _resultRowObjects) if (go) Destroy(go);
            _resultRowObjects.Clear();

            ResultEntry winner = null;
            foreach (var e in entries)
                if (winner == null || e.winRate > winner.winRate) winner = e;

            if (winnerText && winner != null)
                winnerText.text = $"Winner: {winner.deckName} ({winner.winRate * 100f:F1}% win rate)";

            foreach (var entry in entries)
            {
                var row = Instantiate(resultRowPrefab, resultsParent);
                row.SetActive(true);
                _resultRowObjects.Add(row);

                var labels = row.GetComponentsInChildren<TMP_Text>();
                if (labels.Length > 0) labels[0].text = entry.deckName;
                if (labels.Length > 1) labels[1].text = $"{entry.winRate * 100f:F1}%";
                if (labels.Length > 2) labels[2].text = $"W: {entry.wins}";
                if (labels.Length > 3) labels[3].text = $"L: {entry.losses}";
            }
        }

        // ── Panel Visibility ──────────────────────────────────────────────────
        private void SetStatusPanelVisible(bool visible)
        {
            if (statusText)     statusText.transform.parent?.gameObject.SetActive(visible);
            if (progressBar)    progressBar.gameObject.SetActive(visible);
            if (progressText)   progressText.gameObject.SetActive(visible);
            if (elapsedText)    elapsedText.gameObject.SetActive(visible);
            if (simsPerSecText) simsPerSecText.gameObject.SetActive(visible);
        }

        private void SetResultsPanelVisible(bool visible)
        {
            if (resultsParent)  resultsParent.gameObject.SetActive(visible);
            if (winnerText)     winnerText.gameObject.SetActive(visible);
            if (historyButton)  historyButton.gameObject.SetActive(visible);
        }

        // ── Error ─────────────────────────────────────────────────────────────
        private void ShowError(string msg)
        {
            errorPanel.SetActive(true);
            errorText.text = msg;
        }

        // ── Helper Models (private inner classes) ─────────────────────────────
        [Serializable] private class DecksWrapper { public List<LabDeckEntry> decks; }
        [Serializable] private class LabDeckEntry { public string name; public string source; public string commander; }
        [Serializable] private class ProfilesWrapper { public List<AiProfile> profiles; }
        [Serializable] private class AiProfile { public string name; public string description; }
        [Serializable] private class StartRequest
        {
            public List<string> decks; public int numGames; public int threads;
            public bool useLearnedPolicy; public string policyStyle;
            public int seed; public int clock;
        }
        [Serializable] private class SimResult { public Summary summary; }
        [Serializable] private class Summary { public List<ResultEntry> perDeck; }
        [Serializable] private class ResultEntry { public string deckName; public float winRate; public int wins; public int losses; }
    }
}
