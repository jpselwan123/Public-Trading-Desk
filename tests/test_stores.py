"""The stored files: a damaged one never stops the page, and one that holds the user's
record is never written over (28 Sep 2026)."""
from support import *  # noqa: F401,F403

DAMAGED = {"cut short": '{"a": [1, 2', "a list": "[]", "nothing": "null", "a number": "42", "words": '"x"',
           "not text": b"\x00\xff\xfe"}
# every store the page is built from, in the served folder
FOLDER_STORES = ("t212_data.json", "journal.json", "news_data.json", "headlines.json", "health.json", "looks.json",
                 "plans.json", "rating_sample.json", "prices.json", "quotes.json", "ratings_log.json",
                 "fundamentals.json", "earnings_data.json", "summaries.json", "briefs.json", "paper.json",
                 "analysts_data.json", "research.json", "watchlist.json", "theses.json", "diffs.json")


def damage(path, text):
    with open(path, "wb") as f:
        f.write(text if isinstance(text, bytes) else text.encode())


class DamagedStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        with open(os.path.join(self.folder, "t212_data.json"), "w") as f:
            json.dump(generate_demo_data.generate(TODAY), f)

    def test_the_page_builds_whatever_shape_a_store_is_in(self):
        """A store edited by hand into a list or a number, cut short, or not text at all:
        the page still builds, today's and a past day's, and what the store held is left out."""
        real = {name: getattr(mod, attr) for name, (mod, attr) in
                {"universe": (universe, "UNIVERSE_FILE"), "sectors": (sectors, "SECTORS_FILE"),
                 "listings": (universe, "LISTINGS_FILE")}.items()}
        spare = tempfile.mkdtemp()
        try:
            for store in FOLDER_STORES + ("universe.json", "sectors.json", "listings.json"):
                for what, text in DAMAGED.items():
                    with self.subTest(store=store, damage=what):
                        folder = tempfile.mkdtemp()
                        shutil.copy(os.path.join(self.folder, "t212_data.json"), folder)
                        universe.UNIVERSE_FILE = os.path.join(spare, "universe.json")
                        sectors.SECTORS_FILE = os.path.join(spare, "sectors.json")
                        universe.LISTINGS_FILE = os.path.join(spare, "listings.json")
                        for name in ("universe.json", "sectors.json", "listings.json"):
                            if os.path.exists(os.path.join(spare, name)):
                                os.remove(os.path.join(spare, name))
                        damage(os.path.join(spare if store in ("universe.json", "sectors.json", "listings.json")
                                            else folder, store), text)
                        data = build_desk.compute(**build_desk.load_inputs(folder))
                        self.assertIn("__DATA__", build_desk.template_source())
                        build_desk.render(data)
                        build_desk.as_of(folder, "2026-09-10")
                        if store != "t212_data.json":
                            self.assertTrue(data["connected"])              # the account still shows
        finally:
            universe.UNIVERSE_FILE, sectors.SECTORS_FILE, universe.LISTINGS_FILE = (
                real["universe"], real["sectors"], real["listings"])

    def test_records_of_the_wrong_kind_are_left_out(self):
        self.assertEqual(build_desk.load_json(os.path.join(self.folder, "missing.json"), {}), {})
        damage(os.path.join(self.folder, "a.json"), "[1, 2]")
        self.assertEqual(build_desk.load_json(os.path.join(self.folder, "a.json"), {}), {})
        self.assertEqual(build_desk.load_json(os.path.join(self.folder, "a.json"), []), [1, 2])
        self.assertEqual(build_desk.records({"o1": {"note": "x"}, "o2": "x", "o3": [1]}), {"o1": {"note": "x"}})
        damage(os.path.join(self.folder, "ratings_log.json"), json.dumps([{"ticker": "A"}, 7, {"no": "ticker"}]))
        self.assertEqual(rating.load_log(os.path.join(self.folder, "ratings_log.json")), [{"ticker": "A"}])

    def test_a_personal_record_is_never_written_over(self):
        """Plans and theses are written once, the ratings log only added to, and the notes,
        the followed list and the practice book are the user's: a file of any of them that
        is there but cannot be read is left exactly as it is, and the page says why."""
        folder = self.folder
        future = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
        cases = {
            "plans.json": lambda: plans.write(folder, {"ticker": "AMD", "side": "BUY", "why": "a reason",
                                                       "wrong_if": "if not", "review_by": future}),
            "theses.json": lambda: thesis.write(
                "amd", {"revenue_direction": "up", "revenue_change_pct": "10", "margin_direction": "up",
                        "reason": "a reason", "confidence_pct": "70"},
                {"quarters": [{"end": "2026-03-28", "revenue": 125.0, "operating_income": 14.0, "filed": "2026-05-05"},
                              {"end": "2026-06-27", "revenue": 130.0, "operating_income": 16.0, "filed": "2026-08-04"}]},
                "2026-11-03", today=date(2026, 9, 24), path=os.path.join(folder, "theses.json")),
            "ratings_log.json": lambda: rating.load_log_for_writing(os.path.join(folder, "ratings_log.json")),
            "watchlist.json": lambda: news.follow("AMD", path=os.path.join(folder, "watchlist.json")),
            "paper.json": lambda: paper.load(os.path.join(folder, "paper.json")),
        }
        errors = (plans.PlanError, thesis.ThesisError, env_config.UnreadableStore, news.CoverageError, paper.PaperError)
        for store, write in cases.items():
            for what, text in DAMAGED.items():
                if store == "watchlist.json" and what == "a list":
                    continue                                  # a list of tickers is the old, readable form
                if store in ("ratings_log.json", "theses.json") and what == "a list":
                    continue                                  # an empty list is a readable, empty record
                with self.subTest(store=store, damage=what):
                    path = os.path.join(folder, store)
                    damage(path, text)
                    before = open(path, "rb").read()
                    with self.assertRaises(errors) as caught:
                        write()
                    self.assertIn("cannot be read", str(caught.exception))
                    self.assertEqual(open(path, "rb").read(), before)
        # a note: refused over HTTP's handler, the journal left as it was
        handler = server.Handler.__new__(server.Handler)
        handler.folder, handler.demo = folder, False
        damage(os.path.join(folder, "journal.json"), '{"o1": {"note": "kept"')
        code, out = handler.save_note({"id": "o2", "note": "new"})
        self.assertFalse(out["ok"])
        self.assertEqual(open(os.path.join(folder, "journal.json")).read(), '{"o1": {"note": "kept"')
        # the practice book: a trade is refused, "Start over" still begins a new one
        damage(os.path.join(folder, "paper.json"), '{"cash": "lots"}')
        real_build, handler.build = handler.build, lambda: None
        code, out = handler.paper_trade({"action": "buy", "ticker": "AMD", "amount": 100})
        self.assertEqual(out, {"ok": False, "message": paper.UNREADABLE})
        self.assertEqual(open(os.path.join(folder, "paper.json")).read(), '{"cash": "lots"}')
        self.assertEqual(build_desk.build_paper(build_desk.paper_book(os.path.join(folder, "paper.json")), {}, TODAY)
                         ["unreadable"], paper.UNREADABLE)
        self.assertIn("P.unreadable", template_function("renderPaper"))
        code, out = handler.paper_trade({"action": "reset"})
        self.assertTrue(out["ok"])
        self.assertEqual(paper.load(os.path.join(folder, "paper.json"))["cash"], paper.START_CASH)

