"""A trade checked before it is placed: the facts about it, in one place, from what the desk
already holds. Nothing to write and nothing sent.

Given a ticker, buy or sell, and an amount in the account's currency:

  - what the holding would be, and its share of the account, before and after
  - its industry's share of the account, before and after (the SEC's code for the company)
  - the desk's rating and its place, or why it has none
  - when the company next reports, and the days till then
  - its price to earnings against its own five years, and its year against the market
  - what the user's own trades have paid in fees, as a share of their value, and what that
    comes to on this amount
  - the dividend it would pay at its yield, and the share of the user's dividends that has
    been withheld as tax

Each is a plain fact from the stores; nothing here is a judgement of the trade, and the
check never proposes, places or records an order.
"""
import statistics

import rating as rating_mod
import sectors
import value

RECENT_TRADES = 20      # the user's latest trades whose fees are read: a presentation limit


def fee_rate(trades, side):
    """The median of the user's latest trades' fees, as a share of each trade's value, on
    the same side; with how many were read. (None, 0) with none on record."""
    rows = [r for r in trades or [] if r.get("side") == side and (r.get("value") or 0) > 0][:RECENT_TRADES]
    if not rows:
        return None, 0
    return statistics.median((r.get("fees") or 0.0) / r["value"] for r in rows), len(rows)


def withheld_rate(costs, dividends):
    """The share of the user's dividends withheld as tax: withheld over withheld and received.
    None with no dividend on record."""
    withheld, received = (costs or {}).get("withheld") or 0.0, (dividends or {}).get("total") or 0.0
    return withheld / (withheld + received) if withheld + received > 0 else None


def check(ticker, side, amount, data, card=None, ratings=None, store=None, codes=None, price=None, split=1.0):
    """The facts about buying or selling `amount` of `ticker`. `data` is the built page's
    data (desk_data.json); `card` its company card when the company is covered; `ratings`
    rating.rate_all's answer, for a company that is not; `store` and `codes` the universe of
    SEC filers and their industry codes; `price` the last close when the desk has one and the
    company is not covered."""
    ticker, side = str(ticker or "").strip().upper(), str(side or "BUY").upper()
    amount = float(amount or 0)
    account = data.get("account") or {}
    total = account.get("total") or 0.0
    rows = (data.get("positions") or {}).get("rows") or []
    holding = next((r for r in rows if r.get("ticker") == ticker and r.get("us_line")), None)
    # a line held outside the US under this short ticker, and none in the US: it is that line the
    # user means, and the US company of the same letters is someone else (else checking a London
    # ETF would read "not held" and show a US company's rating)
    abroad = None if holding else next((r for r in rows if r.get("ticker") == ticker and not r.get("us_line")), None)
    if abroad:
        holding, card, ratings, store, price = abroad, None, None, None, None
    held = (holding or {}).get("value") or 0.0
    signed = amount if side == "BUY" else -min(amount, held)
    # a purchase is paid from cash and a sale adds to it, so the account's total is the same after
    after = held + signed
    out = {"ticker": ticker, "side": side, "amount": amount, "currency": account.get("currency"),
           "covered": card is not None, "outside_us": bool(abroad), "name": (card or {}).get("name") or
           ((store or {}).get("companies") or {}).get(ticker, {}).get("name") or (abroad or {}).get("name"),
           "held_before": held, "held_after": after,
           "weight_before": held / total if total else None, "weight_after": after / total if total else None,
           "cash": account.get("cash"), "over_cash": side == "BUY" and amount > (account.get("cash") or 0.0),
           "over_held": side == "SELL" and amount > held}
    # the industry: the SEC's code for the company, as build_exposure groups the account
    row = ((store or {}).get("companies") or {}).get(ticker) or {}
    group = sectors.major_group((codes or {}).get(row.get("cik"))) if row else None
    exposure = data.get("exposure") or {}
    whole = exposure.get("whole") or 0.0
    if group and whole:
        now = next((g["value"] for g in exposure.get("groups") or [] if g.get("label") == group), 0.0)
        out["industry"] = {"label": group, "before": now / whole, "after": (now + signed) / whole}
    # the desk's rating: the card's, or placed from the whole universe's
    r = (rating_mod.for_page({}, ticker, us_line=False) if abroad else
         (card or {}).get("rating") or (rating_mod.for_page(ratings, ticker) if ratings else None))
    out["rating"] = {k: r.get(k) for k in ("label", "place", "rated_among", "breakpoints", "why_not")} if r else None
    if card:
        nxt = card.get("next_earnings") or {}
        out["results"] = {"date": nxt.get("date"), "days": card.get("days_to_earnings"), "when": nxt.get("when")} if nxt else None
        pe = card.get("pe_history") or {}
        out["pe"] = {"place": pe.get("place"), "years": pe.get("years")} if pe.get("place") is not None else None
        out["year_vs_market"] = (card.get("price") or {}).get("year_vs_market")
        valuation = ((card.get("context") or {}).get("valuation")) or {}
        out["price"] = (card.get("price") or {}).get("close")
    else:
        valuation = value.value_company(row, price, split) if row and price else {}
        out["price"] = price
    # the user's own costs, as their record shows them
    rate, read = fee_rate((data.get("trades") or {}).get("rows"), side)
    out["fees"] = {"rate": rate, "trades": read, "amount": rate * amount if rate is not None else None}
    dividend_yield = valuation.get("dividend_yield")
    withheld = withheld_rate(data.get("costs"), data.get("dividends"))
    if side == "BUY" and dividend_yield:
        yearly = amount * dividend_yield
        out["dividend"] = {"yield": dividend_yield, "yearly": yearly, "withheld_rate": withheld,
                           "withheld": yearly * withheld if withheld is not None else None}
    return out
