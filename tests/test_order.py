"""Rebuilding Ranked pick order (model/order.py)."""

import unittest

from mira import db
from mira.model import order
from mira.parse import parse_battle

from fakes import entry_3v3, player


def team(tags, brawlers, rank=19):
    return [player(t, b, 16000000 + i, trophies=rank) for i, (t, b) in enumerate(zip(tags, brawlers))]


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.n = 0

    def add(self, time, a_tags, b_tags, a=("SHELLY", "COLT", "BULL"), b=("BROCK", "RICO", "SPIKE"), result="victory"):
        e = entry_3v3(time=time, result=result, teams=[team(a_tags, a), team(b_tags, b)])
        battle = parse_battle(e, a_tags[0])
        for t in a_tags + b_tags:
            db.enqueue_player(self.conn, t, 0)
        db.insert_battle(self.conn, battle, source_tag=a_tags[0])

    def elo(self, **by_tag):
        for tag, e in by_tag.items():
            self.conn.execute("UPDATE players SET elo = ? WHERE tag = ?", (e, "#" + tag))

    def test_games_of_a_set_are_one_draft_with_every_result(self):
        A, B = ["#A1", "#A2", "#A3"], ["#B1", "#B2", "#B3"]
        self.add("20261118T101500.000Z", A, B)
        self.add("20261118T101700.000Z", A, B, result="defeat")
        self.add("20261118T101900.000Z", A, B)
        self.elo(A1=5000, A2=5100, A3=5200, B1=5300, B2=5400, B3=5500)
        drafts = order.load(self.conn)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(len(drafts[0].games), 3)
        self.assertEqual(drafts[0].winner, 0)

    def test_lowest_elo_picks_first_and_a_duo_picks_last(self):
        # #A1 and #A2 queue together (3 sets); #A3 is solo with the highest Elo.
        for i, others in enumerate((["#B1", "#B2", "#B3"], ["#C1", "#C2", "#C3"], ["#D1", "#D2", "#D3"])):
            self.add(("20261118T100000.000Z", "20261119T100000.000Z", "20261120T100000.000Z")[i], ["#A1", "#A2", "#A3" if i == 0 else f"#X{i}"], others)
        self.elo(A1=5000, A2=5100, A3=5400, X1=6000, X2=6000, B1=5300, B2=5200, B3=5100,
                 C1=1, C2=2, C3=3, D1=1, D2=2, D3=3)
        first_set = [x for x in order.load(self.conn) if x.time.startswith("2026-11-18")][0]
        self.assertEqual(first_set.teams[0], ["BULL", "SHELLY", "COLT"])  # solo #A3 first, then the duo by Elo
        self.assertEqual(first_set.party[0], [False, True, True])
        self.assertEqual(first_set.teams[1], ["SPIKE", "RICO", "BROCK"])  # no party: Elo ascending
        self.assertEqual(first_set.first, 0)  # lower average Elo picks first
        self.assertEqual([t for t, _ in first_set.sequence()], [0, 1, 1, 0, 0, 1])


if __name__ == "__main__":
    unittest.main()
