"""Breadth-first battle-log crawler."""

from __future__ import annotations

import signal
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from . import db
from .api import ApiError, AuthError, NotFoundError, normalize_tag
from .parse import parse_battle

# Priorities: higher is crawled first; within a priority, oldest-discovered first (BFS).
PRIORITY_SEED = 3
PRIORITY_RANKED = 2
PRIORITY_OTHER = 1

# Which battle.type values count as "ranked" for queue priority. Configurable from the
# CLI; check `mira stats` to confirm what the API actually returns.
DEFAULT_RANKED_TYPES = frozenset({"soloRanked"})
DEFAULT_RECRAWL_SECONDS = 6 * 3600

# In Ranked battles the API puts the player's rank in brawler.trophies instead of
# trophies. Assumed encoding (verify with `mira stats`): 1-3 Bronze I-III, 4-6 Silver,
# 7-9 Gold, 10-12 Diamond, 13-15 Mythic, 16-18 Legendary, 19-21 Masters, 22 Pro.
RANK_TIERS = ["Bronze", "Silver", "Gold", "Diamond", "Mythic", "Legendary", "Masters"]
MAX_RANK = 22
DEFAULT_MIN_RANK = 19  # Masters I


def rank_name(rank: int | None) -> str:
    if rank is None or rank < 1 or rank > MAX_RANK:
        return "?"
    if rank == MAX_RANK:
        return "Pro"
    tier, step = divmod(rank - 1, 3)
    return f"{RANK_TIERS[tier]} {'I' * (step + 1)}"


def parse_rank(value: str) -> int:
    """Accept a number ('16') or a name ('legendary1', 'Masters III', 'pro')."""
    v = value.strip().lower().replace(" ", "").replace("_", "")
    if v.isdigit():
        n = int(v)
        if 0 <= n <= MAX_RANK:
            return n
        raise ValueError(f"rank must be 0-{MAX_RANK}, got {n}")
    if v == "pro":
        return MAX_RANK
    for i, tier in enumerate(RANK_TIERS):
        t = tier.lower()
        if v.startswith(t):
            step = {"": 1, "1": 1, "i": 1, "2": 2, "ii": 2, "3": 3, "iii": 3}.get(v[len(t):])
            if step:
                return i * 3 + step
    raise ValueError(f"unknown rank {value!r}; use 0-{MAX_RANK} or e.g. 'legendary1', 'masters3', 'pro'")


TAG_CHARS = set("0289PYLQGRJCUV")


def read_tags_file(path: str) -> tuple[list[tuple[str, str | None]], int]:
    """Read 'TAG [name]' lines. Returns ([(tag, name)], number of skipped lines).

    Blank lines and lines whose first token isn't a valid tag (e.g. '# comment')
    are skipped. A comma or whitespace may separate the tag from the name.
    """
    out: list[tuple[str, str | None]] = []
    skipped = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            first, _, rest = line.replace(",", " ", 1).partition(" ")
            tag = normalize_tag(first)
            if len(tag) < 4 or not set(tag[1:]) <= TAG_CHARS:
                skipped += 1
                continue
            out.append((tag, rest.strip() or None))
    return out, skipped


class Client(Protocol):
    def battlelog(self, tag: str) -> list[dict]: ...
    def player_rankings(self, country: str = "global", limit: int = 200) -> list[dict]: ...
    def brawlers(self) -> list[dict]: ...


@dataclass
class CrawlStats:
    players_crawled: int = 0
    players_missing: int = 0
    players_failed: int = 0
    entries_seen: int = 0
    battles_parsed: int = 0
    battles_new: int = 0
    battles_other_types: int = 0  # 3v3 but not a ranked type, so not stored
    battles_below_rank: int = 0   # ranked, but not all six players at match_min_rank
    players_discovered: int = 0
    players_below_rank: int = 0
    players_unranked_skipped: int = 0
    stop_reason: str = ""
    started: float = field(default_factory=time.monotonic)

    def summary(self) -> str:
        elapsed = time.monotonic() - self.started
        return (
            f"crawled {self.players_crawled} players ({self.players_missing} missing, "
            f"{self.players_failed} failed) in {elapsed:.0f}s; "
            f"{self.entries_seen} log entries, {self.battles_parsed} 3v3, "
            f"{self.battles_new} new battles"
            + (f" ({self.battles_other_types} non-ranked not stored)" if self.battles_other_types else "")
            + (f" ({self.battles_below_rank} below match min rank not stored)" if self.battles_below_rank else "")
            + f"; queue +{self.players_discovered} players"
            + (f" (skipped {self.players_below_rank} below min rank, "
               f"{self.players_unranked_skipped} from non-ranked games)"
               if self.players_below_rank or self.players_unranked_skipped else "")
            + (f" [{self.stop_reason}]" if self.stop_reason else "")
        )


def is_match_at_rank(battle, min_rank: int, ranked_types: frozenset[str] = DEFAULT_RANKED_TYPES) -> bool:
    """True if this is a ranked battle and every player's rank is at least ``min_rank``."""
    return battle.battle_type in ranked_types and all(
        p.trophies is not None and p.trophies >= min_rank for p in battle.players
    )


