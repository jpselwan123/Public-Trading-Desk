"""News on each company the user follows, from several sources → headlines.json.

What the press and the wires have written about each followed company: the headline,
who published it, when, and a link to read it at its source. Other people's words,
shown as published; the desk neither scores nor rewrites them. Beside each day's
headlines the page shows how the shares moved that day against the market, and whether
that move was unusual for them (build_desk.build_headlines): a fact about that day, not
a forecast.

The sources, each asked with the company data at every update (several, as each has its limits):

  finnhub  Finnhub's company news: the wires and financial sites it gathers. Its free plan
           covers North American companies. Key: FINNHUB_API_KEY in .env, as earnings.py uses.
  press    The financial press: the FT (read with a subscription of your own),
           Reuters, Bloomberg and Dow Jones's papers (The Wall Street Journal, Barron's,
           MarketWatch) — the newswires and papers the research on news and share prices
           read (Tetlock, Saar-Tsechansky & Macskassy 2008 read Dow Jones's; Heston & Sinha
           2017, Reuters'). Found through Google News's search, which needs no key: two
           searches a company, the FT's alone so a busy week elsewhere cannot crowd it out.
           Google does not document that search as a service, and marks it for personal,
           non-commercial reading, which this desk is; if it stops answering, the step says
           so, and doctor.py.

Only stories about the company are kept: its name or ticker must appear in the headline or
the first 25 words of the story — the rule Tetlock, Saar-Tsechansky & Macskassy (2008) used
to keep only a firm's own news. A search or a feed returns much that merely mentions a
company (a market round-up, a list of stocks); those are dropped.

Why news is not part of the desk's rating: the published evidence on news is about days,
and the rating is about a year. The share of negative words in a company's news forecasts
its earnings and its next day's return, and prices underreact only briefly (Tetlock,
Saar-Tsechansky & Macskassy 2008, "More than words", Journal of Finance 63); one day's
news predicts returns for one or two days, a week's for about a quarter (Heston & Sinha
2017, "News vs. sentiment", Financial Analysts Journal 73). The rating's papers held
portfolios for a year, and its record is scored at 3, 6 and 12 months (rating.py).

Fetched with the company data, on each update: news can arrive at any hour, so each
source is asked for what came since the day it was last asked.

Usage: python3 headlines.py [TICKER ...]     the followed companies' latest headlines
"""
import gzip, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import earnings
import universe
from env_config import atomic_write_json, moment, PARTLY
from news import NEWS_FILE, load_watchlist

HERE = os.path.dirname(os.path.abspath(__file__))
HEADLINES_FILE = os.path.join(HERE, "headlines.json")
# The desk's choices, both presentation and storage limits: a month of headlines per
# company, and at most this many from each source — a large company has dozens a day.
KEEP_DAYS = 30
# A company's news is asked again no sooner than this after it was last asked (the desk's choice, 5 Oct 2026): the
# company data updates every half hour, a request a company costs a polite pause, and the evidence the page shows news
# for is about days (Tetlock et al. 2008; Heston & Sinha 2017), so a story reaches the page within the hour, not the half
# hour. Under the update's own interval and over half of it: with the half hour between updates, every other one asks.
ASK_AGAIN_MINUTES = 45
ASK_AGAIN = timedelta(minutes=ASK_AGAIN_MINUTES)
KEPT = 150
LONGEST = 300                   # characters of a headline kept; a wire's are far shorter
LEDE_WORDS = 25                 # Tetlock, Saar-Tsechansky & Macskassy (2008): the name within the first 25 words
SOURCES = {"finnhub": "Finnhub company news", "press": "the financial press, through Google News"}


class PressError(Exception):
    pass


# ---- which company a story is about -----------------------------------------------------
# Words of legal form at the end of a filed name, which no headline uses: "Nvidia Corp" is
# written "Nvidia", "Amazon Com Inc" "Amazon".
LEGAL = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
         "llc", "lp", "sa", "ag", "nv", "se", "com", "the", "&", "and"}
