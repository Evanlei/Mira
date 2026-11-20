"""Download the game art the website shows into web/public/art, plus a manifest.

Brawler portraits, map layouts and mode icons come from Brawlify's public API/CDN
(art (c) Supercell, used under its Fan Content Policy). Only what the published
model uses is fetched, and files already on disk are skipped, so rerun this after
`mira publish` when new brawlers or maps appear.

    uv run python scripts/fetch_art.py [--db mira.db] [--web web]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.brawlapi.com/v1"
UA = {"User-Agent": "mira-draft-coach/0.1"}


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        dest.write_bytes(r.read())
    time.sleep(0.05)
    return True


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="mira.db")
    ap.add_argument("--web", default="web")
    args = ap.parse_args()

    web = Path(args.web)
    model = json.loads((web / "public" / "model.json").read_text())
    art = web / "public" / "art"
    manifest: dict = {"credit": "Game art (c) Supercell, via Brawlify", "modes": {}, "maps": {}, "brawlers": []}
    fetched = 0

    # Brawlers: ids are the API's, same as Brawlify's.
    for b in model["brawlers"]:
        try:
            fetched += download(f"https://cdn.brawlify.com/brawlers/borderless/{b['id']}.png",
                                art / "brawlers" / f"{b['id']}.png")
            manifest["brawlers"].append(b["id"])
        except Exception as e:  # noqa: BLE001 - report and keep going
            print(f"  no portrait for {b['name']} ({b['id']}): {e}", file=sys.stderr)

    # Modes: icon + official color, matched on the API's camelCase name.
    modes = {key(m.get("scHash") or m["name"]): m for m in get_json(f"{API}/gamemodes")["list"]}
    for mode in model["modes"]:
        m = modes.get(key(mode))
        if not m:
            print(f"  unknown mode {mode}", file=sys.stderr)
            continue
        fetched += download(m["imageUrl"], art / "modes" / f"{mode}.png")
        manifest["modes"][mode] = {"name": m["name"], "color": m.get("color"), "icon": f"/art/modes/{mode}.png"}

    # Maps: the crawler stores each battle's event id, which is Brawlify's map id.
    ids: dict[tuple[str, str], int] = {}
    if Path(args.db).exists():
        conn = sqlite3.connect(args.db)
        for mode, name, eid in conn.execute(
            "SELECT mode, map, event_id FROM battles WHERE event_id IS NOT NULL "
            "GROUP BY mode, map ORDER BY COUNT(*)"):
            ids[(mode, name)] = eid
    by_name = {(key(m["gameMode"]["name"]), key(m["name"])): m["id"] for m in get_json(f"{API}/maps")["list"]}
    for mp in model["maps"]:
        eid = ids.get((mp["mode"], mp["map"])) or by_name.get((key(mp["mode"]), key(mp["map"])))
        if not eid:
            print(f"  no map id for {mp['mode']} / {mp['map']}", file=sys.stderr)
            continue
        try:
            fetched += download(f"https://cdn.brawlify.com/maps/regular/{eid}.png", art / "maps" / f"{eid}.png")
            manifest["maps"][f"{mp['mode']}|{mp['map']}"] = f"/art/maps/{eid}.png"
        except Exception as e:  # noqa: BLE001
            print(f"  no image for map {mp['map']} ({eid}): {e}", file=sys.stderr)

    out = web / "src" / "lib" / "art.json"
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"Downloaded {fetched} new files; {len(manifest['brawlers'])} brawlers, "
          f"{len(manifest['modes'])} modes, {len(manifest['maps'])} maps in {out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
