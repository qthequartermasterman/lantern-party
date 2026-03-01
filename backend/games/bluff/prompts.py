"""
Loads prompts for Bluff and Baffle from the JSON data file.

Each prompt entry has:
  prompt   – question text with "_____" as the blank
  truth    – the real answer
  category – display category
  lies     – list of plausible fake answers for auto-fill
"""
from __future__ import annotations

import json
from pathlib import Path

_DATA_FILE = Path(__file__).parent / "data" / "prompts.json"


def _load() -> dict:
    with open(_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


_data = _load()

ROUND_PROMPTS: list[dict] = _data["round_prompts"]
FINAL_PROMPTS: list[dict] = _data["final_prompts"]
