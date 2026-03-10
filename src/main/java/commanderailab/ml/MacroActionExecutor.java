package commanderailab.ml;

import java.util.*;

/**
 * MacroActionExecutor — Translates learned policy macro-actions into
 * concrete Forge action descriptions.
 *
 * The policy network outputs one of 8 macro-actions. This class maps
 * each macro-action to a heuristic that selects the best concrete
 * Forge action from the available options.
 *
 * Macro-action space (matching ml/config/scope.py):
 *   0: cast_creature      — Play the best available creature from hand
 *   1: cast_removal        — Cast removal/interaction on biggest threat
 *   2: cast_draw           — Cast a card-draw or cantrip spell
 *   3: cast_ramp           — Cast a ramp spell or mana rock
 *   4: cast_commander      — Cast commander from command zone
 *   5: attack_opponent     — Attack with profitable attackers
 *   6: hold_mana           — Pass priority, keep mana open
 *   7: pass                — Pass with no action
 *
 * Integration:
 *   This is designed to work with Forge's game state. In Phase 8+,
 *   when we intercept Forge's decision loop, this class selects
 *   which concrete card/ability to use based on the macro-action.
 *
 *   For now (Phase 7), it produces structured guidance that can be
 *   logged alongside the policy's decision for analysis.
 */
public class MacroActionExecutor {

    // ── Macro-action constants (must match Python scope.py indices) ──
    public static final String CAST_CREATURE = "cast_creature";
    public static final String CAST_REMOVAL = "cast_removal";
    public static final String CAST_DRAW = "cast_draw";
    public static final String CAST_RAMP = "cast_ramp";
    public static final String CAST_COMMANDER = "cast_commander";
    public static final String ATTACK_OPPONENT = "attack_opponent";
    public static final String HOLD_MANA = "hold_mana";
    public static final String PASS = "pass";

    /** All valid macro-action names in index order. */
    public static final List<String> ALL_ACTIONS = List.of(
        CAST_CREATURE, CAST_REMOVAL, CAST_DRAW, CAST_RAMP,
        CAST_COMMANDER, ATTACK_OPPONENT, HOLD_MANA, PASS
    );

    // ── Known card role databases (matching Python labeler.py) ────────

    private static final Set<String> REMOVAL_CARDS = Set.of(
        "Swords to Plowshares", "Path to Exile", "Beast Within", "Chaos Warp",
        "Counterspell", "Swan Song", "Cyclonic Rift", "Blasphemous Act",
        "Wrath of God", "Generous Gift", "Terminate", "Go for the Throat",
        "Doom Blade", "Rapid Hybridization", "Vandalblast", "Krosan Grip",
        "Anguished Unmaking", "Vindicate", "Toxic Deluge", "Damnation",
        "Supreme Verdict", "Austere Command", "Farewell", "Deadly Rollick",
        "Force of Will", "Mana Drain", "Pongify", "Reality Shift",
        "Ravenform", "Abrade", "Lightning Bolt", "Generous Gift"
    );

    private static final Set<String> DRAW_CARDS = Set.of(
        "Rhystic Study", "Mystic Remora", "Harmonize", "Brainstorm",
        "Ponder", "Preordain", "Night's Whisper", "Sign in Blood",
        "Phyrexian Arena", "Sylvan Library", "Skullclamp", "Read the Bones",
        "Blue Sun's Zenith", "Fact or Fiction", "Dig Through Time",
        "Treasure Cruise", "Damnable Pact", "Pull from Tomorrow",
        "Guardian Project", "Beast Whisperer", "Toski, Bearer of Secrets"
    );

    private static final Set<String> RAMP_CARDS = Set.of(
        "Sol Ring", "Arcane Signet", "Cultivate", "Kodama's Reach",
        "Rampant Growth", "Farseek", "Mind Stone", "Commander's Sphere",
        "Fellwar Stone", "Thought Vessel", "Nature's Lore", "Solemn Simulacrum",
        "Sakura-Tribe Elder", "Birds of Paradise", "Llanowar Elves",
        "Elvish Mystic", "Mana Crypt", "Chrome Mox", "Mox Diamond",
        "Jeweled Lotus", "Dockside Extortionist", "Smothering Tithe",
        "Talismans", "Signets", "Three Visits", "Skyshroud Claim"
    );

    // ══════════════════════════════════════════════════════════
    // Action Execution Result
    // ══════════════════════════════════════════════════════════

    /**
     * Result of resolving a macro-action to a concrete action.
     */
    public static class ActionResolution {
        /** The original macro-action from the policy */
        public String macroAction;

        /** The concrete card to play (null for attack/hold/pass) */
        public String selectedCard;

        /** A description of what to do */
        public String description;

        /** Whether this action is actually executable right now */
        public boolean executable;

        /** Fallback macro-action if this one isn't executable */
        public String fallbackAction;

        public ActionResolution(String macroAction, String card, String desc, boolean executable) {
            this.macroAction = macroAction;
            this.selectedCard = card;
            this.description = desc;
            this.executable = executable;
        }

        @Override
        public String toString() {
            return String.format("[%s] %s → %s (%s)",
                macroAction, selectedCard != null ? selectedCard : "-",
                description, executable ? "OK" : "FALLBACK→" + fallbackAction);
        }
    }

    // ══════════════════════════════════════════════════════════
    // Resolution Logic
    // ══════════════════════════════════════════════════════════

