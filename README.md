# Commander AI Lab

A full-stack MTG Commander AI research platform. Simulate hundreds of games overnight, train ML models on the results, and let simulation data automatically shape the AI deck builder — all from a web UI or CLI.

## What It Does

| Layer | What it is |
|---|---|
| **Monte Carlo Engine** | Pure-Python headless sim — runs thousands of games in minutes, no JVM needed |
| **Forge Engine** | Java/Forge rules-complete sim for ground-truth validation |
| **Overnight Runner** | Unattended batch runner — runs sims, updates sim weights, trains neural net |
| **ML Pipeline** | Outcome-weighted RL nudges card scoring weights; neural net trains on decision logs |
| **Deck Builder** | 7-step LLM pipeline (EDHrec → Scryfall → Ollama) now injected with sim-learned insights |
| **AI Coach** | LLM-powered coaching sessions (Anthropic/Ollama) with streaming support |
| **Web UI** | React + FastAPI dashboard for decks, sims, training, and deck building |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Web UI  (React/TypeScript — frontend/)                         │
│    Deck Builder · Sim Dashboard · Training · Coach              │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP/REST + WebSocket
┌────────────────────────┴────────────────────────────────────────┐
│  FastAPI Server  (lab_api.py / routes/ — port 8080)             │
│    /api/lab/*   /api/ml/*   /api/coach/*   /api/deck-builder/*  │
└────────┬──────────────────┬──────────────────┬──────────────────┘
         │                  │                  │
   Java subprocess    Python sim engine    Ollama (local LLM)
   (Forge rules)      (Monte Carlo)        qwen2.5:7b + others
         │                  │
┌────────┴───────┐  ┌───────┴────────────────────────────────────┐
│  Forge Engine  │  │  src/commander_ai_lab/                      │
│  (rules-       │  │    sim/   — engine, models, rules           │
│   complete)    │  │    deck_builder/ — 7-step LLM pipeline      │
└────────────────┘  │    coach/ — streaming LLM coach             │
                    └────────────────────────────────────────────┘
```

## Quick Start (Windows)

**Prerequisites:** Java 17+, Python 3.10+, Maven 3.8+, [Forge](https://github.com/Card-Forge/forge) built at `D:\ForgeCommander\forge-repo`

```powershell
# 1. Build Forge (one-time)
cd D:\ForgeCommander\forge-repo
mvn package -pl forge-gui-desktop "-DskipTests" "-Drevision=2.0.12-SNAPSHOT" -am

# 2. Build Commander AI Lab
cd D:\ForgeCommander\commander-ai-lab
mvn package "-DskipTests"

# 3. Install Python deps
pip install -e .

# 4. Launch
.\start-lab.bat
# → open http://localhost:8080
```

## Overnight AFK Runner

Runs batch sims unattended, then updates card weights and trains the neural net:

```powershell
python overnight-run.py                          # default: 11.5h DeepSeek sims
python overnight-run.py --batches 20 --games 50  # fixed batch count
python overnight-run.py --no-update-weights      # skip weight update
python overnight-run.py --no-train               # skip neural net training
```

**What happens after sims complete:**
1. `update_weights.py` — nudges `learned_weights.json` from decision logs (feeds deck builder)
2. `/api/ml/train` — trains the neural net on the full decision dataset

## Sim → Deck Builder Feedback Loop

Simulation outcomes automatically improve deck recommendations:

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

When active, `BuildResult.sources_consulted` includes `"sim_weights"`. No-op until real sim data exists.

## Deck Builder Pipeline

The `POST /api/deck-builder/build` endpoint runs 7 steps:

1. Resolve commander via Scryfall
2. Fetch EDHrec recommendations
3. Fetch Scryfall candidates by category (ramp, removal, draw, lands)
4. Ollama suggests synergy/protection/wincon cards ← **sim insights injected here**
5. Filter by color identity, collection, ban list
6. Ollama enforces ratios (trim/expand to 99) ← **sim insights injected here**
7. Assemble final deck

## ML Pipeline

```powershell
# Update sim card weights from decision logs (runs automatically in overnight-run.py)
python -m ml.scripts.update_weights --min-games 10 --lr 0.05 --dry-run

# Reset weights to defaults
python -m ml.scripts.update_weights --reset

# Generate synthetic training data
python ml/scripts/generate_synthetic_data.py
```

Learned weights are clamped to `[-20.0, 20.0]` and stored in `src/commander_ai_lab/sim/learned_weights.json`.

## Python Simulator API

```python
from commander_ai_lab.lab.experiments import build_deck, run_simulation

deck = build_deck(["Sol Ring", "Cultivate", "Lightning Bolt"] + ["Forest"] * 36)
stats = run_simulation(deck, num_games=100, name_a="My Deck")
print(f"Win rate: {stats['win_rate']:.1%}, Avg turns: {stats['avg_turns']:.1f}")
```

The Monte Carlo engine models: combat keywords (flying, trample, deathtouch, lifelink, menace, reach, haste), summoning sickness, tapped/untap state, commander zone, multiplayer attack targeting, and board wipes. It does **not** model the stack, instants, or continuous type-changing effects.

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/lab/decks` | GET | List available Commander decks |
| `/api/lab/start` | POST | Start Forge batch (returns batchId) |
| `/api/lab/start-deepseek` | POST | Start Python/DeepSeek batch |
| `/api/lab/status?batchId=X` | GET | Poll batch progress |
| `/api/lab/result?batchId=X` | GET | Get completed batch JSON |
| `/api/lab/history` | GET | List past batch runs |
| `/api/ml/train` | POST | Start neural net training |
| `/api/ml/train/status` | GET | Poll training progress |
| `/api/coach/chat` | POST | LLM coaching session (streaming) |
| `/api/deck-builder/build` | POST | Build a 99-card Commander deck |

## Project Structure

```
commander-ai-lab/
├── overnight-run.py              # AFK batch runner
├── start-lab.bat                 # Windows one-click launcher
├── lab_api.py                    # FastAPI server entry point
├── frontend/                     # React + TypeScript web UI
├── ui/                           # Legacy static HTML UI
├── src/commander_ai_lab/
│   ├── sim/                      # Monte Carlo engine (engine, models, rules)
│   ├── deck_builder/             # LLM deck builder pipeline
│   │   ├── api/                  # Scryfall, EDHrec, Ollama, sim_insights
│   │   ├── core/                 # Models, rules engine, assembler
│   │   └── pipeline/             # build_deck.py (7-step orchestrator)
│   └── coach/                    # LLM coaching (Anthropic + Ollama)
├── ml/
│   ├── scripts/                  # update_weights.py, ml_cli.py
│   ├── training/                 # Neural net trainer
│   ├── encoder/                  # Feature encoding
│   └── models/                   # Saved model checkpoints
├── scanner/                      # Card OCR pipeline
├── logs/decisions/               # ML decision logs (gitignored)
└── src/main/java/commanderailab/ # Java/Forge batch runner
```

## Known Limitations

- **Monte Carlo engine** — no stack, no instants, no continuous type changes (animated lands don't attack)
- **Forge engine** — each game spawns a new JVM (~2-3s overhead), ~0.04 sims/sec single-threaded
- **Forge winner life total** not captured (quiet mode only reports losers)
- **Deck builder** — Ollama suggestions are only as good as the local model; `qwen2.5:7b` works well
