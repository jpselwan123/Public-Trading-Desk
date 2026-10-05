"""The account: sync, what it earned against the market, its costs, and the user's own records (plans, theses, practice)."""
from support import *  # noqa: F401,F403


class SyncTests(unittest.TestCase):
    def pages_client(self, pages_by_path):
        """Serve fixed pages; nextPagePath chains through the list."""
        def opener(req, timeout):
            url = req.full_url.split("/api/v0", 1)[1]
            path, _, query = url.partition("?")
            if path in ("/equity/account/summary",):
                return FakeResponse({"id": 999, "currency": "USD", "totalValue": 10})
            if path == "/equity/positions":
                return FakeResponse([])
            pages = pages_by_path.get(path, [[]])
            idx = int(dict(p.split("=") for p in query.split("&")).get("cursor", 0))
            nxt = f"/api/v0{path}?limit=50&cursor={idx + 1}" if idx + 1 < len(pages) else None
            return FakeResponse({"items": pages[idx], "nextPagePath": nxt})
        return t212.Client("k", "s", "demo", opener=opener, sleep=lambda s: None)

    def test_full_then_incremental(self):
        o = lambda i: {"order": {"id": i}, "fill": {}}
        c = self.pages_client({"/equity/history/orders": [[o(5), o(4)], [o(3), o(2)], [o(1)]]})
        first = t212.sync(c, {}, log=lambda *_: None)
        self.assertEqual([x["order"]["id"] for x in first["orders"]], [5, 4, 3, 2, 1])
        self.assertNotIn("id", first["summary"])                    # account number dropped
        c2 = self.pages_client({"/equity/history/orders": [[o(7), o(6)], [o(5), o(4)], [o(3), o(2)]]})
        second = t212.sync(c2, first, log=lambda *_: None)
        self.assertEqual([x["order"]["id"] for x in second["orders"]], [7, 6, 5, 4, 3, 2, 1])

    def test_the_five_first_requests_go_together(self):
        """The summary, the positions and the first page of each of the three histories do not wait on one
        another: all five must be in flight at once. A barrier of five lets none through until the fifth
        has arrived, so one after another it would time out; each history's later pages stay in turn."""
        barrier, order, lock = threading.Barrier(5, timeout=10), [], threading.Lock()

        def opener(req, timeout):
            url = req.full_url.split("/api/v0", 1)[1]
            path, _, query = url.partition("?")
            with lock:
                order.append((path, query))
            if "cursor" not in query:
                barrier.wait()                               # BrokenBarrierError, then a failed sync, if not all five came
            if path == "/equity/account/summary":
                return FakeResponse({"currency": "USD", "totalValue": 10})
            if path == "/equity/positions":
                return FakeResponse([])
            page = int(dict(p.split("=") for p in query.split("&")).get("cursor", 0))
            more = f"/api/v0{path}?limit=50&cursor={page + 1}" if page == 0 and path.endswith("orders") else None
            return FakeResponse({"items": [{"order": {"id": 10 - page}, "fill": {}}] if path.endswith("orders") else [],
                                 "nextPagePath": more})
        client = t212.Client("k", "s", "demo", opener=opener, sleep=lambda s: None)
        out = t212.sync(client, {}, log=lambda *_: None)
        self.assertEqual([o["order"]["id"] for o in out["orders"]], [10, 9])           # the pages of one history, in turn
        firsts = [p for p, q in order if "cursor" not in q]
        self.assertEqual(sorted(firsts), sorted(["/equity/account/summary", "/equity/positions",
                                                  "/equity/history/orders", "/equity/history/dividends",
                                                  "/equity/history/transactions"]))
        self.assertLess(order.index(("/equity/history/orders", "limit=50")),
                        order.index(("/equity/history/orders", "limit=50&cursor=1")))

    def test_the_first_failure_is_the_first_of_them_in_the_old_order(self):
        """Asked together, answered in order: when the summary and a history both fail, the summary's reason
        is the one said, as it was when they went one after another. A stranger's page in place of the
        account is still no account, and nothing is changed."""
        def opener(req, timeout):
            path = req.full_url.split("/api/v0", 1)[1].partition("?")[0]
            if path == "/equity/account/summary":
                raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
            if path == "/equity/history/orders":
                raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
            return FakeResponse([] if path == "/equity/positions" else {"items": [], "nextPagePath": None})
        client = t212.Client("k", "s", "demo", opener=opener, sleep=lambda s: None)
        with self.assertRaises(t212.T212Error) as cm:
            t212.sync(client, {"orders": [{"order": {"id": 1}}]}, log=lambda *_: None)
        self.assertIn("rejected the key", str(cm.exception))
        def only_orders_refused(req, timeout):
            if req.full_url.endswith("history/orders?limit=50"):
                raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
            return FakeResponse({"currency": "USD"} if "summary" in req.full_url
                                else [] if "positions" in req.full_url else {"items": [], "nextPagePath": None})
        only_orders = t212.Client("k", "s", "demo", sleep=lambda s: None, opener=only_orders_refused)
        with self.assertRaises(t212.T212Error) as cm:
            t212.sync(only_orders, {}, log=lambda *_: None)
        self.assertIn("History", str(cm.exception))
        empty = t212.Client("k", "s", "demo", sleep=lambda s: None, opener=lambda req, timeout: FakeResponse(
            {} if "summary" in req.full_url else [] if "positions" in req.full_url else {"items": [], "nextPagePath": None}))
        with self.assertRaises(t212.T212Error) as cm:
            t212.sync(empty, {}, log=lambda *_: None)
        self.assertIn("without the account in it", str(cm.exception))

    def test_rate_limit_waits_then_retries(self):
        slept, state = [], {"n": 0}

        def opener(req, timeout):
            state["n"] += 1
            if state["n"] == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
            return FakeResponse({"ok": 1})
        c = t212.Client("k", "s", "demo", opener=opener, sleep=slept.append)
        self.assertEqual(c.get("/equity/account/summary"), {"ok": 1})
        self.assertEqual(len(slept), 1)

    def test_auth_errors_are_plain(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        with self.assertRaises(t212.T212Error) as cm:
            t212.Client("k", "s", "demo", opener=opener).get("/equity/history/orders")
        self.assertIn("History", str(cm.exception))


    def test_slow_response_is_retried(self):
        state = {"n": 0}

        def opener(req, timeout):
            state["n"] += 1
            if state["n"] == 1:
                raise socket.timeout("The read operation timed out")
            return FakeResponse({"ok": 1})
        c = t212.Client("k", "s", "demo", opener=opener, sleep=lambda s: None)
        self.assertEqual(c.get("/equity/positions"), {"ok": 1})

    def test_network_block_is_named(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"<html>Access Denied</html>"))
        with self.assertRaises(t212.T212Error) as cm:
            t212.Client("k", "s", "demo", opener=opener).get("/equity/positions")
        self.assertIn("blocking this internet connection", str(cm.exception))


