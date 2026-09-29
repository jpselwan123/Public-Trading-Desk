"""The desk's rating — Buy, Hold or Sell — for a US company in the stored universe.

The desk gives its own rating (since 25 Sep 2026). It does so the way it
does everything else — from published research, with every part of the verdict shown,
and with its own record kept and scored against the market.

How a rating is made (definition 2026-09-28b; docs/RATING.md)
  The rating follows the most accurate studies there are. The two most thorough re-tests of the published findings are Hou, Xue & Zhang
  (2020), who re-ran 452 with the NYSE's breakpoints and size weights and found 65% fail,
  and Jensen, Kelly & Pedersen (2023), who found most of 153 do replicate, fall into
  thirteen themes, and that ten of those themes carry significant weight in the best
  combination of all of them; profitability, investment and size do not, once the others
  are held. The rating uses the four of those ten the desk's data measures well, each
  through measures that also held in Hou, Xue & Zhang:

    Value      book to market     higher is better   Fama & French (1992), at the latest
                                                     price (Asness & Frazzini 2013)
               share count change lower is better    Pontiff & Woodgate (2008)
    Momentum   the year to the month before last     Jegadeesh & Titman (1993)
    Quality    gross profit to assets                Novy-Marx (2013)
    Accruals   earnings less operating cash flow     Sloan (1996)

  Book to market and momentum need a share price. Momentum is the return from the end of
  the month thirteen months back to the end of the month two back: the year before last
  month, which is left out because a single month's move tends to reverse (Jegadeesh 1990).
  Value and momentum tend to pull against each other, which is why they are used together
  (Asness, Moskowitz & Pedersen 2013). Share issuance sits in the value theme, where Jensen,
  Kelly & Pedersen place it; the share count is the weighted average the latest annual
  report gives, which restates the year before for a split.

  Left out, and why (LEFT_OUT, shown on the page): asset growth and the Piotroski F-score,
  whose themes are displaced in Jensen, Kelly & Pedersen's combination (the F-score's own
  evidence is also weakest among large companies weighted by size); and low risk, where
  the careful re-tests disagree (Hou, Xue & Zhang 2020; Novy-Marx & Velikov 2022).

  A price is the one input with a budget: Tiingo's free key prices a few hundred
  companies a month, not the NYSE's thousands. So the desk prices a fixed random sample
  of SAMPLE_SIZE NYSE companies, drawn once and never changed (draw_sample), and places
  every company's value and momentum against that sample: an estimate of the NYSE's
  breakpoints. The sample is also the rating's fair record: companies nobody chose, rated
  and scored. A company with no price is rated on the filing measures, and so is every
  company until three in four of the sample are priced (SAMPLE_READY): the sample is priced
  a few dozen an hour, and placed against the first handful the two would mean little.

  Every non-financial US company listed on an exchange, with at least MIN_THEMES of the
  themes, is placed on each measure (0 to 100, ties half: sectors.ranked) against the
  NYSE-listed companies — the breakpoints the papers and their re-tests use, so that
  thousands of tiny companies do not crowd the ends (Fama & French 2008; Hou, Xue & Zhang
  2020). Over-the-counter shares are not rated: the papers studied exchange-listed ones.
  Each place is read the way its paper found. A theme's place is its measures' average, and
  the themes are averaged with equal weights: the plainest combination, with no weight
  fitted to the desk's own data, and one score across the themes rather than a mix of
  separate picks, which Fitzgibbons, Friedman, Pomorski & Serban (2017) found does better
  for a long-only investor. The average is placed once more against the NYSE companies
  resting on the same number of themes: an average of three swings further than one of
  four. The top third is Buy, the bottom third Sell, the middle third Hold: the thirds
  Jensen, Kelly & Pedersen build every factor from.

  Without the SEC's exchange list (universe.listings, fetched with the company data), every filer is
  the breakpoint group, as before 26 Sep 2026, and the page says so.

What a rating is not
  A forecast for one company. The papers measured average differences between large
  portfolios held for months. Published effects shrink: McLean & Pontiff (2016) found
  them 26% smaller out of sample and 58% smaller after publication. Banks, insurers and
  property companies are not rated: the measures were built on industrial companies, and
  the revenue they tag leaves out interest income. Funds file no operating accounts and
  are not rated either.

Its own record
  There is no backtest of this rating. The SEC frames data it ranks on is restated and
  undated, so a backtest would use figures nobody had at the time. Instead, each rating
  given to a company the user covers or holds is logged on the day it is first given or
  changes (`log`, ratings_log.json, entries added and never edited), with the latest
  close, and scored against the market 3, 6 and 12 months on from the first close after
  that day (`record`).

The rating never proposes or places an order: the desk has no way to place one.
"""
import json, math, os, random
from datetime import date, datetime, timedelta, timezone

