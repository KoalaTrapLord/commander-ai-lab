using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Handles the visual elimination sequence for a seat panel.
    /// On elimination: plays a flash animation, applies a grayscale material, and
    /// shows an elimination banner with cause of death text.
    /// Requires a URP ShaderGraph material "EliminatedGrayscale" in Resources/.
    /// </summary>
    public class EliminationHandler : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private int         seatIndex;
        [SerializeField] private CanvasGroup seatCanvasGroup;    // seat panel root CanvasGroup
        [SerializeField] private Image       eliminationOverlay; // full-panel semi-transparent overlay
        [SerializeField] private TMP_Text    eliminationLabel;   // "ELIMINATED" text
        [SerializeField] private TMP_Text    causeLabel;         // cause of death
        [SerializeField] private Image[]     grayscaleTargets;   // RawImages to recolor to grayscale

        private static readonly Color GrayscaleTint = new Color(0.4f, 0.4f, 0.4f, 1f);
        private bool _eliminated;

        // ── Lifecycle ───────────────────────────────────────────
        private void Start()
        {
            if (eliminationOverlay) eliminationOverlay.gameObject.SetActive(false);
            if (eliminationLabel)   eliminationLabel.gameObject.SetActive(false);
            if (causeLabel)         causeLabel.gameObject.SetActive(false);

            if (GameStateManager.Instance != null)
                GameStateManager.Instance.OnPlayerEliminated += OnPlayerEliminated;
        }

        private void OnDestroy()
        {
            if (GameStateManager.Instance != null)
                GameStateManager.Instance.OnPlayerEliminated -= OnPlayerEliminated;
        }

        // ── Event ───────────────────────────────────────────────
        private void OnPlayerEliminated(int seat, string reason)
        {
            if (seat != seatIndex || _eliminated) return;
            _eliminated = true;
            StartCoroutine(PlayEliminationSequence(reason));
        }

        // ── Animation ──────────────────────────────────────────
        private IEnumerator PlayEliminationSequence(string reason)
        {
            // 1. Red flash
            if (eliminationOverlay)
            {
                eliminationOverlay.gameObject.SetActive(true);
                eliminationOverlay.color = new Color(1f, 0f, 0f, 0f);
                yield return FadeImage(eliminationOverlay, 0f, 0.6f, 0.15f);
                yield return FadeImage(eliminationOverlay, 0.6f, 0f, 0.4f);
                eliminationOverlay.color = new Color(0f, 0f, 0f, 0.4f);  // keep dark overlay
            }

            // 2. Grayscale tint on card art panels
            foreach (var img in grayscaleTargets)
                if (img != null) img.color = GrayscaleTint;

            // 3. Fade-down CanvasGroup to 60%
            if (seatCanvasGroup)
            {
                seatCanvasGroup.interactable = false;
                seatCanvasGroup.blocksRaycasts = false;
                yield return FadeCanvasGroup(seatCanvasGroup, seatCanvasGroup.alpha, 0.6f, 0.3f);
            }

            // 4. Show banner
            if (eliminationLabel) eliminationLabel.gameObject.SetActive(true);
            if (causeLabel)
            {
                causeLabel.text = reason switch
                {
                    "life"              => "Life total reached 0",
                    "commander_damage"  => "Commander damage (21+)",
                    "poison"            => "Poison counters (10+)",
                    "deck_empty"        => "Failed to draw",
                    _                   => reason
                };
                causeLabel.gameObject.SetActive(true);
            }
        }

        private IEnumerator FadeImage(Image img, float from, float to, float duration)
        {
            float t = 0;
            while (t < duration)
            {
                t += Time.deltaTime;
                var c = img.color;
                c.a = Mathf.Lerp(from, to, t / duration);
                img.color = c;
                yield return null;
            }
            var final = img.color;
            final.a = to;
            img.color = final;
        }

        private IEnumerator FadeCanvasGroup(CanvasGroup cg, float from, float to, float duration)
        {
            float t = 0;
            while (t < duration) { t += Time.deltaTime; cg.alpha = Mathf.Lerp(from, to, t / duration); yield return null; }
            cg.alpha = to;
        }
    }
}
