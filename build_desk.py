"""Turn t212_data.json (+ journal.json) into desk_data.json and a static index.html.

Every figure here is a plain fact from the account, or a standard, defined
calculation (money-weighted return, as GIPS defines it). No thresholds, no
scores, no recommendations.

Usage: python3 build_desk.py [dir]      (dir defaults to this folder; demo → demo/)
"""
import base64, json, math, os, sys
from datetime import date, datetime, timedelta, timezone
from env_config import atomic_write, atomic_write_json, moment
import prices as price_store
import bridge
import broker as broker_mod
import brief as brief_mod
import charts as charts_mod
import context
import diffs
import forecasts
import fundamentals as fundamentals_mod
import habits as habits_mod
import checks as checks_mod
import history as history_mod
import headlines as headlines_mod
import health as health_mod
import looks as looks_mod
import news as news_mod
import plans as plans_mod
import rating as rating_mod
import screen
import sectors
import thesis as thesis_mod
import uncertainty
import universe
import value

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "desk_template.html")
# The page's styles and script, kept by subject in page/ and put into the template's markup
# when it is built. The scripts are one script, split: they run in this order, so a file
# may use at load only what the files before it declare.
PAGE = os.path.join(HERE, "page")
PAGE_STYLE = "desk.css"
PAGE_SCRIPTS = ("core.js", "pages.js", "overview.js", "curve.js", "chart.js", "palette.js", "portfolio.js", "history.js", "companies.js", "filings.js", "sources.js",
                "news.js", "screener.js", "trades.js", "research.js", "journal.js", "chat.js", "app.js")
DIVIDEND_MONTHS = 24        # months shown in the dividend chart
MAX_JOURNAL_CHARS = 2000


# ---- small helpers -------------------------------------------------------------
def num(x):
    try:
        v = float(x)
        return v if v == v else 0.0           # NaN → 0
    except (TypeError, ValueError):
        return 0.0


def short_ticker(ticker):
    """AAPL_US_EQ → AAPL, VUSAl_EQ → VUSA (Trading 212 marks London lines with a
    lowercase suffix letter)."""
    base = (ticker or "").split("_")[0]
    while len(base) > 1 and base[-1].islower() and base[:-1].isupper():
        base = base[:-1]
    return base or (ticker or "?")


def day_of(ts):
    """YYYY-MM-DD (UTC) from an ISO timestamp; '' if missing."""
    if not ts:
        return ""
    when = moment(ts)
    return when.astimezone(timezone.utc).date().isoformat() if when else str(ts)[:10]


