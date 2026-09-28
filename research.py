"""Test every rule on a fixed universe, honestly → research.json.

Three habits, because without them a backtest tells you what you want to hear:

1. A fixed universe (backtest.UNIVERSE: the 11 sector funds plus the market),
   written in code, never the watchlist. Testing on shares you already know went
   up is hindsight, and it makes any rule that sits out of the market look bad.
2. A split history. The first 70% of each series is for looking at; only the last
   30% — never used to pick or tune anything — is reported as the result.
3. Statistics that allow for luck: a stationary block bootstrap p-value for
   "this rule's edge over simply holding is not zero", and a Benjamini-Hochberg
   q-value because testing many rules across many funds finds winners by chance.

A rule "clears" only if, in the held-out part, it beat buy-and-hold and its
q-value is below Q_LIMIT. Nothing else is presented as usable.

Usage: python3 research.py
"""
import hashlib, json, os, sys
from datetime import datetime, timezone

import backtest
import prices as price_store
import uncertainty
from env_config import atomic_write_json

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH_FILE = os.path.join(HERE, "research.json")
Q_LIMIT = 0.05
MIN_WINDOW_DAYS = 250        # a window shorter than a year proves nothing
WALK_BLOCKS = 3              # the held-out years, split into equal blocks
# One correction family per kind of test. The 4 time-series rules across 12 funds are
# one question asked many correlated ways; the portfolio rules are a different
# question; the event rule is a third. Correcting all 52 together treats heavily
# dependent tests as independent and costs power (v3 pre-registration, 2026-09-22).
FAMILIES = {"time_series": ("trend_200", "momentum_12_1", "momentum_12", "vol_managed"),
            "portfolio": ("sector_momentum", "sector_momentum_trend", "low_volatility"),
            "event": ("results_5d",)}
MIN_BLOCKS_POSITIVE = 2      # pre-registered: a rule must work in 2 of the 3
# Rule H's sample, frozen (S-16; decided 25 September 2026): the shares the
# run of record of 23 September tested it on. It used to be every followed share with
# results history, so following a company changed the event family — 52 tests became 59
# when the list grew to eight, among them shares chosen knowing how they had done — which
# the fixed-universe rule above exists to prevent. A clarification of the declared
# sample, not a new hypothesis (PREREGISTRATION.md, 25 September 2026).
EVENT_SAMPLE = ("AMD",)


def sample():
    """Every fund and share the research tests: the fixed universe and rule H's frozen
    shares. The refresh prices these whether or not they are followed (S-20): it priced
    only the followed companies, so the funds' closes stopped where they were first
    fetched and every re-run tested the universe on stale prices."""
    return list(backtest.UNIVERSE) + [t for t in EVENT_SAMPLE if t not in backtest.UNIVERSE]
# Two tracks, because the papers make two different claims (v3-B, 2026-09-22).
# A rule's track comes from its source paper, declared in the rule definition, never
# from how its results turned out.
DRAWDOWN_MARGIN = 0.10       # a risk rule must cut the worst fall by a tenth of itself


def _window(days, closes, positions, cash, start, end, cost):
    if end - start < MIN_WINDOW_DAYS:
        return None
    d, c, p = days[start:end], closes[start:end], positions[start:end]
    result = backtest.run(d, c, p, cost, cash[start:end - 1])
    stats = backtest.metrics(result, d)
    if not stats:
        return None
    stats["returns"] = result["returns"]
    return stats


def walk_forward(days, rule_returns, hold_returns, blocks=WALK_BLOCKS):
    """`days` must line up with the returns: run() produces its first return on the
    day after the window opens, so callers pass days[cut+1:], not days[cut:]."""
    """Split the held-out stretch into equal blocks and ask, in each one, whether
    the rule was ahead of simply holding. A rule that only worked in one stretch
    shows up here even when the total looks good."""
    n = min(len(rule_returns), len(hold_returns))
    if n < blocks * 60 or len(days) < n:
        return None
    size, out = n // blocks, []
    for b in range(blocks):
        a, z = b * size, (b + 1) * size if b < blocks - 1 else n
        edge = sum(rule_returns[i] - hold_returns[i] for i in range(a, z))
        out.append({"from": days[a] if a < len(days) else None,
                    "to": days[min(z, len(days) - 1)],
                    "edge": edge, "ahead": edge > 0})
    return out


