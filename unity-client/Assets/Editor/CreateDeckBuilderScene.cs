#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.Reflection;
using System.Linq;

public static class CreateDeckBuilderScene
{
    [MenuItem("Tools/Create DeckBuilder Scene")]
    public static void Create()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        // Services
        var services = new GameObject("[Services]");
        services.AddComponent<CommanderAILab.Services.ApiClient>();
        services.AddComponent<CommanderAILab.Services.ImageCache>();

        // Canvas
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

        // Background
        var bg = CreatePanel(canvasGo.transform, "Background", new Color(0.08f, 0.08f, 0.12f), stretch: true);

        // Header
        var header = CreatePanel(canvasGo.transform, "Header", new Color(0.12f, 0.12f, 0.18f, 0.95f));
        SetAnchors(header.GetComponent<RectTransform>(), new Vector2(0f, 0.93f), new Vector2(1f, 1f));
        var backBtn = CreateTMPButton(header.transform, "BackButton", "< Back", new Color(0.2f, 0.2f, 0.3f));
        SetAnchors(backBtn.GetComponent<RectTransform>(), new Vector2(0.01f, 0.1f), new Vector2(0.07f, 0.9f));
        var titleTxt = CreateTMPText(header.transform, "TitleText", "Deck Builder", 28, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(titleTxt.GetComponent<RectTransform>(), new Vector2(0.3f, 0.1f), new Vector2(0.7f, 0.9f));
        var exportBtn = CreateTMPButton(header.transform, "ExportToSimButton", "Export to Sim", new Color(0.2f, 0.45f, 0.7f));
        SetAnchors(exportBtn.GetComponent<RectTransform>(), new Vector2(0.88f, 0.1f), new Vector2(0.99f, 0.9f));

        // ── LEFT: Deck List Panel ──────────────────────────────────────
        var leftPanel = CreatePanel(canvasGo.transform, "DeckListPanel", new Color(0.1f, 0.1f, 0.16f, 0.97f));
        SetAnchors(leftPanel.GetComponent<RectTransform>(), new Vector2(0f, 0.06f), new Vector2(0.22f, 0.93f));

        var deckNameInput = CreateTMPInputField(leftPanel.transform, "DeckNameInput", "New deck name...");
        SetAnchors(deckNameInput.GetComponent<RectTransform>(), new Vector2(0.02f, 0.91f), new Vector2(0.75f, 0.98f));
        var newDeckBtn = CreateTMPButton(leftPanel.transform, "NewDeckButton", "+", new Color(0.2f, 0.55f, 0.2f));
        SetAnchors(newDeckBtn.GetComponent<RectTransform>(), new Vector2(0.77f, 0.91f), new Vector2(0.98f, 0.98f));

        var deckScroll = new GameObject("DeckListScroll");
        deckScroll.transform.SetParent(leftPanel.transform, false);
        var dsr = deckScroll.AddComponent<ScrollRect>();
        deckScroll.AddComponent<Image>().color = new Color(0,0,0,0.01f);
        SetAnchors(deckScroll.GetComponent<RectTransform>(), new Vector2(0f, 0f), new Vector2(1f, 0.9f));
        var deckContent = new GameObject("Content");
        deckContent.transform.SetParent(deckScroll.transform, false);
        var dcrect = deckContent.AddComponent<RectTransform>();
        dcrect.anchorMin = new Vector2(0,1); dcrect.anchorMax = new Vector2(1,1); dcrect.pivot = new Vector2(0.5f,1f);
        deckContent.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        var dcvlg = deckContent.AddComponent<VerticalLayoutGroup>();
        dcvlg.spacing = 4; dcvlg.padding = new RectOffset(4,4,4,4);
        dcvlg.childForceExpandWidth = true; dcvlg.childForceExpandHeight = false;
        dsr.content = dcrect; dsr.horizontal = false;

        // ── CENTER: Active Deck Panel ──────────────────────────────────
        var centerPanel = CreatePanel(canvasGo.transform, "ActiveDeckPanel", new Color(0.09f, 0.09f, 0.14f, 0.97f));
        SetAnchors(centerPanel.GetComponent<RectTransform>(), new Vector2(0.22f, 0.06f), new Vector2(0.58f, 0.93f));

        var deckTitleTxt = CreateTMPText(centerPanel.transform, "DeckTitleText", "Select a Deck", 22, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(deckTitleTxt.GetComponent<RectTransform>(), new Vector2(0f, 0.93f), new Vector2(0.7f, 1f));
        var cardCountTxt = CreateTMPText(centerPanel.transform, "CardCountText", "0 / 100", 18, FontStyles.Normal, TextAlignmentOptions.Right);
        SetAnchors(cardCountTxt.GetComponent<RectTransform>(), new Vector2(0.7f, 0.93f), new Vector2(1f, 1f));

        var validIndic = CreatePanel(centerPanel.transform, "ValidationIndicator", new Color(0.7f, 0.2f, 0.2f));
        SetAnchors(validIndic.GetComponent<RectTransform>(), new Vector2(0f, 0.88f), new Vector2(0.12f, 0.93f));
        var validTxt = CreateTMPText(centerPanel.transform, "ValidationText", "100 cards needed", 14, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(validTxt.GetComponent<RectTransform>(), new Vector2(0.13f, 0.88f), new Vector2(1f, 0.93f));

        // Commander
        var cmdInput = CreateTMPInputField(centerPanel.transform, "CommanderSearchInput", "Search commander...");
        SetAnchors(cmdInput.GetComponent<RectTransform>(), new Vector2(0.01f, 0.81f), new Vector2(0.65f, 0.87f));
        var cmdSearchBtn = CreateTMPButton(centerPanel.transform, "CommanderSearchButton", "Find", new Color(0.25f, 0.45f, 0.65f));
        SetAnchors(cmdSearchBtn.GetComponent<RectTransform>(), new Vector2(0.66f, 0.81f), new Vector2(0.82f, 0.87f));
        var colorIdDd = CreateTMPDropdown(centerPanel.transform, "ColorIdentityDropdown", new[]{"Any","W","U","B","R","G","WU","WB","WR","WG","UB","UR","UG","BR","BG","RG"});
        SetAnchors(colorIdDd.GetComponent<RectTransform>(), new Vector2(0.01f, 0.75f), new Vector2(0.98f, 0.81f));
        var cmdResultScroll = new GameObject("CommanderResultScroll");
        cmdResultScroll.transform.SetParent(centerPanel.transform, false);
        var cmrsr = cmdResultScroll.AddComponent<ScrollRect>();
        cmdResultScroll.AddComponent<Image>().color = new Color(0,0,0,0.01f);
        SetAnchors(cmdResultScroll.GetComponent<RectTransform>(), new Vector2(0f, 0.66f), new Vector2(1f, 0.75f));
        var cmdContent = CreateScrollContent(cmdResultScroll, out cmrsr);
        var selCmdTxt = CreateTMPText(centerPanel.transform, "SelectedCommanderText", "Commander: None", 15, FontStyles.Italic, TextAlignmentOptions.Left);
        SetAnchors(selCmdTxt.GetComponent<RectTransform>(), new Vector2(0.01f, 0.62f), new Vector2(0.98f, 0.66f));

        // Deck card list
        var deckCardScroll = new GameObject("DeckCardListScroll");
        deckCardScroll.transform.SetParent(centerPanel.transform, false);
        SetAnchors(deckCardScroll.GetComponent<RectTransform>(), new Vector2(0f, 0.12f), new Vector2(1f, 0.62f));
        var dclsr = deckCardScroll.AddComponent<ScrollRect>();
        deckCardScroll.AddComponent<Image>().color = new Color(0,0,0,0.01f);
        var deckCardContent = CreateScrollContent(deckCardScroll, out dclsr);

        var saveDeckBtn = CreateTMPButton(centerPanel.transform, "SaveDeckButton", "Save", new Color(0.2f, 0.55f, 0.2f));
        SetAnchors(saveDeckBtn.GetComponent<RectTransform>(), new Vector2(0.02f, 0.03f), new Vector2(0.35f, 0.11f));
        var deleteDeckBtn = CreateTMPButton(centerPanel.transform, "DeleteDeckButton", "Delete Deck", new Color(0.55f, 0.15f, 0.15f));
        SetAnchors(deleteDeckBtn.GetComponent<RectTransform>(), new Vector2(0.37f, 0.03f), new Vector2(0.7f, 0.11f));

        // ── RIGHT: Card Search + Charts ────────────────────────────────
        var rightPanel = CreatePanel(canvasGo.transform, "CardSearchPanel", new Color(0.1f, 0.1f, 0.16f, 0.97f));
        SetAnchors(rightPanel.GetComponent<RectTransform>(), new Vector2(0.58f, 0.06f), new Vector2(1f, 0.93f));

        var cardSearchInput = CreateTMPInputField(rightPanel.transform, "CardSearchInput", "Search cards...");
        SetAnchors(cardSearchInput.GetComponent<RectTransform>(), new Vector2(0.01f, 0.92f), new Vector2(0.72f, 0.99f));
        var cardSearchBtn = CreateTMPButton(rightPanel.transform, "CardSearchButton", "Search", new Color(0.2f, 0.5f, 0.8f));
        SetAnchors(cardSearchBtn.GetComponent<RectTransform>(), new Vector2(0.73f, 0.92f), new Vector2(0.99f, 0.99f));

        var cardResultScroll = new GameObject("CardSearchResultScroll");
        cardResultScroll.transform.SetParent(rightPanel.transform, false);
        SetAnchors(cardResultScroll.GetComponent<RectTransform>(), new Vector2(0f, 0.55f), new Vector2(1f, 0.92f));
        var crsr = cardResultScroll.AddComponent<ScrollRect>();
        cardResultScroll.AddComponent<Image>().color = new Color(0,0,0,0.01f);
        var cardResultContent = CreateScrollContent(cardResultScroll, out crsr);

        // Mana curve
        var manaCurveLabel = CreateTMPText(rightPanel.transform, "ManaCurveLabel", "Mana Curve", 16, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(manaCurveLabel.GetComponent<RectTransform>(), new Vector2(0f, 0.49f), new Vector2(1f, 0.54f));
        var manaCurveParent = new GameObject("ManaCurveBarParent");
        manaCurveParent.transform.SetParent(rightPanel.transform, false);
        SetAnchors(manaCurveParent.GetComponent<RectTransform>(), new Vector2(0.02f, 0.33f), new Vector2(0.98f, 0.49f));
        var manaHlg = manaCurveParent.AddComponent<HorizontalLayoutGroup>();
        manaHlg.spacing = 4; manaHlg.childForceExpandWidth = true; manaHlg.childForceExpandHeight = false;

        // Color pie
        var colorPieLabel = CreateTMPText(rightPanel.transform, "ColorPieLabel", "Color Identity", 16, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(colorPieLabel.GetComponent<RectTransform>(), new Vector2(0f, 0.27f), new Vector2(1f, 0.32f));
        var colorPieParent = new GameObject("ColorPieParent");
        colorPieParent.transform.SetParent(rightPanel.transform, false);
        SetAnchors(colorPieParent.GetComponent<RectTransform>(), new Vector2(0.02f, 0.13f), new Vector2(0.98f, 0.27f));
        var pieHlg = colorPieParent.AddComponent<HorizontalLayoutGroup>();
        pieHlg.spacing = 6; pieHlg.childForceExpandWidth = true; pieHlg.childForceExpandHeight = false;
        Color[] pieColors = { Color.white, new Color(0.3f,0.6f,1f), new Color(0.1f,0.1f,0.1f), new Color(0.8f,0.2f,0.2f), new Color(0.2f,0.7f,0.2f) };
        string[] pieLabels = { "W", "U", "B", "R", "G" };
        for (int i = 0; i < pieColors.Length; i++)
        {
            var slice = new GameObject("Slice_" + pieLabels[i]);
            slice.transform.SetParent(colorPieParent.transform, false);
            var sliceImg = slice.AddComponent<Image>();
            sliceImg.color = pieColors[i];
            var sliceText = CreateTMPText(slice.transform, "Label", pieLabels[i], 14, FontStyles.Bold, TextAlignmentOptions.Center);
        }

        // -- Card type breakdown --
        var typeLabel = CreateTMPText(rightPanel.transform, "TypeBreakdownLabel", "Card Types", 16, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(typeLabel.GetComponent<RectTransform>(), new Vector2(0f, 0.08f), new Vector2(1f, 0.13f));
        var typeText = CreateTMPText(rightPanel.transform, "TypeBreakdownText", "", 14, FontStyles.Normal, TextAlignmentOptions.TopLeft);
        SetAnchors(typeText.GetComponent<RectTransform>(), new Vector2(0.05f, 0.01f), new Vector2(0.95f, 0.08f));

        // -- Save --
        if (!AssetDatabase.IsValidFolder("Assets/Scenes"))
            AssetDatabase.CreateFolder("Assets", "Scenes");
        string path = "Assets/Scenes/DeckBuilder.unity";
        EditorSceneManager.SaveScene(scene, path);
        var existing = new System.Collections.Generic.List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
        if (!existing.Any(s => s.path == path))
            existing.Add(new EditorBuildSettingsScene(path, true));
        EditorBuildSettings.scenes = existing.ToArray();
        Debug.Log("[CreateDeckBuilderScene] DeckBuilder scene created and saved to " + path);
    }

    // -- Helpers --

    /// <summary>
    /// Creates a Viewport + Content hierarchy inside the given scroll GameObject,
    /// wires up the ScrollRect, and returns the Content RectTransform.
    /// </summary>
    static RectTransform CreateScrollContent(GameObject scrollGo, out ScrollRect scrollRect)
    {
        scrollRect = scrollGo.GetComponent<ScrollRect>();
        if (scrollRect == null)
            scrollRect = scrollGo.AddComponent<ScrollRect>();

        // Viewport
        var viewport = new GameObject("Viewport");
        viewport.transform.SetParent(scrollGo.transform, false);
        viewport.AddComponent<RectMask2D>();
        var vpRect = viewport.GetComponent<RectTransform>();
        vpRect.anchorMin = Vector2.zero;
        vpRect.anchorMax = Vector2.one;
        vpRect.offsetMin = Vector2.zero;
        vpRect.offsetMax = Vector2.zero;

        // Content
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

        scrollRect.viewport  = vpRect;
        scrollRect.content   = contentRect;
        scrollRect.horizontal = false;

        return contentRect;
    }

    static void SetField(object target, string fieldName, object value)
    {
        var field = target.GetType().GetField(fieldName, BindingFlags.NonPublic | BindingFlags.Instance);
        if (field != null) field.SetValue(target, value);
        else Debug.LogWarning("Could not find field: " + fieldName);
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

    static GameObject CreateTMPDropdown(Transform parent, string name, string[] options)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = new Color(0.15f, 0.15f, 0.2f);

        var labelGo = new GameObject("Label");
        labelGo.transform.SetParent(go.transform, false);
        var labelTmp = labelGo.AddComponent<TextMeshProUGUI>();
        labelTmp.text = options.Length > 0 ? options[0] : "";
        labelTmp.fontSize = 16;
        labelTmp.alignment = TextAlignmentOptions.Left;
        labelTmp.color = Color.white;
        SetAnchors(labelGo.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        var dd = go.AddComponent<TMP_Dropdown>();
        dd.captionText = labelTmp;
        dd.ClearOptions();
        dd.AddOptions(new System.Collections.Generic.List<string>(options));

        var le = go.AddComponent<LayoutElement>();
        le.minHeight = 40;

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