class VsMarketTests(unittest.TestCase):
    """The account against the same deposits in the S&P 500 — the one comparison a
    person picking shares most needs, and one Trading 212 does not make."""

    def flows(self, *pairs):
        return [{"type": "DEPOSIT" if amount > 0 else "WITHDRAW", "amount": abs(amount),
                 "dateTime": day + "T10:00:00Z"} for day, amount in pairs]

    def store(self, closes, **extra):
        spy = {day: {"c": price, "a": price} for day, price in closes.items()}
        return dict({prices.BENCHMARK: spy}, **extra)

    def test_each_deposit_goes_into_the_market_on_its_own_day(self):
        store = self.store({"2026-01-05": 100.0, "2026-03-02": 125.0, "2026-09-24": 150.0})
        v = build_desk.build_vs_market({"total": 2000.0, "currency": "USD"},
                                       self.flows(("2026-01-05", 1000.0), ("2026-03-02", 500.0)), store)
        # 10 units at 100, 4 at 125: 14 units at 150
        self.assertAlmostEqual(v["market_value"], 2100.0)
        self.assertAlmostEqual(v["difference"], -100.0)
        self.assertAlmostEqual(v["difference_pct"], 2000.0 / 2100.0 - 1)
        self.assertEqual((v["as_of"], v["since"], v["converted"]), ("2026-09-24", "2026-01-05", False))
        # a deposit on a Sunday buys at the next close
        sunday = build_desk.build_vs_market({"total": 1.0, "currency": "USD"}, self.flows(("2026-03-01", 500.0)), store)
        self.assertAlmostEqual(sunday["market_value"], 500.0 / 125.0 * 150.0)

    def test_a_withdrawal_sells_out_of_the_market(self):
        store = self.store({"2026-01-05": 100.0, "2026-03-02": 125.0, "2026-09-24": 150.0})
        v = build_desk.build_vs_market({"total": 1.0, "currency": "USD"},
                                       self.flows(("2026-01-05", 1000.0), ("2026-03-02", -250.0)), store)
        self.assertAlmostEqual(v["market_value"], (10 - 2) * 150.0)

    def test_an_account_in_euros_goes_through_each_days_rate(self):
        store = self.store({"2026-01-05": 100.0, "2026-09-24": 150.0},
                           **{prices.FX_PREFIX + "EUR": {"2026-01-02": 1.10, "2026-09-24": 1.20}})
        v = build_desk.build_vs_market({"total": 1300.0, "currency": "EUR"}, self.flows(("2026-01-05", 1000.0)), store)
        # 1000 EUR = 1100 USD (the rate on or before the day) = 11 units; 11 x 150 = 1650 USD = 1375 EUR
        self.assertAlmostEqual(v["market_value"], 1375.0)
        self.assertTrue(v["converted"])
        self.assertEqual(prices.tickers(store), [prices.BENCHMARK])             # a rate is never read as a share

    def test_what_cannot_be_compared_says_why(self):
        store = self.store({"2026-01-05": 100.0, "2026-09-24": 150.0})
        deposit = self.flows(("2026-01-05", 1000.0))
        self.assertIn("euro and pound", build_desk.build_vs_market({"total": 1.0, "currency": "EUR"}, deposit, store)["why_not"])
        self.assertIn("only for euro and pound", build_desk.build_vs_market({"total": 1.0, "currency": "CHF"}, deposit, store)["why_not"])
        early = build_desk.build_vs_market({"total": 1.0, "currency": "USD"}, self.flows(("2025-12-31", 10.0)), store)
        self.assertIn("2025-12-31", early["why_not"])                          # never priced at a later close
        # a deposit made since the latest close counts at its face value on both sides
        today = build_desk.build_vs_market({"total": 1510.0, "currency": "USD"},
                                           deposit + self.flows(("2026-09-25", 10.0)), store)
        self.assertAlmostEqual(today["market_value"], 1500.0 + 10.0)
        euro = self.store({"2026-01-05": 100.0, "2026-09-24": 150.0}, **{prices.FX_PREFIX + "EUR": {"2026-02-01": 1.1}})
        self.assertIn("exchange rates", build_desk.build_vs_market({"total": 1.0, "currency": "EUR"}, deposit, euro)["why_not"])
        self.assertIn("next company update", build_desk.build_vs_market({"total": 1.0}, deposit, {})["why_not"])
        self.assertIsNone(build_desk.build_vs_market({"total": 1.0}, [], store))

    def test_the_rates_are_fetched_once_a_day_and_when_missing(self):
        asked = []

        def fx(series, what=None):
            asked.append(series)
            return {"2026-09-24": 1.17}
        fetch = lambda ticker, start, key: []
        today = date(2026, 9, 25)
        store = prices.update([], stored={}, key="k", fetch=fetch, today=today, cash=lambda: {"2026-09-24": 4.0},
                              currency="EUR", fx=fx)
        self.assertEqual((asked, store[prices.FX_PREFIX + "EUR"]), (["DEXUSEU"], {"2026-09-24": 1.17}))
        prices.update([], stored=store, key="k", fetch=fetch, today=today, cash=lambda: {}, currency="EUR", fx=fx)
        self.assertEqual(len(asked), 1)                                          # once a day
        prices.update([], stored=store, key="k", fetch=fetch, today=today, cash=lambda: {}, currency="GBP", fx=fx)
        self.assertEqual(asked[-1], "DEXUSUK")                                   # missing: fetched
        prices.update([], stored={}, key="k", fetch=fetch, today=today, cash=lambda: {"d": 1.0}, currency="USD", fx=fx)
        self.assertEqual(len(asked), 2)                                          # a dollar account needs none
        # as of a past day, a rate is dated like a close
        kept = asof.closes({prices.FX_PREFIX + "EUR": {"2026-01-02": 1.1, "2026-09-24": 1.2}}, "2026-06-01")
        self.assertEqual(kept[prices.FX_PREFIX + "EUR"], {"2026-01-02": 1.1})

    def test_the_page_says_it_on_the_overview(self):
        hero = template_function("renderHero")
        self.assertIn("DATA.vs_market", hero)
        self.assertIn("esc(v.why_not)", hero)
        self.assertIn("currency=self.account_currency()", inspect.getsource(server.Handler.update_research))


class CostTests(unittest.TestCase):
    """What investing has cost, in one place: Trading 212 charges each fill and withholds
    tax on each dividend, and shows neither added up."""

    def fill(self, *taxes, day="2026-03-02"):
        return {"order": {"id": 1}, "fill": {"filledAt": day + "T15:00:00Z", "walletImpact": {
            "taxes": [{"name": n, "quantity": q} for n, q in taxes]}}}

    def test_every_charge_by_kind_and_the_tax_on_dividends(self):
        orders = [self.fill(("CURRENCY_CONVERSION_FEE", 1.5), ("FINRA_FEE", 0.02)),
                  self.fill(("CURRENCY_CONVERSION_FEE", -2.5), ("SOME_NEW_FEE", 0.1), day="2026-01-05")]
        dividends = [{"grossAmountPerShare": 1.0, "quantity": 10, "amount": 8.5, "tickerCurrency": "USD",
                      "paidOn": "2026-03-15T12:00:00Z"}]
        transactions = [{"type": "INTEREST_ON_FREE_CASH", "amount": 3.0}, {"type": "DEPOSIT", "amount": 100.0}]
        positions = {"rows": [{"fx": -4.0}, {"fx": 1.0}]}
        c = build_desk.build_costs(orders, dividends, transactions, {"currency": "USD"}, positions, 95.88, {})
        self.assertEqual([(k["label"], round(k["amount"], 2)) for k in c["kinds"]],
                         [("Currency conversion fee", 4.0), ("Some new fee", 0.1), ("FINRA trading activity fee", 0.02)])
        self.assertAlmostEqual(c["withheld"], 1.5)
        self.assertAlmostEqual(c["total"], 5.62)
        self.assertAlmostEqual(c["share_of_gain"], 5.62 / (95.88 + 5.62))
        self.assertEqual((c["interest"], c["currency_moves"], c["since"]), (3.0, -3.0, "2026-01-05"))

    def test_a_dollar_dividend_into_a_euro_account_goes_through_the_days_rate(self):
        dividends = [{"grossAmountPerShare": 1.1, "quantity": 10, "amount": 8.5, "tickerCurrency": "USD",
                      "paidOn": "2026-03-15T12:00:00Z"},
                     {"grossAmountPerShare": 2.0, "quantity": 1, "amount": 1.0, "tickerCurrency": "CHF",
                      "paidOn": "2026-03-15T12:00:00Z"}]
        store = {prices.FX_PREFIX + "EUR": {"2026-03-13": 1.1}}
        c = build_desk.build_costs([], dividends, [], {"currency": "EUR"}, {}, 10.0, store)
        self.assertAlmostEqual(c["withheld"], 11.0 / 1.1 - 8.5)          # 10 EUR declared, 8.50 received
        self.assertEqual(c["unconverted_dividends"], 1)
        self.assertIsNone(build_desk.build_costs([], [], [], {}, {}, -5.0, {})["share_of_gain"])

    def test_the_portfolio_page_shows_them(self):
        body = template_function("renderCosts")
        self.assertIn("C.share_of_gain", body)
        self.assertIn("esc(k.label)", body)
        d = build_desk.compute(generate_demo_data.generate(TODAY), today=TODAY)
        self.assertGreater(d["costs"]["total"], 0)
        self.assertAlmostEqual(d["costs"]["fees"], d["trades"]["fees"])     # one sum of the same charges


class ExposureTests(unittest.TestCase):
    """What the account really owns, by industry: the SEC's own code for each company, in
    the SIC Manual's major groups, with funds named rather than guessed at."""

    ROWS = [{"ticker": "AAPL", "us_line": True, "value": 600.0}, {"ticker": "NVDA", "us_line": True, "value": 200.0},
            {"ticker": "AMD", "us_line": True, "value": 100.0}, {"ticker": "QQQ", "us_line": True, "value": 80.0},
            {"ticker": "BP", "us_line": False, "value": 20.0}]
    STORE = {"companies": {"AAPL": {"cik": 1}, "NVDA": {"cik": 2}, "AMD": {"cik": 3}, "BP": {"cik": 4}}}
    CODES = {1: 3571, 2: 3674, 3: 3674, 4: 2911}

    def test_holdings_are_grouped_by_the_secs_industry_code(self):
        x = build_desk.build_exposure({"rows": self.ROWS}, self.STORE, self.CODES, {"cash": 90.0, "spending_pot": 10.0})
        self.assertEqual([(g["label"], g["tickers"], g["value"]) for g in x["groups"]],
                         [("Industrial machinery and computer equipment", ["AAPL"], 600.0),
                          ("Electronic and electrical equipment", ["NVDA", "AMD"], 300.0)])
        # a fund, and a London line whose short ticker a US filer also uses, are named, never placed
        self.assertEqual(x["unplaced"]["tickers"], ["QQQ", "BP"])
        self.assertEqual(x["cash"]["value"], 100.0)
        whole = sum(g["weight"] for g in x["groups"]) + x["unplaced"]["weight"] + x["cash"]["weight"]
        self.assertAlmostEqual(whole, 1.0)                                   # shares of the whole account
        self.assertIsNone(x["missing"])

    def test_without_the_stored_data_it_says_what_is_missing(self):
        pos = {"rows": self.ROWS}
        self.assertEqual(build_desk.build_exposure(pos, {}, self.CODES, {})["missing"],
                         build_desk.EXPOSURE_NO_DATA["universe"])
        no_codes = build_desk.build_exposure(pos, self.STORE, {}, {})
        self.assertEqual(no_codes["missing"], build_desk.EXPOSURE_NO_DATA["codes"])
        self.assertEqual((no_codes["groups"], len(no_codes["unplaced"]["tickers"])), ([], 5))
        empty = build_desk.build_exposure({"rows": []}, {}, {}, {"cash": 0.0})
        self.assertEqual((empty["groups"], empty["unplaced"], empty["cash"]["weight"]), ([], None, None))

    def test_major_groups_are_the_manuals(self):
        self.assertEqual([sectors.major_group(c) for c in (3571, "3674", 2086, 2834, 7372, 6021)],
                         ["Industrial machinery and computer equipment", "Electronic and electrical equipment",
                          "Food and drink products", "Chemicals and drugs", "Business services",
                          "Banks and savings institutions"])
        self.assertEqual((sectors.major_group(None), sectors.major_group("x"), sectors.major_group(6600)),
                         (None, None, None))                                 # 66 is not a major group
        self.assertEqual(sectors.major_group(8888), "Foreign governments")    # the SEC's own, not the manual's 88
        # every major group but the manual's catch-all (99) sits inside one of the divisions
        for code in set(sectors.MAJOR_GROUPS) - {99}:
            self.assertIsNotNone(sectors.division(code * 100), code)

    def test_it_reaches_the_portfolio_page(self):
        d = build_desk.compute(generate_demo_data.generate(TODAY), today=TODAY)
        self.assertIn("exposure", d)
        self.assertIsNotNone(d["exposure"]["missing"])                       # no universe in a test
        body = template_function("renderExposure")
        self.assertIn("DATA.exposure", body)
        self.assertIn("esc(X.missing)", body)
        self.assertIn("'renderExposure'", page_source())


