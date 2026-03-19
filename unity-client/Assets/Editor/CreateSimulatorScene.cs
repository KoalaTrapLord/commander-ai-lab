#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.Reflection;
using System.Linq;

public static class CreateSimulatorScene
{
    [MenuItem("Tools/Create Simulator Scene")]
    public static void Create()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        // ── Services ──────────────────────────────────────────────────────────
        var services = new GameObject("[Services]");
        services.AddComponent<CommanderAILab.Services.ApiClient>();

        // ── Canvas ────────────────────────────────────────────────────────────
        var canvasGo = new GameObject("Canvas");
        var canvas   = canvasGo.AddComponent<Canvas>();
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

        // ── Background ────────────────────────────────────────────────────────
        CreatePanel(canvasGo.transform, "Background", new Color(0.08f, 0.08f, 0.12f), stretch: true);

        // ── Header (Top Bar) ──────────────────────────────────────────────────
        var header = CreatePanel(canvasGo.transform, "Header", new Color(0.12f, 0.12f, 0.18f, 0.95f));
        SetAnchors(header.GetComponent<RectTransform>(), new Vector2(0f, 0.93f), new Vector2(1f, 1f));

        var backBtn = CreateTMPButton(header.transform, "BackButton", "< Back", new Color(0.2f, 0.2f, 0.3f));
        SetAnchors(backBtn.GetComponent<RectTransform>(), new Vector2(0.01f, 0.1f), new Vector2(0.08f, 0.9f));

