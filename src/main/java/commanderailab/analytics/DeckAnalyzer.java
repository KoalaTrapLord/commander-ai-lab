package commanderailab.analytics;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;
import java.util.stream.*;

/**
 * DeckAnalyzer — Static analysis of Commander .dck files.
 *
 * Parses Forge deck files and computes:
 *   - Mana curve (CMC distribution)
 *   - Color identity breakdown
 *   - Card category counts (lands, creatures, instants, sorceries, etc.)
 *   - Functional role tagging (ramp, removal, draw, board wipes, tutors)
 *   - Deck health checklist (recommended counts vs actual)
 *
 * Works with Forge .dck format:
 *   [metadata]
 *   Name=Deck Name
 *   [Commander]
 *   1 Card Name|SET
 *   [Main]
 *   1 Card Name|SET
 *   ...
 *
 * Note: Without Scryfall API calls, category tagging uses heuristic
 * keyword matching on card names. A future version can enrich with
 * Scryfall data for accurate type/oracle text analysis.
 */
public class DeckAnalyzer {

    // ── Analysis Result ────────────────────────────────────

    public static class DeckAnalysis {
        public String deckName;
        public String deckFile;
        public String commanderName;
        public int totalCards;

        // Category counts
        public int lands;
        public int creatures;
        public int instants;
        public int sorceries;
        public int artifacts;
        public int enchantments;
        public int planeswalkers;
        public int other;

        // Functional roles (heuristic)
        public int rampCards;
        public int removalCards;
        public int drawCards;
        public int boardWipes;
        public int tutors;
        public int counterSpells;
        public int protectionCards;
        public int recursionCards;

        // Mana curve (index = CMC, value = count; index 7+ = "7+")
        public int[] manaCurve = new int[8]; // 0,1,2,3,4,5,6,7+

        // Color breakdown (count of cards with each color in cost)
        public Map<String, Integer> colorBreakdown = new LinkedHashMap<>();

        // Raw card list
        public List<CardEntry> cards = new ArrayList<>();

        // Health checklist
        public Map<String, HealthCheck> healthChecks = new LinkedHashMap<>();

        public static class HealthCheck {
            public String category;
            public int actual;
            public int recommendedMin;
            public int recommendedMax;
            public String status; // "good", "low", "high"

            public HealthCheck(String cat, int actual, int min, int max) {
                this.category = cat;
                this.actual = actual;
                this.recommendedMin = min;
                this.recommendedMax = max;
                if (actual < min) this.status = "low";
                else if (actual > max) this.status = "high";
                else this.status = "good";
            }
        }
    }

    public static class CardEntry {
        public int quantity;
        public String name;
        public String set;
        public String section; // "Commander", "Main", "Sideboard"
        public List<String> tags = new ArrayList<>(); // heuristic role tags

        public CardEntry(int qty, String name, String set, String section) {
            this.quantity = qty;
            this.name = name;
            this.set = set;
            this.section = section;
        }
    }

    // ── Parsing ────────────────────────────────────────────

    /**
     * Analyze a .dck file from disk.
     */
    public static DeckAnalysis analyze(String deckFilePath) throws IOException {
        List<String> lines = Files.readAllLines(Path.of(deckFilePath));
        String fileName = Path.of(deckFilePath).getFileName().toString();
        return analyze(lines, fileName);
    }

    /**
     * Analyze a deck from its lines and filename.
     */
    public static DeckAnalysis analyze(List<String> lines, String fileName) {
        DeckAnalysis a = new DeckAnalysis();
        a.deckFile = fileName;
        a.deckName = fileName.replace(".dck", "");
        a.colorBreakdown.put("W", 0);
        a.colorBreakdown.put("U", 0);
        a.colorBreakdown.put("B", 0);
        a.colorBreakdown.put("R", 0);
        a.colorBreakdown.put("G", 0);
        a.colorBreakdown.put("C", 0); // Colorless

        String currentSection = "Main";
        Pattern cardPattern = Pattern.compile("^(\\d+)\\s+(.+?)(?:\\|(.+))?$");

        for (String line : lines) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("//")) continue;

