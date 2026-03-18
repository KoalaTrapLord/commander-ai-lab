# Commander AI Lab

Headless batch simulation environment for 3-AI MTG Commander pods.
Run 100+ games, analyze win rates, and stress-test your decks — all from a web UI or CLI.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Web Browser (ai-lab.js + ai-lab.css)                       │
│    Select decks → Start batch → Poll progress → View stats  │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP (REST)
┌─────────────────────┴───────────────────────────────────────┐
│  Python FastAPI Server (lab_api.py, port 8080)              │
│    /api/lab/start  — spawn Java batch runner subprocess     │
│    /api/lab/status — poll progress (parses stdout)          │
│    /api/lab/result — return completed JSON results          │
│    /api/lab/decks  — list decks from Forge user data        │
│    /api/lab/history— browse past batch runs                 │
│    /api/lab/log    — stream live console output             │
└─────────────────────┬───────────────────────────────────────┘
                      │ subprocess (java -jar)
┌─────────────────────┴───────────────────────────────────────┐
│  Java CLI (LabCli.java + BatchRunner + MultiThreadRunner)   │
│    Parses Forge sim output → GameResult objects → JSON      │
└─────────────────────┬───────────────────────────────────────┘
                      │ subprocess per game
┌─────────────────────┴───────────────────────────────────────┐
│  Card Forge Engine (forge-gui-desktop sim mode)             │
│    java -jar forge.jar sim -d "deck1" "deck2" "deck3"       │
│    -f commander -n 1 -q                                     │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start (Windows)

### Prerequisites
- **Java 17+** (`java -version`)
- **Python 3.10+** (`python --version`)
- **Maven 3.8+** (`mvn --version`)
- **Forge repo** cloned and built at `D:\ForgeCommander\forge-repo`

### 1. Build Forge (one-time)
```powershell
cd D:\ForgeCommander\forge-repo
mvn package -pl forge-gui-desktop "-DskipTests" "-Drevision=2.0.12-SNAPSHOT" -am
```

### 2. Build Commander AI Lab
```powershell
cd D:\ForgeCommander\commander-ai-lab
mvn package "-DskipTests"
```
This produces `target/commander-ai-lab-1.0.0-SNAPSHOT.jar` (shaded fat JAR).

### 3. Install Python dependencies
```powershell
pip install fastapi uvicorn
```

### 4. Launch the Web UI
**Option A — One-click launcher:**
```powershell
.\start-lab.bat
```
Edit the paths at the top of `start-lab.bat` if needed.

**Option B — Manual launch:**
```powershell
python lab_api.py `
  --forge-jar "D:\ForgeCommander\forge-repo\forge-gui-desktop\target\forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar" `
  --forge-dir "D:\ForgeCommander\forge-repo\forge-gui" `
  --port 8080
```

Open `http://localhost:8080` — select 3 decks, set game count, click **Run AI Sims**.

### 5. CLI-only usage (no web server)
```powershell
cd D:\ForgeCommander\forge-repo\forge-gui

java -jar "D:\ForgeCommander\commander-ai-lab\target\commander-ai-lab-1.0.0-SNAPSHOT.jar" `
  --forge-jar "..\forge-gui-desktop\target\forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar" `
  --forge-dir "." `
  --deck1 "Edgar Markov" `
  --deck2 "Grimgrin" `
  --deck3 "Xyris" `
  --games 100 `
  --threads 4 `
  --output results/batch-100.json
```

## Scaling Tests

### Single-threaded baseline (10 games)
```powershell
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar `
  --forge-jar "..." --forge-dir "..." `
  --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" `
  --games 10 --threads 1 --output results/baseline-10.json
```

### Multi-threaded (10 games, 2 threads)
```powershell
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar `
  --forge-jar "..." --forge-dir "..." `
  --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" `
  --games 10 --threads 2 --output results/mt-10-t2.json
```

### Scale to 100 games (4 threads)
```powershell
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar `
  --forge-jar "..." --forge-dir "..." `
  --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" `
  --games 100 --threads 4 --output results/scale-100-t4.json
```

### Maximum throughput test (100 games, 8 threads)
```powershell
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar `
  --forge-jar "..." --forge-dir "..." `
  --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" `
  --games 100 --threads 8 --seed 42 --output results/scale-100-t8-seed42.json
```

### Performance comparison script
Run different thread counts and compare sims/sec:
```powershell
# Baseline: 1 thread
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar --forge-jar "..." --forge-dir "..." --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" --games 20 --threads 1 --seed 42 --output results/perf-t1.json

