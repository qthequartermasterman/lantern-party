"""In-memory party storage and management."""
from __future__ import annotations

import contextlib
import random
import string
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import WebSocket



def _generate_code(existing: set[str]) -> str:
    """Return a 4-letter uppercase code not already in *existing*."""
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in existing:
            return code


@dataclass
class Party:
    """Active party holding game state and WebSocket connections."""

    code: str
    game_name: str = "lampoon"
    host_ws: WebSocket | None = None
    # player_id → WebSocket
    player_ws: dict[str, WebSocket] = field(default_factory=dict)
    # player_id → Player (shared with game)
    players: dict[str, Any] = field(default_factory=dict)
    game: Any | None = None  # BaseGame subclass instance
    state: str = "lobby"  # lobby | playing | finished

    async def broadcast(
        self, message: dict[str, Any], target: str | None = None
    ) -> None:
        """Send *message* (as JSON) to the appropriate connection(s).

        target=None      → host + all players
        target="host"    → host only
        target=<uuid>    → that player only
        """
        import json

        payload = json.dumps(message)

        async def _send(ws: WebSocket) -> None:
            with contextlib.suppress(Exception):
                await ws.send_text(payload)

        if target is None:
            if self.host_ws:
                await _send(self.host_ws)
            for ws in list(self.player_ws.values()):
                await _send(ws)
        elif target == "host":
            if self.host_ws:
                await _send(self.host_ws)
        else:
            ws = self.player_ws.get(target)
            if ws:
                await _send(ws)


class PartyManager:
    """Singleton-style in-memory store for all active parties."""

    def __init__(self) -> None:
        """Initialise with an empty party registry."""
        self._parties: dict[str, Party] = {}

    def create_party(self, game_name: str = "lampoon") -> Party:
        """Create a new party. *game_name* is stored for future multi-game support."""
        code = _generate_code(set(self._parties.keys()))
        party = Party(code=code, game_name=game_name)
        self._parties[code] = party
        return party

    def get_party(self, code: str) -> Party | None:
        """Return the party with *code*, or ``None`` if not found."""
        return self._parties.get(code.upper())

    def delete_party(self, code: str) -> None:
        """Remove the party with *code* from the registry."""
        self._parties.pop(code.upper(), None)

    def all_codes(self) -> list[str]:
        """Return all active party codes."""
        return list(self._parties.keys())


# Module-level singleton used by the entire app
party_manager = PartyManager()
