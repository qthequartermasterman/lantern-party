# Copilot Instructions for Lantern Party

## Commit Semantics

All commits **must** follow [Conventional Commits](https://www.conventionalcommits.org/). This drives automated versioning and changelog generation via `python-semantic-release`.

### Format

```
<type>(<optional scope>): <short summary in present tense, lowercase>
```

### Types and Version Bumps

| Type | Purpose | SemVer bump |
|------|---------|-------------|
| `feat` | New user-facing feature | minor |
| `fix` | Bug fix | patch |
| `perf` | Performance improvement | patch |
| `docs` | Documentation only | – |
| `style` | Formatting, whitespace | – |
| `refactor` | Restructuring without feature/fix | – |
| `test` | Adding or fixing tests | – |
| `chore` | Tooling, config, dependencies | – |
| `ci` | CI/CD pipeline changes | – |

Append `!` after the type (or add a `BREAKING CHANGE:` footer) to trigger a **major** version bump.

### Examples

```
feat(bluff): add lie-bank shuffle on round start
fix(lampoon): prevent duplicate prompt assignment
docs: update README with commit semantics
chore: upgrade fastapi to 0.115
feat!: redesign WebSocket protocol

BREAKING CHANGE: players must reconnect after a host restart
```

## Project Conventions

- **Backend**: FastAPI app in `backend/`. Run with `uv run uvicorn backend.main:app --reload --port 8000`.
- **Frontend**: Plain HTML/CSS/JS in `frontend/`. Static assets use absolute paths (e.g., `/bluff/host.css`).
- **Games**: Each game lives in `backend/games/<slug>/` and implements `BaseGame` from `backend/games/base.py`.
- **Tests**: Written with `pytest` + `pytest-asyncio` (strict mode) + `httpx` ASGI transport. Run with `uv run pytest tests/ -v`.
- **Dependencies**: Managed with `uv`. Add runtime deps to `[project].dependencies`, dev deps to `[dependency-groups].dev` in `pyproject.toml`.

## CI / Release

- **CI** (`.github/workflows/ci.yml`): Runs the full test suite on every push and pull request.
- **Release** (`.github/workflows/release.yml`): Runs `semantic-release version --push` on every push to `main`, bumping the version in `pyproject.toml` and creating a GitHub release automatically based on commit history.
