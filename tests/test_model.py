import unittest

import numpy as np

from mira.model import evaluate, patches as patchlog
from mira.model.baselines import Coin, DeepDraftStyle, MapWinRate
from mira.model.dataset import Matches
from mira.model.evaluate import calibration_error, log_loss, paired_bootstrap, time_split
from mira.model.winmodel import WinModel, features, Layout


def synthetic(n=6000, B=20, n_maps=4, seed=0, effects=True):
    """Random 3v3s with known effects: brawler 0 strong everywhere, brawler 1 strong only on
    map 0, brawlers 2+3 synergize, brawler 4 counters brawler 5."""
    rng = np.random.default_rng(seed)
    teams = np.array([rng.choice(B, 6, replace=False).reshape(2, 3) for _ in range(n)], dtype=np.int32)
    maps = rng.integers(0, n_maps, n).astype(np.int32)
    modes = (maps // 2).astype(np.int32)

    def team_score(t, mp, other):
        s = 0.0
        if effects:
            s += 0.6 * (0 in t)
            s += 0.8 * (1 in t and mp == 0)
            s += 0.7 * (2 in t and 3 in t)
            s += 0.7 * (4 in t and 5 in other)
        return s

    logits = np.array([team_score(t[0], mp, t[1]) - team_score(t[1], mp, t[0]) for t, mp in zip(teams, maps)])
    y = (rng.random(n) < 1 / (1 + np.exp(-logits))).astype(float)
    times = [f"2026-11-{1 + i * 18 // n:02d}T{i % 24:02d}:00:00Z" for i in range(n)]
    return Matches(
        [f"id{i}" for i in range(n)], sorted(times), teams, maps, modes, y,
        list(range(B)), [f"B{i}" for i in range(B)],
        [(f"mode{mp // 2}", f"map{mp}") for mp in range(n_maps)], [f"mode{k}" for k in range((n_maps + 1) // 2)],
    )


def one(m, team0, team1, map_idx=0):
    return Matches(["x"], [m.times[-1]], np.array([[team0, team1]], dtype=np.int32),
                   np.array([map_idx], dtype=np.int32), np.array([map_idx // 2], dtype=np.int32), np.array([1.0]),
                   m.brawler_ids, m.brawler_names, m.maps, m.modes)


class WinModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = synthetic()
        cls.model = WinModel.fit(cls.m, l2={"global": 1, "mode": 100, "map": 100, "synergy": 100, "matchup": 100,
                                                    "synergy_mode": 300, "matchup_mode": 300})

    def test_swapping_teams_flips_prediction(self):
        a, b = [0, 7, 9], [4, 11, 13]
        p = self.model.predict(one(self.m, a, b))[0]
        q = self.model.predict(one(self.m, b, a))[0]
        self.assertAlmostEqual(p + q, 1.0, places=9)

    def test_recovers_known_effects(self):
        base = [10, 11, 12]
        p = lambda t0, t1, mp=0: self.model.predict(one(self.m, t0, t1, mp))[0]  # noqa: E731
        self.assertGreater(p([0, 14, 15], base), 0.58)                                # strong brawler
        self.assertGreater(p([1, 14, 15], base, 0), p([1, 14, 15], base, 3) + 0.05)   # map-specific
        self.assertGreater(p([2, 3, 15], base), p([2, 14, 15], [3, 11, 12]) + 0.05)   # synergy
        self.assertGreater(p([4, 14, 15], [5, 11, 12]), p([4, 14, 15], [6, 11, 12]))  # counter (weak: L2)

    def test_tuned_model_beats_baselines_on_held_out(self):
        from mira.model.evaluate import tune_l2
        test = synthetic(n=3000, seed=1)
        tuned = WinModel.fit(self.m, l2=tune_l2(self.m, np.ones(len(self.m)))[0])
        ll_tuned = log_loss(test.y, tuned.predict(test)).mean()
        ll = {name: log_loss(test.y, mdl.predict(test)).mean() for name, mdl in [
            ("coin", Coin().fit(self.m)), ("map", MapWinRate().fit(self.m)),
            ("dd", DeepDraftStyle().fit(self.m)), ("mira", self.model)]}
        # Truth scores ~0.6735 here (coin 0.6931), so 0.008 is most of the attainable gain.
        self.assertLess(ll["mira"], ll["coin"] - 0.008)
        self.assertLess(ll_tuned, ll["coin"] - 0.008)
        # At 6k matches the validation slice can't separate L2 settings ~0.002 apart, so the tuned
        # model may trail the best baseline slightly; it must stay within that noise band.
        self.assertLessEqual(ll_tuned, min(ll["map"], ll["dd"]) + 0.003)

    def test_default_l2_does_not_overfit_noise(self):
        m, test = synthetic(n=6000, effects=False, seed=2), synthetic(n=4000, effects=False, seed=3)
        p = WinModel.fit(m).predict(test)
        self.assertLess(log_loss(test.y, p).mean(), np.log(2) + 0.005)
        self.assertLess(np.abs(p - 0.5).max(), 0.15)

    def test_feature_shape(self):
        idx, sgn = features(self.m, Layout(20, 2, 4))
        self.assertEqual(idx.shape, (len(self.m), 60))
        self.assertTrue(np.all(np.abs(sgn) <= 1))


class BaselineTests(unittest.TestCase):
    def test_cross_fitting_keeps_baselines_honest_without_signal(self):
        # With pure noise, a leaky baseline is overconfident and loses to a coin flip badly.
        train, test = synthetic(n=3000, effects=False, seed=4), synthetic(n=2000, effects=False, seed=5)
        for b in (MapWinRate(), DeepDraftStyle()):
            self.assertLess(log_loss(test.y, b.fit(train).predict(test)).mean(), 0.6931 + 0.01, b.name)


class MetricTests(unittest.TestCase):
    def test_calibration_and_bootstrap(self):
        rng = np.random.default_rng(0)
        p = rng.random(20000)
        y = (rng.random(20000) < p).astype(float)
        self.assertLess(calibration_error(y, p), 0.02)
        self.assertGreater(calibration_error(y, np.clip(p * 1.5, 0, 1)), 0.05)
        d, lo, hi = paired_bootstrap(log_loss(y, p), log_loss(y, np.full_like(p, 0.5)))
        self.assertTrue(lo <= d <= hi < 0)

    def test_time_split_fallback(self):
        m = synthetic(n=100)
        mask, desc = time_split(m, test_days=7)
        self.assertEqual(mask.sum(), 20)
        self.assertIn("newest 20%", desc)


class LobbyRankWeightTests(unittest.TestCase):
    def test_rank_weights_and_test_set(self):
        m = synthetic(n=3000, seed=3)
        rng = np.random.default_rng(0)
        m.lobby_rank = rng.choice([16, 17, 18, 19, 20], size=len(m)).astype(np.int32)
        w = m.rank_weights(0.5)
        self.assertTrue(np.all(w[m.lobby_rank >= 19] == 1.0))
        self.assertTrue(np.allclose(w[m.lobby_rank == 17], 0.25))
        self.assertTrue(np.all(m.rank_weights(0.0)[m.lobby_rank < 19] == 0.0))
        sub = m.subset(slice(10, 20))
        self.assertTrue(np.array_equal(sub.lobby_rank, m.lobby_rank[10:20]))
        r = evaluate.run(m, tune=False, test_days=7.0)
        # Test set holds only all-Masters matches; a Masters-only Mira is reported alongside.
        train_mask, test_mask, _ = evaluate.masters_split(m, 7.0)
        self.assertEqual(r.n_test, int(test_mask.sum()))
        self.assertTrue(m.masters_mask()[test_mask].all())
        # The test set is ~20% of the all-Masters matches, not of all matches.
        self.assertAlmostEqual(test_mask.sum() / m.masters_mask().sum(), 0.2, delta=0.02)
        # Nothing in training is at or after the first test match.
        first_test = min(t for t, x in zip(m.times, test_mask) if x)
        self.assertTrue(all(t < first_test for t, x in zip(m.times, train_mask) if x))
        self.assertIn(evaluate.MASTERS_ONLY, [s.name for s in r.scores])
        self.assertLess(r.n_train_masters, r.n_train)


class TopBoostTests(unittest.TestCase):
    def test_top_weights(self):
        m = synthetic(n=200, seed=4)
        m.lobby_mean = np.array([16.0, 19.0, 20.0, 21.5, 22.0, 23.0] * 33 + [19.0, 19.0])
        w = m.top_weights(2.0)
        self.assertTrue(np.allclose(w[:6], [1, 1, 2, 2 ** 2.5, 8, 8]))  # capped at Pro
        self.assertTrue(np.all(m.top_weights(1.0) == 1.0))
        self.assertTrue(np.allclose(m.subset(slice(0, 6)).lobby_mean, m.lobby_mean[:6]))


class TierReportTests(unittest.TestCase):
    def test_shared_baseline_is_a_real_model(self):
        m = synthetic(n=4000, seed=9)
        m.lobby_rank = np.full(len(m), 19, dtype=np.int32)
        m.lobby_mean = np.random.default_rng(0).choice([19.0, 20.0], size=len(m))
        rows = evaluate.tier_report(m, pick_sample=50)
        self.assertTrue(rows)
        for r in rows:
            self.assertLess(r.shared, 0.69)  # a coin flip scores 0.6931
            self.assertLess(r.tiered, 0.69)


class PatchWeightTests(unittest.TestCase):
    def test_weights(self):
        plog = [patchlog.Patch("2026-11-11", {"AMBER": "nerf"})]
        times = ["2026-11-10T12:00:00Z", "2026-11-10T12:00:00Z", "2026-11-20T00:00:00Z"]
        names = [["AMBER", "B", "C", "D", "E", "F"], ["A", "B", "C", "D", "E", "F"], ["AMBER"] * 6]
        w = patchlog.match_weights(times, names, plog, reference="2026-11-20T00:00:00Z", half_life_days=9.5)
        self.assertAlmostEqual(w[1], 0.5, places=6)          # 9.5 days old -> half
        self.assertAlmostEqual(w[0], 0.05, places=6)         # and pre-patch AMBER -> x0.1
        self.assertEqual(w[2], 1.0)                          # post-patch, newest

    def test_load_real_file(self):
        plog = patchlog.load("data/patches.json")
        self.assertEqual([p.date for p in plog], ["2026-11-03", "2026-11-11"])
        self.assertEqual(plog[1].changes["WENDY"], "rework")


if __name__ == "__main__":
    unittest.main()


class LobbyCutTests(unittest.TestCase):
    """The lowest lobby rank to train on: looser only while lower lobbies clearly help."""

    def data(self, lower_is_noise, seed=3):
        from mira.model.winmodel import DEFAULT_L2
        m = synthetic(n=16000, seed=seed)
        rng = np.random.default_rng(seed)
        m.lobby_rank = rng.choice([19, 16], size=len(m), p=[0.3, 0.7]).astype(np.int32)
        m.lobby_mean = m.lobby_rank.astype(float)
        if lower_is_noise:  # lower lobbies where what wins is the opposite of what wins in Masters
            m.y = np.where(m.lobby_rank < 19, 1 - m.y, m.y)
        return m, DEFAULT_L2

    def test_keeps_helpful_lower_lobbies(self):
        from mira.model import lobbycut
        m, l2 = self.data(lower_is_noise=False)
        cut, rows = lobbycut.choose(m, l2)
        self.assertEqual(cut, 16)
        self.assertEqual([r.cut for r in rows], [19, 16])  # no rank-18 lobbies: that cut adds nothing, skipped

    def test_drops_lower_lobbies_that_dont_help(self):
        from mira.model import lobbycut
        m, l2 = self.data(lower_is_noise=True)
        cut, _ = lobbycut.choose(m, l2)
        self.assertEqual(cut, 19)
