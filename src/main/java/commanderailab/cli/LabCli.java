package commanderailab.cli;

import commanderailab.ai.*;
import commanderailab.analytics.DeckAnalyzer;
import commanderailab.analytics.DeckAnalyzer.DeckAnalysis;
import commanderailab.batch.*;
import commanderailab.db.LabDatabase;
import commanderailab.meta.*;
import commanderailab.meta.DeckProfile.DeckSource;
import commanderailab.schema.*;
import commanderailab.schema.BatchResult.*;
import commanderailab.stats.StatsAggregator;
import picocli.CommandLine;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

import java.io.File;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.Callable;

/**
 * LabCli — Command-line entry point for Commander AI Lab v3.
 *
 * v3 adds:
 *   --import-url     Import deck from URL (Archidekt, EDHREC)
 *   --import-text    Import deck from text file (card list)
 *   --commander-meta Use EDHREC average deck for a commander name
 *   --meta-file      Custom commander→meta mapping JSON
 *   --import-to      Directory to save imported .dck files
 */
@Command(
    name = "commander-ai-lab",
    mixinStandardHelpOptions = true,
    version = "Commander AI Lab v3.0.0",
    description = "Headless batch simulation for 3-AI MTG Commander pods with deck import & meta lookup."
)
public class LabCli implements Callable<Integer> {

    @Option(names = {"--forge-jar", "-F"}, required = true,
            description = "Path to Forge desktop JAR (forge-gui-desktop-XXX-jar-with-dependencies.jar)")
    private String forgeJarPath;

    @Option(names = {"--forge-dir", "-W"}, required = true,
            description = "Working directory for Forge (folder containing res/ — usually forge-gui/)")
    private String forgeWorkDir;

    @Option(names = {"--deck1", "-d1"}, defaultValue = "",
            description = "Commander deck name for seat 0 (as it appears in Forge's deck list)")
    private String deck1;

    @Option(names = {"--deck2", "-d2"}, defaultValue = "",
            description = "Commander deck name for seat 1")
    private String deck2;

    @Option(names = {"--deck3", "-d3"}, defaultValue = "",
            description = "Commander deck name for seat 2")
    private String deck3;

    @Option(names = {"--commander1", "-c1"}, defaultValue = "",
            description = "Commander card name for seat 0 (for display; uses deck name if blank)")
    private String commander1;

    @Option(names = {"--commander2", "-c2"}, defaultValue = "",
            description = "Commander card name for seat 1")
    private String commander2;

    @Option(names = {"--commander3", "-c3"}, defaultValue = "",
            description = "Commander card name for seat 2")
    private String commander3;

    @Option(names = {"--games", "-n"}, defaultValue = "10",
            description = "Number of games to simulate (default: 10)")
    private int numGames;

    @Option(names = {"--threads", "-t"}, defaultValue = "1",
            description = "Number of parallel threads (default: 1, 0 or -1 for auto-detect based on CPU cores)")
    private int threads;

    @Option(names = {"--seed", "-s"}, defaultValue = "",
            description = "Master RNG seed for reproducibility (blank for random)")
    private String seed;

    @Option(names = {"--output", "-o"}, defaultValue = "results/batch-latest.json",
            description = "Output JSON file path")
    private String outputPath;

    @Option(names = {"--clock", "-c"}, defaultValue = "120",
            description = "Max seconds per game before draw (default: 120)")
    private int clockSeconds;

    @Option(names = {"--verbose", "-v"}, defaultValue = "false",
            description = "Show full Forge output (not just parsed results)")
    private boolean verbose;

    // ── v2 Options ──────────────────────────────────────────────

    @Option(names = {"--profile", "-p"}, defaultValue = "default",
            description = "AI behavior profile: default, aggro, control, combo, midrange")
    private String profileName;

    @Option(names = {"--analyze"}, defaultValue = "false",
            description = "Run deck analysis before batch (shows mana curve, roles, health checks)")
    private boolean analyzeDeck;

