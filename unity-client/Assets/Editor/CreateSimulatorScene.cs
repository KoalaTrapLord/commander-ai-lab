#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.Reflection;

public static class CreateSimulatorScene
{
    [MenuItem("Tools/Create Simulator Scene")]
    public static void Create()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        var services = new GameObject("[Services]");
        services.AddComponent<CommanderAILab.Services.ApiClient>();

        var canvasGo = new GameObject("Canvas");
        var canvas = canvasGo.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        var scaler = canvasGo.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1920, 1080);
        canvasGo.AddComponent<GraphicRaycaster>();

        if (Object.FindObjectOfType<UnityEngine.EventSystems.EventSystem>() == null)
        {
            var es = new GameObject("EventSystem");
            es.AddComponent<UnityEngine.EventSystems.EventSystem>();
            es.AddComponent<UnityEngine.EventSystems.StandaloneInputModule>();
        }

        CreatePanel(canvasGo.transform, "Background", new Color(0.08f, 0.08f, 0.12f), stretch: true);

        // Header
        var header = CreatePanel(canvasGo.transform, "Header", new Color(0.12f, 0.12f, 0.18f));
        SetAnchors(header.GetComponent<RectTransform>(), new Vector2(0f, 0.93f), new Vector2(1f, 1f));
        var backBtn = CreateTMPButton(header.transform, "BackButton", "< Back", new Color(0.2f, 0.2f, 0.3f));
        SetAnchors(backBtn.GetComponent<RectTransform>(), new Vector2(0.01f, 0.1f), new Vector2(0.08f, 0.9f));
        var title = CreateTMPText(header.transform, "TitleText", "Simulator", 28, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(title.GetComponent<RectTransform>(), new Vector2(0.3f, 0.1f), new Vector2(0.7f, 0.9f));

        // Config Panel
        var configPanel = CreatePanel(canvasGo.transform, "ConfigPanel", new Color(0.1f, 0.1f, 0.16f));
        SetAnchors(configPanel.GetComponent<RectTransform>(), new Vector2(0.05f, 0.35f), new Vector2(0.5f, 0.93f));
        var cfgVlg = configPanel.AddComponent<VerticalLayoutGroup>();
        cfgVlg.padding = new RectOffset(16, 16, 16, 16); cfgVlg.spacing = 10;
        cfgVlg.childForceExpandWidth = true; cfgVlg.childForceExpandHeight = false;

        CreateTMPText(