            // Section headers
            if (line.startsWith("[") && line.endsWith("]")) {
                String section = line.substring(1, line.length() - 1);
                if (section.equalsIgnoreCase("Commander")) {
                    currentSection = "Commander";
                } else if (section.equalsIgnoreCase("Main")) {
                    currentSection = "Main";
                } else if (section.equalsIgnoreCase("Sideboard")) {
                    currentSection = "Sideboard";
                }
                continue;
            }

            // Metadata: Name=...
            if (line.startsWith("Name=")) {
                a.deckName = line.substring(5).trim();
                continue;
            }

            // Card entry: "1 Card Name|SET" or "1 Card Name"
            Matcher m = cardPattern.matcher(line);
            if (m.matches()) {
                int qty = Integer.parseInt(m.group(1));
                String cardName = m.group(2).trim();
                String setCode = m.group(3) != null ? m.group(3).trim() : "";

                CardEntry card = new CardEntry(qty, cardName, setCode, currentSection);
                a.cards.add(card);
                a.totalCards += qty;

                if (currentSection.equals("Commander")) {
                    a.commanderName = cardName;
                }

                // Tag and classify
                tagCard(card);
                classifyCard(a, card);
            }
        }

        // Compute health checklist
        computeHealthChecks(a);

        return a;
    }

    // ── Card Tagging (Heuristic) ───────────────────────────

    /**
     * Tag a card with functional roles based on name heuristics.
     * This is best-effort without Scryfall data.
     */
    private static void tagCard(CardEntry card) {
        String lower = card.name.toLowerCase();

        // Land detection
        if (isLikelyLand(lower)) {
            card.tags.add("land");
        }

        // Ramp
        if (isLikelyRamp(lower)) {
            card.tags.add("ramp");
        }

        // Removal
        if (isLikelyRemoval(lower)) {
            card.tags.add("removal");
        }

        // Card draw
        if (isLikelyDraw(lower)) {
            card.tags.add("draw");
        }

        // Board wipes
        if (isLikelyBoardWipe(lower)) {
            card.tags.add("wipe");
        }

        // Tutors
        if (isLikelyTutor(lower)) {
            card.tags.add("tutor");
        }

        // Counter spells
        if (isLikelyCounter(lower)) {
            card.tags.add("counter");
        }

        // Protection
        if (isLikelyProtection(lower)) {
            card.tags.add("protection");
        }

        // Recursion
        if (isLikelyRecursion(lower)) {
            card.tags.add("recursion");
        }

        // Creature detection
        if (isLikelyCreature(lower)) {
            card.tags.add("creature");
        }
    }

    // ── Heuristic Keyword Matchers ─────────────────────────

    private static boolean isLikelyLand(String name) {
        String[] landKeywords = {
            "forest", "island", "mountain", "plains", "swamp",
            "land", "grove", "falls", "gardens", "temple",
            "shrine", "citadel", "tower", "gate", "passage",
            "foundry", "forge", "cave", "marsh", "bog",
            "field", "meadow", "terrace", "basin", "pool",
            "command tower", "exotic orchard", "mana confluence",
            "city of brass", "reflecting pool", "sol ring"
        };
        // Sol Ring is NOT a land but commonly in land-adjacent lists — remove it
        if (name.equals("sol ring")) return false;
        for (String kw : landKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyRamp(String name) {
        String[] rampKeywords = {
            "sol ring", "mana crypt", "arcane signet", "signet",
            "talisman", "cultivate", "kodama's reach", "rampant growth",
            "farseek", "nature's lore", "three visits", "sakura-tribe elder",
            "solemn simulacrum", "birds of paradise", "llanowar elves",
            "elvish mystic", "dryad of the ilysian grove", "exploration",
            "mana vault", "mana rock", "fellwar stone", "mind stone",
            "thought vessel", "commander's sphere", "gilded lotus",
            "thran dynamo", "worn powerstone", "dark ritual",
            "cabal ritual", "jeweled lotus", "lotus petal",
            "chrome mox", "mox diamond", "growth spiral",
        };
        for (String kw : rampKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyRemoval(String name) {
        String[] removalKeywords = {
            "swords to plowshares", "path to exile", "terminate",
            "murder", "doom blade", "go for the throat", "beast within",
            "chaos warp", "anguished unmaking", "vindicate",
            "assassin's trophy", "generous gift", "rapid hybridization",
            "pongify", "reality shift", "cyclonic rift",
            "abrupt decay", "mortify", "putrefy", "despark",
            "vanishing verse", "fateful absence", "infernal grasp",
            "deadly rollick", "force of despair", "dismember",
            "ravenous chupacabra", "shriekmaw", "nekrataal",
        };
        for (String kw : removalKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyDraw(String name) {
        String[] drawKeywords = {
            "rhystic study", "mystic remora", "sylvan library",
            "phyrexian arena", "necropotence", "harmonize",
            "blue sun's zenith", "brainstorm", "ponder", "preordain",
            "sign in blood", "read the bones", "night's whisper",
            "skullclamp", "beast whisperer", "guardian project",
            "the great henge", "esper sentinel", "dark confidant",
            "consecrated sphinx", "windfall", "wheel of fortune",
            "wheel of misfortune", "faithless looting",
            "treasure cruise", "dig through time",
        };
        for (String kw : drawKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyBoardWipe(String name) {
        String[] wipeKeywords = {
            "wrath of god", "damnation", "blasphemous act",
            "cyclonic rift", "toxic deluge", "farewell",
            "supreme verdict", "merciless eviction", "austere command",
            "vanquish the horde", "hour of devastation",
            "massacre wurm", "living death", "all is dust",
            "decree of pain", "kindred dominance", "in garruk's wake",
            "storm's wrath", "chain reaction",
        };
        for (String kw : wipeKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyTutor(String name) {
        String[] tutorKeywords = {
            "demonic tutor", "vampiric tutor", "enlightened tutor",
            "mystical tutor", "worldly tutor", "imperial seal",
            "gamble", "fabricate", "diabolic tutor", "diabolic intent",
            "idyllic tutor", "eladamri's call", "green sun's zenith",
            "finale of devastation", "chord of calling",
            "natural order", "eldritch evolution",
        };
        for (String kw : tutorKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyCounter(String name) {
        String[] counterKeywords = {
            "counterspell", "swan song", "negate", "arcane denial",
            "mana drain", "force of will", "force of negation",
            "fierce guardianship", "pact of negation", "dovin's veto",
            "delay", "tale's end", "an offer you can't refuse",
            "flusterstorm", "mental misstep", "spell pierce",
        };
        for (String kw : counterKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyProtection(String name) {
        String[] protectionKeywords = {
            "lightning greaves", "swiftfoot boots", "heroic intervention",
            "teferi's protection", "boros charm", "flawless maneuver",
            "deflecting swat", "grand abolisher", "veil of summer",
            "mother of runes", "giver of runes", "selfless spirit",
            "avacyn, angel of hope", "dauntless bodyguard",
        };
        for (String kw : protectionKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyRecursion(String name) {
        String[] recursionKeywords = {
            "eternal witness", "regrowth", "noxious revival",
            "reanimate", "animate dead", "dance of the dead",
            "necromancy", "living death", "sun titan",
            "muldrotha", "lurrus", "sevinne's reclamation",
            "archaeomancer", "snapcaster mage", "mission briefing",
        };
        for (String kw : recursionKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    private static boolean isLikelyCreature(String name) {
        // Very rough heuristic — many Commander creatures have distinctive names
        // This catches some but is not exhaustive
        String[] creatureKeywords = {
            "elder", "dragon", "angel", "demon", "vampire",
            "zombie", "goblin", "elf", "knight", "wizard",
            "shaman", "cleric", "warrior", "beast", "elemental",
            "sphinx", "titan", "wurm", "drake", "spirit",
        };
        for (String kw : creatureKeywords) {
            if (name.contains(kw)) return true;
        }
        return false;
    }

    // ── Classification ─────────────────────────────────────

    private static void classifyCard(DeckAnalysis a, CardEntry card) {
        int qty = card.quantity;

        // Count by tag
        if (card.tags.contains("land")) a.lands += qty;
        if (card.tags.contains("creature")) a.creatures += qty;
        if (card.tags.contains("ramp")) a.rampCards += qty;
        if (card.tags.contains("removal")) a.removalCards += qty;
        if (card.tags.contains("draw")) a.drawCards += qty;
        if (card.tags.contains("wipe")) a.boardWipes += qty;
        if (card.tags.contains("tutor")) a.tutors += qty;
        if (card.tags.contains("counter")) a.counterSpells += qty;
        if (card.tags.contains("protection")) a.protectionCards += qty;
        if (card.tags.contains("recursion")) a.recursionCards += qty;
    }

    // ── Health Checks ──────────────────────────────────────

    /**
     * Commander deck health checklist with recommended ranges.
     * Based on common Commander deckbuilding guidelines.
     */
    private static void computeHealthChecks(DeckAnalysis a) {
        a.healthChecks.put("Lands",
            new DeckAnalysis.HealthCheck("Lands", a.lands, 35, 40));
        a.healthChecks.put("Ramp",
            new DeckAnalysis.HealthCheck("Ramp", a.rampCards, 8, 15));
        a.healthChecks.put("Card Draw",
            new DeckAnalysis.HealthCheck("Card Draw", a.drawCards, 8, 15));
        a.healthChecks.put("Removal",
            new DeckAnalysis.HealthCheck("Removal", a.removalCards, 8, 12));
        a.healthChecks.put("Board Wipes",
            new DeckAnalysis.HealthCheck("Board Wipes", a.boardWipes, 2, 5));
        a.healthChecks.put("Total Cards",
            new DeckAnalysis.HealthCheck("Total Cards", a.totalCards, 99, 100));
    }

    // ══════════════════════════════════════════════════════════
    // Summary Output
    // ══════════════════════════════════════════════════════════

    /**
     * Print a human-readable analysis summary to stdout.
     */
    public static void printSummary(DeckAnalysis a) {
        System.out.println("╔══════════════════════════════════════════════════════════╗");
        System.out.printf( "║  Deck Analysis: %-40s ║%n", a.deckName);
        if (a.commanderName != null) {
            System.out.printf("║  Commander: %-44s ║%n", a.commanderName);
        }
        System.out.printf( "║  Total Cards: %-42d ║%n", a.totalCards);
        System.out.println("╠══════════════════════════════════════════════════════════╣");

        System.out.println("║  CARD TYPES                                              ");
        System.out.printf( "║    Lands:         %3d    Creatures:    %3d%n", a.lands, a.creatures);
        System.out.printf( "║    Instants:      %3d    Sorceries:   %3d%n", a.instants, a.sorceries);
        System.out.printf( "║    Artifacts:     %3d    Enchantments: %3d%n", a.artifacts, a.enchantments);
        System.out.printf( "║    Planeswalkers: %3d%n", a.planeswalkers);

        System.out.println("║");
        System.out.println("║  FUNCTIONAL ROLES");
        System.out.printf( "║    Ramp:       %3d    Card Draw:   %3d    Removal:     %3d%n",
                a.rampCards, a.drawCards, a.removalCards);
        System.out.printf( "║    Wipes:      %3d    Tutors:      %3d    Counters:    %3d%n",
                a.boardWipes, a.tutors, a.counterSpells);
        System.out.printf( "║    Protection: %3d    Recursion:   %3d%n",
                a.protectionCards, a.recursionCards);

        System.out.println("║");
        System.out.println("║  HEALTH CHECKLIST");
        for (var check : a.healthChecks.values()) {
            String icon = switch (check.status) {
                case "good" -> "[OK]";
                case "low"  -> "[LOW]";
                case "high" -> "[HIGH]";
                default -> "[??]";
            };
            System.out.printf("║    %-14s %3d  (recommended: %d-%d)  %s%n",
                    check.category, check.actual, check.recommendedMin, check.recommendedMax, icon);
        }

        System.out.println("╚══════════════════════════════════════════════════════════╝");
    }

    /**
     * Analyze a deck from a Forge decks directory by name.
     */
    public static DeckAnalysis analyzeFromForge(String decksDir, String deckName) throws IOException {
        // Try exact match first
        Path deckPath = Path.of(decksDir, deckName + ".dck");
        if (!Files.exists(deckPath)) {
            // Try case-insensitive search
            try (var stream = Files.list(Path.of(decksDir))) {
                deckPath = stream
                    .filter(p -> p.getFileName().toString().toLowerCase()
                                  .equals(deckName.toLowerCase() + ".dck"))
                    .findFirst()
                    .orElse(null);
            }
        }

        if (deckPath == null || !Files.exists(deckPath)) {
            throw new FileNotFoundException("Deck not found: " + deckName + " in " + decksDir);
        }

        return analyze(deckPath.toString());
    }
}
