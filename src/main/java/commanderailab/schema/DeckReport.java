package commanderailab.schema;

import java.util.*;

/**
 * DeckReport — Complete deck performance profile.
 *
 * Aggregates simulation results into a comprehensive report that
 * the Python coach service consumes to generate improvement suggestions.
 *
 * Serialized to JSON and written to deck-reports/{deckId}.json.
 */
public class DeckReport {

    public String deckId;
    public String commander;
    public List<String> colorIdentity = new ArrayList<>();

    public DeckMeta meta = new DeckMeta();
    public List<MatchupRecord> matchups = new ArrayList<>();
    public DeckStructure structure = new DeckStructure();
    public List<CardPerformance> cards = new ArrayList<>();

    public List<String> underperformers = new ArrayList<>();
    public List<String> overperformers = new ArrayList<>();
    public List<ComboRecord> knownCombos = new ArrayList<>();
    public String lastUpdated;  // ISO 8601

    // ── Deck-Level Meta Stats ─────────────────────────────────

    public static class DeckMeta {
        public int gamesSimulated;
        public double overallWinRate;
        public double avgGameLength;
        public Map<String, Double> perArchetypeWinRates = new LinkedHashMap<>();
    }

    // ── Matchup Record ────────────────────────────────────────

    public static class MatchupRecord {
        public String opponentDeck;
        public String opponentCommander = "";
        public int gamesPlayed;
        public double winRate;
    }

    // ── Deck Structure ────────────────────────────────────────

    public static class DeckStructure {
        public int landCount;
        public int[] curveBuckets = new int[8];  // CMC 0-7+
        public Map<String, Integer> cardTypeCounts = new LinkedHashMap<>();
        public Map<String, Integer> functionalCounts = new LinkedHashMap<>();
    }

    // ── Per-Card Performance ──────────────────────────────────

    public static class CardPerformance {
        public String name;
        public double drawnRate;
        public double castRate;
        public double keptInOpeningHandRate;
        public double deadCardRate;
        public double impactScore;        // (winRateWhenCast - overallWinRate) * castRate
        public double synergyScore;
        public double clunkinessScore;    // deadCardRate * (1 - castRate)
        public Double avgTurnCast;        // null if never cast
        public double avgDamageDealt;
        public List<String> tags = new ArrayList<>();

        // ── Intermediate accumulators (not serialized) ────────
        // Used during aggregation, then converted to rates
        public transient int gamesDrawn;
        public transient int gamesCast;
        public transient int gamesKeptInOpening;
        public transient int gamesDeadCard;
        public transient int gamesWhenCast;
        public transient int winsWhenCast;
        public transient double totalTurnCast;
        public transient double totalDamage;
        public transient int gamesSeen;
    }

    // ── Combo Record ──────────────────────────────────────────

    public static class ComboRecord {
        public List<String> cardNames = new ArrayList<>();
        public double winRateWhenAssembled;
        public double assemblyRate;
    }
}
