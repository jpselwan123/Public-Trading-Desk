"""Other brokers (broker.py): the same account, known to the cent (tests/ledger.py), given as a CSV
export, as Alpaca's answers and as an Interactive Brokers Flex statement, must come out as the
truth, as Trading 212's records do in test_audit. And Trading 212's path must not change."""
from support import *  # noqa: F401,F403
import gzip
import xml.etree.ElementTree as ET

import broker
import broker_alpaca
import broker_csv
import broker_ibkr
import checks
import ledger


def built(L, raw):
    return build_desk.compute(raw, today=L.end, prices=L.prices())


def csv_record(L, **settings):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "history.csv")
    with open(path, "w") as f:
        f.write(ledger.csv_export(L, settings.pop("dates_written", "iso")))
    return broker_csv.sync(environ=dict({"BROKER_CSV": path, "BROKER_CURRENCY": L.currency}, **settings))


def alpaca_record(L):
    a = ledger.alpaca_answers(L)
    return broker_alpaca.record(a["account"], a["positions"], a["activities"])


def ibkr_record(L):
    return broker_ibkr.record(ET.fromstring(ledger.ibkr_statement(L)))


class BrokerTruthTests(unittest.TestCase):
    def assert_true_to(self, L, d, derived=False):
        a, g, c = d["account"], d["growth"], d["costs"]
        self.assertAlmostEqual(a["total"], L.value_on(L.days[-1]), delta=0.02)
        self.assertAlmostEqual(a["cash"], L.cash, delta=0.02)
        # the ledger's fills are to the cent, as Trading 212's; another broker's shares times price are not
        self.assertAlmostEqual(a["realized"], L.realized, delta=max(0.05, 0.005 * len(L.orders)))
        self.assertAlmostEqual(g["deposited"], sum(x for _, x in L.flows if x > 0), places=6)
        self.assertAlmostEqual(g["withdrawn"], -sum(x for _, x in L.flows if x < 0), places=6)
        self.assertAlmostEqual(c["withheld"], L.withheld, delta=0.02)
        self.assertAlmostEqual(c["fees"], L.fees, delta=0.02)
        self.assertAlmostEqual(d["dividends"]["total"], sum(x["amount"] for x in L.dividends), delta=0.02)
        self.assertEqual(d["trades"]["count"], len(L.orders))
        # every past year the desk could price is the truth's
        for y in d["history"]["years"]:
            if y["value_end"] is not None and not y["current"]:
                self.assertAlmostEqual(y["value_end"], L.year_end(y["year"])[1], delta=0.05)
        if derived:
            self.assertEqual(d["checks"]["checks"], [])
            self.assertIn("no holdings or totals", d["checks"]["none_because"])
        else:
            self.assertEqual(d["checks"]["failed"], [])
            self.assertEqual(len(d["checks"]["checks"]), 6)

    def test_a_csv_export_comes_out_as_the_truth(self):
        for seed, ccy in ((1, "USD"), (2, "EUR"), (3, "GBP"), (4, "USD")):
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy)
                d = built(L, csv_record(L, BROKER_NAME="Fidelity"))
                self.assert_true_to(L, d, derived=True)
                self.assertEqual((d["broker"]["key"], d["broker"]["name"]), ("csv", "Fidelity"))

    def test_alpacas_answers_come_out_as_the_truth(self):
        for seed in (1, 2, 3, 4):
            with self.subTest(seed=seed):
                L = ledger.Ledger(seed, "USD")
                d = built(L, alpaca_record(L))
                self.assert_true_to(L, d)
                self.assertEqual(d["broker"]["name"], "Alpaca")

    def test_an_interactive_brokers_statement_comes_out_as_the_truth(self):
        for seed, ccy in ((1, "USD"), (2, "EUR"), (3, "GBP"), (4, "EUR")):
            with self.subTest(seed=seed, currency=ccy):
                L = ledger.Ledger(seed, ccy, london=seed % 2 == 0)
                self.assert_true_to(L, built(L, ibkr_record(L)))

    def test_each_sale_closes_against_the_average_cost_as_trading_212_states_it(self):
        """The ledger's own sales are closed against the average cost, in the account's money, a
        split counted: the desk works out the same for a broker that states none."""
        L = ledger.Ledger(2, "EUR", london=True)
        raw = broker.complete(ibkr_record(L), L.prices(), L.end)
        sells = sorted((o["fill"]["filledAt"], o["fill"]["walletImpact"]["realisedProfitLoss"])
                       for o in raw["orders"] if o["order"]["side"] == "SELL")
        truth = sorted((o["fill"]["filledAt"], o["fill"]["walletImpact"]["realisedProfitLoss"])
                       for o in L.orders if o["order"]["side"] == "SELL")
        self.assertEqual(len(sells), len(truth))
        for (day, mine), (_, theirs) in zip(sells, truth):
            self.assertAlmostEqual(mine, theirs, delta=0.02, msg=day)

    def test_a_line_the_desk_cannot_price_is_valued_at_cost_and_says_so(self):
        L = ledger.Ledger(2, "EUR", london=True)
        d = built(L, csv_record(L))
        self.assertEqual(d["broker"]["valued_at_cost"], ["LLL"])
        row = next(r for r in d["positions"]["rows"] if r["ticker"] == "LLL")
        self.assertAlmostEqual(row["value"], row["cost"])
        self.assertIn("valued_at_cost", page_source())

    def test_a_trading_212_record_is_untouched(self):
        L = ledger.Ledger(1, "GBP", london=True)
        raw = L.raw()
        self.assertIs(broker.complete(raw, L.prices(), L.end), raw)
        d = built(L, raw)
        self.assertEqual((d["broker"]["key"], d["broker"]["name"]), ("trading212", "Trading 212"))
        self.assertTrue(d["broker"]["states_gains"])

    def test_a_past_day_of_an_export_is_that_days_account(self):
        L = ledger.Ledger(3, "USD")
        raw = csv_record(L)
        day = L.days[400]
        d = build_desk.compute(**dict(asof.apply({"raw": raw, "prices": L.prices()}, day.isoformat()),
                                      today=day, as_of=day.isoformat()))
        self.assertAlmostEqual(d["account"]["total"], L.value_on(day), delta=0.02)


