"""Which broker the account comes from, and the one record every broker's sync writes.

The desk was built on Trading 212 and stays so. With BROKER unset, or `trading212`, in .env,
the sync is t212.py's, run exactly as before: nothing here stands between them. Any other
broker has an adapter that reads its own source and writes the record Trading 212's sync writes
(t212_data.json, in Trading 212's shape: summary, positions, orders with their fills,
dividends, transactions), so every figure on the page is worked out by one code path,
whichever broker it came from:

    BROKER=trading212   Trading 212's API (t212.py)                       the default
    BROKER=alpaca       Alpaca's trading API, read only (broker_alpaca)
    BROKER=ibkr         Interactive Brokers' Flex reports (broker_ibkr)
    BROKER=csv          a CSV of the account's history, from any broker (broker_csv)

The desk reads only: it never places, changes or cancels an order at any broker.

What another broker does not state, the desk works out when the page is built (`complete`),
as Trading 212 would state it: each sale's closed gain against the average cost of the
holding, in the account's currency, a split counted (Trading 212's own convention); and, for
an export that carries no holdings or totals, the holdings from the trades and their value
at the latest close. Such a record is marked `derived`, and checks.py does not set the desk's
figures beside themselves as if they were the broker's.

Usage: python3 broker.py            sync the account from the broker .env names
       python3 broker.py --check    ask the broker once, and say what answered
"""
import json, os, sys
from datetime import datetime, timezone

from env_config import atomic_write_json, load_env

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "t212_data.json")     # the account record, whichever broker it came from
DEFAULT = "trading212"
BROKERS = {
    "trading212": {"name": "Trading 212", "module": None,
                   "keys": ("T212_API_KEY", "T212_API_SECRET"),
                   "connect": ("In the Trading 212 app: Settings → API (Beta) → Generate API key.",
                               "Tick Account data, Portfolio and every History option. Leave Orders unticked, "
                               "so the key cannot trade.",
                               "Add `T212_API_KEY` and `T212_API_SECRET` to `.env`.",
                               "Press the round sync button above.")},
    "alpaca": {"name": "Alpaca", "module": "broker_alpaca",
               "keys": ("ALPACA_API_KEY", "ALPACA_API_SECRET"),
               "connect": ("In Alpaca's dashboard, generate an API key pair (switch to Paper first for a "
                           "paper account).",
                           "Add `BROKER=alpaca`, `ALPACA_API_KEY` and `ALPACA_API_SECRET` to `.env`, and "
                           "`ALPACA_ENV=paper` for a paper account.",
                           "Alpaca's keys can place orders, so keep `.env` private: the desk only reads with it.",
                           "Press the round sync button above.")},
    "ibkr": {"name": "Interactive Brokers", "module": "broker_ibkr",
             "keys": ("IBKR_FLEX_TOKEN", "IBKR_FLEX_QUERY"),
             "connect": ("In IBKR's Client Portal, Performance & Reports → Flex Queries: create an Activity "
                         "Flex Query with Account Information, Open Positions, Trades, Cash Transactions, Cash "
                         "Report and Net Asset Value in Base, for the last 365 days.",
                         "Under Flex Web Service Configuration, turn the service on and generate a token. It "
                         "reads reports only.",
                         "Add `BROKER=ibkr`, `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY` (the query's number) "
                         "to `.env`.",
                         "Press the round sync button above.")},
    "csv": {"name": "your broker", "module": "broker_csv",
            "keys": ("BROKER_CSV",),
            "connect": ("Download your account's whole history from your broker as a CSV, every year of it.",
                        "Arrange its columns as docs/BROKERS.md shows, or rename its headers to the names "
                        "listed there.",
                        "Save it as `account.csv` in the desk's folder (or name it in `BROKER_CSV`), and add "
                        "`BROKER=csv` and `BROKER_CURRENCY` (the account's currency) to `.env`.",
                        "Press the round sync button above to read it.")},
}
ALIASES = {"t212": "trading212", "trading_212": "trading212", "ib": "ibkr", "interactivebrokers": "ibkr",
           "interactive_brokers": "ibkr", "export": "csv"}
