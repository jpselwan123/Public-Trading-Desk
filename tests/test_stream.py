"""stream: the trade streams. A fake Alpaca and a fake Finnhub, written from their documented protocols, on this
machine: the whole way from a connection to a trade in the chart's hands."""
from support import *  # noqa: F401,F403
import stream  # noqa: E402
import wsclient  # noqa: E402
import wsfake  # noqa: E402
import test_feeds  # noqa: E402  (its stand-in for Tiingo, Alpaca and Finnhub, by request)

KEYS = {feeds.ALPACA: ("alpaca-key-id", "alpaca-SECRET"), feeds.FINNHUB: "finnhub-token"}


def alpaca_trade(price, at="2026-10-05T14:59:58.123456789Z", ticker="NVDA", size=100):
    return json.dumps([{"T": "t", "S": ticker, "i": 1, "x": "V", "p": price, "s": size, "c": ["@"], "t": at, "z": "C"}])


def finnhub_trade(price, ms=1791212398123, ticker="NVDA", size=100):
    return json.dumps({"data": [{"p": price, "s": ticker, "t": ms, "v": size, "c": ["1"]}], "type": "trade"})


class Alpaca:
    """A script for an Alpaca data stream: it greets, asks for the sign-in, answers it, and keeps what it is told."""

    def __init__(self, trades=(), answer=None, then=None):
        self.trades, self.answer, self.then, self.received = list(trades), answer, then, []

    def __call__(self, peer):
        peer.send('[{"T":"success","msg":"connected"}]')
        self.received.append(json.loads(peer.recv(3)))
        peer.send(self.answer or '[{"T":"success","msg":"authenticated"}]')
        if self.answer:
            time.sleep(0.2)
            return
        first = True
        while True:
            message = peer.recv(0.3)
            if isinstance(message, str):
                self.received.append(json.loads(message))
                if first:
                    first = False
                    for trade in self.trades:
                        peer.send(trade)
                    if self.then:
                        self.then(peer)
                        return
            elif isinstance(message, tuple) and message[0] == "close":
                return
            elif message is None and peer.closed:
                return


class Finnhub:
    def __init__(self, trades=()):
        self.trades, self.received = list(trades), []

    def __call__(self, peer):
        peer.send('{"type":"ping"}')
        sent = False
        while True:
            message = peer.recv(0.3)
            if isinstance(message, str):
                self.received.append(json.loads(message))
                if not sent:
                    sent = True
                    for trade in self.trades:
                        peer.send(trade)
            elif isinstance(message, tuple) and message[0] == "close":
                return
            elif message is None and peer.closed:
                return


def wait_for(test, condition, seconds=4.0):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


