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

        CreateTMPText(configPanel.transform, "ConfigTitle", "Simulation Config", 20, FontStyles.Bold, TextAlignmentOptions.Center);

        // Deck selector
        var deckLabel = CreateTMPText(configPanel.transform, "DeckLabel", "Deck:", 16, FontStyles.Normal, TextAlignmentOptions.Left);
        var deckInput = CreateTMPInputField(configPanel.transform, "DeckInput", "Deck ID or name...");

        // Num games
        var gamesLabel = CreateTMPText(configPanel.transform, "GamesLabel", "Games:", 16, FontStyles.Normal, TextAlignmentOptions.Left);
        var gamesInput = CreateTMPInputField(configPanel.transform, "GamesInput", "100");

        // Start/Stop buttons
        var startBtn = CreateTMPButton(configPanel.transform, "StartButton", "Start Simulation", new Color(0.2f, 0.55f, 0.2f));
        var stopBtn  = CreateTMPButton(configPanel.transform, "StopButton",  "Stop",             new Color(0.55f, 0.2f, 0.2f));

        // Results Panel
        var resultsPanel = CreatePanel(canvasGo.transform, "ResultsPanel", new Color(0.1f, 0.1f, 0.16f));
        SetAnchors(resultsPanel.GetComponent<RectTransform>(), new Vector2(0.52f, 0.35f), new Vector2(0.95f, 0.93f));

        var resultsTitle = CreateTMPText(resultsPanel.transform, "ResultsTitle", "Results", 20, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(resultsTitle.GetComponent<RectTransform>(), new Vector2(0f, 0.90f), new Vector2(1f, 1f));

        var statusText = CreateTMPText(resultsPanel.transform, "StatusText", "Ready", 16, FontStyles.Normal, TextAlignmentOptions.TopLeft);
        SetAnchors(statusText.GetComponent<RectTransform>(), new Vector2(0.03f, 0.03f), new Vector2(0.97f, 0.90f));

        // Progress bar
        var progressBg = CreatePanel(canvasGo.transform, "ProgressBar", new Color(0.2f, 0.2f, 0.25f));
        SetAnchors(progressBg.GetComponent<RectTransform>(), new Vector2(0.05f, 0.28f), new Vector2(0.95f, 0.33f));
        var progressFill = CreatePanel(progressBg.transform, "ProgressFill", new Color(0.2f, 0.6f, 0.3f));
        SetAnchors(progressFill.GetComponent<RectTransform>(), new Vector2(0f, 0f), new Vector2(0f, 1f));
        var progressText = CreateTMPText(progressBg.transform, "ProgressText", "0%", 14, FontStyles.Normal, TextAlignmentOptions.Center);
        SetAnchors(progressText.GetComponent<RectTransform>(), new Vector2(0f, 0f), new Vector2(1f, 1f));

        EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
        Debug.Log("[CreateSimulatorScene] Simulator scene created.");
    }

    // -- Helpers --

    static void SetAnchors(RectTransform rt, Vector2 min, Vector2 max)
    {
        rt.anchorMin = min;
        rt.anchorMax = max;
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;
    }

    static GameObject CreatePanel(Transform parent, string name, Color color, bool stretch = false)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = color;
        var rt = go.GetComponent<RectTransform>();
        if (stretch) SetAnchors(rt, Vector2.zero, Vector2.one);
        return go;
    }

    static GameObject CreateTMPText(Transform parent, string name, string text, int fontSize, FontStyles style, TextAlignmentOptions alignment)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var tmp = go.AddComponent<TextMeshProUGUI>();
        tmp.text = text;
        tmp.fontSize = fontSize;
        tmp.fontStyle = style;
        tmp.alignment = alignment;
        tmp.color = Color.white;
        var rt = go.GetComponent<RectTransform>();
        SetAnchors(rt, Vector2.zero, Vector2.one);
        return go;
    }

    static GameObject CreateTMPButton(Transform parent, string name, string label, Color bgColor)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = bgColor;
        var btn = go.AddComponent<Button>();
        btn.targetGraphic = img;
        var colors = btn.colors;
        colors.highlightedColor = bgColor * 1.2f;
        colors.pressedColor = bgColor * 0.8f;
        btn.colors = colors;

        var textGo = new GameObject("Text");
        textGo.transform.SetParent(go.transform, false);
        var tmp = textGo.AddComponent<TextMeshProUGUI>();
        tmp.text = label;
        tmp.fontSize = 22;
        tmp.alignment = TextAlignmentOptions.Center;
        tmp.color = Color.white;
        SetAnchors(textGo.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var le = go.AddComponent<LayoutElement>();
        le.minHeight = 50;

        return go;
    }

    static GameObject CreateTMPInputField(Transform parent, string name, string defaultText)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = new Color(0.15f, 0.15f, 0.2f);

        var textArea = new GameObject("Text Area");
        textArea.transform.SetParent(go.transform, false);
        textArea.AddComponent<RectMask2D>();
        SetAnchors(textArea.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var placeholder = new GameObject("Placeholder");
        placeholder.transform.SetParent(textArea.transform, false);
        var phTmp = placeholder.AddComponent<TextMeshProUGUI>();
        phTmp.text = defaultText;
        phTmp.fontSize = 18;
        phTmp.fontStyle = FontStyles.Italic;
        phTmp.color = new Color(0.5f, 0.5f, 0.5f, 0.8f);
        phTmp.alignment = TextAlignmentOptions.Left;
        SetAnchors(placeholder.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var inputText = new GameObject("Text");
        inputText.transform.SetParent(textArea.transform, false);
        var itTmp = inputText.AddComponent<TextMeshProUGUI>();
        itTmp.fontSize = 18;
        itTmp.color = Color.white;
        itTmp.alignment = TextAlignmentOptions.Left;
        SetAnchors(inputText.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var inputField = go.AddComponent<TMP_InputField>();
        inputField.textViewport = textArea.GetComponent<RectTransform>();
        inputField.textComponent = itTmp;
        inputField.placeholder = phTmp;
        inputField.text = defaultText;
        inputField.fontAsset = itTmp.font;

        return go;
    }
}
#endif
