package commanderailab.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
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
 */
public class GameSession {

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

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

    /**
     * Run the game loop. Calls onStateChange after every action resolves.
     * Blocks until the game ends or stop() is called.
     *
     * PHASE 2: AI turns now consult the PolicyClient for decisions.
     * The policy server returns a macro-action which is applied to game state.
     * Falls back to PASS_PRIORITY if the policy server is unreachable.
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
                // Phase 2: consult PolicyClient for AI decision
                priorityPlayer = activePlayer;
                Map<String, Object> snapshot = buildStateSnapshot();
                String policyAction = consultPolicy(activePlayer, snapshot);
                applyPolicyAction(activePlayer, policyAction, rng);
                System.out.println("[Session] AI-" + activePlayer + " policy action: " + policyAction);

            } else {
                // Non-interactive phase — small delay for readability
                Thread.sleep(300);
            }

            // Advance phase
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

    // ---------------------------------------------------------
    // Policy integration (Phase 2)
    // ---------------------------------------------------------

    /**
     * Consult the Python policy server for an AI decision.
     * Sends the current game snapshot and returns the recommended macro-action.
     * Falls back to PASS_PRIORITY on error.
     */
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

    /**
     * Apply a policy-recommended macro-action for an AI player.
     */
    private void applyPolicyAction(int seat, String action, Random rng) {
        switch (action) {
            case "CAST_SPELL" -> {
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
            case "ATTACK" -> {
                int target = (seat + 1) % life.length;
                if (life[target] > 0) {
                    int dmg = rng.nextInt(3) + 1;
                    life[target] -= dmg;
                    System.out.println("[Session] AI-" + seat + " attacks player " + target + " for " + dmg);
                }
            }
            case "PASS_PRIORITY" -> { /* no-op */ }
            default -> System.out.println("[Session] Unknown policy action: " + action);
        }
    }

    // ---------------------------------------------------------
    // Human action handling
    // ---------------------------------------------------------

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

    // ---------------------------------------------------------
    // State serialization
    // ---------------------------------------------------------

    /** Returns a full { type: "STATE", state: {...} } JSON string. */
    public String buildStateMessage() {
        Map<String, Object> msg = new LinkedHashMap<>();
        msg.put("type", "STATE");
        msg.put("state", buildStateSnapshot());
        return GSON.toJson(msg);
    }

    /** Returns the raw state snapshot map (serialized by caller). */
    public Map<String, Object> buildStateSnapshot() {
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("schema", "1.0.0");
        state.put("phase", phase);
        state.put("turnNumber", turnNumber);
        state.put("activePlayer", activePlayer);
        state.put("priorityPlayer", priorityPlayer);
        state.put("awaitingInput", awaitingHumanInput);
        state.put("inputPrompt", awaitingHumanInput ? "Choose an action or pass priority" : null);

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

        // Legal actions — only populated when it's the human's turn
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
