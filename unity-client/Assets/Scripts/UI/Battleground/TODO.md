# Battleground UI — Task Tracker
> Created: 2026-03-28  
> Branch: `feat/battleground-ui`

All issues below are part of the **4-player Commander Battleground** Unity 3D UI build.
Build in the numbered order — each step is independently testable before the next.

---

## Build Order Checklist

| # | Issue | Script(s) | Needs Backend? | Status |
|---|-------|-----------|----------------|--------|
| 1 | [#138 — Battleground.unity scene + 4-seat layout](https://github.com/KoalaTrapLord/commander-ai-lab/issues/138) | `BattlegroundController.cs`, `GameStateManager.cs` | No | ⬜ |
| 2 | [#139 — LifeTrackerWidget + CommanderDamageRow + Poison](https://github.com/KoalaTrapLord/commander-ai-lab/issues/139) | `LifeTrackerWidget.cs`, `CommanderDamageRow.cs` | No | ⬜ |
| 3 | [#140 — PhaseTrackerWidget + PhaseStepButton](https://github.com/KoalaTrapLord/commander-ai-lab/issues/140) | `PhaseTrackerWidget.cs`, `PhaseStepButton.cs` | No | ⬜ |
| 4 | [#141 — TurnOrderBar + TurnOrderPill](https://github.com/KoalaTrapLord/commander-ai-lab/issues/141) | `TurnOrderBar.cs`, `TurnOrderPill.cs` | No | ⬜ |
| 5 | [#142 — CardZone + CardView](https://github.com/KoalaTrapLord/commander-ai-lab/issues/142) | `CardZone.cs`, `CardView.cs` | ImageCache only | ⬜ |
| 6 | [#143 — CommanderZoneWidget](https://github.com/KoalaTrapLord/commander-ai-lab/issues/143) | `CommanderZoneWidget.cs` + `ImageCache` art_crop | ImageCache only | ⬜ |
| 7 | [#144 — Token System](https://github.com/KoalaTrapLord/commander-ai-lab/issues/144) | `TokenModel.cs`, `TokenPanelController.cs`, `TokenRowView.cs` | No | ⬜ |
| 8 | [#146 — StackZoneController + ManaPoolDisplay](https://github.com/KoalaTrapLord/commander-ai-lab/issues/146) | `StackZoneController.cs`, `ManaPoolDisplay.cs` | No (events only) | ⬜ |
| 9 | [#147 — LobbySetupModal + ZoneViewerModal](https://github.com/KoalaTrapLord/commander-ai-lab/issues/147) | `LobbySetupModal.cs`, `ZoneViewerModal.cs` | `/api/decks`, `/api/game/start` | ⬜ |
| 10 | [#148 — GameStateManager + GameState POCOs](https://github.com/KoalaTrapLord/commander-ai-lab/issues/148) | `GameStateManager.cs`, `GameState.cs` | No | ⬜ |
| 11 | [#149 — GameWebSocketClient](https://github.com/KoalaTrapLord/commander-ai-lab/issues/149) | `GameWebSocketClient.cs` | Yes — `/ws/game` | ⬜ |
| 12 | [#145 — HumanActionBar](https://github.com/KoalaTrapLord/commander-ai-lab/issues/145) | `HumanActionBar.cs` | Yes — `/api/game/action` | ⬜ |
| 13 | [#150 — EliminationHandler + Grayscale Shader](https://github.com/KoalaTrapLord/commander-ai-lab/issues/150) | `EliminationHandler.cs`, `EliminatedGrayscale` ShaderGraph | No | ⬜ |
| 14 | [#151 — SimulationController: Play Live button](https://github.com/KoalaTrapLord/commander-ai-lab/issues/151) | `SimulationController.cs` (modify) | No | ⬜ |

---

## New Files Summary

### `Assets/Scripts/UI/Battleground/`
- `BattlegroundController.cs`
- `GameStateManager.cs`
- `LifeTrackerWidget.cs`
- `CommanderDamageRow.cs`
- `PhaseTrackerWidget.cs`
- `PhaseStepButton.cs`
- `TurnOrderBar.cs`
- `TurnOrderPill.cs`
- `CardZone.cs`
- `CardView.cs`
- `CommanderZoneWidget.cs`
- `TokenPanelController.cs`
- `TokenRowView.cs`
- `StackZoneController.cs` + `StackItemView.cs`
- `ManaPoolDisplay.cs`
- `LobbySetupModal.cs`
- `ZoneViewerModal.cs`
- `HumanActionBar.cs`
- `EliminationHandler.cs`

### `Assets/Scripts/Models/`
- `TokenModel.cs` (new)
- `GameState.cs` (new — `GameState`, `SeatState` POCOs)

### `Assets/Scripts/Services/`
- `GameWebSocketClient.cs` (new)

### `Assets/Scenes/`
- `Battleground.unity` (new scene)

### `Assets/Materials/`
- `EliminatedGrayscale` (URP Shader Graph)

### Modified
- `Assets/Scripts/UI/SimulationController.cs` — add Play Live button
- `Assets/Scripts/UI/MainMenuController.cs` — add Play Live nav button
- `Assets/Scripts/Services/ImageCache.cs` — add `LoadArtCrop()` method
- `Assets/Scripts/Models/CardModel.cs` — add `[NonSerialized]` runtime battleground state fields

---

## Architecture Notes

- **`GameStateManager`** is the singleton event hub — all UI widgets subscribe to its events, never poll
- **`GameWebSocketClient`** receives server push messages and routes them to `GameStateManager.ApplyServerEvent()`
- **Canvas mode**: Screen Space — Camera (not World Space) for crisp TMP rendering
- **Seat rotation**: AI panels rotated -90°, 180°, 90° via `localEulerAngles` so text/buttons face the right direction
- **Backend WS**: connect to `ws://localhost:8080/ws/game` (configurable via `PlayerPrefs["ServerUrl"]`)