        var titleTxt = CreateTMPText(header.transform, "TitleText", "Simulator", 28, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(titleTxt.GetComponent<RectTransform>(), new Vector2(0.3f, 0.1f), new Vector2(0.7f, 0.9f));

        var startSimBtn = CreateTMPButton(header.transform, "StartSimButton", "Start Simulation", new Color(0.2f, 0.55f, 0.2f));
        SetAnchors(startSimBtn.GetComponent<RectTransform>(), new Vector2(0.82f, 0.1f), new Vector2(0.99f, 0.9f));

        // ── Config Panel (left) ───────────────────────────────────────────────
        var configPanel = CreatePanel(canvasGo.transform, "ConfigPanel", new Color(0.1f, 0.1f, 0.16f, 0.97f));
        SetAnchors(configPanel.GetComponent<RectTransform>(), new Vector2(0.01f, 0.3f), new Vector2(0.49f, 0.93f));
        var cfgVlg = configPanel.AddComponent<VerticalLayoutGroup>();
        cfgVlg.padding = new RectOffset(16, 16, 16, 16);
        cfgVlg.spacing = 10;
        cfgVlg.childForceExpandWidth  = true;
        cfgVlg.childForceExpandHeight = false;

        CreateTMPText(configPanel.transform, "ConfigTitle", "Simulation Config", 20, FontStyles.Bold, TextAlignmentOptions.Center);

        // Deck dropdowns
        var deckDropdown0 = CreateTMPDropdown(configPanel.transform, "DeckDropdown0", new[] { "-- Select Deck --" });
        var deckDropdown1 = CreateTMPDropdown(configPanel.transform, "DeckDropdown1", new[] { "-- Select Deck --" });
        var deckDropdown2 = CreateTMPDropdown(configPanel.transform, "DeckDropdown2", new[] { "-- Select Deck --" });
        var deckDropdown3 = CreateTMPDropdown(configPanel.transform, "DeckDropdown3", new[] { "-- Select Deck --" });

        // Num players slider
        var numPlayersLabel = CreateTMPText(configPanel.transform, "NumPlayersLabel", "Players: 2", 16, FontStyles.Normal, TextAlignmentOptions.Left);
        var numPlayersSlider = CreateSlider(configPanel.transform, "NumPlayersSlider");

        // Num games input
        CreateTMPText(configPanel.transform, "NumGamesLabel", "Number of Games:", 16, FontStyles.Normal, TextAlignmentOptions.Left);
        var numGamesInput = CreateTMPInputField(configPanel.transform, "NumGamesInput", "100");

        // Threads input
        CreateTMPText(configPanel.transform, "ThreadsLabel", "Threads:", 16, FontStyles.Normal, TextAlignmentOptions.Left);
        var threadsInput = CreateTMPInputField(configPanel.transform, "ThreadsInput", "4");

        // AI Profile dropdown
        CreateTMPText(configPanel.transform, "AiProfileLabel", "AI Profile:", 16, FontStyles.Normal, TextAlignmentOptions.Left);
        var aiProfileDropdown = CreateTMPDropdown(configPanel.transform, "AiProfileDropdown", new[] { "Default" });

        // ── Status Panel (center, hidden initially) ───────────────────────────
        var statusPanel = CreatePanel(canvasGo.transform, "StatusPanel", new Color(0.09f, 0.09f, 0.14f, 0.97f));
        SetAnchors(statusPanel.GetComponent<RectTransform>(), new Vector2(0.01f, 0.06f), new Vector2(0.49f, 0.29f));
        statusPanel.SetActive(false);
        var stVlg = statusPanel.AddComponent<VerticalLayoutGroup>();
        stVlg.padding = new RectOffset(12, 12, 10, 10);
        stVlg.spacing = 6;
        stVlg.childForceExpandWidth  = true;
        stVlg.childForceExpandHeight = false;

        var statusText   = CreateTMPText(statusPanel.transform, "StatusText",     "Ready",   16, FontStyles.Normal, TextAlignmentOptions.TopLeft);
        var progressBar  = CreateSlider(statusPanel.transform, "ProgressBar");
        var progressText = CreateTMPText(statusPanel.transform, "ProgressText",   "0%",      14, FontStyles.Normal, TextAlignmentOptions.Center);
        var elapsedText  = CreateTMPText(statusPanel.transform, "ElapsedText",    "Elapsed: 0s", 14, FontStyles.Normal, TextAlignmentOptions.Left);
        var simsPerSecText = CreateTMPText(statusPanel.transform, "SimsPerSecText", "0 sims/s", 14, FontStyles.Normal, TextAlignmentOptions.Left);

        // ── Results Panel (right, hidden initially) ───────────────────────────
        var resultsPanel = CreatePanel(canvasGo.transform, "ResultsPanel", new Color(0.1f, 0.1f, 0.16f, 0.97f));
        SetAnchors(resultsPanel.GetComponent<RectTransform>(), new Vector2(0.51f, 0.06f), new Vector2(0.99f, 0.93f));
        resultsPanel.SetActive(false);

        CreateTMPText(resultsPanel.transform, "ResultsTitle", "Results", 22, FontStyles.Bold, TextAlignmentOptions.Center);
        var winnerText = CreateTMPText(resultsPanel.transform, "WinnerText", "Winner: —", 18, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(winnerText.GetComponent<RectTransform>(), new Vector2(0f, 0.88f), new Vector2(1f, 0.95f));

        // Results scroll view
        var resultsScroll = new GameObject("ResultsScroll");
        resultsScroll.transform.SetParent(resultsPanel.transform, false);
        SetAnchors(resultsScroll.GetComponent<RectTransform>(), new Vector2(0f, 0.15f), new Vector2(1f, 0.88f));
        ScrollRect resSr;
        var resultsContent = CreateScrollContent(resultsScroll, out resSr);

        var historyBtn = CreateTMPButton(resultsPanel.transform, "HistoryButton", "View History", new Color(0.2f, 0.4f, 0.7f));
        SetAnchors(historyBtn.GetComponent<RectTransform>(), new Vector2(0.2f, 0.03f), new Vector2(0.8f, 0.13f));

        // ── Error Panel (hidden initially) ────────────────────────────────────
        var errorPanel = CreatePanel(canvasGo.transform, "ErrorPanel", new Color(0.15f, 0.05f, 0.05f, 0.97f));
        SetAnchors(errorPanel.GetComponent<RectTransform>(), new Vector2(0.25f, 0.35f), new Vector2(0.75f, 0.65f));
        errorPanel.SetActive(false);

        CreateTMPText(errorPanel.transform, "ErrorTitle", "Error", 22, FontStyles.Bold, TextAlignmentOptions.Center);
        var errorText  = CreateTMPText(errorPanel.transform, "ErrorText", "", 16, FontStyles.Normal, TextAlignmentOptions.TopLeft);
        SetAnchors(errorText.GetComponent<RectTransform>(), new Vector2(0.05f, 0.25f), new Vector2(0.95f, 0.85f));
        var retryBtn = CreateTMPButton(errorPanel.transform, "RetryButton", "Retry", new Color(0.55f, 0.2f, 0.2f));
        SetAnchors(retryBtn.GetComponent<RectTransform>(), new Vector2(0.3f, 0.05f), new Vector2(0.7f, 0.22f));

        // ── Result Row Prefab (disabled child object used as prefab) ──────────
        var resultRowPrefab = new GameObject("ResultRowPrefab");
        resultRowPrefab.transform.SetParent(canvasGo.transform, false);
        resultRowPrefab.SetActive(false);
        var rowImg = resultRowPrefab.AddComponent<Image>();
        rowImg.color = new Color(0.15f, 0.15f, 0.2f, 0.9f);
        var rowHlg = resultRowPrefab.AddComponent<HorizontalLayoutGroup>();
        rowHlg.padding = new RectOffset(8, 8, 4, 4);
        rowHlg.spacing = 12;
        rowHlg.childForceExpandWidth  = false;
        rowHlg.childForceExpandHeight = true;
        var rowLe = resultRowPrefab.AddComponent<LayoutElement>();
        rowLe.minHeight = 40;

        string[] colNames  = { "DeckName", "WinRate", "Wins", "Losses" };
        float[]  colWidths = { 300f,        120f,      100f,   100f };
        for (int i = 0; i < colNames.Length; i++)
        {
            var cell = new GameObject(colNames[i]);
            cell.transform.SetParent(resultRowPrefab.transform, false);
            var cellTxt = cell.AddComponent<TextMeshProUGUI>();
            cellTxt.text      = colNames[i];
            cellTxt.fontSize  = 16;
            cellTxt.color     = Color.white;
            cellTxt.alignment = TextAlignmentOptions.Left;
            var cellLe = cell.AddComponent<LayoutElement>();
            cellLe.minWidth           = colWidths[i];
            cellLe.preferredWidth     = colWidths[i];
            cellLe.flexibleWidth      = i == 0 ? 1f : 0f;
        }

        // ── Wire SimulationController via reflection ───────────────────────────
        var controllerGo = new GameObject("SimulationController");
        controllerGo.transform.SetParent(canvasGo.transform, false);
        var controller = controllerGo.AddComponent<CommanderAILab.UI.SimulationController>();

        SetField(controller, "backButton",       backBtn.GetComponent<Button>());
        SetField(controller, "startSimButton",   startSimBtn.GetComponent<Button>());

        SetField(controller, "deckDropdown0",    deckDropdown0.GetComponent<TMP_Dropdown>());
        SetField(controller, "deckDropdown1",    deckDropdown1.GetComponent<TMP_Dropdown>());
        SetField(controller, "deckDropdown2",    deckDropdown2.GetComponent<TMP_Dropdown>());
        SetField(controller, "deckDropdown3",    deckDropdown3.GetComponent<TMP_Dropdown>());
        SetField(controller, "numGamesInput",    numGamesInput.GetComponent<TMP_InputField>());
        SetField(controller, "numPlayersSlider", numPlayersSlider.GetComponent<Slider>());
        SetField(controller, "numPlayersLabel",  numPlayersLabel.GetComponent<TMP_Text>());
        SetField(controller, "threadsInput",     threadsInput.GetComponent<TMP_InputField>());
        SetField(controller, "aiProfileDropdown", aiProfileDropdown.GetComponent<TMP_Dropdown>());

        SetField(controller, "statusText",       statusText.GetComponent<TMP_Text>());
        SetField(controller, "progressBar",      progressBar.GetComponent<Slider>());
        SetField(controller, "progressText",     progressText.GetComponent<TMP_Text>());
        SetField(controller, "elapsedText",      elapsedText.GetComponent<TMP_Text>());
        SetField(controller, "simsPerSecText",   simsPerSecText.GetComponent<TMP_Text>());

        SetField(controller, "resultsParent",    resultsContent);
        SetField(controller, "resultRowPrefab",  resultRowPrefab);
        SetField(controller, "winnerText",       winnerText.GetComponent<TMP_Text>());
        SetField(controller, "historyButton",    historyBtn.GetComponent<Button>());

        SetField(controller, "errorPanel",       errorPanel);
        SetField(controller, "errorText",        errorText.GetComponent<TMP_Text>());
        SetField(controller, "retryButton",      retryBtn.GetComponent<Button>());

        // ── Save ──────────────────────────────────────────────────────────────
        if (!AssetDatabase.IsValidFolder("Assets/Scenes"))
            AssetDatabase.CreateFolder("Assets", "Scenes");
        string path = "Assets/Scenes/Simulator.unity";
        EditorSceneManager.SaveScene(scene, path);
        var existing = new System.Collections.Generic.List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
        if (!existing.Any(s => s.path == path))
            existing.Add(new EditorBuildSettingsScene(path, true));
        EditorBuildSettings.scenes = existing.ToArray();
        Debug.Log("[CreateSimulatorScene] Simulator scene created and saved to " + path);
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    static void SetField(object target, string fieldName, object value)
    {
        var field = target.GetType().GetField(fieldName,
            BindingFlags.NonPublic | BindingFlags.Instance);
        if (field != null) field.SetValue(target, value);
        else Debug.LogWarning("[CreateSimulatorScene] Could not find field: " + fieldName);
    }

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
        tmp.text      = text;
        tmp.fontSize  = fontSize;
        tmp.fontStyle = style;
        tmp.alignment = alignment;
        tmp.color     = Color.white;
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
        colors.pressedColor     = bgColor * 0.8f;
        btn.colors = colors;

        var textGo = new GameObject("Text");
        textGo.transform.SetParent(go.transform, false);
        var tmp = textGo.AddComponent<TextMeshProUGUI>();
        tmp.text      = label;
        tmp.fontSize  = 22;
        tmp.alignment = TextAlignmentOptions.Center;
        tmp.color     = Color.white;
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
        phTmp.text      = defaultText;
        phTmp.fontSize  = 18;
        phTmp.fontStyle = FontStyles.Italic;
        phTmp.color     = new Color(0.5f, 0.5f, 0.5f, 0.8f);
        phTmp.alignment = TextAlignmentOptions.Left;
        SetAnchors(placeholder.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var inputText = new GameObject("Text");
        inputText.transform.SetParent(textArea.transform, false);
        var itTmp = inputText.AddComponent<TextMeshProUGUI>();
        itTmp.fontSize  = 18;
        itTmp.color     = Color.white;
        itTmp.alignment = TextAlignmentOptions.Left;
        SetAnchors(inputText.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var inputField = go.AddComponent<TMP_InputField>();
        inputField.textViewport = textArea.GetComponent<RectTransform>();
        inputField.textComponent = itTmp;
        inputField.placeholder  = phTmp;
        inputField.text         = defaultText;
        inputField.fontAsset    = itTmp.font;

        var le = go.AddComponent<LayoutElement>();
        le.minHeight = 45;

        return go;
    }

    static GameObject CreateTMPDropdown(Transform parent, string name, string[] options)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = new Color(0.15f, 0.15f, 0.2f);

        var labelGo = new GameObject("Label");
        labelGo.transform.SetParent(go.transform, false);
        var labelTmp = labelGo.AddComponent<TextMeshProUGUI>();
        labelTmp.text      = options.Length > 0 ? options[0] : "";
        labelTmp.fontSize  = 16;
        labelTmp.alignment = TextAlignmentOptions.Left;
        labelTmp.color     = Color.white;
        SetAnchors(labelGo.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var dd = go.AddComponent<TMP_Dropdown>();
        dd.captionText = labelTmp;
        dd.ClearOptions();
        dd.AddOptions(new System.Collections.Generic.List<string>(options));

        var le = go.AddComponent<LayoutElement>();
        le.minHeight = 40;

        return go;
    }

    static GameObject CreateSlider(Transform parent, string name)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);

        // Background track
        var bg = new GameObject("Background");
        bg.transform.SetParent(go.transform, false);
        var bgImg = bg.AddComponent<Image>();
        bgImg.color = new Color(0.2f, 0.2f, 0.25f);
        SetAnchors(bg.GetComponent<RectTransform>(), new Vector2(0f, 0.25f), new Vector2(1f, 0.75f));

        // Fill area
        var fillArea = new GameObject("Fill Area");
        fillArea.transform.SetParent(go.transform, false);
        SetAnchors(fillArea.GetComponent<RectTransform>(), new Vector2(0f, 0.25f), new Vector2(1f, 0.75f));

        var fill = new GameObject("Fill");
        fill.transform.SetParent(fillArea.transform, false);
        var fillImg = fill.AddComponent<Image>();
        fillImg.color = new Color(0.2f, 0.6f, 0.3f);
        var fillRt = fill.GetComponent<RectTransform>();
        fillRt.anchorMin = Vector2.zero;
        fillRt.anchorMax = Vector2.one;
        fillRt.offsetMin = Vector2.zero;
        fillRt.offsetMax = Vector2.zero;

        // Handle
        var handleArea = new GameObject("Handle Slide Area");
        handleArea.transform.SetParent(go.transform, false);
        SetAnchors(handleArea.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var handle = new GameObject("Handle");
        handle.transform.SetParent(handleArea.transform, false);
        var handleImg = handle.AddComponent<Image>();
        handleImg.color = new Color(0.8f, 0.8f, 0.9f);
        var handleRt = handle.GetComponent<RectTransform>();
        handleRt.sizeDelta = new Vector2(20f, 20f);

        var slider = go.AddComponent<Slider>();
        slider.fillRect   = fillRt;
        slider.handleRect = handleRt;
        slider.targetGraphic = handleImg;
        slider.direction  = Slider.Direction.LeftToRight;
        slider.minValue   = 0f;
        slider.maxValue   = 1f;
        slider.value      = 0f;

        var le = go.AddComponent<LayoutElement>();
        le.minHeight = 30;

        return go;
    }

    /// <summary>
    /// Creates a Viewport + Content hierarchy inside the given scroll GameObject,
    /// wires up the ScrollRect, and returns the Content RectTransform.
    /// </summary>
    static RectTransform CreateScrollContent(GameObject scrollGo, out ScrollRect scrollRect)
    {
        scrollRect = scrollGo.GetComponent<ScrollRect>();
        if (scrollRect == null)
            scrollRect = scrollGo.AddComponent<ScrollRect>();

        var viewport = new GameObject("Viewport");
        viewport.transform.SetParent(scrollGo.transform, false);
        viewport.AddComponent<RectMask2D>();
        var vpRect = viewport.GetComponent<RectTransform>();
        vpRect.anchorMin = Vector2.zero;
        vpRect.anchorMax = Vector2.one;
        vpRect.offsetMin = Vector2.zero;
        vpRect.offsetMax = Vector2.zero;

        var content = new GameObject("Content");
        content.transform.SetParent(viewport.transform, false);
        var contentRect = content.AddComponent<RectTransform>();
        contentRect.anchorMin = new Vector2(0f, 1f);
        contentRect.anchorMax = new Vector2(1f, 1f);
        contentRect.pivot     = new Vector2(0.5f, 1f);
        contentRect.offsetMin = Vector2.zero;
        contentRect.offsetMax = Vector2.zero;
        content.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        var vlg = content.AddComponent<VerticalLayoutGroup>();
        vlg.spacing = 4;
        vlg.padding = new RectOffset(4, 4, 4, 4);
        vlg.childForceExpandWidth  = true;
        vlg.childForceExpandHeight = false;

        scrollRect.viewport   = vpRect;
        scrollRect.content    = contentRect;
        scrollRect.horizontal = false;

        return contentRect;
    }
}
#endif
