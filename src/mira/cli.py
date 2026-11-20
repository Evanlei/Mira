"""`mira` command-line interface."""

from __future__ import annotations

import argparse
import csv
import itertools
import sqlite3
import sys
from typing import Sequence

from . import crawler, db, readiness
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
            workers=args.workers,
            watch=args.watch,
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


def _bar(fraction: float, width: int = 20) -> str:
    filled = round(fraction * width)
    return "#" * filled + "." * (width - filled)


def cmd_readiness(args: argparse.Namespace) -> int:
    conn = _open_db(args)
    r = readiness.compute(conn, target=args.target, pool_days=args.pool_days)
    if r.reference_time is None:
        print("No Ranked matches yet: run `mira crawl` first.")
        return 0
    status = "READY to train" if r.ready else "not ready"
    done = sum(m.matches >= r.target for m in r.pool)
    print(f"{status}: {done}/{len(r.pool)} maps in the current pool have >= {r.target} all-Masters matches.")
    print(f"Pool = maps played in the {r.pool_days} days before the newest match ({r.reference_time}).")
    print(f"Overall {r.overall_progress:.0%}; {r.total_needed:,} more matches needed on the thin maps.\n")
    w_mode = max(len(m.mode or "-") for m in r.pool)
    w_map = max(len(m.map or "-") for m in r.pool)
    print(f"  {'mode'.ljust(w_mode)}  {'map'.ljust(w_map)}  {'matches':>7}  progress")
    for m in r.pool:  # thinnest first
        print(f"  {(m.mode or '-').ljust(w_mode)}  {(m.map or '-').ljust(w_map)}  {m.matches:>7,}  "
              f"{_bar(m.progress(r.target))} {m.progress(r.target):>4.0%}")
    if r.retired:
        n = sum(m.matches for m in r.retired)
        print(f"\n  {len(r.retired)} map(s) with {n:,} matches are no longer in the pool (kept, not counted).")
    return 0


def _load_training_data(args: argparse.Namespace):
    try:
        from .model import dataset, patches
    except ImportError as e:  # numpy missing
        raise SystemExit(f"error: training needs numpy ({e}). Run `uv sync`.") from None
    conn = _open_db(args)
    m = dataset.load(conn, min_lobby_rank=args.min_lobby_rank or None)
    if len(m) < 200:
        raise SystemExit(f"error: only {len(m)} Ranked matches in {args.db}; crawl more first.")
    plog = patches.load(args.patches)
    unknown = patches.unknown_names(plog, set(m.brawler_names) | {
        r[0] for r in conn.execute("SELECT name FROM brawlers")})
    if unknown:
        print(f"warning: {args.patches} names not found in the brawler list: {', '.join(unknown)}", file=sys.stderr)
    return m, plog


