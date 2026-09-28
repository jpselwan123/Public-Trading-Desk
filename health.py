"""What each data source did at the desk's last updates → health.json.

The company update and the account sync each run a list of steps (server.run_steps):
filings, news, prices, and so on; Trading 212 for the account. After each run, every
step's outcome is kept here: whether it worked, when, how long it took, what went wrong,
and when it last worked. The page shows it as one row on the Overview ("Data sources"),
and `python3 doctor.py` prints it, so a source that has quietly stopped working is seen
the day it stops rather than when a card looks empty.

Written by the server alone; read by the page build and the doctor. Today's only: a past
day's page shows none of it (asof.py).
"""
import json, os
from datetime import datetime, timezone

from env_config import scrub

HERE = os.path.dirname(os.path.abspath(__file__))
HEALTH_FILE = "health.json"
PARTS = (("market", "Company data"), ("account", "Your account"))


def load(folder):
    try:
        with open(os.path.join(folder, HEALTH_FILE)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(stored, part, timed, failed, now=None):
    """`stored` with one run of `part` added: `timed` is [(step, seconds)] in the order
    they ran, `failed` [(step, what went wrong)]. A step that did not run this time
    keeps what it had."""
    now = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    stored = dict(stored or {})
    steps = dict((stored.get(part) or {}).get("steps") or {})    # in the order first seen
    why = dict(failed or [])
    for name, seconds in timed or []:
        ok = name not in why
        steps[name] = {"ok": ok, "at": now, "seconds": round(float(seconds or 0), 1),
                       "why": None if ok else scrub(why[name])[:300],
                       "last_ok": now if ok else (steps.get(name) or {}).get("last_ok")}
    stored[part] = {"at": now, "steps": steps}
    return stored


def for_page(stored):
    """Each part's last run and its steps, in the order they ran, with how many failed."""
    out = []
    for part, label in PARTS:
        run = (stored or {}).get(part)
        if not run:
            continue
        steps = [dict(v, name=k) for k, v in (run.get("steps") or {}).items()]
        out.append({"part": part, "label": label, "at": run.get("at"), "steps": steps,
                    "failed": sum(1 for s in steps if not s.get("ok"))})
    return out
