"""Filings, the moves after them, the annual report's wording, company news and the written summaries."""
from support import *  # noqa: F401,F403


class NewsTests(unittest.TestCase):
    SUBMISSIONS = {"name": "NVIDIA CORP", "filings": {"recent": {
        "form": ["8-K", "4", "10-Q", "8-K"],
        "filingDate": ["2026-09-18", "2026-09-17", "2026-08-27", "2020-01-02"],
        "acceptanceDateTime": ["2026-09-18T16:05:00.000Z", "2026-09-17T18:00:00.000Z",
                               "2026-08-27T16:10:00.000Z", "2020-01-02T16:00:00.000Z"],
        "accessionNumber": ["0001045810-26-000200", "0001045810-26-000199",
                            "0001045810-26-000180", "0001045810-20-000001"],
        "items": ["2.02,9.01", "", "", "8.01"],
        "primaryDocument": ["nvda-8k.htm", "form4.xml", "nvda-10q.htm", "old.htm"]}}}

    def fake_fetch(self, url, ua, **kw):
        if "company_tickers" in url:
            return {"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}}
        if "CIK0001045810" in url:
            return dict(self.SUBMISSIONS)
        return None

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        news.CIK_CACHE = os.path.join(self.tmp, ".cik_map.json")
        news.WATCHLIST_FILE = os.path.join(self.tmp, "watchlist.json")

    def test_plain_english_labels(self):
        self.assertEqual(news.label_for("8-K", "2.02,9.01")[0], "Company announcement")
        self.assertIn("Results announced", news.label_for("8-K", "2.02")[1])
        self.assertTrue(news.label_for("8-K", "5.02")[2])          # leadership change is important
        self.assertFalse(news.label_for("8-K", "7.01")[2])
        self.assertEqual(news.label_for("4", "")[0], "Insider trade")

    def test_every_common_filing_has_plain_words(self):
        """S-31: the Filings page promises plain words, and showed "3", "25-NSE" and
        "SCHEDULE 13D/A" raw. EDGAR's December 2024 names are included, and the new
        name for an active 5% stake is as important as the old one."""
        for form, words in (("3", "Insider's first holdings"), ("25-NSE", "Listing removed"),
                            ("SCHEDULE 13D/A", "Big stake, active: update"), ("SCHEDULE 13G", "Big stake, passive"),
                            ("144/A", "Planned insider sale, amended"), ("13F-HR/A", "Holdings report, amended")):
            self.assertEqual(news.label_for(form, "")[0], words, form)
        self.assertTrue(news.label_for("SCHEDULE 13D", "")[2])
        self.assertTrue(news.label_for("SC 13D", "")[2])
        self.assertEqual(news.label_for("XYZ-9", "")[:2], ("XYZ-9", "Filed with the SEC."))   # unknown: said as filed
        # a filing stored before the table knew its form reads as the table reads now
        stored = {"tickers": ["ZZZ"], "items": [{"ticker": "ZZZ", "form": "SCHEDULE 13D", "label": "SCHEDULE 13D",
                                                  "what": "Filed with the SEC.", "date": "2026-09-01", "material": False}]}
        row = build_desk.build_news(build_desk.named(stored), [], date(2026, 9, 25), {})["items"][0]
        self.assertEqual((row["label"], row["material"]), ("Big stake, active", True))
        self.assertIn("intends to influence", row["what"])
        page = build_desk.compute({}, today=date(2026, 9, 25), news=stored)
        self.assertEqual(page["news"]["items"][0]["label"], "Big stake, active")     # compute applies it

    def test_older_filings_are_read_once_and_kept(self):
        """27 Sep 2026: every update downloaded each company's whole six years again,
        though only its latest list can change; for a bank, dozens of files each half hour."""
        asked = []
        recent = {"form": ["8-K", "10-Q"], "filingDate": ["2026-09-18", "2026-08-27"],
                  "acceptanceDateTime": ["2026-09-18T16:05:00.000Z", "2026-08-27T16:10:00.000Z"],
                  "accessionNumber": ["a-3", "a-2"], "items": ["2.02", ""], "primaryDocument": ["k.htm", "q.htm"]}
        older = {"form": ["10-K", "8-K"], "filingDate": ["2026-08-27", "2025-02-20"],
                 "acceptanceDateTime": ["2026-08-27T08:00:00.000Z", "2025-02-20T16:00:00.000Z"],
                 "accessionNumber": ["a-1b", "a-1"], "items": ["", "5.02"], "primaryDocument": ["y.htm", "o.htm"]}

        def fetch(url, ua, **kw):
            asked.append(url)
            if "company_tickers" in url:
                return {"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}}
            if url.endswith("CIK0001045810-submissions-001.json"):
                return dict(older)
            return {"name": "NVIDIA CORP", "filings": {"recent": dict(recent), "files": [
                {"name": "CIK0001045810-submissions-001.json", "filingFrom": "2019-01-01", "filingTo": "2026-08-27"}]}}
        first = news.refresh(["NVDA"], ua="t", fetch=fetch, today=date(2026, 9, 21))
        self.assertTrue(any(u.endswith("-001.json") for u in asked))
        self.assertEqual(sorted(i["id"] for i in first["items"]), ["a-1", "a-1b", "a-2", "a-3"])
        self.assertEqual(first["read"], {"NVDA": "2026-09-21"})
        asked.clear()
        second = news.refresh(["NVDA"], ua="t", fetch=fetch, today=date(2026, 9, 22), stored=first)
        self.assertFalse(any(u.endswith("-001.json") for u in asked))                  # the older file: not again
        self.assertEqual(sorted(i["id"] for i in second["items"]), ["a-1", "a-1b", "a-2", "a-3"])   # nothing lost
        asked.clear()
        stale = dict(first, read={"NVDA": "2026-08-01"})                                # away since before the list began
        news.refresh(["NVDA"], ua="t", fetch=fetch, today=date(2026, 9, 22), stored=stale)
        self.assertTrue(any(u.endswith("-001.json") for u in asked))                   # it might have missed some
        self.assertIn("stored=build_desk.load_json", inspect.getsource(server.Handler.update_research))

    def test_refresh_keeps_recent_filings_only(self):
        out = news.refresh(["nvda"], ua="test", fetch=self.fake_fetch, today=date(2026, 9, 21))
        self.assertEqual(out["tickers"], ["NVDA"])
        self.assertEqual([i["form"] for i in out["items"]], ["8-K", "4", "10-Q"])   # 2020 one dropped
        first = out["items"][0]
        self.assertEqual(first["ticker"], "NVDA")
        self.assertTrue(first["material"])
        self.assertTrue(first["url"].startswith("https://www.sec.gov/Archives/edgar/data/1045810/000104581026000200/"))
        self.assertEqual(out["unknown"], [])

    def test_unknown_ticker_is_reported_not_crashing(self):
        out = news.refresh(["NVDA", "NOTREAL"], ua="test", fetch=self.fake_fetch, today=date(2026, 9, 21))
        self.assertEqual(out["unknown"], ["NOTREAL"])
        self.assertTrue(out["items"])

    def test_watchlist_is_deduped_and_uppercased(self):
        self.assertEqual(news.save_watchlist([" nvda ", "NVDA", "msft", ""]), ["NVDA", "MSFT"])
        self.assertEqual(news.load_watchlist(), ["NVDA", "MSFT"])

    def test_a_sixteenth_company_must_name_the_one_it_replaces(self):
        """Phase 6: a coverage list is a commitment; the cap is what makes it one."""
        for i in range(news.MAX_COVERAGE):
            news.follow("T%02d" % i, today=date(2026, 9, 1))
        with self.assertRaises(news.CoverageError) as refused:
            news.follow("XOM")
        self.assertIn("Name the one XOM replaces", str(refused.exception))
        self.assertEqual(len(news.load_watchlist()), news.MAX_COVERAGE)
        with self.assertRaises(news.CoverageError):
            news.follow("XOM", replaces="NOTFOLLOWED")
        saved = news.follow("XOM", replaces="t03", today=date(2026, 9, 24))
        self.assertEqual(len(saved), news.MAX_COVERAGE)
        self.assertNotIn("T03", saved)
        left = news.load_coverage()["past"][-1]
        self.assertEqual((left["ticker"], left["followed_at"], left["replaced_by"]), ("T03", "2026-09-01", "XOM"))
        with self.assertRaises(news.CoverageError):
            news.save_watchlist(saved + ["ONE", "MORE"])                # the one writer enforces it too

    def test_a_ticker_alone_follows_a_company(self):
        """The user dropped the reason on 26 Sep 2026 and removed it on 27 Sep: a ticker
        alone follows, dated today, and no reason is asked, kept or shown."""
        news.follow("nvda", today=date(2026, 9, 1))
        self.assertEqual(news.load_coverage()["coverage"]["NVDA"], {"followed_at": "2026-09-01"})
        with self.assertRaises(news.CoverageError):
            news.follow("NVDA")                                   # already followed
        self.assertNotIn("why", inspect.signature(news.follow).parameters)
        self.assertNotIn("cv.why", template_function("coverageLine"))
        self.assertNotIn('"why"', inspect.getsource(server.Handler.save_watchlist))

    def test_the_command_line_follows_through_follow(self):
        """S-17: `news.py NVDA` added a company with no date, the one way round follow().
        A bare ticker is still refused; --follow goes through follow()."""
        pulled = []
        real = news.refresh
        news.refresh = lambda tickers, **kw: pulled.append(list(tickers)) or {"items": [], "unknown": [], "tickers": tickers}
        old_file, news.NEWS_FILE = news.NEWS_FILE, os.path.join(self.tmp, "news_data.json")
        try:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(news.main(["NVDA"]), 2)
                self.assertEqual(news.main(["--follow"]), 2)
                self.assertEqual(news.load_watchlist(), [])
                self.assertEqual(news.main(["--follow", "nvda"]), 0)
                self.assertEqual(news.main(["--follow", "amd"]), 0)
        finally:
            news.refresh, news.NEWS_FILE = real, old_file
        self.assertTrue(news.load_coverage()["coverage"]["NVDA"]["followed_at"])
        self.assertEqual(pulled, [["NVDA"], ["NVDA", "AMD"]])
        # the one writer is called by follow (a new company, or dating an old one, S-29),
        # unfollow and the server's first list, nothing else
        calls = re.compile(r"(?<![\w.])save_watchlist\(|\bnews\.save_watchlist\(")
        callers = []
        for folder in (ROOT, os.path.join(ROOT, "scripts")):
            for name in sorted(os.listdir(folder)):
                if name.endswith(".py"):
                    with open(os.path.join(folder, name)) as f:
                        callers += [name for line in f if calls.search(line) and "def save_watchlist" not in line]
        self.assertEqual(callers, ["news.py", "news.py", "news.py", "server.py"])
        with open(os.path.join(ROOT, "news.py")) as f:
            tree = ast.parse(f.read())
        owners = sorted(fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                        for node in ast.walk(fn) if isinstance(node, ast.Call)
                        and getattr(node.func, "id", None) == "save_watchlist")
        self.assertEqual(owners, ["follow", "follow", "unfollow"])

    def test_a_company_followed_before_dates_were_kept_can_be_dated_now(self):
        """S-29: a company on the list from before follow dates has no record, so a past
        day cannot place it (K-03). follow() refused it ("You already follow"), and the
        only way round was to stop and re-follow, writing a stop that never happened.
        Following it again now dates it today, and nothing else."""
        news.save_watchlist(["AMD", "KO"])                       # the old list: no records
        news.follow("amd", today=date(2026, 9, 25))
        state = news.load_coverage()
        self.assertEqual(state["tickers"], ["AMD", "KO"])         # same list, same order
        self.assertEqual(state["coverage"]["AMD"], {"followed_at": "2026-09-25"})
        self.assertEqual(state["past"], [])                      # no stop was invented
        with self.assertRaises(news.CoverageError):
            news.follow("AMD")                                   # now dated: written once
        for t in ["T%02d" % i for i in range(news.MAX_COVERAGE - 2)]:
            news.save_watchlist(news.load_watchlist() + [t])      # at the cap, undated KO and
        dated = news.date_undated(today=date(2026, 9, 26))        # the rest are dated without
        self.assertEqual(dated[0], "KO")                          # replacing anything
        state = news.load_coverage()
        self.assertEqual(state["coverage"]["KO"], {"followed_at": "2026-09-26"})
        self.assertEqual((len(state["tickers"]), state["past"]), (news.MAX_COVERAGE, []))
        self.assertEqual(news.date_undated(), [])                # once
        self.assertNotIn("Give the reason", template_function("coverageLine"))
        self.assertIn("news.date_undated(", inspect.getsource(server.Handler.update_research))

    def test_saving_a_list_never_erases_a_follow_date(self):
        news.follow("NVDA", today=date(2026, 9, 1))
        news.save_watchlist(["NVDA", "MSFT"])
        self.assertEqual(news.load_coverage()["coverage"]["NVDA"]["followed_at"], "2026-09-01")
        news.unfollow("NVDA", today=date(2026, 9, 24))
        self.assertEqual(news.load_coverage()["past"][-1],
                         {"followed_at": "2026-09-01", "ticker": "NVDA", "stopped_at": "2026-09-24"})

    def test_a_list_saved_before_coverage_reads_without_dates(self):
        with open(news.WATCHLIST_FILE, "w") as f:
            json.dump({"tickers": ["amd", "ko"]}, f)
        self.assertEqual(news.load_coverage(), {"tickers": ["AMD", "KO"], "coverage": {}, "past": []})
        self.assertEqual(build_desk.coverage_of("AMD", news.load_coverage(), {}, TODAY),
                         {"followed_at": None, "days": None, "notes": 0, "theses": 0})

    def test_contact_required_for_sec(self):
        old_home, old = news.HERE, os.environ.pop("SEC_CONTACT", None)
        news.HERE = self.tmp                      # no .env in the temp folder
        try:
            with self.assertRaises(news.NewsError):
                news.user_agent()
        finally:
            news.HERE = old_home
            if old:
                os.environ["SEC_CONTACT"] = old

    FORM4_XML = """<?xml version="1.0"?><ownershipDocument>
      <reportingOwner><reportingOwnerId><rptOwnerName>SMITH JANE</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer>
          <isTenPercentOwner>0</isTenPercentOwner></reportingOwnerRelationship></reportingOwner>
      <aff10b5One>0</aff10b5One>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionDate><value>2026-09-16</value></transactionDate>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>5000</value></transactionShares>
          <transactionPricePerShare><value>21.50</value></transactionPricePerShare></transactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""

    def test_form4_open_market_purchase_is_read_and_flagged(self):
        d = news.parse_form4(self.FORM4_XML)
        self.assertEqual(d["person"], "Smith Jane")
        self.assertEqual(d["role"], "Director")
        self.assertTrue(d["bought"])
        line, bought = news.describe_insider(d)
        self.assertTrue(bought)
        self.assertIn("5,000 shares", line)
        self.assertIn("107,500", line)                      # 5000 × 21.50
        self.assertIn("bought on the open market", line.lower())

    def test_form4_preset_plan_sale_is_not_flagged(self):
        xml = self.FORM4_XML.replace("<aff10b5One>0</", "<aff10b5One>1</").replace(">P<", ">S<")
        line, bought = news.describe_insider(news.parse_form4(xml))
        self.assertFalse(bought)
        self.assertIn("preset plan", line)

    def test_insider_detail_is_fetched_once_then_cached(self):
        calls = []

        def get_text(url, ua, **kw):
            calls.append(url)
            return self.FORM4_XML
        cache = {}
        out = news.refresh(["NVDA"], ua="t", fetch=self.fake_fetch, today=date(2026, 9, 21),
                           insiders=cache, get_text=get_text)
        row = next(i for i in out["items"] if i["form"] == "4")
        self.assertEqual(row["label"], "Insider bought")
        self.assertTrue(row["material"])
        news.refresh(["NVDA"], ua="t", fetch=self.fake_fetch, today=date(2026, 9, 21),
                     insiders=cache, get_text=get_text)
        self.assertEqual(len(calls), 1)                     # second run used the cache

    def test_bad_form4_never_breaks_the_feed(self):
        out = news.refresh(["NVDA"], ua="t", fetch=self.fake_fetch, today=date(2026, 9, 21),
                           insiders={}, get_text=lambda *a, **k: "<not xml")
        self.assertTrue(out["items"])
        self.assertEqual(next(i for i in out["items"] if i["form"] == "4")["label"], "Insider trade")

    def test_page_marks_held_tickers(self):
        out = news.refresh(["NVDA"], ua="test", fetch=self.fake_fetch, today=date(2026, 9, 21))
        raw = generate_demo_data.generate(TODAY)
        d = build_desk.compute(raw, {}, TODAY, news=out)
        self.assertEqual(d["news"]["count"], 3)
        self.assertTrue(any(i["held"] for i in d["news"]["items"]))     # demo account holds NVDA


class ReactionTests(unittest.TestCase):
    def prices(self, stock_step, bench_step=1.0, days=400):
        """Straight-line series so the expected answer is known exactly."""
        out = {"SPY": {}, "ZZZ": {}}
        d, p, b = date(2024, 1, 1), 100.0, 100.0
        for _ in range(days):
            out["ZZZ"][d.isoformat()] = p
            out["SPY"][d.isoformat()] = b
            p *= stock_step
            b *= bench_step
            d += timedelta(days=1)
        return out

    def events(self, n, category="8-K", what="Results announced"):
        return [{"ticker": "ZZZ", "form": category, "label": "Company announcement", "what": what,
                 "date": (date(2024, 1, 2) + timedelta(days=21 * i)).isoformat(), "material": True}
                for i in range(n)]     # 21 days apart: each outside the last one's 20-day window

    def test_reaction_is_measured_against_the_market(self):
        prices = self.prices(1.01, 1.01)             # stock and market move identically
        r = build_desk.build_reactions(self.events(10), prices, date(2026, 9, 21))
        key = next(iter(r))
        self.assertAlmostEqual(r[key]["moves"]["5"]["estimate"], 0.0, places=6)

    def test_outperformance_shows_as_positive(self):
        prices = self.prices(1.02, 1.00)
        r = build_desk.build_reactions(self.events(10), prices, date(2026, 9, 21))
        stats = r["ZZZ|Announcement: Results announced"]
        self.assertGreater(stats["moves"]["5"]["estimate"], 0.09)      # 1.02^5 - 1 ≈ 10.4%
        self.assertEqual(stats["ups"]["5"]["k"], stats["n"])
        self.assertTrue(stats["ups"]["5"]["distinguishable"])            # 10 of 10 up
        self.assertTrue(stats["moves"]["5"]["distinguishable"])

    def test_a_cluster_of_filings_counts_once(self):
        """S-12: filings cluster — a dozen insider forms on one day — and windows that
        overlap share the same price moves. JPMorgan's 670 insider-trade filings were
        52 separate moves; counted 670 times they read as a certain finding."""
        clusters = [base + extra for base in range(0, 180, 30) for extra in (0, 0, 1, 5, 16)]
        items = [{"ticker": "ZZZ", "form": "4", "label": "Insider trade", "what": "",
                  "date": (date(2024, 1, 2) + timedelta(days=d)).isoformat()} for d in clusters]
        r = build_desk.build_reactions(items, self.prices(1.01), TODAY)
        self.assertEqual([v["n"] for v in r.values()], [6])     # 30 filings, 6 moves
        self.assertEqual(next(iter(r.values()))["ups"]["5"]["n"], 6)

    def test_the_window_opens_before_the_session_the_filing_could_move(self):
        """MacKinlay (1997): the event's own day is in the window. Results filed at 7:00 move that
        morning's session; filed at 16:05, the next. Until 28 Sep 2026 every window opened at the
        close on the filing's date, which left out the session morning results moved."""
        store = {"SPY": {}, "ZZZ": {}}
        d = date(2024, 1, 1)
        days = []
        while len(days) < 300:
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        for i, day in enumerate(days):
            store["SPY"][day] = 100.0
            store["ZZZ"][day] = 100.0
        # each results day: +10% in its own session, flat after
        events = [days[25 * k + 10] for k in range(10)]
        level = 100.0
        for day in days:
            if day in events:
                level *= 1.10
            store["ZZZ"][day] = level
        def filed(day, hour):
            return {"ticker": "ZZZ", "form": "8-K", "what": "Results announced", "date": day,
                    "filed_at": f"{day}T{hour:02d}:00:00.000Z"}
        morning = build_desk.build_reactions([filed(e, 7) for e in events], store, date(2025, 6, 1))
        record = next(iter(morning.values()))
        self.assertAlmostEqual(record["moves"]["1"]["estimate"], 0.10, places=9)     # the session it moved
        evening = build_desk.build_reactions([filed(days[days.index(e) - 1], 16) for e in events], store,
                                             date(2025, 6, 1))
        self.assertAlmostEqual(next(iter(evening.values()))["moves"]["1"]["estimate"], 0.10, places=9)
        after = build_desk.build_reactions([filed(e, 17) for e in events], store, date(2025, 6, 1))
        self.assertAlmostEqual(next(iter(after.values()))["moves"]["1"]["estimate"], 0.0, places=9)

    def test_many_records_side_by_side_share_the_level_that_allows_for_them(self):
        """S-13: 108 records at 95% each would show about five patterns made by luck.
        Up after 10 of 12 is a finding alone (p = 0.039); beside 29 records that split
        evenly it is not."""
        def record(ticker):
            return [{"ticker": ticker, "form": "8-K", "what": "Results announced",
                     "date": (date(2024, 1, 2) + timedelta(days=21 * i)).isoformat()} for i in range(12)]
        tickers = ["T%02d" % i for i in range(30)]
        store = {prices.BENCHMARK: {}, **{t: {} for t in tickers}}
        level = {t: 100.0 for t in tickers}
        for i in range(400):
            day = (date(2024, 1, 1) + timedelta(days=i)).isoformat()
            store[prices.BENCHMARK][day] = 100.0
            for j, t in enumerate(tickers):
                store[t][day] = level[t]
                # each event's window lies inside one 21-day stretch; T00 falls in two
                # of its twelve stretches, the rest alternate
                up = (i // 21) not in (3, 7) if j == 0 else ((i // 21) + j) % 2
                level[t] *= 1.001 if up else 0.999
        alone = build_desk.build_reactions(record("T00"), store, TODAY)
        self.assertEqual(alone["T00|Announcement: Results announced"]["ups"]["5"]["k"], 10)
        self.assertTrue(alone["T00|Announcement: Results announced"]["ups"]["5"]["distinguishable"])
        crowd = build_desk.build_reactions([it for t in tickers for it in record(t)], store, TODAY)
        self.assertFalse(crowd["T00|Announcement: Results announced"]["ups"]["5"]["distinguishable"])
        self.assertFalse(crowd["T00|Announcement: Results announced"]["moves"]["5"]["distinguishable"])
        levels = {r["ups"]["5"]["confidence"] for r in crowd.values()} | {r["moves"]["5"]["confidence"] for r in crowd.values()}
        self.assertEqual(len(levels), 1)
        self.assertGreater(levels.pop(), uncertainty.CONFIDENCE)
        family = build_desk.reaction_family(crowd)
        self.assertEqual(family["records"], len(crowd))
        self.assertEqual(family["usual_level"], "95%")
        self.assertIsNone(build_desk.reaction_family({}))

    def test_the_reaction_note_is_written_from_data(self):
        note = template_function("reactionNote")
        for field in ("f.records", "f.usual_level", "f.by_luck_at_usual", "f.level"):
            self.assertIn(field, note)
        self.assertNotRegex(note, r"\b(95|108|99\.953)\b")

    def test_too_few_events_are_not_reported(self):
        """Below uncertainty.SMALLEST no record can be told from no reaction; the
        minimum is derived there, not chosen here."""
        r = build_desk.build_reactions(self.events(uncertainty.SMALLEST - 1), self.prices(1.01), TODAY)
        self.assertEqual(r, {})
        r = build_desk.build_reactions(self.events(uncertainty.SMALLEST), self.prices(1.01), TODAY)
        self.assertEqual(len(r), 1)
        self.assertNotIn("MIN_EVENTS", open(os.path.join(ROOT, "build_desk.py")).read())

    def test_categories_separate_insider_buys_from_other_insider_filings(self):
        buy = {"ticker": "ZZZ", "form": "4", "material": True, "date": "2024-02-01"}
        other = {"ticker": "ZZZ", "form": "4", "material": False, "date": "2024-02-01"}
        self.assertEqual(build_desk.event_category(buy), "Insider bought")
        self.assertEqual(build_desk.event_category(other), "Insider trade")

    def test_missing_prices_never_break_the_page(self):
        d = build_desk.compute({}, {}, TODAY, news={"tickers": ["ZZZ"], "items": self.events(8)}, prices={})
        self.assertEqual(d["news"]["count"], 8)
        self.assertTrue(all(i["reaction"] is None for i in d["news"]["items"]))


class SummaryTests(unittest.TestCase):
    CARD = {"ticker": "ZZZ", "name": "Zzz Corp", "revenue": 7.3e11, "revenue_growth": 0.205,
            "revenue_asof": "2026-06-30", "gross_margin": None, "operating_margin": 0.12,
            "net_margin": 0.181, "debt_to_equity": 0.23366, "cash": 7.82e10, "eps": 12.16,
            "price": {"close": 253.71, "as_of": "2026-09-18", "year": 0.115, "year_vs_market": -0.04},
            "next_earnings": {"date": "2026-10-28"}, "beats": uncertainty.proportion(2, 4),
            "results_reaction": {"n": 24, "window": 5,
                                 "moves": {"5": uncertainty.median([-0.018] * 12 + [0.01] * 10 + [-0.03, -0.02],
                                                                   expected=0)},
                                 "ups": {"5": uncertainty.against_chance(10, 24)}}}

    def test_figures_reach_the_model_already_formatted(self):
        f = summarise.facts_for(self.CARD)
        self.assertEqual(f["revenue"], screen.format_measure("revenue", 7.3e11))
        self.assertEqual(f["revenue"], "$730.0bn")
        self.assertEqual(f["revenue_growth_vs_year_before"], "+20.5%")
        self.assertEqual(f["debt_compared_with_equity"], "0.23")
        self.assertEqual(f["gross_margin"], "not reported")
        self.assertEqual(f["share_price"], "$253.71")
        self.assertIn("24 past announcements", f["after_past_results_announcements"])
        self.assertIn("up after 10 of them", f["after_past_results_announcements"])
        self.assertIn("cannot be told from no reaction", f["after_past_results_announcements"])
        self.assertIn("95% range", f["after_past_results_announcements"])
        self.assertEqual(f["beat_expectations"], "2 of 4 reports beat the consensus estimate, a 95% range "
                                                 "of 7% to 93%; too few to establish a rate")
        self.assertEqual(f["revenue_and_margins_cover"], "the period to 30 June 2026")
        quarters = summarise.facts_for(dict(self.CARD, revenue_basis="quarters"))
        self.assertEqual(quarters["revenue_and_margins_cover"], "the 12 months to 30 June 2026")
        annual = summarise.facts_for(dict(self.CARD, revenue_basis="annual", revenue_asof="2025-12-31"))
        self.assertEqual(annual["revenue_and_margins_cover"], "the financial year to 31 December 2025")
        blank = summarise.facts_for(dict(self.CARD, debt_to_equity=None, why={"debt_to_equity": "negative book equity"}))
        self.assertEqual(blank["debt_compared_with_equity"], "not shown: negative book equity")
        self.assertEqual(f["gross_margin"], "not reported")
        self.assertEqual(f["share_price_as_of"], "18 September 2026")
        self.assertEqual(f["next_results_date"], "28 October 2026")

    def test_no_advice_is_requested_and_invention_is_forbidden(self):
        prompt = summarise.SYSTEM.lower()
        self.assertIn("never say buy, sell, hold", prompt)
        self.assertIn("never invent", prompt)

    def test_the_key_never_reaches_the_page(self):
        card = dict(self.CARD)
        sent = {}

        class FakeResponse(io.BytesIO):
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                self_inner.close()

        def opener(req, timeout):
            sent["auth"] = req.headers.get("Authorization")
            sent["body"] = json.loads(req.data)
            return FakeResponse(json.dumps({"output_text": "A summary."}).encode())
        out = summarise.write_summary(card, key="secret-key", model="test-model", opener=opener)
        self.assertEqual(out["text"], "A summary.")
        self.assertEqual(sent["auth"], "Bearer secret-key")
        self.assertNotIn("secret-key", json.dumps(out))
        self.assertNotIn("secret-key", json.dumps(sent["body"]))


class FilingNoiseTests(unittest.TestCase):
    """A bank files an offering document for every note it issues."""

    def test_offering_documents_for_one_security_are_skipped(self):
        """JPMorgan had 95,941 424B2 pricing supplements on record. Kept, they buried
        every other filing and made each page build take four minutes."""
        for form in ("424B2", "424b3", "FWP"):
            self.assertTrue(news.skipped(form), form)
        # the decision to raise money is still there
        for form in ("S-3", "S-1", "8-K", "10-K", "4", "SC 13G"):
            self.assertFalse(news.skipped(form), form)

    def test_the_price_history_is_read_once_per_company_not_per_filing(self):
        """build_reactions rebuilt and re-sorted a company's whole price history for
        every filing — 116,641 times. The answer must not depend on that."""
        calls = []
        real = build_desk.price_store.series

        def counting(store, ticker, kind="a"):
            calls.append(ticker)
            return real(store, ticker, kind)
        days = {("2026-01-%02d" % d): {"c": 100.0 + d, "a": 100.0 + d} for d in range(1, 29)}
        prices = {"ZZZ": days, prices_module.BENCHMARK: days}
        items = [{"ticker": "ZZZ", "date": "2026-01-05", "form": "8-K", "label": "x"}
                 for _ in range(50)]
        build_desk.price_store.series = counting
        try:
            build_desk.build_reactions(items, prices, date(2026, 2, 1))
        finally:
            build_desk.price_store.series = real
        self.assertEqual(calls.count("ZZZ"), 1)


class WordingTests(unittest.TestCase):
    """Phase 10: what changed in Items 1A and 7 of the annual report, shown and never
    interpreted."""

    def filing(self, risks, discussion, toc=True):
        contents = ('<p>Item 1A. Risk Factors 12</p><p>Item 1B. Unresolved Staff Comments 30</p>'
                    '<p>Item 7. Management\'s Discussion 40</p><p>Item 7A. Market Risk 60</p>') if toc else ""
        return ('<html><body><ix:header><p>Item 1A hidden xbrl text</p></ix:header>'
                '<div style="display: none">Item 7 hidden</div>' + contents +
                '<p>ITEM 1A. RISK FACTORS</p>' + "".join(f"<p>{r}</p>" for r in risks) +
                '<p>Table of Contents</p><p>23</p><p>Acme | 2026 Form 10-K</p><p>Acme | 2026 Form 10-K</p>'
                '<p>ITEM 1B. UNRESOLVED STAFF COMMENTS</p><p>None.</p>'
                '<p>ITEM 7. MANAGEMENT\'S DISCUSSION AND ANALYSIS</p>' + "".join(f"<p>{d}</p>" for d in discussion) +
                '<table><tr><td>61,575</td><td>6%</td></tr></table>'
                '<p>ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES</p></body></html>')

    OLD = (["Our supply chain depends on one foundry. A disruption would hurt us.",
            "Competition is intense. Rivals may cut prices."],
           ["Revenue rose 10% in 2024. Demand was strong."])
    NEW = (["Our supply chain depends on one foundry. A disruption would hurt us.",
            "Export controls may bar sales to China. New licences may be refused.",
            "Competition is intense."],
           ["Revenue rose 34% in 2025. Demand was strong."])

    def test_a_section_is_the_longest_span_not_the_table_of_contents(self):
        found = diffs.extract(self.filing(*self.NEW))
        self.assertEqual(found["risk_factors"][:2], ["Our supply chain depends on one foundry.",
                                                     "A disruption would hurt us."])
        self.assertNotIn("hidden", " ".join(found["risk_factors"] + found["mdna"]))
        self.assertEqual(found["mdna"], ["Revenue rose 34% in 2025.", "Demand was strong."])

    def test_page_furniture_and_figure_cells_are_left_out(self):
        found = " ".join(diffs.extract(self.filing(*self.NEW))["risk_factors"] +
                         diffs.extract(self.filing(*self.NEW))["mdna"])
        for furniture in ("Table of Contents", "23", "Form 10-K", "61,575"):
            self.assertNotIn(furniture, found)

    def test_passages_added_and_removed_longest_first(self):
        old, new = diffs.extract(self.filing(*self.OLD)), diffs.extract(self.filing(*self.NEW))
        risks = diffs.compare(old["risk_factors"], new["risk_factors"])
        self.assertEqual(risks["added"], ["Export controls may bar sales to China. New licences may be refused."])
        self.assertEqual(risks["removed"], ["Rivals may cut prices."])
        self.assertEqual((risks["kept"], risks["sentences_before"], risks["sentences_now"]), (3, 4, 5))
        words = diffs.compare(old["mdna"], new["mdna"])
        self.assertEqual((words["added"], words["removed"]), (["Revenue rose 34% in 2025."], ["Revenue rose 10% in 2024."]))
        run = diffs.compare(["a b."], ["a b.", "Short one.", "x"])
        self.assertEqual(run["added"], ["Short one. x"])                 # consecutive changes: one passage

    def test_only_what_is_not_held_is_fetched(self):
        items = [{"ticker": "ACME", "form": "10-K", "date": d, "url": "u" + d} for d in ("2025-02-01", "2026-02-01")]
        docs = {"u2025-02-01": self.filing(*self.OLD), "u2026-02-01": self.filing(*self.NEW),
                "u2027-02-01": self.filing(*self.NEW)}
        calls = []
        fetch = lambda url, ua: calls.append(url) or docs[url]
        store = diffs.update(["ACME"], items, "ua", fetch, stored={})
        self.assertEqual(sorted(calls), ["u2025-02-01", "u2026-02-01"])
        diffs.update(["ACME"], items, "ua", fetch, stored=store)
        self.assertEqual(len(calls), 2)                                  # nothing new: nothing fetched
        diffs.update(["ACME"], items + [{"ticker": "ACME", "form": "10-K", "date": "2027-02-01", "url": "u2027-02-01"}],
                     "ua", fetch, stored=store)
        self.assertEqual(calls[2:], ["u2027-02-01"])                     # last year's text is reused
        self.assertEqual(store["companies"]["ACME"]["sections"]["risk_factors"]["added"], [])
        diffs.update(["OTHER"], [], "ua", fetch, stored=store, prune=False)
        self.assertIn("ACME", store["companies"])                        # one company asked for: the rest kept
        diffs.update([], items, "ua", fetch, stored=store)
        self.assertEqual(store["companies"], {})                         # no longer covered

    def test_a_section_that_is_only_its_title_is_not_found(self):
        """JPMorgan's Item 7 in the 10-K is its title alone, pointing to the annual report
        to shareholders; two identical pointers read as "nothing changed"."""
        pointer = ("<p>ITEM 7. MANAGEMENT'S DISCUSSION</p><p>Management's Discussion and Analysis of "
                   "Financial Condition and Results of Operations.</p><p>ITEM 8. STATEMENTS</p>")
        self.assertIsNone(diffs.extract(pointer)["mdna"])

    def test_a_section_not_in_the_main_document_says_so(self):
        bare = "<html><body><p>ITEM 7. MANAGEMENT'S DISCUSSION</p><p>See the annual report.</p><p>ITEM 8. STATEMENTS</p></body></html>"
        items = [{"ticker": "BANK", "form": "10-K", "date": d, "url": d} for d in ("2025-02-01", "2026-02-01")]
        store = diffs.update(["BANK"], items, "ua", lambda url, ua: bare, stored={})
        self.assertIn("incorporated from the annual report", store["companies"]["BANK"]["sections"]["risk_factors"]["why_not"])
        one = diffs.update(["BANK"], items[:1], "ua", lambda url, ua: bare, stored={})
        self.assertIn("fewer than two", one["companies"]["BANK"]["why_not"])

    def test_the_card_shows_the_wording_and_interprets_nothing(self):
        self.assertNotIn("text", diffs.for_card({"companies": {"A": {"text": {}, "sections": {}}}}, "A"))
        body = template_function("wordingBlock")
        self.assertNotRegex(body.lower(), r"worr|concern|bullish|bearish|positive|negative|red flag|warning")
        self.assertIn("wordingBlock(c.wording)", template_function("renderCompanies"))
        for personal in ("diffs.json", "theses.json"):
            self.assertIn(personal, open(os.path.join(ROOT, ".gitignore")).read())
            self.assertIn(f'"{personal}"', open(os.path.join(ROOT, "scripts", "privacy_scan.py")).read())

class CompanyNewsTests(unittest.TestCase):
    """Finnhub's company news for each followed company, beside how the
    shares moved that day; not part of the rating (headlines.py says why)."""
    NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    NAMES = {"AAA": "STORY CO", "BBB": "STORY CO", "CCC": "STORY CO"}     # each "Story n" names its company

    def row(self, i, when, **k):
        return dict({"id": i, "headline": f"Story {i}", "source": "Wire", "url": f"https://example.com/{i}",
                     "datetime": int(when.timestamp())}, **k)

    def test_a_story_needs_a_headline_a_time_and_a_web_link(self):
        at = self.NOW - timedelta(hours=1)
        kept = headlines._item(self.row(7, at, headline="  Big   news\n today ", source=" Reuters "))
        self.assertEqual(kept, {"id": "7", "headline": "Big news today", "source": "Reuters",
                                "url": "https://example.com/7", "at": "2026-09-26T11:00:00+00:00"})
        for bad in (dict(headline=""), dict(datetime=0), dict(datetime="x"), dict(url="javascript:alert(1)"),
                    dict(url="ftp://example.com/x"), dict(url="")):
            self.assertIsNone(headlines._item(self.row(1, at, **bad)), bad)
        self.assertIsNone(headlines._item("not a row"))
        self.assertEqual(headlines._item(self.row(None, at))["id"], "https://example.com/None")
        self.assertEqual(len(headlines._item(self.row(1, at, headline="x" * 999))["headline"]), headlines.LONGEST)
        self.assertIsNone(headlines._item(self.row(1, at, source=""))["source"])

    def test_each_update_asks_only_since_the_last_and_keeps_a_month(self):
        asked, served = [], {"AAA": [], "BBB": []}

        def fetch(path, key):
            asked.append(path)
            ticker = path.split("symbol=")[1].split("&")[0]
            return served[ticker]
        day = lambda n: self.NOW - timedelta(days=n)
        served["AAA"] = [self.row(1, day(40)), self.row(2, day(3)), self.row(3, day(1))]
        store = headlines.update(["aaa", "BBB"], key="k", fetch=fetch, now=self.NOW, names=self.NAMES)
        self.assertEqual(asked, ["company-news?symbol=AAA&from=2026-08-27&to=2026-09-26",
                                 "company-news?symbol=BBB&from=2026-08-27&to=2026-09-26"])
        self.assertEqual([i["id"] for i in store["companies"]["AAA"]], ["3", "2"])     # newest first; 40 days out
        self.assertEqual(store["companies"]["BBB"], [])
        asked.clear()
        served["AAA"] = [self.row(3, day(1), headline="Story 3, corrected"), self.row(4, day(0))]
        later = self.NOW + timedelta(days=2)
        store = headlines.update(["AAA"], stored=store, key="k", fetch=fetch, now=later, names=self.NAMES)
        self.assertEqual(asked, ["company-news?symbol=AAA&from=2026-09-26&to=2026-09-28"])  # since the last day
        self.assertEqual([i["headline"] for i in store["companies"]["AAA"]], ["Story 4", "Story 3, corrected", "Story 2"])
        self.assertNotIn("BBB", store["companies"])                                    # no longer followed
        served["CCC"] = [self.row(i, day(0) - timedelta(minutes=i)) for i in range(100, 100 + headlines.KEPT + 5)]
        one = headlines.update(["CCC"], stored=store, key="k", fetch=fetch, now=self.NOW, prune=False, names=self.NAMES)
        self.assertEqual(len(one["companies"]["CCC"]), headlines.KEPT)                  # the newest kept
        self.assertEqual(one["companies"]["CCC"][0]["id"], "100")
        self.assertEqual(one["companies"]["AAA"], store["companies"]["AAA"])           # the others untouched
        self.assertEqual(one["fetched"]["finnhub"]["AAA"], store["fetched"]["finnhub"]["AAA"])
        headlines.update(["BRK.B", "A&B"], key="k", fetch=lambda path, key: asked.append(path) or [], now=self.NOW)
        self.assertIn("symbol=A%26B&", asked[-1])

    def test_news_reaches_the_first_session_it_could_move(self):
        at = lambda d, hh, mm=0: datetime(2026, 9, d, hh, mm, tzinfo=timezone.utc)
        # New York on summer time (UTC-4): the close is 20:00 UTC
        self.assertEqual(prices.session_day(at(25, 11)), date(2026, 9, 25))            # Friday, pre-market
        self.assertEqual(prices.session_day(at(25, 19, 59)), date(2026, 9, 25))        # Friday, before the close
        self.assertEqual(prices.session_day(at(25, 20)), date(2026, 9, 28))            # Friday, after it: Monday
        self.assertEqual(prices.session_day(at(26, 15)), date(2026, 9, 28))            # Saturday
        self.assertEqual(prices.session_day(datetime(2026, 12, 7, 20, 30, tzinfo=timezone.utc)),
                         date(2026, 12, 7))                                              # winter: 15:30 in New York

    def test_each_day_of_news_carries_that_days_move_against_the_market(self):
        closes = lambda pairs: {d: {"c": v, "a": v} for d, v in pairs}
        store = {prices.BENCHMARK: closes([("2026-09-21", 100.0), ("2026-09-22", 101.0), ("2026-09-23", 101.0),
                                           ("2026-09-24", 100.0), ("2026-09-25", 100.0)]),
                 "AAA": closes([("2026-09-21", 50.0), ("2026-09-22", 53.0), ("2026-09-24", 54.0),
                                ("2026-09-25", 54.0)])}
        at = lambda d, hh: (datetime(2026, 9, d, hh, 0, tzinfo=timezone.utc)).isoformat()
        item = lambda i, when: {"id": i, "headline": f"Story {i}", "source": "Wire", "url": "https://example.com/" + i,
                                "at": when}
        news_store = {"companies": {"AAA": [item("a", at(22, 14)), item("b", at(21, 23)),   # both reach the 22nd
                                            item("c", at(24, 14)),                          # AAA has no close on the 23rd
                                            item("d", at(25, 21))],                         # after Friday's close
                                    "ZZZ": [item("z", at(22, 14))]},
                      "source": "Finnhub company news"}
        page = build_desk.build_headlines(news_store, store, ["AAA"], names=self.NAMES)
        days = {d["session"]: d for d in page["companies"]["AAA"]["days"]}
        self.assertEqual(list(days), ["2026-09-28", "2026-09-24", "2026-09-22"])       # newest first
        self.assertEqual([i["headline"] for i in days["2026-09-22"]["items"]], ["Story a", "Story b"])
        self.assertAlmostEqual(days["2026-09-22"]["move"], 0.06 - 0.01)
        self.assertEqual(days["2026-09-22"]["close_day"], "2026-09-22")
        self.assertIsNone(days["2026-09-24"]["move"])            # the market traded on the 23rd: two days' move
        self.assertEqual(days["2026-09-24"]["close_day"], "2026-09-24")
        self.assertEqual((days["2026-09-28"]["move"], days["2026-09-28"]["close_day"]), (None, None))   # no close yet
        self.assertEqual(page["companies"]["AAA"]["latest"], at(25, 21))
        self.assertNotIn("ZZZ", page["companies"])                                     # not followed
        self.assertEqual([i["headline"] for i in page["feed"]], ["Story d", "Story c", "Story a", "Story b"])
        self.assertEqual(page["feed"][0]["ticker"], "AAA")
        self.assertEqual((page["keep_days"], page["close"]), (headlines.KEEP_DAYS, prices.CLOSE))
        # a holiday: the story's session has no close, so the next close counts, and says so
        holiday = dict(store, **{prices.BENCHMARK: closes([("2026-09-21", 100.0), ("2026-09-23", 102.0)]),
                                 "AAA": closes([("2026-09-21", 50.0), ("2026-09-23", 50.0)])})
        page = build_desk.build_headlines({"companies": {"AAA": [item("h", at(22, 14))]}}, holiday, ["AAA"],
                                          names=self.NAMES)
        (only,) = page["companies"]["AAA"]["days"]
        self.assertEqual((only["session"], only["close_day"]), ("2026-09-22", "2026-09-23"))
        self.assertAlmostEqual(only["move"], -0.02)
        self.assertLessEqual(len(build_desk.build_headlines({"companies": {"AAA": [
            item(str(i), at(24, 14)) for i in range(build_desk.FEED_SHOWN + 5)]}}, store, ["AAA"], names=self.NAMES)["feed"]),
            build_desk.FEED_SHOWN)
        self.assertEqual(build_desk.build_headlines(None, {}, ["AAA"])["companies"]["AAA"]["days"], [])

    def test_the_news_never_enters_the_rating(self):
        with open(os.path.join(ROOT, "rating.py")) as f:
            self.assertNotIn("headlines", f.read())
        d = build_desk.compute(generate_demo_data.generate(TODAY), today=TODAY)
        self.assertIn("company_news", d)
        for card in d["companies"]:
            self.assertNotIn("news", card.get("rating") or {})

    def test_the_page_shows_it_on_each_card_and_in_its_own_section(self):
        page = page_source()
        self.assertIn("newsFold(c.ticker)", template_function("renderCompanies", page))
        self.assertIn("'renderCompanyNews'", page)
        self.assertIn("pages:['companies', 'news', 'filings']", page)
        for name in ("newsFold", "renderCompanyNews", "newsItem"):
            body = template_function(name, page)
            for start in [m.start() for m in re.finditer(r"<a ", body)]:
                self.assertIn('rel="noopener noreferrer"', body[start:body.index(">'", start)], name)
        fold = template_function("newsFold", page)
        self.assertIn("N.close", fold)                          # the close is prices.py's, not typed here
        self.assertIsNone(re.search(r"\b4 ?pm\b|16:00", fold))
        self.assertIn("N.keep_days", fold)
        source = inspect.getsource(server.Handler.update_research)
        self.assertIn('("News", lambda: (headlines.update(covered', source)
        self.assertIn("headlines", inspect.getsource(server.Handler.fetch_company))
        self.assertIn("headlines.json", open(os.path.join(ROOT, ".gitignore")).read().split())


class NewsSourcesTests(unittest.TestCase):
    """The user, 27 Sep 2026: news "filtered" to what concerns each company, from several
    sources ("all of them probably have a limit"), the FT among them. Only stories that
    name the company, each once, beside the day's move and whether it was unusual, and the
    company's own filings of that day."""
    NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

    def test_a_story_counts_only_if_it_names_the_company_early(self):
        self.assertEqual(headlines.search_names("NVDA", "NVIDIA CORP"), ["Nvidia"])
        self.assertEqual(headlines.search_names("AMZN", "AMAZON COM INC"), ["Amazon"])        # legal form dropped
        self.assertEqual(headlines.search_names("GOOGL", "Alphabet Inc."), ["Alphabet", "Google"])   # the press's name
        self.assertEqual(headlines.search_names("XYZ", None), ["XYZ"])
        self.assertIn("Meta", headlines.known_names("META", "Meta Platforms, Inc."))           # as headlines write it
        self.assertNotIn("Booking", headlines.search_names("BKNG", "Booking Holdings Inc."))   # never searched alone
        about = lambda ticker, name, headline, lede="": headlines.about({"headline": headline, "lede": lede}, ticker, name)
        self.assertTrue(about("NVDA", "NVIDIA CORP", "Nvidia shares jump"))
        self.assertTrue(about("MCD", "MCDONALDS CORP", "McDonald's raises prices"))
        self.assertTrue(about("NVDA", "NVIDIA CORP", "Nvidia\u2019s new chip"))                   # a possessive
        self.assertTrue(about("KO", "COCA COLA CO", "Coca-Cola beats estimates"))
        self.assertTrue(about("AMD", "ADVANCED MICRO DEVICES INC", "AMD unveils a chip"))      # the ticker, as written
        self.assertFalse(about("KO", "COCA COLA CO", "Ko-fi raises money"))                    # not in capitals: a word
        self.assertFalse(about("F", "FORD MOTOR CO", "F is for failure"))                      # one letter never counts
        words = lambda n: " ".join(f"w{i}" for i in range(n))
        self.assertTrue(about("NVDA", "NVIDIA CORP", "Stocks close higher", words(24) + " Nvidia"))    # the 25th word
        self.assertFalse(about("NVDA", "NVIDIA CORP", "Stocks close higher", words(25) + " Nvidia"))   # the 26th
        self.assertEqual(headlines.LEDE_WORDS, 25)                                              # Tetlock et al. (2008)
        kept = headlines._item({"id": 1, "headline": "Nvidia", "url": "https://x.example/1", "datetime": 1,
                                "summary": words(40)})
        self.assertEqual(len(kept["lede"].split()), headlines.LEDE_WORDS)                       # no more is kept

    RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>x</title>
      <item><title>Nvidia to sell chips in China - Financial Times</title><link>https://news.google.com/rss/articles/a</link>
        <pubDate>Fri, 25 Sep 2026 14:03:00 GMT</pubDate><source url="https://www.ft.com">Financial Times</source></item>
      <item><title>Nvidia supplier cuts outlook - Reuters</title><link>https://news.google.com/rss/articles/b</link>
        <pubDate>Fri, 25 Sep 2026 09:00:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>
      <item><title>5 chip stocks to buy - Some Blog</title><link>https://news.google.com/rss/articles/c</link>
        <pubDate>Fri, 25 Sep 2026 09:00:00 GMT</pubDate><source url="https://blog.example">Some Blog</source></item>
      <item><title>No link - Reuters</title><link>javascript:alert(1)</link>
        <pubDate>Fri, 25 Sep 2026 09:00:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>
    </channel></rss>"""

    def test_the_press_is_read_from_its_feed_and_nothing_else_passes_for_one(self):
        items = headlines.parse_rss(self.RSS)
        self.assertEqual([(i["headline"], i["source"]) for i in items],
                         [("Nvidia to sell chips in China", "Financial Times"), ("Nvidia supplier cuts outlook", "Reuters")])
        self.assertEqual(items[0]["at"], "2026-09-25T14:03:00+00:00")
        for body in (b"<!DOCTYPE html><html>Our systems have detected unusual traffic</html>", b"",
                     b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel/></rss>', b"<rss/>", b"not xml"):
            with self.assertRaises(headlines.PressError):
                headlines.parse_rss(body)

        def refused(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 429, "slow down", {}, None)
        with self.assertRaises(headlines.PressError):
            headlines.fetch_rss("https://news.google.com/rss/search?q=x", opener=refused)
        self.assertEqual([headlines.outlet(x) for x in ("Bloomberg.com", "WSJ", "Barron's", "FT.com", "Yahoo Finance")],
                         ["Bloomberg", "The Wall Street Journal", "Barron's", "Financial Times", None])

    def test_the_ft_is_searched_alone_and_each_search_since_the_last(self):
        asked = []

        def fetch(url):
            asked.append(urllib.parse.unquote(url.split("q=")[1].split("&")[0]))
            return self.RSS
        store = headlines.update_press(["NVDA"], stored={"companies": {"NVDA": [
            {"id": "f1", "headline": "Nvidia beats", "source": "Yahoo", "url": "https://x.example/f", "at": "2026-09-24T10:00:00+00:00"}]},
            "fetched": {"NVDA": "2026-09-24"}},                     # a store from before: Finnhub's fetch day
            names={"NVDA": "NVIDIA CORP"}, fetch=fetch, now=self.NOW, sleep=lambda s: None)
        self.assertEqual(asked, ['"Nvidia" site:ft.com when:30d',
                                 '"Nvidia" (site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:barrons.com '
                                 'OR site:marketwatch.com) when:30d'])                      # the first search: a month
        self.assertEqual([(i["headline"], i["via"]) for i in store["companies"]["NVDA"]],
                         [("Nvidia to sell chips in China", "press"), ("Nvidia supplier cuts outlook", "press"),
                          ("Nvidia beats", "finnhub")])                                     # Finnhub's kept beside
        self.assertEqual(store["fetched"], {"finnhub": {"NVDA": "2026-09-24"}, "press": {"NVDA": "2026-09-26"}})
        asked.clear()
        headlines.update_press(["NVDA"], stored=store, names={"NVDA": "NVIDIA CORP"}, fetch=fetch,
                               now=self.NOW + timedelta(days=2), sleep=lambda s: None)
        self.assertTrue(all(q.endswith("when:3d") for q in asked), asked)                  # since the last, that day too
        source = inspect.getsource(server.Handler.update_research)
        self.assertLess(source.index("headlines.update(covered"), source.index("headlines.update_press(covered"))
        self.assertIn('"headlines.json"), "press", ("News",))', source)   # both write the stories: one after the other
        self.assertIn("headlines.PressError", inspect.getsource(server.Handler.run_steps))

    def test_the_same_story_from_several_outlets_is_one_line(self):
        at = lambda h: datetime(2026, 9, 24, h, 0, tzinfo=timezone.utc).isoformat()
        store = {"companies": {"NVDA": [
            {"id": "1", "headline": "Nvidia beats estimates", "source": "Yahoo", "url": "https://y.example/1", "at": at(13), "via": "finnhub"},
            {"id": "2", "headline": "NVIDIA beats estimates!", "source": "Reuters", "url": "https://r.example/1", "at": at(14), "via": "press"},
            {"id": "3", "headline": "Nvidia's new chip", "source": "Yahoo", "url": "https://y.example/2", "at": at(12), "via": "finnhub"},
            {"id": "4", "headline": "Stocks close higher", "source": "Yahoo", "url": "https://y.example/3", "at": at(11), "via": "finnhub"},
            # the same words on another day are another story
            {"id": "5", "headline": "Nvidia beats estimates", "source": "Yahoo", "url": "https://y.example/4",
             "at": datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc).isoformat(), "via": "finnhub"}]}}
        page = build_desk.build_headlines(store, {}, ["NVDA"], names={"NVDA": "NVIDIA CORP"}, today=date(2026, 9, 26))
        stories = page["companies"]["NVDA"]["days"][0]["items"]
        self.assertEqual([s["headline"] for s in stories], ["NVIDIA beats estimates!", "Nvidia's new chip"])  # a round-up out
        first = stories[0]
        self.assertEqual((first["sources"], first["url"], first["press"], first["at"]),
                         (["Yahoo", "Reuters"], "https://r.example/1", "Reuters", at(13)))   # the press's link, the first time
        self.assertEqual(page["companies"]["NVDA"]["press"], 1)
        self.assertEqual([d["session"] for d in page["companies"]["NVDA"]["days"]], ["2026-09-24", "2026-09-22"])

    def closes(self, n, big_last=None):
        """n + 1 days of the market flat and the shares moving ±1% against it, alternately;
        the last move `big_last` when given."""
        start = date(2025, 1, 1)
        days = [(start + timedelta(days=i)).isoformat() for i in range(n + 1)]
        bench = {d: {"c": 100.0, "a": 100.0} for d in days}
        price, shares = 100.0, {}
        for i, d in enumerate(days):
            if i:
                price *= 1 + (big_last if (big_last is not None and i == n) else (0.01 if i % 2 else -0.01))
            shares[d] = {"c": price, "a": price}
        return {prices.BENCHMARK: bench, "AAA": shares}, days

    def test_a_day_is_unusual_only_outside_the_range_of_the_shares_own_days(self):
        store, days = self.closes(build_desk.NORMAL_DAYS + 1, big_last=0.05)
        moves = build_desk.excess_moves(prices.series(store, "AAA"), prices.series(store, prices.BENCHMARK))
        last = moves[-1]
        flag = build_desk.unusual(moves, last[0], last[1])
        self.assertTrue(flag["unusual"])
        self.assertAlmostEqual(flag["times"], 0.05 / flag["usual"])
        self.assertFalse(build_desk.unusual(moves, last[0], 0.015)["unusual"])       # inside 1.96 of about 1%
        self.assertIsNone(build_desk.unusual(moves[:build_desk.NORMAL_DAYS], moves[build_desk.NORMAL_DAYS - 1][0], 0.05))
        self.assertEqual(build_desk.NORMAL_DAYS, 250)                                # MacKinlay (1997)
        at = datetime.fromisoformat(days[-1] + "T14:00:00+00:00").isoformat()
        page = build_desk.build_headlines({"companies": {"AAA": [
            {"id": "1", "headline": "Story Co wins", "source": "Wire", "url": "https://x.example/1", "at": at}]}},
            store, ["AAA"], names={"AAA": "STORY CO"}, today=date.fromisoformat(days[-1]))
        (day,) = page["companies"]["AAA"]["days"]
        self.assertTrue(day["unusual"])
        self.assertTrue(page["feed"][0]["unusual"])                                  # the list can filter to it
        self.assertEqual(page["companies"]["AAA"]["unusual_days"], 1)
        self.assertEqual((page["normal_days"], page["level"], page["one_in"]), (250, "95%", 20))

    def test_the_companys_filings_sit_on_the_session_they_could_move(self):
        # the SEC writes New York's time with a "Z": 16:05 on a Thursday is after the close
        self.assertEqual(news.filed_moment("2026-09-24T16:05:00.000Z").astimezone(timezone.utc).isoformat(),
                         "2026-09-24T20:05:00+00:00")
        self.assertEqual(news.filed_moment("2026-12-07T16:05:00.000Z", clock=prices.USEastern())
                         .astimezone(timezone.utc).isoformat(), "2026-12-07T21:05:00+00:00")     # winter, no zone data
        for bad in ("2026-09-24", "", None, "late"):
            self.assertIsNone(news.filed_moment(bad))
        filing = lambda form, when, material=True, what="": {"ticker": "AAA", "form": form, "filed_at": when, "material": material,
                                                             "date": when[:10], "label": "Company announcement", "what": what,
                                                             "url": "https://www.sec.gov/x"}
        filings = [filing("8-K", "2026-09-24T16:05:00.000Z", what="Results announced; Documents attached"),
                   filing("10-Q", "2026-09-23T10:00:00.000Z"),
                   filing("4", "2026-09-23T11:00:00.000Z", material=False),
                   filing("8-K", "2026-09-26", what="Leadership change"),               # a Saturday, no time kept
                   filing("8-K", "2026-07-01T10:00:00.000Z", what="Other news")]        # older than the month
        filings[1]["label"] = "Quarterly report"
        page = build_desk.build_headlines({}, {}, ["AAA"], filings=filings, today=date(2026, 9, 26))
        days = {d["session"]: [f["headline"] for f in d["filings"]] for d in page["companies"]["AAA"]["days"]}
        self.assertEqual(days, {"2026-09-28": ["Leadership change"], "2026-09-25": ["Results announced"],
                                "2026-09-23": ["Quarterly report"]})
        self.assertIn("Google News (FT, press)", inspect.getsource(doctor.sources))
        self.assertIn("inside EDGAR", doctor.filing_hours([{"filed_at": "2026-09-24T06:01:36.000Z"},
                                                           {"filed_at": "2026-09-24T21:59:00.000Z"}]))
        self.assertIn("needs checking", doctor.filing_hours([{"filed_at": "2026-09-24T01:30:00.000Z"}]))

    def test_the_page_words_what_the_python_decides(self):
        page = page_source()
        fold, feed = template_function("newsFold", page), template_function("renderCompanyNews", page)
        for figure in ("N.normal_days", "N.level", "N.one_in", "N.lede_words", "N.outlets"):
            self.assertIn(figure, fold)
        self.assertIsNone(re.search(r"\b250\b|95%|\btwenty\b|\b25 words", fold))
        self.assertIn("unusualTag(d)", fold)
        self.assertIn("NEWS_KINDS", feed)
        self.assertIn('id="cnFilter"', page)
        for name in ("newsItem", "filingItem"):
            body = template_function(name, page)
            for start in [m.start() for m in re.finditer(r"<a ", body)]:
                self.assertIn('rel="noopener noreferrer"', body[start:body.index(">'", start)], name)


class PartlyReadTests(unittest.TestCase):
    """28 Sep 2026: a news source failing halfway through the companies lost every story
    read before it, so a limit met at the same place each half hour would have kept any
    from being stored."""
    NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    def story(self, ticker, n):
        return {"id": f"{ticker}-{n}", "headline": f"{ticker} Corp news {n}", "url": f"https://x.example/{ticker}/{n}",
                "at": "2026-09-27T10:00:00+00:00", "source": "Reuters"}

    def test_what_was_read_is_kept_and_the_least_lately_asked_go_first(self):
        asked = []

        def fetch_press(ticker, filed, days, fetch=None, sleep=None):
            asked.append(ticker)
            if ticker == "CCC":
                raise headlines.PressError("Google News asked the desk to slow down (HTTP 429)")
            return [self.story(ticker, 1)]
        real = headlines.fetch_press
        headlines.fetch_press = fetch_press
        try:
            names = {t: t + " Corp" for t in ("AAA", "BBB", "CCC", "DDD")}
            first = headlines.update_press(["AAA", "BBB", "CCC", "DDD"], stored={}, names=names, now=self.NOW)
            self.assertEqual(asked, ["AAA", "BBB", "CCC"])                    # nothing asked after the failure
            self.assertIn("HTTP 429", first[headlines.PARTLY])
            self.assertEqual([i["id"] for i in first["companies"]["AAA"]], ["AAA-1"])    # read before it: kept
            self.assertEqual(sorted(first["fetched"]["press"]), ["AAA", "BBB"])        # the rest still due
            asked.clear()
            first.pop(headlines.PARTLY)
            later = self.NOW + timedelta(minutes=30)
            headlines.update_press(["AAA", "BBB", "CCC", "DDD"], stored=first, names=names, now=later)
            self.assertEqual(asked[0], "CCC")                                    # the least lately asked first
        finally:
            headlines.fetch_press = real
        # the update step writes what was read, and says the rest failed
        handler = server.Handler.__new__(server.Handler)
        handler.folder = tempfile.mkdtemp()
        part = {"companies": {"AAA": []}, headlines.PARTLY: "Google News asked the desk to slow down"}
        failed = handler.run_steps((("News from the FT and the press", lambda: (dict(part), "headlines.json")),),
                                   lambda e: None, [])
        self.assertEqual(failed, [("News from the FT and the press", "Google News asked the desk to slow down")])
        self.assertEqual(headlines.load(os.path.join(handler.folder, "headlines.json")), {"companies": {"AAA": []}})


class BriefTests(unittest.TestCase):
    """27 Sep 2026: a company's week of news in a few lines, written when asked, from the
    headlines the page already shows and nothing else."""
    TODAY = date(2026, 9, 27)

    def told(self):
        story = lambda n, day: {"headline": f"Story {n}", "url": f"https://example.com/{n}", "at": day + "T14:00:00+00:00",
                                "sources": ["Reuters", "Financial Times"], "press": "Financial Times"}
        return {"ticker": "ZZZ", "days": [
            {"session": "2026-09-25", "move": -0.031, "unusual": True, "items": [story(1, "2026-09-25"), story(2, "2026-09-25")],
             "filings": [{"headline": "Results announced", "form": "8-K", "url": "https://sec.example/1"}]},
            {"session": "2026-09-22", "move": None, "items": [story(3, "2026-09-22")], "filings": []},
            {"session": "2026-09-10", "move": 0.01, "unusual": False, "items": [story(4, "2026-09-10")], "filings": []}]}

    def test_it_is_written_from_the_weeks_headlines_alone(self):
        told = self.told()
        days = brief.week(told, self.TODAY)
        self.assertEqual([d["session"] for d in days], ["2026-09-25", "2026-09-22"])      # the 10th is not this week
        asked = []

        def opener(req, timeout):
            asked.append(json.loads(req.data))
            return contextlib.closing(io.BytesIO(json.dumps({"output_text": "Headlines were about results."}).encode()))
        written = brief.write("ZZZ", "Zed Co", days, "95%", key="k", model="m", opener=opener)
        sent = asked[0]
        text = sent["input"][0]["content"][0]["text"]
        for said in ("Story 1", "Story 3", "Results announced (8-K)", "-3.1%", "outside the 95% range", "Reuters, Financial Times",
                     "25 September 2026", "not measured"):
            self.assertIn(said, text)
        self.assertNotIn("Story 4", text)                                  # older than the week
        self.assertNotIn("totalValue", text)                               # nothing of the account
        for rule in ("never say or suggest that a story caused", "never say buy, sell", "headlines, not the articles"):
            self.assertIn(rule, sent["instructions"].lower())
        self.assertEqual((written["text"], written["model"], written["headlines"]), ("Headlines were about results.", "m", 3))
        self.assertEqual((written["from"], written["to"]), ("2026-09-22", "2026-09-25"))
        self.assertEqual(written["stories"], brief.story_ids(days))
        self.assertIn("https://sec.example/1", written["stories"])
        # shown with how many stories came since, never with its list of them
        shown = brief.for_page(written, told, self.TODAY)
        self.assertNotIn("stories", shown)
        self.assertEqual(shown["new_since"], 0)
        told["days"][0]["items"].append({"headline": "Story 5", "url": "https://example.com/5", "sources": ["Wire"]})
        self.assertEqual(brief.for_page(written, told, self.TODAY)["new_since"], 1)
        self.assertIsNone(brief.for_page(None, told, self.TODAY))
        self.assertNotIn(".post(", open(os.path.join(ROOT, "brief.py")).read())
        self.assertNotIn("import execute", open(os.path.join(ROOT, "brief.py")).read())

    def test_the_endpoint_keeps_a_brief_for_the_same_stories(self):
        told = self.told()
        data = {"today": self.TODAY.isoformat(), "companies": [{"ticker": "ZZZ", "name": "Zed Co"}, {"ticker": "QUIET", "name": "Q"}],
                "company_news": {"level": "95%", "companies": {"ZZZ": told, "QUIET": {"days": []}}}}
        calls = []

        def write(ticker, name, days, level, **kw):
            calls.append((ticker, name, level))
            return {"text": "t", "model": "m", "written_at": "2026-09-27T10:00:00+00:00", "from": "2026-09-22",
                    "to": "2026-09-25", "stories": brief.story_ids(days), "headlines": 3}
        real = brief.write
        brief.write = write
        try:
            with tempfile.TemporaryDirectory() as folder:
                json.dump(data, open(os.path.join(folder, "desk_data.json"), "w"))
                handler = server.Handler.__new__(server.Handler)
                handler.folder = folder
                code, out = handler.write_brief({"ticker": "zzz"})
                self.assertEqual((code, out["ok"], calls), (200, True, [("ZZZ", "Zed Co", "95%")]))
                self.assertEqual(brief.load(folder)["ZZZ"]["stories"], brief.story_ids(brief.week(told, self.TODAY)))
                self.assertTrue(handler.write_brief({"ticker": "ZZZ"})[1]["cached"])           # the same stories: not asked again
                self.assertEqual(len(calls), 1)
                handler.write_brief({"ticker": "ZZZ", "refresh": True})                           # asked for again
                self.assertEqual(len(calls), 2)
                self.assertFalse(handler.write_brief({"ticker": "QUIET"})[1]["ok"])               # no news this week
                self.assertEqual(handler.write_brief({"ticker": "NOPE"})[0], 400)
                # the next build shows it on the company's card, with the week's count beside the news
                built = build_desk.compute({}, today=self.TODAY, news={"tickers": ["ZZZ"]}, briefs=brief.load(folder))
                card = next(c for c in built["companies"] if c["ticker"] == "ZZZ")
                self.assertEqual((card["brief"]["text"], card["brief"]["new_since"]), ("t", 0))
                self.assertEqual(built["company_news"]["week_days"], brief.WEEK_DAYS)
        finally:
            brief.write = real
        self.assertIn('path == "/brief"', inspect.getsource(server.Handler.do_POST))
        page = page_source()
        self.assertIn("briefBlock(ticker, n)", template_function("newsFold", page))
        self.assertIn("N.week_days", template_function("newsFold", page))               # the window is brief.py's
        self.assertIn("if (DATA.as_of) return", template_function("briefBlock", page))  # a past day writes nothing


if __name__ == "__main__":
    unittest.main()