def cmd_evaluate(args: argparse.Namespace) -> int:
    import numpy as np

    from .model import evaluate

    m, plog = _load_training_data(args)
    n_masters = int(m.masters_mask().sum())
    print(f"Evaluating on {len(m):,} Ranked matches ({n_masters:,} all-Masters; {m.times[0]} .. {m.times[-1]}), "
          f"{len(plog)} patches in {args.patches}.")
    print(f"Lower lobbies weigh {args.rank_factor:g} per rank below Masters I; the test set is all-Masters only.")
    if not args.no_tune:
        print("Tuning L2 strengths (coordinate descent on the newest 20% of training matches)...", flush=True)
    r = evaluate.run(m, plog, test_days=args.test_days, half_life_days=args.half_life,
                     pre_patch_factor=args.pre_patch_factor, tune=not args.no_tune,
                     rank_factor=args.rank_factor)
    print(f"\nTest split: {r.split}. Train {r.n_train:,} ({r.n_train_masters:,} all-Masters) / "
          f"test {r.n_test:,} all-Masters matches.")
    print("Chosen L2: " + ", ".join(f"{k}={v:g}" for k, v in r.l2.items()))
    w = max(len(s.name) for s in r.scores)
    print(f"\n  {'model'.ljust(w)}  log loss   Brier  accuracy  calib. err")
    for s in r.scores:
        print(f"  {s.name.ljust(w)}  {s.log_loss:8.4f}  {s.brier:6.4f}  {s.accuracy:8.1%}  {s.ece:10.3f}")
    print("\n  Mira vs baseline: mean log-loss difference per match (negative = Mira better), 95% CI")
    for name, d, lo, hi in r.comparisons:
        verdict = "better" if hi < 0 else ("worse" if lo > 0 else "no clear difference")
        print(f"  {name.ljust(w)}  {d:+.4f}  [{lo:+.4f}, {hi:+.4f}]  {verdict}")
    print("\nMVP bar (spec §8): " + ("PASS" if r.passes else "not met: " + "; ".join(r.reasons)))

    from .model import pickmodel
    from .model.evaluate import time_split
    mask, _ = time_split(m, args.test_days)
    train, test = m.subset(~mask), m.subset(mask & m.masters_mask())
    w_tr = train.rank_weights(args.rank_factor)
    k = int(round(len(train) * 0.8))
    val = train.subset(np.flatnonzero(train.masters_mask()[k:]) + k)
    tuned = pickmodel.tune(pickmodel.PickModel.fit(train.subset(slice(0, k)), w_tr[:k]), val.subset(slice(0, 1500)))
    full = pickmodel.PickModel.fit(train, w_tr)
    full.alpha, full.beta = tuned.alpha, tuned.beta
    base = pickmodel.PickModel.fit(train, w_tr)
    base.alpha = base.beta = 0.0
    sample = test.subset(slice(0, 3000))
    print(f"\nPick model (predict each brawler from the map, its 2 allies and 3 enemies; "
          f"{len(sample) * 6:,} held-out picks, ~{m.n_brawlers - 5} options each):")
    pw = 36
    print(f"  {'model'.ljust(pw)}  log-lik   top-1   top-5  top-10")
    for name, pm in (("map pick rates only", base), (f"+ allies/enemies (a={full.alpha:g}, b={full.beta:g})", full)):
        e = pickmodel.evaluate(pm, sample)
        print(f"  {name.ljust(pw)}  {e['log_lik']:7.3f}  {e['top1']:6.1%}  {e['top5']:6.1%}  {e['top10']:6.1%}")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    import numpy as np

    from .model import evaluate, export
    from .model.winmodel import DEFAULT_L2, WinModel

    m, plog = _load_training_data(args)
    w = evaluate.weights_for(m, plog, args.half_life, args.pre_patch_factor, args.rank_factor)
    if args.no_tune:
        l2 = dict(DEFAULT_L2)
    else:
        print("Tuning L2 strengths on the newest 20% of matches...", flush=True)
        l2 = evaluate.tune_l2(m, w)[0]
    print("L2: " + ", ".join(f"{k}={v:g}" for k, v in l2.items()))
    model = WinModel.fit(m, w, l2)
    from .model.pickmodel import PickModel, tune as tune_pick
    k = int(round(len(m) * 0.8))
    val = m.subset(np.flatnonzero(m.masters_mask()[k:]) + k)
    pm = tune_pick(PickModel.fit(m.subset(slice(0, k)), w[:k]), val.subset(slice(0, 1500)))
    pick = PickModel.fit(m, w)
    pick.alpha, pick.beta = pm.alpha, pm.beta
    print(f"Pick model: alpha={pick.alpha:g}, beta={pick.beta:g}")
    data = export.to_dict(model, m, export.game_counts(m, args.rank_factor), extra={
        "pick_model": export.pick_model_dict(pick),
        "patches": [{"date": p.date, "changes": p.changes} for p in plog],
        "weighting": {"half_life_days": args.half_life, "pre_patch_factor": args.pre_patch_factor,
                      "min_lobby_rank": args.min_lobby_rank, "rank_factor": args.rank_factor},
    })
    size = export.write(args.out, data)
    print(f"Wrote {args.out} ({size / 1e6:.2f} MB) from {len(m):,} matches "
          f"({int(m.masters_mask().sum()):,} all-Masters). "
          "Run `mira evaluate` for held-out accuracy.")
    return 0


def _engine(args):
    from .engine.model import Model
    try:
        model = Model.load(args.model)
    except FileNotFoundError:
        raise SystemExit(f"error: {args.model} not found: run `mira train` first.") from None
    if "pick_model" not in model.data:
        raise SystemExit(f"error: {args.model} has no pick model: rerun `mira train`.")
    return model


def _names(model, csv_list: str | None) -> list[int]:
    return [model.brawler(x) for x in (csv_list or "").split(",") if x.strip()]


def _pct(p: float) -> str:
    return f"{round(p * 100):d}%"


