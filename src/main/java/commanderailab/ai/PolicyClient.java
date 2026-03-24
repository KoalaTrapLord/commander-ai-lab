package commanderailab.ai;

import commanderailab.ml.LearnedPolicy;
import commanderailab.ml.MacroActionExecutor;
import commanderailab.ml.PolicyServerClient;
import commanderailab.schema.DecisionSnapshot;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * PolicyClient — Phase 2 bridge between Forge decision points and the
 * Python policy server for live online training.
 *
 * This class extends the existing LearnedPolicy/PolicyServerClient
 * infrastructure with two key Phase 2 capabilities:
 *
 * 1. Calls the new /api/policy/decide endpoint (purpose-built for live
 *    IPC with richer state including all zones, stack, and priority)
 *    instead of the batch-oriented /api/ml/predict.
 *
 * 2. Collects (state, action, reward) tuples in real-time during live
 *    Forge games and flushes them to the policy server for online PPO
 *    updates via POST /api/policy/collect.
 *
 * Falls back to ForgeBuiltinPolicy heuristics if the policy server
 * is unreachable or returns an error.
 *
 * Usage:
 *   PolicyClient client = new PolicyClient("http://localhost:8080");
 *   if (client.connect()) {
 *       // At each Forge decision point:
 *       String action = client.decide(fullGameState);
 *       // After game ends:
 *       client.submitReward(gameId, reward);
 *       client.flushCollectedTuples();
 *   }
 *
 * Refs: Issue #83 Phase 2.1
 */
public class PolicyClient {

    private static final Gson GSON = new GsonBuilder().create();
    private static final int CONNECT_TIMEOUT_MS = 2000;
    private static final int READ_TIMEOUT_MS = 30_000;

    private final String baseUrl;
    private final LearnedPolicy learnedPolicy;
    private volatile boolean serverAvailable = false;
    private volatile String lastError = "";

    // Online learning tuple buffer
    private final ConcurrentLinkedQueue<JsonObject> tupleBuffer = new ConcurrentLinkedQueue<>();
    private static final int FLUSH_THRESHOLD = 64;

    // Stats
    private int totalDecisions = 0;
    private int policyDecisions = 0;
    private int fallbackDecisions = 0;
    private long totalLatencyMs = 0;

    public PolicyClient(String serverUrl) {
        this.baseUrl = serverUrl.endsWith("/")
            ? serverUrl.substring(0, serverUrl.length() - 1)
            : serverUrl;
        this.learnedPolicy = new LearnedPolicy(serverUrl);
    }

    public PolicyClient(String serverUrl, String playstyle, boolean greedy) {
        this(serverUrl);
        this.learnedPolicy.setPlaystyle(playstyle);
        this.learnedPolicy.setGreedy(greedy);
    }

    // ================================================================
    // Connection
    // ================================================================

    /**
     * Check that the policy server's /api/policy/decide endpoint is live
     * and a model is loaded. Falls back to checking /api/ml/model if the
     * new endpoint isn't available yet.
     */
    public boolean connect() {
        try {
            String json = httpGet(baseUrl + "/api/policy/health");
            serverAvailable = json.contains("\"ready\":true")
                           || json.contains("\"status\":\"ok\"");
        } catch (Exception e) {
            // Fall back to legacy health check
            serverAvailable = learnedPolicy.connect();
        }
        if (serverAvailable) {
            System.out.println("[PolicyClient] Connected to policy server");
        } else {
            System.out.println("[PolicyClient] Server unavailable, using Forge built-in AI");
        }
        return serverAvailable;
    }

    // ================================================================
    // Phase 2.1 — Live decision endpoint
    // ================================================================

    /**
     * Request a macro-action decision from the policy server using the
     * full Forge game state (all zones, stack, priority).
     *
     * This calls POST /api/policy/decide which is purpose-built for the
     * live IPC loop, as opposed to /api/ml/predict which was designed
     * for batch inference.
     *
     * @param gameState Full game state JSON with all zones and priority info
     * @return macro-action name (e.g., "cast_creature"), or "pass" on failure
     */
    public String decide(JsonObject gameState) {
        totalDecisions++;
        long t0 = System.currentTimeMillis();

        if (!serverAvailable) {
            fallbackDecisions++;
            return MacroActionExecutor.PASS;
        }

        try {
            // Add inference params
            gameState.addProperty("playstyle", learnedPolicy.getPlaystyle());
            gameState.addProperty("greedy", learnedPolicy.isGreedy());

            String responseJson = httpPost(
                baseUrl + "/api/policy/decide",
                gameState.toString()
            );

            JsonObject resp = GSON.fromJson(responseJson, JsonObject.class);
            long elapsed = System.currentTimeMillis() - t0;
            totalLatencyMs += elapsed;

            if (resp.has("action") && !resp.has("error")) {
                policyDecisions++;
                String action = resp.get("action").getAsString();

                // Store tuple for online learning
                collectTuple(gameState, action, resp);

                return action;
            } else {
                fallbackDecisions++;
                lastError = resp.has("error")
                    ? resp.get("error").getAsString()
                    : "Unknown error";
                return MacroActionExecutor.PASS;
            }
        } catch (Exception e) {
            fallbackDecisions++;
            lastError = e.getMessage();
            return MacroActionExecutor.PASS;
        }
    }

