"""Load stored matches into numpy arrays."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

RANKED_TYPE = "soloRanked"
MASTERS = 19             # Masters I: lobbies at or above this get full weight and form the test set
DEFAULT_MIN_LOBBY = 16   # Legendary I: lower lobbies are not loaded at all
DEFAULT_RANK_FACTOR = 0.5  # weight multiplier per rank step a lobby sits below MASTERS


@dataclass
class Matches:
    battle_ids: list[str]
    times: list[str]          # ISO, sorted ascending
    teams: np.ndarray         # (n, 2, 3) brawler index
    map_idx: np.ndarray       # (n,)
    mode_idx: np.ndarray      # (n,)
    y: np.ndarray             # (n,) 1.0 if team 0 won
    brawler_ids: list[int]    # index -> API brawler id
    brawler_names: list[str]  # index -> name
    maps: list[tuple[str, str]]  # index -> (mode, map)
    modes: list[str]          # index -> mode
    lobby_rank: np.ndarray | None = None  # (n,) lowest rank of the six players

    def __len__(self) -> int:
        return len(self.y)

    def subset(self, mask_or_idx) -> "Matches":
        idx = np.arange(len(self))[mask_or_idx]
        return Matches(
            [self.battle_ids[i] for i in idx], [self.times[i] for i in idx],
            self.teams[idx], self.map_idx[idx], self.mode_idx[idx], self.y[idx],
            self.brawler_ids, self.brawler_names, self.maps, self.modes,
            None if self.lobby_rank is None else self.lobby_rank[idx],
        )

    def ranks(self) -> np.ndarray:
        return np.full(len(self), MASTERS) if self.lobby_rank is None else self.lobby_rank

    def masters_mask(self) -> np.ndarray:
        return self.ranks() >= MASTERS

    def rank_weights(self, factor: float = DEFAULT_RANK_FACTOR) -> np.ndarray:
        """1 for all-Masters lobbies, ``factor`` per rank step below Masters I otherwise."""
        below = np.clip(MASTERS - self.ranks(), 0, None)
        return np.where(below == 0, 1.0, factor ** below.astype(float))

    def names_per_match(self) -> list[list[str]]:
        return [[self.brawler_names[b] for b in row.ravel()] for row in self.teams]

    @property
    def n_brawlers(self) -> int:
        return len(self.brawler_ids)


def load(conn: sqlite3.Connection, battle_type: str = RANKED_TYPE,
         min_lobby_rank: int | None = DEFAULT_MIN_LOBBY) -> Matches:
    """All non-draw matches of ``battle_type`` with six known brawlers, oldest first,
    from lobbies whose lowest rank is at least ``min_lobby_rank`` (None: no filter)."""
    rows = conn.execute(
        """
        SELECT b.battle_id, b.battle_time, b.mode, b.map, b.winning_team, b.lobby_rank,
               bp.team, bp.slot, bp.brawler_id, bp.brawler_name
        FROM battles b JOIN battle_players bp USING (battle_id)
        WHERE b.battle_type = ? AND b.is_draw = 0 AND b.winning_team IS NOT NULL
          AND (? IS NULL OR b.lobby_rank >= ?)
        ORDER BY b.battle_time, b.battle_id, bp.team, bp.slot
        """,
        (battle_type, min_lobby_rank, min_lobby_rank),
    ).fetchall()

    brawler_index: dict[int, int] = {}
    brawler_ids: list[int] = []
    brawler_names: list[str] = []
    map_index: dict[tuple[str, str], int] = {}
    mode_index: dict[str, int] = {}
    ids, times, teams, maps, modes, ys, lobby = [], [], [], [], [], [], []

    i = 0
    while i < len(rows):
        group = rows[i:i + 6]
        i += 6
        if len(group) < 6 or len({r["battle_id"] for r in group}) != 1 or any(r["brawler_id"] is None for r in group):
            # Shouldn't happen (insert_battle writes six rows); resync on the next battle_id.
            while i < len(rows) and rows[i]["battle_id"] == group[-1]["battle_id"]:
                i += 1
            continue
        first = group[0]
        t = np.empty((2, 3), dtype=np.int32)
        for r in group:
            bid = r["brawler_id"]
            if bid not in brawler_index:
                brawler_index[bid] = len(brawler_ids)
                brawler_ids.append(bid)
                brawler_names.append(r["brawler_name"])
            t[r["team"], r["slot"]] = brawler_index[bid]
        key = (first["mode"], first["map"])
        map_index.setdefault(key, len(map_index))
        mode_index.setdefault(first["mode"], len(mode_index))
        ids.append(first["battle_id"])
        times.append(first["battle_time"])
        teams.append(t)
        maps.append(map_index[key])
        modes.append(mode_index[first["mode"]])
        ys.append(1.0 if first["winning_team"] == 0 else 0.0)
        lobby.append(MASTERS if first["lobby_rank"] is None else first["lobby_rank"])

    return Matches(
        ids, times,
        np.array(teams, dtype=np.int32).reshape(-1, 2, 3),
        np.array(maps, dtype=np.int32), np.array(modes, dtype=np.int32), np.array(ys),
        brawler_ids, brawler_names,
        sorted(map_index, key=map_index.get), sorted(mode_index, key=mode_index.get),
        np.array(lobby, dtype=np.int32),
    )
