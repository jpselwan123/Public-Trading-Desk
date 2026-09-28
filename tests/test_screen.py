"""The screener over every US filer, its scores, industry peers and the universe it reads."""
from support import *  # noqa: F401,F403


class ScreenTests(unittest.TestCase):
    """A screener answers 'which companies meet these conditions' and must not
    quietly answer anything else — least of all on figures it cannot trust."""

    def company(self, ticker="ZZZ", **figures):
        row = {"ticker": ticker, "name": "Example", "assets": [1000.0],
               "revenue": [800.0], "net_income": [100.0], "equity": [500.0]}
        for key, value in figures.items():
            row[key] = value if isinstance(value, list) else [value]
        return row

    def store(self, rows):
        return {"companies": {r["ticker"]: r for r in rows}}

    def test_a_missing_figure_never_passes_a_condition(self):
        """Treating an unreported figure as zero fills a screen with companies that
        simply did not file it."""
        row = self.company()
        row.pop("net_income")
        values = screen.measures(row)
        self.assertFalse(screen.holds(screen.condition("net_margin>0.1"), values))
        self.assertFalse(screen.holds(screen.condition("net_margin<0.1"), values))

    def test_a_figure_on_the_wrong_scale_is_set_aside_not_screened(self):
        """Some filers tag one figure in thousands and the rest in units — Applied
        Industrial files FY2025 net income as 392,988 against revenue of 4.6bn.
        Every ratio built on it still looks plausible, which is the danger."""
        bad = self.company("AIT", revenue=4.6e9, assets=2.9e9, net_income=392988.0)
        self.assertEqual(screen.scale_fault(bad)["figure"], "net_income")
        self.assertIsNone(screen.scale_fault(self.company()))
        out = screen.run(["net_margin>0"], self.store([bad]))
        self.assertEqual((out["matched"], out["excluded"], out["usable"]), (0, 1, 0))

    def test_an_identity_confirms_a_slip_in_thousands_or_millions(self):
        """Net income is EPS times shares. AIT's EPS and share count give 393m
        against the 392,988 it filed; FedEx's give 4.4bn against 4,430."""
        ait = self.company("AIT", revenue=4.6e9, assets=2.9e9, equity=1.8e9,
                           net_income=[392988.0, 385e6, 346e6, 223e6],
                           eps=10.2, shares=38.5e6)
        fault = screen.scale_fault(ait)
        self.assertTrue(fault["confirmed"])
        self.assertEqual(fault["figure"], "net_income")
        self.assertIn("a thousand times", fault["note"])
        fdx = self.company("FDX", revenue=88e9, assets=87e9, equity=27e9,
                           net_income=[4430.0, 4.3e9, 3.9e9], eps=18.2, shares=243e6)
        self.assertIn("a million times", screen.scale_fault(fdx)["note"])
        out = screen.run(["net_margin>0"], self.store([ait, fdx]))
        self.assertEqual((out["excluded"], out["misfiled"]), (2, 2))

    # ---- Phase 2: J-01 both directions, J-02 a narrower "confirmed" ----------------

    def filing(self, ticker="ZZZ", **figures):
        """A small company whose filing adds up, over four years, with overrides."""
        base = {"revenue": [1e9] * 4, "gross_profit": [4e8] * 4, "operating_income": [2e8] * 4,
                "net_income": [1e8] * 4, "operating_cash_flow": [1.5e8] * 4, "assets": [2e9] * 4,
                "current_assets": [8e8] * 4, "liabilities": [1.2e9] * 4, "equity": [8e8] * 4,
                "debt": [5e8] * 4, "cash": [2e8] * 4, "eps": [2.0] * 4, "shares": [5e7] * 4}
        base.update(figures)
        return dict(base, ticker=ticker, name=ticker)

    def test_a_figure_misfiled_too_large_is_caught(self):
        """J-01: a net income a thousand times too big is a spectacular return on
        assets — the direction a screen rewards — and the old check never looked."""
        row = self.filing(net_income=[1e11, 1e8, 1e8, 1e8])
        fault = screen.scale_fault(row)
        self.assertEqual((fault["figure"], fault["grade"]), ("net_income", "confirmed"))
        self.assertIn("a thousand times larger", fault["note"])
        self.assertIsNone(screen.scale_fault(self.filing()))

    def test_gross_profit_above_revenue_is_a_slip(self):
        row = self.filing(gross_profit=[4e11, 4e8, 4e8, 4e8])
        fault = screen.scale_fault(row)
        self.assertEqual((fault["figure"], fault["grade"]), ("gross_profit", "confirmed"))
        slightly = screen.scale_fault(self.filing(gross_profit=[1.1e9] * 4))
        self.assertEqual(slightly["grade"], "unconfirmed")             # cannot be, even a little
        self.assertEqual(slightly["figures"], ["gross_profit", "revenue"])

    def test_debt_above_assets_is_a_slip(self):
        row = self.filing(debt=[5e11, 5e8, 5e8, 5e8])
        fault = screen.scale_fault(row)
        self.assertEqual((fault["figure"], fault["grade"]), ("debt", "confirmed"))

    def test_a_four_hundred_fold_fall_is_unconfirmed_not_confirmed(self):
        """J-02: 400 is inside the old 333–3,000 window, and a real collapse can do it.
        The desk may not state it as a misfiling."""
        row = self.filing(operating_income=[5e5, 2e8, 2e8, 2e8])
        fault = screen.scale_fault(row)
        self.assertEqual(fault["grade"], "suspected")
        self.assertFalse(fault["confirmed"])
        self.assertIn("either a unit slip or a very large real move", fault["note"])
        exact = screen.scale_fault(self.filing(operating_income=[2e5, 2e8, 2e8, 2e8]))
        self.assertEqual(exact["grade"], "confirmed")                  # 1,000 exactly

    def test_a_company_that_slips_every_year_is_judged_by_its_size(self):
        """AIT tags net income in thousands every year, so its history is steady and
        cannot say which side slipped. 392,988 on 4.6bn of sales cannot be a company
        this size; EPS × shares can."""
        row = self.filing(revenue=[4.6e9] * 4, net_income=[392988.0, 385000.0, 346000.0, 223000.0],
                          eps=[10.2, 10.0, 9.0, 5.8], shares=[3.85e7] * 4, assets=[2.9e9] * 4,
                          current_assets=[1.5e9] * 4, liabilities=[1.1e9] * 4, equity=[1.8e9] * 4)
        fault = screen.scale_fault(row)
        self.assertEqual((fault["figures"], fault["grade"]), (["net_income"], "confirmed"))

    # ---- fifth review, K-01: a figure misfiled too large in every year ----------------

    def every_year(self, figure, factor):
        return self.filing(**{figure: [v * factor for v in self.filing()[figure]]})

    def test_revenue_too_large_in_every_year_is_caught(self):
        """K-01: nothing bounded revenue from above, and it is the size everything else
        is judged by. A thousandfold slip in every year is 500 times the assets."""
        fault = screen.scale_fault(self.every_year("revenue", 1e3))
        self.assertEqual((fault["figures"], fault["grade"]), (["revenue", "assets"], "unconfirmed"))
        self.assertIn("has in every year it filed", fault["note"])

    def test_operating_income_too_large_in_every_year_is_caught(self):
        """K-01: 500 times gross profit, steady at its wrong level in every year. The
        steadiness once let it through; it only shows the slip was always there."""
        fault = screen.scale_fault(self.every_year("operating_income", 1e3))
        self.assertEqual(fault["figures"], ["operating_income", "gross_profit"])

    def test_cash_from_operations_too_large_in_every_year_is_caught_when_the_breach_is_a_units(self):
        """K-01: cash from operations is bounded by revenue, but only a unit-sized breach
        counts — a REIT's cash flow runs to 80 times its narrow revenue tag (UDR). So a
        slip is caught where the true figure is at least a third of revenue, and not
        below that: at a 15% cash margin the slipped figure is 150 times revenue, which a
        real filing also reaches. Stated here so it is not mistaken for coverage."""
        rich = self.filing(operating_cash_flow=[4e11] * 4)                     # 40% of revenue, x1000
        self.assertEqual(screen.scale_fault(rich)["figures"], ["operating_cash_flow", "revenue"])
        self.assertIsNone(screen.scale_fault(self.every_year("operating_cash_flow", 1e3)))   # 15%: the limit
        self.assertIsNone(screen.scale_fault(self.filing(operating_cash_flow=[8e10] * 4)))   # 80 times: a REIT

    def test_a_steady_unit_sized_breach_is_set_aside_unless_the_balance_sheet_balances(self):
        """REXR files a revenue tag of 589,000 beside 220m of net income, every year: a
        tag that is not its revenue, and a 37,300% net margin on the screener until now.
        A shell with $2,525 of assets and $1.2m of liabilities is set aside no longer:
        its negative equity balances it, and an identity outranks steadiness."""
        rexr = self.filing(revenue=[5.9e5] * 4, gross_profit=[None] * 4, net_income=[2.2e8] * 4,
                           operating_income=[None] * 4, operating_cash_flow=[1e5] * 4, eps=[None] * 4)
        fault = screen.scale_fault(rexr)
        self.assertEqual((fault["figures"], fault["grade"]), (["net_income", "revenue"], "unconfirmed"))
        self.assertIn("or a tag that describes something else", fault["note"])
        shell = self.company("AMFN", revenue=[None], net_income=[None], assets=2525.0, cash=2525.0,
                             current_assets=2525.0, liabilities=1203400.0, equity=-1200875.0)
        self.assertIsNone(screen.scale_fault(shell))
        unbalanced = self.company("XXX", revenue=[None], net_income=[None], assets=2525.0,
                                  liabilities=1203400.0, equity=500.0)
        self.assertEqual(screen.scale_fault(unbalanced)["grade"], "unconfirmed")

    def test_a_slip_in_the_size_does_not_accuse_a_correct_figure(self):
        """K-02: the company's size is what decides which side of an identity slipped
        when history cannot. Revenue filed a thousandfold too large made the size a
        thousandfold too large, and a correct net income beside a share count misfiled
        in every year was then "confirmed" as the slip. Revenue found slipped is now
        left out of the size, and the checks run again."""
        row = self.filing(revenue=[1e12, 1e9, 1e9, 1e9], gross_profit=[4e11, 4e8, 4e8, 4e8], shares=[5e10] * 4)
        named = [f["figures"] for f in screen.scale_faults(row)]
        self.assertIn(["eps", "shares"], named)
        self.assertNotIn(["net_income"], named)
        self.assertEqual(screen.size(row), 1e12)
        self.assertEqual(screen.size(row, leave_out={"revenue"}), 2e9)
        self.assertIsNone(screen.size({"assets": [None], "revenue": [0.0]}))
        # one definition of the company's size: the float check and the bridge read it
        for module in ("screen.py", "bridge.py", "value.py", "context.py", "scores.py"):
            with open(os.path.join(ROOT, module)) as f:
                self.assertNotRegex(f.read(), r'max\(abs\([^)]*"assets"[^)]*\)[^)]*\), abs\([^)]*"revenue"', module)

    def test_a_slip_is_named_once(self):
        """S-18: revenue a thousandfold above its own years and above its assets is one
        slip; the list named it twice, once confirmed and once suspected."""
        faults = screen.scale_faults(self.filing(revenue=[1e12, 1e9, 1e9, 1e9]))
        self.assertEqual([f["figures"] for f in faults].count(["revenue"]), 1)
        self.assertEqual(faults[0]["grade"], "confirmed")

    def test_a_bank_is_not_judged_on_a_measure_built_on_its_revenue(self):
        """S-19: a bank's tagged revenue leaves out interest income. The card compares
        banks on return on assets alone and builds them no bridge; the screener now
        leaves them unjudged on a condition built on revenue, and says how many."""
        bank = dict(self.filing("BNK", revenue=[1e8] * 4, gross_profit=[None] * 4, operating_income=[None] * 4,
                                operating_cash_flow=[None] * 4, net_income=[9e8] * 4, eps=[None] * 4), cik=1)
        self.assertIsNone(screen.scale_fault(bank))                  # a bank's shape, not a slip
        maker = dict(self.filing("MKR"), cik=2)
        codes = {1: 6021, 2: 2080}
        out = screen.run(["net_margin>0.05"], self.store([bank, maker]), codes=codes)
        self.assertEqual([h["ticker"] for h in out["results"]], ["MKR"])
        self.assertEqual((out["evaluated"]["net_margin"], out["financial_not_judged"]), (1, 1))
        self.assertEqual(out["financial_note"], screen.NOT_FOR_FINANCIALS)
        self.assertIn("leaves out interest income", out["financial_note"])
        # a condition that needs no revenue judges the bank like anyone else
        self.assertEqual(screen.run(["return_on_assets>0"], self.store([bank, maker]), codes=codes)
                         ["financial_not_judged"], 0)
        # without the divisions nothing is withheld, and the result does not claim otherwise
        self.assertIsNone(screen.run(["net_margin>0.05"], self.store([bank, maker]))["financial_not_judged"])
        # one name for the division, owned by sectors.py
        self.assertIs(context.FINANCIAL, sectors.FINANCIAL)
        self.assertEqual(sectors.division(6021), sectors.FINANCIAL)
        self.assertIn("s.financial_not_judged", template_function("renderScreener"))

    def test_the_screen_counts_each_grade(self):
        rows = [self.filing("AAA", net_income=[1e11, 1e8, 1e8, 1e8]),              # confirmed
                self.filing("BBB", operating_income=[5e5, 2e8, 2e8, 2e8]),         # suspected
                self.filing("CCC", gross_profit=[1.1e9] * 4), self.filing("DDD")]  # unconfirmed, fine
        out = screen.run(["revenue>0"], self.store(rows))
        self.assertEqual((out["misfiled"], out["suspected"], out["unconfirmed"], out["usable"]), (1, 1, 1, 1))

    def test_the_side_that_kept_its_own_history_is_not_accused(self):
        """Dillard's net income disagrees with EPS × shares a thousandfold but matches
        its own years: the share count slipped, not the profit."""
        row = self.filing(shares=[5e4, 5e7, 5e7, 5e7])
        fault = screen.scale_fault(row)
        self.assertEqual(fault["figures"], ["eps", "shares"])
        self.assertEqual(fault["grade"], "unconfirmed")

    def test_raised_capital_is_not_a_slip(self):
        """QXO's equity went from 9m to 9.7bn when it raised money. The cash shows up in
        its assets too, which a slip would not do."""
        row = self.filing(equity=[9.7e9, 9e6, 9e6, 9e6], assets=[1.2e10, 1.2e9, 1.2e9, 1.2e9],
                          liabilities=[2.3e9, 1.19e9, 1.19e9, 1.19e9])
        self.assertIsNone(screen.scale_fault(row))

    def test_a_flow_that_rose_a_thousandfold_is_only_suspected(self):
        """A first drug approval can multiply revenue a thousandfold."""
        row = self.filing(revenue=[1e9, 1e6, 1e6, 1e6], gross_profit=[4e8, 4e5, 4e5, 4e5],
                          operating_income=[2e8, -5e7, -5e7, -5e7], net_income=[1e8, -5e7, -5e7, -5e7],
                          eps=[2.0, -1.0, -1.0, -1.0])
        fault = screen.scale_fault(row)
        self.assertEqual(fault["grade"], "suspected")

    def test_negative_equity_is_not_a_breach(self):
        """699 companies owe more than they own — Lowe's, Starbucks — by buying back
        stock. liabilities ≤ assets is usual, not strict."""
        row = self.filing(liabilities=[2.6e9] * 4, equity=[-6e8] * 4)
        self.assertIsNone(screen.scale_fault(row))

    def test_a_bank_earning_more_than_its_tagged_revenue_is_not_set_aside(self):
        """A bank's contract revenue leaves out interest, so its net income can exceed
        it: M&T by 1.7 times."""
        self.assertIsNone(screen.scale_fault(self.filing(net_income=[1.7e9] * 4)))

    def test_net_income_above_revenue_is_never_confirmed(self):
        row = self.filing(net_income=[1e12, 1e8, 1e8, 1e8], eps=[None] * 4)
        fault = screen.scale_fault(row)
        self.assertNotEqual(fault["grade"], "confirmed")

    def test_an_identity_clears_a_figure_that_is_small_but_right(self):
        """Quaker Houghton lost 2.5m on 1.9bn of sales, and its EPS times its shares
        says so. The old rule refused it along with some two hundred others."""
        kwr = self.company("KWR", revenue=1.89e9, assets=2.8e9, net_income=-2.49e6,
                           equity=1.4e9, eps=-0.14, shares=17.8e6)
        self.assertIsNone(screen.scale_fault(kwr))

    def test_a_balance_that_was_always_small_is_the_companys_own_record(self):
        """York Water holds about $1,000 of cash, year after year."""
        yorw = self.company("YORW", revenue=77e6, assets=681e6, net_income=20e6,
                            equity=300e6, cash=[1000.0, 1000.0, 2000.0, 1000.0])
        self.assertIsNone(screen.scale_fault(yorw))

    def test_a_balance_a_thousand_times_below_its_usual_level_is_a_slip(self):
        row = self.company("AAA", revenue=3e9, assets=7e9, net_income=6e8, equity=3e9,
                           cash=[2.04e5, 2.1e8, 1.9e8, 2.2e8])
        fault = screen.scale_fault(row)
        self.assertEqual((fault["figure"], fault["confirmed"]), ("cash", True))
        self.assertIn("other years", fault["note"])

    def test_a_small_figure_nothing_can_check_is_set_aside_as_unconfirmed(self):
        row = self.company("NEW", revenue=3e9, assets=7e9, net_income=6e8, equity=3e9,
                           cash=2.0e5)
        fault = screen.scale_fault(row)
        self.assertFalse(fault["confirmed"])
        self.assertIn("nothing else in its filings can confirm", fault["note"])
        out = screen.run(["net_margin>0"], self.store([row]))
        self.assertEqual((out["excluded"], out["misfiled"], out["unconfirmed"]), (1, 0, 1))

    def test_a_slip_in_another_figure_leaves_growth_alone(self):
        """AXR's share count three years back is filed in thousands; its revenue
        growth over those three years is still right."""
        row = self.filing(shares=[5e7, 5e7, 5e7, 5e4])
        self.assertIsNotNone(screen.scale_fault(row, 3))
        self.assertIsNotNone(screen.measures(row)["revenue_growth_3y"])

    def test_a_slip_in_an_older_year_makes_growth_unknown_not_wrong(self):
        """Revenue filed in thousands three years ago would read as growth of
        tenfold a year."""
        row = self.company("AAA", revenue=[900.0, 850.0, 800.0, 0.75], assets=[1000.0] * 4)
        self.assertIsNotNone(screen.scale_fault(row, 3))
        self.assertIsNone(screen.measures(row)["revenue_growth_3y"])
        fine = self.company("AAA", revenue=[900.0, 850.0, 800.0, 750.0], assets=[1000.0] * 4)
        self.assertAlmostEqual(screen.measures(fine)["revenue_growth_3y"], (900 / 750) ** (1 / 3) - 1)

    def test_every_measure_can_be_computed_from_a_complete_record(self):
        """revenue_growth_5y needed six years of a store that keeps five, so it was
        empty for every company and a condition on it matched nobody."""
        years = universe.DEFAULT_YEARS
        # a filing that adds up: every component within its total
        base = {"revenue": 1000, "gross_profit": 400, "operating_income": 200, "net_income": 100,
                "operating_cash_flow": 150, "capex": 50, "dividends_paid": -30, "eps": 2,
                "shares": 50, "assets": 2000, "current_assets": 800, "liabilities": 1200,
                "current_liabilities": 400, "equity": 800, "debt": 500, "cash": 200,
                "retained_earnings": 300, "shares_outstanding": 50, "public_float": 5000,
                "buybacks": 20, "depreciation": 60, "share_based_compensation": 10,
                "depreciation_alone": 45, "amortisation": 15,
                "interest_expense": 25, "matures_1y": 50, "matures_2y": 50, "matures_3y": 100,
                "matures_4y": 100, "matures_5y": 100, "matures_later": 150}
        self.assertEqual(set(base), set(universe.FIGURES))
        full = {"ticker": "ZZZ", "name": "Example"}
        for figure, amount in base.items():
            full[figure] = [amount * (1 - 0.05 * y) for y in range(years)]
        values = screen.measures(full)
        empty = [name for name, value in values.items() if value is None]
        self.assertEqual(empty, [])

    def test_negative_equity_does_not_pass_a_leverage_condition(self):
        """AutoZone's equity is -3.2bn against 8.6bn of debt, which made
        debt_to_equity -2.67 and slipped through a 'below 1' condition."""
        row = self.company("AZO", equity=-3.2e9, debt=8.6e9, assets=1.7e10,
                           revenue=1.9e10, net_income=2.5e9)
        values = screen.measures(row)
        self.assertIsNone(values["debt_to_equity"])
        self.assertIsNone(values["return_on_equity"])
        self.assertEqual(values["negative_equity"], 1.0)
        self.assertFalse(screen.holds(screen.condition("debt_to_equity<1"), values))
        self.assertTrue(screen.holds(screen.condition("negative_equity>0"), values))

    def test_growth_from_a_negative_base_is_not_reported(self):
        self.assertIsNone(screen.measures(self.company(revenue=[5.0, -10.0]))["revenue_growth"])

    def test_an_unknown_measure_is_an_error_not_a_pass(self):
        for bad in ("nt_margin>0.1", "net_margin", "net_margin>lots"):
            with self.assertRaises(screen.ScreenError):
                screen.condition(bad)

    def test_a_screen_with_no_conditions_is_refused(self):
        with self.assertRaises(screen.ScreenError):
            screen.run([], self.store([self.company()]))

    def test_every_published_screen_is_cited_and_parses(self):
        store = self.store([dict(self.company(), gross_profit=[100.0])])
        for name, spec in screen.PRESETS.items():
            self.assertTrue(spec["source"], name)
            self.assertTrue(spec["where"] or spec.get("top_third"), name)
            for text in spec["where"]:
                screen.condition(text)          # a typo here would always-pass
            self.assertEqual(screen.preset(name, store, listings={})["source"], spec["source"])

    def test_the_published_screens_use_their_authors_own_numbers(self):
        """
        Graham's screen had debt-to-equity under 1 (his rule for a utility is twice equity; for an
        industrial, debt no more than working capital) and $500m of sales (his is $100m of 1972);
        Novy-Marx's had a growth condition that is not his and a fixed cut for his top third."""
        self.assertEqual(screen.PRESETS["graham"]["where"],
                         [f"revenue>={100e6 * 317.7 / 41.8:.0f}", "current_ratio>=2", "debt_to_working_capital<=1",
                          "net_income>0"])
        self.assertIn("not a finding tested on returns", screen.PRESETS["graham"]["source"])
        row = self.company()
        row.update(current_assets=[300.0], current_liabilities=[100.0], debt=[150.0])
        self.assertAlmostEqual(screen.measures(row)["debt_to_working_capital"], 0.75)
        row.update(current_liabilities=[300.0])
        self.assertIsNone(screen.measures(row)["debt_to_working_capital"])          # no working capital: fails
        # the NYSE's top third on the day, never a fixed number; growth is not Novy-Marx's
        spec = screen.PRESETS["profitable"]
        self.assertEqual((spec["top_third"], spec["where"]), ("gross_profitability", []))
        rows = [dict(self.company(), ticker=f"N{i:02d}", cik=100 + i, gross_profit=[i * 10.0], assets=[1000.0])
                for i in range(30)]
        store = self.store(rows)
        listings = {"exchanges": {r["ticker"]: "NYSE" for r in rows}}
        cut, group = screen.top_third("gross_profitability", store, listings=listings)
        self.assertEqual((round(cut, 2), group), (0.2, "NYSE"))                      # 20 of the 30 below it
        out = screen.preset("profitable", store, listings=listings)
        self.assertEqual(out["matched"], 10)
        self.assertIn("0.2, set on NYSE companies", out["about"])

    def test_a_preset_says_which_of_its_criteria_it_cannot_apply(self):
        """Graham's test includes a P/E limit needing a price this store has not
        got. A screen quietly missing a criterion is not that screen."""
        for name in ("graham", "piotroski"):
            self.assertTrue(screen.PRESETS[name]["omits"], name)
        self.assertTrue(screen.preset("graham", self.store([self.company()]))["omits"])

    def test_the_screener_orders_by_the_users_own_first_condition_never_its_own(self):
        """Sorting by desirability would be a recommendation wearing a table, so the
        order is never the desk's: it follows the measure the user put first —
        the answer to the question asked (Phase 4; it was alphabetical, which is a
        choice too and the least useful one). A different first condition gives a
        different order."""
        rows = [self.company("AAA", net_income=100.0, revenue=200.0),
                self.company("BBB", net_income=400.0, revenue=4000.0)]
        by_margin = screen.run(["net_margin>0", "revenue>0"], self.store(rows))
        self.assertEqual(by_margin["sorted_by"], "net_margin")
        self.assertEqual([r["ticker"] for r in by_margin["results"]], ["AAA", "BBB"])   # 50% > 10%
        by_revenue = screen.run(["revenue>0", "net_margin>0"], self.store(rows))
        self.assertEqual([r["ticker"] for r in by_revenue["results"]], ["BBB", "AAA"])
        self.assertIn(by_revenue["sorted_by"], [r["measure"] for r in by_revenue["rules"]])

    def test_the_screener_page_reads_the_keys_the_endpoint_produces(self):
        """The page renders whatever the endpoint returns, so the keys it reads must
        be the ones run() produces — a rename here blanks a card silently."""
        template = page_source()
        out = screen.run(["net_margin>0"], self.store([self.company()]))
        for key in ("evaluated", "excluded", "matched", "results", "sorted_by", "usable",
                    "misfiled", "suspected", "unconfirmed"):
            self.assertIn(key, out)
            self.assertIn("s." + key, template, key)
        self.assertIn("renderScreener", template)
        self.assertIn("'/screen'", template)

    def test_the_holding_bar_is_a_block_so_its_width_applies(self):
        """The share-of-holdings bar was a <span>: inline, so width and height were
        ignored and the bar never drew, from the first commit on."""
        template = page_source()
        rule = re.search(r"\.wbar \.fill\{([^}]*)\}", template).group(1)
        self.assertIn("display:block", rule)

    def test_a_trillion_prints_as_a_trillion(self):
        """AMD's market value printed as "$1017.0bn"."""
        self.assertEqual(value.format_value("market_cap", 1.017e12), "$1.02tn")
        self.assertEqual(screen.format_measure("revenue", 1.017e12), "$1.02tn")

    def test_peer_figures_say_which_year_they_compare(self):
        """The peer table showed a 49.5% gross margin under a card headed 50.3%:
        one filed year against the trailing twelve months, neither labelled."""
        # each row names the filing its figures are from (the paragraph saying so went
        # with the user's clean-up of 26 Sep 2026; the label stays)
        self.assertIn("' filing)</span>'", template_function("peerBlock"))
        source = open(os.path.join(ROOT, "context.py")).read()
        self.assertIn('"figures_from": universe.periods("flow", 1)[0]', source)

    def test_the_page_describes_itself_accurately(self):
        """The footer said "this page never places trades" after a gated order path
        existed, and the journal said a trade "beat" the market "by −11.2%"."""
        template = page_source()
        self.assertNotIn("never places trades", template)
        self.assertEqual(template.count("vsMarket(C.vs_market)"), 1)
        self.assertNotIn("better than leaving", template)

    def test_the_piotroski_preset_says_how_many_of_his_signals_it_applies(self):
        """J-05: titled "Piotroski F-score components", it applied four conditions, and
        two were not his: free cash flow where he uses cash from operations."""
        spec = screen.PRESETS["piotroski"]
        self.assertIn("Four of Piotroski's nine signals", spec["name"])
        self.assertEqual(len(spec["where"]), 4)
        self.assertIn("operating_cash_flow>0", spec["where"])
        self.assertNotIn("free_cash_flow>0", spec["where"])
        self.assertIn("five signals", spec["omits"][0])
        self.assertIn("not the F-score", spec["about"])

    def test_accruals_are_earnings_less_cash_from_operations(self):
        """Sloan (1996), as Piotroski uses it — not earnings less free cash flow."""
        row = {"net_income": [100.0], "operating_cash_flow": [150.0], "capex": [80.0],
               "assets": [1000.0]}
        self.assertAlmostEqual(screen.measures(row)["accruals"], (100.0 - 150.0) / 1000.0)

    def test_a_small_positive_ratio_does_not_print_as_zero(self):
        """American Airlines earned 0.18% on assets. Printed as 0.00 it reads as
        failing the Piotroski condition "greater than zero" that it passes."""
        self.assertEqual(screen.format_measure("return_on_assets", 0.001797), "0.2%")
        self.assertEqual(screen.format_measure("return_on_assets", 0.0000404), "0.0040%")
        self.assertEqual(screen.format_measure("accruals", -0.05), "\u22120.050")
        self.assertEqual(screen.format_measure("return_on_assets", 0.0), "0.0%")
        self.assertEqual(screen.format_measure("current_ratio", 0.35), "0.35")

    def test_following_from_a_screen_uses_the_one_watchlist_path(self):
        """A second route to /watchlist is how two copies of the list drift apart,
        so following a screener result goes through the same follow() and saveWatchlist."""
        template = page_source()
        self.assertIn("data-follow", template)
        self.assertIn("if (pick) follow(pick.dataset.follow", template)
        self.assertIn("follow(t);", template)                           # the Filings page input
        self.assertEqual(template.count("fetch('/watchlist'"), 1)
        self.assertEqual(template.count('<dialog id="followDlg"'), 1)

    def test_the_cards_follow_the_coverage_list_at_once(self):
        """The user, 26 Sep 2026: removing a company under Filings left its card at the
        top of Companies until the page was reloaded — the page redrew the Filings list
        alone. Every change to the list now reads the whole rebuilt page again, and the
        company just followed is the one shown."""
        body = template_function("saveWatchlist")
        self.assertIn("await reloadData()", body)
        self.assertNotIn("DATA.news = res.news", body)
        self.assertIn("coPick = String(body.follow).toUpperCase()", body)
        self.assertIn('for ticker in (news_data or {}).get("tickers") or []', inspect.getsource(build_desk.build_companies))

    def test_a_preset_note_does_not_name_a_command_line_flag(self):
        """The omits text is shown on the page as well as in the terminal."""
        for spec in screen.PRESETS.values():
            for note in spec["omits"]:
                self.assertNotIn("--", note, note)

    def test_the_result_says_how_many_companies_could_be_judged(self):
        """The SEC's frames API omits a concept a company reports only inside a
        dimensional breakdown — Coca-Cola files long-term debt and is absent from
        the frame — so barely a third of filers have a debt figure at all. Without
        this the result reads as though everyone else was tested and failed."""
        rows = [self.company("AAA", debt=100.0), self.company("BBB")]
        rows[1].pop("debt", None)
        out = screen.run(["net_margin>0", "debt_to_equity<1"], self.store(rows))
        self.assertEqual(out["evaluated"]["net_margin"], 2)
        self.assertEqual(out["evaluated"]["debt_to_equity"], 1)
        self.assertEqual(out["narrowest"], 1)
        self.assertEqual([r["ticker"] for r in out["results"]], ["AAA"])


