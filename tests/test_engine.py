import json
import unittest

import numpy as np

from mira.engine.model import Model
from mira.engine.search import Searcher, Settings, suggest_bans, turns_remaining
from mira.model import export
from mira.model.pickmodel import PickModel
from mira.model.winmodel import WinModel

from test_model import one, synthetic


def exported(m, win, pick):
    data = export.to_dict(win, m, export.game_counts(m), extra={"pick_model": export.pick_model_dict(pick, threshold=0)},
                          threshold=0)
    return Model(json.loads(json.dumps(data)))  # round-trip through JSON like the site will


class ParityTests(unittest.TestCase):
    """The stdlib engine must reproduce the numpy models from model.json."""

    @classmethod
    def setUpClass(cls):
        cls.m = synthetic(n=3000)
        cls.win = WinModel.fit(cls.m, l2={"global": 3, "mode": 30, "map": 30, "synergy": 100,
                                          "synergy_mode": 300, "matchup": 100, "matchup_mode": 300})
        cls.pick = PickModel.fit(cls.m)
        cls.pick.alpha, cls.pick.beta = 0.5, 0.25
        cls.engine = exported(cls.m, cls.win, cls.pick)

    def test_win_prob_matches_numpy(self):
        for t0, t1, mp in [([0, 7, 9], [4, 11, 13], 0), ([2, 3, 5], [1, 4, 6], 3), ([4, 5, 6], [7, 8, 9], 1)]:
            expected = self.win.predict(one(self.m, t0, t1, mp))[0]
            self.assertAlmostEqual(self.engine.win_prob(t0, t1, mp), expected, places=3)

    def test_win_prob_is_symmetric(self):
        a, b = [0, 2, 3], [4, 5, 6]
        self.assertAlmostEqual(self.engine.win_prob(a, b, 0) + self.engine.win_prob(b, a, 0), 1.0, places=12)
        self.assertAlmostEqual(self.engine.matchup(4, 5, 0), -self.engine.matchup(5, 4, 0), places=12)

    def test_pick_probs_match_numpy(self):
        allies, enemies = [2], [4, 5]
        unavailable = {2, 4, 5, 9}
        expected = self.pick.probs(1, allies, enemies, unavailable)
        got = self.engine.pick_probs(allies, enemies, unavailable, 1)
        self.assertAlmostEqual(sum(got.values()), 1.0, places=9)
        for b, p in got.items():
            self.assertAlmostEqual(p, expected[b], places=3)
        self.assertNotIn(9, got)

    def test_name_lookup(self):
        self.assertEqual(self.engine.brawler("b12"), 12)
        self.assertEqual(self.engine.map("MAP3"), 3)
        with self.assertRaises(KeyError):
            self.engine.brawler("nobody")
        with self.assertRaises(KeyError):
            self.engine.map("map")  # ambiguous prefix


class TurnOrderTests(unittest.TestCase):
    def test_order(self):
        self.assertEqual(turns_remaining(True, 0, 0), [("us", 1), ("them", 2), ("us", 2), ("them", 1)])
        self.assertEqual(turns_remaining(False, 0, 0), [("them", 1), ("us", 2), ("them", 2), ("us", 1)])
        self.assertEqual(turns_remaining(True, 1, 1), [("them", 1), ("us", 2), ("them", 1)])  # mid double pick
        self.assertEqual(turns_remaining(True, 3, 2), [("them", 1)])
        self.assertEqual(turns_remaining(True, 3, 3), [])

    def test_invalid(self):
        with self.assertRaises(ValueError):
            turns_remaining(True, 2, 1)  # we can't have 2 picks before their 2
        with self.assertRaises(ValueError):
            turns_remaining(False, 1, 0)


def toy_model(B=8):
    """Brawler 0 is far stronger than the rest; the opponent mostly picks 5, then 6."""
    base = [[-3.0] for _ in range(B)]
    base[5][0], base[6][0] = 0.0, -0.5
    data = {
        "brawlers": [{"id": i, "name": f"B{i}"} for i in range(B)],
        "modes": ["m"], "maps": [{"mode": "m", "map": "x"}],
        "win_model": {"global": [2.0 if i == 0 else 0.0 for i in range(B)], "mode": [[0.0]] * B, "map": [[0.0]] * B,
                      "synergy": [], "synergy_mode": [], "matchup": [[1, 5, 1.0]], "matchup_mode": []},
        "pick_model": {"alpha": 1.0, "beta": 1.0, "log_base": base, "ally_lift": [], "enemy_lift": []},
    }
    return Model(data)


class SearchTests(unittest.TestCase):
    def test_takes_the_strong_brawler_unless_banned(self):
        m = toy_model()
        r = Searcher(m, 0, set()).run((), (), we_first=True)
        self.assertEqual(r.suggestions[0].picks, (0,))
        self.assertEqual([s.side for s in r.line], ["us", "them", "us", "them"])
        r = Searcher(m, 0, {0}).run((), (), we_first=True)
        self.assertNotIn((0,), [o.picks for o in r.suggestions])

    def test_counter_pick_uses_opponent_model(self):
        m = toy_model()
        # They hold 5. Brawler 1 counters 5 (+1 logit), so it should top our pair options.
        r = Searcher(m, 0, {0}).run((), (5,), we_first=False)
        self.assertIn(1, r.suggestions[0].picks)

    def test_their_turn_is_an_expectation(self):
        m = toy_model()
        r = Searcher(m, 0, set(), settings=Settings(their_n=3)).run((0, 1), (5, 6), we_first=True)
        self.assertEqual(r.side, "us")
        r = Searcher(m, 0, set(), settings=Settings(their_n=3)).run((0, 1, 2), (5, 6), we_first=True)
        self.assertEqual(r.side, "them")
        probs = [o.prob for o in r.suggestions]
        self.assertAlmostEqual(sum(probs), 1.0, places=9)
        expected = sum(o.prob * m.win_prob((0, 1, 2), (5, 6) + o.picks, 0) for o in r.suggestions)
        self.assertAlmostEqual(r.win, expected, places=12)

    def test_allowed_pool(self):
        m = toy_model()
        r = Searcher(m, 0, set(), allowed={2, 3, 4}).run((), (), we_first=True)
        self.assertTrue(all(b in {2, 3, 4} for o in r.suggestions for b in o.picks))

    def test_allowed_pool_falls_back_when_exhausted(self):
        m = toy_model()
        r = Searcher(m, 0, set(), allowed={2}).run((2,), (5, 6), we_first=True)
        self.assertEqual(len(r.suggestions[0].picks), 2)

    def test_bans(self):
        m = toy_model()
        m.g[5] = 1.0          # their most likely pick is now also strong...
        m.mu.clear()          # ...and nothing of ours counters it
        bans = suggest_bans(m, 0, we_first=False, already_banned=set(), n=3)
        self.assertEqual(bans[0][0], 5)
        self.assertGreater(bans[0][2], 0)
        # Banning our own best brawler (0) only hurts us.
        self.assertNotIn(0, [b for b, _, gain in bans if gain > 0])


if __name__ == "__main__":
    unittest.main()
