"""The page: one definition for every number it shows, its look, its wording, and the desk as of a past day."""
import base64
from support import *  # noqa: F401,F403


class MeasureDisplayTests(unittest.TestCase):
    """J-04: how a measure looks is declared once, by the module that owns it, and
    both the page and the command line format from that declaration."""

    KINDS = {"percent", "ratio", "money", "count", "per_share", "flag"}

    def test_every_offered_measure_declares_how_it_is_displayed(self):
        self.assertEqual(set(screen.MEASURE_DISPLAY), set(screen.measures({})))
        row = {"ticker": "Z", "shares_outstanding": [10.0], "net_income": [5.0],
               "equity": [50.0], "revenue": [80.0]}
        offered = set(value.measures(row, 10.0)) - set(value.TEXT_FIELDS)
        self.assertEqual(set(value.VALUE_DISPLAY), offered)
        for name, spec in {**screen.MEASURE_DISPLAY, **value.VALUE_DISPLAY}.items():
            self.assertIn(spec["kind"], self.KINDS, name)
            self.assertTrue(spec.get("label"), name)

    def test_the_declarations_reach_the_page_and_the_screen_file(self):
        shipped = build_desk.compute({})["measure_display"]
        self.assertEqual(shipped, {**screen.MEASURE_DISPLAY, **value.VALUE_DISPLAY, **bridge.BRIDGE_DISPLAY,
                                   **thesis.THESIS_DISPLAY, **uncertainty.UNCERTAINTY_DISPLAY, **rating.RATING_DISPLAY,
                                   **value.OWN_HISTORY_DISPLAY})
        source = open(os.path.join(ROOT, "screen.py")).read()
        self.assertIn('out["measure_display"] = MEASURE_DISPLAY', source)

    def test_no_name_is_declared_by_two_modules(self):
        owners = (screen.MEASURE_DISPLAY, value.VALUE_DISPLAY, bridge.BRIDGE_DISPLAY, thesis.THESIS_DISPLAY,
                  uncertainty.UNCERTAINTY_DISPLAY, rating.RATING_DISPLAY, value.OWN_HISTORY_DISPLAY)
        for i, a in enumerate(owners):
            for b in owners[i + 1:]:
                self.assertFalse(set(a) & set(b))

    def test_the_screener_does_not_format_a_percentage_as_a_raw_ratio(self):
        """The screener printed every column with the generic num(): 0.0018 for a
        return on assets the card showed as a percentage."""
        template = page_source()
        screener = template_function("renderScreener", template)
        self.assertNotIn("num(", screener)
        self.assertIn("formatMeasure(c, r.measures[c])", screener)
        self.assertNotIn("function num(", template)

    def test_a_card_and_a_screen_row_format_a_measure_through_one_function(self):
        """Return on assets read 5.8% on a card and 0.0018 on the screener."""
        template = page_source()
        self.assertIn("formatMeasure(name, m.value)", template_function("peerBlock", template))
        self.assertIn("formatMeasure(name, v[name])", template_function("valueBlock", template))
        self.assertIn("formatMeasure(name, c[name])", template_function("renderCompanies", template))
        for body in (template_function(f, template) for f in ("peerBlock", "valueBlock", "renderScreener")):
            self.assertNotRegex(body, r"(?<![A-Za-z_.])(pct1|pc|nm)\(")

    def test_every_measure_the_template_names_is_declared(self):
        template = page_source()
        declared = set(build_desk.measure_display())
        named = set(re.findall(r"(?:formatMeasure|measureLabel)\('([a-z_0-9]+)'", template))
        for listing in re.findall(r"\[((?:\s*'[a-z_0-9]+',?)+)\s*\]\s*\.map\(name => kv\(measureLabel", template):
            named |= set(re.findall(r"'([a-z_0-9]+)'", listing))
        self.assertTrue(named)
        self.assertEqual(named - declared, set())

    def test_the_page_and_the_command_line_print_the_same_string(self):
        """The one formatter exists twice only because the page and the command line
        are different languages. Both read the one declaration; this runs both."""
        template = page_source()
        block = template[template.index("/* formatMeasure:begin */"):template.index("/* formatMeasure:end */")]
        display = build_desk.measure_display()
        values = [None, 0.0, 0.125, -0.125, 0.0018, -0.0481, 0.0000404, 0.35, 2.855, -7.5,
                  999999.5, 950000.4, 3.1e9, -2.17e9, 1.017e12, 123456789.0, 1.0]
        cases = [[name, v] for name in sorted(display) for v in values]
        program = ("var DATA = {measure_display: %s};\n%s\n"
                   "var __out = JSON.stringify(%s.map(function(c){ return formatMeasure(c[0], c[1]); }));\n"
                   "(typeof process !== 'undefined') ? console.log(__out) : __out;"
                   % (json.dumps(display), block, json.dumps(cases)))
        printed = run_javascript(program)
        page = json.loads(printed)
        python = [screen.format_with(display[name], v) for name, v in cases]
        mismatched = [(c, p, q) for c, p, q in zip(cases, page, python) if p != q]
        self.assertEqual(mismatched, [])
        self.assertEqual(page[cases.index(["return_on_assets", 0.0018])], "0.2%")


