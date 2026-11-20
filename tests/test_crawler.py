import time
import unittest

from mira import crawler, db

from fakes import FakeClient, entry_3v3, entry_showdown, player

ALL6 = ["#AAA1", "#AAA2", "#AAA3", "#BBB1", "#BBB2", "#BBB3"]


def mem_db():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class SeedTests(unittest.TestCase):
    def test_seed_queues_rankings(self):
        conn = mem_db()
        client = FakeClient(rankings={"global": [{"tag": "#aaa1", "name": "x"}, {"tag": "#AAA2"}]})
        self.assertEqual(crawler.seed(conn, client, ["global"]), 2)
        rows = conn.execute("SELECT tag, priority FROM players ORDER BY tag").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("#AAA1", crawler.PRIORITY_SEED), ("#AAA2", crawler.PRIORITY_SEED)])


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        match = entry_3v3(result="victory")
        loser_view = entry_3v3(result="defeat")
        self.logs = {
            "#AAA1": [match, entry_showdown()],
            **{t: [match] for t in ["#AAA2", "#AAA3"]},
            **{t: [loser_view] for t in ["#BBB1", "#BBB2", "#BBB3"]},
        }
        self.client = FakeClient(self.logs)

    def test_bfs_dedups_and_stores(self):
        db.enqueue_player(self.conn, "#AAA1", crawler.PRIORITY_SEED)
        stats = crawler.crawl(self.conn, self.client)
        self.assertEqual(sorted(self.client.calls), sorted(ALL6))
        self.assertEqual(count(self.conn, "battles"), 1)
        self.assertEqual(count(self.conn, "battle_players"), 6)
        self.assertEqual(stats.battles_new, 1)
        self.assertEqual(stats.battles_parsed, 6)
        self.assertIn("queue empty", stats.stop_reason)
        # Showdown players are not enqueued.
        self.assertEqual(count(self.conn, "players"), 6)
        winner = self.conn.execute("SELECT winning_team, is_draw FROM battles").fetchone()
        self.assertEqual(tuple(winner), (0, 0))
        names = {r[0] for r in self.conn.execute("SELECT name FROM brawlers")}
        self.assertEqual(names, {"SHELLY", "COLT", "BULL", "BROCK", "RICO", "SPIKE"})

    def test_ranked_players_get_priority(self):
        self.client.logs["#AAA1"] = [
            entry_3v3(btype="ranked", teams=[[player("#AAA1", "S", 1), player("#T1", "S", 1), player("#T2", "S", 1)],
                                             [player("#T3", "S", 1), player("#T4", "S", 1), player("#T5", "S", 1)]]),
            entry_3v3(time="20261118T110000.000Z", btype="soloRanked"),
        ]
        db.enqueue_player(self.conn, "#AAA1", crawler.PRIORITY_SEED)
        crawler.crawl(self.conn, self.client, max_players=1)
        prio = dict(self.conn.execute("SELECT tag, priority FROM players").fetchall())
        self.assertEqual(prio["#T1"], crawler.PRIORITY_OTHER)
        self.assertEqual(prio["#BBB1"], crawler.PRIORITY_RANKED)
        # Ranked-discovered players come out of the queue before trophy-ladder ones,
        # even though the trophy-ladder battle was parsed first.
        nxt = db.next_players(self.conn, 5, crawler.DEFAULT_RECRAWL_SECONDS)
        self.assertEqual(set(nxt), {"#AAA2", "#AAA3", "#BBB1", "#BBB2", "#BBB3"})

    def test_ranked_types_configurable(self):
        db.enqueue_player(self.conn, "#AAA1", crawler.PRIORITY_SEED)
        crawler.crawl(self.conn, self.client, max_players=1, ranked_types=frozenset({"ranked"}))
        prio = dict(self.conn.execute("SELECT tag, priority FROM players WHERE tag != '#AAA1'").fetchall())
        self.assertTrue(all(p == crawler.PRIORITY_OTHER for p in prio.values()))

    def test_priority_never_drops(self):
        db.enqueue_player(self.conn, "#X", crawler.PRIORITY_RANKED)
        db.enqueue_player(self.conn, "#X", crawler.PRIORITY_OTHER)
        self.assertEqual(self.conn.execute("SELECT priority FROM players").fetchone()[0], crawler.PRIORITY_RANKED)

    def test_recrawl_window(self):
        db.enqueue_player(self.conn, "#AAA1", crawler.PRIORITY_SEED)
        crawler.crawl(self.conn, self.client)
        n = len(self.client.calls)
        crawler.crawl(self.conn, self.client)  # everyone crawled just now -> nothing due
        self.assertEqual(len(self.client.calls), n)
        later = time.time() + 6 * 3600 + 1
        self.assertEqual(len(db.next_players(self.conn, 10, 6 * 3600, now=later)), 6)

    def test_missing_player_marked_and_skipped(self):
        db.enqueue_player(self.conn, "#GONE", crawler.PRIORITY_SEED)
        stats = crawler.crawl(self.conn, self.client)
        self.assertEqual(stats.players_missing, 1)
        self.assertEqual(self.conn.execute("SELECT status FROM players").fetchone()[0], "missing")
        self.assertEqual(db.next_players(self.conn, 10, 0, now=time.time() + 10**6), [])

    def test_limits_and_stop(self):
        db.enqueue_player(self.conn, "#AAA1", crawler.PRIORITY_SEED)
        stats = crawler.crawl(self.conn, self.client, max_players=2)
        self.assertEqual(stats.players_crawled, 2)
        self.assertEqual(stats.stop_reason, "player limit")
        stats = crawler.crawl(self.conn, self.client, should_stop=lambda: True)
        self.assertEqual((stats.players_crawled, stats.stop_reason), (0, "interrupted"))
        stats = crawler.crawl(self.conn, self.client, max_minutes=0)
        self.assertEqual(stats.stop_reason, "time limit")


if __name__ == "__main__":
    unittest.main()
