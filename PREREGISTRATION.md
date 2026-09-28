# Pre-registration — rule search v1

**Status: PROPOSED, not yet run.** Written before any of these rules were tested on
the data. Nothing below may be changed after the first run; changes become v2, with
both versions kept and the test count re-corrected.

Why this exists: with enough attempts, something always looks profitable. Fixing the
list, the parameters and the pass mark in advance is the difference between research
and fishing. Every rule here comes from published work, and no parameter is chosen by
looking at how it performed on our data.

---

## 1. Universe (fixed, in code)

`backtest.UNIVERSE` — the 11 SPDR sector funds plus SPY:
SPY, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY.

Never the watchlist. XLC starts 2018, XLRE 2015; both are kept with their shorter
histories rather than dropped, so the universe is not survivorship-filtered.

**The set changes mid-sample, and that is worth knowing when reading the results.**
XLRE was carved out of XLF in October 2015, and XLC out of XLK and XLY in June 2018.
So the list used here is today's sector map applied backwards: an investor in 2010
could not have held it, and the contents of XLK and XLY changed when XLC was created.
Each fund's own price history is honest, but the composition of the universe is not
constant across the sample.

Data: Tiingo daily closes (printed close for signals, adjusted close for returns),
FRED DTB3 for cash. Snapshot runs to the last trading day at run time.

## 2. Rules (parameters fixed here, never tuned)

### Time-series rules — applied to each fund separately
| # | Rule | Exact definition | Source |
|---|---|---|---|
| A | Trend, 200-day | Hold while close > 200-day simple average, else cash | Faber (2007) |
| B | Momentum 12−1 | Hold while return from t−252 to t−21 > 0, else cash | Jegadeesh & Titman (1993); skip month per Jegadeesh (1990) |
| C | Time-series momentum, 12 months | Hold while return over the last 252 days > 0, else cash | Moskowitz, Ooi & Pedersen (2012) |
| D | Volatility-managed | Position = min(1, 12% ÷ annualised 21-day volatility); remainder in cash; no leverage | Moreira & Muir (2017), capped at 1× because this is a cash account |

### Cross-sectional rules — one portfolio across the 11 sector funds
| # | Rule | Exact definition | Source |
|---|---|---|---|
| E | Sector momentum | Each month-end, hold the 3 funds with the highest 12−1 return, equally weighted | Moskowitz & Grinblatt (1999); Jegadeesh & Titman (1993) |
| F | Sector momentum + trend | As E, but a chosen fund is held only while above its 200-day average; otherwise that third sits in cash | Faber (2013) |
| G | Low volatility | Each month-end, hold the 3 funds with the lowest 60-day volatility, equally weighted | Blitz & van Vliet (2007); Baker, Bradley & Wurgler (2011) |

### Event rule — watchlist shares only
| # | Rule | Exact definition | Source |
|---|---|---|---|
| H | Post-earnings drift | Hold for 5 trading days after a results announcement (SEC 8-K item 2.02) | Bernard & Thomas (1989) |

**Benchmarks:** every rule is measured against buy-and-hold of the same fund (or, for
E–G, an equally weighted portfolio of all 11 sectors rebalanced monthly) and against SPY.

**Costs, applied identically to rule and benchmark:** 0.15% of traded value on every
entry and exit (Trading 212 FX conversion). Long or cash only; no shorting, no leverage,
no intraday. Money out of the market earns the 3-month Treasury bill rate.

## 3. Test count (declared in advance)

| Family | Tests |
|---|---|
| Time-series rules A–D × 12 funds | 48 |
| Cross-sectional rules E–G × 1 portfolio | 3 |
| Event rule H × watchlist shares with earnings history | ~1–5 |
| **Total entering the correction** | **~52–56** |

All tests enter **one** Benjamini-Hochberg family. Adding rules later re-corrects
everything, which raises the bar for what already passed — deliberately.

## 4. Evaluation

1. **Held-out sample.** The last 30% of each series, never inspected while building.
2. **Walk-forward.** Expanding window: inspect through year *n*, record year *n+1*, step
   forward one year at a time from the first full year after warm-up. Reported per block
   and combined, so a rule that only worked in one regime is visible.
3. **Reported per rule/fund:** annualised return, annualised volatility, Sharpe against
   cash, worst drawdown, trades, time in market, edge over buy-and-hold.
4. **Luck check:** stationary block bootstrap, 1,000 resamples, mean block 20 days
   (Politis & Romano, 1994) on the daily edge over buy-and-hold; two-sided p-value.
