using System.Collections;
using UnityEngine;
using CommanderAILab.Services;
using CommanderAILab.Models;
using Newtonsoft.Json;

namespace CommanderAILab.Services
{
    /// <summary>
    /// Phase 0 validation MonoBehaviour.
    ///
    /// Attach to any GameObject in the Tabletop scene (or a dedicated
    /// "PingTest" GameObject). On Start it will:
    ///   1. Health-check the FastAPI backend
    ///   2. POST /api/play/new to create a 4-player session
    ///   3. Log the returned session_id and first game state to Console
    ///
    /// Green console output = Phase 0 COMPLETE. Remove this component
    /// before shipping Phase 1.
    ///
    /// Expected console output:
    ///   [PingTest] ✅ Backend reachable at http://localhost:8080
    ///   [PingTest] ✅ Session created: abc12345
    ///   [PingTest] ✅ Phase 0 COMPLETE — Turn 1 | Phase: main1 | Active: seat 0
    /// </summary>
    public class WebSocketPingTest : MonoBehaviour
    {
        [Header("Test Settings")]
        [SerializeField] private string backendUrl = "http://localhost:8080";
        [SerializeField] private bool runOnStart = true;
        [SerializeField] private bool destroyAfterTest = true;

        private void Start()
        {
            if (runOnStart)
                StartCoroutine(RunPhase0Test());
        }

        private IEnumerator RunPhase0Test()
        {
            Debug.Log("[PingTest] ====== Phase 0 Connection Test ======");

            // ── Step 1: Health check ───────────────────────────────
            using (var healthReq = UnityEngine.Networking.UnityWebRequest.Get(
                $"{backendUrl}/api/health"))
            {
                healthReq.timeout = 5;
                yield return healthReq.SendWebRequest();

                if (healthReq.result != UnityEngine.Networking.UnityWebRequest.Result.Success)
                {
                    Debug.LogError(
                        $"[PingTest] ❌ Health check FAILED: {healthReq.error}\n" +
                        $"  → Make sure the API server is running:\n" +
                        $"    uvicorn lab_api:app --port 8080 --reload");
                    yield break;
                }
                Debug.Log($"[PingTest] ✅ Backend reachable at {backendUrl}");
                Debug.Log($"[PingTest]    Response: {healthReq.downloadHandler.text}");
            }

            // ── Step 2: Create a 4-player game session ─────────────
            var newGameBody = JsonConvert.SerializeObject(new
            {
                deck_ids       = new string[0],
                player_names   = new[] { "You", "AI-Aggro", "AI-Control", "AI-Combo" },
                human_seat     = 0
            });

            string sessionId = null;
            GameStateResponse gameState = null;

            using (var newGameReq = new UnityEngine.Networking.UnityWebRequest(
                $"{backendUrl}/api/play/new", "POST"))
            {
                newGameReq.uploadHandler = new UnityEngine.Networking.UploadHandlerRaw(
                    System.Text.Encoding.UTF8.GetBytes(newGameBody));
                newGameReq.downloadHandler = new UnityEngine.Networking.DownloadHandlerBuffer();
                newGameReq.SetRequestHeader("Content-Type", "application/json");
                newGameReq.timeout = 15;
                yield return newGameReq.SendWebRequest();

                if (newGameReq.result != UnityEngine.Networking.UnityWebRequest.Result.Success)
                {
                    Debug.LogError(
                        $"[PingTest] ❌ /api/play/new FAILED: {newGameReq.error}\n" +
                        $"  Body: {newGameReq.downloadHandler?.text}");
                    yield break;
                }

                gameState = JsonConvert.DeserializeObject<GameStateResponse>(
                    newGameReq.downloadHandler.text);
                sessionId = gameState?.sessionId;
                Debug.Log($"[PingTest] ✅ Session created: {sessionId}");
            }

            // ── Step 3: Fetch legal moves ──────────────────────────
            using (var movesReq = UnityEngine.Networking.UnityWebRequest.Get(
                $"{backendUrl}/api/play/legal-moves?session_id={sessionId}"))
            {
                movesReq.timeout = 5;
                yield return movesReq.SendWebRequest();

                if (movesReq.result == UnityEngine.Networking.UnityWebRequest.Result.Success)
                {
                    var moves = JsonConvert.DeserializeObject<LegalMove[]>(
                        movesReq.downloadHandler.text);
                    Debug.Log($"[PingTest] ✅ Legal moves: {moves?.Length} available");
                }
            }

            // ── Step 4: Register session with WebSocketClient ──────
            if (WebSocketClient.Instance != null && sessionId != null)
                WebSocketClient.Instance.SetSession(sessionId);

            // ── Result ─────────────────────────────────────────────
            Debug.Log(
                $"[PingTest] ✅ Phase 0 COMPLETE — {gameState}\n" +
                $"  Players: {gameState?.players?.Count}\n" +
                $"  Active seat: {gameState?.activeSeat} ({gameState?.players?[gameState.activeSeat]?.name})");

            Debug.Log("[PingTest] ====== Test PASSED — Phase 0 Bootstrap Complete ======");

            if (destroyAfterTest)
                Destroy(gameObject, 2f);
        }
    }
}
