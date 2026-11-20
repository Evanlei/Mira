"""Record the Python engine's output on a set of drafts, for the web engine's parity test
(web/src/engine/parity.test.ts). Run by `mira publish`."""

import json
import math
import random

from mira.engine.model import Model
from mira.engine.search import Searcher, suggest_bans


def opt(o):
    return {"picks": list(o.picks), "prob": o.prob, "win": o.win}


def test_ranking(data: dict) -> dict:
    """A fixed, clearly non-zero ranking block (penalty + prior), so the parity test exercises
    Model.adjust whatever the live model's own kappa and gamma are."""
    n_tiers = max(1, len(data.get("tiers", [])))
    bm = data.get("games", {}).get("brawler_map")
    B, n_maps = len(data["brawlers"]), len(data["maps"])
    sd = [[round(1 / math.sqrt(0.25 * (bm[b][j] if bm else 100) + 6), 3) for j in range(n_maps)] for b in range(B)]
    return {"kappa": 1.5, "gamma": 0.05, "strength_sd": [sd] * n_tiers}


def write(model_path: str, out_path: str, n_cases: int = 16, seed: int = 7) -> int:
    with open(model_path, encoding="utf-8") as f:
        data = json.load(f)
    n_tiers = max(1, len(data.get("tiers", [])))
    ranking = test_ranking(data)
    models = [Model(data, tier=t) for t in range(n_tiers)]
    ranked = [Model({**data, "ranking": ranking}, tier=t) for t in range(n_tiers)]
    rng = random.Random(seed)
    cases = []
    states = [(0, 0), (0, 1), (1, 0), (1, 1), (1, 2), (3, 2), (2, 3), (3, 3)]
    for i in range(n_cases):
        tier = i % n_tiers
        use_ranking = i % 4 == 1  # every fourth case ranks our picks with the test ranking block
        m = (ranked if use_ranking else models)[tier]
        mp = rng.randrange(len(m.maps))
        we_first = rng.random() < 0.5
        pool = rng.sample(range(m.B), 12)
        bans = pool[:rng.choice([0, 3, 6])]
        rest = [b for b in pool if b not in bans]
        n_first, n_second = states[i % len(states)]
        n_ours, n_theirs = (n_first, n_second) if we_first else (n_second, n_first)
        ours, theirs = rest[:n_ours], rest[n_ours:n_ours + n_theirs]
        # Every third case restricts our side to a pool (the player's power-11 brawlers).
        taken = set(bans) | set(ours) | set(theirs)
        allowed = sorted(rng.sample([b for b in range(m.B) if b not in taken], 15)) if i % 3 == 2 else None
        try:
            r = Searcher(m, mp, set(bans), set(allowed) if allowed else None).run(tuple(ours), tuple(theirs), we_first)
        except ValueError:
            continue
        cases.append({
            "map": mp, "tier": tier, "ranking": use_ranking, "allowed": allowed, "we_first": we_first, "ours": ours, "theirs": theirs, "bans": bans,
            "win": r.win, "side": r.side, "turn_size": r.turn_size,
            "suggestions": [opt(o) for o in r.suggestions],
            "line": [{"side": s.side, "chosen": opt(s.chosen), "alternatives": [opt(a) for a in s.alternatives]}
                     for s in r.line],
        })
    mp, m = 0, Model(data)
    bans = [{"brawler": b, "win": w, "gain": g} for b, w, g in suggest_bans(m, mp, True, set(), n=5)]
    m = Model({**data, "ranking": ranking})
    bans_ranked = [{"brawler": b, "win": w, "gain": g} for b, w, g in suggest_bans(m, mp, True, set(), n=5)]
    with open(out_path, "w") as f:
        json.dump({"cases": cases, "ranking": ranking,
                   "bans": {"map": mp, "we_first": True, "result": bans, "result_ranked": bans_ranked}}, f)
    return len(cases)
