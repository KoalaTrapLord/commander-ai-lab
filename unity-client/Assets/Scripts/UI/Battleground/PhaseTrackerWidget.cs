using UnityEngine;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Horizontal strip of 13 phase/step buttons in the BattlefieldCenter panel.
    /// Subscribes to GameStateManager.OnPhaseChanged.
    /// Test without backend: press Space in Play Mode (debug binding below).
    /// </summary>
    public class PhaseTrackerWidget : MonoBehaviour
    {
        public enum Phase
        {
            Untap = 0,
            Upkeep,
            Draw,
            Main1,
            BeginCombat,
            DeclareAttackers,
            DeclareBlockers,
            FirstStrikeDamage,
            Damage,
            EndCombat,
            Main2,
            EndStep,
            Cleanup
        }

        [SerializeField] private PhaseStepButton[] stepButtons;    // 13 buttons, one per Phase
        [SerializeField] private TMP_Text          activePlayerLabel;
        [SerializeField] private TMP_Text          turnNumberLabel;

        private Phase _currentPhase;

        // ── Lifecycle ───────────────────────────────────────────
        private void Start()
        {
            if (GameStateManager.Instance != null)
                GameStateManager.Instance.OnPhaseChanged += SetPhase;

            SetPhase(Phase.Untap, 0, 1);
        }

        private void OnDestroy()
        {
            if (GameStateManager.Instance != null)
                GameStateManager.Instance.OnPhaseChanged -= SetPhase;
        }

        // ── Public API ─────────────────────────────────────────
        public void SetPhase(Phase phase, int seatIndex, int turnNumber)
        {
            _currentPhase = phase;

            for (int i = 0; i < stepButtons.Length; i++)
                stepButtons[i]?.SetActive(i == (int)phase);

            if (activePlayerLabel)
                activePlayerLabel.text = seatIndex == 0 ? "Your Turn" : $"Seat {seatIndex}'s Turn";

            if (turnNumberLabel)
                turnNumberLabel.text = $"Turn {turnNumber}";
        }

        public Phase CurrentPhase => _currentPhase;

        // ── Debug (editor only) ──────────────────────────────────
#if UNITY_EDITOR
        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.Space))
            {
                int next = ((int)_currentPhase + 1) % System.Enum.GetValues(typeof(Phase)).Length;
                SetPhase((Phase)next, 0, GameStateManager.Instance?.TurnNumber ?? 1);
            }
        }
#endif
    }
}