class DigestTests(unittest.TestCase):
    """Since you last looked: what is new since the sync before this one, at the top of
    the Overview, so a refresh is a two-minute read."""

    def test_only_what_came_after_the_last_look(self):
        raw = {"synced_at": "2026-09-25T09:00:00+00:00", "previous_synced_at": "2026-09-24T18:00:00+00:00"}
        items = [{"ticker": "KO", "label": "Company announcement", "form": "8-K", "what": "Results announced; Exhibits",
                  "material": True, "filed_at": "2026-09-25T08:05:00.000Z", "url": "u"},
                 {"ticker": "AMD", "label": "Insider bought", "what": "Director bought", "material": True,
                  "filed_at": "2026-09-24T21:00:00.000Z"},
                 # the SEC's times are New York's, whatever their "Z" says (news.filed_moment): 13:00
                 # there is 17:00 UTC, before the last look at 18:00; 15:00 there is 19:00 UTC, after it
                 {"ticker": "KO", "label": "Quarterly report", "material": True, "filed_at": "2026-09-24T13:00:00.000Z"},
                 {"ticker": "JNJ", "label": "Insider trade", "material": False, "filed_at": "2026-09-25T07:00:00.000Z"},
                 {"ticker": "MSFT", "label": "Quarterly report", "material": True, "filed_at": "2026-09-24T15:00:00.000Z"}]
        log = [{"ticker": "KO", "date": "2026-06-20", "at": "2026-06-20T09:00:00+00:00", "label": "Hold"},
               {"ticker": "KO", "date": "2026-09-25", "at": "2026-09-25T09:00:00+00:00", "label": "Buy"},
               {"ticker": "AMD", "date": "2026-09-25", "at": "2026-09-25T09:00:00+00:00", "label": "Sell"},
               # the fixed sample's, logged to score the rating: no company of the user's
               {"ticker": "Q031", "date": "2026-09-25", "at": "2026-09-25T09:00:00+00:00", "label": "Buy", "sample": True}]
        days = {"2026-09-23": {"c": 100.0, "a": 100.0}, "2026-09-24": {"c": 110.0, "a": 110.0},
                "2026-09-25": {"c": 99.0, "a": 99.0}}
        positions = {"rows": [{"ticker": "AMD", "us_line": True, "rating": {"label": "Sell"}},
                              {"ticker": "KO", "us_line": True, "rating": {"label": "Buy"}},
                              {"ticker": "RR", "us_line": False, "rating": {"label": None}}]}
        # RR here is Rolls-Royce in London; the stored RR prices are a US company's
        d = build_desk.build_digest(raw, {"items": items}, {"AMD": days, "RR": {"2026-09-24": {"c": 1.0, "a": 1.0},
                                                                                "2026-09-25": {"c": 9.0, "a": 9.0}}},
                                    log, positions, date(2026, 9, 25), looks={"previous": "2026-09-24T18:00:00+00:00"})
        self.assertEqual([i["ticker"] for i in d["important"]], ["KO", "AMD", "MSFT"])   # not the one filed before
        self.assertEqual(d["important"][0]["headline"], "Results announced")          # what the announcement is
        self.assertEqual([i["ticker"] for i in d["insider_buys"]], ["AMD"])
        self.assertEqual(d["ratings"], [{"ticker": "AMD", "label": "Sell", "was": None},
                                        {"ticker": "KO", "label": "Buy", "was": "Hold"}])
        self.assertAlmostEqual(d["moves"][0]["change"], 99.0 / 110.0 - 1)            # from the close before the last look
        self.assertEqual([m["ticker"] for m in d["moves"]], ["AMD"])                 # never another listing's price
        self.assertEqual(d["rated_sell"], ["AMD"])
        self.assertIsNone(build_desk.build_digest(raw, {}, {}, [], {}, date(2026, 9, 25), as_of="2026-06-01"))

    def test_no_trade_is_asked_for_a_reason_and_second_looks_that_have_come_show(self):
        """A trade with no note is never listed as missing one; a second look the user
        set still shows when its day comes."""
        raw = {"synced_at": "2026-09-25T09:00:00+00:00", "previous_synced_at": "2026-09-24T18:00:00+00:00"}
        rows = [{"id": "1", "ticker": "KO", "side": "BUY", "date": "2026-09-24", "time": "2026-09-24T19:00:00.000Z", "note": ""},
                {"id": "2", "ticker": "AMD", "side": "SELL", "date": "2026-09-24", "time": "2026-09-24T20:00:00.000Z",
                 "note": "Why I sold: results"},
                {"id": "3", "ticker": "JNJ", "side": "BUY", "date": "2026-09-01", "time": "2026-09-01T15:00:00.000Z", "note": ""},
                {"id": "4", "ticker": "MSFT", "side": "BUY", "date": "2026-06-01", "time": "2026-06-01T15:00:00.000Z",
                 "note": "Why I bought: cloud\nI'd sell if: margins fall", "look_again": "2026-09-25"},
                {"id": "5", "ticker": "NVDA", "side": "BUY", "date": "2026-06-01", "time": "2026-06-01T15:00:00.000Z",
                 "note": "", "look_again": "2026-10-01"}]
        d = build_desk.build_digest(raw, {}, {}, [], {}, date(2026, 9, 25), trades={"rows": rows})
        self.assertNotIn("unnoted", d)
        self.assertEqual([(t["ticker"], t["note"]) for t in d["due"]], [("MSFT", "Why I bought: cloud")])
        self.assertEqual(d["due_count"], 1)
        body = template_function("renderDigest")
        self.assertNotIn("unnoted", body)
        self.assertNotIn("Write why", page_source())
        self.assertIn("D.due", body)

    def test_a_note_is_optional_and_asks_nothing(self):
        page = page_source()
        self.assertNotIn("NOTE_PROMPTS", page)                         # no questions in an empty note
        self.assertIn("esc(r.note || '')", template_function("renderTrades"))
        self.assertNotIn('data-f="nonote"', page)                      # nor a list of trades "missing" one
        self.assertIn("JSON.stringify({id, note, look_again})", page)

    def test_it_counts_from_the_end_of_the_last_visit(self):
        """27 Sep 2026: it counted from the account sync before the last, so a second sync
        emptied it and no sync froze it. A visit is every opening and reload until the desk
        has been closed for looks.VISIT_GAP."""
        at = lambda h, m=0: datetime(2026, 9, 25, h, m, tzinfo=timezone.utc)
        stored, new = looks.record({}, now=at(9))
        self.assertTrue(new)
        self.assertIsNone(looks.since(stored))                                    # the first time: the last week
        stored, new = looks.record(stored, now=at(9, 40))                         # a reload while open
        self.assertFalse(new)
        stored, new = looks.record(stored, now=at(10, 30))                        # 50 minutes on: the same visit
        self.assertFalse(new)
        stored, new = looks.record(stored, now=at(18))                            # closed for hours: a new look
        self.assertTrue(new)
        self.assertEqual(looks.since(stored), at(10, 30).isoformat())             # since the last visit ended
        self.assertEqual(looks.VISIT_GAP, timedelta(hours=1))
        d = build_desk.build_digest({}, {"items": [{"ticker": "KO", "label": "x", "material": True, "date": "2026-09-25"}]},
                                    {}, [], {}, date(2026, 9, 25), looks=stored)
        self.assertEqual((d["since"], d["important_count"]), (at(10, 30).isoformat(), 0))   # no account sync needed
        self.assertIn("if self.look():", inspect.getsource(server.Handler.do_GET))           # an opening records it
        self.assertIn("looks.json", open(os.path.join(ROOT, ".gitignore")).read().split())

    def test_with_no_earlier_sync_it_reads_the_last_week(self):
        d = build_desk.build_digest({"synced_at": "2026-09-25T09:00:00+00:00"},
                                    {"items": [{"ticker": "KO", "label": "x", "material": True, "date": "2026-09-20"},
                                               {"ticker": "KO", "label": "y", "material": True, "date": "2026-09-10"}]},
                                    {}, [], {}, date(2026, 9, 25))
        self.assertEqual((d["fallback_days"], d["important_count"]), (build_desk.DIGEST_FALLBACK_DAYS, 1))

    def test_each_sync_keeps_the_time_of_the_one_before(self):
        c = SyncTests().pages_client({})
        first = t212.sync(c, {}, log=lambda *_: None)
        self.assertIsNone(first["previous_synced_at"])
        second = t212.sync(c, first, log=lambda *_: None)
        self.assertEqual(second["previous_synced_at"], first["synced_at"])
        self.assertIn("DATA.digest", template_function("renderDigest"))


