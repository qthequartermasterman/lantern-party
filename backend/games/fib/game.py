"""
Fib – Lantern Party bluffing trivia game.

State machine per game:
  lobby → collecting_lies → voting → revealing → [next question]
        → scores (end-of-regular-round) → collecting_lies (next round)
        → game_over

Scoring (all × round multiplier):
  • Finding the truth          : 1000 pts
  • Each player you fool        : 500 pts  (250 if you used "Lie for me!")
  • Voting for a game-provided lie: −500 pts
  Round multipliers: R1 = 1, R2 = 2, Final (R3) = 3
"""
from __future__ import annotations

import asyncio
import difflib
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from backend.games.base import BaseGame
from backend.games.fib.prompts import FINAL_PROMPTS, LIE_BANK, ROUND_PROMPTS

if TYPE_CHECKING:
    pass

# ─────────────────────────────────────────────────────────────
# Shared data model (re-exported so ws.py can import from here)
# ─────────────────────────────────────────────────────────────

@dataclass
class Player:
    id: str
    name: str
    score: int = 0
    ready: bool = False
    is_connected: bool = True


# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

QUESTIONS_PER_ROUND = 3
_ROUND_MULT = {1: 1, 2: 2, 3: 3}

Broadcaster = Callable[[dict[str, Any], str | None], Awaitable[None]]


# ─────────────────────────────────────────────────────────────
# Similarity helper
# ─────────────────────────────────────────────────────────────

def _is_too_similar(text: str, truth: str) -> bool:
    """Return True if *text* is too similar to *truth* to be accepted."""
    t = text.lower().strip()
    r = truth.lower().strip()
    if t == r:
        return True
    ratio = difflib.SequenceMatcher(None, t, r).ratio()
    return ratio > 0.8


# ─────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────

def _score_question(
    choice_keys: list[str],
    votes: dict[str, int],
    game_provided: set[str],
    lie_for_me_players: set[str],
    round_mult: int,
    players: dict[str, Player],
) -> dict[str, int]:
    """
    Compute score deltas for one question.

    choice_keys[i]  = "truth" | player_id  for the choice at index i.
    votes[voter_id] = choice_index the voter selected.

    Returns {player_id: delta} (only non-zero entries).
    """
    deltas: dict[str, int] = {}

    for voter_id, choice_idx in votes.items():
        if voter_id not in players:
            continue
        if choice_idx < 0 or choice_idx >= len(choice_keys):
            continue
        key = choice_keys[choice_idx]
        if key == "truth":
            deltas[voter_id] = deltas.get(voter_id, 0) + 1000 * round_mult
        elif key in game_provided:
            # Voted for a game-provided (auto) lie → penalty
            deltas[voter_id] = deltas.get(voter_id, 0) - 500 * round_mult

    # Fooling points for each liar
    for liar_id in players:
        if liar_id not in choice_keys:
            continue  # player may have had game-provided lie with no separate key
        fooled = sum(
            1
            for voter_id, choice_idx in votes.items()
            if choice_idx < len(choice_keys)
            and choice_keys[choice_idx] == liar_id
            and voter_id != liar_id
        )
        if fooled == 0:
            continue
        if liar_id in game_provided:
            if liar_id in lie_for_me_players:
                # Half points for "Lie for me!" users
                deltas[liar_id] = deltas.get(liar_id, 0) + 250 * round_mult * fooled
            # else auto-timeout: 0 fooling points
        else:
            deltas[liar_id] = deltas.get(liar_id, 0) + 500 * round_mult * fooled

    return deltas


# ─────────────────────────────────────────────────────────────
# Game class
# ─────────────────────────────────────────────────────────────

