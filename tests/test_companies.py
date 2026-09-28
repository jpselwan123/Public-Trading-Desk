"""A company's card: its figures, results, prices, valuation, analysts and the context around them."""
from support import *  # noqa: F401,F403


class OwnHistoryTests(unittest.TestCase):
    """A company's price to earnings against its own last five years: each month's close
    over the earnings filed by then — never a figure filed later."""

    def test_it_is_not_given_the_valuations_name(self):
        """Price over twelve months' earnings per share is not the valuation's market value
        over the last full year's profit: one card showed both as "Price to earnings" with
        different numbers. A different figure has a different name (J-04)."""
        block = template_function("peHistoryBlock")
        self.assertIn("'price_to_eps_12m'", block)
        self.assertNotIn("'price_to_earnings'", block)
        self.assertNotEqual(value.OWN_HISTORY_DISPLAY["price_to_eps_12m"]["label"],
                            value.VALUE_DISPLAY["price_to_earnings"]["label"])

    def quarter_eps(self, year, q, val, filed):
        starts, ends = ["01-01", "04-01", "07-01", "10-01"], ["03-31", "06-30", "09-30", "12-31"]
        return {"start": f"{year}-{starts[q]}", "end": f"{year}-{ends[q]}", "val": val, "form": "10-Q", "filed": filed}

    def stored(self, eps_by_quarter):
        rows = []
        for i, val in enumerate(eps_by_quarter):
            year, q = 2021 + i // 4, i % 4
            end = date.fromisoformat(f"{year}-{['03-31', '06-30', '09-30', '12-31'][q]}")
            rows.append(self.quarter_eps(year, q, val, (end + timedelta(days=40)).isoformat()))
        return {"ticker": "ZZZ", "cik": 1, "tags": {"eps": "EarningsPerShareDiluted"}, "facts": {"eps": rows}}

    def closes(self, price_on):
        days = [(date(2021, 1, 4) + timedelta(days=i)).isoformat() for i in range(0, 2100)]
        return {d: price_on(d) for d in days if date.fromisoformat(d).weekday() < 5}

    def test_each_month_uses_only_the_earnings_filed_by_then(self):
        stored = self.stored([1.0] * 12 + [2.0] * 12)                   # earnings double from 2024
        h = value.own_history(stored, self.closes(lambda d: 100.0), date(2026, 9, 25))
        by_month = {p["month"]: p["pe"] for p in h["points"]}
        # four quarters of 1.00 filed: 100 / 4; the first 2.00 quarter is filed 10 May 2024,
        # so April 2024 still reads 25 and May reads 100 / 5
        self.assertAlmostEqual(by_month["2024-04"], 25.0)
        self.assertAlmostEqual(by_month["2024-05"], 100.0 / 5.0)
        self.assertAlmostEqual(h["now"], 100.0 / 8.0)
        self.assertEqual((h["years"], h["months"]), (value.OWN_HISTORY_YEARS, len(h["points"])))
        self.assertAlmostEqual(h["low"], 12.5)
        self.assertLess(h["place"], 50)                                  # today is the cheapest stretch

    def test_what_cannot_be_measured_says_why(self):
        losing = self.stored([-1.0] * 24)
        self.assertIn("months", value.own_history(losing, self.closes(lambda d: 50.0), date(2026, 9, 25))["why_not"])
        turned = self.stored([1.0] * 20 + [-3.0] * 4)                   # profitable for years, a loss lately
        self.assertIn("not positive", value.own_history(turned, self.closes(lambda d: 50.0), date(2026, 9, 25))["why_not"])
        self.assertIsNone(value.own_history({}, {}, date(2026, 9, 25)))

    def test_it_reaches_the_card(self):
        body = template_function("renderCompanies")
        self.assertIn("peHistoryBlock(c.pe_history)", body)
        self.assertIn('value.own_history(f, price_store.series(prices, ticker, "c"), today, splits)',
                      inspect.getsource(build_desk.build_companies))
        self.assertIn("foldOpen(", template_function("peHistoryBlock"))


