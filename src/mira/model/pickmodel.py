"""Pick model (spec §4.2): how likely a typical Masters player is to pick brawler b, given the
map, their allies, the enemies and what's unavailable. Learned from final teams only, so it
can't tell early picks from late ones.

score(b) = log p(b | map, tier)                 base pick rate, smoothed tier → map → mode → global
         + alpha * Σ_allies  log ally_lift(b, a)   b shows up with a on the same team
         + beta  * Σ_enemies log enemy_lift(b, e)  b shows up against e
P(b) = softmax(score) over available brawlers.

The lifts are naive-Bayes style and over-count when several allies are known, so alpha and beta
(< 1) are fitted on held-out data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dataset import DEFAULT_TIER, TIERS, Matches


@dataclass
class PickModel:
    log_base: np.ndarray    # (B, n_maps) log p(b | map)
    ally_lift: np.ndarray   # (B, B) log lift, symmetric, diagonal 0
    enemy_lift: np.ndarray  # (B, B) log lift of b given enemy e
    alpha: float = 1.0
    beta: float = 1.0
    log_base_tier: np.ndarray | None = None  # (n_tiers, B, n_maps) log p(b | map, tier)

    @classmethod
    def fit(cls, m: Matches, weights: np.ndarray | None = None, k_map: float = 50.0, k_mode: float = 200.0,
            k_lift: float = 30.0, k_tier: float = 100.0) -> "PickModel":
        B, nmap, nmode = m.n_brawlers, len(m.maps), len(m.modes)
        w = np.ones(len(m)) if weights is None else np.asarray(weights, dtype=np.float64)
        map_mode = np.zeros(nmap, dtype=int)
        for mp, md in zip(m.map_idx, m.mode_idx):
            map_mode[mp] = md

        c_map = np.zeros((B, nmap)); t_map = np.zeros(nmap)
        co_ally = np.zeros((B, B)); co_enemy = np.zeros((B, B)); c = np.zeros(B)
        for teams, mp, wi in zip(m.teams, m.map_idx, w):
            t_map[mp] += 2 * wi
            for t in range(2):
                mine, theirs = teams[t], teams[1 - t]
                c_map[mine, mp] += wi
                c[mine] += wi
                for a in mine:
                    for b in mine:
                        if a != b:
                            co_ally[a, b] += wi
                    for e in theirs:
                        co_enemy[a, e] += wi
        n_teams = t_map.sum()

        # Base pick rate: share of team slots, smoothed map -> mode -> global.
        p_glob = (c + 1.0) / (3 * n_teams + B)
        c_mode = np.zeros((B, nmode)); t_mode = np.zeros(nmode)
        for mp in range(nmap):
            c_mode[:, map_mode[mp]] += c_map[:, mp]
            t_mode[map_mode[mp]] += t_map[mp]
        p_mode = (c_mode + k_mode * p_glob[:, None]) / (3 * t_mode[None, :] + k_mode)
        p_map = (c_map + k_map * p_mode[:, map_mode]) / (3 * t_map[None, :] + k_map)
        log_base = np.log(p_map / p_map.sum(axis=0, keepdims=True))

        # Per rank tier: the tier's own pick rates on each map, shrunk toward the map's overall rates,
        # so a thin tier (Masters III+) stays close to everyone else until its games say otherwise.
        T = len(TIERS)
        tiers = m.tier_idx()
        c_tier = np.zeros((T, B, nmap)); t_tier = np.zeros((T, nmap))
        for teams, mp, wi, ti in zip(m.teams, m.map_idx, w, tiers):
            t_tier[ti, mp] += 2 * wi
            for t in range(2):
                c_tier[ti, teams[t], mp] += wi
        p_tier = (c_tier + k_tier * p_map[None]) / (3 * t_tier[:, None, :] + k_tier)
        log_base_tier = np.log(p_tier / p_tier.sum(axis=1, keepdims=True))

        # Lifts: observed co-occurrence vs what pick rates alone predict, shrunk toward 1.
        def lift(co, per_team_b, per_team_a):
            expected = per_team_b[:, None] * per_team_a[None, :] * n_teams
            return np.log((co + k_lift) / (expected + k_lift))

        p_team = c / max(n_teams, 1)  # P(b on a given team)
        ally = lift(co_ally, p_team, p_team)
        np.fill_diagonal(ally, 0.0)
        enemy = lift(co_enemy, p_team, p_team)
        return cls(log_base, ally, enemy, log_base_tier=log_base_tier)

    def scores(self, map_idx: int, allies, enemies, unavailable, tier: int | None = None) -> np.ndarray:
        base = self.log_base if tier is None or self.log_base_tier is None else self.log_base_tier[tier]
        s = base[:, map_idx].copy()
        for a in allies:
            s += self.alpha * self.ally_lift[:, a]
        for e in enemies:
            s += self.beta * self.enemy_lift[:, e]
        s[list(unavailable)] = -np.inf
        return s

    def probs(self, map_idx: int, allies, enemies, unavailable, tier: int | None = None) -> np.ndarray:
        s = self.scores(map_idx, allies, enemies, unavailable, tier)
        s -= s[np.isfinite(s)].max()
        p = np.exp(s)
        return p / p.sum()


def holdout_examples(m: Matches):
    """Each brawler of each team, predicted from its 2 allies and 3 enemies (others unavailable)."""
    for teams, mp in zip(m.teams, m.map_idx):
        for t in range(2):
            mine, theirs = list(teams[t]), list(teams[1 - t])
            for i, target in enumerate(mine):
                allies = mine[:i] + mine[i + 1:]
                yield mp, allies, theirs, target


def evaluate(model: PickModel, m: Matches, tier: int | None = None) -> dict:
    """Mean log-likelihood and top-k accuracy of the held-out brawler (pick rates of ``tier``, or overall)."""
    ll, top1, top5, top10, n = 0.0, 0, 0, 0, 0
    for mp, allies, enemies, target in holdout_examples(m):
        p = model.probs(mp, allies, enemies, set(allies) | set(enemies), tier)
        ll += np.log(max(p[target], 1e-12))
        rank = (p > p[target]).sum()
        top1 += rank < 1; top5 += rank < 5; top10 += rank < 10
        n += 1
    return {"log_lik": ll / n, "top1": top1 / n, "top5": top5 / n, "top10": top10 / n, "n": n}


def tune(model: PickModel, val: Matches, grid=(0.0, 0.25, 0.5, 0.75, 1.0)) -> PickModel:
    """Pick alpha/beta by validation log-likelihood (coordinate-wise, two passes)."""
    best = (model.alpha, model.beta)
    for _ in range(2):
        for which in ("alpha", "beta"):
            results = []
            for v in grid:
                a, b = (v, best[1]) if which == "alpha" else (best[0], v)
                model.alpha, model.beta = a, b
                results.append((evaluate(model, val)["log_lik"], a, b))
            _, *best = max(results)
    model.alpha, model.beta = best
    return model
