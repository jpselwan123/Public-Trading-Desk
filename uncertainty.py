"""Every interval the desk shows about a count or a median, from one place.

A count read as a rate — "you beat the market in 7 of 29 trades", "up after 11 of 25
results" — is a sample, and a sample of 4 or 29 says less than its percentage
suggests. Each such claim on the page carries the interval computed here, and says
whether the value chance would give sits inside it. This module computes nothing
another module owns: callers pass their own counts and values.

Two intervals, both exact and both distribution-free, and both inverting the same
binomial test, so the two statements that share a line on a card ("the median moved
−2.3%" and "up after 9 of 24") cannot contradict each other:

  proportion  Clopper & Pearson (1934), the exact binomial interval. The fourth
              review asked for Wilson's score interval (1927). Measured first: at
              4 of 4 Wilson's 95% interval is 51%–100%, which calls four heads in a
              row a finding against a fair coin although a fair coin gives four of
              a kind one time in eight. The exact interval is 40%–100%. It is
              wider than Wilson's everywhere, which is the cost of never claiming
              more than the data can hold — the direction this desk errs in.
              Values match Newcombe (1998), Statistics in Medicine 17, table I.

  median      The order-statistic interval for a median (Conover, Practical
              Nonparametric Statistics, 3rd ed., 1999): the r-th smallest and r-th
              largest values, with r from the binomial distribution at one half. It
              is the interval the sign test inverts, so "the median is below zero"
              holds exactly when "fewer than half went up" does.

One more, for a slope rather than a count: slope(), the ordinary least-squares line
through paired numbers with its interval (the account's weekly moves against the S&P
500's give its beta). The interval uses Student's t, whose quantile is t_quantile()'s
series (Abramowitz & Stegun 1964, 26.7.5), checked in the tests against the published
table; the residuals are taken as independent, which weekly returns roughly are.

Below SMALLEST (6 at 95%) no result, however lopsided, can be told from an even
split: even 5 of 5 has a 1-in-16 chance. That is where a median cannot be bounded
at all, and where every interval here reads "uncertain". It is derived from the
binomial, not chosen.

Many records shown side by side are many tests: at 95% each, one in twenty would
look like a pattern by luck alone. family_level() gives the level for a family of
records so that its intervals exclude chance exactly where Benjamini & Hochberg
(1995) would declare a discovery — the false-discovery-rate adjusted intervals of
Benjamini & Yekutieli (2005), 'False Discovery Rate-Adjusted Multiple Confidence
Intervals for Selected Parameters', JASA 100. The same correction the research page
already applies to its rule tests. The paper adjusts only the intervals it selects;
the desk applies the level to every record, and uses R = 1 when none is selected —
both its own choices, stated in family_level.

Stdlib only.
"""
import math
import statistics

CONFIDENCE = 0.95            # every interval the desk shows: 2.5% cut from each tail
# How a proportion's estimate and bounds are shown: whole percentages, so "0% to 98%"
# never mixes precisions (joined into measure_display, read by the page's ofCount).
UNCERTAINTY_DISPLAY = {"share": {"kind": "percent", "dp": 0, "label": "Share of cases"}}
_STEPS = 64                  # bisection halvings: 2**-64 is below a float's precision on [0, 1]


def _log_pmf(i, n, p):
    return (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p))


def _at_least(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p), 0 < p < 1."""
    return math.fsum(math.exp(_log_pmf(i, n, p)) for i in range(k, n + 1))


def _at_most(k, n, p):
    """P(X <= k) for X ~ Binomial(n, p), 0 < p < 1."""
    return math.fsum(math.exp(_log_pmf(i, n, p)) for i in range(0, k + 1))


def _solve(f, target, rising):
    """The p in (0, 1) where the monotone f(p) crosses target."""
    low, high = 0.0, 1.0
    for _ in range(_STEPS):
        middle = (low + high) / 2
        if (f(middle) < target) == rising:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def sign_test_p(k, n, expected=0.5):
    """The exact two-sided p-value for k of n against `expected`: twice the smaller
    tail, the test the exact interval inverts (Clopper & Pearson 1934)."""
    if not n:
        return 1.0
    if not 0 < expected < 1:
        raise ValueError("the expected rate must lie strictly between 0 and 1")
    return min(1.0, 2 * min(_at_least(k, n, expected), _at_most(k, n, expected)))


def family_level(p_values, confidence=CONFIDENCE):
    """The level for every interval in a family of m tests: 1 - R q / m, where R is
    the number Benjamini-Hochberg declares at q = 1 - confidence. Benjamini &
    Yekutieli (2005, section 4) build intervals at this level for the R parameters
    the procedure selects; one excludes chance only for a test among the R, and for
    each of them unless its p-value lands exactly on the cut-off.

    Two departures from the paper, both the desk's choices (K-04):
    - The level is applied to every record in the family, selected or not, so a
      record reads the same whichever others were declared. For the unselected it
      is wider than the paper's, which has no interval for them at all, so nothing
      is overstated.
    - With nothing declared (R = 0) the paper has no intervals to adjust; the desk
      uses R = 1, the level had one been selected. That is also the widest level the
      procedure ever sets: Bonferroni's, 1 - q / m."""
    m = len(p_values)
    if not m:
        return confidence
    q = 1 - confidence
    declared = 0
    for rank, p in enumerate(sorted(p_values), start=1):
        if p <= rank * q / m:
            declared = rank
    return 1 - max(declared, 1) * q / m