class ProtocolTests(unittest.TestCase):
    def test_alpaca_messages_are_read_for_trades_the_sign_in_and_errors(self):
        trades, error, signed = stream.alpaca_parse(alpaca_trade(131.4))
        self.assertEqual(trades, [{"ticker": "NVDA", "price": 131.4, "at": "2026-10-05T14:59:58.123+00:00", "size": 100}])
        self.assertEqual((error, signed), (None, False))
        self.assertTrue(stream.alpaca_parse('[{"T":"success","msg":"authenticated"}]')[2])
        self.assertEqual(stream.alpaca_parse('[{"T":"success","msg":"connected"}]'), ([], None, False))
        self.assertEqual(stream.alpaca_parse('[{"T":"subscription","trades":["NVDA"]}]'), ([], None, False))
        for code, words in ((402, "did not accept the key"), (401, "did not accept the key"), (406, "one free connection"),
                            (405, "that many tickers"), (500, "error 500")):
            self.assertIn(words, stream.alpaca_parse(json.dumps([{"T": "error", "code": code, "msg": "x"}]))[1])
        for junk in ("not json", "[]", "[1, 2]", '[{"T":"t","p":0,"t":"2026-10-05T14:59:58Z"}]', '[{"T":"t","p":"x"}]', "null"):
            self.assertEqual(stream.alpaca_parse(junk)[0], [], junk)
        odd = json.dumps([{"T": "t", "S": "NVDA", "p": 131.2, "s": 3, "t": "2026-10-05T14:59:58Z", "c": ["@", "I"]}])
        self.assertEqual(stream.alpaca_parse(odd)[0], [{"ticker": "NVDA", "price": 131.2, "at": "2026-10-05T14:59:58.000+00:00", "size": 3, "odd": True}])
        two = json.dumps([{"T": "t", "S": "aapl", "p": 1.5, "s": 3, "t": "2026-10-05T14:59:58Z"}, {"T": "t", "S": "NVDA", "p": 2.5, "s": 4, "t": "2026-10-05T14:59:59Z"}])
        self.assertEqual([t["ticker"] for t in stream.alpaca_parse(two)[0]], ["AAPL", "NVDA"])

    def test_finnhub_messages_are_read_in_milliseconds_and_a_ping_or_junk_is_nothing(self):
        trades, error, _ = stream.finnhub_parse(finnhub_trade(131.4, 1791212398123))
        self.assertEqual(trades, [{"ticker": "NVDA", "price": 131.4, "at": "2026-10-05T14:59:58.123+00:00", "size": 100}])
        self.assertIsNone(error)
        self.assertEqual(stream.finnhub_parse('{"type":"ping"}'), ([], None, False))
        self.assertIn("Invalid token", stream.finnhub_parse('{"type":"error","msg":"Invalid token"}')[1])
        for junk in ("not json", "[]", '{"type":"trade","data":[{"p":0,"s":"X","t":1}]}', '{"type":"trade","data":[1]}', "null"):
            self.assertEqual(stream.finnhub_parse(junk)[0], [], junk)


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.servers = []
        self.streams = None

    def tearDown(self):
        if self.streams:
            self.streams.stop()
        for server in self.servers:
            server.stop()

    def fake(self, script, **kw):
        server = wsfake.FakeServer(script, **kw)
        self.servers.append(server)
        return server

    def streams_for(self, alpaca=None, finnhub=None, **kw):
        urls = {}
        if alpaca:
            urls[feeds.ALPACA] = alpaca.url("/v2/iex")
        if finnhub:
            urls[feeds.FINNHUB] = finnhub.url("/", "token={key}")
        kw.setdefault("poll", 0.05)
        kw.setdefault("backoff", (0.05, 0.1))
        kw.setdefault("refused_wait", 0.5)
        self.streams = stream.Streams(urls=urls, **kw)
        return self.streams

    def test_alpacas_stream_signs_in_subscribes_and_hands_over_each_trade(self):
        script = Alpaca([alpaca_trade(131.4, "2026-10-05T14:59:58Z"), alpaca_trade(131.45, "2026-10-05T14:59:59Z")])
        server = self.fake(script)
        streams = self.streams_for(alpaca=server)
        now = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
        streams.want("nvda", KEYS)
        streams.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: len(streams.recent(feeds.ALPACA, "NVDA", now)) == 2))
        self.assertEqual(script.received[0], {"action": "auth", "key": "alpaca-key-id", "secret": "alpaca-SECRET"})
        self.assertEqual(script.received[1], {"action": "subscribe", "trades": ["NVDA"]})
        self.assertEqual([t["price"] for t in streams.recent(feeds.ALPACA, "nvda", now)], [131.4, 131.45])
        last = streams.last(feeds.ALPACA, "NVDA", now)
        self.assertEqual((last["price"], last["feed"], last["stream"]), (131.45, "Alpaca", True))
        self.assertTrue(streams.streaming(feeds.ALPACA))
        self.assertIsNone(streams.last(feeds.ALPACA, "AAPL", now))
        self.assertEqual(streams.problems(), [])
        streams.add(feeds.ALPACA, {"ticker": "NVDA", "price": 99.0, "at": "2026-10-05T14:59:59.900+00:00", "size": 1, "odd": True})
        self.assertEqual(streams.last(feeds.ALPACA, "NVDA", now)["price"], 131.45)                 # an odd lot is not the price

    def test_finnhubs_stream_takes_its_token_in_the_address_and_a_symbol_at_a_time(self):
        script = Finnhub([finnhub_trade(131.4, 1791212398123), finnhub_trade(131.5, 1791212399000)])
        server = self.fake(script)
        streams = self.streams_for(finnhub=server)
        now = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
        streams.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: len(streams.recent(feeds.FINNHUB, "NVDA", now)) == 2))
        self.assertEqual(server.requests[0]["path"], "/?token=finnhub-token")
        self.assertEqual(script.received[0], {"type": "subscribe", "symbol": "NVDA"})
        self.assertEqual(streams.last(feeds.FINNHUB, "NVDA", now)["price"], 131.5)
        streams.want("AAPL", KEYS)
        self.assertTrue(wait_for(self, lambda: {"type": "subscribe", "symbol": "AAPL"} in script.received))

    def test_a_feed_without_a_key_is_never_opened(self):
        server = self.fake(Alpaca())
        streams = self.streams_for(alpaca=server)
        streams.want("NVDA", {})
        streams.want("NVDA", {feeds.FINNHUB: "k"})
        time.sleep(0.3)
        self.assertEqual(server.requests, [])
        self.assertNotIn(feeds.ALPACA, streams.workers)

    def test_tickers_come_and_go_with_what_is_asked_about(self):
        script = Alpaca()
        server = self.fake(script)
        clock = [0.0]
        streams = self.streams_for(alpaca=server, clock=lambda: clock[0], idle=60)
        streams.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: {"action": "subscribe", "trades": ["NVDA"]} in script.received))
        clock[0] = 30
        streams.want("AAPL", KEYS)
        self.assertTrue(wait_for(self, lambda: {"action": "subscribe", "trades": ["AAPL"]} in script.received))
        clock[0] = 70                                                    # NVDA has not been asked about for 70 seconds, AAPL for 40
        self.assertTrue(wait_for(self, lambda: {"action": "unsubscribe", "trades": ["NVDA"]} in script.received))
        self.assertEqual(len(server.requests), 1)                       # one connection throughout
        # only WATCH_MOST at a time: the oldest go
        for i, t in enumerate(("A", "B", "C", "D", "E", "F", "G")):
            clock[0] = 71 + i * 0.001
            streams.want(t, KEYS)
        self.assertLessEqual(len(streams.workers[feeds.ALPACA].current()), stream.WATCH_MOST)

    def test_a_feed_nobody_asks_about_closes_and_a_later_look_opens_it_again(self):
        script = Alpaca()
        server = self.fake(script)
        clock = [0.0]
        streams = self.streams_for(alpaca=server, clock=lambda: clock[0], idle=30)
        streams.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: streams.streaming(feeds.ALPACA)))
        clock[0] = 100                                                   # nobody has asked for 100 seconds
        self.assertTrue(wait_for(self, lambda: not streams.workers[feeds.ALPACA].is_alive()))
        self.assertEqual(streams.workers[feeds.ALPACA].status, "idle")
        streams.want("NVDA", KEYS)                                       # looked at again
        self.assertTrue(wait_for(self, lambda: len(server.requests) == 2 and streams.streaming(feeds.ALPACA)))

    def test_a_refused_sign_in_says_why_and_is_not_tried_again_at_once(self):
        server = self.fake(Alpaca(answer='[{"T":"error","code":402,"msg":"auth failed"}]'))
        streams = self.streams_for(alpaca=server, refused_wait=30)
        streams.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: streams.problems()))
        self.assertEqual(streams.problems(), ["Alpaca's stream did not accept the key"])
        time.sleep(0.5)
        self.assertEqual(len(server.requests), 1)                       # no storm of attempts
        self.assertFalse(streams.streaming(feeds.ALPACA))
        server = self.fake(Alpaca(answer='[{"T":"error","code":406,"msg":"connection limit exceeded"}]'))
        other = stream.Streams(urls={feeds.ALPACA: server.url()}, poll=0.05, refused_wait=30)
        self.addCleanup(other.stop)
        other.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: other.problems()))
        self.assertIn("one free connection in use already", other.problems()[0])

    def test_a_handshake_turned_away_for_the_key_is_a_refusal(self):
        server = self.fake(lambda p: None, status="401 Unauthorized")
        streams = self.streams_for(finnhub=server, refused_wait=30)
        streams.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: streams.problems()))
        self.assertEqual(streams.problems(), ["Finnhub's stream did not accept the key"])
        self.assertNotIn("finnhub-token", " ".join(streams.problems()))                              # the token is never in a message

    def test_a_dropped_connection_is_opened_again_and_subscribed_again(self):
        scripts = []

        def script(peer):
            instance = Alpaca([alpaca_trade(131.4 + len(scripts), "2026-10-05T14:59:58Z")], then=(lambda p: p.hang_up()) if not scripts else None)
            scripts.append(instance)
            instance(peer)
        server = self.fake(script)
        streams = self.streams_for(alpaca=server)
        now = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
        streams.want("NVDA", KEYS)
        self.assertTrue(wait_for(self, lambda: len(server.requests) == 2, 6))
        self.assertTrue(wait_for(self, lambda: {"action": "subscribe", "trades": ["NVDA"]} in scripts[1].received))
        self.assertTrue(wait_for(self, lambda: len(streams.recent(feeds.ALPACA, "NVDA", now)) == 2))
        self.assertEqual(streams.problems(), [])                         # a stream that is back says nothing

    def test_it_pings_to_find_a_dead_connection(self):
        real = stream.PING_SECONDS
        stream.PING_SECONDS = 0.2
        try:
            server = self.fake(Alpaca())
            streams = self.streams_for(alpaca=server)
            streams.want("NVDA", KEYS)
            self.assertTrue(wait_for(self, lambda: server.peers and server.peers[0].pings >= 1))
        finally:
            stream.PING_SECONDS = real

    def test_the_trades_kept_are_bounded_in_number_and_in_age(self):
        streams = stream.Streams()
        now = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
        for i in range(stream.TICKS_KEPT + 50):
            streams.add("Alpaca", {"ticker": "NVDA", "price": 100 + i, "at": "2026-10-05T14:59:00.000+00:00", "size": 1})
        got = streams.recent("Alpaca", "NVDA", now)
        self.assertEqual((len(got), got[-1]["price"]), (stream.TICKS_KEPT, 100 + stream.TICKS_KEPT + 49))
        self.assertEqual(streams.recent("Alpaca", "NVDA", now + timedelta(seconds=stream.TICK_AGE_SECONDS + 120)), [])      # older than a quarter of an hour: gone

    def test_no_key_travels_in_a_message_it_should_not(self):
        self.assertNotIn("subscribe", json.dumps(stream.PROTOCOLS and "x"))
        source = read(os.path.join(ROOT, "stream.py"))
        self.assertNotIn("print(", source.split("def main")[0])                                       # nothing prints keys while it runs
        self.assertNotIn(".post(", source)
        for forbidden in ("import t212", "import execute", "orders.json"):
            self.assertNotIn(forbidden, source)
        self.assertEqual(sorted(stream.PROTOCOLS), [feeds.ALPACA, feeds.FINNHUB])


