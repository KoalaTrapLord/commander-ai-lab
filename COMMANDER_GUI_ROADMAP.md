# Commander-AI-Lab GUI + LLM Opponents Roadmap

## Project Summary

Build a playable Magic: The Gathering Commander interface where human players face AI opponents powered by a local LLM. The existing Python rules engine handles game legality and state management, while the LLM acts as the decision-making and narration brain for each AI opponent. A Pygame (or web-based) GUI renders the battlefield, zones, and card interactions. Each AI opponent gets a unique personality prompt to simulate different playstyles (aggro, control, combo, politics).

---

## Architecture Overview

```
Game State (Python dict/dataclass)
        ↓
Legal Moves Generator (rules engine)
        ↓
LLM Prompt: "Given this state and these legal moves, what do you do?"
        ↓
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
- [ ] Set up Ollama or LM Studio endpoint for local model inference (Mistral 7B or Llama 3.2 recommended)
- [ ] Build `AIOpponent` class with fields: name, personality_prompt, model_endpoint, deck
- [ ] Implement `decide_action(game_state, legal_moves)` method — sends prompt, parses LLM response, returns validated action index
- [ ] Add fallback logic: if LLM returns invalid/unparseable action, default to highest-priority heuristic move
- [ ] Write personality prompt templates (Aggro Timmy, Control Spike, Combo Johnny, Political Negotiator)
- [ ] Add narration method: `narrate_play(action)` — LLM generates in-character flavor text for each play

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
- [ ] Implement inter-AI negotiation: before attacking, AI queries LLM "should I propose a deal?"
- [ ] Build deal proposal UI: AI proposes, human can accept/decline, other AIs respond
- [ ] Add threat-based targeting memory: AIs remember who attacked them last turn

### Phase 6 — Testing & Tuning
- [ ] Run 10 full simulated games (4 AI vs AI) and log decision quality
- [ ] Benchmark LLM inference time per decision on RTX 5070 Ti
- [ ] Tune context window compression to stay under 4096 tokens per prompt
- [ ] Profile Pygame render loop for frame rate stability during AI thinking phases
- [ ] Add unit tests for `state_to_prompt()` and `decide_action()` parsing

---

## Tech Stack Recommendations

| Component | Recommended Option | Notes |
|---|---|---|
| GUI | Pygame | Fast to prototype, stays in Python |
| LLM Backend | Ollama (local) | Free, runs on RTX 5070 Ti |
| Model | Mistral 7B or Llama 3.2 | Good reasoning, fast on local GPU |
| Game State | Python dataclass | Structured, easy to serialize |
| Async | asyncio / threading | Keep GUI responsive during inference |
| Card Data | Scryfall API | Free MTG card data + art |
