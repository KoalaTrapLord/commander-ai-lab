# Commander-AI-Lab — Unity TCGEngine Commander Board: Implementation Plan (v5)

> **Architecture Principle:** Forge = Rules Authority · FastAPI = Hub · TCGEngine Unity = Renderer · Dual-Brain AI = Decision Engine

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    UNITY (TCGEngine — 2D Board)                 │
│  PlayerArea x4: Hand | Library | Graveyard | Exile | Command    │
│  Battlefield zones per player · Card art from local cache       │
│  GameNetworkManager.cs ←── WebSocket ──► FastAPI                │
└─────────────────────────────────────────────────────────────────┘
                              ▲ ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FASTAPI (commander-ai-lab)                      │
│  /ws/game  — WebSocket relay                                    │
│  /game/action — receive player/AI action, forward to Forge      │
│  ForgeSubprocessManager — stdin/stdout pipe to Forge JVM        │
│  CardEnricher — injects art_url from local image cache          │
│  AIOrchestrator — routes decisions to DeepSeek-R1 or GPT-OSS   │
│  ChromaDB RAG — card knowledge scoped per player deck           │
│  ai_decisions.jsonl — logs every AI decision (PPO dataset)      │
└─────────────────────────────────────────────────────────────────┘
                              ▲ ▼
┌─────────────────────────────────────────────────────────────────┐
│              FORGE (Java — Headless Rules Engine)               │
│  Full Commander rules: tax, 21-commander-damage, 40 life        │
│  4-player turn queue · Zone redirects · State-based actions     │
│  Emits game state JSON to stdout · Receives actions via stdin   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Dual-Brain AI Decision Flow

This is the **core feature** of Commander-AI-Lab. Every AI player decision runs through this pipeline:

```
Forge emits GameStateDTO (JSON)
  └─► FastAPI detects active player is AI
        └─► select_brain(phase, stack_size)
              ├─ DeepSeek-R1-14B  → combat, stack decisions, removal
              └─ GPT-OSS-20B      → main phase, ramp, card advantage
                    └─► ChromaDB.query(player_deck_cards, top_k=5)
                          └─► build_prompt(state, rag_context, personality)
                                └─► LLM.generate(prompt)
                                      └─► parse_action_json(response)
                                            ├─ validate vs legal_actions[]
                                            ├─ log to ai_decisions.jsonl
                                            └─► Forge stdin ← chosen action
```

### Brain Selector (`ai/brain_selector.py`)

```python
from enum import Enum

class Brain(Enum):
    DEEPSEEK = "deepseek-r1:14b"
    GPT_OSS  = "gpt-oss-20b"       # adjust to your Ollama model tag

def select_brain(phase: str, stack_size: int) -> Brain:
    """
    DeepSeek-R1: combat math, instant-speed stack decisions, targeted removal.
    GPT-OSS:     sorcery-speed strategy, ramp sequencing, card selection.
    """
    combat_phases = {"declare_attackers", "declare_blockers", "combat_damage"}
    if phase in combat_phases or stack_size > 0:
        return Brain.DEEPSEEK
    return Brain.GPT_OSS
```

### Prompt Builder (`ai/prompt_builder.py`)

```python
from chromadb import Client
from .personality import get_personality_prompt

chroma = Client()
card_collection = chroma.get_collection("mtg_cards")

def build_prompt(state: dict, player_id: str, personality: str) -> str:
    # Pull card knowledge scoped to THIS player's deck
    player_cards = [c["name"] for c in state["players"][player_id]["library"]]
    rag_results  = card_collection.query(
        query_texts=player_cards[:10],
        n_results=5
    )
    card_context = "\n".join(rag_results["documents"][0])

    personality_prompt = get_personality_prompt(personality)

    return f"""You are an AI playing Magic: The Gathering Commander.
{personality_prompt}

## Current Game State
- Phase: {state['phase']}
- Active Player: {player_id}
- Life Totals: {state['life_totals']}
- Commander Damage Dealt: {state['commander_damage']}
- Stack: {state['stack']}
- Your Hand: {[c['name'] for c in state['players'][player_id]['hand']]}
- Battlefield: {[c['name'] for c in state['players'][player_id]['battlefield']]}
- Available Mana: {state['players'][player_id]['mana_pool']}

## Legal Actions
{state['legal_actions']}

## Card Knowledge (RAG Context)
{card_context}

Respond with a single JSON object:
{{"action": "<action_type>", "card_id": "<id_or_null>", "targets": [], "reasoning": "<brief>"}}
"""
```

