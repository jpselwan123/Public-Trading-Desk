"""A company's price chart: a line or candles, for any US share or fund, from Tiingo (the key
the desk already uses for its prices), and from every other free feed that has a key in .env.

Daily candles are Tiingo's end-of-day prices, in the shares of today (a split is restated,
a dividend is not: the candle shows the price that was quoted). The day's bars, and the last
five days', are IEX's: Alpaca's, down to the minute, when its key is in .env (200 requests a
minute on the free plan), else Tiingo's. The price above the chart is the newest of what each
feed has (feeds.py: Alpaca's latest trade, Finnhub's quote, Tiingo's latest), each asked as often
as its own allowance lets it; it says which feed gave it, and says so when two disagree. That
price is also folded into the bar it falls in, so the last candle moves between two requests for
bars. All of it is IEX's, one exchange, so it can differ a little from the consolidated price.

Reads only. Tiingo's requests are counted so that this and the company update share its free
allowance (50 an hour, 1,000 a day): a chart may use CHART_PER_HOUR of them, and `prices.update` is
told how many it has used. The other feeds are counted by the minute (ALLOWANCE). A page that has a
live chart open asks again every STREAM_SECONDS while a trade stream is feeding it (stream.py: Alpaca's
and Finnhub's, every trade as it happens), every FAST_SECONDS when a fast feed answered, else every
SLOW_SECONDS, while a session is on. A streamed trade is the price, and joins the candle it falls in
(`fold_ticks`); a feed whose stream is quiet is asked as before.

Usage: python3 charts.py NVDA [1D|5D|1M|6M|1Y|5Y]
"""
import json, os, random, sys, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from env_config import atomic_write_json, moment, NO_TIINGO_KEY
import feeds, news, prices, stream, summarise

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTS_FILE = "charts.json"           # {"asked": [Tiingo requests of the last day], "feeds": {feed: [its requests]}}
IEX_URL = ("https://api.tiingo.com/iex/{ticker}/prices?startDate={start}&resampleFreq={minutes}min"
           "&columns=open,high,low,close,volume")
DAILY_YEARS = 5
# name: (kind, how far back: days of daily bars, or sessions of intraday ones, Tiingo's bar minutes)
RANGES = {"1D": ("intraday", 1, 5), "5D": ("intraday", 5, 15), "1M": ("daily", 31, None),
          "6M": ("daily", 183, None), "1Y": ("daily", 366, None), "5Y": ("daily", 1830, None)}
ALPACA_MINUTES = {"1D": 1, "5D": 5}   # Alpaca's bars are finer, its allowance being larger
DEFAULT_RANGE = "6M"
# The desk's choices. Tiingo's free allowance is 50 requests an hour and 1,000 a day, shared with the
# company update; a chart may use this many of them. Another feed is limited by the minute: Finnhub's
# free plan allows 60 and Alpaca's 200, and the charts take a third and a third of those.
CHART_PER_HOUR, CHART_PER_DAY = 24, 300
ALLOWANCE = {feeds.FINNHUB: (20, 60), feeds.ALPACA: (60, 60), feeds.YAHOO: (12, 60)}   # requests, per this many seconds
FAST_SECONDS, SLOW_SECONDS = 5, 180   # a live chart asks again this often: with a fast feed, and with Tiingo alone
STREAM_SECONDS = 1                    # ... and while a trade stream is feeding it: the trades are already here
# How long an answer is kept. A fast feed's is shorter than the refresh, so every refresh sees a new price;
# Yahoo's is longer, being unofficial and asked gently. test_feeds checks that the refresh and these keep every
# feed within its allowance.
CACHE_SECONDS = {"daily": 6 * 3600, "intraday": 120, "latest": 120, "quote": 3, "alpaca_bars": 4, "yahoo": 10}
LIVE_SESSIONS = ("Pre-market", "Regular session", "After hours")
STALE_MINUTES = 20                    # a session on the clock with nothing newer than this is a holiday or a halt
OPEN, CLOSE = "09:30", prices.CLOSE   # the regular session, New York's clock


class ChartError(Exception):
    pass


_lock = threading.Lock()
_cache = {}                           # (what, ticker, range) → (made, value)