def seed(conn: sqlite3.Connection, client: Client, countries: Iterable[str], limit: int = 200) -> int:
    """Queue the top players of each country trophy ranking. Returns how many were queued."""
    n = 0
    for country in countries:
        for item in client.player_rankings(country, limit=limit):
            if item.get("tag"):
                db.enqueue_player(conn, normalize_tag(item["tag"]), PRIORITY_SEED, name=item.get("name"), seed=True)
                n += 1
        conn.commit()
    return n


def seed_tags(conn: sqlite3.Connection, tags: Iterable[tuple[str, str | None]]) -> int:
    """Queue hand-picked players (e.g. pros). Seeds are always crawled, whatever their rank."""
    n = 0
    for tag, name in tags:
        db.enqueue_player(conn, normalize_tag(tag), PRIORITY_SEED, name=name, seed=True)
        n += 1
    conn.commit()
    return n


def crawl_player(
    conn: sqlite3.Connection,
    client: Client,
    tag: str,
    stats: CrawlStats,
    ranked_types: frozenset[str] = DEFAULT_RANKED_TYPES,
    min_rank: int | None = None,
    ranked_only: bool = False,
    match_min_rank: int | None = None,
) -> None:
    """Fetch one player's log, store new 3v3 battles, and grow the queue.

    Without ``min_rank`` everyone in a stored battle is queued. With it, only
    players seen in a Ranked battle at ``min_rank`` or above are queued; everyone
    else's rank is still recorded if they're already known.

    With ``match_min_rank``, a ranked battle is only stored if all six players
    were at that rank or higher; its players still feed the queue either way.
    """
    try:
        entries = client.battlelog(tag)
    except NotFoundError:
        db.mark_crawled(conn, tag, "missing", "404")
        conn.commit()
        stats.players_missing += 1
        return
    except AuthError:
        raise
    except ApiError as e:
        db.mark_crawled(conn, tag, "error", str(e)[:500])
        conn.commit()
        stats.players_failed += 1
        return

    before = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    for entry in entries:
        stats.entries_seen += 1
        battle = parse_battle(entry, tag)
        if battle is None:
            continue
        stats.battles_parsed += 1
        if ranked_only and battle.battle_type not in ranked_types:
            stats.battles_other_types += 1
            continue
        ranked = battle.battle_type in ranked_types
        if match_min_rank is not None and not is_match_at_rank(battle, match_min_rank, ranked_types):
            stats.battles_below_rank += 1
        elif db.insert_battle(conn, battle, source_tag=tag):
            stats.battles_new += 1
        prio = PRIORITY_RANKED if ranked else PRIORITY_OTHER
        for p in battle.players:
            rank = p.trophies if ranked else None
            if p.tag == tag:
                if rank is not None:
                    db.record_rank(conn, tag, rank)
            elif min_rank is None or (rank is not None and rank >= min_rank):
                db.enqueue_player(conn, p.tag, prio, name=p.name, ranked=ranked, rank=rank)
            elif rank is not None:
                db.record_rank(conn, p.tag, rank)
                stats.players_below_rank += 1
            else:
                stats.players_unranked_skipped += 1
    db.mark_crawled(conn, tag, "done")
    conn.commit()
    stats.players_discovered += conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] - before
    stats.players_crawled += 1


class StopFlag:
    """First Ctrl-C asks the crawler to stop after the current player; a second one aborts."""

    def __init__(self) -> None:
        self.stopped = False
        self._prev = None

    def __enter__(self) -> "StopFlag":
        self._prev = signal.signal(signal.SIGINT, self._handle)
        return self

    def __exit__(self, *exc) -> None:
        signal.signal(signal.SIGINT, self._prev)

    def _handle(self, signum, frame) -> None:
        if self.stopped:
            raise KeyboardInterrupt
        self.stopped = True
        print("\nStopping after the current player (Ctrl-C again to abort)...", flush=True)


def crawl(
    conn: sqlite3.Connection,
    client: Client,
    *,
    max_players: int | None = None,
    max_minutes: float | None = None,
    recrawl_after: float = DEFAULT_RECRAWL_SECONDS,
    ranked_types: frozenset[str] = DEFAULT_RANKED_TYPES,
    min_rank: int | None = None,
    ranked_only: bool = False,
    match_min_rank: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    progress: Callable[[CrawlStats], None] | None = None,
    progress_every: int = 25,
) -> CrawlStats:
    stats = CrawlStats()
    deadline = None if max_minutes is None else time.monotonic() + max_minutes * 60
    while True:
        if should_stop():
            stats.stop_reason = "interrupted"
            break
        if max_players is not None and stats.players_crawled >= max_players:
            stats.stop_reason = "player limit"
            break
        if deadline is not None and time.monotonic() >= deadline:
            stats.stop_reason = "time limit"
            break
        # Re-select every iteration so newly found ranked players jump the queue.
        batch = db.next_players(conn, 1, recrawl_after, min_rank=min_rank)
        if not batch:
            stats.stop_reason = "queue empty (everyone crawled within the recrawl window)"
            break
        crawl_player(conn, client, batch[0], stats, ranked_types, min_rank, ranked_only, match_min_rank)
        if progress and stats.players_crawled and stats.players_crawled % progress_every == 0:
            progress(stats)
    return stats