def nominal_family_sizes():
    """How many tests each family contains: the rules in it, across the universe."""
    return {name: len(rules) * (len(backtest.UNIVERSE) if name == "time_series" else 1)
            for name, rules in FAMILIES.items()}


def _measured_families():
    """The per-family summary from the last run, if there is one."""
    try:
        with open(RESEARCH_FILE) as f:
            return json.load(f).get("families") or {}
    except (OSError, ValueError):
        return {}


def applied_family_size(name=None, measured=None):
    """The family size the Benjamini-Hochberg correction actually divides by.

    **One definition, called by everything that needs this number.** The search and
    the power harness each worked it out for themselves and drifted apart: the search
    corrected at the effective count (~3.4) while the harness measured against the raw
    count (48), so the published power table used a bar fourteen times stricter than
    anything a rule actually faces. That is the second time a measurement tool and the
    thing it measures each computed the same quantity (see G-05), and both times the
    published result described a configuration nothing runs.

    These tests are not independent — twelve sector funds are slices of one index and
    the time-series rules are variations on one signal — so the correction divides by
    the number of questions really asked, estimated from their average pairwise
    correlation (v3-A).

    `measured` is the per-family summary from a run; without it the last run's is
    used, and failing that the nominal counts, which are stricter. With no `name`,
    returns the strictest family — the hardest bar any single rule has to clear."""
    measured = _measured_families() if measured is None else measured
    nominal = nominal_family_sizes()
    if measured:
        # only the families that actually ran: a run over one fund has smaller
        # families than the full universe, and filling the rest in from the nominal
        # counts would report a strictest family no rule in that run ever faced
        sizes = {family: (info.get("effective") or info.get("tests") or nominal.get(family, 1))
                 for family, info in measured.items()}
    else:
        sizes = dict(nominal)
    if name is not None:
        return sizes.get(name, nominal.get(name, 1))
    return max(sizes.values())


def _luck_check(claim, measured, ruled, held, cash_returns):
    """The second condition's p-value, on the statistic the track is about (v3-C).

    A risk-reducing rule claims a better return per unit of risk at a similar return.
    Testing its *return* difference asks whether it did the thing its source paper
    says it does not do, so a perfect reproduction of Faber (2007) — same return,
    half the fall — failed as 'not distinguishable from luck' by construction.

    The reported effect stays the return difference either way: it is what the page
    shows and what the majority-of-funds count uses. Only the luck check changes."""
    if measured is None:
        return None
    if claim != "risk":
        return measured
    return backtest.bootstrap_edge(ruled["returns"], held["returns"],
                                   statistic="sharpe", cash_returns=cash_returns) or measured


def passes(rule, sample_size):
    """The pre-registered pass mark (PREREGISTRATION.md §5 and v3-B).

    Two tracks, because the sources make two different claims. A return-improving
    rule must beat buy-and-hold's return. A risk-reducing rule — Faber's trend
    filter, Moreira & Muir's volatility scaling — claims a better return per unit of
    risk and a smaller fall, explicitly not a higher return, so requiring one would
    disqualify it for reproducing its paper exactly.

    v3-D: the risk track's drawdown comparison is reported, not gating. The worst
    fall is one extreme value from one realised path, and two runs of the same
    process differ by more than the tenth it was tested against, so it decided the
    track's own defining condition close to at random. What gates that track now is
    the Sharpe difference, which is tested for significance."""
    test = rule.get("test") or {}
    blocks = rule.get("blocks") or []
    track = rule.get("claim", "return")
    reasons = []

    if track == "return" and not (test.get("excess") or 0) > 0:
        reasons.append("behind buy-and-hold out of sample")

    if test.get("q") is None or test["q"] >= Q_LIMIT:
        # v3-C: on the risk track this q comes from the Sharpe difference, not the
        # return difference, so the wording names what was actually tested
        reasons.append("return per unit of risk not distinguishable from luck"
                       if track == "risk" else "edge not distinguishable from luck")
    if sample_size is not None and not rule.get("majority", False):
        reasons.append("worked in fewer than half the " + ("shares" if rule.get("sample") == "event_sample" else "funds"))
    if test.get("sharpe") is None or test.get("hold_sharpe") is None or test["sharpe"] < test["hold_sharpe"]:
        reasons.append("worse return per unit of risk than holding")
    if blocks and sum(1 for b in blocks if b["ahead"]) < MIN_BLOCKS_POSITIVE:
        reasons.append(f"ahead in fewer than {MIN_BLOCKS_POSITIVE} of {len(blocks)} stretches")
    return (not reasons), reasons