### Personality System (`ai/personality.py`)

```python
import random

PERSONALITIES = {
    "aggro_beatdown": "You play aggressively. Attack every turn. Remove blockers. Win through combat damage as fast as possible.",
    "control_lockdown": "You play control. Counter key threats. Hold up mana for interaction. Win only when the board is locked.",
    "combo_enabler": "You dig for your combo pieces. Every decision is evaluated by how it advances your win condition.",
    "political_diplomat": "You form alliances. Attack the leader. Make deals. Never be the archenemy.",
    "voltron_commander": "Everything buffs your commander. Protect it at all costs. Win through commander damage.",
    "stax_prison": "You tax and restrict opponents. Deploy hate pieces. Win through attrition and resource denial.",
    "tempo_value": "You trade efficiently. Generate card advantage. Win by being ahead on resources.",
    "chaos_wildcard": "You make unpredictable decisions. Prioritize fun and chaos over optimal play.",
}

def assign_personalities(player_ids: list[str], deck_archetypes: dict) -> dict[str, str]:
    """
    Assign a personality per AI player at game creation.
    80% chance: archetype-matched personality.
    20% chance: random wildcard for unpredictability.
    """
    assignments = {}
    for pid in player_ids:
        archetype = deck_archetypes.get(pid, "tempo_value")
        if random.random() < 0.20:
            assignments[pid] = random.choice(list(PERSONALITIES.keys()))
        else:
            assignments[pid] = archetype
    return assignments

def get_personality_prompt(personality: str) -> str:
    return f"## Your Playstyle\n{PERSONALITIES.get(personality, PERSONALITIES['tempo_value'])}"
```

### AI Orchestrator (`ai/ai_orchestrator.py`)

```python
import json, time, logging
from pathlib import Path
from .brain_selector import select_brain, Brain
from .prompt_builder import build_prompt
import ollama

LOG_PATH = Path("logs/ai_decisions.jsonl")
LOG_PATH.parent.mkdir(exist_ok=True)

async def get_ai_action(state: dict, player_id: str, personality: str) -> dict:
    brain   = select_brain(state["phase"], len(state["stack"]))
    prompt  = build_prompt(state, player_id, personality)
    t_start = time.time()

    try:
        response = ollama.chat(
            model=brain.value,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3, "num_predict": 256}
        )
        raw = response["message"]["content"]
        # Extract JSON from response (model may wrap in markdown)
        action = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except Exception as e:
        logging.warning(f"AI parse failed ({brain.value}): {e}. Passing turn.")
        action = {"action": "pass", "card_id": None, "targets": [], "reasoning": "parse_error"}

    # Validate against Forge legal actions
    if action.get("action") not in [a["type"] for a in state["legal_actions"]]:
        logging.warning(f"Illegal action returned by {brain.value}. Falling back to pass.")
        action = {"action": "pass", "card_id": None, "targets": [], "reasoning": "illegal_action"}

    # Log for PPO training dataset
    log_entry = {
        "timestamp":   time.time(),
        "player_id":   player_id,
        "brain":       brain.value,
        "personality": personality,
        "phase":       state["phase"],
        "action":      action,
        "reasoning":   action.get("reasoning", ""),
        "latency_ms":  round((time.time() - t_start) * 1000),
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return action
```

---

## Phase 0 — Local Card Image Cache

**Build this first.** Every downstream system depends on local art URLs.

### Step 1 — Bulk Download (`scripts/download_card_images.py`)

