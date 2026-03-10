package commanderailab.meta;

import java.util.*;

/**
 * DeckProfile — Represents an imported deck from an external source.
 *
 * Holds card list + metadata about where the deck came from
 * (EDHREC average, Archidekt user deck, Moxfield paste, etc.)
 */
public class DeckProfile {

    /** Display name for the deck (e.g., "Edgar Markov — EDHREC Average") */
    public String name;

    /** Commander card name */
    public String commander;

    /** Color identity (e.g., ["W","B","R"]) */
    public List<String> colorIdentity = new ArrayList<>();

    /** Where this deck came from */
    public DeckSource source;

    /** URL to the original deck (Archidekt/Moxfield/EDHREC page) */
    public String sourceUrl;

    /** Cards in the 99 (mainboard) — cardName → quantity */
    public Map<String, Integer> mainboard = new LinkedHashMap<>();

    /** Cards in the command zone — cardName → quantity (usually 1-2 for partners) */
    public Map<String, Integer> commanders = new LinkedHashMap<>();

    /** Total card count (should be 99 + commander(s) = 100) */
    public int totalCards;

    /** Timestamp of import */
    public String importedAt;

    /** Optional: EDHREC-specific — number of decks sampled */
    public Integer sampleSize;

    /** Optional: archetype tag (aggro, control, combo, etc.) */
    public String archetype;

    // ── Source enum ─────────────────────────────────────────

    public enum DeckSource {
        EDHREC_AVERAGE,    // EDHREC average/recommended deck for a commander
        ARCHIDEKT,         // Archidekt public deck by ID
        MOXFIELD,          // Moxfield text import
        TEXT_IMPORT,       // Raw card list paste (MTGO/Arena format)
        LOCAL_FILE,        // Local .dck file
        CURATED;           // Hand-curated meta deck in JSON mapping

        public String label() {
            return switch (this) {
                case EDHREC_AVERAGE -> "EDHREC Average";
                case ARCHIDEKT -> "Archidekt";
                case MOXFIELD -> "Moxfield";
                case TEXT_IMPORT -> "Text Import";
                case LOCAL_FILE -> "Local File";
                case CURATED -> "Curated Meta";
            };
        }
    }

    // ── Helpers ─────────────────────────────────────────────

    /**
     * Get all cards (commanders + mainboard) as a flat list with quantities.
     */
    public Map<String, Integer> allCards() {
        Map<String, Integer> all = new LinkedHashMap<>();
        all.putAll(commanders);
        all.putAll(mainboard);
        return all;
    }

    /**
     * Validate the deck has a reasonable structure.
     */
    public List<String> validate() {
        List<String> issues = new ArrayList<>();
        if (commander == null || commander.isBlank()) {
            issues.add("No commander specified");
        }
        if (commanders.isEmpty()) {
            issues.add("Commander zone is empty");
        }
        int total = commanders.values().stream().mapToInt(Integer::intValue).sum()
                  + mainboard.values().stream().mapToInt(Integer::intValue).sum();
        if (total < 90) {
            issues.add("Deck has only " + total + " cards (expected ~100)");
        }
        if (total > 101) {
            issues.add("Deck has " + total + " cards (expected 100)");
        }
        totalCards = total;
        return issues;
    }

    @Override
    public String toString() {
        int mainCount = mainboard.values().stream().mapToInt(Integer::intValue).sum();
        int cmdCount = commanders.values().stream().mapToInt(Integer::intValue).sum();
        return String.format("DeckProfile{name='%s', commander='%s', source=%s, cards=%d+%d}",
                name, commander, source, cmdCount, mainCount);
    }
}
