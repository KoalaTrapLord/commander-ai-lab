package commanderailab.schema;

import java.util.*;
import java.util.logging.Logger;
import java.util.regex.Pattern;

/**
 * WinCondition — Formal enum for game outcome classification.
 *
 * Centralizes all known Forge loss-reason strings into a single mapping.
 * Unknown/new loss reasons are logged and classified as UNKNOWN rather
 * than silently dropped.
 *
 * Resolves: GitHub Issue #2
 */
public enum WinCondition {

    COMBAT_DAMAGE("combat_damage", "Life total reduced to 0 or below via combat/direct damage"),
    COMMANDER_DAMAGE("commander_damage", "21+ commander damage from a single commander"),
    MILL("mill", "Library emptied — drew from empty library"),
    COMBO_ALT_WIN("combo_alt_win", "Alternate win condition (poison, Laboratory Maniac, etc.)"),
    LIFE_DRAIN("life_drain", "Life total reduced by non-combat sources (drain, burn spells)"),
    CONCESSION("concession", "Opponent conceded"),
    TIMEOUT("timeout", "Game clock expired or draw"),
    UNKNOWN("unknown", "Unrecognized win condition — see logs");

    private static final Logger LOG = Logger.getLogger(WinCondition.class.getName());

    private final String label;
    private final String description;

    WinCondition(String label, String description) {
        this.label = label;
        this.description = description;
    }

    public String getLabel() { return label; }
    public String getDescription() { return description; }

    // ── Forge loss-reason string → WinCondition mapping ─────────────────
    //
    // Known Forge quiet-mode loss reasons (from forge-gui-desktop source):
    //   "life total reached 0"
    //   "life total reached -N"
    //   "ran out of cards"
    //   "drew from an empty library"
    //   "drew from empty library"
    //   "received 21 or more commander damage"
    //   "got 10 or more poison counters"
    //   "an opponent has won the game"
    //   "conceded"
    //   "all opponents have lost"

    private static final List<LossReasonMapping> LOSS_REASON_MAPPINGS = List.of(
        // Commander damage — must check BEFORE generic life-total patterns
        new LossReasonMapping(
            Pattern.compile("commander\\s+damage", Pattern.CASE_INSENSITIVE),
            COMMANDER_DAMAGE
        ),

        // Poison counters
        new LossReasonMapping(
            Pattern.compile("poison\\s+counter", Pattern.CASE_INSENSITIVE),
            COMBO_ALT_WIN
        ),

        // Mill — empty library
        new LossReasonMapping(
            Pattern.compile("ran\\s+out\\s+of\\s+cards|empty\\s+library|drew\\s+from\\s+.+library", Pattern.CASE_INSENSITIVE),
            MILL
        ),

        // Alternate win conditions (e.g., "wins the game", "won the game")
        new LossReasonMapping(
            Pattern.compile("alternate\\s+win|wins\\s+the\\s+game|won\\s+the\\s+game", Pattern.CASE_INSENSITIVE),
            COMBO_ALT_WIN
        ),

        // Concession
        new LossReasonMapping(
            Pattern.compile("concede", Pattern.CASE_INSENSITIVE),
            CONCESSION
        ),

        // Life total reached 0 or below — generic combat/damage
        new LossReasonMapping(
            Pattern.compile("life\\s+total\\s+reached", Pattern.CASE_INSENSITIVE),
            COMBAT_DAMAGE
        ),

        // Timeout / clock / draw
        new LossReasonMapping(
            Pattern.compile("clock|time\\s+limit|timed?\\s*out", Pattern.CASE_INSENSITIVE),
            TIMEOUT
        )
    );

    /**
     * Classify win condition from a map of loser seat → loss reason strings,
     * plus the full Forge output for additional context scanning.
     *
     * @param lossReasons Map of seat index (as string) → Forge loss reason text
     * @param fullOutput  Complete Forge stdout for fallback pattern matching
     * @return The classified WinCondition
     */
    public static WinCondition classify(Map<String, String> lossReasons, String fullOutput) {
        String combinedReasons = String.join(" ", lossReasons.values()).toLowerCase();
        String lowerOutput = fullOutput.toLowerCase();

        // First pass: check combined loss reason strings
        for (LossReasonMapping mapping : LOSS_REASON_MAPPINGS) {
            if (mapping.pattern.matcher(combinedReasons).find()) {
                return mapping.condition;
            }
        }

        // Second pass: scan full output for patterns not in loss reasons
        for (LossReasonMapping mapping : LOSS_REASON_MAPPINGS) {
            if (mapping.pattern.matcher(lowerOutput).find()) {
                // For timeout, only classify if there's no winner (no loss reasons)
                if (mapping.condition == TIMEOUT && !lossReasons.isEmpty()) {
                    continue;
                }
                return mapping.condition;
            }
        }

        // Check for draw indicators in full output
        if (lowerOutput.contains("draw") && lossReasons.isEmpty()) {
            return TIMEOUT;
        }

        // UNKNOWN — log for review so we can add new mappings
        if (!lossReasons.isEmpty()) {
            LOG.warning("[WinCondition] Unrecognized loss reasons — logging for review:");
            for (Map.Entry<String, String> entry : lossReasons.entrySet()) {
                LOG.warning("  Seat " + entry.getKey() + ": \"" + entry.getValue() + "\"");
            }
        }

        return UNKNOWN;
    }

    /**
     * Convert label string back to enum (for deserialization / backward compat).
     */
    public static WinCondition fromLabel(String label) {
        if (label == null) return UNKNOWN;
        for (WinCondition wc : values()) {
            if (wc.label.equals(label)) return wc;
        }
        LOG.warning("[WinCondition] Unknown label: \"" + label + "\"");
        return UNKNOWN;
    }

    @Override
    public String toString() {
        return label;
    }

    // ── Internal mapping record ─────────────────────────────────────────

    private record LossReasonMapping(Pattern pattern, WinCondition condition) {}
}