import prices as price_store
import screen
import sectors
import uncertainty
import value as value_mod
from env_config import atomic_write_json

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "ratings_log.json")

# The themes the rating averages, each with equal weight (Jensen, Kelly & Pedersen 2023: the
# published findings that replicate fall into thirteen themes, and ten carry significant weight
# in the best combination of all of them; these four are the ones among the ten the desk's data
# measures well). Its measures, each a finding that also replicates on its own (Hou, Xue &
# Zhang 2020), which way is better, the paper that found it, and the theme Jensen, Kelly &
# Pedersen place it in.
THEME_SOURCE = "Jensen, Kelly & Pedersen (2023), Is there a replication crisis in finance?"
THEMES = ("Value", "Momentum", "Quality", "Accruals")
FACTORS = (
    # the two that need a price: placed against the priced sample alone (see above)
    {"name": "book_to_market", "theme": "Value", "better": "higher", "needs_price": True,
     "source": "Fama & French (1992), The cross-section of expected stock returns; at the latest price, "
               "as Asness & Frazzini (2013), The devil in HML's details, found works better"},
    {"name": "shares_change", "theme": "Value", "better": "lower",
     "source": "Pontiff & Woodgate (2008), Share issuance and cross-sectional returns"},
    {"name": "momentum", "theme": "Momentum", "better": "higher", "needs_price": True,
     "source": "Jegadeesh & Titman (1993), Returns to buying winners and selling losers"},
    {"name": "gross_profitability", "theme": "Quality", "better": "higher",
     "source": "Novy-Marx (2013), The other side of value: the gross profitability premium"},
    {"name": "accruals", "theme": "Accruals", "better": "lower",
     "source": "Sloan (1996), Do stock prices fully reflect information in accruals and cash flows?"},
)
# Measured on the card, but no longer part of the rating (2026-09-28b), and why: their themes add
# nothing significant once the others are held (Jensen, Kelly & Pedersen 2023).
LEFT_OUT = (
    {"name": "Asset growth", "theme": "Investment",
     "why": "the investment theme is displaced by the others in Jensen, Kelly & Pedersen's (2023) best "
            "combination of the thirteen themes"},
    {"name": "Piotroski F-score", "theme": "Profitability",
     "why": "the profitability theme is displaced by the others in Jensen, Kelly & Pedersen's (2023) best "
            "combination, and the F-score's own evidence is weakest among large companies weighted by size"},
    {"name": "Low risk (beta, volatility)", "theme": "Low risk",
     "why": "the careful re-tests disagree: 96% of the trading-friction findings, where volatility and beta "
            "sit, failed in Hou, Xue & Zhang (2020), and Novy-Marx & Velikov (2022) traced betting against "
            "beta's returns to effectively equal-weighting the smallest companies"},
)
PRICED = tuple(f["name"] for f in FACTORS if f.get("needs_price"))
MOMENTUM_MONTHS = (13, 2)       # from the end of the month 13 back to the end of the month 2 back
MONTH_END_SLACK = 7             # days a month-end close may fall before the month's end (weekends, holidays)
# The fixed sample (the desk's choices): 200 companies estimates a third's breakpoint to
# about three places in a hundred (3.3, one standard error), and with the desk's own prices stays inside Tiingo's
# few hundred symbols a month. The seed is the day it was set; the draw is kept, never redone.
SAMPLE_SIZE = 200
SAMPLE_SEED = 20260927
SAMPLE_FILE = "rating_sample.json"
# A measure that needs a price is placed only once this share of the sample has it (the desk's
# choice, 28 Sep 2026). The sample is priced a few dozen companies an hour: placed against the
# first two or ten, value and momentum swung each company's rating on a handful of others. At
# three in four of 200, 150, a third's breakpoint is off by about 3.8 places in a hundred (one
# standard error, against 3.3 at 200), and a sample thinned by companies delisted since it was
# drawn still counts.
SAMPLE_READY = 0.75


def ready_at(size):
    """How many of a sample of `size` must have a measure before anyone is placed on it."""
    return max(2, math.ceil(SAMPLE_READY * size))
