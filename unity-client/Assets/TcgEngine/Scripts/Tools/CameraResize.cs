using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Script that will resize the camera frame to a supported aspect ratio
    /// By default: only 16/9 and 16/10 are supported
    /// Black bars will appear on the side if the window is different
    /// </summary>

    [RequireComponent(typeof(Camera))]
    public class CameraResize : MonoBehaviour
    {
        public float aspect_ratio_min = 16f / 10f;
        public float aspect_ratio_max = 16f / 9f;

        [Header("Orthographic Only")]
        public float cam_size_min = 5f;
        public float cam_size_max = 5.5f;

        [Header("Perspective Only")]
        public float cam_fov_min = 50f;
        public float cam_fov_max = 55f;

        private Camera cam;
        private int sheight;
        private int swidth;

        void Start()
        {
            cam = GetComponent<Camera>();
            sheight = Screen.height;
            swidth = Screen.width;
            UpdateSize();
        }

        private void Update()
        {
            if (sheight != Screen.height || swidth != Screen.width)
            {
                sheight = Screen.height;
                swidth = Screen.width;
                UpdateSize();
            }
        }

        public void UpdateSize()
        {
            float screenRatio = Screen.width / (float)Screen.height;
            float targetRatio = GetAspectRatio();

            if (Mathf.Approximately(screenRatio, targetRatio))
            {
                // Screen or window is the target aspect ratio: use the whole area.
                cam.rect = new Rect(0, 0, 1, 1);
            }
            else if (screenRatio > targetRatio)
            {
                // Screen or window is wider than the target: pillarbox.
                float normalizedWidth = targetRatio / screenRatio;
                float barThickness = (1f - normalizedWidth) / 2f;
                cam.rect = new Rect(barThickness, 0, normalizedWidth, 1);
            }
            else
            {
                // Screen or window is narrower than the target: letterbox.
                float normalizedHeight = screenRatio / targetRatio;
                float barThickness = (1f - normalizedHeight) / 2f;
                cam.rect = new Rect(0, barThickness, 1, normalizedHeight);
            }

            if (cam.orthographic)
            {
                float value = GetAspectPercentage();
                float cam_size = value * cam_size_min + (1f - value) * cam_size_max;
                cam.orthographicSize = cam_size;
            }
            else
            {
                float value = GetAspectPercentage();
                float fov = value * cam_fov_min + (1f - value) * cam_fov_max;
                cam.fieldOfView = fov;
            }
        }

        public float GetAspectRatio()
        {
            float screenRatio = Screen.width / (float)Screen.height;
            float targetRatio = Mathf.Clamp(screenRatio, aspect_ratio_min, aspect_ratio_max);
            return targetRatio;
        }

        public float GetAspectPercentage()
        {
            float aspect = GetAspectRatio();
            float value = (aspect - aspect_ratio_min) / (aspect_ratio_max - aspect_ratio_min);
            return value;
        }

    }
}
