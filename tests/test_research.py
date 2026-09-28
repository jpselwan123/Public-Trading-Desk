"""The rule search: backtests, held-out statistics, corrections, power; and uncertainty.py's intervals."""
from support import *  # noqa: F401,F403


class BacktestTests(unittest.TestCase):
    def line(self, step, n=600, start=100.0):
        days, prices_, d, p = [], {}, date(2020, 1, 1), start
        for _ in range(n):
            prices_[d.isoformat()] = p
            days.append(d.isoformat())
            p *= step
            d += timedelta(days=1)
        return days, prices_

    def test_no_lookahead_a_rule_earns_the_next_days_move(self):
        days, series = self.line(1.01, 10)
        closes = [series[d] for d in days]
        # in the market only on the last day of data → no return can be earned
        pos = [0] * (len(closes) - 1) + [1]
        r = backtest.run(days, closes, pos, cost=0)
        self.assertAlmostEqual(r["final"], 1.0, places=9)

    def test_costs_are_charged_on_entry_and_exit(self):
        days, series = self.line(1.0, 10)              # flat prices
        closes = [series[d] for d in days]
        pos = [0, 1, 1, 0, 0, 0, 0, 0, 0, 0]
        r = backtest.run(days, closes, pos, cost=0.01)
        self.assertEqual(r["trades"], 2)
        self.assertAlmostEqual(r["final"], 0.99 * 0.99, places=9)

    def test_trend_rule_stays_out_below_the_average(self):
        up_days, up = self.line(1.01, 400)
        closes = [up[d] for d in up_days]
        pos = backtest.positions_trend(up_days, closes)
        self.assertEqual(pos[-1], 1)                   # rising line is above its average
        down_days, down = self.line(0.99, 400)
        dcloses = [down[d] for d in down_days]
        self.assertEqual(backtest.positions_trend(down_days, dcloses)[-1], 0)

    def test_event_rule_holds_for_five_trading_days(self):
        days, series = self.line(1.0, 30)
        closes = [series[d] for d in days]
        pos = backtest.positions_events(days, closes, [days[10]])
        self.assertEqual(sum(pos), backtest.DRIFT_HOLD)
        self.assertEqual(pos[10], 1)
        self.assertEqual(pos[15], 0)

    def test_buy_and_hold_matches_the_price_change_after_costs(self):
        days, series = self.line(1.01, 100)
        closes = [series[d] for d in days]
        r = backtest.run(days, closes, [1] * len(closes), cost=0.0)
        self.assertAlmostEqual(r["final"], closes[-1] / closes[0], places=6)

    def test_short_history_is_refused_rather_than_guessed(self):
        days, series = self.line(1.01, 50)
        self.assertIsNone(research.evaluate_ticker("ZZZ", {"ZZZ": series}))


class BacktestCorrectnessTests(unittest.TestCase):
    """The four defects fixed in phase 1, each pinned so they cannot come back."""

    def flat(self, n=500, start="2024-01-01", price=100.0):
        days, d = [], date.fromisoformat(start)
        for _ in range(n):
            days.append(d.isoformat())
            d += timedelta(days=1)
        return days, [price] * n

    def test_out_of_the_market_earns_the_cash_rate(self):
        days, closes = self.flat()
        rates = {d: 5.0 for d in days}                       # 5% a year
        cash = backtest.cash_factors(days, rates)
        flat_out = backtest.run(days, closes, [0] * len(days), cost=0, cash=cash)
        years = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days / 365.0
        self.assertAlmostEqual(flat_out["final"], 1.05 ** years, places=6)
        self.assertEqual(flat_out["trades"], 0)

    def test_without_a_cash_rate_nothing_is_invented(self):
        days, closes = self.flat()
        self.assertEqual(backtest.cash_factors(days, {}), [1.0] * (len(days) - 1))
        out = backtest.run(days, closes, [0] * len(days), cost=0, cash=None)
        self.assertAlmostEqual(out["final"], 1.0, places=9)

    def test_a_holiday_carries_the_last_published_rate(self):
        days = ["2024-01-01", "2024-01-02", "2024-01-03"]
        factors = backtest.cash_factors(days, {"2024-01-01": 5.0})
        self.assertAlmostEqual(factors[0], 1.05 ** (1 / 365.0), places=9)
        self.assertAlmostEqual(factors[1], 1.05 ** (1 / 365.0), places=9)   # carried, not zero

    def test_signals_use_printed_closes_and_returns_use_adjusted(self):
        """A 10-for-1 split: the printed price halves-and-more overnight while the
        adjusted series is smooth. A trend rule must not read that as a crash."""
        days, _ = self.flat(420)
        store = {"ZZZ": {}, "SPY": {}}
        for i, d in enumerate(days):
            printed = 100.0 if i < 400 else 10.0              # split on day 400
            adjusted = 10.0                                    # unchanged in total-return terms
            store["ZZZ"][d] = {"c": printed, "a": adjusted}
            store["SPY"][d] = {"c": 50.0, "a": 50.0}
        seen_days, signal, total = backtest._series(store, "ZZZ")
        self.assertEqual(signal[0], 100.0)                     # what the screen showed
        self.assertEqual(total[0], 10.0)                       # what the holding earned
        self.assertEqual(total[-1], 10.0)
        result = backtest.run(seen_days, total, backtest.positions_trend(seen_days, signal), cost=0)
        self.assertAlmostEqual(result["final"], 1.0, places=9)  # flat total return, whatever the signal did

    def test_an_open_position_is_not_charged_an_exit_it_never_paid(self):
        days, closes = self.flat(500)
        out = backtest.run(days, closes, [1] * len(days), cost=0.01)
        self.assertEqual(out["trades"], 1)                     # entry only
        self.assertAlmostEqual(out["final"], 0.99, places=9)

    def test_a_closed_position_is_charged_both_ways(self):
        days, closes = self.flat(500)
        positions = [1] * 250 + [0] * 250
        out = backtest.run(days, closes, positions, cost=0.01)
        self.assertEqual(out["trades"], 2)
        self.assertAlmostEqual(out["final"], 0.99 * 0.99, places=9)

    def test_short_windows_are_refused_rather_than_annualised(self):
        days, closes = self.flat(120)                          # ~4 months
        out = backtest.run(days, closes, [1] * len(days), cost=0)
        self.assertIsNone(backtest.metrics(out, days))
        long_days, long_closes = self.flat(500)
        self.assertIsNotNone(backtest.metrics(backtest.run(long_days, long_closes, [1] * 500, cost=0), long_days))

    def test_old_price_files_are_still_readable(self):
        old = {"ZZZ": {"2024-01-01": 100.0}, "updated_at": "x"}
        self.assertEqual(prices.series(old, "ZZZ"), {"2024-01-01": 100.0})
        self.assertEqual(prices.tickers(old), ["ZZZ"])
        self.assertTrue(prices.needs_refetch(old, "ZZZ"))
        fresh = {"ZZZ": {"2024-01-01": {"c": 100.0, "a": 90.0}}}
        self.assertEqual(prices.series(fresh, "ZZZ", "c"), {"2024-01-01": 100.0})
        self.assertEqual(prices.series(fresh, "ZZZ", "a"), {"2024-01-01": 90.0})
        self.assertFalse(prices.needs_refetch(fresh, "ZZZ"))

    def test_cash_rates_are_parsed_from_the_fred_csv_including_holidays(self):
        csv = "observation_date,DTB3\n2024-01-01,.\n2024-01-02,5.25\n2024-01-03,5.24\n"

        class Fake(io.BytesIO):
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                self_inner.close()
        rates = prices.fetch_cash_rates(opener=lambda req, timeout: Fake(csv.encode()), sleep=lambda s: None)
        self.assertEqual(rates, {"2024-01-02": 5.25, "2024-01-03": 5.24})


