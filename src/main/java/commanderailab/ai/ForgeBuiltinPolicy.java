package commanderailab.ai;

/**
 * ForgeBuiltinPolicy — v1 default policy that delegates all decisions
 * to Forge's built-in utility-based AI.
 *
 * This is the simplest and most correct starting point because Forge's AI
 * already handles:
 *   - Mana payment and land sequencing
 *   - Spell casting priority
 *   - Attacker/blocker declaration
 *   - Target selection
 *   - Mulligan decisions
 *
 * The weight fields here are placeholders for future custom policies.
 */
public class ForgeBuiltinPolicy implements AiPolicy {

    private final double cardAdvantageWeight;
    private final double tempoWeight;
    private final double threatScoringWeight;
    private final double combatWeight;

    public ForgeBuiltinPolicy() {
        // Default balanced weights (used as metadata; Forge AI makes actual decisions)
        this(0.25, 0.30, 0.25, 0.20);
    }

    public ForgeBuiltinPolicy(double cardAdv, double tempo, double threat, double combat) {
        this.cardAdvantageWeight = cardAdv;
        this.tempoWeight = tempo;
        this.threatScoringWeight = threat;
        this.combatWeight = combat;
    }

    @Override
    public String getName() {
        return "forge-builtin";
    }

    @Override
    public double getCardAdvantageWeight() {
        return cardAdvantageWeight;
    }

    @Override
    public double getTempoWeight() {
        return tempoWeight;
    }

    @Override
    public double getThreatScoringWeight() {
        return threatScoringWeight;
    }

    @Override
    public double getCombatWeight() {
        return combatWeight;
    }

    @Override
    public boolean usesForgeBuiltinAi() {
        return true;
    }

    @Override
    public String toString() {
        return String.format("ForgeBuiltinPolicy[cardAdv=%.2f, tempo=%.2f, threat=%.2f, combat=%.2f]",
                cardAdvantageWeight, tempoWeight, threatScoringWeight, combatWeight);
    }
}
