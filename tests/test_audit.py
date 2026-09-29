"""The desk's account figures against the truth of simulated accounts (tests/ledger.py), in
dollars, euros and pounds, with splits, withdrawals, fees, withheld tax and a London line: a
second calculation, written apart from the desk's, never the desk checked against itself: a
figure someone relies on with real money must be right."""
from support import *  # noqa: F401,F403
import copy
import types
import math
import statistics

import checks
import history
import ledger

CASES = [(seed, ccy) for seed in (1, 2, 3, 4) for ccy in ("USD", "EUR", "GBP")]


def build(L):
    return build_desk.compute(L.raw(), today=L.end, prices=L.prices())


class AccountTruthTests(unittest.TestCase):
    """Every figure the Overview, Portfolio and History show, against the simulation's truth."""

    def test_the_account_and_what_went_in_and_out(self):
        for seed, ccy in CASES:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy)
                d = build(L)
                a, g = d["account"], d["growth"]
                self.assertAlmostEqual(a["total"], L.value_on(L.days[-1]), delta=0.02)
                self.assertAlmostEqual(a["cash"], L.cash, delta=0.01)
                self.assertAlmostEqual(g["deposited"], sum(x for _, x in L.flows if x > 0), places=6)
                self.assertAlmostEqual(g["withdrawn"], -sum(x for _, x in L.flows if x < 0), places=6)
                self.assertAlmostEqual(g["gain"], a["total"] - g["net_in"], places=6)
                # what investing earned, from Trading 212's own figures, is the gain on the money put in
                self.assertAlmostEqual(g["investing"], g["gain"], delta=0.05)
                annual, _ = ledger.irr(L.flows, a["total"], L.end.isoformat())
                self.assertAlmostEqual(g["mwr"]["annual"], annual, places=6)
                self.assertAlmostEqual(d["costs"]["fees"], L.fees, delta=0.01)
                self.assertAlmostEqual(d["costs"]["withheld"], L.withheld, delta=0.02)
                self.assertAlmostEqual(d["costs"]["interest"], L.interest, delta=0.01)
                self.assertAlmostEqual(d["dividends"]["total"], sum(x["amount"] for x in L.dividends), places=6)
                self.assertAlmostEqual(sum(x["amount"] for x in d["dividends"]["tickers"]), d["dividends"]["total"], places=6)
                self.assertAlmostEqual(d["vs_market"]["market_value"], L.spy_same_money(L.flows, L.end.isoformat()),
                                       delta=0.02)

    def test_the_performance_curve_against_the_truth_every_week(self):
        """The line the Overview draws (history.curve): each week's account value is the simulation's own for that
        day, the S&P 500 beside it is what the same deposits would be worth that day, and the last point is
        today's total and today's market figure, the ones the Overview states in words."""
        for seed, ccy in CASES:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy)
                d = build(L)
                c = d["history"]["curve"]
                self.assertNotIn("why", c)
                self.assertEqual(c["days"][0], L.flows[0][0])
                self.assertEqual(c["days"][-1], L.end.isoformat())
                self.assertEqual({len(c[k]) for k in ("days", "account", "market", "net")}, {len(c["days"])})
                self.assertTrue(all(b > a for a, b in zip(c["days"], c["days"][1:])))
                for day, account, market, net in zip(c["days"][:-1], c["account"], c["market"], c["net"]):
                    trading = max(x for x in L.days if x.isoformat() <= day)
                    self.assertAlmostEqual(account, L.value_on(trading), delta=max(0.1, account * 1e-5), msg=day)   # the record rounds shares
                    flows = [(f, a) for f, a in L.flows if f <= day]
                    self.assertAlmostEqual(net, sum(a for _, a in flows), places=6, msg=day)
                    if market is not None:
                        self.assertAlmostEqual(market, L.spy_same_money(flows, day), delta=max(0.1, market * 1e-5), msg=day)
                self.assertAlmostEqual(c["account"][-1], d["account"]["total"], places=6)
                self.assertAlmostEqual(c["market"][-1], d["vs_market"]["market_value"], delta=0.01)
                self.assertEqual(c["currency"], ccy)

    def test_each_holding_and_the_account_by_industry_add_up(self):
        for seed, ccy in CASES[:4]:
            with self.subTest(seed=seed, currency=ccy):
                d = build(ledger.Ledger(seed, ccy))
                rows = d["positions"]["rows"]
                self.assertAlmostEqual(sum(r["weight"] for r in rows), 1.0, places=9)
                self.assertAlmostEqual(sum(r["value"] for r in rows), d["account"]["invested"], delta=0.05)
                x = d["exposure"]
                parts = sum(g["value"] for g in x["groups"]) + ((x["unplaced"] or {}).get("value") or 0) + x["cash"]["value"]
                self.assertAlmostEqual(parts, x["whole"], places=6)

    def test_each_year_against_the_truth(self):
        for seed, ccy in CASES:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy)
                h = build(L)["history"]
                self.assertTrue(h["check"]["ok"], h["check"])
                for y in h["years"]:
                    day, truth = L.year_end(y["year"])
                    if not y["current"]:
                        self.assertAlmostEqual(y["value_end"], truth, delta=0.05, msg=y["year"])
                    money = ([(y["start"], y["value_start"])] if y["value_start"] else []) + [
                        (dd, a) for dd, a in L.flows
                        if (dd >= y["start"] if y["start"] == L.flows[0][0] else dd > y["start"]) and dd <= y["end"]]
                    self.assertAlmostEqual(y["return"], ledger.irr(money, y["value_end"], y["end"])[1], places=6)
                    in_year = money[1:] if y["value_start"] else money
                    spy = L.spy_same_money(in_year, y["end"], (y["start"], y["value_start"]) if y["value_start"] else None)
                    self.assertAlmostEqual(y["market"]["value"] / spy, 1.0, places=5, msg=y["year"])
                self.assertAlmostEqual(sum(y["earned"] for y in h["years"]), h["total"]["earned"], delta=0.05)
                self.assertAlmostEqual(sum(y["fees"] for y in h["years"]), L.fees, delta=0.01)

    def test_a_london_line_leaves_the_years_it_was_held_unpriced_and_says_why(self):
        L = ledger.Ledger(3, "GBP", london=True)
        h = build(L)["history"]
        for y in h["years"]:
            day, _ = L.year_end(y["year"])
            if not y["current"] and any(not t.endswith("_US_EQ") for t in L.held_on(day)):
                self.assertIsNone(y["value_end"])
                self.assertIn("LLL was held", y["why"])


