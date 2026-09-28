"""The desk as it was on a past date (fourth review, Phase 11).

Every stored input is cut to what was knowable at the end of the chosen day, and the
page is built from what is left, exactly as it is built today. The rule for each
store is here, in one place, with the date each observation became known:

  account     the balances and holdings are a snapshot taken at each sync, so one
              taken after the day is not shown; orders, dividends and cash movements
              are kept up to the day they happened
  journal     a note is kept if it was last written on or before the day
  filings     by the day the SEC received them, never the period they cover, and only
              for the companies covered that day
  prices      closes on or before the day
  quotes      the latest price taken at a refresh (pre-market, the session, after
              hours), kept only if it was taken on or before the day
  ratings     the desk's ratings are ranked from the universe, so they follow its
              rule; the log of ratings given keeps those given on or before the day
  financials  recomputed from the facts filed on or before the day — by filing date,
              not period end (a quarter ending in June is not known in June)
  earnings    a quarter's result is kept once that quarter's figures were filed; the
              next results date, a forecast made on the day of the last refresh, is not
  analysts    a snapshot taken after the day is not shown
  summaries   an AI summary written after the day is not shown
  briefs      likewise a week's news in brief
  practice    the recorded trades up to the day, replayed from the starting cash
  research    computed from price history running past the day: not shown
  universe    the SEC frames data carries no filing dates and holds restated
              figures, so it is shown only for days on or after it was built
  coverage    companies followed on or before the day, and those followed then and
              dropped since; one added before the desk kept follow dates cannot be
              placed, and is named on the page as not shown
  theses      written on or before the day, and scored only against quarters filed
              by then
  wording     a comparison whose newer 10-K was filed after the day is not shown

A figure with no observation on or before the day is left out, never replaced by
today's value: the page reads "not yet known". A record with no date, or one that
cannot be read, cannot be placed in time and is never shown for a past day (fifth
review, K-03). Every rule above decides with `known`, the one test of whether an
observation was knowable by the day. Nothing here writes; the as-of page is read-only.
"""
from datetime import date

import fundamentals
import paper

MATCH_DAYS = 7          # a data vendor's quarter end and the filing's can differ by days (AMD: 30 vs 27 June)


def _day(value):
    return str(value or "")[:10]


def dated(when):
    """Whether `when` names a real day, written YYYY-MM-DD (a timestamp is read by its
    day). Only that form compares correctly as text, so only it is accepted."""
    try:
        return date.fromisoformat(_day(when)).isoformat() == _day(when)
    except ValueError:
        return False


def known(when, day):
    """Whether an observation dated `when` was knowable at the end of `day`. With no
    date, or one that is not a date, it cannot be placed in time: never (K-03)."""
    return dated(when) and _day(when) <= day


def account(raw, day):
    """The account as the record held it at the end of `day`: its history to that day, and its
    holdings and totals only if they were synced by then. An export's are worked out from its
    history (broker.complete), so they are that day's own."""
    raw = dict(raw or {})
    if not known(raw.get("synced_at"), day) and not raw.get("derived"):
        raw.pop("summary", None)
        raw["positions"] = []
        raw["synced_at"] = None

    def when(order):
        return (order.get("fill") or {}).get("filledAt") or (order.get("order") or {}).get("createdAt")
    raw["orders"] = [o for o in raw.get("orders") or [] if known(when(o), day)]
    raw["dividends"] = [d for d in raw.get("dividends") or [] if known(d.get("paidOn"), day)]
    raw["transactions"] = [t for t in raw.get("transactions") or [] if known(t.get("dateTime"), day)]
    return raw


def journal(notes, day):
    return {oid: n for oid, n in (notes or {}).items() if known(n.get("updated"), day)}


def filings(news, day, tickers):
    news = dict(news or {})
    # a filing is the desk's on that day only if its company was covered then (S-33)
    news["items"] = [i for i in news.get("items") or [] if known(i.get("date"), day) and i.get("ticker") in tickers]
    news["tickers"] = [t for t in news.get("tickers") or [] if t in tickers]
    news["unknown"] = [t for t in news.get("unknown") or [] if t in tickers]
    news.pop("insiders", None)
    news["synced_at"] = None
    return news


