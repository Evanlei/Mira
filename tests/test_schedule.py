"""Adaptive recrawl timing, parallel fetching and watch mode."""

import time
import unittest
from datetime import datetime, timezone

from mira import crawler, db
from mira.api import BrawlStarsClient

from fakes import FakeClient, entry_3v3

from test_crawler import ALL6, mem_db


def stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y%m%dT%H%M%S.000Z")


def log_over(now: float, hours: float, n: int = 25, idle: float = 0.0) -> list[dict]:
    """n entries evenly spread over ``hours``, newest ``idle`` seconds ago (newest first)."""
    newest = now - idle
    step = hours * 3600 / (n - 1)
    return [{"battleTime": stamp(newest - i * step)} for i in range(n)]


class IntervalTests(unittest.TestCase):
    cap = 6 * 3600

    def test_fast_player_is_recrawled_before_log_turns_over(self):
        now = time.time()
        iv = crawler.recrawl_interval(log_over(now, 2.0), now, self.cap)
        self.assertAlmostEqual(iv, 0.7 * 2 * 3600, delta=60)

    def test_slow_player_hits_cap(self):
        now = time.time()
        self.assertEqual(crawler.recrawl_interval(log_over(now, 48), now, self.cap), self.cap)

    def test_floor(self):
        now = time.time()
        self.assertEqual(crawler.recrawl_interval(log_over(now, 0.1), now, self.cap), crawler.MIN_RECRAWL_SECONDS)

    def test_idle_player_backs_off(self):
        now = time.time()
        active = crawler.recrawl_interval(log_over(now, 1.0), now, self.cap)
        idle = crawler.recrawl_interval(log_over(now, 1.0, idle=3 * 3600), now, self.cap)
        self.assertGreater(idle, active + 3600)

    def test_short_or_bad_logs_use_cap(self):
        now = time.time()
        self.assertEqual(crawler.recrawl_interval([], now, self.cap), self.cap)
        self.assertEqual(crawler.recrawl_interval([{"battleTime": "junk"}] * 3, now, self.cap), self.cap)

    def test_partial_log_extrapolates_to_full_size(self):
        # 13 games in 1h: 24 more would take ~2h.
        now = time.time()
        iv = crawler.recrawl_interval(log_over(now, 1.0, n=13), now, self.cap)
        self.assertAlmostEqual(iv, 0.7 * 2 * 3600, delta=60)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        now = time.time()
        busy = log_over(now, 1.0)
        match = entry_3v3(time=stamp(now))
        self.client = FakeClient({"#AAA1": [match] + busy[1:], **{t: [match] for t in ALL6[1:]}})
        db.enqueue_player(self.conn, "#AAA1", crawler.PRIORITY_SEED)

    def test_next_due_drives_queue(self):
        crawler.crawl(self.conn, self.client)
        rows = dict(self.conn.execute("SELECT tag, next_due - last_crawled FROM players").fetchall())
        self.assertLess(rows["#AAA1"], 3 * 3600)
        self.assertEqual(rows["#AAA2"], 6 * 3600)  # a single game -> capped
        soon = time.time() + 3 * 3600
        self.assertEqual(db.next_players(self.conn, 10, 6 * 3600, now=soon), ["#AAA1"])
        self.assertAlmostEqual(db.earliest_due(self.conn, 6 * 3600),
                               self.conn.execute("SELECT next_due FROM players WHERE tag='#AAA1'").fetchone()[0])

    def test_cap_still_applies_to_stored_next_due(self):
        crawler.crawl(self.conn, self.client)
        # A later, shorter cap wins over a longer stored next_due.
        later = time.time() + 2 * 3600
        self.assertEqual(sorted(db.next_players(self.conn, 10, 3600, now=later)), sorted(ALL6))

    def test_parallel_crawl_matches_sequential(self):
        stats = crawler.crawl(self.conn, self.client, workers=4)
        self.assertEqual(sorted(self.client.calls), sorted(ALL6))
        self.assertEqual(len(self.client.calls), 6)  # nobody fetched twice
        self.assertEqual(stats.players_crawled, 6)
        self.assertEqual(stats.battles_new, 1)
        self.assertIn("queue empty", stats.stop_reason)

    def test_parallel_respects_player_limit(self):
        stats = crawler.crawl(self.conn, self.client, workers=4, max_players=3)
        self.assertEqual(stats.players_crawled, 3)
        self.assertEqual(stats.stop_reason, "player limit")

    def test_watch_waits_then_stops_on_time_limit(self):
        sleeps = []
        stats = crawler.crawl(self.conn, self.client, watch=True, max_minutes=0.001,
                              sleep=lambda s: (sleeps.append(s), time.sleep(min(s, 0.01))))
        self.assertEqual(stats.players_crawled, 6)
        self.assertEqual(stats.stop_reason, "time limit")

    def test_watch_stops_when_asked(self):
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > 20

        stats = crawler.crawl(self.conn, self.client, watch=True, should_stop=stop, sleep=lambda s: None)
        self.assertEqual(stats.stop_reason, "interrupted")


class ThrottleThreadTests(unittest.TestCase):
    def test_concurrent_requests_are_spaced(self):
        import threading
        sent = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"items": []}'

        def opener(req, timeout):
            sent.append(time.monotonic())
            return Resp()

        c = BrawlStarsClient("t", min_interval=0.02, opener=opener)
        threads = [threading.Thread(target=c.battlelog, args=("#AAA1",)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        sent.sort()
        self.assertEqual(c.request_count, 8)
        gaps = [b - a for a, b in zip(sent, sent[1:])]
        self.assertGreaterEqual(min(gaps), 0.015)


if __name__ == "__main__":
    unittest.main()
