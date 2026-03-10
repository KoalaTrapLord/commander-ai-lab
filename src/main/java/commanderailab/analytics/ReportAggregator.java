package commanderailab.analytics;

import commanderailab.schema.BatchResult;
import commanderailab.schema.BatchResult.*;
import commanderailab.schema.DeckReport;
import commanderailab.schema.DeckReport.*;
import commanderailab.schema.PerCardGameStats;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.*;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import java.util.stream.Collectors;

/**
 * ReportAggregator — Transforms raw BatchResult data into DeckReport objects.
 *
 * Reads batch result JSON files and computes:
 *   - Deck-level stats: win rate, avg game length, matchup records
 *   - Per-card stats: drawn/cast rates, impact scores, synergy scores
 *   - Underperformer/overperformer identification
 *   - Deck structure analysis
 *
 * Output: writes deck-reports/{deckId}.json to disk.
 */
public class ReportAggregator {

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    // Threshold for identifying underperformers (impactScore below this)
    private static final double UNDERPERFORMER_THRESHOLD = -0.05;
    private static final int MAX_UNDERPERFORMERS = 8;
    private static final int MAX_OVERPERFORMERS = 8;

    /**
     * Generate a DeckReport for a specific deck from multiple batch results.
     *
     * @param deckId       Unique deck identifier (typically deck name)
     * @param deckSeat     The seat index this deck occupied
     * @param batchResults List of batch results to aggregate
     * @return Complete DeckReport
     */
    public DeckReport generateDeckReport(String deckId, int deckSeat,
                                          List<BatchResult> batchResults) {
        DeckReport report = new DeckReport();
        report.deckId = deckId;
        report.lastUpdated = Instant.now().toString();

        // Collect all games where this deck participated
        int totalGames = 0;
        int totalWins = 0;
        long totalTurns = 0;
        long totalTurnsOnWin = 0;

        // Per-card accumulators
        Map<String, CardPerformance> cardMap = new LinkedHashMap<>();

        // Matchup tracking: opponent deck name -> [games, wins]
        Map<String, int[]> matchupMap = new LinkedHashMap<>();

        // Win condition tracking
        Map<String, Integer> winConditions = new LinkedHashMap<>();

        for (BatchResult batch : batchResults) {
            // Find this deck's info
            DeckInfo deckInfo = null;
            for (DeckInfo di : batch.decks) {
                if (di.seatIndex == deckSeat) {
                    deckInfo = di;
                    break;
                }
            }
            if (deckInfo == null) continue;

            // Set commander/color from first batch
            if (report.commander == null || report.commander.isEmpty()) {
                report.commander = deckInfo.commanderName != null
                        ? deckInfo.commanderName : deckId;
                if (deckInfo.colorIdentity != null) {
                    report.colorIdentity = new ArrayList<>(deckInfo.colorIdentity);
                }
            }

            // Track opponents for matchups
            List<String> opponents = new ArrayList<>();
            for (DeckInfo di : batch.decks) {
                if (di.seatIndex != deckSeat) {
                    opponents.add(di.deckName);
                }
            }

            // Process each game
            for (GameResult game : batch.games) {
                totalGames++;
                totalTurns += game.totalTurns;

                PlayerResult myResult = null;
                for (PlayerResult pr : game.playerResults) {
                    if (pr.seatIndex == deckSeat) {
                        myResult = pr;
                        break;
                    }
                }
                if (myResult == null) continue;

                boolean won = myResult.isWinner;
                if (won) {
                    totalWins++;
                    totalTurnsOnWin += game.totalTurns;
                    if (game.winCondition != null) {
                        winConditions.merge(game.winCondition, 1, Integer::sum);
                    }
                }

                // Track matchups
                for (String opp : opponents) {
                    int[] stats = matchupMap.computeIfAbsent(opp, k -> new int[2]);
                    stats[0]++; // games
                    if (won) stats[1]++; // wins
                }

                // Aggregate per-card stats if available
                if (myResult.cardStats != null) {
                    for (PerCardGameStats pcs : myResult.cardStats) {
                        CardPerformance cp = cardMap.computeIfAbsent(
                                pcs.cardName, name -> {
                                    CardPerformance c = new CardPerformance();
                                    c.name = name;
                                    return c;
                                });

                        cp.gamesSeen++;

                        if (pcs.drawn) {
                            cp.gamesDrawn++;
                            if (pcs.cast) {
                                cp.gamesCast++;
                                cp.gamesWhenCast++;
                                if (won) cp.winsWhenCast++;
                                if (pcs.turnCast >= 0) {
                                    cp.totalTurnCast += pcs.turnCast;
                                }
                            }
                            if (pcs.stuckInHand) {
                                cp.gamesDeadCard++;
                            }
                        }

                        if (pcs.inOpeningHand && pcs.keptInOpeningHand) {
                            cp.gamesKeptInOpening++;
                        }

                        cp.totalDamage += pcs.damageDealt;
                    }
                }
            }
        }

        // ── Compute deck-level stats ──────────────────────────────

        report.meta.gamesSimulated = totalGames;
        report.meta.overallWinRate = totalGames > 0
                ? (double) totalWins / totalGames : 0.0;
        report.meta.avgGameLength = totalGames > 0
                ? (double) totalTurns / totalGames : 0.0;

        // ── Compute matchups ──────────────────────────────────────

        for (Map.Entry<String, int[]> entry : matchupMap.entrySet()) {
            MatchupRecord mr = new MatchupRecord();
            mr.opponentDeck = entry.getKey();
            mr.gamesPlayed = entry.getValue()[0];
            mr.winRate = mr.gamesPlayed > 0
                    ? (double) entry.getValue()[1] / mr.gamesPlayed : 0.0;
            report.matchups.add(mr);
        }

        // ── Compute per-card performance ──────────────────────────

        double overallWinRate = report.meta.overallWinRate;

        for (CardPerformance cp : cardMap.values()) {
            int gs = cp.gamesSeen;
            if (gs == 0) continue;

            cp.drawnRate = (double) cp.gamesDrawn / gs;
            cp.castRate = cp.gamesDrawn > 0
                    ? (double) cp.gamesCast / cp.gamesDrawn : 0.0;
            cp.deadCardRate = cp.gamesDrawn > 0
                    ? (double) cp.gamesDeadCard / cp.gamesDrawn : 0.0;
            cp.keptInOpeningHandRate = gs > 0
                    ? (double) cp.gamesKeptInOpening / gs : 0.0;

            // Impact score: how much does casting this card correlate with winning?
            double winRateWhenCast = cp.gamesWhenCast > 0
                    ? (double) cp.winsWhenCast / cp.gamesWhenCast : 0.0;
            cp.impactScore = (winRateWhenCast - overallWinRate) * cp.castRate;

            // Clunkiness: high dead card rate + low cast rate = clunky
            cp.clunkinessScore = cp.deadCardRate * (1.0 - cp.castRate);

            // Average turn cast
            cp.avgTurnCast = cp.gamesCast > 0
                    ? cp.totalTurnCast / cp.gamesCast : null;

            cp.avgDamageDealt = gs > 0 ? cp.totalDamage / gs : 0.0;

            report.cards.add(cp);
        }

        // ── Identify under/over performers ────────────────────────

        List<CardPerformance> sorted = report.cards.stream()
                .sorted(Comparator.comparingDouble(c -> c.impactScore))
                .collect(Collectors.toList());

        for (int i = 0; i < Math.min(MAX_UNDERPERFORMERS, sorted.size()); i++) {
            CardPerformance cp = sorted.get(i);
            if (cp.impactScore < UNDERPERFORMER_THRESHOLD) {
                report.underperformers.add(cp.name);
            }
        }

        for (int i = sorted.size() - 1;
             i >= Math.max(0, sorted.size() - MAX_OVERPERFORMERS); i--) {
            CardPerformance cp = sorted.get(i);
            if (cp.impactScore > 0) {
                report.overperformers.add(cp.name);
            }
        }

        return report;
    }

