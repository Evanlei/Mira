# Mira

A Brawl Stars draft coach. Step 1 is a crawler that collects 3v3 matches from the official API
into SQLite so draft models can be trained on them.

Python 3.11+, standard library only, managed with [uv](https://docs.astral.sh/uv/).

## Setup

1. Create a key at <https://developer.brawlstars.com>. Keys are locked to IP addresses, so add
   your current public IP (`curl ifconfig.me`) to the key's whitelist.
2. Put the token in `.env` (it's gitignored) or export it:

   ```sh
   echo 'BRAWLSTARS_API_TOKEN=eyJ0eXAi...' > .env
   ```

3. Install and check:

   ```sh
   uv sync
   uv run mira check      # "API key OK" or a clear 403 message about the key / IP whitelist
   ```

## Usage

```sh
uv run mira init                              # create mira.db
uv run mira seed --tags-file pros.txt         # queue hand-picked pro players (+ brawler list)
uv run mira seed --country global             # optional: also queue a trophy leaderboard
uv run mira crawl --minutes 30                # or --players 500; Ctrl-C stops cleanly
uv run mira crawl --watch --rate 20           # run nonstop, recrawling players as they come due
scripts/crawl-service.sh install              # same, as a macOS background job (see below)
uv run mira crawl --min-rank masters1         # stricter rank gate (default legendary1)
uv run mira crawl --all-types                 # also store trophy/friendly/event 3v3s
uv run mira stats                             # counts by battle type, mode, map, brawler
uv run mira stats --type soloRanked           # same, for one battle type
uv run mira export --out matches.csv          # one row per match
uv run mira export --type soloRanked --out ranked.csv
```

Global options: `--db PATH` (default `mira.db`) and `--env-file PATH` (default `.env`).

`crawl` options:

| option | default | meaning |
| --- | --- | --- |
| `--players N` | none | stop after N players |
| `--minutes M` | none | stop after M minutes |
| `--recrawl-hours H` | 6 | longest wait before a player is due again; active players come due sooner (below) |
| `--workers N` | 8 | battle logs fetched in parallel; `--rate` still caps the total |
| `--watch` | off | when nobody is due, wait for the next player instead of exiting |
| `--rate R` | 10 | max requests per second (30 has worked without 429s) |
| `--ranked-types T` | `soloRanked` | comma-separated `battle.type` values that count as ranked |
| `--match-min-rank R` | `legendary1` (16) | only store ranked matches where all six players are at this rank or higher; `0` stores them all |
| `--all-types` | off | store every 3v3 type; by default only the ranked types are stored |
| `--min-rank R` | `legendary1` (16) | only queue players seen in Ranked at this rank or higher; `0` turns the gate off |

### Keeping up with players

The API returns only a player's last 25 games, and an active Masters player fills that in
1.5–3.5 hours, so a fixed 6-hour recrawl loses most of their games. After each crawl the
player's next visit is set from the pace of the games in their log: 70% of the time 25 new
games would take, plus half the time they've been idle. It is never less than 20 minutes and
never more than `--recrawl-hours`.

`scripts/crawl-service.sh install` runs `mira crawl --watch --rate 20 --workers 16` under
launchd: it starts at login, restarts if it exits (5 minutes after a failure such as a 403
from a new IP) and logs to `~/Library/Logs/mira-crawl.log`. `status`, `log` and `uninstall`
do what they say. The Mac has to be awake and on a whitelisted IP.

### Daily retrain and deploy

`scripts/retrain-service.sh install` runs `scripts/retrain.sh` every day at 04:30 (on wake if the
Mac was asleep): it snapshots the database with `VACUUM INTO`, trains with the settings `evaluate`
chose, refuses a model trained on fewer matches than the live one, and pushes only
`web/public/model.json` and the engine parity fixtures to main, from a separate worktree
(`.retrain-worktree`) so your own checkout is never touched. Vercel redeploys on the push.
`scripts/retrain.sh --dry-run` trains and checks without pushing; `status`, `run` and `log` do what
they say. Log: `~/Library/Logs/mira-retrain.log`.

## Seeding and the rank gate

The API has no Ranked-mode leaderboard (`/rankings/{country}/players` is trophies only), so you
seed with a list of pro players and the crawler expands from there through Ranked games.

**Tags file**: one tag per line, optionally followed by a name. Lines without a valid tag, such as
comments or blanks, are skipped:

```text
# NA pros
#2PP0Q9YL  Some Pro
#8QJV2R,   Another Pro
```

Seeds are always crawled. Other players are added to the queue only if they appear in a Ranked
battle at `--min-rank` or higher. Players met only in trophy, friendly or event games are not
queued. Players below the threshold get their rank recorded but aren't crawled. If they're later
seen at a higher rank, they're queued then. The queue query applies the same gate, so players added
by an earlier ungated crawl are skipped too. The gate only controls who gets crawled: every 3v3
battle in a crawled log is still stored, subject to the match check below.

**Match check**: a Ranked match is stored only if all six players are at `--match-min-rank` or higher.
The default is Legendary I (16): after the November 2026 ranked reset most Masters players sit in
Legendary while they climb back, and only ~2% of their games had six current Masters players (74%
were all Legendary I+). Each stored match keeps its lowest player's rank in `battles.lobby_rank`;
training weights lower lobbies down and tests on all-Masters games only (see below). Use
`--match-min-rank masters1 --min-rank masters1` for the old all-Masters-only crawl.

The rank comes from `brawler.trophies`, which in Ranked battles holds the player's rank instead of
trophies. The assumed encoding is 1–3 Bronze I–III, 4–6 Silver, 7–9 Gold, 10–12 Diamond,
13–15 Mythic, 16–18 Legendary, 19–21 Masters, and 22 Pro. `--min-rank` accepts either the number or a
name (`mythic3`, `legendary1`, `masters2`, `pro`). `mira stats` shows the raw values seen in Ranked
battles, so you can confirm the encoding. It also lists seeds whose observed rank falls below the
threshold, which helps catch wrong tags in the pro list.

The first Ctrl-C finishes the current player, commits, and prints a summary. A second Ctrl-C aborts
immediately. Every player is committed on its own, so an abort loses at most one battle log.

## How it works

**API client** (`src/mira/api.py`): Bearer token, tags normalized (uppercase, `O`→`0`) and
URL-encoded (`#` → `%23`). Requests are spaced by `1/rate` seconds. 429 and 5xx responses and
network errors are retried up to 5 times, using `Retry-After` when present and exponential
backoff (1, 2, 4… s, capped at 60) otherwise. 403 raises `AuthError` with the API's reason, such
as `accessDenied.invalidIp`. 404 marks the player `missing` and they are not crawled again.

**Parsing** (`src/mira/parse.py`): only entries with exactly two teams of three distinct players and
a result are kept. Showdown, Duels, 5v5 and bot/odd formats are skipped. `battle.result` is from the
log owner's point of view: the winning team is the owner's team on `victory` and the other team on
`defeat`. A `draw` sets `is_draw=1` and `winning_team=NULL`. Every participant's log contains the
same match, so `battle_id = sha256(battleTime + sorted player tags)` dedups them.

**Crawl order** (`src/mira/crawler.py`): seeds (tags file or leaderboard) get priority 3.
Players found in a ranked battle get 2. Everyone else gets 1, but they are only queued when the
rank gate is off (`--min-rank 0`). A player's priority only ever
goes up. The queue is ordered by priority, then never-crawled first, then discovery time
(breadth-first). Only players from stored 3v3 battles are added to the queue.

### Schema

| table | key columns |
| --- | --- |
| `players` (the queue) | `tag`, `priority`, `status` (pending/done/missing/error), `last_crawled`, `ranked_seen`, `max_rank`, `is_seed`, `last_error` |
| `battles` | `battle_id`, `battle_time`, `mode`, `map`, `battle_type`, `winning_team` (0/1), `is_draw`, `raw_json` |
| `battle_players` | `battle_id`, `team` (0/1), `slot` (0–2, API order), `player_tag`, `brawler_id`, `brawler_name`, `power`, `trophies` |
| `brawlers` | `id`, `name` |

`raw_json` holds the full log entry, so new fields can be backfilled later without recrawling.

### Export format

`battle_id, battle_time, map, mode, type, team1_brawler1..3, team2_brawler1..3, winner`, where
`winner` is `1`, `2` or `draw`. Brawlers within a team are in the API's slot order, not pick order.

## Battle types

Checked against a live crawl on 2026-11-19 (567 matches):

| `battle.type` | meaning | evidence |
| --- | --- | --- |
| `soloRanked` | **Ranked mode** | `brawler.trophies` ranged 14–20 (rank values); 6 modes × 4 maps, the Ranked map pool |
| `ranked` | **trophy ladder** (the name is historical) | `brawler.trophies` ranged 0–3005 (real brawler trophies) |
| `friendly` | friendly games | `brawler.trophies` is `-1` |

By default `crawl` stores only `soloRanked` matches. Use `--all-types` to keep the rest.

## Training and evaluation

```sh
uv run mira readiness            # matches per map vs the 3,000-per-map training target
uv run mira evaluate             # time-split test: win model vs coin / map win rates / DeepDraft-style
uv run mira train --out model.json
```

Training needs numpy. It's in the `train` dependency group, which `uv sync` installs by default;
the crawler itself has no dependencies.

- **Win model** (`src/mira/model/winmodel.py`): regularized logistic regression on brawler strength
  (global + per mode + per map), same-team synergy pairs and cross-team matchups (each all-modes +
  per-mode). Each group has its own L2 penalty, tuned on the newest 20% of training data.
- **Weights** (`src/mira/model/patches.py`): matches fade with a 28-day half-life. Matches played
  before a patch changed one of their brawlers count ×0.1. Patches are listed in `data/patches.json`.
- **Lobby rank**: all-Masters lobbies weigh 1, and each rank step below Masters I multiplies a match's
  weight by `--rank-factor` (default 0.5: Legendary III 0.5, II 0.25, I 0.125). Lobbies below
  `--min-lobby-rank` (default Legendary I) are not loaded. The test set and the baselines use
  all-Masters matches only, and `evaluate` also reports Mira trained on all-Masters matches only: keep
  the lower lobbies only while they beat that. `--min-lobby-rank masters1` trains on Masters only.
  Every Legendary I+ lobby counts, not only those whose players have all been Masters (`--min-peak
  masters1` restores that filter). On 9.7k held-out all-Masters games (Nov 2026), all Legendary
  lobbies gave log loss 0.6821 vs 0.6841 with the filter (95% CI excludes 0), better in Masters I and
  II, with the same per-brawler win-rate error (1.47% vs 1.45%). The one visible cost is skill
  brawlers: Legendary players do worse with Leon, which drags his strength down a little.
  `evaluate` prints the per-brawler error next to the Masters-only model's, to keep watching this.
- **Rank tiers**: each match gets a tier from its lobby's average rank (Legendary, Masters I,
  Masters II, Masters III+). The win model adds per-tier brawler strength terms (shrunk toward the
  shared value by their own L2) and the pick model keeps per-tier pick rates per map. `evaluate`
  prints a per-tier comparison against one shared model; with today's data the tier strength terms
  don't help at Masters, so `train --tier-l2 1000` keeps them tight, while per-tier pick rates do
  help. `mira suggest --tier mastersiii` (or the web engine's `withTier`) drafts for a tier.
- **Pro scrims**: the crawler also stores friendly 3v3s where at least 4 of the 6 players are pros
  (seen at Pro rank, or listed in the seeds file), as battle type `friendly`; training ignores them
  for now (`crawl --no-pro-scrims` turns this off).
- **Baselines** (`src/mira/model/baselines.py`): their statistics come from training data, and their
  weights are fitted out-of-fold so they aren't overconfident. The DeepDraft-style score rebuilds
  DeepDraft's published method (base + synergy ± counters − role conflict) with fitted weights.
- **Pick model** (`src/mira/model/pickmodel.py`): how likely a typical Masters player is to pick each
  brawler, from map pick rates plus ally/enemy co-occurrence. It's learned from final teams, so it
  can't tell early picks from late ones.
- **MVP bar:** the paired-bootstrap 95% interval of log loss vs the DeepDraft-style baseline excludes
  0, and calibration error is at most 0.03.

## Draft suggestions

```sh
uv run mira suggest --map "Hard Rock Mine" --first us                       # empty draft
uv run mira suggest --map "hard rock" --first them --theirs piper --bans gus,shade
uv run mira bans --map "Hard Rock Mine" --first us
```

`suggest` runs an expectimax search over the rest of the draft (`src/mira/engine/search.py`). On your
turns it takes the best option; on theirs it weighs their most likely picks by probability. It
prints the top options for the current turn and the most likely line, with alternatives at each
step. The engine reads only `model.json` and uses the standard library, so it is the reference for
the website's port.

Our candidates are ranked, and the best one chosen, by `gain - kappa * sd + gamma * log pick rate`
(`Model.adjust`). `sd` is each brawler's strength error on the map (a Laplace approximation from
the fit, wide for brawlers with few games there), so the brawler with the highest *estimate* can't
top the list on noise alone; the pick-rate term counts what Masters players actually pick. `train`
tunes both on the newest 20% of matches: the held-out picks closest to our top choice should win as
often as without the adjustment (within one standard error), and among the settings that do, it
takes the one leaning least on few-game brawlers. `--kappa` / `--gamma` fix them instead. Displayed
win chances are always the plain win model's.

### Pro drafts

```sh
uv run mira pro-sync          # import pro esports picks, bans and results from Liquipedia
uv run mira pro-eval          # check model.json against the last 6 months of pro drafts
```

`pro-sync` (`src/mira/pro.py`) reads every Liquipedia page with pro drafts (about 330 tournament
pages, 9,000 maps since 2022) into `pro_pages` / `pro_maps`: map, mode, teams, both teams' three
picks and three bans, set score and, where recorded, which team picked first. It follows
Liquipedia's API terms (descriptive User-Agent, gzip, one request every 2.5 s) and refetches only
pages edited since the last sync. Pick order within a team isn't recorded. Liquipedia content is
CC-BY-SA: credit it wherever pro data is shown.

`train` turns them into per-map pro pick and ban rates (`src/mira/model/prorates.py`): the last 60
days, half-life 15 days, shrunk map -> mode -> Masters pick rate (picks) or all pro maps (bans).
The window is short on purpose: pro bans from the 30-60 days before a test window predict its bans
(about 41% in the top 6), bans from 90+ days back do no better than the Ranked pick rate, because
balance changes keep moving the meta. Ban suggestions rank by win gain + `ban_lambda` x pro ban
rate; our picks can add `rho` x log pro pick rate. Both are tuned in `train` (`model/protune.py`)
on the newest 60 days of pro maps, with rates built only from older ones:

- Picks: a setting must keep the real held-out win rate of the Masters picks we'd rank best within
  one standard error of the best (that objective alone favours rare brawlers, whose games are
  mostly played by their mains), and among those it takes the one that ranks pro picks highest.
  First result (Nov 2026): `gamma` 0.05 doubles pro agreement (top 5: 7% -> 20%) at no cost in
  Masters; `rho` > 0 is rejected because pro favourites win *less* in Masters solo queue.
- Bans: pro bans in our top 6 go from 29% to 40% at `ban_lambda` 0.05.

Ranked battle logs don't give pick order (a team's players are listed roughly by rank), but
Liquipedia lists picks in pick order: on maps with a known first pick, popularity falls with the
1-2-2-1 turn (0.52% of pro picks at turn 1, 0.36% at turn 6).

`pro-eval` (`src/mira/proeval.py`) scores a model on recent pro maps it knows: whether the win model
calls the winner, how many pro bans are in Mira's top bans (vs Ranked pick rate and the pros' own
ban rate on the map in other matches), and where Mira ranks each pro pick with the other five known
(vs the Masters pick rate).

**Caveat:** the "expected win chance" is optimistic. The search keeps the best of several noisy
estimates and assumes the opponent picks like a typical player, not a counter-picker. Trust the
ranking more than the absolute %.

## Website

The draft coach site lives in [`web/`](web/README.md): Next.js, a static page, with the engine
running in the browser. After retraining, run `uv run mira publish` to copy the model into the site
and refresh its parity tests.

## Tests

```sh
uv run python -m unittest discover -s tests
(cd web && npm test)
```

The tests are offline. They use a fake API client, sample battle logs (`tests/fakes.py`) and a
scripted `urlopen` to cover retries, `Retry-After`, 403/404 and throttling.
