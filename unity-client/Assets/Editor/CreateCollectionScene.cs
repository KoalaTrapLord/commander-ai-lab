#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.Reflection;
using System.Linq;

public static class CreateCollectionScene
{
    [MenuItem("Tools/Create Collection Scene")]
    public static void Create()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        // -- Services --
        var services = new GameObject("[Services]");
        services.AddComponent<CommanderAILab.Services.ApiClient>();
        services.AddComponent<CommanderAILab.Services.ImageCache>();

        // -- Canvas --
        var canvasGo = new GameObject("Canvas");
        var canvas = canvasGo.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        var scaler = canvasGo.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1920, 1080);
        canvasGo.AddComponent<GraphicRaycaster>();

        // -- EventSystem --
        if (Object.FindObjectOfType<UnityEngine.EventSystems.EventSystem>() == null)
        {
            var es = new GameObject("EventSystem");
            es.AddComponent<UnityEngine.EventSystems.EventSystem>();
            es.AddComponent<UnityEngine.EventSystems.StandaloneInputModule>();
        }

        // -- Background --
        var bg = CreatePanel(canvasGo.transform, "Background", new Color(0.08f, 0.08f, 0.12f), stretch: true);

        // -- Header bar --
        var header = CreatePanel(canvasGo.transform, "Header", new Color(0.12f, 0.12f, 0.18f, 0.95f));
        SetAnchors(header.GetComponent<RectTransform>(), new Vector2(0f, 0.93f), new Vector2(1f, 1f));

        var backBtn = CreateTMPButton(header.transform, "BackButton", "< Back", new Color(0.2f, 0.2f, 0.3f));
        SetAnchors(backBtn.GetComponent<RectTransform>(), new Vector2(0.01f, 0.1f), new Vector2(0.07f, 0.9f));

        var titleText = CreateTMPText(header.transform, "TitleText", "Collection", 28, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(titleText.GetComponent<RectTransform>(), new Vector2(0.3f, 0.1f), new Vector2(0.7f, 0.9f));

        // -- Search bar --
        var searchBar = CreatePanel(canvasGo.transform, "SearchBar", new Color(0.1f, 0.1f, 0.16f, 0.98f));
        SetAnchors(searchBar.GetComponent<RectTransform>(), new Vector2(0.18f, 0.86f), new Vector2(1f, 0.93f));

        var searchInput = CreateTMPInputField(searchBar.transform, "SearchInput", "Search cards...");
        SetAnchors(searchInput.GetComponent<RectTransform>(), new Vector2(0.01f, 0.1f), new Vector2(0.72f, 0.9f));

        var searchBtn = CreateTMPButton(searchBar.transform, "SearchButton", "Search", new Color(0.2f, 0.5f, 0.8f));
        SetAnchors(searchBtn.GetComponent<RectTransform>(), new Vector2(0.73f, 0.1f), new Vector2(0.86f, 0.9f));

        var sortDd = CreateTMPDropdown(searchBar.transform, "SortDropdown",
            new[] { "Name", "CMC", "Color", "Type", "Price" });
        SetAnchors(sortDd.GetComponent<RectTransform>(), new Vector2(0.87f, 0.05f), new Vector2(0.99f, 0.95f));

        // -- Filter toggle button (mobile) --
        var filterToggleBtn = CreateTMPButton(canvasGo.transform, "FilterToggleButton", "Filters", new Color(0.18f, 0.22f, 0.35f));
        SetAnchors(filterToggleBtn.GetComponent<RectTransform>(), new Vector2(0.01f, 0.86f), new Vector2(0.17f, 0.93f));

        // -- Filter sidebar --
        var filterPanel = CreatePanel(canvasGo.transform, "FilterPanel", new Color(0.1f, 0.1f, 0.16f, 0.97f));
        SetAnchors(filterPanel.GetComponent<RectTransform>(), new Vector2(0f, 0.06f), new Vector2(0.18f, 0.86f));
        var filterVlg = filterPanel.AddComponent<VerticalLayoutGroup>();
        filterVlg.padding = new RectOffset(8, 8, 8, 8);
        filterVlg.spacing = 6;
        filterVlg.childForceExpandWidth = true;
        filterVlg.childForceExpandHeight = false;

        CreateTMPText(filterPanel.transform, "FilterTitle", "Filters", 18, FontStyles.Bold, TextAlignmentOptions.Center);
        var colorDd   = CreateTMPDropdown(filterPanel.transform, "ColorFilterDropdown",   new[] { "All Colors", "W", "U", "B", "R", "G", "Colorless" });
        var typeDd    = CreateTMPDropdown(filterPanel.transform, "TypeFilterDropdown",    new[] { "All Types", "Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker", "Land" });
        var setDd     = CreateTMPDropdown(filterPanel.transform, "SetFilterDropdown",     new[] { "All Sets" });
        var rarityDd  = CreateTMPDropdown(filterPanel.transform, "RarityFilterDropdown",  new[] { "All Rarities", "Common", "Uncommon", "Rare", "Mythic" });
        var ownedDd   = CreateTMPDropdown(filterPanel.transform, "OwnedFilterDropdown",   new[] { "All", "Owned", "Missing" });
        var applyBtn  = CreateTMPButton(filterPanel.transform, "ApplyFilterButton", "Apply",  new Color(0.2f, 0.55f, 0.2f));
        var clearBtn  = CreateTMPButton(filterPanel.transform, "ClearFilterButton", "Clear",  new Color(0.45f, 0.2f, 0.2f));

        // -- Card grid scroll view --
        var scrollGo = new GameObject("CardGridScroll");
        scrollGo.transform.SetParent(canvasGo.transform, false);
        var scrollRect = scrollGo.AddComponent<ScrollRect>();
        var scrollImg  = scrollGo.AddComponent<Image>();
        scrollImg.color = new Color(0f, 0f, 0f, 0.01f);
        SetAnchors(scrollGo.GetComponent<RectTransform>(), new Vector2(0.18f, 0.12f), new Vector2(1f, 0.86f));

        var content = new GameObject("Content");
        content.transform.SetParent(scrollGo.transform, false);
        var contentRect = content.AddComponent<RectTransform>();
        contentRect.anchorMin = new Vector2(0f, 1f);
        contentRect.anchorMax = new Vector2(1f, 1f);
        contentRect.pivot     = new Vector2(0.5f, 1f);
        content.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        var grid = content.AddComponent<GridLayoutGroup>();
        grid.cellSize        = new Vector2(160, 220);
        grid.spacing         = new Vector2(8, 8);
        grid.padding         = new RectOffset(10, 10, 10, 10);
        grid.constraint      = GridLayoutGroup.Constraint.FixedColumnCount;
        grid.constraintCount = 6;

        scrollRect.content   = contentRect;
        scrollRect.horizontal = false;

        // -- Page info & load more --
        var pageInfoText = CreateTMPText(canvasGo.transform, "PageInfoText", "Showing 0 of 0 cards", 16, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(pageInfoText.GetComponent<RectTransform>(), new Vector2(0.18f, 0.08f), new Vector2(0.6f, 0.12f));

        var loadMoreBtn = CreateTMPButton(canvasGo.transform, "LoadMoreButton", "Load More", new Color(0.2f, 0.4f, 0.6f));
        SetAnchors(loadMoreBtn.GetComponent<RectTransform>(), new Vector2(0.62f, 0.08f), new Vector2(0.82f, 0.12f));

        // -- Loading spinner (simple panel) --
        var spinner = CreatePanel(canvasGo.transform, "LoadingSpinner", new Color(0f, 0f, 0f, 0.6f), stretch: true);
        CreateTMPText(spinner.transform, "SpinnerText", "Loading...", 32, FontStyles.Bold, TextAlignmentOptions.Center);
        spinner.SetActive(false);

        // -- Detail panel --
        var detailPanel = CreatePanel(canvasGo.transform, "DetailPanel", new Color(0.08f, 0.08f, 0.14f, 0.97f), stretch: true);
        var detailCardFront = new GameObject("DetailCardFront");
        detailCardFront.transform.SetParent(detailPanel.transform, false);
        var detailFrontImg = detailCardFront.AddComponent<Image>();
        SetAnchors(detailCardFront.GetComponent<RectTransform>(), new Vector2(0.05f, 0.15f), new Vector2(0.4f, 0.92f));

        var detailCardBack = new GameObject("DetailCardBack");
        detailCardBack.transform.SetParent(detailPanel.transform, false);
        detailCardBack.AddComponent<Image>().color = new Color(0.1f, 0.1f, 0.2f);
        SetAnchors(detailCardBack.GetComponent<RectTransform>(), new Vector2(0.05f, 0.15f), new Vector2(0.4f, 0.92f));

        var detailName    = CreateTMPText(detailPanel.transform, "DetailCardName",   "", 28, FontStyles.Bold,   TextAlignmentOptions.Left);
        SetAnchors(detailName.GetComponent<RectTransform>(),    new Vector2(0.42f, 0.78f), new Vector2(0.95f, 0.92f));
        var detailMana    = CreateTMPText(detailPanel.transform, "DetailManaCost",   "", 22, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(detailMana.GetComponent<RectTransform>(),    new Vector2(0.42f, 0.70f), new Vector2(0.95f, 0.78f));
        var detailType    = CreateTMPText(detailPanel.transform, "DetailType",       "", 20, FontStyles.Italic, TextAlignmentOptions.Left);
        SetAnchors(detailType.GetComponent<RectTransform>(),    new Vector2(0.42f, 0.63f), new Vector2(0.95f, 0.70f));
        var detailRarity  = CreateTMPText(detailPanel.transform, "DetailRarity",     "", 18, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(detailRarity.GetComponent<RectTransform>(),  new Vector2(0.42f, 0.57f), new Vector2(0.95f, 0.63f));
        var detailSet     = CreateTMPText(detailPanel.transform, "DetailSet",        "", 18, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(detailSet.GetComponent<RectTransform>(),     new Vector2(0.42f, 0.51f), new Vector2(0.95f, 0.57f));
        var detailOracle  = CreateTMPText(detailPanel.transform, "DetailOracleText", "", 17, FontStyles.Normal, TextAlignmentOptions.TopLeft);
        SetAnchors(detailOracle.GetComponent<RectTransform>(),  new Vector2(0.42f, 0.28f), new Vector2(0.95f, 0.51f));
        var detailQty     = CreateTMPText(detailPanel.transform, "DetailQuantity",   "", 18, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(detailQty.GetComponent<RectTransform>(),     new Vector2(0.42f, 0.22f), new Vector2(0.95f, 0.28f));

        var addToDeckBtn  = CreateTMPButton(detailPanel.transform, "DetailAddToDeckButton", "Add to Deck", new Color(0.2f, 0.55f, 0.2f));
        SetAnchors(addToDeckBtn.GetComponent<RectTransform>(),  new Vector2(0.42f, 0.12f), new Vector2(0.68f, 0.20f));
        var closeDetailBtn = CreateTMPButton(detailPanel.transform, "DetailCloseButton", "Close", new Color(0.5f, 0.15f, 0.15f));
        SetAnchors(closeDetailBtn.GetComponent<RectTransform>(), new Vector2(0.70f, 0.12f), new Vector2(0.95f, 0.20f));
        detailPanel.SetActive(false);

        // -- Error panel --
        var errorPanel = CreatePanel(canvasGo.transform, "ErrorPanel", new Color(0.5f, 0.1f, 0.1f, 0.95f));
        SetAnchors(errorPanel.GetComponent<RectTransform>(), new Vector2(0.2f, 0.02f), new Vector2(0.8f, 0.10f));
        var errorText  = CreateTMPText(errorPanel.transform, "ErrorText", "", 16, FontStyles.Normal, TextAlignmentOptions.Center);
        SetAnchors(errorText.GetComponent<RectTransform>(), new Vector2(0f, 0.2f), new Vector2(0.75f, 1f));
        var retryBtn   = CreateTMPButton(errorPanel.transform, "RetryButton", "Retry", new Color(0.6f, 0.25f, 0.25f));
        SetAnchors(retryBtn.GetComponent<RectTransform>(), new Vector2(0.78f, 0.2f), new Vector2(0.98f, 0.8f));
        errorPanel.SetActive(false);

        // -- Wire controller --
        var ctrl = canvasGo.AddComponent<CommanderAILab.UI.CollectionController>();
        SetField(ctrl, "backButton",          backBtn.GetComponent<Button>());
        SetField(ctrl, "searchInput",         searchInput.GetComponent<TMP_InputField>());
        SetField(ctrl, "sortDropdown",        sortDd.GetComponent<TMP_Dropdown>());
        SetField(ctrl, "searchButton",        searchBtn.GetComponent<Button>());
        SetField(ctrl, "filterToggleButton",  filterToggleBtn.GetComponent<Button>());
        SetField(ctrl, "filterPanel",         filterPanel);
        SetField(ctrl, "colorFilterDropdown",  colorDd.GetComponent<TMP_Dropdown>());
        SetField(ctrl, "typeFilterDropdown",   typeDd.GetComponent<TMP_Dropdown>());
        SetField(ctrl, "setFilterDropdown",    setDd.GetComponent<TMP_Dropdown>());
        SetField(ctrl, "rarityFilterDropdown", rarityDd.GetComponent<TMP_Dropdown>());
        SetField(ctrl, "ownedFilterDropdown",  ownedDd.GetComponent<TMP_Dropdown>());
        SetField(ctrl, "applyFilterButton",   applyBtn.GetComponent<Button>());
        SetField(ctrl, "clearFilterButton",   clearBtn.GetComponent<Button>());
        SetField(ctrl, "cardGridParent",      content.transform);
        SetField(ctrl, "cardPrefab",          null); // assign in Inspector
        SetField(ctrl, "gridScrollRect",      scrollGo.GetComponent<ScrollRect>());
        SetField(ctrl, "loadMoreButton",      loadMoreBtn.GetComponent<Button>());
        SetField(ctrl, "pageInfoText",        pageInfoText.GetComponent<TMP_Text>());
        SetField(ctrl, "loadingSpinner",      spinner);
        SetField(ctrl, "detailPanel",         detailPanel);
        SetField(ctrl, "detailCardFront",     detailCardFront.GetComponent<Image>());
        SetField(ctrl, "detailCardBack",      detailCardBack.GetComponent<Image>());
        SetField(ctrl, "detailCardName",      detailName.GetComponent<TMP_Text>());
        SetField(ctrl, "detailManaCost",      detailMana.GetComponent<TMP_Text>());
        SetField(ctrl, "detailType",          detailType.GetComponent<TMP_Text>());
        SetField(ctrl, "detailRarity",        detailRarity.GetComponent<TMP_Text>());
        SetField(ctrl, "detailSet",           detailSet.GetComponent<TMP_Text>());
        SetField(ctrl, "detailOracleText",    detailOracle.GetComponent<TMP_Text>());
        SetField(ctrl, "detailQuantity",      detailQty.GetComponent<TMP_Text>());
        SetField(ctrl, "detailAddToDeckButton", addToDeckBtn.GetComponent<Button>());
        SetField(ctrl, "detailCloseButton",   closeDetailBtn.GetComponent<Button>());
        SetField(ctrl, "errorPanel",          errorPanel);
        SetField(ctrl, "errorText",           errorText.GetComponent<TMP_Text>());
        SetField(ctrl, "retryButton",         retryBtn.GetComponent<Button>());

        // -- Save --
        if (!AssetDatabase.IsValidFolder("Assets/Scenes"))
            AssetDatabase.CreateFolder("Assets", "Scenes");
        string path = "Assets/Scenes/Collection.unity";
        EditorSceneManager.SaveScene(scene, path);
        var existing = new System.Collections.Generic.List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
        if (!existing.Any(s => s.path == path))
            existing.Add(new EditorBuildSettingsScene(path, true));
        EditorBuildSettings.scenes = existing.ToArray();
        Debug.Log("[CreateCollectionScene] Collection scene created and saved to " + path);
    }

    // -- Helpers --

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
