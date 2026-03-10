package commanderailab.schema;

import java.util.List;

/**
 * DecisionSnapshot — State + action at a single decision point.
 *
 * Captures the full game state observable to the active player,
 * plus the action taken. Used for supervised learning of a policy network.
 *
 * Serialized as JSON, one per decision point per game.
 * Format: {"RL_DECISION": <json>} on a single log line so it can be
 * parsed reliably from Forge subprocess output.
 *
 * State encoding (consumed by Python ml/encoder/):
 *   - Global: turn, phase, active_seat
 *   - Per-player: life, cmdr_damage, mana, cards_in_hand, etc.
 *   - Per-zone per-player: list of card names (IDs resolved Python-side)
 *
 * Action: the raw Forge action string, later labeled into a macro-action
 *         by ml/actions/labeler.py
 */
public class DecisionSnapshot {

    // ── Game context ──────────────────────────────────────────
    public String gameId;
    public int turnNumber;
    public String phase;            // "main_1", "combat", "main_2", "end"
    public int activeSeat;          // 0-based seat index of acting player

    // ── Per-player state (index = seat) ──────────────────────
    public List<PlayerSnapshot> players;

    // ── Action taken ─────────────────────────────────────────
    public ActionRecord action;

    // ══════════════════════════════════════════════════════════
    // Player state at this decision point
    // ══════════════════════════════════════════════════════════

    public static class PlayerSnapshot {
        public int seatIndex;
        public int lifeTotal;
        public int commanderDamageTaken;     // from opponent's commander
        public int manaAvailable;            // untapped mana sources
        public int commanderTax;             // times commander has been cast × 2
        public int commanderCasts;

        // Zone contents — card names for embedding lookup
        public List<String> hand;
        public List<String> battlefield;     // permanents controlled
        public List<String> graveyard;
        public List<String> commandZone;     // commander if not on field

        // Board summary stats (pre-computed for faster encoding)
        public int creaturesOnField;
        public int totalPowerOnBoard;
        public int totalToughnessOnBoard;
        public int artifactsOnField;
        public int enchantmentsOnField;
        public int landCount;               // lands on battlefield
    }

    // ══════════════════════════════════════════════════════════
    // Action record — what the AI chose to do
    // ══════════════════════════════════════════════════════════

    public static class ActionRecord {
        public String type;                  // "cast", "attack", "activate", "pass", "land"
        public String cardName;              // card involved (null for pass/attack)
        public String targetDescription;     // human-readable target ("Ai(2)-Name", etc.)
        public String rawLogLine;            // original Forge log line for this action
    }
}
