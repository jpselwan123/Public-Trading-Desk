"""The chart's other feeds (feeds.py: Finnhub, Alpaca) and how charts.py combines them with Tiingo. No
network: each provider is a stand-in that keeps every request it is given."""
from support import *  # noqa: F401,F403
import world  # noqa: E402

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)          # 11:00 in New York, a Monday, in daylight time
LAST_CLOSE = 130.0
FINNHUB_KEY, ALPACA_PAIR = "finnhub-SECRET-key", ("alpaca-KEY-id", "alpaca-SECRET-value")
EVERY_KEY = {feeds.FINNHUB: FINNHUB_KEY, feeds.ALPACA: ALPACA_PAIR}


def unix(text):
    return int(env_config.moment(text).timestamp())


def daily(i, price):
    return {"date": (date(2026, 8, 24) + timedelta(days=i)).isoformat() + "T00:00:00.000Z", "open": price, "high": price + 2,
            "low": price - 1, "close": price + 1, "volume": 1000, "adjClose": price + 1, "splitFactor": 1.0}


def week_of_daily():
    out, price = [], 100.0
    for i in range(40):
        if (date(2026, 8, 24) + timedelta(days=i)).weekday() < 5:
            out.append(daily(i, price))
            price += 1
    return out                                                       # the last close is 2026-10-02: LAST_CLOSE


class Market:
    """Tiingo, Finnhub and Alpaca in one stand-in: it answers each from its own data and keeps the
    (address, headers) of every request."""

    def __init__(self, finnhub=None, trade=None, bars=None, tiingo_bars=None, tiingo_latest=None, fail=None):
        self.finnhub, self.trade, self.bars = finnhub, trade, bars
        self.tiingo_bars, self.tiingo_latest, self.fail, self.asked = tiingo_bars or [], tiingo_latest or [], fail or {}, []

    def host(self, name):
        return [u for u, _ in self.asked if name in u]

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.asked.append((url, dict(req.header_items())))
        for host, code in self.fail.items():
            if host in url:
                raise urllib.error.HTTPError(url, code, "no", {}, None)
        if "finnhub.io" in url:
            return FakeResponse(self.finnhub if self.finnhub is not None else {"c": 0, "t": 0})
        if "/trades/latest" in url:
            return FakeResponse({"symbol": "NVDA", "trade": self.trade} if self.trade else {})
        if "data.alpaca.markets" in url:
            return FakeResponse({"bars": self.bars or [], "symbol": "NVDA", "next_page_token": None})
        if "/iex/?" in url:
            return FakeResponse(self.tiingo_latest)
        if "/iex/" in url:
            return FakeResponse(self.tiingo_bars)
        return FakeResponse(week_of_daily())


def finnhub_at(text, price):
    return {"c": price, "d": 0.1, "dp": 0.1, "h": price + 1, "l": price - 1, "o": price, "pc": 127.0, "t": unix(text)}


def trade_at(text, price):
    return {"t": text, "x": "V", "p": price, "s": 100, "c": ["@"], "i": 1, "z": "C"}


def alpaca_bar(text, o, h, l, c, v):
    return {"t": text, "o": o, "h": h, "l": l, "c": c, "v": v, "n": 5, "vw": c}