# 2 threads
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar --forge-jar "..." --forge-dir "..." --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" --games 20 --threads 2 --seed 42 --output results/perf-t2.json

# 4 threads
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar --forge-jar "..." --forge-dir "..." --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" --games 20 --threads 4 --seed 42 --output results/perf-t4.json

# 8 threads
java -jar target\commander-ai-lab-1.0.0-SNAPSHOT.jar --forge-jar "..." --forge-dir "..." --deck1 "Edgar Markov" --deck2 "Grimgrin" --deck3 "Xyris" --games 20 --threads 8 --seed 42 --output results/perf-t8.json
```

Then compare the `simsPerSecond` values in each output JSON to see scaling behavior.

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/lab/decks` | GET | List available Commander decks |
| `/api/lab/start` | POST | Start a batch run (returns batchId) |
| `/api/lab/status?batchId=X` | GET | Poll progress for a running batch |
| `/api/lab/result?batchId=X` | GET | Get completed batch result JSON |
| `/api/lab/log?batchId=X` | GET | Get live log lines from running batch |
| `/api/lab/history` | GET | List past batch result files |

### POST /api/lab/start
```json
{
  "decks": ["Edgar Markov", "Grimgrin", "Xyris"],
  "numGames": 100,
  "threads": 4,
  "seed": null,
  "clock": 120
}
```

### GET /api/lab/status response
```json
{
  "batchId": "abc123",
  "running": true,
  "completed": 42,
  "total": 100,
  "threads": 4,
  "elapsedMs": 156000,
  "error": null
}
```

## Python Simulator (Monte Carlo Engine)

