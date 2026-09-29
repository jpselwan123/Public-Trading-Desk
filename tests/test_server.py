"""The local server, the account sync and the company update, and the health check."""
from support import *  # noqa: F401,F403


class SlowConnectionTests(unittest.TestCase):
    """The user may reach their broker over a slow connection, and every request of a
    refresh crosses it. What changes at most once a day is fetched on the first refresh of the
    day; a dead connection is named after three tries, not five."""
    TODAY = date(2026, 9, 25)

    def test_fetched_today_reads_the_utc_day_of_a_stamp(self):
        self.assertTrue(env_config.fetched_today("2026-09-25T23:59:00+00:00", self.TODAY))
        self.assertTrue(env_config.fetched_today("2026-09-25", self.TODAY))
        for stamp in ("2026-09-24T23:59:00+00:00", "", None):
            self.assertFalse(env_config.fetched_today(stamp, self.TODAY))

    def test_the_newest_close_that_can_exist_is_the_last_session_ended_in_new_york(self):
        at = lambda y, m, d, hh, mm: datetime(y, m, d, hh, mm, tzinfo=timezone.utc)
        # Friday 25 Sep 2026, New York on summer time (UTC-4): the close is 20:00 UTC
        self.assertEqual(prices.last_close(at(2026, 9, 25, 19, 59)), date(2026, 9, 24))
        self.assertEqual(prices.last_close(at(2026, 9, 25, 20, 0)), date(2026, 9, 25))
        self.assertEqual(prices.last_close(at(2026, 9, 27, 12, 0)), date(2026, 9, 25))       # Sunday
        self.assertEqual(prices.last_close(at(2026, 9, 28, 13, 0)), date(2026, 9, 25))       # Monday morning
        # Monday 7 Dec 2026, winter time (UTC-5): 20:30 UTC is 15:30 in New York
        self.assertEqual(prices.last_close(at(2026, 12, 7, 20, 30)), date(2026, 12, 4))
        self.assertEqual(prices.last_close(at(2026, 12, 7, 21, 0)), date(2026, 12, 7))

    def test_nothing_is_asked_of_tiingo_that_cannot_have_changed(self):
        """The company data updates every half hour while the desk is open, and Tiingo's
        free key allows 50 requests an hour. Between two closes nothing is asked; after
        one, the benchmark first, and a share only once the benchmark has the new close;
        on a holiday (or before Tiingo has the day), the benchmark alone."""
        asked, published = [], {"SPY": {}, "AAA": {}, "BBB": {}}

        def fetch(ticker, start, key):
            asked.append(ticker)
            return [(d, v, v) for d, v in sorted(published[ticker].items()) if d >= start]
        at = lambda d, hh: datetime(2026, 9, d, hh, 0, tzinfo=timezone.utc)
        for t in published:
            published[t]["2026-09-23"] = 10.0
        store = prices.update(["AAA", "BBB"], stored={}, key="k", fetch=fetch, now=at(24, 12),
                              cash=None, fx=None)
        self.assertEqual(asked, ["SPY", "AAA", "BBB"])                    # the first time: everything
        asked.clear()
        for hour in (13, 14, 15, 19):                                     # Thursday, before the close
            store = prices.update(["AAA", "BBB"], stored=store, key="k", fetch=fetch, now=at(24, hour),
                                  cash=None, fx=None)
        self.assertEqual(asked, [])
        store = prices.update(["AAA", "BBB"], stored=store, key="k", fetch=fetch, now=at(24, 21),
                              cash=None, fx=None)
        self.assertEqual(asked, ["SPY"])                                  # closed, not yet published
        asked.clear()
        for t in published:
            published[t]["2026-09-24"] = 11.0
        published["BBB"].pop("2026-09-24")                                # BBB did not trade that day
        store = prices.update(["AAA", "BBB"], stored=store, key="k", fetch=fetch, now=at(24, 22),
                              cash=None, fx=None)
        self.assertEqual(asked, ["SPY", "AAA", "BBB"])
        self.assertEqual(max(store["AAA"]), "2026-09-24")
        asked.clear()
        store = prices.update(["AAA", "BBB"], stored=store, key="k", fetch=fetch, now=at(25, 12),
                              cash=None, fx=None)
        self.assertEqual(asked, ["BBB"])                                  # only the one still behind
        asked.clear()
        for hour in (21, 22, 23):                                         # Friday a holiday: no closes
            prices.update(["AAA"], stored=store, key="k", fetch=fetch, now=at(25, hour), cash=None, fx=None)
        self.assertEqual(asked, ["SPY", "SPY", "SPY"])
        asked.clear()
        prices.update(["AAA"], stored=store, key="k", fetch=fetch, now=at(27, 12), cash=None, fx=None)
        self.assertEqual(asked, ["SPY"])                                  # the weekend: Friday's, once more
        source = inspect.getsource(server.Handler.update_research)
        self.assertIn("prices.update(", source)                           # the refresh goes through it

    def test_a_later_dividend_or_split_restates_the_stored_adjusted_closes(self):
        """27 Sep 2026: the adjusted closes were stored a day at a time and never restated,
        so a split read as a fall and a dividend dropped out of every return. Each update now
        asks from the last stored day, and the ratio on it re-bases the rest."""
        tiingo = {"AAA": [("2026-09-21", 100.0, 100.0, 1.0), ("2026-09-22", 100.0, 100.0, 1.0)]}
        asked = []

        def fetch(ticker, start, key):
            asked.append((ticker, start))
            return [r for r in tiingo.get(ticker, [("2026-09-21", 1.0, 1.0, 1.0), ("2026-09-22", 1.0, 1.0, 1.0),
                                                   ("2026-09-23", 1.0, 1.0, 1.0)]) if r[0] >= start]
        at = lambda d: datetime(2026, 9, d, 21, 30, tzinfo=timezone.utc)
        store = prices.update(["AAA"], stored={}, key="k", fetch=fetch, now=at(22), cash=None, fx=None)
        # a 2% dividend goes ex on the 23rd, then a 2-for-1 split on the 24th: Tiingo restates the past
        tiingo["AAA"] = [("2026-09-21", 100.0, 49.0, 1.0), ("2026-09-22", 100.0, 49.0, 1.0),
                         ("2026-09-23", 98.0, 49.0, 1.0), ("2026-09-24", 49.0, 49.0, 2.0)]
        asked.clear()
        store = prices.update(["AAA"], stored=store, key="k", fetch=fetch, now=at(24), cash=None, fx=None)
        self.assertIn(("AAA", "2026-09-22"), asked)                             # the last stored day again
        adjusted = prices.series(store, "AAA")
        self.assertEqual(adjusted, {"2026-09-21": 49.0, "2026-09-22": 49.0, "2026-09-23": 49.0, "2026-09-24": 49.0})
        self.assertEqual(prices.series(store, "AAA", "c")["2026-09-21"], 100.0)   # the printed close is kept
        self.assertEqual(prices.splits(store, "AAA"), [("2026-09-24", 2.0)])
        self.assertEqual(prices.split_factor(store, "AAA", "2026-09-21", "2026-09-24"), 2.0)

    def test_a_history_stored_before_is_fetched_whole_once_and_a_traded_share_from_its_first_trade(self):
        asked = []

        def fetch(ticker, start, key):
            asked.append((ticker, start))
            return [("2026-09-24", 10.0, 10.0, 1.0)]
        now = datetime(2026, 9, 24, 21, 30, tzinfo=timezone.utc)
        before = {"SPY": {"2026-09-24": {"c": 10.0, "a": 10.0}}, "AAA": {"2026-09-24": {"c": 5.0, "a": 5.0}},
                  prices.META_STARTS: {"SPY": "1991-01-01", "AAA": "1991-01-01"}}     # from before 27 Sep 2026
        store = prices.update(["AAA"], stored=before, key="k", fetch=fetch, now=now, cash=None, fx=None,
                              traded={"OLD": "2024-03-01", "AAA": "2025-01-01"})
        self.assertEqual([t for t, _ in asked], ["SPY", "AAA", "OLD"])            # each once, whole
        self.assertEqual(dict(asked)["OLD"], "2024-03-01")                        # from its first trade
        self.assertEqual(set(store[prices.META_WHOLE]), {"SPY", "AAA", "OLD"})
        asked.clear()
        prices.update(["AAA"], stored=store, key="k", fetch=fetch, now=now, cash=None, fx=None,
                      traded={"OLD": "2024-03-01", "AAA": "2025-01-01"})
        self.assertEqual(asked, [])                                               # then only as needed
        self.assertIn("traded=self.traded_us_shares(book)", inspect.getsource(server.Handler.update_research))

    def test_the_cash_rate_is_fetched_once_a_day(self):
        calls = []

        def cash():
            calls.append(1)
            return {"2026-09-24": 4.0}
        fetch = lambda ticker, start, key: []
        store = prices.update(["ZZZ"], stored={}, key="k", fetch=fetch, today=self.TODAY, cash=cash)
        store = prices.update(["ZZZ"], stored=store, key="k", fetch=fetch, today=self.TODAY, cash=cash)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(prices.CASH_FETCHED, prices.tickers(store))
        prices.update(["ZZZ"], stored=store, key="k", fetch=fetch, today=date(2026, 9, 26), cash=cash)
        self.assertEqual(len(calls), 2)

        def unreachable():
            raise prices.PriceError("Can't reach FRED")
        kept = prices.update(["ZZZ"], stored={prices.CASH_KEY: {"2026-09-23": 4.1}}, key="k", fetch=fetch,
                             today=self.TODAY, cash=unreachable)
        self.assertNotIn(prices.CASH_FETCHED, kept)                 # a failure is tried again

    def test_analyst_ratings_are_fetched_once_a_day(self):
        asked = []

        def fetch(path, key):
            asked.append(path)
            return [{"period": "2026-09-01", "buy": 3, "hold": 1}]
        stored = {"companies": {"KO": {"ticker": "KO", "verdict": "Buy"}}, "updated_at": "2026-09-25T06:00:00+00:00"}
        out = analysts.update(["KO", "AMD"], key="k", fetch=fetch, stored=stored, today=self.TODAY)
        self.assertEqual(asked, ["stock/recommendation?symbol=AMD"])  # a newly followed company is fetched
        self.assertIs(out["companies"]["KO"], stored["companies"]["KO"])
        analysts.update(["KO"], key="k", fetch=fetch, stored=stored, today=date(2026, 9, 26))
        self.assertEqual(asked[-1], "stock/recommendation?symbol=KO")

    def test_earnings_are_fetched_once_a_day_unless_results_are_due(self):
        asked = []

        def fetch(path, key):
            asked.append(path.split("symbol=")[1])
            return [] if path.startswith("stock/") else {"earningsCalendar": []}
        stored = {"updated_at": "2026-09-25T06:00:00+00:00", "companies": {
            "KO": {"ticker": "KO", "history": [], "next": {"date": "2026-10-21"}},
            "AMD": {"ticker": "AMD", "history": [], "next": {"date": "2026-09-25"}}}}   # due today
        out = earnings.update(["KO", "AMD"], key="k", fetch=fetch, stored=stored, today=self.TODAY)
        self.assertEqual(set(asked), {"AMD"})
        self.assertIs(out["companies"]["KO"], stored["companies"]["KO"])
        asked.clear()
        earnings.update(["KO"], key="k", fetch=fetch, stored=stored, today=date(2026, 9, 26))
        self.assertEqual(set(asked), {"KO"})

    def test_trading_212_reads_arrive_compressed(self):
        import gzip
        seen = {}

        def opener(req, timeout):
            seen["asked"] = req.headers.get("Accept-encoding")
            r = FakeResponse({}, headers={"Content-Encoding": "gzip"})
            r.read = lambda: gzip.compress(json.dumps({"currency": "EUR"}).encode())
            return r
        c = t212.Client("k", "s", "demo", opener=opener, sleep=lambda s: None)
        self.assertEqual(c.get("/equity/account/summary"), {"currency": "EUR"})
        self.assertEqual(seen["asked"], "gzip")

    def test_a_dead_connection_is_named_after_three_tries(self):
        tries = []

        def opener(req, timeout):
            tries.append(1)
            raise urllib.error.URLError("timed out")
        with self.assertRaises(t212.T212Error) as cm:
            t212.Client("k", "s", "demo", opener=opener, sleep=lambda s: None).get("/equity/positions")
        self.assertEqual(len(tries), 3)
        self.assertIn("check your connection", str(cm.exception))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        raw = generate_demo_data.generate(TODAY)
        with open(os.path.join(cls.tmp, "t212_data.json"), "w") as f:
            json.dump(raw, f)
        build_desk.main([cls.tmp])
        cls.oid = str(raw["orders"][0]["order"]["id"])
        server.Handler.folder, server.Handler.demo = cls.tmp, True
        server.PORT = 0
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = cls.httpd.server_address[1]
        server.ALLOWED_HOSTS.add(f"127.0.0.1:{port}")
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, body=None, headers=None):
        r = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers=dict({"Content-Type": "application/json"}, **(headers or {})),
                                   method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_serves_page_and_data(self):
        code, body = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Trading Desk", body)
        code, body = self.req("/data")
        self.assertEqual(json.loads(body)["positions"]["count"] > 0, True)

    def test_note_round_trip(self):
        code, _ = self.req("/journal", {"id": self.oid, "note": "Bought the dip"})
        self.assertEqual(code, 200)
        _, body = self.req("/data")
        row = next(r for r in json.loads(body)["trades"]["rows"] if r["id"] == self.oid)
        self.assertEqual(row["note"], "Bought the dip")
        self.req("/journal", {"id": self.oid, "note": ""})
        _, body = self.req("/data")
        row = next(r for r in json.loads(body)["trades"]["rows"] if r["id"] == self.oid)
        self.assertEqual(row["note"], "")

    def test_a_trade_can_carry_the_day_to_look_at_it_again(self):
        """The decision record: a note may name the day its trade is looked at again.
        Only a real YYYY-MM-DD day is kept; a date alone keeps the entry."""
        def row():
            _, body = self.req("/data")
            return next(r for r in json.loads(body)["trades"]["rows"] if r["id"] == self.oid)
        self.req("/journal", {"id": self.oid, "note": "Why I bought: cheap", "look_again": "2026-12-01"})
        self.assertEqual((row()["note"], row()["look_again"]), ("Why I bought: cheap", "2026-12-01"))
        for bad in ("2026-13-01", "next week", "2026-12-01T09:00:00", 20261201):
            self.req("/journal", {"id": self.oid, "note": "n", "look_again": bad})
            self.assertIsNone(row()["look_again"], bad)
        self.req("/journal", {"id": self.oid, "note": "", "look_again": "2026-12-01"})
        self.assertEqual((row()["note"], row()["look_again"]), ("", "2026-12-01"))
        self.req("/journal", {"id": self.oid, "note": ""})
        self.assertEqual((row()["note"], row()["look_again"]), ("", None))

    def test_a_company_followed_is_loaded_beside_the_others_never_over_them(self):
        """The one-company load merges into each store: the other companies' data and the
        stores' own fetch times stay, so the next refresh still fetches what is due."""
        folder = tempfile.mkdtemp()
        dump = lambda name, data: json.dump(data, open(os.path.join(folder, name), "w"))
        dump("t212_data.json", generate_demo_data.generate(TODAY))
        dump("watchlist.json", {"tickers": ["KO", "AMD"], "coverage": {"KO": {"followed_at": "2026-09-01"},
                                                                         "AMD": {"followed_at": "2026-09-26"}}})
        dump("news_data.json", {"tickers": ["KO"], "companies": {"KO": "COCA COLA"}, "unknown": ["AMD"],
                                "insiders": {"x": 1}, "synced_at": "2026-09-25T08:00:00+00:00",
                                "items": [{"ticker": "KO", "filed_at": "2026-09-20T10:00:00Z", "form": "8-K"}]})
        dump("fundamentals.json", {"companies": {"KO": {"kept": True}}, "unknown": ["AMD"], "updated_at": "2026-09-20T00:00:00+00:00"})
        dump("earnings_data.json", {"companies": {"KO": {"kept": True}}, "updated_at": "2026-09-20T00:00:00+00:00"})
        dump("analysts_data.json", {"companies": {"KO": {"kept": True}}, "updated_at": "2026-09-20T00:00:00+00:00"})
        dump("quotes.json", {"quotes": {"KO": {"price": 1.0}}, "fetched_at": "2026-09-25T08:00:00+00:00"})
        ko_story = {"id": "1", "headline": "Coca-Cola story", "source": "Wire", "url": "https://example.com/ko",
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        dump("headlines.json", {"companies": {"KO": [ko_story]}, "fetched": {"KO": "2026-09-25"}})
        asked = []
        fakes = {
            (earnings, "api_key"): lambda: "k",
            (headlines, "fetch_company"): lambda ticker, since, until, key, fetch=None: asked.append(("news", ticker)) or [
                dict(ko_story, id="2", headline="AMD story", url="https://example.com/amd")],
            (headlines, "fetch_press"): lambda ticker, filed, days, fetch=None, sleep=None: asked.append(
                ("press", ticker, filed, days)) or [dict(ko_story, id="3", headline="Advanced Micro Devices in the FT",
                                                         source="Financial Times", url="https://example.com/ft",
                                                         at=(datetime.now(timezone.utc) - timedelta(hours=1))
                                                         .isoformat(timespec="seconds"))],
            (news, "refresh"): lambda tickers, insiders=None, **k: asked.append(("filings", tickers)) or {
                "items": [{"ticker": "AMD", "filed_at": "2026-09-24T10:00:00Z", "form": "10-Q"}],
                "companies": {"AMD": "ADVANCED MICRO"}, "unknown": [], "insiders": dict(insiders or {}, y=2)},
            (diffs, "update"): lambda tickers, items, ua, fetch, stored=None, prune=True: asked.append(
                ("wording", tickers, prune)) or stored,
            (news, "user_agent"): lambda: "ua",
            (prices, "update"): lambda tickers, stored=None, cash=None, fx=None, **k: asked.append(
                ("prices", tickers, cash, fx)) or {"AMD": {}},
            (prices, "load"): lambda path=None: {},
            (prices, "fetch_latest"): lambda tickers: {"quotes": {"AMD": {"price": 2.0}}, "fetched_at": "now"},
            (fundamentals, "update"): lambda tickers, stored=None, filings=None: {
                "companies": {"AMD": {"new": True}}, "unknown": [], "updated_at": "now"},
            (earnings, "update"): lambda tickers, stored=None: {"companies": {"AMD": {"new": True}}, "updated_at": "now"},
            (analysts, "update"): lambda tickers, stored=None: {"companies": {"AMD": {"new": True}}, "updated_at": "now"},
            (rating, "log"): lambda entries, ratings, tickers, prices_, today, **k: asked.append(("rating", tickers)) or [],
        }
        real = {key: getattr(*key) for key in fakes}
        handler = server.Handler.__new__(server.Handler)
        handler.folder, handler.demo = folder, False
        try:
            for (module, name), fake in fakes.items():
                setattr(module, name, fake)
            events = []
            code, result = handler.fetch_company("amd", events.append)
        finally:
            for (module, name), fn in real.items():
                setattr(module, name, fn)
        load = lambda name: json.load(open(os.path.join(folder, name)))
        self.assertEqual((code, result["ok"], result["message"]), (200, True, None))
        stored = load("news_data.json")
        self.assertEqual([i["ticker"] for i in stored["items"]], ["AMD", "KO"])       # newest first, KO kept
        self.assertEqual((stored["unknown"], stored["insiders"], stored["synced_at"]),
                         ([], {"x": 1, "y": 2}, "2026-09-25T08:00:00+00:00"))
        self.assertEqual(stored["tickers"], ["KO", "AMD"])
        for name in ("fundamentals.json", "earnings_data.json", "analysts_data.json"):
            store = load(name)
            self.assertEqual(store["companies"], {"KO": {"kept": True}, "AMD": {"new": True}}, name)
            self.assertEqual(store["updated_at"], "2026-09-20T00:00:00+00:00", name)   # KO still due
        self.assertEqual(load("fundamentals.json")["unknown"], [])
        self.assertEqual(load("quotes.json"), {"quotes": {"KO": {"price": 1.0}, "AMD": {"price": 2.0}},
                                               "fetched_at": "2026-09-25T08:00:00+00:00"})
        self.assertIn(("wording", ["AMD"], False), asked)                               # nothing pruned
        self.assertIn(("prices", ["AMD"], None, None), asked)                           # no FRED for one company
        self.assertIn(("rating", ["AMD"]), asked)
        self.assertIn(("news", "AMD"), asked)
        self.assertIn(("press", "AMD", "ADVANCED MICRO", headlines.KEEP_DAYS), asked)   # by its filed name, a month
        stories = load("headlines.json")
        self.assertEqual({t: [i["headline"] for i in items] for t, items in stories["companies"].items()},
                         {"KO": ["Coca-Cola story"],                                     # KO's kept
                          "AMD": ["AMD story", "Advanced Micro Devices in the FT"]})
        self.assertEqual(stories["fetched"]["finnhub"]["KO"], "2026-09-25")             # KO's own fetch day stands
        self.assertIn("AMD", stories["fetched"]["press"])
        ran = [e["step"] for e in events if e.get("state") == "running"]
        self.assertEqual(sorted(ran), sorted(["Financials", "Filings", "Annual report wording", "Prices", "Latest price",
                                              "News", "Earnings", "Analyst ratings", "News from the FT and the press",
                                              "Its figures on the page", "Rating"]))
        # 28 Sep 2026: the page is rebuilt once its figures and price are in, before its news
        ended = [e["step"] for e in events if e.get("state") == "done"]
        shown = events.index({"built": True})
        for first in ("Financials", "Prices", "Latest price"):
            self.assertLess(events.index({"step": first, "state": "done", "seconds": next(
                e["seconds"] for e in events if e.get("step") == first and e.get("state") == "done")}), shown, first)
        self.assertEqual(len(ended), len(ran))
        self.assertTrue(os.path.exists(os.path.join(folder, "index.html")))              # the page rebuilt
        self.assertEqual(handler.fetch_company("XOM")[1]["ok"], False)                  # only one followed
        source = inspect.getsource(server.Handler.do_POST)
        fetch = source[source.index('"/fetch"'):source.index('"/journal"')]
        self.assertNotIn("market_lock", fetch)              # never waits for the company update

    def test_a_plan_is_written_once_through_the_endpoint(self):
        path = os.path.join(self.tmp, "plans.json")
        try:
            day = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
            code, body = self.req("/plan", {"ticker": "amd", "side": "buy", "why": "results beat", "wrong_if": "margins fall",
                                            "review_by": day})
            result = json.loads(body)
            self.assertTrue(result["ok"], result)
            self.assertEqual([(r["ticker"], r["side"], r["state"]) for r in result["plans"]["rows"]],
                             [("AMD", "BUY", "waiting")])
            code, body = self.req("/plan", {"ticker": "AMD", "side": "BUY", "why": "x", "wrong_if": "y", "review_by": day})
            self.assertIn("why", json.loads(body)["message"])
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_the_macs_tailscale_name_opens_the_desk_but_never_takes_an_order(self):
        """One desk (docs/ONE-DESK.md): the user's phone opens the Mac's desk through
        `tailscale serve`, under the name set in .env. Orders stay on the Mac."""
        name = "my-mac.tail1234.ts.net"
        real = server.Handler.remote_hosts
        try:
            code, _ = self.req("/", headers={"Host": name})
            self.assertEqual(code, 403)                                     # not opted in: refused
            server.Handler.remote_hosts = frozenset({name})
            code, body = self.req("/", headers={"Host": name})
            self.assertEqual(code, 200)
            there = {"Host": name, "Origin": "https://" + name}
            code, body = self.req("/journal", {"id": self.oid, "note": ""}, there)
            self.assertEqual(code, 200)
            code, _ = self.req("/journal", {"id": self.oid, "note": ""}, {"Host": name, "Origin": "https://evil.example"})
            self.assertEqual(code, 403)
        finally:
            server.Handler.remote_hosts = real
        self.assertIn("Handler.remote_hosts = desk_hosts()", inspect.getsource(server.main))

    def test_only_a_tailscale_machine_name_is_taken_from_the_settings(self):
        self.assertEqual(server.desk_hosts({"DESK_HOSTS": " My-Mac.tail1234.ts.net , evil.com, ts.net, *.ts.net,"
                                                          "a.ts.net.evil.com, http://b.ts.net, c.tail9.ts.net"}),
                         {"my-mac.tail1234.ts.net", "c.tail9.ts.net"})
        self.assertEqual(server.desk_hosts({}), frozenset())
        self.assertIn("DESK_HOSTS=", read(os.path.join(ROOT, ".env.example")))
        rows = dict(doctor.keys({"DESK_HOSTS": "evil.com"}))
        self.assertIn("ignored", rows["Phone through Tailscale"])
        self.assertEqual(dict(doctor.keys({"DESK_HOSTS": "a.b.ts.net"}))["Phone through Tailscale"], "set")

    def test_other_websites_are_refused(self):
        code, _ = self.req("/journal", {"id": self.oid, "note": "x"}, {"Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        code, _ = self.req("/refresh", {}, {"Host": "evil.example"})
        self.assertEqual(code, 403)

    def test_a_malformed_request_is_answered_not_dropped(self):
        """28 Sep 2026: a body that was JSON but not an object, or a Content-Length that was not
        a number, ended the handler with no answer at all."""
        for body, length, code in ((b"[]", "2", 400), (b'"x"', "3", 400), (b"{}", "abc", 400), (b"{}", "-5", 400)):
            s = socket.create_connection(("127.0.0.1", int(self.base.rsplit(":", 1)[1])), timeout=5)
            host = self.base.split("//", 1)[1]
            s.sendall(f"POST /journal HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
                      f"Content-Length: {length}\r\n\r\n".encode() + body)
            answer = s.recv(4000)
            s.close()
            self.assertTrue(answer.startswith(f"HTTP/1.0 {code}".encode()), (body, length, answer[:60]))

    def test_watchlist_round_trip(self):
        """Phase 6: follow (a ticker alone since 26 Sep 2026; no reason since 27 Sep) and
        unfollow; the list is the served folder's own, so the demo never edits the real one.
        A company followed is then loaded through /fetch, answered as it goes."""
        code, body = self.req("/watchlist", {"follow": "amd"})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])
        code, body = self.req("/watchlist", {"follow": "nvda", "why": "sent by an older page"})
        self.assertTrue(json.loads(body)["ok"])
        self.assertIn("NVDA", json.loads(body)["news"]["tickers"])
        stored = news.load_coverage(os.path.join(self.tmp, "watchlist.json"))
        self.assertNotIn("why", stored["coverage"]["NVDA"])                  # nothing kept
        self.assertNotIn("why", stored["coverage"]["AMD"])
        code, body = self.req("/fetch", {"ticker": "amd"})
        lines = [json.loads(l) for l in body.decode().splitlines() if l.strip()]
        self.assertEqual(lines[-1], {"ok": True, "message": "The demo account loads nothing new."})
        code, body = self.req("/fetch", {"ticker": "XOM"})
        self.assertFalse([json.loads(l) for l in body.decode().splitlines() if l.strip()][-1]["ok"])
        self.req("/watchlist", {"unfollow": "AMD"})
        code, body = self.req("/watchlist", {"unfollow": "NVDA"})
        self.assertNotIn("NVDA", json.loads(body)["news"]["tickers"])
        code, _ = self.req("/watchlist", {"tickers": ["oops"]})
        self.assertEqual(code, 400)

    def test_a_thesis_round_trip_is_written_once_for_a_covered_company(self):
        where = os.path.join(self.tmp, "watchlist.json")
        funds_path = os.path.join(self.tmp, "fundamentals.json")
        theses_path = os.path.join(self.tmp, "theses.json")
        kept_funds = build_desk.load_json(funds_path, None)
        try:
            write_json(funds_path, {"companies": {"AMD": {"quarters": [
                {"end": "2026-06-27", "revenue": 130.0, "operating_income": 16.0, "filed": "2026-08-04"}]}}})
            self.req("/watchlist", {"follow": "AMD"})
            claim = {"ticker": "amd", "revenue_direction": "up", "margin_direction": "down",
                     "reason": "test", "confidence_pct": 60}
            code, body = self.req("/thesis", dict(claim, ticker="ZZZZ"))
            self.assertEqual(code, 400)
            code, body = self.req("/thesis", claim)
            self.assertTrue(json.loads(body)["ok"], body)
            self.assertEqual(json.loads(body)["theses"]["companies"]["AMD"]["pending"]["confidence"], 0.6)
            code, body = self.req("/thesis", dict(claim, reason="again"))
            self.assertIn("written once", json.loads(body)["message"])
        finally:
            self.req("/watchlist", {"unfollow": "AMD"})
            for path in (theses_path,):
                if os.path.exists(path):
                    os.remove(path)
            if kept_funds is None:
                os.remove(funds_path)
            else:
                write_json(funds_path, kept_funds)

    def test_a_folder_without_its_own_list_keeps_the_tickers_it_already_follows(self):
        where = os.path.join(self.tmp, "watchlist.json")
        news_path = os.path.join(self.tmp, "news_data.json")
        kept = build_desk.load_json(news_path, {})
        try:
            if os.path.exists(where):
                os.remove(where)
            write_json(news_path, {"tickers": ["AMD", "KO"], "items": []})
            code, body = self.req("/watchlist", {"follow": "NVDA"})
            self.assertEqual(json.loads(body)["news"]["tickers"], ["AMD", "KO", "NVDA"])
        finally:
            write_json(news_path, kept)
            if os.path.exists(where):
                os.remove(where)
        code, _ = self.req("/watchlist", {"follow": "A", "unfollow": "B"})
        self.assertEqual(code, 400)

    def test_the_demo_never_writes_the_desks_summaries(self):
        """The summaries were a module path, so a summary asked for in the demo was saved as
        the desk's own, beside real figures."""
        # a summary is kept in the served folder's own store, never the desk's
        real = summarise.SUMMARY_FILE
        summarise.SUMMARY_FILE = os.path.join(tempfile.mkdtemp(), "summaries.json")
        written = {"text": "t", "model": "m", "written_at": "2026-09-28T00:00:00+00:00"}
        real_write, summarise.write_summary = summarise.write_summary, lambda card: written
        built = os.path.join(self.tmp, "desk_data.json")
        page = json.load(open(built))
        ticker = "ZZZ"
        with open(built, "w") as f:
            json.dump(dict(page, companies=[{"ticker": ticker, "name": "Zed"}]), f)
        try:
            code, body = self.req("/summary", {"ticker": ticker})
            self.assertTrue(json.loads(body)["ok"], body)
            self.assertEqual(summarise.load(os.path.join(self.tmp, "summaries.json"))[ticker], written)
            self.assertFalse(os.path.exists(summarise.SUMMARY_FILE))
        finally:
            summarise.SUMMARY_FILE, summarise.write_summary = real, real_write
            with open(built, "w") as f:
                json.dump(page, f)

    def test_demo_refresh_rebuilds_without_network(self):
        code, body = self.req("/refresh", {})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body.splitlines()[-1])["ok"])

    # ---- a refresh answers as it goes (a slow connection made one long silent wait) ----
    def handler(self):
        h = object.__new__(server.Handler)
        h.folder, h.demo = self.tmp, False
        return h

    def test_a_refresh_answers_in_lines_with_the_result_last(self):
        r = urllib.request.Request(self.base + "/refresh", data=b"{}", method="POST",
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            self.assertEqual(resp.headers["Content-Type"], "application/x-ndjson")
            lines = [json.loads(x) for x in resp.read().decode().splitlines() if x.strip()]
        self.assertEqual(lines[-1]["ok"], True)

    def test_the_account_sync_is_trading_212_alone_and_reaches_the_page_first(self):
        """The desk depends on the broker only for the account. Its sync is the broker's, the
        page rebuilt at once; no company source runs in it."""
        h, events = self.handler(), []
        h.sync_account = lambda: (events.append("synced"), (None, None))[1]
        h.instrument_codes = lambda: (events.append("codes"), (None, None))[1]
        h.settle_unknown_orders = lambda: events.append("orders")
        h.update_research = lambda report, timed: self.fail("a company source ran in the account sync")
        code, result = h.refresh_account(events.append)
        plain = [{k: v for k, v in e.items() if k != "seconds"} if isinstance(e, dict) else e for e in events]
        self.assertEqual(plain, [{"step": "Trading 212", "state": "running"}, "synced",
                                 {"step": "Trading 212", "state": "done"}, {"built": True}])
        self.assertTrue(result["ok"])
        self.assertTrue(result["timing"].startswith("Took "))

    def test_a_trading_212_failure_stops_the_account_sync_and_says_why(self):
        h, events = self.handler(), []

        def sync():
            raise t212.T212Error("Can't reach Trading 212 (timed out); check your connection and try again")
        h.sync_account = sync
        h.instrument_codes = lambda: self.fail("asked Trading 212 again after it failed")
        code, result = h.refresh_account(events.append)
        self.assertEqual(result, {"ok": False, "message": "Can't reach Trading 212 (timed out); check your "
                                                          "connection and try again"})
        self.assertNotIn({"built": True}, events)
        self.assertEqual(events[-1]["state"], "failed")

    def test_the_company_data_updates_without_trading_212(self):
        """Filings, prices, financials, results, ratings and research: none of it reaches
        the broker, so none of it waits for the broker. The server's market path names no
        broker call, and no module on it imports a broker's client."""
        h, events = self.handler(), []
        h.sync_account = lambda: self.fail("the company update synced the account")
        h.update_research = lambda report, timed: (events.append("sources"), timed.append(("Prices", 21.0)), [])[2]
        code, result = h.refresh_market(events.append)
        self.assertEqual(events, ["sources"])
        self.assertEqual((code, result["ok"], result["message"]), (200, True, None))
        self.assertTrue(result["timing"].startswith("Took 21 s; longest: Prices 21 s"))
        for method in (server.Handler.refresh_market, server.Handler.update_research, server.Handler.fetch_company):
            source = inspect.getsource(method)
            self.assertIsNone(re.search(r"\b(t212|broker\w*)\.\w", source), method.__name__)
            for account in ("sync_account", "sync_other"):
                self.assertNotIn(account, source, method.__name__)
        for name in ("news", "headlines", "diffs", "prices", "fundamentals", "earnings", "analysts", "universe",
                     "rating", "research", "sectors", "screen", "value", "uncertainty"):
            with open(os.path.join(ROOT, name + ".py")) as f:
                text = f.read()
            self.assertIsNone(re.search(r"^\s*(import|from)\s+[^\n]*\b(t212|broker\w*)\b", text, re.M), name)

    def test_a_refresh_names_its_part_and_one_of_each_runs_at_once(self):
        code, body = self.req("/refresh", {"part": "market"})           # the demo: a rebuild only
        self.assertEqual((code, json.loads(body.splitlines()[-1])["ok"]), (200, True))
        for part, lock in (("account", server.account_lock), ("market", server.market_lock)):
            with lock:
                code, body = self.req("/refresh", {"part": part})
            self.assertEqual((code, json.loads(body)["busy"]), (409, True), part)
        with server.market_lock:                                      # the other part is not held up
            code, body = self.req("/refresh", {"part": "account"})
        self.assertEqual(code, 200)
        code, body = self.req("/refresh", {"part": "everything"})      # an unknown part: the account
        self.assertEqual(code, 200)

    def test_a_company_followed_during_the_company_update_loads_at_once_and_neither_loses_the_others(self):
        """26 Sep: refused while the update ran, a company followed stayed empty. 28 Sep: made to
        wait for the whole update, it took minutes on a slow connection. Now it loads at once, and the update, writing a store from what
        it read before, makes the follow's change again on it, even where it pruned the company."""
        path = os.path.join(tempfile.mkdtemp(), "headlines.json")
        json.dump({"companies": {"KO": ["old"]}, "fetched": {"finnhub": {"KO": "2026-09-20"}}}, open(path, "w"))
        began = server.STORES.begin()
        try:
            read = json.load(open(path))                                       # the update reads the store...
            fresh = {"companies": {"AMD": ["amd story"]}, "fetched": {"finnhub": {"AMD": "2026-09-28"}}}
            server.STORES.write(path, server.Merge(lambda stored: headlines.merge_company(stored, fresh, "AMD")))
            self.assertEqual(sorted(json.load(open(path))["companies"]), ["AMD", "KO"])    # ...AMD is in at once
            read["companies"]["KO"] = ["new"]                                  # ...and writes what it made of it,
            written = server.STORES.write(path, read, since=began)             # AMD pruned as not covered then
        finally:
            server.STORES.end(began)
        self.assertEqual(written["companies"], {"KO": ["new"], "AMD": ["amd story"]})
        self.assertEqual(written["fetched"]["finnhub"], {"KO": "2026-09-20", "AMD": "2026-09-28"})
        self.assertEqual(json.load(open(path)), written)
        self.assertEqual(server.STORES._changes, [])                          # nothing kept once the update ends
        # a whole store written with no update under way is written as it is
        self.assertEqual(server.STORES.write(path, {"companies": {}}), {"companies": {}})
        # the endpoint: answered while the company update holds its lock (it waited 15 minutes before)
        with server.market_lock:
            code, body = self.req("/fetch", {"ticker": "KO"})
        self.assertEqual(code, 200)
        self.assertIn(b'"ok"', body.splitlines()[-1])

    def test_steps_in_lanes_run_side_by_side_each_after_what_it_reads(self):
        h, events, timed, seen = self.handler(), [], [], []
        other = threading.Event()

        def waits():                            # would wait for ever in one lane: the other sets it
            seen.append(other.wait(5))
            return None, None

        def sets():
            other.set()
            return None, None

        def after():
            seen.append("after")
            return None, None

        def broken():
            raise prices.PriceError("Tiingo is down")
        failed = h.run_steps((("A", waits, "one", ()), ("B", sets, "two", ()), ("C", broken, "two", ()),
                              ("D", after, "three", ("A", "C"))), events.append, timed)
        self.assertEqual(seen, [True, "after"])                                 # side by side; D after A and C
        self.assertEqual(failed, [("C", "Tiingo is down")])
        self.assertEqual([name for name, _ in timed], ["A", "B", "C", "D"])     # in the list's order, however run
        with self.assertRaises(ValueError):                                     # a step waits only on one before it
            h.run_steps((("A", sets, "one", ("B",)), ("B", sets, "two", ())), events.append, [])

    def test_a_company_put_into_a_store_twice_is_put_in_once(self):
        """A follow's change is made again by an update under way (Stores), so each must be one
        that can be made twice: a company's entries put in, the others left, a request counted once."""
        stored = {"KO": {"2026-09-25": {"c": 60.0}}, "_asked": ["2026-09-28T09:00:00+00:00"],
                  "_whole": {"KO": "2026-09-01"}, "_starts": {"KO": "2016-09-01"}, "updated_at": "then"}
        fresh = dict(stored, AMD={"2026-09-25": {"c": 150.0}}, _whole={"KO": "2026-09-01", "AMD": "2026-09-28"},
                     _starts={"KO": "2016-09-01", "AMD": "2016-09-28"},
                     _asked=["2026-09-28T09:00:00+00:00", "2026-09-28T10:00:00+00:00"])
        once = prices.merge_ticker(stored, fresh, "amd")
        self.assertEqual(prices.merge_ticker(once, fresh, "AMD"), once)
        self.assertEqual(once["_asked"], ["2026-09-28T09:00:00+00:00", "2026-09-28T10:00:00+00:00"])
        self.assertEqual((once["KO"], once["AMD"], once["_whole"]["AMD"], once["updated_at"]),
                         (stored["KO"], fresh["AMD"], "2026-09-28", "then"))
        # an update since has counted a request of its own: both are kept
        later = dict(stored, _asked=stored["_asked"] + ["2026-09-28T10:30:00+00:00"])
        self.assertEqual(len(prices.merge_ticker(later, fresh, "AMD")["_asked"]), 3)
        news_store = {"companies": {"KO": ["k"]}, "fetched": {"KO": "2026-09-25"}}           # the old flat map
        story = {"companies": {"AMD": ["a"], "KO": ["stale"]}, "fetched": {"finnhub": {"AMD": "2026-09-28"},
                                                                          "press": {"AMD": "2026-09-28"}}}
        once = headlines.merge_company(news_store, story, "AMD")
        self.assertEqual(headlines.merge_company(once, story, "AMD"), once)
        self.assertEqual(once["companies"], {"KO": ["k"], "AMD": ["a"]})
        self.assertEqual(once["fetched"], {"finnhub": {"KO": "2026-09-25", "AMD": "2026-09-28"},
                                           "press": {"AMD": "2026-09-28"}})
        once = diffs.merge_company({"companies": {"KO": 1}}, {"companies": {"AMD": 2, "KO": 0}}, "AMD")
        self.assertEqual((once, diffs.merge_company(once, {"companies": {"AMD": 2}}, "AMD")),
                         ({"companies": {"KO": 1, "AMD": 2}},) * 2)

    def test_every_source_is_asked_for_a_packed_answer(self):
        """28 Sep 2026: on a slow connection a ten-year price history, a company's filed facts or an annual
        report is most of what following a company waits for; packed, a tenth of the size."""
        import gzip
        for fn in (prices._tiingo, earnings.fetch, news.fetch_json, news.fetch_text, universe._request, t212.Client.get):
            self.assertIn('"Accept-Encoding": "gzip"', inspect.getsource(fn), fn.__name__)
            self.assertIn("unpacked(", inspect.getsource(fn), fn.__name__)
        packed = io.BytesIO()
        packed.headers = {"Content-Encoding": "gzip"}
        self.assertEqual(env_config.unpacked(gzip.compress(b'{"a": 1}'), packed), b'{"a": 1}')
        self.assertEqual(env_config.unpacked(b'{"a": 1}', io.BytesIO()), b'{"a": 1}')    # sent plain: as it came
        rows = [{"date": "2026-09-25T00:00:00.000Z", "close": 10.0, "adjClose": 10.0}]

        def opener(req, timeout=None):
            self.assertEqual(req.get_header("Accept-encoding"), "gzip")
            r = io.BytesIO(gzip.compress(json.dumps(rows).encode()))
            r.headers = {"Content-Encoding": "gzip"}
            r.__enter__, r.__exit__ = (lambda: r), (lambda *a: None)
            return r
        self.assertEqual(prices._tiingo("https://api.tiingo.com/x", "k", opener=opener), rows)

    def test_a_failed_source_is_named_and_the_rest_still_run(self):
        h, events, timed = self.handler(), [], []

        def down():
            raise news.NewsError("Can't reach the SEC (timed out)")
        failed = h.run_steps([("Filings", down), ("Prices", lambda: ({"a": 1}, "prices_test.json"))],
                             events.append, timed)
        self.assertEqual(failed, [("Filings", "Can't reach the SEC (timed out)")])
        self.assertEqual([(e["step"], e["state"]) for e in events],
                         [("Filings", "running"), ("Filings", "failed"), ("Prices", "running"), ("Prices", "done")])
        self.assertEqual([name for name, _ in timed], ["Filings", "Prices"])
        self.assertEqual(json.loads(read(os.path.join(self.tmp, "prices_test.json"))), {"a": 1})

    def test_a_long_step_keeps_the_connection_awake(self):
        """A blank line every HEARTBEAT seconds, so neither the web view, the browser nor
        a slow network takes a silent minute for a dead connection."""
        h, out = self.handler(), io.BytesIO()
        h.wfile, h.send_response, h.send_header, h.end_headers = out, lambda c: None, lambda *a: None, lambda: None
        real, server.HEARTBEAT = server.HEARTBEAT, 0.02
        try:
            import time
            h._stream(lambda report: (report({"step": "Research", "state": "running"}), time.sleep(0.2),
                                      (200, {"ok": True}))[2])
        finally:
            server.HEARTBEAT = real
        lines = out.getvalue().decode().split("\n")
        self.assertEqual(json.loads(lines[0]), {"step": "Research", "state": "running"})
        self.assertGreaterEqual(lines.count(""), 3)                  # blank lines while it ran
        self.assertEqual(json.loads([x for x in lines if x][-1]), {"ok": True})

    def test_the_time_a_refresh_took_is_stated(self):
        self.assertEqual(server.timing([("Trading 212", 6.2), ("Prices", 21.4), ("Research", 0.1), ("Filings", 44.9)]),
                         "Took 1 min 13 s; longest: Filings 45 s, Prices 21 s, Trading 212 6 s.")
        self.assertIsNone(server.timing([]))

    def test_the_page_reads_the_refresh_as_it_goes(self):
        reader = template_function("readLines")
        self.assertIn("'ok' in ev", reader)
        self.assertIn("r.body.getReader()", reader)
        template = page_source()
        click = template[template.index("$('refreshBtn').addEventListener"):template.index("/* ---------------- boot")]
        self.assertIn("readLines(r,", click)
        self.assertIn("if (ev.built) built = reloadData()", click)
        self.assertIn("res.timing", click)
        # "not running" only when the server never answered, not when a long refresh dropped
        self.assertIn("!reached ? 'Desk server not running", click)
        self.assertNotIn("Failed to fetch", click)

class LaunchTests(unittest.TestCase):
    def test_every_launcher_keeps_the_update_line_it_logs(self):
        """28 Sep 2026: desk.sh started the server writing a fresh server.log, which erased
        the line update.sh had just written there; doctor.py reports it as the last update.
        The Mac app appended. Both append now."""
        desk = open(os.path.join(ROOT, "desk.sh")).read()
        app = open(os.path.join(ROOT, "native_app", "main.swift")).read()
        for source in (desk, app):
            self.assertIn("update.sh >> server.log", source)
            self.assertNotRegex(source, r"[^>]> server\.log")


class FailureWordsTests(unittest.TestCase):
    def test_steps_that_failed_for_one_reason_are_named_together(self):
        """28 Sep 2026: a desk with no SEC contact in .env said so five times, once for each
        step that asks the SEC, in a paragraph at the top of the page."""
        words = server.Handler.failures([("Filings", env_config.NO_SEC_CONTACT), ("News", "no key"),
                                         ("Industry codes", env_config.NO_SEC_CONTACT), ("Earnings", "no key"),
                                         ("Company universe", env_config.NO_SEC_CONTACT), ("Prices", "busy")])
        self.assertEqual(words, f"Filings, industry codes and company universe: {env_config.NO_SEC_CONTACT}; "
                                "News and earnings: no key; Prices: busy")
        self.assertIsNone(server.Handler.failures([]))
        for module in ("news.py", "sectors.py", "universe.py"):
            source = open(os.path.join(ROOT, module)).read()
            self.assertIn("NO_SEC_CONTACT", source, module)
            self.assertNotIn("requests to identify themselves\")", source, module)

    def test_a_key_not_added_yet_is_a_step_to_take_and_not_a_failure(self):
        """A desk that has not been given its free keys yet is waiting for them, not broken: the update
        says which to add, apart from what really failed, and the page shows the two differently."""
        handler = server.Handler.__new__(server.Handler)
        handler.folder, handler.demo = tempfile.mkdtemp(), False
        handler.build, handler.record_health = lambda: None, lambda *a: None
        problems = [("Filings", env_config.NO_SEC_CONTACT), ("Prices", env_config.NO_TIINGO_KEY),
                    ("Earnings", env_config.NO_FINNHUB_KEY), ("News", env_config.NO_FINNHUB_KEY),
                    ("Company universe", "The SEC is busy: try again later")]
        handler.update_research = lambda report, timed: problems
        code, out = handler.refresh_market()
        self.assertEqual(out["message"], "Company universe: The SEC is busy: try again later")
        self.assertEqual(out["setup"], [env_config.NO_SEC_CONTACT, env_config.NO_TIINGO_KEY, env_config.NO_FINNHUB_KEY])
        handler.update_research = lambda report, timed: problems[:4]
        code, out = handler.refresh_market()
        self.assertIsNone(out["message"])                                   # nothing failed: nothing red
        self.assertEqual(len(out["setup"]), 3)
        handler.update_research = lambda report, timed: []
        self.assertEqual(handler.refresh_market()[1]["setup"], [])
        for module, constant in (("prices.py", "NO_TIINGO_KEY"), ("earnings.py", "NO_FINNHUB_KEY"), ("news.py", "NO_SEC_CONTACT")):
            with open(os.path.join(ROOT, module)) as f:                      # one sentence, said where it is raised
                self.assertIn(constant, f.read(), module)
        self.assertEqual(set(env_config.SETUP_STEPS),
                         {env_config.NO_SEC_CONTACT, env_config.NO_TIINGO_KEY, env_config.NO_FINNHUB_KEY})
        app = page_source()
        self.assertIn("res.setup", app)
        self.assertIn("Company data is waiting for a few free keys", app)
        # and the Data sources row says the same: waiting for a key, not failed
        now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        stored = health.record({}, "market", [("Filings", 1.0), ("Prices", 1.0), ("Earnings", 1.0), ("News", 1.0)],
                               [("Filings", env_config.NO_SEC_CONTACT), ("Prices", env_config.NO_TIINGO_KEY),
                                ("News", "The SEC is busy")], now=now)
        (part,) = health.for_page(stored)
        self.assertEqual((part["failed"], part["waiting"]), (1, 2))
        self.assertEqual([s["name"] for s in part["steps"] if s.get("setup")], ["Filings", "Prices"])
        self.assertIn("waiting for a key", app)


class HealthCheckTests(unittest.TestCase):
    """What each data source did at the last update (health.py, the Overview's "Data
    sources" row), and python3 doctor.py: one report on the code, keys, sources, stores and
    ratings that holds nothing private and can be pasted into a chat."""
    NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

    def test_each_steps_last_outcome_is_kept_and_when_it_last_worked(self):
        first = health.record({}, "market", [("Filings", 2.04), ("Prices", 1.0)], [], now=self.NOW)
        later = self.NOW + timedelta(minutes=30)
        second = health.record(first, "market", [("Prices", 0.5)], [("Prices", "Tiingo's free daily limit is used up")],
                               now=later)
        steps = second["market"]["steps"]
        self.assertEqual(list(steps), ["Filings", "Prices"])                  # in the order they first ran
        self.assertEqual((steps["Prices"]["ok"], steps["Prices"]["why"], steps["Prices"]["last_ok"]),
                         (False, "Tiingo's free daily limit is used up", self.NOW.isoformat(timespec="seconds")))
        self.assertEqual((steps["Filings"]["ok"], steps["Filings"]["seconds"]), (True, 2.0))
        page = health.for_page(health.record(second, "account", [("Trading 212", 3.0)],
                                             [("Trading 212", "Can't reach Trading 212")], now=later))
        self.assertEqual([(p["label"], p["failed"]) for p in page], [("Company data", 1), ("Your account", 1)])
        self.assertIsNone(page[1]["steps"][0]["last_ok"])                      # never worked
        self.assertEqual(health.for_page({}), [])
        self.assertEqual(len(health.record({}, "market", [("X", 1)], [("X", "y" * 999)])["market"]["steps"]["X"]["why"]), 300)

    def test_both_refreshes_record_what_their_steps_did(self):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "t212_data.json"), "w") as f:
            json.dump(generate_demo_data.generate(TODAY), f)
        h = object.__new__(server.Handler)
        h.folder, h.demo = folder, False
        h.update_research = lambda report, timed: (timed.extend([("Filings", 1.0), ("Prices", 2.0)]),
                                                   [("Prices", "Tiingo's limit")])[1]
        code, result = h.refresh_market()
        self.assertEqual(result["message"], "Prices: Tiingo's limit")
        stored = health.load(folder)
        self.assertEqual({k: v["ok"] for k, v in stored["market"]["steps"].items()}, {"Filings": True, "Prices": False})

        def down():
            raise t212.T212Error("Can't reach Trading 212 (timed out)")
        h.sync_account = down
        h.refresh_account()
        self.assertEqual(health.load(folder)["account"]["steps"]["Trading 212"]["why"], "Can't reach Trading 212 (timed out)")
        page = json.load(open(os.path.join(folder, "desk_data.json")))
        self.assertEqual([p["part"] for p in page["health"]], ["market"])      # the account's failure rebuilt nothing
        demo = object.__new__(server.Handler)
        demo.folder, demo.demo = tempfile.mkdtemp(), True
        with open(os.path.join(demo.folder, "t212_data.json"), "w") as f:
            json.dump(generate_demo_data.generate(TODAY), f)
        demo.refresh_market()
        self.assertEqual(health.load(demo.folder), {})                           # the demo asks nothing
        self.assertIsNone(build_desk.compute({}, today=TODAY, as_of="2026-09-01", health=stored)["health"])

    def test_the_page_shows_it_as_one_row_on_the_overview(self):
        page = page_source()
        self.assertIn("'renderHealth'", page)
        body = template_function("renderHealth", page)
        self.assertIn("foldOpen('Data sources'", body)
        self.assertIn("DATA.as_of", body)
        self.assertIn("python3 doctor.py", body)

    def fake_web(self, answers):
        """An opener answering each host as told: a status code, or an exception."""
        asked = []

        class Answer:
            def __init__(self, url):
                self.url = url

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b"x"

        def opener(req, timeout=None):
            asked.append((req.full_url, dict(req.header_items())))
            host = urllib.parse.urlsplit(req.full_url).hostname
            answer = answers.get(host, 200)
            if isinstance(answer, Exception):
                raise answer
            if answer != 200:
                raise urllib.error.HTTPError(req.full_url, answer, "no", {}, None)
            return Answer(req.full_url)
        return opener, asked

    def folder_with_stores(self):
        folder = tempfile.mkdtemp()
        dump = lambda name, data: json.dump(data, open(os.path.join(folder, name), "w"))
        dump("t212_data.json", dict(generate_demo_data.generate(TODAY), synced_at="2026-09-25T11:47:00+00:00"))
        dump("news_data.json", {"tickers": ["AAA", "ZZZ"], "items": [{"ticker": "AAA"}], "unknown": ["ZZZ"],
                                "synced_at": "2026-09-26T11:52:00+00:00"})
        dump("prices.json", {"SPY": {"2026-09-24": {"c": 1, "a": 1}, "2026-09-25": {"c": 1, "a": 1}},
                             "AAA": {"2026-09-25": {"c": 1, "a": 1}}, "_starts": {}, "cash_rates": {}, "updated_at": "x"})
        dump("watchlist.json", {"tickers": ["AAA", "ZZZ"], "coverage": {}})
        dump("ratings_log.json", [{"ticker": "AAA", "date": "2026-09-20"}, {"ticker": "AAA", "date": "2026-09-26"}])
        dump(health.HEALTH_FILE, health.record({}, "market", [("Filings", 1.0), ("Prices", 1.0)],
                                               [("Prices", "Tiingo's free daily limit is used up")],
                                               now=self.NOW - timedelta(minutes=8)))
        with open(os.path.join(folder, "server.log"), "w") as f:
            f.write("2026-09-26 09:58:01 update: up to date (034ce68 News)\nother line\n")
        os.makedirs(os.path.join(folder, ".git"))                           # a Mac checkout
        return folder

    def rated(self):
        factors = {f["name"]: {"place": 70.0, "value": 1.0} for f in rating.FACTORS}
        factors["momentum"]["place"] = None
        return {"rated": 3, "breakpoints": "NYSE", "companies": {
                    "AAA": {"label": "Hold", "place": 62.4, "among": 1234, "measures": 4, "factors": factors},
                    "BBB": {"label": "Buy", "place": 90.0, "among": 1234, "measures": 5, "factors": factors},
                    "CCC": {"label": "Sell", "place": 5.0, "among": 1234, "measures": 5, "factors": factors}},
                "why_not": {"ZZZ": "financial"}, "not_rated": {"financial": 2, "otc": 7, "misfiled": 0, "too_few": 1}}

    def test_the_report_names_what_is_wrong_and_nothing_private(self):
        environ = {"T212_API_KEY": "t212-key-SECRET-1", "T212_API_SECRET": "t212-secret-SECRET-2",
                   "SEC_CONTACT": "owner@example.com", "TIINGO_API_KEY": "tiingo-SECRET-3",
                   "FINNHUB_API_KEY": "finnhub-SECRET-4", "T212_ENV": "live"}
        opener, asked = self.fake_web({"api.tiingo.com": 401, "finnhub.io": 429,
                                       "fred.stlouisfed.org": urllib.error.URLError("timed out")})
        git = lambda args, **k: subprocess.CompletedProcess(args, 0, stdout={
            "status": "", "log": "034ce68 2026-09-26", "rev-parse": "main",
            "ls-remote": "abc refs/heads/main"}[args[1]], stderr="")
        text = doctor.report(self.folder_with_stores(), environ=environ, now=self.NOW, opener=opener, run=git,
                             rated=self.rated(), iphone=False)
        for secret in ("SECRET", "owner@example.com"):
            self.assertNotIn(secret, text)
        for line in ("version      034ce68 2026-09-26 on main, no local edits",
                     "last update  2026-09-26 09:58:01 update: up to date (034ce68 News)",
                     "OpenAI (summaries)       not set (optional)",
                     "SEC EDGAR                ok      ok",
                     "Tiingo (prices)          FAILED  the key was refused (HTTP 401)",
                     "Finnhub (results, news)  FAILED  the free limit is used up for now (HTTP 429)",
                     "Google News (FT, press)  ok      ok",
                     "FRED (cash rate)         FAILED  cannot connect (timed out)",
                     "OpenAI (summaries)       skipped no OPENAI_API_KEY in .env",
                     "GitHub (updates)         ok      ok",
                     "Trading 212              skipped run with --account",
                     "FAILED Prices: Tiingo's free daily limit is used up; last worked never",
                     "not found at the SEC: ZZZ", "SPY's last close 2026-09-25",
                     "2 entries, latest 2026-09-26", "2 followed: AAA, ZZZ",
                     "3 rated against NYSE-listed companies (definition of " + rating.METHOD + "): Buy 1, Hold 1, Sell 1",
                     "AAA  Hold 62 among 1,234 (book to market 70, shares change 70, momentum –, gross profitability 70",
                     "not rated: 2 banks, insurers and property companies, 7 over the counter, 1 with too few themes",
                     "ZZZ  not rated: banks, insurers"):
            self.assertIn(line, text)
        self.assertIn("Company data  2026-09-26 11:52 UTC (8 min ago), 1 of 2 steps ok", text)
        self.assertIn("account (t212_data.json)", text)
        self.assertNotIn("totalValue", text)
        # the account's figures against Trading 212's own: whether each agrees, never what is held
        checked = text[text.index("Checks against Trading 212"):text.index("Ratings")]
        for line in ("shares    agrees · all 9 match", "cash      agrees · apart by 0.00% of the account",
                     "total     agrees", "closed    agrees", "holdings  agrees"):
            self.assertIn(line, checked)
        for held in ("AAPL", "MSFT", "VOO"):
            self.assertNotIn(held, checked)
        sec = next(h for url, h in asked if "sec.gov" in url)
        self.assertIn("owner@example.com", sec["User-agent"])                  # sent to the SEC, never printed
        press = next(url for url, h in asked if "news.google.com" in url)
        self.assertIn("site%3Aft.com", press)                                  # the FT's own search
        self.assertNotIn("owner@example.com", press)
        self.assertEqual(doctor.scrub("…?token=abcdef123&x", {}), "…?token=[key]&x")
        missing = doctor.report(self.folder_with_stores(), environ={}, now=self.NOW, offline=True,
                                rated=self.rated(), iphone=True, opener=lambda *a, **k: self.fail("asked offline"))
        self.assertIn("Trading 212 key          MISSING", missing)
        self.assertIn("not asked (--offline)", missing)

    def test_the_phone_says_which_code_it_runs(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "b.zip")
            with zipfile.ZipFile(bundle, "w") as z:
                z.writestr(phone.MANIFEST, json.dumps({"commit": "034ce68", "made_at": "2026-09-26T10:00:00+00:00",
                                                       "code": ["x.py"], "data": []}))
                z.writestr("x.py", "x")
            folder = os.path.join(root, "desk")
            os.makedirs(folder)
            phone.update(bundle, folder=folder, log=lambda *a: None)
            rows = dict(doctor.code(folder, iphone=True))
            self.assertEqual(rows["version"], "034ce68, packed 2026-09-26")
            self.assertIn("iPhone", rows["python"])
        self.assertIn(phone.MANIFEST, phone_bundle.NOT_SENT)
        self.assertIn("health.json", phone_bundle.NOT_SENT)                   # each desk its own

