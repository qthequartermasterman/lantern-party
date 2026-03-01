"""
WebSocket router – handles real-time connections for host and players.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.games.fib.game import FibGame
from backend.games.lampoon.game import LampoonGame, Player
from backend.party_manager import party_manager

router = APIRouter()


async def _send(ws: WebSocket, message: dict[str, Any]) -> None:
    try:
        await ws.send_text(json.dumps(message))
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# Host connection
# ──────────────────────────────────────────────────────────────────────

@router.websocket("/ws/{party_code}/host")
async def host_ws(websocket: WebSocket, party_code: str) -> None:
    party = party_manager.get_party(party_code)
    if not party:
        await websocket.accept()
        await _send(websocket, {"type": "error", "data": {"message": "Party not found"}})
        await websocket.close()
        return

    await websocket.accept()
    party.host_ws = websocket

    # Send current lobby/game state
    if party.game:
        await _send(
            websocket,
            {"type": "game_state", "data": party.game.get_host_state()},
        )
    else:
        await _send(websocket, _lobby_state(party))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action_type: str = msg.get("type", "")
            data: dict[str, Any] = msg.get("data", {})
            await _handle_host_message(party_code, action_type, data)
    except WebSocketDisconnect:
        party.host_ws = None


async def _handle_host_message(
    party_code: str, action_type: str, data: dict[str, Any]
) -> None:
    party = party_manager.get_party(party_code)
    if not party:
        return

    if action_type == "start_game":
        ready_count = sum(1 for p in party.players.values() if p.ready)
        if ready_count < 2:
            if party.host_ws:
                await _send(
                    party.host_ws,
                    {
                        "type": "error",
                        "data": {"message": "Need at least 2 ready players to start."},
                    },
                )
            return

        party.state = "playing"
        if party.game_name == "fib":
            game: LampoonGame | FibGame = FibGame(
                party_code=party_code,
                players=party.players,
                broadcast=party.broadcast,
            )
        else:
            game = LampoonGame(
                party_code=party_code,
                players=party.players,
                broadcast=party.broadcast,
            )
        party.game = game
        await game.start()

    elif action_type == "next":
        if party.game:
            await party.game.handle_action("host", "next", data)


# ──────────────────────────────────────────────────────────────────────
# Player connection
# ──────────────────────────────────────────────────────────────────────

@router.websocket("/ws/{party_code}/player/{player_id}")
async def player_ws(
    websocket: WebSocket, party_code: str, player_id: str
) -> None:
    party = party_manager.get_party(party_code)
    if not party:
        await websocket.accept()
        await _send(websocket, {"type": "error", "data": {"message": "Party not found"}})
        await websocket.close()
        return

    await websocket.accept()

    # Reconnection: if player already exists, restore connection
    existing_player = party.players.get(player_id)
    if existing_player:
        existing_player.is_connected = True
        party.player_ws[player_id] = websocket
        # Send current state
        if party.game:
            await _send(
                websocket,
                {"type": "game_state", "data": party.game.get_player_state(player_id)},
            )
        else:
            await _send(websocket, _lobby_state(party))
    else:
        # New player – store socket, wait for 'join' message
        party.player_ws[player_id] = websocket
        await _send(websocket, _lobby_state(party))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action_type: str = msg.get("type", "")
            data: dict[str, Any] = msg.get("data", {})
            await _handle_player_message(party_code, player_id, action_type, data, websocket)
    except WebSocketDisconnect:
        _on_player_disconnect(party, player_id)


def _on_player_disconnect(party: Any, player_id: str) -> None:
    party.player_ws.pop(player_id, None)
    p = party.players.get(player_id)
    if p:
        p.is_connected = False


async def _handle_player_message(
    party_code: str,
    player_id: str,
    action_type: str,
    data: dict[str, Any],
    websocket: WebSocket,
) -> None:
    party = party_manager.get_party(party_code)
    if not party:
        return

    if action_type == "join":
        if party.state != "lobby":
            await _send(
                websocket,
                {"type": "error", "data": {"message": "Game already in progress."}},
            )
            return
        name: str = str(data.get("name", "")).strip()[:20]
        if not name:
            await _send(
                websocket, {"type": "error", "data": {"message": "Name is required."}}
            )
            return
        # Check duplicate names
        taken = {p.name.lower() for p in party.players.values()}
        if name.lower() in taken:
            await _send(
                websocket,
                {"type": "error", "data": {"message": "That name is already taken."}},
            )
            return

        player = Player(id=player_id, name=name, is_connected=True)
        party.players[player_id] = player

        # Notify everyone
        await party.broadcast(
            {"type": "player_joined", "data": {"id": player_id, "name": name}}, None
        )
        await party.broadcast({"type": "lobby_state", "data": _lobby_data(party)}, None)

    elif action_type == "ready":
        p = party.players.get(player_id)
        if p and party.state == "lobby":
            p.ready = bool(data.get("ready", True))
            await party.broadcast(
                {"type": "player_ready", "data": {"id": player_id, "ready": p.ready}},
                None,
            )
            await party.broadcast(
                {"type": "lobby_state", "data": _lobby_data(party)}, None
            )

    elif party.game and action_type not in ("join", "ready"):
        await party.game.handle_action(player_id, action_type, data)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _lobby_data(party: Any) -> dict[str, Any]:
    return {
        "party_code": party.code,
        "state": party.state,
        "players": [
            {"id": p.id, "name": p.name, "ready": p.ready}
            for p in party.players.values()
        ],
    }


def _lobby_state(party: Any) -> dict[str, Any]:
    return {"type": "lobby_state", "data": _lobby_data(party)}
