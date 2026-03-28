using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using CommanderAILab.Models;

namespace CommanderAILab.UI
{
    /// <summary>
    /// A single token row in TokenPanelController's list.
    /// Supports qty +/-, tap all, counter editing, and removal.
    /// </summary>
    public class TokenRowView : MonoBehaviour
    {
        [Header("Labels")]
        [SerializeField] private TMP_Text nameLabel;
        [SerializeField] private TMP_Text ptLabel;
        [SerializeField] private TMP_Text qtyLabel;
        [SerializeField] private TMP_Text tappedLabel;

        [Header("Buttons")]
        [SerializeField] private Button qtyPlusBtn;
        [SerializeField] private Button qtyMinusBtn;
        [SerializeField] private Button tapAllBtn;
        [SerializeField] private Button deleteBtn;

        [Header("Counter Editor")]
        [SerializeField] private GameObject       counterEditorPanel;
        [SerializeField] private TMP_Dropdown     counterTypeDropdown;
        [SerializeField] private Button           counterAddBtn;
        [SerializeField] private Button           counterRemoveBtn;
        [SerializeField] private TMP_Text         counterSummaryLabel;
        [SerializeField] private Button           toggleCounterEditorBtn;

        private static readonly List<string> CounterTypes =
            new() { "+1/+1", "-1/-1", "loyalty", "charge", "quest", "time" };

        private TokenModel            _token;
        private Action<TokenModel>    _onDelete;

        // ── Binding ───────────────────────────────────────────
        public void Bind(TokenModel token, Action<TokenModel> onDelete)
        {
            _token    = token;
            _onDelete = onDelete;

            // Wire buttons
            qtyPlusBtn ?.onClick.AddListener(() => AdjustQty(+1));
            qtyMinusBtn?.onClick.AddListener(() => AdjustQty(-1));
            tapAllBtn  ?.onClick.AddListener(TapAll);
            deleteBtn  ?.onClick.AddListener(() => _onDelete?.Invoke(_token));
            toggleCounterEditorBtn?.onClick.AddListener(ToggleCounterEditor);
            counterAddBtn   ?.onClick.AddListener(() => AdjustCounter(+1));
            counterRemoveBtn?.onClick.AddListener(() => AdjustCounter(-1));

            // Populate counter type dropdown
            if (counterTypeDropdown != null)
            {
                counterTypeDropdown.ClearOptions();
                counterTypeDropdown.AddOptions(CounterTypes);
            }

            if (counterEditorPanel) counterEditorPanel.SetActive(false);
            RefreshDisplay();
        }

        // ── Actions ────────────────────────────────────────────
        private void AdjustQty(int delta)
        {
            _token.qty = Mathf.Max(0, _token.qty + delta);
            if (_token.qty == 0) { _onDelete?.Invoke(_token); return; }
            RefreshDisplay();
        }

        private void TapAll()
        {
            _token.isTapped = !_token.isTapped;
            RefreshDisplay();
        }

        private void ToggleCounterEditor()
        {
            if (counterEditorPanel)
                counterEditorPanel.SetActive(!counterEditorPanel.activeSelf);
        }

        private void AdjustCounter(int delta)
        {
            if (counterTypeDropdown == null) return;
            string counterType = CounterTypes[Mathf.Clamp(counterTypeDropdown.value, 0, CounterTypes.Count - 1)];
            _token.counters.TryGetValue(counterType, out int current);
            int next = Mathf.Max(0, current + delta);
            if (next == 0) _token.counters.Remove(counterType);
            else           _token.counters[counterType] = next;
            RefreshDisplay();
        }

        // ── Display ────────────────────────────────────────────
        private void RefreshDisplay()
        {
            if (nameLabel)   nameLabel.text  = _token.name;
            if (ptLabel)     ptLabel.text    = _token.PTString;
            if (qtyLabel)    qtyLabel.text   = $"×{_token.qty}";
            if (tappedLabel) tappedLabel.text = _token.isTapped ? "[Tapped]" : "";

            // Counter summary
            if (counterSummaryLabel)
            {
                var parts = new System.Text.StringBuilder();
                foreach (var kv in _token.counters)
                    parts.Append($"{kv.Key}:{kv.Value} ");
                counterSummaryLabel.text = parts.Length > 0 ? parts.ToString().Trim() : "No counters";
            }
        }
    }
}
