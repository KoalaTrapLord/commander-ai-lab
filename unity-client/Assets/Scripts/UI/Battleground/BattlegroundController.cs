using System;
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
    /// Master orchestrator for the Battleground scene.
    /// Reads the lobby config written by SimulationController (PlayerPrefs "BattleSeats"),
    /// wires up all seat panels, and opens the LobbySetupModal on start.
    /// </summary>
    public class BattlegroundController : MonoBehaviour
    {
        // ── Inspector ─────────────────────────────────────────────
        [Header("Seat Panels")]
        [SerializeField] private RectTransform[] seatPanels;   // [0]=bottom,[1]=right,[2]=top,[3]=left

        [Header("Center")]
        [SerializeField] private PhaseTrackerWidget phaseTracker;
        [SerializeField] private TurnOrderBar       turnOrderBar;

        [Header("Modals")]
        [SerializeField] private LobbySetupModal    lobbyModal;

        [Header("Navigation")]
        [SerializeField] private Button             mainMenuButton;

        // ── Seat rotations ────────────────────────────────────────
        private static readonly float[] SeatRotations = { 0f, -90f, 180f, 90f };

        // ── Lifecycle ──────────────────────────────────────────
        private void Start()
        {
            ApplySeatRotations();
            SubscribeEvents();

            mainMenuButton.onClick.AddListener(() => SceneManager.LoadScene("MainMenu"));

            // Pre-populate lobby from PlayerPrefs if arriving via SimulationController
            string savedSeats = PlayerPrefs.GetString("BattleSeats", "");
            if (lobbyModal != null)
                lobbyModal.Open(savedSeats);
        }

        private void OnDestroy() => UnsubscribeEvents();

        // ── Layout ─────────────────────────────────────────────
        private void ApplySeatRotations()
        {
            for (int i = 0; i < seatPanels.Length; i++)
            {
                if (seatPanels[i] == null) continue;
                seatPanels[i].localEulerAngles = new Vector3(0f, 0f, SeatRotations[i]);
            }
        }

        // ── Event subscriptions ──────────────────────────────────
        private void SubscribeEvents()
        {
            if (GameStateManager.Instance == null) return;
            GameStateManager.Instance.OnTurnChanged  += OnTurnChanged;
            GameStateManager.Instance.OnPhaseChanged += OnPhaseChanged;
            GameStateManager.Instance.OnFullStateSync += OnFullStateSync;
        }

        private void UnsubscribeEvents()
        {
            if (GameStateManager.Instance == null) return;
            GameStateManager.Instance.OnTurnChanged  -= OnTurnChanged;
            GameStateManager.Instance.OnPhaseChanged -= OnPhaseChanged;
            GameStateManager.Instance.OnFullStateSync -= OnFullStateSync;
        }

        private void OnTurnChanged(int seat) =>
            turnOrderBar?.SetActiveSeat(seat);

        private void OnPhaseChanged(PhaseTrackerWidget.Phase phase, int seat, int turn) =>
            phaseTracker?.SetPhase(phase, seat, turn);

        private void OnFullStateSync(GameState state)
        {
            // Delegate per-seat refresh to each SeatPanelController once those exist
            turnOrderBar?.SetActiveSeat(state.activeSeat);
        }
    }
}
