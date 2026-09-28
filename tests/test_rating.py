"""The desk's rating: its measures, breakpoints, fixed sample, log and record."""
from support import *  # noqa: F401,F403


class RatingTests(unittest.TestCase):
    """The desk's rating (decided 25 Sep 2026): published measures, each ranked
    across every rated company the way its paper found, averaged within its theme, the themes
    averaged, and cut into thirds (2026-09-28b). Every rating given is logged, never edited,
    and scored against the market."""

    def company(self, i, gp=0.4, growth=0.05, accrual=0.0, issued=0.0, cik=None):
        """A company whose five measures are set: gross profit to assets, asset growth,
        accruals (net income less cash from operations, over assets) and share change."""
        a0 = 1000.0 + i                                  # sizes differ, so no two tie exactly
        a1 = a0 / (1 + growth)
        ni = 80.0
        return {"ticker": f"C{i:03d}", "cik": cik if cik is not None else i, "name": f"C{i}",
                "assets": [a0, a1], "revenue": [900.0, 850.0], "gross_profit": [gp * a0, gp * a1],
                "net_income": [ni, 60.0], "operating_cash_flow": [ni - accrual * a0, 70.0],
                "operating_income": [120.0, 100.0], "equity": [0.5 * a0, 0.5 * a1],
                "retained_earnings": [300.0, 250.0], "debt": [100.0, 120.0],
                "current_assets": [400.0, 350.0], "current_liabilities": [200.0, 200.0],
                "shares": [10.0 * (1 + issued), 10.0], "shares_outstanding": [10.0]}

    def codes(self):
        """An industry code for each of the fifty, none of them financial."""
        return {i: 3571 for i in range(50)}

    def universe(self, extra=()):
        rows = [self.company(i, gp=0.1 + i * 0.01, growth=0.3 - i * 0.005, accrual=0.05 - i * 0.001,
                             issued=0.1 - i * 0.002) for i in range(50)]
        rows += list(extra)
        return {"built": "2026-09-01", "companies": {r["ticker"]: r for r in rows}}

    def test_the_measures_point_the_way_their_papers_found(self):
        """Each measure in the theme Jensen, Kelly & Pedersen (2023) place it (their cluster labels:
        be_me and chcsho_12m Value, ret_12_1 Momentum, gp_at Quality, oaccruals_at Accruals)."""
        self.assertEqual([(f["name"], f["theme"], f["better"]) for f in rating.FACTORS],
                         [("book_to_market", "Value", "higher"), ("shares_change", "Value", "lower"),
                          ("momentum", "Momentum", "higher"), ("gross_profitability", "Quality", "higher"),
                          ("accruals", "Accruals", "lower")])
        self.assertEqual(rating.THEMES, ("Value", "Momentum", "Quality", "Accruals"))
        self.assertEqual({f["theme"] for f in rating.FACTORS}, set(rating.THEMES))
        self.assertEqual(rating.PRICED, ("book_to_market", "momentum"))
        for f in rating.FACTORS:
            self.assertRegex(f["source"], r"\(\d{4}\)")                  # every measure names its paper
        for x in rating.LEFT_OUT:                                           # and every one left out says why
            self.assertTrue(x["why"] and x["theme"])
        r = rating.rate_all(self.universe(), self.codes())
        best, worst = r["companies"]["C049"], r["companies"]["C000"]      # better on every measure as i rises
        self.assertEqual((best["label"], worst["label"]), ("Buy", "Sell"))
        self.assertGreater(best["factors"]["accruals"]["place"], worst["factors"]["accruals"]["place"])
        self.assertLess(best["factors"]["accruals"]["value"], worst["factors"]["accruals"]["value"])
        self.assertEqual(set(best["themes"]), {"Value", "Quality", "Accruals"})   # no price: the filing three

    def test_each_theme_counts_once_however_many_measures_it_has(self):
        """Value has two measures; averaged within the theme first, it weighs what one does."""
        r = rating.rate_all(self.universe(), self.codes())
        c = r["companies"]["C020"]
        f = c["factors"]
        self.assertAlmostEqual(c["themes"]["Quality"], f["gross_profitability"]["place"])
        self.assertAlmostEqual(c["average"], (c["themes"]["Value"] + c["themes"]["Quality"] + c["themes"]["Accruals"]) / 3)

    def test_thirds_decide_the_label(self):
        """Jensen, Kelly & Pedersen (2023) build every factor from the top third against the bottom."""
        r = rating.rate_all(self.universe(), self.codes())
        labels = [c["label"] for c in r["companies"].values()]
        self.assertEqual((labels.count("Buy"), labels.count("Sell"), labels.count("Hold")), (17, 17, 16))
        self.assertEqual((rating.label_for(rating.BUY_FROM), rating.label_for(66.6), rating.label_for(33.3),
                          rating.label_for(rating.SELL_BELOW)), ("Buy", "Hold", "Sell", "Hold"))
        self.assertAlmostEqual(rating.BUY_FROM, 200 / 3)
        self.assertAlmostEqual(rating.SELL_BELOW, 100 / 3)

    def test_what_is_not_rated_says_why(self):
        bank = self.company(900, cik=900)
        bank["ticker"] = "BANK"
        thin = {"ticker": "THIN", "cik": 901, "name": "thin", "assets": [100.0], "revenue": [50.0],
                "net_income": [5.0], "equity": [50.0]}
        store = self.universe([bank, thin])
        store["companies"]["BANK"] = bank
        r = rating.rate_all(store, {900: 6021})                            # a national bank
        self.assertEqual(rating.for_page(r, "BANK")["why_not"], rating.WHY_NOT["financial"])
        self.assertEqual(rating.for_page(r, "THIN")["why_not"], rating.WHY_NOT["too_few"])
        self.assertEqual(rating.for_page(r, "VOO")["why_not"], rating.WHY_NOT["absent"])
        self.assertIsNone(rating.for_page(r, "VOO")["label"])
        self.assertEqual(r["not_rated"]["financial"], 1)
        self.assertEqual(rating.for_page(r, "c049")["rated_among"], r["rated"])
        self.assertEqual(rating.for_page(rating.rate_all({}), "AAPL")["why_not"], rating.WHY_NOT["no_universe"])

    def test_every_rating_given_is_logged_once_and_never_edited(self):
        r = rating.rate_all(self.universe(), self.codes())
        days = {"2026-09-24": {"c": 10.0, "a": 10.0}, "2026-09-25": {"c": 11.0, "a": 11.0}}
        store = {"C049": days, "C000": days}
        first = rating.log([], r, ["c049", "C000", "C010"], store, date(2026, 9, 25))
        self.assertEqual([(e["ticker"], e["label"], e["close"]) for e in first],
                         [("C049", "Buy", 11.0), ("C000", "Sell", 11.0)])   # C010 has no price: nothing to score
        again = rating.log(first, r, ["C049", "C000"], store, date(2026, 9, 26))
        self.assertEqual(again, first)                                      # unchanged: nothing added
        changed = dict(r, companies=dict(r["companies"], C049=dict(r["companies"]["C049"], label="Hold")))
        later = rating.log(first, changed, ["C049"], store, date(2026, 12, 1))
        self.assertEqual(later[:2], first)                                  # what was logged stays as it was
        self.assertEqual((later[2]["ticker"], later[2]["label"], later[2]["date"]), ("C049", "Hold", "2026-12-01"))

    def test_the_record_scores_each_rating_against_the_market(self):
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(400)]
        up = {d: {"c": 100.0 * 1.001 ** i, "a": 100.0 * 1.001 ** i} for i, d in enumerate(days)}
        flat = {d: {"c": 100.0, "a": 100.0} for d in days}
        store = {"A": up, "B": up, "C": flat, prices.BENCHMARK: flat}
        entries = [{"ticker": t, "date": days[0], "label": label, "close_day": days[0], "close": 100.0,
                    "method": rating.METHOD} for t, label in (("A", "Buy"), ("B", "Buy"), ("C", "Sell"))]
        rec = rating.record(entries, store)
        row = next(x for x in rec["rows"] if (x["label"], x["days"]) == ("Buy", 63))
        self.assertEqual((row["n"], row["beat"]["k"], row["after"]), (2, 2, "3 months"))
        self.assertAlmostEqual(row["lead"]["estimate"], 1.001 ** 63 - 1)
        sell = next(x for x in rec["rows"] if (x["label"], x["days"]) == ("Sell", 63))
        self.assertEqual((sell["n"], sell["beat"]["k"]), (1, 0))
        self.assertIsNone(next(x for x in rec["rows"] if x["days"] == 252 and x["label"] == "Hold")["beat"])
        # records read side by side share one level, the desk's rule for families
        self.assertEqual(rec["level"], uncertainty.level_text(uncertainty.family_level(
            [uncertainty.sign_test_p(2, 2)] * 3 + [uncertainty.sign_test_p(0, 1)] * 3)))
        self.assertEqual([e["ticker"] for e in rec["recent"]], ["A", "B", "C"])

    def test_a_rating_is_scored_from_the_close_after_the_day_it_was_given(self):
        """The day it is given can hold the filing it was made from, and that day's move
        is not the rating's to claim."""
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(300)]
        jump = {d: {"c": 100.0 if i == 0 else 200.0, "a": 100.0 if i == 0 else 200.0} for i, d in enumerate(days)}
        flat = {d: {"c": 100.0, "a": 100.0} for d in days}
        entry = [{"ticker": "J", "date": days[0], "label": "Buy", "close_day": days[0], "close": 100.0,
                  "method": rating.METHOD}]
        row = next(x for x in rating.record(entry, {"J": jump, prices.BENCHMARK: flat})["rows"]
                   if (x["label"], x["days"]) == ("Buy", 63))
        self.assertEqual((row["n"], row["beat"]["k"]), (1, 0))               # flat after the day: no lead
        self.assertAlmostEqual(row["lead"]["estimate"], 0.0)

    def test_a_universe_too_small_to_rank_breaks_nothing(self):
        one = {"built": "2026-09-01", "companies": {"C001": self.company(1)}}
        r = rating.rate_all(one, {1: 3571})
        self.assertEqual((r["rated"], r["why_not"]), (0, {"C001": "too_few"}))
        two = dict(one, companies={"C001": self.company(1), "C002": self.company(2, gp=0.5)})
        self.assertEqual(rating.rate_all(two, {1: 3571, 2: 3571})["rated"], 2)

    def listed_universe(self):
        """Forty NYSE companies of middling size and conduct, forty over-the-counter ones
        at the extremes, and one large Nasdaq company that beats most NYSE ones."""
        rows, exchanges = [], {}
        for i in range(40):
            rows.append(self.company(i, gp=0.2 + i * 0.005, growth=0.12 - i * 0.002, accrual=0.02 - i * 0.001,
                                     issued=0.02 - i * 0.001))
            exchanges[rows[-1]["ticker"]] = "NYSE"
        for i in range(40, 80):
            wild = (i % 2) * 2 - 1                       # half far better, half far worse
            rows.append(self.company(i, gp=0.35 + 0.3 * wild, growth=0.05 - 0.6 * wild,
                                     accrual=-0.2 * wild, issued=-0.05 - 0.4 * wild))
            exchanges[rows[-1]["ticker"]] = "OTC"
        big = self.company(90, gp=0.393, growth=0.045, accrual=-0.017, issued=-0.018)
        big["ticker"] = "BIG"
        rows.append(big)
        exchanges["BIG"] = "Nasdaq"
        codes = {r["cik"]: 3571 for r in rows}
        return {"built": "2026-09-26", "companies": {r["ticker"]: r for r in rows}}, codes, {"exchanges": exchanges}

    def test_places_are_set_against_nyse_companies_and_otc_shares_are_not_rated(self):
        """The user saw every covered company at Hold (26 Sep 2026). Placed among every
        SEC filer, big companies land in the middle: tiny over-the-counter ones hold the
        ends. The papers set their breakpoints on NYSE companies and studied exchange-listed
        shares only (Fama & French 2008; Hou, Xue & Zhang 2020); so does the rating now."""
        store, codes, listings = self.listed_universe()
        before = rating.rate_all(store, codes)                                   # no exchange list
        after = rating.rate_all(store, codes, listings)
        self.assertEqual((before["breakpoints"], after["breakpoints"]), ("all", "NYSE"))
        # its gross profitability against every filer, then against the NYSE's forty alone
        nyse_gp = sorted(0.2 + i * 0.005 for i in range(40))
        self.assertLess(before["companies"]["BIG"]["factors"]["gross_profitability"]["place"], 75)
        self.assertAlmostEqual(after["companies"]["BIG"]["factors"]["gross_profitability"]["place"],
                               100.0 * sum(1 for v in nyse_gp if v < 0.393) / 40)
        self.assertEqual(after["companies"]["BIG"]["label"], "Buy")            # better than most NYSE companies
        self.assertEqual(after["why_not"]["C040"], "otc")
        self.assertEqual(rating.for_page(after, "C041")["why_not"], rating.WHY_NOT["otc"])
        self.assertEqual(after["not_rated"]["otc"], 40)
        nyse = [c for t, c in after["companies"].items() if listings["exchanges"][t] == "NYSE"]
        labels = [c["label"] for c in nyse]
        self.assertEqual((labels.count("Buy"), labels.count("Sell")), (13, 13))  # thirds of the NYSE group
        page = rating.for_page(after, "BIG")
        self.assertEqual((page["breakpoints"], page["rated_among"]), ("NYSE", 40))
        self.assertIn("r.breakpoints === 'NYSE'", template_function("ratingPlace"))

    def test_the_exchange_list_is_read_once_a_day_and_refused_if_misshapen(self):
        good = {"fields": ["cik", "name", "ticker", "exchange"],
                "data": [[320193, "Apple Inc.", "aapl", "Nasdaq"], [21344, "COCA COLA", "KO", "NYSE"], [1, "X", "XX", None]]}
        self.assertEqual(universe.listings("me@x.org", fetch=lambda url, who: good),
                         {"AAPL": "Nasdaq", "KO": "NYSE", "XX": ""})
        with self.assertRaises(universe.UniverseError):
            universe.listings("me@x.org", fetch=lambda url, who: {"0": {"cik_str": 1, "ticker": "A"}})

        def down(url, who):
            raise urllib.error.URLError("no route")
        with self.assertRaises(universe.UniverseError):
            universe.listings("me@x.org", fetch=down)
        today = datetime.now(timezone.utc)
        kept = {"exchanges": {"KO": "NYSE"}, "updated_at": today.isoformat()}
        self.assertIs(universe.update_listings(kept, today=today.date(), fetch=down), kept)   # fetched today
        source = inspect.getsource(server.Handler.update_research)
        self.assertLess(source.index('("Stock exchanges"'), source.index('("Ratings"'))
        self.assertIn("universe.load_listings()", inspect.getsource(server.Handler.log_ratings))
        self.assertIn("universe.UniverseError", inspect.getsource(server.Handler.run_steps))
        self.assertIn("listings.json", read(os.path.join(ROOT, ".gitignore")))

    def test_a_new_definition_starts_its_own_record(self):
        """A change of definition changes what a label means. Under a new one every
        company is logged afresh, the earlier entries stay as they were, and only the
        present definition's ratings are scored."""
        r = rating.rate_all(self.universe(), self.codes())
        days = {"2026-09-24": {"c": 10.0, "a": 10.0}}
        old = [{"ticker": "C049", "date": "2026-09-25", "label": "Buy", "close_day": "2026-09-24", "close": 10.0}]
        logged = rating.log(old, r, ["C049"], {"C049": days}, date(2026, 9, 26))
        self.assertEqual(logged[0], old[0])                                      # never edited
        self.assertEqual((logged[1]["label"], logged[1]["method"]), ("Buy", rating.METHOD))
        self.assertEqual(rating.record(logged, {})["earlier"], 1)
        self.assertEqual(rating.record(logged, {})["logged"], 1)
        # and the digest does not call a re-logged Buy a change
        raw = {"synced_at": "2026-09-26T09:00:00+00:00", "previous_synced_at": "2026-09-25T18:00:00+00:00"}
        for e in logged:
            e["at"] = e["date"] + "T12:00:00+00:00"
        self.assertEqual(build_desk.build_digest(raw, {"tickers": ["C049"]}, {}, logged, {}, date(2026, 9, 26),
                                                 looks={"previous": raw["previous_synced_at"]})["ratings"], [])

    def test_the_command_line_shows_each_ratings_parts(self):
        store, codes, listings = self.listed_universe()
        real = (universe.load, sectors.load, universe.load_listings)
        universe.load, sectors.load, universe.load_listings = lambda: store, lambda: codes, lambda: listings
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(rating.main(["big", "C040"]), 0)
        finally:
            universe.load, sectors.load, universe.load_listings = real
        text = out.getvalue()
        self.assertIn("placed against NYSE-listed companies: Buy ", text)
        self.assertIn("BIG: Buy, place ", text)
        self.assertIn("gross profitability ", text)
        self.assertIn("C040: not rated: it trades over the counter", text)

    def test_the_ranking_is_kept_until_the_universe_changes(self):
        store = self.universe()
        codes = self.codes()
        self.assertIs(rating.rate_all(store, codes), rating.rate_all(dict(store), codes))
        rebuilt = dict(store, built="2026-10-01")
        self.assertIsNot(rating.rate_all(rebuilt, codes), rating.rate_all(store, codes))

    def test_without_industry_codes_nothing_is_ranked(self):
        """Every place is relative to the others, so with banks and blank-check companies
        unmarked every company's place would move: no rating rather than a skewed one."""
        r = rating.rate_all(self.universe(), {})
        self.assertEqual((r["rated"], r["companies"]), (0, {}))
        self.assertEqual(rating.for_page(r, "C049"), {"label": None, "why_not": rating.WHY_NOT["no_codes"]})
        self.assertEqual(rating.explained(r)["why_none"], rating.WHY_NOT["no_codes"])
        self.assertIn("R.why_none", template_function("renderRatingRecord"))

    def test_it_reaches_the_card_the_holdings_and_the_refresh(self):
        store = self.universe()
        news_data = {"tickers": ["C049"], "companies": {"C049": "C49 INC"}, "items": []}
        raw = {"summary": {"totalValue": 10.0}, "positions": [
            {"instrument": {"ticker": "C000_US_EQ", "name": "C0"}, "quantity": 1,
             "walletImpact": {"currentValue": 10.0, "totalCost": 9.0}},
            # a London line sharing a US company's short ticker is not that company
            {"instrument": {"ticker": "C049l_EQ", "name": "C49 London"}, "quantity": 1,
             "walletImpact": {"currentValue": 5.0, "totalCost": 5.0}}]}
        with tempfile.TemporaryDirectory() as folder:
            real, sectors.SECTORS_FILE = sectors.SECTORS_FILE, os.path.join(folder, "sectors.json")
            try:
                with open(sectors.SECTORS_FILE, "w") as f:
                    json.dump({"sic_by_cik": self.codes()}, f)
                d = build_desk.compute(raw, today=date(2026, 9, 25), news=news_data, universe=store)
            finally:
                sectors.SECTORS_FILE = real
        self.assertEqual(d["companies"][0]["rating"]["label"], "Buy")
        held = {r["ticker"]: r["rating"] for r in d["positions"]["rows"]}
        self.assertEqual(held["C000"]["label"], "Sell")
        self.assertEqual(held["C049"], {"label": None, "why_not": rating.WHY_NOT["not_us"]})
        self.assertEqual(d["rating"]["rated"], 50)
        self.assertEqual([f["name"] for f in d["rating"]["factors"]], [f["name"] for f in rating.FACTORS])
        source = inspect.getsource(server.Handler.update_research)
        self.assertIn('("Ratings", self.log_ratings(watchlist + held), "desk"', source)
        self.assertIn("rating.log(", inspect.getsource(server.Handler.log_ratings))
        self.assertIn("ratings_log.json", read(os.path.join(ROOT, ".gitignore")))
        # the page: beside the ticker, first among the card's sections, and its record
        card = template_function("renderCompanies")
        self.assertIn("ratingPill(c.rating)", card)
        self.assertLess(card.index("deskRatingBlock(c.rating)"), card.index("bridgeBlock("))
        self.assertIn("ofCount(x.beat)", template_function("recordLines"))
        self.assertIn("recordLines(rec)", template_function("renderRatingRecord"))
        self.assertIn("esc(R.limits)", template_function("deskRatingBlock"))

    def test_the_rating_never_reaches_an_order(self):
        """It proposes nothing, and there is nothing to propose to: the desk has no order path."""
        self.assertFalse(os.path.exists(os.path.join(ROOT, "execute.py")))
        self.assertFalse(hasattr(t212.Client, "post"))
        self.assertNotIn("rating", read(os.path.join(ROOT, "t212.py")))