```python
import requests, json, os
from pathlib import Path
from tqdm import tqdm

BULK_URL  = "https://api.scryfall.com/bulk-data/default-cards"
IMAGE_DIR = Path("static/card-images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

def download_images():
    # Get bulk data URL
    meta = requests.get(BULK_URL).json()
    cards = requests.get(meta["download_uri"], stream=True).json()

    for card in tqdm(cards, desc="Downloading card images"):
        image_uris = card.get("image_uris") or {}
        url = image_uris.get("normal")
        if not url:
            continue  # skip DFCs without top-level image_uris

        safe_name = card["name"].replace("/", "_").replace(" ", "_")
        set_code  = card.get("set", "unknown")
        filename  = IMAGE_DIR / set_code / f"{safe_name}_{card['collector_number']}.jpg"
        filename.parent.mkdir(parents=True, exist_ok=True)

        if filename.exists():
            continue  # already cached

        img_data = requests.get(url, timeout=10).content
        filename.write_bytes(img_data)

if __name__ == "__main__":
    download_images()
```

### Step 2 — Build SQLite Index (`scripts/build_image_index.py`)

```python
import sqlite3
from pathlib import Path

IMAGE_DIR = Path("static/card-images")
DB_PATH   = Path("data/card_images.db")
DB_PATH.parent.mkdir(exist_ok=True)

def build_index():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS card_images (
            name TEXT PRIMARY KEY,
            path TEXT NOT NULL
        )
    """)
    for img_path in IMAGE_DIR.rglob("*.jpg"):
        card_name = img_path.stem.rsplit("_", 1)[0].replace("_", " ")
        conn.execute("INSERT OR REPLACE INTO card_images VALUES (?, ?)",
                     (card_name, str(img_path)))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    build_index()
```

### Step 3 — Card Enricher (`api/card_enricher.py`)

```python
import sqlite3
from pathlib import Path

DB_PATH    = Path("data/card_images.db")
STATIC_URL = "http://localhost:8000/static/card-images"

def enrich_card(card: dict) -> dict:
    """Inject local art_url into every CardDTO before sending to Unity."""
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT path FROM card_images WHERE name = ?", (card["name"],))
    row    = cursor.fetchone()
    conn.close()
    if row:
        relative = Path(row[0]).relative_to("static/card-images")
        card["art_url"] = f"{STATIC_URL}/{relative}"
    else:
        card["art_url"] = f"{STATIC_URL}/card_back.jpg"
    return card
```

### Step 4 — FastAPI Static Mount (`main.py` addition)

```python
from fastapi.staticfiles import StaticFiles
app.mount("/static/card-images", StaticFiles(directory="static/card-images"), name="card-images")
```

---

## Phase 1 — Forge Bridge (Rules Engine)

### ForgeSubprocessManager (`forge/subprocess_manager.py`)

```python
import subprocess, json, asyncio, threading
from pathlib import Path

FORGE_JAR = Path("forge/forge-game.jar")

class ForgeSubprocessManager:
    def __init__(self):
        self.process = None
        self._lock   = threading.Lock()

    def start(self, deck_paths: list[str], format: str = "commander"):
        cmd = [
            "java", "-jar", str(FORGE_JAR),
            "--headless",
            "--format", format,
            "--decks", *deck_paths,
            "--output", "json"
        ]
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

    def read_state(self) -> dict:
        with self._lock:
            line = self.process.stdout.readline()
            return json.loads(line)

    def send_action(self, action: dict):
        with self._lock:
            self.process.stdin.write(json.dumps(action) + "\n")
            self.process.stdin.flush()

    def stop(self):
        if self.process:
            self.process.terminate()
```

### Data Transfer Objects (`api/dtos.py`)

```python
from pydantic import BaseModel
from typing import Optional

class CardDTO(BaseModel):
    id:       str
    name:     str
    type:     str
    power:    Optional[str]
    toughness: Optional[str]
    mana_cost: str
    art_url:  str = ""
    tapped:   bool = False
    zone:     str  = "hand"

class PlayerDTO(BaseModel):
    id:               str
    life:             int
    commander_damage: dict[str, int]
    commander_tax:    int
    hand:             list[CardDTO]
    battlefield:      list[CardDTO]
    graveyard:        list[CardDTO]
    exile:            list[CardDTO]
    command_zone:     list[CardDTO]
    library_count:    int
    mana_pool:        dict[str, int]
    is_ai:            bool
    personality:      Optional[str]

class GameStateDTO(BaseModel):
    game_id:      str
    phase:        str
    active_player: str
    priority:     str
    turn_number:  int
    players:      list[PlayerDTO]
    stack:        list[dict]
    legal_actions: list[dict]
    winner:       Optional[str]
```

