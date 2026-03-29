using System.Collections.Generic;
using UnityEngine;
using CommanderAILab.Models;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Manages a collection of CardView instances inside one battlefield zone
    /// (Hand, Battlefield, Graveyard, Exile, etc.).
    /// The cardContainer should have a HorizontalLayoutGroup or GridLayoutGroup.
    /// </summary>
    public class CardZone : MonoBehaviour
    {
        [SerializeField] private BattleZone  zoneType;
        [SerializeField] private GameObject  cardPrefab;     // CardPrefab.prefab
        [SerializeField] private Transform   cardContainer;  // layout group parent
        [SerializeField] private bool        faceDown;       // true for AI hand zones

        private readonly List<CardView> _cards = new();

        public BattleZone ZoneType => zoneType;
        public IReadOnlyList<CardView> Cards => _cards;
        public int Count => _cards.Count;

        // ── Public API ─────────────────────────────────────────
        public CardView AddCard(CardModel model)
        {
            var go   = Instantiate(cardPrefab, cardContainer);
            var view = go.GetComponent<CardView>();
            if (view == null)
            {
                Debug.LogError("[CardZone] CardPrefab missing CardView component.");
                Destroy(go);
                return null;
            }
            model.currentZone = zoneType;
            view.Bind(model, faceDown);
            _cards.Add(view);
            return view;
        }

        public void RemoveCard(string cardId)
        {
            var view = _cards.Find(c => c.Model?.id == cardId);
            if (view == null) return;
            _cards.Remove(view);
            Destroy(view.gameObject);
        }

        public void ClearAll()
        {
            foreach (var v in _cards) if (v != null) Destroy(v.gameObject);
            _cards.Clear();
        }

        public void SetFaceDown(bool fd)
        {
            faceDown = fd;
            foreach (var v in _cards) v?.SetFaceDown(fd);
        }

        public CardView FindById(string cardId) =>
            _cards.Find(c => c.Model?.id == cardId);
    }
}
