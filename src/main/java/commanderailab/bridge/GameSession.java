package commanderailab.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import commanderailab.ai.PolicyClient;

import java.util.*;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * GameSession — holds state for one live interactive Commander game.
 *
 * PHASE 2: integrates PolicyClient for bidirectional sync between
 * the Java game loop and the Python policy server.
 *
 * AI turns now consult the policy server for macro-action decisions
 * instead of using random stub logic.
 *
 * STATE VECTOR (Issue #83 Step 1)
 * buildStateVector(seat) emits a float[29] global scalar block that
 * matches the STATE_DIMS layout defined in ml/config/scope.py:
 *
 *   Per-player block — 14 features × 2 players = 28 floats
 *   indices [0..13]  = active seat ("self")
 *   indices [14..27] = averaged opponent seats
 *   index  [28]      = turn_number / MAX_TURNS
 *
 *   Per-player feature layout (offset 0 within each block):
 *     [0]  life_total            / 40.0
 *     [1]  commander_damage      / 21.0  (stub 0.0 — wire from Forge in Step 4)
 *     [2]  mana_available        / 20.0  (stub 0.0 — wire from Forge in Step 4)
 *     [3]  commander_tax         / 10.0
 *     [4]  cards_in_hand         / 15.0
 *     [5]  cards_in_graveyard    / 100.0
 *     [6]  creatures_on_battlefield / 30.0
 *     [7]  total_power_on_board  / 100.0  (stub = creature count — wire P/T in Step 4)
 *     [8]  is_active_player      (0.0 or 1.0)
 *     [9]  phase_onehot[main1]   (0.0 or 1.0)
 *     [10] phase_onehot[combat]  (0.0 or 1.0)
 *     [11] phase_onehot[main2]   (0.0 or 1.0)
 *     [12] phase_onehot[end]     (0.0 or 1.0)
 *     [13] (reserved / padding — always 0.0)
 *
 * buildStateSnapshot() appends "state_vector": [...] so PolicyClient
 * sends a machine-readable vector directly usable by the Python encoder
 * without re-parsing nested human-readable fields.
 */
public class GameSession {

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    // ----------------------------------------------------------------
    // State vector constants — must mirror ml/config/scope.py STATE_DIMS
    // ----------------------------------------------------------------
    private static final int PER_PLAYER_FEATURES = 14;
    private static final int NUM_PLAYERS_IN_VECTOR = 2;  // self + opponents
    private static final int GLOBAL_SCALAR_DIM = PER_PLAYER_FEATURES * NUM_PLAYERS_IN_VECTOR + 1; // 29
    private static final float MAX_LIFE = 40.0f;
    private static final float MAX_COMMANDER_DAMAGE = 21.0f;
    private static final float MAX_MANA = 20.0f;
    private static final float MAX_COMMANDER_TAX = 10.0f;
    private static final float MAX_HAND = 15.0f;
    private static final float MAX_GRAVEYARD = 100.0f;
    private static final float MAX_CREATURES = 30.0f;
    private static final float MAX_POWER = 100.0f;
    private static final float MAX_TURNS = 25.0f;

    // Phase name → one-hot index (matches PHASE_TO_IDX in scope.py)
    private static final Map<String, Integer> PHASE_ONEHOT_IDX;
    static {
        PHASE_ONEHOT_IDX = new HashMap<>();
        PHASE_ONEHOT_IDX.put("MAIN1", 0);
        PHASE_ONEHOT_IDX.put("BEGIN_COMBAT", 1);
        PHASE_ONEHOT_IDX.put("DECLARE_ATTACKERS", 1);
        PHASE_ONEHOT_IDX.put("DECLARE_BLOCKERS", 1);
        PHASE_ONEHOT_IDX.put("DAMAGE", 1);
        PHASE_ONEHOT_IDX.put("END_COMBAT", 1);
        PHASE_ONEHOT_IDX.put("MAIN2", 2);
        PHASE_ONEHOT_IDX.put("END", 3);
        PHASE_ONEHOT_IDX.put("CLEANUP", 3);
        // UNTAP, UPKEEP, DRAW all map to no active slot (all zeros)
    }

    private final List<String> deckNames;
    private final Long seed;
    private final String forgeJarPath;
    private final String forgeWorkDir;
    private final BlockingQueue<String> humanActionQueue;
    private final PolicyClient policyClient;

    private volatile boolean running = false;
    private volatile int turnNumber = 1;

    // Mutable game state
    private String phase = "UNTAP";
    private int activePlayer = 0;
    private int priorityPlayer = 0;
    private final int[] life;
    private final int[] poison;
    private final List<String>[] hands;
    private final List<String>[] battlefields;
    private final List<String>[] graveyards;
    private final List<String>[] commandZones;
    private final int[] commanderTax;
    private boolean awaitingHumanInput = false;

    private static final String[] PHASES = {
        "UNTAP", "UPKEEP", "DRAW",
        "MAIN1", "BEGIN_COMBAT", "DECLARE_ATTACKERS",
        "DECLARE_BLOCKERS", "DAMAGE", "END_COMBAT",
        "MAIN2", "END", "CLEANUP"
    };
    private int phaseIndex = 0;

    @SuppressWarnings("unchecked")
    public GameSession(List<String> deckNames, Long seed,
                       String forgeJarPath, String forgeWorkDir,
                       BlockingQueue<String> humanActionQueue) {
        this(deckNames, seed, forgeJarPath, forgeWorkDir, humanActionQueue,
             new PolicyClient("http://localhost:8080"));
    }

    @SuppressWarnings("unchecked")
    public GameSession(List<String> deckNames, Long seed,
                       String forgeJarPath, String forgeWorkDir,
                       BlockingQueue<String> humanActionQueue,
                       PolicyClient policyClient) {
        this.deckNames = deckNames;
        this.seed = seed;
        this.forgeJarPath = forgeJarPath;
        this.forgeWorkDir = forgeWorkDir;
        this.humanActionQueue = humanActionQueue;
        this.policyClient = policyClient;

        int seats = Math.min(deckNames.size(), 4);
        life = new int[seats];
        poison = new int[seats];
        hands = new List[seats];
        battlefields = new List[seats];
        graveyards = new List[seats];
        commandZones = new List[seats];
        commanderTax = new int[seats];

        for (int i = 0; i < seats; i++) {
            life[i] = 40;
            hands[i] = new ArrayList<>(List.of(
                    "card_stub_1", "card_stub_2", "card_stub_3",
                    "card_stub_4", "card_stub_5", "card_stub_6", "card_stub_7"
            ));
            battlefields[i] = new ArrayList<>();
            graveyards[i] = new ArrayList<>();
            commandZones[i] = new ArrayList<>(List.of(deckNames.get(i) + "_commander"));
        }
    }

    public boolean isRunning() { return running; }
    public int getTurnNumber() { return turnNumber; }
    public void stop() { running = false; }

    // ================================================================
    // Game loop
    // ================================================================

    /**
     * Run the game loop. Calls onStateChange after every action resolves.
     * Blocks until the game ends or stop() is called.
     */
    public void run(Consumer<Map<String, Object>> onStateChange) throws InterruptedException {
        running = true;
        Random rng = seed != null ? new Random(seed) : new Random();

        System.out.println("[Session] Game started. Decks: " + deckNames);
        System.out.println("[Session] PolicyClient endpoint: " + policyClient.getBaseUrl());

        while (running && !isGameOver()) {
            String currentPhase = PHASES[phaseIndex];
            phase = currentPhase;
            activePlayer = (turnNumber - 1) % deckNames.size();
            boolean isHumanTurn = (activePlayer == 0);
            boolean isInteractivePhase = currentPhase.equals("MAIN1") || currentPhase.equals("MAIN2");

            if (isHumanTurn && isInteractivePhase) {
                awaitingHumanInput = true;
                priorityPlayer = 0;
                onStateChange.accept(buildStateSnapshot());

                System.out.println("[Session] Awaiting human action for " + currentPhase + "...");
                String actionJson = humanActionQueue.poll(120, TimeUnit.SECONDS);
                if (actionJson == null) {
                    System.out.println("[Session] Human timed out — auto passing.");
                } else {
                    applyAction(actionJson);
                    System.out.println("[Session] Human action applied: " + actionJson);
                }
                awaitingHumanInput = false;

            } else if (!isHumanTurn && isInteractivePhase) {
                priorityPlayer = activePlayer;
                Map<String, Object> snapshot = buildStateSnapshot();
                String policyAction = consultPolicy(activePlayer, snapshot);
                applyPolicyAction(activePlayer, policyAction, rng);
                System.out.println("[Session] AI-" + activePlayer + " policy action: " + policyAction);

            } else {
                Thread.sleep(300);
            }

            phaseIndex++;
            if (phaseIndex >= PHASES.length) {
                phaseIndex = 0;
                turnNumber++;
            }
            onStateChange.accept(buildStateSnapshot());
        }

        running = false;
        System.out.println("[Session] Game ended after " + turnNumber + " turns.");
    }

    // ================================================================
    // State vector (Issue #83 Step 1)
    // ================================================================

    /**
     * Build the global scalar state vector for the given seat.
     *
     * Returns float[29] matching STATE_DIMS.global_features (29) in
     * ml/config/scope.py:
     *   indices [0..13]  = self (seat) per-player features
     *   indices [14..27] = mean-pooled opponent per-player features
     *   index  [28]      = turn_number / MAX_TURNS
     *
     * Stub fields (mana_available, commander_damage, total_power_on_board)
     * are 0.0 until real Forge board data is wired in Step 4.
     */
    public float[] buildStateVector(int seat) {
        float[] vec = new float[GLOBAL_SCALAR_DIM]; // 29 zeros

        // --- Self block: indices 0..13 ---
        fillPlayerBlock(vec, 0, seat, true);

        // --- Opponent block: indices 14..27 (mean of all non-self seats) ---
        int numOpponents = 0;
        float[] oppAccum = new float[PER_PLAYER_FEATURES];
        for (int i = 0; i < deckNames.size(); i++) {
            if (i == seat) continue;
            float[] oppBlock = buildPlayerFeatures(i, false);
            for (int f = 0; f < PER_PLAYER_FEATURES; f++) {
                oppAccum[f] += oppBlock[f];
            }
            numOpponents++;
        }
        if (numOpponents > 0) {
            for (int f = 0; f < PER_PLAYER_FEATURES; f++) {
                vec[PER_PLAYER_FEATURES + f] = oppAccum[f] / numOpponents;
            }
        }

        // --- Global: turn_number at index 28 ---
        vec[28] = Math.min(turnNumber / MAX_TURNS, 1.0f);

        return vec;
    }

    /**
     * Fill 14 per-player features into vec starting at offset.
     */
    private void fillPlayerBlock(float[] vec, int offset, int seat, boolean isSelf) {
        float[] block = buildPlayerFeatures(seat, isSelf);
        System.arraycopy(block, 0, vec, offset, PER_PLAYER_FEATURES);
    }

    /**
     * Build 14 per-player features for a single seat.
     *
     * Feature layout (must match per_player_features in scope.py):
     *   [0]  life_total            / MAX_LIFE
     *   [1]  commander_damage      / MAX_COMMANDER_DAMAGE  (stub 0.0)
     *   [2]  mana_available        / MAX_MANA              (stub 0.0)
     *   [3]  commander_tax         / MAX_COMMANDER_TAX
     *   [4]  cards_in_hand         / MAX_HAND
     *   [5]  cards_in_graveyard    / MAX_GRAVEYARD
     *   [6]  creatures_on_battlefield / MAX_CREATURES
     *   [7]  total_power_on_board  / MAX_POWER             (stub = creature count)
     *   [8]  is_active_player      (1.0 if this seat == activePlayer)
     *   [9]  phase_onehot[main1]
     *   [10] phase_onehot[combat]
     *   [11] phase_onehot[main2]
     *   [12] phase_onehot[end]
     *   [13] (reserved — 0.0)
     */
    private float[] buildPlayerFeatures(int seat, boolean isSelf) {
        float[] f = new float[PER_PLAYER_FEATURES];

        f[0] = clamp(life[seat] / MAX_LIFE);
        f[1] = 0.0f;  // commander_damage stub — wire from Forge in Step 4
        f[2] = 0.0f;  // mana_available stub — wire from Forge in Step 4
        f[3] = clamp(commanderTax[seat] / MAX_COMMANDER_TAX);
        f[4] = clamp(hands[seat].size() / MAX_HAND);
        f[5] = clamp(graveyards[seat].size() / MAX_GRAVEYARD);

        // Creature count — all battlefield cards treated as creatures until
        // real card type data arrives in Step 4
        float creatureCount = battlefields[seat].size();
        f[6] = clamp(creatureCount / MAX_CREATURES);
        f[7] = clamp(creatureCount / MAX_POWER);  // stub: power = creature count

        f[8] = (seat == activePlayer) ? 1.0f : 0.0f;

        // Phase one-hot (indices 9..12)
        Integer phaseSlot = PHASE_ONEHOT_IDX.get(phase);
        if (phaseSlot != null) {
            f[9 + phaseSlot] = 1.0f;
        }
        // f[13] = 0.0f (reserved)

        return f;
    }

    /** Clamp a normalized value to [0, 1]. */
    private static float clamp(float v) {
        return Math.max(0.0f, Math.min(1.0f, v));
    }

    // ================================================================
    // Policy integration
    // ================================================================

    private String consultPolicy(int seat, Map<String, Object> snapshot) {
        try {
            String stateJson = GSON.toJson(snapshot);
            PolicyClient.PolicyDecision decision = policyClient.decide(stateJson, seat);
            if (decision != null && decision.action() != null) {
                System.out.println("[Session] Policy decision for seat " + seat
                    + ": " + decision.action()
                    + " (confidence=" + String.format("%.2f", decision.confidence()) + ")");
                return decision.action();
            }
        } catch (Exception e) {
            System.err.println("[Session] Policy server error for seat " + seat + ": " + e.getMessage());
        }
        return "PASS_PRIORITY";
    }

    private void applyPolicyAction(int seat, String action, Random rng) {
        switch (action) {
            case "CAST_SPELL", "cast_creature", "cast_ramp", "cast_draw", "cast_commander" -> {
                if (!hands[seat].isEmpty()) {
                    String card = hands[seat].remove(0);
                    battlefields[seat].add(card);
                    System.out.println("[Session] AI-" + seat + " cast: " + card);
                }
            }
            case "PLAY_LAND" -> {
                if (!hands[seat].isEmpty()) {
                    String card = hands[seat].remove(hands[seat].size() - 1);
                    battlefields[seat].add(card);
                }
            }
            case "ATTACK_OPPONENT", "ATTACK" -> {
                int target = (seat + 1) % life.length;
                if (life[target] > 0) {
                    int dmg = rng.nextInt(3) + 1;
                    life[target] -= dmg;
                    System.out.println("[Session] AI-" + seat + " attacks player " + target + " for " + dmg);
                }
            }
            case "cast_removal" -> {
                // Find an opponent with creatures and remove one
                for (int i = 0; i < deckNames.size(); i++) {
                    if (i != seat && !battlefields[i].isEmpty()) {
                        String removed = battlefields[i].remove(0);
                        graveyards[i].add(removed);
                        System.out.println("[Session] AI-" + seat + " removed: " + removed + " from seat " + i);
                        break;
                    }
                }
            }
            case "hold_mana", "pass", "PASS_PRIORITY", "HOLD_MANA" -> { /* no-op */ }
            default -> System.out.println("[Session] Unknown policy action: " + action);
        }
    }

    // ================================================================
    // Human action handling
    // ================================================================

    private void applyAction(String actionJson) {
        try {
            JsonObject action = JsonParser.parseString(actionJson).getAsJsonObject();
            String type = action.has("type") ? action.get("type").getAsString() : "PASS_PRIORITY";
            switch (type) {
                case "PLAY_LAND", "CAST_SPELL" -> {
                    String cardId = action.has("cardId") ? action.get("cardId").getAsString() : null;
                    if (cardId != null && hands[0].contains(cardId)) {
                        hands[0].remove(cardId);
                        battlefields[0].add(cardId);
                    }
                }
                case "PASS_PRIORITY" -> { /* no-op, phase advances naturally */ }
                default -> System.out.println("[Session] Unknown action type: " + type);
            }
        } catch (Exception e) {
            System.err.println("[Session] Failed to apply action: " + e.getMessage());
        }
    }

    private boolean isGameOver() {
        int alive = 0;
        for (int lp : life) if (lp > 0) alive++;
        return alive <= 1 || turnNumber > 50;
    }

    // ================================================================
    // State serialization
    // ================================================================

    /** Returns a full { type: "STATE", state: {...} } JSON string. */
    public String buildStateMessage() {
        Map<String, Object> msg = new LinkedHashMap<>();
        msg.put("type", "STATE");
        msg.put("state", buildStateSnapshot());
        return GSON.toJson(msg);
    }

    /**
     * Returns the raw state snapshot map.
     *
     * Includes a "state_vector" key containing a float[29] global scalar
     * vector (Issue #83 Step 1) so PolicyClient.decide() sends a
     * machine-readable vector the Python /api/policy/decide endpoint can
     * pass directly to the ml/encoder without re-parsing nested fields.
     *
     * Stub fields within the vector are clearly marked in buildPlayerFeatures().
     */
    public Map<String, Object> buildStateSnapshot() {
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("schema", "1.1.0");  // bumped from 1.0.0 — state_vector added
        state.put("phase", phase);
        state.put("turnNumber", turnNumber);
        state.put("activePlayer", activePlayer);
        state.put("priorityPlayer", priorityPlayer);
        state.put("awaitingInput", awaitingHumanInput);
        state.put("inputPrompt", awaitingHumanInput ? "Choose an action or pass priority" : null);

        // Machine-readable global scalar vector for the Python encoder
        // Emitted for activePlayer's perspective
        float[] sv = buildStateVector(activePlayer);
        List<Float> svList = new ArrayList<>(sv.length);
        for (float v : sv) svList.add(v);
        state.put("state_vector", svList);
        state.put("state_vector_dim", sv.length);  // sanity: should always be 29

        List<Map<String, Object>> players = new ArrayList<>();
        for (int i = 0; i < deckNames.size(); i++) {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("seat", i);
            p.put("name", i == 0 ? "Human" : "AI-" + i);
            p.put("isAI", i != 0);
            p.put("deckName", deckNames.get(i));
            p.put("life", life[i]);
            p.put("poison", poison[i]);
            p.put("commanderTax", commanderTax[i]);
            p.put("handCount", hands[i].size());
            p.put("hand", i == 0 ? hands[i] : List.of());
            p.put("battlefield", battlefields[i]);
            p.put("graveyard", graveyards[i]);
            p.put("commandZone", commandZones[i]);
            p.put("manaPool", Map.of("W",0,"U",0,"B",0,"R",0,"G",0,"C",0));
            players.add(p);
        }
        state.put("players", players);
        state.put("stack", List.of());

        List<Map<String, Object>> legalActions = new ArrayList<>();
        if (awaitingHumanInput) {
            legalActions.add(Map.of("type", "PASS_PRIORITY", "label", "Pass Priority"));
            for (String card : hands[0]) {
                legalActions.add(Map.of("type", "CAST_SPELL", "cardId", card, "label", "Cast " + card));
            }
        }
        state.put("legalActions", legalActions);

        return state;
    }
}
