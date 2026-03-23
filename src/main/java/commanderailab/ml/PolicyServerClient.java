package commanderailab.ml;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import commanderailab.schema.DecisionSnapshot;

/**
 * PolicyServerClient — HTTP client for the Python policy inference server.
 *
 * Sends game state snapshots to POST /api/ml/predict and receives
 * macro-action predictions from the trained PolicyNetwork.
 *
 * The client is designed to be lightweight and uses only java.net.HttpURLConnection
 * (no additional dependencies beyond Gson for JSON serialization).
 *
 * Usage:
 *   PolicyServerClient client = new PolicyServerClient("http://localhost:8080");
 *   if (client.isAvailable()) {
 *       PolicyPrediction pred = client.predict(snapshot, "aggro", true);
 *       System.out.println("Action: " + pred.action);
 *   }
 */
public class PolicyServerClient {

    private static final Gson GSON = new GsonBuilder().create();
    private static final int CONNECT_TIMEOUT_MS = 2000;
    private static final int READ_TIMEOUT_MS = 300_000;

    private final String baseUrl;
    private volatile boolean available = false;
    private volatile String lastError = "";

    /**
     * @param baseUrl Base URL of the lab API server (e.g., "http://localhost:8080")
     */
    public PolicyServerClient(String baseUrl) {
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
    }

    // ══════════════════════════════════════════════════════════
    // Prediction Response
    // ══════════════════════════════════════════════════════════

    /**
     * Result of a policy prediction.
     */
    public static class PolicyPrediction {
        /** Macro-action name (e.g., "cast_creature", "attack_opponent") */
        public String action;

        /** Action index (0-7) */
        public int actionIndex;

        /** Model confidence for the chosen action (0.0 - 1.0) */
        public double confidence;

        /** Full probability distribution over all actions */
        public Map<String, Double> probabilities;

        /** Inference time in milliseconds */
        public double inferenceMs;

        /** Error message if prediction failed */
        public String error;

        public boolean isValid() {
            return action != null && !action.isEmpty() && error == null;
        }

        @Override
        public String toString() {
            if (error != null) return "PolicyPrediction[error=" + error + "]";
            return String.format("PolicyPrediction[action=%s, conf=%.3f, %.1fms]",
                    action, confidence, inferenceMs);
        }
    }

    // ══════════════════════════════════════════════════════════
    // Model Status
    // ══════════════════════════════════════════════════════════

    public static class ModelStatus {
        public boolean loaded;
        public String error;
        public String device;
        public boolean torchAvailable;
    }

    // ══════════════════════════════════════════════════════════
    // API Methods
    // ══════════════════════════════════════════════════════════

    /**
     * Check if the policy server has a model loaded and ready.
     */
    public boolean isAvailable() {
        try {
            String json = httpGet(baseUrl + "/api/ml/model");
            ModelStatus status = GSON.fromJson(json, ModelStatus.class);
            available = status.loaded;
            if (!available) {
                lastError = status.error != null ? status.error : "Model not loaded";
            }
            return available;
        } catch (Exception e) {
            available = false;
            lastError = e.getMessage();
            return false;
        }
    }

    /**
     * Predict a macro-action from a DecisionSnapshot.
     *
     * @param snapshot  DecisionSnapshot object (will be serialized to JSON)
     * @param playstyle Deck playstyle: "aggro", "control", "midrange", "combo"
     * @param greedy    If true, always pick the highest-probability action
     * @return PolicyPrediction with the recommended action
     */
    public PolicyPrediction predict(DecisionSnapshot snapshot, String playstyle, boolean greedy) {
        try {
            // Build request JSON from the snapshot
            JsonObject request = buildPredictRequest(snapshot, playstyle, greedy);
            String responseJson = httpPost(baseUrl + "/api/ml/predict", request.toString());
            return GSON.fromJson(responseJson, PolicyPrediction.class);
        } catch (Exception e) {
            PolicyPrediction fail = new PolicyPrediction();
            fail.error = e.getMessage();
            lastError = e.getMessage();
            return fail;
        }
    }

    /**
     * Predict with default settings (midrange playstyle, greedy).
     */
    public PolicyPrediction predict(DecisionSnapshot snapshot) {
        return predict(snapshot, "midrange", true);
    }

    /**
     * Request the server to reload the model checkpoint.
     * Useful after training a new model.
     */
    public boolean reloadModel() {
        try {
            String json = httpPost(baseUrl + "/api/ml/reload", "{}");
            JsonObject resp = JsonParser.parseString(json).getAsJsonObject();
            return resp.has("success") && resp.get("success").getAsBoolean();
        } catch (Exception e) {
            lastError = e.getMessage();
            return false;
        }
    }

    /**
     * Get the last error message.
     */
    public String getLastError() {
        return lastError;
    }

    // ══════════════════════════════════════════════════════════
    // Request Building
    // ══════════════════════════════════════════════════════════

    /**
     * Convert a DecisionSnapshot + inference params into the JSON body
     * expected by POST /api/ml/predict.
     */
    private JsonObject buildPredictRequest(DecisionSnapshot snapshot, String playstyle, boolean greedy) {
        // Serialize the snapshot to JSON, then add inference params
        String snapshotJson = GSON.toJson(snapshot);
        JsonObject obj = JsonParser.parseString(snapshotJson).getAsJsonObject();

        // Map Java field names to Python expected names
        if (obj.has("turnNumber")) {
            obj.addProperty("turn", obj.get("turnNumber").getAsInt());
            obj.remove("turnNumber");
        }
        if (obj.has("activeSeat")) {
            obj.addProperty("active_seat", obj.get("activeSeat").getAsInt());
            obj.remove("activeSeat");
        }
        if (obj.has("gameId")) {
            obj.addProperty("game_id", obj.get("gameId").getAsString());
            obj.remove("gameId");
        }

        // Remap player fields from camelCase to snake_case
        if (obj.has("players") && obj.get("players").isJsonArray()) {
            for (var player : obj.getAsJsonArray("players")) {
                if (!player.isJsonObject()) continue;
                JsonObject p = player.getAsJsonObject();
                renameField(p, "seatIndex", "seat");
                renameField(p, "lifeTotal", "life");
                renameField(p, "commanderDamageTaken", "cmdr_dmg");
                renameField(p, "manaAvailable", "mana");
                renameField(p, "commanderTax", "cmdr_tax");
                renameField(p, "creaturesOnField", "creatures");
                renameField(p, "commandZone", "command_zone");
                renameField(p, "landCount", "lands");
            }
        }

        // Add inference parameters
        obj.addProperty("archetype", playstyle);
        obj.addProperty("greedy", greedy);
        obj.addProperty("temperature", 1.0);

        return obj;
    }

    private void renameField(JsonObject obj, String from, String to) {
        if (obj.has(from)) {
            obj.add(to, obj.get(from));
            obj.remove(from);
        }
    }

    // ══════════════════════════════════════════════════════════
    // HTTP Helpers
    // ══════════════════════════════════════════════════════════

    private String httpGet(String url) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("GET");
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(READ_TIMEOUT_MS);
        conn.setRequestProperty("Accept", "application/json");

        int code = conn.getResponseCode();
        if (code != 200) {
            String errorBody = readStream(conn.getErrorStream());
            throw new IOException("HTTP " + code + ": " + errorBody);
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
            String errorBody = readStream(conn.getErrorStream());
            throw new IOException("HTTP " + code + ": " + errorBody);
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
