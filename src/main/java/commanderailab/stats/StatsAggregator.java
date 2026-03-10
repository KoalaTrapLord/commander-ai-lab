package commanderailab.stats;

import commanderailab.schema.BatchResult;
import commanderailab.schema.BatchResult.*;

import java.util.*;

/**
 * StatsAggregator — Computes summary statistics from a list of GameResults.
 *
 * Thread-safe: call mergeStats() to combine results from multiple workers.
 */
public class StatsAggregator {

    /**
     * Compute summary from completed games.
     */
    public static Summary computeSummary(List<GameResult> games, List<DeckInfo> decks, long totalElapsedMs) {
        Summary summary = new Summary();
        summary.perDeck = new ArrayList<>();

        int podSize = decks.size();

        // Initialize per-deck accumulators
        int[] wins = new int[podSize];
        int[] losses = new int[podSize];
        int[] draws = new int[podSize];
        long[] totalTurnsOnWin = new long[podSize];
        long[] totalMulligans = new long[podSize];
        long[] totalFinalLife = new long[podSize];
        int[] gameCount = new int[podSize];
        WinConditionBreakdown[] breakdowns = new WinConditionBreakdown[podSize];
        for (int i = 0; i < podSize; i++) {
            breakdowns[i] = new WinConditionBreakdown();
        }

        long totalTurnsAllGames = 0;
        long totalGameTimeMs = 0;

        for (GameResult game : games) {
            totalTurnsAllGames += game.totalTurns;
            totalGameTimeMs += game.elapsedMs;

            for (PlayerResult pr : game.playerResults) {
                int seat = pr.seatIndex;
                gameCount[seat]++;
                totalMulligans[seat] += pr.mulligans;
                totalFinalLife[seat] += pr.finalLife;

                if (pr.isWinner) {
                    wins[seat]++;
                    totalTurnsOnWin[seat] += game.totalTurns;
                    breakdowns[seat].increment(game.winCondition);
                } else if (game.winningSeat == null) {
                    draws[seat]++;
                } else {
                    losses[seat]++;
                }
            }
        }

        int completedGames = games.size();

        for (int i = 0; i < podSize; i++) {
            DeckSummary ds = new DeckSummary();
            ds.seatIndex = i;
            ds.deckName = decks.get(i).deckName;
            ds.wins = wins[i];
            ds.losses = losses[i];
            ds.draws = draws[i];
            ds.winRate = completedGames > 0 ? (double) wins[i] / completedGames : 0.0;
            ds.avgTurnsToWin = wins[i] > 0 ? (double) totalTurnsOnWin[i] / wins[i] : null;
            ds.avgMulligans = gameCount[i] > 0 ? (double) totalMulligans[i] / gameCount[i] : 0.0;
            ds.avgFinalLife = gameCount[i] > 0 ? (double) totalFinalLife[i] / gameCount[i] : 0.0;
            ds.winConditionBreakdown = breakdowns[i];
            summary.perDeck.add(ds);
        }

        summary.avgGameTurns = completedGames > 0 ? (double) totalTurnsAllGames / completedGames : 0.0;
        summary.avgGameTimeMs = completedGames > 0 ? (double) totalGameTimeMs / completedGames : 0.0;
        summary.simsPerSecond = totalElapsedMs > 0 ? (double) completedGames / (totalElapsedMs / 1000.0) : 0.0;

        return summary;
    }

    /**
     * Merge game results from multiple worker threads into a single list.
     * Thread-safe: each worker produces its own list; this combines them.
     */
    public static List<GameResult> mergeStats(List<List<GameResult>> workerResults) {
        List<GameResult> merged = new ArrayList<>();
        for (List<GameResult> batch : workerResults) {
            merged.addAll(batch);
        }
        // Re-index games sequentially
        for (int i = 0; i < merged.size(); i++) {
            merged.get(i).gameIndex = i;
        }
        return merged;
    }
}
