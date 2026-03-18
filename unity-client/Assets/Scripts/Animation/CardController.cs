using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using TMPro;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.Animation
{
    /// <summary>
    /// CardController — manages a single card prefab instance.
    /// Handles: card data binding, image loading (async Scryfall),
    /// flip animation, hover scale + glow, click raise + detail panel,
    /// tooltip overlay, drag support, mobile gestures.
    /// Attach to a UI Image-based card prefab.
    /// </summary>
    public class CardController : MonoBehaviour,
        IPointerEnterHandler, IPointerExitHandler, IPointerClickHandler,
        IBeginDragHandler, IDragHandler, IEndDragHandler
    {
        [Header("Card Faces")]
        [SerializeField] private Image frontFaceImage;
        [SerializeField] private Image backFaceImage;

        [Header("Glow / Outline")]
        [SerializeField] private Outline glowOutline;
        [SerializeField] private Color glowColor = new Color(1f, 0.85f, 0f, 0.9f);

        [Header("Tooltip")]
        [SerializeField] private GameObject tooltipPanel;
        [SerializeField] private TMP_Text tooltipName;
        [SerializeField] private TMP_Text tooltipManaCost;
        [SerializeField] private TMP_Text tooltipTypeLine;

        [Header("Animation Settings")]
        [SerializeField] private float hoverScaleMultiplier = 1.12f;
        [SerializeField] private float hoverRaiseY = 15f;
        [SerializeField] private float flipDuration = 0.35f;
        [SerializeField] private float hoverDuration = 0.15f;
        [SerializeField] private float clickRaiseY = 40f;

        [Header("LOD")]
        [SerializeField] private Sprite lowResPlaceholder;

        // Public events for parent scenes
        public event Action<CardModel> OnCardClicked;
        public event Action<CardController> OnDragStarted;
        public event Action<CardController, Vector2> OnDragMoved;
        public event Action<CardController> OnDragEnded;

        private CardModel _card;
        private Vector3 _originalScale;
        private Vector3 _originalPosition;
        private RectTransform _rectTransform;
        private bool _isFaceUp = true;
        private bool _isFlipping = false;
        private bool _isHovered = false;
        private bool _isDragging = false;
        private Vector2 _dragOffset;
        private Canvas _parentCanvas;

        // Mobile gesture tracking
        private float _pointerDownTime;
        private bool _pointerHeld;
        private const float LongPressThreshold = 0.4f;

        private void Awake()
        {
            _rectTransform = GetComponent<RectTransform>();
            _originalScale = transform.localScale;
            _originalPosition = transform.localPosition;
            _parentCanvas = GetComponentInParent<Canvas>();

            if (tooltipPanel != null) tooltipPanel.SetActive(false);
            if (glowOutline != null)
            {
                glowOutline.effectColor = new Color(glowColor.r, glowColor.g, glowColor.b, 0f);
                glowOutline.enabled = false;
            }
        }

        // ── Data Binding ────────────────────────────────────────────────
        public void SetCardData(CardModel card)
        {
            _card = card;
            if (tooltipName != null) tooltipName.text = card.name;
            if (tooltipManaCost != null) tooltipManaCost.text = card.manaCost;
            if (tooltipTypeLine != null) tooltipTypeLine.text = card.typeLine;

            // LOD: show low-res placeholder first
            if (lowResPlaceholder != null && frontFaceImage != null)
                frontFaceImage.sprite = lowResPlaceholder;

            // Async load high-res from Scryfall
            if (!string.IsNullOrEmpty(card.imageUrl))
                ImageCache.Instance.GetSprite(card.imageUrl, sprite =>
                {
                    if (frontFaceImage != null) frontFaceImage.sprite = sprite;
                });
        }

        public CardModel GetCardData() => _card;

        // ── Flip Animation (Y-axis rotation, swap front/back at 90°) ────
        public void Flip()
        {
            if (_isFlipping) return;
            StartCoroutine(FlipCoroutine());
        }

        private IEnumerator FlipCoroutine()
        {
            _isFlipping = true;
            float half = flipDuration * 0.5f;
            // First half: rotate to 90°
            float t = 0f;
            while (t < half)
            {
                t += Time.deltaTime;
                float angle = Mathf.Lerp(0f, 90f, t / half);
                transform.localRotation = Quaternion.Euler(0f, angle, 0f);
                yield return null;
            }
            // Swap face visibility
            _isFaceUp = !_isFaceUp;
            if (frontFaceImage != null) frontFaceImage.gameObject.SetActive(_isFaceUp);
            if (backFaceImage != null) backFaceImage.gameObject.SetActive(!_isFaceUp);
            // Second half: rotate from 90° back to 0°
            t = 0f;
            while (t < half)
            {
                t += Time.deltaTime;
                float angle = Mathf.Lerp(90f, 0f, t / half);
                transform.localRotation = Quaternion.Euler(0f, angle, 0f);
                yield return null;
            }
            transform.localRotation = Quaternion.identity;
            _isFlipping = false;
        }

        // ── Hover: scale-up + glow outline + raise card ───────────────
        public void OnPointerEnter(PointerEventData eventData)
        {
            if (_isDragging) return;
            _isHovered = true;
            StopAllCoroutines();
            StartCoroutine(AnimateHover(true));
            if (tooltipPanel != null) tooltipPanel.SetActive(true);
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            if (_isDragging) return;
            _isHovered = false;
            StopAllCoroutines();
            StartCoroutine(AnimateHover(false));
            if (tooltipPanel != null) tooltipPanel.SetActive(false);
        }

        private IEnumerator AnimateHover(bool entering)
        {
            Vector3 targetScale = entering ? _originalScale * hoverScaleMultiplier : _originalScale;
            Vector3 targetPos = entering
                ? _originalPosition + new Vector3(0, hoverRaiseY, 0)
                : _originalPosition;
            float targetGlow = entering ? 1f : 0f;

            Vector3 startScale = transform.localScale;
            Vector3 startPos = transform.localPosition;
            float startGlow = glowOutline != null ? glowOutline.effectColor.a : 0f;

            if (entering && glowOutline != null) glowOutline.enabled = true;

            float t = 0f;
            while (t < hoverDuration)
            {
                t += Time.deltaTime;
                float p = t / hoverDuration;
                float smooth = p * p * (3f - 2f * p); // smoothstep
                transform.localScale = Vector3.Lerp(startScale, targetScale, smooth);
                transform.localPosition = Vector3.Lerp(startPos, targetPos, smooth);
                if (glowOutline != null)
                {
                    float a = Mathf.Lerp(startGlow, targetGlow, smooth);
                    glowOutline.effectColor = new Color(glowColor.r, glowColor.g, glowColor.b, a);
                }
                yield return null;
            }

            transform.localScale = targetScale;
            transform.localPosition = targetPos;
            if (!entering && glowOutline != null) glowOutline.enabled = false;
        }

        // ── Click: raise card + shadow + detail panel ────────────────
        public void OnPointerClick(PointerEventData eventData)
        {
            if (_isDragging) return;
            StartCoroutine(ClickRaiseAnimation());
            OnCardClicked?.Invoke(_card);
        }

        private IEnumerator ClickRaiseAnimation()
        {
            Vector3 raised = transform.localPosition + new Vector3(0, clickRaiseY, 0);
            float dur = 0.12f;
            float t = 0f;
            Vector3 start = transform.localPosition;
            while (t < dur)
            {
                t += Time.deltaTime;
                transform.localPosition = Vector3.Lerp(start, raised, t / dur);
                yield return null;
            }
            yield return new WaitForSeconds(0.08f);
            t = 0f;
            Vector3 target = _isHovered
                ? _originalPosition + new Vector3(0, hoverRaiseY, 0)
                : _originalPosition;
            while (t < dur)
            {
                t += Time.deltaTime;
                transform.localPosition = Vector3.Lerp(raised, target, t / dur);
                yield return null;
            }
        }

        // ── Drag Support (for DeckBuilder scene) ────────────────────
        public void OnBeginDrag(PointerEventData eventData)
        {
            _isDragging = true;
            if (tooltipPanel != null) tooltipPanel.SetActive(false);
            RectTransformUtility.ScreenPointToLocalPointInRectangle(
                _parentCanvas.transform as RectTransform,
                eventData.position, eventData.pressEventCamera, out _dragOffset);
            _dragOffset = (Vector2)transform.localPosition - _dragOffset;
            transform.SetAsLastSibling();
            OnDragStarted?.Invoke(this);
        }

        public void OnDrag(PointerEventData eventData)
        {
            if (!_isDragging) return;
            RectTransformUtility.ScreenPointToLocalPointInRectangle(
                _parentCanvas.transform as RectTransform,
                eventData.position, eventData.pressEventCamera, out Vector2 localPoint);
            transform.localPosition = localPoint + _dragOffset;
            OnDragMoved?.Invoke(this, eventData.position);
        }

        public void OnEndDrag(PointerEventData eventData)
        {
            _isDragging = false;
            OnDragEnded?.Invoke(this);
        }

        // ── Mobile: tap = hover, long-press = detail, drag = move ─────
        public void SimulateMobileTap()
        {
            // Toggle hover state on tap (mobile has no hover)
            if (_isHovered)
            {
                _isHovered = false;
                StartCoroutine(AnimateHover(false));
                if (tooltipPanel != null) tooltipPanel.SetActive(false);
            }
            else
            {
                _isHovered = true;
                StartCoroutine(AnimateHover(true));
                if (tooltipPanel != null) tooltipPanel.SetActive(true);
            }
        }

        public void SimulateMobileLongPress()
        {
            OnCardClicked?.Invoke(_card);
        }

        /// <summary>Reset card position (e.g. after failed drag)</summary>
        public void ResetPosition()
        {
            transform.localPosition = _originalPosition;
            transform.localScale = _originalScale;
        }
    }
}
