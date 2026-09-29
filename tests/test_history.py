"""History: the account year by year (history.py), asked for by the owner on 28 Sep 2026."""
from support import *  # noqa: F401,F403
import world
import history


def close(value):
    return {"c": value, "a": value}


class HistoryTests(unittest.TestCase):
    """A small account worked by hand. $1,000 in on 1 Mar 2024; 10 AAA bought on 4 Mar at $50
    for $501 with the fee; AAA at $60 at the end of 2024. $200 in on 3 Feb 2025, a $10 dividend
    in May, AAA split two for one in June and at $45 at the end of 2025. Today, 2 Mar 2026,
    Trading 212 holds 20 AAA worth $960 and $709 cash: $1,669.

      end of 2024   499 cash + 10 x 60 = 1,099   earned   99 on 1,000 put in: +9.9%
      end of 2025   709 cash + 20 x 45 = 1,609   earned  310
      today                              1,669   earned   60: +3.73% so far
    The three earned add to Trading 212's total less what was put in: 1,669 - 1,200 = 469."""
    TODAY = date(2026, 3, 2)

    def account(self, currency="USD", deposits=(("2024-03-01", 1000.0), ("2025-02-03", 200.0)), extra_orders=(),
                positions=None, total=1669.0):
        fill = lambda oid, ticker, day, qty, net, fee=0.0, side="BUY", pl=None: {
            "order": {"id": oid, "ticker": ticker, "side": side, "instrument": {"ticker": ticker, "currency": "USD"}},
            "fill": {"filledAt": day + "T15:00:00Z", "quantity": qty if side == "BUY" else -qty, "price": 0, "type": "TRADE",
                     "walletImpact": {"netValue": net, "realisedProfitLoss": pl,
                                      "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": fee}] if fee else []}}}
        raw = {"summary": {"currency": currency, "totalValue": total,
                           "cash": {"availableToTrade": 709.0}, "investments": {"currentValue": 960.0}},
               "positions": positions if positions is not None else [
                   {"instrument": {"ticker": "AAA_US_EQ"}, "quantity": 20, "walletImpact": {"currentValue": 960.0}}],
               "orders": [fill(1, "AAA_US_EQ", "2024-03-04", 10, 501.0, fee=1.0)] + [fill(*o) for o in extra_orders],
               "dividends": [{"ticker": "AAA_US_EQ", "amount": 10.0, "paidOn": "2025-05-01T12:00:00Z"}],
               "transactions": [{"type": "DEPOSIT", "amount": a, "dateTime": d + "T09:00:00Z"} for d, a in deposits]}
        return raw

    def prices(self):
        return {"AAA": {"2024-03-04": close(50.0), "2024-12-31": close(60.0), "2025-06-02": dict(close(30.0), s=2.0),
                        "2025-12-31": close(45.0), "2026-03-02": close(48.0)},
                "SPY": {"2024-03-01": close(100.0), "2024-12-31": close(110.0), "2025-02-03": close(112.0),
                        "2025-12-31": close(121.0), "2026-03-02": close(120.0)}}

    def build(self, raw, prices=None):
        account = build_desk.build_account(raw["summary"], raw["positions"])
        return history.build(raw, account, self.prices() if prices is None else prices, self.TODAY)

    def test_each_year_rebuilt_by_hand(self):
        h = self.build(self.account())
        self.assertTrue(h["check"]["ok"], h["check"])
        self.assertAlmostEqual(h["check"]["rebuilt"], 1669.0)
        y24, y25, y26 = h["years"]
        self.assertEqual((y24["start"], y24["end"], y24["part"]), ("2024-03-01", "2024-12-31", True))
        self.assertEqual((y25["start"], y25["end"], y25["part"]), ("2024-12-31", "2025-12-31", False))
        self.assertEqual((y26["end"], y26["current"], y26["part"]), ("2026-03-02", True, True))
        self.assertAlmostEqual(y24["value_end"], 1099.0)
        self.assertAlmostEqual(y25["value_end"], 1609.0)            # the split: 20 shares at the printed $45
        self.assertEqual(y26["value_end"], 1669.0)                  # today's is Trading 212's own
        self.assertEqual([round(y["earned"], 2) for y in h["years"]], [99.0, 310.0, 60.0])
        self.assertAlmostEqual(sum(y["earned"] for y in h["years"]), h["total"]["earned"])
        self.assertAlmostEqual(y24["return"], 0.099, places=6)     # one deposit: the plain gain on it
        self.assertAlmostEqual(y26["return"], 1669 / 1609 - 1, places=6)
        self.assertEqual((y25["deposited"], y25["dividends"], y24["fees"], y24["trades"]), (200.0, 10.0, 1.0, 1))
        # the same money in the S&P 500: $1,000 on 1 Mar 2024 at 100, worth 1,100 at the end of 2024
        self.assertAlmostEqual(y24["market"]["value"], 1100.0)
        self.assertAlmostEqual(y24["market"]["return"], 0.10, places=6)
        self.assertAlmostEqual(y24["market"]["difference"], -1.0)
        # 2026: the 1,609 it began with, at 121, is worth 1,609 x 120 / 121 today
        self.assertAlmostEqual(y26["market"]["value"], 1609 * 120 / 121)
        self.assertEqual(h["total"]["deposited"], 1200.0)
        self.assertEqual(h["total"]["return"], build_desk.money_weighted_return(
            build_desk.external_flows(self.account()["transactions"]), 1669.0, self.TODAY.isoformat()))

    def test_a_movement_missing_from_the_history_withholds_every_rebuilt_year(self):
        """Rebuilt without the $200 of 2025, today comes to 1,469 against Trading 212's 1,669: some
        movement of money is not in the history, so no rebuilt value is trusted, and each year says so."""
        h = self.build(self.account(deposits=(("2024-03-01", 1000.0),)))
        self.assertFalse(h["check"]["ok"])
        self.assertAlmostEqual(h["check"]["difference"], -200.0)
        self.assertIn("1,469.00", h["check"]["why"])
        for y in h["years"]:
            self.assertIsNone(y["earned"], y["year"])
            self.assertIsNone(y["return"], y["year"])
            self.assertTrue(y["why"], y["year"])
        self.assertIn("1,669.00", h["years"][0]["why"])
        self.assertIn("the value at the end of 2025 is not known", h["years"][-1]["why"])

    def test_shares_the_record_holds_and_trading_212_does_not_fail_the_check(self):
        h = self.build(self.account(positions=[]))
        self.assertFalse(h["check"]["ok"])
        self.assertIn("AAA", h["check"]["why"])

    def test_a_line_listed_outside_the_us_has_no_close_so_its_years_say_why(self):
        london = (2, "VUSAl_EQ", "2024-06-03", 5, 0.0)            # bought for nothing, so the cash still ties
        positions = [{"instrument": {"ticker": "AAA_US_EQ"}, "quantity": 20, "walletImpact": {"currentValue": 960.0}},
                     {"instrument": {"ticker": "VUSAl_EQ"}, "quantity": 5, "walletImpact": {"currentValue": 0.0}}]
        h = self.build(self.account(extra_orders=(london,), positions=positions))
        self.assertTrue(h["check"]["ok"], h["check"])
        y24, y25, y26 = h["years"]
        self.assertIsNone(y24["value_end"])
        self.assertIn("VUSA was held", y24["why"])
        self.assertIn("the value at the end of 2024 is not known", y25["why"])
        self.assertIsNone(y26["return"])
        self.assertEqual(y26["value_end"], 1669.0)                  # today's is still known

    def test_a_year_without_a_close_near_its_end_is_not_priced(self):
        prices = self.prices()
        del prices["AAA"]["2024-12-31"]                             # the last close before it: 4 Mar
        h = self.build(self.account(), prices)
        self.assertIsNone(h["years"][0]["value_end"])
        self.assertIn("no close is stored for AAA at the end of 2024", h["years"][0]["why"])

    def test_an_account_in_euros_prices_its_dollar_shares_at_the_days_rate(self):
        prices = dict(self.prices(), fx_EUR={"2024-03-01": 1.25, "2024-12-31": 1.2, "2025-02-03": 1.2,
                                             "2025-12-31": 1.25, "2026-03-02": 1.25})
        h = self.build(self.account(currency="EUR"), prices)
        self.assertAlmostEqual(h["years"][0]["value_end"], 499 + 600 / 1.2)
        self.assertAlmostEqual(h["years"][1]["value_end"], 709 + 900 / 1.25)
        # the S&P 500 in euros: 1,000 EUR is $1,250 at 100, $1,375 at 110, back at 1.2
        self.assertAlmostEqual(h["years"][0]["market"]["value"], 1375 / 1.2)

    def test_nothing_put_in_is_no_history(self):
        self.assertIsNone(self.build(self.account(deposits=())))

    def test_a_day_whose_account_is_not_known_says_so(self):
        """As of a past day the account's value then is not known (asof.account), so neither is
        any rebuilt one: they cannot be checked."""
        raw = self.account()
        raw["summary"], raw["positions"] = {}, []
        h = self.build(raw)
        self.assertIsNone(h["check"])
        self.assertIsNone(h["years"][-1]["value_end"])
        self.assertIn("cannot be checked", h["years"][0]["why"])
        self.assertIn("cannot be checked", h["years"][-1]["why"])
        raw["transactions"] = raw["transactions"][:1]               # opened this year: nothing to rebuild
        h = history.build(raw, {"currency": "USD"}, self.prices(), date(2024, 6, 1))
        self.assertEqual(h["years"][0]["why"], "the account's value is not known for this day")

    def test_a_year_with_no_money_weighted_return_says_why(self):
        """More taken out than the year began with and put in (its gains taken too) has no
        money-weighted return: the year says so rather than showing none."""
        real = build_desk.money_weighted_return
        build_desk.money_weighted_return = lambda flows, end, day: None
        try:
            h = self.build(self.account())
        finally:
            build_desk.money_weighted_return = real
        self.assertTrue(all(y["return"] is None and "more was taken out" in y["why"] for y in h["years"]))
        self.assertTrue(all(y["earned"] is not None for y in h["years"]))      # what it earned is still known

    def test_the_demo_ties_to_the_penny_and_every_year_is_priced(self):
        today = date(2026, 9, 28)
        raw = generate_demo_data.generate(today)
        d = build_desk.compute(raw, today=today, prices=world.demo_prices(today))
        h = d["history"]
        self.assertTrue(h["check"]["ok"])
        self.assertLess(abs(h["check"]["difference"]), 0.5)
        self.assertTrue(all(y["earned"] is not None and y["return"] is not None for y in h["years"]))
        self.assertAlmostEqual(sum(y["earned"] for y in h["years"]), d["growth"]["gain"], places=6)
        self.assertEqual(h["total"]["trades"], d["trades"]["count"])
        self.assertAlmostEqual(h["total"]["dividends"], d["dividends"]["total"])
        self.assertAlmostEqual(h["total"]["market"]["value"], d["vs_market"]["market_value"])   # one comparison
        build_desk.render(d)

    def test_one_comparison_with_the_market_and_one_list_of_interest(self):
        source = inspect.getsource(build_desk.build_vs_market)
        self.assertIn("same_money_in_market(", source)
        self.assertIn("build_desk.same_money_in_market(", inspect.getsource(history.build))
        self.assertIn("build_desk.money_weighted_return(", inspect.getsource(history.build))
        for name in ("build_desk.py", "history.py"):
            text = read(os.path.join(ROOT, name))
            self.assertEqual(text.count('"LENDING_INTEREST"'), 1 if name == "build_desk.py" else 0, name)


