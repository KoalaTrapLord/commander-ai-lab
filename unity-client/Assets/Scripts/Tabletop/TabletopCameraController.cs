using UnityEngine;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// Orbiting camera for the 3D tabletop.
    /// Controls: Right-drag to orbit, scroll to zoom, middle-drag to pan.
    /// Starts positioned above the human player's side (seat 0).
    /// </summary>
    public class TabletopCameraController : MonoBehaviour
    {
        [Header("Orbit")]
        [SerializeField] private float orbitSpeed = 150f;
        [SerializeField] private float minPitch = 15f;
        [SerializeField] private float maxPitch = 85f;

        [Header("Zoom")]
        [SerializeField] private float zoomSpeed = 2f;
        [SerializeField] private float minDistance = 3f;
        [SerializeField] private float maxDistance = 20f;

        [Header("Pan")]
        [SerializeField] private float panSpeed = 0.1f;
        [SerializeField] private float panBounds = 5f;

        [Header("Initial View")]
        [SerializeField] private float initialYaw = 0f;
        [SerializeField] private float initialPitch = 55f;
        [SerializeField] private float initialDistance = 10f;
        [SerializeField] private Vector3 focusPoint = Vector3.zero;

        [Header("Smooth")]
        [SerializeField] private float smoothSpeed = 10f;

        private float _yaw;
        private float _pitch;
        private float _distance;
        private Vector3 _panOffset;
        private Vector3 _targetPosition;
        private Quaternion _targetRotation;

        private void Start()
        {
            _yaw = initialYaw;
            _pitch = initialPitch;
            _distance = initialDistance;
            _panOffset = Vector3.zero;
            ApplyTransform(instant: true);
        }

        private void LateUpdate()
        {
            HandleOrbit();
            HandleZoom();
            HandlePan();
            ApplyTransform(instant: false);
        }

        // ── Orbit (right mouse drag) ──────────────────────────────

        private void HandleOrbit()
        {
            if (Input.GetMouseButton(1))
            {
                _yaw += Input.GetAxis("Mouse X") * orbitSpeed * Time.deltaTime;
                _pitch -= Input.GetAxis("Mouse Y") * orbitSpeed * Time.deltaTime;
                _pitch = Mathf.Clamp(_pitch, minPitch, maxPitch);
            }
        }

        // ── Zoom (scroll wheel) ──────────────────────────────────

        private void HandleZoom()
        {
            float scroll = Input.GetAxis("Mouse ScrollWheel");
            if (Mathf.Abs(scroll) > 0.001f)
            {
                _distance -= scroll * zoomSpeed;
                _distance = Mathf.Clamp(_distance, minDistance, maxDistance);
            }
        }

        // ── Pan (middle mouse drag) ──────────────────────────────

        private void HandlePan()
        {
            if (Input.GetMouseButton(2))
            {
                float dx = -Input.GetAxis("Mouse X") * panSpeed;
                float dz = -Input.GetAxis("Mouse Y") * panSpeed;

                Vector3 right = transform.right;
                Vector3 forward = Vector3.ProjectOnPlane(transform.forward, Vector3.up).normalized;

                _panOffset += right * dx + forward * dz;
                _panOffset.x = Mathf.Clamp(_panOffset.x, -panBounds, panBounds);
                _panOffset.z = Mathf.Clamp(_panOffset.z, -panBounds, panBounds);
                _panOffset.y = 0;
            }
        }

        // ── Apply Transform ──────────────────────────────────────

        private void ApplyTransform(bool instant)
        {
            Quaternion rotation = Quaternion.Euler(_pitch, _yaw, 0);
            Vector3 negDistance = new Vector3(0, 0, -_distance);
            Vector3 center = focusPoint + _panOffset;

            _targetPosition = center + rotation * negDistance;
            _targetRotation = Quaternion.LookRotation(center - _targetPosition, Vector3.up);

            if (instant)
            {
                transform.position = _targetPosition;
                transform.rotation = _targetRotation;
            }
            else
            {
                transform.position = Vector3.Lerp(transform.position, _targetPosition,
                    Time.deltaTime * smoothSpeed);
                transform.rotation = Quaternion.Slerp(transform.rotation, _targetRotation,
                    Time.deltaTime * smoothSpeed);
            }
        }

        // ── Public: snap to player seat view ─────────────────────

        /// <summary>Snap camera to view a specific seat (0=South, 1=East, 2=North, 3=West).</summary>
        public void SnapToSeat(int seat)
        {
            _yaw = seat * 90f;
            _pitch = 55f;
            _distance = initialDistance;
            _panOffset = Vector3.zero;
        }

        /// <summary>Top-down overview of the full table.</summary>
        public void SnapTopDown()
        {
            _yaw = 0f;
            _pitch = 85f;
            _distance = 14f;
            _panOffset = Vector3.zero;
        }

        /// <summary>Reset to initial view.</summary>
        public void ResetView()
        {
            _yaw = initialYaw;
            _pitch = initialPitch;
            _distance = initialDistance;
            _panOffset = Vector3.zero;
        }
    }
}