class FeedTests(unittest.TestCase):
    def test_a_feed_is_asked_only_when_its_key_is_in_env(self):
        self.assertEqual(feeds.keys({}), {})
        self.assertEqual(feeds.keys({"FINNHUB_API_KEY": " k "}), {feeds.FINNHUB: "k"})
        self.assertEqual(feeds.keys({"ALPACA_API_KEY": "id"}), {})                                   # half a pair is none
        self.assertEqual(feeds.keys({"ALPACA_API_KEY": "id", "ALPACA_API_SECRET": "s"}), {feeds.ALPACA: ("id", "s")})
        self.assertEqual(feeds.keys(EVERY_KEY and {"FINNHUB_API_KEY": "f", "ALPACA_API_KEY": "i", "ALPACA_API_SECRET": "s"}),
                         {feeds.FINNHUB: "f", feeds.ALPACA: ("i", "s")})

    def test_finnhubs_quote_is_a_price_and_a_moment_and_an_unknown_symbol_is_none(self):
        market = Market(finnhub=finnhub_at("2026-10-05T14:59:30Z", 131.25))
        got = feeds.finnhub_quote("brk-b", FINNHUB_KEY, market)
        self.assertEqual(got, {"price": 131.25, "at": "2026-10-05T14:59:30+00:00", "feed": "Finnhub"})
        url, headers = market.asked[0]
        self.assertIn("symbol=BRK.B", url)                                                           # a share class with a dot
        self.assertNotIn(FINNHUB_KEY, url)                                                           # the key is in a header
        self.assertEqual(headers.get("X-finnhub-token"), FINNHUB_KEY)
        for nothing in ({"c": 0, "t": 0}, {}, {"c": 5}, {"c": "x", "t": "y"}, []):
            self.assertIsNone(feeds.finnhub_quote("ZZZZ", "k", Market(finnhub=nothing)))

    def test_alpacas_latest_trade_and_bars_are_read_in_the_desks_shapes(self):
        market = Market(trade=trade_at("2026-10-05T14:59:58.123456789Z", 131.3),
                        bars=[alpaca_bar("2026-10-05T13:30:00Z", 130, 131, 129.5, 130.5, 900),
                              alpaca_bar("2026-10-05T13:31:00Z", 130.5, 131.2, 130.4, 131.0, 700), "junk"])
        got = feeds.alpaca_quote("NVDA", ALPACA_PAIR, market)
        self.assertEqual(got, {"price": 131.3, "at": "2026-10-05T14:59:58+00:00", "feed": "Alpaca"})
        url, headers = market.asked[0]
        self.assertIn("feed=iex", url)                                                               # the free feed, never the consolidated
        self.assertNotIn("alpaca-", url)
        self.assertEqual((headers.get("Apca-api-key-id"), headers.get("Apca-api-secret-key")), ALPACA_PAIR)
        rows = feeds.alpaca_bars("NVDA", 1, "2026-10-01", ALPACA_PAIR, market)
        self.assertEqual(len(rows), 2)
        burl = market.asked[1][0]
        for part in ("timeframe=1Min", "start=2026-10-01", "feed=iex", "adjustment=split"):
            self.assertIn(part, burl)
        bars = charts.parse_intraday(rows)
        self.assertEqual([(b[1], b[4], b[5]) for b in bars], [(130.0, 130.5, 900.0), (130.5, 131.0, 700.0)])
        self.assertIsNone(feeds.alpaca_quote("NVDA", ALPACA_PAIR, Market()))
        self.assertEqual(feeds.alpaca_bars("NVDA", 1, "2026-10-01", ALPACA_PAIR, Market()), [])

    def test_what_a_feed_says_when_it_fails_is_said_in_words_and_names_it(self):
        for code, words in ((401, "did not accept the key"), (403, "did not accept the key"), (429, "free limit is used up"), (500, "HTTP 500")):
            for call in (lambda m: feeds.finnhub_quote("NVDA", "k", m), lambda m: feeds.alpaca_quote("NVDA", ("a", "b"), m)):
                with self.assertRaises(feeds.FeedError) as e:
                    call(Market(fail={"finnhub.io": code, "alpaca.markets": code}))
                self.assertIn(words, str(e.exception))
                self.assertTrue(str(e.exception).startswith(("Finnhub", "Alpaca")))
        def drop(req, timeout=None):
            raise OSError("timed out")
        with self.assertRaises(feeds.FeedError) as e:
            feeds.finnhub_quote("NVDA", "k", drop)
        self.assertIn("Can't reach Finnhub", str(e.exception))
        self.assertEqual(feeds.finnhub_quote("NVDA", "k", Market(fail={"finnhub.io": 404})), None)      # an unknown ticker is not an error

    def test_the_newest_quote_wins_a_tie_goes_to_the_named_order_and_disagreement_is_noticed(self):
        q = lambda feed, at, price: {"feed": feed, "at": at, "price": price}
        a, f, t = (q("Alpaca", "2026-10-05T14:59:50+00:00", 131.0), q("Finnhub", "2026-10-05T14:59:58+00:00", 131.1),
                   q("Tiingo", "2026-10-05T14:57:00+00:00", 130.9))
        best, differ = feeds.combine([a, f, t], NOW)
        self.assertEqual((best["feed"], differ), ("Finnhub", False))
        same = "2026-10-05T14:59:58+00:00"
        self.assertEqual(feeds.combine([q("Finnhub", same, 131.0), q("Tiingo", same, 131.0), q("Alpaca", same, 131.0)], NOW)[0]["feed"], "Alpaca")
        self.assertEqual(feeds.combine([q("Tiingo", same, 131.0), q("Finnhub", same, 131.0)], NOW)[0]["feed"], "Finnhub")
        # half a percent apart at one moment: noticed. The same gap with one of them old: not a disagreement, only age
        self.assertTrue(feeds.combine([q("Alpaca", same, 131.0), q("Finnhub", "2026-10-05T14:59:30+00:00", 131.8)], NOW)[1])
        self.assertFalse(feeds.combine([q("Alpaca", same, 131.0), q("Finnhub", "2026-10-05T14:55:00+00:00", 131.8)], NOW)[1])
        self.assertFalse(feeds.combine([q("Alpaca", same, 131.0), q("Finnhub", same, 131.5)], NOW)[1])      # under half a percent
        self.assertEqual(feeds.combine([None, {}, {"at": "x", "price": 1, "feed": "Alpaca"}], NOW), (None, False))
        self.assertEqual(feeds.combine([], NOW), (None, False))


