"""The account year by year (the owner, 28 Sep 2026: "we can add an extra section and name it
history, where I can check my returns per year, that way I can better track everything").

Trading 212 gives the account's value today, and every movement of money and shares since it
opened, but not its value on any past day. So each year's end is rebuilt from the record: the
shares held that day (each fill, a split since counted in the later day's shares), priced at
the year's last close, and the cash, every deposit, withdrawal, purchase, sale, dividend,
interest payment and fee up to that day. The same rebuilding carried to today is set beside
Trading 212's own total (`check`): when the two differ by more than CHECK_TOLERANCE of the
account, something that moved money or shares is not in the history Trading 212 gives, and no
rebuilt value is used.

For each calendar year:
  put in, taken out      deposits and withdrawals (build_desk.external_flows)
  earned                 the value at the year's end, less the value at its start and what was
                         put in net: what investing did, fees, taxes and currency moves in it
  return                 money-weighted over the year (build_desk.money_weighted_return, the
                         Overview's), the start's value counted as put in on its first day; a
                         part year is its own period, never annualised (GIPS)
  the S&P 500            the start's value and each deposit and withdrawal on its own day put
                         into or taken out of the S&P 500 (build_desk.same_money_in_market, as
                         the Overview compares), valued at the year's end, and its return the same
                         way: what the same money would have done, with the same timing
  dividends, interest, fees, closed gain, trades     as the record has them, each on its day

Only US shares have daily closes (Tiingo), so a year that ended with a line listed elsewhere
held has no rebuilt value, and says why. The current year ends today, at Trading 212's total.
"""
import bisect
import statistics
from datetime import date, timedelta

import broker
import prices as price_store
import uncertainty

# The rebuilt account today may differ from Trading 212's total by this share of it and still
# be used (the desk's choice): fractional shares rounded in the record and a day's price
# between the last close and Trading 212's own price move it a little; a movement missing from
# the history moves it by the whole amount.
CHECK_TOLERANCE = 0.01
# A year's last close must fall this close to its end, or the share was not trading then
# (the rating's month-end rule: rating.MONTH_END_SLACK).
CLOSE_SLACK_DAYS = 7
# Fewer shares than this left of a line is rounding in the record, not a holding.
HELD_AT_LEAST = 1e-6


def _fills(orders):
    """[(day, full ticker, signed quantity, cash moved, fees, closed gain or None)] for each fill,
    oldest first: a purchase moves its net value out of the cash, a sale in."""
    import build_desk
    out = []
    for item in orders or []:
        order, fill = item.get("order") or {}, item.get("fill") or {}
        if not fill or fill.get("type", "TRADE") != "TRADE":
            continue
        w = fill.get("walletImpact") or {}
        ticker = order.get("ticker") or (order.get("instrument") or {}).get("ticker") or ""
        side = order.get("side") or ("SELL" if build_desk.num(fill.get("quantity")) < 0 else "BUY")
        qty, value = abs(build_desk.num(fill.get("quantity"))), abs(build_desk.num(w.get("netValue")))
        day = build_desk.day_of(fill.get("filledAt") or order.get("createdAt"))
        if not day or not ticker:
            continue
        sell = side == "SELL"
        out.append((day, ticker, -qty if sell else qty, value if sell else -value,
                    sum(abs(build_desk.num(t.get("quantity"))) for t in (w.get("taxes") or [])),
                    build_desk.num(w.get("realisedProfitLoss")) if sell and w.get("realisedProfitLoss") is not None else None))
    return sorted(out, key=lambda f: f[0])