def months_back(today, n):
    """The n calendar months ending with today's month, oldest first, as YYYY-MM."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


# ---- money-weighted return (GIPS: IRR of external cash flows) ----------------------
# The solver looks for the period's growth between e^-50 and e^50 times: no account's return
# comes near either, and no float overflows inside it.
MWR_LOG_RANGE = 50.0
# Money counts as at work while what has been put in, net, stands at this share of the most it ever stood at, or more.
# A rate is stated only for a stretch the money was at work for: a balance that sat near nothing for two years, with
# money passing through it for a few weeks, has a calendar of years and a rate that rests on the pennies that stayed
# (it read +4299.8% a year on an account worth 4 pounds). The desk's choice; no study sets it (docs/EVIDENCE.md).
MWR_AT_WORK_SHARE = 0.1
MWR_YEAR_DAYS = 365          # GIPS: no rate for a period under a year is annualised; here, nor for money at work for less


def days_at_work(flows, end_day):
    """The days, from the first of `flows` to `end_day`, on which the net put in stood at MWR_AT_WORK_SHARE of its
    highest or more. Money put in is positive; flows on one day are taken together."""
    by_day = {}
    for d, a in flows:
        by_day[d] = by_day.get(d, 0.0) + a
    days, level, levels = sorted(by_day), 0.0, []
    for d in days:
        level += by_day[d]
        levels.append(level)
    peak = max(levels) if levels else 0.0
    if peak <= 0:
        return 0
    end = date.fromisoformat(end_day)
    total = 0
    for i, d in enumerate(days):
        if levels[i] >= MWR_AT_WORK_SHARE * peak:
            until = date.fromisoformat(days[i + 1]) if i + 1 < len(days) else end
            total += max(0, (until - date.fromisoformat(d)).days)
    return total


def money_weighted_return(flows, end_value, end_day):
    """flows: [(YYYY-MM-DD, amount)] with money put in as positive, taken out as
    negative. Returns {'annual', 'period', 'days', 'at_work', 'steady', 'shown', 'why'} or None. `shown` says which
    of the two figures may be stated ("annual", "period" or None, with `why`): see MWR_AT_WORK_SHARE.

    The IRR solves Σ −flow·(1+r)^((end−t)/365) + end_value = 0. GIPS forbids
    annualising periods under a year, so the page shows `period` (the
    cumulative return over the holding time) until a year has passed.

    It is solved for the period's log growth g = ln(1+r)·(the years from the first flow),
    not for r: a few days' move is a very large annual rate (10% in a fortnight is over
    1,000% a year, 20% down in two days within 1e-17 of −100%), and until the audit of
    28 Sep 2026 a bracket on r gave no answer beyond 1,000% or below −99.99%. `annual`
    is None where it is too large for a float; it is shown only from a year, where it
    never is."""
    flows = [(d, a) for d, a in flows if d and a]
    if not flows or end_value < 0:
        return None
    end = date.fromisoformat(end_day)
    pts = [((end - date.fromisoformat(d)).days / 365.0, a) for d, a in flows]
    span = max(t for t, _ in pts)
    # money must have gone in; more may have come out than went in (Excel's own XIRR
    # example does), which also had no return until 28 Sep 2026
    if span <= 0 or not any(a > 0 for _, a in pts):
        return None

    def fv(g):
        return end_value - math.fsum(a * math.exp(g * t / span) for t, a in pts)

    lo, hi = -MWR_LOG_RANGE, MWR_LOG_RANGE
    if fv(lo) * fv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if fv(lo) * fv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    g = (lo + hi) / 2
    try:
        annual = math.expm1(g / span)
    except OverflowError:
        annual = None
    days = int(round(span * 365))
    at_work = days_at_work(flows, end_day)
    # which figure may be stated: a yearly rate once the money has been at work for a year; for under a year, the
    # period's own return (not annualised) if the money was at work for half of it; otherwise none, and the reason
    steady = 2 * at_work >= days
    shown = ("annual" if annual is not None and at_work >= MWR_YEAR_DAYS else None) if days >= MWR_YEAR_DAYS \
        else ("period" if steady else None)
    why = None if shown else (
        "the money was at work for only %d of the %d days" % (at_work, days) +
        (", and a yearly rate needs a year of it" if days >= MWR_YEAR_DAYS else ""))
    return {"annual": annual, "period": math.expm1(g), "days": days, "at_work": at_work, "steady": steady,
            "shown": shown, "why": why}


# ---- sections --------------------------------------------------------------------
def build_account(summary, positions):
    cash = summary.get("cash") or {}
    inv = summary.get("investments") or {}
    cash_total = num(cash.get("availableToTrade")) + num(cash.get("inPies")) + num(cash.get("reservedForOrders"))
    invested = num(inv.get("currentValue")) or sum(num((p.get("walletImpact") or {}).get("currentValue")) for p in positions)
    total = num(summary.get("totalValue")) or cash_total + invested
    # Trading 212's totalValue includes the spending pot, which the cash block leaves out
    pot = max(0.0, round(total - cash_total - invested, 2))
    return {
        "currency": summary.get("currency") or "USD",
        "total": total,
        "cash": cash_total,
        "cash_free": num(cash.get("availableToTrade")),
        "spending_pot": pot,
        "invested": invested,
        "cost": num(inv.get("totalCost")),
        "unrealized": num(inv.get("unrealizedProfitLoss")),
        "realized": num(inv.get("realizedProfitLoss")),
    }


def build_positions(positions, today):
    rows = []
    for p in positions or []:
        ins = p.get("instrument") or {}
        w = p.get("walletImpact") or {}
        value, cost = num(w.get("currentValue")), num(w.get("totalCost"))
        opened = day_of(p.get("createdAt"))
        rows.append({
            "ticker": short_ticker(ins.get("ticker")),
            # a US listing: only these are the SEC's filers, rated, and priced by the desk.
            # A London line can share a short ticker with an unrelated US company.
            "us_line": (ins.get("ticker") or "").endswith("_US_EQ"),
            "name": ins.get("name") or short_ticker(ins.get("ticker")),
            "currency": ins.get("currency") or "",
            "quantity": num(p.get("quantity")),
            "avg_price": num(p.get("averagePricePaid")),
            "price": num(p.get("currentPrice")),
            "value": value,
            "cost": cost,
            "pl": num(w.get("unrealizedProfitLoss")) if w.get("unrealizedProfitLoss") is not None else value - cost,
            "fx": num(w.get("fxImpact")),
            "opened": opened,
            "days_held": (today - date.fromisoformat(opened)).days if opened else None,
        })
    total = sum(r["value"] for r in rows)
    for r in rows:
        r["weight"] = r["value"] / total if total > 0 else 0.0
        r["pl_pct"] = r["pl"] / r["cost"] if r["cost"] > 0 else None
    rows.sort(key=lambda r: -r["value"])
    return {
        "rows": rows,
        "count": len(rows),
        "largest": rows[0]["weight"] if rows else None,
        "top5": sum(r["weight"] for r in rows[:5]) if rows else None,
    }


def build_trades(orders, journal):
    rows = []
    for item in orders or []:
        order, fill = item.get("order") or {}, item.get("fill") or {}
        if not fill or fill.get("type", "TRADE") != "TRADE":
            continue
        w = fill.get("walletImpact") or {}
        ins = order.get("instrument") or {}
        fees = sum(abs(num(t.get("quantity"))) for t in (w.get("taxes") or []))
        oid = str(order.get("id"))
        rows.append({
            "id": oid,
            "date": day_of(fill.get("filledAt") or order.get("createdAt")),
            "time": fill.get("filledAt") or order.get("createdAt") or "",
            "side": order.get("side") or ("SELL" if num(fill.get("quantity")) < 0 else "BUY"),
            "ticker": short_ticker(order.get("ticker") or ins.get("ticker")),
            # a US listing: only its splits are known (prices.split_factor), and only it is
            # the SEC's filer of that ticker
            "us_line": (order.get("ticker") or ins.get("ticker") or "").endswith("_US_EQ"),
            "name": ins.get("name") or short_ticker(order.get("ticker")),
            "quantity": abs(num(fill.get("quantity"))),
            "price": num(fill.get("price")),
            "price_currency": ins.get("currency") or order.get("currency") or "",
            "value": abs(num(w.get("netValue"))),
            "realized": num(w.get("realisedProfitLoss")) if w.get("realisedProfitLoss") is not None else None,
            "fees": fees,
            "source": order.get("initiatedFrom") or "",
            "note": (journal.get(oid) or {}).get("note", ""),
            # the day the user said they would look at this trade again, if they gave one
            "look_again": (journal.get(oid) or {}).get("look_again"),
        })
    rows.sort(key=lambda r: r["time"], reverse=True)
    return {
        "rows": rows,
        "count": len(rows),
        "buys": sum(1 for r in rows if r["side"] == "BUY"),
        "sells": sum(1 for r in rows if r["side"] == "SELL"),
        "fees": sum(r["fees"] for r in rows),
        "noted": sum(1 for r in rows if r["note"]),
    }


# The company data (filings, prices, financials, ratings, research) is updated by the page
# itself, on opening and at this interval while it is open. The desk's choice: close enough
# for a price seen during the day, far enough apart for the SEC's and Tiingo's limits.
MARKET_EVERY_MINUTES = 30


# ---- since you last looked -----------------------------------------------------------
DIGEST_SHOWN = 3        # items listed of each kind: a presentation limit, the rest counted
DIGEST_FALLBACK_DAYS = 7  # with no earlier sync on record: the last week, the desk's choice


def _stamp(value):
    """An ISO time cut to the second, so "2026-09-25T16:05:00.000Z" and
    "2026-09-25T09:00:00+00:00" compare as the times they are (both UTC)."""
    return str(value or "")[:19]


def _filed_utc(item):
    """When a filing was accepted, as a UTC time cut to the second (the SEC's own time is
    New York's: news.filed_moment); its date alone when no time was kept."""
    when = news_mod.filed_moment(item.get("filed_at"))
    return when.astimezone(timezone.utc).isoformat()[:19] if when else _stamp(item.get("date"))


def build_digest(raw, news, prices, ratings_log, positions, today, as_of=None, trades=None, looks=None):
    """What is new since the user last looked (looks.py: the end of the visit before
    this one; it was the account sync before the last, which emptied on a second sync and
    never moved without one): important filings, insider buys,
    ratings given or changed, the biggest moves among the holdings, the holdings the
    desk rates Sell, and trades whose second look, set by the user, has come. Not for a
    past day: "since you last looked" is about now. No trade is asked for a reason."""
    if as_of:
        return None
    since = looks_mod.since(looks)
    start = _stamp(since) if since else (today - timedelta(days=DIGEST_FALLBACK_DAYS)).isoformat()
    fresh = [i for i in (news or {}).get("items") or [] if _filed_utc(i) > start]
    important = [i for i in fresh if i.get("material")]
    buys = [i for i in fresh if i.get("label") == "Insider bought"]
    previous, changes = {}, []
    # the user's companies only: the log also holds the fixed sample's ratings, logged to
    # score the rating fairly, of companies nobody chose
    mine = set((news or {}).get("tickers") or []) | {r["ticker"] for r in (positions or {}).get("rows") or []
                                                     if r.get("us_line")}
    for e in ratings_log or []:
        if e.get("ticker") not in mine:
            continue
        # a rating logged again under a new definition, with the same label, is no news
        if _stamp(e.get("at") or e.get("date")) > start and previous.get(e["ticker"]) != e["label"]:
            changes.append({"ticker": e["ticker"], "label": e["label"], "was": previous.get(e["ticker"])})
        previous[e["ticker"]] = e["label"]
    moves = []
    for row in (positions or {}).get("rows") or []:
        if not row.get("us_line"):
            continue                                  # the desk prices US listings only
        series = price_store.series(prices, row["ticker"])
        days = sorted(series)
        before = [d for d in days if d <= start[:10]]
        if before and days and days[-1] > before[-1] and series[before[-1]]:
            moves.append({"ticker": row["ticker"], "change": series[days[-1]] / series[before[-1]] - 1,
                          "from": before[-1], "to": days[-1]})
    moves.sort(key=lambda m: -abs(m["change"]))
    # an announcement (8-K) says what it is in its own items ("Results announced"); its
    # label alone ("Company announcement") says nothing
    line = lambda i: dict({k: i.get(k) for k in ("ticker", "label", "what", "date", "url")},
                          headline=(event_category(i).split(": ", 1)[-1]
                                    if (i.get("form") or "").upper() in ("8-K", "6-K") else i.get("label")))
    trade_rows = (trades or {}).get("rows") or []
    due = sorted((r for r in trade_rows if r.get("look_again") and r["look_again"] <= today.isoformat()),
                 key=lambda r: r["look_again"])
    trade = lambda r: {"id": r["id"], "ticker": r["ticker"], "side": r["side"], "date": r["date"],
                       "look_again": r.get("look_again"), "note": (r.get("note") or "").split("\n")[0]}
    return {"since": since, "fallback_days": None if since else DIGEST_FALLBACK_DAYS,
            "due": [trade(r) for r in due[:DIGEST_SHOWN]], "due_count": len(due),
            "important": [line(i) for i in important[:DIGEST_SHOWN]], "important_count": len(important),
            "insider_buys": [line(i) for i in buys[:DIGEST_SHOWN]], "insider_buys_count": len(buys),
            "ratings": changes[-DIGEST_SHOWN:][::-1], "ratings_count": len(changes),
            "moves": moves[:DIGEST_SHOWN],
            "rated_sell": [r["ticker"] for r in (positions or {}).get("rows") or []
                           if (r.get("rating") or {}).get("label") == "Sell"]}


# Trading 212's names for the charges on a fill, in words. A name not here is shown as
# it comes, tidied ("SOME_NEW_FEE" reads "Some new fee"), never dropped.
FEE_NAMES = {
    "CURRENCY_CONVERSION_FEE": "Currency conversion fee",
    "FINRA_FEE": "FINRA trading activity fee",
    "STAMP_DUTY": "UK stamp duty",
    "STAMP_DUTY_RESERVE_TAX": "UK stamp duty reserve tax",
    "PTM_LEVY": "UK PTM levy",
    "TRANSACTION_FEE": "Transaction fee",
    "FRENCH_TRANSACTION_TAX": "French financial transaction tax",
    "COMMISSION": "Commission",                   # another broker's charge on a trade (broker.py)
}


def _fee_name(code):
    code = str(code or "UNNAMED_CHARGE")
    return FEE_NAMES.get(code) or code.replace("_", " ").capitalize()


def build_costs(orders, dividends, transactions, account, positions, investing, prices):
    """What investing has cost: every charge on every fill by kind, the tax withheld from
    dividends (the declared dividend less what reached the account), and beside them the
    interest paid on cash and what currency moves did to the holdings. With their share
    of what investing earned before them."""
    currency = account.get("currency") or "USD"
    kinds, first = {}, None
    for item in orders or []:
        fill = item.get("fill") or {}
        for tax in (fill.get("walletImpact") or {}).get("taxes") or []:
            kinds[_fee_name(tax.get("name"))] = kinds.get(_fee_name(tax.get("name")), 0.0) + abs(num(tax.get("quantity")))
            day = day_of(fill.get("filledAt"))
            first = min(first, day) if first and day else (day or first)
    withheld, unconverted = 0.0, 0
    for d in dividends or []:
        if d.get("grossAmount") is not None:            # another broker's, in the account's currency (broker.py)
            withheld += max(0.0, num(d.get("grossAmount")) - num(d.get("amount")))
            continue
        gross = num(d.get("grossAmountPerShare")) * num(d.get("quantity"))
        paid_in = d.get("tickerCurrency") or (d.get("instrument") or {}).get("currency") or currency
        if gross <= 0:
            continue
        if paid_in != currency:
            # a dollar dividend into a euro or pound account: through that day's rate
            rate = _on_or_before(price_store.fx_rates(prices, currency), day_of(d.get("paidOn")) or "")
            if paid_in != "USD" or not rate:
                unconverted += 1
                continue
            gross = gross / rate
        withheld += max(0.0, gross - num(d.get("amount")))
    fees = sum(kinds.values())
    total = fees + withheld
    before = (investing or 0.0) + total
    return {"kinds": [{"label": k, "amount": v} for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])],
            "fees": fees, "withheld": withheld, "unconverted_dividends": unconverted, "total": total,
            "share_of_gain": total / before if before > 0 else None,
            "interest": sum(num(t.get("amount")) for t in transactions or [] if t.get("type") in INTEREST_TYPES),
            "currency_moves": sum(r.get("fx") or 0.0 for r in (positions or {}).get("rows") or []),
            "since": first}


