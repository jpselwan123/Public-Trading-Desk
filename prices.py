"""Daily prices for the watchlist (Tiingo) → prices.json.

Two closes are stored per day, because they answer different questions:
  "c" the close as printed that day — what a rule could actually have seen, so
      signals (moving averages, past returns) are built from it
  "a" the split- and dividend-adjusted close — what the holding actually earned,
      so returns are computed from it
Using adjusted prices for signals would test a series that did not exist at the
time. Incremental: after the first pull, only days since the last stored one — and that
day again, because an adjusted close is restated whenever a later dividend or split comes:
the stored ones are re-based onto Tiingo's latest by the ratio on that shared day, so a
split never reads as a fall and a dividend is never lost from a return (27 Sep 2026: they
were, before). A split is also stored on its day ("s", Tiingo's splitFactor, the new shares
for each old one), so a trade made before it can be compared with one made after
(splits, split_factor).

Also stored: the 3-month US Treasury bill rate (FRED, no key), so a rule that is
out of the market earns cash interest instead of nothing — the way Faber (2007)
and the rest of the trend literature measure it.

Also on each refresh: the latest price Tiingo has from IEX for each covered company,
pre- and post-market included (quotes.json), shown beside the close when it is newer.

Key (free, no card) from tiingo.com → .env as TIINGO_API_KEY. Nothing here is a
recommendation; prices are the raw material for measuring what happened after an
event (see build_desk.build_reactions).

Usage: python3 prices.py            update the watchlist's prices
       python3 prices.py AAPL       update one ticker
"""
import collections, json, os, re, sys, time, urllib.error, urllib.request
from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo
from env_config import load_env, atomic_write_json, fetched_today, moment, unpacked, PARTLY
from news import FOLLOW_USAGE, load_watchlist

HERE = os.path.dirname(os.path.abspath(__file__))
PRICES_FILE = os.path.join(HERE, "prices.json")
URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}&format=json"
# IEX's latest price for many tickers in one request; afterHours includes the
# exchange's pre- and post-market trades.
LATEST_URL = "https://api.tiingo.com/iex/?tickers={tickers}&afterHours=true"


class USEastern(tzinfo):
    """New York's clock from the US rule itself, for a Python with no time-zone data (an
    iPhone's may have none). Daylight time runs from 02:00 on the second Sunday of March
    to 02:00 on the first Sunday of November (Energy Policy Act of 2005, in force from
    2007); the desk asks the clock only about sessions since then."""
    STANDARD, DAYLIGHT = timedelta(hours=-5), timedelta(hours=-4)

    @staticmethod
    def _sunday(year, month, nth):
        first = date(year, month, 1)
        return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (nth - 1))

    def _daylight_utc(self, year):
        """Daylight time's start and end that year, as UTC wall times."""
        return (datetime.combine(self._sunday(year, 3, 2), datetime.min.time()) + timedelta(hours=7),
                datetime.combine(self._sunday(year, 11, 1), datetime.min.time()) + timedelta(hours=6))

    def fromutc(self, dt):
        naive = dt.replace(tzinfo=None)
        start, end = self._daylight_utc(naive.year)
        return (naive + (self.DAYLIGHT if start <= naive < end else self.STANDARD)).replace(tzinfo=self)

    def utcoffset(self, dt):
        naive = dt.replace(tzinfo=None)
        start, end = self._daylight_utc(naive.year)
        return self.DAYLIGHT if start + self.STANDARD <= naive < end + self.DAYLIGHT else self.STANDARD

    def dst(self, dt):
        return self.utcoffset(dt) - self.STANDARD

    def tzname(self, dt):
        return "EDT" if self.dst(dt) else "EST"


def _market_clock():
    try:
        return ZoneInfo("America/New_York")
    except Exception:                   # no time-zone data on this device
        return USEastern()


MARKET_TZ = _market_clock()
# The US sessions by the exchanges' own clock: trading outside the regular session runs
# from 04:00 before the open and until 20:00 after the close.
SESSIONS = (("04:00", "Pre-market"), ("09:30", "Regular session"), ("16:00", "After hours"),
            ("20:00", "Overnight"))