# The kinds of cash movement an adapter writes, as Trading 212 names them; ADJUSTMENT is the
# desk's own for a movement that is neither money put in nor a fee (a fee refunded, a tax
# reclaimed): counted in the cash as it comes, never as a deposit (history._cash_moves).
CASH_KINDS = ("DEPOSIT", "WITHDRAW", "FEE", "TRANSFER", "INTEREST_ON_FREE_CASH", "ADJUSTMENT")
US_SUFFIX = "_US_EQ"


class BrokerError(Exception):
    pass


def current(environ=None):
    """The broker .env names (BROKER), Trading 212 when it names none."""
    if environ is None:
        load_env(os.path.join(HERE, ".env"))
        environ = os.environ
    key = str(environ.get("BROKER") or "").strip().lower().replace(" ", "").replace("-", "_") or DEFAULT
    key = ALIASES.get(key, key)
    if key not in BROKERS:
        raise BrokerError(f"BROKER={environ.get('BROKER')} is not one the desk reads: "
                          + ", ".join(BROKERS) + " (docs/BROKERS.md)")
    return key


def of(raw):
    """Which broker a stored record came from; Trading 212's records say none."""
    key = (raw or {}).get("broker") or DEFAULT
    return key if key in BROKERS else DEFAULT


def name_of(raw):
    """The name the page gives the broker a record came from: an export's own, if .env gave one."""
    key = of(raw)
    return (raw or {}).get("broker_name") or BROKERS[key]["name"]


def configured():
    """The broker .env names, or Trading 212 (and why) when it names one the desk does not read."""
    try:
        return current(), None
    except BrokerError as e:
        return DEFAULT, str(e)


def for_page(raw, key=None, problem=None):
    """What the page says about the broker: the one the account came from, or before any sync
    the one .env names; its name, whether orders go to it, how to connect it."""
    if (raw or {}).get("summary"):
        key = of(raw)
    key = key if key in BROKERS else DEFAULT
    return {"key": key, "name": name_of(raw) if (raw or {}).get("summary") else BROKERS[key]["name"],
            "states_gains": key == DEFAULT,
            "connect": list(BROKERS[key]["connect"]), "derived": bool((raw or {}).get("derived")),
            "valued_at_cost": list((raw or {}).get("valued_at_cost") or []), "problem": problem}


def line_code(symbol, market="US"):
    """The desk's code for a line, as Trading 212 writes it: a US listing SYMBOL_US_EQ, any other
    SYMBOL_MARKET_EQ. A class letter joins with a hyphen, as the SEC and Tiingo write it (BRK.B →
    BRK-B), so the short ticker is the SEC's. Only a US line is rated, priced or placed as a filer."""
    symbol = str(symbol or "").strip().upper().replace(".", "-").replace("/", "-").replace(" ", "-")
    market = str(market or "US").strip().upper()
    if not symbol:
        raise BrokerError("a trade or holding with no symbol")
    return symbol + (US_SUFFIX if market in US_MARKETS else "_" + market.replace("_", "") + "_EQ")


# How brokers name the US exchanges a line trades on; any of them is a US line.
US_MARKETS = {"US", "USA", "NYSE", "NASDAQ", "NMS", "ARCA", "NYSEARCA", "AMEX", "NYSEAMERICAN", "BATS", "CBOE",
              "IEX", "ISLAND", "SMART", "BYX", "BZX", "PINK", "OTC", "NYSEMKT", "NASDAQGS", "NASDAQGM", "NASDAQCM"}


