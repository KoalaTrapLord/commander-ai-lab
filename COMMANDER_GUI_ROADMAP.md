# Commander-AI-Lab GUI + LLM Opponents Roadmap

## Project Summary

Build a playable Magic: The Gathering Commander interface where human players face AI opponents powered by a local LLM. The existing Python rules engine handles game legality and state management, while the LLM acts as the decision-making and narration brain for each AI opponent. A Pygame (or web-based) GUI renders the battlefield, zones, and card interactions. Each AI opponent gets a unique personality prompt to simulate different playstyles (aggro, control, combo, politics).

**Local LLM:** GPT-OSS 20B (Q4_K_M) via Ollama or LM Studio

---

## GUI Strategy: Two-Phase Frontend Plan

### Phase A (Prototype) — Pygame
Use **Pygame** for Phases 1–3 of development. Pure Python means the rules engine and AI opponent code plug in directly with zero bridging. Fast to iterate — a working battlefield renderer can be built in a day. Handles game loop, input events, and card rendering naturally. Ideal for testing AI decisions visually before investing in a polished UI.

### Phase B (Production) — Flask/FastAPI + Web Frontend
Once the core AI gameplay is working, migrate the UI to a **Flask or FastAPI backend + HTML/JS frontend** (vanilla JS or React). Benefits:
- Far more polished look for a Commander game
- Card art from Scryfall API renders natively in browser
- Easier to add multiplayer later via WebSockets
- Python backend stays pure — frontend calls it via REST API
- No Python/JS bridge complexity; clean separation of concerns

### GUI Framework Comparison

| Option | Language | Curve | Best For | Weakness |
|---|---|---|---|---|
| **Pygame** ✅ Phase A | Python | Low | Quick prototype, game loops | Dated UI, manual widgets |
| **Flask + HTML/JS** ✅ Phase B | Python + JS | Medium | Polished UI, browser-based | JS context switch |
| PyQt6 / PySide6 | Python | Medium | Desktop app widgets | Verbose, overkill for a game |
| Godot | GDScript | Medium | Full game engine, animations | Separate codebase from engine |
| Electron + Python | JS + Python | High | Desktop with web UI | Heavy, complex bridge |
| Tkinter | Python | Low | Simple UI | Very dated look |

---

## Architecture Overview

```
Game State (Python dict/dataclass)
        ↓
Legal Moves Generator (rules engine)
        ↓
LLM Prompt: "Given this state and these legal moves, what do you do?"
        ↓ (GPT-OSS 20B Q4_K_M)
LLM Response → parsed action
        ↓
Rules Engine executes + validates
        ↓
GUI updates board state (Pygame → Web)
```

---

## Task List

### Phase 1 — Game State Serialization
- [ ] Define a compressed game state schema (Python dataclass or dict) covering: hand, battlefield, graveyard, exile, stack, life totals, commander zone, mana pool
- [ ] Write a `state_to_prompt()` function that converts game state to a compact LLM-readable string
- [ ] Write a `legal_moves_to_prompt()` function that lists valid actions in numbered format for LLM selection
- [ ] Add a state snapshot logger for debugging AI decisions

### Phase 2 — LLM AI Opponent Integration
- [ ] Load GPT-OSS 20B (Q4_K_M) in Ollama or LM Studio; verify inference speed on RTX 5070 Ti
- [ ] Benchmark VRAM usage for GPT-OSS 20B Q4_K_M (expected ~12–14 GB VRAM at Q4_K_M quantization)
- [ ] Build `AIOpponent` class with fields: name, personality_prompt, model_endpoint, deck
- [ ] Implement `decide_action(game_state, legal_moves)` method — sends prompt to GPT-OSS 20B, parses LLM response, returns validated action index
- [ ] Add fallback logic: if LLM returns invalid/unparseable action, default to highest-priority heuristic move
- [ ] Write personality prompt templates (Aggro Timmy, Control Spike, Combo Johnny, Political Negotiator)
- [ ] Add narration method: `narrate_play(action)` — GPT-OSS 20B generates in-character flavor text for each play
- [ ] Tune system prompt length to stay within GPT-OSS 20B context window limits

### Phase 3 — Multi-Player Turn Management
- [ ] Implement turn queue: Player → AI1 → AI2 → AI3 → repeat
- [ ] Run AI decisions asynchronously (threading or asyncio) so GUI stays responsive during LLM inference
- [ ] Add priority-passing logic for instants/triggers during other players' turns
- [ ] Implement basic AI threat assessment: each AI scores opponents by board state danger level