class SaleTruthTests(unittest.TestCase):
    """Each sale: what the money did in the account's currency, fees and the exchange rate in it,
    and the S&P 500 over each buy's own days in the same currency (28 Sep 2026: in a euro account
    a sale read 43 points off, the share's own price standing in for the money)."""

    def test_each_sale_against_the_truth(self):
        for seed, ccy in CASES:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy)
                d = build(L)
                rows = sorted(d["closed_trades"]["rows"], key=lambda r: (r["sold"], r["ticker"]))
                truth = sorted(L.sales, key=lambda s: (s["day"].isoformat(), ledger.short(s["ticker"])))
                self.assertEqual(len(rows), len(truth))
                days = sorted(L.spy)
                for r, t in zip(rows, truth):
                    self.assertAlmostEqual(r["gain"], t["gain"], places=7, msg=(r["ticker"], r["sold"]))
                    # the market over each buy's own days, weighted by what each cost
                    parts = []
                    for bought, cost in t["lots"]:
                        i = next(x for x in days if x >= bought)
                        j = next(x for x in days if x >= t["day"])
                        if j > i:
                            parts.append((cost, L.spy[j] / L.spy[i] * L.fx[i] / L.fx[j] - 1))
                    if parts:
                        market = sum(c * m for c, m in parts) / sum(c for c, _ in parts)
                        self.assertAlmostEqual(r["market"], market, places=4, msg=(r["ticker"], r["sold"]))
                    else:
                        self.assertIsNone(r["market"])

    def test_a_purchase_and_a_sale_with_one_time_stamp_are_matched_in_order(self):
        rows = [{"id": "11", "time": "2026-01-05T15:30:00Z", "date": "2026-01-05", "side": "BUY", "ticker": "AAA",
                 "us_line": True, "quantity": 1.0, "price": 10.0, "value": 10.0},
                {"id": "12", "time": "2026-01-05T15:30:00Z", "date": "2026-01-05", "side": "BUY", "ticker": "AAA",
                 "us_line": True, "quantity": 1.0, "price": 20.0, "value": 20.0},
                {"id": "13", "time": "2026-01-05T15:30:00Z", "date": "2026-01-05", "side": "SELL", "ticker": "AAA",
                 "us_line": True, "quantity": 2.0, "price": 30.0, "value": 60.0}]
        out = build_desk.build_closed_trades(list(reversed(rows)), {}, date(2026, 1, 6))
        self.assertEqual((out["count"], out["rows"][0]["buys"]), (1, 2))
        self.assertAlmostEqual(out["rows"][0]["gain"], 60.0 / 30.0 - 1)

    def test_a_london_line_is_never_matched_with_a_us_share_of_the_same_short_ticker(self):
        buy = {"time": "2026-01-05T15:30:00Z", "date": "2026-01-05", "side": "BUY", "ticker": "VUSA",
               "quantity": 1.0, "price": 10.0, "value": 10.0}
        sell = dict(buy, side="SELL", time="2026-02-05T15:30:00Z", date="2026-02-05", price=12.0, value=12.0)
        out = build_desk.build_closed_trades([dict(buy, id="1", us_line=False), dict(sell, id="2", us_line=True)],
                                             {}, date(2026, 3, 1))
        self.assertEqual(out["count"], 0)                                       # the US sale finds no US buy
        self.assertEqual([x["quantity"] for x in out["open_lots"]], [1.0])


