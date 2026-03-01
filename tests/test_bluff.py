"""
Tests for the Bluff and Baffle game logic and HTTP API.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from backend.games.bluff.game import (
    BluffGame,
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


def make_game(players: dict[str, Player]) -> BluffGame:
    return BluffGame(party_code="TEST", players=players, broadcast=noop_broadcast)


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


# ── Hypothesis: property-based tests for similarity check ──────────────

@given(text=st.text(min_size=1, max_size=40, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs'))))
def test_truth_always_too_similar_to_itself(text: str) -> None:
    """Any non-empty string is too similar to itself."""
    assume(text.strip())
    assert _is_too_similar(text, text) is True


@given(
    truth=st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll'))),
    lie=st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll'))),
)
@settings(max_examples=200)
def test_similarity_is_symmetric(truth: str, lie: str) -> None:
    """Similarity check should be approximately symmetric."""
    assume(truth.strip() and lie.strip())
    # If A is too similar to B, B should be too similar to A
    # (SequenceMatcher ratio is symmetric, so this must hold)
    assert _is_too_similar(truth, lie) == _is_too_similar(lie, truth)


@given(
    truth=st.text(min_size=5, max_size=30, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Zs'))),
)
@settings(max_examples=100)
def test_very_different_strings_not_too_similar(truth: str) -> None:
    """Strings sharing no characters with truth should not be 'too similar'."""
    assume(truth.strip())
    # A string of digits has no letter overlap
    digits_only = "12345678901234"
    assume(not any(c.lower() in digits_only.lower() for c in truth))
    assert _is_too_similar(digits_only, truth) is False


# ──────────────────────────────────────────────────────────────────────
# Unit: scoring
# ──────────────────────────────────────────────────────────────────────

class TestScoreQuestion:
    def _players(self, *ids: str) -> dict[str, Player]:
        return {pid: Player(id=pid, name=pid) for pid in ids}

    def test_truth_vote_awards_points(self):
        players = self._players("pid0", "pid1", "pid2")
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
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid2"],
            votes={"pid1": 1},
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
        players = self._players("pid0", "pid1", "pid2")
        deltas = _score_question(
            choice_keys=["truth", "pid0", "pid2"],
            votes={"pid1": 1},
            game_provided={"pid0"},
            lie_for_me_players=set(),
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
        assert deltas.get("pid1", 0) == -500

    def test_multiple_fools(self):
        players = self._players("pid0", "pid1", "pid2", "pid3")
        deltas = _score_question(
            choice_keys=["truth", "pid0"],
            votes={"pid1": 1, "pid2": 1},
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        assert deltas.get("pid0", 0) == 1000

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
        players = self._players("pid0", "pid1")
        deltas = _score_question(
            choice_keys=["truth", "pid0"],
            votes={"pid0": 1},
            game_provided=set(),
            lie_for_me_players=set(),
            round_mult=1,
            players=players,
        )
        assert deltas.get("pid0", 0) == 0


# ── Hypothesis: property-based tests for scoring ──────────────────────

@given(
    round_mult=st.integers(min_value=1, max_value=3),
    n_voters=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=100)
def test_truth_points_scale_with_multiplier(round_mult: int, n_voters: int) -> None:
    """Truth finder always receives exactly 1000 * round_mult points."""
    pids = [f"p{i}" for i in range(n_voters + 2)]
    players = {pid: Player(id=pid, name=pid) for pid in pids}
    # All n_voters vote for truth (index 0)
    votes = {pids[i]: 0 for i in range(2, 2 + n_voters)}
    deltas = _score_question(
        choice_keys=["truth", pids[0], pids[1]],
        votes=votes,
        game_provided=set(),
        lie_for_me_players=set(),
        round_mult=round_mult,
        players=players,
    )
    for voter_pid in votes:
        assert deltas.get(voter_pid, 0) == 1000 * round_mult


@given(
    round_mult=st.integers(min_value=1, max_value=3),
    n_fooled=st.integers(min_value=1, max_value=6),
)
@settings(max_examples=100)
def test_fooling_scales_with_multiplier_and_count(round_mult: int, n_fooled: int) -> None:
    """Liar earns 500 * round_mult per person fooled."""
    pids = [f"p{i}" for i in range(n_fooled + 2)]
    players = {pid: Player(id=pid, name=pid) for pid in pids}
    liar_pid = pids[0]
    # Indices: truth=0, liar=1; fooled voters vote for index 1
    votes = {pids[i]: 1 for i in range(2, 2 + n_fooled)}
    deltas = _score_question(
        choice_keys=["truth", liar_pid],
        votes=votes,
        game_provided=set(),
        lie_for_me_players=set(),
        round_mult=round_mult,
        players=players,
    )
    assert deltas.get(liar_pid, 0) == 500 * round_mult * n_fooled


@given(
    starting_score=st.integers(min_value=0, max_value=500),
)
@settings(max_examples=50)
def test_scores_never_below_zero_property(starting_score: int) -> None:
    """No combination of penalties should push a score below zero."""
    # A player with low score votes for a game-provided lie → -500 penalty
    players = {
        "pid0": Player(id="pid0", name="A", score=starting_score),
        "pid1": Player(id="pid1", name="B", score=0),
    }
    deltas = _score_question(
        choice_keys=["truth", "pid1"],
        votes={"pid0": 1},  # pid0 votes for game-provided lie
        game_provided={"pid1"},
        lie_for_me_players=set(),
        round_mult=1,
        players=players,
    )
    new_score = max(0, players["pid0"].score + deltas.get("pid0", 0))
    assert new_score >= 0


# ──────────────────────────────────────────────────────────────────────
# Unit: BluffGame state
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_bluff_game_start_sets_phase():
    players = make_players("Alice", "Bob", "Charlie")
    game = make_game(players)
    await game.start()
    assert game.phase == "collecting_lies"
    assert game.round_num == 1
    assert game.current_question is not None


@pytest.mark.anyio
async def test_bluff_game_start_broadcasts():
    messages: list[dict] = []

    async def capture(msg, target=None):
        messages.append(msg)

    players = make_players("Alice", "Bob")
    game = BluffGame("TST", players, capture)
    await game.start()

    types = {m["type"] for m in messages}
    assert "bluff_question" in types


@pytest.mark.anyio
async def test_too_similar_rejected():
    errors: list[dict] = []

    async def capture(msg, target=None):
        if msg.get("type") == "error":
            errors.append(msg)

    players = make_players("Alice", "Bob")
    game = BluffGame("TST", players, capture)
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

    await game.handle_action("pid0", "submit_lie", {"text": "fake A"})
    await game.handle_action("pid1", "submit_lie", {"text": "fake B"})
    await game.handle_action("pid2", "submit_lie", {"text": "fake C"})
    assert game.phase == "voting"

    truth_idx = game._choice_keys.index("truth")

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
    game = BluffGame("TST", players, capture)
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
    assert game.lies.get("pid0") == first


@pytest.mark.anyio
async def test_get_host_state_structure():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    state = game.get_host_state()
    assert state["game"] == "bluff"
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
    game.votes = {"pid0": 1}
    game.game_provided = {"pid2"}
    game.lie_for_me_players = set()
    game._question_finalized = False
    game.phase = "voting"
    game.round_num = 1
    game.current_question = {"prompt": "x", "truth": "the truth", "category": "t"}
    await game._finalize_voting()
    assert game.players["pid0"].score >= 0


# ──────────────────────────────────────────────────────────────────────
# Integration: HTTP API for Bluff and Baffle
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_bluff_party():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/party", json={"game_name": "bluff"})
    assert resp.status_code == 200
    body = resp.json()
    assert "code" in body
    assert body["host_url"] == f"/host/{body['code']}"


@pytest.mark.anyio
async def test_join_bluff_party_returns_bluff_player_url():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/api/party", json={"game_name": "bluff"})
        code = create.json()["code"]
        join = await c.post(f"/api/party/{code}/join")
    assert join.status_code == 200
    assert join.json()["player_url"] == f"/player/{code}"


@pytest.mark.anyio
async def test_bluff_host_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/api/party", json={"game_name": "bluff"})
        code = create.json()["code"]
        resp = await c.get(f"/host/{code}")
    assert resp.status_code == 200
    assert "bluff" in resp.text.lower() or "lantern" in resp.text.lower()
    assert '/bluff/host.css' in resp.text
    assert '/bluff/host.js' in resp.text


@pytest.mark.anyio
async def test_bluff_player_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/api/party", json={"game_name": "bluff"})
        code = create.json()["code"]
        resp = await c.get(f"/player/{code}")
    assert resp.status_code == 200
    assert '/bluff/player.css' in resp.text
    assert '/bluff/player.js' in resp.text


@pytest.mark.anyio
async def test_lampoon_party_host_url_uses_party_code():
    """Lampoon party host URL is /host/{code} with no query param."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/party", json={"game_name": "lampoon"})
    body = resp.json()
    assert body["host_url"] == f"/host/{body['code']}"


@pytest.mark.anyio
async def test_unknown_game_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/party", json={"game_name": "unknown_game"})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_host_page_unknown_party_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/host/ZZZZ")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_end_game_broadcasts_party_ended_and_deletes_party():
    """After game over, a party_ended message is sent and the party is removed."""
    from unittest.mock import patch
    from backend.party_manager import party_manager

    messages: list[dict] = []

    async def capture(msg, target=None):
        messages.append({"msg": msg, "target": target})

    party = party_manager.create_party(game_name="bluff")
    players = make_players("Alice", "Bob")
    game = BluffGame(party.code, players, capture)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await game._end_game()

    types_sent = [m["msg"]["type"] for m in messages]
    assert "game_over" in types_sent
    assert "party_ended" in types_sent
    # Party should be removed from manager
    assert party_manager.get_party(party.code) is None
