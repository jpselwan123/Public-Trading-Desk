"""The user's trading habits, measured on their own record the way the published studies
measured everyone's (the review of 27 Sep 2026: what drags an individual investor's returns
most is how they trade, and no broker shows it).

  How much you trade    Barber & Odean (2000), "Trading is hazardous to your wealth", Journal
                        of Finance 55: the households that traded most earned least. Turnover
                        as they define it: half the value bought and sold, over the value held.
  Winners sold, losers kept
                        Odean (1998), "Are investors reluctant to realize their losses?",
                        Journal of Finance 53: on each day something is sold, each holding is a
                        gain or a loss; the share of gains sold (PGR) against the share of
                        losses sold (PLR). Investors sold gains far more readily.
  What replaced what you sold
                        Odean (1999), "Do investors trade too much?", American Economic Review
                        89: a sale followed within three weeks by a purchase of another share,
                        and how the share bought did against the one sold over the next year.
                        The shares bought did worse.

Each is the user's own figure with its interval (uncertainty.py), beside what the paper
found; none is a rule, and nothing here trades. Only US lines are priced, so only they are
counted where a price is needed; a buy before a split is counted in the later day's shares
(prices.split_factor), as in the closed-trade record.
"""
from datetime import date, timedelta

import prices as price_store
import uncertainty

# What the papers found, quoted beside the user's own figures (never a limit the desk sets).
PUBLISHED = {
    # Barber & Odean (2000), 66,465 households, 1991-96: the average turned over 75% of its
    # shares a year; those that traded most earned 11.4% a year, the market 17.9%
    "turnover_yearly_average": 0.75, "return_most_active": 0.114, "return_market": 0.179,
    # Odean (1998), 10,000 accounts, 1987-93, the whole year: gains realised at 14.8% of the
    # chances, losses at 9.8%
    "pgr": 0.148, "plr": 0.098,
}
TURNOVER_MONTHS = 12            # turnover over the last twelve whole months, as Barber & Odean's year
REPLACED_WITHIN_DAYS = 21       # Odean (1999): a purchase within three weeks of a sale
AFTER_DAYS = 252                # one year of trading days after each trade (Odean 1999's horizon)


def turnover_months(today):
    """The last TURNOVER_MONTHS whole months, oldest first, as YYYY-MM."""
    y, m, out = today.year, today.month, []
    for _ in range(TURNOVER_MONTHS):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        out.append(f"{y:04d}-{m:02d}")
    return out[::-1]


def turnover(trades, invested, today, monthly=None, lines="all"):
    """Barber & Odean's (2000) turnover over the last TURNOVER_MONTHS whole months, as a year:
    each month's (history.month_turnover, their definition) averaged, times twelve, the unit of
    their 75%. Without the months rebuilt, half of what was bought and sold over today's holdings
    stands in, and the page says so. What was bought and sold, and in how many trades, are the
    record's own."""
    months = turnover_months(today)
    rows = [r for r in trades or [] if (r.get("date") or "")[:7] in months and (r.get("value") or 0) > 0]
    bought = sum(r["value"] for r in rows if r.get("side") == "BUY")
    sold = sum(r["value"] for r in rows if r.get("side") == "SELL")
    yearly, basis = None, None
    each = [monthly[m] for m in months if (monthly or {}).get(m) is not None]
    if each:
        yearly, basis = 12 * sum(each) / len(each), "month" if lines == "all" else "us_month"
    elif invested and invested > 0:
        yearly, basis = (bought + sold) / 2 / invested, "today"
    return {"trades": len(rows), "bought": bought, "sold": sold, "yearly": yearly, "basis": basis,
            "from": months[0], "to": months[-1], "months": TURNOVER_MONTHS}


def _close(prices, ticker, day, read=None):
    """The printed close on `day` or the latest before it, or None. `read` keeps each
    ticker's closes once read, for a loop over many days."""
    if read is not None and ticker not in read:
        read[ticker] = price_store.series(prices, ticker, "c")
    closes = read[ticker] if read is not None else price_store.series(prices, ticker, "c")
    earlier = [d for d in closes if d <= day]
    return closes[max(earlier)] if earlier else None


