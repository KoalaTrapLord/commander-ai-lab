# Commander AI Lab — Unity Client

Unity front-end for Commander AI Lab. Communicates with the FastAPI backend (`lab_api.py`) via REST API.

## Requirements

| Tool | Version |
|---|---|
| Unity | 2022 LTS (6000.0+) |
| Render Pipeline | Universal Render Pipeline (URP) |
| .NET | .NET Standard 2.1 |
| Backend | Commander AI Lab FastAPI (port 8080) |

## Setup

1. Open Unity Hub
2. Click **Add** → select this `unity-client/` folder
3. Open the project in Unity 2022 LTS
4. Install required packages via Package Manager (see `Packages/manifest.json`)
5. Start the FastAPI backend: `python lab_api.py`
6. Open the `MainMenu` scene and press Play

## Folder Structure

```
unity-client/
  Assets/
    Scenes/           — All Unity scenes
      MainMenu.unity
      Collection.unity
      DeckBuilder.unity
      DeckGenerator.unity
      Simulator.unity
      Coach.unity
      Scanner.unity
      Training.unity
      Precon.unity
    Scripts/
      Models/         — C# POCOs matching FastAPI response shapes
      Services/       — ApiClient.cs, CardImageCache.cs
      UI/             — Scene-specific controllers
      Animation/      — CardAnimator.cs, BattlefieldAnimator.cs
    Prefabs/
      CardPrefab.prefab
      DeckSlotPrefab.prefab
      ChatBubble.prefab
    Materials/        — URP materials + Shader Graphs
    Textures/         — UI sprites, card back
    Fonts/
  Packages/           — Unity package manifest
  ProjectSettings/    — Build settings, input system config
```

## Build Targets

| Platform | Instructions |
|---|---|
| **Windows** | File → Build Settings → PC/Mac → Windows x86_64 |
| **WebGL** | File → Build Settings → WebGL (requires Brotli compression) |
| **Android** | File → Build Settings → Android (requires Android SDK) |
| **iOS** | File → Build Settings → iOS (requires Xcode on Mac) |

## API Configuration

The default backend URL is `http://localhost:8080`. Change it from the **Settings** panel in the MainMenu scene or pass it as a WebGL URL parameter: `?server=http://your-server:8080`

## GitHub Issues

See Epic [#45](https://github.com/KoalaTrapLord/commander-ai-lab/issues/45) for full task breakdown.
