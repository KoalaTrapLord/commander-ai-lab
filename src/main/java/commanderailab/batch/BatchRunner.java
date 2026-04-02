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
 * Deck path resolution (priority order):
 *   1. PRECON_DECKS_DIR environment variable
 *   2. D:\ForgeCommander\commander-ai-lab\precon-decks  (hardcoded project default)
 *   3. %APPDATA%\Forge\decks\commander  (legacy Forge location)
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

    // ── Hardcoded project-default precon directory ────────────────────────
    private static final String DEFAULT_PRECON_DIR =
            "D:\\ForgeCommander\\commander-ai-lab\\precon-decks";

    private final String forgeJarPath;    // Path to forge-gui-desktop JAR (jar-with-dependencies)
    private final String forgeWorkDir;    // Working directory for Forge (where res/ folder is)
    private final List<DeckInfo> decks;   // 3 or 4 decks
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
            Pattern.compile("Game Outcome:\\s*Ai\\(?(\\d+)\\)?-(.+?)\\s+has won because (.+)");

    // "Game Outcome: Ai(2)-Grimgrin has lost because life total reached 0"
    private static final Pattern LOSER_PATTERN =
            Pattern.compile("Game Outcome:\\s*Ai\\(?(\\d+)\\)?-(.+?)\\s+has lost because (.+)");

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
    private static final Pattern LIFE_CHANGE_PATTERN =
            Pattern.compile("Life:\\s*Life:\\s*Ai\\(?(\\d+)\\)?-.+?\\s+(\\d+)\\s*>\\s*(-?\\d+)");

    private static final Pattern LIFE_TOTAL_PATTERN =
            Pattern.compile("Ai\\(?(\\d+)\\)?-.+?'s\\s+life(?:\\s+total)?\\s+is\\s+now\\s+(-?\\d+)", Pattern.CASE_INSENSITIVE);

    private static final Pattern LIFE_LOSS_PATTERN =
            Pattern.compile("Ai\\(?(\\d+)\\)?-.+?\\s+loses\\s+(\\d+)\\s+life", Pattern.CASE_INSENSITIVE);

    private static final Pattern LIFE_GAIN_PATTERN =
            Pattern.compile("Ai\\(?(\\d+)\\)?-.+?\\s+gains\\s+(\\d+)\\s+life", Pattern.CASE_INSENSITIVE);

    // ── Verbose game-log patterns for extracting combat stats ────────────

    private static final Pattern CAST_PATTERN =
            Pattern.compile("(?:Add To Stack:\\s*)?Ai\\(?(\\d+)\\)?-[^\\s].*?\\s+casts?\\s+(.+?)(?:\\s+targeting.*)?$", Pattern.CASE_INSENSITIVE);

    private static final Pattern LAND_PLAY_PATTERN =
                        Pattern.compile("(?:Land:\\s*)?Ai\\(?(\\d+)\\)?-[^\\s].*?\\s+play(?:s|ed)\\s+(.+?)(?:\\s+\\(\\d+\\))?(?:\\.|$)", Pattern.CASE_INSENSITIVE);

    private static final Pattern ZONE_CHANGE_PATTERN =
            Pattern.compile("Zone Change:\\s*(.+?)\\s+(?:\\(\\d+\\)\\s+)?was put into .* from Battlefield", Pattern.CASE_INSENSITIVE);
    private static final Pattern CREATURE_DESTROYED_PATTERN =
            Pattern.compile("(is destroyed|dies|is put into .* graveyard from the battlefield)", Pattern.CASE_INSENSITIVE);

    private static final Pattern DAMAGE_PATTERN =
            Pattern.compile("deals\\s+(\\d+)\\s+(?:combat\\s+)?damage\\s+to\\s+Ai\\(?(\\d+)\\)?", Pattern.CASE_INSENSITIVE);

    private static final Pattern PLAYER_DAMAGE_SOURCE_PATTERN =
            Pattern.compile("(?:Damage:\\s*)?(.+?)\\s+deals\\s+(\\d+)\\s+(?:combat\\s+)?damage\\s+to\\s+Ai\\(?(\\d+)\\)?", Pattern.CASE_INSENSITIVE);
    private static final Pattern CMDR_DAMAGE_PATTERN =
            Pattern.compile("Ai\\(?(\\d+)\\)?.*?commander.*?damage.*?(\\d+)", Pattern.CASE_INSENSITIVE);

    // ── Per-card tracking patterns (verbose log) ─────────────────────────

    private static final Pattern DRAW_PATTERN =
            Pattern.compile("Ai\\(?(\\d+)\\)?-[^\\s].*?\\s+draws\\s+(.+?)(?:\\.|$)", Pattern.CASE_INSENSITIVE);

    private static final Pattern VERBOSE_TURN_PATTERN =
            Pattern.compile("Turn\\s+(\\d+)\\s+\\(Ai\\(?(\\d+)\\)?", Pattern.CASE_INSENSITIVE);

    private static final Pattern CARD_DAMAGE_PATTERN =
            Pattern.compile("(.+?)\\s+deals\\s+(\\d+)\\s+(?:combat\\s+)?damage", Pattern.CASE_INSENSITIVE);

    public BatchRunner(String forgeJarPath, String forgeWorkDir, List<DeckInfo> decks, AiPolicy policy) {
        this(forgeJarPath, forgeWorkDir, decks, policy, false,
                decks.size() >= 4 ? 300 : 180);
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

    public void setProgressCallback(ProgressCallback callback) {
        this.progressCallback = callback;
    }

    public void setUseProcessPool(boolean usePool) {
        this.useProcessPool = usePool;
    }

    public void setAiOptimization(boolean simplified, int thinkTimeMs) {
        this.useSimplifiedAi = simplified;
        this.aiThinkTimeMs = thinkTimeMs;
    }

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

    public List<GameResult> runBatchSingleThread(int numGames, Long masterSeed) {
        List<GameResult> results = new ArrayList<>();
        long batchStartMs = System.currentTimeMillis();

        for (int i = 0; i < numGames; i++) {
            long gameSeed = (masterSeed != null) ? masterSeed + i : System.nanoTime();
            long startMs = System.currentTimeMillis();

            try {
                GameResult result = runSingleGame(i, gameSeed);
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

        shutdownWorkerPool();

        long totalElapsed = System.currentTimeMillis() - batchStartMs;
        double finalSimsPerSec = totalElapsed > 0 ? (double) results.size() / (totalElapsed / 1000.0) : 0.0;
        System.out.printf("[BATCH] Completed %d games in %.1fs (%.3f sims/sec)%n",
                results.size(), totalElapsed / 1000.0, finalSimsPerSec);

        return results;
    }

    private GameResult runSingleGame(int gameIndex, long gameSeed) throws IOException, InterruptedException {
        List<String> cmd = buildForgeCommand();

        String cmdStr = String.join(" ", cmd);
        System.out.println("[DEBUG] Forge command: " + cmdStr);
        System.out.println("[DEBUG] Working dir: " + forgeWorkDir);

        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(new File(forgeWorkDir));
        pb.redirectErrorStream(true);
        pb.environment().remove("JAVA_TOOL_OPTIONS");

        long timeoutSeconds = clockSeconds + 120;

        long jvmStartMs = System.currentTimeMillis();
        Process process = pb.start();
        long jvmReadyMs = System.currentTimeMillis() - jvmStartMs;
        System.out.printf("[PERF] JVM startup: %dms%n", jvmReadyMs);

        StringBuilder output = new StringBuilder();
        Thread watchdog = new Thread(() -> {
            try {
                Thread.sleep(timeoutSeconds * 1000);
                if (process.isAlive()) {
                    System.err.println("[WATCHDOG] Forge process exceeded timeout (" + timeoutSeconds + "s). Killing.");
                    process.destroyForcibly();
                }
            } catch (InterruptedException ignored) {}
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
        watchdog.interrupt();

        String rawOutput = output.toString();
        String[] outLines = rawOutput.split("\n");
        System.out.printf("[DEBUG] Forge exit=%d, output=%d lines, length=%d chars%n",
                exitCode, outLines.length, rawOutput.length());
        if (rawOutput.isBlank()) {
            System.out.println("[DEBUG] Forge produced NO output — deck may not be found or Forge failed silently");
        } else {
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

        writeDebugLog(gameIndex, cmdStr, rawOutput, exitCode);

        return parseForgeOutput(gameIndex, gameSeed, rawOutput, exitCode);
    }

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
     *
     * Deck paths are passed as FULL ABSOLUTE PATHS (e.g.
     * D:\ForgeCommander\commander-ai-lab\precon-decks\Elven_Empire.dck)
     * so Forge can find them regardless of working directory.
     *
     * Path resolution for each deck:
     *   1. If deckFile is already an absolute path that exists → use as-is
     *   2. Resolve against PRECON_DECKS_DIR env var
     *   3. Resolve against hardcoded DEFAULT_PRECON_DIR
     *   4. Resolve against %APPDATA%\Forge\decks\commander (legacy)
     *   5. Fall back to bare name (let Forge try its own lookup)
     */
    private List<String> buildForgeCommand() {
        List<String> cmd = new ArrayList<>();

        cmd.add(javaPath);

        cmd.add("-Xmx4096m");
        cmd.add("-XX:+UseSerialGC");
        cmd.add("-XX:TieredStopAtLevel=1");
        cmd.add("-Dio.netty.tryReflectionSetAccessible=true");
        cmd.add("-Dfile.encoding=UTF-8");

        if (aiThinkTimeMs > 0) {
            cmd.add("-Dforge.ai.thinkTimeMs=" + aiThinkTimeMs);
        }
        if (useSimplifiedAi) {
            cmd.add("-Dforge.ai.simplified=true");
        }

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

        // Pass each deck as a full absolute path so Forge can find the .dck file
        // regardless of its working directory.
        cmd.add("-d");
        for (DeckInfo deck : decks) {
            String resolvedPath = resolveFullDeckPath(deck.deckFile);
            cmd.add(resolvedPath);
            System.out.println("[DECK] Resolved deck path: " + resolvedPath);
        }

        cmd.add("-f");
        cmd.add("commander");

        cmd.add("-n");
        cmd.add("1");

        cmd.add("-c");
        cmd.add(String.valueOf(clockSeconds));

        if (quiet) {
            cmd.add("-q");
        }

        return cmd;
    }

    /**
     * Resolve a deck file name to its full absolute path.
     *
     * Priority:
     *   1. Already an absolute path that exists on disk → return as-is
     *   2. PRECON_DECKS_DIR env var / precon-decks folder
     *   3. Hardcoded DEFAULT_PRECON_DIR
     *   4. %APPDATA%\Forge\decks\commander  (legacy)
     *   5. Bare name with .dck appended (Forge internal lookup fallback)
     */
    private String resolveFullDeckPath(String deckFile) {
        // Ensure .dck extension
        String name = deckFile.endsWith(".dck") ? deckFile : deckFile + ".dck";

        // 1. Already an absolute path?
        Path absolute = Path.of(name);
        if (absolute.isAbsolute() && Files.exists(absolute)) {
            return absolute.toString();
        }

        // 2. PRECON_DECKS_DIR env var
        String envDir = System.getenv("PRECON_DECKS_DIR");
        if (envDir != null && !envDir.isBlank()) {
            Path candidate = Path.of(envDir, name);
            if (Files.exists(candidate)) {
                return candidate.toAbsolutePath().toString();
            }
        }

        // 3. Hardcoded project default
        Path defaultCandidate = Path.of(DEFAULT_PRECON_DIR, name);
        if (Files.exists(defaultCandidate)) {
            return defaultCandidate.toAbsolutePath().toString();
        }

        // 4. Legacy %APPDATA%\Forge\decks\commander
        String appdata = System.getenv("APPDATA");
        if (appdata != null) {
            Path legacyCandidate = Path.of(appdata, "Forge", "decks", "commander", name);
            if (Files.exists(legacyCandidate)) {
                return legacyCandidate.toAbsolutePath().toString();
            }
        }

        // 5. Fallback — Forge will attempt its own lookup
        System.err.println("[WARN] Could not resolve deck path for: " + name
                + " — passing bare name to Forge (may fail)");
        return name;
    }

    private GameResult parseForgeOutput(int gameIndex, long gameSeed, String output, int exitCode) {
        GameResult result = new GameResult();
        result.gameIndex = gameIndex;
        result.gameSeed = gameSeed;
        result.winCondition = "unknown";
        result.totalTurns = 0;
        result.elapsedMs = 0;

        result.playerResults = new ArrayList<>();
        for (int i = 0; i < decks.size(); i++) {
            PlayerResult pr = new PlayerResult();
            pr.seatIndex = i;
            pr.finalLife = 40;
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

        int numPlayers = decks.size();
        int[] lastKnownLife = new int[numPlayers];
        boolean[] lifeTracked = new boolean[numPlayers];
        for (int i = 0; i < numPlayers; i++) {
            lastKnownLife[i] = 40;
            lifeTracked[i] = false;
        }
        Set<Integer> loserSeats = new HashSet<>();
        Set<Integer> winnerCandidates = new HashSet<>();
        int maxVerboseTurn = 0;
        for (String line : lines) {
            line = line.trim();
            if (line.startsWith("Game Outcome:") || line.startsWith("Game Result:") || line.startsWith("Match Result:")) {
                System.out.println("[OUTCOME-LINE] " + line);
            }

            Matcher turnMatcher = TURN_PATTERN.matcher(line);
            if (turnMatcher.find()) {
                result.totalTurns = Integer.parseInt(turnMatcher.group(1));
                continue;
            }

            Matcher verboseTurn = VERBOSE_TURN_PATTERN.matcher(line);
            if (verboseTurn.find()) {
                int t = Integer.parseInt(verboseTurn.group(1));
                if (t > maxVerboseTurn) maxVerboseTurn = t;
            }

            Matcher winMatcher = WINNER_PATTERN.matcher(line);
            if (winMatcher.find()) {
                int aiNumber = Integer.parseInt(winMatcher.group(1));
                int seatIndex = aiNumber - 1;
                if (seatIndex >= 0 && seatIndex < decks.size()) {
                    winnerCandidates.add(seatIndex);
                }
                continue;
            }

            Matcher loseMatcher = LOSER_PATTERN.matcher(line);
            if (loseMatcher.find()) {
                int aiNumber = Integer.parseInt(loseMatcher.group(1));
                int seatIndex = aiNumber - 1;
                String lossReason = loseMatcher.group(3).trim();

                if (seatIndex >= 0 && seatIndex < decks.size()) {
                    lossReasons.put(String.valueOf(seatIndex), lossReason);
                    loserSeats.add(seatIndex);

                    if (lossReason.contains("life total reached 0")) {
                        result.playerResults.get(seatIndex).finalLife = 0;
                        lastKnownLife[seatIndex] = 0;
                    } else if (lossReason.contains("life total reached")) {
                        Matcher lifeMatcher = Pattern.compile("life total reached (-?\\d+)").matcher(lossReason);
                        if (lifeMatcher.find()) {
                            int life = Integer.parseInt(lifeMatcher.group(1));
                            result.playerResults.get(seatIndex).finalLife = life;
                            lastKnownLife[seatIndex] = life;
                        }
                    }
                }
                continue;
            }

            Matcher gameResultMatcher = GAME_RESULT_PATTERN.matcher(line);
            if (gameResultMatcher.find()) {
                result.elapsedMs = Long.parseLong(gameResultMatcher.group(2));
                continue;
            }

            Matcher drawMatcher = GAME_DRAW_PATTERN.matcher(line);
            if (drawMatcher.find()) {
                result.elapsedMs = Long.parseLong(drawMatcher.group(2));
                result.winningSeat = null;
                result.winCondition = WinCondition.TIMEOUT.getLabel();
                continue;
            }

            Matcher lifeChangeMatch = LIFE_CHANGE_PATTERN.matcher(line);
            if (lifeChangeMatch.find()) {
                int aiNum = Integer.parseInt(lifeChangeMatch.group(1));
                int seat = aiNum - 1;
                int newLife = Integer.parseInt(lifeChangeMatch.group(3));
                if (seat >= 0 && seat < decks.size()) {
                    lastKnownLife[seat] = newLife;
                    lifeTracked[seat] = true;
                }
            }

            Matcher lifeMatch = LIFE_TOTAL_PATTERN.matcher(line);
            if (lifeMatch.find()) {
                int aiNum = Integer.parseInt(lifeMatch.group(1));
                int seat = aiNum - 1;
                int life = Integer.parseInt(lifeMatch.group(2));
                if (seat >= 0 && seat < decks.size()) {
                    lastKnownLife[seat] = life;
                    lifeTracked[seat] = true;
                }
            }

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

            if (line.toLowerCase().contains("mulligan")) {
                Matcher mullMatcher = Pattern.compile("Ai\\(?(\\d+)\\)?").matcher(line);
                if (mullMatcher.find()) {
                    int aiNum = Integer.parseInt(mullMatcher.group(1));
                    int seat = aiNum - 1;
                    if (seat >= 0 && seat < decks.size()) {
                        result.playerResults.get(seat).mulligans++;
                    }
                }
            }
        }

        if (winnerCandidates.size() == 1) {
            int winSeat = winnerCandidates.iterator().next();
            result.winningSeat = winSeat;
            result.playerResults.get(winSeat).isWinner = true;
            System.out.printf("[WINNER] Single winner: seat %d%n", winSeat);
        } else if (winnerCandidates.size() > 1) {
            int bestSeat = -1;
            int bestLife = Integer.MIN_VALUE;
            for (int seat : winnerCandidates) {
                int life = lifeTracked[seat] ? lastKnownLife[seat] : 40;
                if (life > bestLife) {
                    bestLife = life;
                    bestSeat = seat;
                }
            }
            if (bestSeat >= 0) {
                result.winningSeat = bestSeat;
                result.playerResults.get(bestSeat).isWinner = true;
                System.out.printf("[WINNER] Resolved from %d candidates: seat %d (life=%d).%n",
                        winnerCandidates.size(), bestSeat, bestLife);
            }
        }

        WinCondition condition = WinCondition.classify(lossReasons, output);
        result.winCondition = condition.getLabel();

        for (int seat = 0; seat < decks.size(); seat++) {
            if (lifeTracked[seat]) {
                result.playerResults.get(seat).finalLife = lastKnownLife[seat];
            }
        }
        if (result.winningSeat != null) {
            int winnerSeat = result.winningSeat;
            if (lifeTracked[winnerSeat]) {
                System.out.printf("[LIFE] Winner seat %d: final life = %d (tracked from log)%n",
                        winnerSeat, lastKnownLife[winnerSeat]);
            } else {
                System.out.printf("[LIFE] Winner seat %d: life not tracked in log (quiet mode?), defaulting to 40%n",
                        winnerSeat);
            }
        }

        if (result.totalTurns == 0 && maxVerboseTurn > 0) {
            result.totalTurns = maxVerboseTurn;
            System.out.printf("[TURNS] Using verbose log turn count: %d%n", maxVerboseTurn);
        } else if (result.totalTurns == 0) {
            result.totalTurns = 1;
        }

        String[] commanderNames = new String[decks.size()];
        for (int ci = 0; ci < decks.size(); ci++) {
            commanderNames[ci] = decks.get(ci).commanderName;
        }
        for (int ci2 = 0; ci2 < decks.size(); ci2++) {
            if (commanderNames[ci2] == null || commanderNames[ci2].isEmpty()
                    || commanderNames[ci2].equals(decks.get(ci2).deckName)
                    || commanderNames[ci2].equals(decks.get(ci2).deckFile)) {
                String detected = readCommanderCardName(decks.get(ci2).deckFile);
                if (detected != null && !detected.isEmpty()) {
                    commanderNames[ci2] = detected;
                    System.out.printf("[CMDR] Seat %d: auto-detected commander '%s' from .dck file%n", ci2, detected);
                }
            }
        }
        for (int ci3 = 0; ci3 < decks.size(); ci3++) {
            System.out.printf("[CMDR-INFO] Seat %d: commander='%s', deckName='%s'%n",
                    ci3, commanderNames[ci3], decks.get(ci3).deckName);
        }

        for (String line : lines) {
            String lower = line.trim().toLowerCase();
            if (lower.contains("cast") || lower.contains("play") || lower.contains("damage") || lower.contains("add to stack") || lower.contains("land:")) {
                System.out.println("[COMBAT-LINE] " + line.trim());
            }
            line = line.trim();
            if (line.isEmpty()) continue;

            Matcher castMatcher = CAST_PATTERN.matcher(line);
            if (castMatcher.find()) {
                int aiNum = Integer.parseInt(castMatcher.group(1));
                int seat = aiNum - 1;
                String cardName = castMatcher.group(2).trim();
                if (seat >= 0 && seat < decks.size()) {
                    result.playerResults.get(seat).spellsCast++;
                    if (commanderNames[seat] != null &&
                            cardName.equalsIgnoreCase(commanderNames[seat])) {
                        result.playerResults.get(seat).commanderCasts++;
                    }
                }
                continue;
            }

            Matcher landMatcher = LAND_PLAY_PATTERN.matcher(line);
            if (landMatcher.find()) {
                int aiNum = Integer.parseInt(landMatcher.group(1));
                int seat = aiNum - 1;
                if (seat >= 0 && seat < decks.size()) {
                    result.playerResults.get(seat).landsPlayed++;
                }
                continue;
            }

            Matcher playerDmgMatcher = PLAYER_DAMAGE_SOURCE_PATTERN.matcher(line);
            if (playerDmgMatcher.find()) {
                String sourceCard = playerDmgMatcher.group(1).trim();
                int dmgAmount = Integer.parseInt(playerDmgMatcher.group(2));
                int targetAiNum = Integer.parseInt(playerDmgMatcher.group(3));
                int targetSeat = targetAiNum - 1;
                for (int ci = 0; ci < decks.size(); ci++) {
                    if (commanderNames[ci] != null && sourceCard.equalsIgnoreCase(commanderNames[ci])) {
                        if (ci >= 0 && ci < result.playerResults.size()) {
                            result.playerResults.get(ci).commanderDamageDealt += dmgAmount;
                            System.out.printf("[CMDR-DMG] %s (seat %d) dealt %d cmdr damage to seat %d%n",
                                    sourceCard, ci, dmgAmount, targetSeat);
                        }
                        break;
                    }
                }
            }

            if (line.toLowerCase().contains("commander damage")) {
                Matcher cdmg = Pattern.compile("(\\d+)\\s+commander\\s+damage").matcher(line.toLowerCase());
                if (cdmg.find()) {
                    int amount = Integer.parseInt(cdmg.group(1));
                    Matcher srcPlayer = Pattern.compile("Ai\\(?(\\d+)\\)?").matcher(line);
                    if (srcPlayer.find()) {
                        int seat = Integer.parseInt(srcPlayer.group(1)) - 1;
                        if (seat >= 0 && seat < decks.size()) {
                            result.playerResults.get(seat).commanderDamageDealt += amount;
                        }
                    }
                }
            }
        }

        System.out.printf("[PARSE-SUMMARY] Game %d: total lines=%d%n", gameIndex, lines.length);
        for (int seat = 0; seat < result.playerResults.size(); seat++) {
            PlayerResult pr = result.playerResults.get(seat);
            System.out.printf("[PARSE] Game %d Seat %d: spells=%d, lands=%d, cmdrCasts=%d, cmdrDmg=%d, life=%d%n",
                    gameIndex, seat, pr.spellsCast, pr.landsPlayed, pr.commanderCasts, pr.commanderDamageDealt, pr.finalLife);
        }

        if (!quiet) {
            try {
                buildPerCardStats(result, lines);
            } catch (Exception e) {
                System.err.println("[COACH] Per-card stat tracking failed: " + e.getMessage());
            }
        }

        if (mlLoggingEnabled && !quiet && mlDecisionLogger != null) {
            try {
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

                Map<Integer, Map<String, String>> deckMeta = new HashMap<>();
                for (int di = 0; di < numPlayers; di++) {
                    Map<String, String> meta = new HashMap<>();
                    meta.put("name", decks.get(di).deckName);
                    meta.put("commander", decks.get(di).commanderName);
                    meta.put("archetype", decks.get(di).archetype != null ? decks.get(di).archetype : "midrange");
                    deckMeta.put(di, meta);
                }

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
            }
        }

        return result;
    }

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

    public interface ProgressCallback {
        void onProgress(int completed, int total, int percentDone,
                        double simsPerSec, GameResult lastResult);
    }

    private List<String> readDeckCardNames(String deckFilePath) {
        List<String> names = new ArrayList<>();
        try {
            Path path = resolveExistingDeckPath(deckFilePath);
            if (path == null) {
                System.err.println("[COACH] Deck file not found: " + deckFilePath);
                return names;
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
                if (section.equalsIgnoreCase("Sideboard")) continue;

                Matcher m = cardLine.matcher(line);
                if (m.matches()) {
                    String cardName = m.group(2).trim();
                    int qty = Integer.parseInt(m.group(1));
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
     * Resolve a deck file name/path to an existing Path on disk.
     * Uses the same priority as resolveFullDeckPath but returns null if not found.
     */
    private Path resolveExistingDeckPath(String deckFile) {
        String name = deckFile.endsWith(".dck") ? deckFile : deckFile + ".dck";

        // 1. Already absolute
        Path absolute = Path.of(name);
        if (absolute.isAbsolute() && Files.exists(absolute)) return absolute;

        // 2. PRECON_DECKS_DIR env var
        String envDir = System.getenv("PRECON_DECKS_DIR");
        if (envDir != null && !envDir.isBlank()) {
            Path candidate = Path.of(envDir, name);
            if (Files.exists(candidate)) return candidate;
        }

        // 3. Hardcoded default
        Path defaultCandidate = Path.of(DEFAULT_PRECON_DIR, name);
        if (Files.exists(defaultCandidate)) return defaultCandidate;

        // 4. Legacy %APPDATA%\Forge\decks\commander
        String appdata = System.getenv("APPDATA");
        if (appdata != null) {
            Path legacyCandidate = Path.of(appdata, "Forge", "decks", "commander", name);
            if (Files.exists(legacyCandidate)) return legacyCandidate;
        }

        return null;
    }

    /**
     * @deprecated Use resolveExistingDeckPath instead.
     */
    private Path resolveForgeDecksPath(String deckName) {
        return resolveExistingDeckPath(deckName);
    }

    private void buildPerCardStats(GameResult result, String[] lines) {
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

        int globalTurn = 0;
        boolean[] openingHandPhase = new boolean[decks.size()];
        java.util.Arrays.fill(openingHandPhase, true);

        for (String rawLine : lines) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;

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

            Matcher drawMatch = DRAW_PATTERN.matcher(line);
            if (drawMatch.find()) {
                int seat = Integer.parseInt(drawMatch.group(1)) - 1;
                String cardName = drawMatch.group(2).trim();
                if (seat >= 0 && seat < decks.size() && seatCards[seat] != null) {
                    PerCardGameStats stats = seatCards[seat].get(cardName);
                    if (stats == null) {
                        stats = new PerCardGameStats(cardName);
                        seatCards[seat].put(cardName, stats);
                    }
                    if (!stats.drawn) {
                        stats.drawn = true;
                        stats.turnDrawn = globalTurn;
                    }
                    if (openingHandPhase[seat]) {
                        stats.inOpeningHand = true;
                        stats.keptInOpeningHand = true;
                    }
                }
                continue;
            }

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
                    if (!stats.drawn) {
                        stats.drawn = true;
                        stats.turnDrawn = globalTurn;
                    }
                }
                continue;
            }

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
                        stats.cast = true;
                        stats.turnCast = globalTurn;
                    }
                    if (!stats.drawn) {
                        stats.drawn = true;
                        stats.turnDrawn = globalTurn;
                    }
                }
                continue;
            }

            Matcher cardDmgMatch = CARD_DAMAGE_PATTERN.matcher(line);
            if (cardDmgMatch.find()) {
                String cardName = cardDmgMatch.group(1).trim();
                int amount = Integer.parseInt(cardDmgMatch.group(2));
                for (int s = 0; s < decks.size(); s++) {
                    if (seatCards[s] != null && seatCards[s].containsKey(cardName)) {
                        seatCards[s].get(cardName).damageDealt += amount;
                        break;
                    }
                }
            }
        }

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

    private String readCommanderCardName(String deckFilePath) {
        try {
            Path path = resolveExistingDeckPath(deckFilePath);
            if (path == null) return null;

            List<String> lines = Files.readAllLines(path);
            boolean inCommanderSection = false;
            Pattern cardLine = Pattern.compile("^(\\d+)\\s+(.+?)(?:\\|(.+))?$");
            for (String line : lines) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("//")) continue;
                if (line.startsWith("[") && line.endsWith("]")) {
                    inCommanderSection = line.equalsIgnoreCase("[Commander]");
                    continue;
                }
                if (line.startsWith("Name=")) continue;
                if (inCommanderSection) {
                    Matcher m = cardLine.matcher(line);
                    if (m.matches()) {
                        return m.group(2).trim();
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("[CMDR] Failed to read commander from .dck: " + deckFilePath + " - " + e.getMessage());
        }
        return null;
    }
}
