package commanderailab.ai;

import java.util.*;

/**
 * AiProfile — Configurable AI behavior profile for Commander simulations.
 *
 * Each profile defines a set of heuristic weights that influence how the
 * Forge AI evaluates decisions. These map to Forge's internal AI tuning
 * parameters where available, and to our own post-processing heuristics.
 *
 * v2 Design:
 *   - Profiles are serializable to/from JSON for storage and UI selection
 *   - Built-in presets: DEFAULT, AGGRO, CONTROL, COMBO, MIDRANGE
 *   - Custom profiles can override any weight
 *   - Weights are normalized 0.0 – 1.0 (0 = ignore, 1 = maximum priority)
 */
public class AiProfile {

    // ── Identity ───────────────────────────────────────────
    private String name;
    private String description;

    // ── Combat Weights ─────────────────────────────────────
    /** How eagerly the AI attacks (0 = conservative, 1 = all-out aggro) */
    private double aggression = 0.5;

    /** How much the AI values trading creatures in combat */
    private double combatWillingness = 0.5;

    /** Priority on dealing commander damage vs regular damage */
    private double commanderDamagePriority = 0.3;

    // ── Resource Weights ───────────────────────────────────
    /** How much the AI values mana efficiency (curving out, using all mana) */
    private double manaEfficiency = 0.5;

    /** How much the AI values card advantage (drawing, cantrips) */
    private double cardAdvantage = 0.5;

    /** How much the AI prioritizes ramping / mana acceleration */
    private double rampPriority = 0.4;

    // ── Threat Assessment ──────────────────────────────────
    /** How much the AI focuses on the leading player */
    private double threatFocus = 0.5;

    /** How much the AI values removal / interaction spells */
    private double removalPriority = 0.5;

    /** How likely the AI is to use removal on the biggest threat vs spreading */
    private double targetConcentration = 0.5;

    // ── Strategic Weights ──────────────────────────────────
    /** How much the AI values board presence (creatures on battlefield) */
    private double boardPresence = 0.5;

    /** How much the AI holds back resources for future turns */
    private double patience = 0.5;

    /** How much the AI values combo pieces and assembling combos */
    private double comboPriority = 0.3;

    /** Mulligan aggressiveness (higher = more willing to mulligan weak hands) */
    private double mulliganStrictness = 0.5;

    // ── Forge Sim Flags ────────────────────────────────────
    /** Clock override in seconds (0 = use default) */
    private int clockOverride = 0;

    // ══════════════════════════════════════════════════════════
    // Constructors
    // ══════════════════════════════════════════════════════════

    public AiProfile() {
        this.name = "custom";
        this.description = "Custom AI profile";
    }

    public AiProfile(String name, String description) {
        this.name = name;
        this.description = description;
    }

    // ══════════════════════════════════════════════════════════
    // Built-in Presets
    // ══════════════════════════════════════════════════════════

    /** Default balanced profile — Forge's built-in AI behavior. */
    public static AiProfile defaultProfile() {
        AiProfile p = new AiProfile("default", "Balanced — Forge's default AI behavior");
        // All weights at 0.5 (balanced)
        return p;
    }

    /** Aggro profile — attacks early and often, prioritizes damage output. */
    public static AiProfile aggro() {
        AiProfile p = new AiProfile("aggro", "Aggressive — attacks early, prioritizes damage");
        p.aggression = 0.9;
        p.combatWillingness = 0.8;
        p.commanderDamagePriority = 0.6;
        p.manaEfficiency = 0.7;
        p.cardAdvantage = 0.3;
        p.rampPriority = 0.2;
        p.threatFocus = 0.3;
        p.removalPriority = 0.3;
        p.targetConcentration = 0.7;
        p.boardPresence = 0.8;
        p.patience = 0.1;
        p.comboPriority = 0.1;
        p.mulliganStrictness = 0.6;
        return p;
    }

    /** Control profile — plays defensively, prioritizes removal and card draw. */
    public static AiProfile control() {
        AiProfile p = new AiProfile("control", "Control — defensive, removal-heavy, card advantage");
        p.aggression = 0.2;
        p.combatWillingness = 0.3;
        p.commanderDamagePriority = 0.2;
        p.manaEfficiency = 0.6;
        p.cardAdvantage = 0.9;
        p.rampPriority = 0.6;
        p.threatFocus = 0.8;
        p.removalPriority = 0.9;
        p.targetConcentration = 0.8;
        p.boardPresence = 0.3;
        p.patience = 0.9;
        p.comboPriority = 0.4;
        p.mulliganStrictness = 0.7;
        return p;
    }

    /** Combo profile — assembles win conditions, protects key pieces. */
    public static AiProfile combo() {
        AiProfile p = new AiProfile("combo", "Combo — ramps, digs for pieces, assembles combos");
        p.aggression = 0.2;
        p.combatWillingness = 0.2;
        p.commanderDamagePriority = 0.1;
        p.manaEfficiency = 0.8;
        p.cardAdvantage = 0.8;
        p.rampPriority = 0.9;
        p.threatFocus = 0.4;
        p.removalPriority = 0.4;
        p.targetConcentration = 0.5;
        p.boardPresence = 0.3;
        p.patience = 0.7;
        p.comboPriority = 0.95;
        p.mulliganStrictness = 0.8;
        return p;
    }

