import json
import sqlite3
import unittest

from mira import db, pro, proeval

from test_engine import toy_model

PAGE = """{{Infobox league
|name=Test Cup
|sdate=2026-10-01
|edate=2026-10-03
}}
{{Matchlist|id=x
|M1={{Match
    |bestof=3
    |date=October 2, 2026 - 13:00 {{Abbr/CET}}
    |opponent1={{TeamOpponent|Alpha}}
    |opponent2={{TeamOpponent|Beta}}
    |map1={{Map
        |map=Hard Rock Mine|maptype=Gem Grab
        |score1=2|score2=1
        |firstpick=2
        |t1c1=Lily|t1c2=Pam|t1c3=Dyna <!-- opponent1 draft -->
        |t2c1=Nita|t2c2=Chester|t2c3=Kit
        |t1b1=Tara|t1b2=Hank|t1b3=Sandy<ref>source</ref>
        |t2b1=Ruffs|t2b2=Alli|t2b3=Shade
    }}
    |map2={{Map
        |map=Super Beach|maptype=Brawl Ball
        |winner=skip
    }}
    |map3={{Map|map=Split|maptype=Hot Zone|score1=0|score2=1
        |t1c1=Bo|t1c2=Gale|t1c3=Stu|t2c1=Sprout|t2c2=Byron|t2c3=Squeak|firstpick=Alpha}}
}}
|M2={{Match
    |opponent1={{TeamOpponent|Gamma}}|opponent2={{TeamOpponent|Delta}}
    |map1={{Map|map=Split|maptype=Hot Zone|score1=1|score2=0
        |t1c1=Bo|t1c2=Gale|t1c3=Stu|t2c1=Sprout|t2c2=Byron|t2c3=Squeak}}
}}
}}"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.maps = pro.parse_page("Test Cup", PAGE)

    def test_keeps_decided_maps_with_picks(self):
        self.assertEqual([m.key for m in self.maps], ["Test Cup#0#1", "Test Cup#0#3", "Test Cup#1#1"])

    def test_fields(self):
        m = self.maps[0]
        self.assertEqual((m.mode, m.map, m.teams, m.score), ("Gem Grab", "Hard Rock Mine", ("Alpha", "Beta"), (2, 1)))
        self.assertEqual(m.picks, (["Lily", "Pam", "Dyna"], ["Nita", "Chester", "Kit"]))
        self.assertEqual(m.bans, (["Tara", "Hank", "Sandy"], ["Ruffs", "Alli", "Shade"]))
        self.assertEqual(m.played_on, "2026-10-02")
        self.assertEqual(m.first_pick, 1)

    def test_first_pick_by_team_name_and_missing(self):
        self.assertEqual(self.maps[1].first_pick, 0)
        self.assertIsNone(self.maps[2].first_pick)

    def test_date_falls_back_to_the_tournament(self):
        self.assertEqual(self.maps[2].played_on, "2026-10-03")
        self.assertEqual(self.maps[1].bans, ([], []))

    def test_parse_date(self):
        self.assertEqual(pro.parse_date("2025-11-28 - 13:00 {{Abbr/CET}}"), "2025-11-28")
        self.assertEqual(pro.parse_date("June 8, 2022 - 16:30"), "2022-06-08")
        self.assertIsNone(pro.parse_date("TBD"))


class FakeLiquipedia:
    def __init__(self, pages):
        self.pages = pages  # title -> (edited_at, text)
        self.fetched = []

    def draft_pages(self):
        return {t: ts for t, (ts, _) in self.pages.items()}

    def contents(self, titles):
        self.fetched += titles
        return {t: self.pages[t][1] for t in titles}


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)

    def test_fetches_only_new_or_edited_pages(self):
        fake = FakeLiquipedia({"Test Cup": ("t1", PAGE), "Other": ("t1", "")})
        st = pro.sync(self.conn, fake)
        self.assertEqual((st.pages_fetched, st.maps), (2, 3))
        fake.fetched.clear()
        pro.sync(self.conn, fake)
        self.assertEqual(fake.fetched, [])
        fake.pages["Test Cup"] = ("t2", PAGE.replace("|map3=", "|mapx="))
        pro.sync(self.conn, fake)
        self.assertEqual(fake.fetched, ["Test Cup"])
        # Re-fetching a page replaces its maps.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM pro_maps").fetchone()[0], 2)

    def test_brawler_aliases(self):
        self.conn.executemany("INSERT INTO brawlers VALUES (?, ?)",
                              [(1, "DYNAMIKE"), (2, "LARRY & LAWRIE"), (3, "8-BIT"), (4, "EL PRIMO")])
        ids = pro.brawler_ids(self.conn)
        self.assertEqual([ids[pro.norm(n)] for n in ("Dyna", "L&L", "8bit", "Primo", "El Primo")], [1, 2, 3, 4, 4])


def row(picks1, picks2, bans1=(), bans2=(), score=(1, 0), map_name="x"):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT ? AS map, ? AS picks1, ? AS picks2, ? AS bans1, ? AS bans2, ? AS score1, ? AS score2, "
        "NULL AS first_pick, '2026-10-01' AS played_on",
        (map_name, json.dumps(picks1), json.dumps(picks2), json.dumps(list(bans1)), json.dumps(list(bans2)), *score),
    ).fetchone()


class EvalTests(unittest.TestCase):
    def test_resolve_skips_unknown_maps_and_brawlers(self):
        m = toy_model()
        rows = [row(["B0", "B1", "B2"], ["B3", "B4", "B5"]), row(["B0", "B1", "B2"], ["B3", "B4", "Nope"]),
                row(["B0", "B1", "B2"], ["B3", "B4", "B5"], map_name="elsewhere")]
        got, skipped = proeval.resolve(m, rows)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].teams, ((0, 1, 2), (3, 4, 5)))
        self.assertEqual(sum(skipped.values()), 2)

    def test_report(self):
        m = toy_model()
        matches, _ = proeval.resolve(m, [row(["B0", "B1", "B2"], ["B3", "B4", "B5"], ["B6"], ["B7"]),
                                         row(["B0", "B6", "B2"], ["B3", "B4", "B5"], ["B1"], ["B7"], (0, 1))])
        rep = proeval.run(m, matches)
        self.assertEqual(rep.n, 2)
        self.assertEqual(rep.pick_n, 12)
        # The strong brawler 0, held out, is Mira's first choice.
        self.assertGreater(rep.pick_hits["Mira (win model)"][1], 0)
        self.assertIn("Bans", proeval.format_report(rep, None))


if __name__ == "__main__":
    unittest.main()


class RatesTests(unittest.TestCase):
    """Pro rates shrink toward the mode, then Masters (picks) or all pro maps (bans)."""

    def setUp(self):
        from mira.model import prorates
        import numpy as np
        self.np, self.prorates = np, prorates
        self.names = [f"B{i}" for i in range(8)]
        self.maps = [("gemGrab", "x"), ("gemGrab", "y"), ("heist", "z")]
        self.modes = ["gemGrab", "heist"]
        self.masters = np.full((8, 3), 1 / 8)

    def rates(self, rows, **kw):
        return self.prorates.compute(rows, self.names, self.maps, self.modes, self.masters, until="2026-10-10", **kw)

    def test_no_pro_data_falls_back_to_masters(self):
        r = self.rates([])
        self.np.testing.assert_allclose(r.pick, self.masters)

    def test_map_rate_moves_toward_pros_and_spills_to_the_mode(self):
        rows = [dict(dict(row(["B0", "B1", "B2"], ["B3", "B4", "B5"], ["B6"], [], map_name="x")), mode="Gem Grab")] * 10
        r = self.rates(rows)
        self.assertGreater(r.pick[0, 0], r.pick[0, 1])   # picked on x: highest there
        self.assertGreater(r.pick[0, 1], 1 / 8)          # same mode, other map: some spill
        self.assertAlmostEqual(r.pick[0, 2], 1 / 8)      # other mode: untouched
        self.assertGreater(r.ban[6, 0], r.ban[7, 0])     # banned on x
        self.np.testing.assert_allclose(r.pick.sum(axis=0), 1.0)

    def test_old_maps_are_left_out(self):
        rows = [dict(dict(row(["B0", "B1", "B2"], ["B3", "B4", "B5"], ["B6"])), mode="Gem Grab", played_on="2025-01-01")]
        self.np.testing.assert_allclose(self.rates(rows).pick, self.masters)


class EngineProTermsTests(unittest.TestCase):
    def model(self, rho=0.0, ban_lambda=0.0, with_pro=True):
        from mira.engine.model import Model
        data = dict(toy_model().data)
        B = len(data["brawlers"])
        data["ranking"] = {"kappa": 0.0, "gamma": 0.0, "rho": rho, "ban_lambda": ban_lambda,
                           "strength_sd": [[[0.0]] * B]}
        if with_pro:
            data["pro"] = {"log_pick": [[0.0 if b == 3 else -5.0] for b in range(B)],
                           "ban": [[0.9 if b == 7 else 0.0] for b in range(B)]}
        return Model(data)

    def test_rho_favours_what_pros_pick(self):
        m = self.model(rho=0.5)
        self.assertGreater(m.adjust(3, 0), m.adjust(4, 0))
        self.assertEqual(self.model(rho=0.5, with_pro=False).adjust(3, 0), 0.0)

    def test_ban_lambda_lifts_pro_bans(self):
        from mira.engine.search import suggest_bans
        plain = [b for b, _, _ in suggest_bans(self.model(), 0, True, set(), n=3)]
        pro_ = [b for b, _, _ in suggest_bans(self.model(ban_lambda=1.0), 0, True, set(), n=3)]
        self.assertNotIn(7, plain)
        self.assertEqual(pro_[0], 7)


class ChooseTests(unittest.TestCase):
    def test_takes_the_most_pro_like_setting_that_still_wins(self):
        from mira.model import protune
        from mira.model.evaluate import RankingRow
        rows = [RankingRow(0, 0, [0.56], [0.5], [10000], [0.05], 0.0),
                RankingRow(0, 0.05, [0.558], [0.5], [10000], [0.01], 0.0),
                RankingRow(0, 0.05, [0.54], [0.5], [10000], [0.0], 0.2)]
        agree = {(0, 0, 0.0): 0.07, (0, 0.05, 0.0): 0.2, (0, 0.05, 0.2): 0.37}
        best = protune.choose(rows, agree)
        self.assertEqual((best.gamma, best.rho), (0.05, 0.0))  # rho=0.2 wins too rarely in Masters


class TurnRoleTests(unittest.TestCase):
    def test_counts_turns_in_1_2_2_1_order(self):
        from mira.model import turnroles
        from mira.model.roles import ROLES
        r = dict(row(["Crow", "Kaze", "Juju"], ["Gene", "Bull", "Sirius"]))
        r["first_pick"] = 0
        role_of = {"crow": "anti_tank", "kaze": "space_maker", "juju": "thrower",
                   "gene": "control", "bull": "tank", "sirius": "thrower"}
        c = turnroles.counts([r], role_of)
        self.assertEqual(c[0, ROLES.index("anti_tank")], 1)   # turn 1: first team's first pick
        self.assertEqual(c[1, ROLES.index("control")], 1)     # turn 2: second team's first
        self.assertEqual(c[4, ROLES.index("thrower")], 1)     # turn 5: first team's last
        self.assertEqual(c[5, ROLES.index("thrower")], 1)     # turn 6: second team's last

    def test_engine_applies_delta_at_the_turn(self):
        from mira.engine.model import Model
        data = dict(toy_model().data)
        B = len(data["brawlers"])
        data["turn_roles"] = {"roles": [0 if b == 2 else -1 for b in range(B)],
                              "delta": [[0.0]] * 5 + [[3.0]]}
        m = Model(data)
        early = m.pick_probs([], [], set(), 0, turn=0)[2]
        late = m.pick_probs([], [], set(), 0, turn=5)[2]
        self.assertGreater(late, 5 * early)
        self.assertEqual(m.pick_probs([], [], set(), 0)[2], early)  # no turn: no adjustment
