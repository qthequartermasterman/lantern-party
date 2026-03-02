"""Pytest configuration and global hooks for the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


def _get_game_slugs() -> list[str]:
    """Return the slug of every game package found under backend/games/."""
    games_dir = Path(__file__).parent.parent / "backend" / "games"
    return [
        entry.name
        for entry in sorted(games_dir.iterdir())
        if entry.is_dir() and (entry / "__init__.py").exists()
    ]


def pytest_collection_finish(session: pytest.Session) -> None:
    """Raise an error if any game has no collected test items."""
    game_slugs = _get_game_slugs()

    covered: set[str] = set()
    for item in session.items:
        # item.fspath is the path to the test file
        test_filename = Path(str(item.fspath)).name
        for slug in game_slugs:
            if test_filename == f"test_{slug}.py" or test_filename.startswith(
                f"test_{slug}_"
            ):
                covered.add(slug)

    missing = sorted(set(game_slugs) - covered)
    if missing:
        pytest.exit(
            f"Missing tests for the following game(s): {', '.join(missing)}. "
            "Each game must have at least one test in a file whose name contains the game slug.",
            returncode=1,
        )
