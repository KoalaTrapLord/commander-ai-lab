// Assets/Editor/CreateBattlegroundScene.cs
// Unity menu: Commander AI Lab ▶ Create Battleground Scene
// Builds the entire Battleground scene hierarchy and wires every SerializeField.
// Run once on an empty scene, then hit Play.

using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using TMPro;
using CommanderAILab.UI;
using CommanderAILab.Services;

namespace CommanderAILab.Editor
{
    public static class CreateBattlegroundScene
    {
        // ── Phase names in enum order (matches PhaseTrackerWidget.Phase) ──────
        private static readonly string[] PhaseNames =
        {
            "Untap", "Upkeep", "Draw", "Main1",
            "Begin Combat", "Attackers", "Blockers",
            "1st Strike", "Damage", "End Combat",
            "Main2", "End Step", "Cleanup"
        };

        // ── Seat labels ───────────────────────────────────────────────────────
        private static readonly string[] SeatNames = { "Bottom", "Right", "Top", "Left" };

        // ─────────────────────────────────────────────────────────────────────
        [MenuItem("Commander AI Lab/Create Battleground Scene")]
        public static void Build()
        {
            // 1. Open a fresh scene
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            // 2. Services (DontDestroyOnLoad singletons — just need to exist in scene)
            var services    = NewGO("Services");
            var apiClient   = services.AddComponent<ApiClient>();
            // GameWebSocketClient added below so BattlegroundController can find it
            var wsClientGO  = NewGO("GameWebSocketClient", services.transform);

            // 3. GameStateManager singleton
            var gsmGO = NewGO("GameStateManager");
            gsmGO.AddComponent<GameStateManager>();

            // 4. EventSystem (required for all UI input)
            var esGO = NewGO("EventSystem");
            esGO.AddComponent<EventSystem>();
            esGO.AddComponent<StandaloneInputModule>();

            // 5. Main Camera
            var camGO = NewGO("Main Camera");
            var cam   = camGO.AddComponent<Camera>();
            cam.clearFlags       = CameraClearFlags.SolidColor;
            cam.backgroundColor  = new Color(0.08f, 0.12f, 0.08f); // dark green
            cam.orthographic     = true;
            cam.orthographicSize = 5f;
            cam.tag              = "MainCamera";
            camGO.AddComponent<AudioListener>();

            // 6. Root Canvas
            var canvasGO = NewGO("Canvas");
            var canvas   = canvasGO.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvasGO.AddComponent<CanvasScaler>();
            canvasGO.AddComponent<GraphicRaycaster>();

            // ── 7. Seat Panels (4 RectTransforms around the board) ────────────
            var seatsRoot  = NewGO("SeatPanels", canvasGO.transform);
            var seatPanels = new RectTransform[4];
            for (int i = 0; i < 4; i++)
            {
                var sp   = NewGO($"SeatPanel_{SeatNames[i]}", seatsRoot.transform);
                var rt   = sp.AddComponent<RectTransform>();
                var img  = sp.AddComponent<Image>();
                img.color = new Color(0f, 0f, 0f, 0.3f);
                StretchFill(rt);
                seatPanels[i] = rt;
            }

            // ── 8. Center panel ───────────────────────────────────────────────
            var centerGO = NewGO("BattlefieldCenter", canvasGO.transform);
            StretchFill(centerGO.GetComponent<RectTransform>() ?? centerGO.AddComponent<RectTransform>());

            // ── 9. PhaseTrackerWidget ─────────────────────────────────────────
            var ptwGO   = NewGO("PhaseTracker", centerGO.transform);
            var ptWidget = ptwGO.AddComponent<PhaseTrackerWidget>();
            SetAnchored(ptwGO, new Vector2(0f, 0f), new Vector2(1f, 0.08f)); // bottom strip

            // -- Active player + turn number labels
            var aplGO = MakeTMPText("ActivePlayerLabel", ptwGO.transform, "Player's Turn", 18);
            var tnlGO = MakeTMPText("TurnNumberLabel",   ptwGO.transform, "Turn 1",        16);

            // -- 13 PhaseStepButtons
            var stepButtons = new PhaseStepButton[13];
            for (int i = 0; i < 13; i++)
            {
                var btnGO = NewGO($"PhaseBtn_{PhaseNames[i]}", ptwGO.transform);
                var img   = btnGO.AddComponent<Image>();
                img.color = new Color(0.2f, 0.2f, 0.2f);

                var psb   = btnGO.AddComponent<PhaseStepButton>();

                // PhaseStepButton.background + label — set via reflection (private SerializeFields)
                var labelGO = MakeTMPText("Label", btnGO.transform, PhaseNames[i], 11);
                SetPrivateField(psb, "background", img);
                SetPrivateField(psb, "label", labelGO.GetComponent<TMP_Text>());

                stepButtons[i] = psb;
            }

            // Wire PhaseTrackerWidget SerializeFields
            SetPrivateField(ptWidget, "stepButtons",       stepButtons);
            SetPrivateField(ptWidget, "activePlayerLabel", aplGO.GetComponent<TMP_Text>());
            SetPrivateField(ptWidget, "turnNumberLabel",   tnlGO.GetComponent<TMP_Text>());

            // ── 10. TurnOrderBar ──────────────────────────────────────────────
            var tobGO  = NewGO("TurnOrderBar", centerGO.transform);
            var tobBar = tobGO.AddComponent<TurnOrderBar>();
            SetAnchored(tobGO, new Vector2(0f, 0.92f), new Vector2(1f, 1f)); // top strip

            // ActiveBorder (sliding highlight)
            var borderGO = NewGO("ActiveBorder", tobGO.transform);
            var borderRT = borderGO.AddComponent<RectTransform>();
            var borderImg = borderGO.AddComponent<Image>();
            borderImg.color = new Color(1f, 0.85f, 0f, 0.35f);

            // 4 TurnOrderPills
            var pills = new TurnOrderPill[4];
            for (int i = 0; i < 4; i++)
            {
                var pillGO  = NewGO($"Pill_{i}", tobGO.transform);
                var pillImg = pillGO.AddComponent<Image>();
                pillImg.color = new Color(0.25f, 0.25f, 0.25f);
                var pill    = pillGO.AddComponent<TurnOrderPill>();

                var nameLabel = MakeTMPText("PlayerName", pillGO.transform, $"Seat {i}", 13);
                var lifeLabel = MakeTMPText("Life",       pillGO.transform, "40",        13);
                var youBadge  = NewGO("YouBadge", pillGO.transform);
                MakeTMPText("YouText", youBadge.transform, "YOU", 11);
                youBadge.SetActive(i == 0);

                SetPrivateField(pill, "playerNameLabel", nameLabel.GetComponent<TMP_Text>());
                SetPrivateField(pill, "lifeLabel",       lifeLabel.GetComponent<TMP_Text>());
                SetPrivateField(pill, "pillBackground",  pillImg);
                SetPrivateField(pill, "youBadge",        youBadge);

                pills[i] = pill;
            }

            SetPrivateField(tobBar, "pills",        pills);
            SetPrivateField(tobBar, "activeBorder", borderRT);

            // ── 11. LobbySetupModal ───────────────────────────────────────────
            var modalGO  = NewGO("LobbySetupModal", canvasGO.transform);
            var modal    = modalGO.AddComponent<LobbySetupModal>();
            StretchFill(modalGO.GetComponent<RectTransform>() ?? modalGO.AddComponent<RectTransform>());

            // Dark overlay panel
            var panelGO  = NewGO("Panel", modalGO.transform);
            var panelImg = panelGO.AddComponent<Image>();
            panelImg.color = new Color(0f, 0f, 0f, 0.85f);
            SetAnchored(panelGO, new Vector2(0.2f, 0.1f), new Vector2(0.8f, 0.9f));

            MakeTMPText("Title", panelGO.transform, "Configure Seats", 24);

            // 4 seat rows
            var seatRows = new LobbyRowUI[4];
            for (int i = 0; i < 4; i++)
            {
                var rowGO  = NewGO($"SeatRow_{i}", panelGO.transform);
                rowGO.AddComponent<RectTransform>();
                var row    = rowGO.AddComponent<LobbyRowUI>();

                var seatLbl  = MakeTMPText("SeatLabel",  rowGO.transform, $"Seat {i}", 14);
                var togGO    = MakeToggle("HumanToggle", rowGO.transform);
                var deckDD   = MakeTMPDropdown("DeckDropdown",    rowGO.transform);
                var styleDD  = MakeTMPDropdown("AiStyleDropdown", rowGO.transform);

                SetPrivateField(row, "seatLabel",       seatLbl.GetComponent<TMP_Text>());
                SetPrivateField(row, "humanToggle",     togGO.GetComponent<Toggle>());
                SetPrivateField(row, "deckDropdown",    deckDD.GetComponent<TMP_Dropdown>());
                SetPrivateField(row, "aiStyleDropdown", styleDD.GetComponent<TMP_Dropdown>());

                seatRows[i] = row;
            }

            // Error label (starts inactive)
            var errGO  = MakeTMPText("ErrorLabel", panelGO.transform, "", 13);
            errGO.GetComponent<TMP_Text>().color = Color.red;
            errGO.SetActive(false);

            // Confirm + Cancel buttons
            var confirmBtn = MakeButton("ConfirmButton", panelGO.transform, "Confirm");
            var cancelBtn  = MakeButton("CancelButton",  panelGO.transform, "Cancel");

            // Wire LobbySetupModal SerializeFields
            SetPrivateField(modal, "seatRows",      seatRows);
            SetPrivateField(modal, "confirmButton", confirmBtn.GetComponent<Button>());
            SetPrivateField(modal, "cancelButton",  cancelBtn.GetComponent<Button>());
            SetPrivateField(modal, "errorLabel",    errGO.GetComponent<TMP_Text>());
            SetPrivateField(modal, "apiClient",     apiClient);

            // ── 12. Main Menu Button (top-left HUD) ───────────────────────────
            var mmBtnGO = MakeButton("MainMenuButton", canvasGO.transform, "⬅ Menu");
            var mmRT    = mmBtnGO.GetComponent<RectTransform>();
            mmRT.anchorMin        = new Vector2(0f, 1f);
            mmRT.anchorMax        = new Vector2(0f, 1f);
            mmRT.pivot            = new Vector2(0f, 1f);
            mmRT.anchoredPosition = new Vector2(10f, -10f);
            mmRT.sizeDelta        = new Vector2(120f, 40f);

            // ── 13. BattlegroundController ────────────────────────────────────
            var bcGO = NewGO("BattlegroundController", canvasGO.transform);
            var bc   = bcGO.AddComponent<BattlegroundController>();

            SetPrivateField(bc, "seatPanels",    seatPanels);
            SetPrivateField(bc, "phaseTracker",  ptWidget);
            SetPrivateField(bc, "turnOrderBar",  tobBar);
            SetPrivateField(bc, "lobbyModal",    modal);
            SetPrivateField(bc, "mainMenuButton", mmBtnGO.GetComponent<Button>());

            // ── 14. Save scene ────────────────────────────────────────────────
            const string scenePath = "Assets/Scripts/UI/Battleground/Battleground.unity";
            EditorSceneManager.SaveScene(scene, scenePath);

            // Add to build settings if not already present
            AddSceneToBuild(scenePath);

            Debug.Log("[CreateBattlegroundScene] ✅ Scene built and saved to " + scenePath);
            EditorUtility.DisplayDialog("Done",
                "Battleground scene created at:\n" + scenePath +
                "\n\nHit Play to run it.", "OK");
        }

