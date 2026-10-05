"""The Chart tab: the bars (split-adjusted, in New York's clock), the price above them, the shared Tiingo
allowance, the demo's own, and the page that draws them. No network: Tiingo is a stand-in."""
from support import *  # noqa: F401,F403
import world  # noqa: E402

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)          # 11:00 in New York, a Monday, in daylight time


def daily_row(day, o, h, l, c, v=1000, split=1.0):
    return {"date": day + "T00:00:00.000Z", "open": o, "high": h, "low": l, "close": c, "volume": v,
            "adjClose": c, "splitFactor": split}


def iex_row(utc, o, h, l, c, v=100):
    return {"date": utc, "open": o, "high": h, "low": l, "close": c, "volume": v}


class Tiingo:
    """A stand-in for Tiingo's three endpoints; every request it is given is kept."""

    def __init__(self, daily=None, bars=None, latest=None, fail=None):
        self.daily, self.bars, self.latest, self.fail, self.asked = daily or [], bars or [], latest or [], fail, []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.asked.append(url)
        if self.fail:
            raise self.fail
        body = self.latest if "/iex/?" in url else self.bars if "/iex/" in url else self.daily
        return FakeResponse(body)


def week_of_daily():
    out, price = [], 100.0
    for i in range(40):
        day = (date(2026, 8, 24) + timedelta(days=i)).isoformat()
        if date.fromisoformat(day).weekday() < 5:
            out.append(daily_row(day, price, price + 2, price - 1, price + 1, 1000 + i))
            price += 1
    return out


class BarTests(unittest.TestCase):
    def test_a_split_restates_the_bars_before_it_and_not_the_day_itself(self):
        """A 4-for-1 on 3 Sep: the 100 dollar shares of 1-2 Sep were 25 dollar shares, and four times the volume."""
        rows = charts.parse_daily([daily_row("2026-09-01", 100, 104, 96, 100, 1000),
                                   daily_row("2026-09-02", 100, 108, 100, 104, 1000),
                                   daily_row("2026-09-03", 26, 27, 25, 26, 4000, split=4.0),
                                   daily_row("2026-09-04", 26, 28, 26, 27, 4000)])
        got = charts.split_adjust(rows)
        self.assertEqual([round(x, 6) for x in got[0][1:]], [25.0, 26.0, 24.0, 25.0, 4000.0])
        self.assertEqual([round(x, 6) for x in got[1][1:]], [25.0, 27.0, 25.0, 26.0, 4000.0])
        self.assertEqual([round(x, 6) for x in got[2][1:]], [26.0, 27.0, 25.0, 26.0, 4000.0])      # the split's day: as it traded
        self.assertEqual(got[3][4], 27)
        # two splits compound: 2-for-1 then 3-for-1 makes the first day's shares a sixth
        rows = charts.parse_daily([daily_row("2026-01-02", 60, 60, 60, 60, 10), daily_row("2026-02-02", 30, 30, 30, 30, 20, 2.0),
                                   daily_row("2026-03-02", 10, 10, 10, 10, 60, 3.0)])
        got = charts.split_adjust(rows)
        self.assertAlmostEqual(got[0][4], 10.0)
        self.assertAlmostEqual(got[0][5], 60.0)
        self.assertAlmostEqual(got[1][4], 10.0)

    def test_a_row_that_cannot_be_a_bar_is_left_out(self):
        rows = charts.parse_daily([daily_row("2026-09-01", 10, 11, 9, 10), {"date": "2026-09-02"}, "nonsense",
                                   daily_row("2026-09-03", 10, 9, 11, 10),         # a high under its low
                                   daily_row("2026-09-04", 0, 11, 9, 10),          # a price of nothing
                                   daily_row("2026-09-07", 10, 11, 9, 10)])
        self.assertEqual([r[0] for r in rows], ["2026-09-01", "2026-09-07"])
        self.assertEqual(charts.parse_daily(None), [])

    def test_the_session_bars_are_new_yorks_regular_hours_in_summer_and_in_winter(self):
        summer = [iex_row("2026-10-05T13:25:00.000Z", 1, 1, 1, 1), iex_row("2026-10-05T13:30:00.000Z", 1, 1, 1, 1),
                  iex_row("2026-10-05T19:55:00.000Z", 1, 1, 1, 1), iex_row("2026-10-05T20:00:00.000Z", 1, 1, 1, 1)]
        winter = [iex_row("2026-12-07T14:25:00.000Z", 1, 1, 1, 1), iex_row("2026-12-07T14:30:00.000Z", 1, 1, 1, 1),
                  iex_row("2026-12-07T20:55:00.000Z", 1, 1, 1, 1), iex_row("2026-12-07T21:00:00.000Z", 1, 1, 1, 1)]
        for rows in (summer, winter):
            kept = charts.parse_intraday(rows)
            self.assertEqual([charts.label(b[0], False) for b in kept], ["09:30", "15:55"])
        self.assertEqual(charts.label(charts.parse_intraday(summer)[0][0], True), "Mon 09:30")

    def test_the_last_sessions_are_the_last_days_that_have_bars(self):
        rows = [iex_row(f"2026-09-{d:02d}T14:00:00.000Z", 1, 1, 1, 1) for d in (28, 29, 30)] + \
               [iex_row("2026-10-01T14:00:00.000Z", 1, 1, 1, 1)]
        bars = charts.parse_intraday(rows)
        self.assertEqual(len(charts.last_sessions(bars, 2)), 2)
        self.assertEqual(charts.last_sessions(bars, 2)[0][0].day, 30)
        self.assertEqual(len(charts.last_sessions(bars, 9)), 4)

    def test_a_ticker_is_letters_and_digits_and_nothing_a_url_could_carry(self):
        self.assertEqual(charts.clean_ticker(" nvda "), "NVDA")
        self.assertEqual(charts.clean_ticker("brk.b"), "BRK.B")
        for bad in ("", None, "A B", "AAPL?x=1", "../etc", "AAPL/..", "TOOLONGTICKER", "$", "AA\nPL", 12345678901):
            self.assertIsNone(charts.clean_ticker(bad), bad)
        self.assertEqual(charts._slug("BRK.B"), "brk-b")