# ---- what the account is invested in ---------------------------------------------------
EXPOSURE_NO_DATA = {
    "universe": "no universe of SEC filers is stored (python3 universe.py builds it)",
    "codes": "no industry codes are stored (python3 sectors.py builds them)",
}


def build_exposure(positions, universe, codes, account):
    """The account by industry: each holding the SEC's data covers placed in its SIC
    major group (the SEC's own code for the company), funds and every other line counted
    together and named, cash apart. Shares of the whole account, so they add to 100%."""
    companies = (universe or {}).get("companies") or {}
    rows = (positions or {}).get("rows") or []
    cash = num(account.get("cash")) + num(account.get("spending_pot"))
    whole = sum(r["value"] for r in rows) + cash
    groups, unplaced = {}, []
    for r in rows:
        company = companies.get(r["ticker"]) if r.get("us_line") else None
        name = sectors.major_group((codes or {}).get((company or {}).get("cik")))
        if not name:
            unplaced.append(r)
            continue
        group = groups.setdefault(name, {"label": name, "value": 0.0, "tickers": []})
        group["value"] += r["value"]
        group["tickers"].append(r["ticker"])
    share = lambda v: v / whole if whole > 0 else None
    out = sorted(groups.values(), key=lambda g: -g["value"])
    for g in out:
        g["weight"] = share(g["value"])
    rest = sum(r["value"] for r in unplaced)
    return {"groups": out,
            "unplaced": {"value": rest, "weight": share(rest), "tickers": [r["ticker"] for r in unplaced]}
            if unplaced else None,
            "cash": {"value": cash, "weight": share(cash)},
            "whole": whole,
            "missing": None if not rows else EXPOSURE_NO_DATA["universe"] if not companies
            else EXPOSURE_NO_DATA["codes"] if not codes else None}


def build_dividends(dividends, today):
    months = months_back(today, DIVIDEND_MONTHS)
    by_month = {m: 0.0 for m in months}
    by_ticker, total = {}, 0.0
    year_ago = date(today.year - 1, today.month, min(today.day, 28)).isoformat()
    last_12 = 0.0
    for d in dividends or []:
        amt = num(d.get("amount"))
        day = day_of(d.get("paidOn"))
        total += amt
        if day >= year_ago:
            last_12 += amt
        if day[:7] in by_month:
            by_month[day[:7]] += amt
        t = short_ticker(d.get("ticker") or (d.get("instrument") or {}).get("ticker"))
        by_ticker[t] = by_ticker.get(t, 0.0) + amt
    tickers = sorted(({"ticker": k, "amount": v} for k, v in by_ticker.items()), key=lambda x: -x["amount"])
    return {
        "total": total,
        "last_12": last_12,
        "months": [{"month": m, "amount": by_month[m]} for m in months],
        "tickers": tickers,
        "count": len(dividends or []),
    }


# Interest the account earned: on its free cash, and from lending its shares.
INTEREST_TYPES = ("INTEREST_ON_FREE_CASH", "LENDING_INTEREST")


def external_flows(transactions):
    """Money the person moved in or out — deposits, withdrawals, transfers.
    Fees and interest are part of the return, not flows."""
    flows = []
    for t in transactions or []:
        kind, amt = t.get("type"), num(t.get("amount"))
        if kind == "DEPOSIT":
            flows.append((day_of(t.get("dateTime")), abs(amt)))
        elif kind == "WITHDRAW":
            flows.append((day_of(t.get("dateTime")), -abs(amt)))
        elif kind == "TRANSFER":
            flows.append((day_of(t.get("dateTime")), amt))
    return sorted(flows)


def _on_or_before(series, day):
    """The value on the latest day not after `day`, or None."""
    earlier = [d for d in series if d <= day]
    return series[max(earlier)] if earlier else None


def same_money_in_market(flows, prices, currency, end=None, opening=None):
    """`flows` [(day, amount in the account's currency)] each put into (or taken out of) the S&P
    500 at the first close on or after its day (SPY's total return, dividends reinvested, no
    fees), valued at the close of `end` or the latest. `opening` (day, value) is what a period
    began with, put in at the close that value was taken at: the last on or before its day. An
    account in euros or pounds goes through the exchange rate of the same session each way
    (prices.FX_SERIES). (value, the close's day, None), or (None, None, why not). The one
    comparison with the market: the Overview's for the whole account, History's for each year.
    (28 Sep 2026: a year ending on a weekend had its opening value bought at the next year's
    first close, through a rate of the day before: the market's year lost its first session.)"""
    market = price_store.series(prices, price_store.BENCHMARK)
    if not market:
        return None, None, "the S&P 500's closes are not stored yet: they come with the next company update"
    fx = None
    if (currency or "USD") != "USD":
        fx = price_store.fx_rates(prices, currency)
        if not fx:
            return None, None, (f"it needs {currency} to dollar exchange rates, fetched from FRED for euro and pound "
                                f"accounts with the next company update" if currency in price_store.FX_SERIES else
                                f"it needs {currency} to dollar exchange rates, which the desk fetches only for "
                                f"euro and pound accounts")
    days = sorted(market)
    units = 0.0
    for day, amount, at_close in ([(opening[0], opening[1], True)] if opening else []) + [(d, a, False) for d, a in flows]:
        if day < days[0]:
            return None, None, f"the S&P 500's stored closes begin on {days[0]}, after a deposit on {day}"
        if at_close:
            session = max(d for d in days if d <= day)
        else:
            # a deposit after the latest close goes in at that close: it has had no time in
            # the market on either side, so it counts at its face value in both
            i = _first_index(days, day)
            session = days[-1 if i is None else i]
        rate = _on_or_before(fx, session) if fx else 1.0
        if not rate:
            return None, None, f"the exchange rates it needs do not reach back to {day}, the day of a deposit"
        units += amount * rate / market[session]
    last = days[-1] if end is None else max((d for d in days if d <= end), default=days[0])
    return units * market[last] / (_on_or_before(fx, last) if fx else 1.0), last, None


def build_vs_market(account, transactions, prices):
    """The account against the same money in the S&P 500 (same_money_in_market): each deposit
    and withdrawal on its own day, valued at the latest close."""
    flows = external_flows(transactions)
    if not flows or not account.get("total"):
        return None
    currency = account.get("currency") or "USD"
    value, last, why = same_money_in_market(flows, prices, currency)
    if value is None:
        return {"why_not": why}
    return {"market_value": value, "account": account["total"], "difference": account["total"] - value,
            "difference_pct": account["total"] / value - 1 if value > 0 else None,
            "as_of": last, "since": flows[0][0], "flows": len(flows), "currency": currency,
            "converted": currency != "USD"}


def build_growth(account, transactions, today, dividends_total=0.0):
    flows = external_flows(transactions)
    interest = sum(num(t.get("amount")) for t in transactions or [] if t.get("type") in INTEREST_TYPES)
    deposited = sum(a for _, a in flows if a > 0)
    withdrawn = -sum(a for _, a in flows if a < 0)
    net_in = deposited - withdrawn
    mwr = money_weighted_return(flows, account["total"], today.isoformat()) if flows else None
    return {
        "deposited": deposited,
        "withdrawn": withdrawn,
        "net_in": net_in,
        "gain": account["total"] - net_in if flows else None,
        # what investing itself earned; unaffected by card spending or ISA transfers
        "investing": account["realized"] + account["unrealized"] + dividends_total + interest,
        "interest": interest,
        "first_deposit": flows[0][0] if flows else None,
        "mwr": mwr,
    }


# ---- what happened after past filings like this one --------------------------------
WINDOWS = (1, 5, 20)            # trading days after the filing
HEADLINE_WINDOW = 5             # the one the page reports; the others are kept for the record


