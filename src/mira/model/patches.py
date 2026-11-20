"""Balance-patch log (data/patches.json) and per-match training weights."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATCHES = Path("data/patches.json")
KINDS = {"buff", "nerf", "rework", "new"}


@dataclass(frozen=True)
class Patch:
    date: str  # YYYY-MM-DD; changes take effect from 00:00 UTC that day
    changes: dict[str, str]  # brawler name (API spelling) -> buff | nerf | rework | new

    @property
    def iso(self) -> str:
        return self.date + "T00:00:00Z"


def load(path: str | Path = DEFAULT_PATCHES) -> list[Patch]:
    p = Path(path)
    if not p.is_file():
        return []
    patches = []
    for item in json.loads(p.read_text(encoding="utf-8")):
        datetime.strptime(item["date"], "%Y-%m-%d")  # validate
        changes = {k.upper(): v for k, v in item.get("changes", {}).items()}
        bad = {k: v for k, v in changes.items() if v not in KINDS}
        if bad:
            raise ValueError(f"{p}: unknown change kinds on {item['date']}: {bad}")
        patches.append(Patch(item["date"], changes))
    return sorted(patches, key=lambda x: x.date)


def unknown_names(patches: list[Patch], known: set[str]) -> list[str]:
    """Brawler names in the patch log that don't match the API's spelling."""
    return sorted({n for p in patches for n in p.changes} - known)


def last_change(patches: list[Patch]) -> dict[str, str]:
    """Brawler name -> ISO time of its most recent change."""
    out: dict[str, str] = {}
    for p in patches:
        for name in p.changes:
            out[name] = max(out.get(name, ""), p.iso)
    return out


def _days_between(a_iso: str, b_iso: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    a = datetime.strptime(a_iso, fmt).replace(tzinfo=timezone.utc)
    b = datetime.strptime(b_iso, fmt).replace(tzinfo=timezone.utc)
    return (b - a).total_seconds() / 86400


def match_weights(
    times: list[str],
    brawler_names: list[list[str]],
    patches: list[Patch],
    reference: str,
    half_life_days: float = 28.0,
    pre_patch_factor: float = 0.1,
) -> list[float]:
    """Weight per match: exponential time decay, times ``pre_patch_factor`` if any of its
    six brawlers changed after the match was played (spec §4.4)."""
    changed = last_change(patches)
    weights = []
    for t, names in zip(times, brawler_names):
        w = 0.5 ** (max(0.0, _days_between(t, reference)) / half_life_days) if half_life_days > 0 else 1.0
        if any(changed.get(n, "") > t for n in names):
            w *= pre_patch_factor
        weights.append(w)
    return weights
