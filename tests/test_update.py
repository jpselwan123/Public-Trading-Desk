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