    @Option(names = {"--db"}, defaultValue = "lab.db",
            description = "SQLite database file for result persistence (default: lab.db)")
    private String dbPath;

    @Option(names = {"--no-db"}, defaultValue = "false",
            description = "Disable SQLite persistence (results only saved to JSON file)")
    private boolean noDb;

    @Option(names = {"--decks-dir"}, defaultValue = "",
            description = "Path to Commander decks folder (for --analyze, default: %%APPDATA%%/Forge/decks/commander)")
    private String decksDir;

    // ── v3 Options — Deck Import & Meta ─────────────────────────

    @Option(names = {"--import-url"},
            description = "Import deck from URL (Archidekt, EDHREC). Can specify 1-3 times for each seat.")
    private List<String> importUrls;

    @Option(names = {"--import-text"},
            description = "Import deck from text file (card list). Can specify 1-3 times for each seat.")
    private List<String> importTextFiles;

    @Option(names = {"--commander-meta"},
            description = "Fetch EDHREC average deck by commander name. Can specify 1-3 times for each seat.")
    private List<String> commanderMeta;

    @Option(names = {"--meta-file"}, defaultValue = "commander-meta.json",
            description = "Path to commander→meta deck mapping JSON (default: commander-meta.json)")
    private String metaFile;

    @Option(names = {"--import-to"}, defaultValue = "",
            description = "Directory to save imported .dck files (default: Forge decks/commander dir)")
    private String importTo;

    @Option(names = {"--list-meta"}, defaultValue = "false",
            description = "List available commanders in the meta mapping and exit")
    private boolean listMeta;

    // ── v4 Options — ML Decision Logging ─────────────────────────

    @Option(names = {"--ml-log"}, defaultValue = "false",
            description = "Enable ML decision logging: extract state+action snapshots for RL training")
    private boolean mlLog;

    // ── v5 Options — Learned Policy ─────────────────────────────

    @Option(names = {"--learned-policy"}, defaultValue = "false",
            description = "Use trained neural network policy (requires running lab API server with model loaded)")
    private boolean useLearnedPolicy;

    @Option(names = {"--policy-server"}, defaultValue = "http://localhost:8080",
            description = "Policy server URL (default: http://localhost:8080)")
    private String policyServerUrl;

    @Option(names = {"--policy-style"}, defaultValue = "midrange",
            description = "Playstyle hint for learned policy: aggro, control, midrange, combo")
    private String policyStyle;

    @Option(names = {"--policy-greedy"}, defaultValue = "true",
            description = "Use greedy (argmax) action selection for learned policy (default: true)")
    private boolean policyGreedy;

    // ── v6 Options — Performance (Issues #3-#5) ─────────────────

    @Option(names = {"--ai-simplified"}, defaultValue = "false",
            description = "Use simplified/faster AI profile for simulations (less lookahead, faster games)")
    private boolean aiSimplified;

    @Option(names = {"--ai-think-time"}, defaultValue = "-1",
            description = "Cap AI think time in ms per decision (-1 for unlimited, 500-2000 recommended)")
    private int aiThinkTimeMs;

    @Option(names = {"--max-queue"}, defaultValue = "-1",
            description = "Max concurrent Forge subprocesses for backpressure (-1 for unlimited)")
    private int maxQueueDepth;

    @Option(names = {"--benchmark"}, defaultValue = "false",
            description = "Run a single-game benchmark before the batch and report throughput metrics")
    private boolean benchmark;

    @Option(names = {"--java17"}, defaultValue = "",
            description = "Path to Java 17 executable for running Forge (Forge requires Java 17, not 25+)")
    private String java17Path;