def event_category(item):
    """Filings are compared with past filings of the same kind."""
    form = (item.get("form") or "").upper()
    if form == "4":
        return "Insider bought" if item.get("material") else "Insider trade"
    if form in ("8-K", "6-K"):
        first = (item.get("what") or "").split(";")[0].strip()
        return f"Announcement: {first}" if first else "Announcement"
    return item.get("label") or form


def _event_moves(days, series, bench, session, windows):
    """{w: the share's move over the w sessions from `session` on, less the market's (SPY) over
    the same two closes}. The window opens at the close before the first session the event
    could move (MacKinlay 1997: day 0 is the event's, in the window), so a filing made before
    or during a session has that session's move in it. Until 28 Sep 2026 it opened at the close
    on the filing's date, which left out the session a morning's results moved. A window whose
    closes the market lacks is left out, never taken as a market move of zero (S-02)."""
    i = _first_index(days, session)
    if not i:                                           # none on or after it, or no close before
        return {}, None
    base = days[i - 1]
    if not series[base] or not bench.get(base):
        return {}, i
    out = {}
    for w in windows:
        j = i - 1 + w
        if j < len(days) and bench.get(days[j]):
            out[w] = (series[days[j]] / series[base] - 1) - (bench[days[j]] / bench[base] - 1)
    return out, i


def event_session(item):
    """The first session a filing could move: by its acceptance time, New York's (a filing
    accepted at 16:05 moves the next); with a date alone, that day's, or the next weekday's."""
    when = news_mod.filed_moment(item.get("filed_at"))
    day = price_store.session_day(when) if when else _weekday_on_or_after(item.get("date"))
    return day.isoformat() if day else None


def _first_index(days, day):
    lo, hi = 0, len(days)
    while lo < hi:                       # days is sorted; bisect without importing
        mid = (lo + hi) // 2
        if days[mid] < day:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(days) else None


def build_reactions(items, prices, today):
    """For each ticker and kind of filing, how the share price moved afterwards
    compared with the market (SPY) over the same days — the company's own history,
    excluding events too recent to have a full window yet.

    An event counts only if it starts after the last counted one's longest window
    has closed. Filings cluster — a dozen insider forms on one day, a proxy and its
    supplements in one week — and overlapping windows share the same price moves,
    so counting each one counts one move many times and makes a record look far
    more certain than it is (event clustering, MacKinlay 1997, 'Event Studies in
    Economics and Finance', Journal of Economic Literature 35). The earliest filing
    of a cluster stands for it."""
    bench = price_store.series(prices, price_store.BENCHMARK)
    per = {}
    # Each company's price history is converted and sorted once, not once per
    # filing, and each acceptance time placed on its session once. It used to be done
    # per filing, which with a bank's record — JPMorgan has over a hundred thousand
    # filings — made every page build take four minutes, and a journal note or a
    # watchlist change rebuilds the page.
    histories, sessions = {}, {}
    for it in items:
        ticker = it.get("ticker")
        if ticker not in histories:
            series = price_store.series(prices, ticker)
            histories[ticker] = (series, sorted(series)) if series else None
        if not histories[ticker] or not it.get("date") or not bench:
            continue
        series, days = histories[ticker]
        placed = (it.get("filed_at"), it["date"])
        if placed not in sessions:
            sessions[placed] = event_session(it)
        if not sessions[placed]:
            continue
        moves, start = _event_moves(days, series, bench, sessions[placed], WINDOWS)
        key = (ticker, event_category(it))
        # Counted only when every window is complete for the share AND the market.
        # Each window used to keep its own sample — a filing 8 days old counted in
        # the 5-day figures but not the 20-day n — so "after 37 announcements… up in
        # 17" took its 17 from a different set than its 37 (S-01).
        if not all(w in moves for w in WINDOWS):
            continue
        per.setdefault(key, []).append((start, moves))
    counted = {}
    for (ticker, category), events in per.items():
        windows, last = {w: [] for w in WINDOWS}, None
        for start, moves in sorted(events, key=lambda e: e[0]):
            if last is not None and start < last + max(WINDOWS):
                continue                    # inside the last counted event's window
            last = start
            for w in WINDOWS:
                windows[w].append(moves[w])
        # Below uncertainty.SMALLEST no record, however lopsided, can be told from
        # no reaction, so none is shown (this replaced a chosen minimum of 5).
        if len(windows[WINDOWS[0]]) >= uncertainty.SMALLEST:
            counted[f"{ticker}|{category}"] = windows
    # Every record is a test of the headline window, and they are shown side by side,
    # so their intervals share one level, set by the false discovery rate across all
    # of them (S-13) — the correction the research page applies to its rules.
    ups = lambda windows, w: sum(1 for v in windows[w] if v > 0)
    level = uncertainty.family_level([uncertainty.sign_test_p(ups(windows, HEADLINE_WINDOW),
                                                               len(windows[HEADLINE_WINDOW]))
                                      for windows in counted.values()])
    out = {}
    for key, windows in counted.items():
        n = len(windows[WINDOWS[0]])        # the same events in every window
        # The median move with its interval, and the count of ups against half: both
        # invert the same sign test, so the two cannot disagree (Phase 5).
        out[key] = {
            "window": HEADLINE_WINDOW,
            "n": n,
            "moves": {str(w): uncertainty.median(windows[w], confidence=level, expected=0) for w in WINDOWS},
            "ups": {str(w): uncertainty.against_chance(ups(windows, w), n, confidence=level) for w in WINDOWS},
        }
    return out


def reaction_family(reactions):
    """What the page says once about every past-reaction range: how many records are
    compared at once, the level that allows for it, and how many would look like
    patterns by luck at 95% each (S-13)."""
    record = next(iter(reactions.values()), None)
    if not record:
        return None
    return {"records": len(reactions),
            "level": record["ups"][str(record["window"])]["level"],
            "usual_level": uncertainty.level_text(uncertainty.CONFIDENCE),
            "by_luck_at_usual": len(reactions) * (1 - uncertainty.CONFIDENCE)}


def named(news):
    """The filings with each form's plain name as news.label_for gives it now, not as it
    read when the filing was fetched (S-31), so the Filings page, the past-reaction
    records (grouped by that name) and the cards all read one table."""
    if not news or not news.get("items"):
        return news
    items = []
    for it in news["items"]:
        row = dict(it)
        name, why, important = news_mod.label_for(row.get("form") or "", "")
        row["label"] = name
        if row.get("what") in (None, "", "Filed with the SEC."):
            row["what"] = why
        row["material"] = bool(row.get("material")) or important
        items.append(row)
    return dict(news, items=items)


def build_news(news, positions_rows, today, prices=None):
    """Filings for the watchlist, newest first, with your holdings marked."""
    news = news or {}
    held = {r["ticker"] for r in positions_rows}
    all_items = news.get("items") or []
    reactions = build_reactions(all_items, prices, today)
    news["_reactions"] = reactions
    items = []
    for it in all_items[:400]:
        row = dict(it)
        row["held"] = row.get("ticker") in held
        row["days_ago"] = (today - date.fromisoformat(row["date"])).days if row.get("date") else None
        row["category"] = event_category(row)
        row["headline"] = filing_headline(row)             # "Results announced", not "Company announcement"
        row["reaction"] = reactions.get(f"{row.get('ticker')}|{row['category']}")
        items.append(row)
    tickers = news.get("tickers") or []
    return {
        "tickers": tickers,
        # the companies followed, apart from those held and shown without being followed
        "followed": [t for t in tickers if t not in (news.get("held") or [])],
        "companies": news.get("companies") or {},
        "unknown": news.get("unknown") or [],
        "items": items,
        "count": len(items),
        "material": sum(1 for i in items if i.get("material")),
        "insider": sum(1 for i in items if i.get("form") == "4"),
        "measured": sum(1 for i in items if i.get("reaction")),
        "max_coverage": news_mod.MAX_COVERAGE,
        "reaction_family": reaction_family(reactions),
        "history_years": round(len({i["date"][:4] for i in all_items if i.get("date")}) or 0),
        "prices_updated": (prices or {}).get("updated_at"),
        "synced_at": news.get("synced_at"),
    }


FEED_SHOWN = 200            # stories sent for the page's list, of each kind it can filter to: a size limit
# Whether a day's move was unusual for the shares: set against their own daily moves against
# the market over the NORMAL_DAYS trading days before it — an event study's market-adjusted
# model, estimated over 250 days (MacKinlay 1997, "Event studies in economics and finance",
# Journal of Economic Literature 35) — and unusual outside the range that holds
# uncertainty.CONFIDENCE of those ordinary days.
NORMAL_DAYS = 250


def excess_moves(series, bench):
    """[(day, the shares' move less the market's since the close before)], oldest first,
    for each day that follows the market's previous close in both series, so no move spans
    a day one of them skipped."""
    bench_days = sorted(bench)
    after = dict(zip(bench_days, bench_days[1:]))
    days = sorted(d for d in series if d in bench)
    return [(b, (series[b] / series[a] - 1) - (bench[b] / bench[a] - 1))
            for a, b in zip(days, days[1:]) if after.get(a) == b and series[a] and bench[a]]


