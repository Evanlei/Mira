# Mira draft engine + website (MVP) — spec

Status: draft, 2026-11-20. Source: interview with Evan plus research (links at the end).

## 1. Goal

Mira suggests the best **pick or ban for the current draft slot** in Brawl Stars Ranked. It also
shows **how the rest of the draft is likely to go**: the most likely line, with the other plausible
picks at each step.

"Better than DeepDraft" means, in order of priority:

1. **Best picks for the draft state.** This is the product.
2. **Accurate win prediction** on held-out Masters matches. This is how we measure it (see §8).

## 2. Ranked draft format (what the engine must model)

- The map is known before the draft starts.
- **Bans:** 3 per team, and both teams may ban the same brawler. A banned brawler can't be picked
  by either team.
- **Picks:** 1-2-2-1 snake order: A, B, B, A, A, B.
- **Pick-order swaps** (Nov 2026 rework) change *who* is in a slot, not the order of the slots.
  Mira only needs "whose turn is it, and what has been picked or banned so far". The user enters
  picks in the order they happen, and Mira suggests for the slot that's up.
- Rank gate for the data: all six players Masters I or higher (already enforced by the crawler).

## 3. Data

**Source:** the existing crawler (`mira crawl`). It stores only `soloRanked` matches where all six
players are Masters I or higher. Each row has map, mode, both teams, winner, rank, power and the
raw JSON.

**What we don't get:** pick order and bans. The API doesn't expose them, and no existing tool seems
to have them either. The models below learn from **final teams only**.

**When to start training:** once every map in the current Ranked pool has **≥ 3,000** all-Masters
matches, about 72k matches across a 24-map pool.
- Add a `mira readiness` command (or a section in `stats`) that lists matches per map in the
  current pool against the target.
- "Current pool" = maps seen in `soloRanked` within the last 7 days.

**Where the crawler runs:** Evan's Mac, because the API key is locked to an IP. Run it on a
schedule, and recrawl every 6h as now.

**Patches:** keep a hand-maintained `data/patches.json`:
```json
[{"date": "2026-11-13", "changes": {"BRAWLER_NAME": "buff|nerf|new|rework"}}]
```
Training uses it as described in §4.4.

**User draft log (from launch):** every draft entered on the site is stored anonymously with pick
order and bans (§6.3). This is the only source of pick-order data, for a later model.

## 4. Models (trained offline in Python, exported as one JSON file)

### 4.1 Win model: P(team A wins | map, team A, team B)

A logistic model with three kinds of terms:

| term | meaning |
| --- | --- |
| `strength[b, map]` | brawler b's strength on this map |
| `synergy[b1, b2, mode]` | bonus or penalty for b1 and b2 on the **same** team |
| `matchup[b1, b2, mode]` | b1's edge over b2 on **opposite** teams (antisymmetric) |

logit = Σ strength(A) − Σ strength(B) + Σ synergy pairs(A) − Σ synergy pairs(B)
+ Σ matchup(A vs B)

**Thin data (hierarchical shrinkage):**
- `strength[b, map]` is pulled toward `strength[b, mode]`, which is pulled toward `strength[b]`.
- Synergy and matchup are estimated per mode, with an optional per-map term only where there's
  enough data. All pair terms have strong L2 regularization toward 0.
- The amount of shrinkage is chosen by validation (§8).

Each prediction also returns a **confidence** value, the effective sample size behind it, so the UI
can flag low-data estimates.

### 4.2 Pick model: P(brawler is picked | map, side, picks so far, bans)

This models "a typical Masters player". It's learned from final teams: how often b shows up on a
team on this map, given the other brawlers already on that team and on the enemy team.
- It conditions on co-occurrence with allies (who people pair) and with enemies (who people pick
  into).
- Smoothing follows the same map → mode → global hierarchy.
- Banned and already-picked brawlers are removed and the probabilities renormalized.
- **Known limitation:** without pick-order data it can't tell first picks from last picks. It's
  replaced later by a model trained on the user draft log (§10).

### 4.3 Search: suggestions and lines (expectimax)

- **State:** map, bans, picks so far, and whose turn it is.
- **Our nodes:** consider the top-K candidates by a quick heuristic (default K = 8) and take the
  max.
- **Opponent nodes:** take the top-N picks from the pick model (default N = 5), renormalize, and
  take the **probability-weighted average**. This is "opponent plays like typical Masters players",
  not worst-case.
