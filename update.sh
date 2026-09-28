#!/bin/bash
# Bring in new code before the desk starts, when you have asked for it: AUTO_UPDATE=1 in
# .env. Run by desk.sh and by Trading Desk.app each time they open; off by default, so the
# code you run changes only when you choose.
#
# Safe by construction:
#   - only on the main branch, and only a fast-forward: it never merges and never
#     overwrites an edited file; the data files git ignores are never touched;
#   - the download gives up after UPDATE_WAIT seconds (a slow connection, or none), and
#     the desk opens on the code it already has;
#   - when an update changes the Mac app itself, the app is rebuilt in the background,
#     so the next opening runs the new one.
# Every attempt is one line in server.log.
cd "$(dirname "$0")" || exit 0
UPDATE_WAIT=${UPDATE_WAIT:-20}
stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S') update: $*"; }

grep -qE '^[[:space:]]*AUTO_UPDATE[[:space:]]*=[[:space:]]*1' .env 2>/dev/null || [ "${AUTO_UPDATE:-}" = "1" ] \
  || { stamp "off (AUTO_UPDATE=1 in .env turns it on)"; exit 0; }

[ -d .git ] || { stamp "not a git checkout; skipped"; exit 0; }
[ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "main" ] || { stamp "not on main; skipped"; exit 0; }
before=$(git rev-parse HEAD)

# the download alone is timed out: stopping it never leaves the checkout half-written
GIT_TERMINAL_PROMPT=0 git fetch --quiet origin main 2>/dev/null &
fetching=$!
( sleep "$UPDATE_WAIT"; kill "$fetching" 2>/dev/null ) &
watchdog=$!
if ! wait "$fetching"; then
  kill "$watchdog" 2>/dev/null
  stamp "no connection to GitHub within ${UPDATE_WAIT}s; opening on $(git log --oneline -1)"
  exit 0
fi
kill "$watchdog" 2>/dev/null

if ! git merge --ff-only --quiet origin/main 2>/dev/null; then
  stamp "not updated: a local edit is in the way (git status shows it); opening on $(git log --oneline -1)"
  exit 0
fi
after=$(git rev-parse HEAD)
if [ "$before" = "$after" ]; then
  stamp "up to date ($(git log --oneline -1))"
  exit 0
fi
stamp "updated to $(git log --oneline -1)"

if [ -n "$(git diff --name-only "$before" "$after" -- native_app)" ] && command -v swiftc >/dev/null 2>&1; then
  stamp "the Mac app changed; rebuilding it in the background for next time"
  nohup ./native_app/build.sh --install >> server.log 2>&1 &
fi
exit 0