    /** Midrange profile — flexible, adapts between aggro and control. */
    public static AiProfile midrange() {
        AiProfile p = new AiProfile("midrange", "Midrange — flexible, strong board presence, value-oriented");
        p.aggression = 0.5;
        p.combatWillingness = 0.6;
        p.commanderDamagePriority = 0.4;
        p.manaEfficiency = 0.6;
        p.cardAdvantage = 0.6;
        p.rampPriority = 0.5;
        p.threatFocus = 0.6;
        p.removalPriority = 0.6;
        p.targetConcentration = 0.5;
        p.boardPresence = 0.7;
        p.patience = 0.5;
        p.comboPriority = 0.3;
        p.mulliganStrictness = 0.5;
        return p;
    }

    /** Get a preset by name. */
    public static AiProfile byName(String name) {
        return switch (name.toLowerCase()) {
            case "aggro" -> aggro();
            case "control" -> control();
            case "combo" -> combo();
            case "midrange" -> midrange();
            default -> defaultProfile();
        };
    }

    /** List all preset names. */
    public static List<String> presetNames() {
        return List.of("default", "aggro", "control", "combo", "midrange");
    }

    /** Get all presets as a map. */
    public static Map<String, AiProfile> allPresets() {
        Map<String, AiProfile> presets = new LinkedHashMap<>();
        presets.put("default", defaultProfile());
        presets.put("aggro", aggro());
        presets.put("control", control());
        presets.put("combo", combo());
        presets.put("midrange", midrange());
        return presets;
    }

    // ══════════════════════════════════════════════════════════
    // Utility Methods
    // ══════════════════════════════════════════════════════════

    /**
     * Compute an overall "style score" for display purposes.
     * Returns a map of style dimensions to 0-100 integer scores.
     */
    public Map<String, Integer> getStyleRadar() {
        Map<String, Integer> radar = new LinkedHashMap<>();
        radar.put("Aggression", toPercent(aggression));
        radar.put("Card Advantage", toPercent(cardAdvantage));
        radar.put("Removal", toPercent(removalPriority));
        radar.put("Board Presence", toPercent(boardPresence));
        radar.put("Combo", toPercent(comboPriority));
        radar.put("Patience", toPercent(patience));
        return radar;
    }

    private int toPercent(double val) {
        return (int) Math.round(val * 100);
    }

    /**
     * Create a summary string for CLI / log output.
     */
    public String toSummaryString() {
        return String.format(
            "AiProfile[%s] — aggro=%.1f card=%.1f removal=%.1f board=%.1f combo=%.1f patience=%.1f",
            name, aggression, cardAdvantage, removalPriority, boardPresence, comboPriority, patience
        );
    }

    // ══════════════════════════════════════════════════════════
    // Getters / Setters
    // ══════════════════════════════════════════════════════════

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDescription() { return description; }
    public void setDescription(String desc) { this.description = desc; }

    public double getAggression() { return aggression; }
    public void setAggression(double v) { this.aggression = clamp(v); }
    public double getCombatWillingness() { return combatWillingness; }
    public void setCombatWillingness(double v) { this.combatWillingness = clamp(v); }
    public double getCommanderDamagePriority() { return commanderDamagePriority; }
    public void setCommanderDamagePriority(double v) { this.commanderDamagePriority = clamp(v); }

    public double getManaEfficiency() { return manaEfficiency; }
    public void setManaEfficiency(double v) { this.manaEfficiency = clamp(v); }
    public double getCardAdvantage() { return cardAdvantage; }
    public void setCardAdvantage(double v) { this.cardAdvantage = clamp(v); }
    public double getRampPriority() { return rampPriority; }
    public void setRampPriority(double v) { this.rampPriority = clamp(v); }

    public double getThreatFocus() { return threatFocus; }
    public void setThreatFocus(double v) { this.threatFocus = clamp(v); }
    public double getRemovalPriority() { return removalPriority; }
    public void setRemovalPriority(double v) { this.removalPriority = clamp(v); }
    public double getTargetConcentration() { return targetConcentration; }
    public void setTargetConcentration(double v) { this.targetConcentration = clamp(v); }

    public double getBoardPresence() { return boardPresence; }
    public void setBoardPresence(double v) { this.boardPresence = clamp(v); }
    public double getPatience() { return patience; }
    public void setPatience(double v) { this.patience = clamp(v); }
    public double getComboPriority() { return comboPriority; }
    public void setComboPriority(double v) { this.comboPriority = clamp(v); }
    public double getMulliganStrictness() { return mulliganStrictness; }
    public void setMulliganStrictness(double v) { this.mulliganStrictness = clamp(v); }

    public int getClockOverride() { return clockOverride; }
    public void setClockOverride(int v) { this.clockOverride = v; }

    private double clamp(double v) { return Math.max(0.0, Math.min(1.0, v)); }
}
