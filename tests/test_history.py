"""History: the account year by year (history.py), asked for by the owner on 28 Sep 2026."""
from support import *  # noqa: F401,F403
import world
import history
import math


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

    def dense(self):
        """The example account's prices with a close every day, as Tiingo gives them."""
        prices, day = self.prices(), date(2024, 3, 4)
        aaa = {}
        while day <= self.TODAY:
            d = day.isoformat()
            aaa[d] = close(50.0 if d < "2024-12-31" else 60.0 if d < "2025-06-02" else 30.0 if d < "2025-12-31" else 45.0)
            day += timedelta(days=1)
        aaa["2025-06-02"] = dict(close(30.0), s=2.0)
        aaa["2026-03-02"] = close(48.0)
        return dict(prices, AAA=aaa)

    def test_the_weekly_curve_by_hand(self):
        """The example account, week by week from the first deposit: the value rebuilt at each week's close, the S&P 500
        beside it with the same deposits, what was put in net, and today's point Trading 212's own."""
        c = self.build(self.account(), self.dense())["curve"]
        self.assertNotIn("why", c)
        self.assertEqual(c["skipped"], 0)
        self.assertEqual(c["days"][:3], ["2024-03-01", "2024-03-08", "2024-03-15"])
        self.assertEqual(c["days"][-1], "2026-03-02")
        self.assertEqual(c["account"][0], 1000.0)                     # the deposit, nothing bought yet
        self.assertEqual(c["account"][1], 999.0)                      # 499 cash + 10 x 50 (the 4 Mar close)
        self.assertEqual(c["market"][:2], [1000.0, 1000.0])           # 10 units at 100, the only close stored
        self.assertEqual(c["net"][:2], [1000.0, 1000.0])
        self.assertEqual(c["account"][-1], 1669.0)
        self.assertAlmostEqual(c["market"][-1], (1000 / 100 + 200 / 112) * 120, places=2)
        self.assertEqual(c["net"][-1], 1200.0)
        after = [k for k, d in enumerate(c["days"]) if d >= "2025-02-03"][0]
        self.assertEqual(c["net"][after], 1200.0)                     # the second deposit counts from its day
        self.assertEqual(c["net"][after - 1], 1000.0)

    def test_the_curve_is_withheld_when_the_rebuild_does_not_tie(self):
        """A week is drawn only while the rebuild ties to Trading 212's total, as a year's end is."""
        c = self.build(self.account(total=2500.0), self.dense())["curve"]
        self.assertEqual(list(c), ["why"])
        self.assertTrue(c["why"])

    def test_a_few_weeks_without_a_close_are_left_out_and_the_rest_still_draw(self):
        prices = self.dense()
        for gone in ("2024-04-08", "2024-04-15", "2024-04-22", "2024-04-29", "2024-05-06", "2024-05-13"):
            for d in [x for x in prices["AAA"] if gone <= x < (date.fromisoformat(gone) + timedelta(days=7)).isoformat()]:
                del prices["AAA"][d]
        c = self.build(self.account(), prices)["curve"]
        self.assertNotIn("why", c)                       # ten days' gap is more than a week's slack: those weeks are skipped
        self.assertGreater(c["skipped"], 0)
        self.assertEqual(len(c["days"]), len(set(c["days"])))
        self.assertTrue(all(b > a for a, b in zip(c["days"], c["days"][1:])))

    def test_many_weeks_without_a_close_withhold_the_line_and_say_why(self):
        prices = self.dense()
        for d in [x for x in prices["AAA"] if "2024-03-15" <= x <= "2024-11-30"]:
            del prices["AAA"][d]
        c = self.build(self.account(), prices)["curve"]
        self.assertEqual(list(c), ["why"])
        self.assertTrue(c["why"])

    def test_a_week_with_a_line_that_has_no_close_says_why_instead_of_drawing_a_gap(self):
        c = self.build(self.account(), prices={"SPY": self.prices()["SPY"]})["curve"]
        self.assertEqual(list(c), ["why"])

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