class PrivateFileTests(unittest.TestCase):
    """Every file the desk writes holds something of the user's (holdings, what they follow,
    their notes), so each is readable by its owner alone, whatever the umask."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.umask = os.umask(0o022)                  # the usual default: files come out world-readable

    def tearDown(self):
        os.umask(self.umask)

    def mode(self, name):
        return oct(os.stat(os.path.join(self.folder, name)).st_mode & 0o777)

    def test_a_written_file_is_private_and_so_is_one_it_replaces(self):
        path = os.path.join(self.folder, "store.json")
        env_config.atomic_write_json(path, {"a": 1})
        self.assertEqual(self.mode("store.json"), "0o600")
        os.chmod(path, 0o644)                                       # an older desk left it readable
        with open(path + ".tmp", "w") as f:                         # ... and a crash left a temp file behind
            f.write("half")
        os.chmod(path + ".tmp", 0o644)
        env_config.atomic_write_json(path, {"a": 2})
        self.assertEqual((self.mode("store.json"), json.load(open(path))), ("0o600", {"a": 2}))
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_the_page_and_its_data_are_private(self):
        with open(os.path.join(self.folder, "t212_data.json"), "w") as f:
            json.dump(generate_demo_data.generate(TODAY), f)
        with contextlib.redirect_stdout(io.StringIO()):
            build_desk.main([self.folder])
        for name in ("index.html", "desk_data.json"):
            self.assertEqual(self.mode(name), "0o600", name)

    def test_nothing_but_atomic_write_creates_a_file(self):
        """The one place that makes files private is the one place files are made: a module that
        opened its own for writing would leave the umask to decide who can read it."""
        allowed = {"env_config.py", "phone.py"}                     # phone.py sets 0600 on what it writes
        for name in sorted(os.listdir(ROOT)):
            if name.endswith(".py") and name not in allowed:
                with open(os.path.join(ROOT, name)) as f:
                    text = f.read()
                self.assertIsNone(re.search(r"open\([^)]*['\"](?:w|wb|a|x)['\"]", text), name)


class StepFaultTests(unittest.TestCase):
    def test_a_fault_in_one_step_fails_that_step_alone(self):
        """A fault in the desk's own code used to stop the whole update at that step; now the
        step fails, says so, and every step after it still runs."""
        handler = server.Handler.__new__(server.Handler)
        handler.folder = tempfile.mkdtemp()
        ran, events, timed = [], [], []

        def broken():
            raise KeyError("a bug")
        with contextlib.redirect_stderr(io.StringIO()) as log:
            failed = handler.run_steps((("First", broken), ("Second", lambda: (ran.append(1), None))),
                                       events.append, timed)
        self.assertEqual(failed, [("First", "an error in the desk itself; server.log has the detail")])
        self.assertEqual(ran, [1])
        self.assertIn("KeyError", log.getvalue())                           # the detail, for server.log
        self.assertEqual([e["state"] for e in events if "seconds" in e], ["failed", "done"])


class UnreadableAnswerTests(unittest.TestCase):
    """28 Sep 2026: a page in place of the data (a network's sign-in page) came
    through as Python's own error ("Expecting value: line 1 column 1")."""

    def test_trading_212_answering_with_another_page_says_so(self):
        for body in (b"<html><body>Your network session has expired</body></html>", b"\x1f\x8b garbage"):
            def opener(req, timeout, body=body):
                class R(io.BytesIO):
                    headers = {"Content-Encoding": "gzip"} if body.startswith(b"\x1f") else {}
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                return R(body)
            with self.assertRaises(t212.T212Error) as caught:
                t212.Client("k", "s", "demo", opener=opener, sleep=lambda s: None).get("/equity/positions")
            self.assertIn("could not be read", str(caught.exception))

    def test_the_secs_data_set_not_being_a_zip_says_so(self):
        def opener(req, timeout):
            class R(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return R(b"<html>not a zip</html>")
        with self.assertRaises(sectors.SectorError) as caught:
            sectors.fetch_quarter("2026q2", "qa@example.com", opener=opener)
        self.assertIn("does not read", str(caught.exception))


class NoKeyInAMessageTests(unittest.TestCase):
    def test_a_failure_that_quotes_a_key_never_stores_it(self):
        """28 Sep 2026: Finnhub's key travels in its addresses, and an error can quote one;
        each step's reason is stored in health.json and shown on the page."""
        real = os.environ.get("FINNHUB_API_KEY")
        os.environ["FINNHUB_API_KEY"] = "fhSECRETkey123"
        try:
            handler = server.Handler.__new__(server.Handler)
            handler.folder = tempfile.mkdtemp()

            def leaky():
                raise earnings.EarningsError("Can't reach Finnhub (bad URL /api/v1/news?symbol=A B&token=fhSECRETkey123)")
            failed = handler.run_steps((("News", leaky),), lambda e: None, [])
            self.assertNotIn("fhSECRETkey123", json.dumps(failed))
            stored = health.record({}, "market", [("News", 1.0)], [("News", "x token=fhSECRETkey123")])
            self.assertNotIn("fhSECRETkey123", json.dumps(stored))
            self.assertIs(doctor.scrub, env_config.scrub)                   # one definition
        finally:
            if real is None:
                os.environ.pop("FINNHUB_API_KEY", None)
            else:
                os.environ["FINNHUB_API_KEY"] = real
