# 🏮 Lantern Party

Open Source, phone-controlled browser party games for couch-friendly chaos.

## Running the App

```bash
uv sync
uvicorn backend.main:app --reload --port 8000
```

Then visit [http://localhost:8000](http://localhost:8000).

Note: game-specific static assets should be referenced with absolute paths like `/bluff/host.css` (not relative `host.css`) because host/player pages are served from dynamic routes such as `/host/{code}` and `/player/{code}`.

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
├── pyproject.toml
├── uv.lock
└── tests/
    └── test_lampoon.py      # 36 unit + integration tests
```

## Commit Semantics

This project follows [Conventional Commits](https://www.conventionalcommits.org/) to automate versioning and changelog generation via [python-semantic-release](https://python-semantic-release.readthedocs.io/).

Each commit message should have the form:

```
<type>(<optional scope>): <short summary>
```

| Type | When to use | Version bump |
|------|-------------|--------------|
| `feat` | A new feature visible to users | **minor** |
| `fix` | A bug fix | **patch** |
| `perf` | A performance improvement | **patch** |
| `docs` | Documentation changes only | none |
| `style` | Formatting / whitespace (no logic change) | none |
| `refactor` | Code restructuring without feature/fix | none |
| `test` | Adding or updating tests | none |
| `chore` | Tooling, dependencies, config | none |
| `ci` | CI/CD pipeline changes | none |

A **breaking change** bumps the **major** version. Indicate it with a `!` after the type or a `BREAKING CHANGE:` footer:

```
feat!: redesign WebSocket protocol

BREAKING CHANGE: players must reconnect after a host restart
```

### Examples

```
feat(bluff): add lie-bank shuffle on round start
fix(lampoon): prevent duplicate prompt assignment
docs: update README with commit semantics
chore: upgrade fastapi to 0.115
```

## Running Tests

```bash
uv run pytest tests/ -v
```
