# 🏮 Lantern Party

Open Source, phone-controlled browser party games for couch-friendly chaos.

## Running the App

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Then visit [http://localhost:8000](http://localhost:8000).

## How to Play

1. **Host** clicks **Create a Party** on the landing page → a big-screen host view opens showing a 4-letter party code.
2. **Players** open the URL on their phones, click **Join a Party**, type the code + a name, then tap **Join Game!**
3. Each player taps **Mark me as Ready**. Once ≥ 2 players are ready, the host hits **Start Game**.

### Lampoon Game Flow

| Phase | What happens |
|-------|-------------|
| **Answering (×2)** | Each player privately receives 2 prompts and types their funniest answers. 90-second timer. |
| **Revealing (×2)** | Each head-to-head matchup is shown on the big screen; everyone who isn't answering casts one vote. 30-second timer. |
| **Final Round** | All players answer the same prompt, then each distributes 3 votes. |
| **Game Over** | Scores tallied, winner crowned. |

### Scoring

| Outcome | Round 1 | Round 2 |
|---------|---------|---------|
| Win bonus | +100 pts | +200 pts |
| 🏮 **Lampoon!** (unanimous) | +250 pts | +500 pts |
| 🔥 **Super Lampoon!** (≥ 90%) | +250 pts | +500 pts |
| 🔗 **JINX** (identical answers) | 0 pts each | 0 pts each |
| No answer submitted | opponent +1000 | opponent +2000 |
| Final round | 3 000 pts split by vote % ||

## Project Structure

```
lantern-party/
├── backend/
│   ├── main.py              # FastAPI app, REST routes
│   ├── party_manager.py     # In-memory party/session store
│   ├── routers/
│   │   └── ws.py            # WebSocket endpoints
│   └── games/
│       ├── base.py          # Abstract BaseGame
│       └── lampoon/
│           ├── game.py      # Full Lampoon game logic
│           └── prompts.py   # 50+ original prompts
├── frontend/
│   ├── index.html           # Landing / lobby page
│   ├── host.html            # Big-screen host view
│   └── player.html          # Mobile player controller
├── requirements.txt
└── tests/
    └── test_lampoon.py      # 36 unit + integration tests
```

## Running Tests

```bash
pytest tests/ -v
```
