"""A Trading 212 account whose truth is known.

Each trading day of a few years is lived through: deposits and withdrawals, purchases and sales
at the day's price, a currency fee on every trade in another currency than the account's,
dividends with 15% withheld at source, interest on cash, a split and a reverse split, and, when
asked, a line listed in London. From the day-by-day account come the records Trading 212 gives
(orders, transactions, dividends, positions, the summary), the closes Tiingo gives, FRED's
exchange rates, and the truth: the account's value and cash on any day, and what each sale made.

test_audit.py checks the desk's figures against the truth, never against themselves. What the
simulation assumes of Trading 212's records (a fill's `netValue` is the money that moved, in the
account's currency, fees in it; a dividend's `amount` is what reached the account) is what the
desk assumes; `checks.py` tests the same assumptions on the user's real records, at every build.
"""
import math, random
from datetime import date, timedelta

FEE = 0.0015                 # Trading 212's currency conversion fee on a trade in another currency
WITHHELD = 0.15              # US tax withheld from a dividend paid to a treaty resident
RATE = 0.04                  # a year's interest on free cash
LINES = (
    # ticker, currency, first price, yearly drift, yearly volatility, dividend a share a quarter, split
    ("AAA_US_EQ", "USD", 100.0, 0.10, 0.25, 0.50, None),
    ("BBB_US_EQ", "USD", 400.0, 0.20, 0.40, 0.00, 4.0),          # four for one
    ("CCC_US_EQ", "USD", 20.0, -0.05, 0.50, 0.00, 1 / 3),        # one for three
    ("DDD_US_EQ", "USD", 60.0, 0.06, 0.15, 0.40, None),
)
LONDON = ("LLLl_EQ", "GBP", 80.0, 0.07, 0.14, 0.00, None)


def short(ticker):
    return ticker.split("_")[0].rstrip("l") if ticker.endswith("l_EQ") else ticker.split("_")[0]