class ChartFromAStreamTests(unittest.TestCase):
    """The whole way: a fake Alpaca stream, the real connection, the real chart."""

    def test_trades_that_come_over_the_wire_are_the_price_and_the_forming_candle(self):
        script = Alpaca([alpaca_trade(131.4, "2026-10-05T14:59:58.100Z", size=40), alpaca_trade(131.45, "2026-10-05T14:59:58.600Z", size=60)])
        server = wsfake.FakeServer(script)
        streams = stream.Streams(urls={feeds.ALPACA: server.url("/v2/iex")}, poll=0.05)
        self.addCleanup(server.stop)
        self.addCleanup(streams.stop)
        charts._cache.clear()
        folder = tempfile.mkdtemp()
        bars = [test_feeds.alpaca_bar("2026-10-05T14:57:00Z", 130.0, 130.6, 129.9, 130.4, 500),
                test_feeds.alpaca_bar("2026-10-05T14:58:00Z", 130.4, 130.8, 130.3, 130.7, 600)]
        market = test_feeds.Market(trade=test_feeds.trade_at("2026-10-05T14:59:00Z", 131.0), bars=bars)
        have = {feeds.ALPACA: ("alpaca-key-id", "alpaca-SECRET")}

        def build():
            charts._cache.clear()
            return charts.chart(folder, "NVDA", "1D", key="k", opener=market, now=test_feeds.NOW, extra=have, live=streams)
        first = build()                                                  # the stream is only being opened: the chart is the polled one
        self.assertEqual((first["streaming"], first["every_seconds"]), ([], charts.FAST_SECONDS))
        self.assertTrue(wait_for(self, lambda: len(streams.recent(feeds.ALPACA, "NVDA", test_feeds.NOW)) == 2))
        got = build()
        self.assertEqual((got["price"]["price"], got["price"]["via"], got["price"]["stream"]), (131.45, "Alpaca", True))
        self.assertEqual((got["streaming"], got["every_seconds"], got["problems"]), (["Alpaca"], charts.STREAM_SECONDS, []))
        self.assertEqual(got["bars"][-1][1:], [131.4, 131.45, 131.4, 131.45, 100])
        self.assertEqual(script.received[0]["key"], "alpaca-key-id")
        self.assertEqual(len(server.requests), 1)                       # one connection for as many charts as are asked


