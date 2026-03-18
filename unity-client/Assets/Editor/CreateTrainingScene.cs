#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.Reflection;

public static class CreateTrainingScene
{
    [MenuItem("Tools/Create Training Scene")]
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

        CreatePanel(canvasGo.transform, "Background", new Color(0.05f, 0.05f, 0.08f), stretch: true);

        // Header
        var header = CreatePanel(canvasGo.transform, "Header", new Color(0.12f, 0.12f, 0.18f));
        SetAnchors(header.GetComponent<RectTransform>(), new Vector2(0f, 0.93f), new Vector2(1f, 1f));
        var backBtn = CreateTMPButton(header.transform, "BackButton", "< Back", new Color(0.2f, 0.2f, 0.3f));
        SetAnchors(backBtn.GetComponent<RectTransform>(), new Vector2(0.01f, 0.1f), new Vector2(0.08f, 0.9f));
        var title = CreateTMPText(header.transform, "TitleText", "ML Training Dashboard", 28, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(title.GetComponent<RectTransform>(), new Vector2(0.1f, 0.1f), new Vector2(0.9f, 0.9f));

        // Left column: Stats + Controls
        var leftCol = CreatePanel(canvasGo.transform, "LeftColumn", new Color(0.08f, 0.08f, 0.12f));
        SetAnchors(leftCol.GetComponent<RectTransform>(), new Vector2(0f, 0.01f), new Vector2(0.28f, 0.92f));

        // Stats panel
        var statsPanel = CreatePanel(leftCol.transform, "StatsPanel", new Color(0.12f, 0.12f, 0.18f));
        SetAnchors(statsPanel.GetComponent<RectTransform>(), new Vector2(0.02f, 0.72f), new Vector2(0.98f, 0.99f));
        var statsTitle = CreateTMPText(statsPanel.transform, "StatsTitle", "TRAINING DATA", 16, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(statsTitle.GetComponent<RectTransform>(), new Vector2(0f, 0.78f), new Vector2(1f, 1f));
        var cardCountTxt = CreateTMPText(statsPanel.transform, "CardCountText", "Cards: --", 14, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(cardCountTxt.GetComponent<RectTransform>(), new Vector2(0.05f, 0.55f), new Vector2(0.95f, 0.77f));
        var sessionCountTxt = CreateTMPText(statsPanel.transform, "SessionCountText", "Sessions: --", 14, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(sessionCountTxt.GetComponent<RectTransform>(), new Vector2(0.05f, 0.33f), new Vector2(0.95f, 0.55f));
        var modelVerTxt = CreateTMPText(statsPanel.transform, "ModelVersionText", "Model: --", 14, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(modelVerTxt.GetComponent<RectTransform>(), new Vector2(0.05f, 0.11f), new Vector2(0.95f, 0.33f));
        var lastTrainedTxt = CreateTMPText(statsPanel.transform, "LastTrainedText", "Last trained: --", 12, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(lastTrainedTxt.GetComponent<RectTransform>(), new Vector2(0.05f, 0f), new Vector2(0.95f, 0.11f));

        // Controls panel
        var ctrlPanel = CreatePanel(leftCol.transform, "ControlsPanel", new Color(0.12f, 0.12f, 0.18f));
        SetAnchors(ctrlPanel.GetComponent<RectTransform>(), new Vector2(0.02f, 0.42f), new Vector2(0.98f, 0.71f));
        var statusTxt = CreateTMPText(ctrlPanel.transform, "StatusText", "Ready.", 13, FontStyles.Normal, TextAlignmentOptions.Center);
        SetAnchors(statusTxt.GetComponent<RectTransform>(), new Vector2(0.02f, 0.75f), new Vector2(0.98f, 1f));
        var startBtn = CreateTMPButton(ctrlPanel.transform, "StartTrainingButton", "Start Training", new Color(0.1f, 0.5f, 0.1f));
        SetAnchors(startBtn.GetComponent<RectTransform>(), new Vector2(0.05f, 0.45f), new Vector2(0.95f, 0.73f));
        var stopBtn = CreateTMPButton(ctrlPanel.transform, "StopTrainingButton", "Stop", new Color(0.5f, 0.1f, 0.1f));
        SetAnchors(stopBtn.GetComponent<RectTransform>(), new Vector2(0.05f, 0.15f), new Vector2(0.95f, 0.43f));
        var exportBtn = CreateTMPButton(ctrlPanel.transform, "ExportModelButton", "Export Model", new Color(0.2f, 0.3f, 0.5f));
        SetAnchors(exportBtn.GetComponent<RectTransform>(), new Vector2(0.05f, 0.01f), new Vector2(0.95f, 0.14f));

        // Center column: Live Charts
        var centerCol = CreatePanel(canvasGo.transform, "CenterColumn", new Color(0.08f, 0.08f, 0.12f));
        SetAnchors(centerCol.GetComponent<RectTransform>(), new Vector2(0.29f, 0.01f), new Vector2(0.69f, 0.92f));

        var accLabel = CreateTMPText(centerCol.transform, "AccuracyLabel", "Accuracy: --", 14, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(accLabel.GetComponent<RectTransform>(), new Vector2(0f, 0.87f), new Vector2(1f, 0.93f));
        var accChart = CreatePanel(centerCol.transform, "AccuracyChart", new Color(0.05f, 0.15f, 0.05f));
        SetAnchors(accChart.GetComponent<RectTransform>(), new Vector2(0.02f, 0.5f), new Vector2(0.98f, 0.86f));

        var lossLabel = CreateTMPText(centerCol.transform, "LossLabel", "Loss: --", 14, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(lossLabel.GetComponent<RectTransform>(), new Vector2(0f, 0.43f), new Vector2(1f, 0.49f));
        var lossChart = CreatePanel(centerCol.transform, "LossChart", new Color(0.15f, 0.05f, 0.05f));
        SetAnchors(lossChart.GetComponent<RectTransform>(), new Vector2(0.02f, 0.06f), new Vector2(0.98f, 0.42f));

        // Feature importance title
        var featTitle = CreateTMPText(centerCol.transform, "FeatureTitle", "Feature Importance", 13, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(featTitle.GetComponent<RectTransform>(), new Vector2(0f, 0.01f), new Vector2(1f, 0.05f));

        // Right column: Model History + Log
        var rightCol = CreatePanel(canvasGo.transform, "RightColumn", new Color(0.08f, 0.08f, 0.12f));
        SetAnchors(rightCol.GetComponent<RectTransform>(), new Vector2(0.7f, 0.01f), new Vector2(1f, 0.92f));

        // History panel
        var histPanel = CreatePanel(rightCol.transform, "HistoryPanel", new Color(0.12f, 0.12f, 0.18f));
        SetAnchors(histPanel.GetComponent<RectTransform>(), new Vector2(0.02f, 0.52f), new Vector2(0.98f, 0.99f));
        var histTitle = CreateTMPText(histPanel.transform, "HistoryTitle", "MODEL HISTORY", 15, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(histTitle.GetComponent<RectTransform>(), new Vector2(0f, 0.88f), new Vector2(1f, 1f));
        var histScrollGo = new GameObject("HistoryScroll");
        histScrollGo.transform.SetParent(histPanel.transform, false);
        var histScroll = histScrollGo.AddComponent<ScrollRect>();
        var histScrollRT = histScrollGo.GetComponent<RectTransform>();
        SetAnchors(histScrollRT, new Vector2(0.01f, 0.01f), new Vector2(0.99f, 0.87f));
        var histContent = new GameObject("Content");
        histContent.transform.SetParent(histScrollGo.transform, false);
        var histContentRT = histContent.AddComponent<RectTransform>();
        histContentRT.anchorMin = Vector2.zero; histContentRT.anchorMax = new Vector2(1f, 0f);
        histContentRT.pivot = new Vector2(0.5f, 0f);
        histContent.AddComponent<VerticalLayoutGroup>().spacing = 4;
        histContent.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        histScroll.content = histContentRT;
        histScroll.vertical = true; histScroll.horizontal = false;

        // Log panel
        var logPanel = CreatePanel(rightCol.transform, "LogPanel", new Color(0.06f, 0.06f, 0.06f));
        SetAnchors(logPanel.GetComponent<RectTransform>(), new Vector2(0.02f, 0.01f), new Vector2(0.98f, 0.51f));
        var logTitle = CreateTMPText(logPanel.transform, "LogTitle", "TRAINING LOG", 14, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(logTitle.GetComponent<RectTransform>(), new Vector2(0f, 0.88f), new Vector2(1f, 1f));
        var logScrollGo = new GameObject("LogScroll");
        logScrollGo.transform.SetParent(logPanel.transform, false);
        var logScroll = logScrollGo.AddComponent<ScrollRect>();
        SetAnchors(logScrollGo.GetComponent<RectTransform>(), new Vector2(0.01f, 0.01f), new Vector2(0.99f, 0.87f));
        var logContent = new GameObject("LogContent");
        logContent.transform.SetParent(logScrollGo.transform, false);
        var logContentRT = logContent.AddComponent<RectTransform>();
        logContentRT.anchorMin = Vector2.zero; logContentRT.anchorMax = new Vector2(1f, 0f);
        logContentRT.pivot = new Vector2(0.5f, 0f);
        var logText = logContent.AddComponent<TextMeshProUGUI>();
        logText.fontSize = 11; logText.color = new Color(0.7f, 1f, 0.7f);
        logText.text = "";
        logContent.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        logScroll.content = logContentRT;
        logScroll.vertical = true; logScroll.horizontal = false;

        // Error panel
        var errorPanel = CreatePanel(canvasGo.transform, "ErrorPanel", new Color(0.4f, 0.05f, 0.05f, 0.95f));
        SetAnchors(errorPanel.GetComponent<RectTransform>(), new Vector2(0.3f, 0.4f), new Vector2(0.7f, 0.6f));
        errorPanel.SetActive(false);
        var errorTxt = CreateTMPText(errorPanel.transform, "ErrorText", "", 16, FontStyles.Normal, TextAlignmentOptions.Center);
        SetAnchors(errorTxt.GetComponent<RectTransform>(), new Vector2(0.05f, 0.1f), new Vector2(0.95f, 0.9f));

        // Wire up TrainingController
        var controllerGo = new GameObject("TrainingController");
        controllerGo.transform.SetParent(canvasGo.transform, false);
        var ctrl = controllerGo.AddComponent<CommanderAILab.UI.TrainingController>();

        SetPrivateField(ctrl, "backButton",           backBtn.GetComponent<Button>());
        SetPrivateField(ctrl, "cardCountText",        cardCountTxt.GetComponent<TextMeshProUGUI>());
        SetPrivateField(ctrl, "sessionCountText",     sessionCountTxt.GetComponent<TextMeshProUGUI>());
        SetPrivateField(ctrl, "modelVersionText",     modelVerTxt.GetComponent<TextMeshProUGUI>());
        SetPrivateField(ctrl, "lastTrainedText",      lastTrainedTxt.GetComponent<TextMeshProUGUI>());
        SetPrivateField(ctrl, "startTrainingButton",  startBtn.GetComponent<Button>());
        SetPrivateField(ctrl, "stopTrainingButton",   stopBtn.GetComponent<Button>());
        SetPrivateField(ctrl, "exportModelButton",    exportBtn.GetComponent<Button>());
        SetPrivateField(ctrl, "statusText",           statusTxt.GetComponent<TextMeshProUGUI>());
        SetPrivateField(ctrl, "accuracyChartRect",    accChart.GetComponent<RectTransform>());
        SetPrivateField(ctrl, "lossChartRect",        lossChart.GetComponent<RectTransform>());
        SetPrivateField(ctrl, "accuracyLabel",        accLabel.GetComponent<TextMeshProUGUI>());
        SetPrivateField(ctrl, "lossLabel",            lossLabel.GetComponent<TextMeshProUGUI>());
        SetPrivateField(ctrl, "historyParent",        histContent.transform);
        SetPrivateField(ctrl, "logText",              logText);
        SetPrivateField(ctrl, "logScrollRect",        logScroll);
        SetPrivateField(ctrl, "errorPanel",           errorPanel);
        SetPrivateField(ctrl, "errorText",            errorTxt.GetComponent<TextMeshProUGUI>());

        EditorSceneManager.SaveScene(scene, "Assets/Scenes/Training.unity");
        UnityEngine.Debug.Log("[CreateTrainingScene] Training scene created.");
    }

    // ── Helpers ───────────────────────────────────────────────────────────
    static GameObject CreatePanel(Transform parent, string name, Color color, bool stretch = false)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = color;
        var rt = go.GetComponent<RectTransform>();
        if (stretch)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = rt.offsetMax = Vector2.zero;
        }
        return go;
    }

    static GameObject CreateTMPText(Transform parent, string name, string text, int size,
        FontStyles style, TextAlignmentOptions align)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var tmp = go.AddComponent<TextMeshProUGUI>();
        tmp.text = text;
        tmp.fontSize = size;
        tmp.fontStyle = style;
        tmp.alignment = align;
        tmp.color = Color.white;
        return go;
    }

    static GameObject CreateTMPButton(Transform parent, string name, string label, Color bgColor)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = bgColor;
        var btn = go.AddComponent<Button>();
        var colors = btn.colors;
        colors.highlightedColor = bgColor * 1.3f;
        colors.pressedColor = bgColor * 0.7f;
        btn.colors = colors;
        var txtGo = new GameObject("Text");
        txtGo.transform.SetParent(go.transform, false);
        var tmp = txtGo.AddComponent<TextMeshProUGUI>();
        tmp.text = label;
        tmp.fontSize = 16;
        tmp.alignment = TextAlignmentOptions.Center;
        tmp.color = Color.white;
        var txtRT = txtGo.GetComponent<RectTransform>();
        txtRT.anchorMin = Vector2.zero;
        txtRT.anchorMax = Vector2.one;
        txtRT.offsetMin = txtRT.offsetMax = Vector2.zero;
        return go;
    }

    static void SetAnchors(RectTransform rt, Vector2 min, Vector2 max)
    {
        rt.anchorMin = min;
        rt.anchorMax = max;
        rt.offsetMin = rt.offsetMax = Vector2.zero;
    }

    static void SetPrivateField(object obj, string fieldName, object value)
    {
        var field = obj.GetType().GetField(fieldName,
            BindingFlags.NonPublic | BindingFlags.Instance);
        field?.SetValue(obj, value);
    }
}
#endif
