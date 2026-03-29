package commanderailab.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import commanderailab.ai.PolicyClient;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import java.util.regex.*;

/**
 * GameSession — Phase 2.3: real Forge IPC for live interactive Commander games.
 *
 * Architecture:
 *   1. Spawns a Forge subprocess with {@code --policy midrange --policyServer <url>}
 *      so Forge calls POST /api/policy/decide at every AI decision point.
 *   2. Reads Forge stdout line-by-line to track zone contents, life totals,
 *      phase transitions, and game outcome.
 *   3. Human actions (seat 0) are intercepted before Forge asks; the session
 *      waits on {@code humanActionQueue}, converts the action to the
 *      macro-action string expected by /api/policy/decide, and injects it
 *      via POST /api/policy/override so the policy server returns it.
 *   4. Publishes a full state snapshot to the WebSocket frontend after every
 *      meaningful Forge output event.
 *   5. Falls back to the synthetic stub loop if Forge cannot be started
 *      (e.g., missing JAR, wrong Java version).
 *
 * Zone sync model:
 *   Forge verbose log lines are parsed with the same regex patterns used
 *   in BatchRunner.  Each recognised event mutates the mutable per-seat
 *   zone lists; the snapshot is rebuilt and pushed on every change.
 *
 * Phase 2.3 — Issue #83
 */
public class GameSession {

    // ----------------------------------------------------------------
    // Constants
    // ----------------------------------------------------------------

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private static final int STALL_LIMIT_SECONDS = 600;   // 10 min
    private static final int HUMAN_TIMEOUT_SECONDS = 120;
    private static final String DEFAULT_POLICY_SERVER = "http://localhost:8080";

