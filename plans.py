"""A plan before each trade: the reason written down before the order, matched to the
trade when the account syncs, and scored against the market on the day the user chose.

Why before: a reason written after a trade is rewritten by what happened next (hindsight
bias: Fischhoff 1975, "Hindsight is not equal to foresight", Journal of Experimental
Psychology: Human Perception and Performance 1). Written first, it can be held to. And
naming what would prove the plan wrong before acting is the pre-mortem (Klein 2007,
"Performing a project premortem", Harvard Business Review 85): it makes the doubts that
are already there say themselves.

A plan names the company, buy or sell, why, what would prove it wrong, and the day to
look at it again. It is written once: there is no edit and no delete, as with a thesis
and the order book. The desk never sends anything because of a plan.

Matched: the first trade in that company, on that side, filled after the plan was written
and within MATCH_DAYS of it; each trade answers one plan. A plan with no such trade is
"not acted on": kept, and not scored.

Scored: from the first close on or after the trade to the first close on or after the
review day, the shares' return against the S&P 500's over the same closes (adjusted
closes, dividends in). Before the review day, the same measured to the latest close, and
said to be "so far". A purchase did better than the market when the shares beat it; a
sale did better when the shares then fell behind it. Over the reviewed plans: how many
did better, with uncertainty.py's interval, and the median difference with its own.
"""
import json, os, re, uuid
from datetime import date, datetime, timedelta, timezone

import prices as price_store
import uncertainty
from env_config import atomic_write_json, read_for_writing, UnreadableStore

HERE = os.path.dirname(os.path.abspath(__file__))
PLANS_FILE = "plans.json"
SIDES = ("BUY", "SELL")
# The desk's choices. A plan is for a trade about to be made: one filled more than a week
# later answers a different moment. A review more than three years off is not a plan for
# a holding of days to months. The lengths are what a plan needs, and no essay.
MATCH_DAYS = 7
LONGEST_REVIEW_DAYS = 3 * 365
MAX_WHY, MAX_WRONG = 500, 300
TICKER = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


class PlanError(Exception):
    pass


def load(folder):
    try:
        with open(os.path.join(folder, PLANS_FILE)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("plans"), list) else {"plans": []}
    except (OSError, ValueError):
        return {"plans": []}


def write(folder, claim, now=None):
    """Check one plan and add it, once. Returns the plan written."""
    now = now or datetime.now(timezone.utc)
    ticker = str(claim.get("ticker") or "").strip().upper()
    side = str(claim.get("side") or "").strip().upper()
    why = " ".join(str(claim.get("why") or "").split())
    wrong = " ".join(str(claim.get("wrong_if") or "").split())
    if not TICKER.match(ticker):
        raise PlanError("Name the company by its ticker, as in AAPL.")
    if side not in SIDES:
        raise PlanError("Say whether it is a buy or a sell.")
    if len(why) < 3:
        raise PlanError("Say why, in a line: that is the plan.")
    if len(wrong) < 3:
        raise PlanError("Say what would prove it wrong: it is the part a plan is most often missing.")
    if len(why) > MAX_WHY or len(wrong) > MAX_WRONG:
        raise PlanError(f"Keep it short: the reason in {MAX_WHY} characters, what would prove it wrong in {MAX_WRONG}.")
    try:
        review = date.fromisoformat(str(claim.get("review_by") or ""))
    except ValueError:
        raise PlanError("Choose the day to look at it again.") from None
    today = now.date()
    if review <= today:
        raise PlanError("The day to look at it again has to be after today.")
    if review > today + timedelta(days=LONGEST_REVIEW_DAYS):
        raise PlanError(f"Choose a day within {LONGEST_REVIEW_DAYS // 365} years.")
    try:
        stored = read_for_writing(os.path.join(folder, PLANS_FILE), dict, {"plans": []})
    except UnreadableStore as e:
        raise PlanError(str(e)) from None
    if not isinstance(stored.get("plans"), list):
        raise PlanError(f"{PLANS_FILE} cannot be read, so nothing was written over it.")
    plan = {"id": uuid.uuid4().hex[:12], "written": now.isoformat(timespec="seconds"), "ticker": ticker,
            "side": side, "why": why, "wrong_if": wrong, "review_by": review.isoformat()}
    stored["plans"].append(plan)
    path = os.path.join(folder, PLANS_FILE)
    atomic_write_json(path, stored, indent=1)
    os.chmod(path, 0o600)
    return plan