class EdgeStatisticTests(unittest.TestCase):
    """F-04: the number that is tested must be the number that is reported."""

    def series(self, mu, sd, n=2500, seed=3):
        """A series whose sample mean is exactly mu, so the two measures can be
        compared without sampling noise swamping the difference."""
        rnd = random.Random(seed)
        draws = [rnd.gauss(0.0, sd) for _ in range(n)]
        drift = sum(draws) / n
        return [d - drift + mu for d in draws]

    def test_the_bootstrapped_statistic_matches_the_reported_excess(self):
        # a calm rule against a wild benchmark: the arithmetic gap is negative while
        # the compounded gap is positive, because compounding is penalised by variance
        rule = self.series(0.00030, 0.004, seed=1)
        hold = self.series(0.00035, 0.020, seed=2)
        arithmetic = (sum(rule) / len(rule) - sum(hold) / len(hold)) * backtest.TRADING_DAYS
        out = backtest.bootstrap_edge(rule, hold, rounds=200)
        geometric = backtest._annualised(rule) - backtest._annualised(hold)
        self.assertLess(arithmetic, 0)
        self.assertGreater(geometric, 0)
        self.assertAlmostEqual(out["edge"], geometric, places=9)   # tested = reported

    def test_the_interval_brackets_the_estimate(self):
        out = backtest.bootstrap_edge(self.series(0.0004, 0.01), self.series(0.0001, 0.01, seed=9),
                                      rounds=200)
        self.assertLessEqual(out["low"], out["edge"])
        self.assertGreaterEqual(out["high"], out["edge"])

    def test_no_edge_gives_a_large_p_value(self):
        same = self.series(0.0003, 0.01, seed=4)
        out = backtest.bootstrap_edge(same, list(same), rounds=200)
        self.assertAlmostEqual(out["edge"], 0.0, places=9)
        self.assertGreater(out["p"], 0.5)

    def test_a_short_window_is_refused(self):
        self.assertIsNone(backtest.bootstrap_edge([0.001] * 30, [0.0] * 30))

    def test_the_page_receives_the_same_excess_the_gate_used(self):
        store = ResearchTests.build(self, ResearchTests.sawtooth.__get__(self))
        out = research.evaluate(store, universe=["ZZZ"])
        for rule in out["results"][0]["rules"]:
            test = rule["test"]
            self.assertIsNotNone(test["p"])
            self.assertIsNotNone(test["excess_low"])
            self.assertLessEqual(test["excess_low"], test["excess"])
            self.assertGreaterEqual(test["excess_high"], test["excess"])


class CorrectionFamilyTests(unittest.TestCase):
    """F-06: correlated tests are corrected within families, and how many were really
    independent is measured rather than assumed."""

    def test_identical_series_count_as_one_test(self):
        same = [0.001, -0.002, 0.003] * 40
        count, r = backtest.effective_tests({("a", "x"): same, ("b", "x"): list(same)})
        self.assertAlmostEqual(count, 1.0, places=6)
        self.assertAlmostEqual(r, 1.0, places=6)

    def test_unrelated_series_count_as_themselves(self):
        rnd = random.Random(2)
        series = {("f%d" % i, "x"): [rnd.gauss(0, 0.01) for _ in range(400)] for i in range(4)}
        count, r = backtest.effective_tests(series)
        self.assertGreater(count, 3.0)
        self.assertLess(abs(r), 0.15)

    def test_each_rule_belongs_to_exactly_one_family(self):
        keys = [k for keys in research.FAMILIES.values() for k in keys]
        self.assertEqual(len(keys), len(set(keys)))
        for key in list(backtest.RULES) + list(backtest.PORTFOLIO_RULES):
            self.assertNotEqual(research.family_of(key), "other", key)

    def test_q_values_are_computed_within_families(self):
        store = ResearchTests.build(self, ResearchTests.sawtooth.__get__(self))
        out = research.evaluate(store, universe=["ZZZ"])
        self.assertIn("families", out)
        for name, info in out["families"].items():
            self.assertLessEqual(info["effective"], info["tests"])
            self.assertGreaterEqual(info["effective"], 1)