# The desk's choice: a rating resting on fewer than three of the four themes says more about
# what is missing than about the company.
MIN_THEMES = 3
# The top and bottom third, as Jensen, Kelly & Pedersen (2023) build every factor: the return
# of the top third of companies on a measure against the bottom third's.
BUY_FROM, SELL_BELOW = 200 / 3, 100 / 3
LABELS = ("Buy", "Hold", "Sell")
RECENT = 8                  # the latest ratings logged, listed with the record: a presentation limit
# Trading days after the rating at which it is scored, and how the page says each.
HORIZONS = ((63, "3 months"), (126, "6 months"), (252, "12 months"))
RATING_DISPLAY = {"book_to_market": {"kind": "ratio", "label": "Book to market", "dp": 2},
                  "momentum": {"kind": "percent", "label": "Momentum (a year, the latest month left out)", "dp": 1}}
# Why a company has no rating, in words the page shows as they are.
WHY_NOT = {
    "financial": "banks, insurers and property companies are not rated: the measures were "
                 "built on industrial companies, and the revenue they tag leaves out interest income",
    "misfiled": "its filings carry a figure on the wrong scale, so no measure built on them is used",
    "too_few": f"fewer than {MIN_THEMES} of the rating's {len(THEMES)} themes can be read from its filings and price",
    "not_us": "this line trades outside the US, and the rating ranks the shares of US filers only",
    "otc": "it trades over the counter or on no exchange, and the papers the rating rests on studied "
           "shares listed on the NYSE, AMEX and Nasdaq",
    "absent": "it is not in the stored universe of SEC filers: a fund, a company listed outside the "
              "US, or one the last universe build did not include",
    "no_universe": "no universe of SEC filers is stored for this day, and the rating ranks a company "
                   "against it (python3 universe.py builds it)",
    "no_codes": "no industry codes are stored, so banks, insurers and blank-check companies cannot be set "
                "apart from the companies they would distort (python3 sectors.py builds them)",
}
# What a rating is not, said beside every one.
LIMITS = ("A rating ranks a company on four themes of published findings about groups of "
          "companies, each measured as the average difference between large portfolios held for "
          "months. It is not a forecast for this one company. Published effects shrink: McLean & "
          "Pontiff (2016) found them 26% smaller out of sample and 58% smaller after publication. "
          "When Hou, Xue & Zhang (2020) re-tested 452 published anomalies with the NYSE's "
          "breakpoints and size weights, 65% failed; each measure here is among those that held. "
          "Momentum has had sudden deep losses when a falling market turned (Daniel & Moskowitz "
          "2016), and the value premium has been smaller since 1991 than before (Fama & French "
          "2021). The rating has no backtest: the figures it ranks on are restated and undated, so "
          "its own record starts on the day it was first given.")
_memo = {}


def values(row, price=None, closes=None, today=None, split=1.0):
    """The measures for one company, None where its filings or its price do not give one.
    `split` restates the filed share count in the price's shares (value.splits_since)."""
    m = screen.measures(row)
    return {"book_to_market": book_to_market(row, price, split),
            "shares_change": m.get("shares_change"),
            "momentum": momentum(closes, today),
            "gross_profitability": m.get("gross_profitability"),
            "accruals": m.get("accruals")}


def themes_read(v):
    """The themes a company's measures (values(), or their places) give at least one of."""
    return {f["theme"] for f in FACTORS if v.get(f["name"]) is not None}


def book_to_market(row, price, split=1.0):
    """Book equity over market value, as Fama & French (1992) sort on it: the inverse of
    value.py's price to book, so its share-basis check applies (a figure it withholds is
    None here too). A company with negative book equity has none, as in the paper."""
    if price is None:
        return None
    to_book = value_mod.value_company(row, price, split).get("price_to_book")
    return 1.0 / to_book if to_book and to_book > 0 else None


def month_end(day, back):
    """The last day of the month `back` months before `day`'s."""
    y, m = divmod(day.year * 12 + day.month - 1 - back + 1, 12)
    return date(y, m + 1, 1) - timedelta(days=1)