def _cash_moves(transactions, dividends, fills):
    """[(day, amount)] for every movement of the account's cash, and the kinds of transaction
    the desk does not know, which are counted as Trading 212 gives them and named by the check."""
    import build_desk
    moves, unknown = [], set()
    for t in transactions or []:
        kind, amount, day = t.get("type"), build_desk.num(t.get("amount")), build_desk.day_of(t.get("dateTime"))
        if not day:
            continue
        if kind == "DEPOSIT":
            moves.append((day, abs(amount)))
        elif kind == "WITHDRAW":
            moves.append((day, -abs(amount)))
        elif kind == "FEE":
            moves.append((day, -abs(amount)))
        elif kind in ("TRANSFER", "ADJUSTMENT") + build_desk.INTEREST_TYPES:   # ADJUSTMENT: broker.CASH_KINDS
            moves.append((day, amount))
        else:
            unknown.add(str(kind))
            moves.append((day, amount))
    for d in dividends or []:
        day = build_desk.day_of(d.get("paidOn"))
        if day:
            moves.append((day, build_desk.num(d.get("amount"))))
    moves.extend((f[0], f[3]) for f in fills)
    return sorted(moves), sorted(unknown)


def _held(fills, through, splits):
    """{full ticker: shares held at the end of `through`}; a US line's earlier fills counted in
    that day's shares (prices.split_factor)."""
    held = {}
    for day, ticker, qty, *_ in fills:
        if day > through:
            break
        if ticker.endswith("_US_EQ"):
            qty *= splits.factor(_short(ticker), day, through)
        held[ticker] = held.get(ticker, 0.0) + qty
    return {t: q for t, q in held.items() if abs(q) > HELD_AT_LEAST}


def _short(ticker):
    import build_desk
    return build_desk.short_ticker(ticker)


class _Closes:
    """Each line's daily closes, read once and searched by day: the close on or before a day.
    A curve of weekly values asks for the same few lines' closes hundreds of times."""

    def __init__(self, prices):
        self.prices, self.read = prices, {}

    def on_or_before(self, short, day):
        """(the day, its close), or (None, None) when the line has no close on or before `day`."""
        if short not in self.read:
            closes = price_store.series(self.prices, short, "c")
            self.read[short] = (sorted(closes), closes)
        days, closes = self.read[short]
        i = bisect.bisect_right(days, day)
        return (days[i - 1], closes[days[i - 1]]) if i else (None, None)


def _value_on(day, fills, moves, prices, splits, fx, closes=None):
    """The account rebuilt at the close of `day`: (value, None), or (None, why) when a line held
    that day has no close the desk can use."""
    held, why = _holdings_on(day, fills, prices, splits, fx, closes)
    return (None, why) if held is None else (sum(a for d, a in moves if d <= day) + held, None)


def _holdings_on(day, fills, prices, splits, fx, closes=None):
    """The shares held at the close of `day`, at that close, in the account's currency: (value,
    None), or (None, why) when a line held has no close the desk can use."""
    import build_desk
    total = 0.0
    earliest = (date.fromisoformat(day) - timedelta(days=CLOSE_SLACK_DAYS)).isoformat()
    for ticker, qty in sorted(_held(fills, day, splits).items()):
        short = _short(ticker)
        if not ticker.endswith("_US_EQ"):
            return None, f"{short} was held, and the desk has daily closes only for US shares"
        on, close = (closes or _Closes(prices)).on_or_before(short, day)
        if not on or on < earliest:
            return None, f"no close is stored for {short} at the end of {day[:4]}"
        rate = 1.0
        if fx is not None:
            rate = build_desk._on_or_before(fx, on)
            if not rate:
                return None, f"no exchange rate is stored for {on}"
        total += qty * close / rate
    return total, None


def month_turnover(raw, account, prices, today, months):
    """(month_turnover's months, "all"), or over the US lines alone, (months, "us"), when a line
    listed elsewhere was held and has no daily closes: Barber & Odean's households held US
    common stocks, and a line the desk cannot price has no month-start value. None as below."""
    every = _month_turnover(raw, account, prices, today, months, us_only=False)
    if every is not None:
        return every, "all"
    us = _month_turnover(raw, account, prices, today, months, us_only=True)
    return (us, "us") if us is not None else None


