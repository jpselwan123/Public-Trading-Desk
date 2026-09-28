"""Company financials straight from SEC filings → fundamentals.json.

The SEC publishes every figure companies report in their 10-K/10-Q as data
(XBRL), so revenue, profit, margins, cash and debt come from the filing itself —
no estimates, no third party, no key.

One request per metric per company (small JSON each), cached between runs.

Usage: python3 fundamentals.py            update the watchlist
       python3 fundamentals.py NVDA
"""
import os, sys
from datetime import datetime, timezone
from env_config import atomic_write_json
from news import FOLLOW_USAGE, NewsError, cik_map, fetch_json, load_watchlist, user_agent

HERE = os.path.dirname(os.path.abspath(__file__))
FUNDAMENTALS_FILE = os.path.join(HERE, "fundamentals.json")
CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
# Every concept for one company in one file. Several megabytes, so it is read only
# when the per-concept endpoint comes back empty for a figure — which it does for
# Coca-Cola's Revenues, while this file holds them through the latest quarter.
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Each line: the plain name, then the XBRL tags to try in order (companies use
# different tags for the same thing).
METRICS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    # The second tag is the one most companies moved to after ASU 2016-18 — Starbucks,
    # AIT and JPMorgan file only it now. It includes restricted cash, a broader figure,
    # so the tag used travels with the value and the card says which (S-07).
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "equity": ["StockholdersEquity"],
    "assets": ["Assets"],
}
FLOWS = {"revenue", "gross_profit", "operating_income", "net_income", "eps"}   # summed over 4 quarters
POINTS = ("cash", "debt", "equity")   # balances dated by the balance sheet (assets) they sit on
QUARTER_DAYS = (80, 100)      # a "quarter" period length, to skip half-year and yearly rows


MONEY_UNITS = ("USD",)
PER_SHARE_UNITS = ("USD/shares",)
# The filings that bring new figures into the SEC's data: the quarterly and annual
# reports, and their amendments, which can restate them.
FIGURE_FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")


def _facts(cik, tag, ua, fetch=fetch_json, units=MONEY_UNITS):
    return _rows(fetch(CONCEPT_URL.format(cik=cik, tag=tag), ua), units)


def _rows(data, units=MONEY_UNITS):
    """One concept's facts, oldest first, from either SEC endpoint's shape."""
    if not data:
        return []
    out = []
    for unit, rows in (data.get("units") or {}).items():
        if units and unit not in units:
            continue
        for r in rows:
            if r.get("val") is None or not r.get("end"):
                continue
            out.append({"start": r.get("start"), "end": r["end"], "val": float(r["val"]),
                        "form": r.get("form"), "filed": r.get("filed")})
    # a period's latest filing last, so it is the one kept (_quarters, _annuals): a later
    # report restates a comparative for a split or a correction; left to the SEC's order
    # until 28 Sep 2026
    return sorted(out, key=lambda r: (r["end"], r.get("start") or "", r.get("filed") or ""))


def _days(row):
    if not row.get("start"):
        return None
    try:
        a = datetime.fromisoformat(row["start"]).date()
        b = datetime.fromisoformat(row["end"]).date()
        return (b - a).days
    except ValueError:
        return None


def _quarters(rows):
    """Quarterly rows only, newest first, one per period end."""
    seen, out = set(), []
    for r in reversed(rows):
        d = _days(r)
        if d is None or not (QUARTER_DAYS[0] <= d <= QUARTER_DAYS[1]):
            continue
        if r["end"] in seen:
            continue
        seen.add(r["end"])
        out.append(r)
    return out


def _latest_point(rows):
    """Newest balance-sheet value (a single date, not a period)."""
    points = [r for r in rows if not r.get("start")] or rows
    return points[-1] if points else None


def _day(text):
    return datetime.fromisoformat(text).date()


