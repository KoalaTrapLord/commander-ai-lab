using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Per-seat life total widget with +/- buttons, danger flash, and history log.
    /// Calls GameStateManager.EliminatePlayer when life reaches 0.
    /// </summary>
    public class LifeTrackerWidget : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private TMP_Text lifeLabel;
        [SerializeField] private Button   plusOneBtn;
        [SerializeField] private Button   minusOneBtn;
        [SerializeField] private Button   plusFiveBtn;
        [SerializeField] private Button   minusFiveBtn;
        [SerializeField] private GameObject dangerFlash;   // red glow overlay, shown at <=5 life

        [Header("Config")]
        [SerializeField] private int startingLife = 40;
        public int SeatIndex { get; set; }

        private int _life;
        private readonly List<LifeHistoryEntry> _history = new();

        // ── Lifecycle ───────────────────────────────────────────
        private void Start()
        {
            SetLife(startingLife);
            plusOneBtn .onClick.AddListener(() => AdjustLife(+1, "manual"));
            minusOneBtn.onClick.AddListener(() => AdjustLife(-1, "manual"));
            plusFiveBtn .onClick.AddListener(() => AdjustLife(+5, "manual"));
            minusFiveBtn.onClick.AddListener(() => AdjustLife(-5, "manual"));
        }

        // ── Public API ─────────────────────────────────────────
        public int Life => _life;

        public void AdjustLife(int delta, string source)
        {
            _life = Mathf.Max(0, _life + delta);
            RefreshDisplay();

            int turn = GameStateManager.Instance != null ? GameStateManager.Instance.TurnNumber : 0;
            _history.Add(new LifeHistoryEntry { delta = delta, source = source, turn = turn });

            if (_life == 0)
                GameStateManager.Instance?.EliminatePlayer(SeatIndex, "life");
        }

        public void SetLife(int value)
        {
            _life = Mathf.Max(0, value);
            RefreshDisplay();
        }

        public List<LifeHistoryEntry> GetHistory() => _history;

        // ── Internal ───────────────────────────────────────────
        private void RefreshDisplay()
        {
            if (lifeLabel)   lifeLabel.text = _life.ToString();
            if (dangerFlash) dangerFlash.SetActive(_life <= 5 && _life > 0);
        }

        [Serializable]
        public class LifeHistoryEntry
        {
            public int    delta;
            public string source;
            public int    turn;
        }
    }
}