def disposition(trades, prices):
    """Odean's (1998) count: on each day something was sold, each US holding held that
    morning is a realised gain or loss (sold that day, at a price above or below its average
    purchase price) or a paper one (kept, its close above or below). The average is of every
    purchase still held, a sale leaving it unchanged (until 28 Sep 2026, the first lots bought
    were taken out first, which moved it). The share of gains realised (PGR)
    and of losses (PLR), each with its interval, and their difference with Newcombe's."""
    lots, counts = {}, {"rg": 0, "rl": 0, "pg": 0, "pl": 0}
    by_day, split, closes = {}, price_store.SplitsRead(prices), {}
    for t in sorted(trades or [], key=lambda r: r.get("time") or ""):
        if t.get("us_line") and t.get("date") and t.get("quantity") and t.get("price"):
            by_day.setdefault(t["date"], []).append(t)
    for day in sorted(by_day):
        sold = {t["ticker"]: t["price"] for t in by_day[day] if t["side"] == "SELL"}
        if sold:
            for ticker, queue in lots.items():
                shares = sum(l["qty"] * split.factor(ticker, l["date"], day) for l in queue)
                if shares <= 1e-9:
                    continue
                average = sum(l["qty"] * l["price"] for l in queue) / shares       # cost per share in the day's shares
                price = sold.get(ticker) or _close(prices, ticker, day, closes)
                if price is None or price == average:
                    continue
                kind = ("r" if ticker in sold else "p") + ("g" if price > average else "l")
                counts[kind] += 1
        for t in by_day[day]:                              # then the day's own trades
            queue = lots.setdefault(t["ticker"], [])
            if t["side"] == "BUY":
                queue.append({"qty": t["quantity"], "price": t["price"], "date": day})
                continue
            # a sale leaves the average purchase price as it was (Odean's reference point, and the
            # average Trading 212 shows): every lot keeps the same share of what is left
            shares = sum(l["qty"] * split.factor(t["ticker"], l["date"], day) for l in queue)
            kept = max(0.0, 1 - t["quantity"] / shares) if shares > 1e-9 else 0.0
            for l in queue:
                l["qty"] *= kept
            if kept <= 1e-9:
                queue.clear()
    gains, losses = counts["rg"] + counts["pg"], counts["rl"] + counts["pl"]
    return {"counts": counts,
            "pgr": uncertainty.proportion(counts["rg"], gains),
            "plr": uncertainty.proportion(counts["rl"], losses),
            "difference": uncertainty.difference(counts["rg"], gains, counts["rl"], losses)}


def _after(prices, ticker, day, read=None):
    """The share's return from its first close on or after `day` to AFTER_DAYS trading days
    later, from adjusted closes; None when that day has not come. `read` keeps each ticker's
    closes, in day order, once read."""
    if read is None:
        read = {}
    if ticker not in read:
        series = price_store.series(prices, ticker)
        read[ticker] = (series, sorted(series))
    series, days = read[ticker]
    start = next((i for i, d in enumerate(days) if d >= day), None)
    if start is None or start + AFTER_DAYS >= len(days) or not series[days[start]]:
        return None
    return series[days[start + AFTER_DAYS]] / series[days[start]] - 1


def replaced(trades, prices):
    """Odean's (1999) pairs: each sale of a US share, and the first purchase of another
    within REPLACED_WITHIN_DAYS after it (each purchase answering one sale). For each, the
    share bought's return over the next year less the share sold's; their median with its
    interval against no difference. Only pairs whose year has passed are counted."""
    rows = sorted((t for t in trades or [] if t.get("us_line") and t.get("date")), key=lambda r: r.get("time") or "")
    used, gaps, pending, read = set(), [], 0, {}
    for i, sale in enumerate(rows):
        if sale["side"] != "SELL":
            continue
        last = (date.fromisoformat(sale["date"]) + timedelta(days=REPLACED_WITHIN_DAYS)).isoformat()
        buy = next((b for b in rows[i + 1:] if b["side"] == "BUY" and b["ticker"] != sale["ticker"]
                    and b["date"] <= last and id(b) not in used), None)
        if not buy:
            continue
        used.add(id(buy))
        sold_after, bought_after = (_after(prices, sale["ticker"], sale["date"], read),
                                    _after(prices, buy["ticker"], buy["date"], read))
        if sold_after is None or bought_after is None:
            pending += 1
            continue
        gaps.append(bought_after - sold_after)
    return {"pairs": len(gaps), "pending": pending, "gap": uncertainty.median(gaps, expected=0),
            "within_days": REPLACED_WITHIN_DAYS, "after_days": AFTER_DAYS}


def measure(trades, invested, prices, today, monthly=None, lines="all"):
    """All three, for the page."""
    return {"turnover": turnover(trades, invested, today, monthly, lines), "disposition": disposition(trades, prices),
            "replaced": replaced(trades, prices), "published": PUBLISHED}
