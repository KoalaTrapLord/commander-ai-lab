package commanderailab.db;

import commanderailab.schema.BatchResult;
import commanderailab.schema.BatchResult.*;
import commanderailab.schema.JsonExporter;
import commanderailab.analytics.DeckAnalyzer.DeckAnalysis;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;

/**
 * LabDatabase — SQLite persistence for Commander AI Lab.
 *
 * Stores:
 *   - Batch run metadata and results (full JSON + indexed columns)
 *   - Per-deck win rate history for trend tracking
 *   - Deck analysis snapshots
 *   - Matchup matrix data (deck A vs B vs C win rates)
 *
 * Schema auto-creates on first use. All operations are thread-safe
 * via synchronized methods (SQLite doesn't handle concurrent writes well).
 */
public class LabDatabase implements AutoCloseable {

    private static final String SCHEMA_VERSION = "2.0.0";
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    private final Connection conn;

    // ══════════════════════════════════════════════════════════
    // Construction & Schema
    // ══════════════════════════════════════════════════════════

    public LabDatabase(String dbPath) throws SQLException {
        this.conn = DriverManager.getConnection("jdbc:sqlite:" + dbPath);
        conn.setAutoCommit(true);
        // Enable WAL for better concurrent read performance
        try (Statement s = conn.createStatement()) {
            s.execute("PRAGMA journal_mode=WAL");
            s.execute("PRAGMA foreign_keys=ON");
        }
        createSchema();
    }

    private void createSchema() throws SQLException {
        try (Statement s = conn.createStatement()) {

            // ── Batch Runs ─────────────────────────────────────
            s.execute("""
                CREATE TABLE IF NOT EXISTS batch_runs (
                    batch_id       TEXT PRIMARY KEY,
                    timestamp      TEXT NOT NULL,
                    total_games    INTEGER NOT NULL,
                    completed_games INTEGER NOT NULL,
                    threads        INTEGER DEFAULT 1,
                    elapsed_ms     INTEGER NOT NULL,
                    master_seed    INTEGER,
                    engine_version TEXT,
                    sims_per_sec   REAL,
                    avg_game_turns REAL,
                    result_json    TEXT NOT NULL,
                    created_at     TEXT DEFAULT (datetime('now'))
                )
            """);

            // ── Per-Deck Results (indexed for queries) ─────────
            s.execute("""
                CREATE TABLE IF NOT EXISTS deck_results (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id       TEXT NOT NULL REFERENCES batch_runs(batch_id),
                    seat_index     INTEGER NOT NULL,
                    deck_name      TEXT NOT NULL,
                    commander_name TEXT,
                    wins           INTEGER NOT NULL,
                    losses         INTEGER NOT NULL,
                    draws          INTEGER NOT NULL,
                    win_rate       REAL NOT NULL,
                    avg_turns_to_win REAL,
                    avg_mulligans  REAL,
                    avg_final_life REAL,
                    timestamp      TEXT NOT NULL,
                    source         TEXT,
                    source_url     TEXT,
                    archetype      TEXT
                )
            """);

            // ── Matchup Data (3-deck pods) ─────────────────────
            s.execute("""
                CREATE TABLE IF NOT EXISTS matchups (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id       TEXT NOT NULL REFERENCES batch_runs(batch_id),
                    deck_a         TEXT NOT NULL,
                    deck_b         TEXT NOT NULL,
                    deck_c         TEXT NOT NULL,
                    deck_a_wins    INTEGER NOT NULL,
                    deck_b_wins    INTEGER NOT NULL,
                    deck_c_wins    INTEGER NOT NULL,
                    total_games    INTEGER NOT NULL,
                    timestamp      TEXT NOT NULL
                )
            """);

            // ── Deck Analysis Snapshots ────────────────────────
            s.execute("""
                CREATE TABLE IF NOT EXISTS deck_analyses (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    deck_name      TEXT NOT NULL,
                    commander_name TEXT,
                    total_cards    INTEGER,
                    lands          INTEGER,
                    creatures      INTEGER,
                    ramp_cards     INTEGER,
                    removal_cards  INTEGER,
                    draw_cards     INTEGER,
                    board_wipes    INTEGER,
                    analysis_json  TEXT NOT NULL,
                    created_at     TEXT DEFAULT (datetime('now'))
                )
            """);

            // ── Indexes ────────────────────────────────────────
            s.execute("CREATE INDEX IF NOT EXISTS idx_deck_results_name ON deck_results(deck_name)");
            s.execute("CREATE INDEX IF NOT EXISTS idx_deck_results_batch ON deck_results(batch_id)");
            s.execute("CREATE INDEX IF NOT EXISTS idx_matchups_decks ON matchups(deck_a, deck_b, deck_c)");
            s.execute("CREATE INDEX IF NOT EXISTS idx_batch_runs_timestamp ON batch_runs(timestamp)");

            // ── Meta ───────────────────────────────────────────
            s.execute("""
                CREATE TABLE IF NOT EXISTS lab_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """);
            s.execute("INSERT OR REPLACE INTO lab_meta(key, value) VALUES('schema_version', '" + SCHEMA_VERSION + "')");
        }
    }

