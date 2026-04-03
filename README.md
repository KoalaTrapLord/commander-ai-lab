# Commander AI Lab

A full-stack Magic: The Gathering Commander research platform. Run thousands of simulated games, train neural networks on the outcomes, build decks with AI that learns from simulation data, get LLM-powered coaching, and play live 4-player battles — all from a single unified system.

---

## Overview

Commander AI Lab connects a rules-complete Forge engine, a fast Monte Carlo simulator, an LLM deck builder, an ML training pipeline, and multiple game clients (web, LAN, Unity) into one closed-loop platform. Simulation results feed back into deck building and AI decision-making, so the system improves the more it plays.

### Key Capabilities

- **Batch Simulation** — Run hundreds or thousands of Commander games unattended using Forge (rules-complete) or a headless Python Monte Carlo engine
- **ML Training Pipeline** — Reinforcement learning (PPO) trains a neural net on game decision logs; outcome-weighted scoring nudges card weights automatically
- **AI Deck Builder** — 7-step LLM pipeline (EDHrec → Scryfall → Ollama) with simulation-learned insights injected into prompts
- **LLM Coach** — Streaming coaching sessions powered by Anthropic Claude or local Ollama models, enriched with RAG-retrieved card knowledge
- **RAG Card Knowledge** — ChromaDB vector store over 30,000+ Scryfall cards with semantic search and auto-staleness monitoring
- **LAN Battlefield** — Browser-based 4-player Commander game client with ML-powered AI opponents and precon deck support
- **Unity Client** — Full Unity application with battleground scene, lobby system, WebSocket game state sync, and cross-platform builds
- **Card Scanner** — OCR pipeline for physical card recognition via Ximilar API
- **163 Precon Decks** — Complete preconstructed deck library in `.dck` format

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Clients                                                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────────┐ │
│  │  Web UI      │ │  LAN Client  │ │  Unity Client                │ │
│  │  (React/TS)  │ │  (HTML/JS)   │ │  (C# / URP)                 │ │
│  │  /ui         │ │  /lan        │ │  /unity-client               │ │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────────────────────┘ │
│         └────────────────┼────────────────┘                         │
│                          │ HTTP/REST + WebSocket                    │
│  ┌───────────────────────┴─────────────────────────────────────────┐│
│  │  FastAPI Backend (lab_api.py — port 8080)                       ││
│  │                                                                  ││
│  │  /api/lab/*          Batch simulation (Forge + Monte Carlo)     ││
│  │  /api/deck-builder/* 7-step LLM deck construction               ││
│  │  /api/coach/*        Streaming LLM coaching sessions            ││
│  │  /api/ml/*           Neural net training + policy server        ││
│  │  /api/rag/*          ChromaDB vector search                     ││
│  │  /api/game/*         Live game sessions (Forge IPC)             ││
│  │  /api/policy/*       ML policy decisions for AI players         ││
│  │  /ws/game/{id}       WebSocket game state streaming             ││
│  └───────┬──────────────┬──────────────┬──────────────┬────────────┘│
│          │              │              │              │              │
│   ┌──────┴──────┐ ┌────┴─────┐ ┌──────┴──────┐ ┌────┴──────┐      │
│   │ Forge       │ │ Monte    │ │ Ollama      │ │ ChromaDB  │      │
│   │ Engine      │ │ Carlo    │ │ (local LLM) │ │ (vector   │      │
│   │ (Java/JVM)  │ │ Engine   │ │ qwen2.5:7b  │ │  store)   │      │
│   └─────────────┘ │ (Python) │ └─────────────┘ └───────────┘      │
│                    └──────────┘                                      │
│  ┌──────────────────────────────────────────────────────────────────┐│
│  │  ML Pipeline                                                     ││
│  │  decisions_*.jsonl → update_weights.py → learned_weights.json    ││
│  │                    → /api/ml/train    → neural net checkpoints   ││
│  └──────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

---

## Features

### Simulation Engines

| Engine | Description | Speed |
|---|---|---|
| **Forge** | Rules-complete Java engine — handles the stack, instants, triggered abilities, and all Commander rules. Each game spawns a JVM subprocess. | ~0.04 sims/sec (single-threaded) |
| **Monte Carlo** | Headless Python engine — models combat keywords (flying, trample, deathtouch, lifelink, menace, reach, haste), summoning sickness, tapped state, commander zone, multiplayer targeting, and board wipes. No JVM required. | Thousands of games in minutes |

Both engines feed structured results into the same ML pipeline.

### Deck Builder

The `POST /api/deck-builder/build` endpoint runs a 7-step pipeline:

1. Resolve commander via Scryfall
2. Fetch EDHrec recommendations
3. Fetch Scryfall candidates by category (ramp, removal, draw, lands)
4. Ollama suggests synergy/protection/wincon cards — **simulation insights injected here**
5. Filter by color identity, collection, and ban list
6. Ollama enforces ratios (trim/expand to 99) — **simulation insights injected here**
7. Assemble final deck with smart substitution (guarantees 99-card output)

### AI Coach

LLM-powered coaching with two modes:

- **Full Session** — Deep analysis including removal coverage, ramp quality, draw engine profiling, win conditions, anti-synergy detection, pod meta evaluation, and tempo assessment
- **Quick Digest** — Fast ~5-second summary for rapid feedback

Coaching prompts are enriched with semantically relevant cards from the ChromaDB RAG store (15 cards for full sessions, 8 for quick digests). Supports both Anthropic Claude and local Ollama models with streaming responses.

### RAG Card Knowledge

- **SQLite FTS5** bulk card database from Scryfall data
- **ChromaDB** vector index with natural-language card embeddings
- Automatic staleness monitoring (checks every 6 hours, auto-rebuilds if >14 days old)
- Graceful fallback — RAG failures never block coaching or deck building

### ML Training Pipeline

```
Overnight sims → decisions_*.jsonl
       ↓
update_weights.py → learned_weights.json (feeds deck builder)
       ↓
/api/ml/train → neural net training on decision dataset
       ↓
/api/policy/decide → ML policy serves AI decisions in live games
```

- **Outcome-weighted RL** nudges card scoring weights from game results
- **Neural net** trains on the full decision log dataset
- **Distillation loop** — self-play → collect data → retrain → repeat
- **ELO tracking** and model tournaments for comparing AI versions
- Weights clamped to `[-20.0, 20.0]`, stored in `learned_weights.json`

### Win Condition Tracking

Games are classified by win type — not just "Combat" vs "Other":

- **Combat** — standard creature damage wins
- **Combo** — Approach of the Second Sun, Felidar Sovereign, Happily Ever After, and 30+ known alternate-win cards
- **Drain** — life drain effects
- **Mill** — library depletion
- **Poison** — infect/poison counter wins

Draw games (timeout) are analyzed separately with per-player life-at-timeout snapshots and likely cause identification.

### LAN Battlefield Client

Browser-based 4-player Commander game at `/lan`:

- **AI Bridge** — REST + WebSocket connectivity with ML policy decisions as Priority 1 (falls back to local heuristic AI)
- **Deck System** — 3-tab selector: Precons (163 decks, grouped by set), EDHREC search, and custom deck import
- **Player Panels** — Life counters, commander damage bars, poison/energy/experience/rad counters, emblem management
- **Backend Detection** — Auto-detects the Commander AI Lab backend; works offline with local precon data

### Unity Client

Full Unity application (URP, .NET Standard 2.1) with:

- **Battleground Scene** — 4-seat layout with rotated perspectives, life/poison/commander damage widgets, phase tracker, turn order bar
- **Card System** — Hand, battlefield, graveyard, exile zones with card art, tapped rotation, face-down state, summoning sickness indicators
- **Stack & Mana** — LIFO stack display and 6-pip mana pool
- **Lobby System** — Configure 4 seats (human/AI), POST to backend, WebSocket game state sync
- **Elimination** — Grayscale shader overlay on eliminated players
- **Token System** — Create, tap, add counters, delete tokens
- **Cross-Platform** — Windows, WebGL, Android, iOS build targets
- **Scenes** — MainMenu, Collection, DeckBuilder, DeckGenerator, Simulator, Coach, Scanner, Training, Precon, Battleground

### Card Scanner

OCR pipeline for physical Magic cards using the Ximilar API. Scan cards from photos and match them to the Scryfall database.

---

## Quick Start

### Prerequisites

| Tool | Version |
|---|---|
| Python | 3.10+ |
| Java | 17+ |
| Maven | 3.8+ |
| Node.js | 18+ (for LAN client scripts) |
| Ollama | Latest (for local LLM inference) |
| [Forge](https://github.com/Card-Forge/forge) | Built at `D:\ForgeCommander\forge-repo` |

### Setup (Windows)

```powershell
# 1. Build Forge (one-time)
cd D:\ForgeCommander\forge-repo
mvn package -pl forge-gui-desktop "-DskipTests" "-Drevision=2.0.12-SNAPSHOT" -am

# 2. Build Commander AI Lab
cd D:\ForgeCommander\commander-ai-lab
mvn package "-DskipTests"

# 3. Install Python dependencies
pip install -e ".[rag,dev]"

# 4. Pull an Ollama model for the deck builder
ollama pull qwen2.5:7b

# 5. Launch
.\start-lab.bat
# → Web UI:        http://localhost:8080
# → LAN Client:    http://localhost:8080/lan/
```

Or use the automated installer:

```powershell
.\install-commander-ai-lab.ps1
```

---

## Overnight AFK Runner

Run batch simulations unattended, then automatically update card weights and train the neural net:

```powershell
python overnight-run.py                          # default: 11.5h DeepSeek sims
python overnight-run.py --batches 20 --games 50  # fixed batch count
python overnight-run.py --no-update-weights      # skip weight update
python overnight-run.py --no-train               # skip neural net training
```

**What happens after sims complete:**
1. `update_weights.py` — nudges `learned_weights.json` from decision logs (feeds deck builder)
2. `/api/ml/train` — trains the neural net on the full decision dataset

---

## Simulation → Deck Builder Feedback Loop

```
Overnight sims → decisions_*.jsonl
       ↓
update_weights.py → learned_weights.json
       ↓
sim_insights.py → natural-language insight block
       ↓
Ollama prompts (suggest_cards + enforce_deck_ratios)
       ↓
Better card recommendations
```

When active, `BuildResult.sources_consulted` includes `"sim_weights"`. The loop is a no-op until real sim data exists.

---

## API Reference

### Simulation

| Endpoint | Method | Description |
|---|---|---|
| `/api/lab/decks` | GET | List available Commander decks |
| `/api/lab/start` | POST | Start Forge batch (returns batchId) |
| `/api/lab/start-deepseek` | POST | Start Python/DeepSeek batch |
| `/api/lab/status?batchId=X` | GET | Poll batch progress |
| `/api/lab/result?batchId=X` | GET | Get completed batch JSON |
| `/api/lab/history` | GET | List past batch runs |
| `/api/lab/precons/deck` | GET | Fetch precon `.dck` file content |

### Deck Builder & Coach

| Endpoint | Method | Description |
|---|---|---|
| `/api/deck-builder/build` | POST | Build a 99-card Commander deck |
| `/api/coach/chat` | POST | Full coaching session (streaming) |
| `/api/coach/quick-digest` | POST | Fast ~5s coaching summary |

### ML & Policy

| Endpoint | Method | Description |
|---|---|---|
| `/api/ml/train` | POST | Start neural net training |
| `/api/ml/train/status` | GET | Poll training progress |
| `/api/policy/decide` | POST | Get ML policy decision for game state |

### RAG

| Endpoint | Method | Description |
|---|---|---|
| `/api/rag/build` | POST | Build/rebuild ChromaDB index |
| `/api/rag/search` | POST | Semantic card search |
| `/api/rag/status` | GET | Index health and staleness |

### Live Game

| Endpoint | Method | Description |
|---|---|---|
| `/api/game/start` | POST | Create a live game session |
| `/api/game/action` | POST | Submit a player action |
| `/api/game/{id}/actions` | GET | Poll Forge IPC actions |
| `/ws/game/{game_id}` | WS | Real-time game state streaming |

---

## ML Scripts

```powershell
# Update card weights from decision logs
python -m ml.scripts.update_weights --min-games 10 --lr 0.05 --dry-run

# Reset weights to defaults
python -m ml.scripts.update_weights --reset

# Generate synthetic training data
python ml/scripts/generate_synthetic_data.py
```

---

## Python Simulator API

```python
from commander_ai_lab.lab.experiments import build_deck, run_simulation

deck = build_deck(["Sol Ring", "Cultivate", "Lightning Bolt"] + ["Forest"] * 36)
stats = run_simulation(deck, num_games=100, name_a="My Deck")
print(f"Win rate: {stats['win_rate']:.1%}, Avg turns: {stats['avg_turns']:.1f}")
```

---

## Project Structure

```
commander-ai-lab/
├── lab_api.py                    # FastAPI server entry point
├── overnight-run.py              # AFK batch runner
├── start-lab.bat                 # Windows one-click launcher
├── install-commander-ai-lab.ps1  # Automated setup script
├── pom.xml                       # Maven build (Java/Forge components)
├── pyproject.toml                # Python package config
│
├── routes/                       # FastAPI route modules
│   ├── lab.py                    #   Batch simulation
│   ├── deckbuilder.py            #   Deck builder pipeline
│   ├── coach.py                  #   LLM coaching
│   ├── ml.py                     #   ML training
│   ├── rag.py                    #   ChromaDB vector search
│   ├── game.py                   #   Live game sessions
│   ├── policy.py                 #   ML policy server
│   ├── precon.py                 #   Precon deck serving
│   ├── scanner.py                #   Card OCR
│   └── ws_game.py                #   WebSocket game state
│
├── services/                     # Core service layer
│   ├── forge_runner.py           #   Forge subprocess management
│   ├── draw_game_analyzer.py     #   Draw/timeout analysis
│   ├── rag_store.py              #   ChromaDB vector store
│   └── card_text.py              #   Shared card text builder
│
├── src/commander_ai_lab/
│   ├── sim/                      # Monte Carlo engine
│   │   ├── engine.py             #   Game loop
│   │   ├── models.py             #   GameResult, Card, Player
│   │   ├── rules.py              #   Combat, keywords, commander rules
│   │   ├── win_condition_parser.py  # Alternate win detection
│   │   └── learned_weights.json  #   ML-learned card weights
│   ├── deck_builder/             # 7-step LLM pipeline
│   │   ├── api/                  #   Scryfall, EDHrec, Ollama, sim_insights
│   │   ├── core/                 #   Models, rules engine, assembler
│   │   └── pipeline/             #   build_deck.py orchestrator
│   └── coach/                    # LLM coaching
│       ├── coach_service.py      #   Session + quick digest
│       ├── prompt_template.py    #   System/user prompts
│       └── embeddings.py         #   Card embedding utilities
│
├── ml/                           # ML training pipeline
│   ├── scripts/                  #   update_weights.py, ml_cli.py
│   ├── training/                 #   Neural net trainer
│   ├── encoder/                  #   Feature encoding
│   └── models/                   #   Saved checkpoints
│
├── lan-client/                   # Browser-based LAN battlefield
│   ├── index.html                #   Entry point
│   ├── engine.js                 #   Game engine + ML AI turns
│   ├── ai-bridge.js              #   Backend connector + policy bridge
│   ├── player-panels.js          #   Enhanced player panels
│   ├── ui.js                     #   3-tab deck selector + setup
│   └── precons.js                #   163 precon deck data
│
├── unity-client/                 # Unity game client
│   └── Assets/
│       ├── Scenes/               #   11 scenes (MainMenu → Battleground)
│       ├── Scripts/              #   C# controllers, models, services
│       ├── Prefabs/              #   Card, deck slot, chat bubble
│       └── Materials/            #   URP materials + grayscale shader
│
├── scanner/                      # Card OCR pipeline (Ximilar)
├── precon-decks/                 # 163 preconstructed decks (.dck)
├── sample-decks/                 # Sample deck files
├── data/                         # Runtime data (ChromaDB, bulk DB)
├── logs/                         # Simulation + decision logs
├── docs/                         # Architecture docs + schemas
├── tests/                        # Test suite
├── scripts/                      # Utility scripts
├── .github/workflows/            # CI + Unity build automation
└── src/main/java/                # Java/Forge batch runner
    └── commanderailab/
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Simulation (rules-complete) | Java 17, Maven, Forge |
| Simulation (fast) | Python Monte Carlo engine |
| LLM Inference | Ollama (qwen2.5:7b), Anthropic Claude |
| Vector Store | ChromaDB with all-MiniLM-L6-v2 embeddings |
| Card Database | SQLite FTS5 (Scryfall bulk data) |
| ML Training | PyTorch, PPO reinforcement learning |
| Web Client | HTML/CSS/JS |
| Unity Client | Unity 2022 LTS, URP, C# |
| CI/CD | GitHub Actions |

---

## Known Limitations

- **Monte Carlo engine** — no stack, no instants, no continuous type-changing effects (animated lands don't attack)
- **Forge engine** — each game spawns a new JVM (~2–3s overhead); ~0.04 sims/sec single-threaded
- **Forge** — winner life total not captured in quiet mode (only reports losers)
- **Deck builder** — Ollama suggestions depend on the local model quality; `qwen2.5:7b` works well
- **LAN client** — EDHREC commander search is a stub (backend-powered, not yet fully wired)

---

## Contributing

Commander AI Lab is an active research project. Check the [open issues](https://github.com/KoalaTrapLord/commander-ai-lab/issues) for areas where contributions are welcome.

---

## License

See repository for license details.
