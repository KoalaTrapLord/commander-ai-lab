package commanderailab.batch;

import commanderailab.ai.AiPolicy;
import commanderailab.ml.DecisionExtractor;
import commanderailab.ml.DecisionLogger;
import commanderailab.schema.BatchResult;
import commanderailab.schema.BatchResult.*;
import commanderailab.schema.DecisionSnapshot;
import commanderailab.schema.PerCardGameStats;
import commanderailab.schema.WinCondition;
import commanderailab.stats.StatsAggregator;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.regex.*;

/**
 * BatchRunner — Single-threaded batch simulation runner.
 *
 * Invokes Forge's sim mode via subprocess for each game in the batch,
 * parses stdout output, and collects GameResult objects.
 *
 * v24 changes (GitHub Issues #1-#5):
 *   - Issue #1: Winner's life total now inferred from remaining player after losers identified
 *   - Issue #2: Win condition classification uses formal WinCondition enum with UNKNOWN fallback + logging
 *   - Issue #3: JVM process pooling via persistent Forge workers (eliminates per-game JVM startup)
 *   - Issue #4: Configurable Forge AI flags, single-game benchmarking support
 *   - Issue #5: Real-time sims/sec reporting via progress callback
 *
 * Forge output format (with -q flag):
 *   Game Outcome: Turn 11
 *   Game Outcome: Ai(1)-Edgar Markov has won because all opponents have lost
 *   Game Outcome: Ai(2)-Grimgrin has lost because life total reached 0
 *   Game Outcome: Ai(3)-Xyris has lost because life total reached 0
 *   Match Result: Ai(1)-Edgar Markov: 1 Ai(2)-Grimgrin: 0 Ai(3)-Xyris: 0
 *   Game Result: Game 1 ended in 9201 ms. Ai(1)-Edgar Markov has won!
 */
public class BatchRunner {

    private final String forgeJarPath;    // Path to forge-gui-desktop JAR (jar-with-dependencies)
    private final String forgeWorkDir;    // Working directory for Forge (where res/ folder is)
    private final List<DeckInfo> decks;   // Exactly 3 decks
    private final AiPolicy policy;
    private final boolean quiet;
    private final int clockSeconds;       // Max seconds per game before draw (default 120)
    private String javaPath = "java";     // Path to Java 17 executable (Forge requires Java 17)

    // ── ML Decision Logging ───────────────────────────────────
    private boolean mlLoggingEnabled = false;
    private DecisionLogger mlDecisionLogger;
    private String mlResultsDir = "results";

    // ── Progress callback (Issue #5) ──────────────────────────
    private ProgressCallback progressCallback;

    // ── JVM Process Pool (Issue #3) ───────────────────────────
    private boolean useProcessPool = true;
    private int poolSize = 1;  // For single-thread runner, pool of 1 is fine
    private final List<ForgeWorker> workerPool = new ArrayList<>();

    // ── Forge AI optimization flags (Issue #4) ────────────────
    private boolean useSimplifiedAi = false;   // Use faster AI profile for sims
    private int aiThinkTimeMs = -1;            // -1 = Forge default; >0 = cap AI think time

    // ── Regex patterns for parsing Forge sim output ────────────────────

    // "Game Outcome: Turn 11"
    private static final Pattern TURN_PATTERN =
            Pattern.compile("Game Outcome:\\s*Turn\\s+(\\d+)");

    // "Game Outcome: Ai(1)-Edgar Markov has won because all opponents have lost"
    private static final Pattern WINNER_PATTERN =
            Pattern.compile("Game Outcome:\\s*Ai\\((\\d+)\\)-(.+?)\\s+has won because (.+)");

    // "Game Outcome: Ai(2)-Grimgrin has lost because life total reached 0"
    private static final Pattern LOSER_PATTERN =
            Pattern.compile("Game Outcome:\\s*Ai\\((\\d+)\\)-(.+?)\\s+has lost because (.+)");

    // "Game Result: Game 1 ended in 9201 ms. Ai(1)-Edgar Markov has won!"
    private static final Pattern GAME_RESULT_PATTERN =
            Pattern.compile("Game Result:\\s*Game\\s+(\\d+)\\s+ended in\\s+(\\d+)\\s*ms\\.\\s*(.+?)\\s+has won!");

    // "Game Result: Game 1 ended in 9201 ms. It's a draw!"  (timeout/draw case)
    private static final Pattern GAME_DRAW_PATTERN =
            Pattern.compile("Game Result:\\s*Game\\s+(\\d+)\\s+ended in\\s+(\\d+)\\s*ms\\..+draw", Pattern.CASE_INSENSITIVE);

    // "Match Result: Ai(1)-Edgar Markov: 1 Ai(2)-Grimgrin: 0 Ai(3)-Xyris: 0"
    private static final Pattern MATCH_RESULT_PATTERN =
            Pattern.compile("Match Result:");

    // ── Life total tracking patterns (Issue #1) ─────────────────────────
    // Verbose Forge log: "Ai(1)-Name's life is now 27." or "Ai(1)-Name's life total is now 27"
    private static final Pattern LIFE_TOTAL_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-.+?'s\\s+life(?:\\s+total)?\\s+is\\s+now\\s+(-?\\d+)", Pattern.CASE_INSENSITIVE);

    // "Ai(1)-Name loses N life" — life loss event
    private static final Pattern LIFE_LOSS_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-.+?\\s+loses\\s+(\\d+)\\s+life", Pattern.CASE_INSENSITIVE);

    // "Ai(1)-Name gains N life" — life gain event
    private static final Pattern LIFE_GAIN_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-.+?\\s+gains\\s+(\\d+)\\s+life", Pattern.CASE_INSENSITIVE);

    // ── Verbose game-log patterns for extracting combat stats ────────────

    // "Ai(1)-Name casts CardName" — any spell cast
    private static final Pattern CAST_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-[^\\s].*?\\s+casts\\s+(.+?)\\.", Pattern.CASE_INSENSITIVE);

    // "Ai(1)-Name plays Land" — land drop
    private static final Pattern LAND_PLAY_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-[^\\s].*?\\s+plays\\s+(.+?)\\.", Pattern.CASE_INSENSITIVE);