class SectorTests(unittest.TestCase):
    """A figure means nothing without the group it should be read against."""

    def company(self, ticker, cik, **figures):
        row = {"ticker": ticker, "cik": cik, "name": ticker, "assets": [1000.0],
               "revenue": [800.0], "net_income": [100.0], "equity": [500.0]}
        for key, value in figures.items():
            row[key] = value if isinstance(value, list) else [value]
        return row

    def world(self, count=8, sic=3571):
        companies, codes = {}, {}
        for i in range(count):
            ticker = "T%02d" % i
            companies[ticker] = self.company(ticker, 100 + i, net_income=float(10 * i))
            codes[100 + i] = sic
        return companies, codes

    def test_peers_come_from_the_narrowest_group_with_enough_members(self):
        companies, codes = self.world(8, sic=3571)
        # two companies in a different 4-digit industry, same 3-digit group
        for i, ticker in enumerate(("X1", "X2")):
            companies[ticker] = self.company(ticker, 200 + i)
            codes[200 + i] = 3572
        found = sectors.peers_for("X1", companies, codes)
        self.assertEqual(found["width"], 3)              # 3572 alone has only 2 members
        self.assertGreaterEqual(len(found["peers"]), sectors.MIN_PEERS)
        self.assertEqual(sectors.peers_for("T01", companies, codes)["width"], 4)

    def test_a_company_with_no_industry_code_gets_no_peers(self):
        companies, codes = self.world(8)
        companies["NEW"] = self.company("NEW", 999)
        found = sectors.peers_for("NEW", companies, codes)
        self.assertEqual(found["peers"], [])
        self.assertIn("has not assigned", found["why"])

    def test_no_percentile_is_shown_for_too_few_peers(self):
        companies, codes = self.world(3)
        out = sectors.compare("T01", screen.measures, companies, codes)
        self.assertEqual(out["measures"], {})
        self.assertIn("fewer than", out["why"])

    def test_a_percentile_puts_ties_in_the_middle(self):
        """Everyone reporting the same figure should land at 50, not 100."""
        self.assertEqual(sectors.percentile(5.0, [5.0, 5.0, 5.0]), 50.0)
        self.assertEqual(sectors.percentile(9.0, [1.0, 2.0, 3.0]), 100.0)
        self.assertEqual(sectors.percentile(0.0, [1.0, 2.0, 3.0]), 0.0)
        self.assertIsNone(sectors.percentile(None, [1.0, 2.0]))
        self.assertIsNone(sectors.percentile(1.0, [None]))

    def test_the_comparison_counts_how_many_peers_reported_each_figure(self):
        companies, codes = self.world(8)
        for ticker in ("T02", "T03", "T04"):
            companies[ticker].pop("net_income")
        out = sectors.compare("T01", screen.measures, companies, codes,
                              measures=["net_margin"])
        self.assertEqual(out["measures"]["net_margin"]["reported_by"], 4)
        self.assertEqual(out["peers"], 8)

    def test_divisions_cover_the_published_ranges(self):
        self.assertEqual(sectors.division(3571), "Manufacturing")
        self.assertEqual(sectors.division(6022), "Finance, insurance and property")
        self.assertIsNone(sectors.division(None))
        self.assertIsNone(sectors.division(9999))

    def test_a_missing_quarter_says_so(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        with self.assertRaises(sectors.SectorError) as cm:
            sectors.fetch_quarter("2099q9", "me", opener)
        self.assertIn("2099q9", str(cm.exception))


class ScoreTests(unittest.TestCase):
    """Published models computed as their authors defined them, and reported without
    being turned into a verdict the authors never made."""

    def company(self, **figures):
        row = {"ticker": "ZZZ", "name": "Example",
               "assets": [1000.0, 900.0], "revenue": [800.0, 700.0],
               "net_income": [100.0, 50.0], "equity": [500.0, 450.0],
               "retained_earnings": [300.0, 250.0], "liabilities": [500.0, 450.0],
               "operating_income": [120.0, 60.0], "operating_cash_flow": [150.0, 80.0],
               "gross_profit": [400.0, 330.0], "debt": [100.0, 150.0],
               "current_assets": [400.0, 300.0], "current_liabilities": [200.0, 200.0],
               "shares": [10.0, 10.0]}
        for key, value in figures.items():
            row[key] = value if isinstance(value, list) else [value]
        return row

    def test_a_strong_company_scores_every_signal(self):
        f = scores.piotroski(self.company())
        self.assertEqual((f["score"], f["out_of"]), (9, 9))
        self.assertTrue(f["complete"])

    def test_a_slip_in_last_years_filing_makes_the_comparisons_unknown(self):
        """Six signals compare with last year. Against a figure filed in the wrong
        unit, "return on assets rose" is a comparison with a number out by a
        thousand — unknown, and said to be, rather than passed."""
        row = self.company(net_income=[100.0, 0.05, 90.0, 80.0])
        f = scores.piotroski(row)
        self.assertEqual(f["unknown"], ["improving returns"])   # the one built on it
        self.assertIn("last year's net income does not reconcile", f["prior_year"])
        self.assertEqual(f["out_of"], 8)
        self.assertIsNone(scores.piotroski(self.company())["prior_year"])

    def test_a_misfiled_share_count_last_year_touches_only_the_dilution_signal(self):
        """A share count out by a thousand says nothing about margins or returns."""
        row = self.company(shares=[10.0, 0.01, 10.0, 10.0], eps=[10.0, 5.0, 9.0, 8.0],
                           net_income=[100.0, 50.0, 90.0, 80.0])
        f = scores.piotroski(row)
        self.assertEqual(f["unknown"], ["no dilution"])

    def test_a_signal_that_cannot_be_computed_is_not_counted_as_failed(self):
        """A missing year is an absent test, not a failed one — otherwise every
        newly listed company scores badly for having no history."""
        row = self.company()
        for figure in ("assets", "revenue", "gross_profit", "net_income",
                       "debt", "current_assets", "current_liabilities", "shares"):
            row[figure] = row[figure][:1]          # one year only
        f = scores.piotroski(row)
        self.assertLess(f["out_of"], 9)
        self.assertFalse(f["complete"])
        self.assertTrue(f["unknown"])
        self.assertEqual(f["score"], sum(1 for s in f["signals"] if s["passed"]))

    def test_the_altman_band_is_withheld_when_the_model_does_not_apply(self):
        """Starbucks earns 6% on assets and scores -0.37. Two of the four inputs are
        equity and retained earnings, which buybacks reduce mechanically; the model
        was fitted where those went negative through losses. Printing 'distress'
        there would be false."""
        bought_back = self.company(equity=-500.0, retained_earnings=-800.0,
                                   net_income=[100.0, 90.0, 80.0, 70.0, 60.0])
        out = scores.altman(bought_back)
        self.assertIsNotNone(out["score"])
        self.assertIsNone(out["band"])
        self.assertFalse(out["applies"])
        self.assertIn("buybacks", out["why_not"])

    def test_a_payout_driven_deficit_withholds_the_band(self):
        """J-03b: Amgen earned 31bn over five years and paid out 33bn; its -25bn of
        retained earnings came from paying shareholders. Its Z'' of 0.14 would read
        "distress" at a company earning 7.7bn a year."""
        amgen = self.company(equity=8.7e9, retained_earnings=-25.1e9, assets=90e9,
                             liabilities=81e9, net_income=[7.7e9, 4.1e9, 6.7e9, 6.6e9, 5.9e9],
                             dividends_paid=[-5.1e9, -4.8e9, -4.6e9, -4.2e9, -4.0e9],
                             buybacks=[0.0, 0.0, 6.3e9, 3.5e9, 1.6e9])
        out = scores.altman(amgen)
        self.assertIsNone(out["band"])
        self.assertEqual(out["test"], "payouts")
        self.assertIn("paying shareholders", out["why_not"])

    def test_a_loss_driven_deficit_keeps_its_band(self):
        """Paid out a little, lost a lot: the deficit is losses, what the model is for."""
        row = self.company(equity=-500.0, retained_earnings=-800.0,
                           net_income=[-200.0, -150.0, -100.0], dividends_paid=[-5.0, -5.0, -5.0],
                           buybacks=[0.0, 0.0, 0.0])
        out = scores.altman(row)
        self.assertTrue(out["applies"])

    def test_a_company_that_lost_before_the_window_keeps_its_band(self):
        """J-03 (b): lost heavily before the five stored years, profitable in all of
        them, still carrying the deficit. The profitability test withheld its band;
        its payouts are too small to explain the hole, so the deficit is losses."""
        row = self.company(equity=-500.0, retained_earnings=-3000.0,
                           net_income=[100.0, 90.0, 80.0, 70.0, 60.0],
                           dividends_paid=[0.0] * 5, buybacks=[-10.0] * 5)
        self.assertTrue(scores.consistently_profitable(row))           # the old test would withhold
        out = scores.altman(row)
        self.assertTrue(out["applies"])

    def test_negative_retained_earnings_with_positive_equity_keeps_its_band(self):
        """J-03a: a company that listed with paid-in capital and an accumulated deficit
        has negative retained earnings and healthy equity. X2 carries the deficit, as
        designed."""
        listed = self.company(equity=500.0, retained_earnings=-800.0,
                              net_income=[100.0, 90.0, -300.0, -400.0, -500.0],
                              dividends_paid=[0.0] * 5, buybacks=[0.0] * 5)
        out = scores.altman(listed)
        self.assertTrue(out["applies"])
        self.assertLess(out["parts"]["X2 retained earnings / assets"], 0)
        without_payouts = self.company(equity=500.0, retained_earnings=-800.0,
                                       net_income=[100.0, 90.0, 80.0, 70.0, 60.0])
        self.assertTrue(scores.altman(without_payouts)["applies"])      # no fallback for this case

    def test_the_card_says_which_test_withheld_the_band(self):
        """When the payouts are not in the filings as published, the older test is
        used and the reason says so."""
        row = self.company(equity=-500.0, retained_earnings=-800.0,
                           net_income=[100.0, 90.0, 80.0, 70.0, 60.0])
        out = scores.altman(row)
        self.assertEqual(out["test"], "profitability")
        self.assertIn("judged from its profits alone", out["why_not"])

    def test_a_deficit_built_from_losses_keeps_its_band(self):
        """BeOne lost money in four of five years and has just turned a profit. Its
        deficit is accumulated losses — what Altman's model is for — and the first
        version of the guard withheld its band as though it were buybacks."""
        recovering = self.company(equity=-500.0, retained_earnings=-800.0,
                                  net_income=[290.0, -640.0, -880.0, -2000.0, -1460.0])
        out = scores.altman(recovering)
        self.assertTrue(out["applies"])
        self.assertIsNotNone(out["band"])

    def test_too_short_a_record_cannot_show_a_pattern_of_payouts(self):
        short = self.company(equity=-500.0, retained_earnings=-800.0,
                             net_income=[100.0, 90.0])
        self.assertFalse(scores.consistently_profitable(short))
        self.assertTrue(scores.altman(short)["applies"])

    def test_a_loss_making_company_with_negative_equity_keeps_its_band(self):
        """The guard is for returned capital, not for genuine distress — a company
        losing money with negative equity is exactly what the model is for."""
        failing = self.company(net_income=[-200.0, -150.0], equity=-500.0,
                               retained_earnings=-800.0,
                               operating_income=[-180.0, -140.0])
        out = scores.altman(failing)
        self.assertTrue(out["applies"])
        self.assertEqual(out["band"], "distress")

    def test_altman_says_what_it_could_not_compute(self):
        row = self.company()
        row.pop("retained_earnings")
        out = scores.altman(row)
        self.assertIsNone(out["score"])
        self.assertTrue(out["missing"])

    def test_a_company_on_a_broken_scale_is_refused_not_scored(self):
        row = self.company(revenue=4.6e9, assets=2.9e9, net_income=392988.0)
        row["ticker"] = "AIT"
        out = scores.for_company("AIT", {"companies": {"AIT": row}})
        self.assertIn("ratio built on it", out["error"])

    def test_every_model_reports_its_source_and_its_caveats(self):
        for model in (scores.PIOTROSKI, scores.ALTMAN):
            self.assertIn("(", model["source"])            # a year, so it is citable
            self.assertTrue(model["caveats"])
        self.assertIn("not a claim about any one of them", scores.PIOTROSKI["found"])

    def test_the_shared_accessors_are_not_copied(self):
        """The standing rule after the same quantity was computed twice in two
        files: one definition, imported."""
        self.assertIs(scores._at, screen.at)
        self.assertIs(scores._ratio, screen.ratio)
        source = read(os.path.join(ROOT, "scores.py"))
        self.assertNotIn("def _at(", source)
        self.assertNotIn("def _ratio(", source)


class UniverseTests(unittest.TestCase):
    """Fundamentals for every US filer, from the SEC's own frames API."""

    def test_periods_stop_at_the_last_complete_year(self):
        """A year's figures are not filed until months after it ends."""
        self.assertEqual(universe.periods("flow", 3, date(2026, 9, 23)),
                         ["CY2025", "CY2024", "CY2023"])
        self.assertEqual(universe.periods("level", 2, date(2026, 9, 23)),
                         ["CY2025Q4I", "CY2024Q4I"])

    def test_a_missing_frame_is_not_an_error(self):
        """Not every concept exists in every period, and that is ordinary."""
        def fetch(url, who):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        self.assertEqual(universe.frame("Revenues", "USD", "CY2024", "me", fetch), [])

    def test_public_float_is_read_from_every_quarter_latest_first(self):
        """Float is measured at the company's second *fiscal* quarter — 31 December
        for Microsoft, 30 November for Nike. Reading only the Q2 frame dropped the
        check for every company whose year does not end in December."""
        frames = universe.frames_for("public_float", "level", 1, date(2026, 9, 23))
        self.assertEqual([f for _, f in frames],
                         ["CY2025Q4I", "CY2025Q3I", "CY2025Q2I", "CY2025Q1I"])
        self.assertEqual(universe.frames_for("assets", "level", 1, date(2026, 9, 23)),
                         [(0, "CY2025Q4I")])

    def test_a_later_quarter_wins_within_a_year(self):
        def fetch(url, who):
            if "company_tickers" in url:
                return {"0": {"cik_str": 1, "ticker": "AAA", "title": "A"}}
            if "EntityPublicFloat" in url and "Q4I" in url:
                return {"data": [{"cik": 1, "val": 400.0}]}
            if "EntityPublicFloat" in url and "Q2I" in url:
                return {"data": [{"cik": 1, "val": 200.0}]}
            return {"data": []}
        built = universe.build(years=1, who="me", fetch=fetch, log=lambda *a: None, sleep=lambda s: None)
        self.assertEqual(built["companies"]["AAA"]["public_float"][0], 400.0)

    def test_throttling_is_retried_then_reported(self):
        """Throttling is transient, so it is retried with a growing pause before the
        build gives up — and then says how many times it tried."""
        calls, waits = [], []

        def fetch(url, who):
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, "Too Many", {}, None)
        with self.assertRaises(universe.UniverseError) as cm:
            universe.frame("Revenues", "USD", "CY2024", "me", fetch, sleep=waits.append)
        self.assertEqual(len(calls), universe.RETRIES + 1)
        self.assertEqual(waits, [universe.BACKOFF * 2 ** i for i in range(universe.RETRIES)])
        self.assertIn("429", str(cm.exception))

    def test_a_dropped_connection_does_not_end_the_build(self):
        """The SEC reset one connection ~100 requests into a build and threw away
        three minutes of work; the run looked successful because a pipe hid it."""
        attempts = []

        def fetch(url, who):
            attempts.append(url)
            if len(attempts) == 1:
                raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))
            return {"data": [{"cik": 1, "val": 5.0}]}
        rows = universe.frame("Revenues", "USD", "CY2024", "me", fetch, sleep=lambda s: None)
        self.assertEqual(rows, [{"cik": 1, "val": 5.0}])
        self.assertEqual(len(attempts), 2)

    def test_a_refusal_is_not_retried(self):
        calls = []

        def fetch(url, who):
            calls.append(url)
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with self.assertRaises(universe.UniverseError) as cm:
            universe.frame("Revenues", "USD", "CY2024", "me", fetch, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)
        self.assertIn("SEC_CONTACT", str(cm.exception))

    def test_the_first_tag_that_reports_a_figure_wins(self):
        """A company files revenue under one of several tags; a later tag must not
        overwrite a value an earlier one already supplied."""
        def fetch(url, who):
            if "company_tickers" in url:
                return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}
            return {"data": [{"cik": 320193,
                              "val": 1.0 if "RevenueFromContract" in url else 999.0}]}
        built = universe.build(years=1, who="me", fetch=fetch, log=lambda *a: None, sleep=lambda s: None)
        self.assertEqual(built["companies"]["AAPL"]["revenue"][0], 1.0)

    def test_a_filer_with_no_listed_ticker_is_left_out(self):
        def fetch(url, who):
            if "company_tickers" in url:
                return {"0": {"cik_str": 1, "ticker": "", "title": "Private Co"}}
            return {"data": [{"cik": 999, "val": 5.0}]}
        self.assertEqual(universe.build(years=1, who="me", fetch=fetch, sleep=lambda s: None,
                                        log=lambda *a: None)["companies"], {})



