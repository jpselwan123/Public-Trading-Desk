"""Synthetic account and market for the demo page, tests and screenshots.

Invented investor, invented prices (random walks), real Trading 212 response shapes. Nothing here
comes from a real account. The demo (`main`) also has invented companies, with invented filings,
figures, news and ratings: the desk's own pipeline run over a simulated market (tests/world.py), so
every screen has something on it. None of those companies exists, and none of the stories is a real
outlet's.

Usage: python3 scripts/generate_demo_data.py [outdir]     (default: demo/)
"""
import math, os, random, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
if HERE not in sys.path:               # the simulated market imports this file by name; the phone starts it with runpy
    sys.path.insert(1, HERE)
from env_config import atomic_write_json  # noqa: E402

SEED = 212
# ticker, name, start price, yearly drift, yearly volatility, dividend per share per quarter
UNIVERSE = [
    ("VOO_US_EQ", "Vanguard S&P 500 ETF", 380.0, 0.10, 0.16, 1.60),
    ("QQQ_US_EQ", "Invesco QQQ Trust", 330.0, 0.13, 0.22, 0.55),
    ("AAPL_US_EQ", "Apple", 165.0, 0.12, 0.27, 0.24),
    ("MSFT_US_EQ", "Microsoft", 290.0, 0.14, 0.25, 0.75),
    ("NVDA_US_EQ", "NVIDIA", 45.0, 0.45, 0.50, 0.01),
    ("AMZN_US_EQ", "Amazon", 105.0, 0.12, 0.32, 0.0),
    ("JNJ_US_EQ", "Johnson & Johnson", 160.0, 0.02, 0.16, 1.19),
    ("KO_US_EQ", "Coca-Cola", 60.0, 0.04, 0.14, 0.48),
    ("SCHD_US_EQ", "Schwab US Dividend Equity ETF", 25.0, 0.06, 0.15, 0.20),
    ("TSLA_US_EQ", "Tesla", 190.0, 0.05, 0.60, 0.0),
    ("PYPL_US_EQ", "PayPal", 75.0, -0.08, 0.40, 0.0),
]
# How closely each line's daily moves follow the market's, in the order of UNIVERSE (the demo's invented lines take the
# place of the real ones and keep their loading): the S&P 500 fund almost wholly, the other funds much, a share about half.
# The market's own draws come from a stream apart, so the account's random sequence, and every trade in it, is unchanged.
MARKET_LOADING = (0.99, 0.85, 0.60, 0.65, 0.55, 0.60, 0.35, 0.35, 0.75, 0.45, 0.40)
MARKET_SEED = 2125
FEE_RATE = 0.0015           # currency-conversion style fee on each fill

# The demo's companies: invented, so nothing shown for them is a real company's figure or a real
# outlet's story. The first eight are held, in the position of the real names the tests use (their
# prices and trades are the same numbers); the last three are companies the demo follows.
# ticker, name, exchange, SIC, CIK (a range the SEC has not reached), revenue $bn a year,
# start price, yearly drift, yearly volatility, dividend per share per quarter
DEMO_COMPANIES = [
    ("ALDV", "Alder Devices Inc.", "Nasdaq", 3571, 9000001, 390.0, 165.0, 0.12, 0.27, 0.24),
    ("MRSW", "Meridian Software Corp.", "Nasdaq", 7372, 9000002, 250.0, 290.0, 0.14, 0.25, 0.75),
    ("NVLX", "Novalux Semiconductor Corp.", "Nasdaq", 3674, 9000003, 130.0, 45.0, 0.45, 0.50, 0.01),
    ("CSKD", "Cascade Retail Group", "Nasdaq", 5961, 9000004, 620.0, 105.0, 0.12, 0.32, 0.0),
    ("HRLN", "Harlan Health Sciences", "NYSE", 2834, 9000005, 88.0, 160.0, 0.02, 0.16, 1.19),
    ("KSTR", "Keystone Beverage Co.", "NYSE", 2080, 9000006, 46.0, 60.0, 0.04, 0.14, 0.48),
    ("TSRA", "Terra Motors Inc.", "Nasdaq", 3711, 9000007, 97.0, 190.0, 0.05, 0.60, 0.0),
    ("PYVO", "Payvo Holdings, Inc.", "Nasdaq", 7389, 9000008, 31.0, 75.0, -0.08, 0.40, 0.0),
    ("ARMD", "Arcadia Micro Devices Inc.", "Nasdaq", 3674, 9000009, 26.0, 100.0, 0.20, 0.45, 0.0),
    ("SMTE", "Summit Energy Corp.", "NYSE", 2911, 9000010, 340.0, 105.0, 0.03, 0.22, 0.0),
    ("FHVN", "Fairhaven Financial Corp.", "NYSE", 6021, 9000011, 160.0, 140.0, 0.08, 0.22, 0.0),
]
COMPANY_STORES = ("analysts_data.json", "diffs.json", "earnings_data.json", "fundamentals.json", "headlines.json", "listings.json",
                  "news_data.json", "prices.json", "quotes.json", "rating_sample.json", "ratings_log.json", "research.json",
                  "screen.json", "sectors.json", "universe.json", "value.json", "watchlist.json", ".cik_map.json")