def _consecutive(quarters):
    """True when each quarter, newest first, ends one quarter after the next.
    Many companies never tag a three-month fourth quarter — it is only in the 10-K's
    annual figure — so the four newest quarterly rows can straddle a missing one,
    and summing them is not a year."""
    for newer, older in zip(quarters, quarters[1:]):
        gap = (_day(newer["end"]) - _day(older["end"])).days
        if not QUARTER_DAYS[0] <= gap <= QUARTER_DAYS[1]:
            return False
    return True


YEAR_DAYS = (330, 400)        # one annual period end to the next


def _annuals(rows):
    """Full-year 10-K figures, newest first, one per period end. A 10-K repeats the
    two prior years as comparatives, so the same year appears several times."""
    seen, out = set(), []
    for r in reversed(rows):
        if (r.get("form") or "").startswith("10-K") and (_days(r) or 0) > 300 and r["end"] not in seen:
            seen.add(r["end"])
            out.append(r)
    return out


def _with_fourth_quarters(rows, quarters):
    """Quarters, newest first, with each missing fourth quarter worked out as the
    annual figure less the three quarters inside it. Most companies never tag a
    three-month Q4 — it exists only inside the 10-K's year — and without it AMD,
    Starbucks and BeOne had no run of four consecutive quarters at all."""
    ends = {q["end"] for q in quarters}
    derived = []
    for year in _annuals(rows):
        if year["end"] in ends or not year.get("start"):
            continue
        inside = [q for q in quarters if year["start"] <= q["start"] and q["end"] < year["end"]]
        if len(inside) == 3 and _consecutive(sorted(inside, key=lambda q: q["end"], reverse=True)):
            last = max(q["end"] for q in inside)
            derived.append({"start": last, "end": year["end"], "form": "derived",
                            "val": year["val"] - sum(q["val"] for q in inside)})
    return sorted(quarters + derived, key=lambda q: q["end"], reverse=True)


def first_filed(rows, period):
    """The day a period's figure first became public: the earliest filing that carries
    it. A figure reappears as a comparative in later filings, which must not count. A
    fourth quarter worked out from the year is public when the 10-K is."""
    if period.get("form") == "derived":
        dates = [r["filed"] for r in rows if r["end"] == period["end"] and (_days(r) or 0) > 300
                 and (r.get("form") or "").startswith("10-K") and r.get("filed")]
    else:
        dates = [r["filed"] for r in rows if r["end"] == period["end"]
                 and r.get("start") == period.get("start") and r.get("filed")]
    return min(dates) if dates else None


def _over(rows, end, basis):
    """A flow's value over one given period — the year a 10-K ends on `end`, or the
    four consecutive quarters ending there — or None if the filings hold no such
    figure."""
    if not end:
        return None
    if basis == "annual":
        match = [r for r in _annuals(rows) if r["end"] == end]
        return match[0]["val"] if match else None
    run = [q for q in _with_fourth_quarters(rows, _quarters(rows)) if q["end"] <= end][:4]
    if len(run) == 4 and run[0]["end"] == end and _consecutive(run):
        return sum(q["val"] for q in run)
    return None


def _trailing(rows):
    """The latest twelve months and the twelve before them, with the end date.

    Four consecutive quarters when the company tags them and they are at least as
    recent as its latest annual report; otherwise that annual report. Without the
    recency test, JPMorgan — which stopped tagging three-month quarters in 2014 —
    showed 2014 revenue as its latest year."""
    annual = _annuals(rows)
    qs = _with_fourth_quarters(rows, _quarters(rows))
    latest_annual = annual[0]["end"] if annual else ""
    if len(qs) >= 4 and _consecutive(qs[:4]) and qs[0]["end"] >= latest_annual:
        before = (sum(q["val"] for q in qs[4:8])
                  if len(qs) >= 8 and _consecutive(qs[:8]) else None)
        return sum(q["val"] for q in qs[:4]), before, qs[0]["end"], "quarters"
    if not annual:
        return None, None, None, None
    now = annual[0]
    before = None
    if len(annual) >= 2:
        gap = (_day(now["end"]) - _day(annual[1]["end"])).days
        if YEAR_DAYS[0] <= gap <= YEAR_DAYS[1]:
            before = annual[1]["val"]
    return now["val"], before, now["end"], "annual"