    @Override
    public Integer call() throws Exception {
        System.out.println("╔══════════════════════════════════════════════════╗");
        System.out.println("║         Commander AI Lab  v3.0.0                ║");
        System.out.println("║    3-AI Headless Batch Sim + Deck Import/Meta   ║");
        System.out.println("╚══════════════════════════════════════════════════╝");
        System.out.println();

        // Load meta mapping
        CommanderMetaService.loadMapping(metaFile);

        // Handle --list-meta
        if (listMeta) {
            printMetaList();
            return 0;
        }

        // Validate Forge paths
        if (!new File(forgeJarPath).exists()) {
            System.err.println("ERROR: Forge JAR not found: " + forgeJarPath);
            return 1;
        }
        if (!new File(forgeWorkDir).isDirectory()) {
            System.err.println("ERROR: Forge work directory not found: " + forgeWorkDir);
            return 1;
        }

        // Resolve import-to directory
        String importDir = resolveImportDir();

        // Build deck info (with possible imports)
        List<DeckInfo> decks = buildDeckInfoList(importDir);
        if (decks == null) return 1; // Error already printed

        System.out.printf("Pod:       %s  vs  %s  vs  %s%n",
                decks.get(0).deckName, decks.get(1).deckName, decks.get(2).deckName);
        for (DeckInfo d : decks) {
            if (d.source != null && !d.source.isEmpty()) {
                System.out.printf("  Seat %d:  %s → %s (%s)%n",
                        d.seatIndex, d.commanderName, d.source, d.sourceUrl != null ? d.sourceUrl : "");
            }
        }
        System.out.printf("Games:     %d%n", numGames);
        // Issue #5: Auto-detect thread count
        int effectiveThreads = threads;
        if (threads <= 0) {
            effectiveThreads = MultiThreadBatchRunner.detectOptimalThreads();
        }
        System.out.printf("Threads:   %d%s%n", effectiveThreads,
                threads <= 0 ? " (auto-detected)" : "");
        System.out.printf("Clock:     %ds per game%n", clockSeconds);

        Long masterSeed = seed.isEmpty() ? null : Long.parseLong(seed);
        if (masterSeed != null) {
            System.out.printf("Seed:      %d%n", masterSeed);
        }
        System.out.println();

        // Choose AI policy and profile
        AiProfile profile = AiProfile.byName(profileName);
        AiPolicy policy;

        if (useLearnedPolicy) {
            commanderailab.ml.LearnedPolicy learned =
                new commanderailab.ml.LearnedPolicy(policyServerUrl, policyStyle, policyGreedy);
            if (learned.connect()) {
                policy = learned;
                System.out.printf("AI Policy: learned-policy (server=%s, style=%s, greedy=%s)%n",
                    policyServerUrl, policyStyle, policyGreedy);
            } else {
                System.out.println("[ML] Learned policy unavailable — falling back to Forge built-in AI");
                policy = new ForgeBuiltinPolicy();
            }
        } else {
            policy = new ForgeBuiltinPolicy();
        }

        System.out.printf("AI Policy: %s%n", policy.getName());
        System.out.printf("AI Profile: %s — %s%n", profile.getName(), profile.getDescription());
        System.out.printf("Engine:    Forge sim (headless)%n");
        System.out.println();

        // v2: Deck analysis (if requested)
        if (analyzeDeck) {
            String resolvedDecksDir = decksDir.isEmpty() ? resolveForgeDecksDir() : decksDir;
            if (resolvedDecksDir != null && !resolvedDecksDir.isEmpty()) {
                System.out.println("═══ DECK ANALYSIS ═══");
                for (DeckInfo deck : decks) {
                    try {
                        DeckAnalysis analysis = DeckAnalyzer.analyzeFromForge(resolvedDecksDir, deck.deckName);
                        DeckAnalyzer.printSummary(analysis);
                        System.out.println();
                    } catch (Exception e) {
                        System.out.printf("  [WARN] Could not analyze %s: %s%n", deck.deckName, e.getMessage());
                    }
                }
            } else {
                System.out.println("  [WARN] --decks-dir not set and auto-detect failed. Skipping deck analysis.");
            }
        }

        // Run simulations
        long startTime = System.currentTimeMillis();
        List<GameResult> games;

        // Always run verbose (quiet=false) to capture combat stats from Forge game log.
        // The --verbose flag now controls whether full output is echoed to console,
        // but the parser always gets the full log for stat extraction.
        boolean quietMode = false;  // Never quiet — we need verbose output for combat stats

        // Resolve Java 17 path for Forge subprocess
        String resolvedJava = resolveJava17Path();
        System.out.printf("Java:      %s%n", resolvedJava);

        // Issue #4: Print AI optimization settings
        if (aiSimplified || aiThinkTimeMs > 0) {
            System.out.printf("AI Opts:   simplified=%s, thinkTime=%s%n",
                    aiSimplified, aiThinkTimeMs > 0 ? aiThinkTimeMs + "ms" : "unlimited");
        }
        System.out.println();

        // Issue #4: Single-game benchmark if requested
        if (benchmark) {
            System.out.println("═══ BENCHMARK (single game) ═══");
            BatchRunner benchRunner = new BatchRunner(
                    forgeJarPath, forgeWorkDir, decks, policy, quietMode, clockSeconds, resolvedJava);
            benchRunner.setAiOptimization(aiSimplified, aiThinkTimeMs);
            long benchStart = System.currentTimeMillis();
            List<GameResult> benchGames = benchRunner.runBatchSingleThread(1, 42L);
            long benchElapsed = System.currentTimeMillis() - benchStart;
            if (!benchGames.isEmpty()) {
                GameResult bg = benchGames.get(0);
                System.out.printf("  Wall time:    %dms%n", benchElapsed);
                System.out.printf("  Forge time:   %dms%n", bg.elapsedMs);
                System.out.printf("  JVM overhead: ~%dms%n", benchElapsed - bg.elapsedMs);
                System.out.printf("  Turns:        %d%n", bg.totalTurns);
                System.out.printf("  Throughput:   %.4f sims/sec%n", 1000.0 / benchElapsed);
            }
            System.out.println();
        }

        if (effectiveThreads > 1) {
            System.out.printf("Running %d games across %d threads...%n%n", numGames, effectiveThreads);
            MultiThreadBatchRunner mtRunner = new MultiThreadBatchRunner(
                    forgeJarPath, forgeWorkDir, decks, policy, effectiveThreads, quietMode, clockSeconds, resolvedJava);
            mtRunner.setAiOptimization(aiSimplified, aiThinkTimeMs);
            if (maxQueueDepth > 0) {
                mtRunner.setMaxQueueDepth(maxQueueDepth);
            }
            games = mtRunner.runBatch(numGames, masterSeed);
        } else {
            System.out.printf("Running %d games (single thread)...%n%n", numGames);
            BatchRunner runner = new BatchRunner(
                    forgeJarPath, forgeWorkDir, decks, policy, quietMode, clockSeconds, resolvedJava);
            runner.setAiOptimization(aiSimplified, aiThinkTimeMs);

            // v4: Enable ML decision logging if requested
            if (mlLog) {
                String batchId = UUID.randomUUID().toString().substring(0, 8);
                runner.enableMlLogging("results", batchId);
                System.out.println("[ML] Decision logging enabled — data will be saved to results/");
            }

            games = runner.runBatchSingleThread(numGames, masterSeed);

            // Close ML logger
            if (mlLog) {
                runner.closeMlLogger();
            }
        }

        long elapsedMs = System.currentTimeMillis() - startTime;

        // Compute stats
        Summary summary = StatsAggregator.computeSummary(games, decks, elapsedMs);

        // Build full BatchResult
        BatchResult result = new BatchResult();
        result.metadata = new Metadata();
        result.metadata.batchId = UUID.randomUUID().toString();
        result.metadata.timestamp = Instant.now().toString();
        result.metadata.totalGames = numGames;
        result.metadata.completedGames = games.size();
        result.metadata.engineVersion = "forge-2.0.12-SNAPSHOT";
        result.metadata.masterSeed = masterSeed;
        result.metadata.threads = threads;
        result.metadata.elapsedMs = elapsedMs;
        result.decks = decks;
        result.games = games;
        result.summary = summary;

        // Export JSON
        JsonExporter.writeToFile(result, outputPath);
        System.out.println();

        // Print summary to console
        printSummary(result);

        // Validate output
        String json = JsonExporter.toJson(result);
        boolean valid = JsonExporter.validateBasicStructure(json);
        System.out.printf("%nJSON validation: %s%n", valid ? "PASSED" : "FAILED");
        System.out.printf("Output written to: %s%n", outputPath);

        // v2: Save to SQLite
        if (!noDb) {
            try (LabDatabase db = new LabDatabase(dbPath)) {
                db.saveBatchResult(result);
                System.out.printf("Saved to database: %s%n", dbPath);

                // Also save deck analyses if we ran them
                if (analyzeDeck) {
                    String resolvedDecksDir = decksDir.isEmpty() ? resolveForgeDecksDir() : decksDir;
                    if (resolvedDecksDir != null) {
                        for (DeckInfo deck : decks) {
                            try {
                                DeckAnalysis analysis = DeckAnalyzer.analyzeFromForge(resolvedDecksDir, deck.deckName);
                                db.saveDeckAnalysis(analysis);
                            } catch (Exception ignore) { }
                        }
                    }
                }

                // Print global stats
                var globalStats = db.getGlobalStats();
                System.out.printf("%n═══ LIFETIME STATS ═══%n");
                System.out.printf("  Total Batches: %s  |  Total Games: %s  |  Unique Decks: %s%n",
                        globalStats.get("totalBatches"),
                        globalStats.get("totalGames"),
                        globalStats.get("uniqueDecks"));
            } catch (Exception e) {
                System.err.printf("WARNING: Database save failed: %s%n", e.getMessage());
            }
        }

        return 0;
    }