FOLLOWED = ("ARMD", "SMTE", "FHVN")             # covered in the demo without being held
_STOCK_FOR = dict(zip(("AAPL", "MSFT", "NVDA", "AMZN", "JNJ", "KO", "TSLA", "PYPL"), (c[0] for c in DEMO_COMPANIES)))
# the account's lines in the demo: the same funds (prices made up) and the invented companies
DEMO_UNIVERSE = [(f"{_STOCK_FOR.get(t.split('_')[0], t.split('_')[0])}_US_EQ",
                  next((c[1] for c in DEMO_COMPANIES if c[0] == _STOCK_FOR.get(t.split('_')[0])), n), *rest)
                 for t, n, *rest in UNIVERSE]


def iso(d, hour=15, minute=31):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def walks(rnd, today, universe=None):
    """The first day and each line's daily price walk {ticker: {day: price}}, weekends at
    Friday's price. Drawn first from the account's own random sequence."""
    start = today - timedelta(days=int(365 * 2.6))
    market = random.Random(MARKET_SEED)
    common = {}                                      # the market's move each weekday, shared by every line
    d = start
    while d <= today:
        if d.weekday() < 5:
            common[d] = market.gauss(0, 1)
        d += timedelta(days=1)
    prices = {}
    for i, (t, _, p0, mu, vol, _) in enumerate(universe or UNIVERSE):
        loading = MARKET_LOADING[i]
        p, series, d = p0, {}, start
        while d <= today:
            if d.weekday() < 5:
                own = rnd.gauss(0, 1)
                move = loading * common[d] + math.sqrt(1 - loading * loading) * own
                p *= math.exp((mu - vol * vol / 2) / 252 + vol / math.sqrt(252) * move)
            series[d] = p
            d += timedelta(days=1)
        prices[t] = series
    return start, prices


