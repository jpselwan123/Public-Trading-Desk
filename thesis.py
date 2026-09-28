"""The user's own judgement, written down before the outcome and scored after it
(fourth review, Phase 9). The discipline of PREREGISTRATION.md, applied to a person.

Before a covered company reports, the user writes a thesis about the quarter it is
about to report: whether revenue will be up or down on the same quarter a year before
and roughly by how much, whether the operating margin will be up or down on it, one
line of reasoning, and a confidence from 50% to 95% that both directions are right.

The rules (docs/THESES.md):

- A thesis names the first quarter after the latest one the desk holds, and is written
  only while that quarter's results are not yet due: on or after the announced date it
  is refused, since the outcome may already be public.
- One thesis per company per quarter, written once. There is no edit and no delete:
  like the order book, it is a record of what was thought before the outcome was known.
- It is scored when the quarter's figures arrive: right when both directions are right.
  The rough magnitude is reported beside the outcome and not scored — a direction is a
  claim that can be settled, a guessed size is not one a probability attaches to.
- A thesis whose quarter was already public when it was written (the desk's figures had
  not been refreshed) is void, never scored.

Scores: the Brier score over every resolved thesis (Brier 1950) — the mean squared gap
between the confidence stated and what happened, 0 at best; always saying 50% scores
0.25 — and calibration: for each band of stated confidence, how often the user was
right, with uncertainty.py's interval against the confidence actually stated. Ten
theses prove nothing, and the interval says so for every band until they do.

Stdlib only. Nothing here is advice: it scores the user's forecasts of a company's
own figures, not trades.
"""
import json
import os
import uuid
from datetime import date, datetime, timezone

import uncertainty
from env_config import atomic_write_json, read_for_writing, UnreadableStore

HERE = os.path.dirname(os.path.abspath(__file__))
THESES_FILE = os.path.join(HERE, "theses.json")
CONFIDENCE = (0.50, 0.95)              # the range the review set: no certainty, no coin flip below it
DIRECTIONS = ("up", "down")
BANDS = ((0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 0.95))   # tenths, the last closed
YEAR_AGO_DAYS = (350, 380)             # the same quarter a year before, whatever the calendar
MAX_REASON = 300
ALWAYS_HALF = 0.25                     # the Brier score of saying 50% every time


# How the figures this module owns are shown (joined into measure_display).
THESIS_DISPLAY = {
    "confidence": {"kind": "percent", "dp": 0, "label": "Confidence stated"},
    "brier":      {"kind": "ratio", "dp": 3, "label": "Brier score"},
}


class ThesisError(Exception):
    pass


