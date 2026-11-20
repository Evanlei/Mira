"""Sample battle logs and a fake API client for tests."""

from __future__ import annotations

import copy

from mira.api import NotFoundError, normalize_tag


def player(tag: str, brawler: str, bid: int, power: int = 11, trophies: int = 750) -> dict:
    return {
        "tag": tag,
        "name": f"name{tag}",
        "brawler": {"id": bid, "name": brawler, "power": power, "trophies": trophies},
    }


TEAM_A = [player("#AAA1", "SHELLY", 16000000), player("#AAA2", "COLT", 16000001), player("#AAA3", "BULL", 16000002)]
TEAM_B = [player("#BBB1", "BROCK", 16000003), player("#BBB2", "RICO", 16000004), player("#BBB3", "SPIKE", 16000005)]


def entry_3v3(
    time: str = "20261118T101500.000Z",
    result: str = "victory",
    btype: str = "soloRanked",
    mode: str = "gemGrab",
    map_: str = "Hard Rock Mine",
    teams: list | None = None,
) -> dict:
    return {
        "battleTime": time,
        "event": {"id": 15000007, "mode": mode, "map": map_},
        "battle": {
            "mode": mode,
            "type": btype,
            "result": result,
            "duration": 120,
            "starPlayer": TEAM_A[0],
            "teams": copy.deepcopy(teams if teams is not None else [TEAM_A, TEAM_B]),
        },
    }


def entry_showdown(time: str = "20261118T100000.000Z") -> dict:
    return {
        "battleTime": time,
        "event": {"id": 15000010, "mode": "soloShowdown", "map": "Skull Creek"},
        "battle": {
            "mode": "soloShowdown",
            "type": "ranked",
            "rank": 3,
            "duration": 110,
            "players": [player(f"#SD{i}", "PIPER", 16000014) for i in range(10)],
        },
    }


def entry_duels(time: str = "20261118T095000.000Z") -> dict:
    return {
        "battleTime": time,
        "event": {"id": 15000020, "mode": "duels", "map": "Arena"},
        "battle": {
            "mode": "duels",
            "type": "ranked",
            "result": "victory",
            "players": [
                {"tag": "#DU1", "name": "a", "brawlers": []},
                {"tag": "#DU2", "name": "b", "brawlers": []},
            ],
        },
    }


class FakeClient:
    """In-memory stand-in for BrawlStarsClient."""

    def __init__(self, logs: dict[str, list[dict]] | None = None, rankings: dict[str, list[dict]] | None = None):
        self.logs = {normalize_tag(k): v for k, v in (logs or {}).items()}
        self.rankings = rankings or {}
        self.calls: list[str] = []
        self.request_count = 0

    def battlelog(self, tag: str) -> list[dict]:
        tag = normalize_tag(tag)
        self.calls.append(tag)
        self.request_count += 1
        if tag not in self.logs:
            raise NotFoundError(f"404 {tag}", status=404)
        return copy.deepcopy(self.logs[tag])

    def player_rankings(self, country: str = "global", limit: int = 200) -> list[dict]:
        self.request_count += 1
        return self.rankings.get(country, [])[:limit]

    def brawlers(self) -> list[dict]:
        self.request_count += 1
        return [{"id": 16000000, "name": "SHELLY"}, {"id": 16000001, "name": "COLT"}]