def momentum(closes, today):
    """The return from the last close of the month MOMENTUM_MONTHS[0] back to the last
    close of the month MOMENTUM_MONTHS[1] back, from adjusted closes; None without both
    (a close more than MONTH_END_SLACK days before its month's end is not that month's)."""
    if not closes or today is None:
        return None
    days = sorted(closes)

    def at(end):
        before = [d for d in days if d <= end.isoformat()]
        if not before or before[-1] < (end - timedelta(days=MONTH_END_SLACK)).isoformat():
            return None
        return closes[before[-1]]
    start, end = at(month_end(today, MOMENTUM_MONTHS[0])), at(month_end(today, MOMENTUM_MONTHS[1]))
    return end / start - 1 if start and end else None


def label_for(place):
    return "Buy" if place >= BUY_FROM else "Sell" if place < SELL_BELOW else "Hold"


# The rating's definition, dated. A change of definition changes what a label means, so
# the record scores only ratings given under the definition in force; earlier ones stay
# in the log, unedited, and are counted apart.
#   2026-09-25  ranked among every SEC filer, averages ranked all together
#   2026-09-26  NYSE breakpoints, over-the-counter shares left out, each average placed
#               among those resting on as many measures
#   2026-09-27  seven measures: value and momentum added, placed against a fixed random
#               sample of NYSE companies, which is also logged and scored (the user:
#               "build everything you suggested")
#   2026-09-28  value and momentum placed only once three in four of the sample have them
#               (SAMPLE_READY); before, against however many were priced, two or more
#   2026-09-28b the measures grouped into Jensen, Kelly & Pedersen's (2023) themes and the four
#               themes averaged with equal weights; asset growth and the F-score left out,
#               their themes displaced in that paper; cut into thirds, as it builds every
#               factor
METHOD = "2026-09-28b"
FIRST_METHOD = "2026-09-25"         # entries logged before methods were recorded
BREAKPOINT_EXCHANGE = "NYSE"
UNLISTED = ("", "OTC")


def rate_all(store, codes=None, listings=None, prices=None, sample=None, today=None):
    """Every rateable company's rating, and why the others have none. `listings` is the
    SEC's exchange list (universe.load_listings); `prices` the stored closes and `sample`
    the fixed sample (load_sample), for the two measures that need a price. Ranking the
    whole universe takes seconds, and the page is rebuilt on every note and practice
    trade, so the answer is kept until an input changes."""
    companies = (store or {}).get("companies") or {}
    exchanges = {str(k).upper(): str(v or "").upper() for k, v in ((listings or {}).get("exchanges") or {}).items()}
    if companies and not codes:
        # every place is relative to the others: with financials unmarked, all would move
        return {"rated": 0, "codes_known": False, "companies": {}, "why_not": {}, "missing": "no_codes",
                "not_rated": {}, "built": (store or {}).get("built")}
    today = today or datetime.now(timezone.utc).date()
    sampled = frozenset(str(t).upper() for t in (sample or {}).get("tickers") or [])
    priced = {t: price_store.series(prices, t) for t in price_store.tickers(prices) if t in companies}
    key = ((store or {}).get("built"), len(companies), len(codes or {}),
           round(sum(((r.get("assets") or [0])[0] or 0) for r in companies.values()), 2),
           len(exchanges), sum(1 for x in exchanges.values() if x == BREAKPOINT_EXCHANGE),
           sampled, today.strftime("%Y-%m"),
           tuple(sorted((t, max(v), v[max(v)]) for t, v in priced.items() if v)))
    if key[0] and key in _memo:
        return _memo[key]
    raw = {t: price_store.series(prices, t, "c") for t in priced}
    out = _rate(companies, codes, exchanges,
                {t: (raw[t][max(raw[t])] if raw[t] else None, priced[t],
                     value_mod.splits_since(companies[t], prices, t, max(raw[t]) if raw[t] else None,
                                            (store or {}).get("built")))
                 for t in priced}, sampled, today)
    out["built"] = (store or {}).get("built")
    if key[0]:
        _memo.clear()
        _memo[key] = out
    return out