CLOSE = "16:00"
# 3-month T-bill, % a year. Asking for the whole series since 1954 is a 300 KB
# download that times out on a slow link; `cosd` limits it to the years we test.
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"
CASH_SERIES = "DTB3"
# US dollars to one unit of an account's currency, FRED's daily series from the Federal
# Reserve's H.10 release. An account kept in one of these is compared with the S&P 500
# through them; one in another currency is not compared.
FX_SERIES = {"EUR": "DEXUSEU", "GBP": "DEXUSUK"}
FX_PREFIX = "fx_"             # stored as fx_EUR: {day: dollars per euro}, dated like a close
CASH_KEY = "cash_rates"
CASH_FETCHED = "_cash_fetched"   # the day the cash rate last came back from FRED
META_KEYS = ("updated_at", CASH_KEY, "_starts", CASH_FETCHED, "_asked", "_slow_asked", "_waiting", "_whole")
BENCHMARK = "SPY"          # every reaction is measured against the market too
HISTORY_YEARS = 35        # each fund's full history; the sector funds start in 1998
EARLIEST = "1990-01-01"   # before any fund in the universe existed
META_STARTS = "_starts"   # how far back each ticker has actually been fetched
TIMEOUT = 30
CASH_TIMEOUT = 90         # the FRED CSV is ~300 KB and slow on a slow connection
CASH_RETRIES = 2
CASH_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) trading-desk/1.0"
REQUEST_GAP = 0.3


class PriceError(Exception):
    pass


def api_key():
    load_env(os.path.join(HERE, ".env"))
    key = os.environ.get("TIINGO_API_KEY", "").strip()
    if not key:
        raise PriceError("Add TIINGO_API_KEY=… to .env (free key from tiingo.com)")
    return key