class HeaderTests(unittest.TestCase):
    BARS = [("2026-10-01", 100, 101, 99, 100.0, 5), ("2026-10-02", 100, 111, 99, 110.0, 5)]

    def at(self, text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

    def test_with_no_fresher_price_it_is_the_last_close_from_the_one_before(self):
        head, live = charts.header(self.BARS, None, [], self.at("2026-10-03T15:00:00"))      # a Saturday
        self.assertEqual((head["price"], head["session"], head["at"], live), (110.0, "Closed", None, False))
        self.assertAlmostEqual(head["change"], 0.10)
        self.assertEqual(head["previous_close"], 100.0)

    def test_a_price_from_a_later_day_is_measured_from_the_last_close_and_is_live_while_fresh(self):
        quote = {"price": 121.0, "at": "2026-10-05T14:55:00+00:00"}                        # 10:55 in New York
        head, live = charts.header(self.BARS, quote, [], self.at("2026-10-05T15:00:00"))
        self.assertEqual((head["price"], head["session"], live), (121.0, "Regular session", True))
        self.assertAlmostEqual(head["change"], 0.10)                                         # 121 against 110
        self.assertEqual(head["at_label"], "10:55:00 New York")
        _, live = charts.header(self.BARS, quote, [], self.at("2026-10-05T15:30:00"))        # 35 minutes on: a halt or a holiday
        self.assertFalse(live)

    def test_after_hours_on_the_day_of_the_last_close_is_measured_from_that_close(self):
        quote = {"price": 112.2, "at": "2026-10-02T21:30:00+00:00"}                          # 17:30 in New York, after the close
        head, live = charts.header(self.BARS, quote, [], self.at("2026-10-02T21:35:00"))
        self.assertEqual((head["session"], live), ("After hours", True))
        self.assertAlmostEqual(head["change"], 112.2 / 110 - 1)
        earlier = {"price": 105.0, "at": "2026-10-02T18:00:00+00:00"}                        # 14:00 that day, before it: stale
        head, _ = charts.header(self.BARS, earlier, [], self.at("2026-10-02T21:35:00"))
        self.assertEqual(head["price"], 110.0)

    def test_the_newest_of_the_bars_and_the_quote_is_the_price(self):
        bars = charts.parse_intraday([iex_row("2026-10-05T14:50:00.000Z", 120, 121, 119, 120.5)])
        quote = {"price": 122.0, "at": "2026-10-05T14:58:00+00:00"}
        head, _ = charts.header(self.BARS, quote, bars, self.at("2026-10-05T15:00:00"))
        self.assertEqual(head["price"], 122.0)
        head, _ = charts.header(self.BARS, None, bars, self.at("2026-10-05T15:00:00"))
        self.assertEqual(head["price"], 120.5)


class ChartTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        charts._cache.clear()

    def test_a_daily_range_asks_for_the_daily_bars_and_the_latest_price_and_then_nothing(self):
        t = Tiingo(daily=week_of_daily(), latest=[{"ticker": "nvda", "tngoLast": 130.5, "timestamp": "2026-10-05T14:58:00.000Z"}])
        got = charts.chart(self.folder, "nvda", "1M", key="k", opener=t, now=NOW)
        self.assertEqual(len(t.asked), 2)
        self.assertIn("/tiingo/daily/nvda/prices?startDate=2021-", t.asked[0])               # five years back
        self.assertIn("/iex/?tickers=nvda", t.asked[1])
        self.assertEqual((got["ticker"], got["range"], got["kind"], got["currency"]), ("NVDA", "1M", "daily", "USD"))
        self.assertEqual(got["bars"][-1][0], "2026-10-02")
        self.assertEqual(got["price"]["price"], 130.5)
        self.assertTrue(got["live"])
        self.assertEqual(got["every_seconds"], charts.SLOW_SECONDS)                           # Tiingo alone: every three minutes
        again = charts.chart(self.folder, "NVDA", "6M", key="k", opener=t, now=NOW + timedelta(seconds=20))
        self.assertEqual(len(t.asked), 2)                                                    # the bars and the price are kept
        self.assertGreaterEqual(len(again["bars"]), len(got["bars"]))
        charts.chart(self.folder, "NVDA", "1M", key="k", opener=t, now=NOW + timedelta(seconds=130))
        self.assertEqual(len(t.asked), 3)                                                    # two minutes on: the price again
        self.assertIn("/iex/?", t.asked[2])

    def test_a_range_is_cut_from_the_last_bar(self):
        t = Tiingo(daily=week_of_daily())
        one_month = charts.chart(self.folder, "NVDA", "1M", key="k", opener=t, now=NOW)["bars"]
        last = date.fromisoformat(one_month[-1][0])
        self.assertTrue(all(b[0] >= (last - timedelta(days=31)).isoformat() for b in one_month))
        self.assertGreater(len(week_of_daily()), len(one_month))                              # the 40 days are more than a month

    def test_the_days_bars_are_the_sessions_and_come_with_labels(self):
        rows = [iex_row("2026-10-05T13:30:00.000Z", 130, 131, 129, 130.5, 50), iex_row("2026-10-05T13:35:00.000Z", 130.5, 132, 130, 131.5, 60),
                iex_row("2026-10-02T19:55:00.000Z", 109, 110, 108, 110.0, 70)]
        t = Tiingo(daily=week_of_daily(), bars=rows)
        got = charts.chart(self.folder, "NVDA", "1D", key="k", opener=t, now=NOW)
        self.assertEqual(got["kind"], "intraday")
        self.assertEqual(got["labels"], ["09:30", "09:35"])                                   # the last day only
        self.assertEqual(got["bars"][0], [int(datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc).timestamp()), 130, 131, 129, 130.5, 50])
        self.assertIn("resampleFreq=5min", t.asked[1])
        self.assertEqual(got["price"]["price"], 131.5)
        five = charts.chart(self.folder, "NVDA", "5D", key="k", opener=t, now=NOW)
        self.assertEqual(len(five["bars"]), 3)
        self.assertEqual(five["labels"][0], "Fri 15:55")
        self.assertIn("resampleFreq=15min", t.asked[-1])

    def test_what_tiingo_says_is_said_in_words(self):
        def http(code):
            return Tiingo(fail=urllib.error.HTTPError("u", code, "x", {}, None))
        for code, words in ((401, "rejected the key"), (429, "free limit"), (500, "HTTP 500")):
            charts._cache.clear()
            with self.assertRaises(charts.ChartError) as e:
                charts.chart(self.folder, "NVDA", "1M", key="k", opener=http(code), now=NOW)
            self.assertIn(words, str(e.exception))
        charts._cache.clear()
        daily_only = Tiingo(daily=week_of_daily())
        real = daily_only.__call__

        def refuse_bars(req, timeout=None):
            if "/iex/" in req.full_url and "/iex/?" not in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 403, "plan", {}, None)
            return real(req, timeout)
        with self.assertRaises(charts.ChartError) as e:
            charts.chart(self.folder, "NVDA", "1D", key="k", opener=refuse_bars, now=NOW)
        self.assertIn("did not give the day's bars", str(e.exception))
        self.assertEqual(charts.chart(self.folder, "NVDA", "1M", key="k", opener=refuse_bars, now=NOW)["range"], "1M")      # the daily ranges still work
        charts._cache.clear()
        with self.assertRaises(charts.ChartError) as e:
            charts.chart(self.folder, "NOPE", "1M", key="k", opener=Tiingo(daily=[]), now=NOW)              # an unknown ticker
        self.assertIn("US shares and funds", str(e.exception))
        with self.assertRaises(charts.ChartError) as e:
            charts.chart(self.folder, "NVDA", "1D", key="k", opener=Tiingo(daily=week_of_daily(), bars=[]), now=NOW)
        self.assertIn("no intraday", str(e.exception))
        with self.assertRaises(charts.ChartError):
            charts.chart(self.folder, "not a ticker!", "1M", key="k", opener=Tiingo(), now=NOW)
        saved = os.environ.pop("TIINGO_API_KEY", None)
        real = prices.load_env if hasattr(prices, "load_env") else None
        try:
            prices.load_env = lambda path: None
            with self.assertRaises(charts.ChartError) as e:
                charts.chart(self.folder, "NVDA", "1M", opener=Tiingo(), now=NOW)
            self.assertEqual(str(e.exception), env_config.NO_TIINGO_KEY)
        finally:
            if real:
                prices.load_env = real
            if saved is not None:
                os.environ["TIINGO_API_KEY"] = saved

    def test_charts_share_tiingos_allowance_with_the_company_update(self):
        for _ in range(charts.CHART_PER_HOUR):
            charts._spend(self.folder, NOW)
        self.assertEqual(len(charts.asked(self.folder, NOW)), charts.CHART_PER_HOUR)
        self.assertFalse(charts.room(self.folder, NOW))
        with self.assertRaises(charts.ChartError) as e:
            charts.chart(self.folder, "NVDA", "1M", key="k", opener=Tiingo(daily=week_of_daily()), now=NOW)
        self.assertIn("share of Tiingo", str(e.exception))
        self.assertTrue(charts.room(self.folder, NOW + timedelta(hours=1, minutes=1)))          # an hour on, there is room
        self.assertEqual(charts.asked(self.folder, NOW + timedelta(days=1, minutes=1)), [])       # a day on, the count is clear
        # the update leaves them room: the same requests count against its 50 an hour
        asked = []

        def fetch(ticker, start, key):
            asked.append(ticker)
            return [("2026-10-02", 100.0, 100.0, 1.0)]
        now = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)
        busy = [(now - timedelta(minutes=5)).isoformat()] * 45
        prices.update(["AAPL"], stored={}, key="k", fetch=fetch, today=date(2026, 10, 3), now=now, cash=None, fx=None, also_asked=busy)
        self.assertEqual(asked, [])                                                          # 45 of 50, 5 kept back: it waits
        prices.update(["AAPL"], stored={}, key="k", fetch=fetch, today=date(2026, 10, 3), now=now, cash=None, fx=None)
        self.assertIn("SPY", asked)                                                          # without them it asks

    def test_what_is_kept_in_memory_is_bounded(self):
        t = Tiingo(daily=week_of_daily(), latest=[])
        hour, day = charts.CHART_PER_HOUR, charts.CHART_PER_DAY
        charts.CHART_PER_HOUR = charts.CHART_PER_DAY = 10_000
        try:
            for i in range(charts.KEPT_MOST + 15):
                charts.chart(self.folder, f"T{i}", "1M", key="k", opener=t, now=NOW + timedelta(seconds=i))
        finally:
            charts.CHART_PER_HOUR, charts.CHART_PER_DAY = hour, day
        self.assertLessEqual(len(charts._cache), charts.KEPT_MOST)

    def test_the_owner_looking_at_a_chart_is_what_the_chat_is_told(self):
        t = Tiingo(daily=week_of_daily())
        charts.chart(self.folder, "NVDA", "1M", key="k", opener=t, now=NOW)
        seen = charts.cached("nvda", "1M", now=NOW)
        words = charts.summary(seen)
        self.assertEqual((words["ticker"], words["range"]), ("NVDA", "1M"))
        self.assertTrue(words["change_over_the_range"].endswith("%") and words["highest_price"].startswith("$"))
        self.assertIsNone(charts.cached("NVDA", "5Y", now=NOW))                              # not the one on show
        self.assertIsNone(charts.cached("NVDA", "1M", now=NOW + timedelta(hours=1)))         # nor one gone cold


