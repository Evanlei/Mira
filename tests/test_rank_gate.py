import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path

from mira import crawler, db
from mira.cli import main

from fakes import FakeClient, entry_3v3, player


def mem_db():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


class RankParsingTests(unittest.TestCase):
    def test_parse_rank(self):
        self.assertEqual(crawler.parse_rank("16"), 16)
        self.assertEqual(crawler.parse_rank("legendary1"), 16)
        self.assertEqual(crawler.parse_rank("Legendary I"), 16)
        self.assertEqual(crawler.parse_rank("masters3"), 21)
        self.assertEqual(crawler.parse_rank("mythic"), 13)
        self.assertEqual(crawler.parse_rank("pro"), 22)
        self.assertEqual(crawler.parse_rank("0"), 0)
        for bad in ("23", "wood", "legendary4"):
            with self.assertRaises(ValueError):
                crawler.parse_rank(bad)

    def test_rank_name(self):
        self.assertEqual(crawler.rank_name(1), "Bronze I")
        self.assertEqual(crawler.rank_name(18), "Legendary III")
        self.assertEqual(crawler.rank_name(22), "Pro")
        self.assertEqual(crawler.rank_name(750), "?")


class TagsFileTests(unittest.TestCase):
    def test_read_tags_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pros.txt"
            p.write_text("# NA pros\n\n#2PP Some Pro\n8qjv,Another Pro\nnot a tag\n#YYY\n")
            tags, skipped = crawler.read_tags_file(str(p))
        self.assertEqual(tags, [("#2PP", "Some Pro"), ("#8QJV", "Another Pro"), ("#YYY", None)])
        self.assertEqual(skipped, 2)

    def test_seed_tags_marks_seeds(self):
        conn = mem_db()
        crawler.seed_tags(conn, [("#2PP", "Pro")])
        row = conn.execute("SELECT priority, is_seed, name FROM players").fetchone()
        self.assertEqual(tuple(row), (crawler.PRIORITY_SEED, 1, "Pro"))