class HistoryPageTests(unittest.TestCase):
    def test_a_tab_of_its_own_and_the_overview_points_to_it(self):
        page = page_source()
        self.assertIn("{id:'history',   label:'History',   pages:['history']}", page)
        self.assertIn("'renderHistory'", page)
        hero = template_function("renderHero", page)
        self.assertNotIn("Put in", hero)                            # moved, not copied
        self.assertIn('href="#history"', hero)
        body = template_function("renderHistory", page)
        for field in ("y.earned", "y.return", "m.return", "m.difference", "T.earned", "TM.difference", "y.why",
                      "H.check.rebuilt", "H.check.actual"):
            self.assertIn(field, body)
        self.assertNotRegex(body, r"0\.01|\b1%")                    # the tolerance is history.py's alone
        self.assertIn("withheld", body)                             # a figure not known is marked, never guessed

    def test_it_renders_on_the_demo_at_phone_width_without_a_table_overflowing(self):
        css = read(os.path.join(ROOT, "page", "desk.css"))
        self.assertRegex(css, r"@media \(max-width:640px\)\{\s*\.hist-tbl thead\{display:none;\}")
        today = date(2026, 9, 28)
        d = build_desk.compute(generate_demo_data.generate(today), today=today,
                               prices=world.demo_prices(today))
        html = build_desk.render(d)
        self.assertIn('id="histBody"', html)
        self.assertIn('id="page-history"', html)
