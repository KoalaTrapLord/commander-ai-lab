package commanderailab;

import commanderailab.ai.*;
import commanderailab.schema.*;
import commanderailab.schema.BatchResult.*;
import commanderailab.stats.StatsAggregator;
import org.junit.jupiter.api.Test;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for Commander AI Lab core components.
 * These tests validate data structures, stats computation, and JSON serialization
 * without requiring the Forge engine to be installed.
 */
class CommanderAiLabTest {

    // ── AI Policy Tests ──────────────────────────────────────

    @Test
    void testForgeBuiltinPolicyDefaults() {
        ForgeBuiltinPolicy policy = new ForgeBuiltinPolicy();
        assertEquals("forge-builtin", policy.getName());
        assertTrue(policy.usesForgeBuiltinAi());
        assertEquals(0.25, policy.getCardAdvantageWeight(), 0.001);
        assertEquals(0.30, policy.getTempoWeight(), 0.001);
        assertEquals(0.25, policy.getThreatScoringWeight(), 0.001);
        assertEquals(0.20, policy.getCombatWeight(), 0.001);
    }

    @Test
    void testCustomPolicyWeights() {
        ForgeBuiltinPolicy policy = new ForgeBuiltinPolicy(0.4, 0.3, 0.2, 0.1);
        assertEquals(0.4, policy.getCardAdvantageWeight(), 0.001);
        assertEquals(0.3, policy.getTempoWeight(), 0.001);
    }

    // ── Stats Aggregation Tests ──────────────────────────────

    @Test
    void testStatsComputationSingleGame() {
        List<DeckInfo> decks = createTestDecks();
        List<GameResult> games = new ArrayList<>();
        games.add(createGameResult(0, 0, 8, "combat_damage", new int[]{20, -5, 0}, new int[]{0, 1, 0}));

        Summary summary = StatsAggregator.computeSummary(games, decks, 1000);

        assertNotNull(summary);
        assertEquals(3, summary.perDeck.size());

        // Seat 0 won
        DeckSummary s0 = summary.perDeck.get(0);
        assertEquals(1, s0.wins);
        assertEquals(0, s0.losses);
        assertEquals(1.0, s0.winRate, 0.001);
        assertNotNull(s0.avgTurnsToWin);
        assertEquals(8.0, s0.avgTurnsToWin, 0.001);

        // Seat 1 lost
        DeckSummary s1 = summary.perDeck.get(1);
        assertEquals(0, s1.wins);
        assertEquals(1, s1.losses);
        assertEquals(0.0, s1.winRate, 0.001);
        assertNull(s1.avgTurnsToWin); // No wins
        assertEquals(1.0, s1.avgMulligans, 0.001); // Had 1 mulligan
    }

    @Test
    void testStatsComputationMultipleGames() {
        List<DeckInfo> decks = createTestDecks();
        List<GameResult> games = new ArrayList<>();
        // Game 0: Seat 0 wins in 8 turns
        games.add(createGameResult(0, 0, 8, "combat_damage", new int[]{20, 0, 5}, new int[]{0, 0, 0}));
        // Game 1: Seat 1 wins in 12 turns
        games.add(createGameResult(1, 1, 12, "commander_damage", new int[]{0, 30, 10}, new int[]{1, 0, 1}));
        // Game 2: Seat 2 wins in 6 turns
        games.add(createGameResult(2, 2, 6, "combo_alt_win", new int[]{40, 40, 40}, new int[]{0, 0, 0}));
        // Game 3: Seat 0 wins in 10 turns
        games.add(createGameResult(3, 0, 10, "combat_damage", new int[]{15, -3, 0}, new int[]{0, 0, 0}));

        Summary summary = StatsAggregator.computeSummary(games, decks, 5000);

        // Seat 0: 2 wins / 4 games = 50%
        assertEquals(2, summary.perDeck.get(0).wins);
        assertEquals(0.5, summary.perDeck.get(0).winRate, 0.001);
        assertEquals(9.0, summary.perDeck.get(0).avgTurnsToWin, 0.001); // (8+10)/2

        // Seat 1: 1 win / 4 games = 25%
        assertEquals(1, summary.perDeck.get(1).wins);
        assertEquals(0.25, summary.perDeck.get(1).winRate, 0.001);

        // Seat 2: 1 win / 4 games = 25%
        assertEquals(1, summary.perDeck.get(2).wins);

        // Average turns across all games: (8+12+6+10)/4 = 9.0
        assertEquals(9.0, summary.avgGameTurns, 0.001);
    }

