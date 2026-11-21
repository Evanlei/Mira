"""How well a trained model agrees with pro drafts (from `mira pro-sync`).

Three checks on recent pro maps whose map and brawlers the model knows:

- Results: does the win model call the winner? (Pro sets are a different game from solo queue:
  coordinated teams, so this mainly guards against a model that's badly off.)
- Bans: how many of the pros' bans are in Mira's top bans for the map, against two simple
  rankings: the brawlers picked most in Ranked on that map, and the pros' own ban rates on the
  map from other matches.
- Picks: hold out one brawler of each pro team; with the other five picks and the bans known,
  where does Mira's ranking put the pro's actual pick? Compared with ranking by how often
  Masters players pick it in that spot (the pick model).
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import pro
from .engine.model import Model
from .engine.search import suggest_bans

BAN_TOP = (3, 6, 10)
PICK_TOP = (1, 3, 5, 10)


@dataclass
class ProMatch:
    map_idx: int
    teams: tuple[tuple[int, ...], tuple[int, ...]]
    bans: tuple[tuple[int, ...], tuple[int, ...]]
    winner: int  # 0 or 1
    games: int
    first_pick: int | None
    played_on: str


def resolve(model: Model, rows: list[sqlite3.Row]) -> tuple[list[ProMatch], Counter]:
    """Rows the model can score, and why the others were skipped."""
    by_name = {pro.norm(n): i for i, n in enumerate(model.names)}
    for alias, target in pro.BRAWLER_ALIASES.items():
        if target in by_name:
            by_name.setdefault(alias, by_name[target])
    maps = {pro.norm(name): i for i, (_, name) in enumerate(model.maps)}
    out, skipped = [], Counter()
    for r in rows:
        mp = maps.get(pro.norm(r["map"]))
        if mp is None:
            skipped["map not in the model"] += 1
            continue
        try:
            teams = tuple(tuple(by_name[pro.norm(n)] for n in json.loads(r[f"picks{t}"])) for t in (1, 2))
            bans = tuple(tuple(by_name[pro.norm(n)] for n in json.loads(r[f"bans{t}"])) for t in (1, 2))
        except KeyError:
            skipped["brawler not in the model"] += 1
            continue
        if len(set(teams[0]) | set(teams[1])) < 6:
            skipped["duplicate brawler"] += 1
            continue
        s1, s2 = r["score1"], r["score2"]
        out.append(ProMatch(mp, teams, bans, 0 if s1 > s2 else 1, s1 + s2, r["first_pick"], r["played_on"] or ""))
    return out, skipped


@dataclass
class Report:
    n: int = 0
    skipped: Counter = field(default_factory=Counter)
    win_acc: float = 0.0
    win_log_loss: float = 0.0
    ban_maps: int = 0
    ban_hits: dict = field(default_factory=dict)   # ranking name -> {k: share of pro bans in top k}
    pick_n: int = 0
    pick_hits: dict = field(default_factory=dict)  # ranking name -> {k: share of held-out picks in top k}


def _hits(rank_lists: list[tuple[list[int], set[int]]], ks) -> dict:
    total = sum(len(want) for _, want in rank_lists) or 1
    return {k: sum(len(set(ranked[:k]) & want) for ranked, want in rank_lists) / total for k in ks}


def run(model: Model, matches: list[ProMatch], ban_maps: int | None = None, log=lambda s: None) -> Report:
    rep = Report(n=len(matches))
    if not matches:
        return rep

    # Results.
    ll = acc = 0.0
    for m in matches:
        p = model.win_prob(m.teams[0], m.teams[1], m.map_idx)
        p_win = p if m.winner == 0 else 1 - p
        ll -= math.log(max(p_win, 1e-12))
        acc += p_win > 0.5
    rep.win_acc, rep.win_log_loss = acc / len(matches), ll / len(matches)

    # Bans, per map: the pros' bans of every match on that map against one ranking per map.
    by_map: dict[int, list[ProMatch]] = defaultdict(list)
    for m in matches:
        by_map[m.map_idx].append(m)
    order = sorted(by_map, key=lambda mp: -len(by_map[mp]))[:ban_maps]
    ban_counts = {mp: Counter(b for m in by_map[mp] for side in m.bans for b in set(side)) for mp in order}
    mira, popular, pros = [], [], []
    for i, mp in enumerate(order):
        log(f"  bans {i + 1}/{len(order)}: {model.maps[mp][1]}")
        ours = [b for b, _, _ in suggest_bans(model, mp, True, set(), n=max(BAN_TOP))]
        p = model.pick_probs([], [], set(), mp)
        pop = sorted(p, key=lambda b: -p[b])
        for m in by_map[mp]:
            want = set(m.bans[0]) | set(m.bans[1])
            if not want:
                continue
            mira.append((ours, want))
            popular.append((pop, want))
            # The pros' ban rate on this map, leaving this match out.
            loo = ban_counts[mp] - Counter(want)
            pros.append(([b for b, _ in loo.most_common()], want))
    rep.ban_maps = len(order)
    rep.ban_hits = {"Mira": _hits(mira, BAN_TOP), "Ranked pick rate": _hits(popular, BAN_TOP),
                    "Pro ban rate (other matches)": _hits(pros, BAN_TOP)}

    # Picks: hold out each brawler with the other five known.
    mira_p, pop_p = [], []
    for m in matches:
        banned = set(m.bans[0]) | set(m.bans[1])
        for t in (0, 1):
            mine, theirs = m.teams[t], m.teams[1 - t]
            for i, target in enumerate(mine):
                allies = mine[:i] + mine[i + 1:]
                taken = set(allies) | set(theirs) | (banned - {target})
                pool = [b for b in range(model.B) if b not in taken]
                score = {b: model.gain(b, allies, theirs, m.map_idx) + model.adjust(b, m.map_idx) for b in pool}
                mira_p.append((sorted(pool, key=lambda b: -score[b]), {target}))
                p = model.pick_probs(allies, theirs, taken, m.map_idx)
                pop_p.append((sorted(pool, key=lambda b: -p.get(b, 0.0)), {target}))
    rep.pick_n = len(mira_p)
    rep.pick_hits = {"Mira (win model)": _hits(mira_p, PICK_TOP), "Masters pick rate": _hits(pop_p, PICK_TOP)}
    return rep


def format_report(rep: Report, since: str | None) -> str:
    lines = [f"Pro maps since {since or 'the start'}: {rep.n} scored"
             + (f" (skipped: {', '.join(f'{v} {k}' for k, v in rep.skipped.items())})" if rep.skipped else "")]
    if not rep.n:
        return "\n".join(lines)
    lines.append(f"\nResults: winner called {rep.win_acc:.1%}, log loss {rep.win_log_loss:.4f} (coin flip 0.6931)")
    lines.append(f"\nBans: share of pro bans in the top k, {rep.ban_maps} maps")
    lines.append("  " + "ranking".ljust(30) + "".join(f"top {k:<5}" for k in BAN_TOP))
    for name, h in rep.ban_hits.items():
        lines.append("  " + name.ljust(30) + "".join(f"{h[k]:<9.1%}" for k in BAN_TOP))
    lines.append(f"\nPicks: rank of the pro's pick with the other five known ({rep.pick_n} picks)")
    lines.append("  " + "ranking".ljust(30) + "".join(f"top {k:<5}" for k in PICK_TOP))
    for name, h in rep.pick_hits.items():
        lines.append("  " + name.ljust(30) + "".join(f"{h[k]:<9.1%}" for k in PICK_TOP))
    lines.append("\nPro data: Liquipedia (CC-BY-SA).")
    return "\n".join(lines)
