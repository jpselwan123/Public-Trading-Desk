"""How large an edge could this design have detected?

A backtest that finds nothing has two possible explanations: there was nothing
there, or the test could not have seen it. This tells them apart.

It plants an edge of known size in a synthetic excess-return series, runs the
project's own bootstrap over it, and reports how often the pass mark fires. The
minimum detectable effect (MDE) is the smallest edge caught 80% of the time.

Usage: python3 power.py [--trials 200] [--rounds N]
"""
import json
import multiprocessing
import math
import os
import random
import sys

import backtest
import research
from env_config import atomic_write_json

HERE = os.path.dirname(os.path.abspath(__file__))
POWER_FILE = os.path.join(HERE, "power.json")

TRADING_DAYS = backtest.TRADING_DAYS
DEFAULT_TRIALS = 200
TARGET_POWER = 0.80
TRACKING_ERROR = 0.12        # a trend rule's yearly wobble against buy-and-hold
EDGES = (0.02, 0.03, 0.05, 0.08, 0.12, 0.15, 0.18, 0.20, 0.30)
WINDOWS = ((3.6, "v1 held-out"), (8.4, "v2 held-out"))
# This file deliberately does not define a family size. research.applied_family_size
# owns that number and the search divides by it; a copy here drifted from it once
# already (H-02) and published a table measured against a bar fourteen times stricter
# than anything a rule faces. The harness must measure what the search does.


class PowerError(Exception):
    pass


FLOOR_MARGIN = 4             # the floor must sit this far below the threshold tested


def corrected_threshold(family, limit=None):
    """What a true effect must clear to reach rank 1 of a Benjamini-Hochberg family
    where every other test is null — the worst case, and the one worth measuring."""
    return (research.Q_LIMIT if limit is None else limit) / family


def required_rounds(family, limit=None, margin=FLOOR_MARGIN):
    """Enough resamples that the corrected threshold is actually reachable.

    Below this the answer is fixed before the data is seen, so the harness refuses
    rather than reporting a non-detection it cannot tell from a floor effect."""
    return int(math.ceil(margin / corrected_threshold(family, limit))) - 1


def default_rounds():
    """What the real search uses, so the harness measures the shipped configuration.

    It used to be a hard-coded 400 against a production BOOTSTRAP_ROUNDS of 1,000,
    which measured a setting nobody runs. --rounds raises it, and the check in
    detection_rate refuses outright if the threshold ever moves below the floor,
    which is how that stops being a silent problem."""
    return backtest.BOOTSTRAP_ROUNDS


def detection_rate(edge, years, trials, tracking_error=TRACKING_ERROR,
                   family=None, seed=11, rounds=None):
    """Share of trials where a planted edge is detected, before and after the
    multiple-testing correction. The corrected figure is the worst case: every
    other test in the family is null, so the true effect must clear p < a/m to
    reach rank 1."""
    family = research.applied_family_size() if family is None else family
    rounds = default_rounds() if rounds is None else rounds
    threshold = corrected_threshold(family)
    floor = backtest.floor_p(rounds)
    if floor >= threshold:
        # G-05: this is how "corrected power is zero at every size" was produced. At
        # 400 rounds the smallest p reachable is 1/401 = 0.0025 and the threshold was
        # 0.05/52 = 0.00096, so the corrected column read 0.00 for any edge at all,
        # including one five times the largest tested. It measured the bootstrap's
        # resolution, not the design. Refuse rather than mislead.
        raise PowerError(
            f"{rounds} rounds cannot reach p < {threshold:.6f} (a family of {family}): "
            f"the smallest p-value possible is {floor:.6f}. "
            f"Use at least {required_rounds(family)} rounds.")
    rnd = random.Random(seed)
    n = int(years * TRADING_DAYS)
    mu = edge / TRADING_DAYS
    sd = tracking_error / math.sqrt(TRADING_DAYS)
    raw = corrected = 0
    for _ in range(trials):
        # the rule's day against a benchmark's day, so the harness exercises the same
        # statistic the project now reports (bootstrap_edge, not a precomputed series)
        hold = [rnd.gauss(0.0004, 0.011) for _ in range(n)]
        rule = [hold[i] + rnd.gauss(mu, sd) for i in range(n)]
        out = backtest.bootstrap_edge(rule, hold, rounds=rounds, seed=rnd.randrange(10 ** 6))
        if out is None:
            continue
        p = out["p"]
        raw += p < research.Q_LIMIT
        corrected += p < threshold
    return raw / trials, corrected / trials