def cut_the_fall(test):
    """Did the rule's worst fall come in a tenth shallower than holding's?

    Reported on every risk-track rule and gating on none of them (v3-D). None when
    either figure is missing."""
    hold_drop, drop = (test or {}).get("hold_worst_drop"), (test or {}).get("worst_drop")
    if hold_drop is None or drop is None:
        return None
    return drop >= hold_drop * (1 - DRAWDOWN_MARGIN)


def evaluate_ticker(ticker, prices, cost=backtest.TRADE_COST, event_days=None):
    days, signal, total = backtest._series(prices, ticker)
    if len(days) < backtest.MIN_DAYS:
        return None
    cash_factors = backtest.cash_factors(days, price_store.cash_rates(prices))
    cash_returns = [f - 1 for f in cash_factors]
    cut = backtest.split_point(days)
    out = {"ticker": ticker, "name": backtest.UNIVERSE_NAMES.get(ticker, ticker),
           "days": len(days), "from": days[0], "to": days[-1], "split_day": days[cut], "rules": []}

    for key, rule in backtest.RULES.items():
        if key == "results_5d":
            if not event_days:
                continue
            positions = backtest.positions_events(days, signal, event_days)
        else:
            positions = rule["positions"](days, signal)
        hold_positions = [1] * len(days)
        row = {"key": key, "name": rule["name"], "why": rule["why"], "claim": rule.get("claim", "return")}
        for label, (a, b) in (("train", (0, cut)), ("test", (cut, len(days)))):
            ruled = _window(days, total, positions, cash_factors, a, b, cost)
            held = _window(days, total, hold_positions, cash_factors, a, b, cost)
            if not ruled or not held:
                row[label] = None
                continue
            measured = (backtest.bootstrap_edge(ruled["returns"], held["returns"])
                        if label == "test" else None)
            luck = _luck_check(row["claim"], measured, ruled, held, cash_returns[a:b])
            row[label] = {
                "annual": ruled["annual"], "hold_annual": held["annual"],
                # the tested statistic and the reported effect are the same number
                "excess": measured["edge"] if measured else ruled["annual"] - held["annual"],
                "excess_low": measured["low"] if measured else None,
                "excess_high": measured["high"] if measured else None,
                "vol": backtest.annual_vol(ruled["returns"]),
                "hold_vol": backtest.annual_vol(held["returns"]),
                "sharpe": backtest.sharpe(ruled["returns"], cash_returns[a:b]),
                "hold_sharpe": backtest.sharpe(held["returns"], cash_returns[a:b]),
                "worst_drop": ruled["worst_drop"], "hold_worst_drop": held["worst_drop"],
                "trades": ruled["trades"], "in_market": ruled["in_market"],
                "years": ruled["years"],
                "turnover": ruled.get("turnover"),
                "p": luck["p"] if luck else None,
                "tested_statistic": luck["statistic"] if luck else None,
                "sharpe_edge": luck["edge"] if luck and luck["statistic"] == "sharpe" else None,
            }
            if label == "test":
                row["blocks"] = walk_forward(days[cut + 1:], ruled["returns"], held["returns"])
                row["test_returns"] = [r - held["returns"][i] for i, r in enumerate(ruled["returns"])
                                       if i < len(held["returns"])]
        if row.get("test"):
            out["rules"].append(row)
    return out if out["rules"] else None