class Record:
    """The account record in Trading 212's shape, built one event at a time by an adapter.
    Amounts named in the account's currency are in it; a price is in its line's own."""

    def __init__(self, broker, currency, env="live", broker_name=None):
        if broker not in BROKERS or broker == DEFAULT:
            raise BrokerError(f"no adapter writes records for {broker}")
        if not currency:
            raise BrokerError(f"{BROKERS[broker]['name']} did not say the account's currency")
        self.currency = str(currency).upper()
        self.out = {"broker": broker, "env": env, "summary": {"currency": self.currency},
                    "positions": [], "orders": [], "dividends": [], "transactions": []}
        if broker_name:
            self.out["broker_name"] = broker_name

    def trade(self, ref, when, code, side, quantity, price, net_value, price_currency=None, name=None, fees=()):
        """A fill: `net_value` the money it moved, in the account's currency, fees in (paid on a
        purchase, less on a sale); `fees` [(name, amount in the account's currency)]."""
        side, qty = str(side).upper(), abs(float(quantity))
        if side not in ("BUY", "SELL"):
            raise BrokerError(f"a trade's side must be buy or sell, not {side}")
        if not qty:
            return
        instrument = {"ticker": code, "name": name or code.split("_")[0], "currency": price_currency or ""}
        self.out["orders"].append({
            "order": {"id": str(ref), "ticker": code, "side": side, "status": "FILLED", "createdAt": when,
                      "instrument": instrument},
            "fill": {"id": str(ref), "filledAt": when, "quantity": qty if side == "BUY" else -qty,
                     "price": abs(float(price)), "type": "TRADE",
                     "walletImpact": {"currency": self.currency, "netValue": abs(float(net_value)),
                                      "realisedProfitLoss": None,
                                      "taxes": [{"name": n, "quantity": abs(float(a))} for n, a in fees if a]}}})

    def cash(self, ref, when, kind, amount):
        if kind not in CASH_KINDS:
            raise BrokerError(f"a cash movement of an unknown kind ({kind})")
        self.out["transactions"].append({"type": kind, "amount": float(amount), "currency": self.currency,
                                         "dateTime": when, "reference": str(ref)})

    def dividend(self, ref, when, code, amount, gross=None):
        """A dividend: `amount` what reached the account, tax withheld out of it; `gross` what was
        declared before the tax, both in the account's currency (build_costs reads the tax as
        their difference)."""
        row = {"ticker": code, "amount": float(amount), "paidOn": when, "reference": str(ref),
               "instrument": {"ticker": code}}
        if gross is not None:
            row["grossAmount"] = float(gross)
        self.out["dividends"].append(row)

    def position(self, code, quantity, price, value, cost=None, price_currency=None, name=None, average=None):
        """A holding as the broker states it: `value` and `cost` in the account's currency."""
        if not quantity:
            return
        row = {"instrument": {"ticker": code, "name": name or code.split("_")[0], "currency": price_currency or ""},
               "quantity": float(quantity), "currentPrice": float(price or 0.0),
               "averagePricePaid": float(average or 0.0),
               "walletImpact": {"currency": self.currency, "currentValue": float(value),
                                "totalCost": float(cost) if cost is not None else None,
                                "unrealizedProfitLoss": (float(value) - float(cost)) if cost is not None else None,
                                "fxImpact": None}}
        self.out["positions"].append(row)

    def finish(self, cash=None, total=None, derived=False, existing=None):
        """The record: the broker's cash and total when it states them; with `derived`, holdings
        and totals are worked out from the history when the page is built. Earlier history kept
        in `existing` is merged in by reference, the new first (a report that reaches back a
        year keeps what earlier syncs read)."""
        out = self.out
        if derived:
            out["derived"] = True
        else:
            values = [p["walletImpact"]["currentValue"] for p in out["positions"]]
            costs = [p["walletImpact"]["totalCost"] for p in out["positions"]]
            invested = sum(values)
            cost = sum(costs) if costs and None not in costs else None
            out["summary"].update({
                "cash": {"availableToTrade": float(cash or 0.0), "inPies": 0.0, "reservedForOrders": 0.0},
                "investments": {"currentValue": invested, "totalCost": cost,
                                "unrealizedProfitLoss": invested - cost if cost is not None else None,
                                "realizedProfitLoss": None},
                "totalValue": float(total) if total is not None else float(cash or 0.0) + invested})
        if existing and of(existing) == out["broker"]:
            for name, key in (("orders", lambda i: i["order"]["id"]), ("dividends", lambda i: i.get("reference")),
                              ("transactions", lambda i: i.get("reference"))):
                seen = {key(i) for i in out[name]}
                out[name] += [i for i in existing.get(name) or [] if key(i) not in seen]
        for name, stamp in (("orders", lambda i: i["fill"]["filledAt"]), ("dividends", lambda i: i["paidOn"]),
                            ("transactions", lambda i: i["dateTime"])):
            out[name].sort(key=stamp, reverse=True)                        # newest first, as Trading 212's
        out["previous_synced_at"] = (existing or {}).get("synced_at")
        out["synced_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return out


# ---- what another broker does not state, worked out when the page is built -----------------
def complete(raw, prices, today):
    """The record with every closed gain, and a derived record's holdings and totals, filled in.
    A Trading 212 record is returned as it is: Trading 212 states all of these itself."""
    raw = raw or {}
    if of(raw) == DEFAULT or not raw.get("summary"):
        return raw
    import prices as price_store
    raw = json.loads(json.dumps(raw))                         # the stored record is never changed
    splits = price_store.SplitsRead(prices or {})
    held = _closed_gains(raw, splits)
    if raw.get("derived"):
        _holdings(raw, held, prices or {}, splits, today)
    else:
        _costs(raw, held, splits, today)
    return raw


def _costs(raw, held, splits, today):
    """Each holding's cost, as Trading 212 states it: the average cost of the shares held, in the
    account's currency at the rates of the days they were bought, fees in (a broker's own cost
    basis is first in, first out, or at today's rate)."""
    import build_desk
    total = 0.0
    for p in raw.get("positions") or []:
        code = (p.get("instrument") or {}).get("ticker") or ""
        if code not in held:
            continue
        cost = held[code][1]
        wallet = p.setdefault("walletImpact", {})
        wallet["totalCost"] = cost
        wallet["unrealizedProfitLoss"] = build_desk.num(wallet.get("currentValue")) - cost
        total += cost
    investments = raw["summary"].setdefault("investments", {})
    if all((p.get("instrument") or {}).get("ticker") in held for p in raw.get("positions") or []):
        investments["totalCost"] = total
        investments["unrealizedProfitLoss"] = build_desk.num(investments.get("currentValue")) - total


def _fills_in_order(raw):
    """The trades' fills, oldest first; two in one second by their order's id (build_desk._trade_order)."""
    import build_desk
    items = [i for i in raw.get("orders") or [] if (i.get("fill") or {}).get("type", "TRADE") == "TRADE"]
    return sorted(items, key=lambda i: build_desk._trade_order({"time": i["fill"].get("filledAt"),
                                                                "id": (i.get("order") or {}).get("id")}))


def _closed_gains(raw, splits):
    """Each sale's closed gain against the average cost of the holding, in the account's
    currency, fees in, a US line's splits counted; the sum as the account's closed gain.
    {code: (shares, cost, last day, last value a share)} left held."""
    import build_desk
    held, total = {}, 0.0
    for item in _fills_in_order(raw):
        order, fill = item["order"], item["fill"]
        code, day = order.get("ticker") or "", build_desk.day_of(fill.get("filledAt"))
        qty, value = abs(build_desk.num(fill.get("quantity"))), abs(build_desk.num((fill.get("walletImpact") or {}).get("netValue")))
        shares, cost, last = held.get(code, (0.0, 0.0, day))
        if code.endswith(US_SUFFIX) and shares:
            shares *= splits.factor(build_desk.short_ticker(code), last, day)
        wallet = fill.setdefault("walletImpact", {})
        if order.get("side") == "SELL" or build_desk.num(fill.get("quantity")) < 0:
            average = cost / shares if shares > 1e-9 else 0.0
            sold = min(qty, shares)
            gain = value - average * sold if shares > 1e-9 else 0.0
            wallet["realisedProfitLoss"] = gain
            total += gain
            shares, cost = shares - sold, cost - average * sold
            if shares <= 1e-9:
                shares, cost = 0.0, 0.0
        else:
            wallet["realisedProfitLoss"] = 0.0
            shares, cost = shares + qty, cost + value
        held[code] = (shares, cost, day)
    raw["summary"].setdefault("investments", {})["realizedProfitLoss"] = total
    return held


def _holdings(raw, held, prices, splits, today):
    """A derived record's holdings and totals: the shares left from the trades, a US line at its
    latest close within history.CLOSE_SLACK_DAYS (the account's currency through that session's
    rate), a line with no such close at its average cost, and says so (`valued_at_cost`); the
    cash from every movement of money."""
    import build_desk, history
    import prices as price_store
    from datetime import timedelta
    currency = raw["summary"]["currency"]
    fx = price_store.fx_rates(prices, currency) if currency != "USD" else None
    earliest = (today - timedelta(days=history.CLOSE_SLACK_DAYS)).isoformat()
    positions, stale = [], []
    for code, (shares, cost, last) in sorted(held.items()):
        if code.endswith(US_SUFFIX):
            shares *= splits.factor(build_desk.short_ticker(code), last, today.isoformat())
        if shares <= history.HELD_AT_LEAST:
            continue
        short, value, price = build_desk.short_ticker(code), None, None
        if code.endswith(US_SUFFIX):
            closes = price_store.series(prices, short, "c")
            on = max((d for d in closes if d <= today.isoformat()), default=None)
            if on and on >= earliest:
                rate = 1.0 if fx is None else build_desk._on_or_before(fx, on)
                if rate:
                    price, value = closes[on], shares * closes[on] / rate
        if value is None:                               # no close the desk can use: at cost, said so
            value = cost
            stale.append(short)
        positions.append({"instrument": {"ticker": code, "name": short,
                                         "currency": "USD" if code.endswith(US_SUFFIX) else ""},
                          "quantity": shares, "currentPrice": price or 0.0,
                          "averagePricePaid": 0.0,
                          "walletImpact": {"currency": currency, "currentValue": value, "totalCost": cost,
                                           "unrealizedProfitLoss": value - cost, "fxImpact": None}})
    moves, _ = history._cash_moves(raw.get("transactions"), raw.get("dividends"), history._fills(raw.get("orders")))
    cash = sum(a for d, a in moves if d <= today.isoformat())
    invested = sum(p["walletImpact"]["currentValue"] for p in positions)
    cost = sum(p["walletImpact"]["totalCost"] for p in positions)
    raw["positions"] = positions
    raw["summary"].update({"cash": {"availableToTrade": cash, "inPies": 0.0, "reservedForOrders": 0.0},
                           "investments": dict(raw["summary"].get("investments") or {}, currentValue=invested,
                                               totalCost=cost, unrealizedProfitLoss=invested - cost),
                           "totalValue": cash + invested})
    raw["valued_at_cost"] = sorted(stale)


# ---- the sync ------------------------------------------------------------------------------
def adapter(key):
    import importlib
    module = BROKERS[key]["module"]
    return importlib.import_module(module) if module else None


def sync_to_file(path=None):
    """Sync the account from the broker .env names into the record. Trading 212's is t212.py's,
    as it always was. Raises BrokerError (or t212.T212Error) with what went wrong, in words."""
    key = current()
    if key == DEFAULT:
        import t212
        return t212.sync_to_file(path)
    path = path or DATA_FILE
    try:
        with open(path) as f:
            existing = json.load(f)
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict) or of(existing) != key:
        existing = {}                   # another broker's record, or none: start clean
    print(f"Syncing {BROKERS[key]['name']}…")
    data = adapter(key).sync(existing)
    atomic_write_json(path, data)
    os.chmod(path, 0o600)
    print(f"Saved {len(data.get('orders') or [])} trades" + ("" if data.get("derived") else
                                                               f", {len(data.get('positions') or [])} positions"))
    return data


def check():
    """Ask the broker once: (its name, what answered), for doctor.py and --check."""
    key = current()
    if key == DEFAULT:
        import t212
        k, s, env = t212.credentials()
        t212.Client(k, s, env).get("/equity/account/summary")
        return BROKERS[key]["name"], f"answered ({env})"
    return BROKERS[key]["name"], adapter(key).check()


def main(argv):
    try:
        if "--check" in argv:
            who, what = check()
            print(f"OK: {who} {what}")
            return 0
        if current() == DEFAULT:
            import t212
            return t212.main(argv)
        sync_to_file()
        return 0
    except BrokerError as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:                  # t212.T212Error and the like, said as they are
        print(str(e) or type(e).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