def unusual(moves, day, move, days=None):
    """{"usual", "times", "unusual"} for a move on `day`: the spread (standard deviation) of
    the NORMAL_DAYS moves before it, how many times that spread this move is, and whether it
    lies outside the uncertainty.CONFIDENCE range of an ordinary day. None without a full
    NORMAL_DAYS of moves before it. `days` is the moves' days, when the caller has them."""
    import bisect, statistics
    end = bisect.bisect_left(days if days is not None else [d for d, _ in moves], day)
    before = [m for _, m in moves[max(0, end - NORMAL_DAYS):end]]
    if move is None or len(before) < NORMAL_DAYS:
        return None
    usual = statistics.stdev(before)
    if not usual:
        return None
    edge = statistics.NormalDist().inv_cdf(0.5 + uncertainty.CONFIDENCE / 2)
    return {"usual": usual, "times": abs(move) / usual, "unusual": abs(move) > edge * usual}


def filing_headline(item):
    """What a filing is, in a line: an announcement (8-K) by its items ("Results announced"),
    anything else by its form's plain name."""
    if (item.get("form") or "").upper() in ("8-K", "6-K"):
        return event_category(item).split(": ", 1)[-1]
    return item.get("label") or item.get("form")


def _story(group, ticker):
    """One story, however many outlets carried it: the first time any of them had it, the
    press outlet's link where there is one (the FT's own link), every source named."""
    group = sorted(group, key=lambda i: i["at"])
    press = [i for i in group if headlines_mod.outlet(i.get("source"))]
    sources = list(dict.fromkeys(i.get("source") or "no source named" for i in group))
    lead = press[0] if press else group[0]
    return {"ticker": ticker, "headline": lead["headline"], "url": lead["url"], "at": group[0]["at"],
            "sources": sources, "press": headlines_mod.outlet(lead.get("source")) if press else None}


def day_move(series, days, bench, bench_days, session):
    """The shares' move from the close before `session` to the first close on or after
    it, less the market's (SPY) over the same two closes; with the day of that close.
    None for the move when that close is not stored yet, or when the market traded
    between the two closes (a missing close would make it a move over several days)."""
    i = _first_index(days, session.isoformat())
    if i is None:
        return None, None
    if i == 0 or not series[days[i - 1]]:
        return None, days[i]
    before, day = days[i - 1], days[i]
    j = _first_index(bench_days, before)
    if (j is None or j + 1 >= len(bench_days) or bench_days[j] != before or bench_days[j + 1] != day
            or not bench[before]):
        return None, day
    return (series[day] / series[before] - 1) - (bench[day] / bench[before] - 1), day


def build_headlines(store, prices, tickers, names=None, filings=None, today=None):
    """Each followed company's news (headlines.py), grouped by the trading session it
    reached first: only stories about the company (headlines.about), each once however
    many outlets carried it, beside the company's important SEC filings of that session,
    how the shares moved that day against the market, and whether that move was unusual
    for them. And the stories across all the companies, for the page to list and filter.
    What was written and what the price did that day, side by side: no score, no forecast."""
    store = store or {}
    bench = price_store.series(prices, price_store.BENCHMARK)
    bench_days = sorted(bench)
    stored = store.get("companies") or {}
    start = ((today or datetime.now(timezone.utc).date()) - timedelta(days=headlines_mod.KEEP_DAYS)).isoformat()
    companies, everything = {}, []
    for ticker in dict.fromkeys(str(t).upper() for t in tickers or []):
        filed = (names or {}).get(ticker)
        items = [i for i in stored.get(ticker) or [] if i.get("headline") and i.get("at")
                 and headlines_mod.about(i, ticker, filed)]
        # the same story is the same headline on the same trading day: outlets carry a wire's
        # story within hours, and a headline written again on another day ("why the shares
        # are up today") is another story
        groups = {}
        for item in items:
            when = moment(item["at"])
            if when is None:
                continue
            session = price_store.session_day(when)
            groups.setdefault((session, headlines_mod._plain(item["headline"])), []).append(item)
        stories = sorted((_story(g, ticker) for g in groups.values()), key=lambda s: s["at"], reverse=True)
        series = price_store.series(prices, ticker)
        days = sorted(series)
        moves = excess_moves(series, bench) if series and bench else []
        move_days = [d for d, _ in moves]
        latest = max((s["at"] for s in stories), default=None)
        sessions = {}

        def session_of(session):
            if session not in sessions:
                move, close_day = day_move(series, days, bench, bench_days, session) if series else (None, None)
                sessions[session] = dict({"session": session.isoformat(), "close_day": close_day, "move": move,
                                          "items": [], "filings": []},
                                         **((unusual(moves, close_day, move, move_days) or {}) if close_day else {}))
            return sessions[session]
        for story in stories:
            session = session_of(price_store.session_day(moment(story["at"])))
            session["items"].append(story)
            everything.append(dict(story, session=session["session"]))
        # the company's own important filings, each on the session it could first move
        for f in filings or []:
            if f.get("ticker") != ticker or not f.get("material") or (f.get("date") or "") < start:
                continue
            when = news_mod.filed_moment(f.get("filed_at"))
            day = price_store.session_day(when) if when else _weekday_on_or_after(f.get("date"))
            if day:
                session_of(day)["filings"].append({"headline": filing_headline(f), "form": f.get("form"),
                                                   "url": f.get("url"), "at": when.isoformat() if when else None})
        # each session's stories and filings are listed on it; the others' unusual flag goes with them
        flags = {k.isoformat(): s.get("unusual") for k, s in sessions.items()}
        for story in everything:
            if story["ticker"] == ticker:
                story["unusual"] = flags.get(story["session"])
        companies[ticker] = {"ticker": ticker, "count": len(stories), "latest": latest,
                             "press": sum(1 for s in stories if s["press"]),
                             "unusual_days": sum(1 for s in sessions.values() if s.get("unusual")),
                             "days": [sessions[k] for k in sorted(sessions, reverse=True)]}
    everything.sort(key=lambda i: i["at"], reverse=True)
    # the newest of every story, of the press's, and of those on an unusual day: what the
    # page's three lists show, each whole within FEED_SHOWN
    feed, seen = [], set()
    for kind in (lambda s: True, lambda s: s["press"], lambda s: s.get("unusual")):
        for story in [s for s in everything if kind(s)][:FEED_SHOWN]:
            if id(story) not in seen:
                seen.add(id(story))
                feed.append(story)
    feed.sort(key=lambda i: i["at"], reverse=True)
    return {"companies": companies, "feed": feed, "count": len(everything),
            "keep_days": headlines_mod.KEEP_DAYS, "close": price_store.CLOSE,
            "sources": list(headlines_mod.SOURCES.values()), "outlets": [name for _, name, _ in headlines_mod.PRESS],
            "normal_days": NORMAL_DAYS, "level": uncertainty.level_text(uncertainty.CONFIDENCE),
            "one_in": round(1 / (1 - uncertainty.CONFIDENCE)), "lede_words": headlines_mod.LEDE_WORDS,
            "updated_at": store.get("updated_at")}


def _weekday_on_or_after(day):
    """The session a filing with a date and no time is placed on: that day, or the next
    weekday."""
    try:
        d = date.fromisoformat(str(day or "")[:10])
    except ValueError:
        return None
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def price_summary(series, bench, today, quote=None, printed=None):
    """Last close, the move over a year against the market, and a price taken since the
    close (pre-market, the session, after hours) when there is one."""
    if not series:
        return None
    days = sorted(series)
    last = days[-1]
    year_ago = (today - timedelta(days=365)).isoformat()
    i = _first_index(days, year_ago)
    close = (printed or {}).get(last) or series[last]      # as printed; the adjusted for the moves
    out = {"close": close, "as_of": last,
           "latest": price_store.latest_after_close(quote, last, close)}
    # the last session's move, and that move less the market's over the same two closes
    if len(days) > 1 and series[days[-2]]:
        out["day"] = series[last] / series[days[-2]] - 1
        if bench:
            out["day_vs_market"] = day_move(series, days, bench, sorted(bench), date.fromisoformat(last))[0]
    if i is not None and i < len(days) - 1 and series[days[i]]:
        out["year"] = series[last] / series[days[i]] - 1
        # the market over the same two closes: until 28 Sep 2026 its newest close was used even
        # when the share's newest was an earlier day's
        if bench and bench.get(days[i]) and bench.get(last):
            out["year_vs_market"] = out["year"] - (bench[last] / bench[days[i]] - 1)
    return out


def notes_by_ticker(rows):
    """How many of the user's journal notes are on trades in each company."""
    counts = {}
    for r in rows or []:
        if r.get("note"):
            counts[r["ticker"]] = counts.get(r["ticker"], 0) + 1
    return counts


