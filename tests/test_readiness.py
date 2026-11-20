import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from mira import db, readiness
from mira.cli import main
from mira.parse import parse_battle

from fakes import entry_3v3, player


def add(conn, n, map_, mode, day, start=0):
    """Insert n distinct all-Masters soloRanked matches on `map_` dated 2026-11-<day>."""
    for i in range(start, start + n):
        teams = [[player(f"#Q{map_[:2]}{i}{j}".upper().replace(" ", ""), "SHELLY", 1, trophies=19) for j in range(3)],
                 [player(f"#L{map_[:2]}{i}{j}".upper().replace(" ", ""), "COLT", 2, trophies=19) for j in range(3)]]
        e = entry_3v3(time=f"202611{day:02d}T{i // 60 % 24:02d}{i % 60:02d}00.000Z", mode=mode, map_=map_, teams=teams)
        db.insert_battle(conn, parse_battle(e, teams[0][0]["tag"]), source_tag="#X")


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)

    def test_empty(self):
        r = readiness.compute(self.conn)
        self.assertIsNone(r.reference_time)
        self.assertFalse(r.ready)

    def test_pool_progress_and_retired(self):
        add(self.conn, 5, "Hard Rock Mine", "gemGrab", day=19)
        add(self.conn, 2, "Pinhole Punt", "brawlBall", day=15)
        add(self.conn, 9, "Old Map", "heist", day=1)  # > 7 days before newest -> retired
        r = readiness.compute(self.conn, target=4, pool_days=7)
        self.assertEqual([m.map for m in r.pool], ["Pinhole Punt", "Hard Rock Mine"])  # thinnest first
        self.assertEqual([m.map for m in r.retired], ["Old Map"])
        self.assertFalse(r.ready)
        self.assertEqual(r.total_needed, 2)
        self.assertAlmostEqual(r.overall_progress, (0.5 + 1.0) / 2)
        add(self.conn, 2, "Pinhole Punt", "brawlBall", day=15, start=100)
        self.assertTrue(readiness.compute(self.conn, target=4).ready)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "t.db")
            conn = db.connect(path)
            db.init_db(conn)
            add(conn, 3, "Hard Rock Mine", "gemGrab", day=19)
            conn.commit()
            conn.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--db", path, "readiness", "--target", "6"]), 0)
        text = out.getvalue()
        self.assertIn("not ready: 0/1 maps", text)
        self.assertIn("Hard Rock Mine", text)
        self.assertIn("50%", text)


if __name__ == "__main__":
    unittest.main()
