"""The demo (scripts/generate_demo_data.py): invented companies with every screen filled, nothing real in it,
and nothing read or written outside its own folder."""
from support import *  # noqa: F401,F403
import world

# Names the demo must never show: real companies the tests once used, and the outlets the desk knows.
REAL = re.compile(r"apple|microsoft|nvidia|amazon|tesla|paypal|coca|johnson|exxon|jpmorgan|advanced micro|"
                  r"reuters|bloomberg|financial times|wall street|barron|marketwatch|yahoo|seekingalpha", re.I)
GLOBAL_STORES = ("universe.json", "listings.json", "sectors.json", "screen.json", "value.json", ".cik_map.json", "prices.json")


def quietly(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args)


class DemoWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.before = {n: os.path.getmtime(os.path.join(ROOT, n)) for n in GLOBAL_STORES if os.path.exists(os.path.join(ROOT, n))}
        cls.paths = {(m, n): getattr(m, n) for m, n in ((universe, "UNIVERSE_FILE"), (universe, "LISTINGS_FILE"),
                                                       (sectors, "SECTORS_FILE"), (screen, "SCREEN_FILE"), (value, "VALUE_FILE"),
                                                       (news, "CIK_CACHE"))}
        quietly(generate_demo_data.main, [cls.folder])
        restore = build_desk.keep_apart(cls.folder)
        try:
            cls.data = build_desk.compute(**build_desk.load_inputs(cls.folder))
        finally:
            restore()

    def test_no_company_or_outlet_in_it_is_real(self):
        roster = generate_demo_data.DEMO_COMPANIES
        self.assertEqual(len(roster), len({c[0] for c in roster}))
        for ticker, name, *_ in roster:
            self.assertIsNone(REAL.search(name), name)
            self.assertNotIn(ticker, {t.split("_")[0] for t, *_ in generate_demo_data.UNIVERSE}, ticker)
            self.assertGreater(roster[[c[0] for c in roster].index(ticker)][4], 9_000_000)     # a CIK the SEC has not reached
        for name in sorted(os.listdir(self.folder)):
            if name.endswith(".json"):
                with open(os.path.join(self.folder, name)) as f:
                    self.assertIsNone(REAL.search(f.read()), name)

    def test_the_account_is_the_same_numbers_under_invented_names(self):
        real, demo = generate_demo_data.generate(TODAY), generate_demo_data.generate(TODAY, universe=generate_demo_data.DEMO_UNIVERSE)
        self.assertEqual(real["summary"], demo["summary"])
        self.assertEqual([o["fill"]["price"] for o in real["orders"]], [o["fill"]["price"] for o in demo["orders"]])
        held = {p["instrument"]["ticker"] for p in demo["positions"]}
        self.assertFalse(held & {"AAPL_US_EQ", "MSFT_US_EQ", "NVDA_US_EQ", "AMZN_US_EQ", "TSLA_US_EQ"})

    def test_every_screen_has_something_on_it(self):
        d = self.data
        self.assertEqual(len(d["companies"]), 11)                      # five held stocks, three funds, three followed
        self.assertGreaterEqual(len([c for c in d["companies"] if c["rating"]]), 6)
        self.assertGreater(len(d["rating"]["buy_list"]), 0)
        self.assertGreater(d["rating"]["rated"], 100)
        self.assertGreater(d["company_news"]["count"], 20)
        self.assertGreater(len(build_desk.load_json(os.path.join(self.folder, "news_data.json"), {}).get("items") or []), 100)   # filings
        self.assertGreater(d["account"]["total"], 0)
        for c in d["companies"]:
            if c["ticker"] not in ("VOO", "QQQ", "SCHD"):
                self.assertTrue(c["price"], c["ticker"])
                self.assertTrue(c["next_earnings"], c["ticker"])

    def test_the_checks_against_the_account_agree(self):
        self.assertGreaterEqual(len(self.data["checks"]["checks"]), 6)
        self.assertEqual(self.data["checks"]["failed"], [])

    def test_the_tilt_is_the_holdings_own_places_weighted(self):
        """The Portfolio's lean is the value-weighted mean of the places each holding already shows in its row, over
        the invented companies the demo holds: the two cannot say different things (one definition)."""
        d = self.data
        self.assertEqual(d["tilt"], rating.tilt(d["positions"]["rows"], d["account"]["total"]))
        self.assertNotIn("why", d["tilt"])
        placed = {x["theme"]: x for x in d["tilt"]["themes"] if x["place"] is not None}
        self.assertGreaterEqual(len(placed), 3)
        for x in placed.values():
            self.assertTrue(0 <= x["place"] <= 100, x)
            self.assertTrue(0 < x["share"] <= d["tilt"]["share"] + 1e-9, x)

    def test_the_demo_moves_with_its_market(self):
        """Its lines share a market (generate_demo_data.MARKET_LOADING), so an account of index funds and shares reads
        as one: a beta near one that the market explains most of. With independent walks the History's risk card read
        0.03 and 0%, which a stranger would take for a fault."""
        risk = self.data["history"]["risk"]
        self.assertNotIn("why", risk)
        self.assertTrue(0.6 < risk["beta"]["slope"] < 1.1, risk["beta"])
        self.assertGreater(risk["beta"]["explained"], 0.5)
        self.assertEqual(len(generate_demo_data.MARKET_LOADING), len(generate_demo_data.UNIVERSE))
        self.assertTrue(all(0 <= x < 1 for x in generate_demo_data.MARKET_LOADING))
        self.assertEqual(len(self.data["trades"]["rows"]), 77)                  # the market's draws are apart: the account's own are unchanged

    def test_results_days_are_not_all_one_day(self):
        self.assertGreater(len({c["next_earnings"]["date"] for c in self.data["companies"] if c["next_earnings"]}), 3)

    def test_nothing_is_read_or_written_outside_its_folder(self):
        for name in GLOBAL_STORES:
            path = os.path.join(ROOT, name)
            if name in self.before:
                self.assertEqual(os.path.getmtime(path), self.before[name], name)
            else:
                self.assertFalse(os.path.exists(path), name)
        for (module, name), path in self.paths.items():
            self.assertEqual(getattr(module, name), path, f"{module.__name__}.{name} was left pointing at the demo")
        for name in ("health.json", "looks.json", "index.html", "desk_data.json"):
            self.assertFalse(os.path.exists(os.path.join(self.folder, name)), name)

    def test_the_simulated_market_is_put_back(self):
        self.assertFalse(world.DEMO)
        self.assertEqual(world.COMPANIES[0]["ticker"], "AAPL")
        self.assertIn("Reuters", world.OUTLETS)
        self.assertIn("NVDA", world.SPLITS)

    def test_no_story_comes_from_a_real_outlet(self):
        stored = build_desk.load_json(os.path.join(self.folder, "headlines.json"), {})
        stories = [s for items in (stored.get("companies") or {}).values() for s in items]
        self.assertGreater(len(stories), 50)
        self.assertEqual({s["via"] for s in stories}, {"finnhub"})
        self.assertLessEqual({s["source"] for s in stories}, {"Demo Wire", "Example Ledger", "Sample Post"})

    def test_a_second_run_is_a_fresh_market_and_keeps_the_demos_own_notes(self):
        folder = tempfile.mkdtemp()
        quietly(generate_demo_data.main, [folder])
        with open(os.path.join(folder, "paper.json"), "w") as f:
            f.write('{"kept": true}')
        quietly(generate_demo_data.main, [folder])                     # would fail on "already follows" if not fresh
        with open(os.path.join(folder, "paper.json")) as f:
            self.assertEqual(f.read(), '{"kept": true}')
        followed = build_desk.load_json(os.path.join(folder, "watchlist.json"), {})
        self.assertEqual(sorted(followed["tickers"]), sorted(generate_demo_data.FOLLOWED))

    def test_the_demo_stores_are_private_to_the_owner(self):
        for name in os.listdir(self.folder):
            path = os.path.join(self.folder, name)
            if os.path.isfile(path):
                self.assertEqual(os.stat(path).st_mode & 0o077, 0, name)

    def test_it_runs_the_way_the_phone_runs_it(self):
        """phone.py starts it with runpy, which does not put scripts/ on the import path; the simulated market imports
        this file by name, so it must find itself (found on a phone-shaped run, not by the suite, which has scripts/ on the path)."""
        import runpy
        folder = tempfile.mkdtemp()
        scripts = os.path.join(ROOT, "scripts")
        saved_path, saved_argv, saved_module = list(sys.path), sys.argv, sys.modules.pop("generate_demo_data")
        try:
            sys.path[:] = [p for p in sys.path if os.path.abspath(p) != scripts]
            sys.argv = ["generate_demo_data.py", folder]
            quietly(runpy.run_path, os.path.join(scripts, "generate_demo_data.py"), None, "__main__")
        finally:
            sys.path[:], sys.argv = saved_path, saved_argv
            sys.modules["generate_demo_data"] = saved_module
        self.assertTrue(os.path.exists(os.path.join(folder, "universe.json")))

    def test_the_demo_server_keeps_apart_too(self):
        source = open(os.path.join(ROOT, "server.py")).read()
        self.assertIn("build_desk.keep_apart(Handler.folder)", source)
        restore = build_desk.keep_apart(self.folder)
        try:
            self.assertEqual(universe.UNIVERSE_FILE, os.path.join(self.folder, "universe.json"))
        finally:
            restore()
        self.assertEqual(universe.UNIVERSE_FILE, self.paths[(universe, "UNIVERSE_FILE")])


if __name__ == "__main__":
    unittest.main()