def load(path=None):
    try:
        with open(path or THESES_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


REPORTS = ("10-Q", "10-K")


def reported_since(ticker, quarter, filings):
    """The company's quarterly and annual reports filed after the one that reported
    `quarter` (S-21). The SEC's figures can lag its filings — Coca-Cola's June quarter
    was filed on 29 July and not in the SEC's data on 25 September — and JPMorgan
    stopped tagging three-month quarters in 2014, so the latest quarter the desk holds
    can be one already followed by others. The quarter's own report is its filing date,
    or failing that the first report after its end."""
    reports = sorted(i["date"] for i in filings or [] if i.get("ticker") == ticker
                     and (i.get("form") or "").upper() in REPORTS and i.get("date"))
    own = quarter.get("filed") or next((d for d in reports if d > quarter["end"]), None)
    return [d for d in reports if own and d > own]


def open_for(ticker, fund, next_report, today, filings=None):
    """(the quarter a thesis would name, or None, and why not)."""
    quarters = (fund or {}).get("quarters") or []
    if not quarters:
        return None, "no quarterly figures stored for it yet: they come with the next company update"
    since = reported_since(ticker, quarters[-1], filings)
    if since:
        n = len(since)
        return None, (f"the SEC's quarterly figures for it are {n} report{'s' if n > 1 else ''} behind its "
                      f"filings, so the quarter a thesis would name is already public")
    if next_report and next_report <= today.isoformat():
        return None, "its results are due today or already out; a thesis is written before them"
    return quarters[-1]["end"], None


def write(ticker, claim, fund, next_report, today=None, path=None, filings=None):
    """Record one thesis, once. `claim`, as the user typed it: revenue_direction,
    revenue_change_pct (optional), margin_direction, reason, confidence_pct (50-95).
    Stored as fractions. `filings` is the filings store's items (S-21)."""
    today = today or datetime.now(timezone.utc).date()     # the desk's day, UTC like every stamp it writes
    ticker = str(ticker or "").strip().upper()
    after, why_not = open_for(ticker, fund, next_report, today, filings)
    if not after:
        raise ThesisError(f"No thesis can be written for {ticker} now: {why_not}.")
    revenue_direction, margin_direction = claim.get("revenue_direction"), claim.get("margin_direction")
    if revenue_direction not in DIRECTIONS or margin_direction not in DIRECTIONS:
        raise ThesisError("Say whether revenue and the operating margin will be up or down.")
    reason = " ".join(str(claim.get("reason") or "").split())
    if not reason:
        raise ThesisError("Write the one line of reasoning: a thesis without one is a guess.")
    try:
        confidence = float(claim.get("confidence_pct")) / 100
    except (TypeError, ValueError):
        raise ThesisError("Give a confidence between 50% and 95%.") from None
    if not CONFIDENCE[0] <= confidence <= CONFIDENCE[1]:
        raise ThesisError("Give a confidence between 50% and 95%.")
    change = claim.get("revenue_change_pct")
    try:
        change = None if change in (None, "") else float(change) / 100
    except (TypeError, ValueError):
        raise ThesisError("The rough size of the revenue change must be a number, or left out.") from None
    if change is not None and (change > 0) != (revenue_direction == "up") and change != 0:
        raise ThesisError("The rough size and the direction disagree.")
    try:
        theses = read_for_writing(path or THESES_FILE, list, [])
    except UnreadableStore as e:
        raise ThesisError(str(e)) from None
    if any(not isinstance(t, dict) for t in theses):
        raise ThesisError("theses.json cannot be read, so nothing was written over it.")
    if any(t.get("ticker") == ticker and t.get("after") == after for t in theses):
        raise ThesisError(f"A thesis for {ticker}'s next quarter is already written; "
                          "theses are written once.")
    entry = {"id": uuid.uuid4().hex[:12], "ticker": ticker, "written": today.isoformat(),
             "after": after, "due": next_report, "revenue_direction": revenue_direction,
             "revenue_change": change, "margin_direction": margin_direction,
             "reason": reason[:MAX_REASON], "confidence": round(confidence, 2)}
    atomic_write_json(path or THESES_FILE, theses + [entry], indent=1)
    return entry


def _gap_days(a, b):
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def outcome(entry, fund):
    """What happened to one thesis: None while its quarter has not arrived, else
    {"status": "right" | "wrong" | "void" | "unscorable", ...}."""
    quarters = (fund or {}).get("quarters") or []
    later = [q for q in quarters if q["end"] > entry["after"]]
    if not later:
        return None
    quarter = min(later, key=lambda q: q["end"])
    if quarter.get("filed") and quarter["filed"] < entry["written"]:
        return {"status": "void", "quarter": quarter["end"],
                "why": "the quarter was already public when the thesis was written"}
    ago = [q for q in quarters if YEAR_AGO_DAYS[0] <= _gap_days(quarter["end"], q["end"]) <= YEAR_AGO_DAYS[1]]
    if not ago:
        return {"status": "unscorable", "quarter": quarter["end"],
                "why": "the same quarter a year before is not stored"}
    before = ago[0]
    out = {"quarter": quarter["end"], "year_before": before["end"]}
    if not quarter.get("revenue") or not before.get("revenue"):
        return dict(out, status="unscorable", why="a quarter's revenue is not stored")
    out["revenue_change"] = quarter["revenue"] / before["revenue"] - 1
    if quarter.get("operating_income") is None or before.get("operating_income") is None:
        return dict(out, status="unscorable", why="a quarter's operating income is not stored")
    out["margin_change"] = (quarter["operating_income"] / quarter["revenue"]
                            - before["operating_income"] / before["revenue"])
    out["margin_change_bp"] = out["margin_change"] * 1e4
    revenue_right = (out["revenue_change"] > 0) == (entry["revenue_direction"] == "up")
    margin_right = (out["margin_change"] > 0) == (entry["margin_direction"] == "up")
    return dict(out, status="right" if revenue_right and margin_right else "wrong",
                revenue_right=revenue_right, margin_right=margin_right)


def brier(scored):
    """Mean squared gap between stated confidence and outcome (Brier 1950)."""
    return (sum((t["confidence"] - (t["outcome"]["status"] == "right")) ** 2 for t in scored) / len(scored)
            if scored else None)


def calibration(scored):
    """For each band of stated confidence: how often right, with its interval, against
    the mean confidence actually stated in that band."""
    bands = []
    for low, high in BANDS:
        inside = [t for t in scored if low <= t["confidence"] < high or (high == BANDS[-1][1] and t["confidence"] == high)]
        if not inside:
            continue
        said = sum(t["confidence"] for t in inside) / len(inside)
        right = sum(1 for t in inside if t["outcome"]["status"] == "right")
        bands.append({"from": low, "to": high, "said": said,
                      "right": uncertainty.against_chance(right, len(inside), expected=said)})
    return bands


def summary(theses, fundamentals, earnings, coverage, today, filings=None):
    """Everything the page shows: each covered company's open thesis or whether one
    can be written, and the scored record."""
    funds = (fundamentals or {}).get("companies") or {}
    dated = (earnings or {}).get("companies") or {}
    judged = []
    for entry in theses:
        judged.append(dict(entry, outcome=outcome(entry, funds.get(entry["ticker"]))))
    scored = [t for t in judged if t["outcome"] and t["outcome"]["status"] in ("right", "wrong")]
    companies = {}
    for ticker in coverage or []:
        fund = funds.get(ticker)
        next_report = ((dated.get(ticker) or {}).get("next") or {}).get("date")
        after, why_not = open_for(ticker, fund, next_report, today, filings)
        pending = next((t for t in judged if t["ticker"] == ticker and not t["outcome"]), None)
        companies[ticker] = {"pending": pending, "can_write": bool(after) and not any(
            t["ticker"] == ticker and t["after"] == after for t in judged),
            "why_not": why_not, "after": after, "due": next_report}
    return {"companies": companies,
            "resolved": sorted([t for t in judged if t["outcome"]], key=lambda t: t["outcome"]["quarter"], reverse=True),
            "scored": len(scored), "right": sum(1 for t in scored if t["outcome"]["status"] == "right"),
            "brier": brier(scored), "always_half": ALWAYS_HALF,
            "calibration": calibration(scored), "confidence_range": list(CONFIDENCE)}