# Words a headline usually drops from a name: "UnitedHealth Group" is "UnitedHealth",
# "Meta Platforms" "Meta". Used to recognise a story already found for the company, never
# to search for one: "Booking" alone would find travel stories.
USUALLY_DROPPED = {"group", "holdings", "holding", "platforms", "technologies", "technology",
                   "international", "companies", "enterprises", "industries", "systems", "brands",
                   "wholesale"}
# The press's own names for companies whose filed name it does not use. Names, not
# thresholds: what the papers call them.
PRESS_NAMES = {"GOOGL": ("Google",), "GOOG": ("Google",), "AMD": ("AMD",), "IBM": ("IBM",),
               "JNJ": ("J&J",), "PG": ("P&G",), "JPM": ("JPMorgan",), "LLY": ("Eli Lilly",),
               "DIS": ("Disney",), "XOM": ("Exxon",), "TSM": ("TSMC",), "BRK.A": ("Berkshire",),
               "BRK.B": ("Berkshire",), "COST": ("Costco",), "HPQ": ("HP",), "GM": ("General Motors",)}


def _plain(text, possessive=False):
    """Lower case, apostrophes dropped, everything but letters and digits a space:
    "McDonald's" and "MCDONALDS" read alike, as do "Coca-Cola" and "COCA COLA". With
    `possessive`, a closing "'s" goes first, so "Nvidia's" reads "nvidia"."""
    text = str(text or "").lower()
    if possessive:
        text = re.sub(r"['’]s\b", "", text)
    text = re.sub(r"['’]", "", text)
    return " " + " ".join(re.sub(r"[^0-9a-z]+", " ", text).split()) + " "


def search_names(ticker, filed=None):
    """The names to search the press for: the filed name without its legal form, and any
    name the press uses instead (PRESS_NAMES). With no filed name, the ticker."""
    names = []
    words = (universe.display_name(filed) or "").replace(",", " ").split() if filed else []
    while words and words[-1].strip(".").lower() in LEGAL:
        words.pop()
    if words and " ".join(words).upper() != str(ticker).upper():
        names.append(" ".join(words))
    names += [n for n in PRESS_NAMES.get(str(ticker).upper(), ()) if n not in names]
    return names or [str(ticker).upper()]


def known_names(ticker, filed=None):
    """Every name a story about the company may use: search_names, and each without the
    words a headline usually drops (at least four letters left, so the name still names)."""
    names = [n for n in search_names(ticker, filed) if n.upper() != str(ticker).upper()]
    for name in list(names):
        words = name.split()
        while len(words) > 1 and words[-1].lower() in USUALLY_DROPPED:
            words.pop()
        short = " ".join(words)
        if short not in names and len(re.sub(r"[^A-Za-z0-9]", "", short)) >= 4:
            names.append(short)
    return names


def about(item, ticker, filed=None):
    """Whether a story is about the company: its name or its ticker in the headline or the
    first LEDE_WORDS words of the story (Tetlock, Saar-Tsechansky & Macskassy 2008). The
    ticker counts as written, in capitals, and only when it is two letters or more."""
    text = " ".join([str(item.get("headline") or "")] + str(item.get("lede") or "").split()[:LEDE_WORDS])
    plains = (_plain(text), _plain(text, possessive=True))       # "McDonald's" is a name, "Nvidia's" a possessive
    if any(_plain(name) in plain for name in known_names(ticker, filed) if _plain(name).strip() for plain in plains):
        return True
    ticker = str(ticker or "").upper()
    return len(ticker) >= 2 and re.search(r"(?<![A-Za-z0-9])\$?" + re.escape(ticker) + r"(?![A-Za-z0-9])", text) is not None


# ---- Finnhub ---------------------------------------------------------------------------
def _item(row):
    """One of Finnhub's rows as the desk keeps it, or None when it lacks a headline, a
    time, or a web link (a link that is not http(s) is never kept: the page links it).
    The start of its summary is kept to tell whether it is about the company."""
    if not isinstance(row, dict):
        return None
    headline = " ".join(str(row.get("headline") or "").split())[:LONGEST]
    url = str(row.get("url") or "").strip()
    try:
        stamp = int(row.get("datetime") or 0)
    except (TypeError, ValueError):
        stamp = 0
    if not headline or stamp <= 0 or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        return None
    at = datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")
    out = {"id": str(row.get("id") or url), "headline": headline,
           "source": " ".join(str(row.get("source") or "").split()) or None, "url": url, "at": at}
    lede = " ".join(str(row.get("summary") or "").split()[:LEDE_WORDS])
    if lede:
        out["lede"] = lede
    return out