class RiskTrackStatisticTests(unittest.TestCase):
    """G-06 / v3-C: the luck check must test what the track is about."""

    def series(self, n=900, seed=5):
        """A calmer rule with the same average return as holding: the Faber shape."""
        rnd = random.Random(seed)
        hold, rule = [], []
        for _ in range(n):
            day = rnd.gauss(0.0004, 0.014)
            hold.append(day)
            rule.append(day * 0.5 + 0.0002)    # half the swing, same drift
        return rule, hold

    def test_a_risk_rule_with_no_return_edge_is_invisible_to_the_return_test(self):
        rule, hold = self.series()
        cash = [0.0] * len(rule)
        by_return = backtest.bootstrap_edge(rule, hold, rounds=300, seed=2)
        by_sharpe = backtest.bootstrap_edge(rule, hold, rounds=300, seed=2,
                                            statistic="sharpe", cash_returns=cash)
        self.assertEqual(by_return["statistic"], "return")
        self.assertEqual(by_sharpe["statistic"], "sharpe")
        self.assertGreater(by_sharpe["edge"], 0)              # clearly better per unit of risk
        self.assertLess(by_sharpe["p"], by_return["p"])       # and the return test cannot see it

    def test_a_risk_rule_with_no_return_edge_can_still_clear(self):
        """The rule that used to fail by construction: same return, smaller fall."""
        rule = {"claim": "risk", "majority": True,
                "blocks": [{"ahead": True}, {"ahead": True}, {"ahead": False}],
                "test": {"excess": 0.0, "q": 0.01, "sharpe": 0.8, "hold_sharpe": 0.5,
                         "worst_drop": -0.18, "hold_worst_drop": -0.36}}
        clears, reasons = research.passes(rule, 12)
        self.assertTrue(clears, reasons)

    def test_a_drawdown_reduction_within_noise_does_not_clear(self):
        """v3-D / H-03: a rule whose fall is barely shallower than holding's no
        longer clears or fails on that basis. What decides it is the Sharpe test,
        which is the one statistic on this track measured against luck."""
        barely = {"claim": "risk", "majority": True,
                  "blocks": [{"ahead": True}, {"ahead": True}, {"ahead": False}],
                  "test": {"excess": 0.0, "q": 0.9, "sharpe": 0.8, "hold_sharpe": 0.5,
                           "worst_drop": -0.35, "hold_worst_drop": -0.36}}
        clears, reasons = research.passes(barely, 12)
        self.assertFalse(clears)
        self.assertIn("return per unit of risk not distinguishable from luck", reasons)
        self.assertNotIn("did not cut the worst fall", reasons)
        # and a deep cut does not rescue a rule whose Sharpe is not distinguishable
        deep = dict(barely, test=dict(barely["test"], worst_drop=-0.10))
        self.assertTrue(research.cut_the_fall(deep["test"]))
        self.assertFalse(research.passes(deep, 12)[0])

    def test_the_reason_names_the_statistic_that_was_tested(self):
        base = {"majority": True, "blocks": [{"ahead": True}, {"ahead": True}],
                "test": {"excess": 0.0, "q": 0.9, "sharpe": 0.8, "hold_sharpe": 0.5,
                         "worst_drop": -0.18, "hold_worst_drop": -0.36}}
        _, risk = research.passes(dict(base, claim="risk"), 12)
        _, ret = research.passes(dict(base, claim="return"), 12)
        self.assertIn("return per unit of risk not distinguishable from luck", risk)
        self.assertIn("edge not distinguishable from luck", ret)

    def test_sharpe_needs_the_cash_rate_and_says_so_by_refusing(self):
        rule, hold = self.series()
        self.assertIsNone(backtest.bootstrap_edge(rule, hold, rounds=50, statistic="sharpe"))

    def test_the_return_track_is_unchanged(self):
        rule, hold = self.series()
        before = backtest.bootstrap_edge(rule, hold, rounds=200, seed=7)
        after = backtest.bootstrap_edge(rule, hold, rounds=200, seed=7, statistic=None)
        self.assertEqual(before["p"], after["p"])
        self.assertEqual(before["edge"], after["edge"])


class EffectiveCorrectionTests(unittest.TestCase):
    """G-07: the effective test count was displayed but never applied."""

    def test_the_override_changes_the_correction(self):
        pairs = [(("A", "r"), 0.001), (("B", "r"), 0.02), (("C", "r"), 0.40)]
        full = backtest.benjamini_hochberg(pairs)
        reduced = backtest.benjamini_hochberg(pairs, m=1.5)
        self.assertAlmostEqual(full[("A", "r")], 0.003)       # 0.001 x 3 / 1
        self.assertLess(reduced[("A", "r")], full[("A", "r")])

    def test_a_q_value_is_never_below_its_own_p(self):
        """With m below the number of tests the arithmetic can produce one, and it
        would say the correction made the evidence stronger."""
        pairs = [((str(i), "r"), 0.01 * (i + 1)) for i in range(20)]
        q = backtest.benjamini_hochberg(pairs, m=2)
        for key, p in pairs:
            self.assertGreaterEqual(q[key], p, key)

    def test_the_override_is_bounded_by_the_real_test_count(self):
        pairs = [(("A", "r"), 0.01), (("B", "r"), 0.02)]
        self.assertEqual(backtest.benjamini_hochberg(pairs, m=99),
                         backtest.benjamini_hochberg(pairs))       # never harsher than m
        self.assertEqual(backtest.benjamini_hochberg(pairs, m=0),
                         backtest.benjamini_hochberg(pairs, m=1))  # never below one

    def test_the_reported_effective_count_matches_the_correction_applied(self):
        """The number on the page must be the number doing the correcting.

        Run on synthetic prices, not on research.json: that file is git-ignored, so a
        test reading it passes here and fails on a clean checkout — which is what it
        did."""
        store = ResearchTests.build(self, ResearchTests.sawtooth.__get__(self))
        out = research.evaluate(store, universe=["ZZZ"])
        families = out.get("families") or {}
        self.assertTrue(families)
        for name, info in families.items():
            self.assertIn("applied", info)
            expected = info["effective"] if info["effective"] else info["tests"]
            self.assertEqual(info["applied"], expected, name)
            self.assertLessEqual(info["applied"], info["tests"], name)

    def test_the_correction_actually_receives_the_effective_count(self):
        """Not just that the numbers agree on paper — that the value reaches BH."""
        seen, real = [], backtest.benjamini_hochberg

        def watched(pairs, m=None):
            seen.append(m)
            return real(pairs, m)
        store = ResearchTests.build(self, ResearchTests.sawtooth.__get__(self))
        backtest.benjamini_hochberg = watched
        try:
            out = research.evaluate(store, universe=["ZZZ"])
        finally:
            backtest.benjamini_hochberg = real
        self.assertTrue(seen)
        self.assertNotIn(None, seen, "the correction was called without a family size")
        self.assertEqual(sorted(seen),
                         sorted(f["applied"] for f in out["families"].values()))


