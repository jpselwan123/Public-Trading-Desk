"""Test a rule on real history, after costs, against simply holding.

Rules here are only ones with published evidence behind them, and each result is
shown next to two honest comparisons: holding the same share, and holding the
market (SPY). Nothing here is a recommendation — it is a measurement.

Costs: every entry and exit is charged TRADE_COST. Trading 212 charges no
commission on US shares but converts currency at 0.15% each way, which is the
real cost of a round trip for this account. A position still open at the end of
the data is not charged an exit it never paid.

Out of the market is not nothing: money sitting in cash earns the 3-month
Treasury bill rate, the way Faber (2007) and the trend-following literature
measure it. Without that, a rule that spends a quarter of its life in cash is
penalised for interest it would really have received.

Signals are built from the close as printed on the day; returns are computed from
the split- and dividend-adjusted close. Building a moving average from adjusted
prices would test a series nobody could have seen at the time.

Rules
  trend_200    hold while the price is above its 200-day average (Faber 2007,
               "A Quantitative Approach to Tactical Asset Allocation")
  momentum_12_1 hold while the last 12 months' return, skipping the most recent
               month, is positive (Jegadeesh & Titman 1993; the skip avoids
               short-term reversal, Jegadeesh 1990)
  results_5d   hold for 5 trading days after a results announcement
               (post-earnings drift, Bernard & Thomas 1989)
"""
import math
import random
from datetime import date

import prices as price_store
import uncertainty

TRADE_COST = 0.0015          # 0.15% per entry or exit (Trading 212 FX conversion)
TRADING_DAYS = 252
SMA_DAYS = 200
MOMENTUM_LOOKBACK = 252
MOMENTUM_SKIP = 21
DRIFT_HOLD = 5
VOL_TARGET = 0.12            # Moreira & Muir (2017), capped at 1x: this is a cash account
VOL_WINDOW = 21
LOWVOL_WINDOW = 60
PICK_N = 3                   # sector rules hold three funds
MONTH_END_REBALANCE = True
MIN_DAYS = 400               # below this there isn't enough history to judge

