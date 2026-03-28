using System;
using System.Collections.Generic;
using UnityEngine;
using Newtonsoft.Json;
using CommanderAILab.Models;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Singleton event hub for the live battleground game state.
    /// All UI widgets subscribe to these events instead of polling.
    /// Receives parsed server events from GameWebSocketClient.
    /// </summary>
    public class GameStateManager : MonoBehaviour
    {
        public static GameStateManager Instance { get; private set; }

        // ── Events ────────────────────────────────────────────────
        public event Action<int>                              OnTurnChanged;      // activeSeat
        public event Action<PhaseTrackerWidget.Phase, int, int> OnPhaseChanged;   // phase, seat, turnNumber
        public event Action<int>                              OnPriorityChanged;  // seatIndex
        public event Action<int, int>                         OnLifeChanged;      // seatIndex, newLife
        public event Action<int, string>                      OnPlayerEliminated; // seatIndex, reason
        public event Action<List<StackZoneController.StackItem>> OnStackUpdated;
        public event Action<GameState>                        OnFullStateSync;

        // ── State ────────────────────────────────────────────────
        public int TurnNumber { get; private set; } = 1;
        private GameState _state;

        // ── Lifecycle ─────────────────────────────────────────────
        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
        }

        // ── Server event dispatch ───────────────────────────────────
        /// <summary>Called by GameWebSocketClient on the Unity main thread.</summary>
        public void ApplyServerEvent(string type, string payload)
        {
            try
            {
                switch (type)
                {
                    case "state_update":
                        _state = JsonConvert.DeserializeObject<GameState>(payload);
                        if (_state != null) OnFullStateSync?.Invoke(_state);
                        break;

                    case "turn_start":
                        var ts = JsonConvert.DeserializeObject<TurnStartEvent>(payload);
                        if (ts != null) { TurnNumber = ts.turnNumber; OnTurnChanged?.Invoke(ts.seat); }
                        break;

                    case "phase_change":
                        var pc = JsonConvert.DeserializeObject<PhaseChangeEvent>(payload);
                        if (pc != null)
                            OnPhaseChanged?.Invoke((PhaseTrackerWidget.Phase)pc.phaseIndex, pc.seat, TurnNumber);
                        break;

                    case "priority":
                        var pv = JsonConvert.DeserializeObject<PriorityEvent>(payload);
                        if (pv != null) OnPriorityChanged?.Invoke(pv.seat);
                        break;

                    case "life_change":
                        var lc = JsonConvert.DeserializeObject<LifeChangeEvent>(payload);
                        if (lc != null) OnLifeChanged?.Invoke(lc.seat, lc.newLife);
                        break;

                    case "stack_update":
                        var su = JsonConvert.DeserializeObject<StackUpdateEvent>(payload);
                        if (su?.items != null) OnStackUpdated?.Invoke(su.items);
                        break;

                    case "player_elim":
                        var pe = JsonConvert.DeserializeObject<EliminationEvent>(payload);
                        if (pe != null) EliminatePlayer(pe.seat, pe.reason);
                        break;

                    default:
                        Debug.LogWarning($"[GameStateManager] Unknown event type: {type}");
                        break;
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[GameStateManager] ApplyServerEvent failed ({type}): {ex.Message}");
            }
        }

        /// <summary>Trigger elimination (called by LifeTrackerWidget, CommanderDamageRow, or server event).</summary>
        public void EliminatePlayer(int seatIndex, string reason) =>
            OnPlayerEliminated?.Invoke(seatIndex, reason);

        // ── Debug helpers (editor only) ─────────────────────────────
#if UNITY_EDITOR
        private void OnGUI()
        {
            GUILayout.BeginArea(new Rect(10, 10, 220, 200));
            GUILayout.Label("[GSM Debug]");
            if (GUILayout.Button("Fake Turn 1 Start"))  ApplyServerEvent("turn_start",  "{\"seat\":0,\"turnNumber\":1}");
            if (GUILayout.Button("Advance Phase Main1")) ApplyServerEvent("phase_change","{\"phaseIndex\":3,\"seat\":0}");
            if (GUILayout.Button("Priority Seat 0"))    ApplyServerEvent("priority",    "{\"seat\":0}");
            if (GUILayout.Button("Elim Seat 2"))        EliminatePlayer(2, "life");
            GUILayout.EndArea();
        }
#endif

        // ── Private event POCOs ───────────────────────────────────
        [Serializable] private class TurnStartEvent  { public int seat; public int turnNumber; }
        [Serializable] private class PhaseChangeEvent { public int phaseIndex; public int seat; }
        [Serializable] private class PriorityEvent   { public int seat; }
        [Serializable] private class LifeChangeEvent { public int seat; public int newLife; }
        [Serializable] private class StackUpdateEvent { public List<StackZoneController.StackItem> items; }
        [Serializable] private class EliminationEvent { public int seat; public string reason; }
    }
}