class FibGame(BaseGame):
    """
    Fib – the Lantern Party bluffing trivia game.

    Three rounds (R1, R2, R3-final).  Each question the host displays a
    trivia fact with one word/phrase blanked out.  Players invent lies;
    everyone votes for what they believe is the truth.
    """

    def __init__(
        self,
        party_code: str,
        players: dict[str, Player],
        broadcast: Broadcaster,
    ) -> None:
        self.party_code = party_code
        self.players = players
        self.broadcast = broadcast

        self.phase: str = "lobby"
        self.round_num: int = 0

        # Question pool
        self._round_question_pool: list[dict] = []
        self._final_question_pool: list[dict] = []
        self._question_idx_in_round: int = 0
        self.total_questions_in_round: int = 0
        self.current_question: dict | None = None

        # Per-question state
        self.lies: dict[str, str] = {}           # player_id → lie text
        self.game_provided: set[str] = set()     # player_ids whose lie was generated
        self.lie_for_me_players: set[str] = set()
        # Shuffled presentation
        self._choice_keys: list[str] = []        # choice_keys[i] → "truth" | player_id
        self._choice_texts: list[str] = []       # choice_texts[i] → display text
        self.votes: dict[str, int] = {}          # player_id → choice index
        self._question_finalized: bool = False

        # Likes: choice_index → list[player_id who liked it]
        self.likes: dict[int, list[str]] = {}
        # Cumulative likes received per player (liar's key is their player_id)
        self.total_likes: dict[str, int] = {}

        # Timer
        self._timer_task: asyncio.Task | None = None
        self._timer_seconds: int = 0

    # ── Public interface ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Called by the host when they click Start Game."""
        self.round_num = 1
        self._pick_questions(1)
        await self._start_next_question()

    async def handle_action(
        self, player_id: str, action_type: str, data: dict[str, Any]
    ) -> None:
        handler = {
            "submit_lie": self._handle_submit_lie,
            "submit_vote": self._handle_submit_vote,
            "submit_like": self._handle_submit_like,
            "next": self._handle_next,
        }.get(action_type)
        if handler:
            await handler(player_id, data)

    def get_host_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "game": "fib",
            "phase": self.phase,
            "round_num": self.round_num,
            "scores": self._scores_list(),
            "timer": self._timer_seconds,
        }
        if self.current_question:
            state["current_question"] = {
                "prompt": self.current_question["prompt"],
                "category": self.current_question.get("category", ""),
                "question_num": self._question_idx_in_round,
                "total_questions": self.total_questions_in_round,
            }
        if self.phase == "collecting_lies":
            state["lies_received"] = len(self.lies)
            state["lies_expected"] = self._active_player_count()
        if self.phase == "voting":
            state["votes_received"] = len(self.votes)
            state["votes_expected"] = self._active_player_count()
            state["choices_count"] = len(self._choice_texts)
        if self.phase == "revealing":
            state["reveal"] = self._build_reveal_data(include_truth=True)
        if self.phase == "game_over":
            state["final_scores"] = self._scores_list()
            state["thumbs_cup"] = self._thumbs_cup_winner()
        return state

    def get_player_state(self, player_id: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "game": "fib",
            "phase": self.phase,
            "round_num": self.round_num,
            "scores": self._scores_list(),
            "timer": self._timer_seconds,
        }
        if self.current_question:
            state["current_question"] = {
                "prompt": self.current_question["prompt"],
                "category": self.current_question.get("category", ""),
                "question_num": self._question_idx_in_round,
                "total_questions": self.total_questions_in_round,
            }
        if self.phase == "collecting_lies":
            state["submitted_lie"] = player_id in self.lies
        if self.phase == "voting":
            state["choices"] = [
                {"index": i, "text": t}
                for i, t in enumerate(self._choice_texts)
            ]
            state["already_voted"] = player_id in self.votes
            # Players cannot vote for their own lie
            own_idx = next(
                (i for i, k in enumerate(self._choice_keys) if k == player_id),
                None,
            )
            state["own_choice_index"] = own_idx
        if self.phase == "revealing":
            state["reveal"] = self._build_reveal_data(include_truth=True)
            state["likes_given"] = [
                idx
                for idx, likers in self.likes.items()
                if player_id in likers
            ]
        if self.phase == "game_over":
            state["final_scores"] = self._scores_list()
            state["thumbs_cup"] = self._thumbs_cup_winner()
        return state

    # ── Internal helpers ─────────────────────────────────────────────────

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

    def _thumbs_cup_winner(self) -> str | None:
        if not self.total_likes:
            return None
        best_id = max(self.total_likes, key=lambda pid: self.total_likes[pid])
        if self.total_likes[best_id] == 0:
            return None
        p = self.players.get(best_id)
        return p.name if p else None

    def _pick_questions(self, round_num: int) -> None:
        """Populate the question pool for the given round."""
        if round_num == 3:
            pool = FINAL_PROMPTS
            n = 1
        else:
            pool = ROUND_PROMPTS
            n = QUESTIONS_PER_ROUND

        # Shuffle and pick without repeating already-used prompts in this game
        used = self._round_question_pool  # track via side-effect below
        available = [q for q in pool if q not in self._round_question_pool]
        if len(available) < n:
            available = list(pool)
        chosen = random.sample(available, k=min(n, len(available)))
        self._round_question_pool.extend(chosen)

        # Reset the per-round queue
        self._questions_queue: list[dict] = list(chosen)
        self._question_idx_in_round = 0
        self.total_questions_in_round = len(chosen)

    async def _start_next_question(self) -> None:
        """Advance to the next question or end the round."""
        if not self._questions_queue:
            await self._end_round()
            return
        self.current_question = self._questions_queue.pop(0)
        self._question_idx_in_round += 1

        # Reset per-question state
        self.lies = {}
        self.game_provided = set()
        self.lie_for_me_players = set()
        self._choice_keys = []
        self._choice_texts = []
        self.votes = {}
        self.likes = {}
        self._question_finalized = False

        self.phase = "collecting_lies"

        await self.broadcast(
            {
                "type": "fib_question",
                "data": {
                    "prompt": self.current_question["prompt"],
                    "category": self.current_question.get("category", ""),
                    "round_num": self.round_num,
                    "question_num": self._question_idx_in_round,
                    "total_questions": self.total_questions_in_round,
                },
            },
            None,
        )
        await self._broadcast_game_state()
        await self._start_timer(90, self._on_collecting_expire)

    async def _on_collecting_expire(self) -> None:
        if self.phase == "collecting_lies":
            await self._begin_voting()

    # ── Lie submission ───────────────────────────────────────────────────

    async def _handle_submit_lie(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        if self.phase != "collecting_lies":
            return
        if player_id not in self.players:
            return
        if player_id in self.lies:
            return  # already submitted

        lie_for_me: bool = bool(data.get("lie_for_me", False))

        if lie_for_me:
            lie_text = self._generate_lie()
            self.game_provided.add(player_id)
            self.lie_for_me_players.add(player_id)
        else:
            raw = str(data.get("text", "")).strip()
            if not raw:
                return
            if len(raw) > 150:
                raw = raw[:150]
            # Check too similar to truth
            truth = self.current_question["truth"] if self.current_question else ""
            if _is_too_similar(raw, truth):
                await self.broadcast(
                    {
                        "type": "error",
                        "data": {"message": "Too similar to the truth! Try a different answer."},
                    },
                    player_id,
                )
                return
            lie_text = raw

        self.lies[player_id] = lie_text
        await self.broadcast(
            {"type": "game_state", "data": self.get_player_state(player_id)},
            player_id,
        )
        await self.broadcast(
            {
                "type": "game_state",
                "data": {
                    "game": "fib",
                    "phase": self.phase,
                    "lies_received": len(self.lies),
                    "lies_expected": self._active_player_count(),
                },
            },
            "host",
        )

        if len(self.lies) >= self._active_player_count():
            self._cancel_timer()
            await self._begin_voting()

    def _generate_lie(self) -> str:
        """Return a lie from the bank, avoiding the truth."""
        truth = (self.current_question["truth"] if self.current_question else "").lower()
        candidates = [l for l in LIE_BANK if l.lower() != truth]
        existing = {v.lower() for v in self.lies.values()}
        fresh = [c for c in candidates if c.lower() not in existing]
        return random.choice(fresh if fresh else candidates)

    # ── Voting phase ─────────────────────────────────────────────────────

    async def _begin_voting(self) -> None:
        """Fill missing lies, build shuffled choices, start voting."""
        if not self.current_question:
            return

        # Fill in missing lies for players who didn't submit
        for p in self._active_players():
            if p.id not in self.lies:
                self.lies[p.id] = self._generate_lie()
                self.game_provided.add(p.id)

        # Build shuffled choice list: truth + one lie per player
        truth_text = self.current_question["truth"]
        entries: list[tuple[str, str]] = [("truth", truth_text)]
        for pid, lie_text in self.lies.items():
            entries.append((pid, lie_text))
        random.shuffle(entries)

        self._choice_keys = [e[0] for e in entries]
        self._choice_texts = [e[1] for e in entries]

        self.votes = {}
        self.phase = "voting"

        voting_data = {
            "prompt": self.current_question["prompt"],
            "category": self.current_question.get("category", ""),
            "choices": [
                {"index": i, "text": t}
                for i, t in enumerate(self._choice_texts)
            ],
        }
        await self.broadcast({"type": "fib_voting", "data": voting_data}, None)
        await self._broadcast_game_state()
        await self._start_timer(30, self._on_voting_expire)

    async def _handle_submit_vote(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        if self.phase != "voting":
            return
        if player_id not in self.players:
            return
        if player_id in self.votes:
            return  # already voted

        choice_index = data.get("choice_index")
        if not isinstance(choice_index, int):
            return
        if choice_index < 0 or choice_index >= len(self._choice_keys):
            return

        # Can't vote for your own lie
        if self._choice_keys[choice_index] == player_id:
            await self.broadcast(
                {"type": "error", "data": {"message": "You can't vote for your own answer!"}},
                player_id,
            )
            return

        self.votes[player_id] = choice_index
        await self.broadcast(
            {"type": "game_state", "data": self.get_player_state(player_id)},
            player_id,
        )
        await self.broadcast(
            {
                "type": "game_state",
                "data": {
                    "game": "fib",
                    "phase": self.phase,
                    "votes_received": len(self.votes),
                    "votes_expected": self._active_player_count(),
                },
            },
            "host",
        )

        if len(self.votes) >= self._active_player_count():
            self._cancel_timer()
            await self._finalize_voting()

    async def _on_voting_expire(self) -> None:
        if self.phase == "voting":
            await self._finalize_voting()

    async def _finalize_voting(self) -> None:
        if self._question_finalized:
            return
        self._question_finalized = True

        mult = _ROUND_MULT.get(self.round_num, 1)
        deltas = _score_question(
            choice_keys=self._choice_keys,
            votes=self.votes,
            game_provided=self.game_provided,
            lie_for_me_players=self.lie_for_me_players,
            round_mult=mult,
            players=self.players,
        )
        for pid, delta in deltas.items():
            p = self.players.get(pid)
            if p:
                p.score = max(0, p.score + delta)

        self.phase = "revealing"
        reveal_data = self._build_reveal_data(include_truth=True)
        reveal_data["score_deltas"] = deltas
        await self.broadcast({"type": "fib_reveal", "data": reveal_data}, None)
        await self._broadcast_game_state()
        await self._start_timer(15, self._on_revealing_expire)

    def _build_reveal_data(self, *, include_truth: bool = False) -> dict[str, Any]:
        """Build the reveal payload for host and players."""
        if not self.current_question:
            return {}
        truth_text = self.current_question["truth"]
        truth_idx = next(
            (i for i, k in enumerate(self._choice_keys) if k == "truth"), None
        )
        choices_detail = []
        for i, (key, text) in enumerate(zip(self._choice_keys, self._choice_texts)):
            is_truth = key == "truth"
            vote_count = sum(1 for v in self.votes.values() if v == i)
            entry: dict[str, Any] = {
                "index": i,
                "text": text,
                "is_truth": is_truth,
                "votes": vote_count,
                "likes": len(self.likes.get(i, [])),
            }
            if not is_truth:
                p = self.players.get(key)
                entry["submitter_id"] = key
                entry["submitter_name"] = p.name if p else "?"
                entry["game_provided"] = key in self.game_provided
            choices_detail.append(entry)

        return {
            "prompt": self.current_question["prompt"],
            "truth": truth_text if include_truth else None,
            "truth_index": truth_idx,
            "choices": choices_detail,
            "scores": self._scores_list(),
        }

    # ── Likes ────────────────────────────────────────────────────────────

    async def _handle_submit_like(
        self, player_id: str, data: dict[str, Any]
    ) -> None:
        if self.phase != "revealing":
            return
        choice_index = data.get("choice_index")
        if not isinstance(choice_index, int):
            return
        if choice_index < 0 or choice_index >= len(self._choice_keys):
            return

        key = self._choice_keys[choice_index]
        # Can only like lies (not the truth, not your own lie)
        if key == "truth" or key == player_id:
            return

        likers = self.likes.setdefault(choice_index, [])
        if player_id in likers:
            return  # already liked
        likers.append(player_id)
        self.total_likes[key] = self.total_likes.get(key, 0) + 1

        await self.broadcast(
            {"type": "game_state", "data": self.get_player_state(player_id)},
            player_id,
        )
        await self.broadcast(
            {
                "type": "like_update",
                "data": {"choice_index": choice_index, "likes": len(likers)},
            },
            None,
        )

    # ── Revealing → next question ────────────────────────────────────────

    async def _on_revealing_expire(self) -> None:
        if self.phase == "revealing":
            await self._start_next_question()

    # ── Host "next" ──────────────────────────────────────────────────────

    async def _handle_next(self, player_id: str, data: dict[str, Any]) -> None:
        if player_id != "host":
            return
        if self.phase == "revealing":
            self._cancel_timer()
            await self._start_next_question()
        elif self.phase == "scores":
            self._cancel_timer()
            await self._advance_after_scores()

    # ── End of round ─────────────────────────────────────────────────────

    async def _end_round(self) -> None:
        self.phase = "scores"
        await self.broadcast(
            {
                "type": "fib_scores",
                "data": {
                    "scores": self._scores_list(),
                    "round_complete": self.round_num,
                },
            },
            None,
        )
        await self._broadcast_game_state()
        await self._start_timer(8, self._on_scores_expire)

    async def _on_scores_expire(self) -> None:
        if self.phase == "scores":
            await self._advance_after_scores()

    async def _advance_after_scores(self) -> None:
        if self.round_num == 1:
            self.round_num = 2
            self._pick_questions(2)
            await self._start_next_question()
        elif self.round_num == 2:
            self.round_num = 3
            self._pick_questions(3)
            await self._start_next_question()
        else:
            await self._end_game()

    async def _end_game(self) -> None:
        self.phase = "game_over"
        scores = self._scores_list()
        max_score = scores[0]["score"] if scores else 0
        winners = [s["name"] for s in scores if s["score"] == max_score]
        await self.broadcast(
            {
                "type": "game_over",
                "data": {
                    "final_scores": scores,
                    "winners": winners,
                    "thumbs_cup": self._thumbs_cup_winner(),
                },
            },
            None,
        )
        await self._broadcast_game_state()

    # ── Timer ────────────────────────────────────────────────────────────

    async def _start_timer(
        self,
        seconds: int,
        on_expire: Callable[[], Awaitable[None]],
    ) -> None:
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_seconds = seconds
        self._timer_task = asyncio.create_task(self._run_timer(seconds, on_expire))

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

    # ── Broadcast helper ─────────────────────────────────────────────────

    async def _broadcast_game_state(self) -> None:
        await self.broadcast(
            {"type": "game_state", "data": self.get_host_state()}, "host"
        )
        for pid in self.players:
            await self.broadcast(
                {"type": "game_state", "data": self.get_player_state(pid)}, pid
            )