# A fixed universe, written here rather than read from the watchlist: testing rules
# on shares chosen because they already went up is hindsight, and it guarantees a
# trend rule looks bad. The 11 SPDR sector funds plus the market cover the whole US
# market without anyone picking them after the fact.
# Note on history: this set is today's sector map applied backwards. XLRE was carved
# out of XLF in 2015 and XLC out of XLK and XLY in 2018, so an investor in 2010 could
# not have held this list, and what XLK and XLY contained changed mid-sample. The
# funds' own price histories are honest; the composition of the set is not constant.
UNIVERSE = (price_store.BENCHMARK, "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
UNIVERSE_NAMES = {
    price_store.BENCHMARK: "The market (S&P 500)", "XLB": "Materials", "XLC": "Communications", "XLE": "Energy",
    "XLF": "Financials", "XLI": "Industrials", "XLK": "Technology", "XLP": "Everyday goods",
    "XLRE": "Property", "XLU": "Utilities", "XLV": "Health care", "XLY": "Consumer",
}
TEST_SHARE = 0.30            # the last 30% of each history is never used to choose anything
BOOTSTRAP_ROUNDS = 1000
BLOCK_DAYS = 20              # mean block length for the stationary bootstrap


def _series(prices, ticker):
    """(days, signal closes, total-return closes) — see the note at the top."""
    adjusted = price_store.series(prices, ticker, "a")
    printed = price_store.series(prices, ticker, "c")
    days = sorted(adjusted)
    return days, [printed.get(d, adjusted[d]) for d in days], [adjusted[d] for d in days]


def cash_factors(days, rates):
    """Growth factor for one day in cash, for each step between consecutive days.
    DTB3 is an annual percentage; it is compounded over the calendar days held."""
    if not rates:
        return [1.0] * max(0, len(days) - 1)
    out, last = [], 0.0
    for i in range(len(days) - 1):
        rate = rates.get(days[i])
        if rate is None:
            rate = last                       # holiday: carry the last published rate
        last = rate
        span = (date.fromisoformat(days[i + 1]) - date.fromisoformat(days[i])).days or 1
        out.append((1 + rate / 100.0) ** (span / 365.0))
    return out


def _sma(values, n):
    """Simple moving average; None until there are n values."""
    out, total = [], 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        out.append(total / n if i >= n - 1 else None)
    return out


def positions_trend(days, closes):
    sma = _sma(closes, SMA_DAYS)
    return [1 if sma[i] is not None and closes[i] > sma[i] else 0 for i in range(len(closes))]


def positions_momentum(days, closes):
    out = []
    for i in range(len(closes)):
        j, k = i - MOMENTUM_LOOKBACK, i - MOMENTUM_SKIP
        out.append(1 if j >= 0 and closes[k] > closes[j] else 0)
    return out


def positions_momentum_12(days, closes):
    """Moskowitz, Ooi & Pedersen (2012): hold while the last 12 months were positive."""
    out = []
    for i in range(len(closes)):
        j = i - MOMENTUM_LOOKBACK
        out.append(1 if j >= 0 and closes[i] > closes[j] else 0)
    return out


def realised_vol(closes, window):
    """Annualised volatility of the last `window` daily moves, per day."""
    out, rets = [], []
    for i in range(len(closes)):
        if i:
            rets.append(closes[i] / closes[i - 1] - 1)
        window_rets = rets[-window:]
        if len(window_rets) < window:
            out.append(None)
            continue
        mean = sum(window_rets) / window
        var = sum((r - mean) ** 2 for r in window_rets) / (window - 1)
        out.append(math.sqrt(var) * math.sqrt(TRADING_DAYS))
    return out


def positions_vol_managed(days, closes):
    """Moreira & Muir (2017): hold less when the market is moving around more.
    Capped at 1 because this account cannot borrow."""
    vols = realised_vol(closes, VOL_WINDOW)
    return [0.0 if not v else min(1.0, VOL_TARGET / v) for v in vols]


def month_end_flags(days):
    """True on the last trading day of each month — the only days a monthly rule acts."""
    out = []
    for i, day in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else None
        out.append(nxt is None or nxt[:7] != day[:7])
    return out


def positions_events(days, closes, event_days):
    """In the market for DRIFT_HOLD trading days after each event."""
    out = [0] * len(days)
    index = {d: i for i, d in enumerate(days)}
    for day in event_days:
        i = index.get(day)
        if i is None:                     # filed on a non-trading day → next open day
            later = [d for d in days if d >= day]
            if not later:
                continue
            i = index[later[0]]
        for k in range(i, min(i + DRIFT_HOLD, len(days))):
            out[k] = 1
    return out


def daily_returns(curve):
    """Day-by-day returns of an equity curve."""
    out = []
    for i in range(1, len(curve)):
        prev = curve[i - 1][1]
        out.append(curve[i][1] / prev - 1 if prev else 0.0)
    return out


def annual_vol(returns):
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def sharpe(returns, cash_returns):
    """Return above cash per unit of how much it moved around (Sharpe 1966)."""
    if len(returns) < 2:
        return None
    excess = [r - (cash_returns[i] if i < len(cash_returns) else 0.0) for i, r in enumerate(returns)]
    mean = sum(excess) / len(excess)
    var = sum((e - mean) ** 2 for e in excess) / (len(excess) - 1)
    sd = math.sqrt(var)
    return (mean * TRADING_DAYS) / (sd * math.sqrt(TRADING_DAYS)) if sd else None


def floor_p(rounds=BOOTSTRAP_ROUNDS):
    """The smallest p-value a bootstrap of this many rounds can produce.

    p is (hits + 1) / (rounds + 1). The +1 is deliberate — a finite number of
    resamples never justifies claiming p = 0 — but it puts a floor under the answer:
    no p below this is reachable, whatever the true effect. A threshold beneath this
    floor cannot be cleared by any edge, however large, so a test against one measures
    the bootstrap's resolution and not the design's power. Any caller comparing p with
    a small threshold must check this first."""
    return 1.0 / (rounds + 1)


def _annualised(returns):
    """Compound a daily return series and annualise it, the same way metrics() does."""
    equity = 1.0
    for r in returns:
        equity *= (1 + r)
    years = len(returns) / TRADING_DAYS
    return equity ** (1 / years) - 1 if years > 0 and equity > 0 else -1.0


def bootstrap_edge(rule_returns, hold_returns, rounds=BOOTSTRAP_ROUNDS, block=BLOCK_DAYS,
                   seed=212, statistic=None, cash_returns=None):
    """Test the number that is actually reported.

    The effect shown on the page is a difference of annualised, compounded returns.
    Resampling a pre-computed daily difference tests the average arithmetic gap
    instead, and for a rule that is calmer than buy-and-hold those two can point in
    opposite directions, because compounding is penalised by variance.

    So the rule's day and the benchmark's day are resampled together, in blocks, and
    both statistics are recomputed inside every resample. Returns
    {'edge', 'p', 'low', 'high'}: the observed difference, a two-sided p-value for
    'the difference is zero', and a 95% interval.

    `statistic` chooses what is being tested — "return" (the default) or "sharpe".
    A risk-reducing rule claims a better return per unit of risk at a similar return,
    so testing its return difference asks a question its source paper never asked
    (v3-C pre-registration, review G-06). Sharpe needs the cash rate of each day, so
    `cash_returns` is required with it and resampled alongside.
    """
    n = min(len(rule_returns), len(hold_returns))
    if statistic == "sharpe":
        if not cash_returns:
            return None
        n = min(n, len(cash_returns))
    if n < 60:
        return None
    rule, hold = rule_returns[:n], hold_returns[:n]
    cash = list(cash_returns[:n]) if statistic == "sharpe" else None

    def difference(order):
        a, b = [rule[k] for k in order], [hold[k] for k in order]
        if statistic != "sharpe":
            return _annualised(a) - _annualised(b)
        c = [cash[k] for k in order]
        mine, theirs = sharpe(a, c), sharpe(b, c)
        return None if mine is None or theirs is None else mine - theirs

    straight = list(range(n))
    observed = difference(straight)
    if observed is None:
        return None
    rnd = random.Random(seed)
    p_new_block = 1.0 / block
    spread, hits = [], 0
    for _ in range(rounds):
        idx, i = [], rnd.randrange(n)
        for _ in range(n):
            idx.append(i)
            i = rnd.randrange(n) if rnd.random() < p_new_block else (i + 1) % n
        edge = difference(idx)
        if edge is None:
            continue
        spread.append(edge)
        if abs(edge - observed) >= abs(observed):      # the world where the edge is zero
            hits += 1
    if not spread:
        return None
    spread.sort()
    tail = (1 - uncertainty.CONFIDENCE) / 2
    lo = spread[int(tail * len(spread))]
    hi = spread[min(len(spread) - 1, int((1 - tail) * len(spread)))]
    floor = floor_p(len(spread))
    p = (hits + 1) / (len(spread) + 1)
    # at_floor means "no resample reached the observed edge": the true p may be far
    # smaller than this, and comparing it with a threshold below `floor` is meaningless
    return {"edge": observed, "p": p, "low": lo, "high": hi, "rounds": len(spread),
            "statistic": statistic or "return", "floor": floor, "at_floor": p <= floor}


def benjamini_hochberg(pairs, m=None):
    """[(key, p)] → {key: q}. Controls the share of false findings when many
    rules are tested at once (Benjamini & Hochberg, 1995).

    `m` overrides the number of tests corrected for. It exists because these tests
    are not independent: 12 sector funds are slices of one index over identical days,
    and the four time-series rules are variations on one signal. Correcting as though
    all 48 were separate questions throws away most of the power (Cheverud 2001;
    Li & Ji 2005 estimate the same quantity from eigenvalues). effective_tests()
    supplies the estimate; this is where it is applied.

    q is never reported below its own p: with m smaller than the number of tests,
    the arithmetic can produce one, and a q-value beneath the p-value it came from
    would say the correction made the evidence stronger."""
    scored = sorted(((p, k) for k, p in pairs if p is not None), key=lambda x: x[0])
    tests = len(scored)
    size = tests if m is None else max(1.0, min(float(m), tests))
    q_by_key, running = {}, 1.0
    for rank in range(tests, 0, -1):
        p, key = scored[rank - 1]
        running = min(running, p * size / rank)
        q_by_key[key] = max(running, p)
    return q_by_key


def effective_tests(series_by_key):
    """How many independent tests a family really contains.

    Sector funds are slices of the same index over the same days, and the trend
    and momentum rules are variations on one signal, so their results move
    together. Correcting as though all of them were independent throws away power.
    Estimated from the average pairwise correlation r as m_eff = m / (1 + (m-1)·r),
    the standard adjustment used for correlated tests (Cheverud 2001; Li & Ji 2005
    use the same idea via eigenvalues)."""
    keys = [k for k, v in series_by_key.items() if v and len(v) > 30]
    m = len(keys)
    if m < 2:
        return m, 0.0
    total, pairs = 0.0, 0
    for i in range(m):
        for j in range(i + 1, m):
            r = _correlation(series_by_key[keys[i]], series_by_key[keys[j]])
            if r is not None:
                total += r
                pairs += 1
    if not pairs:
        return m, 0.0
    average = total / pairs
    effective = m / (1 + (m - 1) * max(0.0, average))
    return max(1.0, effective), average


def _correlation(a, b):
    n = min(len(a), len(b))
    if n < 30:
        return None
    x, y = a[:n], b[:n]
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sxx = sum((v - mx) ** 2 for v in x)
    syy = sum((v - my) ** 2 for v in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None


def split_point(days, share=TEST_SHARE):
    """Index where the held-out part begins."""
    return int(len(days) * (1 - share))


def run(days, closes, positions, cost=TRADE_COST, cash=None):
    """Equity curve for a weight series. A weight set on day i earns day i+1's
    move, so no rule can act on a price it could not have seen. Weights are
    fractions of the account between 0 and 1; the remainder earns the cash rate.
    Cost is charged on the size of each change, so a small adjustment costs little.

    No exit is charged on the last bar: a position still open was never sold."""
    equity, held, trades, turnover = 1.0, 0.0, 0, 0.0
    curve = []
    for i in range(len(closes) - 1):
        want = float(positions[i])
        if abs(want - held) > 1e-9:
            equity *= (1 - cost * abs(want - held))
            turnover += abs(want - held)
            trades += 1
            held = want
        growth = closes[i + 1] / closes[i]
        rate = cash[i] if cash else 1.0
        equity *= held * growth + (1 - held) * rate
        curve.append((days[i + 1], equity))
    return {"curve": curve, "final": equity, "trades": trades, "turnover": turnover,
            "returns": daily_returns([(days[0], 1.0)] + curve),
            "in_market": sum(float(p) for p in positions[:-1]) / max(1, len(positions) - 1)}


def run_portfolio(days, series_by_ticker, weights_by_day, cost=TRADE_COST, cash=None):
    """Same engine for a basket: weights_by_day[i] is {ticker: weight}, weights
    summing to at most 1, the rest in cash."""
    equity, held, trades, turnover = 1.0, {}, 0, 0.0
    curve = []
    for i in range(len(days) - 1):
        want = {t: w for t, w in (weights_by_day[i] or {}).items() if w > 1e-9}
        changed = sum(abs(want.get(t, 0.0) - held.get(t, 0.0)) for t in set(want) | set(held))
        if changed > 1e-9:
            equity *= (1 - cost * changed)
            turnover += changed
            trades += 1
            held = want
        grown = 0.0
        for ticker, weight in held.items():
            prices_ = series_by_ticker.get(ticker) or {}
            a, b = prices_.get(days[i]), prices_.get(days[i + 1])
            grown += weight * (b / a if a and b else 1.0)
        idle = max(0.0, 1 - sum(held.values()))
        equity *= grown + idle * (cash[i] if cash else 1.0)
        curve.append((days[i + 1], equity))
    return {"curve": curve, "final": equity, "trades": trades, "turnover": turnover,
            "returns": daily_returns([(days[0], 1.0)] + curve),
            "in_market": sum(sum((w or {}).values()) for w in weights_by_day[:-1]) / max(1, len(days) - 1)}


def metrics(result, days):
    """None when the window is too short to annualise honestly."""
    curve = result["curve"]
    if not curve:
        return None
    span = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[0][0])).days
    if span < MIN_DAYS:
        return None
    years = span / 365.25
    peak, drawdown = 0.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        drawdown = min(drawdown, v / peak - 1)
    return {
        "total": result["final"] - 1,
        "annual": result["final"] ** (1 / years) - 1,
        "worst_drop": drawdown,
        "trades": result["trades"],
        "in_market": result["in_market"],
        "years": round(years, 1),
    }


