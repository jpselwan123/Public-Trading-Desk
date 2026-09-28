"""Earnings dates and surprises for the watchlist (Finnhub) → earnings_data.json.

Two things the filings alone can't give: what analysts expected, and when the
next report is due. A "surprise" is the reported EPS minus what was expected; the
record of beats and misses is forecasts.py's.

Free key (no card) from finnhub.io → .env as FINNHUB_API_KEY.

Usage: python3 earnings.py [TICKER ...]
"""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from env_config import load_env, atomic_write_json, fetched_today, unpacked
from news import FOLLOW_USAGE, load_watchlist

HERE = os.path.dirname(os.path.abspath(__file__))
EARNINGS_FILE = os.path.join(HERE, "earnings_data.json")
BASE = "https://finnhub.io/api/v1/"
CALENDAR_DAYS = 120          # how far ahead to look for the next report
TIMEOUT = 25
REQUEST_GAP = 1.1            # free tier allows 60 calls a minute


class EarningsError(Exception):
    pass


def api_key():
    load_env(os.path.join(HERE, ".env"))
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        raise EarningsError("Add FINNHUB_API_KEY=… to .env (free key from finnhub.io)")
    return key


def fetch(path, key, opener=None, sleep=time.sleep):
    url = f"{BASE}{path}&token={key}"
    try:
        with (opener or urllib.request.urlopen)(urllib.request.Request(
                url, method="GET", headers={"Accept-Encoding": "gzip"}), timeout=TIMEOUT) as r:
            data = json.loads(unpacked(r.read(), r) or b"{}")
            sleep(REQUEST_GAP)
            return data
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise EarningsError("Finnhub rejected the key: check FINNHUB_API_KEY in .env") from None
        if e.code == 429:
            raise EarningsError("Finnhub's free rate limit is used up; try again in a minute") from None
        if e.code == 404:
            return {}
        raise EarningsError(f"Finnhub returned HTTP {e.code}") from None
    except Exception as e:
        raise EarningsError(f"Can't reach Finnhub ({e})") from None


def history_for(ticker, key, fetch=fetch):
    rows = fetch(f"stock/earnings?symbol={ticker}", key) or []
    out = []
    for r in rows if isinstance(rows, list) else []:
        actual, estimate, day = r.get("actual"), r.get("estimate"), r.get("period")
        if actual is None or estimate is None or not day:
            continue
        out.append({
            "date": str(day)[:10],                 # period end, not the announcement day
            "actual": float(actual),
            "estimate": float(estimate),
            "surprise": float(actual) - float(estimate),
            "surprise_pct": (float(r["surprisePercent"]) / 100.0
                             if r.get("surprisePercent") is not None else None),
            "beat": float(actual) > float(estimate),
        })
    return sorted(out, key=lambda r: r["date"], reverse=True)


def next_for(ticker, key, today=None, fetch=fetch):
    today = today or datetime.now(timezone.utc).date()
    to = (today + timedelta(days=CALENDAR_DAYS)).isoformat()
    data = fetch(f"calendar/earnings?from={today.isoformat()}&to={to}&symbol={ticker}", key) or {}
    rows = sorted((data.get("earningsCalendar") or []), key=lambda r: r.get("date") or "")
    for r in rows:
        if r.get("date"):
            return {"date": r["date"][:10],
                    "when": {"bmo": "before the open", "amc": "after the close"}.get(r.get("hour"), ""),
                    "eps_estimate": r.get("epsEstimate"),
                    "revenue_estimate": r.get("revenueEstimate")}
    return None


def load_stored():
    try:
        with open(EARNINGS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def merge_history(stored, fetched):
    """Keep every quarter ever seen, newest first.

    Finnhub returns only the last four quarters, so replacing the stored history
    caps it at four however long this desk runs — and forecasts.py scores the
    consensus estimate against the outcome, which is worth more the further back it
    reaches. A quarter already stored is replaced by the fetched one: a restatement
    changes the reported figure, and the newer answer is the right one."""
    by_date = {}
    for quarter in list(stored or []) + list(fetched or []):
        when = quarter.get("date")
        if when:
            by_date[when] = quarter
    return sorted(by_date.values(), key=lambda q: q["date"], reverse=True)


def update(tickers, key=None, today=None, fetch=fetch, stored=None):
    """A company fetched earlier today is kept, unless its results are due today or out:
    two requests a company, each waiting out Finnhub's free rate limit, for a date and a
    history that change a few times a year."""
    key = key or api_key()
    today = today or datetime.now(timezone.utc).date()
    kept = (stored or {}).get("companies") or {}
    today_already = fetched_today((stored or {}).get("updated_at"), today)
    companies = {}
    for t in tickers:
        t = t.upper()
        held = kept.get(t)
        due = ((held or {}).get("next") or {}).get("date")
        if today_already and held and not (due and due <= today.isoformat()):
            companies[t] = held
            continue
        companies[t] = {"ticker": t,
                        "history": merge_history((kept.get(t) or {}).get("history"),
                                                 history_for(t, key, fetch=fetch)),
                        "next": next_for(t, key, today=today, fetch=fetch)}
    return {"companies": companies,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def main(argv):
    try:
        tickers = [a.upper() for a in argv if not a.startswith("-")] or load_watchlist()
        if not tickers:
            print("No company followed yet: " + FOLLOW_USAGE, file=sys.stderr)
            return 2
        data = update(tickers, stored=load_stored())
        atomic_write_json(EARNINGS_FILE, data)
        for t, c in data["companies"].items():
            nxt = c["next"]
            print(f"{t}: {len(c['history'])} past reports"
                  + (f", next {nxt['date']} {nxt['when']}" if nxt else ", no date announced"))
        return 0
    except EarningsError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
