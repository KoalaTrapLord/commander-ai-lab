using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using Newtonsoft.Json;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Human player action bar — only active when seat 0 has priority.
    /// Buttons post actions to /api/game/action.
    /// Subscribes to GameStateManager.OnPriorityChanged.
    /// </summary>
    public class HumanActionBar : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private ApiClient  apiClient;
        [SerializeField] private GameObject actionBar;         // root panel
        [SerializeField] private Button     passPriorityBtn;
        [SerializeField] private Button     endTurnBtn;
        [SerializeField] private Button     declareAttackersBtn;
        [SerializeField] private Button     declareBlockersBtn;
        [SerializeField] private TMP_Text   priorityLabel;
        [SerializeField] private TMP_Text   feedbackLabel;

        private bool _hasPriority;

        // ── Lifecycle ───────────────────────────────────────────
        private void Start()
        {
            passPriorityBtn   ?.onClick.AddListener(() => PostAction("pass_priority"));
            endTurnBtn        ?.onClick.AddListener(() => PostAction("end_turn"));
            declareAttackersBtn?.onClick.AddListener(() => PostAction("declare_attackers"));
            declareBlockersBtn ?.onClick.AddListener(() => PostAction("declare_blockers"));

            if (GameStateManager.Instance != null)
            {
                GameStateManager.Instance.OnPriorityChanged += OnPriorityChanged;
                GameStateManager.Instance.OnPhaseChanged   += OnPhaseChanged;
            }

            SetPriority(false);
        }

        private void OnDestroy()
        {
            if (GameStateManager.Instance == null) return;
            GameStateManager.Instance.OnPriorityChanged -= OnPriorityChanged;
            GameStateManager.Instance.OnPhaseChanged   -= OnPhaseChanged;
        }

        // ── Priority visibility ──────────────────────────────────
        private void OnPriorityChanged(int seatIndex)
        {
            SetPriority(seatIndex == 0);
        }

        private void OnPhaseChanged(PhaseTrackerWidget.Phase phase, int seat, int turn)
        {
            // Only show combat buttons during combat phases
            bool inCombat = phase >= PhaseTrackerWidget.Phase.DeclareAttackers
                         && phase <= PhaseTrackerWidget.Phase.EndCombat;
            if (declareAttackersBtn) declareAttackersBtn.gameObject.SetActive(inCombat && _hasPriority);
            if (declareBlockersBtn)  declareBlockersBtn.gameObject.SetActive(inCombat && _hasPriority);
        }

        private void SetPriority(bool hasPriority)
        {
            _hasPriority = hasPriority;
            if (actionBar)     actionBar.SetActive(hasPriority);
            if (priorityLabel) priorityLabel.text = hasPriority ? "Your Priority" : "";
        }

        // ── Action posting ─────────────────────────────────────
        private void PostAction(string actionType)
        {
            var payload = JsonConvert.SerializeObject(new { action = actionType, seat = 0 });
            apiClient?.PostGameAction(payload,
                _ => ShowFeedback(actionType),
                err => ShowFeedback($"Error: {err}", isError: true));
        }

        private void ShowFeedback(string msg, bool isError = false)
        {
            if (!feedbackLabel) return;
            StopCoroutine(nameof(FadeOutFeedback));
            feedbackLabel.text  = msg;
            feedbackLabel.color = isError ? Color.red : Color.green;
            feedbackLabel.gameObject.SetActive(true);
            StartCoroutine(nameof(FadeOutFeedback));
        }

        private IEnumerator FadeOutFeedback()
        {
            yield return new WaitForSeconds(1.5f);
            if (feedbackLabel) feedbackLabel.gameObject.SetActive(false);
        }
    }
}
