package commanderailab.meta;

import com.google.gson.*;
import com.google.gson.reflect.TypeToken;

import java.io.*;
import java.nio.file.*;
import java.util.*;

/**
 * CommanderMetaService — Provides curated meta deck mappings for popular commanders.
 *
 * Maps commander names to recommended meta deck sources (EDHREC average, curated lists).
 * The mapping is stored as a JSON file (commander-meta.json) alongside the JAR,
 * and can be extended by the user.
 *
 * Usage:
 *   CommanderMetaService.loadMapping("commander-meta.json");
 *   List<MetaDeckEntry> decks = CommanderMetaService.getMetaDecks("Edgar Markov");
 */
public class CommanderMetaService {

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    /** Commander name (lowercased) → list of meta deck entries */
    private static Map<String, List<MetaDeckEntry>> mapping = new LinkedHashMap<>();

    /** All known commanders (for autocomplete / listing) */
    private static List<String> knownCommanders = new ArrayList<>();

    // ── Data model ─────────────────────────────────────────

    public static class MetaDeckEntry {
        public String commander;        // Canonical commander name
        public String label;            // Display label (e.g., "EDHREC Average", "High Power Aggro")
        public String source;           // Source type: "edhrec", "archidekt", "curated"
        public String url;              // URL to fetch/reference
        public String archetype;        // Optional: aggro, control, combo, midrange, stax
        public String[] colorIdentity;  // e.g., ["W","B","R"]
        public String notes;            // Optional notes

        public MetaDeckEntry() {}

        public MetaDeckEntry(String commander, String label, String source, String url) {
            this.commander = commander;
            this.label = label;
            this.source = source;
            this.url = url;
        }

        @Override
        public String toString() {
            return String.format("%s — %s (%s)", commander, label, source);
        }
    }

    // ══════════════════════════════════════════════════════════
    // Mapping Management
    // ══════════════════════════════════════════════════════════

    /**
     * Load the commander→meta deck mapping from a JSON file.
     */
    public static void loadMapping(String filePath) throws IOException {
        if (!Files.exists(Path.of(filePath))) {
            System.out.println("  [Meta] No commander-meta.json found, using built-in defaults.");
            loadBuiltinDefaults();
            return;
        }

        String json = Files.readString(Path.of(filePath));
        loadFromJson(json);
        System.out.printf("  [Meta] Loaded %d commanders from %s%n", knownCommanders.size(), filePath);
    }

    /**
     * Load mapping from a JSON string.
     */
    public static void loadFromJson(String json) {
        JsonObject root = JsonParser.parseString(json).getAsJsonObject();
        mapping.clear();
        knownCommanders.clear();

        for (var entry : root.entrySet()) {
            String key = entry.getKey();  // Commander name (canonical)
            JsonArray arr = entry.getValue().getAsJsonArray();
            List<MetaDeckEntry> entries = new ArrayList<>();

            for (JsonElement el : arr) {
                MetaDeckEntry mde = GSON.fromJson(el, MetaDeckEntry.class);
                if (mde.commander == null) mde.commander = key;
                entries.add(mde);
            }

            mapping.put(key.toLowerCase(), entries);
            knownCommanders.add(key);
        }
    }

    /**
     * Save the current mapping to a JSON file.
     */
    public static void saveMapping(String filePath) throws IOException {
        // Reconstruct with canonical names as keys
        JsonObject root = new JsonObject();
        for (String commander : knownCommanders) {
            List<MetaDeckEntry> entries = mapping.get(commander.toLowerCase());
            if (entries != null) {
                root.add(commander, GSON.toJsonTree(entries));
            }
        }
        Files.writeString(Path.of(filePath), GSON.toJson(root));
    }

    // ══════════════════════════════════════════════════════════
    // Queries
    // ══════════════════════════════════════════════════════════

    /**
     * Get meta deck entries for a commander.
     */
    public static List<MetaDeckEntry> getMetaDecks(String commanderName) {
        return mapping.getOrDefault(commanderName.toLowerCase(), List.of());
    }

    /**
     * Check if a commander has meta deck entries.
     */
    public static boolean hasMetaDecks(String commanderName) {
        return mapping.containsKey(commanderName.toLowerCase());
    }

