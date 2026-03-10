package commanderailab.meta;

import com.google.gson.*;
import com.google.gson.reflect.TypeToken;

import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.time.Duration;
import java.time.Instant;
import java.util.*;

/**
 * DeckImporter — Fetches and parses decks from external sources.
 *
 * Supported sources:
 *   - EDHREC average deck:  json.edhrec.com/pages/average-decks/{commander}.json
 *   - Archidekt deck:       archidekt.com/api/decks/{id}/
 *   - Text import:          Plain card list ("1 Card Name" per line)
 *   - Local .dck file:      Forge deck format
 *
 * All imports produce a DeckProfile which can be converted to Forge .dck format.
 */
public class DeckImporter {

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();
    private static final String USER_AGENT = "CommanderAILab/2.0";

    // ══════════════════════════════════════════════════════════
    // EDHREC Average Deck
    // ══════════════════════════════════════════════════════════

    /**
     * Fetch the EDHREC average/recommended deck for a commander.
     *
     * @param commanderName e.g., "Edgar Markov", "Atraxa, Praetors' Voice"
     * @return DeckProfile with ~100 cards
     */
    public static DeckProfile importFromEdhrec(String commanderName) throws IOException, InterruptedException {
        String slug = toEdhrecSlug(commanderName);
        String url = "https://json.edhrec.com/pages/average-decks/" + slug + ".json";

        System.out.printf("  [Import] Fetching EDHREC average deck: %s%n", url);
        String json = httpGet(url);
        JsonObject root = JsonParser.parseString(json).getAsJsonObject();

        DeckProfile profile = new DeckProfile();
        profile.source = DeckProfile.DeckSource.EDHREC_AVERAGE;
        profile.sourceUrl = "https://edhrec.com/average-decks/" + slug;
        profile.importedAt = Instant.now().toString();

        // Get commander info
        JsonObject container = root.getAsJsonObject("container");
        JsonObject jsonDict = container.getAsJsonObject("json_dict");
        JsonObject cardInfo = jsonDict.getAsJsonObject("card");
        String realName = cardInfo.get("name").getAsString();
        profile.commander = realName;
        profile.name = realName + " — EDHREC Average";

        // Parse color identity
        if (cardInfo.has("color_identity") && cardInfo.get("color_identity").isJsonArray()) {
            for (JsonElement ci : cardInfo.getAsJsonArray("color_identity")) {
                profile.colorIdentity.add(ci.getAsString());
            }
        }

        // Sample size
        if (root.has("num_decks_avg")) {
            profile.sampleSize = root.get("num_decks_avg").getAsInt();
        }

        // Build card list from cardlists (each tag is a category)
        JsonArray cardlists = jsonDict.getAsJsonArray("cardlists");
        profile.commanders.put(realName, 1);

        for (JsonElement clEl : cardlists) {
            JsonObject cl = clEl.getAsJsonObject();
            String tag = cl.has("tag") ? cl.get("tag").getAsString() : "";
            JsonArray cardviews = cl.getAsJsonArray("cardviews");

            for (JsonElement cvEl : cardviews) {
                JsonObject cv = cvEl.getAsJsonObject();
                String cardName = cv.get("name").getAsString();
                // Default quantity is 1 for non-basics
                int qty = 1;
                profile.mainboard.put(cardName, qty);
            }
        }

        // Fix basic land quantities using the archidekt export data
        if (root.has("archidekt") && root.get("archidekt").isJsonArray()) {
            fixBasicLandQuantities(profile, root.getAsJsonArray("archidekt"), cardlists);
        }

        // Ensure we hit ~100 cards
        profile.totalCards = profile.commanders.values().stream().mapToInt(Integer::intValue).sum()
                + profile.mainboard.values().stream().mapToInt(Integer::intValue).sum();

        System.out.printf("  [Import] EDHREC deck loaded: %s (%d cards, %d decks sampled)%n",
                profile.commander, profile.totalCards, profile.sampleSize != null ? profile.sampleSize : 0);

        return profile;
    }

