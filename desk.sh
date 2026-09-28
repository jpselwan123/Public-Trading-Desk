#!/bin/bash
# Open the Trading Desk: start the local server (127.0.0.1 only) in the right
# mode, build the page if needed, and open it in the browser.
#   ./desk.sh          your account
#   ./desk.sh --demo   synthetic demo account
cd "$(dirname "$0")"
# new code first, if there is any and the connection allows (update.sh says what it did in server.log)
./update.sh >> server.log 2>&1
PORT=8935
URL="http://127.0.0.1:$PORT"
if [ "$1" = "--demo" ]; then
  WANT=true
  python3 scripts/generate_demo_data.py >/dev/null && python3 build_desk.py demo >/dev/null
else
  WANT=false
  # always rebuilt: after new code arrives (git pull), a page built before it would
  # still show the old design, and its old script would misread the new server
  python3 build_desk.py >/dev/null
fi
# always restart: the running server may predate the code you just changed, and a
# server left in the other mode would show the wrong account
lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null
sleep 0.5
# appended, as the Mac app does: a fresh file here erased the line update.sh had just written,
# which doctor.py reports as the last update
nohup python3 server.py "$@" >> server.log 2>&1 &
for _ in $(seq 1 20); do curl -s -o /dev/null "$URL/data" && break; sleep 0.25; done
if [ "$NO_OPEN" != 1 ]; then
  if [ "$(uname)" = Darwin ]; then open "$URL/"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL/" >/dev/null 2>&1
  else echo "The desk is at $URL/"; fi
fi
