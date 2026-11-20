"""`mira` command-line interface."""

from __future__ import annotations

import argparse
import csv
import itertools
import sqlite3
import sys
from typing import Sequence

from . import crawler, db
from .api import ApiError, AuthError, BrawlStarsClient, load_token

EXPORT_HEADER = [
    "battle_id", "battle_time", "map", "mode", "type",
    "team1_brawler1", "team1_brawler2", "team1_brawler3",
    "team2_brawler1", "team2_brawler2", "team2_brawler3",
    "winner",  # 1, 2 or draw
]


def _client(args: argparse.Namespace) -> BrawlStarsClient:
    rate = getattr(args, "rate", None) or 10.0
    return BrawlStarsClient(load_token(args.env_file), min_interval=1.0 / rate)


def _open_db(args: argparse.Namespace) -> sqlite3.Connection:
    conn = db.connect(args.db)
    db.init_db(conn)  # idempotent; keeps every command usable on a fresh DB
    return conn


# -- commands -----------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    _open_db(args).close()
    print(f"Initialized database at {args.db}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    client = _client(args)
    brawlers = client.brawlers()
    print(f"API key OK: /brawlers returned {len(brawlers)} brawlers.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    if not args.tags_file and not args.country:
        print("error: give --tags-file FILE (e.g. pro players) and/or --country CODE", file=sys.stderr)
        return 1
    tags: list = []
    if args.tags_file:
        tags, skipped = crawler.read_tags_file(args.tags_file)
        if skipped:
            print(f"Skipped {skipped} line(s) in {args.tags_file} without a valid tag.")
        if not tags and not args.country:
            print(f"error: no valid tags in {args.tags_file}", file=sys.stderr)
            return 1
    client = _client(args)
    conn = _open_db(args)
    n_brawlers = db.upsert_brawlers(conn, client.brawlers())
    conn.commit()
    if tags:
        print(f"Queued {crawler.seed_tags(conn, tags)} players from {args.tags_file}.")
    if args.country:
        n = crawler.seed(conn, client, args.country, limit=args.limit)
        print(f"Queued {n} players from the trophy leaderboard of {', '.join(args.country)}.")
    total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    print(f"Stored {n_brawlers} brawlers; {total} players in queue.")
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    client = _client(args)
    conn = _open_db(args)
    ranked = frozenset(t.strip() for t in args.ranked_types.split(",") if t.strip())
    min_rank = args.min_rank or None  # 0 disables the gate
    if conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0:
        print("Queue is empty: run `mira seed` first.", file=sys.stderr)
        return 1
    with crawler.StopFlag() as stop:
        stats = crawler.crawl(
            conn,
            client,
            max_players=args.players,
            max_minutes=args.minutes,
            recrawl_after=args.recrawl_hours * 3600,
            ranked_types=ranked,
            min_rank=min_rank,
            ranked_only=not args.all_types,
            match_min_rank=None if args.all_types else (args.match_min_rank or None),
            should_stop=lambda: stop.stopped,
            progress=lambda s: print("  " + s.summary(), flush=True),
        )
    print("Done: " + stats.summary() + f"; {client.request_count} API requests")
    if min_rank:
        print(f"Rank gate: non-seed players need {crawler.rank_name(min_rank)} ({min_rank}) or higher.")
    if args.match_min_rank and not args.all_types:
        print(f"Match gate: stored matches have all six players at "
              f"{crawler.rank_name(args.match_min_rank)} ({args.match_min_rank}) or higher.")
    return 0


def _print_table(title: str, rows: Sequence[sqlite3.Row], cols: Sequence[str]) -> None:
    print(f"\n{title}")
    if not rows:
        print("  (none)")
        return
    widths = [max(len(c), *(len(_fmt(r[c])) for r in rows)) for c in cols]
    print("  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("  " + "  ".join(_fmt(r[c]).ljust(w) for c, w in zip(cols, widths)))


def _fmt(v: object) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.1%}" if v <= 1 else f"{v:.1f}"
    return str(v)


def cmd_stats(args: argparse.Namespace) -> int:
    conn = _open_db(args)
    where, params = ("WHERE b.battle_type = ?", [args.type]) if args.type else ("", [])
    q = lambda sql, p=(): conn.execute(sql, p).fetchall()  # noqa: E731

    total = q(f"SELECT COUNT(*) AS n FROM battles b {where}", params)[0]["n"]
    print(f"Database: {args.db}" + (f"  (battle type = {args.type})" if args.type else ""))
    print(f"Battles: {total}")

    _print_table("Queue", q(
        "SELECT status, COUNT(*) AS players, SUM(ranked_seen > 0) AS seen_in_ranked "
        "FROM players GROUP BY status ORDER BY players DESC"), ["status", "players", "seen_in_ranked"])
    rows = q("""
        SELECT is_seed, COUNT(*) AS players,
               SUM(max_rank IS NULL) AS no_ranked_games,
               SUM(max_rank >= ?) AS at_or_above_min_rank
        FROM players GROUP BY is_seed ORDER BY is_seed DESC""", [args.min_rank])
    _print_table(f"Players by observed Ranked rank (min rank {crawler.rank_name(args.min_rank)} = {args.min_rank})",
                 [dict(r, group="seeds" if r["is_seed"] else "discovered") for r in rows],
                 ["group", "players", "no_ranked_games", "at_or_above_min_rank"])
    low_seeds = q("SELECT tag, name, max_rank FROM players WHERE is_seed = 1 AND max_rank < ? "
                  "ORDER BY max_rank", [args.min_rank])
    if low_seeds:
        _print_table("Seeds seen below the min rank (check these tags)",
                     [dict(r, rank=crawler.rank_name(r["max_rank"])) for r in low_seeds],
                     ["tag", "name", "max_rank", "rank"])
    ranked_list = ",".join("?" * len(crawler.DEFAULT_RANKED_TYPES))
    _print_table("Rank values in Ranked battles (brawler.trophies; check this looks like 1-22)", [
        dict(r, rank=crawler.rank_name(r["value"])) for r in q(
            f"SELECT bp.trophies AS value, COUNT(*) AS appearances FROM battle_players bp "
            f"JOIN battles b USING (battle_id) WHERE b.battle_type IN ({ranked_list}) "
            "GROUP BY bp.trophies ORDER BY bp.trophies DESC", sorted(crawler.DEFAULT_RANKED_TYPES))
    ], ["value", "rank", "appearances"])
    _print_table("By battle type (all types)", q(
        "SELECT battle_type, COUNT(*) AS battles, "
        "COUNT(DISTINCT mode) AS modes, COUNT(DISTINCT map) AS maps "
        "FROM battles GROUP BY battle_type ORDER BY battles DESC"),
        ["battle_type", "battles", "modes", "maps"])
    _print_table("By mode", q(
        f"SELECT b.mode, COUNT(*) AS battles FROM battles b {where} "
        "GROUP BY b.mode ORDER BY battles DESC", params), ["mode", "battles"])
    _print_table(f"By map (top {args.top})", q(
        f"SELECT b.mode, b.map, COUNT(*) AS battles FROM battles b {where} "
        "GROUP BY b.mode, b.map ORDER BY battles DESC LIMIT ?", [*params, args.top]),
        ["mode", "map", "battles"])
    _print_table(f"By brawler (top {args.top} by picks)", q(
        f"""
        SELECT bp.brawler_name AS brawler, COUNT(*) AS picks,
               SUM(b.winning_team = bp.team) AS wins,
               1.0 * SUM(b.winning_team = bp.team) / NULLIF(SUM(b.is_draw = 0), 0) AS win_rate
        FROM battle_players bp JOIN battles b USING (battle_id) {where}
        GROUP BY bp.brawler_id ORDER BY picks DESC LIMIT ?
        """, [*params, args.top]), ["brawler", "picks", "wins", "win_rate"])
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    conn = _open_db(args)
    where, params = ("WHERE b.battle_type = ?", [args.type]) if args.type else ("", [])
    rows = conn.execute(
        f"""
        SELECT b.battle_id, b.battle_time, b.map, b.mode, b.battle_type, b.winning_team, b.is_draw,
               bp.team, bp.slot, bp.brawler_name
        FROM battles b JOIN battle_players bp USING (battle_id) {where}
        ORDER BY b.battle_time, b.battle_id, bp.team, bp.slot
        """,
        params,
    )
    out = open(args.out, "w", newline="", encoding="utf-8") if args.out != "-" else sys.stdout
    n = 0
    try:
        w = csv.writer(out)
        w.writerow(EXPORT_HEADER)
        for battle_id, group in itertools.groupby(rows, key=lambda r: r["battle_id"]):
            group = list(group)
            if len(group) != 6:
                continue
            first = group[0]
            winner = "draw" if first["is_draw"] else str(first["winning_team"] + 1)
            w.writerow([battle_id, first["battle_time"], first["map"], first["mode"], first["battle_type"],
                        *(r["brawler_name"] for r in group), winner])
            n += 1
    finally:
        if out is not sys.stdout:
            out.close()
    if args.out != "-":
        print(f"Wrote {n} matches to {args.out}")
    return 0


# -- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mira", description="Brawl Stars 3v3 battle crawler.")
    p.add_argument("--db", default=db.DEFAULT_DB, help="SQLite database path (default: %(default)s)")
    p.add_argument("--env-file", default=".env", help="dotenv file holding BRAWLSTARS_API_TOKEN")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database schema").set_defaults(func=cmd_init)

    sp = sub.add_parser("check", help="verify the API key works")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("seed", help="queue seed players (a tags file of pros, and/or trophy leaderboards)")
    sp.add_argument("--tags-file", help="file with one player tag per line, optionally followed by a name")
    sp.add_argument("--country", action="append", default=None,
                    help="also queue a trophy leaderboard: country code or 'global'; repeatable")
    sp.add_argument("--limit", type=int, default=200, help="players per ranking (max 200)")
    sp.set_defaults(func=cmd_seed)

    sp = sub.add_parser("crawl", help="crawl battle logs breadth-first")
    sp.add_argument("--players", type=int, help="stop after crawling this many players")
    sp.add_argument("--minutes", type=float, help="stop after this many minutes")
    sp.add_argument("--recrawl-hours", type=float, default=6.0, help="recrawl a player after (default: 6)")
    sp.add_argument("--rate", type=float, default=10.0, help="max API requests per second (default: 10)")
    sp.add_argument("--ranked-types", default=",".join(sorted(crawler.DEFAULT_RANKED_TYPES)),
                    help="comma-separated battle.type values that count as ranked (default: %(default)s)")
    sp.add_argument("--min-rank", type=_rank_arg, default=crawler.DEFAULT_MIN_RANK,
                    help="only queue non-seed players seen in Ranked at this rank or higher: 0-22 or a "
                         "name like legendary1, masters3, pro; 0 disables (default: masters1 = 19)")
    sp.add_argument("--match-min-rank", type=_rank_arg, default=crawler.DEFAULT_MIN_RANK,
                    help="only store ranked matches where all six players are at this rank or higher; "
                         "0 disables (default: masters1 = 19)")
    sp.add_argument("--all-types", action="store_true",
                    help="store every 3v3 battle type (trophy, friendly, ...), not just the ranked types")
    sp.set_defaults(func=cmd_crawl)

    sp = sub.add_parser("stats", help="show battle counts by type, mode, map and brawler")
    sp.add_argument("--type", help="only count this battle.type (type breakdown always shows all)")
    sp.add_argument("--top", type=int, default=20, help="rows for map/brawler tables")
    sp.add_argument("--min-rank", type=_rank_arg, default=crawler.DEFAULT_MIN_RANK,
                    help="threshold used in the rank tables (default: masters1 = 19)")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("export", help="write one CSV row per match")
    sp.add_argument("--out", default="matches.csv", help="output path, or - for stdout")
    sp.add_argument("--type", help="only export this battle.type")
    sp.set_defaults(func=cmd_export)
    return p


def _rank_arg(value: str) -> int:
    try:
        return crawler.parse_rank(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
