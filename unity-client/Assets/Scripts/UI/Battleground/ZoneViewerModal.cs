using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Full-screen overlay showing all cards in a particular zone (graveyard, exile, etc.).
    /// Opened by clicking zone count badges on each seat panel.
    /// </summary>
    public class ZoneViewerModal : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private TMP_Text   titleLabel;
        [SerializeField] private Transform  cardGrid;       // GridLayoutGroup
        [SerializeField] private GameObject cardPrefab;     // CardView prefab
        [SerializeField] private Button     closeButton;

        private readonly List<GameObject> _cardGOs = new();

        private void Start() => closeButton?.onClick.AddListener(Close);

        // ── Open ─────────────────────────────────────────────────
        public void Open(string zoneName, CardZone zone)
        {
            if (titleLabel) titleLabel.text = $"{zoneName} ({zone.Count} cards)";

            foreach (var go in _cardGOs) if (go) Destroy(go);
            _cardGOs.Clear();

            foreach (var view in zone.Cards)
            {
                if (view?.Model == null) continue;
                var go = Instantiate(cardPrefab, cardGrid);
                go.SetActive(true);
                var cv = go.GetComponent<CardView>();
                cv?.Bind(view.Model, false);
                _cardGOs.Add(go);
            }

            gameObject.SetActive(true);
        }

        // ── Close ───────────────────────────────────────────────
        public void Close()
        {
            foreach (var go in _cardGOs) if (go) Destroy(go);
            _cardGOs.Clear();
            gameObject.SetActive(false);
        }
    }
}