    /**
     * Fix basic land quantities from EDHREC's archidekt export array.
     * The archidekt array has {c, f, q, u} entries where q>1 for basics.
     */
    private static void fixBasicLandQuantities(DeckProfile profile, JsonArray archidekt, JsonArray cardlists) {
        // Build a name→uuid lookup from cardlists
        // Also collect basic land names from cardlists
        Set<String> basicLandNames = new HashSet<>();
        for (JsonElement clEl : cardlists) {
            JsonObject cl = clEl.getAsJsonObject();
            String tag = cl.has("tag") ? cl.get("tag").getAsString() : "";
            if (tag.equals("basics")) {
                for (JsonElement cvEl : cl.getAsJsonArray("cardviews")) {
                    basicLandNames.add(cvEl.getAsJsonObject().get("name").getAsString());
                }
            }
        }

        // Count entries with q>1 — these are basic lands
        int totalFromArchidekt = 0;
        int nonBasicCards = 0;
        Map<String, Integer> basicQuantities = new LinkedHashMap<>();

        for (JsonElement ae : archidekt) {
            JsonObject entry = ae.getAsJsonObject();
            int qty = entry.get("q").getAsInt();
            totalFromArchidekt += qty;
            if (qty > 1) {
                // This is a basic land — we'll match by position
                basicQuantities.put(entry.get("u").getAsString(), qty);
            } else {
                nonBasicCards++;
            }
        }

        // Update basic land quantities in the profile
        // The basic lands in profile.mainboard currently have qty=1
        // We need to update them with correct quantities
        if (!basicQuantities.isEmpty() && !basicLandNames.isEmpty()) {
            // Simple approach: distribute the excess cards among basic lands
            int totalBasicQty = basicQuantities.values().stream().mapToInt(Integer::intValue).sum();
            int numBasics = basicLandNames.size();

            // Try to match by Scryfall UUID (expensive) or just use the quantities in order
            List<String> basicNames = new ArrayList<>(basicLandNames);
            List<Integer> quantities = new ArrayList<>(basicQuantities.values());

            for (int i = 0; i < Math.min(basicNames.size(), quantities.size()); i++) {
                profile.mainboard.put(basicNames.get(i), quantities.get(i));
            }
        }
    }

    // ══════════════════════════════════════════════════════════
    // Archidekt Deck Import
    // ══════════════════════════════════════════════════════════

    /**
     * Fetch a public deck from Archidekt by deck ID.
     *
     * @param deckId Archidekt deck ID (numeric)
     * @return DeckProfile
     */
    public static DeckProfile importFromArchidekt(String deckId) throws IOException, InterruptedException {
        String url = "https://archidekt.com/api/decks/" + deckId + "/";

        System.out.printf("  [Import] Fetching Archidekt deck: %s%n", url);
        String json = httpGet(url);
        JsonObject root = JsonParser.parseString(json).getAsJsonObject();

        DeckProfile profile = new DeckProfile();
        profile.source = DeckProfile.DeckSource.ARCHIDEKT;
        profile.sourceUrl = "https://archidekt.com/decks/" + deckId;
        profile.importedAt = Instant.now().toString();
        profile.name = root.has("name") ? root.get("name").getAsString() : "Archidekt Deck " + deckId;

        // Parse cards
        JsonArray cards = root.getAsJsonArray("cards");
        for (JsonElement cardEl : cards) {
            JsonObject entry = cardEl.getAsJsonObject();
            int qty = entry.get("quantity").getAsInt();
            JsonObject card = entry.getAsJsonObject("card");
            JsonObject oracle = card.getAsJsonObject("oracleCard");
            String cardName = oracle.get("name").getAsString();

            // Check categories for Commander
            JsonArray categories = entry.getAsJsonArray("categories");
            boolean isCommander = false;
            for (JsonElement cat : categories) {
                if (cat.getAsString().equalsIgnoreCase("Commander")) {
                    isCommander = true;
                    break;
                }
            }

            if (isCommander) {
                profile.commanders.put(cardName, qty);
                if (profile.commander == null) {
                    profile.commander = cardName;
                }
                // Extract color identity from commander
                if (oracle.has("colorIdentity") && oracle.get("colorIdentity").isJsonArray()) {
                    for (JsonElement ci : oracle.getAsJsonArray("colorIdentity")) {
                        String color = ci.getAsString();
                        if (!profile.colorIdentity.contains(color)) {
                            profile.colorIdentity.add(color);
                        }
                    }
                }
            } else {
                profile.mainboard.put(cardName, qty);
            }
        }

        profile.totalCards = profile.commanders.values().stream().mapToInt(Integer::intValue).sum()
                + profile.mainboard.values().stream().mapToInt(Integer::intValue).sum();

        System.out.printf("  [Import] Archidekt deck loaded: %s — %s (%d cards)%n",
                profile.name, profile.commander, profile.totalCards);

        return profile;
    }

    // ══════════════════════════════════════════════════════════
    // Text Import (MTGO / Arena / Generic Format)
    // ══════════════════════════════════════════════════════════