def evaluate_portfolio_rules(prices, universe, cost=backtest.TRADE_COST):
    """The fund-picking rules, measured against holding all the sectors equally."""
    sectors = {t: price_store.series(prices, t) for t in universe if t != price_store.BENCHMARK}
    sectors = {t: v for t, v in sectors.items() if v}
    if len(sectors) < backtest.PICK_N + 1:
        return []
    days = sorted(set().union(*[set(v) for v in sectors.values()]))
    if len(days) < backtest.MIN_DAYS:
        return []
    cash_factors = backtest.cash_factors(days, price_store.cash_rates(prices))
    cash_returns = [f - 1 for f in cash_factors]
    cut = backtest.split_point(days)
    bench_weights = backtest.weights_equal(days, sectors)
    out = []
    for key, rule in backtest.PORTFOLIO_RULES.items():
        weights = rule["weights"](days, sectors)
        row = {"key": key, "name": rule["name"], "why": rule["why"], "kind": "portfolio",
               "claim": rule.get("claim", "return")}
        for label, (a, b) in (("train", (0, cut)), ("test", (cut, len(days)))):
            if b - a < MIN_WINDOW_DAYS:
                row[label] = None
                continue
            ruled = backtest.run_portfolio(days[a:b], sectors, weights[a:b], cost, cash_factors[a:b - 1])
            held = backtest.run_portfolio(days[a:b], sectors, bench_weights[a:b], cost, cash_factors[a:b - 1])
            rstats, hstats = backtest.metrics(ruled, days[a:b]), backtest.metrics(held, days[a:b])
            if not rstats or not hstats:
                row[label] = None
                continue
            measured = (backtest.bootstrap_edge(ruled["returns"], held["returns"])
                        if label == "test" else None)
            luck = _luck_check(row["claim"], measured, ruled, held, cash_returns[a:b])
            row[label] = {
                "annual": rstats["annual"], "hold_annual": hstats["annual"],
                "excess": measured["edge"] if measured else rstats["annual"] - hstats["annual"],
                "excess_low": measured["low"] if measured else None,
                "excess_high": measured["high"] if measured else None,
                "vol": backtest.annual_vol(ruled["returns"]),
                "hold_vol": backtest.annual_vol(held["returns"]),
                "sharpe": backtest.sharpe(ruled["returns"], cash_returns[a:b]),
                "hold_sharpe": backtest.sharpe(held["returns"], cash_returns[a:b]),
                "worst_drop": rstats["worst_drop"], "hold_worst_drop": hstats["worst_drop"],
                "trades": rstats["trades"], "in_market": rstats["in_market"],
                "years": rstats["years"], "turnover": ruled.get("turnover"),
                "p": luck["p"] if luck else None,
                "tested_statistic": luck["statistic"] if luck else None,
                "sharpe_edge": luck["edge"] if luck and luck["statistic"] == "sharpe" else None,
            }
            if label == "test":
                row["blocks"] = walk_forward(days[cut + 1:], ruled["returns"], held["returns"])
                row["test_returns"] = [r - held["returns"][i] for i, r in enumerate(ruled["returns"])
                                       if i < len(held["returns"])]
        if row.get("test"):
            out.append(row)
    return out


def family_of(key):
    for name, keys in FAMILIES.items():
        if key in keys:
            return name
    return "other"


