package commanderailab.ai;

/**
 * AiPolicy — Abstraction for AI decision-making in Commander.
 *
 * v1 uses Forge's built-in AI, but this interface allows swapping in
 * custom heuristic or learned policies in v2+.
 *
 * The policy scores actions based on weighted features:
 *   - Card advantage
 *   - Tempo / mana efficiency
 *   - Threat scoring per opponent
 *   - Basic combat logic
 */
public interface AiPolicy {

    /**
     * Unique name of this policy (e.g., "forge-builtin", "utility-v1").
     */
    String getName();

    /**
     * Weight for card-advantage heuristic (0.0–1.0).
     */
    double getCardAdvantageWeight();

    /**
     * Weight for tempo/mana-efficiency heuristic (0.0–1.0).
     */
    double getTempoWeight();

    /**
     * Weight for threat scoring per opponent (0.0–1.0).
     */
    double getThreatScoringWeight();

    /**
     * Weight for combat-outcome evaluation (0.0–1.0).
     */
    double getCombatWeight();

    /**
     * Whether this policy delegates to Forge's built-in AI.
     * When true, the batch runner uses Forge's sim mode directly.
     * When false, decisions are intercepted by BridgePlayerController.
     */
    boolean usesForgeBuiltinAi();
}