    /**
     * Parse a plain text card list.
     * Supports formats:
     *   1 Card Name
     *   1x Card Name
     *   1 Card Name (SET) 123
     *
     * The first card or a line starting with "Commander:" / "[Commander]" is the commander.
     */
    public static DeckProfile importFromText(String text, String commanderOverride) {
        DeckProfile profile = new DeckProfile();
        profile.source = DeckProfile.DeckSource.TEXT_IMPORT;
        profile.importedAt = Instant.now().toString();

        String currentSection = "main";
        boolean commanderFound = false;

        for (String line : text.split("\\n")) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("//") || line.startsWith("#")) continue;

            // Section markers
            if (line.toLowerCase().startsWith("commander") || line.equalsIgnoreCase("[Commander]")) {
                currentSection = "commander";
                continue;
            }
            if (line.toLowerCase().startsWith("main") || line.toLowerCase().startsWith("deck")
                    || line.equalsIgnoreCase("[Main]") || line.equalsIgnoreCase("[Deck]")) {
                currentSection = "main";
                continue;
            }
            if (line.toLowerCase().startsWith("sideboard") || line.equalsIgnoreCase("[Sideboard]")) {
                currentSection = "sideboard";
                continue;
            }

            // Parse card entry: "1 Card Name", "1x Card Name", "1 Card Name (SET) 123"
            String cleanLine = line
                    .replaceAll("\\(\\w+\\)\\s*\\d*$", "")  // Remove "(SET) 123" suffix
                    .replaceAll("\\s*\\*.*$", "")             // Remove "* F" foil markers
                    .trim();

            int qty = 1;
            String cardName;
            var match = java.util.regex.Pattern.compile("^(\\d+)x?\\s+(.+)$").matcher(cleanLine);
            if (match.matches()) {
                qty = Integer.parseInt(match.group(1));
                cardName = match.group(2).trim();
            } else {
                cardName = cleanLine;
            }

            if (cardName.isEmpty()) continue;

