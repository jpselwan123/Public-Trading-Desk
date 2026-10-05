"""A company's price chart: a line or candles, for any US share or fund, from Tiingo (the key
the desk already uses for its prices).

Daily candles are Tiingo's end-of-day prices, in the shares of today (a split is restated,
a dividend is not: the candle shows the price that was quoted). The day's bars, and the last
five days', are IEX's through Tiingo, regular session only, in New York's clock. The price
above the chart is IEX's latest, pre- and post-market included, so it can differ a little
from the consolidated price: IEX is one exchange.

Reads only. Nothing is stored but a count of the requests made, so that this and the company
update share Tiingo's free allowance (50 requests an hour, 1,000 a day): a chart may use
CHART_PER_HOUR of them, and `prices.update` is told how many it has used. A page that has
a live chart open asks again every EVERY_MINUTES, while a session is on.

Usage: python3 charts.py NVDA [1D|5D|1M|6M|1Y|5Y]
"""
import json, os, random, sys, threading
from datetime import date, datetime, timedelta, timezone
from env_config import atomic_write_json, moment, NO_TIINGO_KEY
import news, prices, summarise

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTS_FILE = "charts.json"           # {"asked": [when each request of the last day was made]}
IEX_URL = ("https://api.tiingo.com/iex/{ticker}/prices?startDate={start}&resampleFreq={minutes}min"
           "&columns=open,high,low,close,volume")
DAILY_YEARS = 5
# name: (kind, how far back: days of daily bars, or sessions of intraday ones, bar minutes)
RANGES = {"1D": ("intraday", 1, 5), "5D": ("intraday", 5, 15), "1M": ("daily", 31, None),
          "6M": ("daily", 183, None), "1Y": ("daily", 366, None), "5Y": ("daily", 1830, None)}
DEFAULT_RANGE = "6M"
# The desk's choice, within Tiingo's free allowance of 50 an hour and 1,000 a day: a chart may use
# this many of them, and the company update leaves them to it. An open live chart asks every
# EVERY_MINUTES (20 an hour at 3), a view of a new company two.
CHART_PER_HOUR, CHART_PER_DAY = 24, 300
EVERY_MINUTES = 3
CACHE_SECONDS = {"daily": 6 * 3600, "intraday": 120, "latest": 60}
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
def asked(folder, now=None):
    """When each request this chart made in the last day was made (ISO times)."""
    now = now or datetime.now(timezone.utc)
    try:
        with open(os.path.join(folder, CHARTS_FILE)) as f:
            kept = json.load(f).get("asked")
    except (OSError, ValueError, AttributeError):
        kept = None
    day_ago = (now - timedelta(days=1)).isoformat()
    return [a for a in kept or [] if isinstance(a, str) and a > day_ago]


def room(folder, now=None):
    now = now or datetime.now(timezone.utc)
    kept, hour_ago = asked(folder, now), (now - timedelta(hours=1)).isoformat()
    return sum(1 for a in kept if a > hour_ago) < CHART_PER_HOUR and len(kept) < CHART_PER_DAY


def _spend(folder, now):
    with _lock:
        kept = asked(folder, now) + [now.isoformat(timespec="seconds")]
        try:
            atomic_write_json(os.path.join(folder, CHARTS_FILE), {"asked": kept})
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
    def make():
        rows = _ask(folder, prices.LATEST_URL.format(tickers=_slug(ticker)), key, opener, now)
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            price = row.get("tngoLast") if row.get("tngoLast") is not None else row.get("last")
            when = moment(row.get("timestamp"))
            if isinstance(price, (int, float)) and price > 0 and when:
                return {"price": float(price), "at": when.astimezone(timezone.utc).isoformat(timespec="seconds")}
        return None
    return _kept("latest", ticker, "", CACHE_SECONDS["latest"], make, now.timestamp())


def header(bars, quote, intraday_bars, now):
    """The price shown above the chart, and whether it is live. A price newer than the last daily
    close (a later day's, or the same day's after 16:00) is shown, measured from that close; else the
    close is, measured from the one before. Live: a session is on the clock and the price is fresh."""
    last_day, last_close = bars[-1][0], bars[-1][4]
    prev = bars[-2][4] if len(bars) > 1 else None
    fresh = None                              # (when, price) of the newest price there is
    if intraday_bars:
        fresh = (intraday_bars[-1][0], intraday_bars[-1][4])
    when = moment(quote["at"]) if quote else None
    if when and (fresh is None or when >= fresh[0]):
        fresh = (when, quote["price"])
    price, at, base = last_close, None, prev
    if fresh:
        local = fresh[0].astimezone(prices.MARKET_TZ)
        if local.date().isoformat() > last_day or (local.date().isoformat() == last_day
                                                    and local.strftime("%H:%M") >= CLOSE):
            price, at, base = fresh[1], fresh[0].astimezone(timezone.utc), last_close
    session = prices.session(at) if at else "Closed"
    live = bool(at) and (now - at) < timedelta(minutes=STALE_MINUTES) and session in LIVE_SESSIONS
    return {"price": round(price, 4), "close_day": last_day, "session": session,
            "at": at.isoformat(timespec="seconds") if at else None,
            "at_label": at.astimezone(prices.MARKET_TZ).strftime("%H:%M") + " New York" if at else None,
            "change": None if not base else price / base - 1,
            "previous_close": None if not base else round(base, 4)}, live


# ---- the chart --------------------------------------------------------------------------------
def build(range_, bars, intraday_bars, quote, now):
    kind = RANGES[range_][0]
    head, live = header(bars, quote, intraday_bars, now)
    if kind == "daily":
        cut = (date.fromisoformat(bars[-1][0]) - timedelta(days=RANGES[range_][1])).isoformat()
        shown = [b for b in bars if b[0] >= cut]
        out = {"bars": [_bar(b) for b in shown], "labels": None}
    else:
        many = RANGES[range_][1] > 1
        out = {"bars": [[int(b[0].timestamp())] + [round(x, 4) for x in b[1:5]] + [int(round(b[5]))]
                        for b in intraday_bars],
               "labels": [label(b[0], many) for b in intraday_bars]}
    out.update({"range": range_, "kind": kind, "price": head, "live": live, "every_minutes": EVERY_MINUTES,
                "split_adjusted": True, "demo": False, "currency": "USD"})
    return out


def chart(folder, ticker, range_, key=None, opener=None, now=None):
    """The chart of one ticker over one range: {"bars", "labels", "price", "live", …}. A
    ChartError says in words why not."""
    ticker, range_ = clean_ticker(ticker), range_ if range_ in RANGES else DEFAULT_RANGE
    if not ticker:
        raise ChartError("Type a ticker, like NVDA.")
    now = now or datetime.now(timezone.utc)
    key = key or _key()
    bars = daily(folder, ticker, key, opener, now)
    if RANGES[range_][0] == "intraday":
        got = intraday(folder, ticker, range_, key, opener, now)
        if not got:
            raise ChartError(f"Tiingo has no intraday prices for {ticker} yet.")
        quote = None
    else:
        got, quote = [], latest(folder, ticker, key, opener, now)
    out = build(range_, bars, got, quote, now)
    out["ticker"] = ticker
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
            "bars": f"{len(bars)} " + ("daily" if chart["kind"] == "daily" else f"{RANGES[chart['range']][2]}-minute") + " bars",
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
    out = build(range_, bars, fake, None, now)
    out.update({"ticker": ticker, "demo": True, "live": False})
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
