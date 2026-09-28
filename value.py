"""What the market is charging for a company, for the few that survive a screen.

Valuation is the one part of this that needs a market price, and prices are the one
input with a hard budget: Tiingo's free tier allows a few hundred symbols a month.
So nothing here runs over the universe. A screen narrows 5,900 companies down to a
few dozen on filings alone, and only those get priced — which is the whole reason
screen.py was built to work without prices in the first place.

Every ratio is the market capitalisation against a figure from the filings. That
makes each one only as good as the share count behind it, so the count used is
reported with the answer: the cover-page share count where the company filed one,
the weighted average diluted count otherwise, and those are not the same number.

The price is today's; the earnings are not. Filings give a full financial year, so
in September the newest complete year may be nine months old and every ratio here is
price-now over profit-then. The year is printed with the answer. A company that has
just collapsed or doubled its profit will look wrong until it files again.

Nothing here says whether a price is right. A P/E is an observation about what other
people are paying, not a judgement about what you should.

Usage: python3 value.py AAPL MSFT KO
       python3 screen.py graham --price
"""
import bisect, os, statistics, sys
from datetime import date, timedelta

import asof
import prices as price_store
import screen
import sectors
import universe
from env_config import atomic_write_json

HERE = os.path.dirname(os.path.abspath(__file__))
VALUE_FILE = os.path.join(HERE, "value.json")
MAX_PRICED = 60              # a free Tiingo key is a few hundred symbols a month
LOOKBACK_DAYS = 10           # enough to cross a long weekend and find the last close


class ValuationError(Exception):
    pass


