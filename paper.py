"""Paper portfolio: practise with pretend money, scored against the market.

Trades fill at the last closing price this desk has, plus the same cost a real
Trading 212 trade pays (backtest.TRADE_COST), so results are not flattered. Prices are US dollars,
matching the price data, and this money is imaginary — the real account is never
touched.

The point is the record: after months of paper trades you can see whether your
decisions beat simply holding the market, before any real money is at risk.
"""
import json, os
from datetime import date, datetime, timezone

import backtest

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER_FILE = os.path.join(HERE, "paper.json")
START_CASH = 10000.0          # US dollars of pretend money
TRADE_COST = backtest.TRADE_COST   # one cost, owned by the backtests (was a second copy)
MAX_REASON = 500


class PaperError(Exception):
    pass


UNREADABLE = ("The practice book (paper.json) cannot be read, so it is left as it is: "
              "\u201cStart over\u201d begins a new one")


def readable(data):
    """Whether a stored book has the shape a trade reads: amounts that are numbers, holdings
    that are records of numbers, trades that are records, a start that is a day or none."""
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    return (isinstance(data, dict)
            and all(number(data[k]) for k in ("cash", "start_cash") if k in data)
            and isinstance(data.get("positions", {}), dict)
            and all(isinstance(p, dict) and number(p.get("quantity")) and number(p.get("cost"))
                    for p in data.get("positions", {}).values())
            and isinstance(data.get("trades", []), list)
            and all(isinstance(t, dict) for t in data.get("trades", []))
            and (data.get("started") is None or _is_day(data.get("started"))))


def _is_day(text):
    try:
        date.fromisoformat(str(text)[:10])
        return True
    except ValueError:
        return False


def load(path=None):
    """The practice book, or a new one when there is none. One that is there but cannot be
    read raises PaperError: a trade never writes over it, so nothing in it is lost unseen."""
    try:
        with open(path or PAPER_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError):
        raise PaperError(UNREADABLE) from None
    if not readable(data):
        raise PaperError(UNREADABLE)
    data.setdefault("cash", START_CASH)
    data.setdefault("start_cash", START_CASH)
    data.setdefault("positions", {})
    data.setdefault("trades", [])
    data.setdefault("started", None)
    return data


def save(data, path=None):
    from env_config import atomic_write_json
    atomic_write_json(path or PAPER_FILE, data, indent=1)


def last_close(prices, ticker):
    """The most recent printed close: what a real order would fill near."""
    import prices as price_store
    series = price_store.series(prices, ticker.upper(), "c")
    if not series:
        return None, None
    day = max(series)
    return series[day], day


def trade(data, prices, ticker, side, amount=None, quantity=None, reason="", today=None):
    """Buy or sell at the last close. `amount` is dollars to spend; `quantity` is
    shares. Selling more than you hold, or spending more than your cash, is refused."""
    ticker = (ticker or "").strip().upper()
    side = (side or "").strip().upper()
    if side not in ("BUY", "SELL"):
        raise PaperError("side must be BUY or SELL")
    price, price_day = last_close(prices, ticker)
    if not price:
        raise PaperError(f"No price for {ticker}: follow it, and its prices load at once")
    apply_splits(data, prices)                     # shares held, in today's shares
    held = (data["positions"].get(ticker) or {}).get("quantity", 0.0)

    if quantity is None:
        if not amount or amount <= 0:
            raise PaperError("Enter how much to trade")
        quantity = amount / price if side == "BUY" else min(held, amount / price)
    quantity = round(float(quantity), 6)
    if quantity <= 0:
        raise PaperError("That is too small to trade")

    value = quantity * price
    cost = value * TRADE_COST
    if side == "BUY" and value + cost > data["cash"] + 1e-9:
        raise PaperError(f"Not enough pretend cash: you have ${data['cash']:,.2f}")
    if side == "SELL" and quantity > held + 1e-9:
        raise PaperError(f"You only hold {held:g} shares of {ticker}")
    realised = apply(data, ticker, side, quantity, value, cost, day=price_day)

    now = datetime.now(timezone.utc)
    data["started"] = data["started"] or (today or now.date()).isoformat()
    data["trades"].insert(0, {
        "id": now.strftime("%Y%m%d%H%M%S%f"),
        "date": (today or now.date()).isoformat(),
        "price_day": price_day,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "value": value,
        "fee": cost,
        "realised": realised,
        "reason": str(reason or "").strip()[:MAX_REASON],
    })
    return data


