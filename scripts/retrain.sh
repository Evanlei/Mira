#!/bin/sh
# Retrain the model on the latest data and deploy it: snapshot the database, train, check the
# result, and push only the model files to main (Vercel redeploys on push).
#
# The commit is made in a separate worktree (.retrain-worktree, detached at origin/main), so it
# never touches uncommitted work in your own checkout. Run by scripts/retrain-service.sh daily;
# run it by hand with --dry-run to train and check without pushing.
set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
WORK="$REPO/.retrain-worktree"
CACHE="${XDG_CACHE_HOME:-$HOME/Library/Caches}/mira"
SNAP="$CACHE/snapshot.db"
OUT="$CACHE/model.json"
UV=$(command -v uv || echo "$HOME/.local/bin/uv")
DRY=${1:-}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
cd "$REPO"
mkdir -p "$CACHE"

# 1. A consistent copy of the database. VACUUM INTO reads one snapshot, so the crawler can keep
#    writing (the .backup command restarts on every write and never finishes under the crawler).
log "snapshot"
rm -f "$SNAP"
sqlite3 mira.db ".timeout 60000" "VACUUM INTO '$SNAP'"
[ "$(sqlite3 "$SNAP" 'pragma quick_check')" = "ok" ] || { log "snapshot failed its integrity check"; exit 1; }

# 2. Train with the settings `mira evaluate` chose (see README: Training and evaluation).
log "train"
"$UV" run mira --db "$SNAP" train --rank-factor 0.5 --tier-l2 1000 --out "$OUT"

# 3. Fresh copy of main to commit in.
git fetch -q origin main
if [ ! -d "$WORK" ]; then
  git worktree add -q --detach "$WORK" origin/main
fi
git -C "$WORK" checkout -q --detach origin/main
git -C "$WORK" reset -q --hard origin/main

# 4. Sanity check: never replace the live model with one trained on less data.
new=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['n_matches'])" "$OUT")
old=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('n_matches', 0))" "$WORK/web/public/model.json" 2>/dev/null || echo 0)
log "matches: live $old, new $new"
if [ "$new" -lt "$old" ]; then
  log "new model has fewer matches than the live one; not deploying"
  exit 1
fi

# 5. Copy it into the worktree's site with fresh engine parity fixtures.
"$UV" run mira publish --model "$OUT" --web "$WORK/web" >/dev/null

if git -C "$WORK" diff --quiet -- web/public/model.json; then
  log "model unchanged; nothing to deploy"
  exit 0
fi
if [ "$DRY" = "--dry-run" ]; then
  log "dry run: would commit and push $(git -C "$WORK" diff --stat -- web | tail -1)"
  exit 0
fi

git -C "$WORK" add web/public/model.json web/src/engine/parity.fixtures.json
git -C "$WORK" commit -q -m "Retrain the model on $new Ranked matches (automatic)

Daily retrain by scripts/retrain.sh: Legendary I+ lobbies at 0.5 per rank below
Masters, rank-tier strength terms held tight (L2 1000).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
# If main moved meanwhile, replay the model commit on top and try once more.
if ! git -C "$WORK" push -q origin HEAD:main; then
  git -C "$WORK" fetch -q origin main
  git -C "$WORK" rebase -q origin/main
  git -C "$WORK" push -q origin HEAD:main
fi
log "deployed: $(git -C "$WORK" log --oneline -1)"
