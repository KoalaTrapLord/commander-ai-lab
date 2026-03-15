"""
Commander AI Lab — LAN Discovery (Phase 8)
==========================================
UDP broadcast/listen system for discovering Commander AI Lab hosts
on the local network without manual IP entry.

Protocol:
  - Host sends a UDP broadcast on LAN_PORT every BEACON_INTERVAL seconds
  - Payload is a compact JSON beacon: {"app": "commander-ai-lab",
      "version": "...", "room": ..., "host": ..., "port": int, "players": int}
  - Clients listen on LAN_PORT, collect beacons, and surface them as
    available games
  - Beacons expire after BEACON_TTL seconds of silence from a host

Usage::

    # On the host machine
    discovery = LANDiscovery(mode="host", room_info={...})
    await discovery.start()
    ...
    await discovery.stop()

    # On a client machine
    discovery = LANDiscovery(mode="client")
    await discovery.start()
    beacons = discovery.discovered_hosts()
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from dataclasses import dataclass, field
from typing import Optional

APP_ID          = "commander-ai-lab"
APP_VERSION     = "0.8.0"
LAN_PORT        = 42424
BEACON_INTERVAL = 3.0    # seconds between host broadcasts
BEACON_TTL      = 10.0   # seconds before a beacon is considered stale
MAX_PACKET_SIZE = 2048


@dataclass
class LANBeacon:
    host_ip:    str
    host_port:  int
    room_id:    str
    room_name:  str
    player_count: int
    max_players:  int
    has_password: bool
    version:    str       = APP_VERSION
    last_seen:  float     = field(default_factory=time.time)

    def is_stale(self) -> bool:
        return (time.time() - self.last_seen) > BEACON_TTL

    def to_dict(self) -> dict:
        return {
            "host_ip":      self.host_ip,
            "host_port":    self.host_port,
            "room_id":      self.room_id,
            "room_name":    self.room_name,
            "player_count": self.player_count,
            "max_players":  self.max_players,
            "has_password": self.has_password,
            "version":      self.version,
            "last_seen":    self.last_seen,
        }


class LANDiscovery:
    """
    Manages host broadcasting and client listening for LAN game discovery.

    Parameters
    ----------
    mode :       'host' | 'client'
    room_info :  Required for mode='host'. Dict with room metadata.
    bind_port :  UDP port to use (default LAN_PORT).
    game_port :  TCP/WebSocket port the FastAPI server is listening on.
    """

    def __init__(
        self,
        mode: str,
        room_info: Optional[dict] = None,
        bind_port: int = LAN_PORT,
        game_port: int = 8000,
    ) -> None:
        if mode not in ("host", "client"):
            raise ValueError("mode must be 'host' or 'client'")
        self.mode       = mode
        self.room_info  = room_info or {}
        self.bind_port  = bind_port
        self.game_port  = game_port

        self._running   = False
        self._task: Optional[asyncio.Task] = None
        # client-side discovered hosts: host_ip -> LANBeacon
        self._discovered: dict[str, LANBeacon] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        if self.mode == "host":
            self._task = asyncio.create_task(self._broadcast_loop())
        else:
            self._task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def discovered_hosts(self) -> list[dict]:
        """Return all non-stale discovered hosts (client mode only)."""
        self._prune_stale()
        return [b.to_dict() for b in self._discovered.values()]

    def update_room_info(self, room_info: dict) -> None:
        """Update broadcast payload (e.g. when player count changes)."""
        self.room_info = room_info

    # ------------------------------------------------------------------
    # Host — broadcast loop
    # ------------------------------------------------------------------

    async def _broadcast_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        try:
            while self._running:
                payload = self._build_beacon_payload()
                data    = json.dumps(payload).encode()
                try:
                    sock.sendto(data, ("<broadcast>", self.bind_port))
                except OSError:
                    pass
                await asyncio.sleep(BEACON_INTERVAL)
        finally:
            sock.close()

    def _build_beacon_payload(self) -> dict:
        return {
            "app":          APP_ID,
            "version":      APP_VERSION,
            "room_id":      self.room_info.get("room_id",    ""),
            "room_name":    self.room_info.get("room_name",  "Unnamed Room"),
            "player_count": self.room_info.get("player_count", 1),
            "max_players":  self.room_info.get("max_players",  4),
            "has_password": self.room_info.get("has_password", False),
            "host_port":    self.game_port,
        }

    # ------------------------------------------------------------------
    # Client — listen loop
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        try:
            sock.bind(("", self.bind_port))
        except OSError:
            sock.close()
            return

        loop = asyncio.get_event_loop()
        try:
            while self._running:
                try:
                    data, addr = await loop.run_in_executor(
                        None, lambda: sock.recvfrom(MAX_PACKET_SIZE)
                    )
                    self._handle_beacon(data, addr[0])
                except (OSError, BlockingIOError):
                    await asyncio.sleep(0.1)
        finally:
            sock.close()

    def _handle_beacon(
        self,
        data: bytes,
        sender_ip: str,
    ) -> None:
        try:
            payload = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if payload.get("app") != APP_ID:
            return
        beacon = LANBeacon(
            host_ip=sender_ip,
            host_port=payload.get("host_port", 8000),
            room_id=payload.get("room_id", ""),
            room_name=payload.get("room_name", "Unknown"),
            player_count=payload.get("player_count", 1),
            max_players=payload.get("max_players", 4),
            has_password=payload.get("has_password", False),
            version=payload.get("version", ""),
        )
        self._discovered[sender_ip] = beacon

    def _prune_stale(self) -> None:
        stale = [ip for ip, b in self._discovered.items() if b.is_stale()]
        for ip in stale:
            del self._discovered[ip]
