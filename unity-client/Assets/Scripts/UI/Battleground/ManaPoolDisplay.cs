using System.Collections.Generic;
using UnityEngine;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Displays the mana pool for one seat as coloured symbol + count labels.
    /// Symbols are hidden when the mana amount is 0.
    /// Resets on each phase-change event from GameStateManager.
    /// </summary>
    public class ManaPoolDisplay : MonoBehaviour
    {
        [SerializeField] private int seatIndex;

        [Header("Mana Labels (W U B R G C order)")]
        [SerializeField] private TMP_Text[] manaLabels;      // length 6
        [SerializeField] private GameObject[] manaSymbols;   // parent GO per mana type (contains Image)

        private static readonly string[] ManaKeys = { "W", "U", "B", "R", "G", "C" };

        // ── Lifecycle ───────────────────────────────────────────
        private void Start()
        {
            if (GameStateManager.Instance != null)
            {
                GameStateManager.Instance.OnPhaseChanged  += OnPhaseChanged;
                GameStateManager.Instance.OnFullStateSync += OnFullStateSync;
            }
            UpdatePool(null);
        }

        private void OnDestroy()
        {
            if (GameStateManager.Instance == null) return;
            GameStateManager.Instance.OnPhaseChanged  -= OnPhaseChanged;
            GameStateManager.Instance.OnFullStateSync -= OnFullStateSync;
        }

        // ── Public API ─────────────────────────────────────────
        public void UpdatePool(Dictionary<string, int> pool)
        {
            for (int i = 0; i < ManaKeys.Length; i++)
            {
                int amt = 0;
                pool?.TryGetValue(ManaKeys[i], out amt);

                bool show = amt > 0;
                if (i < manaLabels.Length  && manaLabels[i]  != null)
                    manaLabels[i].text = show ? amt.ToString() : "";
                if (i < manaSymbols.Length && manaSymbols[i] != null)
                    manaSymbols[i].SetActive(show);
            }
        }

        // ── Event handlers ─────────────────────────────────────
        private void OnPhaseChanged(PhaseTrackerWidget.Phase phase, int seat, int turn)
        {
            // Mana pool empties at the end of each phase
            if (phase == PhaseTrackerWidget.Phase.Cleanup)
                UpdatePool(null);
        }

        private void OnFullStateSync(GameState state)
        {
            if (state?.seats == null || seatIndex >= state.seats.Count) return;
            UpdatePool(state.seats[seatIndex].manaPool);
        }
    }
}
