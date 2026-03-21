using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// Master controller for the 3D tabletop gameplay scene.
    /// Orchestrates: game session lifecycle, turn flow, AI turns,
    /// player input, and board/HUD synchronization.
    /// </summary>
    public class GameplayController : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private BoardManager boardManager;
        [SerializeField] private TabletopHUD hud;
        [SerializeField] private TabletopCameraController cameraController;

        [Header("AI Settings")]
        [SerializeField] private float aiTurnDelay = 1.5f;
        [SerializeField] private bool autoAdvanceAI = true;

        // State
        private GameStateResponse _currentState;
        private bool _waitingForServer = false;
        private bool _gameActive = false;

        // ── Lifecycle ──────────────────────────────────────────────

        private void Start()
        {
            // Auto-find references if not set
            if (boardManager == null) boardManager = FindObjectOfType<BoardManager>();
            if (hud == null) hud = FindObjectOfType<TabletopHUD>();
            if (cameraController == null) cameraController = FindObjectOfType<TabletopCameraController>();

            // Subscribe to board events
            if (boardManager != null)
            {
                boardManager.OnCardSelected += OnCardSelected;
                boardManager.OnCardDeselected += OnCardDeselected;
            }

            // Subscribe to session events
            var session = GameSessionService.Instance;
            if (session != null)
            {
                session.OnStateUpdated += OnStateUpdated;
                session.OnError += OnError;
                session.OnGameLog += OnGameLog;
            }

            // Auto-start a new game
            StartCoroutine(InitializeGame());
        }

        private void OnDestroy()
        {
            if (boardManager != null)
            {
                boardManager.OnCardSelected -= OnCardSelected;
                boardManager.OnCardDeselected -= OnCardDeselected;
            }
            var session = GameSessionService.Instance;
            if (session != null)
            {
                session.OnStateUpdated -= OnStateUpdated;
                session.OnError -= OnError;
                session.OnGameLog -= OnGameLog;
            }
        }

        // ── Game Initialization ────────────────────────────────────

        private IEnumerator InitializeGame()
        {
            // Wait for services
            yield return new WaitUntil(() => GameSessionService.Instance != null);

            hud?.SetStatusText("Connecting to Commander AI Lab...");

            // Health check
            bool healthy = false;
            if (ApiClient.Instance != null)
            {
                ApiClient.Instance.HealthCheck(result => healthy = result);
                yield return new WaitForSeconds(2f);
            }
            else
            {
                healthy = true; // Assume connected if no ApiClient
            }

            if (!healthy)
            {
                hud?.SetStatusText("Cannot reach backend at localhost:8080. Start the API server.");
                yield break;
            }

            hud?.SetStatusText("Starting new Commander game...");

            var request = new NewGameRequest
            {
                playerNames = new List<string> { "You", "AI-Aggro", "AI-Control", "AI-Combo" },
                humanSeat = 0
            };

            _waitingForServer = true;
            GameSessionService.Instance.NewGame(request, state =>
            {
                _waitingForServer = false;
                _gameActive = true;
                hud?.SetStatusText("Game started! Your turn.");
                hud?.ShowGameLog("Game started with 4 players.");
            });
        }

        // ── State Updates ──────────────────────────────────────────

        private void OnStateUpdated(GameStateResponse state)
        {
            _currentState = state;
            boardManager?.SyncToState(state);
            hud?.UpdateFromState(state);

            if (state.gameOver)
            {
                _gameActive = false;
                string winner = state.players.Find(p => p.seat == state.winnerSeat)?.name ?? "Unknown";
                hud?.SetStatusText($"Game Over! {winner} wins!");
                return;
            }

            // If it's an AI player's turn and we're auto-advancing, trigger AI
            if (autoAdvanceAI && !state.players[state.activeSeat].isHuman)
            {
                StartCoroutine(RunAITurn(state.activeSeat));
            }
            else if (state.players[state.activeSeat].isHuman)
            {
                hud?.SetStatusText($"Your turn — {state.phase}");
            }
        }

        private void OnError(string error)
        {
            Debug.LogError($"[GameplayController] {error}");
            hud?.ShowGameLog($"[Error] {error}");
            _waitingForServer = false;
        }

        private void OnGameLog(string message)
        {
            hud?.ShowGameLog(message);
        }

        // ── AI Turn Execution ──────────────────────────────────────

        private IEnumerator RunAITurn(int seat)
        {
            if (!_gameActive || _waitingForServer) yield break;

            string name = _currentState.players[seat].name;
            hud?.SetStatusText($"{name} is thinking...");
            yield return new WaitForSeconds(aiTurnDelay);

            _waitingForServer = true;
            GameSessionService.Instance.AITurn(result =>
            {
                _waitingForServer = false;
                // State update will come via OnStateUpdated
            });
        }

        // ── Player Actions ─────────────────────────────────────────

        private void OnCardSelected(CardObject3D card)
        {
            if (!_gameActive || _waitingForServer) return;
            if (_currentState == null) return;

            // Only allow actions on our turn
            if (!_currentState.players[_currentState.activeSeat].isHuman) return;

            hud?.ShowCardInfo(card.Data);
            hud?.SetStatusText(
                $"Selected: {card.Data.name} — Click 'Play' or select a target to attack");
        }

        private void OnCardDeselected(CardObject3D card)
        {
            hud?.HideCardInfo();
            if (_currentState != null && _currentState.players[_currentState.activeSeat].isHuman)
                hud?.SetStatusText($"Your turn — {_currentState.phase}");
        }

        /// <summary>Called by HUD Play button.</summary>
        public void OnPlayCardClicked()
        {
            var selected = boardManager?.SelectedCard;
            if (selected == null || _waitingForServer || !_gameActive) return;

            _waitingForServer = true;
            hud?.SetStatusText($"Playing {selected.Data.name}...");
            GameSessionService.Instance.PlayCard(selected.CardId, result =>
            {
                _waitingForServer = false;
                selected.SetSelected(false);
            });
        }

        /// <summary>Called by HUD Attack button — attacks the weakest opponent.</summary>
        public void OnAttackClicked()
        {
            var selected = boardManager?.SelectedCard;
            if (selected == null || !selected.Data.isCreature || _waitingForServer || !_gameActive)
                return;

            // Find weakest non-eliminated opponent
            int targetSeat = -1;
            int lowestLife = int.MaxValue;
            foreach (var p in _currentState.players)
            {
                if (p.seat != _currentState.activeSeat && !p.eliminated && p.life < lowestLife)
                {
                    lowestLife = p.life;
                    targetSeat = p.seat;
                }
            }
            if (targetSeat < 0) return;

            _waitingForServer = true;
            hud?.SetStatusText($"Attacking with {selected.Data.name}...");
            GameSessionService.Instance.Attack(selected.CardId, targetSeat, result =>
            {
                _waitingForServer = false;
                selected.SetSelected(false);
            });
        }

        /// <summary>Called by HUD Pass button.</summary>
        public void OnPassClicked()
        {
            if (_waitingForServer || !_gameActive) return;
            _waitingForServer = true;
            GameSessionService.Instance.Pass(result =>
            {
                _waitingForServer = false;
            });
        }

        /// <summary>Called by HUD Next Phase button.</summary>
        public void OnNextPhaseClicked()
        {
            if (_waitingForServer || !_gameActive) return;
            _waitingForServer = true;
            GameSessionService.Instance.NextPhase(result =>
            {
                _waitingForServer = false;
            });
        }

        /// <summary>Called by HUD New Game button.</summary>
        public void OnNewGameClicked()
        {
            boardManager?.ClearBoard();
            StartCoroutine(InitializeGame());
        }

        // ── Camera Shortcuts ──────────────────────────────────────

        private void Update()
        {
            // Number keys snap camera to seats
            if (Input.GetKeyDown(KeyCode.Alpha1)) cameraController?.SnapToSeat(0);
            if (Input.GetKeyDown(KeyCode.Alpha2)) cameraController?.SnapToSeat(1);
            if (Input.GetKeyDown(KeyCode.Alpha3)) cameraController?.SnapToSeat(2);
            if (Input.GetKeyDown(KeyCode.Alpha4)) cameraController?.SnapToSeat(3);
            if (Input.GetKeyDown(KeyCode.T)) cameraController?.SnapTopDown();
            if (Input.GetKeyDown(KeyCode.R)) cameraController?.ResetView();

            // Spacebar = pass/next phase
            if (Input.GetKeyDown(KeyCode.Space))
            {
                if (_currentState?.players[_currentState.activeSeat]?.isHuman == true)
                    OnNextPhaseClicked();
            }
        }
    }
}