def closes(prices, day):
    out = {}
    for key, value in (prices or {}).items():
        if isinstance(value, dict) and not key.startswith("_"):     # "_starts", "_slow_asked": bookkeeping
            out[key] = {d: v for d, v in value.items() if known(d, day)}
        else:
            out[key] = value
    out["updated_at"] = None
    return out


def company(stored, day, splits=None):
    """One company's figures as its filings stood at the end of `day`: every figure
    recomputed from the facts filed on or before it — by filing date, never period end.
    With `splits` (prices.splits), a per-share figure is in that day's shares."""
    stored = stored or {}
    facts = {name: [r for r in rows if known(r.get("filed"), day)]
             for name, rows in (stored.get("facts") or {}).items()}
    return fundamentals.derive(stored.get("ticker"), stored.get("cik"),
                               {n: r for n, r in facts.items() if r}, stored.get("tags") or {},
                               splits=splits, through=day)


def financials(funds, day, prices=None):
    """Each company's figures as filed by the end of `day`, a per-share figure in that day's
    shares (its splits from `prices`, the closes as they were: prices.splits)."""
    import prices as price_store
    funds = dict(funds or {})
    funds["companies"] = {t: company(c, day, price_store.splits(prices, t) if prices else None)
                          for t, c in (funds.get("companies") or {}).items()}
    funds["updated_at"] = None
    return funds


def earnings(earn, funds_then, day):
    """A quarter's result is known once its figures were filed. The vendor's quarter
    end is matched to the filing's within MATCH_DAYS; an unmatched quarter cannot be
    placed in time and is left out."""
    earn = dict(earn or {})
    companies = {}
    for ticker, record in (earn.get("companies") or {}).items():
        quarters = ((funds_then.get("companies") or {}).get(ticker) or {}).get("quarters") or []

        def filed(period):
            if not dated(period):
                return None                              # a quarter with no end cannot be matched
            for q in quarters:
                gap = abs((date.fromisoformat(q["end"]) - date.fromisoformat(_day(period))).days)
                if gap <= MATCH_DAYS and q.get("filed"):
                    return q["filed"]
            return None
        history = [h for h in record.get("history") or [] if known(filed(h.get("date")), day)]
        companies[ticker] = dict(record, history=history, next=None)
    earn["companies"], earn["updated_at"] = companies, None
    return earn


def analysts(rated, day):
    rated = dict(rated or {})
    rated["companies"] = {t: c for t, c in (rated.get("companies") or {}).items() if known(c.get("as_of"), day)}
    return rated


def summaries(written, day):
    return {t: s for t, s in (written or {}).items() if known(s.get("written_at"), day)}


def briefs(written, day):
    """A week's news in brief is known from when it was written."""
    return {t: b for t, b in (written or {}).items() if known((b or {}).get("written_at"), day)}


def practice(book, day, prices=None):
    """The practice book at the end of the day: its recorded trades up to it, replayed
    from the starting cash by paper.replay, the one definition of what a trade does, with the
    splits between them (`prices`, the closes known on the day)."""
    book = book or paper.reset()
    return paper.replay(book.get("start_cash", paper.START_CASH),
                        [t for t in book.get("trades") or [] if known(t.get("date"), day)], prices)


def research(results, day):
    return results if results and known(results.get("generated_at"), day) else {}


def universe(store, day):
    if store and known(store.get("built"), day):
        return store
    return {"companies": {}, "withheld": "not shown for a past date: the SEC's frames data carries no filing "
                                        "dates and holds figures restated since"}


def coverage(held, day):
    """The companies covered at the end of the day, and those followed today that
    cannot be placed in time (added before the desk kept follow dates): named so the
    page can say why they are missing, never shown as covered then."""
    held = held or {}
    records = held.get("coverage") or {}
    tickers = [t for t in held.get("tickers") or [] if known(records.get(t, {}).get("followed_at"), day)]
    undated = [t for t in held.get("tickers") or [] if not dated(records.get(t, {}).get("followed_at"))]
    for gone in held.get("past") or []:
        if known(gone.get("followed_at"), day) and dated(gone.get("stopped_at")) \
                and not known(gone.get("stopped_at"), day) and gone.get("ticker") not in tickers:
            tickers.append(gone["ticker"])
            records = dict(records, **{gone["ticker"]: {k: gone.get(k) for k in ("followed_at", "why")}})
    return {"tickers": tickers, "coverage": {t: records[t] for t in tickers if t in records}, "past": [],
            "undated": undated}


