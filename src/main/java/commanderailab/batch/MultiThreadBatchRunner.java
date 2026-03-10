package commanderailab.batch;

import commanderailab.ai.AiPolicy;
import commanderailab.schema.BatchResult.*;

import java.util.*;
import java.util.concurrent.*;

/**
 * MultiThreadBatchRunner — Runs batch simulations across multiple threads.
 *
 * Each thread gets its own BatchRunner instance and a per-thread RNG seed
 * derived from the master seed. Results are merged after all threads complete.
 */
public class MultiThreadBatchRunner {

    private final String forgeJarPath;
    private final String forgeWorkDir;
    private final List<DeckInfo> decks;
    private final AiPolicy policy;
    private final int numThreads;
    private final boolean quiet;
    private final int clockSeconds;
    private final String javaPath;

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
     * Run totalGames across numThreads workers.
     */
    public List<GameResult> runBatch(int totalGames, Long masterSeed) throws InterruptedException, ExecutionException {
        int gamesPerThread = totalGames / numThreads;
        int remainder = totalGames % numThreads;

        ExecutorService executor = Executors.newFixedThreadPool(numThreads);
        List<Future<List<GameResult>>> futures = new ArrayList<>();

        int gameOffset = 0;
        for (int t = 0; t < numThreads; t++) {
            int chunkSize = gamesPerThread + (t < remainder ? 1 : 0);
            Long threadSeed = (masterSeed != null) ? masterSeed + (long) gameOffset * 1000L : null;
            int startIndex = gameOffset;

            BatchRunner runner = new BatchRunner(forgeJarPath, forgeWorkDir, decks, policy, quiet, clockSeconds, javaPath);

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

        return merged;
    }
}
