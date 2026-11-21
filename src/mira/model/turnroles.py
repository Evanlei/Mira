"""When in a draft each role gets picked, from pro drafts with a known pick order.

Liquipedia lists each team's picks in pick order, and on maps with a recorded first pick that
gives the turn of every pick (1-2-2-1: first team picks turns 1, 4, 5; second team 2, 3, 6).
Pros take snipers and control early and throwers, tanks and space makers late (BobbyBS's draft
guide says the same: throwers last pick, space makers at 4-5). Roles by turn are a property of
drafting, not of one patch, so all years are used.

delta[turn][role] = tau * log(P(role | turn) / P(role)), shrunk toward 0 with ``k`` pseudo-picks;
the opponent model adds delta[turn][role(b)] to each brawler's pick score.
"""

from __future__ import annotations

import json

import numpy as np

from .. import pro
from .roles import ROLES

# 0-based turn of each listed pick: (picked first?, position in the team's list)
TURN = {(True, 0): 0, (False, 0): 1, (False, 1): 2, (True, 1): 3, (True, 2): 4, (False, 2): 5}
DEFAULT_TAU = 1.0
K = 50.0


def counts(rows, role_of: dict[str, str]) -> np.ndarray:
    """(6, R) picks per turn and role over pro maps with a known first pick."""
    c = np.zeros((6, len(ROLES)))
    for r in rows:
        if r["first_pick"] is None:
            continue
        teams = (json.loads(r["picks1"]), json.loads(r["picks2"]))
        for t in (0, 1):
            for i, name in enumerate(teams[t]):
                role = role_of.get(pro.norm(name))
                if role in ROLES:
                    c[TURN[(t == r["first_pick"], i)], ROLES.index(role)] += 1
    return c


def fit(c: np.ndarray, tau: float = DEFAULT_TAU, k: float = K) -> np.ndarray:
    p = (c.sum(0) + 1) / (c.sum() + len(ROLES))
    p_t = (c + k * p) / (c.sum(1, keepdims=True) + k)
    return tau * np.log(p_t / p)


def role_lookup(path: str = "data/roles.json") -> dict[str, str]:
    """norm(name) -> role, including Liquipedia spellings."""
    data = json.load(open(path, encoding="utf-8"))["roles"]
    out = {pro.norm(n): v["role"] for n, v in data.items()}
    for alias, target in pro.BRAWLER_ALIASES.items():
        if target in out:
            out.setdefault(alias, out[target])
    return out


def to_dict(delta: np.ndarray, roles: np.ndarray, n_maps: int, tau: float) -> dict:
    return {
        "doc": "Opponent model: add delta[turn][role[b]] to brawler b's pick score at draft turn "
               "`turn` (0-5, 1-2-2-1 order); role[b] = -1 means no adjustment. From pro drafts with a "
               "known pick order (Liquipedia) and BobbyBS's draft roles.",
        "roles": [int(x) for x in roles], "role_names": list(ROLES), "tau": tau, "n_maps": n_maps,
        "delta": [[round(float(x), 4) for x in row] for row in delta],
    }
