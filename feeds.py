"""Where a live price can come from, beside Tiingo (the owner, 5 Oct 2026: "check for other trading
api charts ... add many and combine them to get it as live as possible").

Two more free ones, each used only when its key is in .env, and each read only:

  Finnhub  a real-time quote for a US share (60 requests a minute on the free plan). The key the desk
           already uses for results and news. Its candles are a paid feature, so it gives a price only.
  Alpaca   IEX's latest trade and its bars down to the minute (200 requests a minute on the free
           plan), from the same ALPACA_API_KEY and ALPACA_API_SECRET a broker connection uses; a free
           paper account's pair is enough. The consolidated feed is paid and is never asked for.

Each answers in the same shape as the rest of the desk reads a price: {"price", "at", "feed"} for a
quote, Tiingo's own row shape for a bar, so that charts.py combines them with what Tiingo gives.
A key goes in a header, never in an address. A feed that fails says so in words and the others carry on.

Usage: python3 feeds.py NVDA     asks each feed that has a key once
"""
import json, os, sys, urllib.error, urllib.request
from datetime import datetime, timezone
from env_config import load_env, moment, unpacked

HERE = os.path.dirname(os.path.abspath(__file__))
FINNHUB, ALPACA, TIINGO = "Finnhub", "Alpaca", "Tiingo"
ORDER = (ALPACA, FINNHUB, TIINGO)       # who is preferred when two give the same moment
FAST = (ALPACA, FINNHUB)                # the feeds that can be asked every few seconds
TIMEOUT = 15
AGREE_SECONDS = 60       # feeds that spoke within this of the newest are compared
DISAGREE = 0.005         # the desk's choice: half a percent between two feeds at one moment is worth saying
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote?symbol={symbol}"
ALPACA_TRADE = "https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest?feed=iex"
ALPACA_BARS = ("https://data.alpaca.markets/v2/stocks/{symbol}/bars?timeframe={minutes}Min&start={start}"
               "&feed=iex&adjustment=split&limit=10000&sort=asc")


class FeedError(Exception):
    pass


def keys(environ=None):
    """{feed: its key} for each feed .env has a key for: Finnhub's string, Alpaca's (key, secret)."""
    if environ is None:
        load_env(os.path.join(HERE, ".env"))
        environ = os.environ
    found = {}
    finnhub = str(environ.get("FINNHUB_API_KEY") or "").strip()
    if finnhub:
        found[FINNHUB] = finnhub
    pair = (str(environ.get("ALPACA_API_KEY") or "").strip(), str(environ.get("ALPACA_API_SECRET") or "").strip())
    if all(pair):
        found[ALPACA] = pair
    return found


def symbol(ticker):
    """Finnhub and Alpaca write a share class with a dot, Tiingo with a dash."""
    return str(ticker).upper().replace("-", ".")


def _get(feed, url, headers, opener=None):
    req = urllib.request.Request(url, method="GET", headers=dict(headers, **{"Accept-Encoding": "gzip"}))
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            return json.loads(unpacked(r.read(), r) or b"{}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise FeedError(f"{feed} did not accept the key: check its keys in .env") from None
        if e.code == 429:
            raise FeedError(f"{feed}'s free limit is used up for now") from None
        if e.code == 404:
            return {}
        raise FeedError(f"{feed} returned HTTP {e.code}") from None
    except (OSError, ValueError) as e:
        raise FeedError(f"Can't reach {feed} ({e})") from None


def _alpaca_headers(pair):
    return {"APCA-API-KEY-ID": pair[0], "APCA-API-SECRET-KEY": pair[1]}


def finnhub_quote(ticker, key, opener=None):
    """{"price", "at", "feed"} from Finnhub's quote, or None: an unknown symbol comes back as zeros."""
    got = _get(FINNHUB, FINNHUB_QUOTE.format(symbol=symbol(ticker)), {"X-Finnhub-Token": key}, opener)
    price, stamp = got.get("c") if isinstance(got, dict) else None, got.get("t") if isinstance(got, dict) else None
    if isinstance(price, (int, float)) and price > 0 and isinstance(stamp, (int, float)) and stamp > 0:
        return {"price": float(price), "at": datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds"),
                "feed": FINNHUB}
    return None


def alpaca_quote(ticker, pair, opener=None):
    """{"price", "at", "feed"} from the latest trade on IEX, or None."""
    got = _get(ALPACA, ALPACA_TRADE.format(symbol=symbol(ticker)), _alpaca_headers(pair), opener)
    trade = got.get("trade") if isinstance(got, dict) else None
    when = moment((trade or {}).get("t"))
    price = (trade or {}).get("p")
    if when and isinstance(price, (int, float)) and price > 0:
        return {"price": float(price), "at": when.astimezone(timezone.utc).isoformat(timespec="seconds"), "feed": ALPACA}
    return None


def alpaca_bars(ticker, minutes, start, pair, opener=None):
    """Alpaca's IEX bars of `minutes` from the day `start`, as the rows charts.parse_intraday reads
    (Tiingo's names), oldest first; [] when it has none."""
    got = _get(ALPACA, ALPACA_BARS.format(symbol=symbol(ticker), minutes=minutes, start=start),
               _alpaca_headers(pair), opener)
    rows = []
    for bar in (got.get("bars") if isinstance(got, dict) else None) or []:
        if isinstance(bar, dict):
            rows.append({"date": bar.get("t"), "open": bar.get("o"), "high": bar.get("h"), "low": bar.get("l"),
                         "close": bar.get("c"), "volume": bar.get("v")})
    return rows


def combine(quotes, now):
    """The newest of the quotes: (best, differ). Ties in time go to the feed ORDER names first. `differ`
    is true when feeds that spoke within AGREE_SECONDS of the newest are more than DISAGREE apart: one of
    them is wrong, or one of them is one exchange's price and the other is not."""
    seen = [q for q in quotes if q and moment(q.get("at"))]
    if not seen:
        return None, False
    seen.sort(key=lambda q: (-moment(q["at"]).timestamp(), ORDER.index(q["feed"]) if q["feed"] in ORDER else len(ORDER)))
    best = seen[0]
    near = [q for q in seen if (moment(best["at"]) - moment(q["at"])).total_seconds() <= AGREE_SECONDS]
    prices = [q["price"] for q in near]
    return best, len(near) > 1 and max(prices) / min(prices) - 1 > DISAGREE



def main(argv):
    ticker = (argv[1] if len(argv) > 1 else "SPY").upper()
    have = keys()
    if not have:
        print("No Finnhub or Alpaca key in .env: nothing to ask.")
        return 1
    for name, ask in ((FINNHUB, lambda k: finnhub_quote(ticker, k)), (ALPACA, lambda k: alpaca_quote(ticker, k))):
        if name in have:
            try:
                print(name, ask(have[name]))
            except FeedError as e:
                print(name, "FAILED:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
