# Where the desk's numbers come from

Every number on the desk that could steer a decision, with the study it comes from, or marked
plainly as the desk's own choice and why. Written on 28 September 2026, so that every number
follows the most accurate studies there are.

## What the research says matters most

No study promises a return, and the most careful ones say the edges are small.

- **Published effects shrink.** Across 97 findings, returns were 26% lower out of sample and
  58% lower after publication (McLean & Pontiff 2016, *Journal of Finance*).
- **Most findings do not survive a strict re-test.** With the NYSE's breakpoints and size
  weights, 65% of 452 failed a t-value of 1.96, and 82% the multiple-testing hurdle of 2.78
  (Hou, Xue & Zhang 2020, *Review of Financial Studies*). Those that survive cluster in value,
  momentum, profitability and investment. Only 4% of the trading-friction group survived.
- **What does survive falls into themes.** Most of 153 factors replicate, in 93 countries, and
  fall into thirteen themes. Ten of them carry significant weight in the best combination of
  all; profitability, investment and size do not, once the others are held (Jensen, Kelly &
  Pedersen 2023, *Journal of Finance*).
- **For one investor, how they trade matters more than any of these.** Households that traded
  most earned 11.4% a year against the market's 17.9% (Barber & Odean 2000). The desk
  measures the user's own turnover beside that finding (Trades → Your habits).

## The desk's rating (`rating.py`, definition `2026-09-28b`, set out in `docs/RATING.md`)

| Number | Source |
|---|---|
| Four themes, equal weights: Value, Momentum, Quality, Accruals | Jensen, Kelly & Pedersen (2023): four of the ten themes with significant weight in the tangency portfolio. Equal weights, as none is fitted to the desk's own data; one score across themes, not a mix of separate picks (Fitzgibbons, Friedman, Pomorski & Serban 2017) |
| Each measure's theme | Jensen, Kelly & Pedersen's published cluster labels (`be_me`, `chcsho_12m` Value; `ret_12_1` Momentum; `gp_at` Quality; `oaccruals_at` Accruals) |
| Book to market, at the latest price | Fama & French (1992); a timely price, Asness & Frazzini (2013), whose timely value earned 3.05–3.78% a year of alpha over the standard measure |
| Share count change, split-restated | Pontiff & Woodgate (2008) |
| Momentum: month −13 to month −2 | Jegadeesh & Titman (1993); the latest month left out because a month's move tends to reverse (Jegadeesh 1990) |
| Gross profit to assets | Novy-Marx (2013); held in Hou, Xue & Zhang (0.38% a month, t = 2.62) |
| Accruals: earnings less operating cash flow, over assets | Sloan (1996), in the cash-flow form of Hribar & Collins (2002) |
| NYSE breakpoints; over-the-counter shares not rated | Fama & French (2008); Hou, Xue & Zhang (2020) |
| Thirds: top Buy, bottom Sell | Jensen, Kelly & Pedersen build every factor from the top third against the bottom third |
| Asset growth, F-score, low risk left out | Their themes are displaced (Jensen, Kelly & Pedersen 2023); the F-score is weakest among large, size-weighted companies; low risk is contested (Hou, Xue & Zhang 2020; Novy-Marx & Velikov 2022) |
| Banks, insurers and property companies not rated | The papers' own exclusion: the measures were built on industrial companies |
| Sample of 200, drawn once | The desk's choice, within Tiingo's free budget: a third's breakpoint to about ±3 places in a hundred (one standard error, 3.3) |
| Price measures wait for 3 in 4 of the sample | The desk's choice: at 150, about ±3.8 places |
| A rating needs 3 of 4 themes | The desk's choice |
| Scored at 3, 6 and 12 months, with exact intervals | Horizons of the papers' holding periods; Clopper & Pearson (1934); Benjamini & Yekutieli (2005) for records read side by side |

## The rule tests (`research.py`, `PREREGISTRATION.md`)