def _newest(tags, rows_for):
    """(tag, rows) for the tag reported most recently — companies switch tags over the
    years — or None. On a tie the earlier tag in the list wins, so the narrower
    standard figure is preferred when both are current."""
    best = None
    for tag in tags:
        rows = rows_for(tag)
        if rows and (best is None or rows[-1]["end"] > best[1][-1]["end"]):
            best = (tag, rows)
    return best


def for_company(ticker, cik, ua, fetch=fetch_json):
    raw, tags_used = {}, {}
    for name, tags in METRICS.items():
        units = PER_SHARE_UNITS if name == "eps" else MONEY_UNITS
        found = _newest(tags, lambda tag: _facts(cik, tag, ua, fetch=fetch, units=units))
        if found:
            tags_used[name], raw[name] = found
    missing = [name for name in METRICS if name not in raw]
    if missing:
        every = ((fetch(FACTS_URL.format(cik=cik), ua) or {}).get("facts") or {}).get("us-gaap") or {}
        for name in missing:
            units = PER_SHARE_UNITS if name == "eps" else MONEY_UNITS
            found = _newest(METRICS[name], lambda tag: _rows(every.get(tag), units))
            if found:
                tags_used[name], raw[name] = found
    return card(ticker, cik, raw, tags_used)


def card(ticker, cik, facts, tags):
    """The figures derived from the facts, with the facts kept beside them — each with
    the day it was filed, so the card can be recomputed as the filings stood on any past
    date (Phase 11, asof.company): by filing date, never period end."""
    out = derive(ticker, cik, facts, tags)
    out["facts"], out["tags"] = facts, tags
    return out


def holds_latest_report(facts, ticker, filings):
    """True when the stored facts already include the company's latest quarterly or
    annual report, as the filings store lists them: the newest fact was filed on or
    after it. With no report listed there is no telling, so False. The SEC's figures
    can lag a filing (Coca-Cola's June 10-Q, S-21); such a company stays False, and is
    downloaded again each refresh until they arrive."""
    reports = [i["date"] for i in filings or [] if i.get("ticker") == ticker and i.get("date")
               and (i.get("form") or "").upper() in FIGURE_FORMS]
    newest = max((r.get("filed") or "" for rows in (facts or {}).values() for r in rows or []), default="")
    return bool(reports) and newest >= max(reports)


PER_SHARE = ("eps",)          # figures filed per share, in the shares of the day they were filed


def in_shares_of(raw, splits, through):
    """The facts with each per-share figure restated in `through`'s shares: divided by the
    splits after the day it was filed (prices.factor_between, from the split days stored with
    the closes). A quarter filed before a split is in the old shares and one filed after in
    the new; summed as filed, NVIDIA's twelve months to October 2024, across its ten-for-one
    split, read $15 a share, not $2.5 (until 28 Sep 2026). A comparative filed after the split
    is already restated, and is left as it is."""
    if not splits:
        return raw
    import prices as price_store
    out = dict(raw)
    for name in PER_SHARE:
        rows = raw.get(name)
        if rows:
            out[name] = [dict(r, val=r["val"] / price_store.factor_between(splits, r["filed"], through))
                         if r.get("filed") else r for r in rows]
    return out