    // Forge verbose-log regex (mirror of BatchRunner patterns)
    private static final Pattern P_TURN =
        Pattern.compile("Turn\\s+(\\d+)\\s+\\(Ai\\(?(\\d+)\\)?", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_PHASE =
        Pattern.compile("Phase:\\s*(.+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_LIFE_CHANGE =
        Pattern.compile("Life:\\s*Life:\\s*Ai\\(?(\\d+)\\)?-.+?\\s+(\\d+)\\s*>\\s*(-?\\d+)");
    private static final Pattern P_LIFE_NOW =
        Pattern.compile("Ai\\(?(\\d+)\\)?-.+?'s\\s+life(?:\\s+total)?\\s+is\\s+now\\s+(-?\\d+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_CAST =
        Pattern.compile("(?:Add To Stack:\\s*)?Ai\\(?(\\d+)\\)?-[^\\s].*?\\s+casts?\\s+(.+?)(?:\\s+targeting.*)?$", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_LAND =
        Pattern.compile("(?:Land:\\s*)?Ai\\(?(\\d+)\\)?-[^\\s].*?\\s+play(?:s|ed)\\s+(.+?)(?:\\s+\\(\\d+\\))?(?:\\.|$)", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_ZONE_BF =
        Pattern.compile("Zone Change:\\s*(.+?)\\s+(?:\\(\\d+\\)\\s+)?was put into Battlefield", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_ZONE_GY =
        Pattern.compile("Zone Change:\\s*(.+?)\\s+(?:\\(\\d+\\)\\s+)?was put into Graveyard", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_ZONE_EXILE =
        Pattern.compile("Zone Change:\\s*(.+?)\\s+(?:\\(\\d+\\)\\s+)?was put into Exile", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_WINNER =
        Pattern.compile("Game Outcome:\\s*Ai\\(?(\\d+)\\)?-.+?\\s+has won", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_LOSER =
        Pattern.compile("Game Outcome:\\s*Ai\\(?(\\d+)\\)?-.+?\\s+has lost", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_PRIORITY =
        Pattern.compile("Priority:\\s*Ai\\(?(\\d+)\\)?", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_STACK_ADD =
        Pattern.compile("Stack:\\s*(.+?)\\s+added to stack", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_STACK_RESOLVE =
        Pattern.compile("Stack:\\s*(.+?)\\s+resolves", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_HAND_ADD =
        Pattern.compile("Hand:\\s*Ai\\(?(\\d+)\\)?-.+?\\s+adds?\\s+(.+?)\\s+to hand", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_HAND_REMOVE =
        Pattern.compile("Hand:\\s*Ai\\(?(\\d+)\\)?-.+?\\s+removes?\\s+(.+?)\\s+from hand", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_CMDR_TAX =
        Pattern.compile("Ai\\(?(\\d+)\\)?.*?commander tax.*?(\\d+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern P_GAME_RESULT =
        Pattern.compile("Game Result:\\s*Game\\s+(\\d+)\\s+ended in\\s+(\\d+)\\s*ms");

    // ----------------------------------------------------------------
    // Configuration
    // ----------------------------------------------------------------

    private final List<String> deckNames;
    private final List<String> deckFiles;
    private final Long seed;
    private final String forgeJarPath;
    private final String forgeWorkDir;
    private final String javaPath;
    private final BlockingQueue<String> humanActionQueue;
    private final PolicyClient policyClient;
    private final String policyServerUrl;
    private final int clockSeconds;

    // ----------------------------------------------------------------
    // Mutable game state (updated by Forge log parser)
    // ----------------------------------------------------------------

    private volatile boolean running = false;
    private volatile int turnNumber = 1;
    private volatile String phase = "UNTAP";
    private volatile int activePlayer = 0;
    private volatile int priorityPlayer = 0;
    private volatile boolean awaitingHumanInput = false;
    private volatile Integer winningSeat = null;
    private volatile boolean gameOver = false;
    private volatile long elapsedMs = 0;

    private final int numSeats;
    private final int[] life;
    private final int[] poison;
    private final int[] commanderTax;
    private final List<String>[] hands;
    private final List<String>[] battlefields;
    private final List<String>[] graveyards;
    private final List<String>[] exiles;
    private final List<String>[] commandZones;
    private final List<String> stack = new ArrayList<>();
    private final List<String> logLines = new ArrayList<>();

    // ----------------------------------------------------------------
    // Internal machinery
    // ----------------------------------------------------------------

    private Process forgeProcess;
    private final AtomicBoolean forgeFailed = new AtomicBoolean(false);
    private final AtomicInteger lastActivityEpoch = new AtomicInteger(0);

    // ----------------------------------------------------------------
    // Constructors
    // ----------------------------------------------------------------

    @SuppressWarnings("unchecked")
    public GameSession(
        List<String> deckNames,
        Long seed,
        String forgeJarPath,
        String forgeWorkDir,
        BlockingQueue<String> humanActionQueue
    ) {
        this(deckNames, deckNames, seed, forgeJarPath, forgeWorkDir,
             "java", humanActionQueue,
             new PolicyClient(DEFAULT_POLICY_SERVER),
             DEFAULT_POLICY_SERVER, 300);
    }

    @SuppressWarnings("unchecked")
    public GameSession(
        List<String> deckNames,
        Long seed,
        String forgeJarPath,
        String forgeWorkDir,
        BlockingQueue<String> humanActionQueue,
        PolicyClient policyClient
    ) {
        this(deckNames, deckNames, seed, forgeJarPath, forgeWorkDir,
             "java", humanActionQueue, policyClient,
             DEFAULT_POLICY_SERVER, 300);
    }

    @SuppressWarnings("unchecked")
    public GameSession(
        List<String> deckNames,
        List<String> deckFiles,
        Long seed,
        String forgeJarPath,
        String forgeWorkDir,
        String javaPath,
        BlockingQueue<String> humanActionQueue,
        PolicyClient policyClient,
        String policyServerUrl,
        int clockSeconds
    ) {
        this.deckNames = new ArrayList<>(deckNames);
        this.deckFiles = new ArrayList<>(deckFiles);
        this.seed = seed;
        this.forgeJarPath = forgeJarPath;
        this.forgeWorkDir = forgeWorkDir;
        this.javaPath = (javaPath != null && !javaPath.isEmpty()) ? javaPath : "java";
        this.humanActionQueue = humanActionQueue;
        this.policyClient = policyClient;
        this.policyServerUrl = policyServerUrl;
        this.clockSeconds = clockSeconds;
        this.numSeats = Math.min(deckNames.size(), 4);

        life = new int[numSeats];
        poison = new int[numSeats];
        commanderTax = new int[numSeats];
        hands = new List[numSeats];
        battlefields = new List[numSeats];
        graveyards = new List[numSeats];
        exiles = new List[numSeats];
        commandZones = new List[numSeats];

        for (int i = 0; i < numSeats; i++) {
            life[i] = 40;
            hands[i] = new ArrayList<>();
            battlefields[i] = new ArrayList<>();
            graveyards[i] = new ArrayList<>();
            exiles[i] = new ArrayList<>();
            commandZones[i] = new ArrayList<>(List.of(
                (i < deckNames.size() ? deckNames.get(i) : "Unknown") + " (Commander)"
            ));
        }
    }

    // ----------------------------------------------------------------
    // Public accessors
    // ----------------------------------------------------------------

    public boolean isRunning()      { return running; }
    public int getTurnNumber()      { return turnNumber; }
    public String getPhase()        { return phase; }
    public Integer getWinningSeat() { return winningSeat; }
    public List<String> getLog()    { return Collections.unmodifiableList(logLines); }

    public void stop() {
        running = false;
        if (forgeProcess != null && forgeProcess.isAlive()) {
            forgeProcess.destroyForcibly();
        }
    }

    // ----------------------------------------------------------------
    // Main entry point
    // ----------------------------------------------------------------

    /**
     * Run the live Forge game.
     *
     * Tries to spawn a real Forge subprocess with {@code --policy} flags.
     * If that fails (missing JAR, wrong Java, etc.) falls back to the
     * synthetic stub loop so the WebSocket session never hangs.
     *
     * @param onStateChange called after every meaningful game event with
     *                      the latest state snapshot
     */
    public void run(Consumer<Map<String, Object>> onStateChange) throws InterruptedException {
        running = true;
        log("[Session] Starting game. Decks: " + deckNames);
        log("[Session] Policy server: " + policyServerUrl);

        boolean forgeAvailable = forgeJarPath != null
            && !forgeJarPath.isBlank()
            && Files.exists(Path.of(forgeJarPath));

        if (forgeAvailable) {
            runForgeIpc(onStateChange);
        } else {
            log("[Session] Forge JAR not found (" + forgeJarPath + ") — running synthetic fallback.");
            runSyntheticFallback(onStateChange);
        }

        running = false;
        log(String.format("[Session] Game ended. turns=%d winner=%s",
            turnNumber, winningSeat != null ? "seat-" + winningSeat : "none"));
    }

    // ================================================================
    // Real Forge IPC path
    // ================================================================

    private void runForgeIpc(Consumer<Map<String, Object>> onStateChange) throws InterruptedException {
        List<String> cmd = buildForgeCommand();
        log("[Forge] Command: " + String.join(" ", cmd.subList(0, Math.min(8, cmd.size()))) + " ...");

        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(new File(forgeWorkDir != null && !forgeWorkDir.isBlank() ? forgeWorkDir : "."));
        pb.redirectErrorStream(true);
        pb.environment().remove("JAVA_TOOL_OPTIONS");

        try {
            forgeProcess = pb.start();
        } catch (IOException e) {
            log("[Session] Failed to start Forge: " + e.getMessage() + " — falling back to synthetic.");
            runSyntheticFallback(onStateChange);
            return;
        }

        // Watchdog: kill if stalled
        Thread watchdog = new Thread(() -> {
            long last = System.currentTimeMillis();
            while (forgeProcess.isAlive() && running) {
                try { Thread.sleep(5000); } catch (InterruptedException ignored) { return; }
                long now = System.currentTimeMillis();
                if (lastActivityEpoch.get() == 0) last = now;
                if ((now - last) > STALL_LIMIT_SECONDS * 1000L) {
                    log("[Watchdog] Forge stalled >" + STALL_LIMIT_SECONDS + "s. Killing.");
                    forgeProcess.destroyForcibly();
                    return;
                }
                last = now;
            }
        }, "ForgeSessionWatchdog");
        watchdog.setDaemon(true);
        watchdog.start();

        // Emit initial state so UI shows a board immediately
        onStateChange.accept(buildStateSnapshot());

        // Read Forge stdout in a background thread
        LinkedBlockingQueue<String> lineQueue = new LinkedBlockingQueue<>();
        AtomicBoolean forgeDone = new AtomicBoolean(false);
        Thread reader = new Thread(() -> {
            try (BufferedReader br = new BufferedReader(
                    new InputStreamReader(forgeProcess.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) lineQueue.offer(line);
            } catch (IOException ignored) {}
            forgeDone.set(true);
        }, "ForgeOutputReader");
        reader.setDaemon(true);
        reader.start();

        // Main loop: drain line queue and service human input
        while (!gameOver && running) {
            String line = lineQueue.poll(200, TimeUnit.MILLISECONDS);
            if (line != null) {
                lastActivityEpoch.incrementAndGet();
                boolean changed = parseForgeLine(line);
                if (changed) onStateChange.accept(buildStateSnapshot());
                if (awaitingHumanInput) handleHumanTurn(onStateChange);
            } else if (forgeDone.get() && lineQueue.isEmpty()) {
                break;
            }
        }

        watchdog.interrupt();
        try { forgeProcess.waitFor(10, TimeUnit.SECONDS); } catch (InterruptedException ignored) {}

        running = false;
        onStateChange.accept(buildStateSnapshot());
    }

    // ----------------------------------------------------------------
    // Forge command builder
    // ----------------------------------------------------------------

    private List<String> buildForgeCommand() {
        List<String> cmd = new ArrayList<>();
        cmd.add(javaPath);
        cmd.add("-Xmx4096m");
        cmd.add("-XX:+UseSerialGC");
        cmd.add("-XX:TieredStopAtLevel=1");
        cmd.add("-Dfile.encoding=UTF-8");
        cmd.add("-Dio.netty.tryReflectionSetAccessible=true");

        String[] addOpens = {
            "java.desktop/java.beans=ALL-UNNAMED",
            "java.desktop/javax.swing=ALL-UNNAMED",
            "java.desktop/java.awt=ALL-UNNAMED",
            "java.base/java.util=ALL-UNNAMED",
            "java.base/java.lang=ALL-UNNAMED",
            "java.base/java.lang.reflect=ALL-UNNAMED",
            "java.base/java.text=ALL-UNNAMED",
            "java.base/sun.nio.ch=ALL-UNNAMED",
            "java.base/java.nio=ALL-UNNAMED",
            "java.base/java.net=ALL-UNNAMED",
        };
        for (String m : addOpens) { cmd.add("--add-opens"); cmd.add(m); }

        cmd.add("-jar"); cmd.add(forgeJarPath);
        cmd.add("sim");
        cmd.add("-d");
        for (int i = 0; i < numSeats; i++) {
            String f = (i < deckFiles.size()) ? deckFiles.get(i) : deckNames.get(i);
            if (!f.endsWith(".dck")) f = f + ".dck";
            cmd.add(f);
        }
        cmd.add("-f"); cmd.add("commander");
        cmd.add("-n"); cmd.add("1");
        cmd.add("-c"); cmd.add(String.valueOf(clockSeconds));
        cmd.add("--policy"); cmd.add("midrange");
        cmd.add("--policyServer"); cmd.add(policyServerUrl);
        if (seed != null) { cmd.add("--seed"); cmd.add(seed.toString()); }
        return cmd;
    }

    // ----------------------------------------------------------------
    // Forge stdout parser
    // ----------------------------------------------------------------

    /**
     * Parse one line of Forge verbose output, mutating game state.
     * @return true if state changed meaningfully (triggers snapshot push)
     */
    private boolean parseForgeLine(String raw) {
        String line = raw.trim();
        if (line.isEmpty()) return false;
        logLines.add(line);
        boolean changed = false;

        // Turn boundary
        Matcher mTurn = P_TURN.matcher(line);
        if (mTurn.find()) {
            int t = Integer.parseInt(mTurn.group(1));
            int seat = clampSeat(Integer.parseInt(mTurn.group(2)) - 1);
            if (t != turnNumber || seat != activePlayer) {
                turnNumber = t; activePlayer = seat; phase = "UNTAP"; changed = true;
            }
        }

        // Phase change
        Matcher mPhase = P_PHASE.matcher(line);
        if (mPhase.find()) {
            String np = mPhase.group(1).trim().toUpperCase().replaceAll("\\s+", "_");
            if (!np.equals(phase)) {
                phase = np;
                if (activePlayer == 0 &&
                    (phase.equals("MAIN1") || phase.equals("MAIN_1")
                     || phase.equals("MAIN2") || phase.equals("MAIN_2"))) {
                    awaitingHumanInput = true;
                }
                changed = true;
            }
        }

        // Priority
        Matcher mPrio = P_PRIORITY.matcher(line);
        if (mPrio.find()) {
            priorityPlayer = clampSeat(Integer.parseInt(mPrio.group(1)) - 1);
            changed = true;
        }

        // Life totals
        Matcher mLc = P_LIFE_CHANGE.matcher(line);
        if (mLc.find()) {
            int s = clampSeat(Integer.parseInt(mLc.group(1)) - 1);
            int nl = Integer.parseInt(mLc.group(3));
            if (life[s] != nl) { life[s] = nl; changed = true; }
        }
        Matcher mLn = P_LIFE_NOW.matcher(line);
        if (mLn.find()) {
            int s = clampSeat(Integer.parseInt(mLn.group(1)) - 1);
            int nl = Integer.parseInt(mLn.group(2));
            if (life[s] != nl) { life[s] = nl; changed = true; }
        }

        // Spell cast → hand → battlefield
        Matcher mCast = P_CAST.matcher(line);
        if (mCast.find()) {
            int s = clampSeat(Integer.parseInt(mCast.group(1)) - 1);
            String card = mCast.group(2).trim();
            hands[s].remove(card);
            if (!battlefields[s].contains(card)) battlefields[s].add(card);
            changed = true;
        }

        // Land play
        Matcher mLand = P_LAND.matcher(line);
        if (mLand.find()) {
            int s = clampSeat(Integer.parseInt(mLand.group(1)) - 1);
            String card = mLand.group(2).trim();
            hands[s].remove(card);
            if (!battlefields[s].contains(card)) battlefields[s].add(card);
            changed = true;
        }

        // Zone changes
        Matcher mBf = P_ZONE_BF.matcher(line);
        if (mBf.find()) {
            battlefields[activePlayer].add(mBf.group(1).trim());
            changed = true;
        }
        Matcher mGy = P_ZONE_GY.matcher(line);
        if (mGy.find()) {
            String card = mGy.group(1).trim();
            for (int s = 0; s < numSeats; s++) {
                if (battlefields[s].remove(card)) { graveyards[s].add(card); changed = true; break; }
            }
        }
        Matcher mEx = P_ZONE_EXILE.matcher(line);
        if (mEx.find()) {
            String card = mEx.group(1).trim();
            for (int s = 0; s < numSeats; s++) {
                if (battlefields[s].remove(card) || graveyards[s].remove(card)) {
                    exiles[s].add(card); changed = true; break;
                }
            }
        }

        // Stack
        Matcher mSa = P_STACK_ADD.matcher(line);
        if (mSa.find()) { stack.add(mSa.group(1).trim()); changed = true; }
        Matcher mSr = P_STACK_RESOLVE.matcher(line);
        if (mSr.find()) { stack.remove(mSr.group(1).trim()); changed = true; }

        // Hand tracking
        Matcher mHa = P_HAND_ADD.matcher(line);
        if (mHa.find()) {
            int s = clampSeat(Integer.parseInt(mHa.group(1)) - 1);
            hands[s].add(mHa.group(2).trim()); changed = true;
        }
        Matcher mHr = P_HAND_REMOVE.matcher(line);
        if (mHr.find()) {
            int s = clampSeat(Integer.parseInt(mHr.group(1)) - 1);
            hands[s].remove(mHr.group(2).trim()); changed = true;
        }

        // Commander tax
        Matcher mTax = P_CMDR_TAX.matcher(line);
        if (mTax.find()) {
            int s = clampSeat(Integer.parseInt(mTax.group(1)) - 1);
            commanderTax[s] = Integer.parseInt(mTax.group(2)); changed = true;
        }

        // Game outcome
        Matcher mWin = P_WINNER.matcher(line);
        if (mWin.find()) {
            winningSeat = clampSeat(Integer.parseInt(mWin.group(1)) - 1);
            gameOver = true; changed = true;
        }
        if (P_LOSER.matcher(line).find()) changed = true;

        Matcher mGr = P_GAME_RESULT.matcher(line);
        if (mGr.find()) {
            elapsedMs = Long.parseLong(mGr.group(2));
            gameOver = true; changed = true;
        }

        return changed;
    }

    // ----------------------------------------------------------------
    // Human turn handling
    // ----------------------------------------------------------------

    private void handleHumanTurn(Consumer<Map<String, Object>> onStateChange)
            throws InterruptedException {
        awaitingHumanInput = true;
        onStateChange.accept(buildStateSnapshot());
        log("[Session] Awaiting human action (phase=" + phase + " turn=" + turnNumber + ")");

        String actionJson = humanActionQueue.poll(HUMAN_TIMEOUT_SECONDS, TimeUnit.SECONDS);
        if (actionJson == null) {
            log("[Session] Human timed out — injecting PASS_PRIORITY.");
            actionJson = "{\"type\":\"PASS_PRIORITY\"}";
        }
        String macroAction = mapHumanActionToMacro(actionJson);
        injectHumanOverride(macroAction);
        awaitingHumanInput = false;
        log("[Session] Human action applied: " + macroAction);
    }

    private String mapHumanActionToMacro(String actionJson) {
        try {
            JsonObject obj = JsonParser.parseString(actionJson).getAsJsonObject();
            String type = obj.has("type") ? obj.get("type").getAsString() : "PASS_PRIORITY";
            return switch (type.toUpperCase()) {
                case "CAST_SPELL"   -> "CAST_CREATURE";
                case "PLAY_LAND"    -> "PLAY_LAND";
                case "ATTACK"       -> "ATTACK_ALL";
                case "PASS_PRIORITY", "PASS" -> "PASS";
                default -> "PASS";
            };
        } catch (Exception e) { return "PASS"; }
    }

    private void injectHumanOverride(String macroAction) {
        try {
            JsonObject body = new JsonObject();
            body.addProperty("seat", 0);
            body.addProperty("action", macroAction);
            httpPost(policyServerUrl + "/api/policy/override", body.toString());
        } catch (Exception e) {
            log("[Session] Human override injection failed (" + e.getMessage() + ") — Forge uses policy net.");
        }
    }

    // ================================================================
    // Synthetic fallback loop
    // ================================================================

    private void runSyntheticFallback(Consumer<Map<String, Object>> onStateChange)
            throws InterruptedException {
        log("[Session] Running synthetic stub game.");
        Random rng = seed != null ? new Random(seed) : new Random();
        String[] phases = {
            "UNTAP","UPKEEP","DRAW","MAIN1","BEGIN_COMBAT",
            "DECLARE_ATTACKERS","DECLARE_BLOCKERS","DAMAGE",
            "END_COMBAT","MAIN2","END","CLEANUP"
        };
        int phaseIdx = 0;
        for (int i = 0; i < numSeats; i++)
            for (int c = 1; c <= 7; c++) hands[i].add("stub_card_" + c);

        while (running && !isSyntheticGameOver()) {
            phase = phases[phaseIdx];
            activePlayer = (turnNumber - 1) % numSeats;
            boolean isHuman = activePlayer == 0;
            boolean isMain = phase.equals("MAIN1") || phase.equals("MAIN2");

            if (isHuman && isMain) {
                awaitingHumanInput = true;
                priorityPlayer = 0;
                onStateChange.accept(buildStateSnapshot());
                String actionJson = humanActionQueue.poll(HUMAN_TIMEOUT_SECONDS, TimeUnit.SECONDS);
                if (actionJson != null) applySyntheticAction(actionJson);
                awaitingHumanInput = false;
            } else if (!isHuman && isMain) {
                priorityPlayer = activePlayer;
                applySyntheticPolicy(activePlayer, consultsPolicy(activePlayer), rng);
            } else {
                Thread.sleep(200);
            }

            phaseIdx = (phaseIdx + 1) % phases.length;
            if (phaseIdx == 0) turnNumber++;
            onStateChange.accept(buildStateSnapshot());
        }
    }

    private boolean isSyntheticGameOver() {
        int alive = 0;
        for (int lp : life) if (lp > 0) alive++;
        if (alive <= 1 || turnNumber > 50) { gameOver = true; return true; }
        return false;
    }

    private void applySyntheticAction(String actionJson) {
        try {
            JsonObject obj = JsonParser.parseString(actionJson).getAsJsonObject();
            String type = obj.has("type") ? obj.get("type").getAsString() : "PASS_PRIORITY";
            if ((type.equals("PLAY_LAND") || type.equals("CAST_SPELL")) && !hands[0].isEmpty()) {
                String cardId = obj.has("cardId") ? obj.get("cardId").getAsString() : null;
                String card = (cardId != null && hands[0].contains(cardId)) ? cardId : hands[0].get(0);
                hands[0].remove(card); battlefields[0].add(card);
            }
        } catch (Exception ignored) {}
    }

    private String consultsPolicy(int seat) {
        try {
            PolicyClient.PolicyDecision d = policyClient.decide(GSON.toJson(buildStateSnapshot()), seat);
            return d != null && d.action() != null ? d.action() : "PASS_PRIORITY";
        } catch (Exception e) { return "PASS_PRIORITY"; }
    }

    private void applySyntheticPolicy(int seat, String action, Random rng) {
        switch (action.toUpperCase()) {
            case "CAST_SPELL", "CAST_CREATURE" -> {
                if (!hands[seat].isEmpty()) { battlefields[seat].add(hands[seat].remove(0)); }
            }
            case "PLAY_LAND" -> {
                if (!hands[seat].isEmpty()) { battlefields[seat].add(hands[seat].remove(hands[seat].size() - 1)); }
            }
            case "ATTACK", "ATTACK_ALL" -> {
                int t = (seat + 1) % life.length;
                if (life[t] > 0) life[t] -= rng.nextInt(3) + 1;
            }
        }
    }

    // ----------------------------------------------------------------
    // State snapshot — full zone contents
    // ----------------------------------------------------------------

    public Map<String, Object> buildStateSnapshot() {
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("schema", "2.0.0");
        state.put("phase", phase);
        state.put("turnNumber", turnNumber);
        state.put("activePlayer", activePlayer);
        state.put("priorityPlayer", priorityPlayer);
        state.put("awaitingInput", awaitingHumanInput);
        state.put("inputPrompt", awaitingHumanInput ? "Choose an action or pass priority" : null);
        state.put("gameOver", gameOver);
        state.put("winningSeat", winningSeat);
        state.put("elapsedMs", elapsedMs);
        state.put("isForgeBacked", forgeProcess != null && !forgeFailed.get());

        List<Map<String, Object>> players = new ArrayList<>();
        for (int i = 0; i < numSeats; i++) {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("seat", i);
            p.put("name", i == 0 ? "Human" : "AI-" + i);
            p.put("isAI", i != 0);
            p.put("deckName", i < deckNames.size() ? deckNames.get(i) : "Deck-" + i);
            p.put("life", life[i]);
            p.put("poison", poison[i]);
            p.put("commanderTax", commanderTax[i]);
            p.put("handCount", hands[i].size());
            p.put("hand", i == 0 ? new ArrayList<>(hands[i]) : List.of());
            p.put("battlefield", new ArrayList<>(battlefields[i]));
            p.put("graveyard", new ArrayList<>(graveyards[i]));
            p.put("exile", new ArrayList<>(exiles[i]));
            p.put("commandZone", new ArrayList<>(commandZones[i]));
            p.put("manaPool", Map.of("W",0,"U",0,"B",0,"R",0,"G",0,"C",0));
            p.put("isWinner", winningSeat != null && winningSeat == i);
            players.add(p);
        }
        state.put("players", players);
        state.put("stack", new ArrayList<>(stack));

        List<Map<String, Object>> legal = new ArrayList<>();
        if (awaitingHumanInput) {
            legal.add(Map.of("type", "PASS_PRIORITY", "label", "Pass Priority"));
            for (String card : hands[0])
                legal.add(Map.of("type", "CAST_SPELL", "cardId", card, "label", "Cast " + card));
        }
        state.put("legalActions", legal);
        return state;
    }

    public String buildStateMessage() {
        Map<String, Object> msg = new LinkedHashMap<>();
        msg.put("type", "STATE");
        msg.put("state", buildStateSnapshot());
        return GSON.toJson(msg);
    }

    // ----------------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------------

    private int clampSeat(int s) { return Math.max(0, Math.min(s, numSeats - 1)); }

    private void log(String msg) { System.out.println(msg); logLines.add(msg); }

    private void httpPost(String urlStr, String jsonBody) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(1000);
        conn.setReadTimeout(3000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json");
        try (OutputStream os = conn.getOutputStream()) {
            os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
        }
        int code = conn.getResponseCode();
        if (code != 200) throw new IOException("HTTP " + code + " from " + urlStr);
    }
}