---

## Phase 2 — FastAPI WebSocket Game Server

### Game Loop (`api/game_loop.py`)

```python
import asyncio, uuid
from .dtos import GameStateDTO
from forge.subprocess_manager import ForgeSubprocessManager
from ai.ai_orchestrator import get_ai_action
from ai.personality import assign_personalities
from api.card_enricher import enrich_card

active_games: dict[str, dict] = {}

async def start_game(deck_paths: list[str], ai_players: list[str]) -> str:
    game_id = str(uuid.uuid4())
    forge   = ForgeSubprocessManager()
    forge.start(deck_paths)

    # Assign AI personalities at game creation
    archetypes   = detect_archetypes(deck_paths, ai_players)   # ChromaDB query
    personalities = assign_personalities(ai_players, archetypes)

    active_games[game_id] = {
        "forge":         forge,
        "ai_players":    ai_players,
        "personalities": personalities,
        "websockets":    []
    }
    asyncio.create_task(game_loop(game_id))
    return game_id

async def game_loop(game_id: str):
    game  = active_games[game_id]
    forge = game["forge"]

    while True:
        raw_state = forge.read_state()
        if raw_state.get("winner"):
            await broadcast(game_id, raw_state)
            break

        # Enrich every card with local art_url
        state = enrich_state(raw_state)
        await broadcast(game_id, state)

        priority_player = state["priority"]
        if priority_player in game["ai_players"]:
            personality = game["personalities"][priority_player]
            action = await get_ai_action(state, priority_player, personality)
            forge.send_action(action)
        # else: wait for Unity client to send action via WebSocket

async def broadcast(game_id: str, state: dict):
    game = active_games[game_id]
    for ws in game["websockets"]:
        await ws.send_json(state)

def enrich_state(state: dict) -> dict:
    for player in state["players"]:
        for zone in ["hand", "battlefield", "graveyard", "exile", "command_zone"]:
            player[zone] = [enrich_card(c) for c in player.get(zone, [])]
    return state
```

### WebSocket Endpoint (`api/routes/game.py`)

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from api.game_loop import active_games, start_game

router = APIRouter()