def coverage_of(ticker, coverage, notes, today, theses=None):
    """How long a company has been followed, and what the user has written on it:
    journal notes on its trades (Phase 6) and theses on its results (Phase 9). A company
    followed before the desk kept dates has no date: said so, not guessed."""
    record = ((coverage or {}).get("coverage") or {}).get(ticker) or {}
    since = record.get("followed_at")
    return {"followed_at": since,
            "days": (today - date.fromisoformat(since)).days if since else None,
            "notes": (notes or {}).get(ticker, 0),
            "theses": sum(1 for t in theses or [] if t.get("ticker") == ticker)}


def company_name(ticker, news_data, store=None):
    """The filer's name from its filings, or from the SEC's list of filers (the rating's
    store) until they load; with neither, the ticker as it is — never dressed up as a
    name (never "Aapl")."""
    names = (((news_data or {}).get("companies") or {}).get(ticker),          # news.refresh stores the
             (((store or {}).get("companies") or {}).get(ticker) or {}).get("name"))  # ticker when it has none
    filed = next((n for n in names if n and n.upper() != ticker.upper()), None)
    return universe.display_name(filed) if filed else ticker


def build_companies(news_data, fundamentals, earnings, prices, reactions, today, summaries=None,
                    analysts=None, coverage=None, notes=None, theses=None, wording=None, quotes=None,
                    store=None, held=()):
    """One card per company covered — each followed, then each held and not followed: what
    the company reports, when it next reports, and how its
    shares have moved. Facts only."""
    followed = set((coverage or {}).get("tickers") or [])
    bench = price_store.series(prices, price_store.BENCHMARK)
    funds = (fundamentals or {}).get("companies") or {}
    earn = (earnings or {}).get("companies") or {}
    rated = (analysts or {}).get("companies") or {}
    out = []
    for ticker in (news_data or {}).get("tickers") or []:
        f = funds.get(ticker) or {}
        splits = price_store.splits(prices, ticker)
        if splits and f.get("facts"):
            # the per-share figures in today's shares, not each in the shares of its filing's day
            f = dict(f, **fundamentals_mod.derive(ticker, f.get("cik"), f["facts"], f.get("tags") or {},
                                                  splits=splits, through=today.isoformat()))
        e = earn.get(ticker) or {}
        nxt = e.get("next")
        history = e.get("history") or []
        out.append({
            "ticker": ticker,
            "followed": ticker in followed,
            "held": ticker in set(held),
            "name": company_name(ticker, news_data, store),
            "price": price_summary(price_store.series(prices, ticker), bench, today,
                                   ((quotes or {}).get("quotes") or {}).get(ticker),
                                   printed=price_store.series(prices, ticker, "c")),
            # price to earnings against its own last five years, from printed closes (value.py)
            "pe_history": value.own_history(f, price_store.series(prices, ticker, "c"), today, splits),
            "revenue": f.get("revenue"),
            "revenue_growth": f.get("revenue_growth"),
            "revenue_asof": f.get("revenue_asof"),
            # which period each top-of-card figure covers, so its label can say (J-07)
            "revenue_basis": f.get("revenue_basis"),
            "eps_asof": f.get("eps_asof"),
            "eps_basis": f.get("eps_basis"),
            "cash_asof": f.get("cash_asof"),
            "cash_includes_restricted": f.get("cash_includes_restricted"),
            "why": f.get("why") or {},
            "withheld": f.get("withheld") or [],
            "equity_asof": f.get("equity_asof"),
            "gross_margin": f.get("gross_margin"),
            "operating_margin": f.get("operating_margin"),
            "net_margin": f.get("net_margin"),
            "debt_to_equity": f.get("debt_to_equity"),
            "cash": f.get("cash"),
            "eps": f.get("eps"),
            "next_earnings": nxt,
            "days_to_earnings": ((date.fromisoformat(nxt["date"]) - today).days if nxt else None),
            "surprises": history[:4],
            "beats": forecasts.beat_record(history),
            "results_reaction": reactions.get(f"{ticker}|Announcement: Results announced"),
            "summary": (summaries or {}).get(ticker),
            "analysts": rated.get(ticker),
            "coverage": coverage_of(ticker, coverage, notes, today, theses),
            # what changed in the annual report's wording (Phase 10)
            "wording": diffs.for_card(wording, ticker),
        })
    return out


def _trade_order(row):
    """Fills in the order they happened: by time, and two with one time stamp by their order
    number, which Trading 212 gives in sequence (28 Sep 2026: a purchase and a sale of one day
    with one stamp were matched sale first, and the sale missed the purchase)."""
    oid = str(row.get("id") or "")
    return (row.get("time") or "", int(oid) if oid.isdigit() else 0, oid)


def build_closed_trades(trades, prices, today, currency="USD"):
    """Match each sale to the buys it closed (first in, first out) and ask the question a
    broker never answers: did it beat leaving the same money in the market?

    One row a sale, however many buys it closed. The sale is the decision; counted lot by
    lot, one sale that closed five buys read as five trades, and the record as more
    certain than it is (27 Sep 2026: the demo's 12 sales read as 32 trades). Its return is
    what the money did, in the account's currency: what each buy took from the account and
    the sale gave back (each fill's net value, fees and the day's exchange rate in it; 28 Sep
    2026: it was the share's own price, which left out the currency's move in a euro or pound
    account), its buys weighted by their cost. The market's is SPY's over each buy's own
    days, in the account's currency too (FRED's rates), weighted alike; a buy made and sold
    on one day is left out of both, since daily prices cannot measure it. A buy made before
    a split is counted in the sale's shares (prices.split_factor): a 10-for-1 split read as a
    90% loss, and nine shares in ten were lost from the record. Only a US line's splits are
    known, and a line is its own: a London line sharing a short ticker is never matched with it."""
    bench = price_store.series(prices, price_store.BENCHMARK)
    bench_days = sorted(bench)
    fx = price_store.fx_rates(prices, currency) if (currency or "USD") != "USD" else None
    lots, closed, split = {}, [], price_store.SplitsRead(prices)
    for t in sorted(trades or [], key=_trade_order):
        qty, price, day, value = t.get("quantity") or 0, t.get("price") or 0, t.get("date"), t.get("value") or 0
        if not qty or not price or not day or not value:
            continue
        queue = lots.setdefault((t["ticker"], bool(t.get("us_line"))), [])
        if t["side"] == "BUY":
            # what one share cost the account, fees in; its price, in its own currency, to show
            queue.append({"qty": qty, "each": value / qty, "price": price, "date": day, "us": bool(t.get("us_line"))})
            continue
        left, taken = qty, []
        while left > 1e-9 and queue:
            lot = queue[0]
            f = split.factor(t["ticker"], lot["date"], day) if lot["us"] else 1.0
            take = min(left, lot["qty"] * f)                     # in the sale's shares
            lot["qty"] -= take / f
            left -= take
            if lot["qty"] <= 1e-9:
                queue.pop(0)
            taken.append({"date": lot["date"], "take": take, "each": lot["each"] / f, "price": lot["price"] / f,
                          "split": f != 1.0, "market": _market_return(bench_days, bench, fx, lot["date"], day)})
        if not taken:
            continue
        received = value / qty                                   # what one share gave the account, fees out

        def result(part):
            cost = sum(x["take"] * x["each"] for x in part)
            return sum(x["take"] for x in part) * received / cost - 1 if cost else None
        scored = [x for x in taken if x["market"] is not None]
        weight = sum(x["take"] * x["each"] for x in scored)
        market = sum(x["take"] * x["each"] * x["market"] for x in scored) / weight if scored and weight else None
        gain_scored = result(scored) if scored else None
        shares = sum(x["take"] for x in taken)
        first = min(x["date"] for x in taken)
        closed.append({
            "ticker": t["ticker"],
            "bought": first,
            "bought_last": max(x["date"] for x in taken),
            "buys": len(taken),
            "sold": day,
            "days": (date.fromisoformat(day) - date.fromisoformat(first)).days,
            "quantity": shares,
            "buy_price": sum(x["take"] * x["price"] for x in taken) / shares,
            "sell_price": price,
            "price_currency": t.get("price_currency") or "",      # the prices' own: a US share's dollars
            "value": sum(x["take"] * x["each"] for x in taken),
            "gain": result(taken),
            "market": market,
            "vs_market": (gain_scored - market) if (gain_scored is not None and market is not None) else None,
            "split": any(x["split"] for x in taken),
            "after_fees": bool(t.get("fees")),
        })
    # what is still held from the buys, in today's shares
    open_lots = [{"ticker": k[0], "quantity": sum(l["qty"] * (split.factor(k[0], l["date"], today.isoformat()) if l["us"] else 1.0)
                                                  for l in v),
                  "bought": min(l["date"] for l in v)}
                 for k, v in lots.items() if sum(l["qty"] for l in v) > 1e-9]
    scored = [c for c in closed if c["vs_market"] is not None]
    closed.sort(key=lambda c: c["sold"], reverse=True)
    return {
        "rows": closed,
        "count": len(closed),
        "scored": len(scored),
        # each read as a rate, so each with its interval (Phase 5); the market count
        # against half, the median against no difference — one sign test for both
        "beat_market": uncertainty.against_chance(sum(1 for c in scored if c["vs_market"] > 0), len(scored)),
        "vs_market": uncertainty.median([c["vs_market"] for c in scored], expected=0),
        "won": uncertainty.proportion(sum(1 for c in closed if (c["gain"] or 0) > 0), len(closed)),
        "open_lots": open_lots,
    }