class CompanyDataOnItsOwnTests(unittest.TestCase):
    """The page
    updates the company data on opening and every MARKET_EVERY_MINUTES while open; the
    account syncs only when its button is pressed."""

    def template(self):
        return page_source()

    def test_a_card_is_named_from_its_filings_or_the_sec_list_never_a_dressed_up_ticker(self):
        store = {"companies": {"AAPL": {"name": "Apple Inc."}, "GE": {"name": "GENERAL ELECTRIC CO"}}}
        self.assertEqual(build_desk.company_name("AAPL", {}, store), "Apple Inc.")          # filings not loaded
        self.assertEqual(build_desk.company_name("AAPL", {"companies": {"AAPL": "AAPL"}}, store), "Apple Inc.")
        self.assertEqual(build_desk.company_name("GE", {}, store), "General Electric Co")
        self.assertEqual(build_desk.company_name("PLTR", {}, store), "PLTR")                 # not "Pltr"
        self.assertEqual(build_desk.company_name("PLTR", {"companies": {"PLTR": "Palantir Technologies Inc."}},
                                                 None), "Palantir Technologies Inc.")
        cards = build_desk.build_companies({"tickers": ["AAPL", "PLTR"]}, {}, {}, {}, {}, TODAY, store=store)
        self.assertEqual([c["name"] for c in cards], ["Apple Inc.", "PLTR"])

    def test_the_page_is_told_when_the_company_data_came_and_how_often_it_comes(self):
        news_data = {"tickers": [], "items": [], "synced_at": "2026-09-26T08:00:00+00:00"}
        d = build_desk.compute(generate_demo_data.generate(TODAY), today=TODAY, news=news_data)
        self.assertEqual((d["market_updated_at"], d["market_every_minutes"]),
                         ("2026-09-26T08:00:00+00:00", build_desk.MARKET_EVERY_MINUTES))
        past = build_desk.compute(generate_demo_data.generate(TODAY), today=TODAY, news=news_data,
                                  as_of=TODAY.isoformat())
        self.assertIsNone(past["market_updated_at"])                  # a past day updates nothing

    def test_the_page_has_one_timer_and_it_never_syncs_the_account(self):
        page = self.template()
        self.assertEqual(page.count("setInterval("), 1)
        timer = page[page.index("setInterval("):]
        timer = timer[:timer.index("\n")]
        self.assertIn("updateMarket(false)", timer)
        self.assertNotIn("refreshBtn", timer)
        market = template_function("updateMarket", page)
        self.assertIn("part: 'market'", market)
        self.assertNotIn("account", market.replace("'account", ""))
        # the account's sync is sent from its button alone
        self.assertEqual(page.count("part: 'account'"), 1)
        button = page[page.index("$('refreshBtn').addEventListener"):]
        self.assertIn("part: 'account'", button[:button.index("\n});")])

    def test_the_interval_is_the_pythons_and_the_page_guesses_none(self):
        due = template_function("marketDue", self.template())
        self.assertIn("DATA.market_every_minutes", due)
        self.assertIsNone(re.search(r"market_every_minutes\s*\|\|", self.template()))
        self.assertIsNone(re.search(r"\d", due.replace("60000", "")))

    def test_an_update_that_arrives_by_itself_never_redraws_under_the_users_hands(self):
        page = self.template()
        self.assertIn("typing()", template_function("showMarket", page))
        self.assertIn("keepPlace(renderAll)", template_function("reloadData", page))
        guard = template_function("typing", page)
        for held in ("editing", "INPUT|TEXTAREA|SELECT", "wlAdd", "dialog"):
            self.assertIn(held, guard)
        # not for the demo, a past day or a page opened as a file, and never twice at once
        market = template_function("updateMarket", page)
        for guard_on in ("marketRunning", "DATA.as_of", "DATA.demo", "file:"):
            self.assertIn(guard_on, market[:market.index("marketRunning = true")])


if __name__ == "__main__":
    unittest.main()