class TurnoverTruthTests(unittest.TestCase):
    def truth(self, L, month):
        """Barber & Odean (2000, section I.B), from the simulation's own shares and prices: sales in
        month t and purchases in t-1, each matched to the shares held at t's start, at that day's
        prices, over that day's value; half of each."""
        first = date(int(month[:4]), int(month[5:7]), 1)
        eve = max(x for x in L.days if x < first)
        before = (first - timedelta(days=1)).strftime("%Y-%m")
        held = {t: q for t, q in L.shares_on[eve].items() if q > 1e-6}
        price = {t: L.to_account(t, L.px[t][eve], eve) for t in held}
        worth = sum(held[t] * price[t] for t in held)
        if worth <= 0:
            return None
        sold, bought = {}, {}
        for o in L.orders:
            t, day = o["order"]["ticker"], date.fromisoformat(o["fill"]["filledAt"][:10])
            f, when = L.lines[t]["split"] or 1.0, L.split_day.get(t)
            q = abs(o["fill"]["quantity"])                       # Trading 212 gives a sale's as negative
            if t not in held:
                continue
            if o["order"]["side"] == "SELL" and o["fill"]["filledAt"][:7] == month:
                sold[t] = sold.get(t, 0.0) + (q / f if when and eve < when <= day else q)
            elif o["order"]["side"] == "BUY" and o["fill"]["filledAt"][:7] == before:
                bought[t] = bought.get(t, 0.0) + (q * f if when and day < when <= eve else q)
        return (sum(min(q, held[t]) * price[t] for t, q in sold.items()) +
                sum(min(q, held[t]) * price[t] for t, q in bought.items())) / worth / 2

    def test_turnover_is_barber_and_odeans(self):
        for seed, ccy in CASES:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy)
                t = build(L)["habits"]["turnover"]
                self.assertEqual(t["basis"], "month")
                each = [x for x in (self.truth(L, m) for m in habits.turnover_months(L.end)) if x is not None]
                self.assertAlmostEqual(t["yearly"], 12 * sum(each) / len(each), places=4)

    def test_a_months_purchases_are_counted_against_the_holding_they_are_part_of(self):
        """10 shares held; 100 more bought in February with money put in. Barber & Odean count
        February's purchase at March's start, against the 110 shares it is part of: 100/110 of the
        holding, half of that the month's turnover. The desk's first version counted it against
        the 10 before it: ten times the holding, 500% in a month."""
        raw = {"summary": {"currency": "USD", "cash": {"availableToTrade": 0.0}, "investments": {"currentValue": 11000.0},
                           "totalValue": 11000.0},
               "positions": [{"instrument": {"ticker": "AAA_US_EQ"}, "quantity": 110.0, "currentPrice": 100.0,
                              "walletImpact": {"currentValue": 11000.0}}],
               "transactions": [{"type": "DEPOSIT", "amount": 1000.0, "dateTime": "2026-01-02T09:00:00Z"},
                                {"type": "DEPOSIT", "amount": 10000.0, "dateTime": "2026-02-10T09:00:00Z"}],
               "orders": [{"order": {"id": 1, "ticker": "AAA_US_EQ", "side": "BUY"},
                           "fill": {"filledAt": "2026-01-05T15:00:00Z", "quantity": 10.0, "price": 100.0,
                                    "walletImpact": {"netValue": 1000.0}}},
                          {"order": {"id": 2, "ticker": "AAA_US_EQ", "side": "BUY"},
                           "fill": {"filledAt": "2026-02-11T15:00:00Z", "quantity": 100.0, "price": 100.0,
                                    "walletImpact": {"netValue": 10000.0}}}]}
        prices_ = {"AAA": {d: {"c": 100.0, "a": 100.0} for d in ("2026-01-30", "2026-02-27", "2026-03-31")}}
        account = build_desk.build_account(raw["summary"], raw["positions"])
        got, lines = history.month_turnover(raw, account, prices_, date(2026, 4, 15), ["2026-02", "2026-03", "2026-04"])
        self.assertEqual(lines, "all")
        self.assertAlmostEqual(got["2026-02"], 0.5)            # all ten held were bought in January
        self.assertAlmostEqual(got["2026-03"], 100 / 110 / 2)
        self.assertAlmostEqual(got["2026-04"], 0.0)            # nothing traded in March or April
        self.assertLessEqual(max(got.values()), 1.0)


    def test_with_a_london_line_held_it_is_the_us_shares_turnover(self):
        """A line listed elsewhere has no daily closes, so no month-start value: the turnover is
        the US lines', as Barber & Odean's households held US common stocks, and says so."""
        for seed, ccy in CASES[:6]:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy, london=True)
                t = build(L)["habits"]["turnover"]
                self.assertEqual(t["basis"], "us_month")
                us = ledger.Ledger(seed, ccy, london=True)
                for day in us.shares_on:                                  # the truth without the London line
                    us.shares_on[day] = {k: q for k, q in us.shares_on[day].items() if k.endswith("_US_EQ")}
                us.orders = [o for o in us.orders if o["order"]["ticker"].endswith("_US_EQ")]
                each = [x for x in (self.truth(us, m) for m in habits.turnover_months(L.end)) if x is not None]
                self.assertAlmostEqual(t["yearly"], 12 * sum(each) / len(each), places=4)


class TradeCheckTruthTests(unittest.TestCase):
    def test_a_line_held_outside_the_us_is_the_one_checked(self):
        """28 Sep 2026: checking a London line the user held read "not held" and could show the
        rating of an unrelated US company with the same letters."""
        data = {"account": {"total": 1000.0, "cash": 100.0, "currency": "GBP"},
                "positions": {"rows": [{"ticker": "SHEL", "us_line": False, "value": 400.0, "name": "Shell (London)"}]}}
        store = {"companies": {"SHEL": {"cik": 1, "name": "SHELL PLC (NYSE)"}}}
        ratings = {"rated": 1, "companies": {"SHEL": {"label": "Buy", "place": 90.0}}}
        c = trade_check.check("SHEL", "SELL", 100.0, data, ratings=ratings, store=store, codes={1: 1311}, price=50.0)
        self.assertTrue(c["outside_us"])
        self.assertEqual((c["held_before"], c["held_after"]), (400.0, 300.0))
        self.assertIsNone(c["rating"]["label"])
        self.assertNotIn("industry", c)
        self.assertEqual(c["name"], "Shell (London)")
        # a US line held under the same letters is the one checked
        data["positions"]["rows"].append({"ticker": "SHEL", "us_line": True, "value": 200.0})
        c = trade_check.check("SHEL", "SELL", 100.0, data, ratings=ratings, store=store, codes={1: 1311}, price=50.0)
        self.assertEqual((c["outside_us"], c["held_before"], c["rating"]["label"]), (False, 200.0, "Buy"))