class FoldTests(unittest.TestCase):
    def bars(self):
        return charts.parse_intraday([
            {"date": "2026-10-05T14:57:00Z", "open": 130.0, "high": 130.6, "low": 129.9, "close": 130.4, "volume": 500},
            {"date": "2026-10-05T14:58:00Z", "open": 130.4, "high": 130.8, "low": 130.3, "close": 130.7, "volume": 600}])

    def test_a_fresher_price_joins_the_bar_it_falls_in_or_opens_the_next(self):
        quote = lambda at, price: {"at": at, "price": price, "feed": "Alpaca"}
        inside = charts.fold(self.bars(), quote("2026-10-05T14:58:40+00:00", 131.2), 1)
        self.assertEqual([round(x, 2) for x in inside[-1][1:]], [130.4, 131.2, 130.3, 131.2, 600.0])      # its high and close move
        self.assertEqual(len(inside), 2)
        lower = charts.fold(self.bars(), quote("2026-10-05T14:58:50+00:00", 129.0), 1)
        self.assertEqual((lower[-1][3], lower[-1][4]), (129.0, 129.0))
        after = charts.fold(self.bars(), quote("2026-10-05T15:00:20+00:00", 131.0), 1)
        self.assertEqual(len(after), 3)
        new = after[-1]
        self.assertEqual((new[0].strftime("%H:%M"), new[1], new[4], new[5]), ("15:00", 130.7, 131.0, 0.0))      # from the last close; volume unknown
        self.assertEqual(charts.fold(self.bars(), quote("2026-10-05T15:02:30+00:00", 131.0), 1)[-1][0].strftime("%H:%M"), "15:02")
        self.assertEqual(len(charts.fold(self.bars(), quote("2026-10-05T14:59:30+00:00", 131.0), 5)), 2)       # a 5-minute bar: inside the last
        # a price that is not a regular-session price of the bars' own day is not a bar
        for stale in ("2026-10-05T14:50:00+00:00", "2026-10-05T11:30:00+00:00", "2026-10-05T20:30:00+00:00", "2026-10-06T14:00:00+00:00"):
            self.assertEqual(charts.fold(self.bars(), quote(stale, 140.0), 1), self.bars(), stale)
        self.assertEqual(charts.fold([], quote("2026-10-05T14:59:30+00:00", 1.0), 1), [])
        self.assertEqual(charts.fold(self.bars(), None, 1), self.bars())


class CombinedChartTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        charts._cache.clear()

    def chart(self, market, range_="1M", extra=EVERY_KEY, now=NOW):
        return charts.chart(self.folder, "NVDA", range_, key="tiingo-SECRET", opener=market, now=now, extra=extra)

    def test_a_daily_range_takes_the_newest_price_of_every_feed_and_says_whose_it_is(self):
        market = Market(finnhub=finnhub_at("2026-10-05T14:59:50Z", 131.5), trade=trade_at("2026-10-05T14:59:58Z", 131.4),
                        tiingo_latest=[{"ticker": "nvda", "tngoLast": 131.0, "timestamp": "2026-10-05T14:55:00.000Z"}])
        got = self.chart(market)
        self.assertEqual((got["price"]["price"], got["price"]["via"], got["live"]), (131.4, "Alpaca", True))
        self.assertAlmostEqual(got["price"]["change"], 131.4 / LAST_CLOSE - 1)                              # from the last close
        self.assertEqual([(f["name"], f["age"]) for f in got["feeds"]], [("Alpaca", 2), ("Finnhub", 10)])
        self.assertEqual(got["every_seconds"], charts.FAST_SECONDS)
        self.assertEqual(market.host("/iex/?"), [])                                                  # Tiingo's scarce hourly allowance is left alone
        self.assertEqual(len(market.host("tiingo.com")), 1)                                          # the daily bars, once
        self.assertEqual((got["differ"], got["problems"]), (False, []))
        for url, headers in market.asked:
            for secret in ("SECRET", "alpaca-KEY"):
                self.assertNotIn(secret, url)                                                        # no key in any address

    def test_when_no_fast_feed_answers_tiingos_latest_is_asked_and_alone_it_is_slow(self):
        market = Market(tiingo_latest=[{"ticker": "nvda", "tngoLast": 131.0, "timestamp": "2026-10-05T14:58:00.000Z"}])
        got = self.chart(market, extra={})
        self.assertEqual((got["price"]["via"], got["every_seconds"], len(market.asked)), ("Tiingo", charts.SLOW_SECONDS, 2))
        charts._cache.clear()
        market = Market(finnhub={"c": 0, "t": 0}, tiingo_latest=[{"ticker": "nvda", "tngoLast": 131.0, "timestamp": "2026-10-05T14:58:00.000Z"}])
        got = self.chart(market, extra={feeds.FINNHUB: "k"})
        self.assertEqual(got["price"]["via"], "Tiingo")                                              # Finnhub knew nothing: Tiingo's is the price
        self.assertEqual(got["every_seconds"], charts.SLOW_SECONDS)

    def test_the_days_bars_are_alpacas_by_the_minute_with_the_newest_price_in_the_last_candle(self):
        market = Market(finnhub=finnhub_at("2026-10-05T14:59:40Z", 131.6),
                        bars=[alpaca_bar("2026-10-05T14:57:00Z", 130.0, 130.6, 129.9, 130.4, 500), alpaca_bar("2026-10-05T14:58:00Z", 130.4, 130.8, 130.3, 130.7, 600),
                              alpaca_bar("2026-10-02T19:59:00Z", 126.0, 127.1, 125.9, 127.0, 700)],
                        tiingo_bars=[{"date": "2026-10-05T14:50:00.000Z", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
        got = self.chart(market, "1D")
        self.assertEqual((got["kind"], got["bar_minutes"], got["labels"]), ("intraday", 1, ["10:57", "10:58", "10:59"]))   # the last day's bars, and the price's minute
        self.assertEqual(got["bars"][-1][4], 131.6)                                                  # Finnhub's price is in the last candle
        self.assertEqual(got["bars"][-1][5], 0)
        self.assertEqual(got["price"]["price"], 131.6)
        self.assertEqual(market.host("tiingo.com/iex/"), [])                                         # Tiingo's day bars were not needed
        self.assertIn("timeframe=1Min", market.host("/bars")[0])
        self.assertEqual(got["every_seconds"], charts.FAST_SECONDS)
        five = self.chart(market, "5D")
        self.assertEqual(five["bar_minutes"], 5)
        self.assertIn("timeframe=5Min", market.host("/bars")[-1])
        self.assertIn("1-minute", charts.summary(got)["bars"])

    def test_a_feed_that_fails_is_named_and_the_others_carry_on(self):
        market = Market(finnhub=finnhub_at("2026-10-05T14:59:40Z", 131.6), fail={"data.alpaca.markets": 403},
                        tiingo_bars=[{"date": "2026-10-05T14:50:00.000Z", "open": 131, "high": 131.5, "low": 130.9, "close": 131.2, "volume": 5}])
        got = self.chart(market, "1D")
        self.assertEqual(got["problems"][0], "Alpaca did not accept the key: check its keys in .env")
        self.assertEqual(got["bar_minutes"], 5)                                                      # Tiingo's bars stood in
        self.assertEqual((got["price"]["via"], got["every_seconds"]), ("Finnhub", charts.FAST_SECONDS))
        charts._cache.clear()
        daily_only = self.chart(Market(fail={"finnhub.io": 429, "data.alpaca.markets": 429,
                                             "tiingo.com/iex": 429}), "1M")
        self.assertEqual(len(daily_only["problems"]), 3)                                             # all three named, the chart still drawn
        self.assertEqual((daily_only["price"]["price"], daily_only["every_seconds"]), (LAST_CLOSE, charts.SLOW_SECONDS))
        self.assertIsNone(daily_only["price"]["via"])

    def test_feeds_that_disagree_are_noticed(self):
        market = Market(finnhub=finnhub_at("2026-10-05T14:59:40Z", 131.0), trade=trade_at("2026-10-05T14:59:50Z", 132.0))
        got = self.chart(market)
        self.assertTrue(got["differ"])
        self.assertEqual(got["price"]["via"], "Alpaca")                                              # the newest is the price shown

    def test_each_feed_has_its_own_allowance_by_the_minute_and_a_price_is_kept_a_few_seconds(self):
        old = dict(charts.ALLOWANCE)
        charts.ALLOWANCE[feeds.FINNHUB] = (2, 60)
        try:
            market = Market(finnhub=finnhub_at("2026-10-05T14:59:40Z", 131.0))
            for i in range(5):
                self.chart(market, extra={feeds.FINNHUB: "k"}, now=NOW + timedelta(seconds=10 * i))
            self.assertEqual(len(market.host("finnhub.io")), 2)                                      # five looks, the third and later within the minute: none
            self.assertEqual(len(charts._stamps(charts._stored(self.folder)["feeds"]["Finnhub"], NOW + timedelta(seconds=40), 60)), 2)
            self.chart(market, extra={feeds.FINNHUB: "k"}, now=NOW + timedelta(seconds=75))
            self.assertEqual(len(market.host("finnhub.io")), 3)                                      # a minute on there is room again
        finally:
            charts.ALLOWANCE.clear()
            charts.ALLOWANCE.update(old)
        charts._cache.clear()
        market = Market(finnhub=finnhub_at("2026-10-05T14:59:40Z", 131.0))
        self.chart(market, extra={feeds.FINNHUB: "k"})
        self.chart(market, extra={feeds.FINNHUB: "k"}, now=NOW + timedelta(seconds=3))
        self.assertEqual(len(market.host("finnhub.io")), 1)                                          # three seconds on: the same price
        self.chart(market, extra={feeds.FINNHUB: "k"}, now=NOW + timedelta(seconds=12))
        self.assertEqual(len(market.host("finnhub.io")), 2)

    def test_tiingos_count_is_untouched_by_the_other_feeds(self):
        market = Market(finnhub=finnhub_at("2026-10-05T14:59:40Z", 131.0), trade=trade_at("2026-10-05T14:59:50Z", 131.0))
        self.chart(market)
        self.assertEqual(len(charts.asked(self.folder, NOW)), 1)                                    # the daily bars alone
        self.assertEqual(sorted(charts._stored(self.folder)["feeds"]), ["Alpaca", "Finnhub"])


class PageFeedsTests(unittest.TestCase):
    def test_the_page_says_whose_price_it_is_how_old_the_others_are_and_when_they_differ(self):
        code = read(os.path.join(ROOT, "page", "chart.js"))
        for held in ("p.via", "d.feeds", "d.differ", "d.problems", "pcAge(d.every_seconds)"):
            self.assertIn(held, code)
        program = code[code.index("function pcAge("):code.index("function pcNoteDraw(")]
        got = json.loads(run_javascript(program + "\nconsole.log(JSON.stringify([pcAge(4), pcAge(15), pcAge(89), pcAge(90), pcAge(180)]));"))
        self.assertEqual(got, ["4 s", "15 s", "89 s", "2 min", "3 min"])

    def test_the_new_hosts_are_where_the_network_doc_would_look(self):
        for name in ("feeds.py",):
            source = read(os.path.join(ROOT, name))
            self.assertNotIn(".post(", source)
            for forbidden in ("import t212", "import execute", "orders.json"):
                self.assertNotIn(forbidden, source)
        hosts = set(re.findall(r"https://([a-z.]+)/", read(os.path.join(ROOT, "feeds.py"))))
        self.assertEqual(hosts, {"finnhub.io", "data.alpaca.markets"})


if __name__ == "__main__":
    unittest.main()
