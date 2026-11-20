"""Is there enough data to train? Matches per map in the current Ranked pool vs a target."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_TARGET = 3000
DEFAULT_POOL_DAYS = 7
RANKED_TYPE = "soloRanked"


@dataclass
class MapCount:
    mode: str | None
    map: str | None
    matches: int
    last_seen: str

    def progress(self, target: int) -> float:
        return min(1.0, self.matches / target) if target else 1.0


@dataclass
class Readiness:
    target: int
    pool_days: int
    reference_time: str | None  # newest battle_time in the DB; the pool window ends here
    pool: list[MapCount]        # maps seen within pool_days of reference_time
    retired: list[MapCount]     # maps with data that have left the pool

    @property
    def ready(self) -> bool:
        return bool(self.pool) and all(m.matches >= self.target for m in self.pool)

    @property
    def total_needed(self) -> int:
        return sum(max(0, self.target - m.matches) for m in self.pool)

    @property
    def overall_progress(self) -> float:
        if not self.pool:
            return 0.0
        return sum(m.progress(self.target) for m in self.pool) / len(self.pool)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute(
    conn: sqlite3.Connection,
    target: int = DEFAULT_TARGET,
    pool_days: int = DEFAULT_POOL_DAYS,
    battle_type: str = RANKED_TYPE,
) -> Readiness:
    """The window is anchored on the newest stored battle, not the wall clock, so the
    pool stays meaningful even if the crawler hasn't run for a while."""
    newest = conn.execute(
        "SELECT MAX(battle_time) FROM battles WHERE battle_type = ?", (battle_type,)
    ).fetchone()[0]
    if newest is None:
        return Readiness(target, pool_days, None, [], [])
    ref = datetime.strptime(newest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    cutoff = _iso(ref - timedelta(days=pool_days))

    rows = conn.execute(
        """
        SELECT mode, map, COUNT(*) AS matches, MAX(battle_time) AS last_seen
        FROM battles WHERE battle_type = ?
        GROUP BY mode, map
        ORDER BY matches ASC, mode, map
        """,
        (battle_type,),
    ).fetchall()
    pool, retired = [], []
    for r in rows:
        mc = MapCount(r["mode"], r["map"], r["matches"], r["last_seen"])
        (pool if mc.last_seen >= cutoff else retired).append(mc)
    return Readiness(target, pool_days, newest, pool, retired)
