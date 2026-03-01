"""
Tests for the Fib game logic and HTTP API.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.games.fib.game import (
    FibGame,
    Player,
    _is_too_similar,
    _score_question,
)
from backend.main import app
from backend.party_manager import PartyManager
from httpx import ASGITransport, AsyncClient


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def make_players(*names: str) -> dict[str, Player]:
    return {f"pid{i}": Player(id=f"pid{i}", name=name) for i, name in enumerate(names)}


async def noop_broadcast(msg: dict[str, Any], target: str | None = None) -> None:
    pass


def make_game(players: dict[str, Player]) -> FibGame:
    return FibGame(party_code="TEST", players=players, broadcast=noop_broadcast)


# ──────────────────────────────────────────────────────────────────────
# Unit: similarity check
# ──────────────────────────────────────────────────────────────────────

class TestIsTooSimilar:
    def test_exact_match(self):
        assert _is_too_similar("unicorn", "unicorn") is True

    def test_case_insensitive_exact(self):
        assert _is_too_similar("UNICORN", "unicorn") is True

    def test_clearly_different(self):
        assert _is_too_similar("a purple dinosaur", "unicorn") is False

    def test_very_close(self):
        assert _is_too_similar("unicorns", "unicorn") is True

    def test_not_similar(self):
        assert _is_too_similar("banana", "xyz") is False


# ──────────────────────────────────────────────────────────────────────
# Unit: scoring
# ──────────────────────────────────────────────────────────────────────

class TestScoreQuestion:
    def _players(self, *ids: str) -> dict[str, Player]:
        return {pid: Player(id=pid, name=pid) for pid in ids}

    def test_truth_vote_awards_points(self):
        # choice_keys: [truth, pid0, pid1]
        players = self._players("pid0", "pid1", "pid2")
        # pid2 votes for truth (index 0)
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid1"],
            votes={"pid2": 0},
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        assert deltas.get("pid2", 0) == 1000

    def test_round2_doubles_truth(self):
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid1"],
            votes={"pid2": 0},
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=2,
            players=players,
        )
        assert deltas.get("pid2", 0) == 2000

    def test_round3_triples_truth(self):
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid1"],
            votes={"pid2": 0},
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=3,
            players=players,
        )
        assert deltas.get("pid2", 0) == 3000

    def test_fooling_points(self):
        # pid1 votes for pid0's lie (index 1) → pid0 gets 500 pts
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid2"],
            votes={"pid1": 1},  # votes for pid0's lie
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        assert deltas.get("pid0", 0) == 500

    def test_lie_for_me_half_fooling(self):
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid2"],
            votes={"pid1": 1},
            game_provided={"pid0"},
            lie_for_me_players={"pid0"},
            round_mult=1,
            players=players,
        )
        assert deltas.get("pid0", 0) == 250

    def test_game_provided_no_lie_for_me_no_fooling_points(self):
        # Auto-generated (timeout) lie – no fooling points even if fooled
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid2"],
            votes={"pid1": 1},
            game_provided={"pid0"},
            lie_for_me_players=set(),  # NOT lie-for-me
            round_mult=1,
            players=players,
        )
        assert deltas.get("pid0", 0) == 0

    def test_voting_for_game_provided_lie_penalty(self):
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid2"],
            votes={"pid1": 1},
            game_provided={"pid0"},
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        # pid1 voted for a game-provided lie → -500 pts
        assert deltas.get("pid1", 0) == -500

    def test_multiple_fools(self):
        players = self._players("pid0", "pid1", "pid2", "pid3")
        # pid1 and pid2 both vote for pid0's lie
        deltas = _score_question(
            choice_keys=["truth", "pid0"],
            votes={"pid1": 1, "pid2": 1},
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        assert deltas.get("pid0", 0) == 1000  # 2 fools × 500

    def test_no_votes_no_deltas(self):
        players = self._players("pid0", "pid1")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid1"],
            votes={},
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        assert deltas == {}

    def test_cannot_vote_self_not_reflected_in_score(self):
        # The game prevents self-voting; scoring just checks submitter_id != voter_id
        players = self._players("pid0", "pid1")
        deltas = _score_question(
            choice_keys=["truth", "pid0"],
            votes={"pid0": 1},  # voting for own lie (shouldn't happen but safe)
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        # No fooling points for self-vote
        assert deltas.get("pid0", 0) == 0


# ──────────────────────────────────────────────────────────────────────
# Unit: FibGame state
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_fib_game_start_sets_phase():
    players = make_players("Alice", "Bob", "Charlie")
    game = make_game(players)
    await game.start()
    assert game.phase == "collecting_lies"
    assert game.round_num == 1
    assert game.current_question is not None


@pytest.mark.anyio
async def test_fib_game_start_broadcasts():
    messages: list[dict] = []

    async def capture(msg, target=None):
        messages.append(msg)

    players = make_players("Alice", "Bob")
    game = FibGame("TST", players, capture)
    await game.start()

    types = {m["type"] for m in messages}
    assert "fib_question" in types


@pytest.mark.anyio
async def test_too_similar_rejected():
    errors: list[dict] = []

    async def capture(msg, target=None):
        if msg.get("type") == "error":
            errors.append(msg)

    players = make_players("Alice", "Bob")
    game = FibGame("TST", players, capture)
    await game.start()
    truth = game.current_question["truth"]

    await game.handle_action(
        "pid0", "submit_lie", {"text": truth, "lie_for_me": False}
    )
    assert any("similar" in e["data"]["message"].lower() for e in errors)


@pytest.mark.anyio
async def test_submit_lie_transitions_to_voting():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    await game.start()
    assert game.phase == "collecting_lies"

    await game.handle_action("pid0", "submit_lie", {"text": "fake answer A"})
    await game.handle_action("pid1", "submit_lie", {"text": "fake answer B"})

    assert game.phase == "voting"


@pytest.mark.anyio
async def test_voting_choices_include_truth_and_lies():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    await game.start()

    await game.handle_action("pid0", "submit_lie", {"text": "fake A"})
    await game.handle_action("pid1", "submit_lie", {"text": "fake B"})

    assert game.phase == "voting"
    assert "truth" in game._choice_keys
    assert "pid0" in game._choice_keys
    assert "pid1" in game._choice_keys
    assert len(game._choice_keys) == 3


@pytest.mark.anyio
async def test_submit_vote_advances_when_all_in():
    players = make_players("Alice", "Bob", "Charlie")
    game = make_game(players)
    await game.start()

    # All submit lies
    await game.handle_action("pid0", "submit_lie", {"text": "fake A"})
    await game.handle_action("pid1", "submit_lie", {"text": "fake B"})
    await game.handle_action("pid2", "submit_lie", {"text": "fake C"})
    assert game.phase == "voting"

    # Find truth index
    truth_idx = game._choice_keys.index("truth")

    # Each player votes for truth (can't vote for own, so pick truth index)
    for pid in ["pid0", "pid1", "pid2"]:
        await game.handle_action(pid, "submit_vote", {"choice_index": truth_idx})

    assert game.phase in ("revealing", "collecting_lies", "scores", "game_over")


@pytest.mark.anyio
async def test_cannot_vote_for_own_lie():
    errors: list[dict] = []

    async def capture(msg, target=None):
        if msg.get("type") == "error":
            errors.append(msg)

    players = make_players("Alice", "Bob", "Charlie")
    game = FibGame("TST", players, capture)
    await game.start()

    await game.handle_action("pid0", "submit_lie", {"text": "fake A"})
    await game.handle_action("pid1", "submit_lie", {"text": "fake B"})
    await game.handle_action("pid2", "submit_lie", {"text": "fake C"})

    own_idx = game._choice_keys.index("pid0")
    await game.handle_action("pid0", "submit_vote", {"choice_index": own_idx})
    assert any("can't vote" in e["data"]["message"].lower() for e in errors)


@pytest.mark.anyio
async def test_lie_for_me_flag():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    await game.start()

    await game.handle_action("pid0", "submit_lie", {"lie_for_me": True})
    assert "pid0" in game.game_provided
    assert "pid0" in game.lie_for_me_players
    assert "pid0" in game.lies


@pytest.mark.anyio
async def test_duplicate_submission_ignored():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    await game.start()

    await game.handle_action("pid0", "submit_lie", {"text": "first answer"})
    first = game.lies.get("pid0")
    await game.handle_action("pid0", "submit_lie", {"text": "second answer"})
    assert game.lies.get("pid0") == first  # unchanged


@pytest.mark.anyio
async def test_get_host_state_structure():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    state = game.get_host_state()
    assert state["game"] == "fib"
    assert "phase" in state
    assert "round_num" in state
    assert "scores" in state


@pytest.mark.anyio
async def test_get_player_state_collecting():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    await game.start()
    state = game.get_player_state("pid0")
    assert state["phase"] == "collecting_lies"
    assert "submitted_lie" in state
    assert state["submitted_lie"] is False


@pytest.mark.anyio
async def test_like_during_revealing():
    players = make_players("Alice", "Bob", "Charlie")
    game = make_game(players)
    await game.start()

    await game.handle_action("pid0", "submit_lie", {"text": "fake A"})
    await game.handle_action("pid1", "submit_lie", {"text": "fake B"})
    await game.handle_action("pid2", "submit_lie", {"text": "fake C"})

    truth_idx = game._choice_keys.index("truth")
    for pid in ["pid0", "pid1", "pid2"]:
        await game.handle_action(pid, "submit_vote", {"choice_index": truth_idx})

    assert game.phase == "revealing"
    # pid0 likes pid1's lie
    pid1_idx = game._choice_keys.index("pid1")
    await game.handle_action("pid0", "submit_like", {"choice_index": pid1_idx})
    assert "pid0" in game.likes.get(pid1_idx, [])
    assert game.total_likes.get("pid1", 0) == 1


@pytest.mark.anyio
async def test_thumbs_cup_winner():
    players = make_players("Alice", "Bob", "Charlie")
    game = make_game(players)
    game.total_likes = {"pid1": 3, "pid0": 1}
    winner = game._thumbs_cup_winner()
    assert winner == "Bob"


@pytest.mark.anyio
async def test_scores_not_below_zero():
    """Scores should not go below 0 even with penalties."""
    players = make_players("Alice", "Bob", "Charlie")
    game = make_game(players)
    game.players["pid0"].score = 200
    game._choice_keys = ["pid1", "pid2", "truth"]
    game._choice_texts = ["lie1", "lie2", "the truth"]
    game.votes = {"pid0": 1}  # pid0 votes for game-provided lie → -500
    game.game_provided = {"pid2"}
    game.lie_for_me_players = set()
    game._question_finalized = False
    game.phase = "voting"
    game.round_num = 1
    game.current_question = {"prompt": "x", "truth": "the truth", "category": "t"}
    await game._finalize_voting()
    assert game.players["pid0"].score >= 0


# ──────────────────────────────────────────────────────────────────────
# Integration: HTTP API for Fib
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_fib_party():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/party", json={"game_name": "fib"})
    assert resp.status_code == 200
    body = resp.json()
    assert "code" in body
    assert body["host_url"].startswith("/fib/host/")


@pytest.mark.anyio
async def test_join_fib_party_returns_fib_player_url():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/api/party", json={"game_name": "fib"})
        code = create.json()["code"]
        join = await c.post(f"/api/party/{code}/join")
    assert join.status_code == 200
    assert join.json()["player_url"].startswith("/fib/player/")


@pytest.mark.anyio
async def test_fib_host_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/api/party", json={"game_name": "fib"})
        code = create.json()["code"]
        resp = await c.get(f"/fib/host/{code}")
    assert resp.status_code == 200
    assert "fib" in resp.text.lower() or "lantern" in resp.text.lower()


@pytest.mark.anyio
async def test_fib_player_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/api/party", json={"game_name": "fib"})
        code = create.json()["code"]
        resp = await c.get(f"/fib/player/{code}")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_lampoon_party_unaffected():
    """Existing lampoon parties still get /host/ URLs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/party", json={"game_name": "lampoon"})
    assert resp.json()["host_url"].startswith("/host/")