    /**
     * Convenience: decide from a DecisionSnapshot (delegates to the
     * existing LearnedPolicy path if /api/policy/decide is unavailable).
     */
    public String decide(DecisionSnapshot snapshot) {
        return learnedPolicy.decideAction(snapshot);
    }

    /**
     * Resolve a decision to a concrete Forge action.
     */
    public MacroActionExecutor.ActionResolution resolveAction(
        JsonObject gameState,
        List<String> hand,
        List<String> battlefield,
        List<String> commandZone,
        int manaAvailable,
        String commanderName,
        int commanderTax
    ) {
        String macroAction = decide(gameState);
        return MacroActionExecutor.resolve(
            macroAction, hand, battlefield, commandZone,
            manaAvailable, commanderName, commanderTax
        );
    }

    // ================================================================
    // Phase 2.1 — Online learning tuple collection
    // ================================================================

    /**
     * Buffer a (state, action, prediction_metadata) tuple for later
     * submission to the policy server for online PPO updates.
     */
    private void collectTuple(JsonObject state, String action, JsonObject prediction) {
        JsonObject tuple = new JsonObject();
        tuple.add("state", state);
        tuple.addProperty("action", action);
        if (prediction.has("action_index")) {
            tuple.addProperty("action_index", prediction.get("action_index").getAsInt());
        }
        if (prediction.has("log_prob")) {
            tuple.addProperty("log_prob", prediction.get("log_prob").getAsDouble());
        }
        if (prediction.has("value")) {
            tuple.addProperty("value", prediction.get("value").getAsDouble());
        }
        tuple.addProperty("timestamp", System.currentTimeMillis());

        tupleBuffer.add(tuple);

        // Auto-flush when buffer is full
        if (tupleBuffer.size() >= FLUSH_THRESHOLD) {
            flushCollectedTuples();
        }
    }

    /**
     * Submit end-of-game reward for all tuples in the current game.
     * Call this after a Forge game completes.
     */
    public void submitReward(String gameId, double reward) {
        try {
            JsonObject body = new JsonObject();
            body.addProperty("game_id", gameId);
            body.addProperty("reward", reward);
            httpPost(baseUrl + "/api/policy/reward", body.toString());
        } catch (Exception e) {
            System.err.println("[PolicyClient] Failed to submit reward: " + e.getMessage());
        }
    }

    /**
     * Flush buffered (state, action, reward) tuples to the policy server
     * for online PPO updates via POST /api/policy/collect.
     */
    public void flushCollectedTuples() {
        if (tupleBuffer.isEmpty()) return;

        JsonArray batch = new JsonArray();
        JsonObject tuple;
        while ((tuple = tupleBuffer.poll()) != null) {
            batch.add(tuple);
        }

        try {
            JsonObject body = new JsonObject();
            body.add("tuples", batch);
            body.addProperty("count", batch.size());
            httpPost(baseUrl + "/api/policy/collect", body.toString());
            System.out.println("[PolicyClient] Flushed " + batch.size() + " tuples");
        } catch (Exception e) {
            System.err.println("[PolicyClient] Failed to flush tuples: " + e.getMessage());
            // Re-queue on failure
            for (int i = 0; i < batch.size(); i++) {
                tupleBuffer.add(batch.get(i).getAsJsonObject());
            }
        }
    }

    // ================================================================
    // Accessors
    // ================================================================

    public boolean isServerAvailable() { return serverAvailable; }
    public String getLastError() { return lastError; }
    public int getTotalDecisions() { return totalDecisions; }
    public int getPolicyDecisions() { return policyDecisions; }
    public int getFallbackDecisions() { return fallbackDecisions; }
    public int getPendingTuples() { return tupleBuffer.size(); }

    public double getAverageLatencyMs() {
        return policyDecisions > 0
            ? (double) totalLatencyMs / policyDecisions
            : 0;
    }

    public String getStatsSummary() {
        return String.format(
            "PolicyClient[decisions=%d, policy=%d, fallback=%d, avg=%.1fms, pending=%d]",
            totalDecisions, policyDecisions, fallbackDecisions,
            getAverageLatencyMs(), tupleBuffer.size()
        );
    }

    // ================================================================
    // HTTP helpers
    // ================================================================

    private String httpGet(String url) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("GET");
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(READ_TIMEOUT_MS);
        conn.setRequestProperty("Accept", "application/json");
        int code = conn.getResponseCode();
        if (code != 200) {
            throw new IOException("HTTP " + code + ": " + readStream(conn.getErrorStream()));
        }
        return readStream(conn.getInputStream());
    }

    private String httpPost(String url, String jsonBody) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(READ_TIMEOUT_MS);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Accept", "application/json");
        try (OutputStream os = conn.getOutputStream()) {
            os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
        }
        int code = conn.getResponseCode();
        if (code != 200) {
            throw new IOException("HTTP " + code + ": " + readStream(conn.getErrorStream()));
        }
        return readStream(conn.getInputStream());
    }

    private String readStream(InputStream stream) throws IOException {
        if (stream == null) return "";
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            return sb.toString();
        }
    }
}