def _market_return(days, series, fx, start_day, end_day):
    """SPY's return from the first close on or after `start_day` to the first on or after
    `end_day`, in the account's currency: through FRED's rate on each of those two days, in
    US dollars per unit of it (`fx`, None for a dollar account). None when either is missing."""
    r = _window_return(days, series, start_day, end_day)
    if r is None or fx is None:
        return r
    i, j = _first_index(days, start_day), _first_index(days, end_day)
    a, b = _on_or_before(fx, days[i]), _on_or_before(fx, days[j])
    return (1 + r) * a / b - 1 if a and b else None


def _window_return(days, series, start_day, end_day):
    if not days:
        return None
    i, j = _first_index(days, start_day), _first_index(days, end_day)
    if i is None or j is None or j <= i or not series[days[i]]:
        return None
    return series[days[j]] / series[days[i]] - 1


def build_paper(paper, prices, today):
    """Value the practice portfolio at the last close, and ask the only question
    that matters: is it ahead of simply holding the market since it started?"""
    import copy
    import paper as paper_mod
    if (paper or {}).get("unreadable"):
        return {"unreadable": paper["unreadable"], "positions": [], "trades": []}
    paper = paper_mod.apply_splits(copy.deepcopy(paper or {}), prices)    # today's shares, at today's price
    bench = price_store.series(prices, price_store.BENCHMARK)
    bench_days = sorted(bench)
    cash = num(paper.get("cash", paper_mod.START_CASH))
    start_cash = num(paper.get("start_cash", paper_mod.START_CASH))
    rows, invested = [], 0.0
    for ticker, pos in sorted((paper.get("positions") or {}).items()):
        qty, cost = num(pos.get("quantity")), num(pos.get("cost"))
        price, price_day = paper_mod.last_close(prices, ticker)
        value = qty * (price or 0)
        invested += value
        rows.append({
            "ticker": ticker, "quantity": qty, "cost": cost, "price": price, "price_day": price_day,
            "value": value, "pl": value - cost, "pl_pct": (value / cost - 1) if cost else None,
            "average": cost / qty if qty else None,
        })
    total = cash + invested
    started = paper.get("started")
    market = _window_return(bench_days, bench, started, today.isoformat()) if started else None
    trades = paper.get("trades") or []
    return {
        "cost": paper_mod.TRADE_COST,
        "started": started,
        "days": (today - date.fromisoformat(started)).days if started else None,
        "cash": cash,
        "start_cash": start_cash,
        "invested": invested,
        "total": total,
        "return": total / start_cash - 1 if start_cash else None,
        "market_return": market,
        "vs_market": (total / start_cash - 1 - market) if (market is not None and start_cash) else None,
        "positions": sorted(rows, key=lambda r: -r["value"]),
        "trades": trades,
        "trade_count": len(trades),
        "noted": sum(1 for t in trades if t.get("reason")),
        "fees": sum(num(t.get("fee")) for t in trades),
        "realised": sum(num(t.get("realised")) for t in trades if t.get("realised") is not None),
    }


def build_research(research):
    """The evidence, as research.py measured it. Nothing is recomputed here, so
    the page can never show a different number from the one that was tested."""
    research = research or {}
    results = research.get("results") or []
    return {
        "generated_at": research.get("generated_at"),
        "universe": research.get("universe") or [],
        "by_rule": research.get("by_rule") or [],
        "results": results,
        "portfolio": research.get("portfolio") or [],
        "walk_blocks": research.get("walk_blocks"),
        "min_blocks_positive": research.get("min_blocks_positive"),
        "tested": research.get("tested", 0),
        "clears": research.get("clears", 0),
        "q_limit": research.get("q_limit"),
        "test_share": research.get("test_share"),
        "bootstrap_rounds": research.get("bootstrap_rounds"),
        # the level the stored ranges were computed at, as recorded with them — absent
        # from results older than the field, and then the page names no level
        "confidence": research.get("confidence"),
        "sector_funds": [t for t in (research.get("universe") or []) if t != price_store.BENCHMARK],
        "block_days": research.get("block_days"),
        "cost": research.get("cost"),
        "power": research.get("power") or {},
        "families": research.get("families") or {},
        # rule H's frozen shares (S-16), named on the page from the run that tested them
        "event_sample": research.get("event_sample") or [],
        "test_from": min((r["split_day"] for r in results), default=None),
        "test_to": max((r["to"] for r in results), default=None),
    }


# The figures at the top of every company card, in order. Declared here because both
# sides read it: the page lays them out and context draws each one's filed years.
CARD_TOP = ("revenue", "revenue_growth", "gross_margin", "operating_margin", "net_margin",
            "debt_to_equity", "cash", "eps")


def measure_display():
    """The screen measures', the valuation figures' and the bridge's display
    declarations, joined. Each is declared once by its owning module; a name in two
    would be two owners."""
    owners = (screen.MEASURE_DISPLAY, value.VALUE_DISPLAY, bridge.BRIDGE_DISPLAY, thesis_mod.THESIS_DISPLAY,
              uncertainty.UNCERTAINTY_DISPLAY, rating_mod.RATING_DISPLAY, value.OWN_HISTORY_DISPLAY)
    both = {name for i, a in enumerate(owners) for b in owners[i + 1:] for name in set(a) & set(b)}
    if both:
        raise ValueError(f"declared by two modules: {sorted(both)}")
    return {name: spec for owner in owners for name, spec in owner.items()}