def apply(data, ticker, side, quantity, value, cost, day=None):
    """What one filled trade does to the book: the one definition, used by a new trade
    and by replaying the recorded ones up to a past date (Phase 11). Returns the gain
    realised by a sale, None for a purchase. `day` is the close it filled at: the day a
    new holding's share count is stated on (apply_splits)."""
    if side == "BUY":
        pos = data["positions"].setdefault(ticker, {"quantity": 0.0, "cost": 0.0, "on": day})
        pos["quantity"] += quantity
        pos["cost"] += value + cost
        data["cash"] -= value + cost
        return None
    pos = data["positions"][ticker]
    average = pos["cost"] / pos["quantity"] if pos["quantity"] else 0.0
    realised = value - cost - average * quantity
    pos["cost"] -= average * quantity
    pos["quantity"] -= quantity
    if pos["quantity"] <= 1e-9:
        data["positions"].pop(ticker, None)
    data["cash"] += value - cost
    return realised


def replay(start_cash, trades, prices=None):
    """The book that `trades` make from `start_cash`, replayed oldest first. Which trades
    are replayed — those known by a past day — is asof.py's rule, not this one's. With `prices`,
    each holding is restated for the splits between trades, as trade() restates it before
    each: a trade's quantity is in the shares of its own day (28 Sep 2026: replayed, a sale of 10
    after a 10-for-1 split met a holding of 1)."""
    import prices as price_store
    book = {"cash": start_cash, "start_cash": start_cash, "positions": {}, "trades": [], "started": None}
    for t in sorted(trades, key=lambda t: (t["date"], t.get("id") or "")):
        day = t.get("price_day") or t["date"]
        for ticker, pos in book["positions"].items() if prices else ():
            if pos.get("on") and day > pos["on"]:
                pos["quantity"] *= price_store.split_factor(prices, ticker, pos["on"], day)
                pos["on"] = day
        apply(book, t["ticker"], t["side"], t["quantity"], t["value"], t["fee"], day=day)
        book["trades"].insert(0, t)
        book["started"] = book["started"] or t["date"]
    return book


def _opened(trades, ticker):
    """The day the holding now held was opened: the fill that took it from none to some,
    for a book from before holdings kept that day."""
    held, opened = 0.0, None
    for t in sorted((t for t in trades or [] if t.get("ticker") == ticker), key=lambda t: (t["date"], t.get("id") or "")):
        if t["side"] == "BUY" and held <= 1e-9:
            opened = t.get("price_day") or t["date"]
        held += t["quantity"] if t["side"] == "BUY" else -t["quantity"]
    return opened


def apply_splits(data, prices):
    """Each holding's shares restated for the splits since the day its count was stated
    (prices.split_factor): 1 share before a 10-for-1 split is 10 after it, at the same
    cost, so the price after it values the holding rightly (27 Sep 2026: it read as a 90%
    loss). Changes the book in place and returns it."""
    import prices as price_store
    for ticker, pos in (data.get("positions") or {}).items():
        closes = price_store.series(prices, ticker, "c")
        if not closes:
            continue
        on, last = pos.get("on") or _opened(data.get("trades"), ticker), max(closes)
        if on and last > on:
            pos["quantity"] *= price_store.split_factor(prices, ticker, on, last)
            pos["on"] = last
    return data


def reset(data=None):
    return {"cash": START_CASH, "start_cash": START_CASH, "positions": {}, "trades": [], "started": None}