def _tiingo(url, key, opener=None):
    """One Tiingo request, its JSON, or [] for an unknown ticker; a failure is a PriceError."""
    req = urllib.request.Request(url, method="GET", headers={"Content-Type": "application/json",
                                                             "Authorization": f"Token {key}",
                                                             "Accept-Encoding": "gzip"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            return json.loads(unpacked(r.read(), r) or b"[]")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise PriceError("Tiingo rejected the key: check TIINGO_API_KEY in .env") from None
        if e.code == 404:
            return []                       # unknown ticker: not fatal
        if e.code == 429:
            raise PriceError("Tiingo's free limit is used up for now; the next update carries on") from None
        raise PriceError(f"Tiingo returned HTTP {e.code}") from None
    except Exception as e:
        raise PriceError(f"Can't reach Tiingo ({e})") from None


def fetch_prices(ticker, start, key, opener=None, sleep=time.sleep):
    """[(YYYY-MM-DD, close, adjusted close, split factor)] from start (inclusive), oldest
    first. The split factor is 1 on every day but a split's."""
    rows = _tiingo(URL.format(ticker=ticker.lower(), start=start), key, opener)
    sleep(REQUEST_GAP)
    out = []
    for row in rows or []:
        day = str(row.get("date") or "")[:10]
        raw, adj = row.get("close"), row.get("adjClose")
        try:
            split = float(row.get("splitFactor") or 1.0)
        except (TypeError, ValueError):
            split = 1.0
        if day and (raw is not None or adj is not None):
            raw = float(raw if raw is not None else adj)
            out.append((day, raw, float(adj if adj is not None else raw), split if split > 0 else 1.0))
    return sorted(out)


def session(when):
    """The US market session a moment falls in, by New York's clock."""
    clock = when.astimezone(MARKET_TZ).strftime("%H:%M")
    name = SESSIONS[-1][1]                  # before 04:00 is still the night
    for start, label in SESSIONS:
        if clock >= start:
            name = label
    return name


def fetch_latest(tickers, key=None, opener=None):
    """{"quotes": {TICKER: {"price", "at"}}, "fetched_at"}: the latest price Tiingo has from
    IEX for each ticker, pre- and post-market trades included, in one request. IEX itself
    trades from 08:00 to 17:00 New York time, so earlier in the pre-market and later in
    the evening this is IEX's latest price, and its time says how old it is."""
    wanted = sorted({str(t).upper() for t in tickers or [] if t})
    quotes = {}
    if wanted:
        rows = _tiingo(LATEST_URL.format(tickers=",".join(t.lower() for t in wanted)), key or api_key(), opener)
        for row in rows or []:
            ticker = str(row.get("ticker") or "").upper()
            price = row.get("tngoLast") if row.get("tngoLast") is not None else row.get("last")
            when = moment(row.get("timestamp"))
            if ticker in wanted and isinstance(price, (int, float)) and price > 0 and when:
                quotes[ticker] = {"price": float(price),
                                  "at": when.astimezone(timezone.utc).isoformat(timespec="seconds")}
    return {"quotes": quotes, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# A price this far from the close is flagged for checking in Trading 212 (the desk's choice):
# a 2-for-1 split reads as -50% until the day's close restates the others; few real moves
# between two sessions are this large.
LATEST_CHECK = 0.25


def latest_after_close(quote, close_day, close):
    """The quote as the page shows it beside a close, or None. Only a price taken after
    that close's session ended (16:00 New York time on its day) is newer than it; the
    change is measured from that close."""
    when = moment((quote or {}).get("at"))
    if not when or not close or not close_day:
        return None
    there = when.astimezone(MARKET_TZ)
    if (there.date().isoformat(), there.strftime("%H:%M")) < (close_day, CLOSE):
        return None
    change = quote["price"] / close - 1
    return {"price": quote["price"], "at": quote["at"], "session": session(when), "change": change,
            # a split that takes effect overnight is in the quote before any close has it
            "check": abs(change) >= LATEST_CHECK}


def fetch_cash_rates(start=None, opener=None, sleep=time.sleep):
    """{YYYY-MM-DD: rate % a year} for the 3-month Treasury bill (FRED DTB3)."""
    return fetch_fred(CASH_SERIES, start, opener, sleep, what="the cash rate")


def fetch_fred(series, start=None, opener=None, sleep=time.sleep, what="a rate"):
    """{YYYY-MM-DD: value} for one FRED daily series."""
    start = start or max(EARLIEST, (datetime.now(timezone.utc).date() - timedelta(days=365 * (HISTORY_YEARS + 1))).isoformat())
    # FRED's edge stalls unfamiliar user agents; a conventional one that still
    # names this app gets the CSV in under a second.
    req = urllib.request.Request(FRED_URL.format(series=series, start=start), method="GET",
                                 headers={"User-Agent": CASH_USER_AGENT, "Accept": "text/csv, */*"})
    text = None
    for attempt in range(CASH_RETRIES + 1):
        try:
            with (opener or urllib.request.urlopen)(req, timeout=CASH_TIMEOUT) as r:
                text = r.read().decode("utf-8", "replace")
                sleep(REQUEST_GAP)
            break
        except Exception as e:
            if attempt == CASH_RETRIES:
                raise PriceError(f"Can't reach FRED for {what} ({e})") from None
            sleep(2 * (attempt + 1))
    out = {}
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        day, value = parts[0].strip()[:10], parts[1].strip()
        try:
            out[day] = float(value)
        except ValueError:
            continue                      # FRED writes "." on market holidays
    return out


# ---- reading what is stored --------------------------------------------------------
def tickers(store):
    return [k for k in (store or {}) if k not in META_KEYS and not k.startswith(FX_PREFIX)]


def fx_rates(store, currency):
    """{day: US dollars per unit of `currency`}, or {} when none are stored."""
    return dict((store or {}).get(FX_PREFIX + str(currency or "")) or {})


def series(store, ticker, kind="a"):
    """{day: price} for one ticker. kind "c" = close as printed, "a" = adjusted.
    Understands the old format, where each day held a single adjusted number."""
    raw = (store or {}).get(ticker) or {}
    out = {}
    for day, value in raw.items():
        if isinstance(value, dict):
            picked = value.get(kind, value.get("a", value.get("c")))
        else:
            picked = value                # old file: one number, adjusted
        if picked is not None:
            out[day] = float(picked)
    return out


def cash_rates(store):
    return (store or {}).get(CASH_KEY) or {}


def needs_refetch(store, ticker):
    """Old single-number days have no raw close, so that ticker is pulled again."""
    days = (store or {}).get(ticker) or {}
    return bool(days) and not isinstance(next(iter(days.values())), dict)


def splits(store, ticker):
    """[(day, factor)] for each split stored for a ticker, oldest first: on `day` each old
    share became `factor` new ones (a reverse split is below 1)."""
    raw = (store or {}).get(ticker) or {}
    return sorted((d, float(v["s"])) for d, v in raw.items() if isinstance(v, dict) and v.get("s"))


def split_factor(store, ticker, after, through):
    """How many of `through`'s shares one share held on `after` became: the product of the
    splits on the days after `after`, up to and including `through`. 1 when none."""
    return factor_between(splits(store, ticker), after, through)


def factor_between(split_days, after, through):
    """split_factor's arithmetic on a ticker's splits already read ([(day, factor)]): for a
    loop over many trades, which reads them once (28 Sep 2026: read afresh for each lot,
    3,000 trades took seconds)."""
    factor = 1.0
    for day, f in split_days:
        if after < day <= through:
            factor *= f
    return factor


class SplitsRead(dict):
    """{ticker: its splits}, each read from the store the first time it is asked for."""

    def __init__(self, store):
        super().__init__()
        self.store = store

    def __missing__(self, ticker):
        self[ticker] = splits(self.store, ticker)
        return self[ticker]

    def factor(self, ticker, after, through):
        return factor_between(self[ticker], after, through)


def _merge(days, rows):
    """`days` with `rows` merged in: the stored adjusted closes first re-based onto the
    rows' basis, by the ratio of the two adjusted closes on the day both hold (the last
    stored), so a dividend or split since restates them as Tiingo now does."""
    days = dict(days)
    shared = {row[0]: row for row in rows if row[0] in days}
    if shared:
        day = max(shared)
        old, new = (days[day] or {}).get("a"), shared[day][2]
        if old and new and abs(new / old - 1) > 1e-12:
            ratio = new / old
            days = {d: (dict(v, a=v["a"] * ratio) if isinstance(v, dict) and v.get("a") is not None else v)
                    for d, v in days.items()}
    for row in rows:
        day, raw, adj = row[:3]
        split = row[3] if len(row) > 3 else 1.0
        days[day] = {"c": raw, "a": adj}
        if split and abs(split - 1) > 1e-12:
            days[day]["s"] = split
    return days


def last_close(now):
    """The newest daily close that can exist at `now`: the latest weekday whose regular
    session has ended by New York's clock. A market holiday passes for a session here;
    the benchmark's own close says whether there was one (update)."""
    local = now.astimezone(MARKET_TZ)
    day = local.date() - timedelta(days=0 if local.strftime("%H:%M") >= CLOSE else 1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def session_day(when):
    """The first regular session a moment's news could move a price in: that day's, if it
    came on a weekday before the close by New York's clock, else the next weekday's. A
    holiday passes for a session here; the first close on or after the day is the one
    that counts (build_desk.build_headlines)."""
    local = when.astimezone(MARKET_TZ)
    day = local.date() + timedelta(days=0 if local.strftime("%H:%M") < CLOSE else 1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


# Tiingo's free key: 50 requests an hour and 1,000 a day (tiingo.com's pricing page). Each
# daily-price request is counted in the store, and an update stops asking before either
# is reached, leaving SPARE an hour for the latest prices and a company followed
# meanwhile; what it did not reach, the next update asks.
TIINGO_PER_HOUR, TIINGO_PER_DAY = 50, 1000
SPARE = 5
META_ASKED = "_asked"               # when each request of the last day was made
META_SLOW = "_slow_asked"           # {ticker: "YYYY-MM"}: the month a slow ticker was last asked
META_WAITING = "_waiting"           # how many tickers the last update left for the next
# {ticker: the day its history was last fetched whole, split factors and all}. A ticker not
# in it (all of them, before 27 Sep 2026) is fetched whole once more: its stored adjusted
# closes were never restated for later dividends and splits, and its splits were not kept.
META_WHOLE = "_whole"
# A slow ticker (rating.py's sample) is priced about once a month, with this much history:
# thirteen months for the momentum measure and a margin for holidays.
SLOW_DAYS = 430


def month_end_before(day):
    """The last day of the month before `day`'s."""
    return day.replace(day=1) - timedelta(days=1)


def update(tickers, stored=None, key=None, fetch=fetch_prices, today=None, cash=fetch_cash_rates,
           currency=None, fx=fetch_fred, now=None, slow=None, spare=SPARE, traded=None):
    """Nothing is asked for that cannot have changed. The company data updates by itself
    every build_desk.MARKET_EVERY_MINUTES, and Tiingo's free key allows 50 requests an
    hour: so the benchmark is asked first, and only once a session has closed, and a
    share only for a close the benchmark already has. Between two closes a refresh asks
    nothing here; on a holiday, or before Tiingo has the day's closes, it asks once.

    `slow` tickers (the rating's fixed sample) are asked at most once a month, when last
    month's end is not yet stored, and only with what budget the others leave. `spare`
    is left unused: the company update keeps SPARE back; a company just followed (spare=0)
    may use it. `traded` is {ticker: the first day it was traded in the account}: each is
    fetched whole from that day once, so a split while it was held is known, and then only
    as the other lists ask."""
    key = key or api_key()
    stored = dict(stored or {})
    stored.pop(PARTLY, None)                # an old one is never this update's
    if now is None:
        now = (datetime.now(timezone.utc) if today is None
               else datetime(today.year, today.month, today.day, 23, 59, tzinfo=timezone.utc))
    today = today or now.date()
    full_start = max(EARLIEST, (today - timedelta(days=365 * HISTORY_YEARS)).isoformat())
    slow_start = (today - timedelta(days=SLOW_DAYS)).isoformat()
    closed = last_close(now).isoformat()
    published = None                        # the benchmark's newest close: none is newer
    wanted = list(dict.fromkeys([BENCHMARK] + [t.upper() for t in tickers]))
    starts = dict(stored.get(META_STARTS) or {})
    day_ago, hour_ago = (now - timedelta(days=1)).isoformat(), (now - timedelta(hours=1)).isoformat()
    asked = [a for a in stored.get(META_ASKED) or [] if a > day_ago]
    slow_asked = dict(stored.get(META_SLOW) or {})
    whole = dict(stored.get(META_WHOLE) or {})
    month = today.strftime("%Y-%m")
    waiting = 0
    failed = []                             # why a request failed: nothing more is asked, what came is kept

    def room():
        return (sum(1 for a in asked if a > hour_ago) < TIINGO_PER_HOUR - spare
                and len(asked) < TIINGO_PER_DAY - spare)

    def ask(ticker, start):
        """The closes from `start`, or None once a request has failed: the rest wait."""
        if failed:
            return None
        asked.append(now.isoformat(timespec="seconds"))
        try:
            return fetch(ticker, start, key)
        except PriceError as e:
            failed.append(str(e))
            return None
    for ticker in wanted:
        days = dict(stored.get(ticker) or {})
        start = full_start
        if needs_refetch(stored, ticker) or starts.get(ticker, "9999") > full_start or ticker not in whole:
            days = {}                       # older data wanted than we have ever asked for, or never whole
        elif days:
            last = max(days)
            if last >= (closed if ticker == BENCHMARK else min(closed, published or closed)):
                published = last if ticker == BENCHMARK else published
                continue                    # it has every close there is yet
            start = last                    # that day again: the ratio that re-bases the rest
        if not room():
            waiting += 1
            continue
        whole_now = not days
        answer = ask(ticker, start)
        if answer is None:
            continue
        days = _merge(days, answer)
        if days:
            stored[ticker] = days
            starts[ticker] = min(starts.get(ticker, "9999"), full_start)
            if whole_now:
                whole[ticker] = today.isoformat()
        if ticker == BENCHMARK:
            published = max(days) if days else None
    # the slow ones, those with the oldest close first, so a backlog goes round
    month_end = month_end_before(today).isoformat()
    due = []
    for ticker in dict.fromkeys(str(t).upper() for t in slow or []):
        if ticker in wanted or slow_asked.get(ticker) == month:
            continue
        days = stored.get(ticker) or {}
        if days and not needs_refetch(stored, ticker) and ticker in whole and max(days) >= month_end:
            continue                        # last month's end is here: nothing is due
        due.append((max(days) if days else "", ticker))
    for _, ticker in sorted(due):
        if not room():
            waiting += 1
            continue
        days = {} if needs_refetch(stored, ticker) or ticker not in whole else dict(stored.get(ticker) or {})
        start = max(days) if days else slow_start
        whole_now = not days
        answer = ask(ticker, start)
        if answer is None:
            continue
        days = _merge(days, answer)
        slow_asked[ticker] = month
        if days:
            stored[ticker] = days
            starts[ticker] = min(starts.get(ticker, "9999"), slow_start)
            if whole_now:
                whole[ticker] = today.isoformat()
    # each ticker traded in the account, once, whole from its first trade: its splits
    for ticker, first in sorted((str(t).upper(), str(d)[:10]) for t, d in (traded or {}).items()):
        if ticker in wanted or (ticker in whole and starts.get(ticker, "9999") <= first):
            continue
        if not room():
            waiting += 1
            continue
        answer = ask(ticker, first)
        if answer is None:
            continue
        days = _merge({}, answer)
        if days:
            stored[ticker] = days
            starts[ticker] = min(starts.get(ticker, "9999"), first)
        whole[ticker] = today.isoformat()
    stored[META_ASKED], stored[META_SLOW], stored[META_WAITING] = asked, slow_asked, waiting
    stored[META_WHOLE] = whole
    stored[META_STARTS] = starts
    # FRED publishes the rate once a day, and its CSV is slow on a slow connection
    due = not fetched_today(stored.get(CASH_FETCHED), today)
    fx_key = FX_PREFIX + currency if currency in FX_SERIES else None
    if fx_key and fx is not None and (due or fx_key not in stored):
        try:
            stored[fx_key] = dict(stored.get(fx_key) or {},
                                  **(fx(FX_SERIES[currency], what=f"{currency} exchange rates") or {}))
        except PriceError:
            pass                            # only the market comparison needs them; it says so
    if cash is not None and due:
        rates = dict(stored.get(CASH_KEY) or {})
        try:
            rates.update(cash() or {})
            stored[CASH_FETCHED] = today.isoformat()
        except PriceError as e:
            if not rates:
                failed.append(str(e))       # no cash rate at all: the backtest would be wrong, so say so
        stored[CASH_KEY] = rates            # otherwise keep what we have and carry on
    stored["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if failed:
        stored[PARTLY] = failed[0]
    return stored


def merge_ticker(stored, fresh, ticker):
    """`stored` with one ticker's closes taken from `fresh`, an update run for that ticker alone
    (a company just followed) beside a company update that may be writing the same store: its
    closes, the day it was fetched whole and from when, and each request it made, counted once,
    so the hour's budget still counts them. Made twice, it changes nothing more."""
    out = dict(stored or {})
    ticker = str(ticker).upper()
    if (fresh or {}).get(ticker):
        out[ticker] = fresh[ticker]
    for meta in (META_WHOLE, META_STARTS):
        if ticker in ((fresh or {}).get(meta) or {}):
            out[meta] = dict(out.get(meta) or {}, **{ticker: fresh[meta][ticker]})
    asked = list(out.get(META_ASKED) or [])
    more = collections.Counter((fresh or {}).get(META_ASKED) or []) - collections.Counter(asked)
    out[META_ASKED] = sorted(asked + list(more.elements()))
    return out


def load(path=None):
    try:
        with open(path or PRICES_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main(argv):
    try:
        import research                     # here, not above: research reads this module
        wanted = [a.upper() for a in argv if not a.startswith("-")] or load_watchlist() + research.sample()
        if not wanted:
            print("No company followed yet: " + FOLLOW_USAGE, file=sys.stderr)
            return 2
        data = update(wanted, stored=load())
        partly = data.pop(PARTLY, None)
        atomic_write_json(PRICES_FILE, data)
        if partly:
            print(partly, file=sys.stderr)
        held = {k: data[k] for k in tickers(data)}
        print(f"{len(held)} tickers, {sum(len(v) for v in held.values())} daily closes, "
              f"{len(cash_rates(data))} cash-rate days")
        return 0
    except PriceError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
