"""Read-only Trading 212 sync → t212_data.json.

Pulls the account summary, open positions, and full history (orders, dividends,
cash transactions) from the official Trading 212 Public API (v0, beta). History
is incremental: after the first pull, only pages with new items are fetched.

READ ONLY. The client has one method, `get`, and it reaches only READ_PATHS: nothing
here can place, change or cancel an order. Create the API key with the Account data,
Portfolio and History scopes and leave Orders unticked, so Trading 212 itself refuses a
write as well.

Credentials come from .env (never printed, never written anywhere else):
    T212_API_KEY=...        T212_API_SECRET=...      T212_ENV=live   (or demo)

Usage:  python3 t212.py            sync
        python3 t212.py --check    test the key (one request) and exit
"""
import base64, http.client, json, os, socket, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from env_config import load_env, atomic_write_json, read, unpacked

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "t212_data.json")
HOSTS = {"live": "https://live.trading212.com", "demo": "https://demo.trading212.com"}
API = "/api/v0"

# Every endpoint this app is allowed to call. All GET. Nothing that trades.
READ_PATHS = (
    "/equity/account/summary",
    "/equity/positions",
    "/equity/history/orders",
    "/equity/history/dividends",
    "/equity/history/transactions",
)

PAGE_LIMIT = 50          # API maximum per page
MAX_RETRIES = 4          # waits on a rate limit, which says when to come back
CONNECTION_RETRIES = 2   # a connection that failed three times is down: say so
TIMEOUT = 30


class T212Error(Exception):
    pass


def credentials():
    load_env(os.path.join(HERE, ".env"))
    key = os.environ.get("T212_API_KEY", "").strip()
    secret = os.environ.get("T212_API_SECRET", "").strip()
    env = os.environ.get("T212_ENV", "live").strip().lower() or "live"
    if env not in HOSTS:
        raise T212Error("T212_ENV must be 'live' or 'demo'")
    if not key or not secret:
        raise T212Error("No Trading 212 key yet: add T212_API_KEY and T212_API_SECRET to .env")
    return key, secret, env


class Client:
    """GET-only client with the API's rate-limit headers respected."""

    def __init__(self, key, secret, env="live", opener=None, sleep=time.sleep):
        token = base64.b64encode(f"{key}:{secret}".encode()).decode()
        self._auth = "Basic " + token
        self.host = HOSTS[env]
        self.env = env
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def get(self, path):
        base = path.split("?", 1)[0]
        if base.startswith(API):
            base = base[len(API):]
        if base not in READ_PATHS:
            raise T212Error(f"Refusing to call {base}: not a read-only path this app uses")
        url = self.host + API + base + (("?" + path.split("?", 1)[1]) if "?" in path else "")
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": self._auth, "Accept": "application/json", "Accept-Encoding": "gzip",
            "User-Agent": "trading-desk (personal, read-only)"})
        try:
            body, r = read(req, self._open, TIMEOUT, self._sleep, retries=CONNECTION_RETRIES, rate_retries=MAX_RETRIES,
                           wait=lambda e, attempt: self._wait_seconds(e.headers, default=10),
                           after=lambda r: self._pace(r.headers))
        except urllib.error.HTTPError as e:
            if e.code == 403 and b"Access Denied" in error_body(e):
                raise T212Error("Trading 212 is blocking this internet connection (its website refuses "
                                "this network or location), so the key was never checked") from None
            raise T212Error(explain_status(e.code, base)) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                http.client.HTTPException) as e:
            reason = getattr(e, "reason", None) or "timed out"
            raise T212Error(f"Can't reach Trading 212 ({reason}); check your connection and try again") from None
        try:
            body = unpacked(body, r)
            return json.loads(body) if body else None
        except (ValueError, OSError, EOFError):
            # a network's own page in place of Trading 212's answer
            raise T212Error("Trading 212's answer could not be read: another page came back in its "
                            "place (a network sign-in page?); check the connection and try again") from None

    def _pace(self, headers):
        """If this call used the last request of the window, wait for the reset
        before returning, so the next call never hits a 429."""
        try:
            remaining = int(headers.get("x-ratelimit-remaining", "1"))
        except (TypeError, ValueError):
            return
        if remaining <= 0:
            self._sleep(self._wait_seconds(headers, default=10))

    @staticmethod
    def _wait_seconds(headers, default):
        try:
            reset = float(headers.get("x-ratelimit-reset"))
            return max(0.5, min(70.0, reset - time.time() + 0.5))
        except (TypeError, ValueError):
            return default

    def pages(self, path, known_ids=(), key=None):
        """Walk a newest-first paginated list.

        With `key`, stop at the first page whose items are all already stored, which
        is what an incremental history sync wants: history never changes once written.
        Without it, keep going to the end of the list and let the caller decide when
        to stop — a caller trying to prove something is *absent* has to be able to
        reach every page, not just the newest one."""
        next_path = f"{path}?limit={PAGE_LIMIT}"
        while next_path:
            page = self.get(next_path) or {}
            items = page.get("items") or []
            yield items
            if key is not None and items and all(key(i) in known_ids
                                                 for i in items if key(i) is not None):
                return
            next_path = page.get("nextPagePath")