def generate(today=None, seed=SEED, universe=None):
    universe = universe or UNIVERSE
    rnd = random.Random(seed)
    today = today or datetime.now(timezone.utc).date()
    start, prices = walks(rnd, today, universe)
    names = {t: n for t, n, *_ in universe}
    divs = {t: dv for t, *_, dv in universe}

    cash, holdings, realized = 0.0, {}, 0.0      # holdings: ticker → [qty, cost]
    transactions, orders, dividends = [], [], []
    oid, ref = 40_000_000_000, 1

    def fill(d, ticker, side, q):
        nonlocal cash, realized, oid
        px = prices[ticker][d]
        value = q * px
        fee = round(value * FEE_RATE, 2)
        pl = None
        h = holdings.setdefault(ticker, [0.0, 0.0])
        if side == "BUY":
            h[0] += q; h[1] += value + fee
            cash -= value + fee
        else:
            avg = h[1] / h[0]
            pl = round(value - fee - avg * q, 2)
            realized += pl
            h[1] -= avg * q; h[0] -= q
            cash += value - fee
            if h[0] <= 1e-9:
                holdings.pop(ticker)
        oid += rnd.randint(3, 900)
        orders.append({
            "order": {"id": oid, "ticker": ticker, "side": side, "type": "MARKET", "status": "FILLED",
                      "strategy": "QUANTITY", "quantity": q if side == "BUY" else -q, "filledQuantity": q,
                      "currency": "USD", "createdAt": iso(d, 15, 30), "initiatedFrom": rnd.choice(["IOS", "IOS", "WEB"]),
                      "instrument": {"ticker": ticker, "name": names[ticker], "currency": "USD", "isin": ""}},
            "fill": {"id": oid + 1, "filledAt": iso(d), "price": round(px, 4), "quantity": q if side == "BUY" else -q,
                     "type": "TRADE", "tradingMethod": "TOTV",
                     "walletImpact": {"currency": "USD", "fxRate": 1, "netValue": round(value + fee if side == "BUY" else value - fee, 2),
                                      "realisedProfitLoss": pl if pl is not None else 0.0,
                                      "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": fee, "currency": "USD", "chargedAt": iso(d)}]}},
        })

    d = start
    while d <= today:
        if d.weekday() >= 5:
            d += timedelta(days=1); continue
        if d.day <= 3 and not any(t["dateTime"][:7] == d.isoformat()[:7] for t in transactions):
            amt = float(rnd.choice([300, 400, 500, 500, 750, 1000]) if d > start else 2500)
            cash += amt
            transactions.append({"type": "DEPOSIT", "amount": amt, "currency": "USD", "dateTime": iso(d, 9, 5), "reference": f"dep-{ref}"}); ref += 1
            # spend most of the cash on 1–3 buys
            for _ in range(rnd.randint(1, 3)):
                t = rnd.choice(universe[:9] if rnd.random() < 0.85 else universe)[0]
                budget = cash * rnd.uniform(0.3, 0.7)
                q = round(budget / prices[t][d], 4)
                if q > 0 and budget > 20:
                    fill(d, t, "BUY", q)
        elif rnd.random() < 0.02 and holdings:
            t = rnd.choice(sorted(holdings))
            q = round(holdings[t][0] * rnd.choice([0.25, 0.5, 1.0]), 4)
            if q > 0:
                fill(d, t, "SELL", min(q, holdings[t][0]))
        if d.day == 15 and d.month in (3, 6, 9, 12):
            for t, (q, _) in sorted(holdings.items()):
                if divs[t] > 0:
                    amt = round(q * divs[t] * 0.85, 2)      # after 15% US withholding
                    if amt > 0:
                        cash += amt
                        dividends.append({"ticker": t, "amount": amt, "amountInEuro": amt, "currency": "USD",
                                          "tickerCurrency": "USD", "grossAmountPerShare": divs[t], "quantity": round(q, 4),
                                          "paidOn": iso(d, 12, 0), "reference": f"div-{ref}", "type": "ORDINARY",
                                          "instrument": {"ticker": t, "name": names[t], "currency": "USD", "isin": ""}}); ref += 1
        if d.day == 1:
            interest = round(max(cash, 0) * 0.04 / 12, 2)
            if interest > 0:
                cash += interest
                transactions.append({"type": "INTEREST_ON_FREE_CASH", "amount": interest, "currency": "USD",
                                     "dateTime": iso(d, 6, 0), "reference": f"int-{ref}"}); ref += 1
        d += timedelta(days=1)

    last = max(k for k in prices["VOO_US_EQ"] if k <= today)
    positions, value, cost = [], 0.0, 0.0
    for t, (q, c) in sorted(holdings.items()):
        px = prices[t][last]
        v = q * px
        first_buy = min(o["fill"]["filledAt"] for o in orders if o["order"]["ticker"] == t)
        positions.append({
            "instrument": {"ticker": t, "name": names[t], "currency": "USD", "isin": ""},
            "createdAt": first_buy, "quantity": round(q, 4), "quantityAvailableForTrading": round(q, 4), "quantityInPies": 0,
            "averagePricePaid": round(c / q, 4), "currentPrice": round(px, 4),
            "walletImpact": {"currency": "USD", "currentValue": round(v, 2), "totalCost": round(c, 2),
                             "unrealizedProfitLoss": round(v - c, 2), "fxImpact": 0.0},
        })
        value += v; cost += c
    summary = {
        "currency": "USD",
        "cash": {"availableToTrade": round(cash, 2), "inPies": 0.0, "reservedForOrders": 0.0},
        "investments": {"currentValue": round(value, 2), "totalCost": round(cost, 2),
                        "unrealizedProfitLoss": round(value - cost, 2), "realizedProfitLoss": round(realized, 2)},
        "totalValue": round(value + cash, 2),
    }
    newest = lambda xs, k: sorted(xs, key=k, reverse=True)
    return {
        "demo_data": True,
        "env": "demo",
        "summary": summary,
        "positions": positions,
        "orders": newest(orders, lambda o: o["fill"]["filledAt"]),
        "dividends": newest(dividends, lambda x: x["paidOn"]),
        "transactions": newest(transactions, lambda x: x["dateTime"]),
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def add_companies(out, today=None):
    """The demo's invented companies and their market: the desk's own company update (filings,
    financials, prices, news, ratings) run over a simulated market (tests/world.py) with the demo's
    roster, into `out`. Nothing leaves the machine and nothing outside `out` is written; the
    simulation is put back afterwards. The account and its prices come from `main`."""
    import contextlib, io
    tests = os.path.join(ROOT, "tests")
    if tests not in sys.path:
        sys.path.insert(0, tests)
    import build_desk, news, server, world
    for name in COMPANY_STORES:                     # a fresh market each time; the demo's notes and practice trades stay
        try:
            os.remove(os.path.join(out, name))
        except OSError:
            pass
    restore_paths, restore_net = build_desk.keep_apart(out), world.install()
    restore_roster = world.use_demo_roster()
    try:
        for ticker in FOLLOWED:
            news.follow(ticker, path=os.path.join(out, "watchlist.json"))
        handler = server.Handler.__new__(server.Handler)
        handler.folder, handler.demo = out, False
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = handler.refresh_market()[1]
        if not result.get("ok"):
            raise RuntimeError("The demo's companies could not be built: " + str(result.get("message")))
    finally:
        restore_roster(); restore_net(); restore_paths()
    for name in ("health.json", "looks.json", "index.html", "desk_data.json"):      # the demo keeps no log of a run
        try:
            os.remove(os.path.join(out, name))
        except OSError:
            pass


def main(argv):
    out = os.path.abspath(argv[0]) if argv else os.path.join(ROOT, "demo")
    os.makedirs(out, exist_ok=True)
    data = generate(universe=DEMO_UNIVERSE)
    atomic_write_json(os.path.join(out, "t212_data.json"), data)
    add_companies(out)
    print(f"Demo account → {out}/t212_data.json ({len(data['positions'])} positions, {len(data['orders'])} orders), "
          f"{len(FOLLOWED) + len([p for p in data['positions'] if p['instrument']['ticker'].split('_')[0] in {c[0] for c in DEMO_COMPANIES}])} invented companies")


if __name__ == "__main__":
    main(sys.argv[1:])