class DemoChartTests(unittest.TestCase):
    def store(self):
        return world.demo_prices(date(2026, 10, 5))

    def test_the_demos_bars_are_made_from_its_closes_and_are_the_same_each_time(self):
        a, b = charts.demo_chart(self.store(), "KO", "6M"), charts.demo_chart(self.store(), "KO", "6M")
        self.assertEqual(a["bars"], b["bars"])
        self.assertTrue(a["demo"] and not a["live"])
        closes = prices.series(self.store(), "KO", "c")
        for bar in a["bars"]:
            self.assertAlmostEqual(bar[4], closes[bar[0]], places=3)                          # the close is the demo's close
            self.assertLessEqual(max(bar[1], bar[4]), bar[2])                                  # a high is above both ends
            self.assertGreaterEqual(min(bar[1], bar[4]), bar[3])

    def test_the_demos_day_runs_from_the_open_to_the_close_and_reaches_no_one(self):
        day = charts.demo_chart(self.store(), "KO", "1D")
        self.assertEqual((len(day["bars"]), day["labels"][0], day["labels"][-1]), (78, "09:30", "15:55"))
        closes = prices.series(self.store(), "KO", "c")
        last = max(closes)
        self.assertAlmostEqual(day["bars"][-1][4], closes[last], places=3)
        self.assertEqual(len(charts.demo_chart(self.store(), "KO", "5D")["bars"]), 5 * 26)
        with self.assertRaises(charts.ChartError):
            charts.demo_chart(self.store(), "ZZZZ", "6M")

    def test_the_server_answers_for_the_demo_and_for_a_bad_ticker(self):
        handler = server.Handler.__new__(server.Handler)
        handler.folder, handler.demo = tempfile.mkdtemp(), True
        write_json(os.path.join(handler.folder, "prices.json"), self.store())
        code, out = handler.price_chart({"ticker": "ko", "range": "1m"})
        self.assertTrue(out["ok"] and out["chart"]["demo"] and out["chart"]["range"] == "1M")
        self.assertFalse(handler.price_chart({"ticker": "../x"})[1]["ok"])
        self.assertFalse(handler.price_chart({"ticker": "ZZZZ"})[1]["ok"])
        code, out = handler.price_chart({"ticker": "KO", "range": "9Y"})                      # an unknown range is the default
        self.assertEqual(out["chart"]["range"], charts.DEFAULT_RANGE)

    def test_the_server_hands_the_chart_the_trade_streams_unless_env_says_off(self):
        handler = server.Handler.__new__(server.Handler)
        handler.folder, handler.demo = tempfile.mkdtemp(), False
        seen, real_chart, real_keys, real_env = [], charts.chart, feeds.keys, os.environ.get("LIVE_STREAM")
        charts.chart = lambda folder, ticker, range_, **kw: (seen.append(kw) or {"ticker": ticker})
        feeds.keys = lambda environ=None: {feeds.FINNHUB: "k"}
        try:
            os.environ.pop("LIVE_STREAM", None)
            self.assertTrue(handler.price_chart({"ticker": "KO"})[1]["ok"])
            self.assertIs(seen[-1]["live"], stream.STREAMS)
            self.assertEqual(seen[-1]["extra"], {feeds.FINNHUB: "k"})
            os.environ["LIVE_STREAM"] = "0"
            handler.price_chart({"ticker": "KO"})
            self.assertIsNone(seen[-1]["live"])
        finally:
            charts.chart, feeds.keys = real_chart, real_keys
            os.environ.pop("LIVE_STREAM", None)
            if real_env is not None:
                os.environ["LIVE_STREAM"] = real_env