def derive(ticker, cik, raw, tags_used, splits=None, through="9999-12-31"):
    """Every figure the card shows, from the facts held. With `splits` ([(day, factor)], the
    company's, prices.splits), each per-share figure is first restated in `through`'s shares."""
    raw = in_shares_of(raw, splits, through)
    out = {"ticker": str(ticker or "").upper(), "cik": cik, "quarters": []}
    for name in METRICS:
        rows = raw.get(name)
        if not rows:
            continue
        if name in FLOWS:
            now, before, end, basis = _trailing(rows)
            out[name] = now
            out[name + "_prev"] = before
            out[name + "_asof"] = end
            out[name + "_basis"] = basis          # four quarters, or the last annual report
            if now is not None and before:
                out[name + "_growth"] = now / before - 1 if before > 0 else None
        else:
            point = _latest_point(rows)
            if point:
                out[name] = point["val"]
                out[name + "_asof"] = point["end"]
                out[name + "_tag"] = tags_used[name]
    out["cash_includes_restricted"] = out.get("cash_tag") == METRICS["cash"][1]
    # A balance is only the company's current position if it carries the date of its
    # latest balance sheet, which total assets give. The newest fact under a tag the
    # company stopped using is not that: Starbucks' cash was from July 2022 and
    # JPMorgan's from 2018, both shown as current (S-05). A stale balance is dropped,
    # and the date it was last filed is kept so the page can say why it is blank.
    sheet = out.get("assets_asof")
    for name in POINTS:
        if sheet and out.get(name + "_asof") and out[name + "_asof"] != sheet:
            out[name + "_stale"] = out.pop(name + "_asof")
            out.pop(name, None)
    # Each quarter's revenue and operating income, and the day each quarter's figures
    # first became public — what a thesis is scored against, the quarter it named and
    # the same quarter a year before (Phase 9).
    revenue_rows = raw.get("revenue") or []
    operating_rows = raw.get("operating_income") or []
    operating = {q["end"]: q["val"] for q in _with_fourth_quarters(operating_rows, _quarters(operating_rows))}
    for q in reversed(_with_fourth_quarters(revenue_rows, _quarters(revenue_rows))[:12]):
        out["quarters"].append({"end": q["end"], "revenue": q["val"],
                                "operating_income": operating.get(q["end"]),
                                "filed": first_filed(revenue_rows, q)})
    rev = out.get("revenue")
    if rev:
        # A margin needs its profit over revenue's own period. When a profit's latest
        # period differs — JPMorgan's revenue is its 2025 annual figure, its profit runs
        # to June 2026 — the profit for revenue's period is taken from the same filings
        # (S-09); only if they do not hold one is the margin left blank.
        for margin, part in (("gross_margin", "gross_profit"), ("operating_margin", "operating_income"),
                             ("net_margin", "net_income")):
            value = out.get(part)
            if value is not None and not same_period(out, part, "revenue"):
                value = _over(raw.get(part) or [], out.get("revenue_asof"), out.get("revenue_basis"))
            out[margin] = _possible(margin, value / rev if value is not None else None)
    out["revenue_growth"] = _possible("revenue_growth", out.get("revenue_growth"))
    # Only with both figures on the latest balance sheet. A debt figure that was not
    # filed (or was stale) used to count as zero, printing "Debt to equity 0.00" —
    # a confident claim of no borrowing made from an absence (S-06).
    if out.get("equity") and out["equity"] > 0 and out.get("debt") is not None:
        out["debt_to_equity"] = _possible("debt_to_equity", out["debt"] / out["equity"])
    out["why"], out["withheld"] = _why_blank(out)
    return out