def _month_turnover(raw, account, prices, today, months, us_only):
    """{YYYY-MM: that month's turnover} for `months`, as Barber & Odean (2000, section I.B)
    measure it: half the sales turnover plus half the purchase turnover, each over the value of
    the shares held at the start of month t, at that day's prices. Sales turnover: the shares
    sold during t that were held at its start. Purchase turnover: the shares bought during t-1
    that are held at its start. So each is at most the whole holding, and a month is at most
    100%. A month that began with nothing held has no turnover.
    None when the rebuild does not tie to Trading 212's total today, or a month's holdings
    cannot be priced (a line with no daily closes).

    Until 28 Sep 2026 each month's purchases were set over the holdings before them, so money put
    in and invested in a small account read as many times its turnover."""
    raw = raw or {}
    fills = _fills(raw.get("orders"))
    moves, unknown = _cash_moves(raw.get("transactions"), raw.get("dividends"), fills)
    splits = price_store.SplitsRead(prices)
    currency = account.get("currency") or "USD"
    fx = price_store.fx_rates(prices, currency) if currency != "USD" else None
    checked = check(fills, moves, unknown, raw.get("positions"), account, splits, today,
                    broker.name_of(raw))
    if not checked or not checked["ok"]:
        return None
    out = {}
    if us_only:
        fills = [f for f in fills if f[1].endswith("_US_EQ")]
    for month in months:
        first = date(int(month[:4]), int(month[5:7]), 1)
        eve = (first - timedelta(days=1)).isoformat()
        before = (first.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()[:7]
        held = _held(fills, eve, splits)
        each = {}
        for ticker in held:
            value, why = _holdings_on(eve, [f for f in fills if f[1] == ticker], prices, splits, fx)
            if value is None:
                return None
            each[ticker] = value / held[ticker]                  # a share's price at the start, in the account's money
        worth = sum(held[t] * each[t] for t in held)
        if worth <= 0:
            continue
        sold, bought = {}, {}
        for day, ticker, qty, *_ in fills:
            if ticker not in held:
                continue
            us = ticker.endswith("_US_EQ")
            if qty < 0 and day[:7] == month:                     # sold in t, in the start's shares
                sold[ticker] = sold.get(ticker, 0.0) - qty / (splits.factor(_short(ticker), eve, day) if us else 1.0)
            elif qty > 0 and day[:7] == before:                  # bought in t-1, in the start's shares
                bought[ticker] = bought.get(ticker, 0.0) + qty * (splits.factor(_short(ticker), day, eve) if us else 1.0)
        sales = sum(min(q, held[t]) * each[t] for t, q in sold.items()) / worth
        purchases = sum(min(q, held[t]) * each[t] for t, q in bought.items()) / worth
        out[month] = (sales + purchases) / 2
    return out


def check(fills, moves, unknown, positions, account, splits, today, source="Trading 212"):
    """The record rebuilt to today beside Trading 212's total: the shares held now at Trading 212's
    own prices, and the cash. {"rebuilt", "actual", "difference", "ok", "why"}."""
    import build_desk
    actual = account.get("total")
    if not actual:
        return None
    price = {}
    for p in positions or []:
        ticker = (p.get("instrument") or {}).get("ticker") or p.get("ticker")
        qty, value = build_desk.num(p.get("quantity")), build_desk.num((p.get("walletImpact") or {}).get("currentValue"))
        if ticker and qty:
            price[ticker] = value / qty
    rebuilt = sum(a for _, a in moves)
    missing = []
    for ticker, qty in _held(fills, today.isoformat(), splits).items():
        if ticker in price:
            rebuilt += qty * price[ticker]
        else:
            missing.append(_short(ticker))
    difference = rebuilt - actual
    ok = abs(difference) <= CHECK_TOLERANCE * abs(actual) and not missing
    why = None
    if not ok:
        why = (f"rebuilt from the history {source} gives, the account today comes to {rebuilt:,.2f}, "
               f"against its total of {actual:,.2f}")
        if missing:
            why += f"; the history holds shares of {', '.join(sorted(missing))} that {source} no longer lists"
        if unknown:
            why += f"; it has movements of a kind the desk does not know ({', '.join(unknown)})"
    return {"rebuilt": rebuilt, "actual": actual, "difference": difference, "ok": ok, "why": why,
            "tolerance": CHECK_TOLERANCE}


CURVE_STEP_DAYS = 7          # one point a week: the shape of the account, light enough to draw
CURVE_MOST_SKIPPED = 0.2     # weeks left out for want of a close, at most this share (the desk's choice); more is no line


def curve(flows, fills, moves, prices, splits, fx, currency, today, total, checked):
    """The account's value every week from the first deposit to today, beside what the same money
    would be worth in the S&P 500 (build_desk.same_money_in_market, valued on each of those days)
    and what has been put in net. Each week is rebuilt as a year's end is (`_value_on`), and only
    while the rebuild ties to Trading 212's total (`check`); the last point is Trading 212's own.
    {"days", "account", "market", "net", "currency", "skipped"}, or {"why": ...} when it cannot be drawn."""
    import build_desk
    if not checked or not checked["ok"]:
        return {"why": (checked or {}).get("why") or "the account's value today is not known, so the weeks cannot be checked"}
    if not total:
        return {"why": "the account's value is not known for this day"}
    closes = _Closes(prices)
    last, day, days = today.isoformat(), date.fromisoformat(flows[0][0]), []
    while day.isoformat() < last:
        days.append(day.isoformat())
        day += timedelta(days=CURVE_STEP_DAYS)
    days.append(last)
    out = {"days": [], "account": [], "market": [], "net": [], "currency": currency, "skipped": 0}
    missing = None
    for day in days:
        if day == last:
            value = total
        else:
            value, why = _value_on(day, fills, moves, prices, splits, fx, closes)
            if value is None:                    # a week a held line has no close near: left out, its neighbours joined
                out["skipped"] += 1
                missing = missing or why
                continue
        upto = [(d, a) for d, a in flows if d <= day]
        market, _, _ = build_desk.same_money_in_market(upto, prices, currency, day)
        out["days"].append(day)
        out["account"].append(round(value, 2))
        out["market"].append(None if market is None else round(market, 2))
        out["net"].append(round(sum(a for _, a in upto), 2))
    if out["skipped"] > CURVE_MOST_SKIPPED * len(days):        # too many gaps to be a line: say why, draw nothing
        return {"why": missing}
    return out


# ---- how rough the ride was, from the weekly curve --------------------------------------------
# Plain descriptive figures, no threshold and no verdict. A week's return is Modified Dietz's (Bank
# Administration Institute 1968; a method GIPS allows): the change in value less the money put in, over
# the opening value plus half of what was put in, since a deposit lands on some day of the week and
# half is the average. It is applied to the account and to the S&P 500 with the same deposits alike.
RISK_MIN_WEEKS = 52        # weekly returns needed before any of it is shown (the desk's choice: a year)
RISK_FLOW_WEIGHT = 0.5     # how much of a week's deposits counts as having been in the account all week (Dietz: the average)
RISK_MAX_FLOW = 0.5        # a week whose net deposits exceed this share of its opening value is left out of
                           # the swing and the beta, where the half-week assumption would matter most (the desk's choice)
RISK_WEEKS_A_YEAR = 52     # a weekly swing is made a year's by the square root of the weeks in one (the usual convention)


def _dietz(v0, v1, flow):
    """One week's return with the deposits taken out, or None when there was nothing to earn on."""
    base = v0 + RISK_FLOW_WEIGHT * flow
    return (v1 - v0 - flow) / base if base > 0 else None


def _swing(returns):
    """The spread of the weekly returns made a year's: their sample standard deviation times the square root of
    the weeks in a year."""
    return statistics.stdev(returns) * RISK_WEEKS_A_YEAR ** 0.5


def _worst_fall(days, returns):
    """The deepest fall from a high to a later low in the chain of the weekly returns (return i ends on
    `days[i + 1]`; a week with none counts as no change), with the day of the high, of the low and of the
    first return to that high: {"depth", "peak", "trough", "back"}. Weekly closes only: a fall inside a
    week is not seen."""
    levels = [1.0]
    for r in returns:
        levels.append(levels[-1] * (1 + (r or 0.0)))
    high = 0                                    # index of the highest level so far
    worst, at = 0.0, (0, 0)
    for i, level in enumerate(levels):
        if level >= levels[high]:
            high = i
        elif 1 - level / levels[high] > worst:
            worst, at = 1 - level / levels[high], (high, i)
    back = next((days[j] for j in range(at[1] + 1, len(levels)) if levels[j] >= levels[at[0]]), None) if worst else None
    return {"depth": worst, "peak": days[at[0]], "trough": days[at[1]], "back": back}


def risk(curve):
    """The swing, the worst fall and the beta of the account beside the S&P 500 with the same deposits, over the
    weeks of `curve`. {"weeks", "since", "until", "swing": {account, market}, "fall": {account, market},
    "beta": {slope, low, high, explained, ...}, "flow_weight", "max_flow"}, or {"why": ...} when the weeks are too few or the curve is withheld."""
    if not curve or "why" in curve:
        return {"why": (curve or {}).get("why") or "the account's weeks are not known"}
    days, accounts, markets, net = curve["days"], curve["account"], curve["market"], curve["net"]
    a_returns, m_returns, kept = [], [], []
    for i in range(1, len(days)):
        flow = net[i] - net[i - 1]
        a = _dietz(accounts[i - 1], accounts[i], flow)
        m = None if markets[i - 1] is None or markets[i] is None else _dietz(markets[i - 1], markets[i], flow)
        a_returns.append(a)
        m_returns.append(m)
        whole_week = (date.fromisoformat(days[i]) - date.fromisoformat(days[i - 1])).days == CURVE_STEP_DAYS
        small = abs(flow) <= RISK_MAX_FLOW * accounts[i - 1]
        if a is not None and m is not None and whole_week and small:
            kept.append((a, m))
    if not any(m is not None for m in markets):
        return {"why": "the S&P 500's closes are not stored for these weeks, so the account cannot be set against it"}
    if len(kept) < RISK_MIN_WEEKS:
        known = "no whole week is" if not kept else f"only {len(kept)} whole week{'' if len(kept) == 1 else 's'} {'is' if len(kept) == 1 else 'are'}"
        return {"why": f"{known} known, and it takes {RISK_MIN_WEEKS} (a year) to say anything about a swing"}
    fit = uncertainty.slope([m for _, m in kept], [a for a, _ in kept])
    if fit is None:
        return {"why": "the S&P 500 did not move in these weeks, so the account cannot be set against it"}
    return {"weeks": len(kept), "since": days[0], "until": days[-1],
            "swing": {"account": _swing([a for a, _ in kept]), "market": _swing([m for _, m in kept])},
            "fall": {"account": _worst_fall(days, a_returns), "market": _worst_fall(days, m_returns)},
            "beta": fit, "flow_weight": RISK_FLOW_WEIGHT, "max_flow": RISK_MAX_FLOW}


def build(raw, account, prices, today):
    """The years, oldest first, the totals and the check. None with no money ever put in."""
    import build_desk
    raw = raw or {}
    flows = build_desk.external_flows(raw.get("transactions"))
    if not flows:
        return None
    fills = _fills(raw.get("orders"))
    moves, unknown = _cash_moves(raw.get("transactions"), raw.get("dividends"), fills)
    splits = price_store.SplitsRead(prices)
    currency = account.get("currency") or "USD"
    fx = price_store.fx_rates(prices, currency) if currency != "USD" else None
    checked = check(fills, moves, unknown, raw.get("positions"), account, splits, today,
                    broker.name_of(raw))
    first = flows[0][0]
    years, value_start = [], 0.0
    known_start, why_start = True, None
    for year in range(int(first[:4]), today.year + 1):
        start = first if year == int(first[:4]) else f"{year - 1}-12-31"
        current = year == today.year
        end = today.isoformat() if current else f"{year}-12-31"
        in_year = [(d, a) for d, a in flows if (d >= start if start == first else d > start) and d <= end]
        row = {"year": year, "start": start, "end": end, "part": start != f"{year - 1}-12-31" or current,
               "current": current,
               "deposited": sum(a for _, a in in_year if a > 0), "withdrawn": -sum(a for _, a in in_year if a < 0),
               "dividends": sum(build_desk.num(d.get("amount")) for d in raw.get("dividends") or []
                                if build_desk.day_of(d.get("paidOn"))[:4] == str(year)),
               "interest": sum(build_desk.num(t.get("amount")) for t in raw.get("transactions") or []
                               if t.get("type") in build_desk.INTEREST_TYPES
                               and build_desk.day_of(t.get("dateTime"))[:4] == str(year)),
               "fees": sum(f[4] for f in fills if f[0][:4] == str(year)),
               "closed_gain": sum(f[5] for f in fills if f[0][:4] == str(year) and f[5] is not None),
               "trades": sum(1 for f in fills if f[0][:4] == str(year)),
               "bought": -sum(f[3] for f in fills if f[0][:4] == str(year) and f[3] < 0),
               "sold": sum(f[3] for f in fills if f[0][:4] == str(year) and f[3] > 0), "why": None}
        # the year's end: today's is Trading 212's own; an earlier one is rebuilt, if the rebuild holds
        if current:
            value_end, why_end = (account.get("total"), None) if account.get("total") else (
                None, "the account's value is not known for this day")
        elif not checked:
            value_end, why_end = None, "the account's value today is not known, so the rebuilt ones cannot be checked"
        elif not checked["ok"]:
            value_end, why_end = None, checked["why"]
        else:
            value_end, why_end = _value_on(end, fills, moves, prices, splits, fx)
        row["value_end"] = value_end
        row["value_start"] = value_start if known_start else None
        why = why_start if not known_start else why_end
        if value_end is not None and known_start:
            net = row["deposited"] - row["withdrawn"]
            row["earned"] = value_end - value_start - net
            money = ([(start, value_start)] if value_start else []) + in_year
            mwr = build_desk.money_weighted_return(money, value_end, end)
            row["return"] = mwr["period"] if mwr else None
            market, _, why_market = build_desk.same_money_in_market(
                in_year, prices, currency, end, opening=(start, value_start) if value_start else None)
            if market is not None:
                m = build_desk.money_weighted_return(money, market, end)
                row["market"] = {"value": market, "return": m["period"] if m else None,
                                 "difference": value_end - market}
            else:
                row["market"] = {"why_not": why_market}
            if mwr is None:
                row["why"] = ("nothing was in the account this year" if not money else
                              "more was taken out than the year began with and put in, so it has no money-weighted return")
        else:
            row["earned"] = row["return"] = row["market"] = None
            row["why"] = why
        years.append(row)
        known_start, why_start = value_end is not None, (
            None if value_end is not None else f"the value at the end of {year} is not known: {why_end}")
        value_start = value_end or 0.0
    total = account.get("total")
    deposited = sum(a for _, a in flows if a > 0)
    withdrawn = -sum(a for _, a in flows if a < 0)
    # every year together: the Overview's money-weighted return, and the S&P 500's with the same money
    whole = build_desk.money_weighted_return(flows, total, today.isoformat()) if total else None
    market, _, why_market = build_desk.same_money_in_market(flows, prices, currency) if total else (None, None, None)
    both = build_desk.money_weighted_return(flows, market, today.isoformat()) if market is not None else None
    weekly = curve(flows, fills, moves, prices, splits, fx, currency, today, total, checked)
    return {"years": years, "currency": currency, "since": first, "check": checked,
            "curve": weekly, "risk": risk(weekly),
            "total": {"deposited": deposited, "withdrawn": withdrawn,
                      "earned": total - (deposited - withdrawn) if total else None,
                      "return": whole, "market": {"value": market, "return": both, "difference": total - market}
                      if market is not None
                      else ({"why_not": why_market} if total else None),
                      "dividends": sum(y["dividends"] for y in years), "interest": sum(y["interest"] for y in years),
                      "fees": sum(y["fees"] for y in years), "closed_gain": sum(y["closed_gain"] for y in years),
                      "trades": sum(y["trades"] for y in years)}}