class Ledger:
    def __init__(self, seed, currency="USD", start=date(2023, 1, 3), end=date(2026, 9, 25), london=False,
                 withdrawals=True):
        rnd = random.Random(seed)
        self.currency, self.start, self.end = currency, start, end
        self.days = [start + timedelta(d) for d in range((end - start).days + 1)
                     if (start + timedelta(d)).weekday() < 5]
        lines = list(LINES) + ([LONDON] if london else [])
        self.lines = {t: {"ccy": c, "div": dv, "split": s} for t, c, p0, mu, vol, dv, s in lines}
        # each line's printed price a day; a split's day chosen, the price divided from that day on
        self.px, self.split_day = {}, {}
        for t, c, p0, mu, vol, dv, s in lines:
            price, series = p0, {}
            split_at = self.days[rnd.randrange(len(self.days) // 4, 3 * len(self.days) // 4)] if s else None
            for d in self.days:
                price *= math.exp((mu - vol * vol / 2) / 252 + vol / math.sqrt(252) * rnd.gauss(0, 1))
                if d == split_at:
                    price /= s
                series[d] = price
            self.px[t] = series
            if split_at:
                self.split_day[t] = split_at
        self.spy, price = {}, 400.0
        for d in self.days:
            price *= math.exp((0.09 - 0.16 ** 2 / 2) / 252 + 0.16 / math.sqrt(252) * rnd.gauss(0, 1))
            self.spy[d] = price
        # US dollars per unit of the account's currency, and per pound for a London line
        self.fx, self.gbp = {}, {}
        a, g = {"USD": 1.0, "EUR": 1.08, "GBP": 1.25}[currency], 1.25
        for d in self.days:
            if currency != "USD":
                a *= math.exp(0.07 / math.sqrt(252) * rnd.gauss(0, 1))
            g *= math.exp(0.07 / math.sqrt(252) * rnd.gauss(0, 1))
            self.fx[d] = 1.0 if currency == "USD" else a
            self.gbp[d] = a if currency == "GBP" else g
        self._live(rnd, withdrawals)

    # ---- the money ----------------------------------------------------------------------
    def to_account(self, ticker, amount, day):
        """An amount in a line's own currency, in the account's."""
        ccy = self.lines[ticker]["ccy"]
        if ccy == self.currency:
            return amount
        usd = amount if ccy == "USD" else amount * self.gbp[day]
        return usd / self.fx[day]

    def _live(self, rnd, withdrawals):
        self.cash, self.shares = 0.0, {}
        self.cost = {}                                   # average cost, account currency, fees in
        self.orders, self.transactions, self.dividends = [], [], []
        self.lots = {}                                   # {ticker: [{qty, cost_each (acct), day}]}
        self.sales = []                                  # the truth of each sale
        self.flows, self.realized, self.fees, self.withheld, self.interest = [], 0.0, 0.0, 0.0, 0.0
        self.cash_on, self.shares_on = {}, {}
        oid, month = 1000, None
        withdraw_days = set(rnd.sample(self.days[60:], 3)) if withdrawals else set()
        for d in self.days:
            for t, when in self.split_day.items():            # before any trade that day
                if d == when and self.shares.get(t):
                    f = self.lines[t]["split"]
                    self.shares[t] *= f
                    for lot in self.lots[t]:
                        lot["qty"] *= f
                        lot["each"] /= f
            if d == self.days[0] or (d.month != month and rnd.random() < 0.8):
                amount = 5000.0 if d == self.days[0] else float(rnd.choice([250, 500, 750, 1000, 1500]))
                self._flow(d, amount)
            if d.month != month and d != self.days[0] and self.cash > 0:
                paid = round(self.cash * RATE / 12, 2)
                if paid > 0:
                    self.cash += paid
                    self.interest += paid
                    self.transactions.append({"type": "INTEREST_ON_FREE_CASH", "amount": paid, "currency": self.currency,
                                              "dateTime": f"{d}T06:00:00Z"})
            month = d.month
            if d in withdraw_days and self.cash > 100:
                self._flow(d, -round(self.cash * 0.3, 2))
            # a purchase or two when there is cash to spend, a sale now and then
            if self.cash > 300 and rnd.random() < 0.25:
                t = rnd.choice(list(self.lines))
                oid += 7
                self._buy(d, t, self.cash * rnd.uniform(0.2, 0.6), oid)
            if rnd.random() < 0.03:
                held = [t for t, q in self.shares.items() if q > 1e-6]
                if held:
                    t = rnd.choice(sorted(held))
                    oid += 7
                    self._sell(d, t, self.shares[t] * rnd.choice([0.25, 0.5, 1.0]), oid)
            if d.day >= 15 and d.month in (3, 6, 9, 12) and not any(x["paidOn"][:7] == f"{d:%Y-%m}" for x in self.dividends):
                for t, q in sorted(self.shares.items()):
                    per = self.lines[t]["div"]
                    if per and q > 1e-6:
                        gross = self.to_account(t, q * per, d)
                        net = round(gross * (1 - WITHHELD), 2)
                        self.cash += net
                        self.withheld += gross - net
                        self.dividends.append({"ticker": t, "amount": net, "grossAmountPerShare": per, "quantity": round(q, 6),
                                               "paidOn": f"{d}T12:00:00Z", "tickerCurrency": self.lines[t]["ccy"],
                                               "instrument": {"ticker": t, "currency": self.lines[t]["ccy"]}})
            self.cash_on[d] = self.cash
            self.shares_on[d] = dict(self.shares)

    def _flow(self, d, amount):
        self.cash += amount
        self.flows.append((d.isoformat(), amount))
        self.transactions.append({"type": "DEPOSIT" if amount > 0 else "WITHDRAW", "amount": amount,
                                  "currency": self.currency, "dateTime": f"{d}T09:00:00Z"})

    def _fill(self, d, t, side, qty, net, fee, pl, oid):
        ccy = self.lines[t]["ccy"]
        self.orders.append({
            "order": {"id": oid, "ticker": t, "side": side, "status": "FILLED", "createdAt": f"{d}T15:30:00Z",
                      "instrument": {"ticker": t, "name": short(t), "currency": ccy}},
            "fill": {"id": oid + 1, "filledAt": f"{d}T15:30:00Z", "quantity": qty if side == "BUY" else -qty,
                     "price": round(self.px[t][d], 4), "type": "TRADE",
                     "walletImpact": {"currency": self.currency, "netValue": net, "realisedProfitLoss": pl,
                                      "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": fee}] if fee else []}}})

    def _buy(self, d, t, budget, oid):
        qty = round(budget / self.to_account(t, self.px[t][d], d) * (1 - FEE), 6)
        if qty <= 0:
            return
        value = self.to_account(t, qty * round(self.px[t][d], 4), d)
        fee = round(value * FEE, 2) if self.lines[t]["ccy"] != self.currency else 0.0
        net = round(value + fee, 2)
        if net > self.cash:
            return
        self.cash -= net
        self.fees += fee
        self.shares[t] = self.shares.get(t, 0.0) + qty
        self.cost[t] = self.cost.get(t, 0.0) + net
        self.lots.setdefault(t, []).append({"qty": qty, "each": net / qty, "day": d})
        self._fill(d, t, "BUY", qty, net, fee, 0.0, oid)

    def _sell(self, d, t, qty, oid):
        qty = round(min(qty, self.shares[t]), 6)
        if qty <= 0:
            return
        value = self.to_account(t, qty * round(self.px[t][d], 4), d)
        fee = round(value * FEE, 2) if self.lines[t]["ccy"] != self.currency else 0.0
        net = round(value - fee, 2)
        average = self.cost[t] / self.shares[t]
        pl = round(net - average * qty, 2)
        self.cash += net
        self.fees += fee
        self.realized += pl
        self.cost[t] -= average * qty
        self.shares[t] -= qty
        if self.shares[t] < 1e-6:
            self.shares[t], self.cost[t] = 0.0, 0.0
        # the truth of the sale: first in, first out, in the account's money
        left, cost, taken = qty, 0.0, []
        while left > 1e-9 and self.lots.get(t):
            lot = self.lots[t][0]
            take = min(left, lot["qty"])
            cost += take * lot["each"]
            taken.append((lot["day"], take * lot["each"]))
            lot["qty"] -= take
            left -= take
            if lot["qty"] <= 1e-9:
                self.lots[t].pop(0)
        self.sales.append({"ticker": t, "day": d, "qty": qty, "gain": net / cost - 1 if cost else None,
                           "lots": taken, "net": net})
        self._fill(d, t, "SELL", qty, net, fee, pl, oid)

    # ---- what Trading 212, Tiingo and FRED give ------------------------------------------
    def value_on(self, d):
        """The account's value at the close of a trading day, in its currency."""
        return self.cash_on[d] + sum(self.to_account(t, q * self.px[t][d], d) for t, q in self.shares_on[d].items() if q)

    def raw(self):
        last = self.days[-1]
        positions, invested, cost, unrealised = [], 0.0, 0.0, 0.0
        for t, q in sorted(self.shares.items()):
            if q <= 1e-6:
                continue
            value = round(self.to_account(t, q * self.px[t][last], last), 2)
            positions.append({"instrument": {"ticker": t, "name": short(t), "currency": self.lines[t]["ccy"]},
                              "quantity": round(q, 6), "currentPrice": round(self.px[t][last], 4),
                              "averagePricePaid": round(self.px[t][last], 4), "createdAt": f"{self.days[0]}T15:30:00Z",
                              "walletImpact": {"currency": self.currency, "currentValue": value,
                                               "totalCost": round(self.cost[t], 2),
                                               "unrealizedProfitLoss": round(value - self.cost[t], 2), "fxImpact": 0.0}})
            invested += value
            cost += self.cost[t]
            unrealised += value - self.cost[t]
        newest = lambda xs, k: sorted(xs, key=k, reverse=True)
        return {"summary": {"currency": self.currency,
                            "cash": {"availableToTrade": round(self.cash, 2), "inPies": 0.0, "reservedForOrders": 0.0},
                            "investments": {"currentValue": round(invested, 2), "totalCost": round(cost, 2),
                                            "unrealizedProfitLoss": round(unrealised, 2),
                                            "realizedProfitLoss": round(self.realized, 2)},
                            "totalValue": round(self.cash + invested, 2)},
                "positions": positions,
                "orders": newest(self.orders, lambda o: o["fill"]["filledAt"] + str(o["order"]["id"])),
                "dividends": newest(self.dividends, lambda x: x["paidOn"]),
                "transactions": newest(self.transactions, lambda x: x["dateTime"]),
                "synced_at": f"{last}T21:00:00+00:00"}

    def prices(self):
        """Tiingo's closes for the US lines and SPY, as printed and adjusted for later splits, a
        split's day marked; FRED's rates for an account in euros or pounds."""
        store = {}
        for t, series in self.px.items():
            if not t.endswith("_US_EQ"):
                continue
            f, when = self.lines[t]["split"], self.split_day.get(t)
            store[short(t)] = {d.isoformat(): dict({"c": round(p, 4), "a": round(p / f if when and d < when else p, 6)},
                                                   **({"s": f} if d == when else {}))
                               for d, p in series.items()}
        store["SPY"] = {d.isoformat(): {"c": round(p, 4), "a": round(p, 4)} for d, p in self.spy.items()}
        if self.currency != "USD":
            store["fx_" + self.currency] = {d.isoformat(): round(v, 6) for d, v in self.fx.items()}
        return store

    # ---- the truth -----------------------------------------------------------------------
    def year_end(self, year):
        """The last trading day of a year, and the account's value at its close."""
        d = max(x for x in self.days if x.year == year)
        return d, self.value_on(d)

    def held_on(self, d):
        return {t for t, q in self.shares_on[d].items() if q > 1e-6}

    def spy_same_money(self, flows, end, opening=None):
        """The flows put into and taken out of SPY at the first close on or after their day, and
        what a period opened with at the close it was valued at (the last on or before its day),
        in the account's currency both ways at that session's rate, valued at the close of `end`."""
        units = 0.0
        if opening:
            d = max(x for x in self.days if x.isoformat() <= opening[0])
            units += opening[1] * self.fx[d] / self.spy[d]
        for day, amount in flows:
            d = min(x for x in self.days if x.isoformat() >= day)
            units += amount * self.fx[d] / self.spy[d]
        e = max(x for x in self.days if x.isoformat() <= end)
        return units * self.spy[e] / self.fx[e]


