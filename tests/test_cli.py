import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path

from mira import crawler, db
from mira.cli import EXPORT_HEADER, main

from fakes import FakeClient, entry_3v3


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "t.db")
        conn = db.connect(self.db_path)
        db.init_db(conn)
        logs = {
            "#AAA1": [
                entry_3v3(result="victory", btype="soloRanked"),
                entry_3v3(time="20261118T120000.000Z", result="draw", btype="ranked", mode="brawlBall", map_="Center Stage"),
            ]
        }
        db.enqueue_player(conn, "#AAA1", crawler.PRIORITY_SEED)
        crawler.crawl(conn, FakeClient(logs), max_players=1)
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--db", self.db_path, *argv])
        return code, out.getvalue()

    def test_export(self):
        out_path = str(Path(self.tmp.name) / "m.csv")
        code, _ = self.run_cli("export", "--out", out_path)
        self.assertEqual(code, 0)
        with open(out_path, newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], EXPORT_HEADER)
        self.assertEqual(len(rows), 3)
        first = dict(zip(EXPORT_HEADER, rows[1]))
        self.assertEqual(first["type"], "soloRanked")
        self.assertEqual(first["map"], "Hard Rock Mine")
        self.assertEqual([first[f"team1_brawler{i}"] for i in (1, 2, 3)], ["SHELLY", "COLT", "BULL"])
        self.assertEqual(first["winner"], "1")
        self.assertEqual(dict(zip(EXPORT_HEADER, rows[2]))["winner"], "draw")

    def test_export_type_filter(self):
        code, out = self.run_cli("export", "--out", "-", "--type", "ranked")
        self.assertEqual(len(out.strip().splitlines()), 2)

    def test_stats(self):
        code, out = self.run_cli("stats")
        self.assertEqual(code, 0)
        for s in ("Battles: 2", "soloRanked", "brawlBall", "Center Stage", "SHELLY"):
            self.assertIn(s, out)

    def test_init(self):
        code, out = self.run_cli("init")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
