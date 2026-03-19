#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.Reflection;
using System.Linq;

public static class CreateMainMenuScene
{
    [MenuItem("Tools/Create MainMenu Scene")]
    public static void Create()
    {
        // -- Create new scene --
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        // -- Services (persistent singletons) --
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

        // -- Event System --
        if (Object.FindObjectOfType<UnityEngine.EventSystems.EventSystem>() == null)
        {
            var es = new GameObject("EventSystem");
            es.AddComponent<UnityEngine.EventSystems.EventSystem>();
            es.AddComponent<UnityEngine.EventSystems.StandaloneInputModule>();
        }

        // -- Background --
        var bg = CreatePanel(canvasGo.transform, "Background", Color.black, stretch: true);
        bg.GetComponent<Image>().color = new Color(0.08f, 0.08f, 0.12f, 1f);

        // -- Server Panel (top) --
        var serverPanel = CreatePanel(canvasGo.transform, "ServerPanel", new Color(0.12f, 0.12f, 0.18f, 0.95f));
        var spRect = serverPanel.GetComponent<RectTransform>();
        SetAnchors(spRect, new Vector2(0.1f, 0.75f), new Vector2(0.9f, 0.95f));

        var logoText = CreateTMPText(serverPanel.transform, "LogoText", "Commander AI Lab", 36, FontStyles.Bold, TextAlignmentOptions.Center);
        SetAnchors(logoText.GetComponent<RectTransform>(), new Vector2(0f, 0.5f), new Vector2(1f, 1f));

        var urlInput = CreateTMPInputField(serverPanel.transform, "ServerUrlInput", "http://localhost:8080");
        var urlRect = urlInput.GetComponent<RectTransform>();
        SetAnchors(urlRect, new Vector2(0.05f, 0.05f), new Vector2(0.55f, 0.45f));

        var connectBtn = CreateTMPButton(serverPanel.transform, "ConnectButton", "Connect", new Color(0.2f, 0.6f, 0.2f));
        SetAnchors(connectBtn.GetComponent<RectTransform>(), new Vector2(0.58f, 0.05f), new Vector2(0.75f, 0.45f));

        var statusImg = new GameObject("StatusIndicator");
        statusImg.transform.SetParent(serverPanel.transform, false);
        var statusImage = statusImg.AddComponent<Image>();
        statusImage.color = new Color(0.8f, 0.2f, 0.2f);
        var siRect = statusImg.GetComponent<RectTransform>();
        SetAnchors(siRect, new Vector2(0.78f, 0.15f), new Vector2(0.80f, 0.35f));

        var statusText = CreateTMPText(serverPanel.transform, "StatusText", "Disconnected", 18, FontStyles.Normal, TextAlignmentOptions.Left);
        SetAnchors(statusText.GetComponent<RectTransform>(), new Vector2(0.81f, 0.05f), new Vector2(0.98f, 0.45f));

        // -- Nav Panel (center) --
        var navPanel = CreatePanel(canvasGo.transform, "NavPanel", new Color(0.1f, 0.1f, 0.15f, 0.9f));
        SetAnchors(navPanel.GetComponent<RectTransform>(), new Vector2(0.1f, 0.15f), new Vector2(0.9f, 0.72f));

        // Add vertical layout
        var vlg = navPanel.AddComponent<VerticalLayoutGroup>();
        vlg.spacing = 10;
        vlg.padding = new RectOffset(40, 40, 20, 20);
        vlg.childAlignment = TextAnchor.MiddleCenter;
        vlg.childForceExpandWidth = true;
        vlg.childForceExpandHeight = true;

        string[] btnNames = { "CollectionButton", "DeckBuilderButton", "DeckGenButton", "SimulatorButton", "ScannerButton", "CoachButton", "TrainingButton" };
        string[] btnLabels = { "Collection", "Deck Builder", "Deck Generator", "Simulator", "Scanner", "Coach", "Training" };
        var navButtons = new GameObject[btnNames.Length];
        for (int i = 0; i < btnNames.Length; i++)
        {
            navButtons[i] = CreateTMPButton(navPanel.transform, btnNames[i], btnLabels[i], new Color(0.18f, 0.22f, 0.35f));
        }

        // -- Error Panel (bottom, inactive) --
        var errorPanel = CreatePanel(canvasGo.transform, "ErrorPanel", new Color(0.5f, 0.1f, 0.1f, 0.95f));
        SetAnchors(errorPanel.GetComponent<RectTransform>(), new Vector2(0.2f, 0.02f), new Vector2(0.8f, 0.12f));

        var errorText = CreateTMPText(errorPanel.transform, "ErrorText", "", 16, FontStyles.Normal, TextAlignmentOptions.Center);
        SetAnchors(errorText.GetComponent<RectTransform>(), new Vector2(0f, 0.3f), new Vector2(0.7f, 1f));

        var retryBtn = CreateTMPButton(errorPanel.transform, "RetryButton", "Retry", new Color(0.6f, 0.3f, 0.1f));
        SetAnchors(retryBtn.GetComponent<RectTransform>(), new Vector2(0.72f, 0.15f), new Vector2(0.95f, 0.85f));

        errorPanel.SetActive(false);

        // -- Wire up MainMenuController --
        var controllerGo = new GameObject("MainMenuController");
        var controller = controllerGo.AddComponent<CommanderAILab.UI.MainMenuController>();

        // Use reflection to set private serialized fields
        SetField(controller, "serverUrlInput", urlInput.GetComponent<TMP_InputField>());
        SetField(controller, "connectButton", connectBtn.GetComponent<Button>());
        SetField(controller, "statusIndicator", statusImage);
        SetField(controller, "statusText", statusText.GetComponent<TMP_Text>());
        SetField(controller, "collectionButton", navButtons[0].GetComponent<Button>());
        SetField(controller, "deckBuilderButton", navButtons[1].GetComponent<Button>());
        SetField(controller, "deckGenButton", navButtons[2].GetComponent<Button>());
        SetField(controller, "simulatorButton", navButtons[3].GetComponent<Button>());
        SetField(controller, "scannerButton", navButtons[4].GetComponent<Button>());
        SetField(controller, "coachButton", navButtons[5].GetComponent<Button>());
        SetField(controller, "trainingButton", navButtons[6].GetComponent<Button>());
        SetField(controller, "errorPanel", errorPanel);
        SetField(controller, "errorText", errorText.GetComponent<TMP_Text>());
        SetField(controller, "retryButton", retryBtn.GetComponent<Button>());

        // -- Save --
        string path = "Assets/Scenes/MainMenu.unity";
        EditorSceneManager.SaveScene(scene, path);
        var existing = new System.Collections.Generic.List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
        if (!existing.Any(s => s.path == path))
            existing.Add(new EditorBuildSettingsScene(path, true));
        EditorBuildSettings.scenes = existing.ToArray();

        Debug.Log("MainMenu scene created and saved to " + path);
        EditorUtility.DisplayDialog("Done", "MainMenu scene created!\n\nHit Play to test.\nMake sure your FastAPI backend is running on port 8080.", "OK");
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

    static GameObject CreateTMPInputField(Transform parent, string name, string defaultText)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = new Color(0.15f, 0.15f, 0.2f);

        // Text Area
        var textArea = new GameObject("Text Area");
        textArea.transform.SetParent(go.transform, false);
        textArea.AddComponent<RectMask2D>();
        SetAnchors(textArea.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        // Placeholder
        var placeholder = new GameObject("Placeholder");
        placeholder.transform.SetParent(textArea.transform, false);
        var phTmp = placeholder.AddComponent<TextMeshProUGUI>();
        phTmp.text = "Enter server URL...";
        phTmp.fontSize = 18;
        phTmp.fontStyle = FontStyles.Italic;
        phTmp.color = new Color(0.5f, 0.5f, 0.5f, 0.8f);
        phTmp.alignment = TextAlignmentOptions.Left;
        SetAnchors(placeholder.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

        // Input text
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
