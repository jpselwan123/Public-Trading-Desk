"""Small shared helpers: a minimal .env loader (avoids adding python-dotenv as a
dependency), an atomic file-write helper used everywhere this project writes
JSON or HTML to disk, the one test of whether a store was fetched today, and the one
reader of a moment in time, and the one unpacker of a compressed answer.
"""
import gzip, json, os, re
from datetime import datetime, timezone

OVERRIDE_KEY = 'DESK_ENV_OVERRIDE'      # set to 1 to let an exported variable win
# A store an update step returns with this key was updated in part: what was read is in it,
# and the value says why the rest was not. The step writes the rest and reports the reason
# (server.run_steps); it is never stored. A source failing halfway through a list must not
# lose what it answered before (28 Sep 2026).
PARTLY = "_partly"
# what every step that asks the SEC says when .env names no contact: one fix, one sentence
NO_SEC_CONTACT = ("Add SEC_CONTACT=your@email to .env — the SEC asks automated requests to "
                  "declare a contact address")


def unpacked(body, response):
    """An answer's body, unpacked when it came gzipped. Every source is asked for gzip: a JSON answer
    is about a tenth of the size compressed, and a ten-year price history
    or a company's filed facts is most of what following a company waits for (28 Sep 2026). A
    server may ignore the ask, so the answer's own header decides."""
    headers = getattr(response, "headers", None)
    if headers is not None and (headers.get("Content-Encoding") or "").lower() == "gzip":
        return gzip.decompress(body)
    return body


def load_env(path=None):
    """Load .env into the environment. The file is authoritative.

    This used to call os.environ.setdefault, which meant an exported shell variable
    beat the file. One `export EXECUTE_DRY_RUN=0` — typed once while testing, left in
    a .zshrc, or inherited by a future cron entry — turned the dry run off for every
    run from that shell, with the file that governs it still saying 1. desk.sh
    inherits the interactive shell, so this was silent. Those variables gate
    execution, so the file wins unless DESK_ENV_OVERRIDE=1 says otherwise.

    Returns the set of keys the file set, so a caller can say where a value came from.
    """
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    override = os.environ.get(OVERRIDE_KEY, '').strip() == '1'
    from_file = set()
    if not os.path.exists(path):
        return from_file
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            if override and key in os.environ:
                continue                     # deliberate, and reported as such
            os.environ[key] = value.strip().strip('"').strip("'")
            from_file.add(key)
    return from_file


def atomic_write(path, text):
    """Write text to path without ever leaving a truncated/corrupt file behind if
    the process is killed mid-write (a force-quit, or a subprocess timeout) — write
    to a temp file first, then rename, which is atomic on the filesystem."""
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def atomic_write_json(path, data, indent=None):
    atomic_write(path, json.dumps(data, indent=indent))


# every value in .env that must never be printed, logged, stored or sent to the page
SECRET_NAMES = ("T212_API_KEY", "T212_API_SECRET", "TIINGO_API_KEY", "FINNHUB_API_KEY", "OPENAI_API_KEY",
                "SEC_CONTACT")


def scrub(text, environ=None):
    """Blank every key value that appears in the text, however it got there (Finnhub's key
    travels in its addresses, and an error can quote one)."""
    environ = os.environ if environ is None else environ
    text = str(text)
    for name in SECRET_NAMES:
        value = (environ.get(name) or "").strip()
        if len(value) >= 6:
            text = text.replace(value, "[" + name.lower() + "]")
    return re.sub(r"(token=)[A-Za-z0-9_-]{6,}", r"\1[key]", text)


class UnreadableStore(Exception):
    pass


def read_for_writing(path, kind, empty):
    """A personal store, read before something is added to it: `empty` when there is none
    yet, its contents when they are a `kind` (dict or list). A file that is there but cannot
    be read raises UnreadableStore: it is never written over, so nothing in it is lost —
    plans and theses are written once, and a note written over a damaged journal would
    have been the only note left."""
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return empty
    except (OSError, ValueError):
        data = None
    if not isinstance(data, kind):
        raise UnreadableStore(f"{os.path.basename(path)} cannot be read, so nothing was written over it: "
                              "open it to mend it, or move it aside to start a new one.")
    return data


def fetched_today(stamp, today):
    """True when a store's stamp (an ISO date or time, in UTC like every stamp the desk
    writes) falls on `today`. A source that changes at most once a day is fetched on the
    first refresh of the day, not on every one: each request crosses a slow connection.
    Without `today`, today in UTC (28 Sep 2026: the exchange list's step passed none, and
    every company update after the first stopped there)."""
    today = today or datetime.now(timezone.utc).date()
    return bool(stamp) and str(stamp)[:10] == today.isoformat()


_MOMENT = re.compile(r"^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d(?::\d\d)?)(?:\.(\d+))?\s*(Z|[+-]\d\d:?\d\d)?$")


def moment(stamp):
    """A moment as any of the desk's sources or stores write it — ending in "Z", an offset,
    or neither (read as UTC, as every stamp the desk writes is), with any number of digits
    after the second (Tiingo writes nine) — as an aware datetime; None for anything else,
    a bare date included. The one reader: Python 3.9, the Mac's python3, reads neither a
    "Z" nor more than six digits with datetime.fromisoformat, and 3.11 reads both, so a
    call to it on a source's stamp passes every test here and fails only on the Mac."""
    m = _MOMENT.match(str(stamp or "").strip())
    if not m:
        return None
    zone = m.group(4)
    offset = "+00:00" if zone in (None, "Z") else zone if ":" in zone else zone[:3] + ":" + zone[3:]
    try:
        clock = m.group(2) if len(m.group(2)) == 8 else m.group(2) + ":00"
        return datetime.fromisoformat(f"{m.group(1)}T{clock}.{(m.group(3) or '0')[:6].ljust(6, '0')}{offset}")
    except ValueError:
        return None
