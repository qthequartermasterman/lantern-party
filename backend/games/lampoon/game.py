"""
Lampoon game implementation.

State machine:
  lobby → answering (R1) → revealing (R1) → answering (R2) → revealing (R2)
        → final_answering → final_revealing → game_over
"""
from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Awaitable

from backend.games.base import BaseGame
from backend.games.lampoon.prompts import FINAL_PROMPTS, ROUND_PROMPTS

if TYPE_CHECKING:
    pass

# ──────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────

@dataclass
class Player:
    id: str
    name: str
    score: int = 0
    ready: bool = False
    is_connected: bool = True


@dataclass
class Matchup:
    prompt: str
    player_a_id: str
    player_b_id: str
    answer_a: str = ""
    answer_b: str = ""
    votes_a: int = 0
    votes_b: int = 0
    voter_ids: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# Scoring helpers
# ──────────────────────────────────────────────

_ROUND_MULTIPLIER = {1: 1, 2: 2}


def _score_matchup(
    matchup: Matchup,
    round_num: int,
    players: dict[str, Player],
) -> dict[str, Any]:
    """
    Compute score delta for a matchup.
    Returns dict with keys: points_a, points_b, special
    """
    mult = _ROUND_MULTIPLIER[round_num]
    no_answer_bonus = 1000 * mult

    a_missing = matchup.answer_a.strip() == ""
    b_missing = matchup.answer_b.strip() == ""

    # JINX: both answers identical (non-empty, case-insensitive)
    if (
        not a_missing
        and not b_missing
        and matchup.answer_a.strip().lower() == matchup.answer_b.strip().lower()
    ):
        return {"points_a": 0, "points_b": 0, "special": "jinx"}

    # No-answer penalties / bonuses
    if a_missing and b_missing:
        return {"points_a": 0, "points_b": 0, "special": "no_answer"}
    if a_missing:
        return {"points_a": 0, "points_b": no_answer_bonus, "special": "no_answer"}
    if b_missing:
        return {"points_a": no_answer_bonus, "points_b": 0, "special": "no_answer"}

    total_votes = matchup.votes_a + matchup.votes_b
    if total_votes == 0:
        # No eligible voters (e.g. only 2 players) → tie
        win_bonus = 100 * mult
        return {
            "points_a": win_bonus,
            "points_b": win_bonus,
            "special": "tie",
        }

    pct_a = matchup.votes_a / total_votes * 100
    pct_b = matchup.votes_b / total_votes * 100

    base_a = math.floor(pct_a) * 10 * mult
    base_b = math.floor(pct_b) * 10 * mult

    win_bonus = 100 * mult
    lampoon_bonus = 250 * mult

    special: str | None = None

    if matchup.votes_a == total_votes:
        # Perfect sweep for A
        special = "lampoon"
        points_a = base_a + lampoon_bonus
        points_b = base_b
    elif matchup.votes_b == total_votes:
        special = "lampoon"
        points_a = base_a
        points_b = base_b + lampoon_bonus
    elif pct_a >= 90:
        special = "super_lampoon"
        points_a = base_a + lampoon_bonus
        points_b = base_b
    elif pct_b >= 90:
        special = "super_lampoon"
        points_a = base_a
        points_b = base_b + lampoon_bonus
    elif matchup.votes_a > matchup.votes_b:
        points_a = base_a + win_bonus
        points_b = base_b
    elif matchup.votes_b > matchup.votes_a:
        points_a = base_a
        points_b = base_b + win_bonus
    else:
        # Tie
        special = "tie"
        points_a = base_a + win_bonus
        points_b = base_b + win_bonus

    return {"points_a": points_a, "points_b": points_b, "special": special}


def _score_final(votes_for_player: int, total_votes: int) -> int:
    if total_votes == 0:
        return 0
    pct = votes_for_player / total_votes * 100
    return math.floor(pct) * 30


# ──────────────────────────────────────────────
# Game class
# ──────────────────────────────────────────────

Broadcaster = Callable[[dict[str, Any], str | None], Awaitable[None]]


