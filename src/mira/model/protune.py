"""Tune how our picks are ranked (kappa, gamma, rho) and how bans use pro rates (ban_lambda).

Picks: a setting must keep the real held-out win rate of the Masters picks we'd rank best within
one standard error of the best setting (evaluate.ranking_report, measured on game results). That
objective alone is biased toward rare brawlers (they're mostly played by their mains and by
counter-pickers, so their games flatter them), so among the settings that pass, we take the one
that agrees most with pro drafts: where it ranks each pro pick, with the other five known, on pro
maps newer than any pro data used to build the rates (a time split).

Bans: Ranked has no ban data, so the only check is agreement with pro bans on those newer maps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import proeval
from .dataset import Matches
from .evaluate import RankingRow, _dense_pairs, strength_table

RHO_GRID = (0.0, 0.05, 0.1, 0.2, 0.3)
BAN_LAMBDA_GRID = (0.0, 0.01, 0.02, 0.05, 0.1, 0.2)
PRO_TEST_DAYS = 60
PRO_TIER = 3  # pros are scored with the top rank tier's tables
PICK_K = 5
BAN_K = 6


def pro_split(rows, test_days: int = PRO_TEST_DAYS) -> tuple[str, list, list]:
    """(cutoff date, rows before it, rows from it on): the newest ``test_days`` days are the test."""
    from datetime import date, timedelta

    dated = [r for r in rows if r["played_on"]]
    if not dated:
        return "", [], []
    newest = max(date.fromisoformat(r["played_on"]) for r in dated)
    cutoff = (newest - timedelta(days=test_days)).isoformat()
    return cutoff, [r for r in dated if r["played_on"] < cutoff], [r for r in dated if r["played_on"] >= cutoff]


@dataclass
class _Names:
    names: list[str]
    maps: list[tuple[str, str]]


def pro_matches(m: Matches, rows) -> list[proeval.ProMatch]:
    return proeval.resolve(_Names(m.brawler_names, m.maps), rows)[0]


def pick_agreement(model, log_base_tier: np.ndarray, sd: np.ndarray, pro_log: np.ndarray, m: Matches,
                   matches: list[proeval.ProMatch], settings: list[tuple[float, float, float]],
                   k: int = PICK_K, tier: int = PRO_TIER) -> dict[tuple[float, float, float], float]:
    """Share of held-out pro picks (other five known, bans excluded) in our top ``k``, per
    (kappa, gamma, rho)."""
    if not matches:
        return {s: float("nan") for s in settings}
    mode_of_map = np.array([m.modes.index(mode) for mode, _ in m.maps])
    S = strength_table(model, mode_of_map)[tier]          # (B, n_maps)
    syn, mu = _dense_pairs(model)
    B = S.shape[0]
    tgt, mps, base, blocked = [], [], [], []
    for pm in matches:
        banned = set(pm.bans[0]) | set(pm.bans[1])
        md = mode_of_map[pm.map_idx]
        for t in (0, 1):
            mine, theirs = pm.teams[t], pm.teams[1 - t]
            for i, target in enumerate(mine):
                allies = mine[:i] + mine[i + 1:]
                g = S[:, pm.map_idx].copy()
                for a in allies:
                    g += syn[:, a, md]
                for e in theirs:
                    g += mu[:, e, md]
                blk = np.zeros(B, dtype=bool)
                blk[list(set(allies) | set(theirs) | (banned - {target}))] = True
                tgt.append(target); mps.append(pm.map_idx); base.append(g); blocked.append(blk)
    tgt, mps = np.array(tgt), np.array(mps)
    base, blocked = np.array(base), np.array(blocked)
    unc, lb, pl = sd[tier][:, mps].T, log_base_tier[tier][:, mps].T, pro_log[:, mps].T
    rows_n = np.arange(len(tgt))
    out = {}
    for kappa, gamma, rho in settings:
        score = base - kappa * unc + gamma * lb + rho * pl
        score[blocked] = -np.inf
        rank = (score > score[rows_n, tgt][:, None]).sum(axis=1)
        out[(kappa, gamma, rho)] = float((rank < k).mean())
    return out


def choose(rows: list[RankingRow], agreement: dict) -> RankingRow:
    """Among settings whose Masters picks win within one standard error of the best at every
    coverage, the one that agrees most with pros (ties: least reliance on rare brawlers)."""
    n_cov = len(rows[0].realized)
    best = [max(rows, key=lambda r: r.realized[c]) for c in range(n_cov)]
    ok = [r for r in rows if all(r.realized[c] >= best[c].realized[c] - best[c].se(c) for c in range(n_cov))]
    mid = n_cov // 2

    def key(r):
        a = agreement.get((r.kappa, r.gamma, r.rho), float("nan"))
        return (-(a if a == a else 0.0), round(r.rare[mid], 3), r.kappa + 10 * r.gamma + 10 * r.rho)
    return min(ok, key=key)


def ban_agreement(engine, matches: list[proeval.ProMatch], lambdas=BAN_LAMBDA_GRID, k: int = BAN_K,
                  max_maps: int = 40, log=lambda s: None) -> dict[float, float]:
    """Share of pro bans in our top ``k`` bans, per ban_lambda. ``engine`` is an engine Model with
    the pro block; the search runs once per map and the lambdas only re-rank its candidates."""
    from collections import defaultdict

    from ..engine.search import suggest_bans

    by_map = defaultdict(list)
    for pm in matches:
        if pm.bans[0] or pm.bans[1]:
            by_map[pm.map_idx].append(pm)
    maps = sorted(by_map, key=lambda mp: -len(by_map[mp]))[:max_maps]
    saved = engine.ban_lambda
    engine.ban_lambda = 1.0  # any value > 0: adds the pro favourites to the candidates
    hits = {lam: 0 for lam in lambdas}
    total = 0
    try:
        for i, mp in enumerate(maps):
            log(f"  bans {i + 1}/{len(maps)}")
            cands = suggest_bans(engine, mp, True, set(), n=100)
            for pm in by_map[mp]:
                want = set(pm.bans[0]) | set(pm.bans[1])
                total += len(want)
                for lam in lambdas:
                    ranked = sorted(cands, key=lambda x: x[2] + lam * engine.pro_ban_rate(x[0], mp), reverse=True)
                    hits[lam] += len({b for b, _, _ in ranked[:k]} & want)
    finally:
        engine.ban_lambda = saved
    return {lam: hits[lam] / max(total, 1) for lam in lambdas}


def choose_ban_lambda(agreement: dict[float, float]) -> float:
    """The smallest lambda within one point of the best agreement."""
    best = max(agreement.values())
    return min(lam for lam, a in agreement.items() if a >= best - 0.01)
