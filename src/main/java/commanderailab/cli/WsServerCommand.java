package commanderailab.cli;

import commanderailab.bridge.GameWsServer;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

import java.util.concurrent.Callable;

/**
 * WsServerCommand — picocli subcommand that starts the interactive game WebSocket server.
 *
 * Usage:
 *   java -jar commander-ai-lab.jar ws-server \
 *     --forge-jar path/to/forge.jar \
 *     --forge-dir path/to/forge-gui \
 *     --port 7654
 *
 * Then connect Unity/Godot to ws://localhost:7654 and send:
 *   { "type": "START_GAME", "decks": ["DeckA","DeckB","DeckC","DeckD"], "seed": 42 }
 */
@Command(
    name = "ws-server",
    mixinStandardHelpOptions = true,
    description = "Start the interactive game WebSocket server for Unity/Godot clients."
)
public class WsServerCommand implements Callable<Integer> {

    @Option(names = {"--forge-jar", "-F"}, required = true,
            description = "Path to Forge desktop JAR (forge-gui-desktop-XXX-jar-with-dependencies.jar)")
    private String forgeJarPath;

    @Option(names = {"--forge-dir", "-W"}, required = true,
            description = "Forge working directory (folder containing res/)")
    private String forgeWorkDir;

    @Option(names = {"--port", "-p"}, defaultValue = "7654",
            description = "WebSocket port (default: 7654)")
    private int port;

    @Override
    public Integer call() throws Exception {
        System.out.println("╔══════════════════════════════════════════════════╗");
        System.out.println("║    Commander AI Lab — Interactive WS Server      ║");
        System.out.println("╚══════════════════════════════════════════════════╝");
        System.out.println();
        System.out.println("  Forge JAR : " + forgeJarPath);
        System.out.println("  Forge Dir : " + forgeWorkDir);
        System.out.println("  WS Port   : " + port);
        System.out.println();

        GameWsServer server = new GameWsServer(port, forgeJarPath, forgeWorkDir);
        server.start();

        System.out.println("  Ready — connect Unity/Godot to ws://localhost:" + port);
        System.out.println("  Press Ctrl+C to stop.");
        System.out.println();

        // Block until killed
        Thread.currentThread().join();
        return 0;
    }
}