### Phase 4 — Pygame Prototype GUI
- [ ] Design zone layout: hand, battlefield (creature/non-creature split), graveyard, exile, command zone, stack
- [ ] Build card rendering: card art placeholder, name, P/T or loyalty, tapped/untapped state
- [ ] Add click-to-play card interaction for human player
- [ ] Display AI narration/flavor text in a side panel
- [ ] Add life total trackers and commander damage matrix (4-player)
- [ ] Build phase/step indicator (Main 1, Combat, Main 2, etc.)
- [ ] Add end-of-game screen with win condition display

### Phase 5 — Web Frontend Migration *(Flask/FastAPI + HTML/JS)*
- [ ] Set up Flask or FastAPI backend exposing game state as REST API
- [ ] Build HTML/JS board layout mirroring Pygame zone design
- [ ] Integrate Scryfall API for card art rendering
- [ ] Add WebSocket support for real-time game state updates
- [ ] Add drag-and-drop card interaction
- [ ] Port AI narration panel to web chat-style UI
- [ ] Test full game loop end-to-end on web frontend

### Phase 6 — Politics & Table Talk *(Stretch Goal)*
- [ ] Implement inter-AI negotiation: before attacking, AI queries GPT-OSS 20B "should I propose a deal?"
- [ ] Build deal proposal UI: AI proposes, human can accept/decline, other AIs respond
- [ ] Add threat-based targeting memory: AIs remember who attacked them last turn

### Phase 7 — Testing & Tuning
- [ ] Run 10 full simulated games (4 AI vs AI) and log decision quality
- [ ] Benchmark GPT-OSS 20B Q4_K_M inference time per decision on RTX 5070 Ti
- [ ] Tune context window compression to stay within model token limits
- [ ] Profile Pygame and web render loops for stability during AI thinking phases
- [ ] Add unit tests for `state_to_prompt()` and `decide_action()` parsing

### Phase 8 — Multiplayer (Human vs Human + AI)
- [ ] **Lobby system** — create/join game rooms with configurable seat count (2–4 players); assign each seat as Human or AI
- [ ] **WebSocket game server** — upgrade Flask/FastAPI backend to handle persistent connections for real-time state sync across multiple browser clients
- [ ] **Player session management** — unique session tokens per human player; reconnect support if connection drops mid-game
- [ ] **Private hand views** — each human player sees only their own hand; other hands shown as face-down card backs
- [ ] **Turn notification system** — alert active player when it's their turn (browser notification or in-page indicator)
- [ ] **Action broadcast** — all players see each action played in real-time (card played, attack declared, ability activated) via WebSocket push
- [ ] **Mixed lobby support** — allow any combination of human and AI seats (e.g., 2 humans + 2 AIs, or 1 human + 3 AIs)
- [ ] **Spectator mode** — allow observers to watch a game without participating; full board visible, no hand info
- [ ] **Local LAN play** — host game server on local network so friends can connect via browser on the same Wi-Fi (no internet required)
- [ ] **Optional: Remote play** — expose server via ngrok or Tailscale for play over the internet without full deployment
- [ ] **Multiplayer AI pacing** — add configurable AI decision delay (e.g., 1–3 sec) so human players can follow AI turns without them resolving instantly
- [ ] **Chat panel** — in-game text chat between human players; AI opponents can optionally post narration lines into the same channel
- [ ] **End-of-game summary** — show full game recap (turns played, damage dealt, commanders cast count) visible to all players after win condition met

---

## Tech Stack

| Component | Choice | Notes |
|---|---|---|
| GUI (Prototype) | **Pygame** | Pure Python, fast iteration |
| GUI (Production) | **Flask/FastAPI + HTML/JS** | Polished, browser-based |
| Multiplayer | **WebSockets (Flask-SocketIO)** | Real-time state sync across clients |
| LLM Backend | Ollama or LM Studio | Serves GPT-OSS 20B locally |
| Model | **GPT-OSS 20B (Q4_K_M)** | ~12–14 GB VRAM, strong reasoning |
| Game State | Python dataclass | Structured, easy to serialize |
| Async | asyncio / threading | Keep GUI responsive during inference |
| Card Data | Scryfall API | Free MTG card data + art |
| LAN Hosting | Local network / ngrok | No deployment needed for local play |

### GPT-OSS 20B Q4_K_M Notes
- Q4_K_M quantization balances quality and speed well for a 20B model
- Expected VRAM: ~12–14 GB on RTX 5070 Ti (16 GB VRAM) — fits comfortably
- Stronger reasoning than 7B models — better for multi-step MTG decision making
- Slower inference than smaller models — async handling is essential so GUI doesn't block
- System prompt + game state should be kept under ~3000 tokens to maintain fast response times