    /**
     * Get all known commander names.
     */
    public static List<String> getAllCommanders() {
        return Collections.unmodifiableList(knownCommanders);
    }

    /**
     * Search commanders by partial name match (case-insensitive).
     */
    public static List<String> searchCommanders(String query) {
        String lower = query.toLowerCase();
        return knownCommanders.stream()
                .filter(c -> c.toLowerCase().contains(lower))
                .toList();
    }

    /**
     * Get the first/default meta deck for a commander.
     * Usually the EDHREC average deck.
     */
    public static MetaDeckEntry getDefaultMetaDeck(String commanderName) {
        List<MetaDeckEntry> entries = getMetaDecks(commanderName);
        return entries.isEmpty() ? null : entries.get(0);
    }

    // ══════════════════════════════════════════════════════════
    // Built-in Defaults
    // ══════════════════════════════════════════════════════════

    /**
     * Load a curated set of popular commanders with EDHREC average deck links.
     * These cover the most commonly tested commanders.
     */
    public static void loadBuiltinDefaults() {
        mapping.clear();
        knownCommanders.clear();

        addDefault("Edgar Markov", new String[]{"W","B","R"}, "aggro",
                "https://edhrec.com/average-decks/edgar-markov");
        addDefault("Atraxa, Praetors' Voice", new String[]{"W","U","B","G"}, "midrange",
                "https://edhrec.com/average-decks/atraxa-praetors-voice");
        addDefault("Korvold, Fae-Cursed King", new String[]{"B","R","G"}, "combo",
                "https://edhrec.com/average-decks/korvold-fae-cursed-king");
        addDefault("Muldrotha, the Gravetide", new String[]{"U","B","G"}, "midrange",
                "https://edhrec.com/average-decks/muldrotha-the-gravetide");
        addDefault("The Ur-Dragon", new String[]{"W","U","B","R","G"}, "midrange",
                "https://edhrec.com/average-decks/the-ur-dragon");
        addDefault("Yuriko, the Tiger's Shadow", new String[]{"U","B"}, "aggro",
                "https://edhrec.com/average-decks/yuriko-the-tigers-shadow");
        addDefault("Krenko, Mob Boss", new String[]{"R"}, "aggro",
                "https://edhrec.com/average-decks/krenko-mob-boss");
        addDefault("Meren of Clan Nel Toth", new String[]{"B","G"}, "midrange",
                "https://edhrec.com/average-decks/meren-of-clan-nel-toth");
        addDefault("Prossh, Skyraider of Kher", new String[]{"B","R","G"}, "combo",
                "https://edhrec.com/average-decks/prossh-skyraider-of-kher");
        addDefault("Kaalia of the Vast", new String[]{"W","B","R"}, "aggro",
                "https://edhrec.com/average-decks/kaalia-of-the-vast");
        addDefault("Windgrace", new String[]{"B","R","G"}, "midrange",
                "https://edhrec.com/average-decks/lord-windgrace");
        addDefault("Talrand, Sky Summoner", new String[]{"U"}, "control",
                "https://edhrec.com/average-decks/talrand-sky-summoner");
        addDefault("Omnath, Locus of Creation", new String[]{"W","U","R","G"}, "combo",
                "https://edhrec.com/average-decks/omnath-locus-of-creation");
        addDefault("Teysa Karlov", new String[]{"W","B"}, "combo",
                "https://edhrec.com/average-decks/teysa-karlov");
        addDefault("Lathril, Blade of the Elves", new String[]{"B","G"}, "aggro",
                "https://edhrec.com/average-decks/lathril-blade-of-the-elves");

        System.out.printf("  [Meta] Loaded %d built-in commander defaults%n", knownCommanders.size());
    }

    private static void addDefault(String commander, String[] colors, String archetype, String url) {
        MetaDeckEntry entry = new MetaDeckEntry();
        entry.commander = commander;
        entry.label = "EDHREC Average";
        entry.source = "edhrec";
        entry.url = url;
        entry.archetype = archetype;
        entry.colorIdentity = colors;

        mapping.put(commander.toLowerCase(), new ArrayList<>(List.of(entry)));
        knownCommanders.add(commander);
    }
}