        // ═════════════════════════════════════════════════════════════════════
        // Helpers
        // ═════════════════════════════════════════════════════════════════════

        static GameObject NewGO(string name, Transform parent = null)
        {
            var go = new GameObject(name);
            if (parent != null) go.transform.SetParent(parent, false);
            return go;
        }

        static void StretchFill(RectTransform rt)
        {
            rt.anchorMin        = Vector2.zero;
            rt.anchorMax        = Vector2.one;
            rt.offsetMin        = Vector2.zero;
            rt.offsetMax        = Vector2.zero;
        }

        static void SetAnchored(GameObject go, Vector2 anchorMin, Vector2 anchorMax)
        {
            var rt = go.GetComponent<RectTransform>() ?? go.AddComponent<RectTransform>();
            rt.anchorMin  = anchorMin;
            rt.anchorMax  = anchorMax;
            rt.offsetMin  = Vector2.zero;
            rt.offsetMax  = Vector2.zero;
        }

        static GameObject MakeTMPText(string name, Transform parent, string text, int fontSize)
        {
            var go  = NewGO(name, parent);
            var rt  = go.AddComponent<RectTransform>();
            var tmp = go.AddComponent<TextMeshProUGUI>();
            tmp.text     = text;
            tmp.fontSize = fontSize;
            tmp.color    = Color.white;
            tmp.alignment = TextAlignmentOptions.Center;
            return go;
        }