def evaluate(prices, universe=None, cost=backtest.TRADE_COST, event_days_by_ticker=None,
             extra_tickers=None):
    """`universe` is the fixed list. `extra_tickers` are EVENT_SAMPLE's shares, used
    only for the earnings rule (funds do not report earnings) and always labelled as
    the weaker, after-the-fact sample they are."""
    universe = universe or backtest.UNIVERSE
    events = event_days_by_ticker or {}
    results, pairs = [], []
    for ticker in list(universe) + [t for t in (extra_tickers or []) if t not in universe]:
        sample = "universe" if ticker in universe else "event_sample"
        row = evaluate_ticker(ticker, prices, cost, events.get(ticker))
        if not row:
            continue
        if sample == "event_sample":
            row["rules"] = [r for r in row["rules"] if r["key"] == "results_5d"]
            if not row["rules"]:
                continue
        row["sample"] = sample
        results.append(row)
        for rule in row["rules"]:
            pairs.append(((ticker, rule["key"]), rule["test"]["p"]))

    portfolio = evaluate_portfolio_rules(prices, universe, cost)
    for rule in portfolio:
        pairs.append((("PORTFOLIO", rule["key"]), rule["test"]["p"]))

    # How many of these tests are really separate questions. Measured before the
    # correction, because it is an input to it (v3-A, and review G-07): the count was
    # previously computed afterwards and only displayed, while the correction still
    # divided by every test. Reporting a number that reads as the correction while a
    # different number does the correcting is not honest.
    effective, family_sizes = {}, {}
    for name in set(family_of(k[1]) for k, _ in pairs):
        family_sizes[name] = sum(1 for k, _ in pairs if family_of(k[1]) == name)
        series = {}
        for row in results:
            for rule in row["rules"]:
                if family_of(rule["key"]) == name and rule.get("test_returns"):
                    series[(row["ticker"], rule["key"])] = rule["test_returns"]
        for rule in portfolio:
            if family_of(rule["key"]) == name and rule.get("test_returns"):
                series[("PORTFOLIO", rule["key"])] = rule["test_returns"]
        count, average_r = backtest.effective_tests(series)
        effective[name] = {"tests": family_sizes[name], "effective": round(count, 1),
                           "average_correlation": round(average_r, 2)}
    # the size the correction divides by comes from the shared definition, never from
    # a rule written out again here (H-02)
    for name in effective:
        effective[name]["applied"] = applied_family_size(name, measured=effective)

    # corrected within families, not across everything, and against the number of
    # questions actually asked rather than the number of tests run
    q_by_pair = {}
    for name in family_sizes:
        members = [(k, p) for k, p in pairs if family_of(k[1]) == name]
        q_by_pair.update(backtest.benjamini_hochberg(members, m=effective[name]["applied"]))

    # "positive in more than half the funds it was tested on" (section 5) is judged per
    # rule, across the rows it ran on: the funds for the time-series rules, the frozen
    # shares for rule H. Counting the funds alone left rule H a total of 0, so it failed
    # this condition whatever its results (S-26). Each rule runs in one sample only.
    positives, counts = {}, {}
    for row in results:
        for rule in row["rules"]:
            counts[rule["key"]] = counts.get(rule["key"], 0) + 1
            positives[rule["key"]] = positives.get(rule["key"], 0) + (rule["test"]["excess"] > 0)

    clears = 0
    for row in results:
        for rule in row["rules"]:
            rule["sample"] = row["sample"]
            rule["test"]["q"] = q_by_pair.get((row["ticker"], rule["key"]))
            total = counts.get(rule["key"], 0)
            rule["majority"] = bool(total and positives.get(rule["key"], 0) > total / 2)
            rule["clears"], rule["failed"] = passes(rule, total)
            rule["cut_the_fall"] = cut_the_fall(rule["test"])
            clears += rule["clears"]
    for rule in portfolio:
        rule["test"]["q"] = q_by_pair.get(("PORTFOLIO", rule["key"]))
        rule["majority"] = True                      # one portfolio, not a vote across funds
        rule["sample"] = "universe"
        rule["clears"], rule["failed"] = passes(rule, None)
        rule["cut_the_fall"] = cut_the_fall(rule["test"])
        clears += rule["clears"]

    for row in results:
        for rule in row["rules"]:
            rule.pop("test_returns", None)
    for rule in portfolio:
        rule.pop("test_returns", None)

    by_rule = {}
    for row in results:
        for rule in row["rules"]:
            slot = by_rule.setdefault(rule["key"], {"key": rule["key"], "name": rule["name"],
                                                    "why": rule["why"], "tested": 0, "positive": 0,
                                                    "clears": 0, "excesses": [], "sharpe": [],
                                                    "hold_sharpe": [], "best": None, "worst": None,
                                                    "sample": row["sample"], "kind": "per_fund",
                                                    "claim": rule.get("claim", "return")})
            test = rule["test"]
            slot["tested"] += 1
            slot["positive"] += test["excess"] > 0
            slot["clears"] += rule["clears"]
            slot["excesses"].append(test["excess"])
            if test["sharpe"] is not None:
                slot["sharpe"].append(test["sharpe"])
            if test["hold_sharpe"] is not None:
                slot["hold_sharpe"].append(test["hold_sharpe"])
            entry = {"ticker": row["ticker"], "excess": test["excess"]}
            if not slot["best"] or test["excess"] > slot["best"]["excess"]:
                slot["best"] = entry
            if not slot["worst"] or test["excess"] < slot["worst"]["excess"]:
                slot["worst"] = entry
    for slot in by_rule.values():
        slot["median_excess"] = _median(slot.pop("excesses"))
        slot["median_sharpe"] = _median(slot.pop("sharpe"))
        slot["median_hold_sharpe"] = _median(slot.pop("hold_sharpe"))
    for rule in portfolio:
        test = rule["test"]
        by_rule[rule["key"]] = {
            "key": rule["key"], "name": rule["name"], "why": rule["why"], "kind": "portfolio",
            "claim": rule.get("claim", "return"),
            "sample": "universe", "tested": 1, "positive": int(test["excess"] > 0),
            "clears": int(rule["clears"]), "median_excess": test["excess"],
            "median_sharpe": test["sharpe"], "median_hold_sharpe": test["hold_sharpe"],
            "best": None, "worst": None, "failed": rule["failed"],
            "blocks": rule.get("blocks"), "q": test.get("q"), "trades": test.get("trades"),
        }

    return {
        "universe": list(universe),
        "universe_names": {t: backtest.UNIVERSE_NAMES.get(t, t) for t in universe},
        "results": results,
        "portfolio": portfolio,
        "by_rule": sorted(by_rule.values(), key=lambda r: -(r["median_excess"] or -9)),
        "tested": len(pairs),
        "clears": clears,
        "q_limit": Q_LIMIT,
        "families": effective,
        "test_share": backtest.TEST_SHARE,
        "bootstrap_rounds": backtest.BOOTSTRAP_ROUNDS,
        "confidence": uncertainty.CONFIDENCE,
        "block_days": backtest.BLOCK_DAYS,
        "walk_blocks": WALK_BLOCKS,
        "min_blocks_positive": MIN_BLOCKS_POSITIVE,
        "cost": cost,
        "power": _power(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _power():
    """What size of edge this design could have found, measured by power.py.
    Absent until power.py has been run, and ignored once its inputs change."""
    try:
        import power
        return power.load()
    except Exception:
        return {}


def _median(values):
    vs = sorted(v for v in values if v is not None)
    if not vs:
        return None
    n = len(vs)
    return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2


def event_days_from(news_items, kept=None):
    """Each EVENT_SAMPLE share's results days: those in the filings store, and those
    kept from earlier runs. The filings store holds only followed companies, so a share
    that stops being followed keeps the days already found; later ones are not added."""
    from build_desk import event_category
    out = {t: set((kept or {}).get(t) or []) for t in EVENT_SAMPLE}
    for item in news_items or []:
        if item.get("ticker") in out and item.get("date") \
                and event_category(item) == "Announcement: Results announced":
            out[item["ticker"]].add(item["date"])
    return {t: sorted(days) for t, days in out.items() if days}


def fingerprint(prices, events, code=None):
    """Everything the search's answer depends on: the sample's prices, the cash rate,
    the results days, and the code that tests them. The bootstrap's seed is fixed, so
    equal fingerprints mean an equal answer."""
    if code is None:
        code = b""
        for module in (sys.modules[__name__], backtest, price_store, uncertainty):
            with open(module.__file__, "rb") as f:
                code += f.read()
    digest = hashlib.sha256(code)
    digest.update(json.dumps([{t: prices.get(t) for t in sample()}, prices.get(price_store.CASH_KEY),
                              events], sort_keys=True).encode())
    return digest.hexdigest()


def update(prices=None, news_items=None, stored=None):
    """`stored` is the last research.json, whose frozen sample's results days are kept.
    A search whose inputs have not changed since that run is not run again: it is about
    most of a minute of computing, on every refresh, to reach the answer already stored."""
    prices = prices if prices is not None else price_store.load()
    universe = [t for t in backtest.UNIVERSE if price_store.series(prices, t)]
    events = event_days_from(news_items, (stored or {}).get("event_days"))
    inputs = fingerprint(prices, events)
    if stored and stored.get("inputs") == inputs:
        return stored
    out = evaluate(prices, universe, event_days_by_ticker=events,
                   extra_tickers=[t for t in EVENT_SAMPLE if t in events and price_store.series(prices, t)])
    out["event_sample"], out["event_days"], out["inputs"] = list(EVENT_SAMPLE), events, inputs
    return out


def main(argv):
    news = {}
    try:
        with open(os.path.join(HERE, "news_data.json")) as f:
            news = json.load(f)
    except (OSError, ValueError):
        pass
    stored = {}
    try:
        with open(RESEARCH_FILE) as f:
            stored = json.load(f)
    except (OSError, ValueError):
        pass
    data = update(news_items=news.get("items"), stored=stored)
    atomic_write_json(RESEARCH_FILE, data)
    print(f"{data['tested']} tests on the held-out sample; {data['clears']} cleared")
    for rule in data["by_rule"]:
        print(f"  {rule['name'][:38]:40} [{rule['sample']}] median edge {rule['median_excess'] * 100:+6.2f}%/yr "
              f"· better than holding in {rule['positive']}/{rule['tested']} · cleared {rule['clears']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
