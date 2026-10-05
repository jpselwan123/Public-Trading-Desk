"""Live trades, one at a time, for the chart (the owner, 5 Oct 2026: "tick by tick I need").

Alpaca's and Finnhub's free plans both stream every trade over a WebSocket (Alpaca: IEX's, one connection
and 30 symbols; Finnhub: 50 symbols). This keeps one connection to each feed that has a key, subscribed to
the few tickers a chart has been asking about, and remembers the trades as they come: the latest, and
the last TICKS_KEPT of them (charts.py puts them into the forming candle). Nothing is stored on disk.

A stream asks for nothing it was not asked: a ticker nobody has asked about for IDLE_SECONDS is dropped,
and a feed with no ticker left closes its connection, which frees Alpaca's one free connection for any
other program that uses the same key. A stream that breaks is opened again after a pause that grows
(BACKOFF); one that is refused (the key, or the one connection being in use elsewhere) waits REFUSED_WAIT
and says why, in words. The chart polls meanwhile, so a stream that never works costs it nothing.

Read only: this subscribes to trades and sends nothing else. A key is sent to its own feed alone, and
no message here carries it.

Usage: python3 stream.py NVDA [seconds]    prints each trade for a few seconds, to see the streams work
"""
import json, os, sys, threading, time
from collections import deque
from datetime import datetime, timedelta, timezone
from env_config import load_env, moment
import feeds, wsclient

HERE = os.path.dirname(os.path.abspath(__file__))
URLS = {feeds.ALPACA: "wss://stream.data.alpaca.markets/v2/iex", feeds.FINNHUB: "wss://ws.finnhub.io?token={key}"}
IDLE_SECONDS = 90          # a feed nobody has asked about for this long closes, and a ticker with it
WATCH_MOST = 5             # tickers streamed at once (Alpaca's free plan allows 30, Finnhub's 50)
TICKS_KEPT = 1500          # the desk's choice: minutes of a busy share, a day of a quiet one
TICK_AGE_SECONDS = 900     # and none older than a quarter of an hour
FRESH_SECONDS = 10         # a streamed trade this young is the price
BACKOFF = (2, 4, 8, 16, 32, 60)
REFUSED_WAIT = 300
PING_SECONDS = 25
POLL = 0.5                 # how long a stream waits for a message before it looks at what is wanted


class StreamRefused(Exception):
    pass


# ---- the two protocols --------------------------------------------------------------------------
def alpaca_open(conn, pair):
    """Alpaca's greeting and sign-in: raises StreamRefused if it does not accept."""
    conn.send(json.dumps({"action": "auth", "key": pair[0], "secret": pair[1]}))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        text = conn.recv(1.0)
        if text is None:
            continue
        _, error, signed_in = alpaca_parse(text)
        if error:
            raise StreamRefused(error)
        if signed_in:
            return
    raise StreamRefused("did not answer the sign-in")


def alpaca_parse(text):
    """(trades, error, signed_in) from one Alpaca message (a list of objects)."""
    trades, error, signed_in = [], None, False
    try:
        items = json.loads(text)
    except ValueError:
        return trades, error, signed_in
    for item in items if isinstance(items, list) else [items]:
        if not isinstance(item, dict):
            continue
        kind = item.get("T")
        if kind == "t":
            when, price = moment(item.get("t")), item.get("p")
            if when and isinstance(price, (int, float)) and price > 0:
                trade = {"ticker": str(item.get("S") or "").upper(), "price": float(price),
                         "at": when.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
                         "size": int(item.get("s") or 0)}
                if "I" in (item.get("c") or []):
                    trade["odd"] = True            # an odd lot: Alpaca's own bars count its volume and take no price from it
                trades.append(trade)
        elif kind == "success" and item.get("msg") == "authenticated":
            signed_in = True
        elif kind == "error":
            code = item.get("code")
            error = ("did not accept the key" if code in (401, 402, 403) else
                     "has its one free connection in use already (another program with the same key?)" if code == 406 else
                     "cannot stream that many tickers" if code == 405 else f"gave error {code}")
    return trades, error, signed_in


def alpaca_sync(conn, add, drop):
    if add:
        conn.send(json.dumps({"action": "subscribe", "trades": sorted(add)}))
    if drop:
        conn.send(json.dumps({"action": "unsubscribe", "trades": sorted(drop)}))


def finnhub_open(conn, key):
    """Finnhub signs in with the token in its address: nothing to say."""


