"""Win model (spec §4.1): P(team 0 wins | map, team 0, team 1).

logit = Σ_team0 strength − Σ_team1 strength + same-team synergy pairs (team0 − team1)
        + cross-team matchups (team0 vs team1)

strength[b] on a map = global[b] + per-mode[b, mode] + per-map[b, map]
                       + per-tier[b, tier] + per-tier-mode[b, tier, mode],
each block with its own L2 penalty, which gives map → mode → global shrinkage: a per-map term
only grows when that map has the games to support it. The tier terms work the same way: a rank
tier (Legendary .. Masters III+, by the lobby's average rank) only moves a brawler's strength
away from the shared value when that tier's games support it; synergies and matchups are shared. Synergy and matchup work the same way: a pair term
shared by all modes plus a per-mode adjustment (synergy_mode / matchup_mode). There is no
intercept, so swapping the teams exactly flips the prediction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from .dataset import TIERS, Matches

BLOCKS = ("global", "mode", "map", "synergy", "synergy_mode", "matchup", "matchup_mode", "tier", "tier_mode",
          "role_synergy", "role_matchup")
N_COLS = 75
# Penalties are in pseudo-games. Defaults = what tuning picked on ~12k real matches; weaker
# settings overfit pure noise (see tests/test_model.py).
DEFAULT_L2 = {"global": 3.0, "mode": 30.0, "map": 100.0,
              "synergy": 300.0, "synergy_mode": 1000.0, "matchup": 300.0, "matchup_mode": 1000.0,
              "tier": 100.0, "tier_mode": 300.0, "role_synergy": 30.0, "role_matchup": 30.0}

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
    n_tiers: int = len(TIERS)
    n_roles: int = 0  # draft roles (model/roles.py); 0 = no role terms
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
            "tier": B * self.n_tiers,
            "tier_mode": B * self.n_tiers * self.n_modes,
            # Role pairs, (lo, hi) in an R x R grid: what pair terms shrink toward, so a rare pair
            # (or a new brawler) starts from what its roles do together (synergy) or against
            # each other (matchup, edge of the lower role index). At least 1 so indexing works.
            "role_synergy": max(self.n_roles, 1) ** 2,
            "role_matchup": max(self.n_roles, 1) ** 2,
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


def features(m: Matches, layout: Layout, roles: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Sparse design as (idx, sign), each (n, N_COLS): logit_i = Σ_k w[idx[i,k]] * sign[i,k].
    ``roles``: (B,) role index per brawler (-1 none); defaults to m.brawler_roles."""
    B, nm, nmap, nt = layout.n_brawlers, layout.n_modes, layout.n_maps, layout.n_tiers
    o = layout.offsets
    t0, t1 = m.teams[:, 0, :], m.teams[:, 1, :]
    mode, mp = m.mode_idx[:, None], m.map_idx[:, None]
    tier = m.tier_idx()[:, None]
    n = len(m)
    cols_i, cols_s = [], []

    def add(idx, sign):
        cols_i.append(idx)
        cols_s.append(np.broadcast_to(sign, idx.shape).astype(np.float64))

    for team, sign in ((t0, 1.0), (t1, -1.0)):
        add(o["global"] + team, sign)
        add(o["mode"] + team * nm + mode, sign)
        add(o["map"] + team * nmap + mp, sign)
        add(o["tier"] + team * nt + tier, sign)
        add(o["tier_mode"] + (team * nt + tier) * nm + mode, sign)
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

    # Role pairs: zero weight when roles are off or a brawler has none.
    R = layout.n_roles
    roles = roles if roles is not None else m.brawler_roles
    roles = roles if R else None
    r0 = roles[t0] if roles is not None else np.full(t0.shape, -1)
    r1 = roles[t1] if roles is not None else np.full(t1.shape, -1)
    Rg = max(R, 1)
    for rt, sign in ((r0, 1.0), (r1, -1.0)):
        for a, b in _PAIRS_IN_TEAM:
            x, y = rt[:, a], rt[:, b]
            known = (x >= 0) & (y >= 0)
            pi = np.where(known, np.minimum(x, y) * Rg + np.maximum(x, y), 0)[:, None]
            add(o["role_synergy"] + pi, np.where(known, sign, 0.0)[:, None])
    for a in range(3):
        for b in range(3):
            x, y = r0[:, a], r1[:, b]
            ok = (x >= 0) & (y >= 0) & (x != y)
            pi = np.where(ok, np.minimum(x, y) * Rg + np.maximum(x, y), 0)[:, None]
            add(o["role_matchup"] + pi, np.where(ok, np.where(x < y, 1.0, -1.0), 0.0)[:, None])

    idx = np.concatenate(cols_i, axis=1)
    sgn = np.concatenate(cols_s, axis=1)
    assert idx.shape == (n, N_COLS)
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
    roles: np.ndarray | None = None  # (B,) role index the model was fit with (-1 = none)

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
        n_roles = int(m.brawler_roles.max()) + 1 if m.brawler_roles is not None and (m.brawler_roles >= 0).any() else 0
        layout = Layout(m.n_brawlers, n_modes or len(m.modes), n_maps or len(m.maps), n_roles=n_roles)
        roles = m.brawler_roles if n_roles else None
        idx, sgn = features(m, layout, roles)
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
        return cls(layout, w, l2, roles)

    def predict(self, m: Matches) -> np.ndarray:
        idx, sgn = features(m, self.layout, self.roles)
        return _sigmoid((self.w[idx] * sgn).sum(axis=1))

    # -- export -------------------------------------------------------------

    def tables(self) -> dict[str, np.ndarray]:
        """Parameter tables. "synergy" and "matchup" include the role-pair terms, folded into each
        brawler pair (i < j upper triangle), so the engines need no notion of roles; the raw role
        tables are "role_synergy" / "role_matchup" (R x R, lo < hi meaningful)."""
        B, nm, nmap = self.layout.n_brawlers, self.layout.n_modes, self.layout.n_maps
        R = max(self.layout.n_roles, 1)
        syn = self.layout.block(self.w, "synergy").reshape(B, B).copy()
        mu = self.layout.block(self.w, "matchup").reshape(B, B).copy()
        rs = self.layout.block(self.w, "role_synergy").reshape(R, R)
        rm = self.layout.block(self.w, "role_matchup").reshape(R, R)
        if self.layout.n_roles and self.roles is not None:
            i, j = np.triu_indices(B, k=1)
            ri, rj = self.roles[i], self.roles[j]
            known = (ri >= 0) & (rj >= 0)
            lo, hi = np.minimum(ri, rj), np.maximum(ri, rj)
            syn[i[known], j[known]] += rs[lo[known], hi[known]]
            diff = known & (ri != rj)
            sign = np.where(ri < rj, 1.0, -1.0)
            mu[i[diff], j[diff]] += sign[diff] * rm[lo[diff], hi[diff]]
        return {
            "global": self.layout.block(self.w, "global"),
            "mode": self.layout.block(self.w, "mode").reshape(B, nm),
            "map": self.layout.block(self.w, "map").reshape(B, nmap),
            "synergy": syn,
            "synergy_mode": self.layout.block(self.w, "synergy_mode").reshape(B, B, nm),
            "matchup": mu,
            "matchup_mode": self.layout.block(self.w, "matchup_mode").reshape(B, B, nm),
            "role_synergy": rs,
            "role_matchup": rm,
            "tier": self.layout.block(self.w, "tier").reshape(B, self.layout.n_tiers),
            "tier_mode": self.layout.block(self.w, "tier_mode").reshape(B, self.layout.n_tiers, nm),
        }

    # -- uncertainty ----------------------------------------------------------

    def strength_sd(self, m: Matches, weights: np.ndarray | None = None) -> np.ndarray:
        """(n_tiers, B, n_maps) standard error of each brawler's strength on each map and tier.

        Laplace approximation: the inverse Hessian of the penalized loss, restricted to one
        brawler's own strength terms (global, mode, map, tier, tier-mode). Pair terms and other
        brawlers are held fixed, so this is a little optimistic, but it scales the right way:
        a brawler with 10 games on a map gets a wide error, one with 2,000 a narrow one."""
        L = self.layout
        B, nm, nmap, nt = L.n_brawlers, L.n_modes, L.n_maps, L.n_tiers
        sw = np.ones(len(m)) if weights is None else np.asarray(weights, dtype=np.float64)
        p = self.predict(m)
        r = sw * p * (1 - p)  # Fisher information each appearance adds (sign squared = 1)
        tier = m.tier_idx()
        # Information per brawler, map and tier, summed over both teams' slots.
        info = np.zeros((B, nmap, nt))
        for t in range(2):
            for s in range(3):
                np.add.at(info, (m.teams[:, t, s], m.map_idx, tier), r)
        mode_of_map = np.zeros(nmap, dtype=int)
        for mp, md in zip(m.map_idx, m.mode_idx):
            mode_of_map[mp] = md
        # Local parameters: global | mode[nm] | map[nmap] | tier[nt] | tier_mode[nt * nm].
        D = 1 + nm + nmap + nt + nt * nm
        X = np.zeros((nmap, nt, D))  # indicator of the terms one appearance touches
        for j in range(nmap):
            k = mode_of_map[j]
            for t in range(nt):
                X[j, t, [0, 1 + k, 1 + nm + j, 1 + nm + nmap + t, 1 + nm + nmap + nt + t * nm + k]] = 1.0
        lam = np.concatenate([[self.l2["global"]], np.full(nm, self.l2["mode"]), np.full(nmap, self.l2["map"]),
                              np.full(nt, self.l2["tier"]), np.full(nt * nm, self.l2["tier_mode"])])
        Xf = X.reshape(-1, D)
        out = np.zeros((nt, B, nmap))
        for b in range(B):
            H = (Xf * info[b].reshape(-1)[:, None]).T @ Xf + np.diag(2 * lam)
            var = np.einsum("id,de,ie->i", Xf, np.linalg.inv(H), Xf).reshape(nmap, nt)
            out[:, b, :] = np.sqrt(var).T
        return out
