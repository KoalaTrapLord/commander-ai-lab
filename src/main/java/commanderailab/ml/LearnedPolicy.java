package commanderailab.ml;

import commanderailab.ai.AiPolicy;
import commanderailab.schema.DecisionSnapshot;

import java.util.*;

/**
 * LearnedPolicy — AI policy backed by a trained neural network.
 *
 * Instead of using Forge's built-in heuristic AI, this policy queries
 * the Python policy server (via PolicyServerClient) for macro-action
 * decisions at each game decision point.
 *
 * The policy server runs the trained PolicyNetwork:
 *   game state → state encoder → neural network → macro-action
 *
 * If the policy server is unavailable, falls back to Forge's built-in AI.
 *
 * Usage:
 *   LearnedPolicy policy = new LearnedPolicy("http://localhost:8080");
 *   policy.setPlaystyle("aggro");
 *   policy.setGreedy(true);
 *
 *   // In the game loop:
 *   DecisionSnapshot state = captureGameState();
 *   String macroAction = policy.decideAction(state);
 *   MacroActionExecutor.ActionResolution action =
 *       MacroActionExecutor.resolve(macroAction, hand, battlefield, ...);
 *
 * Integration with BatchRunner:
 *   When usesForgeBuiltinAi() returns false, the BatchRunner should
 *   intercept decisions and call decideAction() instead. For the
 *   initial version (Phase 7), this works alongside Forge's AI —
 *   the policy's decision is logged but Forge still executes the game.
 *   In Phase 8+, decisions will be fully intercepted.
 */
public class LearnedPolicy implements AiPolicy {

    private final PolicyServerClient client;
    private String playstyle;
    private boolean greedy;
    private boolean policyServerAvailable;

    // Stats
    private int totalQueries = 0;
    private int successfulQueries = 0;
    private int fallbackQueries = 0;
    private long totalInferenceMs = 0;

    // Cache the last prediction for logging
    private PolicyServerClient.PolicyPrediction lastPrediction;

    /**
     * Create a learned policy connected to the lab API server.
     *
     * @param serverUrl Base URL (e.g., "http://localhost:8080")
     */
    public LearnedPolicy(String serverUrl) {
        this.client = new PolicyServerClient(serverUrl);
        this.playstyle = "midrange";
        this.greedy = true;
        this.policyServerAvailable = false;
    }

    /**
     * Create with explicit settings.
     */
    public LearnedPolicy(String serverUrl, String playstyle, boolean greedy) {
        this(serverUrl);
        this.playstyle = playstyle;
        this.greedy = greedy;
    }

    // ══════════════════════════════════════════════════════════
    // Connection
    // ══════════════════════════════════════════════════════════

    /**
     * Check if the policy server has a trained model loaded.
     * Call this at startup to decide whether to use learned policy.
     */
    public boolean connect() {
        policyServerAvailable = client.isAvailable();
        if (policyServerAvailable) {
            System.out.println("[ML] Learned policy connected — server has model loaded");
        } else {
            System.out.println("[ML] Learned policy not available: " + client.getLastError());
            System.out.println("[ML] Falling back to Forge built-in AI");
        }
        return policyServerAvailable;
    }

    /**
     * Request the server to reload the model (after training).
     */
    public boolean reloadModel() {
        boolean ok = client.reloadModel();
        if (ok) {
            policyServerAvailable = true;
            System.out.println("[ML] Model reloaded successfully");
        }
        return ok;
    }

    // ══════════════════════════════════════════════════════════
    // Decision Making
    // ══════════════════════════════════════════════════════════

