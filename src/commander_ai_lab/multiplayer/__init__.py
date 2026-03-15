"""
Commander AI Lab — Multiplayer Package (Phase 8)

Exposes:
  LobbyManager     — room creation, player slots, ready-check, game launch
  ChatChannel      — per-room in-game chat with history + moderation
  SpectatorManager — read-only WebSocket feeds for spectators
  LANDiscovery     — UDP beacon broadcast / listener for LAN host discovery
  PrivateHandBus   — routes private-hand snapshots to the correct seat only
"""
from commander_ai_lab.multiplayer.lobby      import LobbyManager, LobbyRoom, LobbySlot, RoomState
from commander_ai_lab.multiplayer.chat       import ChatChannel, ChatMessage, ChatRole
from commander_ai_lab.multiplayer.spectator  import SpectatorManager
from commander_ai_lab.multiplayer.lan        import LANDiscovery, LANBeacon
from commander_ai_lab.multiplayer.hands      import PrivateHandBus

__all__ = [
    "LobbyManager", "LobbyRoom", "LobbySlot", "RoomState",
    "ChatChannel", "ChatMessage", "ChatRole",
    "SpectatorManager",
    "LANDiscovery", "LANBeacon",
    "PrivateHandBus",
]
