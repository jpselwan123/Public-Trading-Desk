# The desk's rating: its definition, and how it will be judged

Definition `2026-09-28b` (`rating.METHOD`). First written on 27 September 2026, before any
rating under it had been given, and before any of its results could be seen; changed twice on 28
September (below), with no result yet to see. What counts as the rating working is set here,
so it cannot be chosen later to fit what happened.

## What it is

Five measures in four themes, from the most accurate studies there are. The two most thorough re-tests of published findings are
Hou, Xue & Zhang (2020, *Review of Financial Studies*), who re-ran 452 anomalies with the
NYSE's breakpoints and size weights and found 65% fail, and Jensen, Kelly & Pedersen (2023,
*Journal of Finance*), who found that most of 153 factors replicate, that they fall into
thirteen themes, and that ten of the themes carry significant weight in the best combination
of all of them (the tangency portfolio); profitability, investment and size do not, once the
others are held. The rating takes the four of those ten the desk's data measures well, through
measures that also held in Hou, Xue & Zhang (gross profitability, for one, earned 0.38% a month
from the top tenth to the bottom there, t = 2.62):

| Theme | Measure | Better when | Paper | Needs |
|---|---|---|---|---|
| Value | Book to market, at the latest price | higher | Fama & French (1992); Asness & Frazzini (2013) | a price |
| Value | Share count change (weighted average, split-restated) | lower | Pontiff & Woodgate (2008) | filings |
| Momentum | The year to the month before last | higher | Jegadeesh & Titman (1993) | a price |
| Quality | Gross profit to assets | higher | Novy-Marx (2013) | filings |
| Accruals | Earnings less operating cash flow, over assets | lower | Sloan (1996) | filings |

Each measure's theme is the one Jensen, Kelly & Pedersen assign it (their published cluster
labels: `be_me`, `chcsho_12m` Value; `ret_12_1` Momentum; `gp_at` Quality; `oaccruals_at`
Accruals).

- Each measure places a company from 0 to 100 against NYSE-listed companies, the
  breakpoints the papers use (Fama & French 2008; Hou, Xue & Zhang 2020).
  Over-the-counter shares, banks, insurers and property companies are not rated.
- The two price measures are placed against a **fixed random sample** of 200 NYSE
  companies (`rating.SAMPLE_SIZE`, seed `rating.SAMPLE_SEED` = 20260927). They are drawn
  once from the NYSE companies the rating can rate on their filings, at the first company
  update with the exchange list, and kept in `rating_sample.json`. The desk can price a
  few hundred companies a month on Tiingo's free key, not the NYSE's thousands. A sample
  of 200 puts each third's breakpoint within about three places in a hundred.
- A price measure places no one until three in four of the sample have it
  (`rating.SAMPLE_READY`: 150 of 200). Until then every company is rated on the others.
- A theme's place is the average of its measures' places, and the themes are averaged with
  equal weights (no weight fitted to the desk's data; one score across the themes rather than
  separate picks mixed, which Fitzgibbons, Friedman, Pomorski & Serban 2017 found does better
  for a long-only investor). The average is placed among the companies resting on as many
  themes (only the sample's, when a price measure is among them), and cut into thirds: the
  top third is Buy, the bottom third Sell, the middle third Hold. Thirds are how Jensen, Kelly
  & Pedersen build every factor: the top third of companies on a measure against the bottom.
- A company needs three of the four themes. With no price, the filing measures give three.

**Left out, and why.** Asset growth (Cooper, Gulen & Schill 2008) and the Piotroski F-score
(Piotroski 2000) were in the definitions before 28 September: their themes, investment and
profitability, are displaced in Jensen, Kelly & Pedersen's combination, and the F-score's own
evidence is weakest among large companies weighted by size. Low risk (low beta, low
volatility) is one of their ten themes, but the other careful re-tests disagree: 96% of the
trading-friction anomalies, where volatility and beta sit, failed in Hou, Xue & Zhang, and
Novy-Marx & Velikov (2022) traced betting against beta's returns to effectively equal-weighting
the smallest companies. The desk adds it only when those agree. Debt issuance, low leverage,
profit growth, seasonality, short-term reversal and skewness are not measured by the desk's
data, or pay over weeks, not the year a rating is held.

## How it will be judged

**The record that counts is the fixed sample's.** These are companies nobody chose, rated
every time their rating changes and scored against the S&P 500 from the first close after
the day (`rating.record(..., "sample")`). The user's own companies have their own record
beside it, but it is not the test: they were chosen, and there are few of them.

**The test is at six months (126 trading days):**

1. Buy-rated sample companies beat the market in more than half of their ratings, and
   the page's interval for that share lies wholly above one half.
2. Sell-rated sample companies beat the market in fewer than half, with the interval
   wholly below one half.
3. The median lead of the Buys is above the median lead of the Sells.

All three are required. The intervals are those the page shows, at the family level for
records read side by side (`uncertainty.family_level`). Three and twelve months are shown
too, but neither decides it.

**Until all three hold, the rating is described as not yet shown to work.** Expect that
to last a long time. The premiums in these papers are a few percent a year. With about
sixty Buys and sixty Sells at a time, six months is one draw of a noisy premium, and it
can take years of them to tell one from luck.

## Changes

Any change to the measures, their weights, the breakpoints or the sample is a new
dated `rating.METHOD` with its reason. Ratings logged under an earlier definition stay in
the log, unedited and unscored. If `rating_sample.json` is ever lost, the new draw is a
new sample, dated when it was drawn. The earlier sample's entries stay in the log.

- **2026-09-28.** Value and momentum are placed only once three in four of the sample have
  them. Under `2026-09-27` they were placed against however many of the sample were priced,
  two or more, and the sample is priced a few dozen companies an hour: the first ratings
  with a price would have rested on a handful of other companies. The user's card showed
  the two waiting ("no sample yet") while the sample was being priced. Nothing else
  changed, and no result under `2026-09-27` could yet be seen: its first six-month score
  was due in March 2027.

- **2026-09-28b.** The measures are grouped into Jensen, Kelly & Pedersen's (2023) themes and
  the themes, not the measures, averaged with equal weights; asset growth and the F-score are
  left out, their themes displaced in that paper's combination; the average is cut into thirds,
  as that paper builds every factor, not fifths. Under the definitions before, value counted twice
  (book to market and share issuance are both its measures) and two measures came from
  displaced themes. How the rating is judged, above, is unchanged, and no result under
  `2026-09-28` could yet be seen.