class DeadCodeTests(unittest.TestCase):
    """K-05: a superseded function is a second copy waiting to be found — the next
    person to need a bootstrap p-value may find the one that tests the wrong
    statistic. So a function or constant nothing in the desk reads is deleted, and a
    test is not a reader: a function only its tests call is kept alive by them."""

    def test_nothing_is_defined_that_nothing_reads(self):
        folders = (ROOT, os.path.join(ROOT, "scripts"))
        files = [os.path.join(d, f) for d in folders for f in sorted(os.listdir(d)) if f.endswith(".py")]
        template = page_source()
        trees = {}
        for path in files:
            with open(path) as f:
                trees[path] = ast.parse(f.read())
        read = {}
        for tree in trees.values():
            for node in ast.walk(tree):
                name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                if name:
                    read[name] = read.get(name, 0) + 1
                if isinstance(node, ast.Constant) and isinstance(node.value, str):     # dispatched by name
                    for word in re.findall(r"[A-Za-z_]\w*", node.value):
                        read.setdefault("text:" + word, 1)
        unread = []
        for path, tree in trees.items():
            for node in tree.body:
                names = ([node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                         [t.id for t in node.targets if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else [])
                for name in names:
                    if name in ("main", "HERE") or name.startswith("__"):
                        continue
                    own = sum(1 for n in ast.walk(node) if isinstance(n, ast.Name) and n.id == name) \
                        if isinstance(node, ast.FunctionDef) else 0          # recursion is not a reader
                    if read.get(name, 0) - own <= 0 and "text:" + name not in read and name not in template:
                        unread.append(f"{os.path.basename(path)}:{node.lineno} {name}")
        self.assertEqual(unread, [])


class SuiteTests(unittest.TestCase):
    """K-06: "Ran 447 tests ... OK" means the same on every machine. No test skips —
    a check that cannot run here fails and says what is missing."""

    def test_no_test_can_skip(self):
        folder = os.path.join(ROOT, "tests")
        found = []
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py"):
                with open(os.path.join(folder, name)) as f:
                    found += [f"{name}:{i}" for i, line in enumerate(f, 1)
                              if re.search(r"\bskip(Test|If|Unless)\b|unittest\.skip|SkipTest", line)
                              and "re.search" not in line]
        self.assertEqual(found, [])


class TemplateQuantityTests(unittest.TestCase):
    """The one-definition rule covers the template: a quantity Python owns reaches the
    page as data, and the page never types in a copy — or a fallback guess."""

    COPIES = ("0.15%", "['5']", "95% range", "3 months", "11 sector",
              "|| 0.3)", "|| 0.8)", "'0.05'", "|| 2)", "|| 3)")

    def test_the_template_types_in_no_number_python_owns(self):
        template = page_source()
        self.assertEqual([c for c in self.COPIES if c in template], [])

    def test_the_research_page_gets_its_level_and_its_funds_as_data(self):
        built = build_desk.build_research({"universe": list(backtest.UNIVERSE),
                                           "confidence": uncertainty.CONFIDENCE})
        self.assertEqual(built["confidence"], uncertainty.CONFIDENCE)
        self.assertEqual(built["sector_funds"], [t for t in backtest.UNIVERSE if t != prices.BENCHMARK])
        self.assertIsNone(build_desk.build_research({})["confidence"])     # never assumed

    def test_the_interval_level_is_one_constant(self):
        source = open(os.path.join(ROOT, "backtest.py")).read()
        self.assertNotIn("0.025", source)
        self.assertNotIn("0.975", source)
        self.assertIn('"confidence": uncertainty.CONFIDENCE', open(os.path.join(ROOT, "research.py")).read())
        self.assertIn("uncertainty.CONFIDENCE", source)

    def reaction_store(self, days, market_days=None):
        start = date(2026, 1, 1)
        store = {"AAA": {}, prices.BENCHMARK: {}}
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            store["AAA"][d] = {"a": 100 + (i % 7)}
            if market_days is None or i < market_days:
                store[prices.BENCHMARK][d] = {"a": 100 + i / 3}
        return start, store

    def results(self, start, offsets):
        return [{"ticker": "AAA", "date": (start + timedelta(days=o)).isoformat(),
                 "form": "8-K", "category": "Announcement: Results announced"} for o in offsets]

    def test_every_window_counts_the_same_events(self):
        """S-01: a filing too recent for the 20-day window counted in the 1- and
        5-day figures, so "up in 17 of them" was out of a different set than the
        37 it was printed beside."""
        start, store = self.reaction_store(200)
        offsets = list(range(1, 148, 21)) + [185, 190, 195]    # the last three are too recent
        out = build_desk.build_reactions(self.results(start, offsets), store, start + timedelta(days=200))
        summary = next(iter(out.values()))
        self.assertEqual(summary["n"], 7)
        for w in build_desk.WINDOWS:
            self.assertEqual(summary["ups"][str(w)]["n"], summary["n"])
            self.assertEqual(summary["moves"][str(w)]["n"], summary["n"])

    def test_a_move_without_a_market_return_is_not_counted_as_one_against_it(self):
        """S-02: a missing market return was read as zero."""
        start, store = self.reaction_store(200, market_days=80)
        out = build_desk.build_reactions(self.results(start, range(0, 147, 21)), store, start + timedelta(days=200))
        n = next(iter(out.values()))["n"] if out else 0
        self.assertLess(n, 7)                                   # events after day 60 lack the market's 20 days

    def test_a_reaction_says_which_window_it_reports(self):
        self.assertIn(build_desk.HEADLINE_WINDOW, build_desk.WINDOWS)
        prices_store = {"AAA": {}, prices.BENCHMARK: {}}
        day = date(2026, 1, 1)
        for i in range(200):
            d = (day + timedelta(days=i)).isoformat()
            prices_store["AAA"][d] = {"a": 100 + i}
            prices_store[prices.BENCHMARK][d] = {"a": 100 + i / 2}
        items = [{"ticker": "AAA", "date": (day + timedelta(days=i)).isoformat(),
                  "form": "8-K", "category": "Announcement: Results announced"} for i in range(0, 150, 21)]
        out = build_desk.build_reactions(items, prices_store, day + timedelta(days=200))
        self.assertTrue(out)
        for summary in out.values():
            self.assertEqual(summary["window"], build_desk.HEADLINE_WINDOW)

    def test_the_cost_and_the_benchmark_are_each_defined_once(self):
        """paper.py kept its own 0.0015 and five modules spelled out "SPY"."""
        self.assertIs(paper.TRADE_COST, backtest.TRADE_COST)
        for name in ("paper.py", "build_desk.py", "research.py", "backtest.py", "value.py", "screen.py"):
            source = open(os.path.join(ROOT, name)).read()
            self.assertNotIn('"SPY"', source, name)
            self.assertNotIn("0.0015", source.replace("TRADE_COST = 0.0015", ""), name)
        self.assertEqual(open(os.path.join(ROOT, "backtest.py")).read().count("TRADE_COST = 0.0015"), 1)
        self.assertFalse(hasattr(build_desk, "BENCHMARK"))

    def test_the_practice_page_is_told_the_cost_it_pays(self):
        built = build_desk.build_paper({}, {}, date(2026, 9, 1))
        self.assertEqual(built["cost"], paper.TRADE_COST)

    def test_analyst_direction_has_no_cut_off_of_its_own(self):
        """S-03: a change under 0.05 was called "unchanged" — a threshold no source
        gives. Now any change visible at the places shown is reported, and both
        averages travel with the word."""
        def month(m, buy, hold):
            return {"period": f"2026-{m:02d}-01", "strongBuy": 0, "buy": buy, "hold": hold,
                    "sell": 0, "strongSell": 0}
        rows = [month(9, 21, 79), month(8, 20, 80), month(7, 20, 80), month(6, 20, 80)]
        out = analysts.for_company("A", "k", fetch=lambda path, key: rows)
        self.assertEqual(out["direction"], "more positive")          # 0.20 → 0.21
        self.assertEqual(out["score_places"], analysts.SCORE_PLACES)
        same = analysts.for_company("A", "k", fetch=lambda path, key: [month(9, 20, 80)] + rows[1:])
        self.assertEqual(same["direction"], "unchanged")
        source = open(os.path.join(ROOT, "analysts.py")).read()
        self.assertNotRegex(source, r"before\s*[<>]\s*-?0\.05")

    def test_analyst_direction_needs_the_whole_gap_it_names(self):
        """With two months of history the direction compared with last month while
        the page said "than 3 months ago"."""
        def month(m, buy):
            return {"period": f"2026-{m:02d}-01", "strongBuy": 0, "buy": buy, "hold": 5,
                    "sell": 0, "strongSell": 0}
        short = analysts.for_company("A", "k", fetch=lambda path, key: [month(9, 9), month(8, 1)])
        self.assertIsNone(short["direction"])
        full = analysts.for_company("A", "k", fetch=lambda path, key: [month(m, 9 if m == 9 else 1) for m in (9, 8, 7, 6)])
        self.assertEqual(full["direction"], "more positive")
        self.assertEqual(full["direction_months"], analysts.DIRECTION_MONTHS)


class CardHeaderTests(unittest.TestCase):
    """What sits beside the ticker is read first and read as the desk's own word."""

    def header(self):
        body = template_function("renderCompanies")
        header = body[body.index("'<div class=\"co-head\">'"):body.index("'<div class=\"co-sec\">")]
        return re.sub(r"/\*.*?\*/", "", header, flags=re.S)          # code, not comments

    def test_no_rating_label_appears_in_the_card_header(self):
        """Q4: "SBUX [Buy · 46 analysts]" put the consensus label above everything,
        and on ONC above a card that withholds every valuation figure. The label and
        its known skew belong together in "What analysts say"."""
        header = self.header()
        self.assertNotIn("verdict", header)
        self.assertNotRegex(header, r"'(Strong buy|Buy|Hold|Sell|Strong sell)")
        self.assertIn("analysts.analysts + ' analysts", header)
        self.assertIn("esc(a.verdict)", template_function("ratingBlock"))

    def test_one_report_is_a_report(self):
        """A past day with one scored quarter read "Last 1 reports: beat 10.5%"."""
        body = template_function("renderCompanies")
        self.assertIn("c.surprises.length === 1 ? 'Last report'", body)
        self.assertNotIn("'Last ' + c.surprises.length + ' reports: '", body)


class BlankReasonTests(unittest.TestCase):
    """Q2: SBUX's "Price to book –" and "Debt ÷ equity –" sat unexplained; the reason,
    negative book equity, was two sections later. A blank figure carries its reason
    at the dash, from the module that left it blank."""


    def test_a_median_with_no_range_is_set_apart(self):
        """S-32: with no range there is no bar, and the text ran on: "−2.2%too few..."."""
        program = ("%s\n%s\n%s\n%s\nvar __out = medianMove({estimate: -0.022, low: null, high: null}, v => (v * 100).toFixed(1) + '%%');\n"
                   "(typeof process !== 'undefined') ? console.log(__out) : __out;"
                   % (template_function("medianMove"), template_function("moveBar"), template_function("intervalBar"),
                      template_function("rangeText")))
        self.assertEqual(run_javascript(program), '<b>-2.2%</b> <span class="iv-txt">(too few to put a range on)</span>')
    def test_a_modules_reason_reads_as_a_sentence(self):
        """S-27: reasons are clauses ("fewer than two annual reports stored"); the page
        showed several bare, lowercase and unclosed. sentence() capitalises and closes
        them, and every block that shows one uses it."""
        program = ("%s\nvar __out = JSON.stringify([sentence('fewer than two annual reports stored'),"
                   " sentence('No bridge for a bank.'), sentence(''), sentence(null)]);\n"
                   "(typeof process !== 'undefined') ? console.log(__out) : __out;" % template_function("sentence"))
        self.assertEqual(json.loads(run_javascript(program)),
                         ["Fewer than two annual reports stored.", "No bridge for a bank.", "", ""])
        for block in ("bridgeBlock", "wordingBlock"):
            self.assertNotRegex(template_function(block), r"esc\(\w+\.why_not\)", block)
    def row(self, **figures):
        base = {"ticker": "Z", "shares_outstanding": [10.0], "net_income": [5.0], "equity": [50.0],
                "revenue": [80.0], "operating_income": [9.0], "dividends_paid": [-1.0]}
        base.update({k: [v] for k, v in figures.items()})
        return base

    def test_each_blank_ratio_says_why(self):
        why = value.measures(self.row(net_income=-5.0, equity=-20.0, dividends_paid=0.0), 10.0)["why"]
        self.assertIn("a loss", why["price_to_earnings"])
        self.assertEqual(why["price_to_book"], "negative book equity")
        self.assertEqual(why["dividend_yield"], "no dividend paid")
        self.assertNotIn("price_to_sales", why)                  # it has a value: no reason
        none = value.measures(self.row(), None)["why"]
        self.assertEqual(none["price_to_earnings"], "no price stored yet")

    def test_enterprise_value_needs_both_debt_and_cash(self):
        """S-08: missing debt counted as zero and understated enterprise value."""
        values = value.measures(self.row(cash=5.0), 10.0)                # no debt filed
        self.assertIsNone(values["enterprise_value"])
        self.assertEqual(values["why"]["enterprise_value"], "debt or cash not filed")
        both = value.measures(self.row(cash=5.0, debt=30.0), 10.0)
        self.assertEqual(both["enterprise_value"], 100.0 + 30.0 - 5.0)

    def test_a_withheld_figure_says_it_was_withheld(self):
        row = self.row(public_float=0.5)                           # market value 100, 200× the float
        values = value.value_company(row, 10.0)
        self.assertIsNone(values["price_to_earnings"])
        self.assertIn("withheld", values["why"]["price_to_earnings"])

    def test_the_top_of_the_card_says_why_a_figure_is_blank(self):
        def fetch(url, ua, **kw):
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            if tag in ("Assets", "StockholdersEquity", "LongTermDebtNoncurrent"):
                val = -7.5e9 if tag == "StockholdersEquity" else 3e10
                return {"units": {"USD": [{"end": "2026-06-28", "val": val, "form": "10-Q"}]}}
            return None
        out = fundamentals.for_company("SBUX", 1, "ua", fetch=fetch)
        self.assertEqual(out["why"]["debt_to_equity"], "negative book equity")
        self.assertEqual(out["why"]["gross_margin"], "no revenue filed")

    def test_both_blocks_print_the_reason_at_the_dash(self):
        self.assertIn("withReason(formatMeasure(name, v[name]), v.why, name, v.withheld)", template_function("valueBlock"))
        self.assertIn("withReason('–', c.why, name, c.withheld)", template_function("renderCompanies"))

    def test_only_a_figure_the_desk_declined_is_marked_withheld(self):
        """Phase 5's --withheld is for a figure the desk refuses to show; a figure the
        company never filed is a plain dash. The owning module says which."""
        values = value.measures(self.row(net_income=-5.0, equity=-20.0, dividends_paid=0.0), 10.0)
        self.assertEqual(sorted(values["withheld"]), ["price_to_book", "price_to_earnings"])
        self.assertIn("dividend_yield", values["why"])                  # no dividend: a fact, not withheld
        self.assertEqual(value.measures(self.row(), None)["withheld"], [])
        basis = value.value_company(self.row(public_float=0.5), 10.0)
        self.assertTrue(set(value.FROM_MARKET_CAP) <= set(basis["withheld"]))
        why, withheld = fundamentals._why_blank({"revenue": 5.0, "equity": -1.0, "cash_stale": True})
        self.assertEqual(withheld, ["cash", "debt_to_equity"])
        self.assertEqual(why["gross_margin"], "not reported")          # never filed: not withheld
        program = ("%s\nvar __out = [withReason('–', {a: 'negative book equity', b: 'not reported'}, 'a', ['a']),"
                   " withReason('–', {a: 'x', b: 'not reported'}, 'b', ['a'])].join('|');\n"
                   "(typeof process !== 'undefined') ? console.log(__out) : __out;"
                   % template_function("withReason").replace("esc(reason)", "reason"))
        printed = run_javascript(program)
        held, plain = printed.split("|")
        self.assertIn('class="withheld"', held)
        self.assertNotIn("withheld", plain)


class ScreenerPageTests(unittest.TestCase):
    """Phase 4: the screener's rows can be read — ordered by the question asked, with
    sector and size beside them — and its coverage comes first."""

    def test_names_are_made_readable_and_nothing_else_is_changed(self):
        cases = {"ABBOTT LABORATORIES": "Abbott Laboratories", "Airbnb, Inc.": "Airbnb, Inc.",
                 "EQT CORP": "EQT Corp", "AT&T INC.": "AT&T Inc.", "ACUITY INC. (DE)": "Acuity Inc.",
                 "U.S. BANCORP \\DE\\": "U.S. Bancorp", "O'REILLY AUTOMOTIVE INC": "O'Reilly Automotive Inc",
                 "BANK OF THE JAMES FINANCIAL GROUP INC": "Bank of the James Financial Group Inc",
                 "VANGUARD ETF TRUST": "Vanguard ETF Trust", "VERISIGN INC/CA": "Verisign Inc",
                 "IDEXX LABORATORIES INC /DE": "Idexx Laboratories Inc",
                 "NOVO NORDISK A/S": "Novo Nordisk A/S",
                 "VERTEX PHARMACEUTICALS INC / MA": "Vertex Pharmaceuticals Inc",
                 "SOUTHERN COPPER CORP/": "Southern Copper Corp", "Alight, Inc. / Delaware": "Alight, Inc.",
                 "TROOPS, INC. /CAYMAN ISLANDS/": "Troops, Inc.", "TRICO BANCSHARES /": "Trico Bancshares",
                 "CULLEN/FROST BANKERS, INC.": "Cullen/Frost Bankers, Inc.", "DATA I/O CORP": "Data I/O Corp",
                 "M/I HOMES, INC.": "M/I Homes, Inc.", "20/20 BIOLABS, INC.": "20/20 Biolabs, Inc.",
                 "KEYCORP /NEW/": "Keycorp", "MELAR ACQUISITION CORP. I/CAYMAN": "Melar Acquisition Corp. I",
                 "ZIONS BANCORPORATION, NATIONAL ASSOCIATION /UT/": "Zions Bancorporation, National Association",
                 "AMERICA MOVIL SAB DE CV/": "America Movil SAB de CV", "Q/C TECHNOLOGIES, INC.": "Q/C Technologies, Inc.",
                 "DIODES INC /DEL": "Diodes Inc", "ARM HOLDINGS PLC /UK": "ARM Holdings PLC",
                 "IMPERIAL PETROLEUM INC./MARSHALL ISLANDS": "Imperial Petroleum Inc."}
        for filed, shown in cases.items():
            self.assertEqual(universe.display_name(filed), shown)
        source = open(os.path.join(ROOT, "build_desk.py")).read()
        self.assertIn("universe.display_name(", source)          # the cards use the same one
        self.assertNotIn(".title()", source)

    def test_each_row_carries_its_sector_and_its_filed_size(self):
        store = {"companies": {"AAA": {"ticker": "AAA", "name": "ALPHA CO", "cik": 7, "revenue": [100.0],
                                       "net_income": [10.0], "assets": [200.0], "public_float": [500.0]}}}
        out = context.for_screen(screen.run(["net_margin>0"], store, limit=None), codes={7: 3571})
        row = out["results"][0]
        self.assertEqual((row["sector"], row["public_float"], row["name"]), ("Manufacturing", 500.0, "Alpha Co"))
        self.assertIn("public_float", screen.MEASURE_DISPLAY)     # a size a condition can use too

    def test_the_endpoint_returns_every_match_so_any_column_resorts_all_of_them(self):
        source = open(os.path.join(ROOT, "server.py")).read()
        self.assertIn("limit=None", source)
        self.assertIn("context.for_screen(out, codes)", source)

    def test_the_coverage_is_stated_before_the_count(self):
        body = template_function("renderScreener")
        self.assertLess(body.index("could be judged"), body.index("companies match"))
        self.assertNotIn('<span class="faint">The rest are not failures', body)

    def test_fifty_rows_at_a_time(self):
        template = page_source()
        self.assertIn("const SC_PAGE = 50;", template)
        self.assertIn("ordered.slice(0, scShown)", template_function("renderScreener", template))
        self.assertIn("sortedResults(", template_function("renderScreener", template))


class PhoneTableTests(unittest.TestCase):
    def test_the_peer_table_restacks_at_phone_width_with_every_label(self):
        """J-09: at phone width the table cut to two columns, the header to "PEER
        MEDIA", with no sign that the rest existed."""
        template = page_source()
        css = template[template.index("  .peer-tbl td:nth-child(2)"):template.index("  .sc-in{")]
        self.assertIn("@media (max-width:640px)", css)
        self.assertIn("content:attr(data-label)", css)
        body = template_function("peerBlock", template)
        for label in ("This company", "Peer median", "Where it stands", "Reported by"):
            self.assertIn(f'data-label="{label}"', body)

    def test_the_screener_table_shows_when_it_scrolls(self):
        self.assertIn('class="scroll-x"', template_function("renderScreener"))


class ScoreLineTests(unittest.TestCase):
    def test_the_f_score_is_always_out_of_nine(self):
        """J-08: "Piotroski F-score 5 of 8 (1 signals unknown)" — out of the number
        computable, which varies by company, and "1 signals"."""
        body = template_function("scoreBlock")
        self.assertIn("' of ' + f.signals.length", body)
        self.assertNotIn("f.out_of", body)
        self.assertNotIn("signals unknown", body)
        self.assertIn("' unknown</span>'", body)


class PeriodLabelTests(unittest.TestCase):
    """J-07: SBUX showed operating margin 7.8% at the top and 7.9% in the peer table
    under the same label. Each label now says which period it covers."""

    def test_the_top_of_the_card_says_what_period_each_figure_covers(self):
        body = template_function("topPeriod")
        self.assertIn("'last 12 months'", body)
        self.assertIn("'year to '", body)                 # an annual report is not the last 12 months
        card = template_function("renderCompanies")
        self.assertIn("topPeriod(c, name)", card)

    def test_the_basis_comes_from_how_the_figure_was_built(self):
        quarters = [{"start": f"2025-{m:02d}-01", "end": f"2025-{m + 2:02d}-28", "val": 1.0, "form": "10-Q"}
                    for m in (1, 4, 7, 10)]
        self.assertEqual(fundamentals._trailing(quarters)[3], "quarters")
        annual = [{"start": "2025-01-01", "end": "2025-12-31", "val": 4.0, "form": "10-K"}]
        self.assertEqual(fundamentals._trailing(annual)[3], "annual")

    def test_the_peer_table_labels_its_filed_year(self):
        body = template_function("peerBlock")
        self.assertIn("' filing)</span>'", body)


class UnfollowAfterFollowTests(unittest.TestCase):
    """Where it was followed, an Unfollow is offered at once: in the follow box while
    it loads and after, and in place of each Follow button. No question asked: following again is one
    click, and the dates are kept in `past` either way (news.unfollow)."""

    def test_the_follow_box_and_every_follow_button_offer_it(self):
        page = page_source()
        say = page[page.index("const wlSay = "):page.index("async function saveWatchlist")]
        self.assertIn('data-unfollow="\' + esc(wlJust)', say)
        self.assertIn("!DATA.as_of", say)                               # a past day changes nothing
        load = template_function("loadCompany", page)
        self.assertIn("wlJust = ticker", load)
        self.assertIn("if (wlJust === ticker) wlSay(text)", load)       # unfollowed while loading: quiet
        self.assertIn("if (ev.built) reloadData()", load)               # its figures shown before the rest
        self.assertIn("wlJust = null", template_function("saveWatchlist", page))
        button = template_function("followButton", page)
        self.assertIn('data-unfollow="\' + esc(ticker)', button)
        self.assertIn("DATA.as_of ? ''", button)
        self.assertIn("saveWatchlist({unfollow: ticker})", template_function("unfollow", page))
        self.assertRegex(page, r"closest\('\[data-unfollow\]'\)[\s\S]{0,60}!DATA\.as_of\) unfollow\(")
        self.assertNotIn("confirm(", template_function("unfollow", page))


class CoverageCardTests(unittest.TestCase):
    """Phase 6: each card says how long the company has been followed, why, and how
    many notes the user has written on it."""

    def test_a_card_carries_its_coverage_age_and_notes(self):
        rows = [{"ticker": "AMD", "note": "bought on the results"}, {"ticker": "AMD", "note": ""},
                {"ticker": "KO", "note": "dividend"}, {"ticker": "AMD", "note": "trimmed"}]
        self.assertEqual(build_desk.notes_by_ticker(rows), {"AMD": 2, "KO": 1})
        coverage = {"tickers": ["AMD"], "coverage": {"AMD": {"followed_at": "2026-06-22", "why": "AI accelerators"}}}
        cv = build_desk.coverage_of("AMD", coverage, {"AMD": 2}, date(2026, 9, 24))
        self.assertEqual(cv, {"followed_at": "2026-06-22", "days": 94, "notes": 2, "theses": 0})   # a stored reason unread
        theses = [{"ticker": "AMD"}, {"ticker": "KO"}, {"ticker": "AMD"}]
        self.assertEqual(build_desk.coverage_of("AMD", coverage, {}, date(2026, 9, 24), theses)["theses"], 2)
        news_data = {"tickers": ["AMD"], "companies": {"AMD": "ADVANCED MICRO DEVICES INC"}, "items": []}
        d = build_desk.compute({}, {}, date(2026, 9, 24), news=news_data, prices={}, coverage=coverage)
        self.assertEqual(d["companies"][0]["coverage"]["days"], 94)
        self.assertEqual(d["news"]["max_coverage"], news.MAX_COVERAGE)

    def test_the_page_says_it_in_words_and_takes_the_cap_from_data(self):
        line = template_function("coverageLine")
        for part in ("'Followed for '", "' notes'", "'Followed since before the desk kept dates'"):
            self.assertIn(part, line)
        self.assertNotIn("reason not recorded", line)                  # none is asked for
        follow = template_function("follow")
        self.assertIn("N.max_coverage", follow)
        self.assertNotRegex(follow, r"\b15\b")
        self.assertIn('value="" disabled selected', follow)          # nothing replaced by default
        self.assertIn("$('fwOut').required = true", follow)
        self.assertIn("loadCompany(ticker)", follow)                  # loaded at once, nothing to press
        self.assertNotIn("fwWhy", page_source())
        self.assertIn("coverageLine(c.coverage, c.ticker, c)", template_function("renderCompanies"))
        # a company held and not followed says so, and is one click from being followed; a
        # followed one, one click from being stopped
        self.assertIn("data-follow-held", line)
        self.assertIn('data-remove="', line)

    def test_a_holding_is_covered_without_counting_toward_the_cap(self):
        """27 Sep 2026: a share held and not followed had no filings, news or results dates."""
        source = inspect.getsource(server.Handler.update_research)
        self.assertIn("covered = watchlist + also", source)
        for step in ("news.refresh(covered", "headlines.update(covered", "headlines.update_press(covered",
                     "fundamentals.update(\n                covered", "earnings.update(\n                covered",
                     "analysts.update(covered", "prices.fetch_latest(covered)"):
            self.assertIn(step.replace("\\n", "\n"), source, step)
        self.assertIn("held=also", source)                              # the filings store knows which
        raw = generate_demo_data.generate(TODAY)
        news_data = {"tickers": ["KO", "AAPL"], "held": ["AAPL"], "items": []}
        d = build_desk.compute(raw, today=TODAY, news=news_data,
                               coverage={"tickers": ["KO"], "coverage": {"KO": {"followed_at": "2026-09-01"}}})
        cards = {c["ticker"]: c for c in d["companies"]}
        self.assertEqual((cards["KO"]["followed"], cards["AAPL"]["followed"]), (True, False))
        self.assertTrue(cards["AAPL"]["held"])
        self.assertEqual(d["news"]["followed"], ["KO"])
        # the coverage list never takes in a company only held
        with tempfile.TemporaryDirectory() as folder:
            json.dump(news_data, open(os.path.join(folder, "news_data.json"), "w"))
            handler = server.Handler.__new__(server.Handler)
            handler.folder = folder
            self.assertEqual(news.load_watchlist(handler.coverage_file()), ["KO"])


class AsOfTests(unittest.TestCase):
    """Phase 11: the desk as it was on a past day, from only what was knowable then."""

    DAY = "2026-06-01"
    FUTURE = "2026-08-03"                  # after DAY, before the real today of these tests
    MARK = "FUTR"                          # a ticker, text or id that exists only in the future

    def inputs(self, future_in=None, undated=False):
        """Every store with an observation before DAY; the one named also gets one after
        it — or, with `undated`, one with no date at all, which cannot be placed (K-03)."""
        f = future_in
        w = None if undated else self.FUTURE              # the seeded observation's date
        at = lambda suffix: w + suffix if w else None
        days = [(date(2026, 1, 2) + timedelta(days=i)).isoformat() for i in range(240)]
        series = {d: {"c": 100.0 + i, "a": 100.0 + i} for i, d in enumerate(days)}
        before = {d: v for d, v in series.items() if d <= self.DAY}
        order = lambda oid, ticker, when: {"order": {"id": oid, "ticker": ticker + "_US_EQ", "side": "BUY", "quantity": 1,
                                                    "filledQuantity": 1, "createdAt": when and when + "T10:00:00Z", "status": "FILLED"},
                                          "fill": {"id": oid, "quantity": 1, "price": 10.0, "filledAt": when and when + "T10:00:01Z",
                                                   "walletImpact": {"netValue": -10.0, "fxRate": 1, "taxes": []}}}
        facts = {"revenue": [{"start": "2025-01-01", "end": "2025-12-31", "val": 800.0, "form": "10-K", "filed": "2026-02-10"}]
                 # ended before the day, filed after it: the case that is easy to get wrong
                 + ([{"start": "2025-04-01", "end": "2026-03-31", "val": 4242e8, "form": "10-K", "filed": w}] if f == "fundamentals" else [])}
        return {
            "raw": {"env": "demo", "synced_at": at("T09:00:00Z") if f == "raw" else "2026-05-30T09:00:00Z",
                    "summary": {"totalValue": 4242.0 if f == "raw" else 1000.0, "cash": {"availableToTrade": 1.0},
                                "investments": {}},
                    "positions": [], "orders": [order("o1", "ZZZ", "2026-03-02")] + ([order("o2", self.MARK, w)] if f == "raw" else []),
                    "dividends": [{"ticker": self.MARK + "_US_EQ", "amount": 42.42, "paidOn": at("T00:00:00Z")}] if f == "raw" else [],
                    "transactions": [{"type": "DEPOSIT", "amount": 4242.0, "dateTime": at("T00:00:00Z"),
                                      "reference": self.MARK}] if f == "raw" else []},
            "journal": {"o1": {"note": ("seeded-only note" if f == "journal" else "kept"),
                               "updated": at("T10:00:00Z") if f == "journal" else "2026-03-03T10:00:00Z"}},
            # the filings store lists every company covered at the last refresh
            "news": {"tickers": ["ZZZ"] + ([self.MARK] if f == "coverage" else []), "companies": {"ZZZ": "ZZZ CORP"},
                     "items": [{"ticker": "ZZZ", "form": "8-K", "label": "Company announcement", "what": "x", "date": "2026-04-01",
                                "url": "https://www.sec.gov/a", "material": True}]
                     + ([{"ticker": "ZZZ", "form": "8-K", "label": "Company announcement", "what": "seeded-only filing",
                          "date": w, "url": "https://www.sec.gov/b", "material": True}] if f == "news" else [])
                     # a company covered only later: its filings, dated before the day, are
                     # not the desk's on that day either (S-33)
                     + ([{"ticker": self.MARK, "form": "8-K", "label": "Company announcement", "what": "seeded-only filing",
                          "date": "2026-04-02", "url": "https://www.sec.gov/c", "material": True}] if f == "coverage" else [])},
            # a close is keyed by its day; an undated one is keyed by nothing that is a day
            "prices": {"ZZZ": (dict(before, **{w or "": {"c": 4242.0, "a": 4242.0}}) if f == "prices" else before),
                       prices.BENCHMARK: before},
            # stored as fundamentals.fetch leaves it: today's figures, and the facts behind them
            "fundamentals": {"companies": {"ZZZ": dict(fundamentals.derive("ZZZ", 1, facts, {"revenue": "Revenues"}),
                                                       facts=facts, tags={"revenue": "Revenues"})}},
            "earnings": {"companies": {"ZZZ": {"history": [{"date": w, "actual": 42.42, "estimate": 1.0, "surprise_pct": 42.42, "beat": True}]
                                                          if f == "earnings" else [],
                                               "next": {"date": w} if f == "earnings" else None}}},
            "analysts": {"companies": {"ZZZ": {"as_of": w, "verdict": "seeded-only rating", "analysts": 3,
                                               "counts": {"strongBuy": 1, "buy": 1, "hold": 1, "sell": 0, "strongSell": 0}}}
                         if f == "analysts" else {}},
            "summaries": {"ZZZ": {"text": "seeded-only summary", "written_at": at("T08:00:00Z")}} if f == "summaries" else {},
            "paper": {"cash": 10000.0, "start_cash": 10000.0, "positions": {}, "started": "2026-03-01",
                      "trades": ([{"id": "p2", "date": w, "ticker": self.MARK, "side": "BUY", "quantity": 1.0,
                                   "price": 5.0, "value": 5.0, "fee": 0.01, "realised": None, "reason": ""}] if f == "paper" else [])},
            "research": {"generated_at": at("T00:00:00Z"), "tested": 4242} if f == "research" else {},
            "universe": {"built": w if f == "universe" else "2026-05-01", "years": 1,
                         "companies": {"ZZZ": {"ticker": "ZZZ", "cik": 1, "name": "seeded-only universe" if f == "universe" else "Z",
                                               "revenue": [800.0], "assets": [1000.0]}}},
            "coverage": {"tickers": ["ZZZ"] + ([self.MARK] if f == "coverage" else []),
                         "coverage": dict({"ZZZ": {"followed_at": "2026-02-01", "why": "kept"}},
                                          **({self.MARK: {"followed_at": w, "why": "seeded-only"}} if f == "coverage" else {})),
                         # followed and dropped since: shown only if followed by the day
                         "past": [{"ticker": self.MARK + "P", "followed_at": w, "why": "seeded-only",
                                   "stopped_at": "2026-09-01"}] if f == "coverage" else []},
            "theses": [{"id": "t1", "ticker": "ZZZ", "written": w, "after": "2026-03-31", "due": "2026-08-10",
                        "revenue_direction": "up", "revenue_change": None, "margin_direction": "up",
                        "reason": "seeded-only thesis", "confidence": 0.6}] if f == "theses" else [],
            # a rating given and logged: known from the day it was given
            "ratings_log": [{"ticker": self.MARK, "date": w, "label": "Buy", "place": 90.0,
                             "close_day": w, "close": 42.42, "method": rating.METHOD}] if f == "ratings_log" else [],
            # the exchange list the rating's breakpoints come from: known from when it was fetched
            "listings": {"exchanges": {f"L{i:04d}": "NYSE" for i in range(4242)}, "updated_at": w}
                        if f == "listings" else {},
            # a price taken at a refresh, after the close: known from when it was taken
            "quotes": {"quotes": {"ZZZ": {"price": 4242.0, "at": at("T20:30:00Z")}}} if f == "quotes" else {},
            # the rating's fixed sample: known from the day it was drawn
            "rating_sample": {"tickers": [self.MARK] + [f"S{i:04d}" for i in range(4241)], "drawn_at": at("T08:00:00Z"),
                              "seed": 1, "size": 4242} if f == "rating_sample" else {},
            # a plan before a trade: known from when it was written
            "plans": {"plans": [{"id": "p1", "written": at("T09:00:00Z"), "ticker": self.MARK, "side": "BUY",
                                 "why": "seeded-only plan", "wrong_if": "seeded-only", "review_by": "2026-12-01"}]}
                     if f == "plans" else {},
            # what each source did at the last update: today's, never a past day's
            "health": {"market": {"at": at("T10:00:00Z"), "steps": {"seeded-only step": {
                "ok": False, "at": at("T10:00:00Z"), "seconds": 1.0, "why": "seeded-only", "last_ok": None}}}}
                      if f == "health" else {},
            # the week's news in brief: known from when it was written
            "briefs": {"ZZZ": {"text": "seeded-only brief", "model": "m", "written_at": at("T12:00:00Z"),
                               "from": "2026-05-25", "to": "2026-05-29", "stories": ["https://example.com/b1"], "headlines": 1}}
                      if f == "briefs" else {},
            # when the user last looked: today's desk only, never a past day's
            "looks": {"previous": at("T04:24:24+00:00"), "last": at("T05:00:00+00:00")} if f == "looks" else {},
            # a headline: known from when it was published, and only for a company covered then
            "headlines": {"companies": {"ZZZ": [{"id": "h1", "headline": "ZZZ seeded-only headline", "source": "Wire",
                                                 "url": "https://example.com/h1", "at": at("T13:00:00Z")}]}}
                         if f == "headlines" else {},
            "wording": {"companies": {"ZZZ": {"new": {"date": w}, "old": {"date": "2025-08-01"},
                                              "sections": {"risk_factors": {"label": "seeded-only wording", "added": [], "removed": [],
                                                                            "kept": 1, "sentences_before": 1, "sentences_now": 1}}}}}
                        if f == "wording" else {},
        }

    def built(self, future_in=None, undated=False):
        return build_desk.compute(today=date.fromisoformat(self.DAY), as_of=self.DAY,
                                  **asof.apply(self.inputs(future_in, undated), self.DAY))

    def assertNothingSeeded(self, page, store):
        # the page's own fields that name what it cannot show are not the seeded record
        text = json.dumps({k: v for k, v in page.items() if k not in ("generated_at", "undated_coverage")})
        self.assertNotIn(self.MARK, text)
        self.assertNotIn("seeded-only", text)
        self.assertNotIn("4242", text)
        self.assertNotIn("42.42", text)
        later = [d for d in re.findall(r"\b20\d\d-\d\d-\d\d\b", text) if d > self.DAY]
        self.assertEqual(later, [], store)

    def test_no_module_returns_data_dated_after_the_as_of_date(self):
        """Every store, seeded in turn with an observation dated after the day: none of
        it reaches the page, and no date after the day appears anywhere in it."""
        self.assertEqual(set(asof.STORES), set(self.inputs()))
        self.assertEqual([c["ticker"] for c in self.built()["companies"]], ["ZZZ"])   # the base company is shown
        for store in asof.STORES:
            with self.subTest(store=store):
                self.assertNothingSeeded(self.built(store), store)

    def test_no_module_returns_an_undated_record_for_a_past_day(self):
        """K-03: every store, seeded in turn with an observation that has no date. It
        cannot be placed in time, so it reaches no past page — the class, not only the
        three filters the review found (analysts, theses, wording) and the two it did
        not (the account snapshot, coverage)."""
        for store in asof.STORES:
            with self.subTest(store=store):
                self.assertNothingSeeded(self.built(store, undated=True), store)

    def test_the_seeds_are_visible_when_nothing_filters_them(self):
        """Built without asof.apply, each seeded observation does reach the page — so the
        two tests above pass because of the filters, not because the seeds are invisible."""
        for store in asof.STORES:
            with self.subTest(store=store):
                text = json.dumps(build_desk.compute(today=date.fromisoformat(self.FUTURE), **self.inputs(store)))
                self.assertTrue(self.MARK in text or "seeded-only" in text or "4242" in text or "42.42" in text
                                or (store == "looks" and "T04:24:24" in text))

    def test_a_date_that_is_not_a_day_is_not_known(self):
        for when in (None, "", "yesterday", "2026-02-30", "20260301", "0", 20260301):
            self.assertFalse(asof.known(when, "2026-06-01"), when)
        self.assertTrue(asof.known("2026-06-01T23:59:59Z", "2026-06-01"))
        self.assertFalse(asof.known("2026-06-02", "2026-06-01"))
        # a close keyed by no day is dropped, though the page, reading the latest dated
        # close, would not show it anyway
        kept = asof.closes({"ZZZ": {"": 1.0, "2026-13-01": 3.0, "2026-05-01": 2.0}}, "2026-06-01")
        self.assertEqual(kept["ZZZ"], {"2026-05-01": 2.0})

    def test_an_undated_follow_is_named_not_shown(self):
        held = {"tickers": ["OLD", "NEW"], "coverage": {"NEW": {"followed_at": "2026-05-01", "why": "x"}}}
        then = asof.coverage(held, "2026-06-01")
        self.assertEqual((then["tickers"], then["undated"]), (["NEW"], ["OLD"]))
        page = build_desk.compute({}, today=date(2026, 6, 1), as_of="2026-06-01", coverage=then,
                                  news={"tickers": then["tickers"]})
        self.assertEqual(page["undated_coverage"], ["OLD"])
        self.assertIn("DATA.undated_coverage", template_function("notPlaced"))
        self.assertEqual(build_desk.compute({}, today=date(2026, 6, 1), coverage=held)["undated_coverage"], [])

    def test_financials_are_placed_by_filing_date_not_period_end(self):
        """A quarter that ended before the day but was filed after it is not known."""
        stored = {"ticker": "ZZZ", "cik": 1, "tags": {"revenue": "Revenues"}, "facts": {"revenue": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 800.0, "form": "10-K", "filed": "2026-02-10"},
            {"start": "2026-01-01", "end": "2026-03-31", "val": 250.0, "form": "10-Q", "filed": "2026-06-15"}]}}
        self.assertEqual(asof.company(stored, "2026-06-01")["revenue_asof"], "2025-12-31")
        self.assertEqual(asof.company(stored, "2026-01-31").get("revenue"), None)     # nothing filed yet
        undated = {"ticker": "ZZZ", "facts": {"revenue": [{"start": "2025-01-01", "end": "2025-12-31", "val": 1.0, "form": "10-K"}]}}
        self.assertIsNone(asof.company(undated, "2030-01-01").get("revenue"))        # cannot be placed in time

    def test_the_latest_day_reproduces_today(self):
        stored = {"ticker": "ZZZ", "cik": 1, "tags": {"revenue": "Revenues"}, "facts": {"revenue": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 800.0, "form": "10-K", "filed": "2026-02-10"}]}}
        now = fundamentals.derive("ZZZ", 1, stored["facts"], stored["tags"])
        self.assertEqual(asof.company(stored, "9999-12-31"), now)
        book = {"start_cash": 1000.0, "trades": [
            {"id": "2", "date": "2026-03-02", "ticker": "A", "side": "SELL", "quantity": 1.0, "value": 12.0, "fee": 0.1},
            {"id": "1", "date": "2026-03-01", "ticker": "A", "side": "BUY", "quantity": 2.0, "value": 20.0, "fee": 0.2}]}
        replayed = asof.practice(book, "9999-12-31")
        self.assertAlmostEqual(replayed["cash"], 1000.0 - 20.2 + 11.9)
        self.assertAlmostEqual(replayed["positions"]["A"]["quantity"], 1.0)
        self.assertEqual(asof.practice(book, "2026-03-01")["positions"]["A"]["quantity"], 2.0)

    def test_coverage_is_what_was_followed_that_day(self):
        held = {"tickers": ["OLD", "NEW"], "coverage": {"OLD": {"followed_at": "2026-02-01", "why": "z"},
                                                        "NEW": {"followed_at": "2026-07-01", "why": "x"}},
                "past": [{"ticker": "GONE", "followed_at": "2026-01-01", "why": "y", "stopped_at": "2026-07-01"},
                         {"ticker": "LATER", "followed_at": "2026-06-10", "stopped_at": "2026-06-20"},
                         {"ticker": "NODATE", "stopped_at": "2026-07-01"},
                         {"ticker": "NOSTOP", "followed_at": "2026-01-01"}]}      # dropped on a day not recorded
        self.assertEqual(asof.coverage(held, "2026-06-01")["tickers"], ["OLD", "GONE"])

    def test_only_a_real_past_day_is_accepted_and_the_page_is_read_only(self):
        today = date(2026, 9, 24)
        self.assertEqual(asof.valid("2026-03-01", today), "2026-03-01")
        for bad in ("2026-09-24", "2099-01-01", "yesterday", "", "2026-02-30"):
            self.assertIsNone(asof.valid(bad, today), bad)
        template = page_source()
        for write in ("#refreshBtn", "[data-follow]", "[data-thesis]", ".note-btn", "[data-confirm]", "#pSubmit"):
            self.assertIn("body.as-of " + write if not write.startswith("#pSubmit") else ".card:has(#pSubmit)", template)
        self.assertIn("data-asof=", template_function("renderTrades"))
        self.assertIn("(DATA.as_of && !th.pending)", template_function("thesisBlock"))   # no empty section
        self.assertIn('if path == "/asof":', open(os.path.join(ROOT, "server.py")).read())