class CsvTests(unittest.TestCase):
    def write(self, text, name="export.csv", folder=None):
        folder = folder or tempfile.mkdtemp()
        with open(os.path.join(folder, name), "w") as f:
            f.write(text)
        return folder, os.path.join(folder, name)

    def sync(self, path, **env):
        return broker_csv.sync(environ=dict({"BROKER_CSV": path, "BROKER_CURRENCY": "EUR"}, **env))

    def test_a_brokers_own_headers_and_figures_are_read(self):
        """An export opens with a title; its columns carry the broker's names; figures in the
        European way; a fee and a tax in rows of their own."""
        _, path = self.write(
            "Account statement\n\n"
            "Trade Date;Action;Ticker;No. of shares;Price / share;Currency (Price / share);Net Amount;Commission;Tax Withheld\n"
            "2025-01-02;Deposit;;;;;1.000,00;;\n"
            "2025-01-03;Market buy;AAPL;2;150,00;USD;280,50;0,50;\n"
            "2025-03-01;Dividend;AAPL;2;;USD;1,70;;0,30\n"
            "2025-04-01;Market sell;AAPL;1;160,00;USD;148,00;0,40;\n"
            "2025-04-02;Fee;;;;;2,00;;\n")
        raw = self.sync(path)
        self.assertEqual(raw["summary"]["currency"], "EUR")
        buy = next(o for o in raw["orders"] if o["order"]["side"] == "BUY")
        self.assertEqual((buy["order"]["ticker"], buy["fill"]["quantity"], buy["fill"]["walletImpact"]["netValue"]),
                         ("AAPL_US_EQ", 2.0, 280.5))
        self.assertEqual(buy["fill"]["walletImpact"]["taxes"], [{"name": "COMMISSION", "quantity": 0.5}])
        div = raw["dividends"][0]
        self.assertEqual((div["amount"], div["grossAmount"]), (1.7, 2.0))
        self.assertEqual(sorted(t["type"] for t in raw["transactions"]), ["DEPOSIT", "FEE"])
        done = broker.complete(raw, {}, date(2025, 5, 1))
        self.assertAlmostEqual(done["summary"]["investments"]["realizedProfitLoss"], 148.0 - 280.5 / 2)
        self.assertAlmostEqual(done["summary"]["cash"]["availableToTrade"], 1000 - 280.5 + 1.7 + 148 - 2)

    def test_a_date_with_slashes_needs_its_order_said(self):
        L = ledger.Ledger(1, "USD", end=date(2023, 6, 30))
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "h.csv")
        with open(path, "w") as f:
            f.write(ledger.csv_export(L, "dmy"))
        with self.assertRaises(broker.BrokerError) as cm:
            broker_csv.sync(environ={"BROKER_CSV": path, "BROKER_CURRENCY": "USD"})
        self.assertIn("BROKER_CSV_DATES", str(cm.exception))
        raw = broker_csv.sync(environ={"BROKER_CSV": path, "BROKER_CURRENCY": "USD", "BROKER_CSV_DATES": "dmy"})
        self.assertEqual(len(raw["orders"]), len(L.orders))
        self.assertEqual(sorted(o["fill"]["filledAt"][:10] for o in raw["orders"]),
                         sorted(o["fill"]["filledAt"][:10] for o in L.orders))

    def test_a_row_it_cannot_read_stops_the_import_and_names_its_line(self):
        _, path = self.write("date,type,symbol,quantity,amount\n2025-01-02,deposit,,,100\n"
                             "2025-01-03,journal,,,5\n")
        with self.assertRaises(broker.BrokerError) as cm:
            self.sync(path)
        self.assertIn("export.csv:3", str(cm.exception))
        self.assertIn("journal", str(cm.exception))
        _, path = self.write("date,type,symbol,quantity,price,currency,amount\n2025-01-03,buy,AAPL,2,150,USD,\n")
        with self.assertRaises(broker.BrokerError) as cm:
            self.sync(path)                                  # a dollar price, a euro account, no amount
        self.assertIn("cannot be told", str(cm.exception))
        with self.assertRaises(broker.BrokerError) as cm:
            self.sync(os.path.join(tempfile.mkdtemp(), "missing.csv"))
        self.assertIn("docs/BROKERS.md", str(cm.exception))

    def test_overlapping_exports_count_a_row_once_and_two_like_trades_twice(self):
        head = "date,type,symbol,quantity,price,currency,amount\n"
        folder, _ = self.write(head + "2025-01-02,deposit,,,,,1000\n2025-01-03,buy,AAPL,1,100,EUR,100\n"
                               "2025-01-03,buy,AAPL,1,100,EUR,100\n", "2025-a.csv")
        self.write(head + "2025-01-03,buy,AAPL,1,100,EUR,100\n2025-01-03,buy,AAPL,1,100,EUR,100\n"
                   "2025-02-01,sell,AAPL,1,120,EUR,120\n", "2025-b.csv", folder)
        raw = self.sync(folder)
        self.assertEqual(sorted(o["order"]["side"] for o in raw["orders"]), ["BUY", "BUY", "SELL"])
        self.assertEqual(len(raw["transactions"]), 1)

    def test_an_export_is_personal_and_never_committed(self):
        self.assertIn("account.csv", open(os.path.join(ROOT, ".gitignore")).read())
        self.assertIn('"account.csv"', open(os.path.join(ROOT, "scripts", "privacy_scan.py")).read())