def cmd_suggest(args: argparse.Namespace) -> int:
    from .engine.search import Searcher

    model = _engine(args)
    try:
        mp = model.map(args.map)
        ours, theirs, bans = _names(model, args.ours), _names(model, args.theirs), _names(model, args.bans)
    except KeyError as e:
        raise SystemExit(f"error: {e.args[0]}") from None
    if set(ours) & set(theirs) or (set(ours) | set(theirs)) & set(bans):
        raise SystemExit("error: a brawler appears twice (picked by both teams, or picked and banned)")
    we_first = args.first == "us"
    try:
        r = Searcher(model, mp, set(bans)).run(tuple(ours), tuple(theirs), we_first)
    except ValueError as e:
        raise SystemExit(f"error: {e}") from None

    name = lambda picks: " + ".join(model.names[b] for b in picks)  # noqa: E731
    mode, map_name = model.maps[mp]
    print(f"{map_name} ({mode}) · you pick {'first' if we_first else 'second'} · "
          f"you: {name(ours) or '-'} · them: {name(theirs) or '-'} · bans: {name(bans) or '-'}")
    if r.side == "done":
        print(f"Draft complete: {_pct(r.win)} win chance.")
        return 0
    print(f"Expected win chance with best play: {_pct(r.win)}\n")
    if r.side == "us":
        print(f"Your pick{'s' if r.turn_size == 2 else ''} now:")
        for o in r.suggestions[:5]:
            low = [model.names[b] for b in o.picks if model.games_on_map(b, mp) < 100]
            note = f"   (few games on this map: {', '.join(low)})" if low else ""
            print(f"  {name(o.picks).ljust(28)} {_pct(o.win):>4}{note}")
    else:
        print("Their turn. Most likely picks:")
        for o in r.suggestions[:5]:
            print(f"  {name(o.picks).ljust(28)} {_pct(o.prob):>4} likely  → you {_pct(o.win)}")
    print("\nMost likely line:")
    for st in r.line:
        who = "You " if st.side == "us" else "Them"
        main = name(st.chosen.picks)
        if st.side == "us":
            head = f"{main} → {_pct(st.chosen.win)}"
            alts = " · ".join(f"{name(a.picks)} {_pct(a.win)}" for a in st.alternatives)
        else:
            head = f"{main} ({_pct(st.chosen.prob)} likely) → {_pct(st.chosen.win)}"
            alts = " · ".join(f"{name(a.picks)} {_pct(a.prob)}" for a in st.alternatives)
        print(f"  {who}: {head.ljust(44)} alts: {alts or '-'}")
    return 0