class MetricTests(unittest.TestCase):
    def test_short_ticker(self):
        self.assertEqual(build_desk.short_ticker("AAPL_US_EQ"), "AAPL")
        self.assertEqual(build_desk.short_ticker("VUSAl_EQ"), "VUSA")
        self.assertEqual(build_desk.short_ticker("BRK.B_US_EQ"), "BRK.B")
        self.assertEqual(build_desk.short_ticker(None), "?")

    def test_mwr_single_deposit_matches_simple_growth(self):
        # 1000 in exactly 2 years ago, 1210 now → 10% a year
        r = build_desk.money_weighted_return([("2024-09-19", 1000)], 1210, "2026-09-19")
        self.assertAlmostEqual(r["annual"], 0.10, places=3)
        self.assertAlmostEqual(r["period"], 0.21, places=3)

    def test_mwr_short_period_not_annualised_on_page(self):
        r = build_desk.money_weighted_return([("2026-06-21", 1000)], 1050, "2026-09-19")
        self.assertLess(r["days"], 365)
        self.assertAlmostEqual(r["period"], 0.05, places=3)

    def test_days_at_work_counts_the_days_the_net_put_in_stood_at_a_tenth_of_its_highest(self):
        """By hand: 100 in on 1 Jan, 95 out on 11 Jan, 5 in on 1 Feb, to 1 Mar. The net stands at 100 for 10 days,
        at 5 (under the tenth, 10) for 21 days, and at 10 (the tenth) for the last 28."""
        flows = [("2026-01-01", 100.0), ("2026-01-11", -95.0), ("2026-02-01", 5.0)]
        self.assertEqual(build_desk.days_at_work(flows, "2026-03-01"), 10 + 28)
        self.assertEqual(build_desk.days_at_work([("2026-01-01", 100.0)], "2026-01-31"), 30)
        self.assertEqual(build_desk.days_at_work([("2026-01-01", 100.0), ("2026-01-01", -100.0)], "2026-01-31"), 0)
        self.assertEqual(build_desk.days_at_work([("2026-01-01", -5.0)], "2026-01-31"), 0)       # nothing was ever put in
        self.assertEqual(build_desk.days_at_work([], "2026-01-31"), 0)
        # a deposit and a withdrawal on one day are one movement: the order the records come in does not matter
        a = build_desk.days_at_work([("2026-01-01", 100.0), ("2026-01-05", 50.0), ("2026-01-05", -50.0)], "2026-01-31")
        b = build_desk.days_at_work([("2026-01-01", 100.0), ("2026-01-05", -50.0), ("2026-01-05", 50.0)], "2026-01-31")
        self.assertEqual((a, b), (30, 30))

    def test_an_account_that_sat_near_empty_for_years_states_no_yearly_rate(self):
        """4 pounds in an account that had money passing through it for a few weeks and pennies for 2.7 years:
        the yearly rate (which the IRR still solves) rests on the pennies, and it once read +4299.8% a year."""
        flows = [("2024-01-15", 150.0), ("2024-01-22", -149.7), ("2026-03-20", 265.0), ("2026-04-24", -264.0),
                 ("2026-06-12", 130.0), ("2026-07-10", -130.4)]
        r = build_desk.money_weighted_return(flows, 3.98, "2026-10-05")
        self.assertGreater(r["days"], 365)
        self.assertLess(r["at_work"], 365)
        self.assertIsNone(r["shown"])
        self.assertFalse(r["steady"])
        self.assertIn("only %d of the %d days" % (r["at_work"], r["days"]), r["why"])
        self.assertIn("a yearly rate needs a year of it", r["why"])
        # the same pennies and a hundred pounds that stayed two years: the rate is stated
        steady = build_desk.money_weighted_return(flows + [("2024-02-01", 100.0)], 120.0, "2026-10-05")
        self.assertEqual(steady["shown"], "annual")
        self.assertIsNone(steady["why"])

    def test_the_figure_that_may_be_stated(self):
        # a year of money at work: the yearly rate, whatever the calendar says
        r = build_desk.money_weighted_return([("2024-09-19", 1000)], 1210, "2026-09-19")
        self.assertEqual((r["shown"], r["at_work"], r["days"]), ("annual", 730, 730))
        r = build_desk.money_weighted_return([("2025-09-19", 1000)], 1100, "2026-09-19")
        self.assertEqual(r["shown"], "annual")                                           # exactly a year is a year
        # a young account: the period's own return, never annualised
        r = build_desk.money_weighted_return([("2026-06-21", 1000)], 1050, "2026-09-19")
        self.assertEqual(r["shown"], "period")
        # ...unless the money was at work for under half of it
        r = build_desk.money_weighted_return([("2026-06-21", 1000), ("2026-06-23", -990)], 12, "2026-09-19")
        self.assertIsNone(r["shown"])
        self.assertNotIn("yearly", r["why"])
        # a regular saver of 14 months keeps the yearly rate: the money was at work from the second month
        saver = [((date(2025, 8, 1) + timedelta(days=30 * k)).isoformat(), 500.0) for k in range(14)]
        r = build_desk.money_weighted_return(saver, 7600.0, "2026-10-05")
        self.assertEqual(r["shown"], "annual")
        # Excel's own XIRR example (more out than in) is 411 days of it
        r = build_desk.money_weighted_return([("2008-01-01", 10000), ("2008-03-01", -2750), ("2008-10-30", -4250),
                                              ("2009-02-15", -3250)], 2750, "2009-04-01")
        self.assertEqual(r["shown"], "annual")

    def test_mwr_with_withdrawal(self):
        r = build_desk.money_weighted_return([("2025-09-19", 1000), ("2026-03-20", -500)], 0, "2026-09-19")
        self.assertIsNotNone(r)
        self.assertLess(r["annual"], 0)

    def test_empty_account_never_crashes(self):
        d = build_desk.compute({}, {}, TODAY)
        self.assertFalse(d["connected"])
        self.assertEqual(d["positions"]["count"], 0)
        self.assertIsNone(d["growth"]["mwr"])
        self.assertEqual(len(d["dividends"]["months"]), build_desk.DIVIDEND_MONTHS)
        self.assertIn("__DATA__", page_source())
        self.assertNotIn("__DATA__", build_desk.render(d))

    def test_demo_account_adds_up(self):
        raw = generate_demo_data.generate(TODAY)
        d = build_desk.compute(raw, {}, TODAY)
        a, p = d["account"], d["positions"]
        self.assertAlmostEqual(sum(r["weight"] for r in p["rows"]), 1.0, places=6)
        self.assertAlmostEqual(sum(r["value"] for r in p["rows"]), a["invested"], delta=0.1)
        self.assertAlmostEqual(a["total"], a["cash"] + a["invested"], delta=0.1)
        self.assertEqual(d["trades"]["count"], d["trades"]["buys"] + sum(1 for r in d["trades"]["rows"] if r["side"] == "SELL"))
        self.assertTrue(d["demo"])
        self.assertEqual(d["dividends"]["months"][-1]["month"], "2026-09")

    def test_spending_pot_is_the_unexplained_part_of_total(self):
        a = build_desk.build_account({"totalValue": 13.87, "cash": {"availableToTrade": 0.5},
                                      "investments": {"currentValue": 0}}, [])
        self.assertAlmostEqual(a["spending_pot"], 13.37, places=2)
        self.assertAlmostEqual(a["cash"], 0.5, places=2)

    def test_investing_gain_ignores_card_spending_and_transfers(self):
        raw = {"summary": {"totalValue": 13.87, "cash": {"availableToTrade": 0.5},
                           "investments": {"currentValue": 0, "realizedProfitLoss": 3.05}},
               "transactions": [{"type": "DEPOSIT", "amount": 50, "dateTime": "2024-01-15T09:00:00Z"},
                                {"type": "WITHDRAW", "amount": -40, "dateTime": "2024-02-01T09:00:00Z"},
                                {"type": "INTEREST_ON_FREE_CASH", "amount": 0.6, "dateTime": "2024-03-01T09:00:00Z"}]}
        g = build_desk.compute(raw, {}, TODAY)["growth"]
        self.assertAlmostEqual(g["investing"], 3.65, places=2)

    def test_flows_ignore_fees_and_interest(self):
        tx = [{"type": "DEPOSIT", "amount": 100, "dateTime": "2026-01-02T09:00:00Z"},
              {"type": "WITHDRAW", "amount": -40, "dateTime": "2026-02-02T09:00:00Z"},
              {"type": "INTEREST_ON_FREE_CASH", "amount": 1, "dateTime": "2026-02-03T09:00:00Z"},
              {"type": "FEE", "amount": -1, "dateTime": "2026-02-04T09:00:00Z"}]
        self.assertEqual(build_desk.external_flows(tx), [("2026-01-02", 100.0), ("2026-02-02", -40.0)])

    def test_journal_note_attaches_to_trade(self):
        raw = generate_demo_data.generate(TODAY)
        oid = str(raw["orders"][0]["order"]["id"])
        d = build_desk.compute(raw, {oid: {"note": "Earnings beat"}}, TODAY)
        self.assertEqual(d["trades"]["rows"][0]["note"], "Earnings beat")
        self.assertEqual(d["trades"]["noted"], 1)

    def test_script_tag_cannot_be_closed_by_data(self):
        d = build_desk.compute({}, {}, TODAY)
        d["x"] = "</script><script>alert(1)</script>"
        self.assertNotIn("</script><script>alert", build_desk.render(d))