@router.websocket("/ws/game/{game_id}")
async def game_ws(websocket: WebSocket, game_id: str):
    await websocket.accept()
    game = active_games.get(game_id)
    if not game:
        await websocket.close(code=4004)
        return
    game["websockets"].append(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Human player action forwarded directly to Forge
            game["forge"].send_action(data)
    except WebSocketDisconnect:
        game["websockets"].remove(websocket)
```

---

## Phase 3 — Unity TCGEngine Board (2D)

### Project Layout

```
unity-commander-ui/
├── Assets/
│   ├── TCGEngine/          ← TCGEngine base (unmodified)
│   ├── Commander/
│   │   ├── Scripts/
│   │   │   ├── GameNetworkManager.cs    ← WebSocket ↔ FastAPI
│   │   │   ├── CommanderBoardUI.cs      ← 4-player layout controller
│   │   │   ├── PlayerAreaUI.cs          ← per-player zone panel
│   │   │   ├── CardImageLoader.cs       ← local cache texture fetcher
│   │   │   ├── ZonePanel.cs             ← Hand/Library/Graveyard/Exile/Command
│   │   │   └── AIThinkingIndicator.cs   ← spinner while AI brain is deciding
│   │   └── Prefabs/
│   │       ├── CardPrefab.prefab
│   │       ├── PlayerAreaPrefab.prefab
│   │       └── ZonePanelPrefab.prefab
│   └── Scenes/
│       └── CommanderBoard.unity
```

### Board Layout (matches screenshot)

```
┌──────────────────────────────────────────────────────────────────┐
│  [LIBRARY][GRAVEYARD][EXILE]  [────── HAND ──────]    (Player 3) │
│  [COMMAND]                                                        │
├──────────────────────────────┬───────────────────────────────────┤
│                              │                                    │
│                              │                                    │
│        BATTLEFIELD           │          BATTLEFIELD              │
│        (Player 1)            │          (Player 2)               │
│                   BATTLEFIELD (center)                           │
│        BATTLEFIELD           │          BATTLEFIELD              │
│        (Player 4)            │          (Player 3)               │
│                              │                                    │
├──────────────────────────────┴───────────────────────────────────┤
│  [COMMAND]                                                        │
│  [LIBRARY][GRAVEYARD][EXILE]  [────── HAND ──────]    (Player 1) │
└──────────────────────────────────────────────────────────────────┘
```

### GameNetworkManager.cs

```csharp
using UnityEngine;
using NativeWebSocket;
using Newtonsoft.Json;

public class GameNetworkManager : MonoBehaviour
{
    public static GameNetworkManager Instance { get; private set; }

    [SerializeField] private string serverUrl = "ws://localhost:8000/ws/game/";
    [SerializeField] private string gameId;

    private WebSocket _socket;

    public delegate void GameStateReceived(GameStateDTO state);
    public event GameStateReceived OnGameStateReceived;

    async void Awake()
    {
        Instance = this;
        _socket  = new WebSocket($"{serverUrl}{gameId}");

        _socket.OnMessage += (bytes) =>
        {
            var json  = System.Text.Encoding.UTF8.GetString(bytes);
            var state = JsonConvert.DeserializeObject<GameStateDTO>(json);
            UnityMainThreadDispatcher.Enqueue(() => OnGameStateReceived?.Invoke(state));
        };

        await _socket.Connect();
    }

    public async void SendAction(object action)
    {
        var json = JsonConvert.SerializeObject(action);
        await _socket.SendText(json);
    }

    void Update() => _socket?.DispatchMessageQueue();

    async void OnDestroy() => await _socket?.Close();
}
```

### CardImageLoader.cs

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

public class CardImageLoader : MonoBehaviour
{
    private static Dictionary<string, Texture2D> _cache = new();

    public static IEnumerator LoadCardArt(string artUrl, RawImage target)
    {
        if (_cache.TryGetValue(artUrl, out var cached))
        {
            target.texture = cached;
            yield break;
        }

        using var req = UnityWebRequestTexture.GetTexture(artUrl);
        yield return req.SendWebRequest();

        if (req.result == UnityWebRequest.Result.Success)
        {
            var tex = DownloadHandlerTexture.GetContent(req);
            _cache[artUrl] = tex;
            target.texture = tex;
        }
        else
        {
            Debug.LogWarning($"Failed to load card art: {artUrl}");
        }
    }
}
```

### AIThinkingIndicator.cs

```csharp
using UnityEngine;
using UnityEngine.UI;

/// Shows a spinner + brain label while the AI is deciding.
public class AIThinkingIndicator : MonoBehaviour
{
    [SerializeField] private GameObject spinnerPanel;
    [SerializeField] private Text brainLabel;
    [SerializeField] private Text personalityLabel;

    public void Show(string brain, string personality)
    {
        spinnerPanel.SetActive(true);
        brainLabel.text      = $"🧠 {brain}";
        personalityLabel.text = $"🎭 {personality}";
    }

    public void Hide() => spinnerPanel.SetActive(false);
}
```

---

## Phase 4 — Commander Zone UIs

### Zone Definitions per Player

| Zone Panel | Content | Notes |
|---|---|---|
| `LIBRARY` | Count only | Click → draw/look at top |
| `GRAVEYARD` | Scrollable card list | Full card art on hover |
| `EXILE` | Scrollable card list | Includes face-down indicators |
| `HAND` | Wide panel, card art | Hidden to opponents |
| `COMMAND` | Commander card(s) | Shows commander tax counter |
| `BATTLEFIELD` | Open grid | Tapped/untapped state, counters |

### Commander-Specific UI Elements

```csharp
public class CommanderZoneUI : MonoBehaviour
{
    [SerializeField] private Text taxCounter;      // "Tax: +{2N}"
    [SerializeField] private RawImage commanderArt;
    [SerializeField] private Text commanderDamageDealt; // per opponent

    public void Refresh(PlayerDTO player)
    {
        int tax = player.CommanderTax;
        taxCounter.text = tax > 0 ? $"+{tax * 2}" : "";

        if (player.CommandZone.Count > 0)
            StartCoroutine(CardImageLoader.LoadCardArt(
                player.CommandZone[0].ArtUrl, commanderArt));
    }
}
```

---

## Phase 5 — Commander Rules Validation Layer

Forge handles all rules natively. FastAPI validates the AI response is within the legal actions list Forge returns — no custom rules code needed in Python or Unity.

Key Commander rules confirmed handled by Forge headless:
- **Commander Tax** — +2 generic per previous cast from command zone
- **21 Commander Damage** — tracked per attacker/defender pair
- **40 Starting Life**
- **Zone Redirect** — commander goes to command zone instead of graveyard/exile (player choice)
- **Color Identity** — deck validation at game start
- **Singleton** — deck validation at game start

---

## Phase 6 — AI Decision Logging & PPO Pipeline

Every AI decision written to `logs/ai_decisions.jsonl`:

```json
{
  "timestamp": 1743520800.123,
  "player_id": "player_2",
  "brain": "deepseek-r1:14b",
  "personality": "aggro_beatdown",
  "phase": "declare_attackers",
  "action": {"action": "attack", "card_id": "c_042", "targets": ["player_1"], "reasoning": "Open attack, no blockers visible"},
  "latency_ms": 847
}
```

This log becomes the **supervised learning dataset** for the next PPO training iteration. Each (state, action) pair from winning games is a positive training example.

---

## Project Directory Structure

```
commander-ai-lab/
├── main.py                          ← FastAPI app, mounts static files
├── api/
│   ├── dtos.py                      ← Pydantic DTOs
│   ├── card_enricher.py             ← Injects art_url into CardDTOs
│   ├── game_loop.py                 ← Main game orchestration loop
│   └── routes/
│       └── game.py                  ← WebSocket + REST endpoints
├── ai/
│   ├── ai_orchestrator.py           ← Main AI decision entry point
│   ├── brain_selector.py            ← DeepSeek-R1 vs GPT-OSS routing
│   ├── prompt_builder.py            ← Game state + RAG → prompt
│   └── personality.py               ← 8 personalities + assignment
├── forge/
│   └── subprocess_manager.py        ← Forge JVM stdin/stdout bridge
├── scripts/
│   ├── download_card_images.py      ← One-time Scryfall bulk download
│   └── build_image_index.py         ← SQLite name→path index
├── static/
│   └── card-images/                 ← ~2GB local image cache
│       └── {set_code}/
│           └── {CardName}_{num}.jpg
├── data/
│   └── card_images.db               ← SQLite image index
├── logs/
│   └── ai_decisions.jsonl           ← PPO training dataset
├── unity-commander-ui/              ← Unity 2D TCGEngine project
└── docs/
    └── implementation_plan.md       ← This document
```

---

## Phased Timeline

| Phase | Scope | Est. Time |
|---|---|---|
| **0** | Scryfall image download + SQLite index + FastAPI static mount | 1 day |
| **1** | Forge subprocess bridge + DTO definitions | 2–3 days |
| **2** | AI Orchestrator + brain selector + prompt builder + personality system | 3–4 days |
| **3** | Unity TCGEngine project setup + WebSocket GameNetworkManager | 3–4 days |
| **4** | PlayerAreaUI + ZonePanels + CardImageLoader + board layout | 3–4 days |
| **5** | Commander zone UI (tax counter, commander damage, zone redirect) | 1–2 days |
| **6** | AI decision logging + end-to-end game loop test | 1–2 days |

**Total estimated: ~3 weeks to first playable Commander game with live AI opponents.**

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Forge = rules authority | Forge already handles all Commander rules natively. No custom rules code. |
| TCGEngine = dumb renderer | All game logic lives in Forge. Unity only renders state it receives. |
| FastAPI = hub | Bridges Forge ↔ Unity ↔ AI. Single point of truth. |
| Dual-brain routing | DeepSeek-R1 excels at analytical/math decisions; GPT-OSS at strategic sequencing. |
| ChromaDB scoped per player | RAG context relevant to the active player's deck, not global card knowledge. |
| Personality persists per game | Consistent playstyle per AI across all 4 players per session. |
| Local image cache | Eliminates network latency for card art. ~2GB one-time download. |
| ai_decisions.jsonl | Every AI decision is a future PPO training sample. |