# ---- rules that pick between funds, rebalanced monthly ----------------------------
def _momentum_score(prices_, day_index, days, lookback=MOMENTUM_LOOKBACK, skip=MOMENTUM_SKIP):
    i = day_index
    if i - lookback < 0:
        return None
    then, now = prices_.get(days[i - lookback]), prices_.get(days[i - skip])
    return (now / then - 1) if (then and now) else None


def _vol_score(prices_, day_index, days, window=LOWVOL_WINDOW):
    if day_index - window < 0:
        return None
    closes = [prices_.get(d) for d in days[day_index - window:day_index + 1]]
    closes = [c for c in closes if c]
    if len(closes) < window // 2:
        return None
    rets = [closes[k] / closes[k - 1] - 1 for k in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def _monthly_weights(days, series_by_ticker, choose, pick=PICK_N):
    """Hold `choose(...)`'s picks, equally weighted, changed only at month ends.

    `pick` fixes the divisor, so a rule that wanted three funds but found only two
    correctly leaves a third in cash. `pick=None` divides by however many were
    picked, which is what a fully invested benchmark needs: a universe whose funds
    start at different dates must still be 100% invested on every day."""
    flags = month_end_flags(days)
    weights, current = [], {}
    for i, day in enumerate(days):
        if i == 0 or flags[i - 1]:                 # act on the day after a month end
            picks = choose(i, days, series_by_ticker)
            divisor = pick if pick else len(picks)
            current = {t: 1.0 / divisor for t in picks} if picks else {}
        weights.append(dict(current))
    return weights


def weights_sector_momentum(days, series_by_ticker, trend_filter=False):
    def choose(i, days, series):
        scored = []
        for ticker, prices_ in series.items():
            score = _momentum_score(prices_, i, days)
            if score is not None:
                scored.append((score, ticker))
        scored.sort(reverse=True)
        picks = [t for _, t in scored[:PICK_N]]
        if not trend_filter:
            return picks
        kept = []
        for ticker in picks:
            closes = [series[ticker].get(d) for d in days[max(0, i - SMA_DAYS):i + 1]]
            closes = [c for c in closes if c]
            if len(closes) >= SMA_DAYS and closes[-1] > sum(closes[-SMA_DAYS:]) / SMA_DAYS:
                kept.append(ticker)                # below its own trend → that third stays in cash
        return kept
    return _monthly_weights(days, series_by_ticker, choose)


def weights_low_vol(days, series_by_ticker):
    def choose(i, days, series):
        scored = []
        for ticker, prices_ in series.items():
            vol = _vol_score(prices_, i, days)
            if vol is not None:
                scored.append((vol, ticker))
        scored.sort()
        return [t for _, t in scored[:PICK_N]]
    return _monthly_weights(days, series_by_ticker, choose)


def weights_equal(days, series_by_ticker):
    """The benchmark for the fund-picking rules: hold every fund that exists on the
    day, equally, and stay fully invested. Dividing by the full list instead would
    park the missing funds' share in cash — XLRE only starts in 2015 and XLC in 2018,
    so the benchmark would have been 9/11 invested for most of the history, and every
    rule measured against it would look better than it is."""
    tickers = sorted(series_by_ticker)
    def choose(i, days, series):
        return [t for t in tickers if series[t].get(days[i])]
    return _monthly_weights(days, series_by_ticker, choose, pick=None)


PORTFOLIO_RULES = {
    "sector_momentum": {
        "name": "Hold the 3 strongest sectors",
        "why": "Moskowitz & Grinblatt (1999): industries that led kept leading for months.",
        "claim": "return",
        "weights": lambda days, series: weights_sector_momentum(days, series, trend_filter=False),
    },
    "sector_momentum_trend": {
        "name": "Hold the 3 strongest sectors, only while trending up",
        "why": "Faber (2013): a trend filter on top of picking the leaders cut the worst falls.",
        "claim": "risk",
        "weights": lambda days, series: weights_sector_momentum(days, series, trend_filter=True),
    },
    "low_volatility": {
        "name": "Hold the 3 calmest sectors",
        "why": "Blitz & van Vliet (2007); Baker, Bradley & Wurgler (2011): calmer shares earned more per unit of risk.",
        "claim": "risk",
        "weights": weights_low_vol,
    },
}


RULES = {
    "trend_200": {
        "name": "Hold while above the 200-day average",
        "why": "Faber (2007): a long-term trend filter cut losses in bad years at a similar return.",
        "claim": "risk",          # the paper claims lower drawdown, not higher return
        "positions": positions_trend,
    },
    "momentum_12_1": {
        "name": "Hold while the past year was positive",
        "why": "Jegadeesh & Titman (1993): winners kept winning over months; the most recent month is skipped.",
        "claim": "return",
        "positions": positions_momentum,
    },
    "momentum_12": {
        "name": "Hold while the past 12 months were positive",
        "why": "Moskowitz, Ooi & Pedersen (2012): a positive last year kept predicting the next months.",
        "claim": "return",
        "positions": positions_momentum_12,
    },
    "vol_managed": {
        "name": "Hold less when prices swing more",
        "why": "Moreira & Muir (2017): scaling down in volatile periods raised return per unit of risk, explicitly at a lower raw return.",
        "claim": "risk",
        "positions": positions_vol_managed,
    },
    "results_5d": {
        "name": "Hold for 5 days after results",
        "why": "Bernard & Thomas (1989): prices kept drifting after earnings surprises.",
        "claim": "return",
        "positions": None,             # needs the filing dates
    },
}