def error_body(e):
    try:
        return e.read(2_000_000) or b""
    except Exception:
        return b""


def explain_status(code, path):
    if code == 401:
        return ("Trading 212 rejected the key: check T212_API_KEY / T212_API_SECRET in .env (and T212_ENV "
                "live/demo); if the key is IP-restricted, your internet IP may have changed")
    if code == 403:
        scope = {"/equity/account/summary": "Account data", "/equity/positions": "Portfolio"}.get(path, "History")
        return (f"Trading 212 refused access: either the key has no '{scope}' permission, or it is "
                "restricted to other IP addresses (your internet IP may have changed)")
    if code == 408:
        return "Trading 212 timed out; try again"
    if code == 429:
        return "Trading 212 is limiting how often it is asked; try again in a minute"
    if code >= 500:
        return f"Trading 212 had a problem on its side (HTTP {code}); try again shortly"
    return f"Trading 212 returned HTTP {code} for {path}"


# ---- id extractors for incremental history -----------------------------------------
def order_id(item):
    return ((item or {}).get("order") or {}).get("id")


def ref_id(item):
    return (item or {}).get("reference")


HISTORY = (
    ("orders", "/equity/history/orders", order_id),
    ("dividends", "/equity/history/dividends", ref_id),
    ("transactions", "/equity/history/transactions", ref_id),
)


def clean_summary(summary):
    """Drop the account number — the page never needs it."""
    summary = dict(summary or {})
    summary.pop("id", None)
    return summary


def history_since(client, path, stored, key):
    """What Trading 212 holds of one history that `stored` does not: its pages walked newest first, in turn,
    until one is wholly known (history never changes once written)."""
    known = {key(i) for i in stored if key(i) is not None}
    fresh = []
    for items in client.pages(path, known, key):
        fresh.extend(i for i in items if key(i) not in known)
    return fresh


def sync(client, existing=None, log=print):
    existing = existing or {}
    # The account's summary, its positions and the first page of each history do not depend on one another, and
    # each over the VPN is a new connection (5 Oct 2026, the owner: "refresh the desk faster"): they are asked
    # together, each history's pages still in turn, and answered in this order, so the first thing to fail is the
    # first of them to fail as it was when they went one after another. The rate limits are per call, in the
    # headers of each answer, which every call waits out for itself (Client._pace).
    with ThreadPoolExecutor(max_workers=2 + len(HISTORY)) as pool:
        asked = [pool.submit(client.get, "/equity/account/summary"), pool.submit(client.get, "/equity/positions")]
        asked += [pool.submit(history_since, client, path, existing.get(name) or [], key) for name, path, key in HISTORY]
        answers = []
        for future in asked:
            try:
                answers.append(future.result())
            except BaseException:
                for other in asked:
                    other.cancel()                  # what has not started need not
                raise
    summary, positions = answers[0], answers[1]
    # an account always has a currency, and a portfolio is a list, if an empty one: an answer
    # that is neither is not the account, and must not stand in for it (an empty answer
    # through a flaky network would have shown an empty portfolio until the next sync)
    if not isinstance(summary, dict) or not summary.get("currency") or not isinstance(positions, list):
        raise T212Error("Trading 212 answered without the account in it; nothing was changed. Try again")
    out = {
        "env": client.env,
        "summary": clean_summary(summary),
        "positions": positions,
    }
    for (name, path, key), fresh in zip(HISTORY, answers[2:]):
        stored = existing.get(name) or []
        seen, merged = set(), []
        for item in fresh + stored:             # newest first, deduplicated
            k = key(item)
            if k is not None and k in seen:
                continue
            seen.add(k)
            merged.append(item)
        out[name] = merged
        log(f"  {name}: {len(fresh)} new, {len(merged)} total")
    # the sync before this one: what the page counts "since you last looked" from
    out["previous_synced_at"] = existing.get("synced_at")
    out["synced_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def sync_to_file(path=None):
    """Sync the account into t212_data.json. Raises T212Error. Run in its own process on
    the Mac (main, below); called directly on an iPhone, which cannot start one."""
    path = path or DATA_FILE
    key, secret, env = credentials()
    client = Client(key, secret, env)
    try:
        with open(path) as f:
            existing = json.load(f)
    except (OSError, ValueError):
        existing = {}                       # none yet, or damaged: Trading 212 has it all again
    if not isinstance(existing, dict):
        existing = {}
    if existing.get("env") not in (None, env):
        existing = {}                       # switched live↔demo: start clean
    print(f"Syncing Trading 212 ({env})…")
    data = sync(client, existing)
    atomic_write_json(path, data)
    os.chmod(path, 0o600)
    print(f"Saved {len(data['positions'])} positions")
    return data


def main(argv):
    try:
        if "--check" in argv:
            key, secret, env = credentials()
            s = Client(key, secret, env).get("/equity/account/summary") or {}
            print(f"OK: connected to Trading 212 ({env}), account currency {s.get('currency', '?')}")
            return 0
        sync_to_file()
        return 0
    except T212Error as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
