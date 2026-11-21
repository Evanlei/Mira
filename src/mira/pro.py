"""Pro esports drafts from Liquipedia (liquipedia.net/brawlstars).

Tournament pages record every map of every match in a ``{{Map ...}}`` template: the map and
mode, both teams' three picks (t1c1..t2c3) and three bans (t1b1..t2b3), the set score, and
sometimes which team picked first. The game's API has none of this for esports, and it never
shows bans at all, so this is our only source of what experts ban.

Liquipedia's API terms: a descriptive User-Agent, gzip, and at most one request every 2 s
(action=parse is stricter, so we read page source with action=query instead). Their content is
CC-BY-SA: credit Liquipedia wherever it's shown.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime

API = "https://liquipedia.net/brawlstars/api.php"
USER_AGENT = "MiraDraftCoach/0.1 (non-commercial draft statistics)"
MIN_INTERVAL = 2.5  # seconds between requests (terms: at most 1 per 2 s)
PAGES_PER_REQUEST = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_pages (
    title       TEXT PRIMARY KEY,
    edited_at   TEXT,              -- the page's last edit, from Liquipedia's search index
    fetched_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pro_maps (
    key         TEXT PRIMARY KEY,  -- page#match#map
    page        TEXT NOT NULL REFERENCES pro_pages (title),
    played_on   TEXT,              -- YYYY-MM-DD (the match's date, else the tournament's)
    mode        TEXT,              -- as Liquipedia writes it, e.g. "Gem Grab"
    map         TEXT,
    team1       TEXT,
    team2       TEXT,
    picks1      TEXT NOT NULL,     -- JSON list of 3 brawler names as written on Liquipedia
    picks2      TEXT NOT NULL,
    bans1       TEXT NOT NULL,     -- JSON list of 0-3 names
    bans2       TEXT NOT NULL,
    score1      INTEGER,           -- games won on this map (sets are best of 1 or 3, same draft)
    score2      INTEGER,
    first_pick  INTEGER            -- 0 = team1, 1 = team2, NULL = not recorded
);
CREATE INDEX IF NOT EXISTS idx_pro_maps_date ON pro_maps (played_on);
"""


# --- parsing ---------------------------------------------------------------------------------

@dataclass
class ProMap:
    key: str
    page: str
    played_on: str | None
    mode: str
    map: str
    teams: tuple[str, str]
    picks: tuple[list[str], list[str]]
    bans: tuple[list[str], list[str]]
    score: tuple[int, int]
    first_pick: int | None


_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S)
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"), 1)}


def _templates(text: str, name: str):
    """Bodies (between the name and the closing braces) of each top-level ``{{name ...}}``."""
    pat = re.compile(r"\{\{\s*" + re.escape(name) + r"\s*(?=[|}\n])", re.I)
    pos = 0
    while (m := pat.search(text, pos)) is not None:
        depth, i = 1, m.end()
        while i < len(text) and depth:
            if text.startswith("{{", i):
                depth += 1; i += 2
            elif text.startswith("}}", i):
                depth -= 1; i += 2
            else:
                i += 1
        yield text[m.end():i - 2]
        pos = i


def _params(body: str) -> tuple[list[str], dict[str, str]]:
    """Split a template body on top-level ``|``: (positional args, named args)."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; cur.append(two); i += 2
        elif two in ("}}", "]]"):
            depth -= 1; cur.append(two); i += 2
        elif body[i] == "|" and depth == 0:
            parts.append("".join(cur)); cur = []; i += 1
        else:
            cur.append(body[i]); i += 1
    parts.append("".join(cur))
    pos, named = [], {}
    for p in parts[1:]:  # parts[0] is whatever followed the template name (usually blank)
        k, eq, v = p.partition("=")
        if eq and re.fullmatch(r"\s*[\w ]+\s*", k):
            named[k.strip().lower()] = v.strip()
        else:
            pos.append(p.strip())
    return pos, named


def parse_date(s: str | None) -> str | None:
    """YYYY-MM-DD from '2025-11-28 - 13:00 ...' or 'November 28, 2025 - 13:00 ...'."""
    if not s:
        return None
    if m := re.search(r"(\d{4})-(\d\d)-(\d\d)", s):
        return "-".join(m.groups())
    if (m := re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", s)) and m.group(1).lower() in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    return None


def _team(v: str) -> str:
    """'{{TeamOpponent|sk gaming}}' -> 'sk gaming'."""
    for body in _templates(v, "TeamOpponent"):
        pos, named = _params(body)
        return (named.get("template") or (pos[0] if pos else "")).strip()
    return v.strip()


def _int(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v.isdigit() else None


def parse_page(title: str, text: str) -> list[ProMap]:
    """Every map with both teams' picks and a decided score."""
    text = _REF.sub("", _COMMENT.sub("", text))
    _, info = _params(next(_templates(text, "Infobox league"), ""))
    page_date = parse_date(info.get("edate") or info.get("sdate") or info.get("date"))
    out: list[ProMap] = []
    for mi, match in enumerate(_templates(text, "Match")):
        _, mp = _params(match)
        date = parse_date(mp.get("date")) or page_date
        teams = (_team(mp.get("opponent1", "")), _team(mp.get("opponent2", "")))
        for k in sorted((k for k in mp if re.fullmatch(r"map\d+", k)), key=lambda k: int(k[3:])):
            body = next(_templates(mp[k], "Map"), None)
            if body is None:
                continue
            _, f = _params(body)
            picks = tuple([f.get(f"t{t}c{i}", "").strip() for i in (1, 2, 3)] for t in (1, 2))
            if not all(all(p) for p in picks):
                continue
            s1, s2 = _int(f.get("score1")), _int(f.get("score2"))
            if s1 is None or s2 is None or s1 == s2:
                continue
            bans = tuple([b for i in (1, 2, 3) if (b := f.get(f"t{t}b{i}", "").strip())] for t in (1, 2))
            fp = (f.get("firstpick") or "").strip()
            first = 0 if fp == "1" or (fp and fp.lower() == teams[0].lower()) else \
                1 if fp == "2" or (fp and fp.lower() == teams[1].lower()) else None
            out.append(ProMap(f"{title}#{mi}#{k[3:]}", title, date, f.get("maptype", "").strip(),
                              f.get("map", "").strip(), teams, picks, bans, (s1, s2), first))
    return out


