package commanderailab.schema;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

/**
 * JsonExporter — Serializes BatchResult to JSON files.
 *
 * Output conforms to batch-result-schema.json.
 */
public class JsonExporter {

    private static final Gson GSON = new GsonBuilder()
            .setPrettyPrinting()
            .serializeNulls()
            .disableHtmlEscaping()
            .create();

    /**
     * Serialize a BatchResult to a JSON string.
     */
    public static String toJson(BatchResult result) {
        return GSON.toJson(result);
    }

    /**
     * Write a BatchResult to a JSON file.
     *
     * @param result   The batch result to export
     * @param filePath Output file path (e.g., "results/ml-decision-20260306-001.json")
     * @throws IOException if file cannot be written
     */
    public static void writeToFile(BatchResult result, String filePath) throws IOException {
        Path path = Paths.get(filePath);

        // Ensure parent directories exist
        if (path.getParent() != null) {
            Files.createDirectories(path.getParent());
        }

        String json = toJson(result);
        Files.writeString(path, json, StandardCharsets.UTF_8);
    }

    /**
     * Read a BatchResult from a JSON file.
     */
    public static BatchResult readFromFile(String filePath) throws IOException {
        String json = Files.readString(Paths.get(filePath), StandardCharsets.UTF_8);
        return GSON.fromJson(json, BatchResult.class);
    }

    /**
     * Validate that a JSON string contains all required top-level keys.
     * (Lightweight validation — full JSON Schema validation would need a library.)
     */
    public static boolean validateBasicStructure(String json) {
        try {
            BatchResult result = GSON.fromJson(json, BatchResult.class);
            return result.metadata != null
                    && result.decks != null && result.decks.size() >= 3 && result.decks.size() <= 4
                    && result.games != null
                    && result.summary != null
                    && result.metadata.schemaVersion.equals("1.0.0")
                    && result.metadata.podSize >= 3 && result.metadata.podSize <= 4;
        } catch (Exception e) {
            return false;
        }
    }
}