class AlpacaTests(unittest.TestCase):
    def opener(self, answers, asked):
        class Answer:
            def __init__(self, body):
                self.body, self.headers = gzip.compress(json.dumps(body).encode()), {"Content-Encoding": "gzip"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body

        def open_(req, timeout=None):
            url = urllib.parse.urlsplit(req.full_url)
            asked.append((url.path, dict(urllib.parse.parse_qsl(url.query)), req.get_method(), dict(req.header_items())))
            return Answer(answers(url.path, dict(urllib.parse.parse_qsl(url.query))))
        return open_

    def test_every_page_of_activities_is_read_and_nothing_is_written(self):
        L = ledger.Ledger(3, "USD")
        a = ledger.alpaca_answers(L)
        items = a["activities"]

        def answers(path, query):
            if path == "/v2/account":
                return a["account"]
            if path == "/v2/positions":
                return a["positions"]
            start = next((i + 1 for i, x in enumerate(items) if x["id"] == query.get("page_token")), 0)
            return items[start:start + int(query["page_size"])]
        asked = []
        raw = broker_alpaca.sync(environ={"ALPACA_API_KEY": "key-SECRET", "ALPACA_API_SECRET": "sec-SECRET",
                                          "ALPACA_ENV": "paper"}, opener=self.opener(answers, asked))
        pages = [q for p, q, m, h in asked if p == "/v2/account/activities"]
        self.assertEqual(len(pages), len(items) // 100 + 1)
        self.assertEqual({m for *_, m, h in asked}, {"GET"})
        self.assertTrue(all(h["Apca-api-key-id"] == "key-SECRET" and "paper-api" not in p for p, q, m, h in asked))
        self.assertEqual(raw["env"], "paper")
        self.assertNotIn("SECRET", json.dumps(raw))                       # no key, no account number
        d = build_desk.compute(raw, today=L.end, prices=L.prices())
        self.assertEqual(d["env"], "paper")
        self.assertAlmostEqual(d["account"]["total"], L.value_on(L.days[-1]), delta=0.02)
        with self.assertRaises(broker.BrokerError):
            broker_alpaca.Client("k", "s").get("/v2/orders")               # an order path is refused

    def test_a_refused_key_says_so(self):
        def open_(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
        with self.assertRaises(broker.BrokerError) as cm:
            broker_alpaca.sync(environ={"ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "s"}, opener=open_)
        self.assertIn("the key was refused", str(cm.exception))
        with self.assertRaises(broker.BrokerError) as cm:
            broker_alpaca.sync(environ={})
        self.assertIn("ALPACA_API_KEY", str(cm.exception))


class InteractiveBrokersTests(unittest.TestCase):
    def opener(self, statement, busy=2):
        calls = {"get": 0}

        class Answer:
            def __init__(self, text):
                self.text, self.headers = text.encode(), {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.text

        def open_(req, timeout=None):
            if "SendRequest" in req.full_url:
                return Answer("<FlexStatementResponse><Status>Success</Status><ReferenceCode>77</ReferenceCode>"
                              "<Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/"
                              "GetStatement</Url></FlexStatementResponse>")
            calls["get"] += 1
            if calls["get"] <= busy:
                return Answer("<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>"
                              "<ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>")
            return Answer(statement)
        return open_, calls

    def test_the_statement_is_asked_for_then_collected_while_it_is_made(self):
        L = ledger.Ledger(2, "EUR", london=True)
        opener, calls = self.opener(ledger.ibkr_statement(L))
        waits = []
        raw = broker_ibkr.sync(environ={"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_QUERY": "123"}, opener=opener,
                               sleep=waits.append)
        self.assertEqual(calls["get"], 3)
        self.assertEqual(waits, list(broker_ibkr.WAITS[:2]))
        self.assertNotIn("SECRET", json.dumps(raw))                       # the account id is never kept
        self.assertNotIn("A Person", json.dumps(raw))
        self.assertEqual(raw["summary"]["currency"], "EUR")

    def test_a_refusal_says_why(self):
        def refuse(req, timeout=None):
            class Answer:
                headers = {}

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return (b"<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode>"
                            b"<ErrorMessage>Token has expired.</ErrorMessage></FlexStatementResponse>")
            return Answer()
        with self.assertRaises(broker.BrokerError) as cm:
            broker_ibkr.sync(environ={"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_QUERY": "123"}, opener=refuse)
        self.assertIn("Token has expired", str(cm.exception))

    def test_a_years_report_adds_to_what_earlier_syncs_read(self):
        """A Flex query reaches back a year; what earlier syncs read is kept, merged by IBKR's own
        references, so the whole history comes out as the truth."""
        L = ledger.Ledger(4, "EUR")
        whole = ET.fromstring(ledger.ibkr_statement(L))
        cut = str(L.end.year - 1) + L.end.strftime("%m%d")
        recent = ET.fromstring(ledger.ibkr_statement(L))
        for section in ("Trades", "CashTransactions"):
            parent = recent.find(".//" + section)
            for row in list(parent):
                if "".join(ch for ch in row.get("dateTime", "") if ch.isdigit())[:8] < cut:
                    parent.remove(row)
        first = broker_ibkr.record(whole)
        again = broker_ibkr.record(recent, existing=first)
        self.assertEqual(len(again["orders"]), len(first["orders"]))
        d = build_desk.compute(again, today=L.end, prices=L.prices())
        self.assertAlmostEqual(d["account"]["realized"], L.realized, delta=0.05)
        self.assertEqual(d["checks"]["failed"], [])
        alone = build_desk.compute(broker_ibkr.record(recent), today=L.end, prices=L.prices())
        self.assertIn("shares", alone["checks"]["failed"])                # a year alone does not tie

    def test_without_the_base_currency_or_the_cash_it_says_what_to_add(self):
        L = ledger.Ledger(1, "USD")
        text = ledger.ibkr_statement(L)
        no_info = re.sub(r"<AccountInformation [^>]*/>", "", text)
        with self.assertRaises(broker.BrokerError) as cm:
            broker_ibkr.record(ET.fromstring(no_info))
        self.assertIn("Account Information", str(cm.exception))
        no_cash = re.sub(r"<CashReport>.*</CashReport>", "", re.sub(r"<EquitySummaryInBase>.*</EquitySummaryInBase>", "", text))
        with self.assertRaises(broker.BrokerError) as cm:
            broker_ibkr.record(ET.fromstring(no_cash))
        self.assertIn("Cash Report", str(cm.exception))


class BrokerWiringTests(unittest.TestCase):
    def test_trading_212_is_the_default_and_other_names_are_read(self):
        self.assertEqual(broker.current({}), "trading212")
        self.assertEqual(broker.current({"BROKER": "Interactive Brokers"}), "ibkr")
        self.assertEqual(broker.current({"BROKER": "t212"}), "trading212")
        with self.assertRaises(broker.BrokerError) as cm:
            broker.current({"BROKER": "robinhood"})
        self.assertIn("docs/BROKERS.md", str(cm.exception))
        self.assertEqual(broker.line_code("brk.b"), "BRK-B_US_EQ")
        self.assertEqual(broker.line_code("VUSA", "LSE"), "VUSA_LSE_EQ")
        self.assertEqual(build_desk.short_ticker(broker.line_code("VUSA", "LSE")), "VUSA")

    def test_trading_212s_sync_is_its_own_as_before(self):
        """With Trading 212 named or none, the sync is t212.py's, exactly as it was."""
        source = inspect.getsource(broker.sync_to_file)
        self.assertIn("return t212.sync_to_file(path)", source)
        self.assertIn("return t212.main(argv)", inspect.getsource(broker.main))
        self.assertIn("if broker.current() != broker.DEFAULT:", inspect.getsource(server.Handler.sync_account))
        self.assertIn("python3 broker.py", open(os.path.join(ROOT, "refresh.sh")).read())

    def test_the_desk_reads_only_at_every_broker(self):
        """No module can place, change or cancel an order: Trading 212's client has no write,
        Alpaca's reaches three read paths, and no request is anything but a read."""
        self.assertFalse(hasattr(t212.Client, "post"))
        self.assertNotIn("/execute", inspect.getsource(server.Handler))
        for name in ("t212.py", "broker.py", "broker_csv.py", "broker_alpaca.py", "broker_ibkr.py"):
            text = open(os.path.join(ROOT, name)).read()                   # every module that reaches a broker
            for never in (".post(", "POST", "DELETE", "PATCH", "PUT"):
                self.assertNotIn(never, text, name)
        self.assertEqual(broker_alpaca.Client.PATHS, ("/v2/account", "/v2/positions", "/v2/account/activities"))

    def test_another_brokers_sync_reads_it_and_builds_the_page(self):
        folder = tempfile.mkdtemp()
        L = ledger.Ledger(3, "USD", end=date(2024, 6, 28))
        with open(os.path.join(folder, "account.csv"), "w") as f:
            f.write(ledger.csv_export(L))
        h, events = object.__new__(server.Handler), []
        h.folder, h.demo = folder, False
        h.build = lambda: events.append("built page")
        h.instrument_codes = lambda: self.fail("Trading 212's instrument codes asked for another broker")
        h.settle_unknown_orders = lambda: self.fail("Trading 212's orders asked for another broker")
        saved = (broker.current, server.IN_PROCESS_SYNC, dict(os.environ))
        broker.current = lambda environ=None: "csv"
        server.IN_PROCESS_SYNC = True
        os.environ.update({"BROKER_CSV": os.path.join(folder, "account.csv"), "BROKER_CURRENCY": "USD",
                           "BROKER_NAME": "Fidelity"})
        try:
            code, result = h.refresh_account(events.append)
        finally:
            broker.current, server.IN_PROCESS_SYNC = saved[:2]
            os.environ.clear()
            os.environ.update(saved[2])
        self.assertTrue(result["ok"], result)
        self.assertEqual(events[0], {"step": "Your broker", "state": "running"})
        self.assertIn("built page", events)
        raw = json.load(open(os.path.join(folder, "t212_data.json")))
        self.assertEqual((raw["broker"], raw["broker_name"], len(raw["orders"])), ("csv", "Fidelity", len(L.orders)))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "account.csv")))

    def test_the_page_names_the_broker_and_shows_how_to_connect_it(self):
        page = page_source()
        self.assertNotIn("Connect Trading 212", page)
        self.assertIn("function brokerName()", page)
        self.assertIn("B.connect", page)
        for key, info in broker.BROKERS.items():
            self.assertTrue(info["connect"], key)
        d = build_desk.compute({}, today=date(2026, 9, 28), broker=("ibkr", None))
        self.assertEqual((d["broker"]["name"], d["connected"]), ("Interactive Brokers", False))
        self.assertIn("IBKR_FLEX_TOKEN", " ".join(d["broker"]["connect"]))
        d = build_desk.compute({}, today=date(2026, 9, 28), broker=("trading212", "BROKER=x is not one"))
        self.assertEqual(d["broker"]["problem"], "BROKER=x is not one")

    def test_doctor_asks_for_the_brokers_keys_and_not_trading_212s(self):
        rows = dict(doctor.keys({"BROKER": "alpaca", "ALPACA_API_KEY": "k"}))
        self.assertEqual(rows["Broker"], "Alpaca")
        self.assertEqual((rows["ALPACA_API_KEY"], rows["ALPACA_API_SECRET"]), ("set", "MISSING"))
        self.assertNotIn("Trading 212 key", rows)
        rows = dict(doctor.keys({}))
        self.assertEqual(rows["Trading 212 key"], "MISSING")
        self.assertIn("the default", rows["Broker"])
        L = ledger.Ledger(1, "USD", end=date(2023, 6, 30))
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "a.csv"), "w") as f:
            f.write(ledger.csv_export(L))
        found = doctor.sources({"BROKER": "csv", "BROKER_CSV": os.path.join(folder, "a.csv")},
                               opener=lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("offline")),
                               iphone=True)
        mine = next(r for r in found if r[0] == "Your broker")
        self.assertEqual(mine[1], "ok")
        self.assertIn("rows", mine[2])
