"""Core module for all Lantern Party games.

Contains the shared ``Player`` data model, ``Broadcaster`` type alias, and the
``BaseGame`` abstract class which provides concrete implementations of common
game logic (timer management, active-player queries, score lists, and the
broadcast-to-all-clients helper) so individual games don't duplicate them.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# ─────────────────────────────────────────────────────────────
# Shared data model
# ─────────────────────────────────────────────────────────────


@dataclass
class Player:
    """Player participating in a Lantern Party game."""

    id: str
    name: str
    score: int = 0
    ready: bool = False
    is_connected: bool = True


# ─────────────────────────────────────────────────────────────
# Broadcaster type alias
# ─────────────────────────────────────────────────────────────

Broadcaster = Callable[[dict[str, Any], str | None], Awaitable[None]]


# ─────────────────────────────────────────────────────────────
# Base game
# ─────────────────────────────────────────────────────────────


class BaseGame(ABC):
    """Base class every game must implement.

    Provides a common ``__init__`` that stores ``party_code``, ``players``,
    and ``broadcast``, initialises the timer state, and exposes concrete
    helper methods shared by all games:

    * :meth:`_active_players` / :meth:`_active_player_count`
    * :meth:`_scores_list`
    * :meth:`_broadcast_game_state`
    * :meth:`_start_timer` / :meth:`_run_timer` / :meth:`_cancel_timer`
    """

    def __init__(
        self,
        party_code: str,
        players: dict[str, Player],
        broadcast: Broadcaster,
    ) -> None:
        """Initialise shared state for a Lantern Party game."""
        self.party_code = party_code
        self.players = players
        self.broadcast = broadcast

        # Timer state managed by _start_timer / _cancel_timer
        self._timer_task: asyncio.Task[None] | None = None
        self._timer_seconds: int = 0

    # ── Abstract interface ────────────────────────────────────────────────

    @abstractmethod
    async def start(self) -> None:
        """Start the game (called after host clicks Start Game)."""

    @abstractmethod
    async def handle_action(
        self, player_id: str, action_type: str, data: dict[str, Any]
    ) -> None:
        """Process an action sent by a player."""

    @abstractmethod
    def get_host_state(self) -> dict[str, Any]:
        """Return the full state dict to send to the host WebSocket."""

    @abstractmethod
    def get_player_state(self, player_id: str) -> dict[str, Any]:
        """Return the personalized state dict for a specific player."""

    # ── Common helpers ────────────────────────────────────────────────────

    def _active_players(self) -> list[Player]:
        """Return all players that are currently connected."""
        return [p for p in self.players.values() if p.is_connected]

    def _active_player_count(self) -> int:
        """Return the number of currently connected players."""
        return len(self._active_players())

    def _scores_list(self) -> list[dict[str, Any]]:
        """Return a score-sorted list of ``{id, name, score}`` dicts."""
        return sorted(
            [
                {"id": p.id, "name": p.name, "score": p.score}
                for p in self.players.values()
            ],
            key=lambda x: x["score"],
            reverse=True,
        )

    async def _broadcast_game_state(self) -> None:
        """Push the current game state to the host and every player."""
        await self.broadcast(
            {"type": "game_state", "data": self.get_host_state()}, "host"
        )
        for pid in self.players:
            await self.broadcast(
                {"type": "game_state", "data": self.get_player_state(pid)}, pid
            )

    # ── Timer ─────────────────────────────────────────────────────────────

    async def _start_timer(
        self,
        seconds: int,
        on_expire: Callable[[], Awaitable[None]],
    ) -> None:
        """Cancel any running timer and start a new countdown."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_seconds = seconds
        self._timer_task = asyncio.create_task(self._run_timer(seconds, on_expire))

    async def _run_timer(
        self,
        seconds: int,
        on_expire: Callable[[], Awaitable[None]],
    ) -> None:
        """Broadcast a ``timer`` event each second; call *on_expire* at zero."""
        for remaining in range(seconds, -1, -1):
            self._timer_seconds = remaining
            await self.broadcast(
                {"type": "timer", "data": {"seconds_remaining": remaining}}, None
            )
            if remaining == 0:
                break
            await asyncio.sleep(1)
        await on_expire()

    def _cancel_timer(self) -> None:
        """Cancel the running timer task and reset the seconds counter."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_seconds = 0