    /**
     * Query the policy network for a macro-action decision.
     *
     * @param snapshot Current game state snapshot
     * @return Macro-action name (e.g., "cast_creature"), or "pass" on failure
     */
    public String decideAction(DecisionSnapshot snapshot) {
        totalQueries++;

        if (!policyServerAvailable) {
            fallbackQueries++;
            return MacroActionExecutor.PASS;
        }

        PolicyServerClient.PolicyPrediction pred = client.predict(snapshot, playstyle, greedy);
        lastPrediction = pred;

        if (pred.isValid()) {
            successfulQueries++;
            totalInferenceMs += (long) pred.inferenceMs;
            return pred.action;
        } else {
            fallbackQueries++;
            System.err.println("[ML] Prediction failed: " + pred.error);
            return MacroActionExecutor.PASS;
        }
    }

    /**
     * Get the full prediction result for the last decision.
     * Useful for logging probabilities alongside game actions.
     */
    public PolicyServerClient.PolicyPrediction getLastPrediction() {
        return lastPrediction;
    }

    /**
     * Resolve the last decision to a concrete action.
     * Convenience method that combines decideAction + MacroActionExecutor.
     */
    public MacroActionExecutor.ActionResolution resolveAction(
            DecisionSnapshot snapshot,
            List<String> hand,
            List<String> battlefield,
            List<String> commandZone,
            int manaAvailable,
            String commanderName,
            int commanderTax
    ) {
        String macroAction = decideAction(snapshot);
        return MacroActionExecutor.resolve(
            macroAction, hand, battlefield, commandZone,
            manaAvailable, commanderName, commanderTax
        );
    }

    // ══════════════════════════════════════════════════════════
    // AiPolicy Interface
    // ══════════════════════════════════════════════════════════

    @Override
    public String getName() {
        return "learned-policy";
    }

    @Override
    public double getCardAdvantageWeight() {
        // These weights are not used by the learned policy
        // (the network learns its own weights)
        return 0.5;
    }

    @Override
    public double getTempoWeight() {
        return 0.5;
    }

    @Override
    public double getThreatScoringWeight() {
        return 0.5;
    }

    @Override
    public double getCombatWeight() {
        return 0.5;
    }

    @Override
    public boolean usesForgeBuiltinAi() {
        // When policy server is not available, fall back to Forge AI
        return !policyServerAvailable;
    }

    // ══════════════════════════════════════════════════════════
    // Configuration
    // ══════════════════════════════════════════════════════════

    public void setPlaystyle(String playstyle) {
        this.playstyle = playstyle;
    }

    public String getPlaystyle() {
        return playstyle;
    }

    public void setGreedy(boolean greedy) {
        this.greedy = greedy;
    }

    public boolean isGreedy() {
        return greedy;
    }

    public boolean isPolicyServerAvailable() {
        return policyServerAvailable;
    }

    // ══════════════════════════════════════════════════════════
    // Stats
    // ══════════════════════════════════════════════════════════

    public int getTotalQueries() { return totalQueries; }
    public int getSuccessfulQueries() { return successfulQueries; }
    public int getFallbackQueries() { return fallbackQueries; }

    public double getAverageInferenceMs() {
        return successfulQueries > 0 ? (double) totalInferenceMs / successfulQueries : 0;
    }

    public double getSuccessRate() {
        return totalQueries > 0 ? (double) successfulQueries / totalQueries : 0;
    }

    /**
     * Get a summary of policy performance for logging.
     */
    public String getStatsSummary() {
        return String.format(
            "LearnedPolicy[queries=%d, success=%d (%.1f%%), fallback=%d, avg_inference=%.1fms, style=%s, greedy=%s]",
            totalQueries, successfulQueries,
            getSuccessRate() * 100,
            fallbackQueries, getAverageInferenceMs(),
            playstyle, greedy
        );
    }

    public void resetStats() {
        totalQueries = 0;
        successfulQueries = 0;
        fallbackQueries = 0;
        totalInferenceMs = 0;
    }

    @Override
    public String toString() {
        return String.format("LearnedPolicy[server=%s, available=%s, style=%s]",
            policyServerAvailable ? "connected" : "disconnected",
            policyServerAvailable, playstyle);
    }
}
