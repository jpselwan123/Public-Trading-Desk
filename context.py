"""Everything the desk knows about one company, gathered into one place.

The screener, the scoring models, the peer groups, the valuation and the forecast
record were each usable only from a terminal. This assembles them onto the company
cards the page already builds, so a company can be read whole rather than in five
separate command-line calls.

It computes nothing of its own. Every figure here comes from the module that owns
it, which is the standing rule after the same quantity was worked out twice in two
files and the copies drifted apart. If a number looks wrong, there is exactly one
place it can be wrong.

No network. Prices come from the store the refresh already filled, so adding this
to a page build costs nothing and cannot spend the price budget.
"""
from datetime import date

import bridge
import forecasts
import scores
import screen
import sectors
import universe
import value

# The measures worth seeing against an industry rather than alone: a 51% gross
# margin is excellent for a grocer and poor for a software company.
AGAINST_PEERS = ("gross_margin", "operating_margin", "net_margin", "return_on_assets",
                 "debt_to_equity", "current_ratio", "revenue_growth_3y")

# Banks, insurers and property companies do not have the balance sheet these models
# read. A bank has no current ratio, no gross margin and no working capital in the
# industrial sense, so JPMorgan can compute only six of Piotroski's nine signals and
# scores two of them — which reads as a weak company when it means an inapplicable
# test. Altman states outright that his model is not for financial firms.
FINANCIAL = sectors.FINANCIAL         # the division's name, owned by sectors.py
# A bank's tagged revenue is its fee income: under ASC 606 revenue from contracts
# with customers leaves out interest, which is most of what a bank earns. Margins
# and revenue growth built on it are meaningless — the median net margin of
# JPMorgan's peers read 104.6%. Return on assets needs no revenue figure.
AGAINST_FINANCIAL_PEERS = ("return_on_assets",)
FINANCIAL_PEER_NOTE = ("Only return on assets is compared: the revenue a bank or insurer "
                       "tags leaves out interest income, so margins and revenue growth "
                       "built on it do not mean what they mean elsewhere.")
NOT_FOR_FINANCIALS = ("Both models were built for industrial companies. A bank or insurer "
                      "has no current ratio, gross margin or working capital in the sense "
                      "they read, so several signals cannot be computed and the ones that "
                      "can do not mean what they mean elsewhere. Read these as not "
                      "applicable, not as weak.")


def _price_now(prices, ticker, price_store):
    """The latest printed close and its day. series() returns {day: price}, not a list, and
    the printed close is the right one for a market capitalisation — the adjusted close
    is rebased for dividends and splits and is not what the shares trade at."""
    days = price_store.series(prices, ticker, "c")
    if not days:
        return None, None
    return days[max(days)], max(days)


def for_company(ticker, store=None, codes=None, groups=None, prices=None,
                price_store=None, earnings=None):
    """One company's filings, scores, peer standing, valuation and forecast record.

    Every part is optional: a company the SEC has no industry code for still gets
    its scores, and one with no stored price still gets everything but valuation.
    A missing part is absent rather than guessed at."""
    ticker = str(ticker or "").upper()
    companies = (store or {}).get("companies") or {}
    row = companies.get(ticker)
    if not row:
        return {"ticker": ticker,
                "why_not": (store or {}).get("withheld") or "not in the stored universe — run universe.py"}

    fault = screen.scale_fault(row)
    if fault:
        return {"ticker": ticker, "name": row.get("name"),
                "why_not": "this company " + fault["note"]}

    out = {"ticker": ticker, "name": row.get("name"), "why_not": None,
           "measures": screen.measures(row),
           "piotroski": scores.piotroski(row),
           "altman": scores.altman(row)}

    if codes:
        found = sectors.peers_for(ticker, companies, codes, groups)
        out["industry"] = {"sic": found.get("sic"), "division": found.get("division"),
                           "peers": len(found.get("peers") or []), "why": found.get("why"),
                           # the peers are compared on one filed year, which is not the
                           # trailing twelve months shown at the top of the card
                           "figures_from": universe.periods("flow", 1)[0],
                           "rank_below": sectors.RANK_BELOW}
        if found.get("division") == FINANCIAL:
            out["models_apply"] = False
            out["models_note"] = NOT_FOR_FINANCIALS
            if out["altman"] and out["altman"].get("score") is not None:
                out["altman"]["band"] = None
                out["altman"]["applies"] = False
                out["altman"]["why_not"] = ("Altman's model is not for financial firms, "
                                            "by his own account.")
        financial = found.get("division") == FINANCIAL
        if financial:
            out["industry"]["note"] = FINANCIAL_PEER_NOTE
        if len(found.get("peers") or []) >= sectors.MIN_PEERS:
            out["peer_standing"] = sectors.compare(
                ticker, screen.measures, companies, codes,
                measures=list(AGAINST_FINANCIAL_PEERS if financial else AGAINST_PEERS))["measures"]

    price, day = _price_now(prices, ticker, price_store) if (prices and price_store) else (None, None)
    if price is not None:
        out["valuation"] = value.value_company(
            row, price, value.splits_since(row, prices, ticker, day, (store or {}).get("built")))

    out["forecast_record"] = forecasts.for_company(ticker, earnings)["record"]
    return out


def for_screen(result, codes=None):
    """The sector of each company a screen returned, looked up from sectors.py — so a
    row can be read in context. Adds nothing computed: the division is the SEC's own
    label for the industry code the company files under."""
    codes = sectors.load() if codes is None else codes
    for hit in result.get("results") or []:
        hit["sector"] = sectors.division(codes.get(hit.get("cik")))
    return result


def add_to(cards, prices=None, price_store=None, earnings=None,
           store=None, codes=None, history=()):
    """Attach the context to each card build_desk already made. `history` names the
    measures whose filed years are drawn beside the card's figures.

    Loaded once for the whole page rather than per company: the universe is several
    megabytes and the peer groups are built by walking all of it."""
    cards = cards or []
    if not cards:
        return cards
    store = universe.load() if store is None else store
    codes = sectors.load() if codes is None else codes
    companies = store.get("companies") or {}
    groups = sectors.groups(companies, codes) if codes else None
    for card in cards:
        card["context"] = for_company(card.get("ticker"), store, codes, groups,
                                      prices, price_store, earnings)
        row = companies.get(str(card.get("ticker") or "").upper())
        if not row or card["context"].get("why_not"):
            continue
        financial = (card["context"].get("industry") or {}).get("division") == FINANCIAL
        # the years the universe was built for, not the years as of today
        built = str(store.get("built") or "")[:10]
        years = [y[2:] for y in reversed(universe.periods(
            "flow", store.get("years") or universe.DEFAULT_YEARS,
            today=date.fromisoformat(built) if built else None))]
        if history:
            # a bank's tagged revenue leaves out interest, so every line built on it is
            # left out, as its peer table leaves those measures out
            lines = screen.history(row, history, without=("revenue",) if financial else ())
            card["context"]["history"] = {"years": years[-len(lines[history[0]]):], "lines": lines}
        card["context"]["bridge"] = dict(bridge.for_company(row, financial), years=years[-2:])
    return cards
