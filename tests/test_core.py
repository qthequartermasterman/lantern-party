"""
Tests for the shared core module (backend/games/base.py).

Covers:
  - Player dataclass defaults and field types
  - BaseGame.__init__ shared-state setup
  - _active_players / _active_player_count
  - _scores_list ordering and structure
  - _broadcast_game_state routing
  - Timer: _start_timer, _run_timer, _cancel_timer
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.games.base import BaseGame, Broadcaster, Player

# ──────────────────────────────────────────────────────────────────────
# Minimal concrete subclass used throughout all tests
# ──────────────────────────────────────────────────────────────────────


class _MinimalGame(BaseGame):
    """Concrete stub that satisfies the abstract interface."""

    def __init__(
        self,
        players: dict[str, Player],
        broadcast: Broadcaster,
    ) -> None:
        super().__init__("TEST", players, broadcast)
        self.phase = "lobby"

    async def start(self) -> None:
        self.phase = "started"

    async def handle_action(
        self, player_id: str, action_type: str, data: dict[str, Any]
    ) -> None:
        pass

    def get_host_state(self) -> dict[str, Any]:
        return {"phase": self.phase, "host": True}

    def get_player_state(self, player_id: str) -> dict[str, Any]:
        return {"phase": self.phase, "player_id": player_id}


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def make_players(*names: str) -> dict[str, Player]:
    return {f"pid{i}": Player(id=f"pid{i}", name=name) for i, name in enumerate(names)}


async def noop_broadcast(msg: dict[str, Any], target: str | None = None) -> None:
    pass


def make_game(players: dict[str, Player]) -> _MinimalGame:
    return _MinimalGame(players, noop_broadcast)


# ──────────────────────────────────────────────────────────────────────
# Unit: Player dataclass
# ──────────────────────────────────────────────────────────────────────


class TestPlayer:
    def test_required_fields(self):
        p = Player(id="p1", name="Alice")
        assert p.id == "p1"
        assert p.name == "Alice"

    def test_default_score_zero(self):
        p = Player(id="p1", name="Alice")
        assert p.score == 0

    def test_default_ready_false(self):
        p = Player(id="p1", name="Alice")
        assert p.ready is False

    def test_default_is_connected_true(self):
        p = Player(id="p1", name="Alice")
        assert p.is_connected is True

    def test_score_mutable(self):
        p = Player(id="p1", name="Alice", score=100)
        p.score += 50
        assert p.score == 150

    def test_ready_mutable(self):
        p = Player(id="p1", name="Alice")
        p.ready = True
        assert p.ready

    def test_is_connected_mutable(self):
        p = Player(id="p1", name="Alice")
        p.is_connected = False
        assert not p.is_connected


# ──────────────────────────────────────────────────────────────────────
# Unit: BaseGame.__init__ (via _MinimalGame)
# ──────────────────────────────────────────────────────────────────────


class TestBaseGameInit:
    def test_party_code_stored(self):
        game = make_game(make_players("Alice"))
        assert game.party_code == "TEST"

    def test_players_stored(self):
        players = make_players("Alice", "Bob")
        game = make_game(players)
        assert game.players is players

    def test_broadcast_stored(self):
        captured = []

        async def capture(msg, target=None):
            captured.append((msg, target))

        players = make_players("Alice")
        game = _MinimalGame(players, capture)
        assert game.broadcast is capture

    def test_timer_task_initially_none(self):
        game = make_game(make_players("Alice"))
        assert game._timer_task is None

    def test_timer_seconds_initially_zero(self):
        game = make_game(make_players("Alice"))
        assert game._timer_seconds == 0


# ──────────────────────────────────────────────────────────────────────
# Unit: _active_players / _active_player_count
# ──────────────────────────────────────────────────────────────────────


class TestActivePlayers:
    def test_all_connected(self):
        players = make_players("Alice", "Bob", "Charlie")
        game = make_game(players)
        assert game._active_player_count() == 3

    def test_disconnected_excluded(self):
        players = make_players("Alice", "Bob", "Charlie")
        players["pid1"].is_connected = False
        game = make_game(players)
        assert game._active_player_count() == 2

    def test_all_disconnected(self):
        players = make_players("Alice", "Bob")
        for p in players.values():
            p.is_connected = False
        game = make_game(players)
        assert game._active_player_count() == 0
        assert game._active_players() == []

    def test_returns_player_objects(self):
        players = make_players("Alice", "Bob")
        game = make_game(players)
        active = game._active_players()
        assert all(isinstance(p, Player) for p in active)

    def test_count_matches_list_length(self):
        players = make_players("Alice", "Bob", "Charlie", "Dave")
        players["pid2"].is_connected = False
        game = make_game(players)
        assert game._active_player_count() == len(game._active_players())


# ──────────────────────────────────────────────────────────────────────
# Unit: _scores_list
# ──────────────────────────────────────────────────────────────────────


class TestScoresList:
    def test_sorted_descending(self):
        players = make_players("Alice", "Bob", "Charlie")
        players["pid0"].score = 100
        players["pid1"].score = 500
        players["pid2"].score = 300
        game = make_game(players)
        scores = game._scores_list()
        assert scores[0]["score"] == 500
        assert scores[1]["score"] == 300
        assert scores[2]["score"] == 100

    def test_contains_required_keys(self):
        players = make_players("Alice")
        game = make_game(players)
        entry = game._scores_list()[0]
        assert "id" in entry
        assert "name" in entry
        assert "score" in entry

    def test_id_and_name_correct(self):
        players = make_players("Zara")
        game = make_game(players)
        entry = game._scores_list()[0]
        assert entry["id"] == "pid0"
        assert entry["name"] == "Zara"

    def test_all_players_included(self):
        players = make_players("A", "B", "C")
        game = make_game(players)
        assert len(game._scores_list()) == 3

    def test_zero_scores_all_equal(self):
        players = make_players("A", "B")
        game = make_game(players)
        scores = game._scores_list()
        assert all(s["score"] == 0 for s in scores)

    def test_empty_players(self):
        game = make_game({})
        assert game._scores_list() == []


# ──────────────────────────────────────────────────────────────────────
# Unit: _broadcast_game_state
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_broadcast_game_state_sends_to_host():
    players = make_players("Alice", "Bob")
    messages: list[tuple[dict, str | None]] = []

    async def capture(msg, target=None):
        messages.append((msg, target))

    game = _MinimalGame(players, capture)
    await game._broadcast_game_state()

    host_msgs = [m for m in messages if m[1] == "host"]
    assert len(host_msgs) == 1
    assert host_msgs[0][0]["type"] == "game_state"
    assert host_msgs[0][0]["data"]["host"] is True


@pytest.mark.anyio
async def test_broadcast_game_state_sends_to_all_players():
    players = make_players("Alice", "Bob", "Charlie")
    messages: list[tuple[dict, str | None]] = []

    async def capture(msg, target=None):
        messages.append((msg, target))

    game = _MinimalGame(players, capture)
    await game._broadcast_game_state()

    player_ids = {p.id for p in players.values()}
    sent_to = {m[1] for m in messages if m[1] != "host"}
    assert sent_to == player_ids


@pytest.mark.anyio
async def test_broadcast_game_state_player_msg_includes_player_id():
    players = make_players("Alice")
    messages: list[tuple[dict, str | None]] = []

    async def capture(msg, target=None):
        messages.append((msg, target))

    game = _MinimalGame(players, capture)
    await game._broadcast_game_state()

    player_msgs = [m for m in messages if m[1] == "pid0"]
    assert len(player_msgs) == 1
    assert player_msgs[0][0]["data"]["player_id"] == "pid0"


# ──────────────────────────────────────────────────────────────────────
# Unit: Timer (_start_timer, _cancel_timer, _run_timer)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_cancel_timer_with_no_timer_is_noop():
    game = make_game(make_players("Alice"))
    # Should not raise
    game._cancel_timer()
    assert game._timer_seconds == 0


@pytest.mark.anyio
async def test_start_timer_sets_seconds():
    game = make_game(make_players("Alice"))
    expired = []

    async def on_expire():
        expired.append(True)

    task = asyncio.create_task(game._start_timer(5, on_expire))
    await asyncio.sleep(0)  # allow task to be created
    assert game._timer_seconds == 5
    task.cancel()
    game._cancel_timer()


@pytest.mark.anyio
async def test_cancel_timer_cancels_task():
    game = make_game(make_players("Alice"))
    expired = []

    async def on_expire():
        expired.append(True)

    await game._start_timer(100, on_expire)
    assert game._timer_task is not None
    assert not game._timer_task.done()

    game._cancel_timer()
    # Yield to the event loop so the cancellation can be processed
    await asyncio.sleep(0)
    assert game._timer_task.cancelled() or game._timer_task.done()
    assert game._timer_seconds == 0
    assert expired == []


@pytest.mark.anyio
async def test_timer_broadcasts_timer_events():
    timer_msgs: list[dict] = []

    async def capture(msg, target=None):
        if msg.get("type") == "timer":
            timer_msgs.append(msg)

    game = _MinimalGame(make_players("Alice"), capture)
    expired = asyncio.Event()

    async def on_expire():
        expired.set()

    await game._start_timer(2, on_expire)
    await asyncio.wait_for(expired.wait(), timeout=5)

    # Should have broadcast for seconds 2, 1, 0
    assert len(timer_msgs) == 3
    remaining_values = [m["data"]["seconds_remaining"] for m in timer_msgs]
    assert remaining_values == [2, 1, 0]


@pytest.mark.anyio
async def test_timer_calls_on_expire():
    game = _MinimalGame(make_players("Alice"), noop_broadcast)
    expired = asyncio.Event()

    async def on_expire():
        expired.set()

    await game._start_timer(0, on_expire)
    await asyncio.wait_for(expired.wait(), timeout=2)
    assert expired.is_set()


@pytest.mark.anyio
async def test_start_timer_cancels_previous_timer():
    game = _MinimalGame(make_players("Alice"), noop_broadcast)
    first_expired = []
    second_expired = []

    async def expire_first():
        first_expired.append(True)

    async def expire_second():
        second_expired.append(True)

    await game._start_timer(100, expire_first)
    first_task = game._timer_task
    assert first_task is not None

    # Start a new short timer immediately – should cancel the first
    await game._start_timer(0, expire_second)
    await asyncio.sleep(0.1)

    assert first_task.cancelled() or first_task.done()
    assert first_expired == []
    assert second_expired == [True]