    // ══════════════════════════════════════════════════════════
    // Deck Info Construction (v3 — supports import)
    // ══════════════════════════════════════════════════════════

    private List<DeckInfo> buildDeckInfoList(String importDir) throws Exception {
        String[] deckNames = {deck1, deck2, deck3};
        String[] commanders = {commander1, commander2, commander3};

        // Build import lists for each seat
        DeckProfile[] imports = new DeckProfile[3];

        // Process --commander-meta flags
        if (commanderMeta != null) {
            for (int i = 0; i < Math.min(commanderMeta.size(), 3); i++) {
                String cmdrName = commanderMeta.get(i);
                System.out.printf("═══ IMPORT SEAT %d: Commander Meta — %s ═══%n", i, cmdrName);
                imports[i] = DeckImporter.importFromEdhrec(cmdrName);
            }
        }

        // Process --import-url flags (overrides commander-meta for same seat)
        if (importUrls != null) {
            for (int i = 0; i < Math.min(importUrls.size(), 3); i++) {
                if (imports[i] != null) continue; // Don't override if already set
                String url = importUrls.get(i);
                int seat = findNextEmptySeat(imports);
                if (seat < 0) break;
                System.out.printf("═══ IMPORT SEAT %d: URL — %s ═══%n", seat, url);
                imports[seat] = DeckImporter.importFromUrl(url);
            }
        }

        // Process --import-text flags
        if (importTextFiles != null) {
            for (int i = 0; i < Math.min(importTextFiles.size(), 3); i++) {
                String filePath = importTextFiles.get(i);
                int seat = findNextEmptySeat(imports);
                if (seat < 0) break;
                System.out.printf("═══ IMPORT SEAT %d: Text File — %s ═══%n", seat, filePath);
                String text = Files.readString(Path.of(filePath));
                imports[seat] = DeckImporter.importFromText(text, null);
            }
        }

        // Save imported decks to .dck files and set deck names
        for (int i = 0; i < 3; i++) {
            if (imports[i] != null) {
                DeckProfile profile = imports[i];
                Path dckPath = DeckImporter.saveToDckFile(profile, importDir);
                String savedName = dckPath.getFileName().toString().replace(".dck", "");
                deckNames[i] = savedName;
                if (profile.commander != null) {
                    commanders[i] = profile.commander;
                }
                System.out.printf("  Seat %d → saved as %s%n", i, dckPath);
                System.out.println();
            }
        }

        // Validate all 3 seats have decks
        for (int i = 0; i < 3; i++) {
            if (deckNames[i] == null || deckNames[i].isEmpty()) {
                System.err.printf("ERROR: Seat %d has no deck. Use --deck%d, --import-url, --import-text, or --commander-meta.%n", i, i + 1);
                return null;
            }
        }

        // Build DeckInfo list
        List<DeckInfo> list = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            DeckInfo d = new DeckInfo();
            d.seatIndex = i;
            d.deckFile = deckNames[i];
            d.deckName = deckNames[i];
            d.commanderName = commanders[i].isEmpty() ? deckNames[i] : commanders[i];
            d.colorIdentity = List.of();
            d.cardCount = 100;

            // v3: Populate source metadata from import
            if (imports[i] != null) {
                DeckProfile p = imports[i];
                d.source = p.source != null ? p.source.label() : null;
                d.sourceUrl = p.sourceUrl;
                d.archetype = p.archetype;
                d.colorIdentity = p.colorIdentity != null ? p.colorIdentity : List.of();
                d.cardCount = p.totalCards;
                if (p.sampleSize != null) d.sampleSize = p.sampleSize;
                d.importedAt = p.importedAt;
            }

            list.add(d);
        }
        return list;
    }

    private int findNextEmptySeat(DeckProfile[] imports) {
        for (int i = 0; i < imports.length; i++) {
            if (imports[i] == null) return i;
        }
        return -1;
    }

    // ══════════════════════════════════════════════════════════
    // Helpers
    // ══════════════════════════════════════════════════════════

    private String resolveImportDir() {
        if (!importTo.isEmpty()) return importTo;

        // Try Forge decks/commander dir
        String decksDir = resolveForgeDecksDir();
        if (decksDir != null) return decksDir;

        // Fallback to local directory
        return "imported-decks";
    }

    private void printMetaList() {
        System.out.println("═══ AVAILABLE COMMANDERS (Meta Mapping) ═══");
        System.out.println();
        for (String cmdr : CommanderMetaService.getAllCommanders()) {
            var entries = CommanderMetaService.getMetaDecks(cmdr);
            for (var entry : entries) {
                System.out.printf("  %-35s  %-20s  %s%n",
                        cmdr,
                        entry.archetype != null ? entry.archetype : "",
                        entry.source);
            }
        }
        System.out.printf("%n  Total: %d commanders%n", CommanderMetaService.getAllCommanders().size());
        System.out.println("  Use --commander-meta \"Commander Name\" to fetch the EDHREC average deck.");
    }

    private void printSummary(BatchResult result) {
        System.out.println("╔══════════════════════════════════════════════════════════╗");
        System.out.println("║                    BATCH RESULTS                        ║");
        System.out.println("╠══════════════════════════════════════════════════════════╣");

        Summary s = result.summary;
        for (DeckSummary ds : s.perDeck) {
            DeckInfo deckInfo = result.decks.get(ds.seatIndex);
            System.out.printf("║  Seat %d: %-40s     ║%n", ds.seatIndex, ds.deckName);
            if (deckInfo.source != null && !deckInfo.source.isEmpty()) {
                System.out.printf("║    Source:     %-36s     ║%n", deckInfo.source);
            }
            System.out.printf("║    Win Rate:     %5.1f%%  (%d W / %d L / %d D)%n",
                    ds.winRate * 100, ds.wins, ds.losses, ds.draws);
            System.out.printf("║    Avg Turns:    %5s%n",
                    ds.avgTurnsToWin != null ? String.format("%.1f", ds.avgTurnsToWin) : "N/A");
            System.out.printf("║    Avg Mulligan: %5.2f%n", ds.avgMulligans);
            System.out.printf("║    Avg Life:     %5.1f%n", ds.avgFinalLife);

            if (ds.winConditionBreakdown != null && ds.wins > 0) {
                WinConditionBreakdown b = ds.winConditionBreakdown;
                System.out.printf("║    Win By: Combat=%d  CmdrDmg=%d  Combo=%d  Drain=%d  Mill=%d%n",
                        b.combat_damage, b.commander_damage, b.combo_alt_win, b.life_drain, b.mill);
            }
            System.out.println("║");
        }

        System.out.println("╠══════════════════════════════════════════════════════════╣");
        System.out.printf("║  Games: %-5d   Avg Turns: %-6.1f   Sims/sec: %-6.2f%n",
                result.metadata.completedGames, s.avgGameTurns, s.simsPerSecond);
        System.out.printf("║  Wall Time: %.1fs%n", result.metadata.elapsedMs / 1000.0);
        System.out.println("╚══════════════════════════════════════════════════════════╝");
    }

    public static void main(String[] args) {
        int exitCode = new CommandLine(new LabCli()).execute(args);
        System.exit(exitCode);
    }

    /**
     * Resolve the Java 17 executable path for running Forge subprocesses.
     * Forge requires Java 17 — newer versions (25+) cause ExceptionInInitializerError.
     *
     * Priority: --java17 flag > auto-detect Adoptium > auto-detect Oracle > system "java"
     */
    private String resolveJava17Path() {
        // 1. Explicit --java17 flag
        if (java17Path != null && !java17Path.isEmpty()) {
            File f = new File(java17Path);
            if (f.exists()) return f.getAbsolutePath();
            System.err.println("WARNING: --java17 path not found: " + java17Path);
        }

        // 2. Auto-detect common Java 17 locations on Windows
        String[] candidates = {
            "C:\\Program Files\\Eclipse Adoptium\\jdk-17.0.18.8-hotspot\\bin\\java.exe",
            "C:\\Program Files\\Java\\jdk-17\\bin\\java.exe",
            "C:\\Program Files\\Eclipse Adoptium\\jdk-17\\bin\\java.exe",
        };

        // Also scan for any jdk-17* in Adoptium and Java dirs
        String[] searchDirs = {
            "C:\\Program Files\\Eclipse Adoptium",
            "C:\\Program Files\\Java",
        };
        for (String dir : searchDirs) {
            File d = new File(dir);
            if (d.isDirectory()) {
                File[] children = d.listFiles();
                if (children != null) {
                    for (File child : children) {
                        if (child.isDirectory() && child.getName().startsWith("jdk-17")) {
                            File java = new File(child, "bin/java.exe");
                            if (java.exists()) return java.getAbsolutePath();
                            // Linux/Mac
                            java = new File(child, "bin/java");
                            if (java.exists()) return java.getAbsolutePath();
                        }
                    }
                }
            }
        }

        // 3. Check explicit candidate paths
        for (String path : candidates) {
            File f = new File(path);
            if (f.exists()) return f.getAbsolutePath();
        }

        // 4. Fallback to system java (may be wrong version)
        System.err.println("WARNING: Java 17 not found. Forge may crash on Java 25+.");
        System.err.println("         Install Adoptium JDK 17 or use --java17 <path>");
        return "java";
    }

    /**
     * Auto-detect Forge Commander decks directory.
     */
    private String resolveForgeDecksDir() {
        // Windows: %APPDATA%\Forge\decks\commander
        String appdata = System.getenv("APPDATA");
        if (appdata != null) {
            File candidate = new File(appdata, "Forge/decks/commander");
            if (candidate.isDirectory()) return candidate.getAbsolutePath();
        }
        // Linux/Mac
        String home = System.getProperty("user.home");
        for (String path : new String[]{"/.forge/decks/commander", "/Forge/decks/commander"}) {
            File candidate = new File(home + path);
            if (candidate.isDirectory()) return candidate.getAbsolutePath();
        }
        return null;
    }
}