class RiskByHandTests(unittest.TestCase):
    """history.risk on weekly curves made up so the answer is known: the swing, the worst fall and the beta
    are worked here with plain arithmetic, not read back from the desk."""

    MARKET = [0.02, -0.01, 0.03, -0.02, 0.015, -0.005, 0.01, -0.03, 0.025, 0.0, -0.015, 0.02, 0.005]   # a repeating pattern

    def weeks(self, n=60, start=date(2024, 1, 5)):
        return [(start + timedelta(days=7 * i)).isoformat() for i in range(n)]

    def curve(self, n=60, beta=1.5, flow=0.0, deposit_week=None, big=0.0, gap=None):
        """`n` weeks: the market moves by MARKET's pattern, the account by `beta` times it, `flow` put in every week
        (landing, in Dietz's sense, half way through it), so each week's return is exactly the pattern's."""
        a, m, net = [1000.0], [1000.0], [1000.0]
        for i in range(1, n):
            r = self.MARKET[(i - 1) % len(self.MARKET)]
            f = flow + (big if deposit_week == i else 0.0)
            a.append(a[-1] + f + beta * r * (a[-1] + f / 2))
            m.append(m[-1] + f + r * (m[-1] + f / 2))
            net.append(net[-1] + f)
        days = self.weeks(n)
        if gap is not None:                       # a week with no close: dropped, its neighbours joined
            for series in (days, a, m, net):
                del series[gap]
        return {"days": days, "account": a, "market": m, "net": net, "currency": "USD", "skipped": 0}

    def swing(self, returns):
        mean = sum(returns) / len(returns)
        return math.sqrt(sum((x - mean) ** 2 for x in returns) / (len(returns) - 1)) * math.sqrt(52)

    def test_an_account_that_moves_one_and_a_half_times_the_market_has_that_beta(self):
        r = history.risk(self.curve())
        pattern = [self.MARKET[i % len(self.MARKET)] for i in range(59)]
        self.assertEqual(r["weeks"], 59)
        self.assertAlmostEqual(r["beta"]["slope"], 1.5, places=9)
        self.assertAlmostEqual(r["beta"]["explained"], 1.0, places=9)
        self.assertAlmostEqual(r["beta"]["high"] - r["beta"]["low"], 0.0, places=6)     # a perfect fit leaves no doubt
        self.assertAlmostEqual(r["swing"]["market"], self.swing(pattern), places=9)
        self.assertAlmostEqual(r["swing"]["account"], 1.5 * self.swing(pattern), places=9)
        self.assertEqual((r["since"], r["until"]), ("2024-01-05", self.weeks(60)[-1]))

    def test_deposits_are_taken_out_of_every_weeks_return(self):
        """$100 in every week on a growing account: the returns are still the pattern's exactly, not the pattern plus
        what was put in. A week with a deposit over half its opening value is left out of the swing and the beta."""
        r = history.risk(self.curve(flow=100.0))
        pattern = [self.MARKET[i % len(self.MARKET)] for i in range(59)]
        self.assertAlmostEqual(r["beta"]["slope"], 1.5, places=9)
        self.assertAlmostEqual(r["swing"]["market"], self.swing(pattern), places=9)
        big = history.risk(self.curve(big=5000.0, deposit_week=30))
        self.assertEqual(big["weeks"], 58)                                  # the week of the $5,000 is not counted
        self.assertAlmostEqual(big["beta"]["slope"], 1.5, places=6)         # and the rest are untouched

    def test_a_week_with_no_close_is_not_a_two_week_return(self):
        r = history.risk(self.curve(gap=20))
        self.assertEqual(r["weeks"], 57)                                    # 59 returns, the joined fortnight not one of them
        self.assertAlmostEqual(r["beta"]["slope"], 1.5, places=6)

    def test_too_few_weeks_say_so_instead_of_a_number(self):
        r = history.risk(self.curve(n=40))
        self.assertEqual(list(r), ["why"])
        self.assertIn(str(history.RISK_MIN_WEEKS), r["why"])
        self.assertEqual(history.risk({"why": "the rebuild does not tie"}), {"why": "the rebuild does not tie"})
        self.assertEqual(list(history.risk(None)), ["why"])

    def test_the_reason_names_what_is_missing_in_plain_words(self):
        two = {"days": ["2024-01-05", "2024-01-12"], "account": [100.0, 101.0], "market": [100.0, 101.0], "net": [100.0, 100.0]}
        self.assertEqual(history.risk(two)["why"], "only 1 whole week is known, and it takes 52 (a year) to say anything about a swing")
        none = dict(two, days=["2024-01-05", "2024-01-19"])                       # a fortnight is not a whole week
        self.assertEqual(history.risk(none)["why"], "no whole week is known, and it takes 52 (a year) to say anything about a swing")
        blind = dict(two, market=[None, None])
        self.assertIn("closes are not stored", history.risk(blind)["why"])

    def test_the_worst_fall_by_hand(self):
        days = ["2024-01-05", "2024-01-12", "2024-01-19", "2024-01-26", "2024-02-02", "2024-02-09"]
        values = [100.0, 120.0, 90.0, 95.0, 130.0, 104.0]
        returns = [b / a - 1 for a, b in zip(values, values[1:])]
        fall = history._worst_fall(days, returns)
        self.assertAlmostEqual(fall["depth"], 0.25)                         # 120 down to 90
        self.assertEqual((fall["peak"], fall["trough"], fall["back"]), ("2024-01-12", "2024-01-19", "2024-02-02"))
        rising = history._worst_fall(days, [0.1] * 5)
        self.assertEqual((rising["depth"], rising["back"]), (0.0, None))
        never = history._worst_fall(days, [-0.1, -0.1, -0.1, 0.1, 0.1])
        self.assertAlmostEqual(never["depth"], 1 - 0.9 ** 3)
        self.assertIsNone(never["back"])                                    # 0.729 x 1.21 is 0.882: not back to 1
        self.assertEqual(never["peak"], "2024-01-05")

    def test_a_market_that_never_moves_cannot_be_set_against(self):
        c = self.curve()
        c["market"] = [1000.0] * len(c["days"])
        c["net"] = [1000.0] * len(c["days"])
        c["account"] = [1000.0 + 0.01 * i for i in range(len(c["days"]))]
        self.assertEqual(list(history.risk(c)), ["why"])

    def test_it_is_carried_in_the_history(self):
        case = HistoryTests()
        h = case.build(case.account(), case.dense())
        self.assertEqual(h["risk"], history.risk(h["curve"]))

    def test_the_page_draws_it_from_the_histories_words_and_numbers(self):
        page = page_source()
        body = template_function("renderRisk", page)
        self.assertIn('id="riskCard"', page)
        self.assertIn("'renderRisk'", template_function("renderAll", page))
        self.assertIn("$('riskCard').hidden = !R || !!DATA.as_of;", body)    # no history, or a past day, no card
        self.assertIn("esc(sentence(R.why))", body)                         # a withheld one says why in history.py's words
        for owned in ("52", "50%", "1.96", "95%"):                          # what history.py and uncertainty.py own reaches the page as data
            self.assertNotIn(owned, body, owned)
        self.assertIn("pct(R.flow_weight)", body)
        self.assertIn("pct(R.max_flow)", body)
        self.assertIn("B.level", body)
        self.assertNotIn("critical", body)                                   # no figure is coloured as good or bad

    def test_the_evidence_register_states_what_the_code_uses(self):
        text = read(os.path.join(ROOT, "docs", "EVIDENCE.md"))
        self.assertIn(f"At least {history.RISK_MIN_WEEKS} whole weeks", text)
        self.assertEqual((history.RISK_FLOW_WEIGHT, history.RISK_MAX_FLOW, history.RISK_WEEKS_A_YEAR), (0.5, 0.5, 52))
        for name in ("history.RISK_FLOW_WEIGHT", "history.RISK_MAX_FLOW", "history.RISK_MIN_WEEKS", "uncertainty.slope", "rating.tilt"):
            self.assertIn(name, text, name)
