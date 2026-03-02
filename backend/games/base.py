"""Abstract base class for all Lantern Party games."""

from abc import ABC, abstractmethod
from typing import Any


class BaseGame(ABC):
    """Base class every game must implement."""

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