class UpkeepTests(unittest.TestCase):
    """27 Sep 2026: the rating's universe and the industry codes were built by hand once
    and never again, so ratings drifted behind the filings. The company update keeps them
    up on the Mac: the universe monthly, the codes when missing; never on a phone."""

    def test_the_latest_year_is_the_last_whose_annual_reports_are_in(self):
        self.assertEqual(universe.latest_year(date(2027, 3, 31)), 2025)          # 10-Ks for 2026 still due
        self.assertEqual(universe.latest_year(date(2027, 4, 1)), 2026)
        self.assertEqual(universe.periods("flow", 2, date(2027, 2, 1)), ["CY2025", "CY2024"])

    def test_it_is_rebuilt_when_missing_a_month_old_or_a_year_has_come_in(self):
        today = date(2026, 9, 27)
        fresh = {"built": "2026-09-20", "companies": {"A": {}}}
        self.assertFalse(universe.due(fresh, today))
        self.assertTrue(universe.due(dict(fresh, built="2026-08-27"), today))    # 31 days
        self.assertTrue(universe.due(dict(fresh, companies={}), today))
        self.assertTrue(universe.due({}, today))
        self.assertTrue(universe.due({"built": "2027-03-25", "companies": {"A": {}}}, date(2027, 4, 2)))

    def test_keeping_up_builds_only_when_due_and_never_writes_an_empty_one(self):
        with tempfile.TemporaryDirectory() as folder:
            real = universe.UNIVERSE_FILE
            universe.UNIVERSE_FILE = os.path.join(folder, "universe.json")
            try:
                built = []
                make = lambda log=None: built.append(1) or {"built": "2026-09-27", "companies": {"A": {"cik": 1}}}
                self.assertEqual(universe.keep_up(date(2026, 9, 27), build_it=make)["companies"], {"A": {"cik": 1}})
                self.assertEqual(universe.keep_up(date(2026, 9, 28), build_it=make)["built"], "2026-09-27")
                self.assertEqual(len(built), 1)                                    # not due the next day
                with self.assertRaises(universe.UniverseError):
                    universe.keep_up(date(2026, 11, 1), build_it=lambda log=None: {"companies": {}})
                self.assertEqual(universe.load()["built"], "2026-09-27")          # the stored one kept

                def down(log=None):
                    raise urllib.error.URLError("no route")
                with self.assertRaises(universe.UniverseError):
                    universe.keep_up(date(2026, 11, 1), build_it=down)
            finally:
                universe.UNIVERSE_FILE = real

    def test_the_industry_codes_are_built_from_the_latest_quarters_published(self):
        self.assertEqual(sectors.recent_quarters(date(2026, 9, 27)), ["2026q2", "2026q1", "2025q4"])
        self.assertEqual(sectors.recent_quarters(date(2026, 2, 1), 2), ["2025q4", "2025q3"])
        with tempfile.TemporaryDirectory() as folder:
            real, sectors.SECTORS_FILE = sectors.SECTORS_FILE, os.path.join(folder, "sectors.json")
            old = os.environ.get("SEC_CONTACT")
            os.environ["SEC_CONTACT"] = "me@example.com"
            try:
                asked = []

                def fetch(quarter, who):
                    asked.append(quarter)
                    if quarter == "2026q2":
                        raise sectors.SectorError("not published yet")
                    return {1: 3571 if quarter == "2026q1" else 1000, 2: 6021}
                data = sectors.keep_up(date(2026, 9, 27), fetch=fetch)
                self.assertEqual((asked, data["quarters"]), (["2026q2", "2026q1", "2025q4"], ["2026q1", "2025q4"]))
                self.assertEqual(sectors.load(), {1: 3571, 2: 6021})             # the newer quarter's code
                self.assertIsNone(sectors.keep_up(date(2026, 9, 27), fetch=fetch))    # kept once built
            finally:
                sectors.SECTORS_FILE = real
                if old is None:
                    os.environ.pop("SEC_CONTACT", None)
                else:
                    os.environ["SEC_CONTACT"] = old

    def test_the_company_update_keeps_them_up_on_the_mac_only(self):
        source = inspect.getsource(server.Handler.update_research)
        self.assertLess(source.index('("Company universe"'), source.index('("Rating sample"'))
        self.assertIn("None if ON_PHONE else universe.keep_up()", source)
        self.assertIn("None if ON_PHONE else sectors.keep_up()", source)
        self.assertIn("server.ON_PHONE = True", read(os.path.join(ROOT, "phone.py")))
        self.assertIn("sectors.SectorError", inspect.getsource(server.Handler.run_steps))
        self.assertIn('"Accept-Encoding": "gzip"', inspect.getsource(universe._request))

if __name__ == "__main__":
    unittest.main()
