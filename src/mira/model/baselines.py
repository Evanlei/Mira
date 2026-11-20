"""Baselines the win model must beat (spec §8).

1. coin:      always 50%.
2. map_wr:    sum of each brawler's smoothed win rate on the map (as logits), team 0 minus team 1,
              scaled by one fitted coefficient.
3. deepdraft: a rebuild of DeepDraft's published scoring: base (win rate + usage on the map)
              + synergy with allies ± counters vs enemies − role conflict. Its weights aren't
              published, so we fit them on the training data (the most favourable reading).

All statistics are computed from the training matches only. The weights are fitted
on out-of-fold features (statistics from the other folds), otherwise a match's own result
leaks into its features and the fitted weights come out overconfident.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .dataset import Matches


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1e-3, iters: int = 50) -> np.ndarray:
    """Newton's method, no intercept (features are antisymmetric in the teams)."""
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + l2 * w
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


class Coin:
    name = "coin (50%)"

    def fit(self, m: Matches) -> "Coin":
        return self

    def predict(self, m: Matches) -> np.ndarray:
        return np.full(len(m), 0.5)


@dataclass
class _Counts:
    """Win/game counts per brawler (global, per map), per pair on a team and per matchup (per mode)."""

    k_map: float = 30.0   # pseudo-games pulling map win rate toward the brawler's global rate
    k_pair: float = 20.0  # pseudo-games pulling pair stats toward "no effect"

    def fit(self, m: Matches) -> "_Counts":
        B, nm, nmap = m.n_brawlers, len(m.modes), len(m.maps)
        self.g_games = np.zeros(B); self.g_wins = np.zeros(B)
        self.m_games = np.zeros((B, nmap)); self.m_wins = np.zeros((B, nmap))
        self.map_teams = np.zeros(nmap)
        self.s_games = np.zeros((B, B, nm)); self.s_wins = np.zeros((B, B, nm))
        self.c_games = np.zeros((B, B, nm)); self.c_wins = np.zeros((B, B, nm))
        self.mode_teams = np.zeros(nm); self.mode_pick = np.zeros((B, nm))
        for teams, mp, md, y in zip(m.teams, m.map_idx, m.mode_idx, m.y):
            won = (y, 1 - y)
            self.map_teams[mp] += 2
            self.mode_teams[md] += 2
            for t in range(2):
                for b in teams[t]:
                    self.g_games[b] += 1; self.g_wins[b] += won[t]
                    self.m_games[b, mp] += 1; self.m_wins[b, mp] += won[t]
                    self.mode_pick[b, md] += 1
                for a, b in combinations(teams[t], 2):
                    for i, j in ((a, b), (b, a)):
                        self.s_games[i, j, md] += 1; self.s_wins[i, j, md] += won[t]
            for a in teams[0]:
                for b in teams[1]:
                    self.c_games[a, b, md] += 1; self.c_wins[a, b, md] += y
                    self.c_games[b, a, md] += 1; self.c_wins[b, a, md] += 1 - y
        # Smoothed rates.
        self.g_rate = (self.g_wins + 0.5 * 50) / (self.g_games + 50)
        self.m_rate = (self.m_wins + self.k_map * self.g_rate[:, None]) / (self.m_games + self.k_map)
        self.m_usage = (self.m_games + 1) / (self.map_teams[None, :] * 3 + B)
        g_logit = _logit(self.g_rate)
        exp_pair = (g_logit[:, None] + g_logit[None, :]) / 2
        pair_rate = (self.s_wins + self.k_pair * 0.5) / (self.s_games + self.k_pair)
        self.synergy = np.where(self.s_games > 0, _logit(pair_rate) - exp_pair[:, :, None] * (self.s_games / (self.s_games + self.k_pair)), 0.0)
        exp_c = (g_logit[:, None] - g_logit[None, :])
        c_rate = (self.c_wins + self.k_pair * 0.5) / (self.c_games + self.k_pair)
        self.counter = np.where(self.c_games > 0, _logit(c_rate) - exp_c[:, :, None] * (self.c_games / (self.c_games + self.k_pair)), 0.0)
        # Role conflict: pairs seen together on a team much less than their pick rates predict.
        p = self.mode_pick / np.maximum(self.mode_teams, 1)[None, :]  # per-team pick prob
        expected = self.mode_teams[None, None, :] * p[:, None, :] * p[None, :, :]
        self.conflict = np.minimum(0.0, np.log((self.s_games + 1) / (expected + 1)))
        return self


class _CrossFitted:
    """Stats from all training data for prediction; weights from K-fold out-of-fold features."""

    folds = 5

    def fit(self, m: Matches):
        oof = np.zeros((len(m), self.n_features))
        fold = np.arange(len(m)) % self.folds
        for k in range(self.folds):
            stats = _Counts().fit(m.subset(fold != k))
            oof[fold == k] = self._features(stats, m.subset(fold == k))
        self.w = _fit_logistic(oof, m.y)
        self.c = _Counts().fit(m)
        return self

    def predict(self, m: Matches) -> np.ndarray:
        return 1 / (1 + np.exp(-self._features(self.c, m) @ self.w))


class MapWinRate(_CrossFitted):
    name = "map win rates"
    n_features = 1

    @staticmethod
    def _features(c: _Counts, m: Matches) -> np.ndarray:
        s = _logit(c.m_rate)[m.teams, m.map_idx[:, None, None]]  # (n, 2, 3)
        return (s[:, 0].sum(1) - s[:, 1].sum(1))[:, None]


class DeepDraftStyle(_CrossFitted):
    name = "DeepDraft-style additive"
    n_features = 5

    @staticmethod
    def _features(c: _Counts, m: Matches) -> np.ndarray:
        mp = m.map_idx[:, None, None]
        base_wr = _logit(c.m_rate)[m.teams, mp]
        base_use = np.log(c.m_usage)[m.teams, mp]
        md = m.mode_idx
        syn = np.zeros((len(m), 2)); conf = np.zeros((len(m), 2)); ctr = np.zeros(len(m))
        for a, b in combinations(range(3), 2):
            for t in range(2):
                i, j = m.teams[:, t, a], m.teams[:, t, b]
                syn[:, t] += c.synergy[i, j, md]
                conf[:, t] += c.conflict[i, j, md]
        for a in range(3):
            for b in range(3):
                ctr += c.counter[m.teams[:, 0, a], m.teams[:, 1, b], md]
        return np.column_stack([
            base_wr[:, 0].sum(1) - base_wr[:, 1].sum(1),
            base_use[:, 0].sum(1) - base_use[:, 1].sum(1),
            syn[:, 0] - syn[:, 1],
            ctr,
            conf[:, 0] - conf[:, 1],
        ])
