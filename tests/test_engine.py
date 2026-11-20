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


class TierTests(unittest.TestCase):
    """Per-tier strength: learned where a tier's games show it, and reproduced by the engine."""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(7)
        m = synthetic(n=6000, seed=5, effects=False)
        m.lobby_rank = np.full(len(m), 19, dtype=np.int32)
        m.lobby_mean = rng.choice([19.0, 21.0], size=len(m))
        # At Masters III+, brawler 0 is much stronger than elsewhere.
        top = m.lobby_mean >= 20.5
        has0 = (m.teams[:, 0, :] == 0).any(axis=1)
        flip = top & has0 & (rng.random(len(m)) < 0.6)
        m.y = np.where(flip, 1.0, m.y)
        cls.m = m
        cls.win = WinModel.fit(m, l2={"tier": 30, "tier_mode": 100})
        cls.pick = PickModel.fit(m)
        cls.data = json.loads(json.dumps(export.to_dict(
            cls.win, m, export.game_counts(m), extra={"pick_model": export.pick_model_dict(cls.pick, threshold=0)},
            threshold=0)))

    def test_tier_effect_is_learned(self):
        t = self.win.tables()["tier"]
        self.assertGreater(t[0, 3] - t[0, 1], 0.3)
        # Brawlers without a tier effect stay near the shared strength.
        self.assertLess(np.abs(t[5:, 3] - t[5:, 1]).max(), 0.2)

    def test_engine_matches_numpy_per_tier(self):
        for tier, mean in ((1, 19.0), (3, 21.0)):
            engine = Model(self.data, tier=tier)
            x = one(self.m, [0, 7, 9], [4, 11, 13], 2)
            x.lobby_mean = np.array([mean])
            self.assertAlmostEqual(engine.win_prob([0, 7, 9], [4, 11, 13], 2), self.win.predict(x)[0], places=3)

    def test_default_tier_is_masters_one(self):
        self.assertEqual(Model(self.data).tier, 1)
        self.assertEqual(self.data["tiers"][3], "Masters III+")

    def test_pick_rates_per_tier(self):
        engine = Model(self.data, tier=3)
        got = engine.pick_probs([], [], set(), 0)
        expected = self.pick.probs(0, [], [], set(), tier=3)
        for b, p in got.items():
            self.assertAlmostEqual(p, expected[b], places=3)


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


class RankingTests(unittest.TestCase):
    """Uncertainty penalty and pick-rate prior: they change which of our picks wins, never a win %."""

    def model(self, kappa=0.0, gamma=0.0):
        # Brawler 1 has a slightly higher estimate than 2, but few games (wide sd) and a tiny pick rate.
        B = 8
        base = [[-2.0] for _ in range(B)]
        base[1][0] = -8.0
        data = {
            "brawlers": [{"id": i, "name": f"B{i}"} for i in range(B)],
            "modes": ["m"], "maps": [{"mode": "m", "map": "x"}],
            "win_model": {"global": [0.0, 0.32, 0.30] + [0.0] * (B - 3), "mode": [[0.0]] * B, "map": [[0.0]] * B,
                          "synergy": [], "synergy_mode": [], "matchup": [], "matchup_mode": []},
            "pick_model": {"alpha": 1.0, "beta": 1.0, "log_base": base, "ally_lift": [], "enemy_lift": []},
            "ranking": {"kappa": kappa, "gamma": gamma,
                        "strength_sd": [[[0.05]] + [[0.20]] + [[0.03]] * (B - 2)]},
        }
        return Model(data)

    def top(self, m):
        return Searcher(m, 0, set()).run((3, 4), (5, 6, 7), we_first=False).suggestions[0]

    def test_plain_ranking_takes_the_higher_estimate(self):
        self.assertEqual(self.top(self.model()).picks, (1,))

    def test_uncertainty_penalty_prefers_the_well_measured_brawler(self):
        self.assertEqual(self.top(self.model(kappa=1.0)).picks, (2,))

    def test_pick_rate_prior_prefers_what_players_pick(self):
        self.assertEqual(self.top(self.model(gamma=0.05)).picks, (2,))

    def test_reported_win_is_the_plain_model(self):
        m = self.model(kappa=1.0, gamma=0.05)
        o = self.top(m)
        self.assertAlmostEqual(o.win, m.win_prob((3, 4) + o.picks, (5, 6, 7), 0), places=12)
        r = Searcher(m, 0, set()).run((3, 4), (5, 6, 7), we_first=False)
        self.assertEqual(r.win, r.suggestions[0].win)  # the root value is the option we take

    def test_old_files_without_ranking_rank_as_before(self):
        m = self.model(kappa=1.0, gamma=0.05)
        del m.data["ranking"]
        self.assertEqual(self.top(Model(m.data)).picks, (1,))


class StrengthSdTests(unittest.TestCase):
    def test_fewer_games_means_wider_error(self):
        m = synthetic(n=4000, seed=3, effects=False)
        # Make brawler 7 rare on map 0: swap it out of most of its map-0 games.
        rng = np.random.default_rng(0)
        for i in np.flatnonzero(m.map_idx == 0):
            if (m.teams[i] == 7).any() and rng.random() < 0.9:
                free = [b for b in range(m.n_brawlers) if b not in m.teams[i]]
                m.teams[i][m.teams[i] == 7] = free[0]
        win = WinModel.fit(m)
        sd = win.strength_sd(m)
        self.assertEqual(sd.shape, (win.layout.n_tiers, m.n_brawlers, len(m.maps)))
        others = np.delete(sd[1, :, 0], 7)
        self.assertGreater(sd[1, 7, 0], others.max())
        self.assertGreater(sd[1, 7, 0], sd[1, 7, 1])  # brawler 7 is still common on map 1
        self.assertTrue(np.all(sd > 0))

    def test_exported_and_tuned(self):
        from mira.model import evaluate
        m = synthetic(n=3000, seed=4)
        win, pick = WinModel.fit(m), PickModel.fit(m)
        sd = win.strength_sd(m)
        games = np.array(export.game_counts(m)["brawler_map"])
        rows = evaluate.ranking_report(win, pick.log_base_tier, sd, games, m, kappas=(0.0, 1.0), gammas=(0.0, 0.05))
        self.assertEqual(len(rows), 4)
        best = evaluate.choose_ranking(rows)
        self.assertIn(best, rows)
        data = export.to_dict(win, m, export.game_counts(m), extra={
            "pick_model": export.pick_model_dict(pick), "ranking": export.ranking_dict(best.kappa, best.gamma, sd)})
        e = Model(json.loads(json.dumps(data)))
        self.assertEqual((e.kappa, e.gamma), (best.kappa, best.gamma))
        self.assertAlmostEqual(e.sd_of(0, 0), sd[e.tier, 0, 0], places=3)


if __name__ == "__main__":
    unittest.main()
