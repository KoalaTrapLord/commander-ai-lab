package commanderailab.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.java_websocket.WebSocket;
import org.java_websocket.handshake.ClientHandshake;
import org.java_websocket.server.WebSocketServer;

import java.net.InetSocketAddress;
import java.util.*;
import java.util.concurrent.*;

/**
 * GameWsServer — WebSocket server that exposes the Forge engine to a Unity/Godot client.
 *
 * Connect at: ws://localhost:7654
 *
 * Protocol:
 *   ENGINE -> CLIENT:  GameStateSnapshot JSON (pushed after every action resolves)
 *   CLIENT -> ENGINE:  PlayerAction JSON
 *
 * Message types (CLIENT -> ENGINE):
 *   { "type": "START_GAME",  "decks": ["DeckA","DeckB","DeckC","DeckD"], "seed": 12345 }
 *   { "type": "PLAYER_ACTION", "action": { ... } }
 *   { "type": "PING" }
 *
 * Message types (ENGINE -> CLIENT):
 *   { "type": "STATE",  "state": { ... GameStateSnapshot ... } }
 *   { "type": "ERROR",  "message": "..." }
 *   { "type": "PONG" }
 */
public class GameWsServer extends WebSocketServer {

    private static final int DEFAULT_PORT = 7654;
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    private final String forgeJarPath;
    private final String forgeWorkDir;

    // Active game session (one game at a time for Phase 1)
    private volatile GameSession activeSession;

    // Waiting-for-human-input: the session parks here until Unity sends an action
    private final BlockingQueue<String> humanActionQueue = new LinkedBlockingQueue<>();

    public GameWsServer(String forgeJarPath, String forgeWorkDir) {
        super(new InetSocketAddress(DEFAULT_PORT));
        this.forgeJarPath = forgeJarPath;
        this.forgeWorkDir = forgeWorkDir;
        setReuseAddr(true);
    }

    public GameWsServer(int port, String forgeJarPath, String forgeWorkDir) {
        super(new InetSocketAddress(port));
        this.forgeJarPath = forgeJarPath;
        this.forgeWorkDir = forgeWorkDir;
        setReuseAddr(true);
    }

    // ---------------------------------------------------------
    // WebSocket lifecycle
    // ---------------------------------------------------------

    @Override
    public void onOpen(WebSocket conn, ClientHandshake handshake) {
        System.out.println("[WS] Client connected: " + conn.getRemoteSocketAddress());
        // Send current state if a game is in progress
        if (activeSession != null) {
            conn.send(activeSession.buildStateMessage());
        }
    }

    @Override
    public void onClose(WebSocket conn, int code, String reason, boolean remote) {
        System.out.println("[WS] Client disconnected: " + conn.getRemoteSocketAddress());
    }

    @Override
    public void onMessage(WebSocket conn, String message) {
        try {
            JsonObject msg = JsonParser.parseString(message).getAsJsonObject();
            String type = msg.get("type").getAsString();

            switch (type) {
                case "PING" -> conn.send(buildPong());
                case "START_GAME" -> handleStartGame(conn, msg);
                case "PLAYER_ACTION" -> handlePlayerAction(conn, msg);
                case "STOP_GAME" -> {
                    if (activeSession != null) activeSession.stop();
                    activeSession = null;
                    broadcast(buildInfo("Game stopped."));
                }
                default -> sendError(conn, "Unknown message type: " + type);
            }
        } catch (Exception e) {
            sendError(conn, "Parse error: " + e.getMessage());
        }
    }

    @Override
    public void onError(WebSocket conn, Exception ex) {
        System.err.println("[WS] Error: " + ex.getMessage());
    }

    @Override
    public void onStart() {
        System.out.println("[WS] GameWsServer started on port " + getPort());
        System.out.println("[WS] Connect Unity/Godot to: ws://localhost:" + getPort());
    }

    // ---------------------------------------------------------
    // Message handlers
    // ---------------------------------------------------------

    private void handleStartGame(WebSocket conn, JsonObject msg) {
        if (activeSession != null && activeSession.isRunning()) {
            sendError(conn, "A game is already in progress. Send { type: 'STOP_GAME' } first.");
            return;
        }

        List<String> decks = new ArrayList<>();
        if (msg.has("decks")) {
            msg.getAsJsonArray("decks").forEach(d -> decks.add(d.getAsString()));
        }

        if (decks.size() < 3) {
            sendError(conn, "Need at least 3 deck names in 'decks' array.");
            return;
        }

        Long seed = msg.has("seed") ? msg.get("seed").getAsLong() : null;

        System.out.println("[WS] Starting game: " + decks + " seed=" + seed);

        // Clear any stale actions from previous game
        humanActionQueue.clear();

        activeSession = new GameSession(decks, seed, forgeJarPath, forgeWorkDir, humanActionQueue);

        // Push initial state immediately
        broadcast(activeSession.buildStateMessage());

        // Run the game loop on a background thread so WebSocket thread stays free
        Thread gameThread = new Thread(() -> {
            try {
                activeSession.run(state -> broadcast(GSON.toJson(state)));
                broadcast(buildInfo("Game over after " + activeSession.getTurnNumber() + " turns."));
            } catch (Exception e) {
                broadcastError("Game error: " + e.getMessage());
                e.printStackTrace();
            }
        }, "game-loop");
        gameThread.setDaemon(true);
        gameThread.start();
    }

    private void handlePlayerAction(WebSocket conn, JsonObject msg) {
        if (activeSession == null || !activeSession.isRunning()) {
            sendError(conn, "No active game. Send START_GAME first.");
            return;
        }
        if (!msg.has("action")) {
            sendError(conn, "Missing 'action' field.");
            return;
        }
        // Put the raw action JSON string onto the queue -- GameSession polls this
        humanActionQueue.offer(msg.get("action").toString());
    }

    // ---------------------------------------------------------
    // Broadcast helpers
    // ---------------------------------------------------------

    private void broadcastError(String message) {
        broadcast(buildError(message));
    }

    private void sendError(WebSocket conn, String message) {
        conn.send(buildError(message));
    }

    private static String buildError(String message) {
        JsonObject obj = new JsonObject();
        obj.addProperty("type", "ERROR");
        obj.addProperty("message", message);
        return obj.toString();
    }

    private static String buildInfo(String message) {
        JsonObject obj = new JsonObject();
        obj.addProperty("type", "INFO");
        obj.addProperty("message", message);
        return obj.toString();
    }

    private static String buildPong() {
        JsonObject obj = new JsonObject();
        obj.addProperty("type", "PONG");
        obj.addProperty("ts", System.currentTimeMillis());
        return obj.toString();
    }
}
