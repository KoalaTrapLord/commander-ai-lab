package commanderailab.ml;

import commanderailab.schema.DecisionSnapshot;
import commanderailab.schema.DecisionSnapshot.*;

import java.util.*;
import java.util.regex.*;

/**
 * DecisionExtractor — Reconstructs game state and decisions from Forge verbose logs.
 *
 * Forge verbose output emits lines for each game event: draws, casts, attacks,
 * damage, phase transitions, etc. This class maintains running game state and
 * emits a DecisionSnapshot at each point where the AI made a meaningful choice.
 *
 * Key Forge log patterns:
 *   "== Turn 5 (Ai(1)-CommanderName) =="     → Turn/active player
 *   "Ai(1)-Name draws CardName."              → Draw event
 *   "Ai(1)-Name casts CardName."              → Spell cast decision
 *   "Ai(1)-Name plays LandName."              → Land play decision
 *   "Ai(1)-Name attacks with [CreatureList]"  → Attack declaration
 *   "Phase: Main 1" / "Phase: Combat" / etc.  → Phase transition
 *   "Ai(1) life: 40 → 37"                    → Life change
 *
 * Limitations:
 *   - Hand contents must be inferred from draws and casts (Forge doesn't dump hands)
 *   - Mana available is estimated from land count and known mana rocks
 *   - Graveyard is tracked from death/destroy/discard events
 */
public class DecisionExtractor {

    // ── Patterns ──────────────────────────────────────────────

    // Turn boundary: "Turn 5 (Ai(1)-Name)" or "== Turn 5 (Ai(1)-Name) =="
    private static final Pattern TURN_PATTERN =
            Pattern.compile("Turn\\s+(\\d+)\\s+\\(Ai\\((\\d+)\\)-", Pattern.CASE_INSENSITIVE);

    // Phase indicator: various Forge phase strings
    private static final Pattern PHASE_PATTERN =
            Pattern.compile("(?:Phase|Step):\\s*(.*?)(?:\\s*$|\\s*-)", Pattern.CASE_INSENSITIVE);

    // Cast: "Ai(1)-Name casts CardName."
    private static final Pattern CAST_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-[^\\s].*?\\s+casts\\s+(.+?)\\.", Pattern.CASE_INSENSITIVE);

    // Land play: "Ai(1)-Name plays LandName."
    private static final Pattern LAND_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-[^\\s].*?\\s+plays\\s+(.+?)\\.", Pattern.CASE_INSENSITIVE);

    // Draw: "Ai(1)-Name draws CardName."
    private static final Pattern DRAW_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-[^\\s].*?\\s+draws\\s+(.+?)\\.", Pattern.CASE_INSENSITIVE);

    // Attack: "Ai(1)-Name attacks with" or "declares attackers"
    private static final Pattern ATTACK_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-.*?(?:attacks|declares? attackers)", Pattern.CASE_INSENSITIVE);