def fetch_company(ticker, since, until, key, fetch=earnings.fetch):
    """Finnhub's news for one company between two days (inclusive), newest first."""
    rows = fetch(f"company-news?symbol={urllib.parse.quote(ticker)}&from={since}&to={until}", key) or []
    items = [i for i in map(_item, rows if isinstance(rows, list) else []) if i]
    return sorted(items, key=lambda i: i["at"], reverse=True)


# ---- the financial press, through Google News ----------------------------------------------
# (domain, the outlet's name as the page shows it, the ways a source line names it). The
# FT is searched alone; the others together.
PRESS = (("ft.com", "Financial Times", ("financial times", "ft com")),
         ("reuters.com", "Reuters", ("reuters",)),
         ("bloomberg.com", "Bloomberg", ("bloomberg",)),
         ("wsj.com", "The Wall Street Journal", ("wall street journal", "wsj")),
         ("barrons.com", "Barron's", ("barrons",)),
         ("marketwatch.com", "MarketWatch", ("marketwatch",)))
FT = PRESS[0][0]
SEARCH_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) trading-desk/1.0"
TIMEOUT = 25
REQUEST_GAP = 0.5               # seconds between searches: Google publishes no limit, so the desk goes gently
LARGEST = 3_000_000             # bytes of one answer read; a search's 100 stories are a tenth of that


def outlet(source):
    """The outlet's name as the page shows it, when a source is one of PRESS; else None."""
    plain = _plain(source)
    return next((name for _, name, forms in PRESS if any(_plain(f) in plain for f in forms)), None)


def press_queries(ticker, filed=None, days=KEEP_DAYS):
    """The two searches for one company: the FT's, and the rest of the press's."""
    names = " OR ".join('"' + n.replace('"', "") + '"' for n in search_names(ticker, filed))
    names = f"({names})" if " OR " in names else names
    others = " OR ".join(f"site:{domain}" for domain, _, _ in PRESS[1:])
    return [f"{names} site:{FT} when:{days}d", f"{names} ({others}) when:{days}d"]


def fetch_rss(url, opener=None):
    """The raw answer to one search."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, text/xml",
                                               "Accept-Encoding": "gzip"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            body = r.read(LARGEST)
            if (r.headers.get("Content-Encoding") or "") == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as unpacked:
                    body = unpacked.read(LARGEST)          # never more than that, however it unpacks
            return body
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise PressError("Google News asked the desk to slow down (HTTP 429); the next update tries again") from None
        raise PressError(f"Google News returned HTTP {e.code}") from None
    except Exception as e:
        raise PressError(f"Can't reach Google News ({e})") from None


def parse_rss(body):
    """The stories in one search's answer, as the desk keeps them, from the outlets in PRESS
    only. A page that is not a feed (a notice in place of results) is an error, not an
    empty answer."""
    if not body or b"<!ENTITY" in body or b"<!DOCTYPE" in body[:2000].upper():
        raise PressError("Google News answered with something other than a news feed")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise PressError("Google News answered with something other than a news feed") from None
    if root.find("channel") is None:
        raise PressError("Google News answered with something other than a news feed")
    out = []
    for node in root.iter("item"):
        source = " ".join((node.findtext("source") or "").split())
        name = outlet(source)
        title = " ".join((node.findtext("title") or "").split())
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        url = (node.findtext("link") or "").strip()
        try:
            when = parsedate_to_datetime(node.findtext("pubDate") or "")
        except (TypeError, ValueError, IndexError):
            when = None
        if not name or not title or when is None or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        out.append({"id": url, "headline": title[:LONGEST], "source": name, "url": url,
                    "at": when.astimezone(timezone.utc).isoformat(timespec="seconds")})
    return out


def fetch_press(ticker, filed, days, fetch=fetch_rss, sleep=time.sleep):
    """The press's stories on one company over the last `days` days, newest first."""
    items = {}
    for query in press_queries(ticker, filed, days):
        for item in parse_rss(fetch(SEARCH_URL.format(query=urllib.parse.quote(query)))):
            items[item["id"]] = item
        sleep(REQUEST_GAP)
    return sorted(items.values(), key=lambda i: i["at"], reverse=True)