            if (currentSection.equals("commander")) {
                profile.commanders.put(cardName, qty);
                if (!commanderFound) {
                    profile.commander = cardName;
                    commanderFound = true;
                }
            } else if (!currentSection.equals("sideboard")) {
                profile.mainboard.put(cardName, qty);
            }
        }

        // Commander override
        if (commanderOverride != null && !commanderOverride.isBlank()) {
            profile.commander = commanderOverride;
            if (profile.commanders.isEmpty()) {
                // Move from mainboard to commander zone if found
                if (profile.mainboard.containsKey(commanderOverride)) {
                    int qty = profile.mainboard.remove(commanderOverride);
                    profile.commanders.put(commanderOverride, qty);
                } else {
                    profile.commanders.put(commanderOverride, 1);
                }
            }
        }

        profile.name = profile.commander != null ? profile.commander + " — Text Import" : "Text Import";
        profile.totalCards = profile.commanders.values().stream().mapToInt(Integer::intValue).sum()
                + profile.mainboard.values().stream().mapToInt(Integer::intValue).sum();

        return profile;
    }

    // ══════════════════════════════════════════════════════════
    // Local .dck File Import
    // ══════════════════════════════════════════════════════════

    /**
     * Parse a Forge .dck file into a DeckProfile.
     */
    public static DeckProfile importFromDckFile(String filePath) throws IOException {
        List<String> lines = Files.readAllLines(Path.of(filePath));
        DeckProfile profile = new DeckProfile();
        profile.source = DeckProfile.DeckSource.LOCAL_FILE;
        profile.sourceUrl = filePath;
        profile.importedAt = Instant.now().toString();

        String currentSection = "Main";
        String deckName = Path.of(filePath).getFileName().toString().replace(".dck", "");

        for (String line : lines) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("//")) continue;

            if (line.startsWith("[") && line.endsWith("]")) {
                currentSection = line.substring(1, line.length() - 1);
                continue;
            }
            if (line.startsWith("Name=")) {
                deckName = line.substring(5).trim();
                continue;
            }

            var match = java.util.regex.Pattern.compile("^(\\d+)\\s+(.+?)(?:\\|(.+))?$").matcher(line);
            if (match.matches()) {
                int qty = Integer.parseInt(match.group(1));
                String cardName = match.group(2).trim();

                if (currentSection.equalsIgnoreCase("Commander")) {
                    profile.commanders.put(cardName, qty);
                    if (profile.commander == null) profile.commander = cardName;
                } else if (currentSection.equalsIgnoreCase("Main")) {
                    profile.mainboard.put(cardName, qty);
                }
            }
        }

        profile.name = deckName;
        profile.totalCards = profile.commanders.values().stream().mapToInt(Integer::intValue).sum()
                + profile.mainboard.values().stream().mapToInt(Integer::intValue).sum();

        return profile;
    }

    // ══════════════════════════════════════════════════════════
    // Auto-detect import from URL
    // ══════════════════════════════════════════════════════════

    /**
     * Auto-detect the source from a URL and import.
     *
     * Supported URL patterns:
     *   https://archidekt.com/decks/12345/...  → Archidekt
     *   https://edhrec.com/average-decks/edgar-markov  → EDHREC
     *   https://edhrec.com/commanders/edgar-markov  → EDHREC average
     */
    public static DeckProfile importFromUrl(String url) throws IOException, InterruptedException {
        url = url.trim();

        // Archidekt: https://archidekt.com/decks/12345 or /decks/12345/name
        if (url.contains("archidekt.com/decks/")) {
            String id = url.replaceAll(".*/decks/(\\d+).*", "$1");
            return importFromArchidekt(id);
        }

        // EDHREC average deck: https://edhrec.com/average-decks/edgar-markov
        if (url.contains("edhrec.com/average-decks/")) {
            String slug = url.replaceAll(".*/average-decks/([^/?#]+).*", "$1");
            String commanderName = slug.replace("-", " ");
            return importFromEdhrec(commanderName);
        }

        // EDHREC commander page: https://edhrec.com/commanders/edgar-markov
        if (url.contains("edhrec.com/commanders/")) {
            String slug = url.replaceAll(".*/commanders/([^/?#]+).*", "$1");
            String commanderName = slug.replace("-", " ");
            return importFromEdhrec(commanderName);
        }

        throw new IllegalArgumentException("Unsupported URL: " + url
                + "\nSupported: archidekt.com/decks/..., edhrec.com/average-decks/..., edhrec.com/commanders/...");
    }

    // ══════════════════════════════════════════════════════════
    // Forge .dck Export
    // ══════════════════════════════════════════════════════════

    /**
     * Convert a DeckProfile to Forge .dck format.
     *
     * Format:
     *   [metadata]
     *   Name=Edgar Markov — EDHREC Average
     *   [Commander]
     *   1 Edgar Markov
     *   [Main]
     *   1 Blood Artist
     *   1 Sol Ring
     *   ...
     */
    public static String toDckFormat(DeckProfile profile) {
        StringBuilder sb = new StringBuilder();
        sb.append("[metadata]\n");
        sb.append("Name=").append(profile.name != null ? profile.name : "Imported Deck").append("\n");
        sb.append("\n");

        // Commander zone
        sb.append("[Commander]\n");
        for (var entry : profile.commanders.entrySet()) {
            sb.append(entry.getValue()).append(" ").append(entry.getKey()).append("\n");
        }
        sb.append("\n");

        // Mainboard
        sb.append("[Main]\n");
        for (var entry : profile.mainboard.entrySet()) {
            sb.append(entry.getValue()).append(" ").append(entry.getKey()).append("\n");
        }

        return sb.toString();
    }

    /**
     * Save a DeckProfile as a Forge .dck file.
     *
     * @param profile The deck to save
     * @param outputDir Directory to save into
     * @return Path to the saved .dck file
     */
    public static Path saveToDckFile(DeckProfile profile, String outputDir) throws IOException {
        String safeName = sanitizeFileName(profile.name);
        Path outPath = Path.of(outputDir, safeName + ".dck");
        Files.createDirectories(outPath.getParent());
        Files.writeString(outPath, toDckFormat(profile));
        System.out.printf("  [Export] Saved .dck file: %s%n", outPath);
        return outPath;
    }

    // ══════════════════════════════════════════════════════════
    // Helpers
    // ══════════════════════════════════════════════════════════

    /**
     * Convert commander name to EDHREC URL slug.
     * "Edgar Markov" → "edgar-markov"
     * "Atraxa, Praetors' Voice" → "atraxa-praetors-voice"
     */
    static String toEdhrecSlug(String commanderName) {
        return commanderName.toLowerCase()
                .replaceAll("[',.]", "")
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("^-|-$", "");
    }

    private static String sanitizeFileName(String name) {
        if (name == null) return "imported-deck";
        return name.replaceAll("[^a-zA-Z0-9 _-]", "")
                .replaceAll("\\s+", "_")
                .trim();
    }

    private static String httpGet(String url) throws IOException, InterruptedException {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("User-Agent", USER_AGENT)
                .timeout(Duration.ofSeconds(30))
                .GET()
                .build();

        HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());

        if (resp.statusCode() != 200) {
            throw new IOException("HTTP " + resp.statusCode() + " fetching " + url + ": " + resp.body().substring(0, Math.min(200, resp.body().length())));
        }

        return resp.body();
    }
}