def theses(written, day):
    return [t for t in written or [] if known(t.get("written"), day)]


def wording(stored, day):
    stored = dict(stored or {})
    stored["companies"] = {t: c for t, c in (stored.get("companies") or {}).items()
                           if known((c.get("new") or {}).get("date"), day) and not c.get("why_not")}
    return stored


# Every store the page is built from, and its rule. A test seeds each with an
# observation dated after the day and checks none reaches the page.
STORES = ("raw", "journal", "news", "prices", "fundamentals", "earnings", "analysts", "summaries",
          "paper", "research", "universe", "coverage", "theses", "wording", "quotes",
          "ratings_log", "listings", "headlines", "health", "plans", "rating_sample", "looks", "briefs")


def headlines(stored, day, tickers):
    """Each headline known from when it was published, and only for a company covered
    on the day, as with its filings (S-33)."""
    stored = stored or {}
    return {"companies": {t: [i for i in items or [] if known((i or {}).get("at"), day)]
                          for t, items in (stored.get("companies") or {}).items() if t in tickers},
            "source": stored.get("source")}


def health(stored, day):
    """What each source did at the last update describes today's desk, not a past day's:
    a past page shows none of it, whatever its dates."""
    return {}


def plans(stored, day):
    """A plan is known from when it was written; its trade and its result follow from the
    account and the closes as they were on the day."""
    return {"plans": [p for p in (stored or {}).get("plans") or [] if known((p or {}).get("written"), day)]}


def quotes(stored, day):
    """The prices taken at a refresh, each kept only if taken on or before the day."""
    return {"quotes": {t: q for t, q in ((stored or {}).get("quotes") or {}).items()
                       if known((q or {}).get("at"), day)}}


def apply(inputs, day):
    """The inputs to build_desk.compute, as they were at the end of `day` (YYYY-MM-DD)."""
    held = coverage(inputs.get("coverage"), day)
    funds_then = financials(inputs.get("fundamentals"), day, closes(inputs.get("prices"), day))
    return {
        "raw": account(inputs.get("raw"), day),
        "journal": journal(inputs.get("journal"), day),
        "news": filings(inputs.get("news"), day, held["tickers"]),
        "headlines": headlines(inputs.get("headlines"), day, held["tickers"]),
        "health": health(inputs.get("health"), day),
        # when the user last looked is about today's desk: a past day has no "since you last looked"
        "looks": {},
        "plans": plans(inputs.get("plans"), day),
        # the rating's fixed sample: known from the day it was drawn
        "rating_sample": inputs.get("rating_sample") if known((inputs.get("rating_sample") or {}).get("drawn_at"), day)
                         else {},
        "prices": closes(inputs.get("prices"), day),
        "fundamentals": funds_then,
        "earnings": earnings(inputs.get("earnings"), funds_then, day),
        "analysts": analysts(inputs.get("analysts"), day),
        "summaries": summaries(inputs.get("summaries"), day),
        "briefs": briefs(inputs.get("briefs"), day),
        "paper": practice(inputs.get("paper"), day, closes(inputs.get("prices"), day)),
        "research": research(inputs.get("research"), day),
        "universe": universe(inputs.get("universe"), day),
        "coverage": held,
        "theses": theses(inputs.get("theses"), day),
        "broker": inputs.get("broker"),                  # which broker .env names: a setting, not a record
        "wording": wording(inputs.get("wording"), day),
        "quotes": quotes(inputs.get("quotes"), day),
        "ratings_log": [e for e in inputs.get("ratings_log") or [] if known((e or {}).get("date"), day)],
        # the exchange list as fetched: known from the day it was, like the universe it sorts
        "listings": inputs.get("listings") if known((inputs.get("listings") or {}).get("updated_at"), day) else {},
    }


def valid(day, today):
    """A past day the desk can be shown as of, or None: a real date, before today."""
    try:
        chosen = date.fromisoformat(str(day))
    except ValueError:
        return None
    return chosen.isoformat() if chosen < today else None

