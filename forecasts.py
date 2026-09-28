"""How accurate the analysts' own forecasts turned out to be.

The point of showing what analysts say is knowing what it has been worth. Price
targets would be the obvious thing to score, but Finnhub's target endpoint is not
on the free tier and no historical record of targets exists here to score anyway —
a track record that starts today is not a track record.

What can be scored, and honestly, is the quarterly earnings estimate. It is a
falsifiable number with a published consensus, a known outcome, and several years
of both already stored by earnings.py. So this measures the forecast that can be
checked rather than approximating the one that cannot.

Read the hit rate with the finding that explains it: companies beat the consensus
most of the time, because estimates are walked down to a level management can clear
(Richardson, Teoh & Wysocki, 2004, 'The Walk-down to Beatable Analyst Forecasts').
A company beating four times out of five is the normal state, not an achievement,
and the error and the bias say far more than the hit rate does.

Usage: python3 forecasts.py AMD
"""
import json, os, sys

import uncertainty

HERE = os.path.dirname(os.path.abspath(__file__))
EARNINGS_FILE = os.path.join(HERE, "earnings_data.json")
MIN_QUARTERS = 4             # fewer than a year of outcomes is an anecdote

WALK_DOWN = ("Richardson, Teoh & Wysocki (2004), 'The Walk-down to Beatable Analyst "
             "Forecasts', Contemporary Accounting Research 21")
WALK_DOWN_FINDING = ("Consensus estimates drift down as a quarter approaches, so most "
                     "companies beat them. A high hit rate is the normal state rather "
                     "than a sign of strength; the size and direction of the error are "
                     "the informative parts.")


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _scored(history):
    return [q for q in (history or [])
            if q.get("actual") is not None and q.get("estimate") is not None]


def beat_record(history):
    """How many reported quarters beat the consensus, with the interval on that
    count. The one count of beats: the card's record, the overview's "beat
    expectations in" and the analysts' block all read it. It is never compared with
    half: most companies beat most quarters (the walk-down), so half is not what
    chance gives here."""
    quarters = _scored(history)
    return uncertainty.proportion(
        sum(1 for q in quarters if float(q["actual"]) > float(q["estimate"])), len(quarters))


def accuracy(history, minimum=MIN_QUARTERS):
    """How well the consensus estimate predicted the reported figure.

    Returns None when there are too few quarters to say anything. Errors are
    measured against the actual, and quarters where the actual was zero are left out
    rather than producing a percentage with a zero denominator."""
    quarters = _scored(history)
    if len(quarters) < minimum:
        return None
    errors, signed = [], []
    for q in quarters:
        actual, estimate = float(q["actual"]), float(q["estimate"])
        if actual == 0:
            continue
        gap = (estimate - actual) / abs(actual)
        errors.append(abs(gap))
        signed.append(gap)
    beats = beat_record(quarters)
    misses = sum(1 for q in quarters if float(q["actual"]) < float(q["estimate"]))
    return {
        "quarters": len(quarters),
        "beats": beats,
        "missed": misses,
        "met": len(quarters) - beats["k"] - misses,
        "median_error": _median(errors),
        "median_bias": _median(signed),
        "from": quarters[-1].get("date"),
        "to": quarters[0].get("date"),
        "source": WALK_DOWN,
        "finding": WALK_DOWN_FINDING,
    }


def bias_reads(median_bias):
    """Plain words for the direction of the error, or None when it is negligible."""
    if median_bias is None:
        return None
    if abs(median_bias) < 0.01:
        return "estimates landed close to the reported figure"
    if median_bias < 0:
        return (f"estimates sat {abs(median_bias):.1%} below what was reported, in the "
                "median quarter — the pattern the walk-down describes")
    return (f"estimates sat {median_bias:.1%} above what was reported, in the median "
            "quarter — the opposite of the usual pattern")


def for_company(ticker, earnings=None):
    """One company's forecast record, from the stored earnings history."""
    if earnings is None:
        try:
            with open(EARNINGS_FILE) as f:
                earnings = json.load(f)
        except (OSError, ValueError):
            earnings = {}
    row = ((earnings.get("companies") or {}).get(str(ticker).upper())) or {}
    record = accuracy(row.get("history"))
    return {"ticker": str(ticker).upper(), "record": record,
            "why_not": None if record else
            f"fewer than {MIN_QUARTERS} quarters of estimate and outcome are stored"}


def add_to(companies, earnings):
    """Attach the record to each company card the page already builds."""
    for card in companies or []:
        card["forecast_record"] = for_company(card.get("ticker"), earnings)["record"]
    return companies


def main(argv):
    if not argv:
        print("Usage: python3 forecasts.py TICKER")
        return 1
    out = for_company(argv[0])
    record = out["record"]
    if not record:
        print(f"{out['ticker']}: {out['why_not']}")
        return 1
    print(f"{out['ticker']} — how the consensus estimate did, "
          f"{record['from']} to {record['to']}\n")
    print(f"   quarters measured   {record['quarters']:>8}")
    beats = record["beats"]
    print(f"   beat the estimate   {beats['k']:>8}  ({beats['estimate']:.0%}; "
          f"{beats['confidence']:.0%} range {beats['low']:.0%} to {beats['high']:.0%})")
    print(f"   missed it           {record['missed']:>8}")
    print(f"   median error        {record['median_error']:>8.1%}   of the reported figure")
    print(f"   median bias         {record['median_bias']:>+8.1%}")
    reads = bias_reads(record["median_bias"])
    if reads:
        print(f"\n   {reads}")
    print(f"\n   {record['source']}")
    print(f"   {record['finding']}")
    print("\nThis scores the forecast that can be checked. Price targets are not on "
          "the free\ntier and none are stored, so nothing here pretends to score those.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