    // ══════════════════════════════════════════════════════════
    // Batch Run Storage
    // ══════════════════════════════════════════════════════════

    /**
     * Store a complete batch result.
     */
    public synchronized void saveBatchResult(BatchResult result) throws SQLException {
        String json = JsonExporter.toJson(result);
        Metadata m = result.metadata;

        // Insert batch run
        try (PreparedStatement ps = conn.prepareStatement("""
            INSERT OR REPLACE INTO batch_runs
            (batch_id, timestamp, total_games, completed_games, threads, elapsed_ms,
             master_seed, engine_version, sims_per_sec, avg_game_turns, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)) {
            ps.setString(1, m.batchId);
            ps.setString(2, m.timestamp);
            ps.setInt(3, m.totalGames);
            ps.setInt(4, m.completedGames);
            ps.setInt(5, m.threads);
            ps.setLong(6, m.elapsedMs);
            if (m.masterSeed != null) ps.setLong(7, m.masterSeed);
            else ps.setNull(7, Types.INTEGER);
            ps.setString(8, m.engineVersion);
            ps.setDouble(9, result.summary.simsPerSecond);
            ps.setDouble(10, result.summary.avgGameTurns);
            ps.setString(11, json);
            ps.executeUpdate();
        }

        // Insert per-deck results
        try (PreparedStatement ps = conn.prepareStatement("""
            INSERT INTO deck_results
            (batch_id, seat_index, deck_name, commander_name, wins, losses, draws,
             win_rate, avg_turns_to_win, avg_mulligans, avg_final_life, timestamp,
             source, source_url, archetype)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)) {
            for (DeckSummary ds : result.summary.perDeck) {
                DeckInfo deck = result.decks.get(ds.seatIndex);
                ps.setString(1, m.batchId);
                ps.setInt(2, ds.seatIndex);
                ps.setString(3, ds.deckName);
                ps.setString(4, deck.commanderName);
                ps.setInt(5, ds.wins);
                ps.setInt(6, ds.losses);
                ps.setInt(7, ds.draws);
                ps.setDouble(8, ds.winRate);
                if (ds.avgTurnsToWin != null) ps.setDouble(9, ds.avgTurnsToWin);
                else ps.setNull(9, Types.REAL);
                ps.setDouble(10, ds.avgMulligans);
                ps.setDouble(11, ds.avgFinalLife);
                ps.setString(12, m.timestamp);
                ps.setString(13, deck.source);
                ps.setString(14, deck.sourceUrl);
                ps.setString(15, deck.archetype);
                ps.addBatch();
            }
            ps.executeBatch();
        }

        // Insert matchup data
        if (result.decks.size() == 3 && result.summary.perDeck.size() == 3) {
            try (PreparedStatement ps = conn.prepareStatement("""
                INSERT INTO matchups
                (batch_id, deck_a, deck_b, deck_c, deck_a_wins, deck_b_wins, deck_c_wins, total_games, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """)) {
                ps.setString(1, m.batchId);
                ps.setString(2, result.decks.get(0).deckName);
                ps.setString(3, result.decks.get(1).deckName);
                ps.setString(4, result.decks.get(2).deckName);
                ps.setInt(5, result.summary.perDeck.get(0).wins);
                ps.setInt(6, result.summary.perDeck.get(1).wins);
                ps.setInt(7, result.summary.perDeck.get(2).wins);
                ps.setInt(8, m.completedGames);
                ps.setString(9, m.timestamp);
                ps.executeUpdate();
            }
        }
    }

    // ══════════════════════════════════════════════════════════
    // Queries
    // ══════════════════════════════════════════════════════════