def _rate(companies, codes, exchanges=None, priced=None, sampled=frozenset(), today=None):
    exchanges, priced = exchanges or {}, priced or {}
    financial = {cik for cik, sic in (codes or {}).items() if sectors.division(sic) == sectors.FINANCIAL}
    measured, why_not = {}, {}
    for ticker, row in companies.items():
        if row.get("cik") in financial:
            why_not[ticker] = "financial"
        elif exchanges and exchanges.get(ticker, "") in UNLISTED:
            why_not[ticker] = "otc"
        elif screen.scale_fault(row):
            why_not[ticker] = "misfiled"
        else:
            price, closes, split = priced.get(ticker, (None, None, 1.0))
            v = values(row, price, closes, today, split)
            if len(themes_read(v)) >= MIN_THEMES:
                measured[ticker] = v
            else:
                why_not[ticker] = "too_few"
    # the breakpoint group: the NYSE's companies, or with no exchange list every filer;
    # for a measure that needs a price, only the fixed sample's, since the others priced
    # are the user's choices and would lean the breakpoints their way
    base = {t for t in measured if exchanges.get(t) == BREAKPOINT_EXCHANGE}
    breakpoints = BREAKPOINT_EXCHANGE if len(base) >= 2 else "all"
    if breakpoints == "all":
        base = set(measured)
    places, placed = {}, {}
    for factor in FACTORS:
        group = (base & sampled) if factor.get("needs_price") else base
        known = [v[factor["name"]] for t, v in measured.items() if t in group]
        placed[factor["name"]] = sum(x is not None for x in known)
        if factor.get("needs_price") and placed[factor["name"]] < ready_at(len(sampled)):
            known = []                              # too few of the sample priced yet: nobody is placed on it
        place = sectors.ranked(known)
        flip = factor["better"] == "lower"
        for ticker, v in measured.items():
            p = place(v[factor["name"]])
            places.setdefault(ticker, {})[factor["name"]] = None if p is None else (100.0 - p if flip else p)
    # a company whose value or momentum was placed, and is not in the sample, is one the
    # user chose: it is rated, but sets no breakpoint for the averages
    fair = {t for t in base if t in sampled or all(places[t][p] is None for p in PRICED)}
    # each theme's place is its measures' average; the rating's average is the themes', each
    # with equal weight, so Value's two measures count once between them
    averages, counts, by_theme = {}, {}, {}
    for ticker, ps in places.items():
        themes = {}
        for f in FACTORS:                                   # a measure too few report cannot place anyone
            if ps[f["name"]] is not None:
                themes.setdefault(f["theme"], []).append(ps[f["name"]])
        if len(themes) >= MIN_THEMES:
            by_theme[ticker] = {t: sum(v) / len(v) for t, v in themes.items()}
            averages[ticker] = sum(by_theme[ticker].values()) / len(themes)
            counts[ticker] = len(themes)
        else:
            why_not[ticker] = "too_few"
    # each average against the breakpoint companies resting on as many themes as it does
    # (the sample's alone, where a price measure is among them); a group smaller than
    # sectors.MIN_PEERS says more about the group than the company, so then against all
    groups = {}
    for ticker, k in counts.items():
        if ticker in fair:
            groups.setdefault(k, []).append(averages[ticker])
    everyone = [a for values in groups.values() for a in values]
    overall = {k: (sectors.ranked(values), len(values)) for k, values in groups.items()
               if len(values) >= sectors.MIN_PEERS}
    fallback = (sectors.ranked(everyone), len(everyone))
    rated = {}
    for ticker, average in averages.items():
        place_of, among = overall.get(counts[ticker], fallback)
        place = place_of(average)
        if place is None:                                     # alone in its group: no place
            why_not[ticker] = "too_few"
            continue
        rated[ticker] = {"label": label_for(place), "place": place, "average": average,
                         "measures": counts[ticker], "among": among, "sampled": ticker in sampled,
                         "themes": by_theme[ticker],
                         "factors": {f["name"]: {"value": measured[ticker][f["name"]],
                                                 "place": places[ticker][f["name"]]} for f in FACTORS}}
    in_sample = [t for t in sampled if t in measured]
    return {"rated": len(rated), "codes_known": bool(codes), "companies": rated, "why_not": why_not,
            "breakpoints": breakpoints,
            "sample": {"size": len(sampled), "priced": sum(1 for t in in_sample
                                                           if any(measured[t][p] is not None for p in PRICED)),
                       "placed": {p: placed[p] for p in PRICED}},
            "not_rated": {k: sum(1 for w in why_not.values() if w == k) for k in ("financial", "otc", "misfiled", "too_few")}}