class RatingTwoTests(unittest.TestCase):
    """The rating's definition of 27 Sep 2026: value (Fama & French 1992) and momentum
    (Jegadeesh & Titman 1993) beside the five filing measures. Both need a price, and the
    desk can price a few hundred companies a month, so both are placed against a fixed
    random sample of NYSE companies, drawn once, which is also the rating's fair record."""
    company = RatingTests.company
    TODAY = date(2026, 9, 27)

    def closes(self, start_price, monthly, months=16, end=None):
        """Business-day closes growing `monthly` a month, ending the day before TODAY."""
        end = end or self.TODAY - timedelta(days=1)
        day, price, out = end - timedelta(days=31 * months), start_price, {}
        while day <= end:
            if day.weekday() < 5:
                out[day.isoformat()] = {"c": round(price, 4), "a": round(price, 4)}
            price *= (1 + monthly) ** (1 / 21)
            day += timedelta(days=1)
        return out

    def test_momentum_is_the_year_to_the_month_before_last(self):
        self.assertEqual((rating.month_end(self.TODAY, 13), rating.month_end(self.TODAY, 2)),
                         (date(2025, 8, 31), date(2026, 7, 31)))
        self.assertEqual(rating.month_end(date(2026, 1, 15), 1), date(2025, 12, 31))
        series = {"2025-08-29": 100.0, "2025-09-30": 101.0, "2026-07-31": 130.0, "2026-09-25": 200.0}
        self.assertAlmostEqual(rating.momentum(series, self.TODAY), 0.30)      # August's move is left out
        self.assertIsNone(rating.momentum({"2025-08-20": 100.0, "2026-07-31": 130.0}, self.TODAY))   # no August end
        self.assertIsNone(rating.momentum({"2025-08-29": 100.0}, self.TODAY))
        self.assertIsNone(rating.momentum(series, None))

    def test_book_to_market_is_book_over_value_with_the_share_basis_check(self):
        row = self.company(0)                                                  # equity 500, 10 shares
        self.assertAlmostEqual(rating.book_to_market(row, 100.0), 500.0 / 1000.0)
        self.assertIsNone(rating.book_to_market(row, None))
        self.assertIsNone(rating.book_to_market(dict(row, equity=[-5.0, 1.0]), 100.0))   # no book equity
        depositary = dict(row, public_float=[1.0])                             # value 1,000 times the float
        self.assertIsNone(rating.book_to_market(depositary, 100.0))

    def listed(self, n=40, sample_every=2):
        """`n` NYSE companies, every `sample_every`th in the sample, all priced; and FOL, a
        followed NYSE company outside the sample with the strongest momentum of all."""
        rows, exchanges, prices_ = [], {}, {prices.BENCHMARK: self.closes(100.0, 0.005)}
        for i in range(n):
            rows.append(self.company(i, gp=0.2 + i * 0.005, growth=0.12 - i * 0.002, accrual=0.02 - i * 0.001,
                                     issued=0.02 - i * 0.001))
            exchanges[rows[-1]["ticker"]] = "NYSE"
            prices_[rows[-1]["ticker"]] = self.closes(50.0 + i, -0.02 + i * 0.001)
        fol = self.company(99)
        fol["ticker"] = "FOL"
        rows.append(fol)
        exchanges["FOL"] = "NYSE"
        prices_["FOL"] = self.closes(50.0, 0.10)
        store = {"built": "2026-09-26", "companies": {r["ticker"]: r for r in rows}}
        sample = {"tickers": [r["ticker"] for r in rows[:n:sample_every]], "drawn_at": "2026-09-27T08:00:00+00:00"}
        return store, {r["cik"]: 3571 for r in rows}, {"exchanges": exchanges}, prices_, sample

    def test_an_average_is_placed_among_those_resting_on_as_many_themes(self):
        """An average of three themes swings further than one of four: ranked together, the
        companies missing a theme crowded the ends. Each group has its own thirds; a group too
        small to place anyone in is placed against everyone."""
        store, codes, listings, prices_, sample = self.listed()
        unpriced = {t: v for t, v in prices_.items() if t in sample["tickers"] or t == prices.BENCHMARK}
        r = rating.rate_all(store, codes, listings, unpriced, sample, self.TODAY)
        for tickers, themes, counts in ((sample["tickers"], 4, (7, 7, 6)),
                                        ([f"C{i:03d}" for i in range(1, 40, 2)] + ["FOL"], 3, (7, 7, 7))):
            group = [r["companies"][t] for t in tickers]
            self.assertEqual({c["measures"] for c in group}, {themes})
            self.assertEqual({c["among"] for c in group}, {len(tickers)})
            labels = [c["label"] for c in group]
            self.assertEqual((labels.count("Buy"), labels.count("Sell"), labels.count("Hold")), counts, themes)
        few = dict(sample, tickers=sample["tickers"][:sectors.MIN_PEERS - 1])
        small = rating.rate_all(store, codes, listings, {t: v for t, v in unpriced.items()
                                                         if t in few["tickers"] or t == prices.BENCHMARK}, few, self.TODAY)
        placed = [small["companies"][t] for t in few["tickers"]]
        self.assertTrue(placed and all(c["measures"] == 4 and c["among"] == small["rated"] for c in placed))

    def test_price_measures_are_placed_against_the_sample_alone(self):
        store, codes, listings, prices_, sample = self.listed()
        r = rating.rate_all(store, codes, listings, prices_, sample, self.TODAY)
        fol = r["companies"]["FOL"]
        self.assertEqual(fol["factors"]["momentum"]["place"], 100.0)            # above every sampled company
        self.assertEqual(fol["measures"], 4)                                    # every theme
        sampled = [t for t in sample["tickers"]]
        self.assertEqual(fol["among"], len(sampled))                            # placed among the sample's own
        without = rating.rate_all(store, codes, listings, {t: v for t, v in prices_.items() if t != "FOL"},
                                  sample, self.TODAY)
        for t in sampled:                                                       # FOL moves no sampled place
            self.assertEqual(r["companies"][t]["factors"]["momentum"]["place"],
                             without["companies"][t]["factors"]["momentum"]["place"])
            self.assertTrue(r["companies"][t]["sampled"])
        self.assertIsNone(without["companies"]["FOL"]["factors"]["momentum"]["value"])
        self.assertEqual(without["companies"]["FOL"]["measures"], 3)            # no price: the filing three
        self.assertEqual(r["sample"], {"size": len(sampled), "priced": len(sampled),
                                       "placed": {"book_to_market": len(sampled), "momentum": len(sampled)}})
        # with no sample, a price measure has nothing to be placed against
        alone = rating.rate_all(store, codes, listings, prices_, {}, self.TODAY)
        self.assertIsNone(alone["companies"]["FOL"]["factors"]["momentum"]["place"])
        self.assertEqual(alone["companies"]["FOL"]["measures"], 3)              # still rated, on the three
        self.assertEqual(rating.sample_for_page(r, sample),
                         {"size": len(sampled), "priced": len(sampled), "drawn_at": sample["drawn_at"],
                          "ready_at": rating.ready_at(len(sampled)), "ready": True,
                          "per_hour": prices.TIINGO_PER_HOUR - prices.SPARE})

    def test_value_and_momentum_wait_for_three_in_four_of_the_sample(self):
        """28 Sep 2026, the user's card: value and momentum read "no sample yet" while the sample was
        being priced, and once two of it had a price they would have been placed against those two."""
        store, codes, listings, prices_, sample = self.listed()
        need = rating.ready_at(len(sample["tickers"]))
        self.assertEqual((rating.ready_at(200), rating.ready_at(1)), (150, 2))
        few = {t: v for t, v in prices_.items() if t not in sample["tickers"][need - 1:]}   # one short
        r = rating.rate_all(store, codes, listings, few, sample, self.TODAY)
        self.assertEqual(r["sample"]["placed"]["momentum"], need - 1)
        for ticker, row in r["companies"].items():
            self.assertIsNone(row["factors"]["momentum"]["place"], ticker)
            self.assertIsNone(row["factors"]["book_to_market"]["place"], ticker)
        self.assertEqual(r["companies"]["FOL"]["measures"], 3)                  # rated on the three meanwhile
        page = rating.sample_for_page(r, sample)
        self.assertEqual((page["ready"], page["priced"], page["ready_at"]), (False, need - 1, need))
        enough = {t: v for t, v in prices_.items() if t not in sample["tickers"][need:]}
        r = rating.rate_all(store, codes, listings, enough, sample, self.TODAY)
        self.assertEqual(r["companies"]["FOL"]["measures"], 4)
        self.assertTrue(rating.sample_for_page(r, sample)["ready"])

    def test_the_sample_is_drawn_once_from_the_rateable_nyse_companies(self):
        store, codes, listings, _, _ = self.listed()
        listings["exchanges"].update({"C001": "Nasdaq", "C003": "OTC"})
        codes[2] = 6021                                                         # a bank
        drawn = rating.draw_sample(store, codes, listings, size=10, seed=7)
        self.assertEqual(len(drawn["tickers"]), 10)
        self.assertFalse({"C001", "C002", "C003"} & set(drawn["tickers"]))
        self.assertEqual(drawn["tickers"], rating.draw_sample(store, codes, listings, size=10, seed=7)["tickers"])
        self.assertEqual(drawn["eligible"], 41 - 3)
        self.assertIsNone(rating.draw_sample(store, codes, {}, size=10))        # no exchange list, no draw
        with tempfile.TemporaryDirectory() as folder:
            kept = rating.keep_sample(folder, store, codes, listings)
            self.assertEqual(len(kept["tickers"]), min(rating.SAMPLE_SIZE, 38))
            other = dict(store, companies={"C000": store["companies"]["C000"]})
            self.assertEqual(rating.keep_sample(folder, other, codes, listings), kept)   # never redrawn
            self.assertEqual(rating.load_sample(folder), kept)
        self.assertEqual((rating.SAMPLE_SIZE, rating.SAMPLE_SEED), (200, 20260927))

    def test_the_samples_ratings_are_logged_and_scored_apart(self):
        store, codes, listings, prices_, sample = self.listed()
        r = rating.rate_all(store, codes, listings, prices_, sample, self.TODAY)
        entries = rating.log([], r, ["FOL"] + sample["tickers"], prices_, self.TODAY, sample=sample)
        self.assertEqual({e["ticker"]: e["sample"] for e in entries}["FOL"], False)
        self.assertTrue(all(e["sample"] for e in entries if e["ticker"] != "FOL"))
        self.assertEqual(rating.record(entries, prices_, "sample")["logged"], len(sample["tickers"]))
        self.assertEqual(rating.record(entries, prices_, "yours")["logged"], 1)
        self.assertEqual(rating.record(entries, prices_)["logged"], len(entries))
        self.assertEqual(rating.METHOD, "2026-09-28b")

    def test_the_sample_is_priced_once_a_month_within_tiingos_budget(self):
        asked = []

        def fetch(ticker, start, key):
            asked.append((ticker, start))
            return [("2026-09-25", 1.0, 1.0)]
        now = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)                 # a Sunday
        store = {prices.BENCHMARK: {"2026-09-25": {"c": 1.0, "a": 1.0}}, prices.META_STARTS: {prices.BENCHMARK: "1990-01-01"},
                 prices.META_WHOLE: {prices.BENCHMARK: "2026-09-26"}}
        slow = [f"S{i:03d}" for i in range(60)]
        out = prices.update([], stored=store, key="k", fetch=fetch, now=now, cash=None, fx=None, slow=slow)
        room = prices.TIINGO_PER_HOUR - prices.SPARE
        self.assertEqual(len(asked), room)                                      # the hour's budget, no more
        self.assertEqual(asked[0], ("S000", "2025-07-24"))                      # the history the measure needs
        self.assertEqual(out[prices.META_WAITING], 60 - room)
        asked.clear()
        prices.update([], stored=out, key="k", fetch=fetch, now=now + timedelta(minutes=30), cash=None, fx=None, slow=slow)
        self.assertEqual(asked, [])                                             # the same hour: none left
        later = prices.update([], stored=out, key="k", fetch=fetch, now=now + timedelta(hours=1, minutes=1),
                              cash=None, fx=None, slow=slow)
        self.assertEqual(sorted(t for t, _ in asked), slow[room:])              # the rest, an hour on
        asked.clear()
        prices.update([], stored=later, key="k", fetch=fetch, now=now + timedelta(hours=3), cash=None, fx=None, slow=slow)
        self.assertEqual(asked, [])                                             # each asked once this month
        # a company followed meanwhile may use the requests the update keeps spare
        spent = dict(out, **{prices.META_ASKED: [now.isoformat()] * room})
        asked.clear()
        prices.update(["NEW"], stored=spent, key="k", fetch=fetch, now=now, cash=None, fx=None)
        self.assertEqual(asked, [])
        prices.update(["NEW"], stored=spent, key="k", fetch=fetch, now=now, cash=None, fx=None, spare=0)
        self.assertEqual([t for t, _ in asked], ["NEW"])
        self.assertIn("spare=0", inspect.getsource(server.Handler.fetch_company))
        asked.clear()
        october = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        prices.update([], stored=dict(later, **{prices.META_ASKED: []}), key="k", fetch=fetch, now=october,
                      cash=None, fx=None, slow=slow[:3])
        self.assertEqual([t for t, _ in asked], ["SPY"] + slow[:3])             # September's end is due
        self.assertEqual(asked[1][1], "2026-09-25")                             # from the last close, which re-bases the rest

    def test_the_buy_list_is_the_top_fifth_highest_first(self):
        """27 Sep 2026: the rating as a list of ideas to look through, each a click from being
        followed. The list is the rating's own Buy label, never a second cut-off."""
        ratings = {"companies": {"AAA": {"label": "Buy", "place": 91.23, "measures": 7, "sampled": True},
                                 "BBB": {"label": "Buy", "place": 99.0, "measures": 5},
                                 "CCC": {"label": "Hold", "place": 70.0, "measures": 5}}}
        store = {"companies": {"AAA": {"cik": 1, "name": "ALPHA CORP"}, "BBB": {"cik": 2, "name": "Beta Inc"}}}
        out = rating.buy_list(ratings, store, {1: 3571, 2: 2834})
        self.assertEqual([x["ticker"] for x in out], ["BBB", "AAA"])
        self.assertEqual((out[1]["name"], out[1]["place"], out[1]["measures"]), ("Alpha Corp", 91.2, 7))
        self.assertEqual((out[0]["industry"], out[1]["industry"]), (sectors.major_group(2834), sectors.major_group(3571)))
        page = page_source()
        body = template_function("renderBuyList", page)
        self.assertIn("followButton(c.ticker)", body)
        self.assertRegex(page, r"\$\('blList'\)\.addEventListener\('click'[\s\S]{0,300}follow\(pick\.dataset\.follow")
        self.assertIn("esc(R.limits", body)                               # its limits, one click away
        self.assertIn("'renderBuyList'", page)
        self.assertNotRegex(body, r"place >= |\b80\b")                  # the label is rating.py's alone

    def test_the_update_draws_the_sample_before_pricing_it(self):
        source = inspect.getsource(server.Handler.update_research)
        self.assertLess(source.index('("Stock exchanges"'), source.index('("Rating sample"'))
        self.assertLess(source.index('("Rating sample"'), source.index('("Rating sample prices"'))
        # the lanes run side by side, so its closes wait for the sample to be drawn, by name
        self.assertIn('slow=rating.load_sample(self.folder).get("tickers") or []),\n'
                      '                                              "prices.json"), "tiingo", ("Rating sample",)),', source)
        self.assertIn("slow=self.sold_lately()", source)                  # a year after each sale, for habits.replaced
        self.assertIn("sample=sample", inspect.getsource(server.Handler.log_ratings))
        block = template_function("deskRatingBlock")
        self.assertIn("f.needs_price ? (v.value == null ? 'no price' : waiting ? 'sample being priced' : 'no sample yet')", block)
        self.assertIn("S.ready_at + ' of the sample&rsquo;s ' + S.size", block)     # how far it has come, from the data
        self.assertIn("R.sample.priced", block)
        self.assertIn("rating_sample.json", read(os.path.join(ROOT, ".gitignore")))


if __name__ == "__main__":
    unittest.main()


class EvidenceRegisterTests(unittest.TestCase):
    """docs/EVIDENCE.md names the study behind every number that could steer a decision. A measure or a screen added without its entry there fails here."""

    def test_every_rating_measure_and_screen_is_in_the_register(self):
        text = read(os.path.join(ROOT, "docs", "EVIDENCE.md"))
        rules = read(os.path.join(ROOT, "docs", "RATING.md"))
        for f in rating.FACTORS:
            author = f["source"].split(" (")[0]
            self.assertIn(author, text, f["name"])
            self.assertIn(author, rules, f["name"])
        for x in rating.LEFT_OUT:
            self.assertIn(x["name"].split(" (")[0].lower(), text.lower(), x["name"])
        self.assertIn(rating.THEME_SOURCE.split(" (")[0], text)
        self.assertIn(f"`{rating.METHOD}`", text)
        for name, spec in screen.PRESETS.items():
            self.assertIn(spec["name"].split(" (")[0], text, name)