def irr(flows, end_value, end_day):
    """The money-weighted return, solved by Newton's method from a different start than the
    desk's bisection: (annual, period). Flows put in are positive."""
    end = date.fromisoformat(end_day)
    pts = [((end - date.fromisoformat(d)).days / 365.0, a) for d, a in flows if a]
    r = 0.05
    for _ in range(100):
        f = end_value - sum(a * (1 + r) ** t for t, a in pts)
        df = -sum(a * t * (1 + r) ** (t - 1) for t, a in pts)
        step = f / df
        r -= step
        if abs(step) < 1e-12:
            break
    days = max(t for t, _ in pts) * 365
    return r, (1 + r) ** (days / 365.0) - 1


# ---- the same account as other brokers give it (broker_csv, broker_alpaca, broker_ibkr) -----------
def _fills(L):
    """(day, ticker, side, qty, price, net in the account's money, fee in it, id) for each fill, oldest first."""
    out = []
    for o in L.orders:
        f = o["fill"]
        fee = sum(x["quantity"] for x in f["walletImpact"]["taxes"])
        out.append((f["filledAt"][:10], o["order"]["ticker"], o["order"]["side"], abs(f["quantity"]), f["price"],
                    f["walletImpact"]["netValue"], fee, str(o["order"]["id"])))
    return sorted(out, key=lambda x: (x[0], int(x[7])))


