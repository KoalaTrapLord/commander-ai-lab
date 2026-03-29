using UnityEngine;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Horizontal strip of 4 TurnOrderPills at the top of BattlefieldCenter.
    /// Animates an active border sliding to the current seat's pill on turn change.
    /// Subscribes to GameStateManager.OnTurnChanged.
    /// </summary>
    public class TurnOrderBar : MonoBehaviour
    {
        [SerializeField] private TurnOrderPill[] pills;        // length 4
        [SerializeField] private RectTransform   activeBorder; // sliding highlight rect
        [SerializeField] private float           slideDuration = 0.25f;

        private int _activeSeat = 0;

        // ── Lifecycle ───────────────────────────────────────────
        private void Start()
        {
            if (GameStateManager.Instance != null)
            {
                GameStateManager.Instance.OnTurnChanged  += SetActiveSeat;
                GameStateManager.Instance.OnLifeChanged  += OnLifeChanged;
                GameStateManager.Instance.OnPlayerEliminated += OnPlayerEliminated;
            }
            SetActiveSeat(0);
        }

        private void OnDestroy()
        {
            if (GameStateManager.Instance == null) return;
            GameStateManager.Instance.OnTurnChanged      -= SetActiveSeat;
            GameStateManager.Instance.OnLifeChanged      -= OnLifeChanged;
            GameStateManager.Instance.OnPlayerEliminated -= OnPlayerEliminated;
        }

        // ── Public API ─────────────────────────────────────────
        public void SetActiveSeat(int seatIndex)
        {
            _activeSeat = seatIndex;
            for (int i = 0; i < pills.Length; i++)
                pills[i]?.SetActive(i == seatIndex);

            AnimateBorderToPill(seatIndex);
        }

        // ── Internal ──────────────────────────────────────────
        private void AnimateBorderToPill(int seatIndex)
        {
            if (activeBorder == null || pills == null || seatIndex >= pills.Length) return;
            if (pills[seatIndex] == null) return;

            var targetPos = (pills[seatIndex].transform as RectTransform)?.anchoredPosition
                            ?? pills[seatIndex].transform.localPosition;

            StopAllCoroutines();
            StartCoroutine(SlideBorder(targetPos));
        }

        private System.Collections.IEnumerator SlideBorder(Vector2 targetPos)
        {
            var start = activeBorder.anchoredPosition;
            float elapsed = 0f;
            while (elapsed < slideDuration)
            {
                elapsed += Time.deltaTime;
                float t = Mathf.SmoothStep(0f, 1f, elapsed / slideDuration);
                activeBorder.anchoredPosition = Vector2.Lerp(start, targetPos, t);
                yield return null;
            }
            activeBorder.anchoredPosition = targetPos;
        }

        private void OnLifeChanged(int seatIndex, int newLife)
        {
            if (seatIndex < pills.Length) pills[seatIndex]?.UpdateLife(newLife);
        }

        private void OnPlayerEliminated(int seatIndex, string reason)
        {
            if (seatIndex < pills.Length) pills[seatIndex]?.SetEliminated();
        }
    }
}