# --- names -----------------------------------------------------------------------------------

def norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


# Liquipedia spellings that differ from the game's names (after norm()).
BRAWLER_ALIASES = {
    "ll": "larrylawrie", "larryandlawrie": "larrylawrie", "larry": "larrylawrie",
    "colonelruffs": "ruffs", "dyna": "dynamike", "primo": "elprimo", "jae": "jaeyong",
    "nova": "starrnova", "melo": "melodie", "glowbert": "glowy",
}


def brawler_ids(conn: sqlite3.Connection) -> dict[str, int]:
    """norm(name) -> API brawler id, including the aliases above."""
    ids = {norm(r[1]): r[0] for r in conn.execute("SELECT id, name FROM brawlers")}
    for alias, target in BRAWLER_ALIASES.items():
        if target in ids:
            ids.setdefault(alias, ids[target])
    return ids


# --- fetching --------------------------------------------------------------------------------

class Liquipedia:
    def __init__(self, opener=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic):
        self._open, self._sleep, self._clock = opener, sleep, clock
        self._last = -1e9

    def _get(self, params: dict) -> dict:
        wait = self._last + MIN_INTERVAL - self._clock()
        if wait > 0:
            self._sleep(wait)
        data = urllib.parse.urlencode({**params, "format": "json"}).encode()
        req = urllib.request.Request(API, data=data, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        try:
            with self._open(req, timeout=60) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
        finally:
            self._last = self._clock()
        return json.loads(body)

    def draft_pages(self) -> dict[str, str]:
        """Title -> last-edit timestamp of every page with pro picks on it."""
        out, offset = {}, 0
        while True:
            d = self._get({"action": "query", "list": "search", "srsearch": 'insource:"t1c1"',
                           "srlimit": 500, "sroffset": offset, "srprop": "timestamp"})
            out.update({x["title"]: x["timestamp"] for x in d["query"]["search"]})
            if "continue" not in d:
                return out
            offset = d["continue"]["sroffset"]

    def contents(self, titles: list[str]) -> dict[str, str]:
        """Title -> current wikitext."""
        out = {}
        for i in range(0, len(titles), PAGES_PER_REQUEST):
            d = self._get({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                           "titles": "|".join(titles[i:i + PAGES_PER_REQUEST])})
            for p in d["query"]["pages"].values():
                if rv := p.get("revisions"):
                    out[p["title"]] = rv[0]["slots"]["main"]["*"]
        return out


# --- storage ---------------------------------------------------------------------------------

def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def store_page(conn: sqlite3.Connection, title: str, edited_at: str | None, maps: list[ProMap]) -> None:
    conn.execute("INSERT OR REPLACE INTO pro_pages VALUES (?, ?, ?)", (title, edited_at, time.time()))
    conn.execute("DELETE FROM pro_maps WHERE page = ?", (title,))
    conn.executemany(
        "INSERT OR REPLACE INTO pro_maps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(m.key, m.page, m.played_on, m.mode, m.map, m.teams[0], m.teams[1],
          json.dumps(m.picks[0]), json.dumps(m.picks[1]), json.dumps(m.bans[0]), json.dumps(m.bans[1]),
          m.score[0], m.score[1], m.first_pick) for m in maps])


@dataclass
class ImportStats:
    pages_seen: int = 0
    pages_fetched: int = 0
    maps: int = 0


def sync(conn: sqlite3.Connection, client: Liquipedia | None = None, full: bool = False,
         log=lambda s: None) -> ImportStats:
    """Fetch pages that are new or edited since the last sync (all of them with ``full``)."""
    init(conn)
    client = client or Liquipedia()
    stats = ImportStats()
    pages = client.draft_pages()
    stats.pages_seen = len(pages)
    known = dict(conn.execute("SELECT title, edited_at FROM pro_pages"))
    todo = [t for t, ts in pages.items() if full or known.get(t) != ts]
    log(f"{len(pages)} pages with pro drafts, {len(todo)} to fetch")
    for i in range(0, len(todo), PAGES_PER_REQUEST):
        batch = todo[i:i + PAGES_PER_REQUEST]
        for title, text in client.contents(batch).items():
            maps = parse_page(title, text)
            store_page(conn, title, pages.get(title), maps)
            stats.pages_fetched += 1
            stats.maps += len(maps)
        conn.commit()
        log(f"  {min(i + PAGES_PER_REQUEST, len(todo))}/{len(todo)} pages")
    return stats


def load_rows(conn: sqlite3.Connection, since: str | None = None) -> list[sqlite3.Row]:
    init(conn)
    return conn.execute(
        "SELECT * FROM pro_maps WHERE (? IS NULL OR played_on >= ?) ORDER BY played_on, key",
        (since, since)).fetchall()


def season_start(today: datetime | None = None, months: int = 12) -> str:
    """The date ``months`` before today, as YYYY-MM-DD."""
    t = today or datetime.now()
    y, m = divmod(t.year * 12 + t.month - 1 - months, 12)
    return f"{y:04d}-{m + 1:02d}-01"