def draw_sample(store, codes, listings, size=SAMPLE_SIZE, seed=SAMPLE_SEED, now=None):
    """The fixed sample, drawn once: SAMPLE_SIZE of the NYSE-listed companies the rating
    could rate on their filings, at random with a fixed seed, from the list in ticker
    order. None without the universe, the industry codes or the exchange list."""
    companies = (store or {}).get("companies") or {}
    exchanges = {str(k).upper(): str(v or "").upper() for k, v in ((listings or {}).get("exchanges") or {}).items()}
    if not companies or not codes or not exchanges:
        return None
    financial = {cik for cik, sic in codes.items() if sectors.division(sic) == sectors.FINANCIAL}
    eligible = sorted(t for t, row in companies.items()
                      if exchanges.get(t) == BREAKPOINT_EXCHANGE and row.get("cik") not in financial
                      and not screen.scale_fault(row)
                      and len(themes_read(values(row))) >= MIN_THEMES)
    if not eligible:
        return None
    return {"tickers": sorted(random.Random(seed).sample(eligible, min(size, len(eligible)))),
            "drawn_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "seed": seed, "size": size, "eligible": len(eligible),
            "universe_built": (store or {}).get("built"), "exchange_list": (listings or {}).get("updated_at")}


def load_sample(folder):
    try:
        with open(os.path.join(folder, SAMPLE_FILE)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("tickers"), list) else {}
    except (OSError, ValueError):
        return {}


def keep_sample(folder, store, codes, listings):
    """The sample as drawn the first time, never redrawn: returned as stored, or drawn and
    written now if there is none yet (and the inputs to draw it exist)."""
    stored = load_sample(folder)
    if stored.get("tickers"):
        return stored
    drawn = draw_sample(store, codes, listings)
    if drawn:
        atomic_write_json(os.path.join(folder, SAMPLE_FILE), drawn, indent=1)
    return drawn or {}


def for_page(ratings, ticker, us_line=True):
    """One company's rating as the page shows it, or why it has none. A holding listed
    outside the US is never matched by its short ticker: London's lines can share one
    with an unrelated US company."""
    if not us_line:
        return {"label": None, "why_not": WHY_NOT["not_us"]}
    ticker = str(ticker or "").upper()
    r = (ratings.get("companies") or {}).get(ticker)
    if r:
        return dict(r, rated_among=r.get("among"), breakpoints=ratings.get("breakpoints"))
    if not ratings.get("rated"):
        return {"label": None, "why_not": WHY_NOT[ratings.get("missing") or "no_universe"]}
    return {"label": None, "why_not": WHY_NOT[(ratings.get("why_not") or {}).get(ticker, "absent")]}


PLACE_MIDDLE = 50.0         # a place runs 0 to 100 among the companies ranked; this is the middle of them


def tilt(rows, total):
    """Where the account leans on the rating's four themes: for each, the places of the rated companies held
    (each company's average over that theme's measures, 0 to 100) averaged by what is held in each, with how many
    companies it rests on and how much of the account they are. A fact about what is held, not a signal:
    a fund holds many companies and the desk does not see inside it, and a company listed outside the US has
    no rating, so both are left out and their share of the account is what `share` leaves unsaid.
    {"themes", "held", "rated", "share", "middle"}, or {"why": ...}."""
    if not total or total <= 0:
        return {"why": "the account's value is not known"}
    rated = [r for r in rows or [] if (r.get("rating") or {}).get("themes") and (r.get("value") or 0) > 0]
    if not rated:
        return {"why": "none of the companies held is rated: the rating covers US-listed companies, "
                       "so a fund or a share listed elsewhere has none"}
    themes = []
    for theme in THEMES:
        have = [r for r in rated if r["rating"]["themes"].get(theme) is not None]
        weight = sum(r["value"] for r in have)
        themes.append({"theme": theme, "companies": len(have), "share": weight / total,
                       "place": sum(r["value"] * r["rating"]["themes"][theme] for r in have) / weight if weight else None})
    return {"themes": themes, "held": len(rows), "rated": len(rated),
            "share": sum(r["value"] for r in rated) / total, "middle": PLACE_MIDDLE}


def explained(ratings):
    """What the page needs to say how any rating was made: the factors, the cut-offs,
    the count it was ranked among — each once, from here."""
    return {"factors": [dict(f, label=(RATING_DISPLAY.get(f["name"]) or screen.MEASURE_DISPLAY[f["name"]])["label"])
                        for f in FACTORS],
            "themes": list(THEMES), "theme_source": THEME_SOURCE, "left_out": list(LEFT_OUT),
            "buy_from": BUY_FROM, "sell_below": SELL_BELOW, "min_themes": MIN_THEMES,
            "rated": ratings.get("rated"), "not_rated": ratings.get("not_rated"),
            "breakpoints": ratings.get("breakpoints"),
            "built": ratings.get("built"), "codes_known": ratings.get("codes_known"),
            "why_none": None if ratings.get("rated") else WHY_NOT[ratings.get("missing") or "no_universe"],
            "limits": LIMITS}


