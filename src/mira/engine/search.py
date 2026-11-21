"""Expectimax over the rest of the draft (spec §4.3).

Pick order is 1-2-2-1: F, S, S, F, F, S (F = the team with first pick). Consecutive picks by
the same side form one *turn*, and a two-pick turn is searched as an unordered pair, since the
order within a turn doesn't change the final teams.

- Our turns: the best option among our top-K candidates. Candidates are ranked, and the best
  one chosen, with the model's ranking adjustment (Model.adjust: an uncertainty penalty and a
  pick-rate prior), so a brawler with a handful of games can't top the list on noise alone.
  Reported win chances stay the plain win model's.
- Their turns: the most likely options for a typical Masters player (pick model), weighted by
  probability (expectation), not their best counter.
- A finished draft is scored by the win model.

States are memoized by (our set, their set), so equivalent pick orders are searched once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from .model import Model

ORDER = ("F", "S", "S", "F", "F", "S")


@dataclass
class Settings:
    our_k: int = 8         # our candidate brawlers per turn
    our_pairs: int = 12    # best candidate pairs kept for a two-pick turn
    their_n: int = 5       # their likely single picks
    their_pairs: int = 8   # their likely pairs
    pair_pool: int = 8     # singles combined into their candidate pairs


@dataclass
class Option:
    picks: tuple[int, ...]   # 1 or 2 brawlers
    prob: float | None       # likelihood (their turns); None on our turns
    win: float               # our expected win chance after this option, with best play onward


@dataclass
class Step:
    side: str                # "us" or "them"
    chosen: Option           # our best option, or their most likely one
    alternatives: list[Option] = field(default_factory=list)


@dataclass
class Result:
    win: float                       # expected win chance with best play
    suggestions: list[Option]        # for the current turn, best first
    line: list[Step]                 # main line: the rest of the draft
    turn_size: int                   # picks in the current turn (1 or 2)
    side: str                        # whose turn it is


def turns_remaining(we_first: bool, n_ours: int, n_theirs: int) -> list[tuple[str, int]]:
    """Remaining turns as (side, picks) from the current draft position."""
    sides = [("us" if (s == "F") == we_first else "them") for s in ORDER]
    need = {"us": n_ours, "them": n_theirs}
    seen = {"us": 0, "them": 0}
    remaining = []
    for side in sides:
        if seen[side] < need[side]:
            seen[side] += 1
            continue
        if remaining and remaining[-1][0] == side:
            remaining[-1] = (side, remaining[-1][1] + 1)
        else:
            remaining.append((side, 1))
    # Validate: the picks made must be a prefix of the order.
    made = n_ours + n_theirs
    prefix = sides[:made]
    if prefix.count("us") != n_ours or prefix.count("them") != n_theirs:
        raise ValueError(f"{n_ours} of our picks and {n_theirs} of theirs don't fit the 1-2-2-1 order "
                         f"with {'us' if we_first else 'them'} picking first")
    return remaining


class Searcher:
    def __init__(self, model: Model, mp: int, banned: set[int], allowed: set[int] | None = None,
                 settings: Settings | None = None):
        self.m = model
        self.mp = mp
        self.banned = banned
        self.allowed = allowed  # our brawler pool (player-tag filter); None = all
        self.s = settings or Settings()
        self.memo: dict = {}

    # -- candidate generation ---------------------------------------------------

    def _ours(self, ours: tuple, theirs: tuple, size: int) -> list[tuple[int, ...]]:
        taken = set(ours) | set(theirs) | self.banned
        pool = [b for b in range(self.m.B) if b not in taken and (self.allowed is None or b in self.allowed)]
        if len(pool) < size:
            # The player's pool is used up (or too small): fall back to every available brawler,
            # since teammates can still pick them.
            pool = [b for b in range(self.m.B) if b not in taken]
        score = {b: self.m.gain(b, ours, theirs, self.mp) + self.m.adjust(b, self.mp) for b in pool}
        pool.sort(key=score.get, reverse=True)
        top = pool[: self.s.our_k]
        if size == 1:
            return [(b,) for b in top]
        pairs = list(combinations(top, 2))
        pairs.sort(key=lambda p: score[p[0]] + score[p[1]] + self.m.synergy(p[0], p[1], self.mp), reverse=True)
        return pairs[: self.s.our_pairs]

    def _theirs(self, ours: tuple, theirs: tuple, size: int) -> list[tuple[tuple[int, ...], float]]:
        taken = set(ours) | set(theirs) | self.banned
        turn = len(ours) + len(theirs)  # draft turn of their next pick (0-5)
        p1 = self.m.pick_probs(theirs, ours, taken, self.mp, turn)
        if size == 1:
            top = sorted(p1.items(), key=lambda kv: kv[1], reverse=True)[: self.s.their_n]
            z = sum(p for _, p in top)
            return [((b,), p / z) for b, p in top]
        singles = sorted(p1, key=p1.get, reverse=True)[: self.s.pair_pool]
        scored = []
        for a, b in combinations(singles, 2):
            # Either order: a then b (b given a as an ally), or b then a.
            pa_b = self.m.pick_probs(theirs + (a,), ours, taken | {a}, self.mp, turn + 1).get(b, 0.0)
            pb_a = self.m.pick_probs(theirs + (b,), ours, taken | {b}, self.mp, turn + 1).get(a, 0.0)
            scored.append(((a, b), p1[a] * pa_b + p1[b] * pb_a))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        top = scored[: self.s.their_pairs]
        z = sum(p for _, p in top)
        return [(picks, p / z) for picks, p in top]

    def choice(self, o: Option) -> float:
        """How we rank our own options: the win chance plus the ranking adjustment of the picks,
        moved from logit to probability scale (d p / d logit = p (1 - p))."""
        a = sum(self.m.adjust(b, self.mp) for b in o.picks)
        return o.win + o.win * (1 - o.win) * a

    # -- search -----------------------------------------------------------------

    def value(self, ours: tuple, theirs: tuple, turns: tuple) -> float:
        key = (frozenset(ours), frozenset(theirs))
        if key in self.memo:
            return self.memo[key][0]
        if not turns:
            v = self.m.win_prob(ours, theirs, self.mp)
            self.memo[key] = (v, [])
            return v
        options = self.expand(ours, theirs, turns)
        side = turns[0][0]
        if side == "us":
            v = options[0].win  # sorted by choice(): the option we'd actually take
        else:
            v = sum(o.prob * o.win for o in options)
        self.memo[key] = (v, options)
        return v

    def expand(self, ours: tuple, theirs: tuple, turns: tuple) -> list[Option]:
        side, size = turns[0]
        rest = turns[1:]
        if side == "us":
            opts = [Option(p, None, self.value(ours + p, theirs, rest)) for p in self._ours(ours, theirs, size)]
            opts.sort(key=self.choice, reverse=True)
        else:
            opts = [Option(p, prob, self.value(ours, theirs + p, rest)) for p, prob in self._theirs(ours, theirs, size)]
            opts.sort(key=lambda o: o.prob, reverse=True)
        return opts

    def run(self, ours: tuple, theirs: tuple, we_first: bool, alternatives: int = 3) -> Result:
        turns = tuple(turns_remaining(we_first, len(ours), len(theirs)))
        if not turns:
            v = self.m.win_prob(ours, theirs, self.mp)
            return Result(v, [], [], 0, "done")
        win = self.value(ours, theirs, turns)
        suggestions = self.memo[(frozenset(ours), frozenset(theirs))][1]
        # Main line: our best option on our turns, their most likely option on theirs.
        line, o, t, rest = [], ours, theirs, turns
        while rest:
            options = self.memo[(frozenset(o), frozenset(t))][1]
            side = rest[0][0]
            chosen = options[0]  # sorted: best win for us, most likely for them
            line.append(Step(side, chosen, options[1: 1 + alternatives]))
            if side == "us":
                o = o + chosen.picks
            else:
                t = t + chosen.picks
            rest = rest[1:]
            self.value(o, t, rest)  # make sure the next node is expanded
        return Result(win, suggestions, line, turns[0][1], turns[0][0])


PRO_BAN_CANDIDATES = 6  # pro favourites added to the ban candidates when ban_lambda > 0


def suggest_bans(model: Model, mp: int, we_first: bool, already_banned: set[int], n: int = 5,
                 candidates: int = 15, settings: Settings | None = None,
                 allowed: set[int] | None = None) -> list[tuple[int, float, float]]:
    """Bans ranked by how much removing the brawler raises our expected win chance.

    Returns (brawler, win chance if banned, gain vs not banning). Candidates are the brawlers
    the opponent is most likely to pick on this map, weighted by strength there, plus (when the
    model has pro data and ban_lambda > 0) the pros' most-banned brawlers there. They're ranked
    by gain + ban_lambda * pro ban rate: Ranked has no ban data, so the pros' bans are our only
    direct evidence of what's worth banning.
    """
    s = settings or Settings(our_k=6, our_pairs=8, their_n=4, their_pairs=6, pair_pool=6)
    base = Searcher(model, mp, set(already_banned), allowed, s).run((), (), we_first).win
    p = model.pick_probs((), (), already_banned, mp)
    # Threat uses the pessimistic strength, so a noisy few-game brawler isn't a top ban candidate.
    pool = sorted(p, key=lambda b: p[b] * (1 + max(0.0, model.strength(b, mp) - model.kappa * model.sd_of(b, mp))),
                  reverse=True)[:candidates]
    if model.ban_lambda:
        # Also try what pros ban most here; rank by gain + ban_lambda * pro ban rate.
        pool += [b for b in sorted(p, key=lambda b: model.pro_ban_rate(b, mp), reverse=True)[:PRO_BAN_CANDIDATES]
                 if b not in pool]
    out = []
    for b in pool:
        v = Searcher(model, mp, set(already_banned) | {b}, allowed, s).run((), (), we_first).win
        out.append((b, v, v - base))
    out.sort(key=lambda x: x[2] + model.ban_lambda * model.pro_ban_rate(x[0], mp), reverse=True)
    return out[:n]
