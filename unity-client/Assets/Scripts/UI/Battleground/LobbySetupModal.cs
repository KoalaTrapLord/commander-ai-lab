using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using TMPro;
using Newtonsoft.Json;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Modal shown at Battleground scene start.
    /// Configures 4 seats (Human vs AI, deck choice, AI style).
    /// On Confirm writes seat config to PlayerPrefs["BattleSeats"] and starts the game.
    /// </summary>
    public class LobbySetupModal : MonoBehaviour
    {
        [Header("Seat Rows (4)")]
        [SerializeField] private LobbyRowUI[] seatRows;   // length 4

        [Header("Buttons")]
        [SerializeField] private Button confirmButton;
        [SerializeField] private Button cancelButton;

        [SerializeField] private ApiClient apiClient;

        private List<string> _deckNames = new();

        // ── Open ────────────────────────────────────────────────
        public void Open(string savedSeatsJson)
        {
            gameObject.SetActive(true);
            confirmButton.onClick.AddListener(OnConfirm);
            cancelButton.onClick.AddListener(() => SceneManager.LoadScene("MainMenu"));

            // Load deck list for dropdowns
            apiClient?.GetDecks(
                json =>
                {
                    try
                    {
                        var w = JsonConvert.DeserializeObject<DecksWrapper>(json);
                        _deckNames = new List<string>();
                        if (w?.decks != null)
                            foreach (var d in w.decks) _deckNames.Add(d.name);
                    }
                    catch { _deckNames = new List<string>(); }
                    PopulateRows(savedSeatsJson);
                },
                _ => PopulateRows(savedSeatsJson));
        }

        private void PopulateRows(string savedJson)
        {
            List<SeatConfig> saved = null;
            try { saved = JsonConvert.DeserializeObject<List<SeatConfig>>(savedJson); } catch { }

            for (int i = 0; i < seatRows.Length; i++)
            {
                if (seatRows[i] == null) continue;
                var cfg = (saved != null && i < saved.Count) ? saved[i] : null;
                seatRows[i].Populate(i, _deckNames, cfg);
            }
        }

        // ── Confirm ─────────────────────────────────────────────
        private void OnConfirm()
        {
            var configs = new List<SeatConfig>();
            foreach (var row in seatRows)
                configs.Add(row?.GetConfig() ?? new SeatConfig());

            PlayerPrefs.SetString("BattleSeats", JsonConvert.SerializeObject(configs));
            PlayerPrefs.Save();
            gameObject.SetActive(false);
        }

        // ── Models ─────────────────────────────────────────────
        [Serializable]
        public class SeatConfig
        {
            public bool   isHuman;
            public string deckName;
            public string aiStyle;   // Aggro / Control / Combo / Political
        }

        [Serializable] private class DecksWrapper { public List<DeckEntry> decks; }
        [Serializable] private class DeckEntry { public string name; }
    }

    /// <summary>Per-seat row in the lobby modal (UI bindings are set in inspector).</summary>
    [Serializable]
    public class LobbyRowUI : MonoBehaviour
    {
        [SerializeField] private TMP_Text     seatLabel;
        [SerializeField] private Toggle       humanToggle;
        [SerializeField] private TMP_Dropdown deckDropdown;
        [SerializeField] private TMP_Dropdown aiStyleDropdown;

        private static readonly List<string> AiStyles = new() { "Aggro", "Control", "Combo", "Political" };

        public void Populate(int seatIndex, List<string> deckNames, LobbySetupModal.SeatConfig saved)
        {
            if (seatLabel) seatLabel.text = seatIndex == 0 ? "Seat 0 (You)" : $"Seat {seatIndex} (AI)";

            if (humanToggle)
            {
                humanToggle.isOn = saved?.isHuman ?? (seatIndex == 0);
                humanToggle.onValueChanged.AddListener(isHuman =>
                {
                    if (aiStyleDropdown) aiStyleDropdown.gameObject.SetActive(!isHuman);
                });
                if (aiStyleDropdown) aiStyleDropdown.gameObject.SetActive(!humanToggle.isOn);
            }

            if (deckDropdown)
            {
                deckDropdown.ClearOptions();
                var opts = new List<string> { "-- Select Deck --" };
                opts.AddRange(deckNames);
                deckDropdown.AddOptions(opts);
                if (!string.IsNullOrEmpty(saved?.deckName))
                {
                    int idx = opts.IndexOf(saved.deckName);
                    deckDropdown.value = idx >= 0 ? idx : 0;
                }
            }

            if (aiStyleDropdown)
            {
                aiStyleDropdown.ClearOptions();
                aiStyleDropdown.AddOptions(AiStyles);
                if (!string.IsNullOrEmpty(saved?.aiStyle))
                {
                    int idx = AiStyles.IndexOf(saved.aiStyle);
                    aiStyleDropdown.value = idx >= 0 ? idx : 0;
                }
            }
        }

        public LobbySetupModal.SeatConfig GetConfig() => new()
        {
            isHuman  = humanToggle?.isOn ?? false,
            deckName = deckDropdown != null && deckDropdown.value > 0
                       ? deckDropdown.options[deckDropdown.value].text : "",
            aiStyle  = aiStyleDropdown != null
                       ? aiStyleDropdown.options[aiStyleDropdown.value].text : "Aggro"
        };
    }
}
