using UnityEngine;
using UnityEngine.SceneManagement;
using TcgEngine.Client;
using CommanderAILab.Tabletop;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// CommanderGameBridge — drop this onto the same GameObject as TCGEngine's
    /// GameClient in the Game3D scene.
    ///
    /// Responsibility:
    ///   1. Suppress TCGEngine's built-in network/matchmaking so it doesn't try
    ///      to connect to its own server.
    ///   2. Forward game state from your FastAPI backend (via GameSessionService)
    ///      into BoardManager.SyncToState() and TabletopHUD.UpdateFromState().
    ///   3. Expose a static entry point so MainMenu can load the scene and pass
    ///      session parameters without a login flow.
    ///
    /// Setup (one-time in Unity Editor):
    ///   - Open TcgEngine/Scenes/Game/Game3D.unity
    ///   - File > Save As > Assets/Scenes/Simulator.unity
    ///   - Find the GameClient GameObject in the hierarchy
    ///   - Add this script as a component alongside GameClient
    ///   - Make sure GameplayController and BoardManager are also in the scene
    /// </summary>
    public class CommanderGameBridge : MonoBehaviour
    {
        [Header("Commander AI Lab References")]
        [Tooltip("Auto-found if left empty")]
        [SerializeField] private GameplayController gameplayController;
        [SerializeField] private BoardManager boardManager;

        [Header("TCGEngine Suppression")]
        [Tooltip("Disables TCGEngine's matchmaker so it won't try to reach its own server")]
        [SerializeField] private bool suppressTcgNetworking = true;

        // -- Static session params passed from MainMenu ----
        public static string PendingSessionId { get; private set; }
        public static int PendingHumanSeat { get; private set; } = 0;

        /// <summary>
        /// Call this from MainMenu before loading the Simulator scene.
        /// Stores session parameters so the bridge can pick them up on Start.
        /// </summary>
        public static void PrepareSession(string sessionId, int humanSeat = 0)
        {
            PendingSessionId = sessionId;
            PendingHumanSeat = humanSeat;
        }

        // -- Lifecycle ----

        private void Awake()
        {
            if (suppressTcgNetworking)
                DisableTcgNetworking();
        }

        private void Start()
        {
            // Auto-find references
            if (gameplayController == null)
                gameplayController = FindObjectOfType<GameplayController>();
            if (boardManager == null)
                boardManager = FindObjectOfType<BoardManager>();

            if (gameplayController == null)
            {
                Debug.LogError("[CommanderGameBridge] GameplayController not found in scene. " +
                               "Add it to the Simulator scene.");
                return;
            }

            // Wire GameSessionService state updates > BoardManager
            var session = GameSessionService.Instance;
            if (session != null)
            {
                session.OnStateUpdated += OnStateReceived;
                Debug.Log("[CommanderGameBridge] Subscribed to GameSessionService.OnStateUpdated");
            }
            else
            {
                Debug.LogWarning("[CommanderGameBridge] GameSessionService not found. " +
                                 "Make sure it exists in the scene or as a DontDestroyOnLoad singleton.");
            }

            Debug.Log($"[CommanderGameBridge] Ready. Session='{PendingSessionId}' Seat={PendingHumanSeat}");
        }

        private void OnDestroy()
        {
            var session = GameSessionService.Instance;
            if (session != null)
                session.OnStateUpdated -= OnStateReceived;
        }

        // -- State Forwarding ----

        /// <summary>
        /// Receives game state from FastAPI backend and syncs the board.
        /// This is the core bridge: FastAPI > GameStateResponse > TCGEngine scene.
        /// </summary>
        private void OnStateReceived(GameStateResponse state)
        {
            if (state == null) return;

            // Forward to BoardManager (spawns/moves/destroys CardObject3D instances)
            boardManager?.SyncToState(state);

            // GameplayController already subscribes to OnStateUpdated directly,
            // so HUD updates happen automatically. No double-call needed.

            Debug.Log($"[CommanderGameBridge] State synced -- Turn {state.turn}, " +
                      $"Active seat: {state.activeSeat}, Phase: {state.phase}");
        }

        // -- TCGEngine Network Suppression ----

        /// <summary>
        /// Disables TCGEngine components that would try to connect to its
        /// own game server (not your FastAPI backend).
        /// </summary>
        private void DisableTcgNetworking()
        {
            // Disable the matchmaker -- Commander AI Lab uses direct FastAPI sessions
            var matchmaker = GetComponent<GameClientMatchmaker>();
            if (matchmaker != null)
            {
                matchmaker.enabled = false;
                Debug.Log("[CommanderGameBridge] Disabled GameClientMatchmaker");
            }

            // Note: TCGEngine's AIPlayer is an abstract class (not a MonoBehaviour),
            // so it cannot be found via FindObjectOfType or disabled via .enabled.
            // AI suppression is handled by not starting a TCGEngine game session;
            // your Python AI backend handles all AI decisions instead.
            Debug.Log("[CommanderGameBridge] TCGEngine networking suppressed. " +
                      "AI is handled by the FastAPI/Python backend.");
        }

        // -- Main Menu Integration ----

        /// <summary>
        /// Loads the Simulator scene. Call from MainMenuController's Play button.
        /// Usage: CommanderGameBridge.LoadSimulator("session-id-from-api", 0);
        /// </summary>
        public static void LoadSimulator(string sessionId = "", int humanSeat = 0)
        {
            PrepareSession(sessionId, humanSeat);
            SceneManager.LoadScene("Simulator");
        }
    }
}
