using UnityEngine;
using UnityEngine.UI;
using TMPro;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Visual representation of a single card in a CardZone.
    /// Handles art loading via ImageCache, tapped rotation, and face-down state.
    /// </summary>
    public class CardView : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private RawImage   artImage;
        [SerializeField] private TMP_Text   nameLabel;
        [SerializeField] private TMP_Text   ptLabel;           // power/toughness
        [SerializeField] private TMP_Text   manaCostLabel;
        [SerializeField] private GameObject tappedIndicator;   // e.g. coloured strip
        [SerializeField] private GameObject summonSickOverlay; // semi-transparent overlay
        [SerializeField] private GameObject faceDownOverlay;   // card back image object

        public CardModel Model { get; private set; }
        private bool _faceDown;

        // ── Binding ─────────────────────────────────────────────
        public void Bind(CardModel model, bool faceDown = false)
        {
            Model = model;
            _faceDown = faceDown;
            RefreshDisplay();
        }

        public void SetFaceDown(bool faceDown)
        {
            _faceDown = faceDown;
            RefreshDisplay();
        }

        // ── State ──────────────────────────────────────────────
        public void SetTapped(bool tapped)
        {
            if (Model == null) return;
            Model.isTapped = tapped;
            // Rotate the RectTransform -90 degrees when tapped
            transform.localEulerAngles = tapped ? new Vector3(0f, 0f, -90f) : Vector3.zero;
            if (tappedIndicator) tappedIndicator.SetActive(tapped);
        }

        public void SetSummonSick(bool sick)
        {
            if (Model == null) return;
            Model.isSummoningSick = sick;
            if (summonSickOverlay) summonSickOverlay.SetActive(sick);
        }

        // ── Internal ───────────────────────────────────────────
        private void RefreshDisplay()
        {
            if (faceDownOverlay) faceDownOverlay.SetActive(_faceDown);
            if (artImage)        artImage.gameObject.SetActive(!_faceDown);

            if (nameLabel)
                nameLabel.text = _faceDown ? "?" : (Model?.name ?? "");

            bool hasStats = !_faceDown
                            && Model != null
                            && !string.IsNullOrEmpty(Model.power)
                            && !string.IsNullOrEmpty(Model.toughness);

            if (ptLabel)
            {
                ptLabel.text = hasStats ? $"{Model.power}/{Model.toughness}" : "";
                ptLabel.gameObject.SetActive(hasStats);
            }

            if (manaCostLabel)
            {
                manaCostLabel.text = (!_faceDown && Model != null) ? Model.manaCost ?? "" : "";
            }

            // Load art via ImageCache if visible and URL available
            if (!_faceDown && Model != null && !string.IsNullOrEmpty(Model.imageUri)
                && artImage != null && ImageCache.Instance != null)
            {
                StartCoroutine(ImageCache.Instance.LoadCard(Model.imageUri, artImage));
            }

            // Reset tapped/sick overlays on rebind
            if (tappedIndicator)   tappedIndicator.SetActive(false);
            if (summonSickOverlay) summonSickOverlay.SetActive(false);
            transform.localEulerAngles = Vector3.zero;
        }
    }
}
