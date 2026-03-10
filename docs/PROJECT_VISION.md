# Commander AI Lab — Project Vision

## Vision Statement

Commander AI Lab is a headless, batch-oriented simulation environment for Magic: The Gathering Commander that pits 3 AI-controlled decks against each other in automated games, collects structured JSON results, and surfaces actionable statistics—win rates, average turns to win, mulligan rates, and win-condition breakdowns. By wrapping the open-source Forge rules engine in a programmable pipeline, the lab enables deck builders to stress-test strategies at scale (hundreds or thousands of simulated games) without manual play, providing data-driven insights into Commander deck performance.

## Core v1 Goals

1. **Headless 3-AI Simulations** — Run Commander games with 3 AI players, no GUI, no human input, leveraging Forge's built-in `sim` mode with Commander format support.
2. **JSON Batch Results** — Every batch run produces a structured JSON file conforming to a defined schema, containing per-game outcomes, per-deck statistics, and run metadata.
3. **Basic Statistics** — Compute and report:
   - Win rate per deck
   - Average turns to win
   - Mulligan frequency per deck
   - Win condition classification (commander damage, combat damage, combo/alt-win, concession/timeout)

## v1 Scope

| In Scope | Out of Scope |
|----------|-------------|
| Fixed 3-player pods | 4-player pods (v2) |
| Fixed/pre-built decks only | Dynamic deck generation |
| Forge's built-in AI (utility-based) | Reinforcement learning / training UI |
| No politics, no table talk | Multiplayer human players |
| CLI batch runner | EDHREC / meta integration |
| JSON export to file | Database persistence |
| Single-thread + multi-thread batch | Distributed / cloud execution |
| Basic stats dashboard in web UI | Advanced analytics / ML insights |

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                Commander AI Lab                      │
│                                                      │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │ CLI /    │──▶│ Batch Runner │──▶│ Stats        │ │
│  │ Web UI   │   │ (single/mt)  │   │ Aggregator   │ │
│  └──────────┘   └──────┬───────┘   └──────┬───────┘ │
│                        │                   │         │
│                        ▼                   ▼         │
│              ┌──────────────┐     ┌──────────────┐   │
│              │ Forge Engine │     │ JSON Export   │   │
│              │ (sim mode)   │     │ (schema v1)  │   │
│              └──────────────┘     └──────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ AI Policy Layer                               │    │
│  │ • Card advantage scoring                      │    │
│  │ • Tempo / mana efficiency                     │    │
│  │ • Threat scoring per opponent                 │    │
│  │ • Basic combat logic                          │    │
│  └──────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

## Current Components (Inventory)

### Existing Pieces
1. **Forge-based rules engine** (`forge-commander-engine`) — Java 17/Maven project wrapping Forge with `BridgePlayerController` for JSON-serialized decisions.
2. **Bridge/JSON controller** — `BridgePlayerController.java` serializes gameplay decisions as JSON, `StdioBridgeTransport` and `InProcessTransport` handle communication.
3. **Web simulator UI** (`mtg-commander-lan`) — HTML/CSS/JS Commander simulator with board state, Scryfall integration, deck builder, collection tracker, token system.
4. **Deck builder / tracker** — Integrated into web simulator with localStorage persistence, Scryfall API card data.

### Missing Pieces (To Build)
1. **Batch Runner** — Orchestration layer that invokes Forge `sim` mode repeatedly, collects output, handles threading.
2. **AI Policy Class** — Abstraction layer over Forge's built-in AI with configurable heuristic weights for Commander-specific decisions.
3. **Stats Aggregation** — Module to parse game outcomes and compute win rates, turn counts, mulligan rates, win conditions.
4. **JSON Export** — Structured serialization of batch results conforming to the defined schema.
5. **CLI Entry Point** — Command-line interface to trigger batch runs with parameters.
6. **Web UI Integration** — Deck selection, "Run N sims" button, results display in the existing web simulator.