class LatestPriceTests(unittest.TestCase):
    """The user asked for pre- and post-market prices beside the close (AMD closed at
    $629.26 and was $638 before the open). Fetched on each refresh, never on a timer."""

    def test_one_request_for_every_company_with_extended_hours(self):
        seen = []

        def opener(req, timeout):
            seen.append((req.full_url, req.headers.get("Authorization")))
            return FakeResponse([
                {"ticker": "AMD", "tngoLast": 638.0, "last": 637.9, "timestamp": "2026-09-25T08:42:10.186520297-04:00"},
                {"ticker": "KO", "tngoLast": None, "last": 71.2, "timestamp": "2026-09-25T12:40:00+00:00"},
                {"ticker": "ZZZ", "tngoLast": 0, "timestamp": "2026-09-25T12:40:00Z"},          # no price
                {"ticker": "NOPE", "tngoLast": 5.0, "timestamp": "2026-09-25T12:40:00Z"}])       # not asked for
        out = prices.fetch_latest(["amd", "KO", "ZZZ"], key="k", opener=opener)
        self.assertEqual(seen, [("https://api.tiingo.com/iex/?tickers=amd,ko,zzz&afterHours=true", "Token k")])
        self.assertEqual(out["quotes"], {"AMD": {"price": 638.0, "at": "2026-09-25T12:42:10+00:00"},
                                         "KO": {"price": 71.2, "at": "2026-09-25T12:40:00+00:00"}})
        self.assertEqual(prices.fetch_latest([], key="k", opener=opener)["quotes"], {})
        self.assertEqual(len(seen), 1)                                   # nothing to ask, nothing asked

        def refused(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
        with self.assertRaises(prices.PriceError):
            prices.fetch_latest(["AMD"], key="k", opener=refused)

    def test_the_session_is_read_on_new_yorks_clock(self):
        for stamp, name in (("2026-09-25T12:42:00Z", "Pre-market"),        # 08:42 in New York, summer time
                            ("2026-01-15T13:00:00Z", "Pre-market"),        # 08:00, winter time
                            ("2026-01-15T14:29:00Z", "Pre-market"),        # 09:29
                            ("2026-09-25T15:00:00Z", "Regular session"),
                            ("2026-09-25T21:30:00Z", "After hours"),       # 17:30
                            ("2026-09-26T01:00:00Z", "Overnight"),         # 21:00 the evening before
                            ("2026-09-25T07:00:00Z", "Overnight")):        # 03:00
            self.assertEqual(prices.session(prices.moment(stamp)), name, stamp)
        self.assertIsNone(prices.moment("yesterday"))

    def test_every_moment_is_read_by_one_reader_python_39_accepts(self):
        """28 Sep 2026: the Mac's python3 is 3.9, whose datetime.fromisoformat reads neither a
        "Z" (Trading 212's and the SEC's stamps) nor nine digits after the second (Tiingo's);
        3.11 reads both, so a direct call passed every test here and dropped the stamp on the
        Mac. env_config.moment is the one reader, written so that 3.9 takes what it builds."""
        utc = timezone.utc
        for stamp, meant in (("2026-09-25T14:00:00Z", datetime(2026, 9, 25, 14, tzinfo=utc)),
                             ("2026-09-25T14:00:00.123Z", datetime(2026, 9, 25, 14, 0, 0, 123000, tzinfo=utc)),
                             ("2026-09-25T10:00:00.186520297-04:00", datetime(2026, 9, 25, 14, 0, 0, 186520, tzinfo=utc)),
                             ("2026-09-25T14:00:00+00:00", datetime(2026, 9, 25, 14, tzinfo=utc)),
                             ("2026-09-25T19:30:00+0530", datetime(2026, 9, 25, 14, tzinfo=utc)),
                             ("2026-09-25T14:00:00", datetime(2026, 9, 25, 14, tzinfo=utc)),     # the desk's own: UTC
                             ("2026-09-25 14:00", datetime(2026, 9, 25, 14, tzinfo=utc))):
            self.assertEqual(env_config.moment(stamp), meant, stamp)
        for never in ("2026-09-25", "2026-02-30T10:00:00Z", "yesterday", "", None, 20260925):
            self.assertIsNone(env_config.moment(never), never)
        self.assertIs(prices.moment, env_config.moment)
        # no module reads a stamp any other way; the three left build a date or a day from parts
        allowed = {"env_config.py": 1, "news.py": 1, "fundamentals.py": 3}
        for name in sorted(os.listdir(ROOT)):
            if name.endswith(".py"):
                calls = open(os.path.join(ROOT, name)).read().count("datetime.fromisoformat(")
                self.assertLessEqual(calls, allowed.get(name, 0), name)

    def test_only_a_price_taken_after_the_close_is_shown_beside_it(self):
        close = ("2026-09-24", 629.26)
        pre = prices.latest_after_close({"price": 638.0, "at": "2026-09-25T12:42:10+00:00"}, *close)
        self.assertEqual((pre["session"], pre["price"]), ("Pre-market", 638.0))
        self.assertAlmostEqual(pre["change"], 638.0 / 629.26 - 1)
        after = prices.latest_after_close({"price": 631.0, "at": "2026-09-24T20:05:00+00:00"}, *close)
        self.assertEqual(after["session"], "After hours")                  # 16:05 on the close's own day
        self.assertIsNone(prices.latest_after_close({"price": 630.0, "at": "2026-09-24T19:59:00+00:00"}, *close))
        self.assertIsNone(prices.latest_after_close(None, *close))
        self.assertIsNone(prices.latest_after_close({"price": 1.0, "at": None}, *close))
        self.assertFalse(pre["check"])
        # a 2-for-1 split overnight: the quote is in the new shares, the close in the old
        split = prices.latest_after_close({"price": 319.0, "at": "2026-09-25T12:42:10+00:00"}, *close)
        self.assertTrue(split["check"])
        self.assertIn("q.check", page_source())

    def test_the_card_carries_it_and_the_refresh_fetches_it(self):
        days = {"2026-09-23": {"c": 600.0, "a": 600.0}, "2026-09-24": {"c": 629.26, "a": 629.26}}
        quote = {"price": 638.0, "at": "2026-09-25T12:42:10+00:00"}
        card = build_desk.price_summary(prices.series({"AMD": days}, "AMD"), {}, date(2026, 9, 25), quote)
        self.assertEqual((card["close"], card["latest"]["price"]), (629.26, 638.0))
        self.assertIsNone(build_desk.price_summary(prices.series({"AMD": days}, "AMD"), {}, date(2026, 9, 25))["latest"])
        self.assertIn('("Latest prices", lambda: (prices.fetch_latest(covered), "quotes.json"), "tiingo"',
                      inspect.getsource(server.Handler.update_research))
        self.assertIn("quotes.json", read(os.path.join(ROOT, ".gitignore")))
        body = template_function("renderCompanies")
        self.assertIn("latestCol(p)", body)
        self.assertIn("esc(q.session)", template_function("latestCol"))


class FundamentalsTests(unittest.TestCase):
    def concept(self, tag, rows):
        return {"units": {"USD": rows}}

    def quarters(self, start_year, n, value, step=1.0):
        rows, v = [], value
        for i in range(n):
            q = i % 4
            year = start_year + i // 4
            starts = ["01-01", "04-01", "07-01", "10-01"][q]
            ends = ["03-31", "06-30", "09-30", "12-31"][q]
            rows.append({"start": f"{year}-{starts}", "end": f"{year}-{ends}", "val": v, "form": "10-Q"})
            v *= step
        return rows

    def trailing_year(self, rows):
        """(latest twelve months, the twelve before, end date), as the card shows them:
        through derive, not a test-only wrapper (K-05)."""
        card = fundamentals.derive("ZZZ", 1, {"revenue": rows}, {})
        return card["revenue"], card["revenue_prev"], card["revenue_asof"]

    def test_trailing_year_sums_four_quarters_and_the_four_before(self):
        facts = [{"start": r["start"], "end": r["end"], "val": r["val"], "form": "10-Q"}
                 for r in self.quarters(2024, 8, 100.0)]
        now, before, end = self.trailing_year(facts)
        self.assertEqual(now, 400.0)
        self.assertEqual(before, 400.0)
        self.assertEqual(end, "2025-12-31")

    def test_stale_quarters_give_way_to_a_newer_annual_report(self):
        """JPMorgan stopped tagging three-month quarters in 2014 and kept filing
        10-Ks. Its card showed 2014 revenue as the latest year."""
        facts = [dict(r, form="10-Q") for r in self.quarters(2013, 8, 25.0)]
        for year, value in ((2024, 150.0), (2025, 160.0)):
            facts.append({"start": f"{year}-01-01", "end": f"{year}-12-31", "val": value, "form": "10-K"})
            facts.append({"start": f"{year}-01-01", "end": f"{year}-12-31", "val": value, "form": "10-K/A"})
        facts.sort(key=lambda r: (r["end"], r["start"]))
        self.assertEqual(self.trailing_year(facts), (160.0, 150.0, "2025-12-31"))

    def test_quarters_with_a_gap_are_not_summed_as_a_year(self):
        """A company that tags Q1-Q3 but leaves Q4 inside the annual figure: the
        four newest quarterly rows straddle the missing one."""
        rows = [r for r in self.quarters(2024, 8, 100.0) if not r["end"].endswith("12-31")]
        rows.append({"start": "2025-01-01", "end": "2025-12-31", "val": 420.0, "form": "10-K"})
        rows.sort(key=lambda r: (r["end"], r["start"]))
        now, before, end = self.trailing_year(rows)
        self.assertEqual((now, end), (420.0, "2025-12-31"))

    def test_a_missing_fourth_quarter_is_the_year_less_the_other_three(self):
        """AMD tags Q1-Q3 and leaves Q4 inside the 10-K. The latest twelve months
        to June are Q2 + Q1 + (year − Q1..Q3) + Q3, not the year before."""
        rows = [r for r in self.quarters(2025, 6, 100.0, step=1.1) if not r["end"].endswith("12-31")]
        q = {r["end"]: r["val"] for r in rows}
        rows.append({"start": "2025-01-01", "end": "2025-12-31", "val": 500.0, "form": "10-K"})
        rows.sort(key=lambda r: (r["end"], r["start"]))
        now, _, end = self.trailing_year(rows)
        fourth = 500.0 - q["2025-03-31"] - q["2025-06-30"] - q["2025-09-30"]
        expected = q["2026-06-30"] + q["2026-03-31"] + fourth + q["2025-09-30"]
        self.assertEqual(end, "2026-06-30")
        self.assertAlmostEqual(now, expected)

    def test_an_empty_concept_is_read_from_the_full_company_file(self):
        """The SEC's per-concept endpoint returns no facts for Coca-Cola's Revenues;
        its full company-facts file has them."""
        asked = []

        def fetch(url, ua, **kw):
            asked.append(url)
            if "companyfacts" in url:
                return {"facts": {"us-gaap": {"Revenues": self.concept("Revenues", self.quarters(2024, 8, 100.0))}}}
            return {"units": {"USD": []}}
        out = fundamentals.for_company("KO", 21344, "ua", fetch=fetch)
        self.assertEqual((out["revenue"], out["revenue_asof"]), (400.0, "2025-12-31"))
        self.assertEqual(sum(1 for u in asked if "companyfacts" in u), 1)

    def test_a_balance_from_an_old_balance_sheet_is_not_shown_as_current(self):
        """S-05: Starbucks stopped using the cash tag in 2022; its newest fact under it
        was shown as today's cash."""
        def point(end, val):
            return {"end": end, "val": val, "form": "10-Q"}

        def fetch(url, ua, **kw):
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            if tag == "CashAndCashEquivalentsAtCarryingValue":
                return self.concept(tag, [point("2022-07-03", 2.8e9)])
            if tag == "Assets":
                return self.concept(tag, [point("2022-07-03", 27e9), point("2026-06-28", 31e9)])
            if tag == "StockholdersEquity":
                return self.concept(tag, [point("2026-06-28", -7.5e9)])
            return None
        out = fundamentals.for_company("SBUX", 1, "ua", fetch=fetch)
        self.assertNotIn("cash", out)
        self.assertEqual(out["cash_stale"], "2022-07-03")
        self.assertEqual(out["equity"], -7.5e9)                       # dated at the sheet: kept

    def test_cash_under_the_newer_tag_says_it_includes_restricted_cash(self):
        """S-07: Starbucks, AIT and JPMorgan file cash only under the post-2018 tag,
        which includes restricted cash — shown, and labelled as the broader figure."""
        def point(end, val):
            return {"end": end, "val": val, "form": "10-Q"}

        def fetch(url, ua, **kw):
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            if tag == "CashAndCashEquivalentsAtCarryingValue":
                return self.concept(tag, [point("2022-07-03", 2.8e9)])
            if tag == "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents":
                return self.concept(tag, [point("2026-06-28", 3.2e9)])
            if tag == "Assets":
                return self.concept(tag, [point("2026-06-28", 31e9)])
            return None
        out = fundamentals.for_company("SBUX", 1, "ua", fetch=fetch)
        self.assertEqual((out["cash"], out["cash_asof"]), (3.2e9, "2026-06-28"))
        self.assertTrue(out["cash_includes_restricted"])
        self.assertIn("incl. restricted", template_function("topPeriod"))

    def test_a_margin_takes_its_profit_over_revenues_own_period(self):
        """S-09: JPMorgan's revenue is its 2025 annual figure and its profit runs to
        June 2026, so the net margin was blank. The 2025 profit is in the same 10-K."""
        annual = lambda y, v: {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": "10-K"}

        def fetch(url, ua, **kw):
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            if tag == "Revenues":
                return self.concept(tag, [annual(2024, 177e9), annual(2025, 182e9)])
            if tag == "NetIncomeLoss":
                return self.concept(tag, [annual(2024, 58e9), annual(2025, 57e9)] + self.quarters(2025, 6, 14e9))
            return None
        out = fundamentals.for_company("JPM", 1, "ua", fetch=fetch)
        self.assertNotEqual(out["net_income_asof"], out["revenue_asof"])
        self.assertAlmostEqual(out["net_margin"], 57e9 / 182e9)

    def test_debt_that_was_not_filed_is_not_zero_leverage(self):
        """S-06: a missing debt figure counted as zero and printed 0.00."""
        def fetch(url, ua, **kw):
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            if tag in ("Assets", "StockholdersEquity"):
                return self.concept(tag, [{"end": "2026-06-30", "val": 5e9, "form": "10-Q"}])
            return None
        out = fundamentals.for_company("ZZZ", 1, "ua", fetch=fetch)
        self.assertNotIn("debt_to_equity", out)

    def test_newest_reporting_tag_wins(self):
        calls = {}

        def fetch(url, ua, **kw):
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            calls[tag] = True
            if tag == "Revenues":                       # stale tag, stopped in 2020
                return self.concept(tag, self.quarters(2019, 8, 50.0))
            if tag == "RevenueFromContractWithCustomerExcludingAssessedTax":
                return self.concept(tag, self.quarters(2024, 8, 100.0))
            return None
        out = fundamentals.for_company("ZZZ", 1, "ua", fetch=fetch)
        self.assertEqual(out["revenue"], 400.0)
        self.assertEqual(out["revenue_asof"], "2025-12-31")

    def test_margin_from_mismatched_periods_is_dropped(self):
        def fetch(url, ua, **kw):
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            if tag == "RevenueFromContractWithCustomerExcludingAssessedTax":
                return self.concept(tag, self.quarters(2024, 8, 100.0))
            if tag == "GrossProfit":                    # only old quarters reported
                return self.concept(tag, self.quarters(2019, 8, 40.0))
            return None
        out = fundamentals.for_company("ZZZ", 1, "ua", fetch=fetch)
        self.assertIsNone(out["gross_margin"])

    def test_absurd_values_never_reach_the_page(self):
        self.assertIsNone(fundamentals._possible("gross_margin", 16.2))      # 1615%: cannot be
        self.assertEqual(fundamentals._possible("gross_margin", 0.62), 0.62)

    def test_a_real_extreme_is_not_hidden_by_a_bound_of_our_own(self):
        """S-10: a -800% operating margin and a fifteenfold rise in sales are real;
        the old bounds (-500%, +1,000%) were invented and hid them."""
        self.assertEqual(fundamentals._possible("operating_margin", -8.0), -8.0)
        self.assertEqual(fundamentals._possible("revenue_growth", 15.0), 15.0)
        self.assertEqual(fundamentals._possible("net_margin", 1.7), 1.7)       # a gain
        self.assertIsNone(fundamentals._possible("revenue_growth", -1.2))

    def test_figures_are_downloaded_again_only_after_a_new_report(self):
        """Every refresh asked the SEC for fifteen files a company, some of several
        megabytes, over a slow connection, for figures that change only when the company
        files. Stored facts that include the latest report are recomputed, not fetched;
        a company that has filed since, or whose report the SEC's data lacks (S-21), is
        fetched as before."""
        def facts(filed):
            return {"revenue": [dict(r, filed=filed) for r in self.quarters(2024, 8, 100.0)]}
        stored = {"companies": {
            "KO": dict(fundamentals.card("KO", 21344, facts("2026-07-29"), {"revenue": "Revenues"}), revenue=1.0),
            "AMD": fundamentals.card("AMD", 2488, facts("2026-05-06"), {"revenue": "Revenues"}),
            "SBUX": fundamentals.card("SBUX", 829224, facts("2026-04-29"), {"revenue": "Revenues"})}}
        filings = [{"ticker": "KO", "form": "10-Q", "date": "2026-07-29"},
                   {"ticker": "KO", "form": "8-K", "date": "2026-09-01"},        # brings no figures
                   {"ticker": "AMD", "form": "10-Q", "date": "2026-08-05"},      # filed since
                   {"ticker": "SBUX", "form": "10-Q", "date": "2026-07-29"}]     # the SEC's data lags it
        asked = []

        def fetch(url, ua, **kw):
            asked.append(url)
            return self.concept("Revenues", self.quarters(2024, 8, 100.0))
        real = fundamentals.cik_map
        fundamentals.cik_map = lambda ua, fetch=None: {"KO": 21344, "AMD": 2488, "SBUX": 829224, "NVDA": 1045810}
        try:
            out = fundamentals.update(["KO", "AMD", "SBUX", "NVDA"], ua="ua", fetch=fetch,
                                      stored=stored, filings=filings)
            self.assertFalse([u for u in asked if "0000021344" in u])
            for cik in ("0000002488", "0000829224", "0001045810"):
                self.assertTrue([u for u in asked if cik in u], cik)
            # recomputed with today's code from the stored facts, not the stored figure
            self.assertEqual(out["companies"]["KO"]["revenue"], 400.0)
            self.assertEqual(out["companies"]["KO"]["facts"], stored["companies"]["KO"]["facts"])
            asked.clear()
            fundamentals.update(["KO"], ua="ua", fetch=fetch, stored=stored)      # no filings: no telling
            self.assertTrue([u for u in asked if "0000021344" in u])
        finally:
            fundamentals.cik_map = real


class EarningsTests(unittest.TestCase):
    ROWS = [{"period": "2026-09-30", "actual": 2.22, "estimate": 2.1384, "surprisePercent": 3.8159},
            {"period": "2026-06-30", "actual": 1.87, "estimate": 1.7922, "surprisePercent": 4.3},
            {"period": "2026-03-31", "actual": 1.40, "estimate": 1.50, "surprisePercent": -6.7},
            {"period": "2025-12-31", "actual": None, "estimate": 1.2, "surprisePercent": None}]

    def fetch(self, path, key, **kw):
        if path.startswith("stock/earnings"):
            return list(self.ROWS)
        return {"earningsCalendar": [{"date": "2026-11-17", "hour": "amc", "epsEstimate": 2.52},
                                     {"date": "2027-02-20", "hour": "bmo", "epsEstimate": 2.9}]}

    def test_history_skips_rows_without_an_actual(self):
        h = earnings.history_for("ZZZ", "k", fetch=self.fetch)
        self.assertEqual(len(h), 3)
        self.assertEqual(h[0]["date"], "2026-09-30")
        self.assertTrue(h[0]["beat"])
        self.assertFalse(h[2]["beat"])
        self.assertAlmostEqual(h[0]["surprise_pct"], 0.038159, places=5)

    def test_next_report_is_the_soonest_one(self):
        n = earnings.next_for("ZZZ", "k", today=date(2026, 9, 21), fetch=self.fetch)
        self.assertEqual(n["date"], "2026-11-17")
        self.assertEqual(n["when"], "after the close")

    def test_company_card_has_facts_and_no_advice(self):
        news_data = {"tickers": ["ZZZ"], "companies": {"ZZZ": "ZZZ CORP"}, "items": []}
        funds = {"companies": {"ZZZ": {"revenue": 4.0e9, "revenue_growth": 0.2, "net_margin": 0.25,
                                       "revenue_asof": "2026-06-30"}}}
        earn = {"companies": {"ZZZ": {"history": earnings.history_for("ZZZ", "k", fetch=self.fetch),
                                      "next": {"date": "2026-11-17", "when": "after the close"}}}}
        d = build_desk.compute({}, {}, date(2026, 9, 21), news=news_data, prices={},
                               fundamentals=funds, earnings=earn)
        card = d["companies"][0]
        self.assertEqual(card["ticker"], "ZZZ")
        self.assertEqual(card["days_to_earnings"], 57)
        self.assertEqual((card["beats"]["k"], card["beats"]["n"]), (2, 3))
        self.assertEqual(card["beats"], forecasts.beat_record(earn["companies"]["ZZZ"]["history"]))
        self.assertAlmostEqual(card["revenue_growth"], 0.2)


class ContextTests(unittest.TestCase):
    """Everything the desk knows about one company, gathered onto its card."""

    def company(self, ticker="ZZZ", cik=1, **figures):
        row = {"ticker": ticker, "cik": cik, "name": ticker,
               "assets": [1000.0, 900.0], "revenue": [800.0, 700.0],
               "net_income": [100.0, 50.0], "equity": [500.0, 450.0],
               "retained_earnings": [300.0, 250.0], "operating_income": [120.0, 60.0],
               "operating_cash_flow": [150.0, 80.0], "gross_profit": [400.0, 330.0],
               "debt": [100.0, 150.0], "current_assets": [400.0, 300.0],
               "current_liabilities": [200.0, 200.0], "shares": [10.0, 10.0],
               "shares_outstanding": [10.0]}
        for key, figure in figures.items():
            row[key] = figure if isinstance(figure, list) else [figure]
        return row

    def store(self, rows):
        return {"companies": {r["ticker"]: r for r in rows}}

    def test_a_line_is_the_measure_applied_to_each_filed_year(self):
        """Phase 5 sparklines: screen.history runs the one measures() over each year,
        oldest first, so the line and the definition behind it cannot drift."""
        row = self.company(revenue=[800.0, 700.0, 640.0], gross_profit=[400.0, 330.0, 300.0],
                           assets=[1000.0, 900.0, 850.0], equity=[500.0, 450.0, 420.0],
                           net_income=[100.0, 50.0, 40.0], debt=[100.0, 150.0, 160.0])
        lines = screen.history(row, ["gross_margin", "revenue_growth", "revenue"])
        self.assertEqual(lines["revenue"], [640.0, 700.0, 800.0])
        self.assertEqual(lines["gross_margin"][-1], screen.measures(row)["gross_margin"])
        self.assertEqual(lines["gross_margin"][0], 300.0 / 640.0)
        self.assertIsNone(lines["revenue_growth"][0])                 # nothing before the first year
        self.assertAlmostEqual(lines["revenue_growth"][-1], 800.0 / 700.0 - 1)

    def test_a_slipped_year_is_a_gap_only_in_the_lines_built_on_it(self):
        """AMD's 2021 long-term debt is filed a million times too large: its debt to
        equity that year is a gap, its revenue is not."""
        row = self.company(debt=[100.0, 150.0, 1.5e11], assets=[1000.0, 900.0, 850.0],
                           equity=[500.0, 450.0, 420.0], revenue=[800.0, 700.0, 640.0],
                           net_income=[100.0, 50.0, 40.0])
        lines = screen.history(row, ["debt_to_equity", "revenue"])
        self.assertIsNone(lines["debt_to_equity"][0])
        self.assertEqual(lines["revenue"][0], 640.0)
        self.assertAlmostEqual(lines["debt_to_equity"][-1], 0.2)

    def test_a_bank_draws_no_line_built_on_its_revenue(self):
        rows = [self.company("B%02d" % i, cik=300 + i) for i in range(6)]
        store = dict(self.store(rows), built="2026-09-24")
        cards = [{"ticker": "B01"}]
        context.add_to(cards, store=store, codes={300 + i: 6022 for i in range(6)},
                       history=("revenue", "net_margin", "eps"))
        lines = cards[0]["context"]["history"]["lines"]
        self.assertEqual(set(lines["revenue"]) | set(lines["net_margin"]), {None})
        self.assertEqual(cards[0]["context"]["history"]["years"], ["2024", "2025"])
        makers = [{"ticker": "B01"}]
        context.add_to(makers, store=store, codes={300 + i: 3571 for i in range(6)}, history=("revenue",))
        self.assertEqual(makers[0]["context"]["history"]["lines"]["revenue"], [700.0, 800.0])

    def test_the_cards_figures_are_listed_once(self):
        template = page_source()
        self.assertIn("(DATA.card_top || []).map(", template)
        self.assertNotIn("['revenue', 'revenue_growth'", template)
        self.assertIn("history=CARD_TOP", open(os.path.join(ROOT, "build_desk.py")).read())
        self.assertTrue(set(build_desk.CARD_TOP) <= set(screen.MEASURE_DISPLAY))

    def test_alike_measures_share_a_scale_and_a_gap_breaks_the_line(self):
        program = ("var DATA = {measure_display: %s};\n%s\n"
                   "var h = {lines: {gross_margin: [0.5, 0.5, 0.5], net_margin: [0.1, null, 0.2], revenue: [1, 2, 3]}};\n"
                   "var block = ['gross_margin', 'net_margin', 'revenue'];\n"
                   "var __out = [sparkline('gross_margin', h, block), sparkline('net_margin', h, block),"
                   " sparkline('revenue', {lines: {revenue: [5, null]}}, block)].join('|');\n"
                   "(typeof process !== 'undefined') ? console.log(__out) : __out;"
                   % (json.dumps(build_desk.measure_display()), template_function("sparkline")))
        printed = run_javascript(program)
        gross, net, lone = printed.split("|")
        # on one scale from 0.1 to 0.5, the gross margin sits at the top, not mid-box
        self.assertIn("M1.0 2.0", gross)
        self.assertEqual(net.count("M"), 2)                          # the gap splits the line
        self.assertEqual(lone, "")                                   # one point is not a line

    def test_each_money_figure_draws_on_its_own_scale(self):
        """Fifth review, Q2: cash on revenue's scale drew flat — "nothing happened",
        which is false. Cash doubling from 1 to 2 beside revenue of 100 spans its box."""
        program = ("var DATA = {measure_display: %s};\n%s\n"
                   "var h = {lines: {revenue: [100, 110, 120], cash: [1, 1.5, 2]}};\n"
                   "var __out = sparkline('cash', h, ['revenue', 'cash']);\n"
                   "(typeof process !== 'undefined') ? console.log(__out) : __out;"
                   % (json.dumps(build_desk.measure_display()), template_function("sparkline")))
        cash = run_javascript(program)
        self.assertIn("M1.0 14.0", cash)                             # its lowest year at the bottom
        self.assertIn("L59.0 2.0", cash)                             # and its highest at the top

    def test_a_company_gets_its_scores_without_an_industry_or_a_price(self):
        """Each part is optional. A missing one is absent, not guessed at."""
        out = context.for_company("ZZZ", self.store([self.company()]))
        self.assertEqual(out["piotroski"]["out_of"], 9)
        self.assertIsNotNone(out["altman"]["score"])
        self.assertNotIn("industry", out)
        self.assertNotIn("valuation", out)

    def test_a_company_on_a_broken_scale_gets_no_context_at_all(self):
        row = self.company("AIT", revenue=4.6e9, assets=2.9e9, net_income=392988.0)
        out = context.for_company("AIT", self.store([row]))
        self.assertIn("ratio built on it", out["why_not"])
        self.assertNotIn("piotroski", out)

    def test_a_financial_company_is_told_the_models_do_not_apply(self):
        """JPMorgan scores two of six Piotroski signals, which reads as weak when it
        means the test does not fit a bank. Altman excludes financial firms himself."""
        rows = [self.company("B%02d" % i, cik=300 + i) for i in range(6)]
        codes = {300 + i: 6022 for i in range(6)}                    # state banks
        out = context.for_company("B01", self.store(rows), codes)
        self.assertFalse(out["models_apply"])
        self.assertIn("not as weak", out["models_note"])
        self.assertIsNone(out["altman"]["band"])
        self.assertIn("financial firms", out["altman"]["why_not"])
        industrial = {300 + i: 3571 for i in range(6)}
        self.assertNotIn("models_apply", context.for_company("B01", self.store(rows), industrial))

    def test_a_bank_is_compared_with_its_peers_only_on_return_on_assets(self):
        """A bank's tagged revenue leaves out interest income; the median net margin
        of JPMorgan's peers read 104.6%."""
        rows = [self.company("B%02d" % i, cik=300 + i) for i in range(6)]
        banks = context.for_company("B01", self.store(rows), {300 + i: 6022 for i in range(6)})
        self.assertEqual(list(banks["peer_standing"]), ["return_on_assets"])
        self.assertIn("interest income", banks["industry"]["note"])
        makers = context.for_company("B01", self.store(rows), {300 + i: 3571 for i in range(6)})
        self.assertIn("net_margin", makers["peer_standing"])

    def test_below_ten_reporting_a_rank_is_shown_not_a_percentile(self):
        """J-06: SBUX showed "percentile 100 · reported by 5". From five values a
        percentile moves in steps of 20; "highest of 5" is what it means."""
        rows = [self.company("T%02d" % i, cik=100 + i) for i in range(6)]
        for i, row in enumerate(rows):
            row["net_income"] = [10.0 * (i + 1)]
        codes = {100 + i: 3571 for i in range(6)}
        found = sectors.compare("T05", screen.measures, self.store(rows)["companies"], codes,
                                measures=["net_margin"])
        standing = found["measures"]["net_margin"]
        self.assertEqual((standing["rank"], standing["of"]), (1, 6))
        out = context.for_company("T05", self.store(rows), codes)
        self.assertEqual(out["industry"]["rank_below"], sectors.RANK_BELOW)
        body = template_function("standing")
        self.assertIn("m.of < rankBelow", body)
        self.assertNotRegex(body, r"<\s*10\b")          # the line is data, not typed in

    def test_an_even_sized_peer_group_has_a_true_median(self):
        """S-04: known[n // 2] took the upper of the two middle values."""
        rows = [self.company("T%02d" % i, cik=100 + i) for i in range(7)]
        for i, row in enumerate(rows):
            row["net_income"] = [10.0 * (i + 1)]                 # peers of T06: 10..60
        codes = {100 + i: 3571 for i in range(7)}
        found = sectors.compare("T06", screen.measures, self.store(rows)["companies"], codes,
                                measures=["net_income"])
        self.assertEqual(found["measures"]["net_income"]["median"], 35.0)

    def test_peer_standing_appears_only_with_enough_peers(self):
        rows = [self.company("T%02d" % i, cik=100 + i) for i in range(8)]
        codes = {100 + i: 3571 for i in range(8)}
        out = context.for_company("T01", self.store(rows), codes)
        self.assertEqual(out["industry"]["peers"], 8)
        self.assertIn("net_margin", out["peer_standing"])
        thin = context.for_company("T01", self.store(rows[:3]),
                                   {100 + i: 3571 for i in range(3)})
        self.assertNotIn("peer_standing", thin)

    def test_an_unchecked_share_basis_does_not_read_like_a_passed_check(self):
        """Not every company files a public float — 5,248 of 6,323 in the latest
        year. Where none is on record nothing cross-checks the market cap, and the
        card has to say so."""
        class Prices:
            @staticmethod
            def series(store, ticker, kind="a"):
                return {"2026-09-18": 50.0}
        out = context.for_company("ZZZ", self.store([self.company()]),
                                  prices={"ZZZ": {}}, price_store=Prices)
        check = out["valuation"]["float_check"]
        self.assertIsNone(check["plausible"])
        self.assertIn("could not be checked", check["note"])

    def test_the_latest_printed_close_is_used_not_the_adjusted_one(self):
        """The adjusted close is rebased for dividends and splits; a market cap
        needs what the shares actually trade at."""
        asked = {}

        class Prices:
            @staticmethod
            def series(store, ticker, kind="a"):
                asked["kind"] = kind
                return {"2026-09-01": 10.0, "2026-09-18": 50.0}
        out = context.for_company("ZZZ", self.store([self.company()]),
                                  prices={"ZZZ": {}}, price_store=Prices)
        self.assertEqual(asked["kind"], "c")
        self.assertEqual(out["valuation"]["price"], 50.0)

    def test_liabilities_fall_back_to_the_accounting_identity(self):
        """Many companies never tag Liabilities — AMD and Nike both omit it — and
        assets minus equity is exact, not an estimate."""
        row = self.company()
        self.assertEqual(screen.liabilities(row), 500.0)     # 1000 assets - 500 equity
        row["liabilities"] = [420.0]
        self.assertEqual(screen.liabilities(row), 420.0)     # filed wins
        bare = {"ticker": "X"}
        self.assertIsNone(screen.liabilities(bare))

    def test_the_card_renderer_reads_the_keys_context_produces(self):
        template = page_source()
        out = context.for_company("ZZZ", self.store([self.company()]))
        for key in ("piotroski", "altman", "why_not"):
            self.assertIn("x." + key, template, key)
        self.assertIn("contextBlock(c.context)", template)


class ForecastTests(unittest.TestCase):
    """Scoring the forecast that can actually be checked."""

    def quarters(self, pairs):
        return [{"date": d, "actual": a, "estimate": e} for d, a, e in pairs]

    def test_too_few_quarters_is_not_a_track_record(self):
        thin = self.quarters([("2026-06-30", 1.0, 0.9), ("2026-03-31", 1.0, 0.9)])
        self.assertIsNone(forecasts.accuracy(thin))
        out = forecasts.for_company("AAA", {"companies": {"AAA": {"history": thin}}})
        self.assertIsNone(out["record"])
        self.assertIn("fewer than", out["why_not"])

    def test_the_record_counts_beats_misses_error_and_bias(self):
        rows = self.quarters([("2026-06-30", 1.10, 1.00), ("2026-03-31", 1.00, 1.00),
                              ("2025-12-31", 0.90, 1.00), ("2025-09-30", 1.20, 1.00)])
        out = forecasts.accuracy(rows)
        self.assertEqual((out["quarters"], out["beats"]["k"], out["missed"], out["met"]),
                         (4, 2, 1, 1))
        self.assertAlmostEqual(out["beats"]["estimate"], 0.5)
        self.assertEqual(out["beats"], forecasts.beat_record(rows))
        self.assertIsNotNone(out["median_error"])
        self.assertIn("Walk-down", out["source"])

    def test_a_high_hit_rate_is_reported_with_why_that_is_normal(self):
        """Four beats out of four is the usual state, not an achievement — estimates
        are walked down to a level management can clear."""
        rows = self.quarters([("2026-06-30", 1.10, 1.00), ("2026-03-31", 1.10, 1.00),
                              ("2025-12-31", 1.10, 1.00), ("2025-09-30", 1.10, 1.00)])
        out = forecasts.accuracy(rows)
        self.assertEqual(out["beats"]["estimate"], 1.0)
        self.assertNotIn("expected", out["beats"])          # never compared with half
        self.assertEqual(out["beats"]["reads"], "uncertain")  # four quarters cannot establish a rate
        self.assertIn("normal state", out["finding"])
        self.assertIn("below what was reported", forecasts.bias_reads(out["median_bias"]))

    def test_a_zero_actual_does_not_become_a_percentage(self):
        rows = self.quarters([("2026-06-30", 0.0, 0.10), ("2026-03-31", 1.0, 0.9),
                              ("2025-12-31", 1.0, 0.9), ("2025-09-30", 1.0, 0.9)])
        out = forecasts.accuracy(rows)
        self.assertEqual(out["quarters"], 4)          # still counted as a quarter
        self.assertIsNotNone(out["median_error"])     # but not as a percentage error

    def test_a_negligible_bias_is_not_dressed_up(self):
        self.assertIn("close to", forecasts.bias_reads(0.001))
        self.assertIsNone(forecasts.bias_reads(None))


class EarningsHistoryTests(unittest.TestCase):
    """Finnhub returns four quarters; the record has to outlive that."""

    def test_stored_quarters_are_kept_not_replaced(self):
        """Replacing the history caps the forecast record at four quarters however
        long this desk runs, which would make the record permanently thin."""
        stored = [{"date": "2024-12-31", "actual": 1.0, "estimate": 0.9},
                  {"date": "2025-03-31", "actual": 1.1, "estimate": 1.0}]
        fetched = [{"date": "2025-03-31", "actual": 1.15, "estimate": 1.0},
                   {"date": "2025-06-30", "actual": 1.2, "estimate": 1.1}]
        merged = earnings.merge_history(stored, fetched)
        self.assertEqual([q["date"] for q in merged],
                         ["2025-06-30", "2025-03-31", "2024-12-31"])
        restated = next(q for q in merged if q["date"] == "2025-03-31")
        self.assertEqual(restated["actual"], 1.15)    # a restatement wins

    def test_update_carries_the_stored_history_through(self):
        def fetch(path, key, **kw):
            if path.startswith("stock/earnings"):
                return [{"period": "2026-06-30", "actual": 2.0, "estimate": 1.8}]
            return {}
        stored = {"companies": {"AAA": {"history": [
            {"date": "2025-06-30", "actual": 1.0, "estimate": 0.9}]}}}
        out = earnings.update(["AAA"], key="k", fetch=fetch, stored=stored)
        dates = [q["date"] for q in out["companies"]["AAA"]["history"]]
        self.assertEqual(dates, ["2026-06-30", "2025-06-30"])


class ValueTests(unittest.TestCase):
    """Valuation is the one part that needs a price, and prices are the one input
    with a hard budget."""

    def company(self, ticker="ZZZ", **figures):
        row = {"ticker": ticker, "name": ticker, "assets": [1000.0], "revenue": [800.0],
               "net_income": [100.0], "equity": [500.0], "operating_income": [120.0],
               "debt": [200.0], "cash": [50.0], "dividends_paid": [-20.0],
               "shares_outstanding": [10.0], "shares": [11.0]}
        for key, figure in figures.items():
            row[key] = figure if isinstance(figure, list) else [figure]
        return row

    def priced(self, known, close=50.0):
        def fetch(ticker, start, key):
            return [("2026-09-22", close, close)] if ticker in known else []
        return fetch

    def test_market_cap_prefers_the_cover_page_share_count_and_says_which(self):
        """The weighted average diluted count is averaged over the year and includes
        dilution — a different number, and the wrong one for a market cap."""
        cap, basis = value.market_cap(self.company(), 50.0)
        self.assertEqual(cap, 500.0)
        self.assertIn("cover", basis)
        row = self.company()
        row.pop("shares_outstanding")
        cap, basis = value.market_cap(row, 50.0)
        self.assertEqual(cap, 550.0)
        self.assertIn("approximate", basis)

    def test_a_ratio_against_a_negative_denominator_is_dropped(self):
        """A P/E of -8 is not a cheap company, and screening on it silently puts the
        worst businesses at the top."""
        loss = value.measures(self.company(net_income=-100.0, equity=-200.0), 50.0)
        self.assertIsNone(loss["price_to_earnings"])
        self.assertIsNone(loss["price_to_book"])
        self.assertLess(loss["earnings_yield"], 0)        # still reported, signed

    def test_enterprise_value_adds_debt_and_takes_out_cash(self):
        values = value.measures(self.company(), 50.0)
        self.assertEqual(values["enterprise_value"], 500.0 + 200.0 - 50.0)
        self.assertAlmostEqual(values["ev_to_operating_income"], 650.0 / 120.0)

    def test_pricing_a_long_list_is_refused_rather_than_spending_the_budget(self):
        with self.assertRaises(value.ValuationError) as cm:
            value.for_tickers([f"T{i}" for i in range(80)], {"companies": {}},
                              key="k", limit=60)
        self.assertIn("Tighten the screen", str(cm.exception))

    def test_a_company_on_a_broken_scale_is_not_valued(self):
        row = self.company("AIT", revenue=4.6e9, assets=2.9e9, net_income=392988.0)
        out = value.for_tickers(["AIT"], {"companies": {"AIT": row}}, key="k",
                                fetch=self.priced({"AIT"}))
        self.assertIn("ratio built on it", out["AIT"]["error"])

    def test_the_year_the_figures_came_from_is_reported(self):
        """The price is today's and the profit is a filed year old — in September
        the newest complete year may be nine months stale."""
        out = value.for_tickers(["AAA"], {"companies": {"AAA": self.company("AAA")}},
                                key="k", fetch=self.priced({"AAA"}))
        self.assertEqual(out["AAA"]["figures_from"], universe.periods("flow", 1)[0])
        self.assertEqual(out["AAA"]["as_of"], "2026-09-22")

    def test_an_unpriceable_ticker_says_so_rather_than_being_skipped(self):
        out = value.for_tickers(["AAA"], {"companies": {"AAA": self.company("AAA")}},
                                key="k", fetch=self.priced(set()))
        self.assertIn("no recent price", out["AAA"]["error"])

    def test_a_market_cap_far_above_the_filed_float_is_flagged(self):
        """BeOne files 1.44bn ordinary shares and trades as ADS worth about thirteen
        of them, so price times share count reads 530bn against a filed public float
        of 14.7bn. Float is part of market value, not a multiple of it."""
        row = self.company("ONC", public_float=14.7e9, assets=15e9, revenue=5.9e9)
        bad = value.float_check(row, 530.9e9)
        self.assertFalse(bad["plausible"])
        self.assertIn("depositary shares", bad["note"])
        fine = value.float_check(row, 20.0e9)
        self.assertTrue(fine["plausible"])
        self.assertEqual(fine["note"], "")

    def test_a_market_cap_below_the_filed_float_is_explained_not_flagged(self):
        """Float is filed as of a past date, so a fallen price puts market value
        under it. That is ordinary, not a data fault."""
        row = self.company("AAA", public_float=100e9, assets=60e9)
        out = value.float_check(row, 80e9)
        self.assertTrue(out["plausible"])
        self.assertIn("fallen", out["note"])

    def test_an_older_float_is_used_when_the_newest_year_has_none(self):
        """AMD filed a float every year but the last. Reading only the newest slot
        skipped a check that an older float still does perfectly well."""
        row = self.company("AMD", public_float=[None, 232.3e9, 182.9e9])
        self.assertEqual(screen.latest_float(row), (232.3e9, 1))
        out = value.float_check(row, 900e9)
        self.assertTrue(out["plausible"])
        self.assertEqual(out["years_old"], 1)

    def test_a_failed_share_basis_withholds_every_figure_built_on_it(self):
        """BeOne's P/E read 1,850 beside the warning. A number known to be wrong
        is not printed, and Graham's limits cannot pass on it."""
        row = self.company("ONC", public_float=10.0)   # market value 1,000
        out = value.value_company(row, 100.0)
        self.assertFalse(out["float_check"]["plausible"])
        for name in value.FROM_MARKET_CAP:
            self.assertIsNone(out[name], name)
        self.assertEqual(out["price"], 100.0)
        self.assertIsNone(out["graham"]["price_to_earnings"]["passes"])
        self.assertIn("withheld", out["float_check"]["note"])

    def test_no_share_count_is_not_described_as_no_float(self):
        row = self.company("AAA", public_float=5e9)
        row["shares"], row["shares_outstanding"] = None, None
        out = value.value_company(row, 10.0)
        self.assertIsNone(out["float_check"]["plausible"])
        self.assertIn("no share count", out["float_check"]["note"])

    def test_the_card_and_the_priced_screen_value_a_company_the_same_way(self):
        """One definition: both reach value.value_company, so they cannot drift."""
        row = self.company("AAA")
        screened = value.for_tickers(["AAA"], {"companies": {"AAA": row}},
                                     key="k", fetch=self.priced({"AAA"}))["AAA"]
        direct = value.value_company(row, screened["price"])
        for name, figure in direct.items():
            self.assertEqual(screened[name], figure, name)
        source = open(os.path.join(ROOT, "context.py")).read()
        self.assertIn("value.value_company(", source)
        self.assertNotIn("value.float_check(", source)

    def test_a_float_in_the_wrong_unit_is_not_used(self):
        """S-11: Novanta files its float a thousand times too large in every year —
        3.5tn for a company with 1.8bn of assets — so its history is steady; its size
        is not. Champion Homes did so in four years of five."""
        novanta = self.company("NOVT", public_float=[3.5e12, 4.4e12, 5.0e12], assets=[1.8e9, 1.4e9, 1.2e9],
                               revenue=[0.95e9, 0.9e9, 0.86e9])
        self.assertEqual(screen.latest_float(novanta), (None, None))
        champion = self.company("SKY", public_float=[4.1e12, 5.4e12, 3.4e12, 3.4e9],
                                assets=[2.1e9, 2.0e9, 1.9e9, 1.1e9], revenue=[2.5e9, 2.4e9, 2.2e9, 2.0e9])
        self.assertEqual(screen.latest_float(champion), (3.4e9, 3))
        one_year = self.company("WWD", public_float=[9.8e12, 9.1e9, 8.7e9], assets=[4.6e9] * 3,
                                revenue=[3.3e9] * 3)
        self.assertEqual(screen.latest_float(one_year), (9.1e9, 1))
        raised = self.company("QXO", public_float=[13.7e9, 47.7e6, 11e6], assets=[15.9e9, 5.1e9, 20e6],
                              revenue=[6.8e9, 57e6, 55e6])
        self.assertEqual(screen.latest_float(raised), (13.7e9, 0))    # a real rise, kept
        nvidia = self.company("NVDA", public_float=4.0e12, assets=111e9, revenue=130e9)
        self.assertEqual(screen.latest_float(nvidia), (4.0e12, 0))      # 31 times its size: real

    def test_no_float_filed_means_no_check_rather_than_a_false_pass(self):
        self.assertIsNone(value.float_check(self.company("AAA"), 50e9))

    def test_grahams_two_valuation_limits_are_his_own(self):
        self.assertEqual((value.GRAHAM_PE, value.GRAHAM_PB), (15.0, 1.5))
        cheap = value.graham_valuation({"price_to_earnings": 12.0, "price_to_book": 1.2})
        self.assertTrue(cheap["price_to_earnings"]["passes"])
        self.assertTrue(cheap["price_to_book"]["passes"])
        dear = value.graham_valuation({"price_to_earnings": 40.0, "price_to_book": None})
        self.assertFalse(dear["price_to_earnings"]["passes"])
        self.assertIsNone(dear["price_to_book"]["passes"])
        self.assertIn("1973", dear["source"])


class AnalystTests(unittest.TestCase):
    def rows(self, **kw):
        base = {"strongBuy": 10, "buy": 20, "hold": 5, "sell": 1, "strongSell": 0}
        base.update(kw)
        return base

    def fetch_factory(self, months):
        def fetch(path, key, **kw):
            return [dict(m, period=p) for p, m in months]
        return fetch

    def test_score_and_label(self):
        self.assertEqual(analysts.label_for(1.6), "Strong buy")
        self.assertEqual(analysts.label_for(1.0), "Buy")
        self.assertEqual(analysts.label_for(0.0), "Hold")
        self.assertEqual(analysts.label_for(-1.0), "Sell")
        self.assertEqual(analysts.label_for(-1.9), "Strong sell")
        self.assertEqual(analysts.label_for(None), "No rating")
        value, count = analysts.score({"strongBuy": 1, "buy": 1, "hold": 0, "sell": 0, "strongSell": 0})
        self.assertAlmostEqual(value, 1.5)
        self.assertEqual(count, 2)

    def test_direction_compares_with_three_months_ago(self):
        months = [("2026-09-01", self.rows(strongBuy=20)), ("2026-08-01", self.rows()),
                  ("2026-07-01", self.rows()), ("2026-06-01", self.rows(strongBuy=2, hold=20))]
        out = analysts.for_company("ZZZ", "k", fetch=self.fetch_factory(months))
        self.assertEqual(out["as_of"], "2026-09-01")
        self.assertEqual(out["direction"], "more positive")
        self.assertEqual(out["analysts"], 46)
        self.assertEqual(len(out["history"]), 4)

    def test_sell_share_is_reported_so_the_skew_is_visible(self):
        months = [("2026-09-01", self.rows(sell=0, strongSell=0))]
        out = analysts.for_company("ZZZ", "k", fetch=self.fetch_factory(months))
        self.assertEqual(out["sell_share"], 0.0)

    def test_no_coverage_is_not_invented(self):
        out = analysts.for_company("ZZZ", "k", fetch=lambda *a, **k: [])
        self.assertIsNone(out)

    def test_ratings_reach_the_company_card(self):
        months = [("2026-09-01", self.rows())]
        rated = analysts.update(["ZZZ"], key="k", fetch=self.fetch_factory(months))
        d = build_desk.compute({}, {}, TODAY, news={"tickers": ["ZZZ"], "items": []},
                               prices={}, analysts=rated)
        card = d["companies"][0]
        self.assertEqual(card["analysts"]["verdict"], "Buy")
        self.assertEqual(card["analysts"]["counts"]["hold"], 5)


class BridgeTests(unittest.TestCase):
    """Phase 7: what changed between the last two annual reports, the same four
    blocks every time, computed by bridge.py from the stored filings."""

    def row(self, **figures):
        base = {"ticker": "ZZZ", "cik": 1, "name": "ZZZ",
                "revenue": [1000.0, 800.0], "gross_profit": [450.0, 320.0],
                "operating_income": [200.0, 120.0], "net_income": [100.0, 70.0],
                "operating_cash_flow": [150.0, 90.0], "depreciation": [60.0, 50.0],
                "share_based_compensation": [10.0, 8.0], "assets": [2000.0, 1800.0],
                "liabilities": [1200.0, 1100.0], "equity": [800.0, 700.0], "debt": [500.0, 450.0],
                "interest_expense": [20.0, 24.0], "matures_1y": [50.0, 40.0], "matures_2y": [60.0, 50.0],
                "matures_3y": [100.0, 60.0], "matures_4y": [None, 100.0], "matures_5y": [90.0, None],
                "matures_later": [200.0, 200.0]}
        base.update({k: v if isinstance(v, list) else [v] for k, v in figures.items()})
        return base

    def test_the_margin_walk_reads_the_screens_own_measures(self):
        b = bridge.for_company(self.row())
        now, before = screen.measures(self.row()), screen.measures(screen._as_of(self.row(), 1))
        walk = {m["name"]: m for m in b["margins"]}
        self.assertEqual(list(walk), ["gross_margin", "operating_margin", "net_margin"])
        for name, m in walk.items():
            self.assertEqual((m["before"], m["now"]), (before[name], now[name]))
        self.assertAlmostEqual(walk["gross_margin"]["change_bp"], (0.45 - 0.40) * 1e4)
        self.assertAlmostEqual(walk["operating_margin"]["change_bp"], 500.0)
        self.assertEqual((b["revenue"]["change"], b["revenue"]["growth"]), (200.0, 0.25))

    def test_the_cash_gap_is_named_from_the_cash_flow_statements_own_lines(self):
        cash = bridge.for_company(self.row())["cash"]
        self.assertEqual(cash["cash_gap"], 50.0)
        lines = {l["name"]: l["value"] for l in cash["lines"]}
        self.assertEqual(lines, {"depreciation": 60.0, "share_based_compensation": 10.0,
                                 "working_capital_and_other": -20.0})
        self.assertEqual(cash["cash_conversion"], 1.5)
        self.assertAlmostEqual(cash["cash_conversion_before"], 90.0 / 70.0)
        unnamed = bridge.for_company(self.row(depreciation=[None, None]))["cash"]
        self.assertIsNone({l["name"]: l["value"] for l in unnamed["lines"]}["working_capital_and_other"])
        self.assertEqual(unnamed["why"]["working_capital_and_other"], "not separable without depreciation")
        self.assertNotIn("working_capital_and_other", unnamed["withheld"])

    def test_depreciation_from_the_notes_is_used_only_as_a_pair(self):
        """AMD and Microsoft tag the cash-flow line under their own names; its two
        parts are in the notes. Together they stand in for it, one alone never does."""
        row = self.row(depreciation=[None, None], depreciation_alone=[45.0, 40.0], amortisation=[15.0, 10.0])
        cash = bridge.for_company(row)["cash"]
        self.assertEqual({l["name"]: l["value"] for l in cash["lines"]}["depreciation"], 60.0)
        self.assertEqual(cash["depreciation_basis"], "summed")
        alone = bridge.for_company(self.row(depreciation=[None, None], depreciation_alone=[45.0, 40.0]))["cash"]
        self.assertIsNone({l["name"]: l["value"] for l in alone["lines"]}["depreciation"])
        self.assertIsNone(alone["depreciation_basis"])
        self.assertEqual(bridge.for_company(self.row())["cash"]["depreciation_basis"], "tagged")

    def test_a_loss_states_no_conversion(self):
        cash = bridge.for_company(self.row(net_income=[-40.0, 70.0]))["cash"]
        self.assertIsNone(cash["cash_conversion"])
        self.assertIn("a loss", cash["why"]["cash_conversion"])
        self.assertIn("cash_conversion", cash["withheld"])

    def test_a_figure_larger_than_the_total_it_sits_inside_is_withheld(self):
        """The figures the bridge adds are not in screen's unit-slip check, so each is
        held inside a total it cannot exceed: a thousandfold slip upward breaks it."""
        slipped = bridge.for_company(self.row(interest_expense=[20000.0, 24.0], depreciation=[60000.0, 50.0],
                                              matures_later=[200000.0, 200.0]))
        self.assertIsNone(slipped["debt"]["interest_coverage"])
        self.assertIn("interest_expense", slipped["debt"]["withheld"])
        self.assertIsNone({l["name"]: l["value"] for l in slipped["cash"]["lines"]}["depreciation"])
        self.assertIn("depreciation", slipped["cash"]["withheld"])
        self.assertIsNone(slipped["debt"]["maturing"])
        self.assertIn("unit slip", slipped["debt"]["why"]["maturing"])

    def test_debt_when_it_falls_due_and_interest_coverage(self):
        debt = bridge.for_company(self.row())["debt"]
        self.assertEqual([m["when"] for m in debt["maturities"]][:2], ["within a year", "in year two"])
        self.assertEqual(debt["maturing"], 50.0 + 60.0 + 100.0 + 90.0 + 200.0)
        self.assertEqual((debt["interest_coverage"], debt["interest_coverage_before"]), (10.0, 5.0))
        self.assertEqual((debt["debt"], debt["debt_before"]), (500.0, 450.0))
        none = bridge.for_company(self.row(**{m: [None, None] for m in universe.MATURITIES},
                                           interest_expense=[None, None]))["debt"]
        self.assertIn("no maturity table", none["why"]["maturing"])
        self.assertIn("no interest expense", none["why"]["interest_coverage"])
        self.assertEqual(none["withheld"], [])
        self.assertNotIn("matures_2y", none["why"])                  # no table: one reason for all of it

    def test_a_margin_the_filings_do_not_support_says_so(self):
        """S-30: Starbucks files no gross profit; its margin row was three bare dashes."""
        walk = bridge.margin_walk({"gross_margin": [None, None], "operating_margin": [0.15, 0.079],
                                   "net_margin": [None, 0.05]})
        by = {m["name"]: m for m in walk}
        self.assertEqual(by["gross_margin"]["why"], "not in its tagged filings")
        self.assertIsNone(by["operating_margin"]["why"])
        self.assertAlmostEqual(by["operating_margin"]["change_bp"], -710)
        self.assertIn("one of the two years", by["net_margin"]["why"])
        self.assertIn("m.why ? '<div class=\"dash-why\">'", template_function("bridgeBlock"))

    def test_a_year_the_debt_table_leaves_out_says_so(self):
        """S-23: AMD tags every year of its maturity table but the second. The page
        dropped that row, which read as nothing due in year two."""
        gap = bridge.for_company(self.row(matures_2y=[None, None]))["debt"]
        self.assertIsNone(gap["maturities"][1]["amount"])
        self.assertEqual(gap["why"]["matures_2y"], "not in its tagged filings")
        body = template_function("bridgeBlock")
        self.assertNotIn("filter(m => m.amount != null)", body)
        self.assertIn("withReason('–', debt.why, m.name, debt.withheld)", body)

    def test_segments_are_never_invented_and_a_bank_gets_no_bridge(self):
        b = bridge.for_company(self.row())
        self.assertIn("carries no segment breakdowns", b["revenue"]["segments"])
        self.assertNotIn("segment_split", json.dumps(b))
        bank = bridge.for_company(self.row(), financial=True)
        self.assertIn("interest", bank["why_not"])
        self.assertIn("fewer than two", bridge.for_company({"revenue": [5.0]})["why_not"])

    def test_the_card_gets_the_bridge_and_the_page_formats_it_from_declarations(self):
        rows = [dict(self.row(), ticker="B%02d" % i, cik=300 + i) for i in range(6)]
        cards = [{"ticker": "B01"}]
        store = {"companies": {r["ticker"]: r for r in rows}, "built": "2026-09-24", "years": 2}
        context.add_to(cards, store=store, codes={300 + i: 3571 for i in range(6)})
        self.assertEqual(cards[0]["context"]["bridge"]["years"], ["2024", "2025"])
        banks = [{"ticker": "B01"}]
        context.add_to(banks, store=store, codes={300 + i: 6022 for i in range(6)})
        self.assertIn("why_not", banks[0]["context"]["bridge"])
        display = build_desk.measure_display()
        self.assertTrue(set(bridge.BRIDGE_DISPLAY) <= set(display))
        body = template_function("bridgeBlock")
        self.assertIn("withReason('–', block.why, name, block.withheld)", body)
        self.assertNotRegex(body, r"toFixed|\* 100|10000")          # formats nothing itself
        self.assertIn("bridgeBlock((c.context || {}).bridge)", template_function("renderCompanies"))


if __name__ == "__main__":
    unittest.main()
