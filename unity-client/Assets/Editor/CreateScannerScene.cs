#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.Reflection;

public static class CreateScannerScene
{
    [MenuItem("Tools/Create Scanner Scene")]
    public static void Create()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        var services = new GameObject("[Services]");
        services.AddComponent<CommanderAILab.Services.ApiClient>();
        services.AddComponent<CommanderAILab.Services.ImageCache>();

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

        CreatePanel(canvasGo.transform, "Background", new Color(0.05f, 0.05f, 0.08f), stretch: true);

        // Header
        var header = CreatePanel(canvasGo.transform, "Header", new Color(0.12f, 0.12f, 0.18f));
        SetAnchors(header.GetComponent<RectTransform>(), new Vector2(0f, 0.93f), new Vector2(1f, 1f));
        var backBtn = CreateTMPButton(header.transform, "BackButton", "< Back", new Color(0.2f, 0.2f, 0.3f));
        SetAnchors(backBtn.GetComponent<RectTransform>(), new Vector2(0.01f, 0.1f), new Vector2(0.08f, 0.9f));
        var title = CreateTMPText(header.transform, "TitleText", "Card Scanner", 28, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(title.GetComponent<RectTransform>(), new Vector2(0.3f, 0.1f), new Vector2(0.7f, 0.9f));

        // Camera feed (left)
        var camFeedGo = new GameObject("CameraFeedImage");
        camFeedGo.transform.SetParent(canvasGo.transform, false);
        camFeedGo.AddComponent<RawImage>().color = Color.black;
        SetAnchors(camFeedGo.GetComponent<RectTransform>(), new Vector2(0.01f, 0.20f), new Vector2(0.55f, 0.93f));

        // Scan overlay (animated line placeholder)
        var scanOverlay = CreatePanel(canvasGo.transform, "ScanOverlay", new Color(0f, 0.8f, 0f, 0.35f));
        SetAnchors(scanOverlay.GetComponent<RectTransform>(), new Vector2(0.01f, 0.55f), new Vector2(0.55f, 0.57f));
        scanOverlay.SetActive(false);

        // Camera status
        var camStatus = CreateTMPText(canvasGo.transform, "CameraStatusText", "Initializing camera...", 16, FontStyles.Normal, TextAlignmentOptions.Center);
        SetAnchors(camStatus.GetComponent<RectTransform>(), new Vector2(0.01f, 0.15f), new Vector2(0.55f, 0.20f));

        // Capture + toggle buttons
        var captureBtn = CreateTMPButton(canvasGo.transform, "CaptureButton", "Scan Card", new Color(0.15f, 0.6f, 0.15f));
        SetAnchors(captureBtn.GetComponent<RectTransform>(), new Vector2(0.05f, 0.07f), new Vector2(0.32f, 0.14f));
        var toggleCamBtn = CreateTMPButton(canvasGo.transform, "ToggleCameraButton", "Flip Camera", new Color(0.2f, 0.3f, 0.5f));
        SetAnchors(toggleCamBtn.GetComponent<RectTransform>(), new Vector2(0.34f, 0.07f), new Vector2(0.54f, 0.14f));

        // Result panel (right)
        var resultPanel = CreatePanel(canvasGo.transform, "ResultPanel", new Color(0.1f, 0.1f, 0.16f, 0.97f));
        SetAnchors(resultPanel.GetComponent<RectTransform>(), new Vector2(0.56f, 0.20f), new Vector2(0.99f, 0.93f));

        var resultImg = new GameObject("ResultCardImage");
        resultImg.transform.SetParent(resultPanel.transform, false);
        resultImg.AddComponent<Image>().color = new Color(0.15f, 0.15f, 0.2f);
        SetAnchors(resultImg.GetComponent<RectTransform>(), new Vector2(0.03f, 0.55f), new Vector2(0.45f, 0.98f));

        var rName       = CreateTMPText(resultPanel.transform, "ResultCardName",  "", 22, FontStyles.Bold,   TextAlignmentOptions.Left);
        SetAnchors(r