- **Double-pick slots** (B, B or A, A) are handled as two picks in a row by the same side.
- **Leaves** are scored by the win model once all six are picked.
- **Depth:** the rest of the draft (at most 6 picks). It must run in under 300 ms on a mid-range
  phone; if it doesn't, reduce K and N on early slots.

**Bans:** a ban candidate is scored by how much it raises our expected win % when removed from the
pool, weighted by how likely the opponent is to pick it. Only the top ~15 candidates by map
strength and pick rate are evaluated. MVP: suggest bans for the whole team; bans are entered
together because they're simultaneous.

### 4.4 Patch-aware recalibration

- **Unchanged brawlers:** matches are weighted by age, with about a 4-week half-life.
- **Changed brawlers** (buff, nerf, new or rework in `patches.json`): pre-patch matches involving
  them are heavily discounted (e.g. ×0.1). Their estimates start from the pre-patch value, nudged in
  the direction of the change, and move to post-patch data as it comes in. New brawlers start from a
  mildly positive prior, because releases tend to be strong.
- **UI:** a "recalibrating · N games" badge on any brawler whose post-patch sample is below a
  threshold (e.g. 300 games).
- **Early signal:** a sudden rise in post-patch pick rate nudges strength upward until the win-rate
  data catches up. The weight for this is set by validation, and it can be turned off.

### 4.5 Export

A single `model.json` (versioned, with a `trained_at` field and the data window), containing:
- strength, synergy and matchup tables;
- pick-model tables;
- the brawler and map lists with icons' IDs;
- per-brawler recalibration flags.

The target is under ~2 MB gzipped so it loads quickly on phones.

## 5. Personalization (MVP)

- **Optional player tag field.** If set, only brawlers the player owns at **power 11 or higher**
  are suggested for our side. The power threshold is adjustable.
- The opponent pick model is **not** filtered, because we don't know their accounts.
- **Later:** boost or penalize brawlers using the player's own Ranked win history.

## 6. Website (MVP)

### 6.1 Stack and hosting

- Next.js (TypeScript) on **Vercel**, with a custom domain later.
- **Inference runs in the browser:** `model.json` is a static asset, and search runs client-side in
  a Web Worker. That makes it fast and free to serve, and it works on phones.
- **No login and no accounts** in the MVP.

### 6.2 Screens and flow

One page, mobile-first:

1. **Map picker:** current Ranked pool first, grouped by mode, plus search.
2. **Draft board:** 3 ban slots per team, then 6 pick slots in 1-2-2-1 order, and a "we pick
   first / second" toggle. Tapping a brawler fills the active slot. Undo, plus an edit mode for
   swaps or mistakes.
3. **Suggestions panel** for the active slot: the top 5 picks (or bans), each with win % and a
   confidence badge.