def _dividends(L):
    """(day, ticker, shares, per share in its currency, gross in the account's, net in it) for each dividend."""
    out = []
    for x in L.dividends:
        d = date.fromisoformat(x["paidOn"][:10])
        gross = L.to_account(x["ticker"], x["quantity"] * x["grossAmountPerShare"], d)
        out.append((d.isoformat(), x["ticker"], x["quantity"], x["grossAmountPerShare"], gross, x["amount"]))
    return out


def _market(t):
    return "US" if t.endswith("_US_EQ") else "LSE"


def csv_export(L, dates="iso"):
    """The account's history as a broker's CSV export, in broker_csv's columns (a date in slashes, day
    first, when `dates` is "dmy")."""
    def day(d):
        return d if dates == "iso" else f"{d[8:10]}/{d[5:7]}/{d[:4]}"
    rows = [["Date", "Type", "Symbol", "Market", "Quantity", "Price", "Currency", "Amount", "Fee", "Withheld", "ID"]]
    for d, t, side, qty, price, net, fee, oid in _fills(L):
        rows.append([day(d), side.lower(), short(t), _market(t), repr(qty), repr(price), L.lines[t]["ccy"], repr(net),
                     repr(fee) if fee else "", "", "t" + oid])
    for i, x in enumerate(L.transactions):
        kind = {"DEPOSIT": "deposit", "WITHDRAW": "withdrawal", "INTEREST_ON_FREE_CASH": "interest"}[x["type"]]
        rows.append([day(x["dateTime"][:10]), kind, "", "", "", "", L.currency, repr(abs(x["amount"])), "", "", f"c{i}"])
    for i, (d, t, q, per, gross, net) in enumerate(_dividends(L)):
        rows.append([day(d), "dividend", short(t), _market(t), repr(q), "", L.lines[t]["ccy"], repr(net), "",
                     repr(gross - net), f"d{i}"])
    return "\n".join(",".join(r) for r in rows) + "\n"