def compute(raw, journal=None, today=None, news=None, prices=None, fundamentals=None, earnings=None,
            summaries=None, paper=None, analysts=None, research=None, coverage=None,
            theses=None, wording=None, universe=None, as_of=None, quotes=None, ratings_log=None, listings=None,
            headlines=None, health=None, plans=None, rating_sample=None, looks=None, briefs=None,
            broker=None):
    journal = journal or {}
    news = named(news)
    today = today or datetime.now(timezone.utc).date()
    # another broker's record, with what Trading 212 would state worked out; Trading 212's as it is
    raw = broker_mod.complete(raw or {}, prices, today)
    raw_positions = raw.get("positions") or []
    account = build_account(raw.get("summary") or {}, raw_positions)
    trades_data = build_trades(raw.get("orders"), journal)
    positions = build_positions(raw_positions, today)
    growth = build_growth(account, raw.get("transactions"), today,
                          sum(num(d.get("amount")) for d in raw.get("dividends") or []))
    # the desk's rating (decided 25 Sep 2026): the universe ranked on five
    # published measures, and the record of every rating logged since
    codes = sectors.load()
    ratings = rating_mod.rate_all(universe, codes, listings, prices, rating_sample, today)
    for row in positions["rows"]:
        row["rating"] = rating_mod.for_page(ratings, row["ticker"], row["us_line"])
    # each plan written before a trade, matched to it and scored; each trade shows its plan
    planned = plans_mod.summary(plans, trades_data["rows"], prices, today)
    for oid, plan in plans_mod.by_trade(planned).items():
        for row in trades_data["rows"]:
            if row["id"] == oid:
                row["plan"] = {k: plan[k] for k in ("id", "written", "why", "wrong_if", "review_by", "state")}
    companies = context.add_to(
        build_companies(news, fundamentals, earnings, prices,
                        build_reactions((news or {}).get("items") or [], prices, today),
                        today, summaries, analysts, coverage=coverage,
                        notes=notes_by_ticker(trades_data["rows"]), theses=theses, wording=wording,
                        quotes=quotes, store=universe, held=[r["ticker"] for r in positions["rows"] if r["us_line"]]),
        prices=prices, price_store=price_store, earnings=earnings, history=CARD_TOP, store=universe)
    company_news = build_headlines(headlines, prices, (news or {}).get("tickers") or [],
                                   names=(news or {}).get("companies"), filings=(news or {}).get("items"), today=today)
    for ticker, told in company_news["companies"].items():
        told["week"] = len(brief_mod.story_ids(brief_mod.week(told, today)))
    company_news["week_days"] = brief_mod.WEEK_DAYS
    for card in companies:
        card["rating"] = rating_mod.for_page(ratings, card["ticker"])
        # the week's news in brief, written when asked (brief.py), with how many stories came since
        card["brief"] = brief_mod.for_page((briefs or {}).get(card["ticker"]),
                                           company_news["companies"].get(card["ticker"]), today)
    return {
        "connected": bool(raw.get("summary")),
        # which broker the account comes from (broker.py): its name on the page, whether orders go to it
        "broker": broker_mod.for_page(raw, *(broker or (None, None))),
        "env": raw.get("env") or "live",
        "demo": bool(raw.get("demo_data")),
        "synced_at": raw.get("synced_at"),
        # when the company data was last fetched in full (the filings step of the market
        # refresh), and how often the page fetches it again; nothing for a past day
        "market_updated_at": None if as_of else (news or {}).get("synced_at"),
        "market_every_minutes": MARKET_EVERY_MINUTES,
        # the chart tab: its ranges are charts.py's (how often a live one asks again comes with each chart)
        "chart": {"ranges": list(charts_mod.RANGES), "default": charts_mod.DEFAULT_RANGE},
        # what each data source did at the last company update and account sync; today's only
        "health": None if as_of else health_mod.for_page(health),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        # how every measure is shown, from the modules that own them — the page's
        # formatMeasure reads this and nothing else (J-04)
        "measure_display": measure_display(),
        "card_top": list(CARD_TOP),
        # the past day the desk is shown as of (Phase 11), or None for today
        "as_of": as_of,
        # companies followed today that a past day cannot place: added before follow
        # dates were kept, so named rather than shown as covered then (K-03)
        "undated_coverage": (coverage or {}).get("undated") or [],
        "theses": thesis_mod.summary(theses or [], fundamentals, earnings,
                                     (news or {}).get("tickers") or [], today, (news or {}).get("items")),
        "account": account,
        "growth": growth,
        # the same deposits in the S&P 500: whether the account's choices beat the plain alternative
        "vs_market": build_vs_market(account, raw.get("transactions"), prices),
        # the account year by year: money in and out, what it earned, and the S&P 500 beside it
        "history": history_mod.build(raw, account, prices, today),
        # the desk's figures rebuilt from the records, against Trading 212's own (checks.py)
        "checks": checks_mod.checks(raw, account, prices, today) if not as_of else None,
        "digest": build_digest(raw, news, prices, ratings_log, positions, today, as_of, trades_data, looks),
        "exposure": build_exposure(positions, universe, codes, account),
        # where what is held leans on the rating's four themes: a fact about the holdings, never a signal
        "tilt": rating_mod.tilt(positions["rows"], account.get("total")),
        "costs": build_costs(raw.get("orders"), raw.get("dividends"), raw.get("transactions"), account, positions,
                             growth["investing"], prices),
        "positions": positions,
        "trades": trades_data,
        "plans": planned,
        "dividends": build_dividends(raw.get("dividends"), today),
        "news": build_news(news, positions["rows"], today, prices),
        # what the press has written about each followed company, beside that day's move
        "company_news": company_news,
        "research": build_research(research),
        "closed_trades": build_closed_trades(trades_data["rows"], prices, today, account.get("currency") or "USD"),
        # the user's habits, measured as the papers measured everyone's (habits.py)
        "habits": habits_mod.measure(trades_data["rows"], account.get("invested"), prices, today,
                                     *(history_mod.month_turnover(raw, account, prices, today,
                                                                  habits_mod.turnover_months(today)) or (None, "all"))),
        "paper": build_paper(paper, prices, today),
        # context.add_to attaches the screener's measures, the scoring models, the
        # peer standing, the valuation and the forecast record. It reads only stored
        # files, so a page build still touches no network.
        "companies": companies,
        # the record: the fixed sample's ratings (the fair test), and the user's companies'
        "rating": dict(rating_mod.explained(ratings), exchange_list=rating_mod.exchange_list(listings),
                       buy_list=rating_mod.buy_list(ratings, universe, codes),
                       sample=rating_mod.sample_for_page(ratings, rating_sample),
                       record=rating_mod.record(ratings_log, prices, "sample"),
                       record_yours=rating_mod.record(ratings_log, prices, "yours")),
    }


def template_source():
    """The page's whole source as one text: the markup, its styles and its script."""
    def read(path):
        with open(path) as f:
            return f.read()
    return (read(TEMPLATE).replace("__PAGE_CSS__\n", read(os.path.join(PAGE, PAGE_STYLE)))
            .replace("__PAGE_JS__\n", "".join(read(os.path.join(PAGE, name)) for name in PAGE_SCRIPTS)))


# The page's typefaces (page/fonts/, licences beside them) and the places in the stylesheet they go.
PAGE_FONTS = {"__FONT_ARCHIVO__": "archivo-latin.woff2", "__FONT_IBMPLEXSANS__": "ibmplexsans-latin.woff2"}


def font_uri(name):
    """A typeface kept in page/fonts/, as data the page carries itself, so it asks no one for it.
    One that is missing or cannot be read gives an empty address: the browser goes on to the next
    font in the stack, and the page still opens."""
    try:
        with open(os.path.join(PAGE, "fonts", name), "rb") as f:
            return "data:font/woff2;base64," + base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return "data:,"


def render(data):
    html = template_source()
    for token, name in PAGE_FONTS.items():
        html = html.replace(token, font_uri(name))
    payload = json.dumps(data).replace("</", "<\\/")     # can't close the <script>
    return html.replace("__DATA__", payload)


def load_json(path, default):
    """A stored JSON file, or `default` when it is missing, unreadable, or not the shape
    `default` is (a file edited by hand into a list or a number must not stop the page)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default
    return data if default is None or isinstance(data, type(default)) else default


def paper_book(path):
    """The practice book for the page: the stored one, or what says it cannot be read."""
    import paper as paper_mod
    try:
        return paper_mod.load(path)
    except paper_mod.PaperError as e:
        return {"unreadable": str(e)}


def records(stored):
    """A store keyed by id or ticker, kept to the entries that are records (a mapping):
    one that is not cannot be read, and is left out rather than stopping the page."""
    return {k: v for k, v in (stored or {}).items() if isinstance(v, dict)}


def load_inputs(folder):
    """Every store the page is built from, read from one folder — for today's page and
    for the page as of a past date (asof.apply) alike."""
    raw = load_json(os.path.join(folder, "t212_data.json"), {})
    return {
        "raw": raw,
        "broker": broker_mod.configured() if os.path.realpath(folder) == os.path.realpath(HERE) else None,
        "journal": records(load_json(os.path.join(folder, "journal.json"), {})),
        "news": load_json(os.path.join(folder, "news_data.json"), {}),
        "headlines": headlines_mod.load(os.path.join(folder, "headlines.json")),
        "health": health_mod.load(folder),
        "looks": looks_mod.load(folder),
        "plans": plans_mod.load(folder),
        "rating_sample": rating_mod.load_sample(folder),
        "prices": load_json(os.path.join(folder, "prices.json"), {}),
        "quotes": load_json(os.path.join(folder, "quotes.json"), {}),
        "ratings_log": rating_mod.load_log(os.path.join(folder, "ratings_log.json")),
        "fundamentals": load_json(os.path.join(folder, "fundamentals.json"), {}),
        "earnings": load_json(os.path.join(folder, "earnings_data.json"), {}),
        "summaries": records(load_json(os.path.join(folder, "summaries.json"), {})),
        "briefs": brief_mod.load(folder),
        "paper": paper_book(os.path.join(folder, "paper.json")),
        "analysts": load_json(os.path.join(folder, "analysts_data.json"), {}),
        "research": load_json(os.path.join(folder, "research.json"), {}),
        "coverage": news_mod.load_coverage(os.path.join(folder, "watchlist.json")),
        "theses": thesis_mod.load(os.path.join(folder, "theses.json")),
        "wording": diffs.load(os.path.join(folder, "diffs.json")),
        "universe": universe.load(),
        "listings": universe.load_listings(),
    }


DEMO_DIR = os.path.join(HERE, "demo")


def keep_apart(folder):
    """Point the stores the desk keeps beside its code (the SEC universe and its exchange list, the
    industry codes, the screens, the price ratios, the filers' number map) at this folder, so the
    demo reads the demo's and never the desk's own. Returns what puts them back."""
    places = ((universe, "UNIVERSE_FILE", "universe.json"), (universe, "LISTINGS_FILE", "listings.json"),
              (sectors, "SECTORS_FILE", "sectors.json"), (screen, "SCREEN_FILE", "screen.json"),
              (value, "VALUE_FILE", "value.json"), (news_mod, "CIK_CACHE", ".cik_map.json"))
    before = [(module, name, getattr(module, name)) for module, name, _ in places]
    for module, name, file in places:
        setattr(module, name, os.path.join(folder, file))

    def restore():
        for module, name, path in before:
            setattr(module, name, path)
    return restore


def as_of(folder, day):
    """The page's data as it was at the end of a past day (Phase 11)."""
    import asof
    return compute(today=date.fromisoformat(day), as_of=day, **asof.apply(load_inputs(folder), day))


def main(argv):
    folder = os.path.abspath(argv[0]) if argv else HERE
    if folder == DEMO_DIR:
        keep_apart(folder)
    data = compute(**load_inputs(folder))
    atomic_write_json(os.path.join(folder, "desk_data.json"), data)
    atomic_write(os.path.join(folder, "index.html"), render(data))
    print(f"Built {os.path.join(folder, 'index.html')} "
          f"({data['positions']['count']} positions, {data['trades']['count']} trades)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