    /**
     * Resolve a macro-action to a concrete action given the current game state.
     *
     * @param macroAction  The macro-action name from the policy (e.g., "cast_creature")
     * @param hand         Cards in the active player's hand
     * @param battlefield  Cards on the active player's battlefield
     * @param commandZone  Cards in the command zone
     * @param manaAvailable Available mana
     * @param commanderName The player's commander name
     * @param commanderTax Commander tax amount
     * @return ActionResolution with the concrete action to take
     */
    public static ActionResolution resolve(
            String macroAction,
            List<String> hand,
            List<String> battlefield,
            List<String> commandZone,
            int manaAvailable,
            String commanderName,
            int commanderTax
    ) {
        return switch (macroAction) {
            case CAST_CREATURE -> resolveCastCreature(hand, manaAvailable);
            case CAST_REMOVAL -> resolveCastRemoval(hand, manaAvailable);
            case CAST_DRAW -> resolveCastDraw(hand, manaAvailable);
            case CAST_RAMP -> resolveCastRamp(hand, manaAvailable);
            case CAST_COMMANDER -> resolveCastCommander(commandZone, commanderName, commanderTax, manaAvailable);
            case ATTACK_OPPONENT -> resolveAttack(battlefield);
            case HOLD_MANA -> new ActionResolution(HOLD_MANA, null, "Hold mana open, pass priority", true);
            case PASS -> new ActionResolution(PASS, null, "Pass with no action", true);
            default -> new ActionResolution(macroAction, null, "Unknown macro-action", false);
        };
    }

    private static ActionResolution resolveCastCreature(List<String> hand, int mana) {
        // Find castable creatures (those not in removal/draw/ramp databases)
        List<String> creatures = new ArrayList<>();
        for (String card : hand) {
            if (!isRemoval(card) && !isDraw(card) && !isRamp(card)) {
                creatures.add(card);
            }
        }

        if (creatures.isEmpty()) {
            ActionResolution r = new ActionResolution(CAST_CREATURE, null,
                "No creatures in hand", false);
            r.fallbackAction = HOLD_MANA;
            return r;
        }

        // Pick a creature (heuristic: prefer variety, first one found)
        String pick = creatures.get(0);
        return new ActionResolution(CAST_CREATURE, pick,
            "Cast creature: " + pick, true);
    }

    private static ActionResolution resolveCastRemoval(List<String> hand, int mana) {
        for (String card : hand) {
            if (isRemoval(card)) {
                return new ActionResolution(CAST_REMOVAL, card,
                    "Cast removal: " + card, true);
            }
        }

        ActionResolution r = new ActionResolution(CAST_REMOVAL, null,
            "No removal in hand", false);
        r.fallbackAction = HOLD_MANA;
        return r;
    }

    private static ActionResolution resolveCastDraw(List<String> hand, int mana) {
        for (String card : hand) {
            if (isDraw(card)) {
                return new ActionResolution(CAST_DRAW, card,
                    "Cast draw spell: " + card, true);
            }
        }

        ActionResolution r = new ActionResolution(CAST_DRAW, null,
            "No draw spells in hand", false);
        r.fallbackAction = HOLD_MANA;
        return r;
    }

    private static ActionResolution resolveCastRamp(List<String> hand, int mana) {
        for (String card : hand) {
            if (isRamp(card)) {
                return new ActionResolution(CAST_RAMP, card,
                    "Cast ramp: " + card, true);
            }
        }

        ActionResolution r = new ActionResolution(CAST_RAMP, null,
            "No ramp in hand", false);
        r.fallbackAction = HOLD_MANA;
        return r;
    }

    private static ActionResolution resolveCastCommander(
            List<String> commandZone, String commanderName, int tax, int mana) {
        if (commandZone == null || commandZone.isEmpty() ||
            !commandZone.contains(commanderName)) {
            ActionResolution r = new ActionResolution(CAST_COMMANDER, null,
                "Commander not in command zone", false);
            r.fallbackAction = HOLD_MANA;
            return r;
        }

        // Rough mana check (commander cost is ~4-6 average + tax)
        int estimatedCost = 4 + tax;
        if (mana < estimatedCost) {
            ActionResolution r = new ActionResolution(CAST_COMMANDER, commanderName,
                "Insufficient mana for commander (need ~" + estimatedCost + ", have " + mana + ")", false);
            r.fallbackAction = HOLD_MANA;
            return r;
        }

        return new ActionResolution(CAST_COMMANDER, commanderName,
            "Cast commander: " + commanderName + " (tax=" + tax + ")", true);
    }

    private static ActionResolution resolveAttack(List<String> battlefield) {
        if (battlefield == null || battlefield.isEmpty()) {
            ActionResolution r = new ActionResolution(ATTACK_OPPONENT, null,
                "No creatures on battlefield to attack with", false);
            r.fallbackAction = PASS;
            return r;
        }

        return new ActionResolution(ATTACK_OPPONENT, null,
            "Attack with " + battlefield.size() + " permanent(s)", true);
    }

    // ── Card role checks ────────────────────────────────────

    private static boolean isRemoval(String card) {
        return REMOVAL_CARDS.contains(card);
    }

    private static boolean isDraw(String card) {
        return DRAW_CARDS.contains(card);
    }

    private static boolean isRamp(String card) {
        return RAMP_CARDS.contains(card);
    }

    /**
     * Get the macro-action name from an index (matching Python IDX_TO_ACTION).
     */
    public static String actionNameFromIndex(int index) {
        if (index >= 0 && index < ALL_ACTIONS.size()) {
            return ALL_ACTIONS.get(index);
        }
        return PASS;
    }

    /**
     * Get the index from a macro-action name.
     */
    public static int indexFromActionName(String name) {
        int idx = ALL_ACTIONS.indexOf(name);
        return idx >= 0 ? idx : 7; // default to PASS
    }
}