# ---- the store ----------------------------------------------------------------------------
def _fetched(stored, via):
    """{ticker: the day `via` last asked}. A store from before there were two sources holds
    one flat map, which was Finnhub's."""
    fetched = (stored or {}).get("fetched") or {}
    if fetched and all(isinstance(v, str) for v in fetched.values()):
        return dict(fetched) if via == "finnhub" else {}
    return dict(fetched.get(via) or {})


def _asked(stored, via):
    """{ticker: the moment `via` last asked}, a stamp kept beside the day in `fetched`: the day sets what is
    asked for, the moment how soon it is asked again. Anything but a map of stamps is no record."""
    asked = ((stored or {}).get("asked") or {})
    asked = asked.get(via) if isinstance(asked, dict) else None
    return {t: m for t, m in asked.items() if isinstance(t, str) and moment(m)} if isinstance(asked, dict) else {}


def _merge(stored, via, tickers, fresh_for, now, prune, names, skip_within=None, ask=None):
    """The store with one source's fresh stories merged in: for each of `tickers`, every
    story kept that is about the company, a month at most, KEPT from each source. The other
    source's stories and fetch days are kept as they are; with `prune`, companies no longer
    followed are dropped.

    The companies asked least lately are asked first. When one cannot be read (a rate
    limit, a network gone, a page that is not a feed), nothing more is asked this time, what
    was read is kept, and the store says why under PARTLY (28 Sep 2026: a failure halfway
    lost every company's stories read before it, so a limit met at the same place every
    half hour would have kept any from being stored).

    `skip_within` (a timedelta) leaves a company alone that this source asked about more recently
    than that and whose stories are kept; `ask` is the companies that may be asked this time, the
    others left as they are (the update asks the ones whose names are known first, and the rest once
    the filings have named them). Companies not followed any more are dropped whatever either says."""
    stored = stored or {}
    today = now.date()
    oldest = (today - timedelta(days=KEEP_DAYS)).isoformat()
    had = stored.get("companies") or {}
    fetched = {v: _fetched(stored, v) for v in SOURCES}
    asked = {v: _asked(stored, v) for v in SOURCES}
    wanted = list(dict.fromkeys(str(t).upper() for t in tickers or []))
    companies = {t: had[t] for t in (wanted if prune else had) if t in had}
    if prune:
        fetched = {v: {t: d for t, d in days.items() if t in wanted} for v, days in fetched.items()}
        asked = {v: {t: m for t, m in stamps.items() if t in wanted} for v, stamps in asked.items()}
    allowed = None if ask is None else {str(t).upper() for t in ask}

    def recent(ticker):
        when = moment(asked[via].get(ticker))
        return bool(skip_within and when and ticker in had and now - when < skip_within)
    failed = None
    for ticker in sorted(wanted, key=lambda t: asked[via].get(t) or fetched[via].get(t) or ""):
        filed = (names or {}).get(ticker)
        last = fetched[via].get(ticker)
        since = max(oldest, last) if last and ticker in had else oldest
        items = {i["id"]: dict(i, via=i.get("via", "finnhub")) for i in had.get(ticker) or []}
        if failed is None and (allowed is None or ticker in allowed) and not recent(ticker):
            try:
                for item in fresh_for(ticker, since, filed):
                    items[item["id"]] = dict(item, via=via)
                fetched[via][ticker] = today.isoformat()
                asked[via][ticker] = now.isoformat(timespec="seconds")
            except (PressError, earnings.EarningsError) as e:
                failed = str(e)
        keep = [i for i in items.values() if i["at"][:10] >= oldest and about(i, ticker, filed)]
        by_source = {v: sorted((i for i in keep if i["via"] == v), key=lambda i: i["at"],
                               reverse=True)[:KEPT] for v in SOURCES}
        companies[ticker] = sorted((i for v in SOURCES for i in by_source[v]), key=lambda i: i["at"], reverse=True)
    out = {"companies": companies, "fetched": fetched, "asked": asked, "source": "; ".join(SOURCES.values()),
           "updated_at": now.isoformat(timespec="seconds")}
    if failed:
        out[PARTLY] = failed
    return out


