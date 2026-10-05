"""The account sync and the company update, run whole against a simulated network
(tests/world.py) as they run on the user's Mac: every step, twice (28 Sep 2026). The
exchange list's step failed on every update after the first, and stopped the rest of it;
no module's own test could see that."""
from support import *  # noqa: F401,F403
import world


class WholeUpdateTests(unittest.TestCase):
    MOVED = ((universe, "UNIVERSE_FILE"), (universe, "LISTINGS_FILE"), (sectors, "SECTORS_FILE"),
             (t212, "DATA_FILE"),
             (news, "CIK_CACHE"), (summarise, "SUMMARY_FILE"), (screen, "SCREEN_FILE"), (value, "VALUE_FILE"))

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.restore = world.install()
        # every store in the one folder, as the desk keeps them on the Mac
        self.saved = [(mod, name, getattr(mod, name)) for mod, name in self.MOVED]
        for mod, name, path in self.saved:
            setattr(mod, name, os.path.join(self.folder, os.path.basename(path)))
        self.real = (server.IN_PROCESS_SYNC, research.update)
        server.IN_PROCESS_SYNC = True                       # the sync in this process, as on the phone
        research.update = lambda news_items=None, stored=None, **k: stored or {}   # the backtests: tested apart
        self.handler = server.Handler.__new__(server.Handler)
        self.handler.folder, self.handler.demo = self.folder, False

    def tearDown(self):
        self.restore()
        for mod, name, path in self.saved:
            setattr(mod, name, path)
        server.IN_PROCESS_SYNC, research.update = self.real

    def update(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as log:
            code, out = self.handler.refresh_market()
        return out, log.getvalue()

    def test_two_updates_in_a_row_run_every_step_and_the_second_asks_only_what_changed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code, out = self.handler.refresh_account()
        self.assertEqual((out["ok"], out["message"]), (True, None), out)
        raw = json.load(open(os.path.join(self.folder, "t212_data.json")))
        self.assertNotIn("id", raw["summary"])                              # the account number dropped
        self.assertEqual(len(raw["orders"]), len(world.account()["orders"]))  # every page of the history

        first, log = self.update()
        self.assertEqual((first["ok"], first["message"]), (True, None), log)
        steps = health.load(self.folder)["market"]["steps"]
        self.assertEqual([n for n, s in steps.items() if not s["ok"]], [])
        self.assertIn("Stock exchanges", steps)

        world.ASKED.clear(); del world.LOG[:]
        second, log = self.update()
        self.assertEqual((second["ok"], second["message"]), (True, None), log)
        paths = [urllib.parse.urlsplit(url).path for _, url in world.LOG]
        # nothing that cannot have changed: no closes before a session ends, no financials
        # before a new report, no results or ratings twice a day, no universe or industry codes
        for never in ("/tiingo/daily/", "/api/xbrl/", "/stock/", "/calendar/", "dera", "fredgraph"):
            self.assertEqual([p for p in paths if never in p], [], never)
        self.assertEqual(world.ASKED["t212"], 0)                            # the account only when synced

        data = build_desk.compute(**build_desk.load_inputs(self.folder))
        held = sorted({r["ticker"] for r in data["positions"]["rows"] if r["us_line"]} & set(world.BY_TICKER))
        self.assertEqual(sorted(c["ticker"] for c in data["companies"]), held)   # each holding covered
        for card in data["companies"]:
            self.assertTrue((card.get("price") or {}).get("close"), card["ticker"])
            self.assertIn("label", card.get("rating") or {}, card["ticker"])
        self.assertTrue(data["company_news"]["companies"])
        build_desk.render(data)

    def test_news_is_asked_again_only_after_the_window_or_when_the_button_is_pressed(self):
        """Run whole over the simulated network: the second update, a moment after the first, asks neither
        Finnhub nor Google News for any company's stories; the button's does, for every one it covers."""
        with contextlib.redirect_stdout(io.StringIO()):
            self.handler.refresh_account()
        first, log = self.update()
        self.assertEqual((first["ok"], first["message"]), (True, None), log)
        news_requests = lambda: ([u for s, u in world.LOG if s == "finnhub" and "company-news" in u],
                                 [u for s, u in world.LOG if s == "google"])
        finnhub, google = news_requests()
        self.assertTrue(finnhub and google)                                     # the first update asks for the news
        del world.LOG[:]
        second, log = self.update()
        self.assertEqual((second["ok"], second["message"]), (True, None), log)
        self.assertEqual(news_requests(), ([], []))                             # within the window: not again
        del world.LOG[:]
        self.handler.pressed = True
        try:
            third, log = self.update()
        finally:
            self.handler.pressed = False
        self.assertEqual((third["ok"], third["message"]), (True, None), log)
        again_finnhub, again_google = news_requests()
        symbol = lambda url: re.search(r"symbol=([A-Z.]+)", url).group(1)
        held = {symbol(u) for u in again_finnhub}
        self.assertTrue(len(held) >= 5 and held <= {symbol(u) for u in finnhub})   # pressed: each company covered, afresh
        self.assertTrue(again_google)
        store = json.load(open(os.path.join(self.folder, "headlines.json")))
        self.assertTrue(set(store["asked"]) == {"finnhub", "press"} and store["asked"]["finnhub"])

    def test_the_page_is_rebuilt_when_the_prices_and_the_filings_are_in_not_when_the_news_is(self):
        """5 Oct 2026, the owner: "update companies and refresh the desk faster". The news is the slowest chain
        (Finnhub's pause, then the press's two searches a company); the prices and the filings are not, and used to
        wait for it. Here the news is held back until the page has been rebuilt and shown: it must be, while the
        news is still unasked."""
        with contextlib.redirect_stdout(io.StringIO()):
            self.handler.refresh_account()
        seen, waited, real = threading.Event(), [], headlines.update

        def held(*a, **k):
            waited.append(seen.wait(30))                 # false only if the page was never rebuilt meanwhile
            return real(*a, **k)
        headlines.update = held
        events, shown = [], []

        def report(event):
            events.append(event)
            if event.get("built"):
                shown.append(json.load(open(os.path.join(self.folder, "desk_data.json"))))
                seen.set()
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as log:
                code, out = self.handler.refresh_market(report)
        finally:
            headlines.update = real
        self.assertEqual((out["ok"], out["message"]), (True, None), log.getvalue())
        self.assertTrue(waited and all(waited))                     # rebuilt while the news waited
        self.assertTrue(shown)
        self.assertTrue(shown[0]["companies"])                      # a whole page, with the companies on it (the first to come in)
        news_ended = next(i for i, e in enumerate(events) if e.get("step") == "News" and e.get("state") in ("done", "failed"))
        self.assertLess(events.index({"built": True}), news_ended)
        steps = health.load(self.folder)["market"]["steps"]
        self.assertEqual([n for n, st in steps.items() if not st["ok"]], [])
        for name in server.ON_THE_PAGE:
            self.assertIn(name, steps)

    def test_the_news_does_not_wait_for_the_filings_for_a_name_it_has_and_does_for_one_it_has_not(self):
        """The news used to start once the filings ended, for the name each company's filings give (a story
        counts when it names the company). A company already named is asked at once beside the filings; one the
        filings have not named yet is asked after them, in a pass of its own, and loses nothing by it."""
        with contextlib.redirect_stdout(io.StringIO()):
            self.handler.refresh_account()
        first, log = self.update()
        self.assertEqual((first["ok"], first["message"]), (True, None), log)
        names = json.load(open(os.path.join(self.folder, "news_data.json")))["companies"]
        self.assertTrue(len(names) >= 5)
        asks, filings_done = [], []
        real_update, real_press, real_filings = headlines.update, headlines.update_press, news.refresh

        def update(covered, *a, **k):
            asks.append(("finnhub", sorted(k.get("ask") or []), bool(filings_done)))
            return real_update(covered, *a, **k)

        def update_press(covered, *a, **k):
            asks.append(("press", sorted(k.get("ask") or []), bool(filings_done)))
            return real_press(covered, *a, **k)

        def refresh(*a, **k):
            started = threading.Event()
            deadline = time.monotonic() + 20
            while not any(x[0] == "finnhub" for x in asks) and time.monotonic() < deadline:
                started.wait(0.01)                       # the filings hold back until the first news pass has begun
            filings_done.append(any(x[0] == "finnhub" for x in asks))
            return real_filings(*a, **k)
        headlines.update, headlines.update_press, news.refresh = update, update_press, refresh
        try:
            self.handler.pressed = True
            second, log = self.update()
            self.assertEqual((second["ok"], second["message"]), (True, None), log)
            self.assertEqual(filings_done, [True])           # the news began before the filings ended: it did not wait for them
            self.assertEqual([x[0] for x in asks], ["finnhub", "press"])         # nobody new: no second pass
            self.assertEqual(asks[0][1], sorted(names))                            # every named company, at once
            # one company the filings have not named yet: dropped from their names, as a holding bought today is
            del asks[:], filings_done[:]
            stranger = sorted(names)[0]
            kept = dict(names)
            del kept[stranger]
            path = os.path.join(self.folder, "news_data.json")
            store = json.load(open(path))
            store["companies"] = kept
            json.dump(store, open(path, "w"))
            third, log = self.update()
            self.assertEqual((third["ok"], third["message"]), (True, None), log)
        finally:
            headlines.update, headlines.update_press, news.refresh = real_update, real_press, real_filings
            self.handler.pressed = False
        passes = [(src, ask) for src, ask, _ in asks]
        self.assertEqual(passes, [("finnhub", sorted(kept)), ("press", sorted(kept)),
                                  ("finnhub", [stranger]), ("press", [stranger])])
        self.assertTrue(all(done for src, ask, done in asks[2:]))                 # the new company's pass came after the filings
        steps = health.load(self.folder)["market"]["steps"]
        self.assertIn("News (companies new to the desk)", steps)
        stories = json.load(open(os.path.join(self.folder, "headlines.json")))
        self.assertIn(stranger, stories["companies"])

    def test_a_step_that_shows_the_page_does_so_only_while_something_else_is_still_going(self):
        h, events, built = self.handler, [], []
        h.build = lambda: built.append(1)
        h.unfinished = {"Prices on the page", "Filings on the page", "News", "Ratings", "Research"}
        h.show_partway(events.append)
        self.assertEqual((built, events), ([1], [{"built": True}]))        # the news is still to come
        h.unfinished = {"Prices on the page", "Filings on the page", "Ratings", "Research"}
        h.show_partway(events.append)
        self.assertEqual(built, [1])                                       # only the desk's own last steps: the update's rebuild is next
        h.unfinished = frozenset()

    def test_every_source_failing_is_reported_never_the_desk_itself(self):
        """Every source at once answering with garbage, with another page (a network's), with
        nothing, or refusing the key: each step fails with its reason, the page still builds,
        and none fails as "an error in the desk itself"."""
        for mode in ("garbage", "html", "empty", "403", "404"):
            with self.subTest(mode=mode):
                for name in os.listdir(self.folder):
                    os.remove(os.path.join(self.folder, name))
                for source in ("sec", "frames", "dera", "tiingo", "fred", "finnhub", "google", "t212", "openai"):
                    world.FAULTS[source] = mode
                with contextlib.redirect_stdout(io.StringIO()):
                    code, account = self.handler.refresh_account()
                self.assertFalse(account["ok"])
                self.assertNotIn("desk itself", account["message"])
                with open(os.path.join(self.folder, "t212_data.json"), "w") as f:
                    json.dump(world.account(), f)
                out, log = self.update()
                self.assertTrue(out["ok"])
                self.assertNotIn("desk itself", out["message"] or "", log)
                self.assertNotIn("Traceback", log)
                build_desk.render(build_desk.compute(**build_desk.load_inputs(self.folder)))
                world.FAULTS.clear()


class PricesPartlyTests(unittest.TestCase):
    """28 Sep 2026: one price request failing, or FRED's cash rate on a first run, failed the
    whole step, so every close already fetched was lost, and with it the count of requests
    that Tiingo's hourly limit is kept by: the next update asked for all of them again."""
    NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    def fetch(self, fail_on=None):
        asked = []

        def fetch(ticker, start, key):
            asked.append(ticker)
            if ticker == fail_on:
                raise prices.PriceError("Can't reach Tiingo (timed out)")
            return [("2026-09-24", 10.0, 10.0, 1.0), ("2026-09-25", 11.0, 11.0, 1.0)]
        return fetch, asked

    def test_what_was_fetched_is_kept_and_counted(self):
        fetch, asked = self.fetch(fail_on="BBB")
        out = prices.update(["AAA", "BBB", "CCC"], stored={}, key="k", fetch=fetch, now=self.NOW, cash=None, fx=None)
        self.assertEqual(asked, ["SPY", "AAA", "BBB"])                       # nothing asked after the failure
        self.assertIn("timed out", out[env_config.PARTLY])
        self.assertIn("AAA", out)
        self.assertNotIn("BBB", out)
        self.assertEqual(len(out[prices.META_ASKED]), 3)                    # every request counted, the failed one too

    def test_no_cash_rate_on_a_first_run_keeps_the_closes(self):
        fetch, asked = self.fetch()

        def no_fred(*a, **k):
            raise prices.PriceError("Can't reach FRED for the cash rate (timed out)")
        out = prices.update(["AAA"], stored={}, key="k", fetch=fetch, now=self.NOW, cash=no_fred, fx=None)
        self.assertIn("FRED", out[env_config.PARTLY])
        self.assertIn("AAA", out)
        kept = prices.update(["AAA"], stored=dict(out, **{prices.CASH_KEY: {"2026-09-25": 4.2}}), key="k",
                             fetch=fetch, now=self.NOW, cash=no_fred, fx=None)
        self.assertNotIn(env_config.PARTLY, kept)                          # a stored rate carries on, as before
