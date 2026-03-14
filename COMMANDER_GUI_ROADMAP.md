# Commander-AI-Lab GUI + LLM Opponents Roadmap

## Project Summary

Build a playable Magic: The Gathering Commander interface where human players face AI opponents powered by a local LLM. The existing Python rules engine handles game legality and state management, while the LLM acts as the decision-making and narration brain for each AI opponent. A Pygame (or web-based) GUI renders the battlefield, zones, and card interactions. Each AI opponent gets a unique personality prompt to simulate different playstyles (aggro, control, combo, politics).

**Local LLM:** GPT-OSS 20B (Q4_K_M) via Ollama or LM Studio

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
GUI updates board state
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

### Phase 4 — GUI (Pygame or Web Frontend)
- [ ] Design zone layout: hand, battlefield (creature/non-creature split), graveyard, exile, command zone, stack
- [ ] Build card rendering: card art placeholder, name, P/T or loyalty, tapped/untapped state
- [ ] Add drag-and-drop (or click-to-play) card interaction for human player
- [ ] Display AI narration/flavor text in a chat-style side panel
- [ ] Add life total trackers and commander damage matrix (4-player)
- [ ] Build phase/step indicator (Main 1, Combat, Main 2, etc.)
- [ ] Add end-of-game screen with win condition display

### Phase 5 — Politics & Table Talk *(Stretch Goal)*
- [ ] Implement inter-AI negotiation: before attacking, AI queries GPT-OSS 20B "should I propose a deal?"
- [ ] Build deal proposal UI: AI proposes, human can accept/decline, other AIs respond
- [ ] Add threat-based targeting memory: AIs remember who attacked them last turn

### Phase 6 — Testing & Tuning
- [ ] Run 10 full simulated games (4 AI vs AI) and log decision quality
- [ ] Benchmark GPT-OSS 20B Q4_K_M inference time per decision on RTX 5070 Ti
- [ ] Tune context window compression to stay within model token limits
- [ ] Profile Pygame render loop for frame rate stability during AI thinking phases
- [ ] Add unit tests for `state_to_prompt()` and `decide_action()` parsing

---

## Tech Stack

| Component | Choice | Notes |
|---|---|---|
| GUI | Pygame | Fast to prototype, stays in Python |
| LLM Backend | Ollama or LM Studio | Serves GPT-OSS 20B locally |
| Model | **GPT-OSS 20B (Q4_K_M)** | ~12–14 GB VRAM, strong reasoning |
| Game State | Python dataclass | Structured, easy to serialize |
| Async | asyncio / threading | Keep GUI responsive during inference |
| Card Data | Scryfall API | Free MTG card data + art |

### GPT-OSS 20B Q4_K_M Notes
- Q4_K_M quantization balances quality and speed well for a 20B model
- Expected VRAM: ~12–14 GB on RTX 5070 Ti (16 GB VRAM) — fits comfortably
- Stronger reasoning than 7B models — better for multi-step MTG decision making
- Slower inference than smaller models — async handling is essential so GUI doesn't block
- System prompt + game state should be kept under ~3000 tokens to maintain fast response times
