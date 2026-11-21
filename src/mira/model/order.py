"""Ranked drafts with their pick order, rebuilt from who was in the lobby.

The battle log has no pick order, but the draft follows the players:
- Ranked is best of 3, and every game of a set is logged with the same six brawlers, so a set
  is one draft. Games are grouped into sets by (map, the six player tags).
- Within a team, solo players pick first, lowest Elo first; party members (duo, trio) pick
  after them. Pro player Enraged (NAVI) describes the Elo order; the duo-last rule is from
  this project's owner. Both show in the data: ordered this way, later picks counter earlier
  enemy picks (the matchup edge grows with how much later the pick is), while the battle log's
  own order shows nothing (README: "Pick order in Ranked").
- Parties are teammates seen together in PARTY_SETS or more different sets: random solo-queue
  teammates almost never repeat.
- First pick goes to one team by ``first_team`` (default: lower average Elo, see README).

Elo is the player's profile reading closest in time to the set (player_elo, refreshed daily
by the crawler), else their latest one (players.elo), so the order is approximate.
"""

from __future__ import annotations

import bisect
import itertools
import sqlite3
from datetime import datetime
from collections import Counter, defaultdict
from dataclasses import dataclass

PARTY_SETS = 3
# Turn (0-5) of each team's k-th pick: the first team picks turns 0, 3, 4; the second 1, 2, 5.
TURNS = ((0, 3, 4), (1, 2, 5))


@dataclass
class Draft:
    set_id: str            # battle_id of the set's first game
    time: str
    mode: str
    map: str
    lobby_rank: int
    lobby_mean: float
    teams: tuple[list[str], list[str]]          # brawler names in pick order within each team
    elos: tuple[list[int], list[int]]
    party: tuple[list[bool], list[bool]]        # in a party (duo/trio) with a teammate
    first: int                                  # team with first pick
    games: list[int]                            # winner of each game in the set (0/1)

    @property
    def winner(self) -> int | None:
        c = Counter(self.games)
        return None if c[0] == c[1] else (0 if c[0] > c[1] else 1)

    def sequence(self) -> list[tuple[int, str]]:
        """[(team, brawler)] in the 1-2-2-1 turn order."""
        out = [None] * 6
        for k in range(3):
            out[TURNS[0][k]] = (self.first, self.teams[self.first][k])
            out[TURNS[1][k]] = (1 - self.first, self.teams[1 - self.first][k])
        return out


def _lower_mean_elo(elos) -> int:
    return 0 if sum(elos[0]) <= sum(elos[1]) else 1


def load(conn: sqlite3.Connection, min_lobby_rank: int = 16, since: str | None = None,
         first_team=_lower_mean_elo, party_sets: int = PARTY_SETS) -> list[Draft]:
    """Ordered drafts of Ranked sets where all six players have a known Elo, oldest first."""
    rows = conn.execute(
        """SELECT b.battle_id, b.battle_time, b.mode, b.map, b.lobby_rank, b.winning_team, b.is_draw,
                  bp.team, bp.player_tag, bp.brawler_name, bp.trophies, p.elo
           FROM battles b JOIN battle_players bp USING (battle_id) LEFT JOIN players p ON p.tag = bp.player_tag
           WHERE b.battle_type = 'soloRanked' AND b.lobby_rank >= ? AND (? IS NULL OR b.battle_time >= ?)
           ORDER BY b.battle_time, b.battle_id""", (min_lobby_rank, since, since)).fetchall()
    games = defaultdict(list)
    for r in rows:
        games[r[0]].append(r)
    sets: dict[tuple, list] = {}
    for bid, rs in games.items():
        if len(rs) != 6:
            continue
        key = (rs[0][3], tuple(sorted(r[8] for r in rs)))
        sets.setdefault(key, []).append(rs)

    history = defaultdict(list)  # tag -> [(unix seconds, elo)] ascending
    try:
        for tag, at, elo in conn.execute("SELECT tag, at, elo FROM player_elo ORDER BY tag, at"):
            history[tag].append((at, elo))
    except sqlite3.OperationalError:  # older database without the table
        pass

    def elo_at(tag: str, when: float, latest):
        h = history.get(tag)
        if not h:
            return latest
        i = bisect.bisect_left(h, (when, -1))
        near = [h[j] for j in (i - 1, i) if 0 <= j < len(h)]
        return min(near, key=lambda x: abs(x[0] - when))[1]

    pair = Counter()
    for gs in sets.values():
        rs = gs[0]
        for t in (0, 1):
            for a, b in itertools.combinations(sorted(r[8] for r in rs if r[7] == t), 2):
                pair[(a, b)] += 1

    def together(a, b):
        return pair[(a, b) if a < b else (b, a)] >= party_sets

    out = []
    for gs in sets.values():
        rs = gs[0]
        when = datetime.fromisoformat(rs[0][1].replace("Z", "+00:00")).timestamp()
        rs = [r[:11] + (elo_at(r[8], when, r[11]),) for r in rs]
        if any(r[11] is None for r in rs):
            continue
        teams, elos, party = [], [], []
        for t in (0, 1):
            mine = [r for r in rs if r[7] == t]
            in_party = {r[8]: any(together(r[8], o[8]) for o in mine if o is not r) for r in mine}
            order = sorted(mine, key=lambda r: (in_party[r[8]], r[11]))  # solo first, then by Elo
            teams.append([r[9] for r in order]); elos.append([r[11] for r in order])
            party.append([in_party[r[8]] for r in order])
        results = [g[0][5] for g in gs if not g[0][6] and g[0][5] is not None]
        ranks = [r[10] for r in rs if r[10] is not None]
        out.append(Draft(rs[0][0], rs[0][1], rs[0][2], rs[0][3], rs[0][4],
                         sum(ranks) / len(ranks) if ranks else float(rs[0][4]),
                         (teams[0], teams[1]), (elos[0], elos[1]), (party[0], party[1]),
                         first_team(elos), results))
    out.sort(key=lambda d: (d.time, d.set_id))
    return out