def buy_list(ratings, store, codes):
    """The companies rated Buy, highest place first: the rating's top third, as a list to look
    through. Each with its name, its industry (the SEC's code),
    its place and how many of the measures it rests on. What the papers measured is how such
    a group did on average, held for a year: not how any one company will."""
    companies = (store or {}).get("companies") or {}
    import universe
    out = []
    for ticker, r in (ratings.get("companies") or {}).items():
        if r.get("label") != "Buy":
            continue
        row = companies.get(ticker) or {}
        out.append({"ticker": ticker, "name": universe.display_name(row.get("name")) or ticker,
                    "industry": sectors.major_group((codes or {}).get(row.get("cik"))),
                    "place": round(r["place"], 1), "measures": r.get("measures"), "sampled": r.get("sampled", False)})
    return sorted(out, key=lambda x: (-x["place"], x["ticker"]))


def sample_for_page(ratings, sample):
    """The fixed sample as the page names it: how many, how many priced so far, when drawn, how
    many it takes before value and momentum are placed, whether they are, and how many companies
    Tiingo's free key prices in an hour while the desk is open."""
    tickers = (sample or {}).get("tickers") or []
    got = (ratings or {}).get("sample") or {}
    return {"size": len(tickers), "priced": got.get("priced", 0), "drawn_at": (sample or {}).get("drawn_at"),
            "ready_at": ready_at(len(tickers)),
            "ready": all(n >= ready_at(len(tickers)) for n in (got.get("placed") or {0: 0}).values()),
            "per_hour": price_store.TIINGO_PER_HOUR - price_store.SPARE} if tickers else None


def exchange_list(listings):
    """Which day's exchange list set the breakpoints, and how many tickers it holds; None
    without one."""
    exchanges = (listings or {}).get("exchanges") or {}
    return {"updated_at": (listings or {}).get("updated_at"), "tickers": len(exchanges)} if exchanges else None


# ---- the record: each rating logged when given, scored when time has passed ----------
def load_log(path=None):
    try:
        with open(path or LOG_FILE) as f:
            entries = json.load(f)
        return [e for e in entries if isinstance(e, dict) and e.get("ticker")] if isinstance(entries, list) else []
    except (OSError, ValueError):
        return []


def load_log_for_writing(path):
    """The log, read before entries are added. One that is there but cannot be read raises
    env_config.UnreadableStore: it is added to and never edited, so never written over."""
    from env_config import read_for_writing, UnreadableStore
    entries = read_for_writing(path, list, [])
    if not all(isinstance(e, dict) for e in entries):
        raise UnreadableStore(f"{os.path.basename(path)} cannot be read, so nothing was written over it.")
    return entries


def log(entries, ratings, tickers, prices, today, now=None, sample=None):
    """The log with an entry added for each of `tickers` whose rating is new or has
    changed since its last entry under the definition in force (METHOD). Nothing already
    logged is edited or removed. An entry carries the latest close on or before today,
    the price it is scored from, the definition that gave it, and whether the company is
    in the fixed sample (`sample`, load_sample), whose record is the fair one."""
    sampled = {str(t).upper() for t in (sample or {}).get("tickers") or []}
    entries = list(entries or [])
    last = {e["ticker"]: e for e in entries if e.get("method", FIRST_METHOD) == METHOD}
    for ticker in dict.fromkeys(t.upper() for t in tickers or []):
        r = (ratings.get("companies") or {}).get(ticker)
        if not r or (last.get(ticker) or {}).get("label") == r["label"]:
            continue
        series = price_store.series(prices, ticker)
        days = sorted(d for d in series if d <= today.isoformat())
        if not days:
            continue                                  # no close to score it from
        entry = {"ticker": ticker, "date": today.isoformat(),
                 "at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "label": r["label"],
                 "place": round(r["place"], 1), "close_day": days[-1], "close": series[days[-1]],
                 "universe_built": ratings.get("built"), "method": METHOD,
                 "breakpoints": ratings.get("breakpoints"), "sample": ticker in sampled}
        entries.append(entry)
        last[ticker] = entry
    return entries