4. **Line view** (Evan's spec): one main line, the most likely continuation of the draft (our best
   pick → the opponent's most likely reply → …). At each step, the alternative possible picks are
   listed with their likelihood and the win % if taken.
   ```
   Now (you):  GALE 54%     alts: STU 53% · MELODIE 52%
   Them ×2:    PIPER+RICO (38%)   alts: AMBER+MAX 22% · BROCK+SPIKE 15%
   You ×2:     BYRON+GENE → 56%   alts: MORTIS+LOU 55%
   Them:       BELLE (27%)        alts: MAX 18% · SURGE 12%
   ```
   Tapping an alternative re-roots the line on that choice.
5. **Final analysis** once all 6 are picked: win % with a short breakdown of the biggest synergy
   and matchup terms ("why").

**Win % display (decided):** a whole-number percent ("54%"), plus a
low-confidence badge when the sample is thin.

### 6.3 Draft log

- When a draft is completed, or abandoned after at least 2 picks, POST
  `{map, bans, picks_in_order, side_first, model_version, suggestions_shown, timestamp}` to a Vercel
  function, stored in Postgres (Vercel/Neon) or Supabase.
- No personal data. Player tags are **not** stored with drafts.
- There's an optional "did you win?" tap after the draft, for future evaluation.

### 6.4 Player-tag lookup: needs a fix

The Brawl Stars API key only works from IPs on its whitelist, and Vercel functions don't have fixed
outbound IPs. Options:

1. Use a community proxy with a fixed IP (e.g. RoyaleAPI's proxy for Supercell APIs) and a key
   made for that IP.
2. Run a tiny lookup service on a host with a static IP (small VM).
3. Vercel Secure Compute, which has static IPs but is an Enterprise feature.

Default: **option 1 for the MVP**, if its terms allow it. Cache each player's brawler list for 1h.

## 7. Pipeline

**Decisions (2026-11-20):**
- **One repo.** The Python package stays at the root and the website lives in `web/`. Vercel's
  project root directory is set to `web/`.
- **Dependencies.** The trainer (`mira train`) may use **numpy**, added as an optional dependency
  group `train`. The crawler stays standard library only.

```
crawler (Mac) ──► mira.db ──► `mira train` ──► model.json ──► website repo /public ──► Vercel deploy
                                   ▲
                           data/patches.json
```

- `mira train`: fits the §4 models, writes `model.json` and an evaluation report (§8).
- `mira publish`: copies `model.json` into the site and commits it, which triggers a Vercel deploy.
  MVP: run by hand after each retrain, weekly or after a patch.

## 8. Evaluation (the bar for "done")

- **Split by time:** train on everything before the most recent 7 days, test on the last 7 days.
  Never split randomly, because it leaks the meta.
- **Win model metrics:** log loss (primary), Brier score, accuracy and a calibration plot.
  Baselines:
  1. 50/50;
  2. brawler-on-map win rates only;
  3. a **DeepDraft-style additive score**: base + synergy + counters − role conflict, rebuilt from
     their published description.
- **MVP passes** if the full model beats baseline 3 on held-out log loss, meaning the paired-bootstrap
  95% interval of the per-match difference excludes 0, and its calibration error (ECE over 10
  equal-count bins) is ≤ 0.03. Note: at ~2.5k test matches, a coin flip's ECE is already ~0.03 from
  noise alone, so this check only becomes meaningful at larger test sizes.
- **Implemented (2026-11-20):** `mira evaluate` and `mira train` (`src/mira/model/`). At 13.4k
  matches the win model is the best of the four (log loss 0.6898, ECE 0.015), but not yet clearly
  better than baseline 3. Tuning uses one validation slice and is noise-limited at this size;
  consider time-ordered K-fold tuning once data allows.
- **Pick quality checks:**
  - In held-out matches, how often the winning team's comp contained Mira's top-3 suggestion for a
    slot, against chance.
  - A manual head-to-head with DeepDraft on 20 drafts, recorded in a sheet.
  - Later: agreement with pro drafts (BSC) as a sanity set.
- **Search sanity:** the line's predicted opponent picks should match real held-out picks better
  than "most-picked brawler on this map".

## 9. MVP scope

**In:**
- the readiness check;
- `patches.json`;
- the win model, pick model, search and ban suggestions;
- the export to `model.json`;
- the one-page mobile site with the line view;
- the player-tag power filter;
- the anonymous draft log;
- the evaluation report.

**Out:**
- login and accounts;
- ads;
- languages other than English;
- personal win-history adjustment;
- the stream overlay;
- reading drafts from videos;
- a pick-order model;
- best-of-3 effects;
- automated retraining.

## 10. Later

1. A pick-order model trained on the user draft log, replacing §4.2's order-blind pick model.
2. Personal skill adjustment from the player's Ranked history.
3. A stream overlay for high-rank streamers (with consent), as a source of ordered Masters and Pro
   drafts.
4. Pro esports (BSC) drafts as an evaluation set.
5. Reading drafts from VODs, only with creator permission.
6. Automated crawl → train → publish on a schedule.

## 11. Open questions

1. **Player-tag lookup:** confirm the proxy option and check its terms (§6.4).
2. **Map icons and brawler art:** these are Supercell assets, so use them under Supercell's Fan
   Content Policy and credit it on the site.

## Sources

- Draft format and ranks: [PlayerVault](https://www.playervault.gg/blog/brawl-stars/ranked-system-explained),
  [Smart Draft Assistant](https://smartdraftassistant.com/ranked-draft-guide),
  [Brawl Draft](https://brawldraft.com/guide),
  [LDShop rework guide](https://www.ldshop.gg/blog/brawl-stars-gp/ranked-rework-guide.html),
  [TrophyCoach ranks](https://trophycoach.com/brawl-stars/guides/brawl-stars-ranks-explained)
- DeepDraft method and features: [deepdraft.fr/bsdraft](https://deepdraft.fr/bsdraft/),
  [deepdraft.fr](https://deepdraft.fr/), [stream board](https://deepdraft.fr/stream/)
- No pick order in the API: [r/BrawlStarsCompetitive thread](https://redlib.ssps.io/r/BrawlStarsCompetitive/comments/1l737t7/brawl_stars_public_api_evolution)
- BSC draft format: [White Market news](https://news.white.market/latest/brawl-stars-map-draft-global-bans-summer-split/)