        static GameObject MakeButton(string name, Transform parent, string label)
        {
            var go  = NewGO(name, parent);
            go.AddComponent<RectTransform>();
            var img = go.AddComponent<Image>();
            img.color = new Color(0.15f, 0.15f, 0.15f);
            go.AddComponent<Button>();

            var lblGO = MakeTMPText("Text", go.transform, label, 14);
            StretchFill(lblGO.GetComponent<RectTransform>());
            return go;
        }

        static GameObject MakeToggle(string name, Transform parent)
        {
            var go     = NewGO(name, parent);
            go.AddComponent<RectTransform>();
            var toggle = go.AddComponent<Toggle>();

            var bgGO   = NewGO("Background", go.transform);
            var bgImg  = bgGO.AddComponent<Image>();
            bgImg.color = Color.white;

            var checkGO  = NewGO("Checkmark", bgGO.transform);
            var checkImg = checkGO.AddComponent<Image>();
            checkImg.color = new Color(0.2f, 0.8f, 0.2f);

            toggle.targetGraphic = bgImg;
            toggle.graphic       = checkImg;
            return go;
        }

        static GameObject MakeTMPDropdown(string name, Transform parent)
        {
            var go  = NewGO(name, parent);
            go.AddComponent<RectTransform>();
            var img = go.AddComponent<Image>();
            img.color = new Color(0.15f, 0.15f, 0.15f);
            var dd  = go.AddComponent<TMP_Dropdown>();

            // Required child: Label
            var lblGO = MakeTMPText("Label", go.transform, "Select...", 13);
            StretchFill(lblGO.GetComponent<RectTransform>());
            dd.captionText = lblGO.GetComponent<TMP_Text>();

            // Required child: Arrow
            var arrowGO  = MakeTMPText("Arrow", go.transform, "▼", 12);
            var arrowRT  = arrowGO.GetComponent<RectTransform>();
            arrowRT.anchorMin        = new Vector2(1f, 0.5f);
            arrowRT.anchorMax        = new Vector2(1f, 0.5f);
            arrowRT.pivot            = new Vector2(1f, 0.5f);
            arrowRT.anchoredPosition = new Vector2(-5f, 0f);
            arrowRT.sizeDelta        = new Vector2(20f, 20f);

            // Required child: Template (hidden)
            var tmplGO  = NewGO("Template", go.transform);
            var tmplImg = tmplGO.AddComponent<Image>();
            tmplImg.color = new Color(0.1f, 0.1f, 0.1f);
            var tmplRT  = tmplGO.GetComponent<RectTransform>() ?? tmplGO.AddComponent<RectTransform>();
            tmplRT.anchorMin        = new Vector2(0f, 0f);
            tmplRT.anchorMax        = new Vector2(1f, 0f);
            tmplRT.pivot            = new Vector2(0.5f, 1f);
            tmplRT.sizeDelta        = new Vector2(0f, 150f);
            tmplGO.AddComponent<ScrollRect>();
            tmplGO.SetActive(false);

            // Viewport > Content > Item > ItemLabel
            var vpGO    = NewGO("Viewport", tmplGO.transform);
            vpGO.AddComponent<RectTransform>();
            vpGO.AddComponent<Mask>();
            vpGO.AddComponent<Image>();

            var contentGO = NewGO("Content", vpGO.transform);
            contentGO.AddComponent<RectTransform>();

            var itemGO  = NewGO("Item", contentGO.transform);
            var itemTog = itemGO.AddComponent<Toggle>();
            var itemLbl = MakeTMPText("Item Label", itemGO.transform, "Option", 13);
            itemTog.targetGraphic = itemGO.AddComponent<Image>();
            itemTog.graphic       = itemLbl.GetComponent<TMP_Text>();
            dd.itemText           = itemLbl.GetComponent<TMP_Text>();

            return go;
        }

        /// <summary>Set a private [SerializeField] via reflection.</summary>
        static void SetPrivateField(object target, string fieldName, object value)
        {
            var type  = target.GetType();
            while (type != null)
            {
                var fi = type.GetField(fieldName,
                    System.Reflection.BindingFlags.NonPublic |
                    System.Reflection.BindingFlags.Instance);
                if (fi != null) { fi.SetValue(target, value); return; }
                type = type.BaseType;
            }
            Debug.LogWarning($"[CreateBattlegroundScene] Field not found: {fieldName} on {target.GetType().Name}");
        }

        static void AddSceneToBuild(string scenePath)
        {
            var scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            foreach (var s in scenes)
                if (s.path == scenePath) return; // already present

            scenes.Insert(0, new EditorBuildSettingsScene(scenePath, true));
            EditorBuildSettings.scenes = scenes.ToArray();
        }
    }
}