    /**
     * Get win rate history for a deck across all batches.
     */
    public List<Map<String, Object>> getDeckWinRateHistory(String deckName) throws SQLException {
        List<Map<String, Object>> history = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement("""
            SELECT batch_id, timestamp, wins, losses, draws, win_rate,
                   avg_turns_to_win, avg_mulligans, avg_final_life
            FROM deck_results
            WHERE deck_name = ?
            ORDER BY timestamp ASC
        """)) {
            ps.setString(1, deckName);
            ResultSet rs = ps.executeQuery();
            while (rs.next()) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("batchId", rs.getString("batch_id"));
                row.put("timestamp", rs.getString("timestamp"));
                row.put("wins", rs.getInt("wins"));
                row.put("losses", rs.getInt("losses"));
                row.put("draws", rs.getInt("draws"));
                row.put("winRate", rs.getDouble("win_rate"));
                row.put("avgTurnsToWin", rs.getObject("avg_turns_to_win"));
                row.put("avgMulligans", rs.getDouble("avg_mulligans"));
                row.put("avgFinalLife", rs.getDouble("avg_final_life"));
                history.add(row);
            }
        }
        return history;
    }

    /**
     * Get overall stats for a deck (aggregated across all batches).
     */
    public Map<String, Object> getDeckOverallStats(String deckName) throws SQLException {
        Map<String, Object> stats = new LinkedHashMap<>();
        try (PreparedStatement ps = conn.prepareStatement("""
            SELECT
                COUNT(*) as batch_count,
                SUM(wins) as total_wins,
                SUM(losses) as total_losses,
                SUM(draws) as total_draws,
                AVG(win_rate) as avg_win_rate,
                MIN(win_rate) as min_win_rate,
                MAX(win_rate) as max_win_rate,
                AVG(avg_turns_to_win) as avg_turns,
                AVG(avg_mulligans) as avg_mulligans
            FROM deck_results WHERE deck_name = ?
        """)) {
            ps.setString(1, deckName);
            ResultSet rs = ps.executeQuery();
            if (rs.next()) {
                stats.put("deckName", deckName);
                stats.put("batchCount", rs.getInt("batch_count"));
                stats.put("totalWins", rs.getInt("total_wins"));
                stats.put("totalLosses", rs.getInt("total_losses"));
                stats.put("totalDraws", rs.getInt("total_draws"));
                stats.put("avgWinRate", rs.getDouble("avg_win_rate"));
                stats.put("minWinRate", rs.getDouble("min_win_rate"));
                stats.put("maxWinRate", rs.getDouble("max_win_rate"));
                stats.put("avgTurns", rs.getObject("avg_turns"));
                stats.put("avgMulligans", rs.getDouble("avg_mulligans"));
            }
        }
        return stats;
    }

    /**
     * Get all unique deck names that have been tested.
     */
    public List<String> getAllTestedDecks() throws SQLException {
        List<String> decks = new ArrayList<>();
        try (Statement s = conn.createStatement();
             ResultSet rs = s.executeQuery(
                "SELECT DISTINCT deck_name FROM deck_results ORDER BY deck_name")) {
            while (rs.next()) {
                decks.add(rs.getString("deck_name"));
            }
        }
        return decks;
    }

    /**
     * Get recent batch runs (most recent first).
     */
    public List<Map<String, Object>> getRecentBatches(int limit) throws SQLException {
        List<Map<String, Object>> batches = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement("""
            SELECT batch_id, timestamp, total_games, completed_games, threads,
                   elapsed_ms, sims_per_sec, avg_game_turns
            FROM batch_runs ORDER BY timestamp DESC LIMIT ?
        """)) {
            ps.setInt(1, limit);
            ResultSet rs = ps.executeQuery();
            while (rs.next()) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("batchId", rs.getString("batch_id"));
                row.put("timestamp", rs.getString("timestamp"));
                row.put("totalGames", rs.getInt("total_games"));
                row.put("completedGames", rs.getInt("completed_games"));
                row.put("threads", rs.getInt("threads"));
                row.put("elapsedMs", rs.getLong("elapsed_ms"));
                row.put("simsPerSec", rs.getDouble("sims_per_sec"));
                row.put("avgGameTurns", rs.getDouble("avg_game_turns"));
                batches.add(row);
            }
        }
        return batches;
    }

    /**
     * Get full batch result JSON by batchId.
     */
    public String getBatchResultJson(String batchId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT result_json FROM batch_runs WHERE batch_id = ?")) {
            ps.setString(1, batchId);
            ResultSet rs = ps.executeQuery();
            if (rs.next()) return rs.getString("result_json");
        }
        return null;
    }

    /**
     * Get matchup win rates for a specific 3-deck pod.
     */
    public Map<String, Object> getMatchupStats(String deckA, String deckB, String deckC) throws SQLException {
        Map<String, Object> stats = new LinkedHashMap<>();
        try (PreparedStatement ps = conn.prepareStatement("""
            SELECT
                COUNT(*) as match_count,
                SUM(total_games) as total_games,
                SUM(deck_a_wins) as a_wins,
                SUM(deck_b_wins) as b_wins,
                SUM(deck_c_wins) as c_wins
            FROM matchups
            WHERE deck_a = ? AND deck_b = ? AND deck_c = ?
        """)) {
            ps.setString(1, deckA);
            ps.setString(2, deckB);
            ps.setString(3, deckC);
            ResultSet rs = ps.executeQuery();
            if (rs.next()) {
                int totalGames = rs.getInt("total_games");
                stats.put("matchCount", rs.getInt("match_count"));
                stats.put("totalGames", totalGames);
                stats.put("deckAWins", rs.getInt("a_wins"));
                stats.put("deckBWins", rs.getInt("b_wins"));
                stats.put("deckCWins", rs.getInt("c_wins"));
                if (totalGames > 0) {
                    stats.put("deckAWinRate", (double) rs.getInt("a_wins") / totalGames);
                    stats.put("deckBWinRate", (double) rs.getInt("b_wins") / totalGames);
                    stats.put("deckCWinRate", (double) rs.getInt("c_wins") / totalGames);
                }
            }
        }
        return stats;
    }

    // ══════════════════════════════════════════════════════════
    // Deck Analysis Storage
    // ══════════════════════════════════════════════════════════

    /**
     * Store a deck analysis snapshot.
     */
    public synchronized void saveDeckAnalysis(DeckAnalysis analysis) throws SQLException {
        String json = GSON.toJson(analysis);
        try (PreparedStatement ps = conn.prepareStatement("""
            INSERT INTO deck_analyses
            (deck_name, commander_name, total_cards, lands, creatures,
             ramp_cards, removal_cards, draw_cards, board_wipes, analysis_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)) {
            ps.setString(1, analysis.deckName);
            ps.setString(2, analysis.commanderName);
            ps.setInt(3, analysis.totalCards);
            ps.setInt(4, analysis.lands);
            ps.setInt(5, analysis.creatures);
            ps.setInt(6, analysis.rampCards);
            ps.setInt(7, analysis.removalCards);
            ps.setInt(8, analysis.drawCards);
            ps.setInt(9, analysis.boardWipes);
            ps.setString(10, json);
            ps.executeUpdate();
        }
    }

    /**
     * Get the latest deck analysis for a deck.
     */
    public String getLatestDeckAnalysis(String deckName) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("""
            SELECT analysis_json FROM deck_analyses
            WHERE deck_name = ? ORDER BY created_at DESC LIMIT 1
        """)) {
            ps.setString(1, deckName);
            ResultSet rs = ps.executeQuery();
            if (rs.next()) return rs.getString("analysis_json");
        }
        return null;
    }

    // ══════════════════════════════════════════════════════════
    // Stats Summary
    // ══════════════════════════════════════════════════════════

    /**
     * Get a global stats summary across all batches.
     */
    public Map<String, Object> getGlobalStats() throws SQLException {
        Map<String, Object> stats = new LinkedHashMap<>();
        try (Statement s = conn.createStatement()) {
            ResultSet rs = s.executeQuery("""
                SELECT
                    COUNT(*) as total_batches,
                    SUM(completed_games) as total_games,
                    AVG(sims_per_sec) as avg_sims_sec,
                    AVG(avg_game_turns) as avg_turns,
                    SUM(elapsed_ms) as total_time_ms
                FROM batch_runs
            """);
            if (rs.next()) {
                stats.put("totalBatches", rs.getInt("total_batches"));
                stats.put("totalGames", rs.getInt("total_games"));
                stats.put("avgSimsPerSec", rs.getDouble("avg_sims_sec"));
                stats.put("avgGameTurns", rs.getDouble("avg_turns"));
                stats.put("totalTimeMs", rs.getLong("total_time_ms"));
            }

            // Count unique decks tested
            rs = s.executeQuery("SELECT COUNT(DISTINCT deck_name) as deck_count FROM deck_results");
            if (rs.next()) {
                stats.put("uniqueDecks", rs.getInt("deck_count"));
            }
        }
        return stats;
    }

    @Override
    public void close() throws SQLException {
        if (conn != null && !conn.isClosed()) {
            conn.close();
        }
    }
}
