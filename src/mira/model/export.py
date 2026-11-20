"""Write the trained win model to model.json for the website (spec §4.5)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .dataset import DEFAULT_RANK_FACTOR, Matches
from .winmodel import WinModel

FORMAT_VERSION = 1


def _r(x: float) -> float:
    return round(float(x), 4)


def to_dict(model: WinModel, m: Matches, games: dict, extra: dict | None = None, threshold: float = 1e-4) -> dict:
    t = model.tables()
    B = m.n_brawlers

    def sparse_pairs(arr: np.ndarray) -> list:
        """Upper-triangle (i < j) entries above threshold: [i, j, value] or [i, j, mode, value]."""
        i, j = np.triu_indices(B, k=1)
        vals = arr[i, j]
        if vals.ndim == 1:
            keep = np.abs(vals) > threshold
            return [[int(a), int(b), _r(v)] for a, b, v in zip(i[keep], j[keep], vals[keep])]
        out = []
        for k in range(vals.shape[1]):
            keep = np.abs(vals[:, k]) > threshold
            out += [[int(a), int(b), k, _r(v)] for a, b, v in zip(i[keep], j[keep], vals[keep, k])]
        return out

    return {
        "format": FORMAT_VERSION,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_window": [m.times[0], m.times[-1]],
        "n_matches": len(m),
        "brawlers": [{"id": bid, "name": name} for bid, name in zip(m.brawler_ids, m.brawler_names)],
        "modes": m.modes,
        "maps": [{"mode": mode, "map": name} for mode, name in m.maps],
        "win_model": {
            "doc": "logit(team A wins) = sum_A s - sum_B s + syn(A) - syn(B) + sum_{a in A, b in B} mu(a,b); "
                   "s[b] = global[b] + mode[b][mode] + map[b][map]; syn(T) = sum over pairs {i<j} in T of "
                   "synergy[i,j] + synergy_mode[i,j,mode]; with lo=min(a,b), hi=max(a,b): "
                   "M = matchup[lo,hi] + matchup_mode[lo,hi,mode], mu(a,b) = +M if a<b else -M. "
                   "Pair lists are sparse [i, j, (mode,) value]; missing entries are 0.",
            "l2": model.l2,
            "global": [_r(v) for v in t["global"]],
            "mode": [[_r(v) for v in row] for row in t["mode"]],
            "map": [[_r(v) for v in row] for row in t["map"]],
            "synergy": sparse_pairs(t["synergy"]),
            "synergy_mode": sparse_pairs(t["synergy_mode"]),
            "matchup": sparse_pairs(t["matchup"]),
            "matchup_mode": sparse_pairs(t["matchup_mode"]),
        },
        "games": games,
        **(extra or {}),
    }


def pick_model_dict(pm, threshold: float = 0.01) -> dict:
    B = pm.log_base.shape[0]
    i, j = np.triu_indices(B, k=1)

    def sparse(arr):
        v = arr[i, j]
        keep = np.abs(v) > threshold
        return [[int(a), int(b), round(float(x), 3)] for a, b, x in zip(i[keep], j[keep], v[keep])]

    return {
        "doc": "score(b) = log_base[b][map] + alpha*sum_allies lift + beta*sum_enemies lift; softmax over "
               "available brawlers. Lifts are symmetric, sparse [i, j, value] with i<j; missing = 0.",
        "alpha": pm.alpha, "beta": pm.beta,
        "log_base": [[round(float(x), 3) for x in row] for row in pm.log_base],
        "ally_lift": sparse(pm.ally_lift),
        "enemy_lift": sparse(pm.enemy_lift),
    }


def game_counts(m: Matches, rank_factor: float = DEFAULT_RANK_FACTOR) -> dict:
    """Sample sizes the UI uses for confidence badges: games per brawler overall and per map,
    in all-Masters equivalents (a lower lobby counts as its rank weight)."""
    B, nmap = m.n_brawlers, len(m.maps)
    per_map = np.zeros((B, nmap))
    for teams, mp, w in zip(m.teams, m.map_idx, m.rank_weights(rank_factor)):
        for b in teams.ravel():
            per_map[b, mp] += w
    per_map = np.rint(per_map).astype(int)
    return {"brawler": per_map.sum(1).tolist(), "brawler_map": per_map.tolist()}


def write(path: str | Path, data: dict) -> int:
    text = json.dumps(data, separators=(",", ":"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")
    return len(text)