class ClosedTradeTests(unittest.TestCase):
    def prices(self):
        # market doubles over 100 days; each day +~0.7%
        out, d, v = {}, date(2024, 1, 1), 100.0
        for _ in range(200):
            out[d.isoformat()] = v
            v *= 1.007
            d += timedelta(days=1)
        return {"SPY": out}

    def trades(self):
        """Each with its net value, what moved in the account (Trading 212's walletImpact.netValue)."""
        return [
            {"ticker": "ZZZ", "side": "BUY", "quantity": 10, "price": 100.0, "value": 1000.0, "date": "2024-01-02", "time": "2024-01-02T10:00:00Z"},
            {"ticker": "ZZZ", "side": "BUY", "quantity": 10, "price": 110.0, "value": 1100.0, "date": "2024-01-10", "time": "2024-01-10T10:00:00Z"},
            {"ticker": "ZZZ", "side": "SELL", "quantity": 15, "price": 130.0, "value": 1950.0, "date": "2024-02-01", "time": "2024-02-01T10:00:00Z"},
        ]

    def test_a_sale_is_one_row_whatever_it_closed(self):
        """27 Sep 2026: one sale closing two buys read as two trades, and the record as more
        certain than it is. The sale is the decision."""
        c = build_desk.build_closed_trades(self.trades(), self.prices(), TODAY)
        self.assertEqual(c["count"], 1)
        (row,) = c["rows"]
        self.assertEqual((row["buys"], row["quantity"], row["bought"], row["bought_last"]), (2, 15, "2024-01-02", "2024-01-10"))
        self.assertAlmostEqual(row["buy_price"], (10 * 100 + 5 * 110) / 15)       # first in, first out
        self.assertAlmostEqual(row["gain"], 15 * 130 / (10 * 100 + 5 * 110) - 1)

    def test_leftover_shares_stay_open(self):
        c = build_desk.build_closed_trades(self.trades(), self.prices(), TODAY)
        self.assertEqual(c["open_lots"], [{"ticker": "ZZZ", "quantity": 5, "bought": "2024-01-10"}])

    def test_each_sale_is_compared_with_the_market_over_its_buys_own_dates(self):
        c = build_desk.build_closed_trades(self.trades(), self.prices(), TODAY)
        (row,) = c["rows"]
        first, second = 1.007 ** 30 - 1, 1.007 ** 22 - 1                          # 2 Jan and 10 Jan → 1 Feb
        self.assertAlmostEqual(row["market"], (1000 * first + 550 * second) / 1550, places=9)   # by their cost
        self.assertAlmostEqual(row["vs_market"], row["gain"] - row["market"], places=9)
        self.assertEqual((c["beat_market"]["k"], c["beat_market"]["n"]), (1, 1))
        self.assertEqual(c["beat_market"]["expected"], 0.5)
        self.assertEqual((c["vs_market"]["n"], c["won"]["n"]), (1, 1))

    def test_fees_come_off_what_the_money_did(self):
        """A fill's net value has its fee in: added to what a purchase took, taken from what a sale gave."""
        fee = lambda t: t["quantity"] * t["price"] * 0.0015
        trades = [dict(t, value=t["quantity"] * t["price"] + (fee(t) if t["side"] == "BUY" else -fee(t)), fees=fee(t))
                  for t in self.trades()]
        (row,) = build_desk.build_closed_trades(trades, self.prices(), TODAY)["rows"]
        self.assertAlmostEqual(row["gain"], 15 * 130 * (1 - 0.0015) / ((10 * 100 + 5 * 110) * 1.0015) - 1)
        self.assertTrue(row["after_fees"])

    def test_a_split_while_held_is_never_a_loss(self):
        """A 10-for-1 split: bought 1 share at $1,000 before it, sold 10 at $120 after. It read
        as an 88% loss, and nine of the ten shares vanished from the record."""
        prices_ = dict(self.prices(), NVDA={"2024-01-02": {"c": 1000.0, "a": 100.0},
                                            "2024-01-20": {"c": 110.0, "a": 110.0, "s": 10.0},
                                            "2024-02-01": {"c": 120.0, "a": 120.0}})
        trades = [{"ticker": "NVDA", "side": "BUY", "quantity": 1, "price": 1000.0, "value": 1000.0, "date": "2024-01-02",
                   "time": "2024-01-02T15:00:00Z", "us_line": True},
                  {"ticker": "NVDA", "side": "SELL", "quantity": 10, "price": 120.0, "value": 1200.0, "date": "2024-02-01",
                   "time": "2024-02-01T15:00:00Z", "us_line": True}]
        c = build_desk.build_closed_trades(trades, prices_, TODAY)
        (row,) = c["rows"]
        self.assertAlmostEqual(row["gain"], 0.20)
        self.assertEqual((row["quantity"], row["buy_price"], row["split"]), (10, 100.0, True))
        self.assertEqual(c["open_lots"], [])
        # a London line shares a short ticker with a US company, never its splits
        london = [dict(t, us_line=False) for t in trades]
        self.assertAlmostEqual(build_desk.build_closed_trades(london, prices_, TODAY)["rows"][0]["gain"], -0.88)
        self.assertEqual(prices.split_factor(prices_, "NVDA", "2024-01-02", "2024-02-01"), 10.0)
        self.assertEqual(prices.split_factor(prices_, "NVDA", "2024-01-20", "2024-02-01"), 1.0)   # bought on the new basis
        # read once for a loop over many trades: the same arithmetic, one definition
        read = prices.SplitsRead(prices_)
        for after, through in (("2024-01-02", "2024-02-01"), ("2024-01-20", "2024-02-01"), ("2023-01-01", "2023-06-01")):
            self.assertEqual(read.factor("NVDA", after, through), prices.split_factor(prices_, "NVDA", after, through))
        self.assertEqual(read.factor("NONE", "2024-01-01", "2024-02-01"), 1.0)
        raw = generate_demo_data.generate(TODAY)
        rows = build_desk.build_trades(raw["orders"], {})["rows"]
        self.assertTrue(all(isinstance(r["us_line"], bool) for r in rows))

    def test_same_day_trades_are_not_scored_against_daily_prices(self):
        trades = [{"ticker": "ZZZ", "side": "BUY", "quantity": 1, "price": 100.0, "value": 100.0, "date": "2024-01-02",
                   "time": "2024-01-02T10:00:00Z"},
                  {"ticker": "ZZZ", "side": "SELL", "quantity": 1, "price": 103.0, "value": 103.0, "date": "2024-01-02",
                   "time": "2024-01-02T15:00:00Z"}]
        c = build_desk.build_closed_trades(trades, self.prices(), TODAY)
        self.assertEqual(c["count"], 1)
        self.assertEqual(c["scored"], 0)
        self.assertIsNone(c["rows"][0]["vs_market"])