    // Life change: captures current life from various formats
    private static final Pattern LIFE_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\).*?life.*?(\\d+)", Pattern.CASE_INSENSITIVE);

    // Destroy/die: card leaves battlefield
    private static final Pattern DESTROY_PATTERN =
            Pattern.compile("(.+?)\\s+(?:is destroyed|dies|is put into .* graveyard)", Pattern.CASE_INSENSITIVE);

    // Damage: "CardName deals N damage to Ai(X)"
    private static final Pattern DAMAGE_TO_PLAYER =
            Pattern.compile("deals\\s+(\\d+)\\s+(?:combat\\s+)?damage\\s+to\\s+Ai\\((\\d+)\\)", Pattern.CASE_INSENSITIVE);

    // Commander damage: various formats
    private static final Pattern CMDR_DMG_PATTERN =
            Pattern.compile("(\\d+)\\s+commander\\s+damage", Pattern.CASE_INSENSITIVE);

    // ── Running game state ─────────────────────────────────────

    private final int numPlayers;
    private final String gameId;
    private final String[] commanderNames;  // commander name per seat

    // Per-seat mutable state
    private final int[] lifeTotals;
    private final int[] commanderDamage;    // damage from opponent's commander
    private final int[] commanderCasts;
    private final List<List<String>> hands;        // inferred hand contents
    private final List<List<String>> battlefields;
    private final List<List<String>> graveyards;
    private final List<List<String>> commandZones;

    // Turn tracking
    private int currentTurn = 0;
    private int activeSeat = 0;
    private String currentPhase = "main_1";

    // Output
    private final List<DecisionSnapshot> decisions = new ArrayList<>();

    // ══════════════════════════════════════════════════════════
    // Constructor
    // ══════════════════════════════════════════════════════════

    /**
     * @param numPlayers      Number of players (2 for 1v1)
     * @param gameId          Unique identifier for this game
     * @param commanderNames  Commander name for each seat (0-indexed)
     * @param deckCardNames   Cards in each player's deck (for initial state)
     */
    public DecisionExtractor(int numPlayers, String gameId,
                             String[] commanderNames,
                             List<List<String>> deckCardNames) {
        this.numPlayers = numPlayers;
        this.gameId = gameId;
        this.commanderNames = commanderNames;

        this.lifeTotals = new int[numPlayers];
        this.commanderDamage = new int[numPlayers];
        this.commanderCasts = new int[numPlayers];
        this.hands = new ArrayList<>();
        this.battlefields = new ArrayList<>();
        this.graveyards = new ArrayList<>();
        this.commandZones = new ArrayList<>();

        for (int i = 0; i < numPlayers; i++) {
            lifeTotals[i] = 40;
            commanderDamage[i] = 0;
            commanderCasts[i] = 0;
            hands.add(new ArrayList<>());
            battlefields.add(new ArrayList<>());
            graveyards.add(new ArrayList<>());

            // Commander starts in command zone
            List<String> cmdZone = new ArrayList<>();
            if (commanderNames[i] != null) {
                cmdZone.add(commanderNames[i]);
            }
            commandZones.add(cmdZone);
        }
    }

    // ══════════════════════════════════════════════════════════
    // Main parsing entry point
    // ══════════════════════════════════════════════════════════

    /**
     * Process all lines of a Forge verbose game log.
     * Call this once with the full output; it populates the decisions list.
     *
     * @param lines Array of log lines (split from full output)
     * @return List of decision snapshots extracted from this game
     */
    public List<DecisionSnapshot> processGameLog(String[] lines) {
        for (String rawLine : lines) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;

            // ── Turn boundary ──────────────────────────────
            Matcher turnM = TURN_PATTERN.matcher(line);
            if (turnM.find()) {
                currentTurn = Integer.parseInt(turnM.group(1));
                activeSeat = Integer.parseInt(turnM.group(2)) - 1;
                currentPhase = "main_1"; // Reset to main 1 at turn start
                continue;
            }

            // ── Phase transition ───────────────────────────
            Matcher phaseM = PHASE_PATTERN.matcher(line);
            if (phaseM.find()) {
                currentPhase = normalizePhase(phaseM.group(1).trim());
                continue;
            }

            // ── Draw event (state update only, not a decision) ──
            Matcher drawM = DRAW_PATTERN.matcher(line);
            if (drawM.find()) {
                int seat = Integer.parseInt(drawM.group(1)) - 1;
                String card = drawM.group(2).trim();
                if (seat >= 0 && seat < numPlayers) {
                    hands.get(seat).add(card);
                }
                continue;
            }

            // ── Cast spell → DECISION POINT ────────────────
            Matcher castM = CAST_PATTERN.matcher(line);
            if (castM.find()) {
                int seat = Integer.parseInt(castM.group(1)) - 1;
                String card = castM.group(2).trim();
                if (seat >= 0 && seat < numPlayers) {
                    // Snapshot BEFORE the action changes state
                    ActionRecord action = new ActionRecord();
                    action.rawLogLine = line;
                    action.cardName = card;

                    // Determine action type
                    if (commanderNames[seat] != null &&
                            card.equalsIgnoreCase(commanderNames[seat])) {
                        action.type = "cast_commander";
                        commanderCasts[seat]++;
                        commandZones.get(seat).remove(card);
                    } else {
                        action.type = "cast";
                    }

                    // Emit decision snapshot
                    emitDecision(seat, action);

                    // Update state: card moves from hand to battlefield
                    hands.get(seat).remove(card);
                    battlefields.get(seat).add(card);
                }
                continue;
            }

            // ── Land play → DECISION POINT ─────────────────
            Matcher landM = LAND_PATTERN.matcher(line);
            if (landM.find()) {
                int seat = Integer.parseInt(landM.group(1)) - 1;
                String card = landM.group(2).trim();
                if (seat >= 0 && seat < numPlayers) {
                    ActionRecord action = new ActionRecord();
                    action.type = "land";
                    action.cardName = card;
                    action.rawLogLine = line;

                    emitDecision(seat, action);

                    hands.get(seat).remove(card);
                    battlefields.get(seat).add(card);
                }
                continue;
            }

            // ── Attack declaration → DECISION POINT ────────
            Matcher attackM = ATTACK_PATTERN.matcher(line);
            if (attackM.find()) {
                int seat = Integer.parseInt(attackM.group(1)) - 1;
                if (seat >= 0 && seat < numPlayers) {
                    ActionRecord action = new ActionRecord();
                    action.type = "attack";
                    action.rawLogLine = line;

                    emitDecision(seat, action);
                }
                continue;
            }

            // ── Damage to player (state update) ────────────
            Matcher dmgM = DAMAGE_TO_PLAYER.matcher(line);
            if (dmgM.find()) {
                int amount = Integer.parseInt(dmgM.group(1));
                int targetSeat = Integer.parseInt(dmgM.group(2)) - 1;
                if (targetSeat >= 0 && targetSeat < numPlayers) {
                    lifeTotals[targetSeat] -= amount;
                }
                // Check for commander damage
                if (line.toLowerCase().contains("commander")) {
                    if (targetSeat >= 0 && targetSeat < numPlayers) {
                        commanderDamage[targetSeat] += amount;
                    }
                }
                continue;
            }

            // ── Card destroyed / dies (state update) ───────
            Matcher destroyM = DESTROY_PATTERN.matcher(line);
            if (destroyM.find()) {
                String card = destroyM.group(1).trim();
                // Move from battlefield to graveyard
                for (int s = 0; s < numPlayers; s++) {
                    if (battlefields.get(s).remove(card)) {
                        graveyards.get(s).add(card);
                        // If it's the commander, it goes to command zone instead
                        if (commanderNames[s] != null &&
                                card.equalsIgnoreCase(commanderNames[s])) {
                            graveyards.get(s).remove(card);
                            commandZones.get(s).add(card);
                        }
                        break;
                    }
                }
            }
        }

        return decisions;
    }

    // ══════════════════════════════════════════════════════════
    // Snapshot emission
    // ══════════════════════════════════════════════════════════

    private void emitDecision(int actingSeat, ActionRecord action) {
        DecisionSnapshot snap = new DecisionSnapshot();
        snap.gameId = gameId;
        snap.turnNumber = currentTurn;
        snap.phase = currentPhase;
        snap.activeSeat = actingSeat;
        snap.action = action;

        // Build player snapshots
        snap.players = new ArrayList<>();
        for (int s = 0; s < numPlayers; s++) {
            PlayerSnapshot ps = new PlayerSnapshot();
            ps.seatIndex = s;
            ps.lifeTotal = lifeTotals[s];
            ps.commanderDamageTaken = commanderDamage[s];
            ps.manaAvailable = estimateMana(s);
            ps.commanderTax = commanderCasts[s] * 2;
            ps.commanderCasts = commanderCasts[s];

            ps.hand = new ArrayList<>(hands.get(s));
            ps.battlefield = new ArrayList<>(battlefields.get(s));
            ps.graveyard = new ArrayList<>(graveyards.get(s));
            ps.commandZone = new ArrayList<>(commandZones.get(s));

            // Compute board stats
            ps.creaturesOnField = countType(battlefields.get(s), "creature");
            ps.totalPowerOnBoard = 0;  // Would need card DB — leave as 0 for now
            ps.totalToughnessOnBoard = 0;
            ps.artifactsOnField = 0;
            ps.enchantmentsOnField = 0;
            ps.landCount = countLands(battlefields.get(s));

            snap.players.add(ps);
        }

        decisions.add(snap);
    }

    // ══════════════════════════════════════════════════════════
    // Helpers
    // ══════════════════════════════════════════════════════════

    /**
     * Estimate available mana from land count on battlefield.
     * Simple heuristic: lands count ≈ mana available.
     * (Mana rocks and dorks would improve this.)
     */
    private int estimateMana(int seat) {
        return countLands(battlefields.get(seat));
    }

    /**
     * Count lands on battlefield.
     * Heuristic: any card name containing typical land keywords.
     */
    private int countLands(List<String> battlefield) {
        int count = 0;
        for (String card : battlefield) {
            String lower = card.toLowerCase();
            if (lower.contains("plains") || lower.contains("island") ||
                    lower.contains("swamp") || lower.contains("mountain") ||
                    lower.contains("forest") || lower.contains("land") ||
                    lower.contains("command tower") || lower.contains("sol ring") ||
                    lower.contains("temple") || lower.contains("shock") ||
                    lower.contains("fetch") || lower.endsWith(" gate")) {
                count++;
            }
        }
        return count;
    }

    /**
     * Count cards of a given type on battlefield.
     * Without a card database, we use name heuristics.
     * TODO: Load card type data from Scryfall cache for accuracy.
     */
    private int countType(List<String> battlefield, String type) {
        // Without type data, return total non-land count as creature estimate
        return battlefield.size() - countLands(battlefield);
    }

    /**
     * Normalize Forge phase strings to our canonical names.
     */
    private String normalizePhase(String forgePhase) {
        String lower = forgePhase.toLowerCase();
        if (lower.contains("main") && (lower.contains("1") || lower.contains("pre"))) {
            return "main_1";
        }
        if (lower.contains("combat") || lower.contains("attack") || lower.contains("block") || lower.contains("damage")) {
            return "combat";
        }
        if (lower.contains("main") && (lower.contains("2") || lower.contains("post"))) {
            return "main_2";
        }
        if (lower.contains("end") || lower.contains("cleanup")) {
            return "end";
        }
        return "main_1"; // Default
    }

    /**
     * Get all extracted decisions (call after processGameLog).
     */
    public List<DecisionSnapshot> getDecisions() {
        return Collections.unmodifiableList(decisions);
    }
}