class PracticeTruthTests(unittest.TestCase):
    def test_a_replayed_book_restates_its_holdings_for_a_split_between_trades(self):
        """Bought 1 share at $1,000, a 10-for-1 split, sold all 10 at $120: nothing left, $200 made."""
        prices_ = {"NVDA": {"2024-01-02": {"c": 1000.0, "a": 100.0}, "2024-01-20": {"c": 110.0, "a": 110.0, "s": 10.0},
                            "2024-02-01": {"c": 120.0, "a": 120.0}}}
        trades = [{"id": "1", "date": "2024-01-02", "price_day": "2024-01-02", "ticker": "NVDA", "side": "BUY",
                   "quantity": 1.0, "price": 1000.0, "value": 1000.0, "fee": 0.0},
                  {"id": "2", "date": "2024-02-01", "price_day": "2024-02-01", "ticker": "NVDA", "side": "SELL",
                   "quantity": 10.0, "price": 120.0, "value": 1200.0, "fee": 0.0}]
        book = paper.replay(10000.0, trades, prices_)
        self.assertEqual(book["positions"], {})
        self.assertAlmostEqual(book["cash"], 10200.0)
        half = paper.replay(10000.0, trades[:1] + [dict(trades[1], quantity=5.0, value=600.0)], prices_)
        self.assertAlmostEqual(half["positions"]["NVDA"]["quantity"], 5.0)            # ten after the split, five sold
        self.assertAlmostEqual(half["positions"]["NVDA"]["cost"], 500.0)
        book = {"start_cash": 10000.0, "trades": trades}
        self.assertEqual(asof.practice(book, "2024-02-02", prices_)["positions"], {})


class ReconciliationTests(unittest.TestCase):
    """checks.py, on the real account at every build: each check holds on a true record and fails
    when the record is wrong in the way it is there to catch."""

    def made(self, raw, prices_, L):
        account = build_desk.build_account(raw["summary"], raw["positions"])
        return checks.checks(raw, account, prices_, L.days[-1])

    def test_every_check_holds_on_a_true_record(self):
        for seed, ccy in CASES:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy, london=seed % 2 == 0)
                made = self.made(L.raw(), L.prices(), L)
                self.assertEqual(made["failed"], [])
                self.assertEqual([c["name"] for c in made["checks"]],
                                 ["shares", "cash", "total", "closed", "holdings", "prices"])

    def test_each_check_fails_on_the_fault_it_is_there_for(self):
        L = ledger.Ledger(2, "EUR", london=True)
        raw, prices_ = L.raw(), L.prices()

        # a deposit missing from the history: the cash and the total
        r = copy.deepcopy(raw)
        r["transactions"] = [t for t in r["transactions"] if t["type"] != "DEPOSIT"][:1] + \
            [t for t in r["transactions"] if t["type"] == "DEPOSIT"][1:]
        self.assertEqual(self.made(r, prices_, L)["failed"], ["cash", "total"])

        # a purchase missing: the shares, the cash and the total
        r = copy.deepcopy(raw)
        held = {p["instrument"]["ticker"] for p in r["positions"]}
        gone = next(i for i, o in enumerate(r["orders"]) if o["order"]["side"] == "BUY" and o["order"]["ticker"] in held)
        del r["orders"][gone]
        made = self.made(r, prices_, L)
        self.assertIn("shares", made["failed"])
        self.assertIn("cash", made["failed"])
        shares = made["checks"][0]
        gone = ledger.short(raw["orders"][gone]["order"]["ticker"])
        self.assertIn(gone, shares["detail"])                          # the page names it
        self.assertNotIn(gone, shares["plain"])                        # doctor.py's report does not

        # a split the desk has not got: the shares and the prices
        split = next((t for t, d in prices_.items() if not t.startswith("fx_") and any("s" in v for v in d.values())), None)
        self.assertIsNotNone(split)
        p = copy.deepcopy(prices_)
        for day, bar in p[split].items():
            if "s" in bar:
                del bar["s"]
        self.assertTrue(any(x["instrument"]["ticker"].startswith(split + "_") for x in raw["positions"]))
        self.assertIn("shares", self.made(raw, p, L)["failed"])

        # a price read as another company's
        p = copy.deepcopy(prices_)
        us = next(x for x in raw["positions"] if x["instrument"]["ticker"].endswith("_US_EQ"))
        last = max(p[ledger.short(us["instrument"]["ticker"])])
        p[ledger.short(us["instrument"]["ticker"])][last]["c"] *= 3
        self.assertEqual(self.made(raw, p, L)["failed"], ["prices"])

        # a sale's closed gain misread
        r = copy.deepcopy(raw)
        sale = next(o for o in r["orders"] if o["order"]["side"] == "SELL")
        sale["fill"]["walletImpact"]["realisedProfitLoss"] += 0.05 * r["summary"]["totalValue"]
        self.assertEqual(self.made(r, prices_, L)["failed"], ["closed"])

        # a holding's value not in the invested figure
        r = copy.deepcopy(raw)
        r["summary"]["investments"]["currentValue"] += 0.05 * r["summary"]["totalValue"]
        self.assertIn("holdings", self.made(r, prices_, L)["failed"])

    def test_the_details_name_no_amount(self):
        L = ledger.Ledger(1, "GBP")
        raw = L.raw()
        raw["transactions"] = raw["transactions"][1:]
        made = self.made(raw, L.prices(), L)
        for c in made["checks"]:
            self.assertNotRegex(c["detail"], r"\d{2,}[.,]\d\d(?!%)")

    def test_no_account_no_checks(self):
        self.assertIsNone(checks.checks({}, {}, {}, date(2026, 9, 28)))
        self.assertIsNone(checks.checks(None, None, None, date(2026, 9, 28)))