def _moment(text):
    """A trade's or a plan's time as written (Trading 212's milliseconds and Z included)."""
    return price_store.moment(text)


def match(plans, trades):
    """{plan id: the trade row that carried it out}. Plans are taken oldest first, and
    each trade answers one plan."""
    used, out = set(), {}
    by_time = sorted((t for t in trades or [] if _moment(t.get("time"))), key=lambda t: t["time"])
    for plan in sorted(plans or [], key=lambda p: p.get("written") or ""):
        written = _moment(plan.get("written"))
        if not written:
            continue
        last = written + timedelta(days=MATCH_DAYS)
        for trade in by_time:
            when = _moment(trade["time"])
            if (trade.get("id") not in used and trade.get("ticker") == plan.get("ticker")
                    and trade.get("side") == plan.get("side") and written <= when <= last):
                used.add(trade.get("id"))
                out[plan["id"]] = trade
                break
    return out


def _close_on_or_after(days, day):
    for d in days:
        if d >= day:
            return d
    return None


def result(plan, trade, prices, today):
    """The shares against the market from the trade to the review day (final), or to the
    latest close before then (so far); None when there are not two closes yet."""
    shares = price_store.series(prices, plan["ticker"])
    market = price_store.series(prices, price_store.BENCHMARK)
    if not shares or not market:
        return None
    days = sorted(d for d in shares if d in market)
    start = _close_on_or_after(days, trade["date"])
    end = _close_on_or_after(days, plan["review_by"]) if today.isoformat() >= plan["review_by"] else None
    final = end is not None
    end = end or (days[-1] if days else None)
    if not start or not end or end <= start or not shares[start] or not market[start]:
        return None
    s, m = shares[end] / shares[start] - 1, market[end] / market[start] - 1
    edge = (s - m) if plan["side"] == "BUY" else (m - s)
    return {"from": start, "to": end, "final": final, "shares": s, "market": m, "edge": edge}


def summary(stored, trades, prices, today):
    """Every plan, newest first, with its state and result; and the record over those
    reviewed."""
    plans = list((stored or {}).get("plans") or [])
    done = match(plans, trades)
    rows = []
    for plan in sorted(plans, key=lambda p: p.get("written") or "", reverse=True):
        trade = done.get(plan.get("id"))
        row = {k: plan.get(k) for k in ("id", "written", "ticker", "side", "why", "wrong_if", "review_by")}
        written = _moment(plan.get("written"))
        if trade:
            row["trade"] = {k: trade.get(k) for k in ("id", "date", "price", "price_currency", "quantity")}
            row["result"] = result(plan, trade, prices, today)
            row["state"] = "reviewed" if (row["result"] or {}).get("final") else "acted"
        elif written and today > (written + timedelta(days=MATCH_DAYS)).date():
            row["state"] = "not acted on"
        else:
            row["state"] = "waiting"
            row["match_until"] = (written + timedelta(days=MATCH_DAYS)).date().isoformat() if written else None
        rows.append(row)
    reviewed = [r["result"]["edge"] for r in rows if r["state"] == "reviewed"]
    return {"rows": rows, "count": len(rows), "reviewed": len(reviewed),
            "waiting": sum(1 for r in rows if r["state"] == "waiting"),
            "better": uncertainty.against_chance(sum(1 for e in reviewed if e > 0), len(reviewed)),
            "median_edge": uncertainty.median(reviewed, expected=0),
            "match_days": MATCH_DAYS, "longest_review_days": LONGEST_REVIEW_DAYS,
            "max_why": MAX_WHY, "max_wrong": MAX_WRONG}


def by_trade(summary_):
    """{trade id: its plan's row}, for the trade list to show the reason given first."""
    return {r["trade"]["id"]: r for r in (summary_ or {}).get("rows") or [] if r.get("trade")}