def clean_ticker(text):
    """The ticker as Tiingo's url takes it, or None: letters and digits, with a dot or a dash."""
    ticker = str(text or "").strip().upper()
    return ticker if news.TICKER.match(ticker) else None


def _slug(ticker):
    return ticker.lower().replace(".", "-")


KEPT_MOST = 60                        # bars and prices held in memory; the oldest go first


def _trim():
    """Called with the lock held."""
    for key in sorted(_cache, key=lambda k: _cache[k][0])[:max(0, len(_cache) - KEPT_MOST)]:
        del _cache[key]


def _kept(what, ticker, range_, seconds, make, now):
    """What `make()` gave less than `seconds` ago, else a new one."""
    with _lock:
        got = _cache.get((what, ticker, range_))
    if got and now - got[0] < seconds:
        return got[1]
    value = make()
    with _lock:
        _cache[(what, ticker, range_)] = (now, value)
        _trim()
    return value


# ---- the shared allowance ---------------------------------------------------------------------
def _stored(folder):
    try:
        with open(os.path.join(folder, CHARTS_FILE)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stamps(value, now, seconds):
    cut = (now - timedelta(seconds=seconds)).isoformat()
    return [a for a in value if isinstance(a, str) and a > cut] if isinstance(value, list) else []


def asked(folder, now=None):
    """When each Tiingo request the charts made in the last day was made (ISO times)."""
    now = now or datetime.now(timezone.utc)
    return _stamps(_stored(folder).get("asked"), now, 86400)


def room(folder, now=None):
    now = now or datetime.now(timezone.utc)
    kept = asked(folder, now)
    return sum(1 for a in _stamps(kept, now, 3600)) < CHART_PER_HOUR and len(kept) < CHART_PER_DAY


def feed_room(folder, name, now):
    """Whether the charts may ask another feed again: its allowance by the minute is not spent."""
    limit, seconds = ALLOWANCE[name]
    return len(_stamps(((_stored(folder).get("feeds") or {}).get(name)), now, seconds)) < limit


def _spend(folder, now, feed=None):
    with _lock:
        data = _stored(folder)
        stamp = now.isoformat(timespec="seconds")
        if feed:
            by = data.get("feeds") if isinstance(data.get("feeds"), dict) else {}
            by[feed] = _stamps(by.get(feed), now, 86400) + [stamp]
            data["feeds"] = by
        else:
            data["asked"] = _stamps(data.get("asked"), now, 86400) + [stamp]
        try:
            atomic_write_json(os.path.join(folder, CHARTS_FILE), data)
        except OSError:
            pass                       # a folder that cannot be written still gets its chart


def _ask(folder, url, key, opener, now):
    if not room(folder, now):
        raise ChartError("The charts have used their share of Tiingo's free limit for now; "
                         "they carry on in a few minutes.")
    _spend(folder, now)
    try:
        return prices._tiingo(url, key, opener)
    except prices.PriceError as e:
        raise ChartError(str(e)) from None


# ---- daily candles ----------------------------------------------------------------------------
def parse_daily(rows):
    """[(day, open, high, low, close, volume, split factor)] oldest first, from Tiingo's daily rows."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "")[:10]
        try:
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            v = float(row.get("volume") or 0)
            split = float(row.get("splitFactor") or 1.0)
        except (KeyError, TypeError, ValueError):
            continue
        if day and min(o, h, l, c) > 0 and h >= l:
            out.append((day, o, h, l, c, v, split if split > 0 else 1.0))
    return sorted(out)


def split_adjust(rows):
    """The bars in the shares of the latest day: every bar before a split is divided by its factor
    (its volume multiplied), the split's own day being already after it."""
    out, factor = [], 1.0
    for day, o, h, l, c, v, split in reversed(rows):
        out.append((day, o / factor, h / factor, l / factor, c / factor, v * factor))
        if abs(split - 1) > 1e-12:
            factor *= split
    return out[::-1]


def _bar(b):
    return [b[0]] + [round(x, 4) for x in b[1:5]] + [int(round(b[5]))]


def daily(folder, ticker, key, opener, now):
    """The split-adjusted daily bars of the last DAILY_YEARS, from one request."""
    def make():
        start = (now.date() - timedelta(days=365 * DAILY_YEARS + 7)).isoformat()
        rows = parse_daily(_ask(folder, prices.URL.format(ticker=_slug(ticker), start=start), key, opener, now))
        if not rows:
            raise ChartError(f"Tiingo has no prices for {ticker}: the charts cover US shares and funds.")
        return split_adjust(rows)
    return _kept("daily", ticker, "", CACHE_SECONDS["daily"], make, now.timestamp())


# ---- the day's bars ---------------------------------------------------------------------------
def parse_intraday(rows):
    """[(UTC time, open, high, low, close, volume)] oldest first, regular session only."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        when = moment(row.get("date"))
        try:
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            v = float(row.get("volume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if when and min(o, h, l, c) > 0 and h >= l:
            clock = when.astimezone(prices.MARKET_TZ).strftime("%H:%M")
            if OPEN <= clock < CLOSE:
                out.append((when.astimezone(timezone.utc), o, h, l, c, v))
    return sorted(out)


def last_sessions(bars, n):
    """The bars of the last n New York days that have any."""
    days = sorted({b[0].astimezone(prices.MARKET_TZ).date() for b in bars})[-n:]
    return [b for b in bars if b[0].astimezone(prices.MARKET_TZ).date() in days]


def intraday(folder, ticker, range_, key, opener, now):
    sessions, minutes = RANGES[range_][1], RANGES[range_][2]

    def make():
        start = (now.date() - timedelta(days=sessions + 6)).isoformat()      # weekends and holidays
        try:
            rows = _ask(folder, IEX_URL.format(ticker=_slug(ticker), start=start, minutes=minutes), key, opener, now)
        except ChartError as e:
            if "rejected the key" in str(e):      # the daily bars were given to this key: it is the day's bars it is not given
                raise ChartError("Tiingo did not give the day's bars to this key (its plan may not include them). "
                                 "The longer ranges still work.") from None
            raise
        return last_sessions(parse_intraday(rows), sessions)
    return _kept("intraday", ticker, range_, CACHE_SECONDS["intraday"], make, now.timestamp())


def label(when, with_day):
    local = when.astimezone(prices.MARKET_TZ)
    return (local.strftime("%a ") if with_day else "") + local.strftime("%H:%M")


# ---- the price above the chart ----------------------------------------------------------------
def latest(folder, ticker, key, opener, now):
    """Tiingo's latest price from IEX, {"price", "at", "feed"}, or None."""
    def make():
        rows = _ask(folder, prices.LATEST_URL.format(tickers=_slug(ticker)), key, opener, now)
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            price = row.get("tngoLast") if row.get("tngoLast") is not None else row.get("last")
            when = moment(row.get("timestamp"))
            if isinstance(price, (int, float)) and price > 0 and when:
                return {"price": float(price), "at": when.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        "feed": feeds.TIINGO}
        return None
    return _kept("latest", ticker, "", CACHE_SECONDS["latest"], make, now.timestamp())


def fast_quote(folder, name, ticker, have, opener, now):
    """One fast feed's quote, kept for a few seconds; None when its allowance by the minute is spent or it
    knows nothing of the ticker. A FeedError says why it failed."""
    def make():
        if not feed_room(folder, name, now):
            return None
        _spend(folder, now, name)
        if name == feeds.FINNHUB:
            return feeds.finnhub_quote(ticker, have[name], opener)
        return feeds.alpaca_quote(ticker, have[name], opener)
    return _kept("quote-" + name, ticker, "", CACHE_SECONDS["quote"], make, now.timestamp())


def alpaca_intraday(folder, ticker, range_, pair, opener, now):
    """The day's (or five days') bars from Alpaca, regular session only, or [] when its allowance is spent."""
    sessions, minutes = RANGES[range_][1], ALPACA_MINUTES[range_]

    def make():
        if not feed_room(folder, feeds.ALPACA, now):
            return []
        _spend(folder, now, feeds.ALPACA)
        start = (now.date() - timedelta(days=sessions + 6)).isoformat()
        return last_sessions(parse_intraday(feeds.alpaca_bars(ticker, minutes, start, pair, opener)), sessions)
    return _kept("alpaca_bars", ticker, range_, CACHE_SECONDS["alpaca_bars"], make, now.timestamp())


def yahoo_fetch(folder, ticker, range_, opener, now):
    """Yahoo's chart: {"quote", "rows"} for the day (or, for the five-day range, five days), kept for
    CACHE_SECONDS["yahoo"]; None when its allowance is spent. Asked for every range, its quote is a price."""
    days, minutes = (5, 5) if range_ == "5D" else (1, 1)

    def make():
        if not feed_room(folder, feeds.YAHOO, now):
            return None
        _spend(folder, now, feeds.YAHOO)
        return feeds.yahoo_chart(ticker, minutes, days, opener)
    return _kept("yahoo", ticker, str(days), CACHE_SECONDS["yahoo"], make, now.timestamp())


def fold(bars, quote, minutes):
    """The bars with a fresher price put in: the price joins the bar its moment falls in, or opens a
    new one if the moment is past the last (from the last close, its volume not yet known). Only a
    regular-session price of the last bar's own day goes in: a pre-market price is not a bar."""
    when = moment(quote.get("at")) if quote else None
    if not bars or not when:
        return bars
    last = bars[-1]
    there = when.astimezone(prices.MARKET_TZ)
    if (there.date() != last[0].astimezone(prices.MARKET_TZ).date() or not OPEN <= there.strftime("%H:%M") < CLOSE
            or when < last[0]):
        return bars
    price, width = quote["price"], timedelta(minutes=minutes)
    if when < last[0] + width:
        return bars[:-1] + [(last[0], last[1], max(last[2], price), min(last[3], price), price, last[5])]
    start = last[0] + width * int((when - last[0]) / width)
    return bars + [(start, last[4], max(last[4], price), min(last[4], price), price, 0.0)]


def fold_ticks(bars, ticks, minutes, count_volume):
    """The bars with every streamed trade put in, oldest first. A trade inside the last bar moves its
    close, high and low (its volume is the feed's own, which already holds it); one past the last bar
    makes the bars the stream began, each opening at its first trade. `count_volume` is true only when the
    trades are of the same exchange as the bars (IEX's), so their sizes add up to the bar's volume. An odd
    lot (`odd`) adds its volume and takes no price, as in Alpaca's own bars, and opens no bar. Only the
    regular session of the last bar's own day is folded."""
    if not bars or not ticks:
        return bars
    bars, width = list(bars), timedelta(minutes=minutes)
    settled = bars[-1][0] + width                  # from here on no bar is the feed's: the stream's are
    day = bars[-1][0].astimezone(prices.MARKET_TZ).date()
    for t in sorted(ticks, key=lambda t: t["at"]):
        when = moment(t["at"])
        there = when.astimezone(prices.MARKET_TZ) if when else None
        last = bars[-1]
        if (not there or there.date() != day or not OPEN <= there.strftime("%H:%M") < CLOSE or when < last[0]):
            continue
        price, size = t["price"], (t.get("size") or 0) if count_volume else 0
        if when < last[0] + width:
            own = last[0] >= settled
            if t.get("odd"):
                bars[-1] = last[:5] + (last[5] + (size if own else 0),)
            else:
                bars[-1] = (last[0], last[1], max(last[2], price), min(last[3], price), price, last[5] + (size if own else 0))
        elif t.get("odd"):
            continue
        else:
            start = last[0] + width * int((when - last[0]) / width)
            bars.append((start, price, price, price, price, float(size)))
    return bars


def header(bars, quote, intraday_bars, now, bars_feed=None):
    """The price shown above the chart, and whether it is live. A price newer than the last daily
    close (a later day's, or the same day's after 16:00) is shown, measured from that close; else the
    close is, measured from the one before. Live: a session is on the clock and the price is fresh.
    `via` names the feed it came from (`bars_feed` for a price taken from the bars)."""
    last_day, last_close = bars[-1][0], bars[-1][4]
    prev = bars[-2][4] if len(bars) > 1 else None
    fresh = None                              # (when, price, feed) of the newest price there is
    if intraday_bars:
        fresh = (intraday_bars[-1][0], intraday_bars[-1][4], bars_feed)
    when = moment(quote["at"]) if quote else None
    if when and (fresh is None or when >= fresh[0]):
        fresh = (when, quote["price"], quote.get("feed"))
    price, at, base, via = last_close, None, prev, None
    if fresh:
        local = fresh[0].astimezone(prices.MARKET_TZ)
        if local.date().isoformat() > last_day or (local.date().isoformat() == last_day
                                                    and local.strftime("%H:%M") >= CLOSE):
            price, at, base, via = fresh[1], fresh[0].astimezone(timezone.utc), last_close, fresh[2]
    session = prices.session(at) if at else "Closed"
    live = bool(at) and (now - at) < timedelta(minutes=STALE_MINUTES) and session in LIVE_SESSIONS
    return {"price": round(price, 4), "close_day": last_day, "session": session,
            "at": at.isoformat(timespec="seconds") if at else None,
            "at_label": at.astimezone(prices.MARKET_TZ).strftime("%H:%M:%S") + " New York" if at else None,
            "via": via,
            "change": None if not base else price / base - 1,
            "previous_close": None if not base else round(base, 4)}, live


# ---- the chart --------------------------------------------------------------------------------
def build(range_, bars, intraday_bars, quote, now, bars_feed=None, minutes=None):
    kind = RANGES[range_][0]
    head, live = header(bars, quote, intraday_bars, now, bars_feed)
    if kind == "daily":
        cut = (date.fromisoformat(bars[-1][0]) - timedelta(days=RANGES[range_][1])).isoformat()
        shown = [b for b in bars if b[0] >= cut]
        out = {"bars": [_bar(b) for b in shown], "labels": None, "bar_minutes": None}
    else:
        many = RANGES[range_][1] > 1
        out = {"bars": [[int(b[0].timestamp())] + [round(x, 4) for x in b[1:5]] + [int(round(b[5]))]
                        for b in intraday_bars],
               "labels": [label(b[0], many) for b in intraday_bars], "bar_minutes": minutes}
    out.update({"range": range_, "kind": kind, "price": head, "live": live, "every_seconds": SLOW_SECONDS,
                "split_adjusted": True, "demo": False, "currency": "USD", "feeds": [], "differ": False,
                "problems": [], "consolidated": bars_feed == feeds.YAHOO})
    return out


def _run(tasks):
    """The tasks side by side: {label: (value, None)} or {label: (None, why)} for a feed that failed."""
    done = {}
    if not tasks:
        return done
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        waiting = {label: pool.submit(task) for label, task in tasks.items()}
        for label, future in waiting.items():
            try:
                done[label] = (future.result(), None)
            except (feeds.FeedError, ChartError) as e:
                done[label] = (None, str(e))
    return done


def streamed(live, ticker, have, now):
    """What the trade streams hold for this ticker: ({feed: its newest trade as a quote}, {feed: its
    trades}, [the problems they report]). `live` is a stream.Streams, or None for no streams."""
    if live is None:
        return {}, {}, []
    live.want(ticker, have)
    quotes, trades = {}, {}
    for name in stream.PROTOCOLS:
        if name in have and live.streaming(name):
            last = live.last(name, ticker, now)
            if last:
                quotes[name], trades[name] = last, live.recent(name, ticker, now)
    return quotes, trades, live.problems()


def chart(folder, ticker, range_, key=None, opener=None, now=None, extra=None, live=None):
    """The chart of one ticker over one range: {"bars", "labels", "price", "live", …}. `extra` is
    feeds.keys(): the other feeds there are keys for, asked side by side with Tiingo; `live` the trade
    streams (stream.py), which give the price and the forming candle between requests. A ChartError says
    in words why not; a feed that fails is named in the chart's `problems` and the others carry on."""
    ticker, range_ = clean_ticker(ticker), range_ if range_ in RANGES else DEFAULT_RANGE
    if not ticker:
        raise ChartError("Type a ticker, like NVDA.")
    now = now or datetime.now(timezone.utc)
    key = key or _key()
    have = extra or {}
    bars = daily(folder, ticker, key, opener, now)
    intraday_range = RANGES[range_][0] == "intraday"
    pushed, ticks, stream_problems = streamed(live, ticker, have, now)
    # a feed whose stream gave a trade a moment ago needs no request for its price
    quiet = [name for name in feeds.QUOTES if name in have
             and not (name in pushed and (now - moment(pushed[name]["at"])).total_seconds() <= stream.FRESH_SECONDS)]
    tasks = {"quote-" + name: (lambda name=name: fast_quote(folder, name, ticker, have, opener, now)) for name in quiet}
    if intraday_range and feeds.ALPACA in have:
        tasks["bars-" + feeds.ALPACA] = lambda: alpaca_intraday(folder, ticker, range_, have[feeds.ALPACA], opener, now)
    if feeds.YAHOO in have:
        tasks["yahoo"] = lambda: yahoo_fetch(folder, ticker, range_, opener, now)
    results, problems = _run(tasks), []
    quotes = []
    for label, (value, why) in results.items():
        problems += [why] if why else []
        if label.startswith("quote-") and value:
            quotes.append(value)
    yahoo = results.get("yahoo", (None, None))[0] or {}
    if yahoo.get("quote"):
        quotes.append(yahoo["quote"])
    quotes += list(pushed.values())
    got, bars_feed, minutes = [], None, RANGES[range_][2]
    if intraday_range:
        sessions = RANGES[range_][1]
        alpaca = results.get("bars-" + feeds.ALPACA, (None, None))[0]
        yahoo_bars = last_sessions(parse_intraday(yahoo.get("rows")), sessions) if yahoo else []
        if alpaca:
            got, bars_feed, minutes = alpaca, feeds.ALPACA, ALPACA_MINUTES[range_]
        elif yahoo_bars:
            got, bars_feed, minutes = yahoo_bars, feeds.YAHOO, ALPACA_MINUTES[range_]
        else:
            got, bars_feed = intraday(folder, ticker, range_, key, opener, now), feeds.TIINGO
            if not got:
                raise ChartError(f"Tiingo has no intraday prices for {ticker} yet.")
    fast = bool(quotes) or bars_feed in (feeds.ALPACA, feeds.YAHOO)
    pushing = bool(pushed)
    if not quotes and not intraday_range:      # a daily range's price, when no fast feed gave one: Tiingo's latest
        try:
            tiingo = latest(folder, ticker, key, opener, now)
            quotes += [tiingo] if tiingo else []
        except ChartError as e:
            problems.append(str(e))
    best, differ = feeds.combine(quotes, now)
    if intraday_range:
        # Alpaca's trades are IEX's, as its bars and Tiingo's are; Finnhub's are the market's, so they give a price only
        tick_feed = feeds.ALPACA if ticks.get(feeds.ALPACA) else feeds.FINNHUB if ticks.get(feeds.FINNHUB) else None
        if tick_feed:
            got = fold_ticks(got, ticks[tick_feed], minutes,
                             tick_feed == feeds.ALPACA and bars_feed in (feeds.ALPACA, feeds.TIINGO))
        got = fold(got, best, minutes)
    out = build(range_, bars, got, best, now, bars_feed, minutes)
    out["price"]["stream"] = bool(best and best.get("stream"))
    out.update({"ticker": ticker,
                "every_seconds": STREAM_SECONDS if pushing else FAST_SECONDS if fast else SLOW_SECONDS,
                "differ": differ, "streaming": sorted(pushed, key=feeds.ORDER.index),
                "problems": problems + [p for p in stream_problems if p not in problems],
                "feeds": [{"name": q["feed"], "price": round(q["price"], 4), "stream": bool(q.get("stream")),
                           "age": max(0, int((now - moment(q["at"])).total_seconds()))}
                          for q in sorted(quotes, key=lambda q: feeds.ORDER.index(q["feed"]))]})
    with _lock:
        _cache[("built", ticker, range_)] = (now.timestamp(), out)
        _trim()
    return out


def cached(ticker, range_, now=None, seconds=900):
    """The chart of this ticker and range as it was last built, if that was less than `seconds`
    ago: what the owner is looking at, for the chat. Asks no one."""
    with _lock:
        got = _cache.get(("built", clean_ticker(ticker), range_))
    return got[1] if got and (now or datetime.now(timezone.utc)).timestamp() - got[0] < seconds else None


def summary(chart):
    """What a chart shows, in words the model repeats as written (the figures, rounded and dated as
    the page shows them)."""
    bars, labels = chart["bars"], chart.get("labels")
    first, last = bars[0], bars[-1]
    high = max(range(len(bars)), key=lambda i: bars[i][2])
    low = min(range(len(bars)), key=lambda i: bars[i][3])
    when = (lambda i: labels[i]) if labels else (lambda i: summarise._day(bars[i][0]))
    money = lambda v: f"${v:,.2f}"
    return {"ticker": chart.get("ticker"), "range": chart["range"],
            "bars": f"{len(bars)} " + ("daily" if chart["kind"] == "daily" else f"{chart.get('bar_minutes')}-minute") + " bars",
            "from": when(0), "to": when(len(bars) - 1),
            "first_close": money(first[4]), "last_close": money(last[4]),
            "change_over_the_range": f"{(last[4] / first[4] - 1) * 100:+.1f}%",
            "highest_price": f"{money(bars[high][2])} ({when(high)})",
            "lowest_price": f"{money(bars[low][3])} ({when(low)})",
            "average_volume_per_bar": f"{int(sum(b[5] for b in bars) / len(bars)):,} shares",
            "last_bar_volume": f"{last[5]:,} shares",
            "prices_are": "split-adjusted; IEX's regular-session bars" if chart["kind"] == "intraday"
                          else "split-adjusted daily prices as quoted"}



def _key():
    try:
        return prices.api_key()
    except prices.PriceError:
        raise ChartError(NO_TIINGO_KEY) from None


# ---- the demo ---------------------------------------------------------------------------------
def demo_chart(store, ticker, range_, today=None):
    """The same chart from the demo's own closes: bars made up around them, the same each time.
    The demo reaches no one."""
    ticker, range_ = clean_ticker(ticker), range_ if range_ in RANGES else DEFAULT_RANGE
    if not ticker:
        raise ChartError("Type a ticker, like NVDA.")
    closes = prices.series(store, ticker, "c")
    days = sorted(closes)
    if len(days) < 25:
        raise ChartError(f"The demo has no prices for {ticker}: try one of the companies above.")
    bars, previous = [], closes[days[0]]
    for day in days:
        rnd = random.Random(f"{ticker}{day}")
        c = closes[day]
        o = previous
        high = max(o, c) * (1 + rnd.uniform(0.001, 0.012))
        low = min(o, c) * (1 - rnd.uniform(0.001, 0.012))
        bars.append((day, o, high, low, c, rnd.randint(2_000_000, 9_000_000)))
        previous = c
    now = datetime(int(days[-1][:4]), int(days[-1][5:7]), int(days[-1][8:10]), 21, 0, tzinfo=timezone.utc)
    sessions = RANGES[range_][1] if RANGES[range_][0] == "intraday" else 0
    fake = []
    if sessions:
        minutes = RANGES[range_][2]
        for d in days[-sessions:]:
            i = days.index(d)
            start, end = closes[days[i - 1]], closes[d]
            rnd = random.Random(f"{ticker}{d}intraday")
            count, level = (390 // minutes), start
            first = datetime(int(d[:4]), int(d[5:7]), int(d[8:10]), 9, 30, tzinfo=prices.MARKET_TZ).astimezone(timezone.utc)
            walk = [rnd.gauss(0, 1) for _ in range(count)]
            drift = [sum(walk[:k + 1]) for k in range(count)]
            for k in range(count):
                target = start + (end - start) * (k + 1) / count
                noise = (drift[k] - drift[-1] * (k + 1) / count) * start * 0.0006     # a bridge from open to close
                close = max(0.01, target + noise)
                high, low = max(level, close) * (1 + rnd.uniform(0, 0.0008)), min(level, close) * (1 - rnd.uniform(0, 0.0008))
                fake.append((first + timedelta(minutes=minutes * k), level, high, low, close, rnd.randint(20_000, 200_000)))
                level = close
    out = build(range_, bars, fake, None, now, None, RANGES[range_][2])
    out.update({"ticker": ticker, "demo": True, "live": False, "every_seconds": None})
    return out


def main(argv):
    ticker = argv[1] if len(argv) > 1 else "SPY"
    range_ = (argv[2] if len(argv) > 2 else DEFAULT_RANGE).upper()
    try:
        out = chart(HERE, ticker, range_)
    except ChartError as e:
        print(e)
        return 1
    print(json.dumps({k: v for k, v in out.items() if k not in ("bars", "labels")}, indent=1))
    print(len(out["bars"]), "bars; the last:", out["bars"][-1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