def latest_close(ticker, key, fetch=price_store.fetch_prices, today=None, since=None):
    """The most recent close, its date, and the splits since `since` (split_factor's product,
    1 without one). None when the ticker is unknown. Asked from `since` when given, so one
    request finds both. Tiingo's rows carry four fields; until 28 Sep 2026 this read three
    and could not run."""
    start = ((today or date.today()) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    rows = fetch(ticker, min(start, since) if since else start, key)
    if not rows:
        return None, None, 1.0
    split = 1.0
    for row in rows:
        if since and row[0] > since and len(row) > 3 and row[3]:
            split *= row[3]
    return rows[-1][1], rows[-1][0], split


def count_day(row, built=None):
    """The day the share count a market value uses was measured: the cover's own day, as the
    universe keeps it (universe.DATED), or else the end of the year its frame was read for."""
    if screen.at(row, "shares_outstanding"):
        on = screen.at(row, "shares_outstanding" + universe.DATED_SUFFIX)
        if asof.dated(on):
            return on
    built = str(built or "")[:10]
    year = universe.latest_year(date.fromisoformat(built)) if asof.dated(built) else universe.latest_year()
    return f"{year}-12-31"


def splits_since(row, prices, ticker, price_day, built=None):
    """How many of `price_day`'s shares one share counted in the filing became: a split since
    the count, from the split days stored with the closes (prices.split_factor). Until 28 Sep
    2026 none was applied, so a company that split after its last filing (NVIDIA's ten for
    one in June 2024) had its market value, P/E and book to market out by the split."""
    if not price_day:
        return 1.0
    return price_store.split_factor(prices, ticker, count_day(row, built), price_day)


def market_cap(row, price, split=1.0):
    """Price times shares, and which share count that was.

    The cover-page count is the right one and is filed by fewer companies, so the
    weighted average diluted count is the fallback. It is averaged over the year and
    includes dilution, so a market cap built on it is approximate — which is why the
    source travels with the number rather than being buried. `split` restates the count
    in the price's shares (splits_since)."""
    if price is None:
        return None, None
    since = "" if split == 1 else f", restated for a split since ({split:g} for one)"
    outstanding = screen.at(row, "shares_outstanding")
    if outstanding:
        return price * outstanding * split, "shares outstanding on the filing cover" + since
    weighted = screen.at(row, "shares")
    if weighted:
        return price * weighted * split, "weighted average diluted shares (approximate)" + since
    return None, None


# How each valuation figure is shown — declared here, by the module that computes
# them, in the same form as screen.MEASURE_DISPLAY and formatted by the same function.
# share_count_basis is words, not a figure, so it has no entry.
VALUE_DISPLAY = {
    "price":                  {"kind": "per_share", "label": "Price"},
    "market_cap":             {"kind": "money",     "label": "Market value"},
    "enterprise_value":       {"kind": "money",     "label": "Enterprise value"},
    "price_to_earnings":      {"kind": "ratio",     "label": "Price to earnings", "dp": 1},
    "price_to_book":          {"kind": "ratio",     "label": "Price to book", "dp": 1},
    "price_to_sales":         {"kind": "ratio",     "label": "Price to sales", "dp": 1},
    "ev_to_operating_income": {"kind": "ratio",     "label": "EV to operating income", "dp": 1},
    "dividend_yield":         {"kind": "percent",   "label": "Dividend yield", "dp": 2},
    "earnings_yield":         {"kind": "percent",   "label": "Earnings yield", "dp": 2},
}
TEXT_FIELDS = ("share_count_basis", "why", "withheld")      # words, not figures


# ---- the price against the company's own history ----------------------------------
# The desk's choices, both labelled on the page: five years is long enough for a run of
# results and short enough to be the company it is now; two years of months is the
# least that says anything about a range.
OWN_HISTORY_YEARS = 5
OWN_HISTORY_MIN_MONTHS = 24
# own_history's measure: the printed price over the twelve months' earnings per share as
# filed, the same way in every month. Not price_to_earnings, which divides the market
# value by the latest full year's profit: a different figure, so a different name.
OWN_HISTORY_DISPLAY = {
    "price_to_eps_12m": {"kind": "ratio", "label": "Price to earnings per share (last 12 months)", "dp": 1},
}


def _month_ends(start, end):
    """The last day of each month from `start` to `end`, and `end` itself last."""
    out, y, m = [], start.year, start.month
    while True:
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        last = nxt - timedelta(days=1)
        if last >= end:
            break
        if last >= start:
            out.append(last)
        y, m = nxt.year, nxt.month
    return out


def own_history(stored, closes, today, splits=None):
    """Today's price to earnings against the company's own over the last five years.
    Each month end: that day's close as printed, over the earnings per share for the
    twelve months as filed by then (asof.company) — never a figure filed later — each
    quarter restated in that day's shares (`splits`, prices.splits), so a split cannot
    bend the line, nor the quarters before it mix with those after. A month whose
    earnings were not positive has no price to earnings."""
    if not stored or not closes:
        return None
    facts = sorted({r.get("filed") for rows in (stored.get("facts") or {}).values() for r in rows or []
                    if asof.dated(r.get("filed"))})
    days = sorted(closes)
    known, points = {}, []

    def eps_on(day):
        filed = [f for f in facts if f <= day]
        key = filed[-1] if filed else None
        if key not in known:                       # in the shares of the last filing's day...
            known[key] = asof.company(stored, key, splits).get("eps") if key else None
        eps = known[key]                           # ...and in `day`'s, after any split since
        return eps / price_store.factor_between(splits, key, day) if eps and splits else eps
    start = date(today.year - OWN_HISTORY_YEARS, today.month, min(today.day, 28))
    for end in _month_ends(start, today):
        day = end.isoformat()
        i = bisect.bisect_right(days, day)            # decades of closes: found, not scanned
        eps = eps_on(day)
        if i and eps and eps > 0 and days[i - 1] >= start.isoformat():
            points.append({"month": day[:7], "pe": closes[days[i - 1]] / eps})
    eps_now, last = eps_on(today.isoformat()), days[-1]
    if len(points) < OWN_HISTORY_MIN_MONTHS:
        return {"why_not": f"fewer than {OWN_HISTORY_MIN_MONTHS} months in the last {OWN_HISTORY_YEARS} years "
                           f"have both a stored close and positive earnings"}
    if not eps_now or eps_now <= 0:
        return {"why_not": "the last twelve months' earnings are not positive, so there is no price to earnings today"}
    now = closes[last] / eps_now
    values = sorted(p["pe"] for p in points)
    return {"now": now, "as_of": last, "low": values[0], "high": values[-1],
            "median": statistics.median(values),
            "place": sectors.percentile(now, values), "months": len(points), "years": OWN_HISTORY_YEARS,
            "points": points}


def format_value(name, value):
    return screen.format_with(VALUE_DISPLAY.get(name), value)


def _why_blank(price, cap, net_income, equity, revenue, operating, dividends, enterprise_missing=False):
    """Why each ratio is blank, in words the card prints beside the dash — a dash with
    no reason reads as missing data, which is a different and less useful thing than
    "this cannot be computed, and here is why" (Q2)."""
    if price is None:
        return {name: "no price stored yet" for name in VALUE_DISPLAY}, []
    if cap is None:
        return {name: "no share count filed" for name in FROM_MARKET_CAP}, []
    # A ratio on a zero or negative denominator is withheld — the figures exist and the
    # desk declines the ratio; the rest are figures the company did not file.
    why, withheld = {}, []
    if net_income is None:
        why["price_to_earnings"] = why["earnings_yield"] = "no net income filed"
    elif net_income <= 0:
        why["price_to_earnings"] = "a loss: there is no P/E to state"
        withheld.append("price_to_earnings")
    if equity is None:
        why["price_to_book"] = "no equity filed"
    elif equity <= 0:
        why["price_to_book"] = "negative book equity"
        withheld.append("price_to_book")
    if revenue is None:
        why["price_to_sales"] = "no revenue filed"
    elif revenue <= 0:
        why["price_to_sales"] = "no revenue"
        withheld.append("price_to_sales")
    if enterprise_missing:
        why["enterprise_value"] = why["ev_to_operating_income"] = "debt or cash not filed"
    elif operating is not None and operating <= 0:
        why["ev_to_operating_income"] = "an operating loss"
        withheld.append("ev_to_operating_income")
    if not dividends:
        why["dividend_yield"] = "no dividend paid"
    return why, withheld


def measures(row, price, split=1.0):
    """Valuation ratios. None wherever the filing or the price will not support one.

    A ratio against a negative denominator is dropped rather than shown: a P/E of
    -8 for a loss-making company is not a cheap company, and sorting or screening on
    it silently puts the worst businesses at the top."""
    cap, basis = market_cap(row, price, split)
    net_income = screen.at(row, "net_income")
    equity = screen.at(row, "equity")
    revenue = screen.at(row, "revenue")
    operating = screen.at(row, "operating_income")
    debt, cash = screen.at(row, "debt"), screen.at(row, "cash")
    # Both figures or no enterprise value: a debt figure that was not filed counted as
    # zero, which understates the value of any company whose debt is not in the
    # frames data — a third of filers have one (S-08).
    enterprise = (None if cap is None or debt is None or cash is None
                  else cap + debt - cash)
    dividends = abs(screen.at(row, "dividends_paid") or 0.0)
    why, withheld = _why_blank(price, cap, net_income, equity, revenue, operating, dividends,
                               enterprise_missing=cap is not None and enterprise is None)
    return {
        "why": why,
        "withheld": withheld,
        "price": price,
        "market_cap": cap,
        "share_count_basis": basis,
        "enterprise_value": enterprise,
        "price_to_earnings": screen.ratio(cap, net_income if (net_income or 0) > 0 else None),
        "price_to_book": screen.ratio(cap, equity if (equity or 0) > 0 else None),
        "price_to_sales": screen.ratio(cap, revenue if (revenue or 0) > 0 else None),
        "ev_to_operating_income": screen.ratio(enterprise,
                                               operating if (operating or 0) > 0 else None),
        "dividend_yield": screen.ratio(dividends or None, cap),
        "earnings_yield": screen.ratio(net_income, cap),
    }


def for_tickers(tickers, store=None, key=None, fetch=price_store.fetch_prices,
                limit=MAX_PRICED, today=None):
    """Price a short list and value it. Refuses a long one rather than silently
    spending a month's price budget on a screen that was too broad."""
    tickers = [str(t).upper() for t in tickers]
    if len(tickers) > limit:
        raise ValuationError(
            f"{len(tickers)} companies is more than the {limit} this will price in one "
            "go. Tighten the screen, or raise --limit if your Tiingo plan allows it.")
    store = store or universe.load()
    companies = store.get("companies") or {}
    key = key or price_store.api_key()
    out = {}
    for ticker in tickers:
        row = companies.get(ticker)
        if not row:
            out[ticker] = {"error": "not in the stored universe"}
            continue
        fault = screen.scale_fault(row)
        if fault:
            out[ticker] = {"error": fault["note"]}
            continue
        close, day, split = latest_close(ticker, key, fetch, today, since=count_day(row, store.get("built")))
        if close is None:
            out[ticker] = {"error": "no recent price from Tiingo"}
            continue
        values = value_company(row, close, split)
        values["as_of"] = day
        values["name"] = row.get("name")
        out[ticker] = values
    return out


# A market capitalisation multiplies a share count from the filings by a price from
# the market, and that is only right when both describe the same instrument. For a
# company listed through depositary shares they do not: BeOne Medicines files 1.44bn
# ordinary shares and trades as ADS worth roughly thirteen of them, so the product
# comes out around thirteen times the real figure and its P/E reads 1,850.
#
# The only independent market value in this data comes from the filer itself: the
# public float on the 10-K cover, what the company said its publicly held shares were
# worth on the last business day of its second fiscal quarter. Float is a subset of
# market value, so a market capitalisation below it is impossible, and one many times
# above it means either an extraordinary price move or the wrong share basis.
#
# The multiple below is arithmetic, not research: an exchange-listed company keeps a
# meaningful fraction of its shares public, and prices rarely move tenfold in the year
# or so since the float was filed. Together those make a larger gap a question about
# the data rather than a fact about the market.
FLOAT_GAP = 10.0


def float_check(row, cap):
    """Compare a computed market capitalisation with the company's own filed float."""
    reported, years_old = screen.latest_float(row)
    if not reported or not cap:
        return None
    ratio = cap / reported
    if ratio > FLOAT_GAP:
        return {"public_float": reported, "years_old": years_old, "ratio": ratio,
                "plausible": False,
                "note": f"the computed market value is {ratio:,.0f} times the public "
                        f"float this company filed with the SEC. Float is part of "
                        f"market value, not a multiple of it, so the share basis is "
                        f"probably wrong — a listing through depositary shares files "
                        f"ordinary shares while trading in units worth several of "
                        f"them, and SEC data does not give the ratio. The market "
                        f"value and every ratio built on it are withheld."}
    if ratio < 1.0:
        return {"public_float": reported, "years_old": years_old, "ratio": ratio,
                "plausible": True,
                "note": "the computed market value is below the filed public float, "
                        "which normally means the share price has fallen since the "
                        "float was reported."}
    return {"public_float": reported, "years_old": years_old, "ratio": ratio,
            "plausible": True, "note": ""}


# Every figure that multiplies the share count by the price. When the share basis is
# known to be wrong, all of these are wrong by the same unknown multiple.
FROM_MARKET_CAP = ("market_cap", "enterprise_value", "price_to_earnings", "price_to_book",
                   "price_to_sales", "ev_to_operating_income", "dividend_yield",
                   "earnings_yield")


def _unchecked(values):
    """Why no check ran — which must not read like one that passed."""
    if values.get("market_cap") is None:
        note = "no share count was filed, so there is no market value to check"
    else:
        note = ("this company files no usable public float — none, or only ones in the "
                "wrong unit — so the share basis could not be checked against anything "
                "it reported itself")
    return {"plausible": None, "public_float": None, "note": note}


def value_company(row, price, split=1.0):
    """One company's valuation at one price: the ratios, the share-basis check, the
    year the figures came from and Graham's two limits.

    The one place this is assembled; the company card and the priced screen both call
    it. A failed share-basis check withholds every figure built on the market value
    rather than printing it beside a warning: BeOne's P/E read 1,850, and a number
    known to be wrong would still be sorted, compared and remembered."""
    values = measures(row, price, split)
    check = float_check(row, values["market_cap"])
    values["float_check"] = check or _unchecked(values)
    if check and not check["plausible"]:
        for name in FROM_MARKET_CAP:
            values[name] = None
            values["why"][name] = "withheld: the share count and the price describe different shares"
            if name not in values["withheld"]:
                values["withheld"].append(name)
    values["figures_from"] = universe.periods("flow", 1)[0]
    values["graham"] = graham_valuation(values)
    return values


# Graham's two valuation limits, which screen.py cannot apply without a price.
# Chapter 14 of the 1973 revision: "current price should not be more than 15 times
# average earnings" and "not more than 1½ times the book value last reported".
GRAHAM_PE, GRAHAM_PB = 15.0, 1.5


def graham_valuation(values):
    """The two criteria screen.py lists as omitted, now that a price exists."""
    pe, pb = values.get("price_to_earnings"), values.get("price_to_book")
    return {
        "price_to_earnings": {"value": pe, "limit": GRAHAM_PE,
                              "passes": None if pe is None else pe <= GRAHAM_PE},
        "price_to_book": {"value": pb, "limit": GRAHAM_PB,
                          "passes": None if pb is None else pb <= GRAHAM_PB},
        "source": "Graham, 'The Intelligent Investor' (1973), chapter 14",
    }


def main(argv):
    tickers = [a for a in argv if not a.startswith("--")]
    if not tickers:
        print("Usage: python3 value.py TICKER [TICKER …]")
        return 1
    try:
        out = for_tickers(tickers)
    except (ValuationError, price_store.PriceError) as e:
        print(f"value: {e}")
        return 1
    atomic_write_json(VALUE_FILE, out)
    for ticker, values in out.items():
        if values.get("error"):
            print(f"{ticker}: {values['error']}")
            continue
        print(f"\n{ticker} — {values['name']}   close {format_value('price', values['price'])} "
              f"on {values['as_of']}")
        print(f"   filings from {values['figures_from']} — the price is today's, "
              f"the profit is that year's")
        print(f"   {VALUE_DISPLAY['market_cap']['label']:<24}"
              f"{format_value('market_cap', values['market_cap']):>10}   "
              f"({values['share_count_basis']})")
        for name in ("price_to_earnings", "price_to_book", "price_to_sales",
                     "ev_to_operating_income", "dividend_yield"):
            print(f"   {VALUE_DISPLAY[name]['label']:<24}{format_value(name, values[name]):>10}")
        g = values["graham"]
        marks = {True: "within", False: "above", None: "not computable"}
        print(f"   Graham: P/E {marks[g['price_to_earnings']['passes']]} 15, "
              f"P/B {marks[g['price_to_book']['passes']]} 1.5")
        check = values.get("float_check")
        if check and not check["plausible"]:
            print(f"\n   CHECK THE SHARE BASIS: {check['note']}")
        elif check and check["note"]:
            print(f"   ({check['note']})")
    print("\nWhat the market is charging, against what the filings report.\n"
          "Neither figure says whether that price is worth paying.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