class RankGateTests(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        # Seed #P plays one Ranked game: teammates rank 20 & 12, opponents 19, 16, 15.
        seed_team = [player("#P", "SHELLY", 16000000, trophies=21),
                     player("#HI", "COLT", 16000001, trophies=20),
                     player("#L0", "BULL", 16000002, trophies=12)]
        opp = [player("#0PP1", "BROCK", 16000003, trophies=19),
               player("#0PP2", "RICO", 16000004, trophies=16),
               player("#0PP3", "SPIKE", 16000005, trophies=15)]
        trophy_game_team = [player("#P", "SHELLY", 16000000, trophies=900),
                            player("#TR1", "COLT", 16000001, trophies=900),
                            player("#TR2", "BULL", 16000002, trophies=900)]
        trophy_opp = [player(f"#TR{i}", "RICO", 16000004, trophies=900) for i in (3, 8, 9)]
        self.client = FakeClient({
            "#P": [entry_3v3(teams=[seed_team, opp]),
                   entry_3v3(time="20261118T090000.000Z", btype="ranked", teams=[trophy_game_team, trophy_opp])],
        })
        crawler.seed_tags(self.conn, [("#P", "Pro")])

    def queued(self):
        return {r[0] for r in self.conn.execute("SELECT tag FROM players")}

    def test_only_high_rank_players_queued(self):
        stats = crawler.crawl(self.conn, self.client, max_players=1, min_rank=16)
        self.assertEqual(self.queued(), {"#P", "#HI", "#0PP1", "#0PP2"})
        self.assertEqual(stats.players_below_rank, 2)
        self.assertEqual(stats.players_unranked_skipped, 5)
        ranks = dict(self.conn.execute("SELECT tag, max_rank FROM players").fetchall())
        self.assertEqual(ranks, {"#P": 21, "#HI": 20, "#0PP1": 19, "#0PP2": 16})
        # Both battles are still stored; the gate only affects the queue.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM battles").fetchone()[0], 2)

    def test_ranked_only_skips_other_types(self):
        stats = crawler.crawl(self.conn, self.client, max_players=1, min_rank=19, ranked_only=True)
        types = [r[0] for r in self.conn.execute("SELECT battle_type FROM battles")]
        self.assertEqual(types, ["soloRanked"])
        self.assertEqual(stats.battles_other_types, 1)
        # Masters gate: only the rank-20 teammate and rank-19 opponent are queued.
        self.assertEqual(self.queued(), {"#P", "#HI", "#0PP1"})

    def test_match_min_rank_only_stores_all_masters_matches(self):
        all_masters = entry_3v3(time="20261118T080000.000Z", teams=[
            [player("#P", "SHELLY", 16000000, trophies=21), player("#M1", "COLT", 16000001, trophies=19),
             player("#M2", "BULL", 16000002, trophies=22)],
            [player("#M3", "BROCK", 16000003, trophies=19), player("#M4", "RICO", 16000004, trophies=20),
             player("#M5", "SPIKE", 16000005, trophies=19)]])
        self.client.logs["#P"].append(all_masters)
        stats = crawler.crawl(self.conn, self.client, max_players=1, min_rank=19,
                              ranked_only=True, match_min_rank=19)
        times = [r[0] for r in self.conn.execute("SELECT battle_time FROM battles")]
        self.assertEqual(times, ["2026-11-18T08:00:00Z"])
        self.assertEqual(stats.battles_below_rank, 1)
        # The mixed-rank match still fed the queue with its Masters players.
        self.assertTrue({"#HI", "#0PP1", "#M1", "#M5"} <= self.queued())
        self.assertNotIn("#L0", self.queued())

    def test_gate_disabled_queues_everyone(self):
        crawler.crawl(self.conn, self.client, max_players=1, min_rank=None)
        self.assertEqual(len(self.queued()), 11)

    def test_queue_skips_previously_queued_low_rank_players(self):
        db.enqueue_player(self.conn, "#L0W", crawler.PRIORITY_RANKED, rank=10)
        db.enqueue_player(self.conn, "#N0RANK", crawler.PRIORITY_OTHER)
        db.enqueue_player(self.conn, "#G00D", crawler.PRIORITY_RANKED, rank=18)
        due = db.next_players(self.conn, 10, 3600, min_rank=16)
        self.assertEqual(set(due), {"#P", "#G00D"})
        self.assertEqual(len(db.next_players(self.conn, 10, 3600)), 4)

    def test_seed_exempt_and_rank_only_rises(self):
        db.record_rank(self.conn, "#P", 3)
        self.assertIn("#P", db.next_players(self.conn, 10, 3600, min_rank=16))
        db.record_rank(self.conn, "#P", 18)
        db.record_rank(self.conn, "#P", 5)
        self.assertEqual(self.conn.execute("SELECT max_rank FROM players").fetchone()[0], 18)

    def test_record_rank_does_not_enqueue(self):
        db.record_rank(self.conn, "#UNKN0WN", 20)
        self.assertNotIn("#UNKN0WN", self.queued())


class MigrationTests(unittest.TestCase):
    def test_old_players_table_gets_new_columns(self):
        conn = db.connect(":memory:")
        conn.execute("CREATE TABLE players (tag TEXT PRIMARY KEY, name TEXT, priority INTEGER NOT NULL DEFAULT 0, "
                     "status TEXT NOT NULL DEFAULT 'pending', discovered_at REAL NOT NULL, last_crawled REAL, "
                     "crawl_count INTEGER NOT NULL DEFAULT 0, ranked_seen INTEGER NOT NULL DEFAULT 0, last_error TEXT)")
        conn.execute("INSERT INTO players (tag, discovered_at) VALUES ('#X', ?)", (time.time(),))
        db.init_db(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(players)")}
        self.assertTrue({"max_rank", "is_seed"} <= cols)
        db.init_db(conn)  # idempotent


class CliSeedTests(unittest.TestCase):
    def test_seed_requires_a_source(self):
        with tempfile.TemporaryDirectory() as d:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(["--db", str(Path(d) / "t.db"), "seed"])
        self.assertEqual(code, 1)
        self.assertIn("--tags-file", err.getvalue())

    def test_stats_shows_rank_tables(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "t.db")
            conn = db.connect(path)
            db.init_db(conn)
            gate = RankGateTests("test_only_high_rank_players_queued")
            gate.setUp()
            crawler.seed_tags(conn, [("#P", "Pro")])
            crawler.crawl(conn, gate.client, max_players=1, min_rank=16)
            db.record_rank(conn, "#P", 9)  # no effect: rank only rises
            conn.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--db", path, "stats"]), 0)
        text = out.getvalue()
        self.assertIn("Players by observed Ranked rank", text)
        self.assertIn("Masters III", text)
        self.assertNotIn("Seeds seen below the min rank", text)


if __name__ == "__main__":
    unittest.main()


class LobbyRankTests(unittest.TestCase):
    """Every Ranked match of a crawled player is stored by default, tagged with its lobby rank."""

    def setUp(self):
        self.conn = mem_db()
        mixed = entry_3v3(time="20261118T090000.000Z", teams=[
            [player("#P", "SHELLY", 16000000, trophies=21), player("#M1", "COLT", 16000001, trophies=19),
             player("#M2", "BULL", 16000002, trophies=17)],
            [player("#M3", "BROCK", 16000003, trophies=19), player("#M4", "RICO", 16000004, trophies=20),
             player("#M5", "SPIKE", 16000005, trophies=19)]])
        masters = entry_3v3(time="20261118T080000.000Z", teams=[
            [player("#P", "SHELLY", 16000000, trophies=21), player("#M1", "COLT", 16000001, trophies=19),
             player("#M2", "BULL", 16000002, trophies=22)],
            [player("#M3", "BROCK", 16000003, trophies=19), player("#M4", "RICO", 16000004, trophies=20),
             player("#M5", "SPIKE", 16000005, trophies=19)]])
        self.client = FakeClient({"#P": [mixed, masters, entry_3v3(time="20261118T070000.000Z", btype="ranked")]})
        db.enqueue_player(self.conn, "#P", crawler.PRIORITY_SEED, seed=True)

    def rows(self):
        return [tuple(r) for r in self.conn.execute(
            "SELECT battle_time, battle_type, lobby_rank FROM battles ORDER BY battle_time")]

    def test_default_stores_only_all_masters_lobbies(self):
        crawler.crawl(self.conn, self.client, max_players=1, min_rank=19, ranked_only=True,
                      match_min_rank=crawler.DEFAULT_MATCH_MIN_RANK)
        self.assertEqual(self.rows(), [("2026-11-18T08:00:00Z", "soloRanked", 19)])

    def test_lower_lobbies_stored_with_rank_when_gate_off(self):
        crawler.crawl(self.conn, self.client, max_players=1, min_rank=19, ranked_only=True, match_min_rank=None)
        self.assertEqual(self.rows(), [("2026-11-18T08:00:00Z", "soloRanked", 19),
                                       ("2026-11-18T09:00:00Z", "soloRanked", 17)])

    def test_migration_backfills_lobby_rank(self):
        crawler.crawl(self.conn, self.client, max_players=1, ranked_only=True)
        self.conn.execute("UPDATE battles SET lobby_rank = NULL")
        # Simulate an old database: drop the column, then let init_db add and backfill it.
        self.conn.execute("ALTER TABLE battles DROP COLUMN lobby_rank")
        db.init_db(self.conn)
        self.assertEqual([r[2] for r in self.rows()], [19, 17])

    def test_readiness_counts_only_all_masters(self):
        from mira import readiness
        crawler.crawl(self.conn, self.client, max_players=1, ranked_only=True)
        r = readiness.compute(self.conn, target=10)
        self.assertEqual(sum(m.matches for m in r.pool), 1)
        self.assertEqual(sum(m.matches for m in readiness.compute(self.conn, min_lobby_rank=16).pool), 2)
