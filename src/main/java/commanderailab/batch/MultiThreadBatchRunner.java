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

    /**
     * Set progress callback for real-time reporting (Issue #5).
     */
    public void setProgressCallback(BatchRunner.ProgressCallback callback) {
        this.progressCallback = callback;
    }

    /**
     * Set max subprocess queue depth for backpressure (Issue #5).
     * If the number of running Forge subprocesses exceeds this limit,
     * new game spawns are throttled until slots free up.
     *
     * @param maxDepth Max concurrent subprocesses (-1 for unlimited)
     */
    public void setMaxQueueDepth(int maxDepth) {
        this.maxQueueDepth = maxDepth;
    }

    /**
     * Configure AI optimization flags (Issue #4).
     */
    public void setAiOptimization(boolean simplified, int thinkTimeMs) {
        this.useSimplifiedAi = simplified;
        this.aiThinkTimeMs = thinkTimeMs;
    }

    /**
     * Auto-detect optimal thread count based on available CPU cores (Issue #5).
     *
     * Uses physical core count (not logical/hyperthreaded) when possible.
     * Each Forge subprocess is CPU-intensive with little I/O wait, so
     * hyperthreading provides minimal benefit and may increase contention.
     *
     * @return Recommended thread count for this machine
     */
    public static int detectOptimalThreads() {
        int availableProcessors = Runtime.getRuntime().availableProcessors();

        // On most systems, availableProcessors includes hyperthreads.
        // For CPU-bound Forge sims, physical cores are what matter.
        // Heuristic: assume HT gives 2x logical cores on Intel/AMD
        int estimatedPhysical = availableProcessors;

        // Try to detect if hyperthreading is active
        // On Windows, we can check if logical > physical
        try {
            String os = System.getProperty("os.name", "").toLowerCase();
            if (os.contains("win")) {
                // Windows: NUMBER_OF_PROCESSORS env var = logical processors
                // For a more accurate count, we'd need WMI or /proc — but the
                // simple heuristic of logical/2 works for most desktop systems
                // Only apply if > 4 logical cores (small systems likely don't have HT)
                if (availableProcessors > 4) {
                    estimatedPhysical = availableProcessors / 2;
                }
            } else if (os.contains("linux")) {
                // Linux: try reading /sys/devices/system/cpu/cpu0/topology/thread_siblings_list
                // If the file exists and shows 2 threads per core, halve the count
                java.io.File topology = new java.io.File("/sys/devices/system/cpu/cpu0/topology/thread_siblings_list");
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

        // Reserve 1 core for the OS/JVM overhead, minimum 1 worker
        int optimal = Math.max(1, estimatedPhysical - 1);

        System.out.printf("[THREADS] Detected: %d logical processors, ~%d physical cores → using %d threads%n",
                availableProcessors, estimatedPhysical, optimal);

        return optimal;
    }

    /**
     * Run totalGames across numThreads workers.
     *
     * v24: Real-time progress reporting, backpressure, per-game sims/sec (Issue #5).
     */
    public List<GameResult> runBatch(int totalGames, Long masterSeed) throws InterruptedException, ExecutionException {
        // Issue #5: Auto-detect if threads=0 or threads=-1 (auto mode)
        if (numThreads <= 0) {
            numThreads = detectOptimalThreads();
        }

        int gamesPerThread = totalGames / numThreads;
        int remainder = totalGames % numThreads;

        // Issue #5: Backpressure — limit concurrent subprocesses if configured
        ExecutorService executor;
        if (maxQueueDepth > 0) {
            // Use a bounded thread pool to prevent RAM exhaustion from too many Forge JVMs
            int effectiveThreads = Math.min(numThreads, maxQueueDepth);
            executor = Executors.newFixedThreadPool(effectiveThreads);
            System.out.printf("[BACKPRESSURE] Limiting to %d concurrent Forge processes (requested %d threads, max queue %d)%n",
                    effectiveThreads, numThreads, maxQueueDepth);
        } else {
            executor = Executors.newFixedThreadPool(numThreads);
        }

        List<Future<List<GameResult>>> futures = new ArrayList<>();

        totalCompleted.set(0);
        batchStartMs.set(System.currentTimeMillis());

        System.out.printf("[BATCH] Starting %d games across %d threads (%.1f games/thread avg)%n",
                totalGames, numThreads, (double) totalGames / numThreads);

        int gameOffset = 0;
        for (int t = 0; t < numThreads; t++) {
            int chunkSize = gamesPerThread + (t < remainder ? 1 : 0);
            if (chunkSize == 0) continue;

            Long threadSeed = (masterSeed != null) ? masterSeed + (long) gameOffset * 1000L : null;
            int startIndex = gameOffset;
            int threadId = t;

            BatchRunner runner = new BatchRunner(forgeJarPath, forgeWorkDir, decks, policy, quiet, clockSeconds, javaPath);

            // Issue #4: Forward AI optimization settings
            runner.setAiOptimization(useSimplifiedAi, aiThinkTimeMs);

            // Issue #5: Per-thread progress callback that aggregates across all threads
            runner.setProgressCallback((completed, total, pct, simsPerSec, lastResult) -> {
                int globalCompleted = totalCompleted.incrementAndGet();
                long elapsed = System.currentTimeMillis() - batchStartMs.get();
                double globalSimsPerSec = elapsed > 0
                        ? (double) globalCompleted / (elapsed / 1000.0)
                        : 0.0;
                int globalPct = (int) ((double) globalCompleted * 100.0 / totalGames);

                System.out.printf("[PROGRESS] %d/%d games (%.1f%%) — %.3f sims/sec (thread %d: %d/%d)%n",
                        globalCompleted, totalGames, (double) globalPct,
                        globalSimsPerSec, threadId, completed, total);

                // Forward to external callback if set
                if (progressCallback != null) {
                    progressCallback.onProgress(globalCompleted, totalGames, globalPct, globalSimsPerSec, lastResult);
                }
            });

            futures.add(executor.submit(() -> {
                List<GameResult> results = runner.runBatchSingleThread(chunkSize, threadSeed);
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
        double finalSimsPerSec = totalElapsed > 0 ? (double) merged.size() / (totalElapsed / 1000.0) : 0.0;
        System.out.printf("[BATCH] Completed %d games in %.1fs — %.3f sims/sec (across %d threads)%n",
                merged.size(), totalElapsed / 1000.0, finalSimsPerSec, numThreads);

        return merged;
    }
}