def _why_blank(out):
    """Why each figure the card shows is blank, printed beside its dash (Q2), and which
    of those the desk withheld: a figure the filings hold but the desk declines to
    show (an old balance as if current, a ratio on negative equity), as against one
    the company never filed. The page colours only the first as withheld."""
    why, withheld = {}, set()

    def declined(name, reason):
        why[name] = reason
        withheld.add(name)

    for name in ("revenue", "eps"):
        if out.get(name) is None:
            why[name] = "not in its filings"
    for margin, part in (("gross_margin", "gross_profit"), ("operating_margin", "operating_income"),
                         ("net_margin", "net_income")):
        if out.get(margin) is not None:
            continue
        if not out.get("revenue"):
            why[margin] = "no revenue filed"
        elif out.get(part) is None:
            why[margin] = "not reported"
        elif not same_period(out, part, "revenue"):
            declined(margin, "no profit figure for revenue's period")
        else:
            declined(margin, "outside any possible range")
    if out.get("cash") is None:
        if out.get("cash_stale"):
            declined("cash", "not in its latest filing")
        else:
            why["cash"] = "not in its filings"
    if out.get("debt_to_equity") is None:
        equity, debt = out.get("equity"), out.get("debt")
        if equity is not None and equity <= 0:
            declined("debt_to_equity", "negative book equity")
        elif equity is None and out.get("equity_stale"):
            declined("debt_to_equity", "equity not in its latest filing")
        elif equity is None:
            why["debt_to_equity"] = "no equity filed"
        elif debt is None and out.get("debt_stale"):
            declined("debt_to_equity", "debt not in its latest filing")
        elif debt is None:
            why["debt_to_equity"] = "no debt figure filed"
        else:
            declined("debt_to_equity", "outside any possible range")
    return why, sorted(withheld)


def same_period(out, a, b):
    """Only compare two figures that cover the same reporting period."""
    return bool(out.get(a + "_asof")) and out.get(a + "_asof") == out.get(b + "_asof")


# The only limits a figure is held to are ones a correct filing cannot break: gross or
# operating profit above revenue, revenue falling by more than all of it, debt over
# positive equity below zero (S-10). The old bounds — margins under -200% or -500%,
# growth over 1,000%, debt over 50 times equity — were ours, and hid real companies: a
# young biotech's -800% operating margin, a company's first full year of sales.
POSSIBLE = {"gross_margin": (None, 1.0), "operating_margin": (None, 1.0),
            "net_margin": (None, None),              # a gain can exceed revenue
            "revenue_growth": (-1.0, None), "debt_to_equity": (0.0, None)}


def _possible(name, value):
    if value is None:
        return None
    low, high = POSSIBLE[name]
    return None if (low is not None and value < low) or (high is not None and value > high) else value


def update(tickers, ua=None, fetch=fetch_json, stored=None, filings=None):
    """Every covered company's figures. With `stored` (the last fundamentals.json) and
    `filings` (the filings store's items), a company whose stored facts already include
    its latest report is recomputed from them instead of downloaded again: fifteen
    requests a company, and often a file of several megabytes, for figures that change
    only when it files."""
    held = (stored or {}).get("companies") or {}
    companies, unknown, ciks = {}, [], None
    for t in tickers:
        t = t.upper()
        kept = held.get(t) or {}
        if kept.get("facts") and holds_latest_report(kept["facts"], t, filings):
            companies[t] = card(t, kept.get("cik"), kept["facts"], kept.get("tags") or {})
            continue
        if ciks is None:
            ua = ua or user_agent()
            ciks = cik_map(ua, fetch=fetch)
        cik = ciks.get(t)
        if not cik:
            unknown.append(t)
            continue
        companies[t] = for_company(t, cik, ua, fetch=fetch)
    return {"companies": companies, "unknown": unknown,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def main(argv):
    try:
        tickers = [a.upper() for a in argv if not a.startswith("-")] or load_watchlist()
        if not tickers:
            print("No company followed yet: " + FOLLOW_USAGE, file=sys.stderr)
            return 2
        data = update(tickers)
        atomic_write_json(FUNDAMENTALS_FILE, data)
        for t, c in data["companies"].items():
            rev = c.get("revenue")
            print(f"{t}: revenue {rev/1e9:.1f}B" if rev else f"{t}: no revenue figure",
                  f"· net margin {c.get('net_margin'):.1%}" if c.get("net_margin") else "")
        return 0
    except NewsError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