| Number | Source |
|---|---|
| 70% to learn, the last 30% held out and alone reported | Pre-registered before the run |
| p-values from a stationary block bootstrap | Politis & Romano (1994) |
| Corrected for testing many rules; "clears" at q < 0.05 | Benjamini & Hochberg (1995) |
| Costs: 0.15% a side | Trading 212's currency conversion fee, a plain fact; cash earns the 3-month Treasury bill rate (FRED DTB3) |

## News, moves and filings

| Number | Source |
|---|---|
| A story counts when it names the company in the headline or first 25 words | Tetlock, Saar-Tsechansky & Macskassy (2008) |
| A day's move is unusual outside the 95% range of the shares' own moves against the market over the 250 trading days before | MacKinlay (1997), the market model's estimation window |
| A past reaction counts only outside the last one's longest window | MacKinlay (1997): overlapping windows are one price move |
| A reaction's window opens at the close before the first session the filing could move, by its acceptance time | MacKinlay (1997): the event's own day is in the window |
| News never enters the rating | The evidence on news tone is about days (Tetlock et al. 2008; Heston & Sinha 2017); the rating's is about a year |

## The company card

| Number | Source |
|---|---|
| Piotroski F-score, its nine signals | Piotroski (2000) |
| Altman Z'': above 2.6 safe, 1.1–2.6 grey, below 1.1 distress | Altman's own cut-offs for Z'' (1993, 2000) |
| Analysts' ratings shown with their bias to "buy" | Barber, Lehavy, McNichols & Trueman (2001) |
| Estimates drift down before results | Richardson, Teoh & Wysocki (2004) |
| The price against its own five years of earnings | A plain fact, the desk's window; no study finds a company's own P/E history predicts its return |

## The screener's published screens (`screen.PRESETS`)

| Screen | Source |
|---|---|
| Gross profitability, the NYSE's top third | Novy-Marx (2013); the cut is computed from the NYSE's companies on the day |
| Four of Piotroski's nine signals | Piotroski (2000): his own zero lines |
| Graham's defensive criteria | Graham (1973), a book's rules, not a finding tested on returns: $100m of 1972's sales ($760m today by the CPI-U, 41.8 in 1972 against 317.7 in 2025), a current ratio of 2, long-term debt no more than working capital |
| Dividends covered by free cash flow | Arithmetic: below 1 the dividend is not funded by the business |

## Your trading and your account