def signature():
    """What the answer depends on. If any of this changes, the cache is stale."""
    return {"test_share": backtest.TEST_SHARE, "rounds": backtest.BOOTSTRAP_ROUNDS,
            "block_days": backtest.BLOCK_DAYS, "q_limit": research.Q_LIMIT,
            "tracking_error": TRACKING_ERROR,
            "applied_family": research.applied_family_size(),
            "windows": [w[0] for w in WINDOWS], "edges": list(EDGES)}


def load():
    """The cached answer, or {} when it is missing or no longer applies."""
    try:
        with open(POWER_FILE) as f:
            cached = json.load(f)
    except (OSError, ValueError):
        return {}
    return cached if cached.get("signature") == signature() else {}


def _cell(job):
    """One (window, edge) cell. Top level so it can be run in a worker process."""
    years, label, edge, trials, rounds = job
    raw, corrected = detection_rate(edge, years, trials, rounds=rounds)
    return {"edge": edge, "years": years, "window": label,
            "power": raw, "power_corrected": corrected}


def measure(trials=DEFAULT_TRIALS, rounds=None, workers=None):
    """The whole table plus the minimum detectable effect per window.

    Two minimum detectable effects are reported, and the corrected one is the honest
    headline: a rule has to clear its family's threshold, not just p < 0.05.

    Cells run in parallel where possible. Each one seeds its own generator, so the
    answer does not depend on how many processes ran it — a run that takes an hour
    is a run nobody repeats, and this table is worth repeating."""
    rounds = default_rounds() if rounds is None else rounds
    jobs = [(years, label, edge, trials, rounds)
            for years, label in WINDOWS for edge in EDGES]
    workers = min(len(jobs), os.cpu_count() or 1) if workers is None else workers
    if workers > 1:
        with multiprocessing.Pool(workers) as pool:
            table = pool.map(_cell, jobs)
    else:
        table = [_cell(job) for job in jobs]
    mde = {}
    for years, label in WINDOWS:
        rows = [row for row in table if row["window"] == label]
        found = next((r["edge"] for r in rows if r["power"] >= TARGET_POWER), None)
        after = next((r["edge"] for r in rows if r["power_corrected"] >= TARGET_POWER), None)
        mde[label] = {"years": years, "edge": found, "above": found is None,
                      "corrected_edge": after, "corrected_above": after is None}
    return {"table": table, "mde": mde, "trials": trials, "target_power": TARGET_POWER,
            "largest_tested": max(EDGES), "rounds": rounds,
            "threshold": corrected_threshold(research.applied_family_size()),
            "applied_family": research.applied_family_size(),
            "floor": backtest.floor_p(rounds), "signature": signature()}


def main(argv):
    trials = DEFAULT_TRIALS
    if "--trials" in argv:
        trials = int(argv[argv.index("--trials") + 1])
    rounds = int(argv[argv.index("--rounds") + 1]) if "--rounds" in argv else None
    measured = measure(trials, rounds=rounds)
    atomic_write_json(POWER_FILE, measured)
    print(f"Tracking error against buy-and-hold: {TRACKING_ERROR:.0%}/yr · "
          f"{trials} trials per cell · strictest family {research.applied_family_size():g} questions")
    print(f"{measured['rounds']} resamples · smallest p reachable {measured['floor']:.6f} · "
          f"rank-1 threshold {measured['threshold']:.6f}\n")
    print(f"{'edge/yr':>8}  {'window':<14} {'P(p<.05)':>9} {'P(q<.05)':>9}")
    for row in measured["table"]:
        print(f"{row['edge']:>7.0%}  {row['window']:<14} {row['power']:>9.2f} {row['power_corrected']:>9.2f}")
    print()
    for label, found in measured["mde"].items():
        raw = ("above " + f"{measured['largest_tested']:.0%}" if found["above"]
               else f"{found['edge']:.0%}")
        after = ("above " + f"{measured['largest_tested']:.0%}" if found["corrected_above"]
                 else f"{found['corrected_edge']:.0%}")
        print(f"{label} ({found['years']}y): minimum detectable effect {raw}/yr "
              f"on its own, {after}/yr after the correction, at {TARGET_POWER:.0%} power.")
    print(f"\nWritten to {os.path.basename(POWER_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