def alpaca_answers(L):
    """Alpaca's three answers for a dollar account of US lines: the account, the positions, and
    every activity, newest first."""
    assert L.currency == "USD" and all(t.endswith("_US_EQ") for t in L.lines)
    last = L.days[-1]
    positions = [{"symbol": short(t), "qty": repr(q), "current_price": repr(L.px[t][last]),
                  "market_value": repr(q * L.px[t][last]), "avg_entry_price": "1.0", "exchange": "NASDAQ",
                  "asset_class": "us_equity"}
                 for t, q in sorted(L.shares.items()) if q > 1e-6]
    items = []
    for d, t, side, qty, price, net, fee, oid in _fills(L):
        items.append({"id": f"{d.replace('-', '')}153000000::{oid}", "activity_type": "FILL",
                      "transaction_time": f"{d}T15:30:00Z", "type": "fill", "price": repr(price), "qty": repr(qty),
                      "side": side.lower(), "symbol": short(t), "order_id": oid})
    for i, x in enumerate(L.transactions):
        kind = {"DEPOSIT": "CSD", "WITHDRAW": "CSW", "INTEREST_ON_FREE_CASH": "INT"}[x["type"]]
        items.append({"id": f"{x['dateTime'][:10].replace('-', '')}000000000::c{i}", "activity_type": kind,
                      "date": x["dateTime"][:10], "net_amount": repr(x["amount"])})
    for i, (d, t, q, per, gross, net) in enumerate(_dividends(L)):
        stamp = d.replace("-", "")
        items.append({"id": f"{stamp}000000000::d{i}", "activity_type": "DIV", "date": d, "symbol": short(t),
                      "qty": repr(q), "per_share_amount": repr(per), "net_amount": repr(gross)})
        items.append({"id": f"{stamp}000000000::w{i}", "activity_type": "DIVNRA", "date": d, "symbol": short(t),
                      "qty": repr(q), "net_amount": repr(-(gross - net))})
    items.sort(key=lambda x: x["id"], reverse=True)
    total = L.cash + sum(float(p["market_value"]) for p in positions)
    return {"account": {"id": "a-secret-account-id", "account_number": "PA0000SECRET", "currency": "USD",
                        "cash": repr(L.cash), "portfolio_value": repr(total), "equity": repr(total)},
            "positions": positions, "activities": items}