class HabitTests(unittest.TestCase):
    """27 Sep 2026: how the user trades, measured as Barber & Odean (2000) and Odean (1998,
    1999) measured everyone, each figure with its interval beside the paper's."""

    def trade(self, ticker, side, day, qty, price, value=None):
        return {"ticker": ticker, "side": side, "date": day, "time": day + "T15:00:00Z", "quantity": qty, "price": price,
                "value": value if value is not None else qty * price, "us_line": True}

    def test_turnover_is_each_months_averaged_a_year(self):
        """Barber & Odean (2000): each month's turnover (history.month_turnover, their definition,
        checked in test_audit), averaged, twelve months of it a year: the unit of their 75%.
        Without the months, today's holdings stand in, and the page says so."""
        rows = [self.trade("AAA", "BUY", "2026-06-01", 10, 100.0), self.trade("AAA", "SELL", "2026-07-01", 10, 120.0),
                self.trade("BBB", "BUY", "2024-01-01", 1, 100.0),                  # older than a year: not counted
                self.trade("CCC", "BUY", "2026-09-02", 1, 100.0)]                  # this month, not whole: not yet
        today = date(2026, 9, 27)
        self.assertEqual(habits.turnover_months(today)[0], "2025-09")
        self.assertEqual(habits.turnover_months(today)[-1], "2026-08")
        t = habits.turnover(rows, 10000.0, today)
        self.assertEqual((t["trades"], t["bought"], t["sold"], t["basis"]), (2, 1000.0, 1200.0, "today"))
        self.assertAlmostEqual(t["yearly"], (1000.0 + 1200.0) / 2 / 10000.0)
        monthly = {m: 0.0 for m in habits.turnover_months(today)}
        monthly.update({"2026-07": 0.5, "2026-08": 0.25})
        monthly["2025-09"] = None                                                 # began with nothing held
        t = habits.turnover(rows, 10000.0, today, monthly)
        self.assertEqual(t["basis"], "month")
        self.assertAlmostEqual(t["yearly"], 12 * 0.75 / 11)
        self.assertIsNone(habits.turnover(rows, 0, today)["yearly"])
        self.assertEqual(habits.PUBLISHED["turnover_yearly_average"], 0.75)      # Barber & Odean (2000)

    def test_gains_and_losses_are_counted_on_each_day_something_is_sold(self):
        """Odean (1998): on a day with a sale, each holding is a realised or paper gain or loss."""
        rows = [self.trade("WIN", "BUY", "2026-01-02", 10, 100.0), self.trade("LOSE", "BUY", "2026-01-02", 10, 100.0),
                self.trade("KEEP", "BUY", "2026-01-02", 10, 100.0),
                self.trade("WIN", "SELL", "2026-03-02", 10, 130.0)]                  # a gain sold
        closes = lambda v: {"2026-01-02": {"c": 100.0, "a": 100.0}, "2026-03-02": {"c": v, "a": v}}
        prices_ = {"LOSE": closes(80.0), "KEEP": closes(110.0)}
        d = habits.disposition(rows, prices_)
        self.assertEqual(d["counts"], {"rg": 1, "rl": 0, "pg": 1, "pl": 1})      # KEEP a paper gain, LOSE a paper loss
        self.assertEqual((d["pgr"]["k"], d["pgr"]["n"], d["plr"]["k"], d["plr"]["n"]), (1, 2, 0, 1))
        self.assertIn("distinguishable", d["difference"])
        # a split while held: 1 share at $1,000 is 10 at $110, a gain, not a 90% loss
        split = {"NVDA": {"2026-01-02": {"c": 1000.0, "a": 100.0}, "2026-02-01": {"c": 110.0, "a": 110.0, "s": 10.0}}}
        rows = [self.trade("NVDA", "BUY", "2026-01-02", 1, 1000.0), self.trade("ZZZ", "BUY", "2026-01-02", 1, 10.0),
                self.trade("ZZZ", "SELL", "2026-02-01", 1, 12.0)]
        self.assertEqual(habits.disposition(rows, split)["counts"]["pg"], 1)

    def test_a_sale_and_its_replacement_are_compared_over_the_next_year(self):
        days = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(400)]
        rising = {d: {"c": 100.0 + i, "a": 100.0 + i} for i, d in enumerate(days)}
        flat = {d: {"c": 100.0, "a": 100.0} for d in days}
        rows = [self.trade("OLD", "SELL", days[0], 1, 100.0), self.trade("NEW", "BUY", days[10], 1, 100.0),
                self.trade("OLD", "SELL", days[100], 1, 100.0), self.trade("NEW", "BUY", days[200], 1, 100.0)]  # too late
        r = habits.replaced(rows, {"OLD": rising, "NEW": flat})
        self.assertEqual((r["pairs"], r["within_days"], r["after_days"]), (1, 21, 252))
        self.assertLess(r["gap"]["estimate"], 0)                                   # the share bought did worse
        self.assertEqual(r["gap"]["expected"], 0)

    def test_the_difference_of_two_shares_has_newcombes_interval(self):
        """Newcombe (1998), Table II, method 10: 56/70 − 48/80 is 0.0524 to 0.3339; 9/10 −
        3/10 is 0.1705 to 0.8090."""
        d = uncertainty.difference(56, 70, 48, 80)
        self.assertEqual((round(d["low"], 4), round(d["high"], 4), d["distinguishable"]), (0.0524, 0.3339, True))
        d = uncertainty.difference(9, 10, 3, 10)
        self.assertEqual((round(d["low"], 4), round(d["high"], 4)), (0.1705, 0.8090))
        self.assertFalse(uncertainty.difference(5, 10, 5, 10)["distinguishable"])
        self.assertIsNone(uncertainty.difference(1, 0, 1, 1))
        page = page_source()
        body = template_function("renderHabits", page)
        for part in ("ofCount(d.pgr)", "ofCount(d.plr)", "d.difference.distinguishable", "P.pgr", "P.turnover_yearly_average"):
            self.assertIn(part, body)
        self.assertIsNone(re.search(r"14\.8|9\.8|\b75%", body))               # the papers' figures come as data
        self.assertIn("habits", build_desk.compute(generate_demo_data.generate(TODAY), today=TODAY))


class PaperTests(unittest.TestCase):
    PRICES = {"ZZZ": {"2026-09-18": 100.0}, "SPY": {"2026-09-01": 100.0, "2026-09-18": 110.0}}

    def test_a_split_restates_the_practice_holding_not_its_value(self):
        prices_ = {"NVDA": {"2024-01-02": {"c": 1000.0, "a": 100.0}, "2024-01-20": {"c": 110.0, "a": 110.0, "s": 10.0},
                            "2024-02-01": {"c": 120.0, "a": 120.0}},
                   "SPY": {"2024-01-02": {"c": 100.0, "a": 100.0}, "2024-02-01": {"c": 101.0, "a": 101.0}}}
        before = {k: {d: v for d, v in days.items() if d <= "2024-01-02"} for k, days in prices_.items()}
        book = paper.trade(paper.reset(), before, "NVDA", "BUY", amount=1000, today=date(2024, 1, 2))
        page = build_desk.build_paper(book, prices_, date(2024, 2, 1))
        self.assertEqual((page["positions"][0]["quantity"], page["positions"][0]["value"]), (10.0, 1200.0))
        self.assertEqual(book["positions"]["NVDA"]["quantity"], 1.0)            # the stored book is not changed by a page
        book = paper.trade(book, prices_, "NVDA", "SELL", quantity=9, today=date(2024, 2, 1))
        self.assertAlmostEqual(book["positions"]["NVDA"]["quantity"], 1.0)      # ten after the split, nine sold
        old = {"cash": 0.0, "start_cash": 0.0, "positions": {"NVDA": {"quantity": 1.0, "cost": 1000.0}},
               "trades": [{"ticker": "NVDA", "side": "BUY", "quantity": 1.0, "date": "2024-01-02", "price_day": "2024-01-02"}]}
        self.assertEqual(paper.apply_splits(old, prices_)["positions"]["NVDA"]["quantity"], 10.0)   # a book from before

    def book(self):
        return {"cash": 10000.0, "start_cash": 10000.0, "positions": {}, "trades": [], "started": None}

    def test_buy_spends_cash_and_pays_the_same_cost_as_a_real_trade(self):
        b = paper.trade(self.book(), self.PRICES, "ZZZ", "BUY", amount=1000, today=date(2026, 9, 21))
        self.assertAlmostEqual(b["positions"]["ZZZ"]["quantity"], 10.0, places=6)
        self.assertAlmostEqual(b["cash"], 10000 - 1000 - 1000 * paper.TRADE_COST, places=6)
        self.assertAlmostEqual(b["trades"][0]["fee"], 1.5, places=6)

    def test_cannot_spend_money_it_does_not_have(self):
        with self.assertRaises(paper.PaperError):
            paper.trade(self.book(), self.PRICES, "ZZZ", "BUY", amount=20000)

    def test_cannot_sell_more_than_it_holds(self):
        b = paper.trade(self.book(), self.PRICES, "ZZZ", "BUY", amount=1000)
        with self.assertRaises(paper.PaperError):
            paper.trade(b, self.PRICES, "ZZZ", "SELL", quantity=99)

    def test_selling_records_the_gain_after_costs(self):
        b = paper.trade(self.book(), self.PRICES, "ZZZ", "BUY", amount=1000)
        higher = {"ZZZ": {"2026-09-18": 110.0}}
        b = paper.trade(b, higher, "ZZZ", "SELL", quantity=10)
        sell = b["trades"][0]
        self.assertEqual(sell["side"], "SELL")
        self.assertAlmostEqual(sell["realised"], 1100 - 1100 * paper.TRADE_COST - (1000 + 1.5), places=6)
        self.assertNotIn("ZZZ", b["positions"])

    def test_unknown_ticker_is_refused_with_a_readable_reason(self):
        with self.assertRaises(paper.PaperError) as cm:
            paper.trade(self.book(), self.PRICES, "NOPE", "BUY", amount=10)
        self.assertIn("follow it", str(cm.exception))

    def test_page_scores_practice_against_the_market_since_it_started(self):
        b = paper.trade(self.book(), self.PRICES, "ZZZ", "BUY", amount=1000, today=date(2026, 9, 1))
        out = build_desk.build_paper(b, self.PRICES, date(2026, 9, 18))
        self.assertAlmostEqual(out["market_return"], 0.10, places=6)
        self.assertAlmostEqual(out["total"], out["cash"] + out["invested"], places=6)
        self.assertAlmostEqual(out["vs_market"], out["return"] - 0.10, places=6)
        self.assertEqual(out["positions"][0]["ticker"], "ZZZ")

    def test_reset_clears_everything(self):
        b = paper.trade(self.book(), self.PRICES, "ZZZ", "BUY", amount=1000)
        b = paper.reset(b)
        self.assertEqual(b["trades"], [])
        self.assertEqual(b["positions"], {})
        self.assertEqual(b["cash"], paper.START_CASH)