    /**
     * Save a DeckReport as JSON to the specified directory.
     */
    public void saveDeckReport(DeckReport report, Path outputDir) throws IOException {
        Files.createDirectories(outputDir);
        Path outFile = outputDir.resolve(report.deckId + ".json");
        try (Writer writer = new FileWriter(outFile.toFile())) {
            GSON.toJson(report, writer);
        }
    }

    /**
     * Load a DeckReport from JSON file.
     */
    public DeckReport loadDeckReport(Path reportFile) throws IOException {
        try (Reader reader = new FileReader(reportFile.toFile())) {
            return GSON.fromJson(reader, DeckReport.class);
        }
    }

    /**
     * Load a BatchResult from JSON file.
     */
    public BatchResult loadBatchResult(Path resultFile) throws IOException {
        try (Reader reader = new FileReader(resultFile.toFile())) {
            return GSON.fromJson(reader, BatchResult.class);
        }
    }

    /**
     * Rebuild all deck reports from a directory of batch result JSONs.
     */
    public List<DeckReport> rebuildAllReports(Path inputLogsDir, Path outputDir)
            throws IOException {
        List<BatchResult> allResults = new ArrayList<>();

        // Load all batch result files
        try (var stream = Files.list(inputLogsDir)) {
            stream.filter(p -> p.toString().endsWith(".json"))
                  .forEach(p -> {
                      try {
                          allResults.add(loadBatchResult(p));
                      } catch (IOException e) {
                          System.err.println("Failed to load: " + p + " - " + e.getMessage());
                      }
                  });
        }

        if (allResults.isEmpty()) {
            System.out.println("No batch result files found in " + inputLogsDir);
            return Collections.emptyList();
        }

        // Find all unique decks across batches
        Map<String, Integer> deckSeats = new LinkedHashMap<>();
        for (BatchResult br : allResults) {
            for (DeckInfo di : br.decks) {
                deckSeats.putIfAbsent(di.deckName, di.seatIndex);
            }
        }

        // Generate report for each deck
        List<DeckReport> reports = new ArrayList<>();
        for (Map.Entry<String, Integer> entry : deckSeats.entrySet()) {
            DeckReport report = generateDeckReport(
                    entry.getKey(), entry.getValue(), allResults);
            saveDeckReport(report, outputDir);
            reports.add(report);
            System.out.printf("Generated report for %s: %d games, %.1f%% win rate%n",
                    report.deckId, report.meta.gamesSimulated,
                    report.meta.overallWinRate * 100);
        }

        return reports;
    }
}