class StatisticsReferenceTests(unittest.TestCase):
    """Every statistic against values computed elsewhere: SciPy 1.17 (binomtest's exact interval,
    false_discovery_control), the papers' own tables, and Excel's XIRR. Computed once outside the
    desk and written in, as the desk has no dependencies."""

    def test_the_exact_interval_is_scipys(self):
        for (k, n, level), (low, high) in {
                (0, 10, .95): (0.0, 0.308497), (1, 10, .95): (0.002529, 0.445016), (5, 10, .95): (0.187086, 0.812914),
                (7, 29, .95): (0.102984, 0.4354), (29, 29, .95): (0.880555, 1.0), (11, 25, .95): (0.244024, 0.650718),
                (4, 4, .95): (0.397635, 1.0), (3, 50, .99): (0.006872, 0.202706)}.items():
            got = uncertainty.proportion(k, n, level)
            self.assertAlmostEqual(got["low"], low, places=6)
            self.assertAlmostEqual(got["high"], high, places=6)

    def test_the_median_interval_is_the_textbooks(self):
        """Conover (1999): at 95%, the 2nd and 9th of 10, the 6th and 15th of 20, the 40th and 61st of 100."""
        for n, (low, high) in {10: (2, 9), 20: (6, 15), 30: (10, 21), 50: (18, 33), 100: (40, 61)}.items():
            got = uncertainty.median(list(range(1, n + 1)))
            self.assertEqual((got["low"], got["high"]), (low, high))
        self.assertIsNone(uncertainty.median([1, 2, 3, 4, 5])["low"])

    def test_the_difference_is_newcombes(self):
        """Newcombe (1998), table II, method 10."""
        for (k1, n1, k2, n2), (low, high) in {(56, 70, 48, 80): (0.0524, 0.3339), (9, 10, 3, 10): (0.1705, 0.8090),
                                              (10, 10, 0, 20): (0.6791, 1.0), (0, 10, 0, 20): (-0.1611, 0.2775)}.items():
            got = uncertainty.difference(k1, n1, k2, n2)
            self.assertAlmostEqual(got["low"], low, places=4)
            self.assertAlmostEqual(got["high"], high, places=4)

    def test_benjamini_hochberg_is_scipys(self):
        """Benjamini & Hochberg (1995)'s own fifteen p-values; SciPy's adjusted values."""
        ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216, 0.222, 0.251, 0.269, 0.275, 0.34]
        want = [0.015, 0.06, 0.126, 0.126, 0.126, 0.15, 0.158571] + [0.294643] * 7 + [0.34]
        q = backtest.benjamini_hochberg(list(enumerate(ps)))
        for i, w in enumerate(want):
            self.assertAlmostEqual(q[i], w, places=6)
        self.assertAlmostEqual(uncertainty.family_level(ps), 1 - 1 * 0.05 / 15)       # one declared at 5%

    def test_students_t_is_the_published_table(self):
        """Two-sided 95% (and one 99%) points from the standard t table (NIST/SEMATECH e-Handbook, 1.3.6.7.2)."""
        for df, level, want in ((10, .95, 2.22814), (12, .95, 2.17881), (24, .95, 2.06390), (50, .95, 2.00856),
                                (100, .95, 1.98397), (200, .95, 1.97190), (30, .99, 2.75000)):
            self.assertAlmostEqual(uncertainty.t_quantile(df, level), want, delta=3e-4, msg=(df, level))
        self.assertIsNone(uncertainty.t_quantile(9))                    # below the series' floor: no interval

    def test_the_slope_and_its_interval_are_an_exact_fraction_calculation(self):
        """x = 1..12 against y read to a tenth; the slope, r squared and the interval worked with fractions apart from
        the desk's code (normal equations, t = 2.22814 for ten degrees of freedom)."""
        ys = [2.1, 3.9, 6.2, 7.8, 10.1, 12.2, 13.8, 16.1, 18.0, 20.2, 21.9, 24.1]
        got = uncertainty.slope(list(range(1, 13)), ys)
        self.assertAlmostEqual(got["slope"], 2.002097902, places=8)
        self.assertAlmostEqual(got["explained"], 0.99957095, places=7)
        self.assertAlmostEqual(got["low"], 1.972871529, delta=5e-5)
        self.assertAlmostEqual(got["high"], 2.031324276, delta=5e-5)
        self.assertEqual((got["n"], got["confidence"]), (12, 0.95))
        exact = uncertainty.slope(list(range(1, 13)), [2 * x + 1 for x in range(1, 13)])
        self.assertAlmostEqual(exact["slope"], 2.0, places=12)
        self.assertAlmostEqual(exact["high"] - exact["low"], 0.0, places=9)
        self.assertAlmostEqual(exact["explained"], 1.0, places=12)
        self.assertIsNone(uncertainty.slope(list(range(11)), list(range(11))))          # too few pairs for the interval
        self.assertIsNone(uncertainty.slope([1.0] * 20, list(range(20))))               # x never moves
        self.assertIsNone(uncertainty.slope([1, 2, 3], [1, 2]))

    def test_the_money_weighted_return_is_excels_xirr(self):
        """Excel's XIRR example: 10,000 in, 2,750, 4,250 and 3,250 out, 2,750 left: 37.34% a year.
        More came out than went in, which had no return until 28 Sep 2026."""
        got = build_desk.money_weighted_return([("2008-01-01", 10000), ("2008-03-01", -2750), ("2008-10-30", -4250),
                                                ("2009-02-15", -3250)], 2750, "2009-04-01")
        self.assertAlmostEqual(got["annual"], 0.373363, places=5)

    def test_a_short_period_has_its_return(self):
        """10% in a fortnight is over 1,000% a year: it had no return until 28 Sep 2026."""
        got = build_desk.money_weighted_return([("2026-09-14", 1000.0)], 1100.0, "2026-09-28")
        self.assertAlmostEqual(got["period"], 0.10, places=9)
        self.assertGreater(got["annual"], 10)
        got = build_desk.money_weighted_return([("2026-09-26", 1000.0)], 800.0, "2026-09-28")
        self.assertAlmostEqual(got["period"], -0.20, places=9)
        # a constant rate, deposits and withdrawals at any time: the rate itself
        for daily in (-0.004, 0.0, 0.0007, 0.02):
            flows, balance, last = [], 0.0, date(2024, 1, 2)
            for i, (day, amount) in enumerate([(date(2024, 1, 2), 5000), (date(2024, 6, 3), 2000),
                                               (date(2025, 2, 10), -0.4), (date(2026, 1, 5), 1500)]):
                balance *= math.exp(daily * (day - last).days)
                last = day
                amount = amount * balance if amount < 0 else amount
                balance += amount
                flows.append((day.isoformat(), amount))
            balance *= math.exp(daily * (date(2026, 9, 28) - last).days)
            got = build_desk.money_weighted_return(flows, balance, "2026-09-28")
            self.assertAlmostEqual(math.log1p(got["annual"]), daily * 365, places=9)
        self.assertIsNone(build_desk.money_weighted_return([("2026-01-02", -100.0)], 0.0, "2026-09-28"))


