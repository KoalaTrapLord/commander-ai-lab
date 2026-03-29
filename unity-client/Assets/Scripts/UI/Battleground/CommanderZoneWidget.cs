using UnityEngine;
using UnityEngine.UI;
using TMPro;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Per-seat commander zone widget.
    /// Shows: art crop banner, commander name, cast count, commander tax.
    /// Requires ImageCache singleton in scene.
    /// </summary>
    public class CommanderZoneWidget : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private RawImage   artCropImage;
        [SerializeField] private TMP_Text   commanderNameLabel;
        [SerializeField] private TMP_Text   castCountLabel;
        [SerializeField] private TMP_Text   taxLabel;
        [SerializeField] private UnityEngine.UI.Button castCommanderBtn;

        public CardModel CommanderCard { get; private set; }
        private int _castCount = 0;

        // ── Binding ───────────────────────────────────────────
        public void Bind(CardModel commander)
        {
            CommanderCard = commander;
            _castCount    = commander != null ? commander.counters.GetValueOrDefault("cast_count", 0) : 0;

            if (commanderNameLabel)
                commanderNameLabel.text = commander?.name ?? "No Commander";

            UpdateTaxDisplay();

            // Load art crop from Scryfall
            if (commander != null && !string.IsNullOrEmpty(commander.name)
                && artCropImage != null && ImageCache.Instance != null)
            {
                StartCoroutine(ImageCache.Instance.LoadArtCrop(commander.name, artCropImage));
            }
        }

        // ── Cast tracking ──────────────────────────────────────
        public void OnCommanderCast()
        {
            _castCount++;
            UpdateTaxDisplay();
        }

        public void SetCastCount(int count)
        {
            _castCount = Mathf.Max(0, count);
            UpdateTaxDisplay();
        }

        // ── Internal ──────────────────────────────────────────
        private void UpdateTaxDisplay()
        {
            if (castCountLabel)
                castCountLabel.text = _castCount == 0 ? "Not yet cast" : $"Cast #{_castCount}";

            int tax = _castCount * 2;
            if (taxLabel)
                taxLabel.text = tax == 0 ? "No tax" : $"+{tax} ☀ tax";
        }
    }
}
