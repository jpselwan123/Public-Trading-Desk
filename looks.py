"""When the user last looked at the desk → looks.json: what "since you last looked" counts from.

It counted from the account sync before the last one (27 Sep 2026's review): pressing sync
twice emptied it, and without a sync it never moved on, though the company data now
updates by itself. A look is a visit to the page: every opening, and every reload the page
makes while it stays open, belongs to one visit until the desk has been closed for
VISIT_GAP. The digest counts from the end of the visit before this one.

Each served folder keeps its own (the demo never touches the real one); the phone's desk its
own too. Nothing in it is private but when the page was open: it stays on the machine.
"""
import json, os
from datetime import datetime, timedelta, timezone

from env_config import moment

LOOKS_FILE = "looks.json"
# The desk's choice: closed for an hour, the next opening is a new look. The page asks for
# fresh data every build_desk.MARKET_EVERY_MINUTES while open, well inside it.
VISIT_GAP = timedelta(hours=1)


def load(folder):
    try:
        with open(os.path.join(folder, LOOKS_FILE)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _moment(text):
    return moment(text)


def record(stored, now=None):
    """(the store with this moment of use recorded, whether it began a new visit). A new
    visit keeps the end of the last one as `previous`: what "since you last looked" means."""
    now = now or datetime.now(timezone.utc)
    stored = dict(stored or {})
    last = _moment(stored.get("last"))
    new_visit = last is None or now - last >= VISIT_GAP
    if new_visit and last is not None:
        stored["previous"] = last.isoformat(timespec="seconds")
    if new_visit:
        stored["visit_began"] = now.isoformat(timespec="seconds")
    stored["last"] = now.isoformat(timespec="seconds")
    return stored, new_visit


def since(stored):
    """The end of the visit before this one, or None the first time."""
    return (stored or {}).get("previous")