class LookTests(unittest.TestCase):
    """The user found the first page too dark, cramped, and all over the place (25 Sep
    2026), then the light one too bright. It is now a dim slate page with soft ink, larger type, and one company at a
    time. These keep it readable: a later edit that brings back faint or tiny text, or
    glare, fails here."""

    def template(self):
        return page_source()

    def tokens(self):
        root = self.template().split(":root{", 1)[1].split("\n  }", 1)[0]
        return dict(re.findall(r"--([\w-]+):(#[0-9A-Fa-f]{6});", root))

    @staticmethod
    def luminance(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    @classmethod
    def contrast(cls, a, b):
        hi, lo = sorted((cls.luminance(a), cls.luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def test_every_text_colour_reads_on_every_background(self):
        """WCAG AA for body text, 4.5:1, for each colour text is set in, on the page,
        a card and a card's inset."""
        t = self.tokens()
        for fg in ("ink", "ink-muted", "ink-faint", "accent", "measured", "withheld", "critical", "warn"):
            for bg in ("bg", "surface", "surface-2"):
                self.assertGreaterEqual(self.contrast(t[fg], t[bg]), 4.5, (fg, bg))
        # the verdict pill's "does not clear" is set in --uncertain, on the card
        self.assertGreaterEqual(self.contrast(t["uncertain"], t["surface"]), 4.5)
        # a dim page with light ink: plenty of contrast, but not white on black (21:1), the glare
        self.assertLess(self.luminance(t["bg"]), self.luminance(t["ink"]))
        self.assertTrue(12 < self.contrast(t["ink"], t["bg"]) < 17)
        self.assertIn("color-scheme:dark", self.template())              # dates, lists and scrollbars too
        # a button's words on its fill, and a pill's on its tint
        self.assertGreaterEqual(self.contrast(t["on-accent"], t["accent-strong"]), 4.5)
        self.assertGreaterEqual(self.contrast(t["accent"], t["accent-soft"]), 4.5)

    def test_no_text_is_tiny(self):
        sizes = [float(x) for x in re.findall(r"font-size:(\d+(?:\.\d+)?)px", self.template())]
        self.assertGreaterEqual(min(sizes), 12)
        self.assertIn("font-size:15px", self.template().split("\n  body{", 1)[1].split("}", 1)[0])

    def test_labels_are_words_not_spaced_capitals(self):
        css = self.template().split("</style>", 1)[0]
        self.assertNotIn("text-transform:uppercase", css)
        self.assertNotIn("IBM Plex Mono", self.template())

    def test_the_typefaces_are_the_pages_own(self):
        """The look of the page (29 Sep 2026: it must not change) is Archivo for headings and
        figures and IBM Plex Sans for the rest, as it was when Google served them. Both are kept in
        page/fonts/ with their licences and carried inside the built page."""
        css = self.template().split("</style>", 1)[0]
        faces = re.findall(r"@font-face\{font-family:\"([^\"]+)\"", css)
        self.assertEqual(sorted(faces), ["Archivo", "IBM Plex Sans"])
        named = set(re.findall(r"font-family:\"([^\"]+)\"", css)) | set(re.findall(r"--font-num:\"([^\"]+)\"", css))
        self.assertEqual(named, set(faces))                   # no font is named that the page does not carry
        page = build_desk.render({})
        self.assertEqual(page.count("data:font/woff2;base64,"), len(faces))
        self.assertNotIn("__FONT_", page)
        folder = os.path.join(ROOT, "page", "fonts")
        licences = open(os.path.join(folder, "LICENSES.txt")).read()
        self.assertIn("SIL Open Font License", licences)
        for token, name in build_desk.PAGE_FONTS.items():
            with open(os.path.join(folder, name), "rb") as f:
                data = f.read()
            self.assertEqual(data[:4], b"wOF2", name)          # a real web font, not a saved error page
            self.assertLess(len(data), 100_000, name)
            self.assertIn("data:font/woff2;base64," + base64.b64encode(data).decode("ascii"), page)
            self.assertIn(name, licences)
        self.assertEqual(sorted(n for n in os.listdir(folder) if n.endswith(".woff2")), sorted(build_desk.PAGE_FONTS.values()))

    def test_a_missing_typeface_does_not_stop_the_page(self):
        """Never break the page: with a font file gone, the browser goes on to the next font in the stack."""
        real = build_desk.PAGE_FONTS
        build_desk.PAGE_FONTS = {token: "gone.woff2" for token in real}
        try:
            page = build_desk.render({})
        finally:
            build_desk.PAGE_FONTS = real
        self.assertNotIn("__FONT_", page)
        self.assertNotIn("data:font/woff2", page)

    def test_one_company_at_a_time(self):
        """Every company's full card, one after another, made a page thousands of pixels
        long. The companies are one table (27 Sep 2026: every figure to scan at once), each
        row a click from its card; the chosen one's card is shown."""
        body = template_function("renderCompanies")
        self.assertIn("coTable(C, pick)", body)
        self.assertIn('data-co-pick="', template_function("coTable"))
        self.assertIn("(c.ticker === pick ? '' : ' hidden')", body)
        self.assertIn("card.hidden = card.dataset.co !== ticker", template_function("pickCompany"))

    def test_the_detail_opens_on_click(self):
        """The user asked for a page they can read and find things in (25 Sep 2026). A
        company card opens on its price and key figures; every other section, and every
        research rule, is a row with a plain title that opens on click."""
        template = self.template()
        for block in ("deskRatingBlock", "bridgeBlock", "scoreBlock", "peerBlock", "valueBlock",
                      "forecastBlock", "ratingBlock", "thesisBlock", "wordingBlock"):
            body = template_function(block)
            self.assertIn("foldOpen(", body, block)
            self.assertNotIn('<div class="eyebrow">', body, block)
        self.assertIn('<div class="co-sec"><div class="eyebrow">Key figures</div>', template_function("renderCompanies"))
        self.assertIn("foldOpen('Past results'", template_function("renderCompanies"))
        # closed, the analysts' row gives the count and the direction, never the label (Q4)
        self.assertNotIn("a.verdict", template_function("ratingBlock").split("foldOpen(", 1)[1].split(") +", 1)[0])
        self.assertEqual(template_function("renderResearch").count("return ruleOpen("), 2)
        self.assertIn("let newsFilter = 'material';", template)

    def test_six_tabs_hold_every_section_once(self):
        """Nine tabs were too many to find anything in (25 Sep 2026). Five, each one
        subject: every section sits under exactly one, and an old address still lands. A
        sixth, History, the account year by year, (28 Sep 2026)."""
        template = self.template()
        block = template[template.index("const TABS = ["):template.index("];", template.index("const TABS = ["))]
        tabs = re.findall(r"\{id:'(\w+)',\s*label:'([^']+)',\s*pages:\[([^\]]*)\]", block)
        self.assertEqual([t[1] for t in tabs], ["Overview", "Portfolio", "History", "Companies", "Research", "Trades"])
        pages = [p for t in tabs for p in re.findall(r"'(\w+)'", t[2])]
        sections = re.findall(r'<section class="page" id="page-(\w+)"', template)
        self.assertEqual(sorted(pages), sorted(sections))
        self.assertEqual(len(pages), len(set(pages)))
        self.assertIn("TABS.find(t => t.pages.includes(id))", template_function("showPage"))
        self.assertIn('<button data-f="material" aria-pressed="true">Important</button>', template)


class QuickTests(unittest.TestCase):
    """Nothing asks for a reason; what cannot be acted on is out of the way."""

    def test_every_write_the_page_asks_for_reads_the_answer(self):
        """28 Sep 2026: the note editor took any answer from the server as saved, so a note
        refused (the journal unreadable) looked saved. Every write reads the server's `ok`."""
        page = page_source()
        for endpoint in ("/journal", "/thesis", "/watchlist", "/summary", "/brief", "/screen", "/paper",
                         "/plan", "/check"):
            start = page.index("fetch('" + endpoint + "'")
            self.assertRegex(page[start:start + 700], r"!res\.ok|res\.ok\)", endpoint)

    def test_a_company_held_and_not_followed_does_not_count_toward_the_cap(self):
        """28 Sep 2026: the page counted every company covered, held ones too, so with 14
        followed and one held the 15th follow asked which to replace, offering the held one,
        which the server would refuse; and a held company's Follow button read "following"."""
        d = build_desk.compute({}, today=TODAY, news={"tickers": ["AAA", "HELD"], "held": ["HELD"]})
        self.assertEqual((d["news"]["tickers"], d["news"]["followed"]), (["AAA", "HELD"], ["AAA"]))
        body = template_function("follow")
        self.assertIn("mine = N.followed", body)
        self.assertNotIn("(N.tickers || []).length >=", body)
        self.assertIn("mine.map(", body)
        self.assertIn("N.followed", template_function("watched"))

    def test_a_price_to_earnings_at_either_end_of_its_history_says_so(self):
        """The companies table read "higher than 0%" for a company at its lowest."""
        program = template_function("pePlace") + (
            "\nvar __out = [pePlace(0), pePlace(100), pePlace(86.6), pePlace(0.2, 'its last 5 years')].join('|');"
            "\n(typeof process !== 'undefined') ? console.log(__out) : __out;")
        self.assertEqual(run_javascript(program).strip(),
                         "at its lowest|at its highest|higher than 87%|at its lowest in its last 5 years")
        self.assertNotIn("'higher than ' + Math.round", page_source())

    def test_a_past_day_offers_no_start_over(self):
        """28 Sep 2026: the as-of page said nothing could be changed from it, and still
        showed the practice book's "Start over", which would have cleared today's book."""
        page = page_source()
        self.assertIn("body.as-of #pReset{display:none !important;}", page)
        for handler in ("$('pReset').addEventListener", "$('pSubmit').addEventListener"):
            start = page.index(handler)
            self.assertIn("if (DATA.as_of) return;", page[start:start + 200], handler)

    def test_a_link_from_the_stores_is_a_web_address_or_none(self):
        """28 Sep 2026: every link the page builds from the stores goes through link(), which
        makes nothing else a link: a javascript: address in a store (edited by hand, or from a
        source's slip) must never become a link that runs."""
        page = page_source()
        self.assertNotRegex(page, r"""href="' \+ esc\(""")
        lines = [l for l in page.split("\n") if l.startswith(("const esc = ", "const link = "))]
        self.assertEqual(len(lines), 2)
        js = ("\n".join(lines) + "\nvar __out = [link('javascript:alert(1)'), link(' javascript:x'), link('data:text/html,x'),"
              " link(null), link('https://www.ft.com/a?b=1&c=\"2\"')].join('|');\n"
              "(typeof process !== 'undefined') ? console.log(__out) : __out;")
        self.assertEqual(run_javascript(js).strip(), "#|#|#|#|https://www.ft.com/a?b=1&amp;c=&quot;2&quot;")

    def test_a_phone_sorts_the_companies_from_a_menu(self):
        """The companies table stacks on a phone and hides its headings, which were the only
        way to sort it: a menu does the same there."""
        body = template_function("coTable")
        self.assertIn('id="coSortSel"', body)
        self.assertIn(".co-sort-menu{display:block;}", page_source())
        self.assertIn("coFirstDir(e.target.value)", page_source())

    def test_nothing_asks_for_a_reason(self):
        page = page_source()
        for nag in ("no reason written", "Write why", "NOTE_PROMPTS", "notes on ", "with a reason written down",
                    "Before your next trade, write down why"):
            self.assertNotIn(nag, page, nag)
        self.assertNotIn("What the evidence says", page)                 # the Overview's old card
        self.assertNotIn("renderFindings", page)
        self.assertIn("closest('.card').hidden = !resolved.length", template_function("renderTheses", page))

    def test_filings_are_named_by_what_they_announce(self):
        d = build_desk.compute(generate_demo_data.generate(TODAY), today=TODAY,
                               news={"tickers": ["KO"], "items": [{"ticker": "KO", "form": "8-K", "date": "2026-09-10",
                                                                    "what": "Results announced; Documents attached"}]})
        self.assertEqual(d["news"]["items"][0]["headline"], "Results announced")
        self.assertIn("esc(i.headline || i.label)", template_function("renderHeadlines"))

    def test_a_summary_written_before_the_latest_figures_says_so(self):
        self.assertIn("c.summary.as_of < c.revenue_asof", template_function("renderCompanies"))


class TradeCheckTests(unittest.TestCase):
    """27 Sep 2026: a quick check before a trade — a ticker and an amount, the facts, nothing
    to write and nothing sent."""

    def data(self):
        raw = generate_demo_data.generate(TODAY)
        return build_desk.compute(raw, today=TODAY)

    def test_the_facts_come_from_the_desks_own_figures(self):
        d = self.data()
        holding = next(r for r in d["positions"]["rows"] if r["us_line"])
        card = {"ticker": holding["ticker"], "name": "Seeded Co", "rating": {"label": "Hold", "place": 50.0, "rated_among": 100},
                "next_earnings": {"date": "2026-10-01", "when": "after the close"}, "days_to_earnings": 12,
                "pe_history": {"place": 80.0, "years": 5}, "price": {"close": 100.0, "year_vs_market": 0.05},
                "context": {"valuation": {"dividend_yield": 0.02}}}
        c = trade_check.check(holding["ticker"], "BUY", 1000.0, d, card=card)
        total = d["account"]["total"]
        self.assertAlmostEqual(c["weight_after"] - c["weight_before"], 1000.0 / total)
        self.assertAlmostEqual(c["held_after"], holding["value"] + 1000.0)
        self.assertEqual((c["results"]["days"], c["pe"]["place"], c["rating"]["label"]), (12, 80.0, "Hold"))
        self.assertAlmostEqual(c["dividend"]["yearly"], 20.0)
        rate, read = trade_check.fee_rate(d["trades"]["rows"], "BUY")
        self.assertEqual((c["fees"]["rate"], c["fees"]["trades"]), (rate, read))
        self.assertAlmostEqual(c["fees"]["amount"], rate * 1000.0)
        sold = trade_check.check(holding["ticker"], "SELL", holding["value"] * 2, d, card=card)
        self.assertTrue(sold["over_held"])
        self.assertAlmostEqual(sold["held_after"], 0.0)               # never below none
        self.assertNotIn("dividend", sold)
        self.assertEqual(trade_check.fee_rate([], "BUY"), (None, 0))
        self.assertIsNone(trade_check.withheld_rate({}, {}))
        self.assertAlmostEqual(trade_check.withheld_rate({"withheld": 30.0}, {"total": 70.0}), 0.3)

    def test_it_sends_nothing_and_asks_for_nothing_written(self):
        source = open(os.path.join(ROOT, "trade_check.py")).read()
        for never in ("import execute", "import t212", ".post(", "atomic_write"):
            self.assertNotIn(never, source)
        page = page_source()
        form = page[page.index('id="ckForm"'):page.index('id="ckOut"')]
        self.assertNotIn("textarea", form)                              # a ticker and an amount, no reason
        self.assertIn('data-check="', template_function("renderCompanies"))
        self.assertIn("'renderCheckCard'", page)
        self.assertIn('path == "/check"', inspect.getsource(server.Handler.do_POST))

    def test_the_endpoint_answers_for_a_company_not_covered(self):
        with tempfile.TemporaryDirectory() as folder:
            json.dump(self.data(), open(os.path.join(folder, "desk_data.json"), "w"))
            handler = server.Handler.__new__(server.Handler)
            handler.folder = folder
            code, out = handler.check_trade({"ticker": "zzzz", "side": "BUY", "amount": "500"})
            self.assertEqual((code, out["ok"], out["check"]["covered"], out["check"]["ticker"]), (200, True, False, "ZZZZ"))
            self.assertFalse(handler.check_trade({"ticker": "NVDA", "amount": "0"})[1]["ok"])
            self.assertFalse(handler.check_trade({"ticker": "not a ticker!", "amount": "5"})[1]["ok"])


class CleanPageTests(unittest.TestCase):
    """No page opens on a paragraph, and there is no
    footer. What must stay reachable — a rating's limits, what analysts' ratings lean to —
    is one closed "About" row away, never deleted."""

    def test_no_page_opens_on_a_paragraph(self):
        template = page_source()
        for head in re.findall(r'<div class="page-head">(.*?)</div>\s*(?:<div|<details|</section)', template, re.S):
            self.assertNotRegex(head, r"<p>", head[:80])
        self.assertNotIn("<footer", template)

    def test_what_must_stay_is_one_click_away(self):
        self.assertIn("about(", template_function("deskRatingBlock"))
        self.assertIn("esc(R.limits)", template_function("deskRatingBlock"))
        self.assertIn("esc(R.limits", template_function("renderRatingRecord"))
        self.assertIn("Barber, Lehavy", template_function("ratingBlock"))
        self.assertIn("<details class=\"about\">", template_function("about"))


class IntervalPageTests(unittest.TestCase):
    """Phase 5: every count the page reads as evidence carries its interval, drawn by
    one component, and the verdict comes from uncertainty.py, never the page."""

    # "k of n" built in the template; "as of <date>" is a date, not a count
    COUNT = re.compile(r"""(?<!\bas )\bof (?:the (?:last )?)?['"]\s*\+|\+\s*['"]\s*of\b""")

    def draw(self, iv, lo=0, hi=1):
        program = ("%s\nvar __out = intervalBar(%s, %s, %s);\n"
                   "(typeof process !== 'undefined') ? console.log(__out) : __out;"
                   % (template_function("intervalBar"), json.dumps(iv), lo, hi))
        return run_javascript(program)

    def rects(self, svg):
        return {m.group(1): {k: float(v) for k, v in re.findall(r'\s(x|width)="([-0-9.]+)"', m.group(0))}
                for m in re.finditer(r'<rect class="(iv-[a-z]+)"[^>]*>', svg)}

    def test_no_page_reports_a_proportion_without_its_interval(self):
        """Every "k of n" the template builds is either drawn by ofCount, which always
        adds the interval, or marked with why it is not a rate (a census, a rank, a
        count of tests already corrected for multiple testing)."""
        lines = page_source().split("\n")
        bare = []
        for i, line in enumerate(lines):
            if not self.COUNT.search(line):
                continue
            near = lines[max(0, i - 3):i + 1]
            if not any("not a rate:" in l or "function ofCount(" in l for l in near):
                bare.append((i + 1, line.strip()[:80]))
        self.assertEqual(bare, [])
        of_count = template_function("ofCount")
        self.assertIn("intervalBar(p, 0, 1)", of_count)
        self.assertIn("rangeText(p, v => formatMeasure('share', v))", of_count)
        template = "\n".join(lines)
        for gone in ("hit_rate", "median_vs_market", "sells_gain", "few cases", ".positive[", "c.reports"):
            self.assertNotIn(gone, template)

    def test_an_interval_spanning_the_null_renders_as_uncertain(self):
        spans = self.draw(uncertainty.against_chance(11, 25))
        self.assertIn('class="ivbar uncertain"', spans)
        self.assertIn("iv-null", spans)
        self.assertIn('class="ivbar measured"', self.draw(uncertainty.against_chance(7, 29)))
        self.assertIn('class="ivbar uncertain"', self.draw(uncertainty.against_chance(4, 4)))
        # a rate with no chance level to compare with draws no reference line
        self.assertNotIn("iv-null", self.draw(uncertainty.proportion(3, 4)))

    def test_the_interval_is_the_mark_and_the_estimate_a_tick_inside_it(self):
        iv = uncertainty.against_chance(7, 29)
        svg = self.draw(iv)
        r = self.rects(svg)
        self.assertAlmostEqual(r["iv-span"]["x"], round(iv["low"] * 64, 1), places=1)
        self.assertAlmostEqual(r["iv-span"]["x"] + r["iv-span"]["width"], round(iv["high"] * 64, 1), delta=0.11)
        self.assertAlmostEqual(r["iv-null"]["x"], 0.5 * 64 - 0.5, places=1)
        tick = r["iv-est"]["x"] + 1
        self.assertTrue(r["iv-span"]["x"] <= tick <= r["iv-span"]["x"] + r["iv-span"]["width"])
        self.assertEqual(self.draw({"estimate": 0.02, "low": None, "high": None, "reads": "uncertain"}), "")

    def test_no_number_is_coloured_as_good_or_bad(self):
        """Phase 5: green and red on returns are retired; a sign carries itself through
        its + or −. The data's only colours are --measured, --uncertain and --withheld;
        --critical is left for the page's own error messages."""
        template = page_source()
        for gone in ("tone(", "--good", ".pos{", ".neg{", "'pos'", "'neg'", "blk.up", "blk.down"):
            self.assertNotIn(gone, template)
        for token in ("--measured", "--uncertain", "--withheld"):
            self.assertIn(token + ":", template)
        uses = re.findall(r"^.*var\(--critical\).*$", template, re.M)
        self.assertEqual(len(uses), 2, uses)                             # .msg and the remove button's hover
        self.assertTrue(all(".msg" in u or ".chip .x:hover" in u for u in uses))

    def test_the_page_takes_its_verdict_from_uncertainty(self):
        """The page draws `reads` and words `distinguishable`; it never compares an
        interval with chance itself."""
        for name in ("intervalBar", "ofCount", "chanceText", "reactionLine", "vsMarket"):
            body = template_function(name)
            self.assertNotRegex(body, r"\.low\s*[<>]=?|[<>]=?\s*\w+\.low\b|\.high\s*[<>]|[<>]=?\s*\w+\.high\b", name)
        self.assertIn("{measured: 'measured', bounded: 'bounded'}[iv.reads]", template_function("intervalBar"))

    def test_measured_is_drawn_only_for_a_comparison_made(self):
        """K-07: the finding colour is --measured, and only an interval that excludes
        what chance would give takes it. A rate with no chance line never does."""
        for k, n in ((6, 6), (40, 40), (0, 30), (15, 30)):
            self.assertNotEqual(uncertainty.proportion(k, n)["reads"], "measured", (k, n))
        self.assertEqual(uncertainty.median([0.01 * i for i in range(1, 30)])["reads"], "bounded")
        self.assertIn('class="ivbar bounded"', self.draw(uncertainty.proportion(6, 6)))
        self.assertIn('class="ivbar measured"', self.draw(uncertainty.against_chance(7, 29)))
        template = page_source()
        self.assertIn(".ivbar.bounded .iv-span{fill:var(--ink-faint);}", template)

    def test_every_count_the_page_reads_as_evidence_arrives_with_its_interval(self):
        trades = [{"ticker": "ZZZ", "side": "BUY", "quantity": 1, "price": 100.0, "value": 100.0, "date": "2024-01-02",
                   "time": "2024-01-02T10:00:00Z"},
                  {"ticker": "ZZZ", "side": "SELL", "quantity": 1, "price": 90.0, "value": 90.0, "date": "2024-02-01",
                   "time": "2024-02-01T15:00:00Z"}]
        days = {(date(2024, 1, 1) + timedelta(days=i)).isoformat(): {"c": 100.0 + i, "a": 100.0 + i} for i in range(60)}
        closed = build_desk.build_closed_trades(trades, {"ZZZ": days, prices.BENCHMARK: days}, TODAY)
        for key in ("beat_market", "vs_market", "won"):
            self.assertIn("reads", closed[key], key)
        self.assertEqual(closed["beat_market"]["expected"], 0.5)
        self.assertEqual(closed["vs_market"]["expected"], 0)
        self.assertNotIn("expected", closed["won"])           # a gain is not a coin flip: markets drift up
        empty = build_desk.build_closed_trades([], {}, TODAY)
        self.assertIsNone(empty["beat_market"])
        self.assertIsNone(empty["vs_market"])
        self.assertIsNone(forecasts.beat_record([]))
        self.assertNotIn("sells_gain", build_desk.build_trades([], {}))


if __name__ == "__main__":
    unittest.main()
