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

from env_config import SETUP_STEPS, scrub

HERE = os.path.dirname(os.path.abspath(__file__))
HEALTH_FILE = "health.json"
PARTS = (("market", "Company data"), ("account", "Your account"))
SLOWEST_SHOWN = 3            # steps named in the time a refresh took: a presentation limit


def duration(seconds):
    whole = int(round(seconds))
    return f"{whole} s" if whole < 60 else f"{whole // 60} min {whole % 60} s"


def timing(steps, wall=None):
    """How long a refresh took and its SLOWEST_SHOWN longest steps: "Took 1 min 12 s; longest: Financials
    38 s, Prices 21 s, Trading 212 6 s." `steps` is [(name, seconds)]. Steps in different lanes run side by
    side, so what the refresh took is `wall`, the clock's, when given; without it the steps' sum, which is
    the time of steps that ran one after another. None for a refresh with no steps (the demo)."""
    if not steps:
        return None
    longest = sorted(steps, key=lambda s: s[1], reverse=True)[:SLOWEST_SHOWN]
    took = sum(s for _, s in steps) if wall is None else wall
    return f"Took {duration(took)}; longest: " + ", ".join(f"{name} {duration(s)}" for name, s in longest) + "."


def load(folder):
    try:
        with open(os.path.join(folder, HEALTH_FILE)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(stored, part, timed, failed, now=None, wall=None):
    """`stored` with one run of `part` added: `timed` is [(step, seconds)] in the order
    they ran, `failed` [(step, what went wrong)], `wall` the seconds the whole run took by the
    clock. A step that did not run this time keeps what it had."""
    now = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    stored = dict(stored or {})
    steps = dict((stored.get(part) or {}).get("steps") or {})    # in the order first seen
    why = dict(failed or [])
    for name, seconds in timed or []:
        ok = name not in why
        steps[name] = {"ok": ok, "at": now, "seconds": round(float(seconds or 0), 1),
                       "why": None if ok else scrub(why[name])[:300],
                       "last_ok": now if ok else (steps.get(name) or {}).get("last_ok")}
        if not ok and why[name] in SETUP_STEPS:
            steps[name]["setup"] = True                # it only lacks a key: waiting for it, not failed
    stored[part] = {"at": now, "steps": steps}
    if wall is not None:
        stored[part]["seconds"] = round(float(wall), 1)
    return stored


def for_page(stored):
    """Each part's last run and its steps, in the order they ran, with how many failed and how
    many are only waiting for a key to be added."""
    out = []
    for part, label in PARTS:
        run = (stored or {}).get(part)
        if not run:
            continue
        steps = [dict(v, name=k) for k, v in (run.get("steps") or {}).items()]
        out.append({"part": part, "label": label, "at": run.get("at"), "seconds": run.get("seconds"), "steps": steps,
                    "failed": sum(1 for s in steps if not s.get("ok") and not s.get("setup")),
                    "waiting": sum(1 for s in steps if not s.get("ok") and s.get("setup"))})
    return out
