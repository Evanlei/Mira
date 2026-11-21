"""SQLite storage: crawl queue, battles, participants, brawlers."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .parse import ParsedBattle

DEFAULT_DB = "mira.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    tag            TEXT PRIMARY KEY,
    name           TEXT,
    priority       INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | done | missing | error
    discovered_at  REAL NOT NULL,
    last_crawled   REAL,                              -- unix seconds
    crawl_count    INTEGER NOT NULL DEFAULT 0,
    ranked_seen    INTEGER NOT NULL DEFAULT 0,        -- times seen in a ranked battle
    max_rank       INTEGER,                           -- highest Ranked rank observed in battles
    is_seed        INTEGER NOT NULL DEFAULT 0,        -- hand-picked or leaderboard seed
    last_error     TEXT
);
CREATE INDEX IF NOT EXISTS idx_players_queue
    ON players (priority DESC, last_crawled, discovered_at);

CREATE TABLE IF NOT EXISTS battles (
    battle_id     TEXT PRIMARY KEY,                   -- hash(battleTime + sorted tags)
    battle_time   TEXT NOT NULL,                      -- ISO 8601 UTC
    event_id      INTEGER,
    mode          TEXT,
    map           TEXT,
    battle_type   TEXT,
    duration      INTEGER,
    winning_team  INTEGER,                            -- 0/1 index into battle_players.team; NULL on draw
    is_draw       INTEGER NOT NULL DEFAULT 0,
    source_tag    TEXT,                               -- whose log we first saw it in
    raw_json      TEXT NOT NULL,
    inserted_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_battles_type ON battles (battle_type);
CREATE INDEX IF NOT EXISTS idx_battles_map ON battles (mode, map);

CREATE TABLE IF NOT EXISTS battle_players (
    battle_id     TEXT NOT NULL REFERENCES battles (battle_id),
    team          INTEGER NOT NULL,
    slot          INTEGER NOT NULL,
    player_tag    TEXT NOT NULL,
    player_name   TEXT,
    brawler_id    INTEGER,
    brawler_name  TEXT,
    power         INTEGER,
    trophies      INTEGER,
    PRIMARY KEY (battle_id, team, slot)
);
CREATE INDEX IF NOT EXISTS idx_bp_brawler ON battle_players (brawler_id);
CREATE INDEX IF NOT EXISTS idx_bp_player ON battle_players (player_tag);

CREATE TABLE IF NOT EXISTS player_elo (
    tag   TEXT NOT NULL,
    at    REAL NOT NULL,                              -- unix seconds the profile was read
    elo   INTEGER NOT NULL,                           -- rankedElo then
    PRIMARY KEY (tag, at)
);

CREATE TABLE IF NOT EXISTS brawlers (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL
);
"""


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Columns added after the first release: (table, column, definition).
MIGRATIONS = [
    ("players", "max_rank", "INTEGER"),
    ("players", "is_seed", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "next_due", "REAL"),  # unix seconds; when this player's log should be read again
    ("battles", "lobby_rank", "INTEGER"),  # lowest Ranked rank of the six players; NULL if not ranked
    ("players", "peak_rank", "INTEGER"),   # highestAllTimeRankedRank from the player's profile
    ("players", "elo", "INTEGER"),         # rankedElo from the profile
    ("players", "profile_at", "REAL"),     # unix seconds the profile was read
]

RANKED_TYPE = "soloRanked"  # the only type whose brawler.trophies holds a rank


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, ddl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            if (table, column) == ("battles", "lobby_rank"):
                conn.execute(
                    "UPDATE battles SET lobby_rank = (SELECT MIN(trophies) FROM battle_players bp "
                    "WHERE bp.battle_id = battles.battle_id) WHERE battle_type = ?", (RANKED_TYPE,))
    conn.commit()


