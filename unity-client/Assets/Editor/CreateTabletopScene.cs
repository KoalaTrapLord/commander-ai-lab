#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UIElements;

/// <summary>
/// Editor tool: creates the "Tabletop" scene with all required
/// GameObjects, components, camera, lighting, and services pre-wired.
/// Run via: Commander AI Lab > Create Tabletop Scene
/// </summary>
public class CreateTabletopScene
{
    [MenuItem("Commander AI Lab/Create Tabletop Scene")]
    public static void Create()
    {
        // Create a new scene
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        scene.name = "Tabletop";

        // ── Directional Light ──────────────────────────────────────
        var dirLight = new GameObject("Directional Light");
        var light = dirLight.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 0.6f;
        light.color = new Color(1f, 0.95f, 0.9f);
        light.shadows = LightShadows.Soft;
        dirLight.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        // ── Camera ─────────────────────────────────────────────────
        var camObj = new GameObject("Main Camera");
        camObj.tag = "MainCamera";
        var cam = camObj.AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.05f, 0.05f, 0.08f);
        cam.fieldOfView = 50f;
        cam.nearClipPlane = 0.1f;
        cam.farClipPlane = 100f;
        camObj.AddComponent<AudioListener>();

        // Add orbit camera controller
        var camCtrl = camObj.AddComponent<CommanderAILab.Tabletop.TabletopCameraController>();
        camObj.transform.position = new Vector3(0, 10, -6);
        camObj.transform.LookAt(Vector3.zero);

        // ── Services (DontDestroyOnLoad singletons) ────────────────
        var servicesObj = new GameObject("[Services]");

        // ApiClient
        var apiClient = servicesObj.AddComponent<CommanderAILab.Services.ApiClient>();

        // GameSessionService
        var gameSession = servicesObj.AddComponent<CommanderAILab.Services.GameSessionService>();

        // ImageCache
        var imageCache = servicesObj.AddComponent<CommanderAILab.Services.ImageCache>();

        // ── Table ──────────────────────────────────────────────────
        var tableObj = new GameObject("Table");
        tableObj.transform.position = Vector3.zero;
        tableObj.AddComponent<CommanderAILab.Tabletop.TableMeshGenerator>();

        // ── Board Manager ──────────────────────────────────────────
        var boardObj = new GameObject("BoardManager");
        boardObj.transform.position = Vector3.zero;
        var boardMgr = boardObj.AddComponent<CommanderAILab.Tabletop.BoardManager>();

        // ── HUD (UI Document) ──────────────────────────────────────
        var hudObj = new GameObject("TabletopHUD");
        var uiDoc = hudObj.AddComponent<UIDocument>();
        // Create a default PanelSettings asset if needed
        var panelSettings = ScriptableObject.CreateInstance<PanelSettings>();
        panelSettings.name = "TabletopPanelSettings";
        panelSettings.scaleMode = PanelScaleMode.ScaleWithScreenSize;
        panelSettings.referenceResolution = new Vector2Int(1920, 1080);

        string settingsPath = "Assets/UI/TabletopPanelSettings.asset";
        EnsureDirectoryExists("Assets/UI");
        AssetDatabase.CreateAsset(panelSettings, settingsPath);
        uiDoc.panelSettings = AssetDatabase.LoadAssetAtPath<PanelSettings>(settingsPath);

        var hud = hudObj.AddComponent<CommanderAILab.Tabletop.TabletopHUD>();

        // ── Gameplay Controller ────────────────────────────────────
        var gameCtrlObj = new GameObject("GameplayController");
        var gameCtrl = gameCtrlObj.AddComponent<CommanderAILab.Tabletop.GameplayController>();

        // Wire serialized references via SerializedObject
        var so = new SerializedObject(gameCtrl);
        so.FindProperty("boardManager").objectReferenceValue = boardMgr;
        so.FindProperty("hud").objectReferenceValue = hud;
        so.FindProperty("cameraController").objectReferenceValue = camCtrl;
        so.ApplyModifiedProperties();

        // ── Save Scene ─────────────────────────────────────────────
        string scenePath = "Assets/Scenes/Tabletop.unity";
        EnsureDirectoryExists("Assets/Scenes");
        EditorSceneManager.SaveScene(scene, scenePath);

        // Add to build settings
        var buildScenes = new System.Collections.Generic.List<EditorBuildSettingsScene>(
            EditorBuildSettings.scenes);
        if (!buildScenes.Exists(s => s.path == scenePath))
        {
            buildScenes.Add(new EditorBuildSettingsScene(scenePath, true));
            EditorBuildSettings.scenes = buildScenes.ToArray();
        }

        Debug.Log($"[Commander AI Lab] Tabletop scene created at {scenePath}");
        EditorUtility.DisplayDialog("Tabletop Scene Created",
            "The 3D tabletop scene has been created with all components:\n\n" +
            "- Orbit camera (right-drag to orbit, scroll to zoom)\n" +
            "- Table with felt surface and rim\n" +
            "- Board manager with 4-player zones\n" +
            "- HUD overlay (life, phase, log, buttons)\n" +
            "- Gameplay controller (auto-starts game)\n" +
            "- API services (connects to localhost:8080)\n\n" +
            "Press Play to start!", "OK");
    }

    private static void EnsureDirectoryExists(string path)
    {
        if (!AssetDatabase.IsValidFolder(path))
        {
            var parts = path.Split('/');
            string current = parts[0];
            for (int i = 1; i < parts.Length; i++)
            {
                string next = current + "/" + parts[i];
                if (!AssetDatabase.IsValidFolder(next))
                    AssetDatabase.CreateFolder(current, parts[i]);
                current = next;
            }
        }
    }
}
#endif
