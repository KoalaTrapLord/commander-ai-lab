# Battleground UI — Task Tracker
> Created: 2026-03-28  
> Updated: 2026-03-29 — all 14 issues complete
> Branch: `feat/battleground-ui`

All issues below are part of the **4-player Commander Battleground** Unity 3D UI build.
Build in the numbered order — each step is independently testable before the next.

---

## Build Order Checklist

| # | Issue | Script(s) | Needs Backend? | Status |
|---|-------|-----------|----------------|--------|
| 1 | [#138 — Battleground.unity scene + 4-seat layout](https://github.com/KoalaTrapLord/commander-ai-lab/issues/138) | `BattlegroundController.cs`, `GameStateManager.cs` | No | ✅ |
| 2 | [#139 — LifeTrackerWidget + CommanderDamageRow + Poison](https://github.com/KoalaTrapLord/commander-ai-lab/issues/139) | `LifeTrackerWidget.cs`, `CommanderDamageRow.cs`, `PoisonCounter.cs` | No | ✅ |
| 3 | [#140 — PhaseTrackerWidget + PhaseStepButton](https://github.com/KoalaTrapLord/commander-ai-lab/issues/140) | `PhaseTrackerWidget.cs`, `PhaseStepButton.cs` | No | ✅ |
| 4 | [#141 — TurnOrderBar + TurnOrderPill](https://github.com/KoalaTrapLord/commander-ai-lab/issues/141) | `TurnOrderBar.cs`, `TurnOrderPill.cs` | No | ✅ |
| 5 | [#142 — CardZone + CardView](https://github.com/KoalaTrapLord/commander-ai-lab/issues/142) | `CardZone.cs`, `CardView.cs` + `CardModel` runtime fields | ImageCache only | ✅ |
| 6 | [#143 — CommanderZoneWidget](https://github.com/KoalaTrapLord/commander-ai-lab/issues/143) | `CommanderZoneWidget.cs` + `ImageCache.LoadArtCrop()` | ImageCache only | ✅ |
| 7 | [#144 — Token System](https://github.com/KoalaTrapLord/commander-ai-lab/issues/144) | `TokenModel.cs`, `TokenPanelController.cs`, `TokenRowView.cs` | No | ✅ |
| 8 | [#146 — StackZoneController + ManaPoolDisplay](https://github.com/KoalaTrapLord/commander-ai-lab/issues/146) | `StackZoneController.cs`, `ManaPoolDisplay.cs` | No (events only) | ✅ |
| 9 | [#147 — LobbySetupModal + ZoneViewerModal](https://github.com/KoalaTrapLord/commander-ai-lab/issues/147) | `LobbySetupModal.cs`, `ZoneViewerModal.cs` | `/api/decks`, `/api/game/start` | ✅ |
| 10 | [#148 — GameStateManager + GameState POCOs](https://github.com/KoalaTrapLord/commander-ai-lab/issues/148) | `GameStateManager.cs`, `GameState.cs` | No | ✅ |
| 11 | [#149 — GameWebSocketClient](https://github.com/KoalaTrapLord/commander-ai-lab/issues/149) | `GameWebSocketClient.cs` | Yes — `/ws/game` | ✅ |
| 12 | [#145 — HumanActionBar](https://github.com/KoalaTrapLord/commander-ai-lab/issues/145) | `HumanActionBar.cs`, `ApiClient.PostGameAction()` | Yes — `/api/game/action` | ✅ |
| 13 | [#150 — EliminationHandler + Grayscale Shader](https://github.com/KoalaTrapLord/commander-ai-lab/issues/150) | `EliminationHandler.cs`, `EliminatedGrayscale` ShaderGraph | No | ✅ |
| 14 | [#151 — SimulationController: Play Live button](https://github.com/KoalaTrapLord/commander-ai-lab/issues/151) | `SimulationController.cs` (modify) | No | ✅ |

---

## All Files Committed

### `Assets/Scripts/UI/Battleground/` (new folder)
- ✅ `BattlegroundController.cs` — scene orchestrator, seat rotations, event subscriptions
- ✅ `GameStateManager.cs` — singleton event hub
- ✅ `LifeTrackerWidget.cs` — life +/- with history + danger flash
- ✅ `CommanderDamageRow.cs` — 4-pip commander damage tracker per seat
- ✅ `PoisonCounter.cs` — 10-pip poison tracker
- ✅ `PhaseTrackerWidget.cs` — 13-step phase strip, Space key debug advance
- ✅ `PhaseStepButton.cs` — individual phase pill (color + scale)
- ✅ `TurnOrderBar.cs` — animated seat border slider
- ✅ `TurnOrderPill.cs` — per-seat pill with name, life, eliminated state
- ✅ `CardZone.cs` — zone container (add/remove/clear CardView children)
- ✅ `CardView.cs` — card visual (art, tapped rotation, face-down, summoning sick)
- ✅ `CommanderZoneWidget.cs` — art crop, cast count, tax (+2 per cast)
- ✅ `TokenPanelController.cs` — token creation panel
- ✅ `TokenRowView.cs` — token row (qty, tap, counters, delete)
- ✅ `StackZoneController.cs` — LIFO stack display, hidden when empty
- ✅ `StackItemView.cs` — individual stack item row
- ✅ `ManaPoolDisplay.cs` — 6-pip mana display, hides zero labels
- ✅ `LobbySetupModal.cs` — 4-seat lobby config, loads decks from API, POSTs to /api/game/start
- ✅ `ZoneViewerModal.cs` — fullscreen graveyard/exile viewer with search filter
- ✅ `HumanActionBar.cs` — priority-gated action buttons + targeting mode
- ✅ `EliminationHandler.cs` — overlay + grayscale material on elimination

### `Assets/Scripts/Models/`
- ✅ `GameState.cs` — `GameState` + `SeatState` POCOs
- ✅ `TokenModel.cs` — token data model
- ✅ `CardModel.cs` — modified: added `[NonSerialized]` runtime state + `BattleZone` enum

### `Assets/Scripts/Services/`
- ✅ `ImageCache.cs` — modified: added `LoadCard(RawImage)` + `LoadArtCrop(name, RawImage)`
- ✅ `GameWebSocketClient.cs` — WS connect/reconnect, ping, ConcurrentQueue main-thread dispatch
- ✅ `ApiClient.cs` — modified: added `PostGameAction()` + `PostGameStart()`

### `Assets/Scenes/`
- ✅ `Battleground.unity` — new scene

### `Assets/Materials/`
- ✅ `EliminatedGrayscale` — URP Shader Graph

### Modified Existing Files
- ✅ `SimulationController.cs` — Play Live button + `OnPlayLive()` + `BuildSeatsJson()`
- ✅ `MainMenuController.cs` — Play Live nav button

---

## Backend Endpoints Required

These Python routes must exist before end-to-end testing:

| Endpoint | Used By | Status |
|----------|---------|--------|
| `GET /api/decks` | `LobbySetupModal` | verify |
| `POST /api/game/start` | `LobbySetupModal` | verify |
| `POST /api/game/action` | `HumanActionBar` | verify |
| `WS /ws/game` | `GameWebSocketClient` | verify (PR #107) |

---

## Architecture Notes

- **`GameStateManager`** is the singleton event hub — all UI widgets subscribe to its events, never poll
- **`GameWebSocketClient`** receives server push messages and routes them to `GameStateManager.ApplyServerEvent()`
- **Canvas mode**: Screen Space — Camera (not World Space) for crisp TMP rendering
- **Seat rotation**: AI panels rotated -90°, 180°, 90° via `localEulerAngles` so text/buttons face the right direction
- **Backend WS**: connect to `ws://localhost:8080/ws/game` (configurable via `PlayerPrefs["ServerUrl"]`)
- **Space key** in Play Mode advances the phase strip for isolated testing without WebSocket
