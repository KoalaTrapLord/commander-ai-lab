using System;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using Newtonsoft.Json;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Displays the active spell/ability stack (LIFO order, top of stack shown first).
    /// Hidden when stack is empty. Subscribes to GameStateManager.OnStackUpdated.
    /// </summary>
    public class StackZoneController : MonoBehaviour
    {
        [SerializeField] private GameObject stackPanel;
        [SerializeField] private Transform  stackItemParent;  // VerticalLayoutGroup
        [SerializeField] private GameObject stackItemPrefab;
        [SerializeField] private TMP_Text   stackCountLabel;

        private readonly List<GameObject> _itemGOs = new();

        // ── Lifecycle ───────────────────────────────────────────
        private void Start()
        {
            if (GameStateManager.Instance != null)
                GameStateManager.Instance.OnStackUpdated += SetStack;
            SetStack(new List<StackItem>());
        }

        private void OnDestroy()
        {
            if (GameStateManager.Instance != null)
                GameStateManager.Instance.OnStackUpdated -= SetStack;
        }

        // ── Public API ─────────────────────────────────────────
        public void SetStack(List<StackItem> items)
        {
            // Clear existing rows
            foreach (var go in _itemGOs) if (go) Destroy(go);
            _itemGOs.Clear();

            bool hasItems = items != null && items.Count > 0;
            if (stackPanel) stackPanel.SetActive(hasItems);

            if (stackCountLabel)
                stackCountLabel.text = hasItems ? $"Stack ({items.Count})" : "";

            if (!hasItems) return;

            // LIFO — iterate in reverse so top of stack appears first
            for (int i = items.Count - 1; i >= 0; i--)
            {
                var go = Instantiate(stackItemPrefab, stackItemParent);
                go.SetActive(true);
                var view = go.GetComponent<StackItemView>();
                view?.Bind(items[i], items.Count - 1 - i);
                _itemGOs.Add(go);
            }
        }

        // ── Serializable stack item (shared with GameState) ───────────
        [Serializable]
        public class StackItem
        {
            [JsonProperty("card_name")]  public string cardName;
            [JsonProperty("caster_seat")] public int casterSeat;
            [JsonProperty("targets")]   public List<string> targets;
            [JsonProperty("is_ability")] public bool isAbility;
        }
    }
}
