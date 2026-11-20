"""Record the Python engine's output on a set of drafts, for the web engine's parity test
(web/src/engine/parity.test.ts). Run by `mira publish`."""

import json
import random

from mira.engine.model import Model
from mira.engine.search import Searcher, suggest_bans


def opt(o):
    return {"picks": list(o.picks), "prob": o.prob, "win": o.win}


def write(model_path: str, out_path: str, n_cases: int = 12, seed: int = 7) -> int:
    m = Model.load(model_path)
    rng = random.Random(seed)
    cases = []
    states = [(0, 0), (0, 1), (1, 0), (1, 1), (1, 2), (3, 2), (2, 3), (3, 3)]
    for i in range(n_cases):
        mp = rng.randrange(len(m.maps))
        we_first = rng.random() < 0.5
        pool = rng.sample(range(m.B), 12)
        bans = pool[:rng.choice([0, 3, 6])]
        rest = [b for b in pool if b not in bans]
        n_first, n_second = states[i % len(states)]
        n_ours, n_theirs = (n_first, n_second) if we_first else (n_second, n_first)
        ours, theirs = rest[:n_ours], rest[n_ours:n_ours + n_theirs]
        try:
            r = Searcher(m, mp, set(bans)).run(tuple(ours), tuple(theirs), we_first)
        except ValueError:
            continue
        cases.append({
            "map": mp, "we_first": we_first, "ours": ours, "theirs": theirs, "bans": bans,
            "win": r.win, "side": r.side, "turn_size": r.turn_size,
            "suggestions": [opt(o) for o in r.suggestions],
            "line": [{"side": s.side, "chosen": opt(s.chosen), "alternatives": [opt(a) for a in s.alternatives]}
                     for s in r.line],
        })
    mp = 0
    bans = [{"brawler": b, "win": w, "gain": g} for b, w, g in suggest_bans(m, mp, True, set(), n=5)]
    with open(out_path, "w") as f:
        json.dump({"cases": cases, "bans": {"map": mp, "we_first": True, "result": bans}}, f)
    return len(cases)