class RiskTruthTests(unittest.TestCase):
    """How rough the ride was (history.risk): the swing, the worst fall and the beta the Overview's weekly line gives,
    against the same figures worked from the simulation's own daily values with the deposits taken out on their true
    days (a time-weighted return), apart from the desk's weekly approximation (Modified Dietz)."""

    def exact(self, L, curve):
        days = curve["days"]
        flows = {}
        for f, a in L.flows:
            flows[f] = flows.get(f, 0.0) + a
        trading = [x.isoformat() for x in L.days]
        value = {x.isoformat(): L.value_on(x) for x in L.days}

        def account(d0, d1):
            t0, t1 = (max(x for x in trading if x <= d) for d in (d0, d1))
            span, growth = [x for x in trading if t0 <= x <= t1], 1.0
            for a, b in zip(span, span[1:]):
                growth *= (value[b] - sum(v for k, v in flows.items() if a < k <= b)) / value[a]
            return growth - 1

        unit = lambda day: L.spy_same_money([(L.flows[0][0], 1.0)], day)
        weekly = [(account(days[i - 1], days[i]), unit(days[i]) / unit(days[i - 1]) - 1, i) for i in range(1, len(days))]
        return weekly

    def test_the_swing_the_fall_and_the_beta_match_the_daily_truth(self):
        for seed, ccy in CASES:
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy)
                d = build(L)
                c, r = d["history"]["curve"], d["history"]["risk"]
                self.assertNotIn("why", r)
                weekly = self.exact(L, c)
                whole = [(a, m) for a, m, i in weekly
                         if (date.fromisoformat(c["days"][i]) - date.fromisoformat(c["days"][i - 1])).days == history.CURVE_STEP_DAYS
                         and abs(c["net"][i] - c["net"][i - 1]) <= history.RISK_MAX_FLOW * c["account"][i - 1]]
                self.assertEqual(r["weeks"], len(whole))
                for who, k in (("account", 0), ("market", 1)):
                    xs = [w[k] for w in whole]
                    swing = statistics.stdev(xs) * math.sqrt(52)
                    self.assertAlmostEqual(r["swing"][who], swing, delta=0.01 * swing, msg=who)
                fit = uncertainty.slope([m for _, m in whole], [a for a, _ in whole])
                self.assertAlmostEqual(r["beta"]["slope"], fit["slope"], delta=0.01)
                self.assertAlmostEqual(r["beta"]["low"], fit["low"], delta=0.01)
                self.assertAlmostEqual(r["beta"]["high"], fit["high"], delta=0.01)
                self.assertAlmostEqual(r["beta"]["explained"], fit["explained"], delta=0.01)
                # the worst fall: the chain of every week's true return, the deepest peak-to-trough
                for who, k in (("account", 0), ("market", 1)):
                    level, high, worst = 1.0, 1.0, 0.0
                    for w in weekly:
                        level *= 1 + w[k]
                        high = max(high, level)
                        worst = max(worst, 1 - level / high)
                    self.assertAlmostEqual(r["fall"][who]["depth"], worst, delta=0.005, msg=who)
                self.assertLessEqual(r["fall"]["account"]["peak"], r["fall"]["account"]["trough"])
                self.assertEqual((r["since"], r["until"]), (c["days"][0], c["days"][-1]))


    def test_the_health_report_says_whether_they_can_be_drawn_without_an_amount(self):
        import doctor
        L = ledger.Ledger(1, "USD")
        raw = L.raw()
        account = build_desk.build_account(raw["summary"], raw["positions"])
        rows = dict(doctor.weekly_line(raw, account, L.prices(), L.end))
        curve = build(L)["history"]["curve"]
        self.assertEqual(rows["weekly"], f"drawn · {len(curve['days'])} weeks, 0 left out for want of a close")
        self.assertRegex(rows["risk"], r"^shown · \d+ whole weeks$")
        raw["summary"]["totalValue"] = float(raw["summary"]["totalValue"]) * 1.5            # a total the record cannot reach
        broken = build_desk.build_account(raw["summary"], raw["positions"])
        rows = dict(doctor.weekly_line(raw, broken, L.prices(), L.end))
        self.assertIn("does not tie", rows["weekly"])
        self.assertNotRegex(rows["weekly"], r"[$€£]|\d,\d{3}")
        self.assertNotIn("risk", rows)
        self.assertEqual(doctor.weekly_line({}, {}, {}, L.end), [("weekly", "no money put in yet")])