def enqueue_player(
    conn: sqlite3.Connection,
    tag: str,
    priority: int,
    name: str | None = None,
    ranked: bool = False,
    rank: int | None = None,
    seed: bool = False,
    now: float | None = None,
) -> None:
    """Add a player to the queue, or raise their priority/rank if already known."""
    now = time.time() if now is None else now
    conn.execute(
        """
        INSERT INTO players (tag, name, priority, discovered_at, ranked_seen, max_rank, is_seed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (tag) DO UPDATE SET
            priority    = MAX(players.priority, excluded.priority),
            name        = COALESCE(excluded.name, players.name),
            ranked_seen = players.ranked_seen + excluded.ranked_seen,
            max_rank    = MAX(COALESCE(players.max_rank, excluded.max_rank),
                              COALESCE(excluded.max_rank, players.max_rank)),
            is_seed     = MAX(players.is_seed, excluded.is_seed)
        """,
        (tag, name, priority, now, 1 if ranked else 0, rank, 1 if seed else 0),
    )


def record_rank(conn: sqlite3.Connection, tag: str, rank: int) -> None:
    """Raise a known player's max_rank without adding them to the queue."""
    conn.execute(
        "UPDATE players SET max_rank = MAX(COALESCE(max_rank, ?), ?) WHERE tag = ?",
        (rank, rank, tag),
    )


def next_players(
    conn: sqlite3.Connection,
    limit: int,
    recrawl_after: float,
    now: float | None = None,
    min_rank: int | None = None,
    min_peak: int | None = None,
) -> list[str]:
    """Players due for a crawl: highest priority first, then breadth-first by discovery.

    With ``min_rank``, non-seed players are only eligible once they've been seen at
    that Ranked rank or higher. With ``min_peak``, players whose profile shows an all-time
    peak below it are skipped (unknown peaks stay eligible: the crawler reads the profile first).
    """
    now = time.time() if now is None else now
    rows = conn.execute(
        """
        SELECT tag FROM players
        WHERE status != 'missing'
          AND (last_crawled IS NULL OR MIN(COALESCE(next_due, last_crawled + ?), last_crawled + ?) <= ?)
          AND (? IS NULL OR is_seed = 1 OR max_rank >= ?)
          AND (? IS NULL OR is_seed = 1 OR peak_rank IS NULL OR peak_rank >= ? OR max_rank >= ?)
        ORDER BY priority DESC, (last_crawled IS NOT NULL), next_due, discovered_at, tag
        LIMIT ?
        """,
        (recrawl_after, recrawl_after, now, min_rank, min_rank, min_peak, min_peak, min_peak, limit),
    ).fetchall()
    return [r["tag"] for r in rows]


def earliest_due(
    conn: sqlite3.Connection, recrawl_after: float, min_rank: int | None = None
) -> float | None:
    """When the next crawled player becomes due again (unix seconds), or None if nobody will."""
    row = conn.execute(
        """
        SELECT MIN(MIN(COALESCE(next_due, last_crawled + ?), last_crawled + ?)) FROM players
        WHERE status != 'missing' AND last_crawled IS NOT NULL
          AND (? IS NULL OR is_seed = 1 OR max_rank >= ?)
        """,
        (recrawl_after, recrawl_after, min_rank, min_rank),
    ).fetchone()
    return row[0]


PRO_RANK = 22  # "Pro", the top Ranked rank


def needs_profile(conn: sqlite3.Connection, tag: str, min_peak: int | None, max_age: float,
                  now: float | None = None, elo_max_age: float | None = None) -> str | None:
    """Why to read this player's profile before their battle log, or None:
    "gate"  not a seed, not yet seen at ``min_peak`` or higher, no profile within ``max_age``
            (the peak gate: a low peak skips the battle log);
    "elo"   any player whose profile (Elo) is older than ``elo_max_age``: Elo orders the picks
            within a team (model/order.py), so it should be close to the games it orders."""
    now = time.time() if now is None else now
    row = conn.execute("SELECT is_seed, max_rank, peak_rank, profile_at FROM players WHERE tag = ?", (tag,)).fetchone()
    if row is None:
        return None
    stale = lambda age: row["profile_at"] is None or row["profile_at"] < now - age  # noqa: E731
    if (min_peak is not None and not row["is_seed"] and max(row["max_rank"] or 0, row["peak_rank"] or 0) < min_peak
            and stale(max_age)):
        return "gate"
    if elo_max_age is not None and stale(elo_max_age):
        return "elo"
    return None


