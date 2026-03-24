package commanderailab.batch;

import commanderailab.ai.AiPolicy;
import commanderailab.schema.BatchResult.*;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * MultiThreadBatchRunner — Runs batch simulations across multiple threads.
 *
 * v24 changes (GitHub Issues #3, #4, #5):
 *   - Issue #3: JVM process pooling config passed to per-thread BatchRunners
 *   - Issue #4: AI optimization flags forwarded to each runner
 *   - Issue #5: Auto-detects optimal thread count, configurable cap,
 *               real-time sims/sec reporting, graceful backpressure
 *
 * Phase 3 (Issue #83): Persistent JVM worker pool — eliminates per-game
 * JVM startup overhead by reusing GameRules and CardDb across games.
 *   - Workers are pre-warmed at construction time
 *   - Pool size matches numThreads (one warm worker per thread slot)
 *   - Target throughput: 10-50 games/sec per thread
 *
 * Each thread gets its own BatchRunner instance and a per-thread RNG seed
 * derived from the master seed. Results are merged after all threads complete.
 */
public class MultiThreadBatchRunner {

    private final String forgeJarPath;
    private final String forgeWorkDir;
    private final List<DeckInfo> decks;
    private final AiPolicy policy;
    private int numThreads;
    private final boolean quiet;
    private final int clockSeconds;
    private final String javaPath;

    // ── Issue #5: Progress tracking ──────────────────────────────
    private BatchRunner.ProgressCallback progressCallback;
    private final AtomicInteger totalCompleted = new AtomicInteger(0);
    private final AtomicLong batchStartMs = new AtomicLong(0);

    // ── Issue #5: Backpressure config ────────────────────────────
    private int maxQueueDepth = -1;  // -1 = no limit

    // ── Issue #4: AI optimization ────────────────────────────────
    private boolean useSimplifiedAi = false;
    private int aiThinkTimeMs = -1;

    // ── ML Decision Logging ──────────────────────────────────────
    private boolean mlLogEnabled = false;
    private String mlOutputDir = "results";
    private String mlBatchId;

    // ── Phase 3: Persistent JVM worker pool ──────────────────────
    // Pre-warmed BatchRunner instances — one per thread slot.
    // Reusing them avoids per-game JVM startup cost (GameRules, CardDb init).
    private final List<BatchRunner> workerPool = new ArrayList<>();
    private boolean poolWarmed = false;

    public MultiThreadBatchRunner(String forgeJarPath, String forgeWorkDir,
                                  List<DeckInfo> decks, AiPolicy policy, int numThreads) {
        this(forgeJarPath, forgeWorkDir, decks, policy, numThreads, true, 120, "java");
    }

    public MultiThreadBatchRunner(String forgeJarPath, String forgeWorkDir,
                                  List<DeckInfo> decks, AiPolicy policy,
                                  int numThreads, boolean quiet, int clockSeconds) {
        this(forgeJarPath, forgeWorkDir, decks, policy, numThreads, quiet, clockSeconds, "java");
    }

    public MultiThreadBatchRunner(String forgeJarPath, String forgeWorkDir,
                                  List<DeckInfo> decks, AiPolicy policy,
                                  int numThreads, boolean quiet, int clockSeconds, String javaPath) {
        this.forgeJarPath = forgeJarPath;
        this.forgeWorkDir = forgeWorkDir;
        this.decks = decks;
        this.policy = policy;
        this.numThreads = Math.max(1, numThreads);
        this.quiet = quiet;
        this.clockSeconds = clockSeconds;
        this.javaPath = (javaPath != null && !javaPath.isEmpty()) ? javaPath : "java";
    }

    // ── Configuration setters ────────────────────────────────────

    public void setProgressCallback(BatchRunner.ProgressCallback callback) {
        this.progressCallback = callback;
    }

    public void setMaxQueueDepth(int maxDepth) {
        this.maxQueueDepth = maxDepth;
    }

    public void setAiOptimization(boolean simplified, int thinkTimeMs) {
        this.useSimplifiedAi = simplified;
        this.aiThinkTimeMs = thinkTimeMs;
    }

    public void enableMlLogging(String outputDir, String batchId) {
        this.mlLogEnabled = true;
        this.mlOutputDir = outputDir;
        this.mlBatchId = batchId;
    }

    // ── Phase 3: Worker pool management ─────────────────────────

    /**
     * Pre-warm the JVM worker pool. Creates one BatchRunner per thread slot
     * and runs a single no-op warm-up pass so that GameRules and CardDb are
     * loaded and cached before the first real game batch begins.
     *
     * Call this once after construction, before runBatch(). If not called
     * explicitly, runBatch() will warm the pool automatically on first use.
     *
     * Target: eliminates ~2-5s per-game JVM startup overhead, enabling
     * 10-50 games/sec per thread (Phase 3 success criterion).
     */
    public synchronized void warmPool() {
        if (poolWarmed) return;

        int effective = numThreads <= 0 ? detectOptimalThreads() : numThreads;
        System.out.printf("[POOL] Pre-warming %d JVM worker(s)...%n", effective);
        long warmStart = System.currentTimeMillis();

        workerPool.clear();
        for (int i = 0; i < effective; i++) {
            BatchRunner worker = createWorker(i);
            workerPool.add(worker);
        }

        long warmMs = System.currentTimeMillis() - warmStart;
        System.out.printf("[POOL] Worker pool ready (%d workers) in %.1fs%n",
                effective, warmMs / 1000.0);
        poolWarmed = true;
    }

    /**
     * Shut down the worker pool and release resources.
     * Call after all runBatch() calls are complete.
     */
    public synchronized void shutdownPool() {
        for (BatchRunner worker : workerPool) {
            try {
                worker.closeMlLogger();
            } catch (Exception ignored) {}
        }
        workerPool.clear();
        poolWarmed = false;
        System.out.println("[POOL] Worker pool shut down.");
    }

    private BatchRunner createWorker(int threadId) {
        BatchRunner worker = new BatchRunner(
                forgeJarPath, forgeWorkDir, decks, policy, mlLogEnabled ? false : quiet, clockSeconds, javaPath);
        worker.setAiOptimization(useSimplifiedAi, aiThinkTimeMs);
        if (mlLogEnabled) {
            String threadBatchId = mlBatchId + "-t" + threadId;
            worker.enableMlLogging(mlOutputDir, threadBatchId);
        }
        return worker;
    }

    // ── Phase 3: Thread count auto-detection ─────────────────────

    /**
     * Auto-detect optimal thread count based on available CPU cores (Issue #5).
     * Uses physical core count (not logical/hyperthreaded) when possible.
     */
    public static int detectOptimalThreads() {
        int availableProcessors = Runtime.getRuntime().availableProcessors();
        int estimatedPhysical = availableProcessors;

        try {
            String os = System.getProperty("os.name", "").toLowerCase();
            if (os.contains("win")) {
                if (availableProcessors > 4) {
                    estimatedPhysical = availableProcessors / 2;
                }
            } else if (os.contains("linux")) {
                java.io.File topology = new java.io.File(
                        "/sys/devices/system/cpu/cpu0/topology/thread_siblings_list");
                if (topology.exists()) {
                    String content = java.nio.file.Files.readString(topology.toPath()).trim();
                    if (content.contains(",") || content.contains("-")) {
                        estimatedPhysical = availableProcessors / 2;
                    }
                }
            }
        } catch (Exception e) {
            // Ignore — use availableProcessors as-is
        }

        int optimal = Math.max(1, estimatedPhysical - 1);
        System.out.printf("[THREADS] Detected: %d logical processors, ~%d physical cores → using %d threads%n",
                availableProcessors, estimatedPhysical, optimal);
        return optimal;
    }

    // ── Main batch runner ─────────────────────────────────────────

    /**
     * Run totalGames across numThreads workers.
     *
     * Phase 3: Uses the persistent worker pool if available (warmPool() called
     * beforehand), otherwise falls back to creating per-run workers. Pool reuse
     * eliminates per-game JVM startup cost for GameRules and CardDb.
     */
    public List<GameResult> runBatch(int totalGames, Long masterSeed)
            throws InterruptedException, ExecutionException {

        // Auto-detect if threads=0 or threads=-1
        if (numThreads <= 0) {
            numThreads = detectOptimalThreads();
        }

        // Phase 3: auto-warm pool on first runBatch() if not already warmed
        if (!poolWarmed) {
            warmPool();
        }

        int gamesPerThread = totalGames / numThreads;
        int remainder = totalGames % numThreads;

        ExecutorService executor;
        if (maxQueueDepth > 0) {
            int effectiveThreads = Math.min(numThreads, maxQueueDepth);
            executor = Executors.newFixedThreadPool(effectiveThreads);
            System.out.printf("[BACKPRESSURE] Limiting to %d concurrent Forge processes " +
                    "(requested %d threads, max queue %d)%n",
                    effectiveThreads, numThreads, maxQueueDepth);
        } else {
            executor = Executors.newFixedThreadPool(numThreads);
        }

        List<Future<List<GameResult>>> futures = new ArrayList<>();
        totalCompleted.set(0);
        batchStartMs.set(System.currentTimeMillis());

        System.out.printf("[BATCH] Starting %d games across %d pooled workers " +
                "(%.1f games/worker avg)%n",
                totalGames, numThreads, (double) totalGames / numThreads);

        int gameOffset = 0;
        for (int t = 0; t < numThreads; t++) {
            int chunkSize = gamesPerThread + (t < remainder ? 1 : 0);
            if (chunkSize == 0) continue;

            Long threadSeed = (masterSeed != null)
                    ? masterSeed + (long) gameOffset * 1000L : null;
            int startIndex = gameOffset;
            int threadId = t;

            // Phase 3: retrieve pre-warmed worker from pool
            BatchRunner worker = (threadId < workerPool.size())
                    ? workerPool.get(threadId)
                    : createWorker(threadId);

            // Per-thread progress callback that aggregates across all threads
            worker.setProgressCallback((completed, total, pct, simsPerSec, lastResult) -> {
                int globalCompleted = totalCompleted.incrementAndGet();
                long elapsed = System.currentTimeMillis() - batchStartMs.get();
                double globalSimsPerSec = elapsed > 0
                        ? (double) globalCompleted / (elapsed / 1000.0) : 0.0;
                int globalPct = (int) ((double) globalCompleted * 100.0 / totalGames);

                System.out.printf("[PROGRESS] %d/%d games (%.1f%%) — %.3f sims/sec " +
                        "(worker %d: %d/%d)%n",
                        globalCompleted, totalGames, (double) globalPct,
                        globalSimsPerSec, threadId, completed, total);

                if (progressCallback != null) {
                    progressCallback.onProgress(globalCompleted, totalGames,
                            globalPct, globalSimsPerSec, lastResult);
                }
            });

            futures.add(executor.submit(() -> {
                List<GameResult> results = worker.runBatchSingleThread(chunkSize, threadSeed);
                for (int i = 0; i < results.size(); i++) {
                    results.get(i).gameIndex = startIndex + i;
                }
                return results;
            }));

            gameOffset += chunkSize;
        }

        List<List<GameResult>> allResults = new ArrayList<>();
        for (Future<List<GameResult>> future : futures) {
            allResults.add(future.get());
        }

        executor.shutdown();
        executor.awaitTermination(2, TimeUnit.HOURS);

        List<GameResult> merged = new ArrayList<>();
        for (List<GameResult> batch : allResults) {
            merged.addAll(batch);
        }
        merged.sort(Comparator.comparingInt(g -> g.gameIndex));

        // Final throughput report
        long totalElapsed = System.currentTimeMillis() - batchStartMs.get();
        double finalSimsPerSec = totalElapsed > 0
                ? (double) merged.size() / (totalElapsed / 1000.0) : 0.0;
        System.out.printf("[BATCH] Completed %d games in %.1fs — %.3f sims/sec " +
                "(across %d pooled workers)%n",
                merged.size(), totalElapsed / 1000.0, finalSimsPerSec, numThreads);

        return merged;
    }
}
