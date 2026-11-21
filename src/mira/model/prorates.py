"""Pro pick and ban rates per map, from the Liquipedia drafts `mira pro-sync` stores.

A map sees about 60 pro sets in half a year, too few to use raw, so each rate is shrunk toward
a broader one:

    pick:  pro rate on the map  <-  pro rate in the mode, tilted by how Masters players' rates on
                                     this map differ from the mode  <-  Masters rate in the mode
    ban:   pro ban rate on the map  <-  pro ban rate in the mode  <-  pro ban rate overall

Ranked has no ban data at all (the API doesn't report bans), so ban rates fall back to pros only.
Maps are weighted by recency (half-life ``half_life`` days) over the last ``days`` days.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .. import pro

# Pro bans go stale fast: rates from the 30-60 days before a pro test window put about 41% of the
# test's bans in the top 6, rates from 90+ days back about 29% (no better than the Ranked pick
# rate), because balance changes keep moving the meta. So: a short, steeply weighted window.
PRO_DAYS = 60
HALF_LIFE = 15.0
K_MODE = 5.0  # pseudo pro maps behind each mode rate
K_MAP = 5.0   # pseudo pro maps behind each map rate


@dataclass
class ProRates:
    pick: np.ndarray    # (B, n_maps) share of pro team slots; each column sums to 1
    ban: np.ndarray     # (B, n_maps) share of pro maps where the brawler was banned (by either team)
    n_map: np.ndarray   # (n_maps,) weighted pro maps behind each map's own rate
    n_total: float      # weighted pro maps used
    since: str
    until: str

    @property
    def log_pick(self) -> np.ndarray:
        return np.log(self.pick)


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def compute(rows, brawler_names: list[str], maps: list[tuple[str, str]], modes: list[str],
            masters_pick: np.ndarray, until: str | None = None, days: int = PRO_DAYS,
            half_life: float = HALF_LIFE, k_mode: float = K_MODE, k_map: float = K_MAP) -> ProRates:
    """``rows``: pro_maps rows. ``masters_pick``: (B, n_maps) Masters pick shares (columns sum to 1).
    Uses maps played in [until - days, until); ``until`` defaults to the newest row + 1 day."""
    B, nmap, nmode = len(brawler_names), len(maps), len(modes)
    by_name = {pro.norm(n): i for i, n in enumerate(brawler_names)}
    for alias, target in pro.BRAWLER_ALIASES.items():
        if target in by_name:
            by_name.setdefault(alias, by_name[target])
    map_idx = {pro.norm(name): j for j, (_, name) in enumerate(maps)}
    mode_idx = {pro.norm(md): k for k, md in enumerate(modes)}
    mode_of_map = np.array([mode_idx[pro.norm(md)] for md, _ in maps], dtype=int)

    dated = [r for r in rows if r["played_on"]]
    end = _day(until) if until else (max((_day(r["played_on"]) for r in dated), default=date.today()) + timedelta(days=1))
    start = end - timedelta(days=days)

    c_map = np.zeros((B, nmap)); n_map = np.zeros(nmap)
    c_mode = np.zeros((B, nmode)); n_mode = np.zeros(nmode)
    bn_map = np.zeros((B, nmap)); bn_mode = np.zeros((B, nmode)); bn_all = np.zeros(B)
    n_total = 0.0
    for r in dated:
        d = _day(r["played_on"])
        if not (start <= d < end):
            continue
        k = mode_idx.get(pro.norm(r["mode"] or ""))
        if k is None:
            continue
        picks = [by_name.get(pro.norm(x)) for x in json.loads(r["picks1"]) + json.loads(r["picks2"])]
        bans = {by_name.get(pro.norm(x)) for x in json.loads(r["bans1"]) + json.loads(r["bans2"])} - {None}
        if None in picks:
            continue
        w = 0.5 ** ((end - d).days / half_life)
        j = map_idx.get(pro.norm(r["map"] or ""))
        if j is not None and mode_of_map[j] != k:
            j = None  # same map name in another mode
        n_total += w
        n_mode[k] += w
        for b in picks:
            c_mode[b, k] += w
        for b in bans:
            bn_mode[b, k] += w; bn_all[b] += w
        if j is not None:
            n_map[j] += w
            for b in picks:
                c_map[b, j] += w
            for b in bans:
                bn_map[b, j] += w

    # Picks. Masters' mode rate is the mean of its map rates in the mode.
    q_mode = np.zeros((B, nmode))
    for k in range(nmode):
        cols = mode_of_map == k
        q_mode[:, k] = masters_pick[:, cols].mean(axis=1) if cols.any() else 1.0 / B
    p_mode = (c_mode + 6 * k_mode * q_mode) / (6 * n_mode + 6 * k_mode)[None, :]
    prior = p_mode[:, mode_of_map] * masters_pick / np.maximum(q_mode[:, mode_of_map], 1e-12)
    prior /= prior.sum(axis=0, keepdims=True)
    pick = (c_map + 6 * k_map * prior) / (6 * n_map + 6 * k_map)[None, :]
    pick = np.maximum(pick, 1e-6)
    pick /= pick.sum(axis=0, keepdims=True)

    # Bans.
    g = (bn_all + 1.0) / (n_total + B)  # overall pro ban rate, add-one
    b_mode = (bn_mode + k_mode * g[:, None]) / (n_mode + k_mode)[None, :]
    ban = (bn_map + k_map * b_mode[:, mode_of_map]) / (n_map + k_map)[None, :]
    return ProRates(pick, ban, n_map, n_total, start.isoformat(), end.isoformat())


def to_dict(r: ProRates) -> dict:
    return {
        "doc": "Pro esports drafts (Liquipedia, CC-BY-SA) from `since` to `until`, recency weighted. "
               "log_pick[b][map]: log share of pro team slots; ban[b][map]: share of pro maps where b "
               "was banned. Both shrunk toward the mode's pro rate, then Masters (picks) or all pro "
               "maps (bans). n_map: weighted pro maps behind each map's own rate.",
        "since": r.since, "until": r.until, "n_maps": round(r.n_total, 1),
        "n_map": [round(float(x), 1) for x in r.n_map],
        "log_pick": [[round(float(x), 3) for x in row] for row in np.log(r.pick)],
        "ban": [[round(float(x), 4) for x in row] for row in r.ban],
    }