class DispositionTruthTests(unittest.TestCase):
    def trade(self, ticker, side, day, qty, price):
        return {"ticker": ticker, "side": side, "date": day, "time": day + "T15:00:00Z", "quantity": qty,
                "price": price, "value": qty * price, "us_line": True}

    def test_the_reference_is_the_average_purchase_price(self):
        """Odean (1998) sets each holding against its average purchase price, as Trading 212 shows it.
        10 bought at 100 and 10 at 200: an average of 150, which a sale of half leaves at 150. At
        170 the half kept is a gain; the first lots out first made it a loss against 200."""
        rows = [self.trade("AAA", "BUY", "2026-01-02", 10, 100.0), self.trade("AAA", "BUY", "2026-01-05", 10, 200.0),
                self.trade("BBB", "BUY", "2026-01-05", 10, 50.0),
                self.trade("AAA", "SELL", "2026-02-02", 10, 160.0),                 # a gain against 150
                self.trade("BBB", "SELL", "2026-03-02", 10, 40.0)]                  # a loss; AAA kept at 170
        prices_ = {"AAA": {"2026-02-02": {"c": 160.0, "a": 160.0}, "2026-03-02": {"c": 170.0, "a": 170.0}},
                   "BBB": {"2026-02-02": {"c": 55.0, "a": 55.0}, "2026-03-02": {"c": 40.0, "a": 40.0}}}
        d = habits.disposition(rows, prices_)
        # 2 Feb: AAA sold at a gain, BBB kept at a gain; 2 Mar: BBB sold at a loss, AAA kept at a gain
        self.assertEqual(d["counts"], {"rg": 1, "rl": 1, "pg": 2, "pl": 0})


class SplitSinceTheFilingTests(unittest.TestCase):
    """A market value is today's price times a share count from the last filing. NVIDIA split
    ten for one on 10 June 2024, after its May 10-Q: its count and its price then described
    different shares, and until 28 Sep 2026 its market value, P/E and book to market read a
    tenth of what they were."""

    def row(self, **extra):
        return dict({"ticker": "NVDA", "cik": 1045810, "name": "NVIDIA", "assets": [96e9], "revenue": [96e9],
                     "net_income": [53e9], "equity": [58e9], "operating_income": [60e9], "debt": [8.5e9],
                     "cash": [7e9], "shares_outstanding": [2.46e9], "shares_outstanding_on": ["2024-05-22"],
                     "shares": [2.49e9], "public_float": [1.1e12]}, **extra)

    def prices(self):
        return {"NVDA": {"2024-06-07": {"c": 1208.88, "a": 120.888}, "2024-06-10": {"c": 121.79, "a": 121.79, "s": 10.0},
                         "2024-09-27": {"c": 121.40, "a": 121.40}}}

    def test_the_count_is_restated_in_the_prices_shares(self):
        split = value.splits_since(self.row(), self.prices(), "NVDA", "2024-09-27")
        self.assertEqual(split, 10.0)
        v = value.value_company(self.row(), 121.40, split)
        self.assertAlmostEqual(v["market_cap"], 121.40 * 2.46e10)                # about $3.0tn, not $0.3tn
        self.assertAlmostEqual(v["price_to_earnings"], 121.40 * 2.46e10 / 53e9)
        self.assertIn("restated for a split since", v["share_count_basis"])
        # a count measured after the split is not restated again
        after = self.row(shares_outstanding=[24.5e9], shares_outstanding_on=["2024-08-21"])
        self.assertEqual(value.splits_since(after, self.prices(), "NVDA", "2024-09-27"), 1.0)

    def test_the_rating_reads_book_to_market_at_the_restated_count(self):
        row = self.row()
        split = value.splits_since(row, self.prices(), "NVDA", "2024-09-27")
        self.assertAlmostEqual(rating.book_to_market(row, 121.40, split), 58e9 / (121.40 * 2.46e10))
        self.assertIn("value_mod.splits_since(companies[t], prices, t", inspect.getsource(rating.rate_all))
        self.assertIn("value.splits_since(", inspect.getsource(context.for_company))
        self.assertIn("value.splits_since(", inspect.getsource(server.Handler))

    def test_the_universe_keeps_the_day_each_cover_count_was_measured(self):
        def fetch(url, who):
            if "company_tickers" in url:
                return {"0": {"cik_str": 1, "ticker": "AAA", "title": "A"}}
            if "EntityCommonStockSharesOutstanding" in url:
                return {"data": [{"cik": 1, "val": 5e8, "end": "2026-01-23"}]}
            return {"data": []}
        built = universe.build(years=1, who="me", fetch=fetch, log=lambda *a: None, sleep=lambda s: None)
        row = built["companies"]["AAA"]
        self.assertEqual((row["shares_outstanding"], row["shares_outstanding_on"]), ([5e8], ["2026-01-23"]))
        self.assertEqual(value.count_day(row), "2026-01-23")
        # a universe built before the day was kept: the end of the year its frame was read for
        del row["shares_outstanding_on"]
        self.assertEqual(value.count_day(row, "2026-05-01"), f"{universe.latest_year(date(2026, 5, 1))}-12-31")

    def test_the_command_line_pricing_reads_tiingos_rows(self):
        """Tiingo's rows carry four fields (the split factor last); latest_close read three."""
        rows = [("2024-05-22", 950.0, 95.0, 1.0), ("2024-06-10", 121.79, 121.79, 10.0), ("2024-09-27", 121.4, 121.4, 1.0)]
        fetch = lambda ticker, start, key: [r for r in rows if r[0] >= start]
        close, day, split = value.latest_close("NVDA", "k", fetch, date(2024, 9, 27), since="2024-05-22")
        self.assertEqual((close, day, split), (121.4, "2024-09-27", 10.0))
        out = value.for_tickers(["NVDA"], {"companies": {"NVDA": self.row()}, "built": "2024-09-01"}, key="k",
                                fetch=fetch, today=date(2024, 9, 27))
        self.assertAlmostEqual(out["NVDA"]["market_cap"], 121.4 * 2.46e10)


