using UnityEngine;
using UnityEngine.UIElements;
using CommanderAILab.Services;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// Drop this on any GameObject in your Tabletop scene.
    /// On Awake it ensures every runtime system exists:
    ///   - Lighting + Camera
    ///   - ApiClient  (singleton, DontDestroyOnLoad)
    ///   - GameSessionService  (singleton, DontDestroyOnLoad)
    ///   - ImageCache
    ///   - BoardManager  (with TableMeshGenerator)
    ///   - TabletopHUD   (requires UIDocument)
    ///   - GameplayController
    ///   - TabletopCameraController
    /// </summary>
    public class TabletopSceneBootstrapper : MonoBehaviour
    {
        [Header("Optional: drag existing refs here to skip auto-creation")]
        [SerializeField] private Camera mainCamera;
        [SerializeField] private Light mainLight;

        private void Awake()
        {
            EnsureLighting();
            EnsureCamera();
            EnsureSingleton<ApiClient>("_ApiClient");
            EnsureSingleton<GameSessionService>("_GameSessionService");
            EnsureSingleton<ImageCache>("_ImageCache");
            EnsureBoardManager();
            EnsureHUD();
            EnsureGameplayController();
            Debug.Log("[Bootstrapper] Tabletop scene ready.");
        }

        // ── Helpers ──────────────────────────────────────────

        private T EnsureSingleton<T>(string goName) where T : MonoBehaviour
        {
            var existing = FindObjectOfType<T>();
            if (existing != null) return existing;
            var go = new GameObject(goName);
            return go.AddComponent<T>();
        }

        private void EnsureLighting()
        {
            if (mainLight != null) return;
            if (FindObjectOfType<Light>() != null) return;

            var lightGo = new GameObject("Directional Light");
            mainLight = lightGo.AddComponent<Light>();
            mainLight.type = LightType.Directional;
            mainLight.color = new Color(1f, 0.96f, 0.9f);
            mainLight.intensity = 1.2f;
            lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

            // Ambient
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.25f, 0.22f, 0.3f);
        }

        private void EnsureCamera()
        {
            if (mainCamera != null) return;
            mainCamera = Camera.main;
            if (mainCamera != null) return;

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            mainCamera = camGo.AddComponent<Camera>();
            mainCamera.clearFlags = CameraClearFlags.SolidColor;
            mainCamera.backgroundColor = new Color(0.08f, 0.08f, 0.12f);
            camGo.transform.position = new Vector3(0f, 8f, -6f);
            camGo.transform.rotation = Quaternion.Euler(50f, 0f, 0f);

            // Add camera controller
            if (camGo.GetComponent<TabletopCameraController>() == null)
                camGo.AddComponent<TabletopCameraController>();
        }

        private void EnsureBoardManager()
        {
            if (FindObjectOfType<BoardManager>() != null) return;

            var go = new GameObject("BoardManager");
            go.AddComponent<BoardManager>();
            go.AddComponent<TableMeshGenerator>();
        }

        private void EnsureHUD()
        {
            if (FindObjectOfType<TabletopHUD>() != null) return;

            var go = new GameObject("TabletopHUD");
            var doc = go.AddComponent<UIDocument>();
            // TabletopHUD builds its own UI in OnEnable via BuildUI()
            go.AddComponent<TabletopHUD>();

            // Assign the default Panel Settings if one exists in the project
            var panelSettings = Resources.Load<PanelSettings>("DefaultPanelSettings");
            if (panelSettings != null)
                doc.panelSettings = panelSettings;
            else
                Debug.LogWarning("[Bootstrapper] No 'DefaultPanelSettings' found in Resources. " +
                    "Create one at Assets/Resources/DefaultPanelSettings.asset or assign manually.");
        }

        private void EnsureGameplayController()
        {
            if (FindObjectOfType<GameplayController>() != null) return;
            var go = new GameObject("GameplayController");
            go.AddComponent<GameplayController>();
        }
    }
}