def ibkr_statement(L):
    """Interactive Brokers' Activity Flex statement of the account, in its base currency."""
    from xml.sax.saxutils import quoteattr
    base, last = L.currency, L.days[-1]

    def rate(t, d):                          # base currency per unit of the line's own
        return L.to_account(t, 1.0, date.fromisoformat(d) if isinstance(d, str) else d)

    def row(tag, **attrs):
        return "<" + tag + " " + " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items()) + " />"
    trades = []
    for d, t, side, qty, price, net, fee, oid in _fills(L):
        r = rate(t, d)
        cash = (net if side == "SELL" else -net) / r
        trades.append(row("Trade", accountId="U0000SECRET", currency=L.lines[t]["ccy"], fxRateToBase=repr(r),
                          assetCategory="STK", symbol=short(t), description=short(t) + " INC",
                          listingExchange="NASDAQ" if t.endswith("_US_EQ") else "LSE", tradeID=oid,
                          dateTime=d.replace("-", "") + ";153000", tradeDate=d.replace("-", ""),
                          quantity=repr(qty if side == "BUY" else -qty), tradePrice=repr(price),
                          proceeds=repr(-qty * price if side == "BUY" else qty * price), netCash=repr(cash),
                          ibCommission=repr(-fee), ibCommissionCurrency=base, buySell=side,
                          levelOfDetail="EXECUTION"))
        trades.append(row("Trade", currency=L.lines[t]["ccy"], assetCategory="STK", symbol=short(t),
                          tradeID="", quantity=repr(qty), netCash=repr(cash), levelOfDetail="CLOSED_LOT",
                          dateTime=d.replace("-", "")))
    cash = []
    for i, x in enumerate(L.transactions):
        kind = {"DEPOSIT": "Deposits/Withdrawals", "WITHDRAW": "Deposits/Withdrawals",
                "INTEREST_ON_FREE_CASH": "Broker Interest Received"}[x["type"]]
        cash.append(row("CashTransaction", currency=base, fxRateToBase="1", assetCategory="", symbol="",
                        type=kind, amount=repr(x["amount"]), dateTime=x["dateTime"][:10].replace("-", ""),
                        transactionID=f"c{i}", levelOfDetail="DETAIL"))
    for i, (d, t, q, per, gross, net) in enumerate(_dividends(L)):
        r = rate(t, d)
        cash.append(row("CashTransaction", currency=L.lines[t]["ccy"], fxRateToBase=repr(r), assetCategory="STK",
                        symbol=short(t), type="Dividends", amount=repr(q * per), dateTime=d.replace("-", ""),
                        transactionID=f"d{i}", levelOfDetail="DETAIL"))
        cash.append(row("CashTransaction", currency=L.lines[t]["ccy"], fxRateToBase=repr(r), assetCategory="STK",
                        symbol=short(t), type="Withholding Tax", amount=repr(-(gross - net) / r),
                        dateTime=d.replace("-", ""), transactionID=f"w{i}", levelOfDetail="DETAIL"))
    positions, total = [], L.cash
    for t, q in sorted(L.shares.items()):
        if q <= 1e-6:
            continue
        value = q * L.px[t][last]
        total += value * rate(t, last)
        positions.append(row("OpenPosition", currency=L.lines[t]["ccy"], fxRateToBase=repr(rate(t, last)),
                             assetCategory="STK", symbol=short(t), description=short(t) + " INC",
                             listingExchange="NASDAQ" if t.endswith("_US_EQ") else "LSE", position=repr(q),
                             markPrice=repr(L.px[t][last]), positionValue=repr(value), levelOfDetail="SUMMARY"))
    stamp = last.isoformat().replace("-", "")
    return ("<FlexQueryResponse queryName=\"desk\" type=\"AF\"><FlexStatements count=\"1\">"
            f"<FlexStatement accountId=\"U0000SECRET\" fromDate=\"20230101\" toDate=\"{stamp}\">"
            + row("AccountInformation", accountId="U0000SECRET", currency=base, name="A Person")
            + "<Trades>" + "".join(trades) + "</Trades>"
            + "<CashTransactions>" + "".join(cash) + "</CashTransactions>"
            + "<OpenPositions>" + "".join(positions) + "</OpenPositions>"
            + "<CashReport>" + row("CashReportCurrency", currency="BASE_SUMMARY", endingCash=repr(L.cash))
            + row("CashReportCurrency", currency="USD", endingCash="0") + "</CashReport>"
            + "<EquitySummaryInBase>" + row("EquitySummaryByReportDateInBase", reportDate=stamp, cash=repr(L.cash),
                                             total=repr(total)) + "</EquitySummaryInBase>"
            + "</FlexStatement></FlexStatements></FlexQueryResponse>")