class PerShareAcrossASplitTests(unittest.TestCase):
    """NVIDIA's diluted EPS as filed, its ten-for-one split of 10 June 2024 between two
    quarters, and the restated comparatives in the later 10-Qs."""

    def q(self, start, end, val, filed, form="10-Q"):
        return {"start": start, "end": end, "val": val, "form": form, "filed": filed}

    def facts(self):
        return {"eps": [
            self.q("2021-02-01", "2021-05-02", 0.76, "2021-05-26"),
            self.q("2021-05-03", "2021-08-01", 0.94, "2021-08-20"),
            self.q("2021-08-02", "2021-10-31", 0.97, "2021-11-22"),
            self.q("2021-02-01", "2022-01-30", 3.85, "2022-03-18", "10-K"),
            self.q("2022-01-31", "2022-05-01", 0.64, "2022-05-27"),
            self.q("2022-05-02", "2022-07-31", 0.26, "2022-08-31"),
            self.q("2022-08-01", "2022-10-30", 0.27, "2022-11-18"),
            self.q("2022-01-31", "2023-01-29", 1.74, "2023-02-24", "10-K"),
            self.q("2023-01-30", "2023-04-30", 0.82, "2023-05-26"),
            self.q("2023-05-01", "2023-07-30", 2.48, "2023-08-28"),
            self.q("2023-07-31", "2023-10-29", 3.71, "2023-11-21"),
            self.q("2023-01-30", "2024-01-28", 11.93, "2024-02-21", "10-K"),
            self.q("2024-01-29", "2024-04-28", 5.98, "2024-05-29"),
            self.q("2023-05-01", "2023-07-30", 0.25, "2024-08-28"),           # restated comparative
            self.q("2024-04-29", "2024-07-28", 0.67, "2024-08-28"),
            self.q("2023-07-31", "2023-10-29", 0.37, "2024-11-20"),           # restated comparative
            self.q("2024-07-29", "2024-10-27", 0.78, "2024-11-20")]}

    SPLITS = [("2024-06-10", 10.0)]

    def test_twelve_months_are_summed_in_one_share(self):
        # 0.78 + 0.67 + 5.98/10 + (11.93/10 - 0.82/10 - 0.25 - 0.37): about $2.54, NVIDIA's own
        got = fundamentals.derive("NVDA", 1045810, self.facts(), {}, splits=self.SPLITS, through="2024-12-02")
        self.assertAlmostEqual(got["eps"], 0.78 + 0.67 + 0.598 + (1.193 - 0.082 - 0.25 - 0.37), places=9)
        self.assertEqual(got["eps_basis"], "quarters")
        # as filed, the quarters mixed two sizes of share: over $17
        self.assertGreater(fundamentals.derive("NVDA", 1045810, self.facts(), {})["eps"], 17)

    def test_a_past_day_reads_that_days_shares(self):
        stored = {"ticker": "NVDA", "cik": 1045810, "facts": self.facts(), "tags": {}}
        before = asof.company(stored, "2024-06-03", self.SPLITS)        # before the split: the old shares
        self.assertAlmostEqual(before["eps"], 5.98 + (11.93 - 0.82 - 2.48 - 3.71) + 3.71 + 2.48, places=6)
        after = asof.company(stored, "2024-06-14", self.SPLITS)         # the same filings, the new shares
        self.assertAlmostEqual(after["eps"], before["eps"] / 10, places=9)

    def test_the_price_to_earnings_history_does_not_jump_at_the_split(self):
        stored = {"ticker": "NVDA", "cik": 1045810, "facts": self.facts(), "tags": {}}
        closes = {}
        d = date(2019, 1, 1)
        while d <= date(2024, 12, 2):
            if d.weekday() < 5:
                closes[d.isoformat()] = 1100.0 if d < date(2024, 6, 10) else 110.0
            d += timedelta(days=1)
        got = value.own_history(stored, closes, date(2024, 12, 2), self.SPLITS)
        by_month = {p["month"]: p["pe"] for p in got["points"]}
        twelve = 5.98 + (11.93 - 0.82 - 2.48 - 3.71) + 3.71 + 2.48                # as filed by May 2024
        self.assertAlmostEqual(by_month["2024-05"], 1100.0 / twelve, places=6)
        self.assertAlmostEqual(by_month["2024-06"], 110.0 / (twelve / 10), places=6)       # the same, no jump
        self.assertAlmostEqual(got["now"], 110.0 / 2.539, places=2)

    def test_the_card_reads_them_in_todays_shares(self):
        news_data = {"tickers": ["NVDA"]}
        funds = {"companies": {"NVDA": dict(fundamentals.card("NVDA", 1045810, self.facts(), {}))}}
        prices_ = {"NVDA": {"2024-06-07": {"c": 1208.88, "a": 120.888}, "2024-06-10": {"c": 121.79, "a": 121.79, "s": 10.0},
                            "2024-11-29": {"c": 138.25, "a": 138.25}}}
        card = build_desk.build_companies(news_data, funds, {}, prices_, {}, date(2024, 12, 2))[0]
        self.assertAlmostEqual(card["eps"], 2.539, places=3)