| Number | Source |
|---|---|
| Turnover: each month half the sales turnover and half the purchase turnover, the shares sold that month and bought the month before, matched to the holdings at its start, at that day's prices, over their value; twelve months averaged, times twelve | Barber & Odean (2000), section I.B, beside their 75% a year average; with a line listed elsewhere held, over the US lines, as their households held US common stocks |
| Gains against losses sold (PGR, PLR), each holding against its average purchase price | Odean (1998), beside his 14.8% and 9.8% |
| What replaced a sale: a purchase within 21 days, followed for 252 trading days | Odean (1999) |
| Returns money-weighted, never annualised under a year | GIPS |
| A yearly money-weighted rate is stated only once the money has been at work for a year, and a return for under a year only if it was at work for half of it; money is at work while the net put in stands at a tenth of its highest or more (`build_desk.MWR_AT_WORK_SHARE`, `days_at_work`) | The year is GIPS's. The tenth and the half are the desk's choice, a guard and not a finding: an account that sat at pence for two years with money passing through it for weeks read +4299.8% a year, a rate resting on the pence that stayed. The rate is withheld with its reason, never shown beside a warning |
| The S&P 500 with the same money on the same days | A plain comparison: SPY's total return |
| History's rebuilt years used while today's rebuild ties to the broker's total within 1% | The desk's choice, a check on the data, not a finding |
| The performance chart: one point a week (`history.CURVE_STEP_DAYS`), the last point the broker's own total; weeks with no close left out, and the line withheld if more than a fifth are (`CURVE_MOST_SKIPPED`) | The desk's choice, a display resolution and a guard, not a finding. It is drawn only while History's check above passes |
| The chart's candles are restated for splits and not for dividends; a live chart asks again every 3 minutes (`charts.EVERY_MINUTES`) and may use 24 of Tiingo's 50 requests an hour and 300 of 1,000 a day (`CHART_PER_HOUR`, `CHART_PER_DAY`) | The desk's choices, none a finding: the price as it was quoted is what a quote screen shows, and the allowance is shared with the company update, which keeps the rest |
| The Ask chat: at most 100 questions a day, answers under 110 words, the last 6 turns sent with each question, a company's last 5 sessions of headlines | The desk's choices, to bound what a stray loop can cost and keep answers short; no number in an answer is the model's: each is a figure the desk gave it |
| A company's news is asked again no sooner than 45 minutes after it was last asked (`headlines.ASK_AGAIN_MINUTES`), the button's update excepted | The desk's choice, to spare the sources: the company data updates every half hour, and the evidence on news is about days (Tetlock, Saar-Tsechansky & Macskassy 2008; Heston & Sinha 2017), so a story reaches the page within the hour, not the half hour |
| How rough the ride was: a week's return by Modified Dietz, what was put in counted for half the week (`history.RISK_FLOW_WEIGHT`), applied to the account and to the S&P 500 with the same deposits alike | Bank Administration Institute (1968), a method the GIPS standards allow; half a week is the average for a deposit on an unknown day |
| A week with more than half the account put in at once is left out of the swing and the beta (`history.RISK_MAX_FLOW`) | The desk's choice: the half-week assumption matters most there. A test against the simulation's daily truth keeps the two within a hundredth |
| At least 52 whole weeks before the swing, worst fall or beta is shown (`history.RISK_MIN_WEEKS`) | The desk's choice: a year. With fewer, the beta's interval is too wide to say anything |
| Weekly swing made a year's by the square root of the weeks in a year | The usual convention, exact for independent weekly returns; a description, not a forecast |
| The beta and its interval: a least-squares slope with Student's t on n − 2 degrees of freedom (`uncertainty.slope`, `t_quantile`) | Standard regression; the t series is Abramowitz & Stegun (1964) 26.7.5, checked in the tests against the published table |
| What the holdings lean toward: each theme's place averaged by value held (`rating.tilt`) | A description of the holdings under the rating's own places, not a finding and not a signal; the middle is 50 by how places are made |

## Checks on the data, the desk's own tolerances

| Number | Why |
|---|---|
| Shares rebuilt from the trades agree with the broker's within 0.0001 of a share | Fractional fills are rounded in the record |
| Cash, total and closed gains agree within 1% of the account | As History's check: rounding and a day's price move less than this; a missing record more |
| The desk's latest close within 10% of the broker's price | More than a usual day's move: a split missed or a ticker read as another company |
| A quote 25% or more from the close is flagged | A split overnight reads as -50% until a close has it |

## Built on purpose, not on research

These steer nothing about what to buy: how often the company data updates (30 minutes), how
many items a list shows, how long a visit lasts, a plan matched to a trade within 7 days, a
week of news in a brief. Each is labelled in the code as the desk's choice.

## What the evidence suggests, not built yet

- **Momentum scaled by its own recent volatility.** Barroso & Santa-Clara (2015) nearly doubled
  momentum's Sharpe ratio (0.97 against 0.53) by scaling it down when its last six months were
  volatile; Daniel & Moskowitz (2016) found its crashes follow market falls and high volatility.
  It needs a history of the sample's momentum returns the desk does not yet keep.
- **Debt issuance and low leverage**, two more of the ten themes, need filing figures the
  desk's universe does not yet fetch.
- **Low risk** will be added if the careful re-tests come to agree.