class PassMarkTrackTests(unittest.TestCase):
    """F-03: a rule is judged against the claim its own source paper makes."""

    def test_every_rule_declares_its_source_claim(self):
        for name, rules in (("RULES", backtest.RULES), ("PORTFOLIO_RULES", backtest.PORTFOLIO_RULES)):
            for key, rule in rules.items():
                self.assertIn(rule.get("claim"), ("return", "risk"), f"{name}[{key}]")

    def test_the_claim_comes_from_the_paper_not_the_result(self):
        self.assertEqual(backtest.RULES["trend_200"]["claim"], "risk")
        self.assertEqual(backtest.RULES["vol_managed"]["claim"], "risk")
        self.assertEqual(backtest.RULES["momentum_12_1"]["claim"], "return")
        self.assertEqual(backtest.PORTFOLIO_RULES["low_volatility"]["claim"], "risk")

    def base(self, **test):
        row = {"test": {"excess": 0.05, "q": 0.01, "sharpe": 0.9, "hold_sharpe": 0.8,
                        "worst_drop": -0.20, "hold_worst_drop": -0.36},
               "majority": True, "blocks": [{"ahead": True}, {"ahead": True}, {"ahead": False}]}
        row["test"].update(test)
        return row

    def test_a_risk_rule_is_not_disqualified_for_a_lower_return(self):
        row = dict(self.base(excess=-0.02), claim="risk")
        ok, reasons = research.passes(row, 12)
        self.assertTrue(ok, reasons)

    def test_the_fall_is_reported_and_no_longer_gates(self):
        """v3-D: the worst fall is one extreme value from one path and decided the
        risk track close to at random, so it is reported and gates nothing. It used
        to be the track's defining condition — this test asserted that."""
        row = dict(self.base(excess=-0.02, worst_drop=-0.35), claim="risk")
        ok, reasons = research.passes(row, 12)
        self.assertTrue(ok, reasons)
        self.assertNotIn("did not cut the worst fall", reasons)
        self.assertFalse(research.cut_the_fall(row["test"]))     # still measured

    def test_a_return_rule_still_has_to_beat_holding(self):
        row = dict(self.base(excess=-0.02), claim="return")
        ok, reasons = research.passes(row, 12)
        self.assertFalse(ok)
        self.assertIn("behind buy-and-hold out of sample", reasons)

    def test_the_other_conditions_apply_to_both_tracks(self):
        for track in ("return", "risk"):
            self.assertFalse(research.passes(dict(self.base(q=0.5), claim=track), 12)[0])
            self.assertFalse(research.passes(dict(self.base(sharpe=0.1), claim=track), 12)[0])
            self.assertFalse(research.passes(dict(self.base(), claim=track, majority=False), 12)[0])


class PowerTests(unittest.TestCase):
    """F-07: a test that finds nothing is only informative if it could have found
    something. These check the harness that measures that."""

    # 120 resamples cannot reach a family-of-52 threshold, and the harness now says so
    # rather than reporting a non-detection. These two only ever checked the raw rate,
    # so they run against a small family where that resolution is honest.
    SMALL_FAMILY = 3

    def test_power_harness_detects_a_large_planted_edge(self):
        import power
        raw, _ = power.detection_rate(0.20, 8.4, trials=6, rounds=120,
                                      family=self.SMALL_FAMILY, seed=3)
        self.assertGreater(raw, 0.5)                 # a 20%/yr edge is usually seen

    def test_a_planted_edge_of_zero_is_rarely_flagged(self):
        import power
        raw, _ = power.detection_rate(0.0, 8.4, trials=6, rounds=120,
                                      family=self.SMALL_FAMILY, seed=5)
        self.assertLess(raw, 0.5)

    def test_the_harness_defaults_to_the_production_resample_count(self):
        """G-09: it ran 400 against a production 1,000, measuring a setting nobody
        uses. The refusal in detection_rate is what stops that being silent."""
        import power
        self.assertEqual(power.default_rounds(), backtest.BOOTSTRAP_ROUNDS)
        self.assertNotIn("rounds=400", read(os.path.join(ROOT, "power.py")))
        # production only just clears its own floor; if that ever reverses, the
        # harness must refuse rather than report zeros
        self.assertLess(backtest.floor_p(power.default_rounds()),
                        power.corrected_threshold(research.applied_family_size()))

    def test_the_harness_measures_the_families_the_search_uses(self):
        """G-08: a constant 52 described the single family v1 and v2 used, which F-06
        replaced with three. The harness was measuring a design already retired."""
        self.assertEqual(research.nominal_family_sizes(),
                         {"time_series": len(research.FAMILIES["time_series"]) * len(backtest.UNIVERSE),
                          "portfolio": len(research.FAMILIES["portfolio"]),
                          "event": len(research.FAMILIES["event"])})
        self.assertNotIn("FAMILY_SIZE", read(os.path.join(ROOT, "power.py")))

    def test_the_harness_corrects_at_the_same_threshold_as_the_search(self):
        """H-02: the search corrected at the effective count and the harness at the
        raw one, so the published power table used a bar fourteen times stricter than
        any rule actually faces. This is the test that stops a third occurrence.

        It asserts the two agree, not that they equal a particular number — a clean
        checkout has no research.json and both fall back to the same nominal counts."""
        import power
        store = ResearchTests.build(self, ResearchTests.sawtooth.__get__(self))
        out = research.evaluate(store, universe=["ZZZ"])
        for name, info in out["families"].items():
            self.assertEqual(info["applied"],
                             research.applied_family_size(name, measured=out["families"]), name)
        strictest = max(f["applied"] for f in out["families"].values())
        self.assertEqual(research.applied_family_size(measured=out["families"]), strictest)
        # and the harness takes its threshold from that same function, not a copy
        self.assertEqual(power.corrected_threshold(research.applied_family_size()),
                         research.Q_LIMIT / research.applied_family_size())

    def test_no_other_module_defines_its_own_family_size(self):
        """The standing rule after G-05 and H-02: one definition, and deleting the
        second copy is the fix rather than correcting it."""
        for name in ("power.py", "build_desk.py", "server.py"):
            source = read(os.path.join(ROOT, name))
            self.assertNotIn("len(backtest.UNIVERSE)", source, name)
            self.assertNotIn("FAMILIES.items()", source, name)

    def test_the_bootstrap_floor_is_below_the_correction_threshold(self):
        """G-05: p is (hits+1)/(rounds+1), so no p below 1/(rounds+1) is reachable.
        A threshold under that floor cannot be cleared by any edge, however large."""
        import power
        self.assertAlmostEqual(backtest.floor_p(999), 0.001)
        for family in (3, 48, 52):
            rounds = power.required_rounds(family)
            self.assertLess(backtest.floor_p(rounds), power.corrected_threshold(family))
        # the configuration that produced "corrected power is zero at every size"
        self.assertGreater(backtest.floor_p(400), power.corrected_threshold(52))

    def test_the_harness_refuses_a_threshold_it_cannot_reach(self):
        """It used to report 0.00, which reads as 'the design cannot detect this'."""
        import power
        with self.assertRaises(power.PowerError) as cm:
            power.detection_rate(0.50, 3.6, trials=1, family=52, rounds=400)
        self.assertIn("cannot reach", str(cm.exception))

    def test_a_huge_planted_edge_is_detected_after_correction(self):
        """The test that would have caught G-05: with enough resolution, a very large
        edge must clear the corrected threshold. It used to read 0.00 at every size."""
        import power
        family = 3
        _, corrected = power.detection_rate(0.40, 3.6, trials=8, family=family,
                                            rounds=power.required_rounds(family), seed=17)
        self.assertGreater(corrected, 0.8)

    def test_the_production_correction_is_reachable_at_all(self):
        """The same floor, in the real search rather than the harness.

        The largest family is the 4 time-series rules across 12 funds. At 1,000
        resamples the smallest p reachable is 0.000999, so the best q a perfect rule
        could reach is 0.000999 x 48 = 0.048 — inside the 0.05 limit by 4%. At 51
        tests it would be 0.051 and nothing could ever clear, whatever the evidence.
        The pre-registration declared "~52-56" tests, so this is not hypothetical."""
        floor = backtest.floor_p(backtest.BOOTSTRAP_ROUNDS)
        largest = max(len(rules) * len(backtest.UNIVERSE) if name == "time_series"
                      else len(rules) for name, rules in research.FAMILIES.items())
        self.assertLess(floor * largest, research.Q_LIMIT,
                        "no rule could clear %d tests at %d resamples, however real its edge"
                        % (largest, backtest.BOOTSTRAP_ROUNDS))

    def test_the_reported_p_says_when_it_is_at_the_floor(self):
        rule = [0.01] * 300                       # an edge no resample can match
        hold = [0.0] * 300
        out = backtest.bootstrap_edge(rule, hold, rounds=99, seed=1)
        self.assertTrue(out["at_floor"])
        self.assertAlmostEqual(out["p"], out["floor"])
        self.assertAlmostEqual(out["floor"], 0.01)

    def test_the_cache_is_dropped_when_the_design_changes(self):
        import power
        folder = tempfile.mkdtemp()
        real, power.POWER_FILE = power.POWER_FILE, os.path.join(folder, "power.json")
        try:
            measured = {"mde": {}, "signature": power.signature()}
            with open(power.POWER_FILE, "w") as f:
                json.dump(measured, f)
            self.assertTrue(power.load())
            stale = dict(measured, signature=dict(power.signature(), block_days=999))
            with open(power.POWER_FILE, "w") as f:
                json.dump(stale, f)
            self.assertEqual(power.load(), {})
        finally:
            power.POWER_FILE = real

    def test_the_page_reports_what_the_test_could_detect(self):
        page = build_desk.build_research({"results": [], "by_rule": [], "tested": 52, "clears": 0,
                                          "power": {"mde": {"v2": {"edge": 0.2, "years": 8.4, "above": False}},
                                                    "trials": 120, "target_power": 0.8}})
        self.assertEqual(page["power"]["mde"]["v2"]["edge"], 0.2)

    def test_the_verdict_never_claims_the_rules_do_not_work(self):
        template = page_source()
        self.assertNotIn("No rule works", template)
        self.assertIn("No rule showed an edge this test could detect", template)