def _after(series, day, steps):
    """The return from the first close on or after `day` to the close `steps` trading
    days later, or None when that day has not come."""
    days = sorted(series)
    start = next((i for i, d in enumerate(days) if d >= day), None)
    if start is None or start + steps >= len(days) or not series[days[start]]:
        return None
    return series[days[start + steps]] / series[days[start]] - 1


def _day_after(day):
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def record(entries, prices, group=None):
    """For each label and horizon: how many ratings beat the market over it, with the
    exact interval, and the median lead or lag, with its interval. The nine records are
    shown side by side, so all take one level (uncertainty.family_level).

    `group` "sample" scores the fixed sample's ratings alone — companies nobody chose,
    so the fair test of the rating; "yours" the others, the companies the user covers
    or holds; None every one.

    A rating is scored from the first close after the day it was given, never the close
    before: a filing the universe took in that morning moves that day's price, and the
    rating would be credited with the move that made it.

    Only ratings given under the definition in force are scored (METHOD)."""
    if group:
        entries = [e for e in entries or [] if bool(e.get("sample")) == (group == "sample")]
    earlier = [e for e in entries or [] if e.get("method", FIRST_METHOD) != METHOD]
    entries = [e for e in entries or [] if e.get("method", FIRST_METHOD) == METHOD]
    market = price_store.series(prices, price_store.BENCHMARK)
    scored = {(label, h): [] for label in LABELS for h, _ in HORIZONS}
    for e in entries or []:
        own = price_store.series(prices, e["ticker"])
        start = _day_after(e["date"])
        for h, _ in HORIZONS:
            mine, theirs = _after(own, start, h), _after(market, start, h)
            if mine is not None and theirs is not None and e.get("label") in LABELS:
                scored[(e["label"], h)].append(mine - theirs)
    counted = {key: (sum(1 for x in xs if x > 0), len(xs)) for key, xs in scored.items() if xs}
    level = uncertainty.family_level([uncertainty.sign_test_p(k, n) for k, n in counted.values()])
    out = []
    for label in LABELS:
        for h, after in HORIZONS:
            xs = scored[(label, h)]
            k, n = counted.get((label, h), (0, 0))
            out.append({"label": label, "days": h, "after": after, "n": n,
                        "beat": uncertainty.against_chance(k, n, confidence=level) if n else None,
                        "lead": uncertainty.median(xs, confidence=level, expected=0) if n else None})
    return {"rows": out, "level": uncertainty.level_text(level), "logged": len(entries or []),
            "earlier": len(earlier),
            "first": min((e["date"] for e in entries or []), default=None),
            # the latest given, newest first: what was said, when, and at what price
            "recent": [{k: e.get(k) for k in ("ticker", "date", "label", "close")}
                       for e in sorted(entries or [], key=lambda e: e.get("date") or "", reverse=True)[:RECENT]]}


def main(argv):
    """python3 rating.py [TICKER ...]: how the rated companies split, against which group,
    and each covered company's place on each measure — the rating's parts, plainly."""
    import news, universe
    sample = load_sample(HERE)
    ratings = rate_all(universe.load(), sectors.load(), universe.load_listings(), price_store.load(), sample)
    if not ratings.get("rated"):
        print("Nothing rated: " + WHY_NOT[ratings.get("missing") or "no_universe"])
        return 2
    labels = [c["label"] for c in ratings["companies"].values()]
    against = "NYSE-listed companies" if ratings.get("breakpoints") == BREAKPOINT_EXCHANGE else \
        "every US filer (no exchange list yet: it comes with the next company update)"
    print(f"{ratings['rated']} companies rated, placed against {against}: "
          + ", ".join(f"{label} {labels.count(label)}" for label in LABELS))
    s = ratings.get("sample") or {}
    print(f"The fixed sample: {s.get('priced', 0)} of {s.get('size', 0)} priced so far"
          + ("" if s.get("size") else " (drawn with the next company update)"))
    for ticker in [t.upper() for t in argv] or news.load_watchlist():
        r = for_page(ratings, ticker)
        if not r.get("label"):
            print(f"{ticker}: not rated: {r['why_not']}")
            continue
        parts = ", ".join(f"{f['name'].replace('_', ' ')} "
                          + ("–" if r["factors"][f["name"]]["place"] is None else f"{r['factors'][f['name']]['place']:.0f}")
                          for f in FACTORS)
        print(f"{ticker}: {r['label']}, place {r['place']:.0f} of 100 among {r['among']} ({parts})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
