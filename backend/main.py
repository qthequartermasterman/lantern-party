"""
Lantern Party – FastAPI application entry point.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.party_manager import party_manager
from backend.routers.ws import router as ws_router

# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────

app = FastAPI(title="Lantern Party", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Games whose static files live under frontend/<game_slug>/
_KNOWN_GAMES = {"lampoon", "bluff"}


# ──────────────────────────────────────────────
# HTML page routes
# ──────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/host/{party_code}", include_in_schema=False)
async def host_page(party_code: str) -> FileResponse:
    party = party_manager.get_party(party_code)
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    path = FRONTEND_DIR / party.game_name / "host.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Game page not found")
    return FileResponse(path)


@app.get("/player/{party_code}", include_in_schema=False)
async def player_page(party_code: str) -> FileResponse:
    party = party_manager.get_party(party_code)
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    path = FRONTEND_DIR / party.game_name / "player.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Game page not found")
    return FileResponse(path)


# ──────────────────────────────────────────────
# REST API
# ──────────────────────────────────────────────

class CreatePartyRequest(BaseModel):
    game_name: str


@app.post("/api/party")
async def create_party(body: CreatePartyRequest) -> dict:
    if body.game_name not in _KNOWN_GAMES:
        raise HTTPException(status_code=400, detail="Unknown game")
    party = party_manager.create_party(game_name=body.game_name)
    return {
        "code": party.code,
        "host_url": f"/host/{party.code}",
    }


class JoinPartyRequest(BaseModel):
    pass  # code is in the URL; name is sent via WebSocket


@app.post("/api/party/{code}/join")
async def join_party(code: str) -> dict:
    party = party_manager.get_party(code)
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    if party.state != "lobby":
        raise HTTPException(status_code=400, detail="Game already in progress")
    upper = code.upper()
    return {"player_url": f"/player/{upper}"}


# ──────────────────────────────────────────────
# Static files (CSS, JS assets if any)
# ──────────────────────────────────────────────

# Mount static files last so the explicit routes above take priority
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
