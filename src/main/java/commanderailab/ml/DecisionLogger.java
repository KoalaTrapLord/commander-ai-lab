package commanderailab.ml;

import commanderailab.schema.DecisionSnapshot;
import commanderailab.schema.JsonExporter;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/**
 * DecisionLogger — Writes decision snapshots to JSONL files for ML training.
 *
 * Each game's decisions are appended as JSON lines to a batch-specific file.
 * Format: one DecisionSnapshot JSON object per line (JSONL/ndjson).
 *
 * Output path: results/ml-decisions-{batchId}.jsonl
 *
 * Usage from BatchRunner:
 *   DecisionLogger logger = new DecisionLogger(resultsDir, batchId);
 *   // After each game:
 *   logger.logGameDecisions(gameId, decisions, deckMeta);
 *   // After batch:
 *   logger.close();
 */
public class DecisionLogger {

    private final Path outputPath;
    private BufferedWriter writer;
    private int totalDecisions = 0;
    private int totalGames = 0;

    /**
     * @param resultsDir  Directory to write JSONL files (e.g., "results")
     * @param batchId     Batch identifier for file naming
     */
    public DecisionLogger(String resultsDir, String batchId) throws IOException {
        Path dir = Path.of(resultsDir);
        if (!Files.exists(dir)) {
            Files.createDirectories(dir);
        }
        this.outputPath = dir.resolve("ml-decisions-" + batchId + ".jsonl");
        this.writer = Files.newBufferedWriter(outputPath, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);

        System.out.println("[ML] Decision logger writing to: " + outputPath.toAbsolutePath());
    }

    /**
     * Log all decisions from a single game.
     *
     * @param decisions    Decision snapshots extracted from the game
     * @param deckMeta     Metadata to attach: {seatIndex → {deckName, commander, archetype}}
     * @param gameOutcome  "win_seat_0", "win_seat_1", "draw"
     */
    public void logGameDecisions(List<DecisionSnapshot> decisions,
                                 Map<Integer, Map<String, String>> deckMeta,
                                 String gameOutcome) {
        if (decisions == null || decisions.isEmpty()) return;

        try {
            for (DecisionSnapshot snap : decisions) {
                // Serialize to JSON using our lightweight exporter
                String json = serializeDecision(snap, deckMeta, gameOutcome);
                writer.write(json);
                writer.newLine();
                totalDecisions++;
            }
            writer.flush();
            totalGames++;
        } catch (IOException e) {
            System.err.println("[ML] Failed to write decisions: " + e.getMessage());
        }
    }

    /**
     * Serialize a DecisionSnapshot to a compact JSON string.
     * Uses manual JSON building to avoid adding Gson/Jackson dependency.
     */
    private String serializeDecision(DecisionSnapshot snap,
                                     Map<Integer, Map<String, String>> deckMeta,
                                     String gameOutcome) {
        StringBuilder sb = new StringBuilder(2048);
        sb.append("{");

        // Game context
        appendString(sb, "game_id", snap.gameId); sb.append(",");
        appendInt(sb, "turn", snap.turnNumber); sb.append(",");
        appendString(sb, "phase", snap.phase); sb.append(",");
        appendInt(sb, "active_seat", snap.activeSeat); sb.append(",");
        appendString(sb, "game_outcome", gameOutcome); sb.append(",");

        // Deck metadata for active player
        if (deckMeta != null && deckMeta.containsKey(snap.activeSeat)) {
            Map<String, String> meta = deckMeta.get(snap.activeSeat);
            sb.append("\"deck_name\":").append(jsonStr(meta.getOrDefault("name", ""))).append(",");
            sb.append("\"commander\":").append(jsonStr(meta.getOrDefault("commander", ""))).append(",");
            sb.append("\"archetype\":").append(jsonStr(meta.getOrDefault("archetype", "midrange"))).append(",");
        }

        // Players array
        sb.append("\"players\":[");
        for (int i = 0; i < snap.players.size(); i++) {
            if (i > 0) sb.append(",");
            serializePlayer(sb, snap.players.get(i));
        }
        sb.append("],");

        // Action
        sb.append("\"action\":{");
        if (snap.action != null) {
            appendString(sb, "type", snap.action.type); sb.append(",");
            appendString(sb, "card", snap.action.cardName != null ? snap.action.cardName : ""); sb.append(",");
            appendString(sb, "target", snap.action.targetDescription != null ? snap.action.targetDescription : ""); sb.append(",");
            appendString(sb, "raw", truncate(snap.action.rawLogLine, 200));
        }
        sb.append("}");

        sb.append("}");
        return sb.toString();
    }

    private void serializePlayer(StringBuilder sb, DecisionSnapshot.PlayerSnapshot ps) {
        sb.append("{");
        appendInt(sb, "seat", ps.seatIndex); sb.append(",");
        appendInt(sb, "life", ps.lifeTotal); sb.append(",");
        appendInt(sb, "cmdr_dmg", ps.commanderDamageTaken); sb.append(",");
        appendInt(sb, "mana", ps.manaAvailable); sb.append(",");
        appendInt(sb, "cmdr_tax", ps.commanderTax); sb.append(",");
        appendInt(sb, "creatures", ps.creaturesOnField); sb.append(",");
        appendInt(sb, "lands", ps.landCount); sb.append(",");

        // Zone card lists
        sb.append("\"hand\":").append(jsonList(ps.hand)).append(",");
        sb.append("\"battlefield\":").append(jsonList(ps.battlefield)).append(",");
        sb.append("\"graveyard\":").append(jsonList(ps.graveyard)).append(",");
        sb.append("\"command_zone\":").append(jsonList(ps.commandZone));

        sb.append("}");
    }

    // ── JSON helpers ─────────────────────────────────────────

    private void appendString(StringBuilder sb, String key, String value) {
        sb.append("\"").append(key).append("\":").append(jsonStr(value));
    }

    private void appendInt(StringBuilder sb, String key, int value) {
        sb.append("\"").append(key).append("\":").append(value);
    }

    private String jsonStr(String s) {
        if (s == null) return "null";
        return "\"" + s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t") + "\"";
    }

    private String jsonList(List<String> items) {
        if (items == null || items.isEmpty()) return "[]";
        StringBuilder sb = new StringBuilder();
        sb.append("[");
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(jsonStr(items.get(i)));
        }
        sb.append("]");
        return sb.toString();
    }

    private String truncate(String s, int maxLen) {
        if (s == null) return "";
        return s.length() <= maxLen ? s : s.substring(0, maxLen);
    }

    /**
     * Close the writer and print summary.
     */
    public void close() {
        try {
            if (writer != null) {
                writer.close();
            }
            System.out.printf("[ML] Decision log complete: %d decisions from %d games → %s%n",
                    totalDecisions, totalGames, outputPath.toAbsolutePath());
        } catch (IOException e) {
            System.err.println("[ML] Failed to close decision logger: " + e.getMessage());
        }
    }

    public Path getOutputPath() {
        return outputPath;
    }

    public int getTotalDecisions() {
        return totalDecisions;
    }
}
