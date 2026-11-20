"""Win model (spec §4.1): P(team 0 wins | map, team 0, team 1).

logit = Σ_team0 strength − Σ_team1 strength + same-team synergy pairs (team0 − team1)
        + cross-team matchups (team0 vs team1)

strength[b] on a map = global[b] + per-mode[b, mode] + per-map[b, map], each block with
its own L2 penalty, which gives map → mode → global shrinkage: a per-map term only grows
when that map has the games to support it. Synergy and matchup work the same way: a pair term
shared by all modes plus a per-mode adjustment (synergy_mode / matchup_mode). There is no
intercept, so swapping the teams exactly flips the prediction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from .dataset import Matches

BLOCKS = ("global", "mode", "map", "synergy", "synergy_mode", "matchup", "matchup_mode")
# Penalties are in pseudo-games. Defaults = what tuning picked on ~12k real matches; weaker
# settings overfit pure noise (see tests/test_model.py).
DEFAULT_L2 = {"global": 3.0, "mode": 30.0, "map": 100.0,
              "synergy": 300.0, "synergy_mode": 1000.0, "matchup": 300.0, "matchup_mode": 1000.0}

_PAIRS_IN_TEAM = list(combinations(range(3), 2))  # 3 pairs


def _pair_index(i: np.ndarray, j: np.ndarray, n: int) -> np.ndarray:
    """Index of unordered pair (min, max) in an n×n upper triangle (flattened n*n grid)."""
    lo, hi = np.minimum(i, j), np.maximum(i, j)
    return lo * n + hi


@dataclass
class Layout:
    n_brawlers: int
    n_modes: int
    n_maps: int
    offsets: dict[str, int] = field(default_factory=dict)
    sizes: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        B = self.n_brawlers
        self.sizes = {
            "global": B,
            "mode": B * self.n_modes,
            "map": B * self.n_maps,
            "synergy": B * B,
            "synergy_mode": B * B * self.n_modes,
            "matchup": B * B,
            "matchup_mode": B * B * self.n_modes,
        }
        off = 0
        for k in BLOCKS:
            self.offsets[k] = off
            off += self.sizes[k]

    @property
    def n_params(self) -> int:
        return sum(self.sizes.values())

    def block(self, w: np.ndarray, name: str) -> np.ndarray:
        return w[self.offsets[name]:self.offsets[name] + self.sizes[name]]


def features(m: Matches, layout: Layout) -> tuple[np.ndarray, np.ndarray]:
    """Sparse design as (idx, sign), each (n, 48): logit_i = Σ_k w[idx[i,k]] * sign[i,k]."""
    B, nm, nmap = layout.n_brawlers, layout.n_modes, layout.n_maps
    o = layout.offsets
    t0, t1 = m.teams[:, 0, :], m.teams[:, 1, :]
    mode, mp = m.mode_idx[:, None], m.map_idx[:, None]
    n = len(m)
    cols_i, cols_s = [], []

    def add(idx, sign):
        cols_i.append(idx)
        cols_s.append(np.broadcast_to(sign, idx.shape).astype(np.float64))

    for team, sign in ((t0, 1.0), (t1, -1.0)):
        add(o["global"] + team, sign)
        add(o["mode"] + team * nm + mode, sign)
        add(o["map"] + team * nmap + mp, sign)
        for a, b in _PAIRS_IN_TEAM:
            pi = _pair_index(team[:, a], team[:, b], B)[:, None]
            # Same brawler twice on a team can't happen in Ranked; guard anyway.
            same = (team[:, a] == team[:, b])[:, None]
            sg = np.where(same, 0.0, sign)
            add(o["synergy"] + pi, sg)
            add(o["synergy_mode"] + pi * nm + mode, sg)

    for a in range(3):
        for b in range(3):
            x, y = t0[:, a], t1[:, b]
            pi = _pair_index(x, y, B)[:, None]
            # matchup[lo, hi] = edge of lo over hi; flip the sign when team 0 holds hi.
            sign = np.where(x < y, 1.0, -1.0)[:, None]
            sign = np.where((x == y)[:, None], 0.0, sign)  # mirror matchup: no information
            add(o["matchup"] + pi, sign)
            add(o["matchup_mode"] + pi * nm + mode, sign)

    idx = np.concatenate(cols_i, axis=1)
    sgn = np.concatenate(cols_s, axis=1)
    assert idx.shape == (n, 48)
    return idx, sgn


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * z))


def _lbfgs(fg, x0: np.ndarray, max_iter: int = 300, m: int = 10, tol: float = 1e-6) -> np.ndarray:
    """Minimal L-BFGS with backtracking (Armijo) line search; fine for this convex problem."""
    x = x0.copy()
    f, g = fg(x)
    s_hist: list[np.ndarray] = []
    y_hist: list[np.ndarray] = []
    for _ in range(max_iter):
        q = g.copy()
        alphas = []
        for s, y in zip(reversed(s_hist), reversed(y_hist)):
            a = s.dot(q) / y.dot(s)
            alphas.append(a)
            q -= a * y
        if s_hist:
            q *= s_hist[-1].dot(y_hist[-1]) / y_hist[-1].dot(y_hist[-1])
        for (s, y), a in zip(zip(s_hist, y_hist), reversed(alphas)):
            q += s * (a - y.dot(q) / y.dot(s))
        d = -q
        gd = g.dot(d)
        if gd >= 0:  # not a descent direction: reset to steepest descent
            s_hist.clear(); y_hist.clear()
            d, gd = -g, -g.dot(g)
        step = 1.0
        while True:
            x_new = x + step * d
            f_new, g_new = fg(x_new)
            if f_new <= f + 1e-4 * step * gd or step < 1e-10:
                break
            step *= 0.5
        s, y = x_new - x, g_new - g
        if s.dot(y) > 1e-12:
            s_hist.append(s); y_hist.append(y)
            if len(s_hist) > m:
                s_hist.pop(0); y_hist.pop(0)
        converged = abs(f - f_new) <= tol * max(1.0, abs(f))
        x, f, g = x_new, f_new, g_new
        if converged or np.sqrt(g.dot(g)) < 1e-8:
            break
    return x


@dataclass
class WinModel:
    layout: Layout
    w: np.ndarray
    l2: dict[str, float]

    @classmethod
    def fit(
        cls,
        m: Matches,
        weights: np.ndarray | None = None,
        l2: dict[str, float] | None = None,
        n_maps: int | None = None,
        n_modes: int | None = None,
        max_iter: int = 300,
    ) -> "WinModel":
        l2 = {**DEFAULT_L2, **(l2 or {})}
        layout = Layout(m.n_brawlers, n_modes or len(m.modes), n_maps or len(m.maps))
        idx, sgn = features(m, layout)
        y = m.y
        sw = np.ones(len(m)) if weights is None else np.asarray(weights, dtype=np.float64)
        flat_idx = idx.ravel()
        lam = np.concatenate([np.full(layout.sizes[k], l2[k]) for k in BLOCKS])

        def fg(w):
            z = (w[idx] * sgn).sum(axis=1)
            p = _sigmoid(z)
            eps = 1e-12
            loss = -(sw * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))).sum()
            r = sw * (p - y)
            grad = np.bincount(flat_idx, weights=(sgn * r[:, None]).ravel(), minlength=layout.n_params)
            return loss + (lam * w * w).sum(), grad + 2 * lam * w

        w = _lbfgs(fg, np.zeros(layout.n_params), max_iter=max_iter)
        return cls(layout, w, l2)

    def predict(self, m: Matches) -> np.ndarray:
        idx, sgn = features(m, self.layout)
        return _sigmoid((self.w[idx] * sgn).sum(axis=1))

    # -- export -------------------------------------------------------------

    def tables(self) -> dict[str, np.ndarray]:
        B, nm, nmap = self.layout.n_brawlers, self.layout.n_modes, self.layout.n_maps
        return {
            "global": self.layout.block(self.w, "global"),
            "mode": self.layout.block(self.w, "mode").reshape(B, nm),
            "map": self.layout.block(self.w, "map").reshape(B, nmap),
            "synergy": self.layout.block(self.w, "synergy").reshape(B, B),
            "synergy_mode": self.layout.block(self.w, "synergy_mode").reshape(B, B, nm),
            "matchup": self.layout.block(self.w, "matchup").reshape(B, B),
            "matchup_mode": self.layout.block(self.w, "matchup_mode").reshape(B, B, nm),
        }
