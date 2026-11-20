"""Turn raw battle-log entries into normalized 3v3 matches."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .api import normalize_tag


@dataclass
class ParsedPlayer:
    team: int  # 0 or 1, index into battle.teams as stored
    slot: int  # 0..2, position within the team as given by the API
    tag: str
    name: str | None
    brawler_id: int | None
    brawler_name: str | None
    power: int | None
    trophies: int | None


@dataclass
class ParsedBattle:
    battle_id: str
    battle_time: str  # ISO 8601 UTC
    event_id: int | None
    mode: str | None
    map: str | None
    battle_type: str | None
    duration: int | None
    winning_team: int | None  # 0/1, None for a draw
    is_draw: bool
    players: list[ParsedPlayer] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def tags(self) -> list[str]:
        return [p.tag for p in self.players]


def battle_hash(battle_time: str, tags: list[str]) -> str:
    """Stable ID for a match: same for every participant's copy of the log."""
    key = battle_time + "|" + ",".join(sorted(normalize_tag(t) for t in tags))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def parse_battle_time(value: str) -> str:
    """'20240101T120000.000Z' -> '2024-01-01T12:00:00Z'. Unknown formats pass through."""
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return value


def parse_battle(entry: dict, owner_tag: str) -> ParsedBattle | None:
    """Parse one battle-log item fetched from ``owner_tag``'s log.

    Returns None unless the entry is a 3v3 (two teams of three) with a usable
    result. ``battle.result`` is from the log owner's point of view, so the
    winning team is the owner's team on "victory" and the other on "defeat".
    """
    battle = entry.get("battle") or {}
    event = entry.get("event") or {}
    teams = battle.get("teams")
    battle_time = entry.get("battleTime")
    if not battle_time or not isinstance(teams, list) or len(teams) != 2:
        return None
    if any(not isinstance(t, list) or len(t) != 3 for t in teams):
        return None

    players: list[ParsedPlayer] = []
    for ti, team in enumerate(teams):
        for si, p in enumerate(team):
            tag = p.get("tag")
            if not tag:
                return None
            brawler = p.get("brawler") or {}
            players.append(
                ParsedPlayer(
                    team=ti,
                    slot=si,
                    tag=normalize_tag(tag),
                    name=p.get("name"),
                    brawler_id=brawler.get("id"),
                    brawler_name=brawler.get("name"),
                    power=brawler.get("power"),
                    trophies=brawler.get("trophies"),
                )
            )
    if len({p.tag for p in players}) != 6:
        return None

    owner = normalize_tag(owner_tag)
    owner_team = next((p.team for p in players if p.tag == owner), None)
    result = battle.get("result")
    if result == "draw":
        winning_team, is_draw = None, True
    elif result in ("victory", "defeat") and owner_team is not None:
        winning_team = owner_team if result == "victory" else 1 - owner_team
        is_draw = False
    else:
        return None  # no result, or the owner isn't in the match

    return ParsedBattle(
        battle_id=battle_hash(battle_time, [p.tag for p in players]),
        battle_time=parse_battle_time(battle_time),
        event_id=event.get("id"),
        mode=event.get("mode") or battle.get("mode"),
        map=event.get("map"),
        battle_type=battle.get("type"),
        duration=battle.get("duration"),
        winning_team=winning_team,
        is_draw=is_draw,
        players=players,
        raw=entry,
    )