def cmd_bans(args: argparse.Namespace) -> int:
    from .engine.search import suggest_bans

    model = _engine(args)
    try:
        mp = model.map(args.map)
        banned = set(_names(model, args.bans))
    except KeyError as e:
        raise SystemExit(f"error: {e.args[0]}") from None
    mode, map_name = model.maps[mp]
    print(f"Ban suggestions for {map_name} ({mode}), you pick {'first' if args.first == 'us' else 'second'}:")
    for b, win, gain in suggest_bans(model, mp, args.first == "us", banned, n=args.n):
        print(f"  {model.names[b].ljust(16)} → {_pct(win)} win chance ({gain * 100:+.1f} pts)")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    import shutil
    from pathlib import Path

    from .engine import fixtures

    src, web = Path(args.model), Path(args.web)
    if not src.is_file():
        raise SystemExit(f"error: {src} not found: run `mira train` first.")
    if not (web / "package.json").is_file():
        raise SystemExit(f"error: {web} doesn't look like the website folder.")
    dest = web / "public" / "model.json"
    shutil.copyfile(src, dest)
    n = fixtures.write(str(dest), str(web / "src" / "engine" / "parity.fixtures.json"))
    print(f"Copied {src} to {dest} and wrote {n} parity cases.")
    print(f"Next: (cd {web} && npm test), then commit {dest} to deploy.")
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
    sp.add_argument("--recrawl-hours", type=float, default=6.0,
                    help="longest wait before recrawling a player; active players are recrawled sooner, "
                         "before their 25-game log turns over (default: 6)")
    sp.add_argument("--workers", type=int, default=crawler.DEFAULT_WORKERS,
                    help="battle logs fetched in parallel; --rate still caps requests (default: %(default)s)")
    sp.add_argument("--watch", action="store_true",
                    help="run until stopped: when nobody is due, wait for the next player instead of exiting")
    sp.add_argument("--rate", type=float, default=10.0, help="max API requests per second (default: 10)")
    sp.add_argument("--ranked-types", default=",".join(sorted(crawler.DEFAULT_RANKED_TYPES)),
                    help="comma-separated battle.type values that count as ranked (default: %(default)s)")
    sp.add_argument("--min-rank", type=_rank_arg, default=crawler.DEFAULT_MIN_RANK,
                    help="only queue non-seed players seen in Ranked at this rank or higher: 0-22 or a "
                         "name like legendary1, masters3, pro; 0 disables (default: masters1 = 19)")
    sp.add_argument("--match-min-rank", type=_rank_arg, default=crawler.DEFAULT_MATCH_MIN_RANK,
                    help="only store ranked matches where all six players are at this rank or higher; "
                         "0 stores every Ranked match of the crawled players (default: masters1 = 19)")
    sp.add_argument("--all-types", action="store_true",
                    help="store every 3v3 battle type (trophy, friendly, ...), not just the ranked types")
    sp.set_defaults(func=cmd_crawl)

    sp = sub.add_parser("stats", help="show battle counts by type, mode, map and brawler")
    sp.add_argument("--type", help="only count this battle.type (type breakdown always shows all)")
    sp.add_argument("--top", type=int, default=20, help="rows for map/brawler tables")
    sp.add_argument("--min-rank", type=_rank_arg, default=crawler.DEFAULT_MIN_RANK,
                    help="threshold used in the rank tables (default: masters1 = 19)")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("readiness", help="matches per map in the current Ranked pool vs the training target")
    sp.add_argument("--target", type=int, default=readiness.DEFAULT_TARGET,
                    help="matches needed per map (default: %(default)s)")
    sp.add_argument("--pool-days", type=int, default=readiness.DEFAULT_POOL_DAYS,
                    help="a map is in the current pool if played in this many days (default: %(default)s)")
    sp.set_defaults(func=cmd_readiness)

    def model_args(sp):
        sp.add_argument("--patches", default="data/patches.json", help="balance patch log (default: %(default)s)")
        sp.add_argument("--half-life", type=float, default=28.0,
                        help="days for a match's weight to halve (default: %(default)s)")
        sp.add_argument("--pre-patch-factor", type=float, default=0.1,
                        help="weight multiplier for matches played before a patch changed one of their "
                             "brawlers (default: %(default)s)")
        sp.add_argument("--no-tune", action="store_true", help="skip the L2 grid search; use defaults")
        sp.add_argument("--min-lobby-rank", type=_rank_arg, default=19,
                        help="ignore matches whose lowest player is below this rank (default: masters1 = 19, "
                             "i.e. all-Masters lobbies only)")
        sp.add_argument("--rank-factor", type=float, default=0.5,
                        help="with --min-lobby-rank below 19: weight multiplier per rank step a lobby sits "
                             "below Masters I (default: %(default)s)")

    sp = sub.add_parser("evaluate", help="time-split test of the win model vs baselines")
    model_args(sp)
    sp.add_argument("--test-days", type=float, default=7.0, help="test on the newest N days (default: 7)")
    sp.set_defaults(func=cmd_evaluate)

    sp = sub.add_parser("train", help="fit the win model on all data and write model.json")
    model_args(sp)
    sp.add_argument("--out", default="model.json", help="output path (default: %(default)s)")
    sp.set_defaults(func=cmd_train)

    def draft_args(sp):
        sp.add_argument("--model", default="model.json", help="trained model (default: %(default)s)")
        sp.add_argument("--map", required=True, help="map name (prefix ok)")
        sp.add_argument("--first", choices=["us", "them"], required=True, help="who has first pick")
        sp.add_argument("--bans", help="comma-separated banned brawlers (both teams)")

    sp = sub.add_parser("suggest", help="suggest picks for the current draft and show the likely line")
    draft_args(sp)
    sp.add_argument("--ours", help="our picks so far, comma-separated, in pick order")
    sp.add_argument("--theirs", help="their picks so far, comma-separated, in pick order")
    sp.set_defaults(func=cmd_suggest)

    sp = sub.add_parser("bans", help="suggest bans for a map")
    draft_args(sp)
    sp.add_argument("-n", type=int, default=5, help="number of suggestions (default: 5)")
    sp.set_defaults(func=cmd_bans)

    sp = sub.add_parser("publish", help="copy model.json into the website and refresh its parity tests")
    sp.add_argument("--model", default="model.json", help="trained model (default: %(default)s)")
    sp.add_argument("--web", default="web", help="website folder (default: %(default)s)")
    sp.set_defaults(func=cmd_publish)

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
