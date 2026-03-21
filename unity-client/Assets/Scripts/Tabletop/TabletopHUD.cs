using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;
using CommanderAILab.Models;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// UI Toolkit-based HUD overlay for the 3D tabletop.
    /// Displays: player life totals, phase indicator, turn counter,
    /// game log, selected card info, and action buttons.
    /// </summary>
    [RequireComponent(typeof(UIDocument))]
    public class TabletopHUD : MonoBehaviour
    {
        private UIDocument _doc;
        private VisualElement _root;

        // Player panels (4 corners)
        private Label[] _playerNameLabels = new Label[4];
        private Label[] _playerLifeLabels = new Label[4];
        private Label[] _playerManaLabels = new Label[4];
        private VisualElement[] _playerPanels = new VisualElement[4];

        // Center HUD
        private Label _turnLabel;
        private Label _phaseLabel;
        private Label _statusLabel;

        // Card info panel
        private VisualElement _cardInfoPanel;
        private Label _cardNameLabel;
        private Label _cardTypeLabel;
        private Label _cardStatsLabel;
        private Label _cardTextLabel;

        // Game log
        private ScrollView _logScroll;
        private VisualElement _logContainer;
        private readonly List<string> _logEntries = new();
        private const int MaxLogEntries = 50;

        // Buttons
        private Button _playBtn;
        private Button _attackBtn;
        private Button _passBtn;
        private Button _nextPhaseBtn;
        private Button _newGameBtn;

        private void OnEnable()
        {
            _doc = GetComponent<UIDocument>();
            BuildUI();
        }

        // ── UI Construction (runtime) ──────────────────────────────

        private void BuildUI()
        {
            _root = _doc.rootVisualElement;
            _root.Clear();

            // Root styles
            _root.style.flexDirection = FlexDirection.Column;
            _root.style.width = Length.Percent(100);
            _root.style.height = Length.Percent(100);

            // === Top bar: turn / phase / status ===
            var topBar = new VisualElement();
            topBar.style.flexDirection = FlexDirection.Row;
            topBar.style.justifyContent = Justify.Center;
            topBar.style.alignItems = Align.Center;
            topBar.style.height = 40;
            topBar.style.backgroundColor = new Color(0, 0, 0, 0.7f);
            topBar.style.paddingLeft = topBar.style.paddingRight = 16;
            _root.Add(topBar);

            _turnLabel = MakeLabel("Turn 1", 16, Color.white);
            _turnLabel.style.marginRight = 20;
            topBar.Add(_turnLabel);

            _phaseLabel = MakeLabel("main1", 16, new Color(0.6f, 0.9f, 1f));
            _phaseLabel.style.marginRight = 20;
            topBar.Add(_phaseLabel);

            _statusLabel = MakeLabel("Connecting...", 14, new Color(0.8f, 0.8f, 0.6f));
            _statusLabel.style.flexGrow = 1;
            topBar.Add(_statusLabel);

            // === Player panels (4 corners overlaid on 3D view) ===
            var playerOverlay = new VisualElement();
            playerOverlay.style.flexGrow = 1;
            playerOverlay.style.position = Position.Relative;
            _root.Add(playerOverlay);

            // Position: BL=seat0, BR=seat1, TR=seat2, TL=seat3
            StyleEnum<Position>[] hAlign = {
                Position.Absolute, Position.Absolute,
                Position.Absolute, Position.Absolute
            };

            for (int i = 0; i < 4; i++)
            {
                var panel = new VisualElement();
                panel.style.position = Position.Absolute;
                panel.style.backgroundColor = new Color(0, 0, 0, 0.6f);
                panel.style.borderTopLeftRadius = panel.style.borderTopRightRadius =
                    panel.style.borderBottomLeftRadius = panel.style.borderBottomRightRadius = 8;
                panel.style.paddingLeft = panel.style.paddingRight = 12;
                panel.style.paddingTop = panel.style.paddingBottom = 8;
                panel.style.width = 160;

                // Corner positions
                switch (i)
                {
                    case 0: panel.style.bottom = 10; panel.style.left = 10; break;
                    case 1: panel.style.bottom = 10; panel.style.right = 10; break;
                    case 2: panel.style.top = 10; panel.style.right = 10; break;
                    case 3: panel.style.top = 10; panel.style.left = 10; break;
                }

                _playerNameLabels[i] = MakeLabel($"Player {i}", 14, Color.white);
                _playerNameLabels[i].style.unityFontStyleAndWeight = FontStyle.Bold;
                panel.Add(_playerNameLabels[i]);

                _playerLifeLabels[i] = MakeLabel("40", 24, new Color(0.3f, 1f, 0.4f));
                panel.Add(_playerLifeLabels[i]);

                _playerManaLabels[i] = MakeLabel("Mana: 0", 12, new Color(0.4f, 0.7f, 1f));
                panel.Add(_playerManaLabels[i]);

                _playerPanels[i] = panel;
                playerOverlay.Add(panel);
            }

            // === Card info panel (right side) ===
            _cardInfoPanel = new VisualElement();
            _cardInfoPanel.style.position = Position.Absolute;
            _cardInfoPanel.style.right = 10;
            _cardInfoPanel.style.top = Length.Percent(30);
            _cardInfoPanel.style.width = 220;
            _cardInfoPanel.style.backgroundColor = new Color(0, 0, 0, 0.8f);
            _cardInfoPanel.style.borderTopLeftRadius = _cardInfoPanel.style.borderTopRightRadius =
                _cardInfoPanel.style.borderBottomLeftRadius = _cardInfoPanel.style.borderBottomRightRadius = 8;
            _cardInfoPanel.style.paddingLeft = _cardInfoPanel.style.paddingRight = 12;
            _cardInfoPanel.style.paddingTop = _cardInfoPanel.style.paddingBottom = 10;
            _cardInfoPanel.style.display = DisplayStyle.None;
            playerOverlay.Add(_cardInfoPanel);

            _cardNameLabel = MakeLabel("Card Name", 16, Color.white);
            _cardNameLabel.style.unityFontStyleAndWeight = FontStyle.Bold;
            _cardInfoPanel.Add(_cardNameLabel);

            _cardTypeLabel = MakeLabel("Type", 12, new Color(0.7f, 0.7f, 0.7f));
            _cardInfoPanel.Add(_cardTypeLabel);

            _cardStatsLabel = MakeLabel("", 14, new Color(1f, 0.8f, 0.3f));
            _cardInfoPanel.Add(_cardStatsLabel);

            _cardTextLabel = MakeLabel("", 11, new Color(0.9f, 0.9f, 0.9f));
            _cardTextLabel.style.whiteSpace = WhiteSpace.Normal;
            _cardTextLabel.style.maxWidth = 196;
            _cardInfoPanel.Add(_cardTextLabel);

            // === Bottom bar: buttons + game log ===
            var bottomBar = new VisualElement();
            bottomBar.style.flexDirection = FlexDirection.Row;
            bottomBar.style.height = 140;
            bottomBar.style.backgroundColor = new Color(0, 0, 0, 0.75f);
            _root.Add(bottomBar);

            // Buttons column
            var btnCol = new VisualElement();
            btnCol.style.width = 200;
            btnCol.style.paddingLeft = btnCol.style.paddingRight = 8;
            btnCol.style.paddingTop = btnCol.style.paddingBottom = 6;
            btnCol.style.justifyContent = Justify.SpaceAround;
            bottomBar.Add(btnCol);

            _playBtn = MakeButton("Play Card", new Color(0.2f, 0.6f, 0.3f));
            btnCol.Add(_playBtn);
            _attackBtn = MakeButton("Attack", new Color(0.7f, 0.2f, 0.2f));
            btnCol.Add(_attackBtn);
            _passBtn = MakeButton("Next Phase", new Color(0.3f, 0.3f, 0.6f));
            btnCol.Add(_passBtn);
            _newGameBtn = MakeButton("New Game", new Color(0.5f, 0.5f, 0.5f));
            btnCol.Add(_newGameBtn);

            // Game log
            _logScroll = new ScrollView(ScrollViewMode.Vertical);
            _logScroll.style.flexGrow = 1;
            _logScroll.style.paddingLeft = 8;
            _logScroll.style.paddingTop = 4;
            bottomBar.Add(_logScroll);

            _logContainer = _logScroll.contentContainer;

            // Wire button events to GameplayController
            _playBtn.clicked += () => FindObjectOfType<GameplayController>()?.OnPlayCardClicked();
            _attackBtn.clicked += () => FindObjectOfType<GameplayController>()?.OnAttackClicked();
            _passBtn.clicked += () => FindObjectOfType<GameplayController>()?.OnNextPhaseClicked();
            _newGameBtn.clicked += () => FindObjectOfType<GameplayController>()?.OnNewGameClicked();
        }

        // ── Public Update Methods ──────────────────────────────────

        public void UpdateFromState(GameStateResponse state)
        {
            if (state == null) return;

            _turnLabel.text = $"Turn {state.turn}";
            _phaseLabel.text = FormatPhase(state.phase);

            for (int i = 0; i < state.players.Count && i < 4; i++)
            {
                var p = state.players[i];
                _playerNameLabels[i].text = p.eliminated ? $"{p.name} (DEAD)" : p.name;
                _playerLifeLabels[i].text = p.life.ToString();
                _playerLifeLabels[i].style.color =
                    p.life > 20 ? new Color(0.3f, 1f, 0.4f) :
                    p.life > 10 ? new Color(1f, 0.8f, 0.2f) :
                    new Color(1f, 0.2f, 0.2f);
                _playerManaLabels[i].text = $"Mana: {p.manaAvailable} | Hand: {p.handCount}";

                // Highlight active player
                _playerPanels[i].style.borderLeftWidth =
                    _playerPanels[i].style.borderRightWidth =
                    _playerPanels[i].style.borderTopWidth =
                    _playerPanels[i].style.borderBottomWidth =
                    state.activeSeat == i ? 2 : 0;
                _playerPanels[i].style.borderLeftColor =
                    _playerPanels[i].style.borderRightColor =
                    _playerPanels[i].style.borderTopColor =
                    _playerPanels[i].style.borderBottomColor =
                    new Color(1f, 0.85f, 0f);

                if (p.eliminated)
                    _playerPanels[i].style.opacity = 0.4f;
            }

            // Add new log entries
            if (state.log != null)
            {
                foreach (var entry in state.log)
                {
                    if (!_logEntries.Contains(entry))
                        ShowGameLog(entry);
                }
            }
        }

        public void SetStatusText(string text)
        {
            if (_statusLabel != null) _statusLabel.text = text;
        }

        public void ShowGameLog(string message)
        {
            _logEntries.Add(message);
            while (_logEntries.Count > MaxLogEntries)
                _logEntries.RemoveAt(0);

            var label = MakeLabel(message, 11, new Color(0.85f, 0.85f, 0.75f));
            label.style.marginBottom = 2;
            _logContainer?.Add(label);

            // Auto-scroll to bottom
            _logScroll?.schedule.Execute(() =>
                _logScroll.scrollOffset = new Vector2(0, float.MaxValue));
        }

        public void ShowCardInfo(BoardCard card)
        {
            if (card == null || _cardInfoPanel == null) return;
            _cardInfoPanel.style.display = DisplayStyle.Flex;
            _cardNameLabel.text = card.name;
            _cardTypeLabel.text = card.typeLine ?? "";
            _cardStatsLabel.text = card.isCreature
                ? $"{card.power}/{card.toughness}  CMC: {card.cmc}"
                : $"CMC: {card.cmc}";
            _cardTextLabel.text = card.oracleText ?? "";
        }

        public void HideCardInfo()
        {
            if (_cardInfoPanel != null)
                _cardInfoPanel.style.display = DisplayStyle.None;
        }

        // ── Helpers ────────────────────────────────────────────────

        private string FormatPhase(string phase)
        {
            return phase switch
            {
                "main1" => "Main Phase 1",
                "main2" => "Main Phase 2",
                "combat_begin" => "Begin Combat",
                "combat_attackers" => "Declare Attackers",
                "combat_blockers" => "Declare Blockers",
                "combat_damage" => "Combat Damage",
                "combat_end" => "End Combat",
                "end" => "End Step",
                "cleanup" => "Cleanup",
                _ => phase
            };
        }

        private Label MakeLabel(string text, int fontSize, Color color)
        {
            var label = new Label(text);
            label.style.fontSize = fontSize;
            label.style.color = color;
            return label;
        }

        private Button MakeButton(string text, Color bgColor)
        {
            var btn = new Button();
            btn.text = text;
            btn.style.height = 28;
            btn.style.fontSize = 13;
            btn.style.backgroundColor = bgColor;
            btn.style.color = Color.white;
            btn.style.borderTopLeftRadius = btn.style.borderTopRightRadius =
                btn.style.borderBottomLeftRadius = btn.style.borderBottomRightRadius = 4;
            btn.style.marginBottom = 3;
            return btn;
        }
    }
}