def record_profile(conn: sqlite3.Connection, tag: str, profile: dict, now: float | None = None) -> int | None:
    """Store the player's all-time peak rank and Elo from /players/{tag}; returns the peak."""
    now = time.time() if now is None else now
    peak = profile.get("highestAllTimeRankedRank")
    elo = profile.get("rankedElo")
    conn.execute(
        "UPDATE players SET peak_rank = ?, elo = ?, profile_at = ? WHERE tag = ?",
        (peak, elo, now, tag),
    )
    if elo is not None:
        conn.execute("INSERT OR IGNORE INTO player_elo VALUES (?, ?, ?)", (tag, now, elo))
    return peak


def count_pros(conn: sqlite3.Connection, tags: list[str]) -> int:
    """How many of these players we have seen at Pro rank, or hand-listed as pros (seeds)."""
    marks = ",".join("?" * len(tags))
    return conn.execute(
        f"SELECT COUNT(*) FROM players WHERE tag IN ({marks}) AND (max_rank >= ? OR is_seed = 1)",
        (*tags, PRO_RANK),
    ).fetchone()[0]


def mark_crawled(
    conn: sqlite3.Connection,
    tag: str,
    status: str,
    error: str | None = None,
    now: float | None = None,
    next_due: float | None = None,
) -> None:
    now = time.time() if now is None else now
    conn.execute(
        """
        UPDATE players
        SET status = ?, last_crawled = ?, crawl_count = crawl_count + 1, last_error = ?, next_due = ?
        WHERE tag = ?
        """,
        (status, now, error, next_due, tag),
    )


def lobby_rank(b: ParsedBattle) -> int | None:
    """Lowest rank among the six players of a Ranked battle (None otherwise)."""
    if b.battle_type != RANKED_TYPE or any(p.trophies is None for p in b.players):
        return None
    return min(p.trophies for p in b.players)


def insert_battle(
    conn: sqlite3.Connection, b: ParsedBattle, source_tag: str, now: float | None = None
) -> bool:
    """Store a battle and its six players. Returns False if it was already stored."""
    now = time.time() if now is None else now
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO battles
            (battle_id, battle_time, event_id, mode, map, battle_type, duration,
             winning_team, is_draw, source_tag, raw_json, inserted_at, lobby_rank)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            b.battle_id, b.battle_time, b.event_id, b.mode, b.map, b.battle_type, b.duration,
            b.winning_team, int(b.is_draw), source_tag,
            json.dumps(b.raw, separators=(",", ":")), now, lobby_rank(b),
        ),
    )
    if cur.rowcount == 0:
        return False
    conn.executemany(
        """
        INSERT INTO battle_players
            (battle_id, team, slot, player_tag, player_name, brawler_id, brawler_name, power, trophies)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (b.battle_id, p.team, p.slot, p.tag, p.name, p.brawler_id, p.brawler_name, p.power, p.trophies)
            for p in b.players
        ],
    )
    conn.executemany(
        "INSERT INTO brawlers (id, name) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
        {(p.brawler_id, p.brawler_name) for p in b.players if p.brawler_id is not None and p.brawler_name},
    )
    return True


def upsert_brawlers(conn: sqlite3.Connection, items: list[dict]) -> int:
    rows = [(b["id"], b["name"]) for b in items if b.get("id") is not None and b.get("name")]
    conn.executemany(
        "INSERT INTO brawlers (id, name) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET name = excluded.name",
        rows,
    )
    return len(rows)