    @Test
    void testStatsWithDraws() {
        List<DeckInfo> decks = createTestDecks();
        List<GameResult> games = new ArrayList<>();
        // Draw game (winningSeat = null)
        GameResult draw = createGameResult(0, null, 50, "timeout", new int[]{10, 10, 10}, new int[]{0, 0, 0});
        games.add(draw);

        Summary summary = StatsAggregator.computeSummary(games, decks, 1000);

        for (DeckSummary ds : summary.perDeck) {
            assertEquals(0, ds.wins);
            assertEquals(0, ds.losses);
            assertEquals(1, ds.draws);
            assertEquals(0.0, ds.winRate, 0.001);
            assertNull(ds.avgTurnsToWin);
        }
    }

    @Test
    void testWinConditionBreakdown() {
        List<DeckInfo> decks = createTestDecks();
        List<GameResult> games = new ArrayList<>();
        games.add(createGameResult(0, 0, 8, "combat_damage", new int[]{20, 0, 0}, new int[]{0, 0, 0}));
        games.add(createGameResult(1, 0, 10, "commander_damage", new int[]{15, 0, 0}, new int[]{0, 0, 0}));
        games.add(createGameResult(2, 0, 6, "combo_alt_win", new int[]{40, 0, 0}, new int[]{0, 0, 0}));

        Summary summary = StatsAggregator.computeSummary(games, decks, 1000);
        WinConditionBreakdown b = summary.perDeck.get(0).winConditionBreakdown;

        assertEquals(1, b.combat_damage);
        assertEquals(1, b.commander_damage);
        assertEquals(1, b.combo_alt_win);
        assertEquals(0, b.life_drain);
    }

    // ── Merge Stats Tests ────────────────────────────────────

    @Test
    void testMergeStats() {
        List<GameResult> worker1 = new ArrayList<>();
        worker1.add(createGameResult(0, 0, 8, "combat_damage", new int[]{20, 0, 0}, new int[]{0, 0, 0}));
        worker1.add(createGameResult(1, 1, 10, "commander_damage", new int[]{0, 20, 0}, new int[]{0, 0, 0}));

        List<GameResult> worker2 = new ArrayList<>();
        worker2.add(createGameResult(2, 2, 6, "combo_alt_win", new int[]{0, 0, 40}, new int[]{0, 0, 0}));

        List<List<GameResult>> workers = List.of(worker1, worker2);
        List<GameResult> merged = StatsAggregator.mergeStats(workers);

        assertEquals(3, merged.size());
        // Verify re-indexing
        assertEquals(0, merged.get(0).gameIndex);
        assertEquals(1, merged.get(1).gameIndex);
        assertEquals(2, merged.get(2).gameIndex);
    }

    // ── JSON Serialization Tests ─────────────────────────────

    @Test
    void testJsonRoundTrip() {
        BatchResult original = createTestBatchResult();

        String json = JsonExporter.toJson(original);
        assertNotNull(json);
        assertTrue(json.contains("\"schemaVersion\": \"1.0.0\""));
        assertTrue(json.contains("\"format\": \"commander\""));
        assertTrue(json.contains("\"podSize\": 3"));

        // Validate structure
        assertTrue(JsonExporter.validateBasicStructure(json));
    }