class ChartPageTests(unittest.TestCase):
    def head(self):
        code = read(os.path.join(ROOT, "page", "chart.js"))
        curve = read(os.path.join(ROOT, "page", "curve.js"))
        return curve[:curve.index("function axisMoney(")] + code[:code.index("function pcDefault(")]

    def evaluate(self, body):
        return run_javascript(self.head() + "\nconst __out = (" + body + ");\n"
                              "(typeof process !== 'undefined') ? console.log(JSON.stringify(__out)) : JSON.stringify(__out);")

    def test_the_scale_has_room_and_round_steps(self):
        got = json.loads(self.evaluate("[[100, 110], [57.2, 60.1, 55], [5, 5], [0.12, 0.18]].map(v => pcScale(v))"))
        for (lo, hi), s in zip(((100, 110), (55, 60.1), (5, 5), (0.12, 0.18)), got):
            self.assertLessEqual(s["lo"], lo)
            self.assertGreaterEqual(s["hi"], hi)
            self.assertLess(s["lo"], s["hi"])
        self.assertEqual(got[0]["step"], 5)
        self.assertEqual(got[1]["step"], 2)

    def test_candles_are_a_smear_below_the_width_of_a_slot_and_a_line_is_drawn_instead(self):
        got = json.loads(self.evaluate("[pcKindShown('candles', 4.5), pcKindShown('candles', 0.9), pcKindShown('line', 9), pcSlots(10, 6, 100).slot, pcSlots(10, 6, 100).x(0), pcBody(0.9), pcBody(5), pcBody(40)]"))
        self.assertEqual(got, ["candles", "line", "line", 10, 11, 1, 3, 14])

    def test_prices_are_written_with_the_places_the_step_needs(self):
        got = json.loads(self.evaluate("[pcPrice(120, 20), pcPrice(12.5, 2.5), pcPrice(12.55, 0.05), pcPrice(1234.5, 5), pcPrice(0.3, 0.1)]"))
        self.assertEqual(got, ["$120", "$12.5", "$12.55", "$1,235", "$0.3"])

    def test_the_tab_is_there_and_colour_never_says_good_or_bad(self):
        page, css = page_source(), read(os.path.join(ROOT, "page", "desk.css"))
        self.assertIn("{id:'chart',     label:'Chart',     pages:['chart']}", page)
        self.assertIn("'renderChart'", page)
        code = read(os.path.join(ROOT, "page", "chart.js"))
        self.assertNotRegex(code, r"#[0-9a-fA-F]{3,8}\b|rgba?\(")                      # no colour typed in
        block = css[css.index("the price chart (chart.js)"):css.index("Ask: the chat (chat.js)")]
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")
        self.assertIn(".pcx .body-up{fill:var(--surface)", block)                       # up: hollow
        self.assertIn(".pcx .body-down{fill:var(--accent)", block)                      # down: filled
        for forbidden in ("--critical", "--warn", "green", "red"):
            self.assertNotIn(forbidden, block)
        self.assertNotRegex(block, r"font-size:\s*(?:[0-9]|1[01])(?:\.\d+)?px")        # text 12px or larger

    def test_a_live_chart_asks_again_only_on_show_open_and_fresh_and_never_in_the_demo_or_a_past_day(self):
        tick = template_function("chartTick", page_source())
        for held in ("currentPage !== 'chart'", "document.hidden", "pcx.busy", "pcx.hold", "!d.live", "DATA.as_of", "DATA.demo"):
            self.assertIn(held, tick)
        self.assertIn("d.every_seconds", tick)                                          # how often is charts.py's, with each chart
        self.assertNotRegex(tick.replace("1000", ""), r"\b\d{2,}\b")                   # and the page guesses none (1000: a second in milliseconds, and a second's slack)
        timer = [l for l in page_source().splitlines() if "setInterval(" in l][0]
        self.assertIn("chartTick()", timer)
        self.assertEqual(page_source().count("setInterval("), 1)
        self.assertEqual(build_desk.compute(generate_demo_data.generate(date(2026, 10, 5)), today=date(2026, 10, 5))["chart"],
                         {"ranges": list(charts.RANGES), "default": charts.DEFAULT_RANGE})
        self.assertRegex(page_source(), r"\}, 1000\);")                                  # the one timer ticks every second

    def test_the_page_reaches_only_the_desks_own_chart_endpoint(self):
        code = read(os.path.join(ROOT, "page", "chart.js"))
        self.assertEqual(re.findall(r"fetch\('([^']+)'", code), ["/chart"])
        self.assertNotIn("http", code.replace("http://www.w3.org", ""))


if __name__ == "__main__":
    unittest.main()
