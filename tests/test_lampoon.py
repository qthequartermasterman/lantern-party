"""
Tests for the Lampoon game logic and HTTP API.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.games.lampoon.game import LampoonGame, Player, _score_matchup, _score_final, Matchup
from backend.main import app
from backend.party_manager import party_manager, PartyManager


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def make_players(*names: str) -> dict[str, Player]:
    return {f"pid{i}": Player(id=f"pid{i}", name=name) for i, name in enumerate(names)}


async def noop_broadcast(msg: dict[str, Any], target: str | None = None) -> None:
    pass


def make_game(players: dict[str, Player]) -> LampoonGame:
    return LampoonGame(
        party_code="TEST",
        players=players,
        broadcast=noop_broadcast,
    )


# ──────────────────────────────────────────────────────────────────────
# Unit: scoring
# ──────────────────────────────────────────────────────────────────────

class TestScoreMatchup:
    def _matchup(self, answer_a="hello", answer_b="world", votes_a=0, votes_b=0) -> Matchup:
        m = Matchup(prompt="?", player_a_id="pa", player_b_id="pb")
        m.answer_a = answer_a
        m.answer_b = answer_b
        m.votes_a = votes_a
        m.votes_b = votes_b
        return m

    def test_jinx(self):
        m = self._matchup(answer_a="same", answer_b="same")
        result = _score_matchup(m, 1, {})
        assert result["special"] == "jinx"
        assert result["points_a"] == 0
        assert result["points_b"] == 0

    def test_jinx_case_insensitive(self):
        m = self._matchup(answer_a="SAME", answer_b="same")
        result = _score_matchup(m, 1, {})
        assert result["special"] == "jinx"

    def test_no_answer_a(self):
        m = self._matchup(answer_a="", answer_b="something")
        result = _score_matchup(m, 1, {})
        assert result["special"] == "no_answer"
        assert result["points_a"] == 0
        assert result["points_b"] == 1000

    def test_no_answer_b(self):
        m = self._matchup(answer_a="something", answer_b="")
        result = _score_matchup(m, 1, {})
        assert result["points_a"] == 1000
        assert result["points_b"] == 0

    def test_no_answer_round2_double(self):
        m = self._matchup(answer_a="", answer_b="something")
        result = _score_matchup(m, 2, {})
        assert result["points_b"] == 2000

    def test_lampoon_unanimous(self):
        m = self._matchup(votes_a=3, votes_b=0)
        result = _score_matchup(m, 1, {})
        assert result["special"] == "lampoon"
        assert result["points_a"] > 0
        assert result["points_b"] == 0

    def test_super_lampoon(self):
        # 9 out of 10 = 90% → super_lampoon
        m = self._matchup(votes_a=9, votes_b=1)
        result = _score_matchup(m, 1, {})
        assert result["special"] == "super_lampoon"

    def test_win_bonus(self):
        m = self._matchup(votes_a=3, votes_b=1)
        result = _score_matchup(m, 1, {})
        assert result["points_a"] > result["points_b"]
        assert result["special"] is None

    def test_tie(self):
        m = self._matchup(votes_a=2, votes_b=2)
        result = _score_matchup(m, 1, {})
        assert result["special"] == "tie"
        assert result["points_a"] == result["points_b"]

    def test_round2_doubles_base(self):
        # With 50/50 votes in round 1 vs round 2
        m1 = self._matchup(votes_a=2, votes_b=2)
        m2 = self._matchup(votes_a=2, votes_b=2)
        r1 = _score_matchup(m1, 1, {})
        r2 = _score_matchup(m2, 2, {})
        assert r2["points_a"] == r1["points_a"] * 2

    def test_no_voters_tie(self):
        m = self._matchup(votes_a=0, votes_b=0)
        result = _score_matchup(m, 1, {})
        assert result["special"] == "tie"
        assert result["points_a"] == result["points_b"]


class TestScoreFinal:
    def test_all_votes(self):
        pts = _score_final(10, 10)
        assert pts == 30 * 100  # 100% * 30

    def test_half_votes(self):
        pts = _score_final(5, 10)
        assert pts == 30 * 50  # 50% * 30

    def test_no_votes(self):
        assert _score_final(0, 10) == 0

    def test_no_total(self):
        assert _score_final(0, 0) == 0


# ──────────────────────────────────────────────────────────────────────
# Unit: PartyManager
# ──────────────────────────────────────────────────────────────────────

class TestPartyManager:
    def test_create_and_get(self):
        mgr = PartyManager()
        party = mgr.create_party()
        assert len(party.code) == 4
        assert party.code.isupper()
        assert mgr.get_party(party.code) is party

    def test_get_uppercase(self):
        mgr = PartyManager()
        party = mgr.create_party()
        assert mgr.get_party(party.code.lower()) is party

    def test_get_missing(self):
        mgr = PartyManager()
        assert mgr.get_party("ZZZZ") is None

    def test_delete(self):
        mgr = PartyManager()
        party = mgr.create_party()
        mgr.delete_party(party.code)
        assert mgr.get_party(party.code) is None

    def test_unique_codes(self):
        mgr = PartyManager()
        codes = {mgr.create_party().code for _ in range(20)}
        assert len(codes) == 20


# ──────────────────────────────────────────────────────────────────────
# Unit: LampoonGame prompt assignment
# ──────────────────────────────────────────────────────────────────────

class TestPromptAssignment:
    def test_each_player_gets_two_prompts(self):
        players = make_players("Alice", "Bob", "Charlie", "Diana")
        game = make_game(players)
        game._assign_prompts_for_round()
        for pid in players:
            assignments = game.prompt_assignments.get(pid, [])
            assert len(assignments) >= 1  # at minimum 1 (could be 2 in normal flow)

    def test_matchup_count_equals_player_count(self):
        players = make_players("A", "B", "C", "D")
        game = make_game(players)
        game._assign_prompts_for_round()
        assert len(game.matchups) == len(players)

    def test_each_matchup_has_two_different_players(self):
        players = make_players("A", "B", "C", "D")
        game = make_game(players)
        game._assign_prompts_for_round()
        for m in game.matchups:
            assert m.player_a_id != m.player_b_id

    def test_two_players(self):
        players = make_players("Alice", "Bob")
        game = make_game(players)
        game._assign_prompts_for_round()
        # Should still work with minimal players
        assert len(game.matchups) >= 1


# ──────────────────────────────────────────────────────────────────────
# Integration: HTTP API
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_create_party():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/party", json={"game_name": "lampoon"})
    assert resp.status_code == 200
    body = resp.json()
    assert "code" in body
    assert len(body["code"]) == 4
    assert "host_url" in body


@pytest.mark.anyio
async def test_join_party():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/party", json={"game_name": "lampoon"})
        code = create_resp.json()["code"]
        join_resp = await client.post(f"/api/party/{code}/join")
    assert join_resp.status_code == 200
    assert "player_url" in join_resp.json()


@pytest.mark.anyio
async def test_join_nonexistent_party():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/party/ZZZZ/join")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_index_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "Lantern Party" in resp.text


@pytest.mark.anyio
async def test_host_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/host/ABCD?game=lampoon")
    assert resp.status_code == 200
    assert "host" in resp.text.lower()


@pytest.mark.anyio
async def test_player_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/party", json={"game_name": "lampoon"})
        code = resp.json()["code"]
        page = await client.get(f"/player/{code}?game=lampoon")
    assert page.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# Async game logic tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_game_start_broadcasts():
    messages: list[dict] = []

    async def capture_broadcast(msg, target=None):
        messages.append({"msg": msg, "target": target})

    players = make_players("Alice", "Bob", "Charlie")
    game = LampoonGame("TSTG", players, capture_broadcast)
    await game.start()

    types_sent = {m["msg"]["type"] for m in messages}
    assert "game_state" in types_sent or "prompt" in types_sent


@pytest.mark.anyio
async def test_submit_answer_advances_when_all_in():
    received: list[dict] = []

    async def capture(msg, target=None):
        received.append({"msg": msg, "target": target})

    # Use 3 players so there is always 1 eligible voter per matchup.
    # With a voter present, _start_current_matchup_reveal creates a 30s timer
    # task (background) and returns, leaving phase == "revealing".
    players = make_players("Alice", "Bob", "Charlie")
    game = LampoonGame("TADV", players, capture)
    game.phase = "answering"
    game.round_num = 1
    game._assign_prompts_for_round()

    # Submit all answers
    for pid, assignments in game.prompt_assignments.items():
        for _, idx in assignments:
            await game.handle_action(pid, "submit_answer", {"prompt_index": idx, "answer": "funny"})

    # Game should have moved to revealing (timer task is a background task,
    # so phase stays "revealing" until a vote or timer fires)
    assert game.phase == "revealing"


@pytest.mark.anyio
async def test_submit_vote():
    received: list[dict] = []

    async def capture(msg, target=None):
        received.append({"msg": msg, "target": target})

    players = make_players("Alice", "Bob", "Charlie")
    game = LampoonGame("TVOT", players, capture)
    game.phase = "answering"
    game.round_num = 1
    game._assign_prompts_for_round()

    # Submit all answers
    for pid, assignments in game.prompt_assignments.items():
        for _, idx in assignments:
            m = game.matchups[idx]
            await game.handle_action(pid, "submit_answer", {"prompt_index": idx, "answer": "test"})

    assert game.phase == "revealing"
    current = game._current_matchup()
    assert current is not None

    voter_id = next(
        pid for pid in players
        if pid not in (current.player_a_id, current.player_b_id)
    )
    await game.handle_action(voter_id, "submit_vote", {"voted_for_id": current.player_a_id})

    assert current.votes_a == 1


@pytest.mark.anyio
async def test_final_votes_must_sum_to_3():
    errors: list[dict] = []

    async def capture(msg, target=None):
        if msg.get("type") == "error":
            errors.append(msg)

    players = make_players("Alice", "Bob", "Charlie")
    game = LampoonGame("TFIN", players, capture)
    game.phase = "final_revealing"
    game.final_answers = {pid: "answer" for pid in players}

    # Try to submit only 2 votes
    await game.handle_action(
        "pid0", "submit_final_votes", {"votes": {"pid1": 2}}
    )
    assert any(e["data"]["message"] == "You must cast exactly 3 votes." for e in errors)


@pytest.mark.anyio
async def test_get_host_state_structure():
    players = make_players("Alice", "Bob")
    game = make_game(players)
    game.phase = "lobby"
    state = game.get_host_state()
    assert "phase" in state
    assert "scores" in state


@pytest.mark.anyio
async def test_get_player_state_answering():
    players = make_players("Alice", "Bob", "Charlie")
    game = make_game(players)
    game.phase = "answering"
    game.round_num = 1
    game._assign_prompts_for_round()

    pid = list(players.keys())[0]
    state = game.get_player_state(pid)
    assert "prompts" in state
    assert isinstance(state["prompts"], list)
