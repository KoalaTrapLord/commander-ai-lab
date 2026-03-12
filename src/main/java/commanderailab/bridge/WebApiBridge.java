package commanderailab.bridge;

import commanderailab.schema.BatchResult;
import commanderailab.schema.BatchResult.*;
import commanderailab.schema.JsonExporter;
import commanderailab.stats.StatsAggregator;
import commanderailab.ai.AiPolicy;
import commanderailab.ai.ForgeBuiltinPolicy;
import commanderailab.batch.BatchRunner;
import commanderailab.batch.MultiThreadBatchRunner;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.time.Instant;
import java.util.*;

/**
 * WebApiBridge — HTTP/WebSocket API layer for the web UI.
 *
 * This class provides methods that can be called from a web server
 * (e.g., Javalin, Spring, or the existing Python FastAPI server)
 * to trigger batch runs and retrieve results.
 */
public class WebApiBridge {

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    private final String forgeJarPath;
    private final String forgeWorkDir;
    private volatile BatchResult lastResult;
    private volatile boolean isRunning;
    private volatile int progress;
    private volatile double currentSimsPerSec;
    private String policyServerUrl = "http://localhost:8080";

    // Issue #4/#5: Performance settings
    private boolean aiSimplified = false;
    private int aiThinkTimeMs = -1;
    private int maxQueueDepth = -1;

    public WebApiBridge(String forgeJarPath, String forgeWorkDir) {
        this.forgeJarPath = forgeJarPath;
        this.forgeWorkDir = forgeWorkDir;
        this.isRunning = false;
        this.progress = 0;
        this.currentSimsPerSec = 0.0;
    }

    /**
     * Configure AI optimization settings (Issue #4).
     */
    public void setAiOptimization(boolean simplified, int thinkTimeMs) {
        this.aiSimplified = simplified;
        this.aiThinkTimeMs = thinkTimeMs;
    }

    /**
     * Set max concurrent Forge processes for backpressure (Issue #5).
     */
    public void setMaxQueueDepth(int maxDepth) {
        this.maxQueueDepth = maxDepth;
    }

    /**
     * Start a batch run (backward-compatible, Forge AI only).
     */
    public String startBatchAsync(String deck1, String deck2, String deck3,
                                   int numGames, int threads, Long seed) {
        return startBatchAsync(deck1, deck2, deck3, numGames, threads, seed, false, "midrange");
    }

    /**
     * Start a batch with learned policy support.
     *
     * @param useLearnedPolicy If true, attempts to use the trained neural network policy
     * @param policyStyle Playstyle for the learned policy ("aggro", "control", "midrange", "combo")
     */
    public String startBatchAsync(String deck1, String deck2, String deck3,
                                   int numGames, int threads, Long seed,
                                   boolean useLearnedPolicy, String policyStyle) {
        String batchId = UUID.randomUUID().toString();

        Thread batchThread = new Thread(() -> {
            try {
                isRunning = true;
                progress = 0;

                List<DeckInfo> decks = buildDecks(deck1, deck2, deck3);
                AiPolicy policy;

                if (useLearnedPolicy) {
                    commanderailab.ml.LearnedPolicy learned =
                        new commanderailab.ml.LearnedPolicy(
                            policyServerUrl,
                            policyStyle != null ? policyStyle : "midrange",
                            true
                        );
                    if (learned.connect()) {
                        policy = learned;
                        System.out.println("[ML] Using learned policy for batch " + batchId);
                    } else {
                        System.out.println("[ML] Learned policy unavailable, using Forge AI");
                        policy = new ForgeBuiltinPolicy();
                    }
                } else {
                    policy = new ForgeBuiltinPolicy();
                }

                long startTime = System.currentTimeMillis();
                List<GameResult> games;

                if (threads > 1) {
                    MultiThreadBatchRunner runner = new MultiThreadBatchRunner(
                            forgeJarPath, forgeWorkDir, decks, policy, threads);
                    runner.setAiOptimization(aiSimplified, aiThinkTimeMs);
                    if (maxQueueDepth > 0) runner.setMaxQueueDepth(maxQueueDepth);
                    // Issue #5: Progress callback for real-time sims/sec
                    runner.setProgressCallback((completed, total, pct, simsPerSec, lastResult) -> {
                        progress = pct;
                        currentSimsPerSec = simsPerSec;
                    });
                    games = runner.runBatch(numGames, seed);
                } else {
                    BatchRunner runner = new BatchRunner(
                            forgeJarPath, forgeWorkDir, decks, policy);
                    runner.setAiOptimization(aiSimplified, aiThinkTimeMs);
                    // Issue #5: Progress callback
                    runner.setProgressCallback((completed, total, pct, simsPerSec, lastResult) -> {
                        progress = pct;
                        currentSimsPerSec = simsPerSec;
                    });
                    games = runner.runBatchSingleThread(numGames, seed);
                }

                long elapsed = System.currentTimeMillis() - startTime;
                Summary summary = StatsAggregator.computeSummary(games, decks, elapsed);

                BatchResult result = new BatchResult();
                result.metadata = new Metadata();
                result.metadata.batchId = batchId;
                result.metadata.timestamp = Instant.now().toString();
                result.metadata.totalGames = numGames;
                result.metadata.completedGames = games.size();
                result.metadata.engineVersion = "forge-2.0.12-SNAPSHOT";
                result.metadata.masterSeed = seed;
                result.metadata.threads = threads;
                result.metadata.elapsedMs = elapsed;
                result.decks = decks;
                result.games = games;
                result.summary = summary;

                lastResult = result;
                progress = 100;

            } catch (Exception e) {
                System.err.println("Batch run failed: " + e.getMessage());
                e.printStackTrace();
            } finally {
                isRunning = false;
            }
        }, "batch-runner-" + batchId);

        batchThread.setDaemon(true);
        batchThread.start();

        return batchId;
    }

    public int getProgress() { return progress; }
    public boolean isRunning() { return isRunning; }
    public double getCurrentSimsPerSec() { return currentSimsPerSec; }

    public String getLastResultJson() {
        if (lastResult == null) return "{}";
        return JsonExporter.toJson(lastResult);
    }

    public BatchResult getLastResult() { return lastResult; }

    private List<DeckInfo> buildDecks(String... deckNames) {
        List<DeckInfo> decks = new ArrayList<>();
        for (int i = 0; i < deckNames.length; i++) {
            DeckInfo d = new DeckInfo();
            d.seatIndex = i;
            d.deckFile = deckNames[i];
            d.deckName = deckNames[i].replace(".dck", "");
            d.commanderName = d.deckName;
            d.colorIdentity = List.of();
            d.cardCount = 100;
            decks.add(d);
        }
        return decks;
    }
}
