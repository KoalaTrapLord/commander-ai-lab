package commanderailab.schema;

import java.util.List;

/**
 * Complete data model for batch simulation results.
 * Serialized to JSON conforming to batch-result-schema.json.
 */
public class BatchResult {

    public Metadata metadata;
    public List<DeckInfo> decks;
    public List<GameResult> games;
    public Summary summary;

    // ── Metadata ───────────────────────────────────────────────

    public static class Metadata {
        public String schemaVersion = "1.0.0";
        public String batchId;
        public String timestamp;       // ISO 8601
        public int totalGames;
        public int completedGames;
        public String format = "commander";
        public int podSize = 3;
        public String engineVersion;
        public Long masterSeed;        // null if random
        public int threads = 1;
        public long elapsedMs;
    }

    // ── Deck Info ──────────────────────────────────────────────

    public static class DeckInfo {
        public int seatIndex;
        public String deckName;
        public String commanderName;
        public String deckFile;
        public List<String> colorIdentity;
        public int cardCount;

        // v3: Source/import metadata
        public String source;           // e.g., "edhrec", "archidekt", "local", "text"
        public String sourceUrl;        // URL to original deck (if imported)
        public String archetype;        // e.g., "aggro", "control", "combo"
        public Integer sampleSize;      // EDHREC: number of decks sampled
        public String importedAt;       // ISO 8601 timestamp of import
    }

    // ── Per-Game Result ────────────────────────────────────────

    public static class GameResult {
        public int gameIndex;
        public Integer winningSeat;     // null if draw/timeout
        public int totalTurns;
        public String winCondition;     // enum from schema
        public long gameSeed;
        public long elapsedMs;
        public List<PlayerResult> playerResults;
    }

    public static class PlayerResult {
        public int seatIndex;
        public int finalLife;
        public int mulligans;
        public boolean isWinner;
        public int commanderDamageDealt;
        public int commanderCasts;
        public int landsPlayed;
        public int spellsCast;
        public int creaturesDestroyed;

        // v4: Per-card detailed stats for coach analytics
        public List<PerCardGameStats> cardStats;
    }

    // ── Summary ────────────────────────────────────────────────

    public static class Summary {
        public List<DeckSummary> perDeck;
        public double avgGameTurns;
        public double avgGameTimeMs;
        public double simsPerSecond;
    }

    public static class DeckSummary {
        public int seatIndex;
        public String deckName;
        public int wins;
        public int losses;
        public int draws;
        public double winRate;
        public Double avgTurnsToWin;    // null if zero wins
        public double avgMulligans;

                // v5: Aggregate combat stats from per-game PlayerResult data
        public double avgSpellsCast;
        public double avgLandsPlayed;
        public double avgCommanderCasts;
        public double avgCommanderDamageDealt;
        public double avgCreaturesDestroyed;
        public double avgFinalLife;
        public WinConditionBreakdown winConditionBreakdown;
    }

    public static class WinConditionBreakdown {
        public int combat_damage;
        public int commander_damage;
        public int combo_alt_win;
        public int life_drain;
        public int mill;
        public int concession;
        public int timeout;
        public int unknown;

        public void increment(String condition) {
            switch (condition) {
                case "combat_damage" -> combat_damage++;
                case "commander_damage" -> commander_damage++;
                case "combo_alt_win" -> combo_alt_win++;
                case "life_drain" -> life_drain++;
                case "mill" -> mill++;
                case "concession" -> concession++;
                case "timeout" -> timeout++;
                default -> unknown++;
            }
        }
    }
}