class CheckTests(unittest.TestCase):
    """The doctor's question: can the stream be opened and signed in to?"""

    def setUp(self):
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.stop()

    def serve(self, script, **kw):
        server = wsfake.FakeServer(script, **kw)
        self.servers.append(server)
        return server

    def test_it_says_ok_a_refused_key_a_busy_connection_and_nobody_there(self):
        pair = KEYS[feeds.ALPACA]
        ok = stream.check(feeds.ALPACA, pair, urls={feeds.ALPACA: self.serve(Alpaca()).url()})
        self.assertEqual(ok[:2], (True, "ok"))
        refused = stream.check(feeds.ALPACA, pair, urls={feeds.ALPACA: self.serve(Alpaca(answer='[{"T":"error","code":402,"msg":"x"}]')).url()})
        self.assertEqual(refused[:2], (False, "did not accept the key"))
        busy = stream.check(feeds.ALPACA, pair, urls={feeds.ALPACA: self.serve(Alpaca(answer='[{"T":"error","code":406,"msg":"x"}]')).url()})
        self.assertTrue(busy[0])
        self.assertIn("one free connection is in use now", busy[1])
        turned_away = stream.check(feeds.FINNHUB, "finnhub-token",
                                   urls={feeds.FINNHUB: self.serve(lambda p: None, status="401 Unauthorized").url("/", "token={key}")})
        self.assertEqual(turned_away[:2], (False, "the key was refused (HTTP 401)"))
        finnhub = stream.check(feeds.FINNHUB, "finnhub-token", urls={feeds.FINNHUB: self.serve(Finnhub()).url("/", "token={key}")})
        self.assertEqual(finnhub[:2], (True, "ok"))
        idle = socket.socket()                                   # a port that nothing listens on
        idle.bind(("127.0.0.1", 0))
        address = f"ws://127.0.0.1:{idle.getsockname()[1]}/"
        idle.close()
        nobody = stream.check(feeds.ALPACA, pair, urls={feeds.ALPACA: address})
        self.assertFalse(nobody[0])
        self.assertTrue(nobody[1].startswith("cannot connect"))
        for result in (ok, refused, busy, turned_away, nobody):
            self.assertNotIn("alpaca-SECRET", result[1])
            self.assertNotIn("finnhub-token", result[1])


if __name__ == "__main__":
    unittest.main()