class ResearchTests(unittest.TestCase):
    """Phase 2: a fixed universe, a held-out sample, and statistics that allow for luck."""

    def build(self, shape, n=2600, start="2016-01-04"):
        """shape(i) → price. Returns a price store with a flat SPY for company."""
        days, d = [], date.fromisoformat(start)
        for _ in range(n):
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        store = {"SPY": {}, "ZZZ": {}, prices.CASH_KEY: {}}
        for i, day in enumerate(days):
            price = shape(i)
            store["ZZZ"][day] = {"c": price, "a": price}
            store["SPY"][day] = {"c": 100.0, "a": 100.0}
            store[prices.CASH_KEY][day] = 2.0
        return store

    def sawtooth(self, i):
        """Six months doubling, six months halving — a trend rule should dodge the falls."""
        cycle, step = 250, i % 250
        return 100.0 * (1.004 ** step if step < cycle // 2 else 1.004 ** (cycle - step))

    def test_split_keeps_the_last_30_percent_unseen(self):
        days = [f"2020-01-{d:02d}" for d in range(1, 11)]
        self.assertEqual(backtest.split_point(days, 0.30), 7)

    def test_an_edge_needs_more_than_a_few_market_cycles(self):
        """A rule can be ahead and still not clear: three cycles is not evidence,
        and the block bootstrap says so rather than flattering it."""
        out = research.evaluate(self.build(self.sawtooth), universe=["ZZZ"])
        rule = next(r for r in out["results"][0]["rules"] if r["key"] == "trend_200")
        self.assertGreater(rule["test"]["excess"], 0)          # ahead of holding
        self.assertGreater(rule["test"]["p"], research.Q_LIMIT)  # but not distinguishable from luck
        self.assertFalse(rule["clears"])

    def test_clearing_needs_every_pre_registered_condition(self):
        """PREREGISTRATION.md section 5: five conditions, all required."""
        full = {"test": {"excess": 0.05, "q": 0.01, "sharpe": 0.9, "hold_sharpe": 0.8},
                "majority": True,
                "blocks": [{"ahead": True}, {"ahead": True}, {"ahead": False}]}
        ok, reasons = research.passes(full, 12)
        self.assertTrue(ok, reasons)

        def broken(**changes):
            import copy
            row = copy.deepcopy(full)
            row["test"].update({k: v for k, v in changes.items() if k in row["test"]})
            for k, v in changes.items():
                if k not in row["test"]:
                    row[k] = v
            return research.passes(row, 12)

        self.assertFalse(broken(excess=-0.01)[0])                      # behind out of sample
        self.assertFalse(broken(q=0.20)[0])                            # could be luck
        self.assertFalse(broken(majority=False)[0])                    # worked in a minority of funds
        self.assertFalse(broken(sharpe=0.5)[0])                        # worse per unit of risk
        self.assertFalse(broken(blocks=[{"ahead": True}, {"ahead": False}, {"ahead": False}])[0])
        self.assertIn("luck", broken(q=0.20)[1][0])

    def test_walk_forward_splits_the_held_out_years(self):
        days, d = [], date(2024, 1, 1)
        while len(days) < 300:                       # the split needs 60+ days per block
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        rule = [0.001] * len(days)
        hold = [0.0] * len(days)
        blocks = research.walk_forward(days, rule, hold, blocks=3)
        self.assertEqual(len(blocks), 3)
        self.assertTrue(all(b["ahead"] for b in blocks))
        mixed = research.walk_forward(days, [0.001] * 90 + [-0.002] * (len(days) - 90), hold, blocks=3)
        self.assertLess(sum(1 for b in mixed if b["ahead"]), 3)
        self.assertIsNone(research.walk_forward(days[:60], rule[:60], hold[:60], blocks=3))

    def test_block_labels_line_up_with_the_returns(self):
        """F-12: run() starts its curve the day after the window opens."""
        days, d = [], date(2024, 1, 1)
        while len(days) < 300:
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        returns = [0.001] * (len(days) - 1)
        blocks = research.walk_forward(days[1:], returns, [0.0] * len(returns), blocks=3)
        self.assertEqual(blocks[0]["from"], days[1])
        self.assertEqual(blocks[-1]["to"], days[-1])
        self.assertIsNone(research.walk_forward(days[:10], returns, returns, blocks=3))

    def test_a_weighted_rule_costs_only_what_it_changes(self):
        days = [f"2024-01-{d:02d}" for d in range(1, 11)]
        closes = [100.0] * 10
        half = backtest.run(days, closes, [0.5] * 10, cost=0.01)
        full = backtest.run(days, closes, [1.0] * 10, cost=0.01)
        self.assertAlmostEqual(half["final"], 0.995, places=9)
        self.assertAlmostEqual(full["final"], 0.99, places=9)
        self.assertAlmostEqual(half["turnover"], 0.5, places=9)

    def test_the_equal_weight_benchmark_is_always_fully_invested(self):
        """F-05: funds starting at different dates must not leave the benchmark in cash."""
        days, d = [], date(2020, 1, 1)
        while len(days) < 700:
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        series = {}
        for n, ticker in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"]):
            starts = 0 if n < 2 else 300 + n * 40          # three funds start late
            series[ticker] = {day: 100.0 for day in days[starts:]}
        weights = backtest.weights_equal(days, series)
        for i in (0, 100, 350, 500, len(days) - 1):
            self.assertAlmostEqual(sum(weights[i].values()), 1.0, places=9,
                                   msg=f"day {days[i]} is not fully invested")
        self.assertEqual(len(weights[0]), 2)               # only the two that existed
        self.assertEqual(len(weights[-1]), 5)

    def test_a_rule_that_finds_too_few_funds_still_leaves_the_rest_in_cash(self):
        """The trend-filtered rule deliberately holds cash; that must not change."""
        days, d = [], date(2020, 1, 1)
        while len(days) < 400:
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        series = {t: {day: 100.0 for day in days} for t in ("AAA", "BBB")}
        weights = backtest._monthly_weights(days, series, lambda i, d, s: ["AAA"], pick=backtest.PICK_N)
        self.assertAlmostEqual(sum(weights[-1].values()), 1 / 3, places=9)

    def test_sector_rules_hold_three_funds_and_rebalance_monthly(self):
        days, series = [], {}
        d = date(2020, 1, 1)
        for _ in range(900):
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        for n, ticker in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"]):
            series[ticker] = {day: 100.0 * (1 + n * 0.0005) ** i for i, day in enumerate(days)}
        weights = backtest.weights_sector_momentum(days, series)
        picked = weights[-1]
        self.assertEqual(len(picked), backtest.PICK_N)
        self.assertAlmostEqual(sum(picked.values()), 1.0, places=6)
        self.assertEqual(set(picked), {"CCC", "DDD", "EEE"})           # the three fastest risers
        changes = sum(1 for i in range(1, len(weights)) if weights[i] != weights[i - 1])
        self.assertLess(changes, 40)                                   # monthly, not daily

    def test_a_rule_with_no_edge_does_not_clear(self):
        rnd = random.Random(7)
        walk = [100.0]
        for _ in range(2600):
            walk.append(walk[-1] * (1 + rnd.gauss(0.0003, 0.012)))
        out = research.evaluate(self.build(lambda i: walk[i]), universe=["ZZZ"])
        for rule in out["results"][0]["rules"]:
            self.assertFalse(rule["clears"], rule["key"])
            self.assertIsNotNone(rule["test"]["p"])

    def test_train_and_test_are_reported_separately(self):
        out = research.evaluate(self.build(self.sawtooth), universe=["ZZZ"])
        rule = out["results"][0]["rules"][0]
        self.assertIn("train", rule)
        self.assertIn("test", rule)
        self.assertNotEqual(rule["train"]["years"], rule["test"]["years"])
        self.assertIsNone(rule["train"]["p"])            # no statistic on the part we looked at
        for field in ("vol", "sharpe", "trades", "excess", "worst_drop"):
            self.assertIn(field, rule["test"])

    def test_the_universe_is_fixed_not_the_watchlist(self):
        self.assertIn("SPY", backtest.UNIVERSE)
        self.assertIn("XLE", backtest.UNIVERSE)
        self.assertEqual(len(backtest.UNIVERSE), 12)
        source = read(os.path.join(ROOT, "research.py"))
        self.assertNotIn("load_watchlist", source)

    def test_the_event_sample_is_marked_as_the_weaker_sample(self):
        store = self.build(self.sawtooth)
        store["AAA"] = store["ZZZ"]
        out = research.evaluate(store, universe=["ZZZ"], extra_tickers=["AAA"],
                                event_days_by_ticker={"AAA": sorted(store["AAA"])[::40]})
        samples = {r["ticker"]: r["sample"] for r in out["results"]}
        self.assertEqual(samples["ZZZ"], "universe")
        self.assertEqual(samples["AAA"], "event_sample")
        extra = next(r for r in out["results"] if r["ticker"] == "AAA")
        self.assertEqual([x["key"] for x in extra["rules"]], ["results_5d"])

    def test_following_a_company_does_not_change_the_tests(self):
        """S-16: rule H's sample is fixed in code, the share of the run of record. The
        watchlist grew to eight and the family from 52 tests to 59; now filings for any
        other company leave the event tests as they were, and a share that stops being
        followed keeps the results days already found."""
        self.assertEqual(research.EVENT_SAMPLE, ("AMD",))
        store = self.build(self.sawtooth)
        store["AMD"] = store["MSFT"] = store["ZZZ"]
        days = sorted(store["ZZZ"])[::40]
        result = lambda t, d: {"ticker": t, "form": "8-K", "date": d, "what": "Results announced", "label": ""}
        items = [result("AMD", d) for d in days] + [result("MSFT", d) for d in days]
        self.assertEqual(research.event_days_from(items), {"AMD": days})       # MSFT is not in the sample
        real = backtest.UNIVERSE
        backtest.UNIVERSE = ("ZZZ",)
        try:
            followed = research.update(store, items)
            dropped = research.update(store, [], stored=followed)              # AMD no longer followed
        finally:
            backtest.UNIVERSE = real
        for out in (followed, dropped):
            self.assertEqual(sorted(r["ticker"] for r in out["results"]), ["AMD", "ZZZ"])
            self.assertEqual(out["event_sample"], ["AMD"])
        self.assertEqual(dropped["event_days"], {"AMD": days})
        self.assertEqual(followed["tested"], dropped["tested"])
        # the page names the share from the run, through build_research to the template
        self.assertEqual(build_desk.build_research(followed)["event_sample"], ["AMD"])
        self.assertIn("R.event_sample", template_function("renderResearch"))

    def test_the_event_rule_is_judged_on_the_shares_it_ran_on(self):
        """S-26: "positive in more than half the funds it was tested on" was counted over
        the funds alone. Rule H never runs on a fund, so its count was 0 and it failed
        the condition whatever it did; a share where it works must pass it."""
        store = self.build(lambda i: 100.0 * 1.0004 ** i)
        store["AAA"] = {d: dict(v) for d, v in store["ZZZ"].items()}
        days = sorted(store["AAA"])
        events = days[::20]
        bumped, level = {}, 100.0                     # a rise in the five days after each event
        for i, d in enumerate(days):
            after = any(0 < i - days.index(e) <= 5 for e in events if e < d)
            level *= 1.01 if after else 0.9995
            bumped[d] = {"c": level, "a": level}
        store["AAA"] = bumped
        out = research.evaluate(store, universe=["ZZZ"], extra_tickers=["AAA"], event_days_by_ticker={"AAA": events})
        rule = next(r for r in out["results"] if r["ticker"] == "AAA")["rules"][0]
        self.assertGreater(rule["test"]["excess"], 0)
        self.assertTrue(rule["majority"])
        self.assertNotIn("worked in fewer than half the shares", rule["failed"])
        self.assertIn("unit = rule.sample === 'event_sample' ? 'share' : 'fund'", template_function("renderResearch"))

    def test_the_refresh_prices_what_the_research_tests(self):
        """S-20: the refresh priced only followed companies and practice holdings, so
        the sector funds' closes stopped on the day they were first fetched (18
        September, while followed shares ran on) and every re-run tested stale funds."""
        self.assertEqual(research.sample(), list(backtest.UNIVERSE) + ["AMD"])
        source = inspect.getsource(server.Handler.update_research)
        self.assertIn("research.sample()", source)
        self.assertIn("research.sample()", inspect.getsource(prices.main))

    def test_an_unchanged_search_is_not_run_again(self):
        """The search is most of a minute of computing, and ran on every refresh. With
        the same prices, cash rate, results days and code — the seed is fixed — the
        stored answer is the answer. A new close, a new results day or new code runs it."""
        calls, real = [], research.evaluate
        research.evaluate = lambda *a, **k: calls.append(1) or {"results": []}
        try:
            store = {"SPY": {"2026-09-24": {"c": 1.0, "a": 1.0}}, prices.CASH_KEY: {"2026-09-24": 4.0},
                     "KO": {"2026-09-24": {"c": 9.0, "a": 9.0}}}
            first = research.update(store, [])
            self.assertIs(research.update(store, [], stored=first), first)
            store["KO"]["2026-09-25"] = {"c": 9.9, "a": 9.9}           # not in the search's sample
            self.assertIs(research.update(store, [], stored=first), first)
            self.assertEqual(len(calls), 1)
            store["SPY"]["2026-09-25"] = {"c": 1.1, "a": 1.1}          # a new close
            second = research.update(store, [], stored=first)
            research.update(store, [], stored=dict(second, event_days={"AMD": ["2026-07-28"]}))
            self.assertEqual(len(calls), 3)
        finally:
            research.evaluate = real
        self.assertNotEqual(research.fingerprint(store, {}, code=b"a"), research.fingerprint(store, {}, code=b"b"))

    def test_q_values_cover_every_test_together(self):
        store = self.build(self.sawtooth)
        store["BBB"] = store["ZZZ"]
        out = research.evaluate(store, universe=["ZZZ", "BBB"])
        qs = [r["test"]["q"] for res in out["results"] for r in res["rules"]]
        ps = [r["test"]["p"] for res in out["results"] for r in res["rules"]]
        self.assertEqual(out["tested"], len(ps))
        for p, q in zip(ps, qs):
            self.assertGreaterEqual(q + 1e-9, p)         # correction never lowers a p-value

    def test_short_histories_are_skipped_rather_than_judged(self):
        store = self.build(self.sawtooth, n=300)
        self.assertIsNone(research.evaluate_ticker("ZZZ", store))

    def test_the_page_shows_exactly_what_was_measured(self):
        out = research.evaluate(self.build(self.sawtooth), universe=["ZZZ"])
        page = build_desk.build_research(out)
        self.assertEqual(page["tested"], out["tested"])
        self.assertEqual(page["clears"], out["clears"])
        self.assertEqual(page["by_rule"], out["by_rule"])


class UncertaintyTests(unittest.TestCase):
    """Phase 5: every interval on a count or a median comes from uncertainty.py."""

    def test_the_interval_matches_published_values(self):
        """Newcombe (1998), Statistics in Medicine 17, table I, method 5 (exact)."""
        published = {(81, 263): (0.2527, 0.3676), (15, 148): (0.0578, 0.1617),
                     (0, 20): (0.0, 0.1684), (1, 29): (0.0009, 0.1776)}
        for (k, n), (low, high) in published.items():
            p = uncertainty.proportion(k, n)
            self.assertEqual((round(p["low"], 4), round(p["high"], 4)), (low, high), (k, n))
            self.assertEqual(p["estimate"], k / n)

    def test_four_of_four_is_not_distinguishable_from_chance(self):
        four = uncertainty.against_chance(4, 4)
        self.assertFalse(four["distinguishable"])
        self.assertEqual(four["reads"], "uncertain")
        self.assertAlmostEqual(four["low"], 0.3976, places=4)
        # Wilson's interval (the review's choice) would be 51%-100% and call this a
        # finding, though a fair coin lands four of a kind one time in eight
        self.assertEqual(2 * 0.5 ** 4, 1 / 8)

    def test_seven_of_twenty_nine_is_a_real_shortfall(self):
        seven = uncertainty.against_chance(7, 29)
        self.assertTrue(seven["distinguishable"])
        self.assertEqual(seven["reads"], "measured")
        self.assertEqual(seven["expected_count"], 14.5)

    def test_an_interval_spanning_the_null_reads_as_uncertain(self):
        eleven = uncertainty.against_chance(11, 25)
        self.assertLess(eleven["low"], 0.5)
        self.assertGreater(eleven["high"], 0.5)
        self.assertEqual(eleven["reads"], "uncertain")
        moves = uncertainty.median([0.02, -0.01, 0.03, -0.02, 0.01, 0.04, -0.03, 0.02], expected=0)
        self.assertLess(moves["low"], 0)
        self.assertEqual(moves["reads"], "uncertain")

    def test_the_median_and_the_count_of_ups_never_disagree(self):
        """Both invert the same sign test, so one card line cannot say the median
        moved while the ups cannot be told from half."""
        for n in range(1, 61):
            for k in range(n + 1):
                values = [0.01 * (i + 1) for i in range(k)] + [-0.01 * (i + 1) for i in range(n - k)]
                moved = uncertainty.median(values, expected=0)
                ups = uncertainty.against_chance(k, n)
                self.assertEqual(moved["distinguishable"], ups["distinguishable"], (k, n))

    def test_the_median_interval_is_the_order_statistic_one(self):
        values = [-0.05, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.04, 0.06, 0.08]
        m = uncertainty.median(values)
        self.assertEqual(m["estimate"], 0.005)
        # n = 10: P(X <= 1) = 11/1024 <= 2.5% < P(X <= 2), so the 2nd smallest and 2nd largest
        self.assertEqual((m["low"], m["high"]), (-0.03, 0.06))
        self.assertIsNone(uncertainty.median([]))
        self.assertEqual(uncertainty.median([None, 0.01])["n"], 1)

    def test_below_the_smallest_sample_nothing_is_measured(self):
        self.assertEqual(uncertainty.SMALLEST, 6)          # derived: (1/2)**6 is inside 2.5%
        five = uncertainty.median([0.01, 0.02, 0.03, 0.04, 0.05], expected=0)
        self.assertIsNone(five["low"])
        self.assertFalse(five["distinguishable"])
        self.assertEqual(uncertainty.proportion(5, 5)["reads"], "uncertain")
        # K-07: bounded, not measured — nothing was compared, so nothing was found
        self.assertEqual(uncertainty.proportion(6, 6)["reads"], "bounded")
        self.assertNotIn("distinguishable", uncertainty.proportion(6, 6))
        self.assertTrue(uncertainty.against_chance(6, 6)["distinguishable"])
        self.assertIsNone(uncertainty.proportion(0, 0))
        with self.assertRaises(ValueError):
            uncertainty.proportion(5, 4)

    def test_the_family_level_follows_benjamini_hochberg(self):
        """Benjamini & Hochberg (1995), section 3.2: of these fifteen p-values the
        procedure declares four at q = 0.05 (Bonferroni three)."""
        p = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344, 0.0459,
             0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0]
        self.assertAlmostEqual(uncertainty.family_level(p), 1 - 4 * 0.05 / 15)
        # nothing declared: the paper has no interval to adjust; the desk's choice (K-04)
        # is R = 1, Bonferroni's level, the widest the procedure sets
        self.assertAlmostEqual(uncertainty.family_level([0.5] * 108), 1 - 0.05 / 108)
        self.assertIn("the desk's choices", uncertainty.family_level.__doc__)
        self.assertEqual(uncertainty.family_level([]), uncertainty.CONFIDENCE)
        self.assertEqual(uncertainty.sign_test_p(4, 4), 0.125)

    def test_at_the_family_level_an_interval_excludes_chance_only_for_a_declared_test(self):
        rng = random.Random(13)
        for _ in range(40):
            family = [(rng.randint(0, n), n) for n in (rng.randint(6, 60) for _ in range(rng.randint(2, 30)))]
            p = [uncertainty.sign_test_p(k, n) for k, n in family]
            level = uncertainty.family_level(p)
            cut = 1 - level
            declared = [pk for pk in p if pk <= cut]            # Benjamini-Hochberg's R
            self.assertEqual(len(declared), max(0, round((1 - level) * len(p) / 0.05)) if declared else 0)
            for (k, n), pk in zip(family, p):
                seen = uncertainty.against_chance(k, n, confidence=level)["distinguishable"]
                if abs(pk - cut) > 1e-12:                          # off the cut-off itself
                    self.assertEqual(seen, pk < cut, (k, n, pk, cut))

    def test_a_level_is_never_written_rounded_up(self):
        self.assertEqual(uncertainty.level_text(0.95), "95%")
        self.assertEqual(uncertainty.level_text(1 - 0.05 / 108), "99.953%")
        self.assertEqual(uncertainty.level_text(1 - 4 * 0.05 / 15), "98.6%")
        self.assertEqual(uncertainty.level_text(0.99999), "99.999%")
        self.assertEqual(uncertainty.proportion(3, 9, confidence=0.99)["level"], "99%")

    def test_it_owns_intervals_and_computes_nothing_else(self):
        tree = ast.parse(open(os.path.join(ROOT, "uncertainty.py")).read())
        imported = {a.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for a in node.names}
        self.assertEqual(imported, {"math", "statistics"})
        for name in ("backtest.py", "research.py", "power.py"):
            self.assertNotRegex(open(os.path.join(ROOT, name)).read(), r"\bCONFIDENCE\s*=")


if __name__ == "__main__":
    unittest.main()