def merge_company(stored, fresh, ticker):
    """`stored` with one company's stories and the days each source last asked for them taken
    from `fresh`, an update run for it alone (prune=False), the other companies' as they were.
    Made twice, it changes nothing more."""
    out = dict(stored or {})
    ticker = str(ticker).upper()
    if ticker in ((fresh or {}).get("companies") or {}):
        out["companies"] = dict(out.get("companies") or {}, **{ticker: fresh["companies"][ticker]})
    fetched = {v: _fetched(out, v) for v in SOURCES}
    asked = {v: _asked(out, v) for v in SOURCES}
    for v in SOURCES:
        day, stamp = _fetched(fresh, v).get(ticker), _asked(fresh, v).get(ticker)
        if day:
            fetched[v][ticker] = day
        if stamp:
            asked[v][ticker] = stamp
    out["fetched"] = fetched
    out["asked"] = asked
    for key in ("source", "updated_at"):
        if key not in out and (fresh or {}).get(key):
            out[key] = fresh[key]
    return out


def update(tickers, stored=None, key=None, fetch=earnings.fetch, now=None, prune=True, names=None, skip_within=None,
           ask=None):
    """Finnhub's stories for each company, merged with those kept. A company is asked only
    for what came since the day it was last asked (that day included: a story can arrive
    late on it), and for a month the first time. With prune=False (one company followed
    at once) the other companies' stories are kept as they are. `names` is {ticker: filed
    name}, to tell which stories are about the company."""
    key = key or earnings.api_key()
    now = now or datetime.now(timezone.utc)
    return _merge(stored, "finnhub", tickers,
                  lambda t, since, filed: fetch_company(t, since, now.date().isoformat(), key, fetch=fetch),
                  now, prune, names, skip_within, ask)


def update_press(tickers, stored=None, names=None, fetch=fetch_rss, now=None, prune=True, sleep=time.sleep,
                 skip_within=None, ask=None):
    """The press's stories for each company, merged with those kept: searched over the days
    since the day it was last searched (that day included), and a month the first time."""
    now = now or datetime.now(timezone.utc)
    today = now.date()

    def fresh(ticker, since, filed):
        days = max(1, min(KEEP_DAYS, (today - date.fromisoformat(since)).days + 1))
        return fetch_press(ticker, filed, days, fetch=fetch, sleep=sleep)
    return _merge(stored, "press", tickers, fresh, now, prune, names, skip_within, ask)


def load(path=None):
    try:
        with open(path or HEADLINES_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def filed_names(path=None):
    """{ticker: the name its filings give} from the filings store, to tell which stories
    are about each company."""
    try:
        with open(path or NEWS_FILE) as f:
            return (json.load(f) or {}).get("companies") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def main(argv):
    tickers = [a.upper() for a in argv if not a.startswith("-")] or load_watchlist()
    if not tickers:
        print("Follow a company first: python3 news.py --follow NVDA", file=sys.stderr)
        return 2
    names, data, failed = filed_names(), load(), []
    for step in (lambda d: update(tickers, stored=d, prune=not argv, names=names),
                 lambda d: update_press(tickers, stored=d, prune=not argv, names=names)):
        try:
            data = step(data)
        except (earnings.EarningsError, PressError) as e:
            failed.append(str(e))
        if data.get(PARTLY):
            failed.append(data.pop(PARTLY))
    atomic_write_json(HEADLINES_FILE, data)
    for ticker in tickers:
        items = (data.get("companies") or {}).get(ticker) or []
        press = sum(1 for i in items if i.get("via") == "press")
        print(f"{ticker}: {len(items)} stories about it in the last {KEEP_DAYS} days "
              f"({len(items) - press} from Finnhub, {press} from the press)")
        for i in items[:5]:
            print(f"  {i['at'][:16].replace('T', ' ')}  {i['headline']}  ({i['source'] or 'no source'})")
    for why in failed:
        print(why, file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