def level_text(confidence):
    """How a level is written, on the page and to the summary alike: a whole level as
    it is ("95%"), any other to two figures of what it leaves out, cut rather than
    rounded so it is never overstated — "98.6%", "99.953%", never "100%"."""
    percent = confidence * 100
    if abs(percent - round(percent)) < 1e-9:
        return f"{round(percent)}%"
    places = max(1, math.ceil(-math.log10(100 - percent)) + 1)
    shown = math.floor(percent * 10 ** places + 1e-9) / 10 ** places
    return f"{shown:.{places}f}".rstrip("0").rstrip(".") + "%"


def smallest_sample(confidence=CONFIDENCE):
    """The fewest cases in which an all-one-way result can be told from an even
    split: (1/2)**n inside one tail."""
    tail = (1 - confidence) / 2
    n = 1
    while 0.5 ** n > tail:
        n += 1
    return n


SMALLEST = smallest_sample()


def _reads(out, expected):
    """Whether the interval is a finding. `distinguishable` is set only when there is
    a value chance would give to compare with; `reads` is what the page draws:
    "measured" when the interval excludes that value, "uncertain" when it does not or
    the sample is too small to tell, and "bounded" when there is nothing to compare
    with and the sample is large enough to bound (K-07). "Measured" once covered that
    last case too, so 6 beats of 6 took the colour of a finding having been compared
    with nothing."""
    bounded = out["low"] is not None and out["high"] is not None
    if expected is not None:
        out["expected"] = expected
        out["distinguishable"] = bool(bounded and not (out["low"] <= expected <= out["high"]))
        out["reads"] = "measured" if out["distinguishable"] else "uncertain"
    else:
        out["reads"] = ("bounded" if bounded and out["n"] >= smallest_sample(out["confidence"])
                        else "uncertain")
    return out


def proportion(k, n, confidence=CONFIDENCE):
    """The exact interval for k successes in n (Clopper & Pearson 1934). None when
    there is nothing to count."""
    if not n:
        return None
    if not 0 <= k <= n:
        raise ValueError(f"{k} of {n} is not a count")
    tail = (1 - confidence) / 2
    low = 0.0 if k == 0 else _solve(lambda p: _at_least(k, n, p), tail, rising=True)
    high = 1.0 if k == n else _solve(lambda p: _at_most(k, n, p), tail, rising=False)
    return _reads({"k": k, "n": n, "estimate": k / n, "low": low, "high": high,
                   "confidence": confidence, "level": level_text(confidence)}, None)


def against_chance(k, n, expected=0.5, confidence=CONFIDENCE):
    """The same, plus whether `expected` sits inside the interval. A record that
    cannot be told from chance must say so rather than be reported as a finding."""
    out = proportion(k, n, confidence)
    if out is None:
        return None
    out["expected_count"] = expected * n
    return _reads(out, expected)


def median(values, confidence=CONFIDENCE, expected=None):
    """The median and its order-statistic interval. low and high are None when the
    sample is too small to bound it (fewer than SMALLEST at 95%). With `expected`
    (0 for a move against the market), says whether the interval excludes it."""
    values = sorted(v for v in values if v is not None)
    n = len(values)
    if not n:
        return None
    tail = (1 - confidence) / 2
    # The largest r with P(X <= r - 1) < tail. Strictly below, like the exact
    # interval's test, so the two agree even where a tail lands exactly on it.
    r = 0
    while r < n and _at_most(r, n, 0.5) < tail:
        r += 1
    out = {"n": n, "estimate": statistics.median(values),
           "low": values[r - 1] if r else None, "high": values[n - r] if r else None,
           "confidence": confidence, "level": level_text(confidence)}
    return _reads(out, expected)


def _wilson(k, n, z):
    """The Wilson score interval for k in n (Wilson 1927), the building block of the
    difference below."""
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def difference(k1, n1, k2, n2, confidence=CONFIDENCE):
    """The first proportion less the second, with its interval: Newcombe's hybrid score
    interval (1998, "Interval estimation for the difference between independent
    proportions", Statistics in Medicine 17, method 10), which keeps its coverage where the
    usual one does not, at small counts and near 0 or 1. Whether it can be told from no
    difference is said, not left to the page. None when either has nothing to count."""
    if not n1 or not n2:
        return None
    z = statistics.NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = _wilson(k1, n1, z)
    l2, u2 = _wilson(k2, n2, z)
    d = p1 - p2
    out = {"estimate": d, "low": d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2),
           "high": d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2),
           "n": n1 + n2, "confidence": confidence, "level": level_text(confidence)}
    return _reads(out, 0.0)


def t_quantile(df, confidence=CONFIDENCE):
    """Student's t for a two-sided interval at `confidence` with `df` degrees of freedom: the series in
    1/df from the normal quantile (Abramowitz & Stegun 1964, 26.7.5), good to four places from df = 10.
    None below that, where the series is not to be trusted."""
    if df < 10:
        return None
    z = statistics.NormalDist().inv_cdf(0.5 + confidence / 2)
    return (z + (z ** 3 + z) / (4 * df)
            + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)
            + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * df ** 3))


def slope(xs, ys, confidence=CONFIDENCE):
    """The least-squares line y = a + b x through the pairs: {"slope", "low", "high", "explained", "n"}, where
    `explained` is r squared, the share of y's movement the line accounts for. None with fewer than 12 pairs
    (10 degrees of freedom, t_quantile's floor) or when x never varies."""
    n = len(xs)
    if n != len(ys) or n < 12:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    b = sxy / sxx
    residual = max(syy - b * sxy, 0.0)
    half = t_quantile(n - 2, confidence) * math.sqrt(residual / (n - 2) / sxx)
    return {"slope": b, "low": b - half, "high": b + half, "n": n,
            "explained": (sxy * sxy / (sxx * syy)) if syy > 0 else None,
            "confidence": confidence, "level": level_text(confidence)}