A pure-Python deck simulator for rapid Monte Carlo analysis — no Forge JVM required.
Ported from the [mtg-commander-lan](https://github.com/) Node.js simulator.

### Location

```
src/commander_ai_lab/
├── __init__.py
├── sim/                         # Core simulation engine
│   ├── __init__.py              # Public exports
│   ├── models.py                # Card, Player, SimState, GameResult, PlayerStats
│   ├── engine.py                # GameEngine — turn loop, combat (flying/trample/deathtouch/lifelink/menace/reach)
│   └── rules.py                 # AI_DEFAULT_WEIGHTS, enrich_card(), score_card(), parse_decklist()
└── lab/                         # High-level experiment helpers
    ├── __init__.py
    └── experiments.py           # build_deck(), run_single_game(), run_simulation(), _cli_main()
```

### Install as editable package

```powershell
cd D:\ForgeCommander\commander-ai-lab
pip install -e .
```

This installs `commander_ai_lab` as an importable package and registers the `commander-sim` CLI command.

### Quick smoke test

```powershell
python -m commander_ai_lab.lab.experiments
```

Expected output — a 10-game Monte Carlo run of a sample "Korvold" deck:

```
══════════════════════════════════════════
  Commander AI Lab — Experiment Runner
══════════════════════════════════════════

--- Demo: Korvold Aristocrats (10 games) ---

  Win rate:          XX.X%
  Avg turns:         XX.X
  Avg damage dealt:  XX.X
  Avg spells cast:   XX.X
  Avg creatures:     XX.X
  Elapsed:           0.02s

  Done.
```

### Python API

```python
from commander_ai_lab.sim.models import Card
from commander_ai_lab.sim.engine import GameEngine
from commander_ai_lab.lab.experiments import build_deck, run_simulation

# Build a deck from card names
deck = build_deck(["Sol Ring", "Cultivate", "Lightning Bolt", "Forest"] + ["Forest"] * 36)

# Monte Carlo simulation (100 games)
stats = run_simulation(deck, num_games=100, name_a="My Deck")
print(f"Win rate: {stats['win_rate']:.1%}")
print(f"Avg turns: {stats['avg_turns']:.1f}")
```

Key functions:

| Function | Description |
|---|---|
| `build_deck(card_names)` | Create enriched `Card` list from names |
| `build_deck_from_text(decklist)` | Parse `"1 Sol Ring\n37 Forest"` format |
| `run_single_game(deck_a, deck_b)` | One game, returns winner/turns/stats |
| `run_simulation(deck_a, deck_b, n)` | Monte Carlo over `n` games, aggregated stats |

### CLI entry point

After `pip install -e .`:

```powershell
commander-sim
```

Runs the same demo as `python -m commander_ai_lab.lab.experiments`.

### How the engine works

1. **Deck enrichment** — `enrich_card()` infers type, CMC, keywords, and power/toughness from card name heuristics when Scryfall data is unavailable.
2. **AI scoring** — `score_card()` uses weighted categories (removal, ramp, draw, aggro, etc.) to pick the best play each turn.
3. **Game loop** — Each turn: untap → draw → play lands → cast spells (AI scored) → combat (attack/block decisions) → end step. Full keyword support for flying, trample, deathtouch, lifelink, menace, and reach.
4. **Monte Carlo** — `run_simulation()` runs N independent games and aggregates win rate, avg turns, damage dealt/received, spells cast, creatures played, removal used, ramp played, cards drawn, and max board size.

## Project Structure

```
commander-ai-lab/
├── lab_api.py                    # Python FastAPI server (web UI backend)
├── start-lab.bat                 # Windows one-click launcher
├── pom.xml                       # Maven build (Java 17, shaded JAR)
├── pyproject.toml                # Python package config (src/ layout)
├── ui/
│   ├── index.html                # Web UI entry point
│   ├── ai-lab.js                 # UI controller (deck selection, progress, results)
│   ├── ai-lab.css                # Styles (dark theme, responsive)
│   ├── collection.html           # Card collection manager
│   ├── collection.js             # Collection controller
│   ├── collection.css            # Collection styles
│   ├── deckbuilder.html          # Deck builder + EDH advisor
│   ├── deckbuilder.js            # Deck builder controller
│   └── deckbuilder.css           # Deck builder styles
├── src/commander_ai_lab/         # Python simulator package
│   ├── __init__.py
│   ├── sim/                      # Core engine (models, engine, rules)
│   └── lab/                      # Experiment helpers
├── src/main/java/commanderailab/ # Java batch runner (Forge integration)
│   ├── cli/LabCli.java           # CLI entry point (picocli)
│   ├── batch/
│   │   ├── BatchRunner.java      # Single-thread runner (parses Forge output)
│   │   └── MultiThreadBatchRunner.java  # Multi-thread runner (ExecutorService)
│   ├── bridge/WebApiBridge.java  # Java-side web API bridge
│   ├── schema/
│   │   ├── BatchResult.java      # Data model POJOs
│   │   └── JsonExporter.java     # JSON serialization + validation
│   ├── stats/StatsAggregator.java # Win rates, turn counts, breakdowns
│   └── ai/
│       ├── AiPolicy.java         # Policy interface
│       └── ForgeBuiltinPolicy.java # v1 Forge AI wrapper
├── scanner/                      # Card scanner (OCR pipeline)
│   ├── __init__.py
│   ├── ocr.py                    # Tesseract OCR wrapper
│   ├── pipeline.py               # Image preprocessing pipeline
│   └── preprocess.py             # Image preprocessing helpers
├── docs/
│   ├── PROJECT_VISION.md
│   ├── batch-result-schema.json
│   └── game-log-schema.json
├── sample-decks/                 # 3 sample .dck files
├── precon-decks/                 # Preconstructed decks + index
├── results/                      # Batch output JSON files (gitignored)
└── src/test/java/                # Unit tests
```

## Output Format

Each batch run produces JSON conforming to `docs/batch-result-schema.json`:
```json
{
  "metadata": {
    "schemaVersion": "1.0.0",
    "batchId": "uuid",
    "timestamp": "2026-03-06T...",
    "totalGames": 100,
    "completedGames": 100,
    "format": "commander",
    "podSize": 3,
    "engineVersion": "forge-2.0.12-SNAPSHOT",
    "masterSeed": 42,
    "threads": 4,
    "elapsedMs": 260000
  },
  "decks": [...],
  "games": [...],
  "summary": {
    "perDeck": [
      { "deckName": "Edgar Markov", "winRate": 0.60, "wins": 60, ... }
    ],
    "avgGameTurns": 12.3,
    "simsPerSecond": 0.38
  }
}
```

## Frontend Development

The UI is a React + TypeScript SPA in the `frontend/` directory.

### Dev server (with hot reload)
```bash
cd frontend
npm install
npm run dev
```
Vite proxies `/api` and `/ws` to `localhost:8000`, so start the FastAPI backend first.

### Production build
```bash
cd frontend
npm run build
```
FastAPI serves the built assets from `frontend/dist/`.

## Known Limitations
- Winner's life total not captured (Forge quiet mode only reports losers)
- Win condition classification is heuristic-based on Forge loss reason strings
- Each game spawns a new JVM process (~2-3s overhead per game)
- Max throughput ~0.04 sims/sec single-threaded (Forge sim is CPU-heavy)
- Multithreading spawns parallel subprocesses — throughput scales linearly with threads up to CPU core count