    @Test
    void testJsonContainsAllRequiredKeys() {
        BatchResult result = createTestBatchResult();
        String json = JsonExporter.toJson(result);

        assertTrue(json.contains("\"metadata\""));
        assertTrue(json.contains("\"decks\""));
        assertTrue(json.contains("\"games\""));
        assertTrue(json.contains("\"summary\""));
        assertTrue(json.contains("\"batchId\""));
        assertTrue(json.contains("\"timestamp\""));
        assertTrue(json.contains("\"winRate\""));
        assertTrue(json.contains("\"avgTurnsToWin\""));
        assertTrue(json.contains("\"avgMulligans\""));
        assertTrue(json.contains("\"winConditionBreakdown\""));
    }

    @Test
    void testJsonValidationRejectsInvalid() {
        assertFalse(JsonExporter.validateBasicStructure("{}"));
        assertFalse(JsonExporter.validateBasicStructure("not json"));
        assertFalse(JsonExporter.validateBasicStructure("{\"metadata\": {}}"));
    }

    // ── Helper Methods ───────────────────────────────────────

    private List<DeckInfo> createTestDecks() {
        List<DeckInfo> decks = new ArrayList<>();
        String[] names = {"Atraxa_Superfriends", "Korvold_Aristocrats", "Muldrotha_Value"};
        String[] commanders = {"Atraxa, Praetors' Voice", "Korvold, Fae-Cursed King", "Muldrotha, the Gravetide"};
        for (int i = 0; i < 3; i++) {
            DeckInfo d = new DeckInfo();
            d.seatIndex = i;
            d.deckName = names[i];
            d.commanderName = commanders[i];
            d.deckFile = names[i] + ".dck";
            d.colorIdentity = List.of("W", "U", "B", "G");
            d.cardCount = 100;
            decks.add(d);
        }
        return decks;
    }

    private GameResult createGameResult(int gameIndex, Integer winningSeat, int turns,
                                         String winCondition, int[] lives, int[] mulligans) {
        GameResult g = new GameResult();
        g.gameIndex = gameIndex;
        g.winningSeat = winningSeat;
        g.totalTurns = turns;
        g.winCondition = winCondition;
        g.gameSeed = 42 + gameIndex;
        g.elapsedMs = 1000 + gameIndex * 500;
        g.playerResults = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            PlayerResult pr = new PlayerResult();
            pr.seatIndex = i;
            pr.finalLife = lives[i];
            pr.mulligans = mulligans[i];
            pr.isWinner = (winningSeat != null && winningSeat == i);
            pr.commanderDamageDealt = 0;
            pr.commanderCasts = 0;
            pr.landsPlayed = turns / 2;
            pr.spellsCast = turns;
            pr.creaturesDestroyed = 0;
            g.playerResults.add(pr);
        }
        return g;
    }

    private BatchResult createTestBatchResult() {
        List<DeckInfo> decks = createTestDecks();
        List<GameResult> games = new ArrayList<>();
        games.add(createGameResult(0, 0, 8, "combat_damage", new int[]{20, 0, 5}, new int[]{0, 1, 0}));
        games.add(createGameResult(1, 1, 12, "commander_damage", new int[]{0, 30, 10}, new int[]{1, 0, 1}));
        games.add(createGameResult(2, 2, 6, "combo_alt_win", new int[]{40, 40, 40}, new int[]{0, 0, 0}));

        Summary summary = StatsAggregator.computeSummary(games, decks, 3000);

        BatchResult result = new BatchResult();
        result.metadata = new Metadata();
        result.metadata.batchId = "test-batch-001";
        result.metadata.timestamp = "2026-03-06T22:00:00Z";
        result.metadata.totalGames = 3;
        result.metadata.completedGames = 3;
        result.metadata.engineVersion = "forge-1.6.64-SNAPSHOT";
        result.metadata.masterSeed = 42L;
        result.metadata.threads = 1;
        result.metadata.elapsedMs = 3000;
        result.decks = decks;
        result.games = games;
        result.summary = summary;

        return result;
    }
}
