import unittest

from mira.parse import battle_hash, parse_battle, parse_battle_time

from fakes import TEAM_A, TEAM_B, entry_3v3, entry_duels, entry_showdown, player


class ParseBattleTests(unittest.TestCase):
    def test_victory_from_team0_owner(self):
        b = parse_battle(entry_3v3(result="victory"), "#AAA1")
        self.assertEqual(b.winning_team, 0)
        self.assertFalse(b.is_draw)
        self.assertEqual(b.battle_type, "soloRanked")
        self.assertEqual((b.mode, b.map), ("gemGrab", "Hard Rock Mine"))
        self.assertEqual(b.battle_time, "2026-11-18T10:15:00Z")
        self.assertEqual(len(b.players), 6)
        self.assertEqual([p.brawler_name for p in b.players if p.team == 1], ["BROCK", "RICO", "SPIKE"])

    def test_result_is_owner_relative(self):
        # Owner on team 1 says "victory" -> team 1 won; says "defeat" -> team 0 won.
        self.assertEqual(parse_battle(entry_3v3(result="victory"), "#BBB2").winning_team, 1)
        self.assertEqual(parse_battle(entry_3v3(result="defeat"), "#BBB2").winning_team, 0)
        self.assertEqual(parse_battle(entry_3v3(result="defeat"), "#AAA3").winning_team, 1)

    def test_draw(self):
        b = parse_battle(entry_3v3(result="draw"), "#AAA1")
        self.assertTrue(b.is_draw)
        self.assertIsNone(b.winning_team)

    def test_owner_tag_normalized(self):
        self.assertEqual(parse_battle(entry_3v3(), "aaa1").winning_team, 0)

    def test_same_match_from_both_sides_agrees(self):
        a = parse_battle(entry_3v3(result="victory"), "#AAA1")
        b = parse_battle(entry_3v3(result="defeat"), "#BBB1")
        self.assertEqual(a.battle_id, b.battle_id)
        self.assertEqual(a.winning_team, b.winning_team)

    def test_hash_is_order_independent_and_time_sensitive(self):
        tags = ["#AAA1", "#AAA2", "#AAA3", "#BBB1", "#BBB2", "#BBB3"]
        self.assertEqual(battle_hash("t1", tags), battle_hash("t1", list(reversed(tags))))
        self.assertNotEqual(battle_hash("t1", tags), battle_hash("t2", tags))

    def test_rejects_non_3v3(self):
        self.assertIsNone(parse_battle(entry_showdown(), "#SD1"))
        self.assertIsNone(parse_battle(entry_duels(), "#DU1"))
        five = [player(f"#F{i}", "X", 1) for i in range(5)]
        self.assertIsNone(parse_battle(entry_3v3(teams=[five, five]), "#F1"))
        three_teams = [TEAM_A, TEAM_B, TEAM_A]
        self.assertIsNone(parse_battle(entry_3v3(teams=three_teams), "#AAA1"))

    def test_rejects_missing_result_or_owner(self):
        e = entry_3v3()
        del e["battle"]["result"]
        self.assertIsNone(parse_battle(e, "#AAA1"))
        self.assertIsNone(parse_battle(entry_3v3(), "#NOTINIT"))

    def test_mode_falls_back_to_battle_mode(self):
        e = entry_3v3()
        del e["event"]["mode"]
        self.assertEqual(parse_battle(e, "#AAA1").mode, "gemGrab")

    def test_parse_battle_time_passthrough(self):
        self.assertEqual(parse_battle_time("weird"), "weird")


if __name__ == "__main__":
    unittest.main()