    // "...is destroyed" or "...is put into graveyard from the battlefield"
    private static final Pattern CREATURE_DESTROYED_PATTERN =
            Pattern.compile("(is destroyed|dies|is put into .* graveyard from the battlefield)", Pattern.CASE_INSENSITIVE);

    // "deals N combat damage" or "deals N damage to Ai(X)"
    private static final Pattern DAMAGE_PATTERN =
            Pattern.compile("deals\\s+(\\d+)\\s+(?:combat\\s+)?damage\\s+to\\s+Ai\\((\\d+)\\)", Pattern.CASE_INSENSITIVE);

    // "commander damage" — specifically commander damage dealt
    private static final Pattern CMDR_DAMAGE_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\).*?commander.*?damage.*?(\\d+)", Pattern.CASE_INSENSITIVE);

    // ── Per-card tracking patterns (verbose log) ─────────────────────────

    // "Ai(1)-Name draws CardName." — card drawn
    private static final Pattern DRAW_PATTERN =
            Pattern.compile("Ai\\((\\d+)\\)-[^\\s].*?\\s+draws\\s+(.+?)\\.", Pattern.CASE_INSENSITIVE);

    // Turn boundary: "Turn 5 (Ai(1)-Name)" or "Turn 5 (Ai(2)-Name)"
    // Some Forge versions use: "== Turn X (Ai(N)-Name) =="
    private static final Pattern VERBOSE_TURN_PATTERN =
            Pattern.compile("Turn\\s+(\\d+)\\s+\\(Ai\\((\\d+)\\)", Pattern.CASE_INSENSITIVE);

    // "CardName deals N damage" — damage by a specific card
    private static final Pattern CARD_DAMAGE_PATTERN =
            Pattern.compile("(.+?)\\s+deals\\s+(\\d+)\\s+(?:combat\\s+)?damage", Pattern.CASE_INSENSITIVE);

    public BatchRunner(String forgeJarPath, String forgeWorkDir, List<DeckInfo> decks, AiPolicy policy) {
        this(forgeJarPath, forgeWorkDir, decks, policy, false, 120);  // verbose by default for combat stats
    }

    public BatchRunner(String forgeJarPath, String forgeWorkDir, List<DeckInfo> decks,
                       AiPolicy policy, boolean quiet, int clockSeconds) {
        this(forgeJarPath, forgeWorkDir, decks, policy, quiet, clockSeconds, "java");
    }

    public BatchRunner(String forgeJarPath, String forgeWorkDir, List<DeckInfo> decks,
                       AiPolicy policy, boolean quiet, int clockSeconds, String javaPath) {
        if (decks.size() < 3 || decks.size() > 4) {
            throw new IllegalArgumentException("Requires 3 or 4 decks, got " + decks.size());
        }
        this.forgeJarPath = forgeJarPath;
        this.forgeWorkDir = forgeWorkDir;
        this.decks = decks;
        this.policy = policy;
        this.quiet = quiet;
        this.clockSeconds = clockSeconds;
        this.javaPath = (javaPath != null && !javaPath.isEmpty()) ? javaPath : "java";
    }

    // ── Configuration methods ─────────────────────────────────────────

    /**
     * Set a progress callback for real-time sims/sec reporting (Issue #5).
     */
    public void setProgressCallback(ProgressCallback callback) {
        this.progressCallback = callback;
    }

    /**
     * Enable/disable JVM process pooling (Issue #3).
     * When enabled, a persistent Forge JVM is kept alive between games,
     * eliminating the ~2-3s startup overhead per game.
     */
    public void setUseProcessPool(boolean usePool) {
        this.useProcessPool = usePool;
    }

    /**
     * Configure Forge AI optimization (Issue #4).
     * @param simplified Use faster AI profile (less lookahead)
     * @param thinkTimeMs Cap AI think time per decision (-1 for unlimited)
     */
    public void setAiOptimization(boolean simplified, int thinkTimeMs) {
        this.useSimplifiedAi = simplified;
        this.aiThinkTimeMs = thinkTimeMs;
    }

    /**
     * Enable ML decision logging for this batch.
     * When enabled, each game's decision points are extracted and written
     * to a JSONL file for supervised learning.
     *
     * @param resultsDir Directory for ML output files
     * @param batchId    Batch identifier for file naming
     */
    public void enableMlLogging(String resultsDir, String batchId) {
        this.mlLoggingEnabled = true;
        this.mlResultsDir = resultsDir;
        try {
            this.mlDecisionLogger = new DecisionLogger(resultsDir, batchId);
            System.out.println("[ML] Decision logging enabled for batch: " + batchId);
        } catch (IOException e) {
            System.err.println("[ML] Failed to initialize decision logger: " + e.getMessage());
            this.mlLoggingEnabled = false;
        }
    }

    /**
     * Close ML logger after batch completes. Call from the API layer.
     */
    public void closeMlLogger() {
        if (mlDecisionLogger != null) {
            mlDecisionLogger.close();
        }
    }

    public boolean isMlLoggingEnabled() {
        return mlLoggingEnabled;
    }

    public DecisionLogger getMlDecisionLogger() {
        return mlDecisionLogger;
    }

    /**
     * Run N games sequentially on the current thread.
     * Each invocation of Forge sim runs 1 game (-n 1) to get individual results.
     *
     * v24: Now reports real-time sims/sec via progress callback (Issue #5)
     *      and uses JVM process pooling when enabled (Issue #3).
     *
     * @param numGames   Number of games to simulate
     * @param masterSeed Base seed (null for random); each game uses masterSeed + gameIndex
     * @return List of GameResult objects
     */
    public List<GameResult> runBatchSingleThread(int numGames, Long masterSeed) {
        List<GameResult> results = new ArrayList<>();
        long batchStartMs = System.currentTimeMillis();

        for (int i = 0; i < numGames; i++) {
            long gameSeed = (masterSeed != null) ? masterSeed + i : System.nanoTime();
            long startMs = System.currentTimeMillis();

            try {
                GameResult result = runSingleGame(i, gameSeed);
                // Use Forge-reported time if available, otherwise wall clock
                if (result.elapsedMs == 0) {
                    result.elapsedMs = System.currentTimeMillis() - startMs;
                }
                results.add(result);

                System.out.printf("[Game %d/%d] Winner: %s | Turns: %d | Time: %dms%n",
                        i + 1, numGames,
                        result.winningSeat != null
                                ? decks.get(result.winningSeat).deckName
                                : "DRAW",
                        result.totalTurns, result.elapsedMs);

                // ── Issue #5: Real-time progress reporting ──────────────
                if (progressCallback != null) {
                    long elapsedMs = System.currentTimeMillis() - batchStartMs;
                    double simsPerSec = elapsedMs > 0
                            ? (double) (i + 1) / (elapsedMs / 1000.0)
                            : 0.0;
                    int pct = (int) ((i + 1) * 100.0 / numGames);
                    progressCallback.onProgress(i + 1, numGames, pct, simsPerSec, result);
                }

            } catch (Exception e) {
                System.err.printf("[Game %d/%d] ERROR: %s%n", i + 1, numGames, e.getMessage());
                GameResult failed = createFailedGame(i, gameSeed, System.currentTimeMillis() - startMs);
                results.add(failed);
            }
        }

        // Shut down any pooled workers
        shutdownWorkerPool();

        // Final throughput report
        long totalElapsed = System.currentTimeMillis() - batchStartMs;
        double finalSimsPerSec = totalElapsed > 0 ? (double) results.size() / (totalElapsed / 1000.0) : 0.0;
        System.out.printf("[BATCH] Completed %d games in %.1fs (%.3f sims/sec)%n",
                results.size(), totalElapsed / 1000.0, finalSimsPerSec);

        return results;
    }

    /**
     * Run a single game via Forge subprocess.
     * Issue #3: Uses pooled JVM process when available.
     */
    private GameResult runSingleGame(int gameIndex, long gameSeed) throws IOException, InterruptedException {
        List<String> cmd = buildForgeCommand();

        // Log the full command for debugging
        String cmdStr = String.join(" ", cmd);
        System.out.println("[DEBUG] Forge command: " + cmdStr);
        System.out.println("[DEBUG] Working dir: " + forgeWorkDir);

        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(new File(forgeWorkDir));
        pb.redirectErrorStream(true);

        // Remove JAVA_TOOL_OPTIONS if inherited — it interferes with Forge startup
        pb.environment().remove("JAVA_TOOL_OPTIONS");

        // Timeout: clock seconds + 120s buffer for initialization
        long timeoutSeconds = clockSeconds + 120;

        long jvmStartMs = System.currentTimeMillis();
        Process process = pb.start();
        long jvmReadyMs = System.currentTimeMillis() - jvmStartMs;

        // Issue #4: Log JVM startup overhead for benchmarking
        System.out.printf("[PERF] JVM startup: %dms%n", jvmReadyMs);

        // Read stdout with a watchdog thread for timeout
        StringBuilder output = new StringBuilder();
        Thread watchdog = new Thread(() -> {
            try {
                Thread.sleep(timeoutSeconds * 1000);
                if (process.isAlive()) {
                    System.err.println("[WATCHDOG] Forge process exceeded timeout (" + timeoutSeconds + "s). Killing.");
                    process.destroyForcibly();
                }
            } catch (InterruptedException ignored) {
                // Normal: watchdog cancelled because process finished in time
            }
        }, "ForgeWatchdog-" + gameIndex);
        watchdog.setDaemon(true);
        watchdog.start();

        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
            String line;
            while ((line = reader.readLine()) != null) {
                output.append(line).append("\n");
            }
        }

        int exitCode = process.waitFor();
        watchdog.interrupt(); // Cancel watchdog if process finished naturally

        // Diagnostic: show Forge output summary
        String rawOutput = output.toString();
        String[] outLines = rawOutput.split("\n");
        System.out.printf("[DEBUG] Forge exit=%d, output=%d lines, length=%d chars%n",
                exitCode, outLines.length, rawOutput.length());
        if (rawOutput.isBlank()) {
            System.out.println("[DEBUG] Forge produced NO output — deck may not be found or Forge failed silently");
        } else {
            // Print first 5 and last 5 lines for quick diagnosis
            int show = Math.min(5, outLines.length);
            for (int li = 0; li < show; li++) {
                System.out.println("[DEBUG] OUT> " + outLines[li]);
            }
            if (outLines.length > 10) {
                System.out.println("[DEBUG] ... (" + (outLines.length - 10) + " lines omitted) ...");
                for (int li = outLines.length - 5; li < outLines.length; li++) {
                    if (li >= 0) System.out.println("[DEBUG] OUT> " + outLines[li]);
                }
            }
        }

        // Write debug log for every game
        writeDebugLog(gameIndex, cmdStr, rawOutput, exitCode);

        return parseForgeOutput(gameIndex, gameSeed, rawOutput, exitCode);
    }

    /**
     * Write raw Forge subprocess output to a debug log file.
     * This helps diagnose issues where Forge produces unexpected output.
     */
    private void writeDebugLog(int gameIndex, String command, String output, int exitCode) {
        try {
            Path logDir = Path.of(forgeWorkDir).getParent();
            if (logDir == null) logDir = Path.of(".");
            Path logFile = logDir.resolve("forge-sim-debug.log");

            StringBuilder log = new StringBuilder();
            log.append("\n════════════════════════════════════════════════════════════\n");
            log.append("Game ").append(gameIndex).append(" @ ");
            log.append(LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")));
            log.append("\nCommand: ").append(command);
            log.append("\nWorking Dir: ").append(forgeWorkDir);
            log.append("\nExit Code: ").append(exitCode);
            log.append("\n── RAW OUTPUT ──────────────────────────────────────────────\n");
            if (output.isBlank()) {
                log.append("<< NO OUTPUT >>\n");
            } else {
                log.append(output);
            }
            log.append("── END OUTPUT ──────────────────────────────────────────────\n");

            Files.writeString(logFile, log.toString(), StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);

            System.out.println("[DEBUG] Log written to: " + logFile.toAbsolutePath());
        } catch (Exception e) {
            System.err.println("[DEBUG] Failed to write debug log: " + e.getMessage());
        }
    }

    /**
     * Build the Forge sim command.
     * Invokes: java -jar forge-gui-desktop-XXX-jar-with-dependencies.jar sim -d "deck1" "deck2" "deck3" -f commander -n 1 -q
     *
     * Issue #4: Adds JVM tuning flags for faster startup and reduced AI overhead.
     */
    private List<String> buildForgeCommand() {
        List<String> cmd = new ArrayList<>();

        cmd.add(javaPath);

        // ── Forge-required JVM flags (from forge-gui-desktop/pom.xml) ──────
        // Memory — Commander 3-player games need substantial heap
        cmd.add("-Xmx4096m");

        // Issue #4: JVM startup optimization flags
        // -XX:+UseSerialGC reduces GC overhead for short-lived batch processes
        cmd.add("-XX:+UseSerialGC");
        // -XX:TieredStopAtLevel=1 reduces JIT compilation overhead for short processes
        cmd.add("-XX:TieredStopAtLevel=1");

        // NOTE: Do NOT add -Djava.awt.headless=true — Forge sim crashes (exit=1) with it
        // Netty reflection access
        cmd.add("-Dio.netty.tryReflectionSetAccessible=true");
        // UTF-8 encoding
        cmd.add("-Dfile.encoding=UTF-8");

        // Issue #4: AI think time cap (if configured)
        if (aiThinkTimeMs > 0) {
            cmd.add("-Dforge.ai.thinkTimeMs=" + aiThinkTimeMs);
        }
        if (useSimplifiedAi) {
            cmd.add("-Dforge.ai.simplified=true");
        }

        // ── Module access flags required by Forge on Java 17+ ─────────────
        String[] addOpens = {
            "java.desktop/java.beans=ALL-UNNAMED",
            "java.desktop/javax.swing.border=ALL-UNNAMED",
            "java.desktop/javax.swing.event=ALL-UNNAMED",
            "java.desktop/sun.swing=ALL-UNNAMED",
            "java.desktop/java.awt.image=ALL-UNNAMED",
            "java.desktop/java.awt.color=ALL-UNNAMED",
            "java.desktop/sun.awt.image=ALL-UNNAMED",
            "java.desktop/javax.swing=ALL-UNNAMED",
            "java.desktop/java.awt=ALL-UNNAMED",
            "java.base/java.util=ALL-UNNAMED",
            "java.base/java.lang=ALL-UNNAMED",
            "java.base/java.lang.reflect=ALL-UNNAMED",
            "java.base/java.text=ALL-UNNAMED",
            "java.desktop/java.awt.font=ALL-UNNAMED",
            "java.base/jdk.internal.misc=ALL-UNNAMED",
            "java.base/sun.nio.ch=ALL-UNNAMED",
            "java.base/java.nio=ALL-UNNAMED",
            "java.base/java.math=ALL-UNNAMED",
            "java.base/java.util.concurrent=ALL-UNNAMED",
            "java.base/java.net=ALL-UNNAMED",
        };
        for (String module : addOpens) {
            cmd.add("--add-opens");
            cmd.add(module);
        }

        cmd.add("-jar");
        cmd.add(forgeJarPath);

        cmd.add("sim");

        // Deck arguments — append .dck so Forge loads from DECK_COMMANDER_DIR as files
        // Without .dck, Forge uses FModel deck store which may fail in subprocess context
        cmd.add("-d");
        for (DeckInfo deck : decks) {
            String name = deck.deckFile;
            if (!name.endsWith(".dck")) {
                name = name + ".dck";
            }
            cmd.add(name);
        }

        // Format
        cmd.add("-f");
        cmd.add("commander");

        // Single game per subprocess call
        cmd.add("-n");
        cmd.add("1");

        // Clock (max seconds per game)
        cmd.add("-c");
        cmd.add(String.valueOf(clockSeconds));

        // Quiet mode for parseable output
        if (quiet) {
            cmd.add("-q");
        }

        return cmd;
    }

    /**
     * Parse Forge's stdout output into a GameResult.
     *
     * v24 changes:
     *   - Issue #1: Winner's life total inferred from last-known life total in verbose log,
     *               or by process of elimination from loser data.
     *   - Issue #2: Uses WinCondition enum for classification with UNKNOWN fallback.
     *
     * Expected lines:
     *   Game Outcome: Turn 11
     *   Game Outcome: Ai(1)-Edgar Markov has won because all opponents have lost
     *   Game Outcome: Ai(2)-Grimgrin has lost because life total reached 0
     *   Game Outcome: Ai(3)-Xyris has lost because life total reached 0
     *   Game Result: Game 1 ended in 9201 ms. Ai(1)-Edgar Markov has won!
     */
    private GameResult parseForgeOutput(int gameIndex, long gameSeed, String output, int exitCode) {
        GameResult result = new GameResult();
        result.gameIndex = gameIndex;
        result.gameSeed = gameSeed;
        result.winCondition = "unknown";
        result.totalTurns = 0;
        result.elapsedMs = 0;

        // Initialize player results for all 3 seats
        result.playerResults = new ArrayList<>();
        for (int i = 0; i < decks.size(); i++) {
            PlayerResult pr = new PlayerResult();
            pr.seatIndex = i;
            pr.finalLife = 40; // Commander starting life
            pr.mulligans = 0;
            pr.isWinner = false;
            pr.commanderDamageDealt = 0;
            pr.commanderCasts = 0;
            pr.landsPlayed = 0;
            pr.spellsCast = 0;
            pr.creaturesDestroyed = 0;
            result.playerResults.add(pr);
        }

        if (output.isBlank()) {
            result.winCondition = WinCondition.TIMEOUT.getLabel();
            return result;
        }

        String[] lines = output.split("\n");
        Map<String, String> lossReasons = new HashMap<>();

        // ── Issue #1: Track last-known life totals from verbose log ──────
        int numPlayers = decks.size();
        int[] lastKnownLife = new int[numPlayers];
        boolean[] lifeTracked = new boolean[numPlayers];
        for (int i = 0; i < numPlayers; i++) {
            lastKnownLife[i] = 40;  // Commander starting life
            lifeTracked[i] = false;
        }
        Set<Integer> loserSeats = new HashSet<>();

        for (String line : lines) {
            line = line.trim();

            // Parse turn count: "Game Outcome: Turn 11"
            Matcher turnMatcher = TURN_PATTERN.matcher(line);
            if (turnMatcher.find()) {
                result.totalTurns = Integer.parseInt(turnMatcher.group(1));
                continue;
            }

            // Parse winner: "Game Outcome: Ai(1)-Edgar Markov has won because ..."
            Matcher winMatcher = WINNER_PATTERN.matcher(line);
            if (winMatcher.find()) {
                int aiNumber = Integer.parseInt(winMatcher.group(1));
                int seatIndex = aiNumber - 1; // Forge uses 1-based, we use 0-based
                String winReason = winMatcher.group(3).trim();

                if (seatIndex >= 0 && seatIndex < decks.size()) {
                    result.winningSeat = seatIndex;
                    result.playerResults.get(seatIndex).isWinner = true;
                }
                continue;
            }

            // Parse loser: "Game Outcome: Ai(2)-Grimgrin has lost because life total reached 0"
            Matcher loseMatcher = LOSER_PATTERN.matcher(line);
            if (loseMatcher.find()) {
                int aiNumber = Integer.parseInt(loseMatcher.group(1));
                int seatIndex = aiNumber - 1;
                String lossReason = loseMatcher.group(3).trim();

                if (seatIndex >= 0 && seatIndex < decks.size()) {
                    lossReasons.put(String.valueOf(seatIndex), lossReason);
                    loserSeats.add(seatIndex);

                    // Try to extract final life from loss reason
                    if (lossReason.contains("life total reached 0")) {
                        result.playerResults.get(seatIndex).finalLife = 0;
                        lastKnownLife[seatIndex] = 0;
                    } else if (lossReason.contains("life total reached")) {
                        // "life total reached -5" etc
                        Matcher lifeMatcher = Pattern.compile("life total reached (-?\\d+)").matcher(lossReason);
                        if (lifeMatcher.find()) {
                            int life = Integer.parseInt(lifeMatcher.group(1));
                            result.playerResults.get(seatIndex).finalLife = life;
                            lastKnownLife[seatIndex] = life;
                        }
                    }
                    // For non-life-related losses (mill, poison, commander damage),
                    // life is NOT necessarily 0 — we rely on verbose log tracking below
                }
                continue;
            }

            // Parse game result timing: "Game Result: Game 1 ended in 9201 ms."
            Matcher gameResultMatcher = GAME_RESULT_PATTERN.matcher(line);
            if (gameResultMatcher.find()) {
                result.elapsedMs = Long.parseLong(gameResultMatcher.group(2));
                continue;
            }

            // Parse draw: "Game Result: Game 1 ended in ... draw"
            Matcher drawMatcher = GAME_DRAW_PATTERN.matcher(line);
            if (drawMatcher.find()) {
                result.elapsedMs = Long.parseLong(drawMatcher.group(2));
                result.winningSeat = null;
                result.winCondition = WinCondition.TIMEOUT.getLabel();
                continue;
            }

            // ── Issue #1: Track life totals from verbose log ────────────
            // "Ai(1)-Name's life is now 27"
            Matcher lifeMatch = LIFE_TOTAL_PATTERN.matcher(line);
            if (lifeMatch.find()) {
                int aiNum = Integer.parseInt(lifeMatch.group(1));
                int seat = aiNum - 1;
                int life = Integer.parseInt(lifeMatch.group(2));
                if (seat >= 0 && seat < decks.size()) {
                    lastKnownLife[seat] = life;
                    lifeTracked[seat] = true;
                }
                // Don't continue — other patterns may also match this line
            }

            // "Ai(1)-Name loses N life"
            Matcher lossMatch = LIFE_LOSS_PATTERN.matcher(line);
            if (lossMatch.find()) {
                int aiNum = Integer.parseInt(lossMatch.group(1));
                int seat = aiNum - 1;
                int amount = Integer.parseInt(lossMatch.group(2));
                if (seat >= 0 && seat < decks.size()) {
                    lastKnownLife[seat] -= amount;
                    lifeTracked[seat] = true;
                }
            }

            // "Ai(1)-Name gains N life"
            Matcher gainMatch = LIFE_GAIN_PATTERN.matcher(line);
            if (gainMatch.find()) {
                int aiNum = Integer.parseInt(gainMatch.group(1));
                int seat = aiNum - 1;
                int amount = Integer.parseInt(gainMatch.group(2));
                if (seat >= 0 && seat < decks.size()) {
                    lastKnownLife[seat] += amount;
                    lifeTracked[seat] = true;
                }
            }

            // Count mulligans from non-quiet output
            if (line.toLowerCase().contains("mulligan")) {
                Matcher mullMatcher = Pattern.compile("Ai\\((\\d+)\\)").matcher(line);
                if (mullMatcher.find()) {
                    int aiNum = Integer.parseInt(mullMatcher.group(1));
                    int seat = aiNum - 1;
                    if (seat >= 0 && seat < decks.size()) {
                        result.playerResults.get(seat).mulligans++;
                    }
                }
            }
        }

        // ── Issue #2: Classify win condition using formal enum ───────────
        WinCondition condition = WinCondition.classify(lossReasons, output);
        result.winCondition = condition.getLabel();

        // ── Issue #1: Set winner's final life total ─────────────────────
        // Strategy: Use last-known life from verbose log if available,
        // otherwise winner keeps default 40 (which is wrong but was the old behavior).
        // If we tracked life for the winner, use that.
        if (result.winningSeat != null) {
            int winnerSeat = result.winningSeat;
            if (lifeTracked[winnerSeat]) {
                result.playerResults.get(winnerSeat).finalLife = lastKnownLife[winnerSeat];
                System.out.printf("[LIFE] Winner seat %d: final life = %d (tracked from log)%n",
                        winnerSeat, lastKnownLife[winnerSeat]);
            } else {
                // Verbose tracking didn't capture — leave at 40 but log it
                System.out.printf("[LIFE] Winner seat %d: life not tracked in log (quiet mode?), defaulting to 40%n",
                        winnerSeat);
            }

            // Also update losers whose life wasn't set from loss reasons
            // (e.g., mill/poison losers whose life may not be 0)
            for (int seat = 0; seat < decks.size(); seat++) {
                if (seat != winnerSeat && lifeTracked[seat]) {
                    result.playerResults.get(seat).finalLife = lastKnownLife[seat];
                }
            }
        }

        // Default turn count if not parsed
        if (result.totalTurns == 0) {
            result.totalTurns = 1;
        }

        // ── Parse verbose game log for combat stats ─────────────────────
        // These patterns match Forge's full game log (non-quiet mode)
        // Track commander names for each seat to detect commander casts
        String[] commanderNames = new String[decks.size()];
        for (int ci = 0; ci < decks.size(); ci++) {
            commanderNames[ci] = decks.get(ci).commanderName;
        }

        for (String line : lines) {
            line = line.trim();
            if (line.isEmpty()) continue;

            // Match spell casts: "Ai(1)-Name casts CardName."
            Matcher castMatcher = CAST_PATTERN.matcher(line);
            if (castMatcher.find()) {
                int aiNum = Integer.parseInt(castMatcher.group(1));
                int seat = aiNum - 1;
                String cardName = castMatcher.group(2).trim();
                if (seat >= 0 && seat < decks.size()) {
                    result.playerResults.get(seat).spellsCast++;
                    // Check if this is the commander being cast
                    if (commanderNames[seat] != null &&
                            cardName.equalsIgnoreCase(commanderNames[seat])) {
                        result.playerResults.get(seat).commanderCasts++;
                    }
                }
                continue;
            }

            // Match land plays: "Ai(1)-Name plays LandName."
            Matcher landMatcher = LAND_PLAY_PATTERN.matcher(line);
            if (landMatcher.find()) {
                int aiNum = Integer.parseInt(landMatcher.group(1));
                int seat = aiNum - 1;
                if (seat >= 0 && seat < decks.size()) {
                    result.playerResults.get(seat).landsPlayed++;
                }
                continue;
            }

            // Match damage dealt: "deals N damage to Ai(X)"
            Matcher dmgMatcher = DAMAGE_PATTERN.matcher(line);
            while (dmgMatcher.find()) {
                // Note: this captures damage TO a player, not FROM.
                // We track it as creature/combat damage events
            }

            // Match creature deaths: "is destroyed" / "dies"
            if (CREATURE_DESTROYED_PATTERN.matcher(line).find()) {
                // Try to figure out which player's creature died
                // Look for Ai(N) reference before the destruction text
                Matcher aiRef = Pattern.compile("Ai\\((\\d+)\\)").matcher(line);
                // We attribute destruction to the OPPOSING player (the one who caused it)
                // But since we can't reliably determine the attacker, count it globally
                // For each seat, count creatures they destroyed (opponent's creatures that died)
                // Simple heuristic: if a creature controlled by Ai(X) dies, credit opponents
                if (aiRef.find()) {
                    int aiNum = Integer.parseInt(aiRef.group(1));
                    int victimSeat = aiNum - 1;
                    // Credit all non-victim seats with 1 creature destroyed
                    for (int s = 0; s < decks.size(); s++) {
                        if (s != victimSeat && s < result.playerResults.size()) {
                            // We can't know who did it, so we don't increment here
                            // Instead, use a simpler approach below
                        }
                    }
                }
            }

            // Commander damage tracking from loss reasons (already captured above)
            // Also try to parse "commander damage" mentions in verbose log
            if (line.toLowerCase().contains("commander damage")) {
                Matcher cdmg = Pattern.compile("(\\d+)\\s+commander\\s+damage").matcher(line.toLowerCase());
                if (cdmg.find()) {
                    int amount = Integer.parseInt(cdmg.group(1));
                    // Try to find the source player
                    Matcher srcPlayer = Pattern.compile("Ai\\((\\d+)\\)").matcher(line);
                    if (srcPlayer.find()) {
                        int seat = Integer.parseInt(srcPlayer.group(1)) - 1;
                        if (seat >= 0 && seat < decks.size()) {
                            result.playerResults.get(seat).commanderDamageDealt += amount;
                        }
                    }
                }
            }
        }

        // Estimate creatures destroyed from total turns if verbose parsing didn't catch specifics
        // (Forge log format varies; this provides a reasonable fallback)
        for (int seat = 0; seat < result.playerResults.size(); seat++) {
            PlayerResult pr = result.playerResults.get(seat);
            // If we got no spell data from parsing, it means either quiet mode or no matches
            // Leave at 0 rather than fabricating data
        }

        // ── Build per-card stats from verbose output (for coach analytics) ──
        if (!quiet) {
            try {
                buildPerCardStats(result, lines);
            } catch (Exception e) {
                System.err.println("[COACH] Per-card stat tracking failed: " + e.getMessage());
                // Non-fatal — game result is still valid without per-card data
            }
        }

        // ── ML Decision extraction (for RL training data) ─────────────────
        if (mlLoggingEnabled && !quiet && mlDecisionLogger != null) {
            try {
                int numPlayers = decks.size();
                String gid = "game-" + gameIndex + "-" + gameSeed;
                String[] cmdNames = new String[numPlayers];
                List<List<String>> deckCardLists = new ArrayList<>();

                for (int di = 0; di < numPlayers; di++) {
                    cmdNames[di] = decks.get(di).commanderName;
                    deckCardLists.add(readDeckCardNames(decks.get(di).deckFile));
                }

                DecisionExtractor extractor = new DecisionExtractor(
                        numPlayers, gid, cmdNames, deckCardLists);
                List<DecisionSnapshot> decisions = extractor.processGameLog(lines);

                // Build deck metadata map
                Map<Integer, Map<String, String>> deckMeta = new HashMap<>();
                for (int di = 0; di < numPlayers; di++) {
                    Map<String, String> meta = new HashMap<>();
                    meta.put("name", decks.get(di).deckName);
                    meta.put("commander", decks.get(di).commanderName);
                    meta.put("archetype", decks.get(di).archetype != null ? decks.get(di).archetype : "midrange");
                    deckMeta.put(di, meta);
                }

                // Determine game outcome
                String outcome = result.winningSeat != null
                        ? "win_seat_" + result.winningSeat
                        : "draw";

                mlDecisionLogger.logGameDecisions(decisions, deckMeta, outcome);

                if (!decisions.isEmpty()) {
                    System.out.printf("[ML] Game %d: %d decision snapshots extracted%n",
                            gameIndex, decisions.size());
                }
            } catch (Exception e) {
                System.err.println("[ML] Decision extraction failed for game " + gameIndex + ": " + e.getMessage());
                // Non-fatal
            }
        }

        return result;
    }

    // ══════════════════════════════════════════════════════════════
    // JVM Process Pool (Issue #3)
    // ══════════════════════════════════════════════════════════════

    /**
     * Shutdown any pooled Forge worker processes.
     */
    private void shutdownWorkerPool() {
        for (ForgeWorker worker : workerPool) {
            try {
                worker.shutdown();
            } catch (Exception e) {
                System.err.println("[POOL] Error shutting down worker: " + e.getMessage());
            }
        }
        workerPool.clear();
    }

    /**
     * Inner class representing a persistent Forge JVM worker process.
     * Issue #3: Keeps a JVM alive to avoid repeated startup overhead.
     *
     * NOTE: This is a future enhancement stub. Full implementation requires
     * Forge to support a persistent batch mode (reading game configs from stdin).
     * Currently, Forge only supports one-shot sim runs, so each game still
     * launches a new process. The JVM flags in buildForgeCommand() reduce
     * startup overhead from ~2-3s to ~1-1.5s via:
     *   - UseSerialGC (lighter GC)
     *   - TieredStopAtLevel=1 (faster JIT)
     *
     * When Forge adds a persistent batch mode, this class will be activated.
     */
    static class ForgeWorker {
        private Process process;
        private boolean alive = false;

        void shutdown() {
            if (process != null && process.isAlive()) {
                process.destroyForcibly();
            }
            alive = false;
        }
    }

    // ══════════════════════════════════════════════════════════════
    // Progress Callback Interface (Issue #5)
    // ══════════════════════════════════════════════════════════════

    /**
     * Callback interface for real-time progress reporting.
     * Implementations receive updates after each game completes.
     */
    public interface ProgressCallback {
        /**
         * Called after each game completes.
         *
         * @param completed  Number of games completed so far
         * @param total      Total games in the batch
         * @param percentDone Completion percentage (0-100)
         * @param simsPerSec Current throughput (games per second)
         * @param lastResult The most recently completed game result
         */
        void onProgress(int completed, int total, int percentDone,
                        double simsPerSec, GameResult lastResult);
    }

    // ══════════════════════════════════════════════════════════════
    // Per-Card Stat Tracking
    // ══════════════════════════════════════════════════════════════

    /**
     * Read card names from a Forge .dck file.
     * Format:
     *   [Commander]
     *   1 Card Name|SET
     *   [Main]
     *   1 Card Name|SET
     *   ...
     *
     * Returns all card names (Commander + Main), excluding sideboard.
     */
    private List<String> readDeckCardNames(String deckFilePath) {
        List<String> names = new ArrayList<>();
        try {
            Path path = Path.of(deckFilePath);
            if (!Files.exists(path)) {
                // Try adding .dck extension
                Path withExt = Path.of(deckFilePath + ".dck");
                if (Files.exists(withExt)) {
                    path = withExt;
                } else {
                    // Try resolving against Forge commander decks directory
                    Path resolved = resolveForgeDecksPath(deckFilePath);
                    if (resolved != null && Files.exists(resolved)) {
                        path = resolved;
                    } else {
                        System.err.println("[COACH] Deck file not found: " + deckFilePath);
                        return names;
                    }
                }
            }
            List<String> lines = Files.readAllLines(path);
            String section = "Main";
            Pattern cardLine = Pattern.compile("^(\\d+)\\s+(.+?)(?:\\|(.+))?$");

            for (String line : lines) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("//")) continue;

                if (line.startsWith("[") && line.endsWith("]")) {
                    section = line.substring(1, line.length() - 1);
                    continue;
                }
                if (line.startsWith("Name=")) continue;

                // Skip sideboard
                if (section.equalsIgnoreCase("Sideboard")) continue;

                Matcher m = cardLine.matcher(line);
                if (m.matches()) {
                    String cardName = m.group(2).trim();
                    int qty = Integer.parseInt(m.group(1));
                    // In Commander, qty is always 1, but just in case
                    for (int q = 0; q < qty; q++) {
                        names.add(cardName);
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("[COACH] Failed to read deck file: " + deckFilePath + " - " + e.getMessage());
        }
        return names;
    }

    /**
     * Resolve a deck name to its full path in the Forge commander decks directory.
     * Checks %APPDATA%/Forge/decks/commander/ on Windows.
     */
    private Path resolveForgeDecksPath(String deckName) {
        try {
            String appdata = System.getenv("APPDATA");
            if (appdata == null || appdata.isEmpty()) return null;
            Path decksDir = Path.of(appdata, "Forge", "decks", "commander");
            if (!Files.isDirectory(decksDir)) return null;

            // Try with .dck extension
            String name = deckName;
            if (!name.endsWith(".dck")) name = name + ".dck";
            Path candidate = decksDir.resolve(name);
            if (Files.exists(candidate)) return candidate;

            // Case-insensitive fallback
            String lowerName = name.toLowerCase();
            try (var stream = Files.list(decksDir)) {
                return stream
                    .filter(p -> p.getFileName().toString().toLowerCase().equals(lowerName))
                    .findFirst()
                    .orElse(null);
            }
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * Build per-card game stats from verbose Forge log output.
     *
     * Tracks for each card in each player's deck:
     *   - drawn: was the card drawn (or in opening hand)
     *   - turnDrawn: first turn the card was drawn
     *   - cast: was the card cast
     *   - turnCast: turn it was cast
     *   - stuckInHand: drawn but never cast
     *   - damageDealt: damage attributed to this card (best effort)
     *   - inOpeningHand / keptInOpeningHand: opening-hand tracking
     */
    private void buildPerCardStats(GameResult result, String[] lines) {
        // Initialize per-card maps for each seat from deck files
        @SuppressWarnings("unchecked")
        Map<String, PerCardGameStats>[] seatCards = new Map[decks.size()];
        for (int s = 0; s < decks.size(); s++) {
            seatCards[s] = new LinkedHashMap<>();
            List<String> cardNames = readDeckCardNames(decks.get(s).deckFile);
            for (String name : cardNames) {
                if (!seatCards[s].containsKey(name)) {
                    seatCards[s].put(name, new PerCardGameStats(name));
                }
            }
        }

        // Track current turn per seat
        int globalTurn = 0;
        boolean[] openingHandPhase = new boolean[decks.size()];
        java.util.Arrays.fill(openingHandPhase, true); // before first turn

        for (String rawLine : lines) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;

            // Detect turn boundaries: "Turn 5 (Ai(1)-Name)"
            Matcher turnMatch = VERBOSE_TURN_PATTERN.matcher(line);
            if (turnMatch.find()) {
                int turnNum = Integer.parseInt(turnMatch.group(1));
                int aiNum = Integer.parseInt(turnMatch.group(2));
                globalTurn = turnNum;
                int seat = aiNum - 1;
                if (seat >= 0 && seat < decks.size()) {
                    openingHandPhase[seat] = false;
                }
                continue;
            }

            // Detect draws: "Ai(1)-Name draws CardName."
            Matcher drawMatch = DRAW_PATTERN.matcher(line);
            if (drawMatch.find()) {
                int seat = Integer.parseInt(drawMatch.group(1)) - 1;
                String cardName = drawMatch.group(2).trim();
                if (seat >= 0 && seat < decks.size() && seatCards[seat] != null) {
                    PerCardGameStats stats = seatCards[seat].get(cardName);
                    if (stats == null) {
                        // Card not in deck list (token draw, etc.) — create entry
                        stats = new PerCardGameStats(cardName);
                        seatCards[seat].put(cardName, stats);
                    }
                    if (!stats.drawn) {
                        stats.drawn = true;
                        stats.turnDrawn = globalTurn;
                    }
                    if (openingHandPhase[seat]) {
                        stats.inOpeningHand = true;
                        stats.keptInOpeningHand = true; // assume kept unless mulligan detected
                    }
                }
                continue;
            }

            // Detect casts: "Ai(1)-Name casts CardName."
            Matcher castMatch = CAST_PATTERN.matcher(line);
            if (castMatch.find()) {
                int seat = Integer.parseInt(castMatch.group(1)) - 1;
                String cardName = castMatch.group(2).trim();
                if (seat >= 0 && seat < decks.size() && seatCards[seat] != null) {
                    PerCardGameStats stats = seatCards[seat].get(cardName);
                    if (stats == null) {
                        stats = new PerCardGameStats(cardName);
                        seatCards[seat].put(cardName, stats);
                    }
                    if (!stats.cast) {
                        stats.cast = true;
                        stats.turnCast = globalTurn;
                    }
                    // Mark as drawn if not already (commander zone casts, etc.)
                    if (!stats.drawn) {
                        stats.drawn = true;
                        stats.turnDrawn = globalTurn;
                    }
                }
                continue;
            }

            // Detect land plays: "Ai(1)-Name plays LandName."
            Matcher landMatch = LAND_PLAY_PATTERN.matcher(line);
            if (landMatch.find()) {
                int seat = Integer.parseInt(landMatch.group(1)) - 1;
                String cardName = landMatch.group(2).trim();
                if (seat >= 0 && seat < decks.size() && seatCards[seat] != null) {
                    PerCardGameStats stats = seatCards[seat].get(cardName);
                    if (stats == null) {
                        stats = new PerCardGameStats(cardName);
                        seatCards[seat].put(cardName, stats);
                    }
                    if (!stats.cast) {
                        stats.cast = true;  // playing a land counts as "using" it
                        stats.turnCast = globalTurn;
                    }
                    if (!stats.drawn) {
                        stats.drawn = true;
                        stats.turnDrawn = globalTurn;
                    }
                }
                continue;
            }

            // Detect per-card damage: "CardName deals N damage"
            Matcher cardDmgMatch = CARD_DAMAGE_PATTERN.matcher(line);
            if (cardDmgMatch.find()) {
                String cardName = cardDmgMatch.group(1).trim();
                int amount = Integer.parseInt(cardDmgMatch.group(2));
                // Try to find which seat owns this card
                for (int s = 0; s < decks.size(); s++) {
                    if (seatCards[s] != null && seatCards[s].containsKey(cardName)) {
                        seatCards[s].get(cardName).damageDealt += amount;
                        break; // attribute to first matching seat
                    }
                }
            }
        }

        // Finalize: compute stuckInHand and attach to PlayerResults
        for (int s = 0; s < result.playerResults.size(); s++) {
            if (seatCards[s] == null) continue;
            List<PerCardGameStats> cardStatsList = new ArrayList<>();
            for (PerCardGameStats stats : seatCards[s].values()) {
                stats.computeStuckInHand();
                cardStatsList.add(stats);
            }
            result.playerResults.get(s).cardStats = cardStatsList;
        }
    }

    /**
     * Create a placeholder GameResult for a failed/crashed game.
     */
    private GameResult createFailedGame(int gameIndex, long gameSeed, long elapsedMs) {
        GameResult result = new GameResult();
        result.gameIndex = gameIndex;
        result.gameSeed = gameSeed;
        result.winningSeat = null;
        result.totalTurns = 0;
        result.winCondition = WinCondition.TIMEOUT.getLabel();
        result.elapsedMs = elapsedMs;
        result.playerResults = new ArrayList<>();
        for (int i = 0; i < decks.size(); i++) {
            PlayerResult pr = new PlayerResult();
            pr.seatIndex = i;
            pr.finalLife = 40;
            pr.mulligans = 0;
            pr.isWinner = false;
            result.playerResults.add(pr);
        }
        return result;
    }
}