class LampoonGame(BaseGame):
    """
    Lampoon – the Lantern Party word-answer game.

    The party passes a ``broadcast`` coroutine so the game can push
    messages to connected clients without importing WebSocket logic.

    broadcast(message, target_player_id=None)
      • target_player_id=None  → send to all (host + all players)
      • target_player_id="host" → send only to host
      • target_player_id=<uuid> → send only to that player
    """

    def __init__(
        self,
        party_code: str,
        players: dict[str, Player],
        broadcast: Broadcaster,
    ) -> None:
        self.party_code = party_code
        self.players = players  # shared reference with Party
        self.broadcast = broadcast

        self.phase: str = "lobby"
        self.round_num: int = 0  # 1 or 2 for regular rounds, 0 = lobby
        self.matchups: list[Matchup] = []
        self.current_matchup_idx: int = 0

        # prompt_assignments[player_id] = list of (prompt_text, global_matchup_idx)
        self.prompt_assignments: dict[str, list[tuple[str, int]]] = {}

        # answers_received: how many answers are in for current answering phase
        self._answers_expected: int = 0
        self._answers_received: int = 0

        # voting
        self._votes_expected: int = 0
        self._votes_received: int = 0

        # final round
        self.final_prompt: str = ""
        self.final_answers: dict[str, str] = {}  # player_id → answer
        # final_votes[voter_id] = {player_id: num_votes}
        self.final_votes: dict[str, dict[str, int]] = {}

        # timer task
        self._timer_task: asyncio.Task | None = None
        self._timer_seconds: int = 0

        # idempotency guard: tracks which matchup indices have already been finalized
        self._finalized_matchups: set[int] = set()

    # ── Public interface ────────────────────────────────────────────────

    async def start(self) -> None:
        """Called by host clicking 'Start Game'."""
        self.phase = "answering"
        self.round_num = 1
        self._assign_prompts_for_round()
        await self._send_prompts_to_players()
        await self._broadcast_game_state()
        await self._start_timer(90, self._on_answering_timer_expire)

    async def handle_action(
        self, player_id: str, action_type: str, data: dict[str, Any]
    ) -> None:
        handler = {
            "submit_answer": self._handle_submit_answer,
            "submit_vote": self._handle_submit_vote,
            "submit_final_votes": self._handle_submit_final_votes,
            "next": self._handle_next,
        }.get(action_type)
        if handler:
            await handler(player_id, data)

    def get_host_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "phase": self.phase,
            "round_num": self.round_num,
            "scores": self._scores_list(),
            "timer": self._timer_seconds,
        }
        if self.phase in ("answering",):
            state["answers_received"] = self._answers_received
            state["answers_expected"] = self._answers_expected
        if self.phase == "revealing":
            m = self._current_matchup()
            if m:
                state["matchup"] = self._matchup_dict(m, reveal_answers=True)
                state["matchup_index"] = self.current_matchup_idx
                state["matchup_total"] = len(self.matchups)
        if self.phase == "final_answering":
            state["final_prompt"] = self.final_prompt
            state["answers_received"] = len(self.final_answers)
            state["answers_expected"] = self._active_player_count()
        if self.phase == "final_revealing":
            state["final_prompt"] = self.final_prompt
            state["final_answers"] = [
                {
                    "player_id": pid,
                    "name": self.players[pid].name,
                    "answer": ans,
                    "votes": sum(
                        v.get(pid, 0) for v in self.final_votes.values()
                    ),
                }
                for pid, ans in self.final_answers.items()
                if pid in self.players
            ]
        if self.phase == "game_over":
            state["final_scores"] = self._scores_list()
        return state

    def get_player_state(self, player_id: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "phase": self.phase,
            "round_num": self.round_num,
            "scores": self._scores_list(),
            "timer": self._timer_seconds,
        }
        if self.phase == "answering":
            prompts = self.prompt_assignments.get(player_id, [])
            state["prompts"] = [
                {"prompt_text": p[0], "prompt_index": p[1]} for p in prompts
            ]
            # Which prompt indices this player has already answered
            submitted = []
            for p_text, p_idx in prompts:
                if p_idx < len(self.matchups):
                    m = self.matchups[p_idx]
                    if m.player_a_id == player_id and m.answer_a:
                        submitted.append(p_idx)
                    elif m.player_b_id == player_id and m.answer_b:
                        submitted.append(p_idx)
            state["submitted"] = submitted

        if self.phase == "revealing":
            m = self._current_matchup()
            if m:
                # Only show both answers during reveal
                state["matchup"] = self._matchup_dict(m, reveal_answers=True)
                state["matchup_index"] = self.current_matchup_idx
                state["matchup_total"] = len(self.matchups)
                # Can this player vote?
                already_voted = player_id in m.voter_ids
                is_answerer = player_id in (m.player_a_id, m.player_b_id)
                state["can_vote"] = not already_voted and not is_answerer
                state["already_voted"] = already_voted

        if self.phase == "final_answering":
            state["final_prompt"] = self.final_prompt
            state["submitted_final"] = player_id in self.final_answers

        if self.phase == "final_revealing":
            state["final_prompt"] = self.final_prompt
            state["final_answers"] = [
                {
                    "player_id": pid,
                    "name": self.players[pid].name,
                    "answer": ans,
                    "votes": sum(
                        v.get(pid, 0) for v in self.final_votes.values()
                    ),
                }
                for pid, ans in self.final_answers.items()
                if pid in self.players
            ]
            state["already_voted_final"] = player_id in self.final_votes

        if self.phase == "game_over":
            state["final_scores"] = self._scores_list()

        return state

    # ── Internal helpers ────────────────────────────────────────────────

    def _active_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.is_connected]

    def _active_player_count(self) -> int:
        return len(self._active_players())

    def _scores_list(self) -> list[dict[str, Any]]:
        return sorted(
            [{"id": p.id, "name": p.name, "score": p.score} for p in self.players.values()],
            key=lambda x: x["score"],
            reverse=True,
        )

    def _current_matchup(self) -> Matchup | None:
        if 0 <= self.current_matchup_idx < len(self.matchups):
            return self.matchups[self.current_matchup_idx]
        return None

    def _matchup_dict(self, m: Matchup, *, reveal_answers: bool = False) -> dict[str, Any]:
        pa = self.players.get(m.player_a_id)
        pb = self.players.get(m.player_b_id)
        d: dict[str, Any] = {
            "prompt": m.prompt,
            "player_a_id": m.player_a_id,
            "player_b_id": m.player_b_id,
            "player_a_name": pa.name if pa else "?",
            "player_b_name": pb.name if pb else "?",
            "votes_a": m.votes_a,
            "votes_b": m.votes_b,
        }
        if reveal_answers:
            d["answer_a"] = m.answer_a
            d["answer_b"] = m.answer_b
        return d

    def _assign_prompts_for_round(self) -> None:
        """Assign prompts & build matchups for the current round."""
        self.matchups = []
        self.prompt_assignments = {}
        self.current_matchup_idx = 0
        self._answers_received = 0

        active = self._active_players()
        n = len(active)
        if n < 2:
            return

        # Choose prompts: we need exactly n prompts (one per matchup).
        # If there are fewer unique prompts than players, tile and shuffle.
        if not ROUND_PROMPTS:
            return
        if len(ROUND_PROMPTS) >= n:
            chosen = random.sample(ROUND_PROMPTS, k=n)
        else:
            repeats = math.ceil(n / len(ROUND_PROMPTS))
            prompt_pool = list(ROUND_PROMPTS) * repeats
            random.shuffle(prompt_pool)
            chosen = prompt_pool[:n]

        # Pair players round-robin style
        random.shuffle(active)
        matchup_list: list[Matchup] = []
        for i, prompt in enumerate(chosen):
            pa = active[i % n]
            pb = active[(i + 1) % n]
            # Avoid self-matchup
            if pa.id == pb.id:
                pb = active[(i + 2) % n]
            matchup_list.append(Matchup(prompt=prompt, player_a_id=pa.id, player_b_id=pb.id))

        self.matchups = matchup_list

        # Build per-player prompt assignments
        for idx, m in enumerate(self.matchups):
            self.prompt_assignments.setdefault(m.player_a_id, []).append((m.prompt, idx))
            self.prompt_assignments.setdefault(m.player_b_id, []).append((m.prompt, idx))

        # Each player should have exactly 2 prompts; if a player appears only once
        # (small groups), duplicate to fill
        for pid in [p.id for p in active]:
            while len(self.prompt_assignments.get(pid, [])) < 2:
                extra_idx = random.randrange(len(self.matchups))
                extra_m = self.matchups[extra_idx]
                # Only add if player is one of the answerers
                if pid in (extra_m.player_a_id, extra_m.player_b_id):
                    self.prompt_assignments[pid].append((extra_m.prompt, extra_idx))
                else:
                    break  # can't pad safely, leave as-is

        # Derive _answers_expected from the actual assignments, not a fixed n*2,
        # so rounds advance correctly even if some players got fewer prompts.
        self._answers_expected = sum(
            len(assignments) for assignments in self.prompt_assignments.values()
        )

    async def _send_prompts_to_players(self) -> None:
        for player_id, prompts in self.prompt_assignments.items():
            msg = {
                "type": "prompt",
                "data": {
                    "prompts": [
                        {"prompt_text": p[0], "prompt_index": p[1]} for p in prompts
                    ]
                },
            }
            await self.broadcast(msg, player_id)

    async def _broadcast_game_state(self) -> None:
        # Send host state
        await self.broadcast(
            {"type": "game_state", "data": self.get_host_state()}, "host"
        )
        # Send personalized state to each player
        for pid in self.players:
            await self.broadcast(
                {"type": "game_state", "data": self.get_player_state(pid)}, pid
            )

    # ── Timer ────────────────────────────────────────────────────────────

    async def _start_timer(
        self,
        seconds: int,
        on_expire: Callable[[], Awaitable[None]],
    ) -> None:
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_seconds = seconds
        self._timer_task = asyncio.create_task(
            self._run_timer(seconds, on_expire)
        )

    async def _run_timer(
        self,
        seconds: int,
        on_expire: Callable[[], Awaitable[None]],
    ) -> None:
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
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_seconds = 0

    # ── Answering phase ──────────────────────────────────────────────────

    async def _on_answering_timer_expire(self) -> None:
        if self.phase == "answering":
            await self._begin_revealing()

    # ── Revealing phase ──────────────────────────────────────────────────

    async def _begin_revealing(self) -> None:
        self.phase = "revealing"
        self.current_matchup_idx = 0
        self._finalized_matchups = set()
        await self._start_current_matchup_reveal()

    async def _start_current_matchup_reveal(self) -> None:
        m = self._current_matchup()
        if m is None:
            await self._end_revealing()
            return

        pa = self.players.get(m.player_a_id)
        pb = self.players.get(m.player_b_id)
        msg: dict[str, Any] = {
            "type": "matchup_start",
            "data": {
                "prompt": m.prompt,
                "player_a_id": m.player_a_id,
                "player_b_id": m.player_b_id,
                "player_a_name": pa.name if pa else "?",
                "player_b_name": pb.name if pb else "?",
                "answer_a": m.answer_a,
                "answer_b": m.answer_b,
                "matchup_index": self.current_matchup_idx,
                "matchup_total": len(self.matchups),
            },
        }
        await self.broadcast(msg, None)
        await self._broadcast_game_state()

        # Count eligible voters
        eligible_voters = [
            p
            for p in self._active_players()
            if p.id not in (m.player_a_id, m.player_b_id)
        ]
        self._votes_expected = len(eligible_voters)
        self._votes_received = 0

        if self._votes_expected == 0:
            # No voters possible – auto-advance after computing scores
            await self._finalize_matchup_voting()
        else:
            await self._start_timer(30, self._on_voting_timer_expire)

    async def _handle_submit_vote(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        if self.phase != "revealing":
            return
        m = self._current_matchup()
        if m is None:
            return
        if player_id in (m.player_a_id, m.player_b_id):
            await self.broadcast(
                {"type": "error", "data": {"message": "You are answering this round!"}},
                player_id,
            )
            return
        if player_id in m.voter_ids:
            return  # already voted

        voted_for: str = data.get("voted_for_id", "")
        if voted_for == m.player_a_id:
            m.votes_a += 1
        elif voted_for == m.player_b_id:
            m.votes_b += 1
        else:
            return

        m.voter_ids.append(player_id)
        self._votes_received += 1

        await self._broadcast_game_state()

        if self._votes_received >= self._votes_expected:
            self._cancel_timer()
            await self._finalize_matchup_voting()

    async def _on_voting_timer_expire(self) -> None:
        if self.phase == "revealing":
            await self._finalize_matchup_voting()

    async def _finalize_matchup_voting(self) -> None:
        # Idempotency guard: ensure this matchup is only finalized once even if
        # the voting timer and the last-vote path both call us concurrently.
        if self.current_matchup_idx in self._finalized_matchups:
            return
        self._finalized_matchups.add(self.current_matchup_idx)

        m = self._current_matchup()
        if m is None:
            return

        result = _score_matchup(m, self.round_num, self.players)
        pa = self.players.get(m.player_a_id)
        pb = self.players.get(m.player_b_id)
        if pa:
            pa.score += result["points_a"]
        if pb:
            pb.score += result["points_b"]

        vote_result_msg: dict[str, Any] = {
            "type": "vote_result",
            "data": {
                "player_a_id": m.player_a_id,
                "player_b_id": m.player_b_id,
                "player_a_name": pa.name if pa else "?",
                "player_b_name": pb.name if pb else "?",
                "points_a": result["points_a"],
                "points_b": result["points_b"],
                "votes_a": m.votes_a,
                "votes_b": m.votes_b,
                "special": result.get("special"),
            },
        }
        await self.broadcast(vote_result_msg, None)
        await self._broadcast_game_state()

        # Auto-advance after 4 s; guard against a concurrent host 'next' that
        # already advanced the matchup index during the sleep window.
        finalized_idx = self.current_matchup_idx
        await asyncio.sleep(4)
        if self.phase == "revealing" and self.current_matchup_idx == finalized_idx:
            await self._advance_matchup()

    async def _advance_matchup(self) -> None:
        self.current_matchup_idx += 1
        if self.current_matchup_idx >= len(self.matchups):
            await self._end_revealing()
        else:
            await self._start_current_matchup_reveal()

    async def _end_revealing(self) -> None:
        # Send scoreboard
        await self.broadcast(
            {
                "type": "scores",
                "data": {
                    "scores": self._scores_list(),
                    "round_complete": True,
                    "round_num": self.round_num,
                },
            },
            None,
        )
        if self.round_num == 1:
            # Advance to round 2
            await asyncio.sleep(5)
            await self._start_round2()
        else:
            # Round 2 done → final round
            await asyncio.sleep(5)
            await self._start_final_round()

    # ── Round 2 ──────────────────────────────────────────────────────────

    async def _start_round2(self) -> None:
        self.round_num = 2
        self.phase = "answering"
        self._assign_prompts_for_round()
        await self._send_prompts_to_players()
        await self._broadcast_game_state()
        await self._start_timer(90, self._on_answering_timer_expire)

    # ── Final round ──────────────────────────────────────────────────────

    async def _start_final_round(self) -> None:
        self.phase = "final_answering"
        self.final_prompt = random.choice(FINAL_PROMPTS)
        self.final_answers = {}
        self.final_votes = {}
        await self.broadcast(
            {"type": "final_prompt", "data": {"prompt_text": self.final_prompt}}, None
        )
        await self._broadcast_game_state()
        await self._start_timer(90, self._on_final_answering_expire)

    async def _on_final_answering_expire(self) -> None:
        if self.phase == "final_answering":
            await self._begin_final_revealing()

    async def _handle_submit_answer(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        """Unified answer submission for both regular and final rounds."""
        if self.phase == "answering":
            await self._handle_regular_answer(player_id, data)
        elif self.phase == "final_answering":
            await self._handle_final_answer(player_id, data)

    async def _handle_regular_answer(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        prompt_index: int = data.get("prompt_index", -1)
        answer: str = str(data.get("answer", "")).strip()
        if prompt_index < 0 or prompt_index >= len(self.matchups):
            return

        m = self.matchups[prompt_index]
        already_answered = False
        if m.player_a_id == player_id:
            if m.answer_a:
                already_answered = True
            else:
                m.answer_a = answer
        elif m.player_b_id == player_id:
            if m.answer_b:
                already_answered = True
            else:
                m.answer_b = answer
        else:
            return

        if not already_answered:
            self._answers_received += 1

        await self.broadcast(
            {
                "type": "game_state",
                "data": {
                    "phase": self.phase,
                    "answers_received": self._answers_received,
                    "answers_expected": self._answers_expected,
                },
            },
            "host",
        )
        await self.broadcast(
            {"type": "game_state", "data": self.get_player_state(player_id)},
            player_id,
        )

        if self._answers_received >= self._answers_expected:
            self._cancel_timer()
            await self._begin_revealing()

    async def _handle_final_answer(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        if player_id in self.final_answers:
            return
        answer: str = str(data.get("answer", "")).strip()
        self.final_answers[player_id] = answer
        await self.broadcast(
            {"type": "game_state", "data": self.get_player_state(player_id)},
            player_id,
        )
        await self.broadcast(
            {
                "type": "game_state",
                "data": {
                    "phase": self.phase,
                    "answers_received": len(self.final_answers),
                    "answers_expected": self._active_player_count(),
                },
            },
            "host",
        )
        if len(self.final_answers) >= self._active_player_count():
            self._cancel_timer()
            await self._begin_final_revealing()

    async def _begin_final_revealing(self) -> None:
        self.phase = "final_revealing"
        await self.broadcast(
            {
                "type": "final_prompt",
                "data": {
                    "prompt_text": self.final_prompt,
                    "answers": [
                        {
                            "player_id": pid,
                            "name": self.players[pid].name if pid in self.players else "?",
                            "answer": ans,
                        }
                        for pid, ans in self.final_answers.items()
                    ],
                },
            },
            None,
        )
        await self._broadcast_game_state()

        # Count votes expected: each active player casts 3 votes (can stack)
        self._votes_expected = self._active_player_count()
        self._votes_received = 0

        await self._start_timer(60, self._on_final_voting_expire)

    async def _handle_submit_final_votes(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        if self.phase != "final_revealing":
            return
        if player_id in self.final_votes:
            return
        raw_votes = data.get("votes", {})
        if not isinstance(raw_votes, dict):
            await self.broadcast(
                {"type": "error", "data": {"message": "Invalid vote format."}},
                player_id,
            )
            return

        valid_targets = set(self.final_answers.keys())
        total = 0
        for target_id, cnt in raw_votes.items():
            if target_id not in valid_targets:
                await self.broadcast(
                    {"type": "error", "data": {"message": "Invalid vote target."}},
                    player_id,
                )
                return
            if target_id == player_id:
                await self.broadcast(
                    {"type": "error", "data": {"message": "You cannot vote for yourself."}},
                    player_id,
                )
                return
            if not isinstance(cnt, int) or cnt < 0 or cnt > 3:
                await self.broadcast(
                    {"type": "error", "data": {"message": "Invalid vote count."}},
                    player_id,
                )
                return
            total += cnt

        if total != 3:
            await self.broadcast(
                {"type": "error", "data": {"message": "You must cast exactly 3 votes."}},
                player_id,
            )
            return

        self.final_votes[player_id] = raw_votes
        self._votes_received += 1
        await self.broadcast(
            {"type": "game_state", "data": self.get_player_state(player_id)},
            player_id,
        )
        await self._broadcast_game_state()

        if self._votes_received >= self._votes_expected:
            self._cancel_timer()
            await self._finalize_final_round()

    async def _on_final_voting_expire(self) -> None:
        if self.phase == "final_revealing":
            await self._finalize_final_round()

    async def _finalize_final_round(self) -> None:
        # Tally final votes
        total_votes = sum(
            sum(v.values()) for v in self.final_votes.values()
        )
        vote_totals: dict[str, int] = {}
        for voter_votes in self.final_votes.values():
            for target_id, cnt in voter_votes.items():
                vote_totals[target_id] = vote_totals.get(target_id, 0) + cnt

        player_results = []
        for pid, ans in self.final_answers.items():
            p = self.players.get(pid)
            if not p:
                continue
            votes_for = vote_totals.get(pid, 0)
            pts = _score_final(votes_for, total_votes)
            p.score += pts
            player_results.append(
                {"name": p.name, "answer": ans, "votes": votes_for, "points": pts}
            )

        player_results.sort(key=lambda x: x["votes"], reverse=True)
        await self.broadcast(
            {"type": "final_reveal", "data": {"player_votes": player_results}}, None
        )
        await asyncio.sleep(5)
        await self._end_game()

    async def _end_game(self) -> None:
        self.phase = "game_over"
        scores = self._scores_list()
        max_score = scores[0]["score"] if scores else 0
        winners = [s["name"] for s in scores if s["score"] == max_score]
        await self.broadcast(
            {
                "type": "game_over",
                "data": {"final_scores": scores, "winners": winners},
            },
            None,
        )
        await self._broadcast_game_state()

    # ── Host 'next' handler ──────────────────────────────────────────────

    async def _handle_next(self, player_id: str, data: dict[str, Any]) -> None:
        """Host can manually advance certain phases."""
        if player_id != "host":
            return
        # Only allow manual advance in the revealing phase if the current matchup
        # has already been finalized/scored (prevents skipping voting or double-scoring).
        if self.phase == "revealing":
            if self.current_matchup_idx not in self._finalized_matchups:
                return
            self._cancel_timer()
            await self._advance_matchup()