5. **Multiple testing:** Benjamini-Hochberg q across the whole family.

## 5. Pass marks (fixed now)

A rule is **"clears"** — the only status that may be described as usable — when **all** of:
- positive edge over buy-and-hold in the held-out sample, **and**
- q < 0.05, **and**
- positive edge in **more than half** the funds it was tested on, **and**
- Sharpe (after costs) at least as high as buy-and-hold's, **and**
- positive in **at least 2 of 3** walk-forward blocks.

Anything failing any condition is reported as **"does not clear"** and is not tradeable
by this system, however good one number looks.

## 6. What happens with the result

- **If nothing clears:** no execution layer is enabled. The honest conclusion is recorded
  on the Research page, and the practice book plus index funds remain the plan.
- **If something clears:** it may be taken forward to the execution layer, which still
  requires a per-order confirmation click, position and daily limits, and a kill switch.
  No minimum practice period is required (decided 21 September 2026; the
  author's recommendation was 3 months of practice first, recorded here for the file).
- **Either way:** this document and the results stay in the repository, including failures.

## 7. Deliberately excluded

Parameter sweeps (trying 50/100/150/200-day averages and reporting the best), rule
variants invented after seeing results, any rule without published support, shorting,
leverage, intraday trading, and single-stock picks chosen after the fact.

---

Written 21 September 2026, before the first run.
Approved by the account owner, 21 September 2026, with the practice-period requirement removed.


---

# Pre-registration — rule search v2 (extended history)

**Status: PROPOSED, not yet run.** Written after v1 produced no rule that cleared,
and before any rule was tested on the longer history.

## What changes from v1

Only the amount of data. **The rules, their parameters, the universe, the costs, the
statistics and the five pass marks are unchanged.** No rule is added, dropped or
adjusted after seeing v1's results.

- v1 used 12 years (2014–2026), because that was the window the app happened to
  store. That was not a data limit: Tiingo has the sector funds from **22 December
  1998** and SPY from **29 January 1993**.
- v2 uses each fund's full available history. Nine sector funds gain ~16 years,
  including the 2000–02 and 2007–09 bear markets in the inspected portion and the
  2020 and 2022 falls in the held-out portion.
- XLC (from 2018) and XLRE (from 2015) keep their shorter histories rather than
  being dropped, as in v1.

## Why this is a legitimate second look, and its cost

The honest reason for re-running: a 3.6-year held-out window cannot distinguish a
4.7%/yr edge from luck for *any* rule, good or bad. Extending the data tests the same
hypotheses with more power. It is not a new hypothesis chosen because it looked good.

The cost is recorded here: this is a **second look at the same rules**, so the family
of tests grows. Every v2 test enters the Benjamini-Hochberg correction together, and
the v1 results stay in the repository. If sector momentum clears in v2, the honest
description is "cleared on the second, larger test, after failing the first for lack
of data" — not "cleared".

## Pre-committed interpretation

- **If sector momentum clears with the longer history:** it may go to the execution
  layer, which still requires the confirmation click, limits and kill switch.
- **If it does not clear:** no execution layer is enabled and the search stops here.
  A third look with different data would be fishing, and is excluded in advance.
- **If a rule that failed v1 clears only because of the added years:** it is reported
  with both results side by side, never the better one alone.

Written 21 September 2026, before the extended run.


---

# Correction log

## 2026-09-22 — F-05, equal-weight benchmark under-invested

An external review found that the benchmark for the three sector-picking rules
divided by the full list of 11 funds while holding only the funds that existed on
the day. XLRE starts in 2015 and XLC in mid-2018, so before then the benchmark was
9/11 = 81.8% invested with the rest earning cash. That biased the benchmark's
return down and flattered every rule measured against it.

Fixed by dividing by the number of funds actually held. The deliberate cash held by
the trend-filtered rule, which skips a pick that is below its own trend, is unchanged.

Effect, recorded as required:

| Window | Benchmark before | Benchmark after | Sector momentum edge before → after |
|---|---|---|---|
| Inspected years (1999–2018) | +7.12%/yr | **+7.88%/yr** | +0.21% → **−0.56%** |
| Held-out years (2018–2026) | +12.25%/yr | +12.25%/yr | +1.33% → +1.33% |

The reported v2 figures are unchanged, because all 11 funds exist throughout the
held-out window. The inspected years moved by 0.77 points a year, and sector
momentum's edge there is negative once the benchmark is measured properly.

---

# Pre-registration — v3 amendments, 22 September 2026

Written after an external review (`docs/history/REVIEW-2026-09-21.md`), before re-running.
v1 and v2 stay exactly as they were; these changes apply from here on and the previous
results remain in the repository.

## v3-A — correction families (review F-06)

v1 and v2 put all 52 tests into one Benjamini-Hochberg family. The tests are not
independent: the 12 sector funds are slices of the same index over identical days, and
the four time-series rules are variations on one trend/momentum signal. BH stays valid
under that kind of dependence, so this was never a false-positive problem — it was a
power problem, correcting for 52 shots when far fewer were really taken.

From v3, q-values are computed **within three families**: the time-series rules across
funds, the portfolio rules, and the event rule. The number of effectively independent
tests in each family is estimated from the average pairwise correlation of the daily
edge series, m / (1 + (m−1)·r̄), and reported on the Research page beside the q-values.

Measured on the current data: time-series 48 tests ≈ 3.4 independent (average overlap
0.28), portfolio 3 ≈ 1.7 (0.40), event 1. About six real questions, not 52.

The pass marks themselves are unchanged by this amendment.

### v3-A amendment, 22 September 2026 — the effective count is applied, not just reported

The paragraph above said the effective count would be "reported on the Research page
beside the q-values". It was, and the correction went on dividing by every test: 48,
not 3.4. A second external review (G-07) pointed out that publishing a number which
reads like the correction, while a different number does the correcting, is not honest.

From here the estimate is passed into Benjamini-Hochberg as the family size. **This is
a genuine loosening of a pre-registered pass mark, so it is written down rather than
applied quietly.** It makes q-values smaller and a pass easier, which is exactly why it
is recorded with its result attached.

Two guards come with it. A q-value is never reported below its own p-value — with a
family size under the number of tests the arithmetic can produce one, and that would
say the correction had made the evidence stronger. And the estimate can never exceed
the real number of tests, so this can never become harsher than plain BH.

Result after the change: **still 0 of 52.** The smallest q fell from a hard ceiling of
0.048 to 0.0051, but the q-values that fell belong to rules that are significantly
*worse* than buy-and-hold — a two-sided test flags a large negative edge too. The best
candidate, holding the three strongest sectors, sits at q = 0.69 and is nowhere near.

Recorded separately because it matters more than the amendment: before this change the
largest family could not have produced a clearing q **at all**. At 1,000 resamples the
smallest p-value reachable is 1/1001 = 0.000999, so the best q available across 48
tests was 0.048 — inside the 0.05 limit by four percent. Under v1 and v2, which
corrected all 52 together, it was 0.052: **no rule could have cleared, whatever the
evidence.** A test now fails if that combination ever returns.

## v3-B — two tracks, matched to what each paper claims (review F-03)

v1 and v2 required a rule to beat buy-and-hold's **return** and match its return per
unit of risk, together. Two of the eight rules never claimed the first of those:

- Faber (2007) claims a comparable return at materially lower drawdown.
- Moreira & Muir (2017) claim a higher Sharpe explicitly at a **lower** raw return.

Those rules were therefore disqualified for reproducing their source papers exactly,
which tests a hypothesis nobody made.

From v3, every rule declares a `claim` in its definition — `"return"` or `"risk"` —
taken from its source paper and fixed before the run, never from how it performed:

| Track | Rules | First condition |
|---|---|---|
| Return-improving | momentum 12−1, time-series momentum, sector momentum, post-earnings drift | beat buy-and-hold's return out of sample |
| Risk-reducing | 200-day trend, volatility-managed, sector momentum with trend filter, low volatility | cut the worst fall by at least a tenth of it |

The other four conditions are unchanged for both tracks: q below 0.05 within its
family, positive in more than half the funds, return per unit of risk at least
matching buy-and-hold, and ahead in 2 of 3 walk-forward stretches.

This is a genuine loosening for four rules, so it is written down here rather than
applied quietly. Result after the change: still 0 of 52. The risk-track rules do cut
the fall (the three calmest sectors: −28.7% against −36.3% for holding all of them),
and now fail on return per unit of risk and on the luck check instead.

---

## v3-C — the luck check tests the statistic its track is about (review G-06)

**Status: PROPOSED, written before the run.** Approved by the account owner,
22 September 2026. v1, v2, v3-A and v3-B stay exactly as they are.

v3-B gave each track its own first condition and left the second one testing return
for both. A risk-reducing rule was therefore still required to beat buy-and-hold's
return *significantly* — `q` came from a bootstrap of the difference in annualised
return, whatever the rule claimed. A rule reproducing Faber (2007) exactly, the same
return at half the fall, has a return edge near zero, so its p-value is near 1 and it
fails as "edge not distinguishable from luck". F-03 was half-fixed: the first
condition moved to each track's own claim, the second kept testing the thing the risk
track says is irrelevant.

From v3-C, the second condition tests the statistic the track is about:

| Track | Second condition bootstraps |
|---|---|
| Return-improving | the difference in annualised return (unchanged) |
| Risk-reducing | the difference in **Sharpe ratio** |

Both are computed the same way: the rule's day and the benchmark's day are resampled
together in blocks, the statistic is recomputed inside every resample, and the
p-value is two-sided for "the difference is zero". The other four conditions are
unchanged for both tracks.

**Why Sharpe rather than maximum drawdown.** Drawdown would be the symmetric choice,
since the risk track's first condition is a drawdown cut. It is rejected on power:
maximum drawdown is a single extreme order statistic with a heavy-tailed sampling
distribution, so a bootstrap of it has very little power, and in a design whose
corrected minimum detectable effect is already 30%/yr that would make the condition
unpassable rather than correct — trading one wrong answer for another. Sharpe is also
what the sources claim. Moreira & Muir's (2017) headline result *is* a Sharpe
improvement, at an explicitly lower raw return; Faber's (2007) is a comparable return
at a smaller fall, which is the same statement.

**The overlap is acknowledged.** The fourth condition already requires the rule's
Sharpe to be at least buy-and-hold's. Under v3-C the second condition tests whether
that same difference is distinguishable from luck. Size and significance are
different questions, and this mirrors the return track exactly — there the first
condition sizes the edge and the second asks whether it is luck — but it does mean
the risk track is two conditions about Sharpe and one about the worst fall, rather
than three separate things. Recorded because it is a real cost of the choice.

**This is a loosening for the four risk-track rules** (200-day trend,
volatility-managed, sector momentum with trend filter, low volatility). It is written
here before the run, with the result appended below afterwards.

### Result, appended after the run — 22 September 2026

**Still 0 of 52.** The amendment did what it was meant to do and changed no verdict.

Of the 26 risk-track tests, **22 do cut the worst fall by at least a tenth**, so the
first condition is met widely — as the source papers would predict. The second
condition now tests the right statistic, and that is where they fail: only **4 of 26
show any improvement in return per unit of risk at all**, and the best of those is
+0.09 Sharpe with q = 0.48, nowhere near significant.

Six risk-track tests *are* significant at q < 0.05. **Every one of them is significant
in the wrong direction** — a negative Sharpe difference, meaning the rule made return
per unit of risk materially worse on that fund over the held-out years (worst: XLB
under volatility scaling, −0.38 Sharpe, q = 0.004). A two-sided test flags a real
harm as readily as a real benefit, and here it is only finding harm.

So the honest summary of the risk track on this data: these rules deliver the smaller
fall they promise, and pay for it with enough lost return that risk-adjusted
performance does not improve. That is a finding about this universe and window, not a
refutation of the papers — the corrected minimum detectable effect is 30%/yr, and
nothing here is remotely that large.


---

## v3-D — the risk track stops gating on its noisiest number (review H-03)

**Status: PROPOSED, written before the run.** Raised by an external review
(`docs/history/REVIEW-2026-09-23.md`, H-03), not chosen after seeing a result. Approved by the
account owner, 23 September 2026. v1, v2, v3-A, v3-B and v3-C stay exactly as they are.

After v3-C the risk track tested three things, and the one that defined the track was
the only one with no significance test at all:

| Criterion | Statistic | Tested for significance? |
|---|---|---|
| 1 | worst fall vs holding's, must be a tenth better | **No** |
| 2 | Sharpe difference | Yes (v3-C) |
| 4 | Sharpe level vs holding's | No |

Maximum drawdown is the single worst peak-to-trough fall in one realised history — one
extreme value from one path. Two runs of the same process routinely differ by more than
the tenth that criterion 1 tests against, so a risk rule could clear or fail its own
defining condition largely by chance, and nothing in the pass mark measured that.

**From v3-D, criterion 1 stops gating.** The worst fall and the comparison against
holding are still computed and still reported on every rule; they no longer decide
anything. A risk-track rule clears on criteria 2, 3, 4 and 5 — the Sharpe difference
being distinguishable from luck, working in more than half the funds, return per unit
of risk at least matching holding, and ahead in 2 of 3 stretches.

**Why not bootstrap the drawdown instead.** That was the review's other suggestion and
it is the more obvious repair: test the defining condition properly rather than drop it.
It is rejected for the same reason v3-C chose Sharpe over drawdown. An extreme-value
statistic has a very wide sampling distribution, so its bootstrap has very little power,
and in a design whose corrected minimum detectable effect is already 18%/yr the
criterion would fail nearly every rule regardless of merit. That replaces "clears at
random" with "never clears", which is not more correct — it is differently wrong, and
harder to notice.

**What this costs, stated plainly.** The risk track no longer requires a smaller fall.
Faber (2007) claims specifically a comparable return at a materially smaller drawdown,
and after this amendment a rule reproducing that claim is judged on its risk-adjusted
return rather than on the fall itself. The two are related but not the same, and this
pass mark now tests the better-behaved of them rather than the one the paper leads with.
That is a real narrowing of what "risk-reducing" means here.

**This is the third loosening in two days**, after v3-A applying the effective test
count and v3-C changing which statistic is tested. Each was argued separately and each
is recorded with its result, but every one has moved in the same direction. The pass
mark now in force is materially easier than the one v1 committed to. Nothing has
cleared under any of them, so no false positive has been bought — but if something ever
does clear, the honest description is "cleared under a pass mark amended three times,
each time downward", and this paragraph exists so that description is available.

### Result, appended after the run — 23 September 2026

**Still 0 of 52,** as expected: 22 of the 26 risk-track tests already met the criterion
that was removed, so dropping it changed no verdict. The risk track continues to fail
on the Sharpe test — only 4 of 26 improve return per unit of risk at all, and the six
that reach significance do so in the wrong direction.

## 2026-09-25 — rule H's sample, frozen (S-16)

**A clarification of section 3, not a new hypothesis.** Section 3 declared rule H on
"watchlist shares with earnings history", "~1–5" tests, and "~52–56" in total. The run
of record on 23 September had one such share, AMD: 52 tests. The code took the sample
from the watchlist at every run, so it moved with the list. When the list grew to eight
companies (six of them test tickers added on 24 September), a re-run tested 59 pairs,
outside the declared range. Some of those shares were chosen knowing how they had done.
This is the hindsight that section 1's "never the watchlist" exists to prevent, and rule
H was the one place the section did not reach.

**From 25 September, rule H is tested on AMD only**, the share of the run of record,
written in code as `research.EVENT_SAMPLE` (one of the reviewer's two
options). Following or dropping a company no longer changes any test. AMD's results
days come from the filings store while AMD is followed, and are kept in research.json,
so dropping AMD keeps the days already found (later ones are not added). The count is
52 again, inside the declared range.

**What this does not freeze.** The data keeps growing, as for every other test. Since
the run of record, AMD's price history was refetched back to 1991, which moved its
held-out split from February 2023 to March 2016. Rule H's p-value went from 0.11 to 0.03
on the same 24 results days: the edge is now distinguishable from zero, but negative.
Holding only in the five days after results trails holding AMD by about 65% a year.

**Why not the alternative.** The reviewer also offered retiring rule H from the tested
family, since one share with about 24 events cannot clear any pass mark. That is a
change to the tested family made after seeing results. Since v3-A the event rule is its
own correction family, so it adds nothing to the other rules' corrections. Freezing it
costs nothing and keeps section 3's declared count.

### Result, run on 25 September 2026

**Still 0 of 52.** Rule H on AMD fails four of the five pass conditions: behind
buy-and-hold out of sample, not working in more than half its sample, a worse return per
unit of risk, and ahead in fewer than 2 of 3 stretches.

## 2026-09-25 — S-26, rule H's "more than half" was counted over the funds

Section 5 requires a positive edge "in more than half the funds it was tested on". The
code counted each rule's positive results over the fund universe only. Rule H never
runs on a fund, so its count was 0 of 0 and it failed this condition whatever it did:
a rule H that worked could never have cleared. This is an implementation fault, not an
amendment. The condition is now counted over the rows each rule ran on: the funds for
A–D, the frozen shares for H.

**Result: still 0 of 52.** On AMD, rule H is positive in 0 of its 1 share, so it fails
the condition on its own results now, not by construction, along with three others.
