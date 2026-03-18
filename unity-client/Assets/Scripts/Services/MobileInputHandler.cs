using UnityEngine;
using UnityEngine.UI;

namespace CommanderAILab.Services
{
    /// <summary>
    /// Mobile-specific input handler and responsive UI utilities.
    /// Handles: touch controls, pinch-to-zoom, swipe gestures,
    /// safe area insets, orientation changes, and responsive layout.
    /// </summary>
    public class MobileInputHandler : MonoBehaviour
    {
        public static MobileInputHandler Instance { get; private set; }

        [Header("Touch Settings")]
        [SerializeField] private float pinchZoomSpeed = 0.01f;
        [SerializeField] private float swipeThreshold = 50f;
        [SerializeField] private float longPressTime = 0.5f;

        [Header("Safe Area")]
        [SerializeField] private RectTransform safeAreaRect;

        // Gesture state
        private float _touchStartTime;
        private Vector2 _touchStartPos;
        private bool _isTouching;
        private float _lastPinchDistance;

        // Events
        public event System.Action<float> OnPinchZoom;    // delta
        public event System.Action<Vector2> OnSwipe;       // direction
        public event System.Action<Vector2> OnLongPress;   // position
        public event System.Action<Vector2> OnTap;         // position

        private void Awake()
        {
            if (Instance != null) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);
        }

        private void Start()
        {
            ApplySafeArea();
            SetTargetFrameRate();
        }

        private void Update()
        {
            if (!IsMobilePlatform()) return;

            HandleTouchInput();
            HandlePinchZoom();

            // Handle orientation changes
            if (Screen.orientation != _lastOrientation)
            {
                _lastOrientation = Screen.orientation;
                ApplySafeArea();
            }
        }

        private ScreenOrientation _lastOrientation;

        // ── Touch Gestures ─────────────────────────────────────────────
        private void HandleTouchInput()
        {
            if (Input.touchCount != 1) return;
            Touch touch = Input.GetTouch(0);

            switch (touch.phase)
            {
                case TouchPhase.Began:
                    _touchStartTime = Time.time;
                    _touchStartPos = touch.position;
                    _isTouching = true;
                    break;

                case TouchPhase.Ended:
                    if (!_isTouching) break;
                    _isTouching = false;
                    float duration = Time.time - _touchStartTime;
                    Vector2 delta = touch.position - _touchStartPos;

                    if (duration >= longPressTime && delta.magnitude < swipeThreshold)
                    {
                        OnLongPress?.Invoke(touch.position);
                    }
                    else if (delta.magnitude >= swipeThreshold)
                    {
                        OnSwipe?.Invoke(delta.normalized);
                    }
                    else
                    {
                        OnTap?.Invoke(touch.position);
                    }
                    break;

                case TouchPhase.Canceled:
                    _isTouching = false;
                    break;
            }
        }

        private void HandlePinchZoom()
        {
            if (Input.touchCount != 2) { _lastPinchDistance = 0; return; }

            Touch t0 = Input.GetTouch(0);
            Touch t1 = Input.GetTouch(1);
            float dist = Vector2.Distance(t0.position, t1.position);

            if (_lastPinchDistance > 0)
            {
                float delta = (dist - _lastPinchDistance) * pinchZoomSpeed;
                OnPinchZoom?.Invoke(delta);
            }
            _lastPinchDistance = dist;
        }

        // ── Safe Area (notch / rounded corners) ─────────────────────
        private void ApplySafeArea()
        {
            if (safeAreaRect == null) return;
            Rect safe = Screen.safeArea;
            Vector2 anchorMin = safe.position;
            Vector2 anchorMax = safe.position + safe.size;
            anchorMin.x /= Screen.width;
            anchorMin.y /= Screen.height;
            anchorMax.x /= Screen.width;
            anchorMax.y /= Screen.height;
            safeAreaRect.anchorMin = anchorMin;
            safeAreaRect.anchorMax = anchorMax;
        }

        // ── Platform Config ──────────────────────────────────────────
        private void SetTargetFrameRate()
        {
#if UNITY_IOS || UNITY_ANDROID
            Application.targetFrameRate = 60;
            Screen.sleepTimeout = SleepTimeout.NeverSleep;
#endif
        }

        public static bool IsMobilePlatform()
        {
#if UNITY_IOS || UNITY_ANDROID
            return true;
#else
            return false;
#endif
        }

        /// <summary>Returns responsive font size based on screen DPI.</summary>
        public static int ResponsiveFontSize(int baseSizeAt96DPI)
        {
            float dpi = Screen.dpi > 0 ? Screen.dpi : 96f;
            return Mathf.RoundToInt(baseSizeAt96DPI * (dpi / 96f) * 0.6f);
        }

        /// <summary>Returns true if device is in portrait orientation.</summary>
        public static bool IsPortrait()
        {
            return Screen.height > Screen.width;
        }
    }
}