def finnhub_parse(text):
    trades, error = [], None
    try:
        item = json.loads(text)
    except ValueError:
        return trades, error, False
    if not isinstance(item, dict):
        return trades, error, False
    if item.get("type") == "trade":
        for t in item.get("data") or []:
            if not isinstance(t, dict):
                continue
            price, stamp = t.get("p"), t.get("t")
            if isinstance(price, (int, float)) and price > 0 and isinstance(stamp, (int, float)) and stamp > 0:
                trades.append({"ticker": str(t.get("s") or "").upper(), "price": float(price),
                               "at": (datetime.fromtimestamp(int(stamp) // 1000, timezone.utc)
                                      + timedelta(milliseconds=int(stamp) % 1000)).isoformat(timespec="milliseconds"),
                               "size": int(t.get("v") or 0)})
    elif item.get("type") == "error":
        error = "gave an error (" + str(item.get("msg") or "no reason")[:60] + ")"
    return trades, error, False


def finnhub_sync(conn, add, drop):
    for ticker in sorted(add):
        conn.send(json.dumps({"type": "subscribe", "symbol": ticker}))
    for ticker in sorted(drop):
        conn.send(json.dumps({"type": "unsubscribe", "symbol": ticker}))


PROTOCOLS = {feeds.ALPACA: (alpaca_open, alpaca_parse, alpaca_sync), feeds.FINNHUB: (finnhub_open, finnhub_parse, finnhub_sync)}


# ---- one feed's connection ----------------------------------------------------------------------
class Worker(threading.Thread):
    def __init__(self, owner, feed, key):
        super().__init__(daemon=True, name=f"stream-{feed}")
        self.owner, self.feed, self.key = owner, feed, key
        self.wanted = {}                   # ticker → when it was last asked about (the owner's clock)
        self.status = "starting"
        self.problem = None                # why it is not streaming, in words, or None
        self.failures = 0

    def note(self, ticker):
        with self.owner.lock:
            self.wanted[ticker] = self.owner.clock()
            for old in sorted(self.wanted, key=self.wanted.get)[:max(0, len(self.wanted) - WATCH_MOST)]:
                del self.wanted[old]

    def current(self):
        cut = self.owner.clock() - self.owner.idle
        with self.owner.lock:
            return {t for t, at in self.wanted.items() if at >= cut}

    def nap(self, seconds):
        """Wait, but wake for a stop or when nothing is asked for any more; True if the stream should end."""
        end = self.owner.clock() + seconds
        while self.owner.clock() < end:
            if self.owner.stopping.wait(0.1) or not self.current():
                return True
        return False

    def pause(self, failures):
        return self.owner.backoff[min(failures - 1, len(self.owner.backoff) - 1)]

    def run(self):
        try:
            while not self.owner.stopping.is_set() and self.current():
                self.status = "connecting"
                try:
                    conn = self.owner.connect(self.owner.urls[self.feed].format(key=self.key if isinstance(self.key, str) else ""))
                except wsclient.WebSocketError as e:
                    self.failures += 1
                    wait = self.owner.refused_wait if self.refused(e) else self.pause(self.failures)
                    if self.nap(wait):
                        return
                    continue
                try:
                    self.stream(conn)
                    return                                     # nothing is asked for any more
                except StreamRefused as e:
                    self.problem, self.status = f"{self.feed}'s stream {e}", "refused"
                    wait = self.owner.refused_wait
                except (wsclient.WebSocketError, OSError, ValueError) as e:
                    self.failures += 1
                    self.status = "broken"
                    self.problem = f"{self.feed}'s stream broke ({str(e)[:60]}); opening it again"
                    wait = self.pause(self.failures)
                except Exception as e:                       # a background thread must not die unseen
                    self.failures += 1
                    self.status = "broken"
                    self.problem = f"{self.feed}'s stream failed ({type(e).__name__}); opening it again"
                    wait = self.pause(self.failures)
                finally:
                    conn.close()
                if self.nap(wait):
                    return
        finally:
            if self.status != "refused":
                self.status = "idle"

    def refused(self, error):
        """A handshake turned away for the key is a refusal, not a break: True if it was."""
        if isinstance(error, wsclient.WebSocketRefused) and error.code in (401, 403):
            self.problem, self.status = f"{self.feed}'s stream did not accept the key", "refused"
            return True
        self.problem, self.status = f"{self.feed}'s stream can't be reached ({str(error)[:60]}); opening it again", "broken"
        return False

    def stream(self, conn):
        opener, parse, sync = PROTOCOLS[self.feed]
        opener(conn, self.key)
        self.status, self.problem, self.failures = "streaming", None, 0
        subscribed, last_ping = set(), self.owner.clock()
        while not self.owner.stopping.is_set():
            wanted = self.current()
            if not wanted:
                return
            sync(conn, wanted - subscribed, subscribed - wanted)
            subscribed = wanted
            text = conn.recv(self.owner.poll)
            if text:
                trades, error, _ = parse(text)
                if error:
                    raise StreamRefused(error)
                for trade in trades:
                    self.owner.add(self.feed, trade)
            if self.owner.clock() - last_ping > PING_SECONDS:
                conn.ping()
                last_ping = self.owner.clock()


# ---- the streams ---------------------------------------------------------------------------------
class Streams:
    def __init__(self, connect=wsclient.connect, urls=None, clock=time.monotonic, wall=None, idle=IDLE_SECONDS,
                 backoff=BACKOFF, refused_wait=REFUSED_WAIT, poll=POLL):
        self.connect, self.urls, self.clock, self.idle = connect, dict(urls or URLS), clock, idle
        self.backoff, self.refused_wait, self.poll = backoff, refused_wait, poll
        self.workers, self.lock, self.stopping = {}, threading.RLock(), threading.Event()
        self.ticks = {}                    # (feed, ticker) → deque of trades

    def want(self, ticker, have):
        """Say the chart of `ticker` is being looked at: start the feeds that have a key, or keep them going."""
        ticker = feeds.symbol(ticker)
        for feed in PROTOCOLS:
            if feed not in have or feed not in self.urls or self.stopping.is_set():
                continue
            with self.lock:
                worker = self.workers.get(feed)
                if worker is None or not worker.is_alive():
                    worker = Worker(self, feed, have[feed])
                    worker.note(ticker)
                    self.workers[feed] = worker
                    worker.start()
                else:
                    worker.note(ticker)

    def add(self, feed, trade):
        with self.lock:
            queue = self.ticks.setdefault((feed, trade["ticker"]), deque(maxlen=TICKS_KEPT))
            queue.append(trade)

    def recent(self, feed, ticker, now=None):
        """The trades of the last TICK_AGE_SECONDS, oldest first."""
        now = now or datetime.now(timezone.utc)
        with self.lock:
            queue = list(self.ticks.get((feed, feeds.symbol(ticker))) or [])
        return [t for t in queue if (now - moment(t["at"])).total_seconds() <= TICK_AGE_SECONDS]

    def last(self, feed, ticker, now=None):
        """The latest trade that sets a price, as a quote ({"price", "at", "feed", "stream"}), or None."""
        trades = [t for t in self.recent(feed, ticker, now) if not t.get("odd")]
        return {"price": trades[-1]["price"], "at": trades[-1]["at"], "feed": feed, "stream": True} if trades else None

    def streaming(self, feed):
        worker = self.workers.get(feed)
        return bool(worker and worker.is_alive() and worker.status == "streaming")

    def problems(self):
        return [w.problem for w in list(self.workers.values()) if w.problem]

    def stop(self):
        self.stopping.set()
        for worker in list(self.workers.values()):
            worker.join(timeout=3)


STREAMS = Streams()


def check(feed, key, connect=wsclient.connect, urls=None):
    """Whether a stream can be opened and signed in to, for doctor.py: (ok, in words, seconds). It subscribes
    to nothing; Alpaca's one free connection, if the desk's own server holds it, says so."""
    started = time.monotonic()
    took = lambda: time.monotonic() - started
    try:
        conn = connect((urls or URLS)[feed].format(key=key if isinstance(key, str) else ""))
    except wsclient.WebSocketRefused as e:
        return False, ("the key was refused" if e.code in (401, 403) else "refused") + f" (HTTP {e.code})", took()
    except wsclient.WebSocketError as e:
        return False, f"cannot connect ({str(e)[:100]})", took()
    try:
        PROTOCOLS[feed][0](conn, key)
        return True, "ok", took()
    except StreamRefused as e:
        if "connection in use" in str(e):
            return True, "the key works; its one free connection is in use now (by the desk's own server, or another program)", took()
        return False, str(e), took()
    except wsclient.WebSocketError as e:
        return False, f"the connection broke ({str(e)[:100]})", took()
    finally:
        conn.close()


def main(argv):
    ticker = (argv[1] if len(argv) > 1 else "SPY").upper()
    seconds = float(argv[2]) if len(argv) > 2 else 15
    have = {k: v for k, v in feeds.keys().items() if k in PROTOCOLS}
    if not have:
        print("No Alpaca key pair or Finnhub key in .env: nothing to stream.")
        return 1
    streams = Streams()
    streams.want(ticker, have)
    seen, end = {}, time.monotonic() + seconds
    print(f"Streaming {ticker} from {', '.join(have)} for {seconds:.0f} seconds (trades only come while the market is open)...")
    while time.monotonic() < end:
        time.sleep(0.25)
        streams.want(ticker, have)
        for feed in have:
            for trade in streams.recent(feed, ticker):
                if trade["at"] > seen.get(feed, ""):
                    seen[feed] = trade["at"]
                    print(f"  {feed:8} {trade['at'][11:23]}  {trade['price']:>10.4f}  x {trade['size']}")
    for feed in have:
        worker = streams.workers.get(feed)
        print(f"{feed}: {worker.status if worker else 'not started'}" + (f" ({worker.problem})" if worker and worker.problem else ""))
    streams.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