class ThesisTests(unittest.TestCase):
    """Phase 9: the user's judgement written before the outcome, once, and scored."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "theses.json")

    def fund(self, *extra):
        quarters = [{"end": "2025-06-28", "revenue": 100.0, "operating_income": 10.0, "filed": "2025-08-05"},
                    {"end": "2025-09-27", "revenue": 110.0, "operating_income": 12.0, "filed": "2025-11-04"},
                    {"end": "2025-12-27", "revenue": 120.0, "operating_income": 15.0, "filed": "2026-02-03"},
                    {"end": "2026-03-28", "revenue": 125.0, "operating_income": 14.0, "filed": "2026-05-05"},
                    {"end": "2026-06-27", "revenue": 130.0, "operating_income": 16.0, "filed": "2026-08-04"}]
        return {"quarters": quarters + list(extra)}

    CLAIM = {"revenue_direction": "up", "revenue_change_pct": "10", "margin_direction": "up",
             "reason": "data-centre orders", "confidence_pct": "70"}

    def write(self, claim=None, fund=None, due="2026-11-03", today=date(2026, 9, 24)):
        return thesis.write("amd", dict(self.CLAIM, **(claim or {})), fund or self.fund(), due,
                            today=today, path=self.path)

    def test_no_thesis_names_a_quarter_already_reported(self):
        """S-21: the SEC's figures can lag the filings. Coca-Cola's June quarter was
        filed on 29 July and not in the SEC's data on 25 September, and JPMorgan's
        quarters stop in 2014; the page offered a thesis on a quarter already public,
        which could only ever be void. A report filed after the latest quarter's own
        report says the next one is out."""
        report = lambda form, day, ticker="AMD": {"ticker": ticker, "form": form, "date": day}
        own = [report("10-Q", "2026-08-04")]                        # the latest quarter's own report
        self.assertEqual(thesis.write("amd", self.CLAIM, self.fund(), "2026-11-03", today=date(2026, 9, 24),
                                      path=self.path, filings=own)["after"], "2026-06-27")
        os.remove(self.path)
        for later in ([report("10-Q", "2026-09-10")], [report("10-K", "2026-09-10")]):
            with self.assertRaises(thesis.ThesisError) as refused:
                thesis.write("amd", self.CLAIM, self.fund(), "2026-11-03", today=date(2026, 9, 24),
                             path=self.path, filings=own + later)
            self.assertIn("already public", str(refused.exception))
        # another company's reports, and an amendment, say nothing about this quarter
        ok = own + [report("10-Q", "2026-09-10", "KO"), report("10-Q/A", "2026-09-10")]
        self.assertEqual(thesis.open_for("AMD", self.fund(), "2026-11-03", date(2026, 9, 24), ok)[0], "2026-06-27")
        # a store without filing dates: the first report after the quarter's end is its own
        undated = {"quarters": [{"end": "2014-12-31", "revenue": 1.0, "operating_income": 1.0}]}
        jpm = [report("10-K", "2015-02-24", "JPM"), report("10-Q", "2015-05-01", "JPM"), report("10-Q", "2026-08-06", "JPM")]
        after, why = thesis.open_for("JPM", undated, "2026-10-13", date(2026, 9, 25), jpm)
        self.assertIsNone(after)
        self.assertIn("2 reports behind", why)
        page = thesis.summary([], {"companies": {"JPM": undated}}, {}, ["JPM"], date(2026, 9, 25), jpm)
        self.assertFalse(page["companies"]["JPM"]["can_write"])
        # S-28: the confidence range is thesis.py's, shown where it is typed, with no step of the page's own
        opener = template_function("openThesis")
        self.assertIn("$('thConf').placeholder = Math.round(range[0] * 100) + ' to ' + Math.round(range[1] * 100)", opener)
        self.assertNotIn("step = 5", opener)
        # S-25: the page frames the fragment as the refusal does, a sentence, not a bare clause
        self.assertIn("'No thesis can be written now: ' + esc(th.why_not) + '.'", template_function("thesisBlock"))

    def test_a_thesis_is_written_once_and_never_changed(self):
        entry = self.write()
        self.assertEqual((entry["ticker"], entry["after"], entry["confidence"], entry["revenue_change"]),
                         ("AMD", "2026-06-27", 0.7, 0.1))
        with self.assertRaises(thesis.ThesisError) as again:
            self.write({"reason": "changed my mind"})
        self.assertIn("written once", str(again.exception))
        self.assertEqual(len(thesis.load(self.path)), 1)
        public = [n for n in dir(thesis) if callable(getattr(thesis, n)) and not n.startswith("_")]
        self.assertFalse([n for n in public if any(w in n for w in ("edit", "update", "delete", "remove"))])

    def test_it_is_refused_once_the_results_are_due(self):
        with self.assertRaises(thesis.ThesisError) as late:
            self.write(due="2026-09-24")
        self.assertIn("due today or already out", str(late.exception))
        with self.assertRaises(thesis.ThesisError):
            self.write(fund={"quarters": []})

    def test_each_part_of_the_claim_is_required_and_consistent(self):
        for bad, words in (({"reason": " "}, "one line of reasoning"), ({"confidence_pct": "97"}, "between 50% and 95%"),
                           ({"confidence_pct": "45"}, "between 50% and 95%"), ({"margin_direction": "flat"}, "up or down"),
                           ({"revenue_change_pct": "-5"}, "disagree"), ({"revenue_change_pct": "lots"}, "a number")):
            with self.assertRaises(thesis.ThesisError) as refused:
                self.write(bad)
            self.assertIn(words, str(refused.exception), bad)
        self.assertIsNone(self.write({"revenue_change_pct": ""})["revenue_change"])

    def test_it_is_scored_against_the_quarter_it_named_and_the_year_before(self):
        entry = self.write()
        self.assertIsNone(thesis.outcome(entry, self.fund()))                 # not reported yet
        arrived = self.fund({"end": "2026-09-26", "revenue": 121.0, "operating_income": 13.0, "filed": "2026-11-03"})
        out = thesis.outcome(entry, arrived)
        self.assertEqual((out["quarter"], out["year_before"]), ("2026-09-26", "2025-09-27"))
        self.assertAlmostEqual(out["revenue_change"], 0.1)
        self.assertAlmostEqual(out["margin_change"], 13 / 121 - 12 / 110)
        self.assertEqual(out["status"], "wrong")                           # revenue up, margin down
        self.assertEqual((out["revenue_right"], out["margin_right"]), (True, False))

    def test_a_quarter_already_public_when_written_is_void(self):
        entry = self.write()
        early = self.fund({"end": "2026-09-26", "revenue": 121.0, "operating_income": 14.0, "filed": "2026-09-20"})
        self.assertEqual(thesis.outcome(entry, early)["status"], "void")

    def test_the_brier_score_is_brier_1950s(self):
        scored = [{"confidence": 0.8, "outcome": {"status": "right"}},
                  {"confidence": 0.6, "outcome": {"status": "wrong"}}]
        self.assertAlmostEqual(thesis.brier(scored), (0.2 ** 2 + 0.6 ** 2) / 2)
        self.assertEqual(thesis.brier([{"confidence": 0.5, "outcome": {"status": s}} for s in ("right", "wrong")]),
                         thesis.ALWAYS_HALF)
        self.assertIsNone(thesis.brier([]))

    def test_ten_theses_prove_nothing_and_the_calibration_says_so(self):
        scored = [{"confidence": 0.7, "outcome": {"status": "right" if i < 4 else "wrong"}} for i in range(10)]
        band = thesis.calibration(scored)[0]
        self.assertEqual((band["from"], band["to"], band["right"]["k"], band["right"]["n"]), (0.7, 0.8, 4, 10))
        self.assertAlmostEqual(band["said"], 0.7)
        self.assertAlmostEqual(band["right"]["expected"], 0.7)
        self.assertFalse(band["right"]["distinguishable"])                 # 4 of 10 against 70%: cannot tell
        top = thesis.calibration([{"confidence": 0.95, "outcome": {"status": "right"}}])
        self.assertEqual((top[0]["from"], top[0]["to"]), (0.9, 0.95))

    def test_the_page_and_the_server_carry_the_rules_without_their_own(self):
        summary = thesis.summary([self.write()], {"companies": {"AMD": self.fund()}},
                                 {"companies": {"AMD": {"next": {"date": "2026-11-03"}}}}, ["AMD"], date(2026, 9, 25))
        self.assertEqual(summary["companies"]["AMD"]["pending"]["reason"], "data-centre orders")
        self.assertFalse(summary["companies"]["AMD"]["can_write"])
        block = template_function("thesisBlock")
        self.assertIn("th.can_write", block)
        self.assertIn("cannot be changed", page_source())
        self.assertEqual(open(os.path.join(ROOT, "server.py")).read().count("thesis.write("), 1)
        self.assertNotRegex(template_function("renderTheses"), r"toFixed|\* 100")

    def test_a_quarter_is_dated_by_its_first_filing(self):
        rows = [{"start": "2026-03-29", "end": "2026-06-27", "val": 5.0, "form": "10-Q", "filed": "2026-08-04"},
                {"start": "2026-03-29", "end": "2026-06-27", "val": 5.0, "form": "10-Q", "filed": "2027-08-03"}]
        self.assertEqual(fundamentals.first_filed(rows, rows[1]), "2026-08-04")
        annual = [{"start": "2025-01-01", "end": "2025-12-27", "val": 20.0, "form": "10-K", "filed": "2026-02-03"}]
        self.assertEqual(fundamentals.first_filed(annual, {"end": "2025-12-27", "form": "derived"}), "2026-02-03")

class PlanTests(unittest.TestCase):
    """A plan before each trade (plans.py): why and what would prove it wrong, written
    once before the order, matched to the trade, and scored against the market on the day
    the user chose. Nothing here sends anything."""
    NOW = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)

    def claim(self, **k):
        return dict({"ticker": "aaa", "side": "buy", "why": "Cheap after a good quarter", "wrong_if": "Margins fall",
                     "review_by": "2026-12-01"}, **k)

    def test_a_plan_is_checked_and_written_once(self):
        folder = tempfile.mkdtemp()
        plan = plans.write(folder, self.claim(why="  Cheap   after\n a good quarter "), now=self.NOW)
        self.assertEqual({k: plan[k] for k in ("ticker", "side", "why", "wrong_if", "review_by", "written")},
                         {"ticker": "AAA", "side": "BUY", "why": "Cheap after a good quarter", "wrong_if": "Margins fall",
                          "review_by": "2026-12-01", "written": "2026-09-01T09:00:00+00:00"})
        self.assertEqual(oct(os.stat(os.path.join(folder, plans.PLANS_FILE)).st_mode & 0o777), "0o600")
        for bad, words in ((dict(ticker="aapl!"), "ticker"), (dict(ticker=""), "ticker"), (dict(side="hold"), "buy or a sell"),
                           (dict(why="x"), "why"), (dict(wrong_if=""), "wrong"), (dict(why="x" * (plans.MAX_WHY + 1)), "short"),
                           (dict(review_by="2026-09-01"), "after today"), (dict(review_by="soon"), "day"),
                           (dict(review_by="2030-01-01"), "within 3 years")):
            with self.assertRaises(plans.PlanError) as caught:
                plans.write(folder, self.claim(**bad), now=self.NOW)
            self.assertIn(words, str(caught.exception), bad)
        self.assertEqual(len(plans.load(folder)["plans"]), 1)
        # write once: no way to change or remove one, here or through the server
        self.assertFalse([n for n in dir(plans) if re.search(r"edit|delete|remove|update|amend", n)])
        self.assertNotIn("plans.json", inspect.getsource(server.Handler.do_POST))

    def trade(self, oid, ticker, side, when, price=10.0):
        return {"id": oid, "ticker": ticker, "side": side, "time": when, "date": when[:10], "price": price,
                "price_currency": "USD", "quantity": 1}

    def test_a_plan_is_matched_to_the_next_trade_that_carries_it_out(self):
        written = lambda d: {"id": f"p{d}", "written": f"2026-09-{d:02d}T09:00:00+00:00", "ticker": "AAA", "side": "BUY",
                             "why": "w", "wrong_if": "x", "review_by": "2026-12-01"}
        trades = [self.trade("before", "AAA", "BUY", "2026-09-01T08:00:00.000Z"),     # before the plan
                  self.trade("sell", "AAA", "SELL", "2026-09-02T10:00:00.000Z"),      # the other side
                  self.trade("other", "BBB", "BUY", "2026-09-02T10:00:00.000Z"),      # another company
                  self.trade("t1", "AAA", "BUY", "2026-09-03T14:31:05.123Z"),
                  self.trade("late", "AAA", "BUY", "2026-09-30T10:00:00Z")]           # past the window
        done = plans.match([written(2), written(1)], trades)
        self.assertEqual({k: v["id"] for k, v in done.items()}, {"p1": "t1"})         # the older plan takes it
        self.assertEqual(plans.MATCH_DAYS, 7)

    def test_a_plan_is_scored_against_the_market_on_its_day(self):
        closes = lambda pairs: {d: {"c": v, "a": v} for d, v in pairs}
        store = {prices.BENCHMARK: closes([("2026-09-03", 100.0), ("2026-10-01", 102.0), ("2026-12-01", 105.0)]),
                 "AAA": closes([("2026-09-03", 10.0), ("2026-10-01", 11.0), ("2026-12-01", 12.0)])}
        plan = {"id": "p", "ticker": "AAA", "side": "BUY", "review_by": "2026-12-01"}
        trade = self.trade("t", "AAA", "BUY", "2026-09-03T14:00:00Z")
        so_far = plans.result(plan, trade, store, date(2026, 10, 15))
        self.assertEqual((so_far["final"], so_far["to"]), (False, "2026-12-01"))       # the latest close stored
        final = plans.result(plan, trade, store, date(2026, 12, 2))
        self.assertEqual((final["final"], final["from"], final["to"]), (True, "2026-09-03", "2026-12-01"))
        self.assertAlmostEqual(final["edge"], 0.20 - 0.05)
        sale = plans.result(dict(plan, side="SELL"), dict(trade, side="SELL"), store, date(2026, 12, 2))
        self.assertAlmostEqual(sale["edge"], 0.05 - 0.20)                              # the shares then rose
        self.assertIsNone(plans.result(plan, trade, {}, date(2026, 12, 2)))
        waiting_close = dict(store, AAA=closes([("2026-09-03", 10.0)]))
        self.assertIsNone(plans.result(plan, trade, waiting_close, date(2026, 12, 2)))  # one close: nothing yet

    def test_the_page_lists_every_plan_and_counts_only_the_reviewed(self):
        closes = lambda pairs: {d: {"c": v, "a": v} for d, v in pairs}
        store = {prices.BENCHMARK: closes([("2026-09-03", 100.0), ("2026-12-01", 101.0)]),
                 "AAA": closes([("2026-09-03", 10.0), ("2026-12-01", 12.0)])}
        stored = {"plans": [
            {"id": "done", "written": "2026-09-02T09:00:00+00:00", "ticker": "AAA", "side": "BUY", "why": "w",
             "wrong_if": "x", "review_by": "2026-12-01"},
            {"id": "idle", "written": "2026-09-02T09:00:00+00:00", "ticker": "CCC", "side": "BUY", "why": "w",
             "wrong_if": "x", "review_by": "2026-12-01"},
            {"id": "new", "written": "2026-12-01T09:00:00+00:00", "ticker": "DDD", "side": "SELL", "why": "w",
             "wrong_if": "x", "review_by": "2027-01-01"}]}
        trades = [self.trade("t", "AAA", "BUY", "2026-09-03T14:00:00Z")]
        page = plans.summary(stored, trades, store, date(2026, 12, 2))
        self.assertEqual([(r["id"], r["state"]) for r in page["rows"]],
                         [("new", "waiting"), ("done", "reviewed"), ("idle", "not acted on")])
        self.assertEqual(page["rows"][0]["match_until"], "2026-12-08")
        self.assertEqual((page["reviewed"], page["waiting"], page["better"]["k"], page["better"]["n"]), (1, 1, 1, 1))
        self.assertIn("low", page["better"])                                            # a count with its interval
        raw = generate_demo_data.generate(TODAY)
        rows = build_desk.build_trades(raw["orders"], {})["rows"]
        first = rows[-1]
        planned = {"plans": [{"id": "x", "written": (prices.moment(first["time"]) - timedelta(hours=1)).isoformat(),
                              "ticker": first["ticker"], "side": first["side"], "why": "planned first",
                              "wrong_if": "x", "review_by": "2030-01-01"}]}
        d = build_desk.compute(raw, today=TODAY, plans=planned)
        row = next(r for r in d["trades"]["rows"] if r["id"] == first["id"])
        self.assertEqual(row["plan"]["why"], "planned first")
        self.assertEqual(d["plans"]["rows"][0]["trade"]["id"], first["id"])

    def test_the_page_writes_plans_and_shows_them_beside_their_trades(self):
        page = page_source()
        self.assertIn("'renderPlans'", page)
        self.assertIn("fetch('/plan'", page)
        self.assertIn("r.plan ?", template_function("renderTrades", page))
        opener = template_function("openPlan", page)
        for owned in ("P.match_days", "P.max_why", "P.max_wrong", "P.longest_review_days"):
            self.assertIn(owned, opener)
        self.assertIn("ofCount(P.better)", template_function("renderPlans", page))


if __name__ == "__main__":
    unittest.main()
