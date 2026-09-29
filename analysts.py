"""What professional analysts say about each watchlist company → analysts_data.json.

These are other people's published ratings (Finnhub's recommendation trends), not
this desk's opinion and not advice. They are shown with two facts that matter when
reading them:

- Analysts rarely say sell. Ratings skew heavily to buy, so "most say buy" is the
  normal state, not a distinction (Barber, Lehavy, McNichols & Trueman, 2001,
  "Can Investors Profit from the Prophets?").
- Following the consensus did not beat the market once trading costs were counted
  in that study. The value here is seeing how opinion is *changing*, and against
  what the company actually reports.
"""
import os, sys
from datetime import datetime, timezone
from earnings import EarningsError, api_key, fetch
from env_config import atomic_write_json, fetched_today
from news import FOLLOW_USAGE, load_watchlist

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSTS_FILE = os.path.join(HERE, "analysts_data.json")
MONTHS_KEPT = 12
DIRECTION_MONTHS = 3        # the direction compares with this many months earlier
SCORE_PLACES = 2            # the average rating is shown to this many places
WEIGHTS = {"strongBuy": 2, "buy": 1, "hold": 0, "sell": -1, "strongSell": -2}
LABELS = (("Strong buy", 1.5), ("Buy", 0.5), ("Hold", -0.5), ("Sell", -1.5))


def score(row):
    """Average rating on a −2…+2 scale (strong sell … strong buy)."""
    total = sum(int(row.get(k) or 0) for k in WEIGHTS)
    if not total:
        return None, 0
    return sum(WEIGHTS[k] * int(row.get(k) or 0) for k in WEIGHTS) / total, total


def label_for(value):
    if value is None:
        return "No rating"
    for name, floor in LABELS:
        if value >= floor:
            return name
    return "Strong sell"


def for_company(ticker, key, fetch=fetch):
    rows = fetch(f"stock/recommendation?symbol={ticker}", key) or []
    rows = sorted([r for r in rows if r.get("period")], key=lambda r: r["period"], reverse=True)[:MONTHS_KEPT]
    if not rows:
        return None
    now, count = score(rows[0])
    # Exactly DIRECTION_MONTHS back or not at all: with less history this compared
    # with a more recent month while the page still said "than 3 months ago".
    older = rows[DIRECTION_MONTHS] if len(rows) > DIRECTION_MONTHS else None
    before, _ = score(older) if older else (None, 0)
    counts = {k: int(rows[0].get(k) or 0) for k in WEIGHTS}
    return {
        "ticker": ticker.upper(),
        "as_of": rows[0]["period"][:10],
        "counts": counts,
        "analysts": count,
        "score": now,
        "verdict": label_for(now),
        "score_before": before,
        "direction_months": DIRECTION_MONTHS,
        # No cut-off of our own: the two averages are shown, and "unchanged" means
        # equal at the two places the page prints (S-03 — this was ±0.05, invented).
        "direction": (None if (now is None or before is None) else
                      "unchanged" if round(now, SCORE_PLACES) == round(before, SCORE_PLACES) else
                      "more positive" if now > before else "more negative"),
        "score_places": SCORE_PLACES,
        "sell_share": (counts["sell"] + counts["strongSell"]) / count if count else None,
        "history": [{"month": r["period"][:7], "score": score(r)[0], "analysts": score(r)[1]} for r in rows][::-1],
    }


def update(tickers, key=None, fetch=fetch, stored=None, today=None):
    """With `stored`, a company already fetched today is kept: the ratings are monthly
    counts, and each request waits out Finnhub's free rate limit."""
    key = key or api_key()
    today = today or datetime.now(timezone.utc).date()
    kept = ((stored or {}).get("companies") or {}) if fetched_today((stored or {}).get("updated_at"), today) else {}
    companies = {}
    for t in tickers:
        t = t.upper()
        data = kept.get(t) or for_company(t, key, fetch=fetch)
        if data:
            companies[t] = data
    return {"companies": companies,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def main(argv):
    try:
        tickers = [a.upper() for a in argv if not a.startswith("-")] or load_watchlist()
        if not tickers:
            print("No company followed yet: " + FOLLOW_USAGE, file=sys.stderr)
            return 2
        data = update(tickers)
        atomic_write_json(ANALYSTS_FILE, data)
        for t, c in data["companies"].items():
            since = ("" if not c.get("direction") else
                     f", unchanged from {c['direction_months']} months ago"
                     if c["direction"] == "unchanged" else
                     f", {c['direction']} than {c['direction_months']} months ago")
            print(f"{t}: {c['verdict']} ({c['analysts']} analysts{since})")
        return 0
    except EarningsError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
