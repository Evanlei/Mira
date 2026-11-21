"""Draft roles (data/roles.json, from BobbyBS's draft guide) as an index per brawler."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROLES = ("anti_tank", "control", "thrower", "sniper", "space_maker", "tank", "support")
DEFAULT_PATH = "data/roles.json"


def load(names: list[str], path: str | Path = DEFAULT_PATH) -> np.ndarray:
    """(len(names),) role index per brawler name, -1 for brawlers without a role."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))["roles"]
    return np.array([ROLES.index(data[n]["role"]) if n in data else -1 for n in names], dtype=np.int32)
