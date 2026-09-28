# Theses — the rules, fixed before any is written

`PREREGISTRATION.md` holds the desk's own rule search to what was written before the
results. This document does the same for the user's judgement (fourth review,
Phase 9). It is committed before the first thesis exists, and `PREREGISTRATION.md` is
not changed by it.

## What a thesis is

Before a covered company reports, the user writes, about the quarter it is about to
report:

| Part | Scored? |
|---|---|
| Revenue up or down, against the same quarter a year before | yes |
| Roughly by how much, in % (optional) | no: reported beside the outcome |
| Operating margin up or down, against the same quarter a year before | yes |
| One line of reasoning | required, not scored |
| A confidence from 50% to 95% that both directions are right | the probability scored |

The operating margin is used rather than the gross margin because more companies report
operating income; Starbucks, for one, reports no gross profit.

## When one can be written

- A thesis names the first quarter after the latest one the desk holds.
- Only while that quarter's results are not yet due. On or after the announced date it
  is refused, since the outcome may already be public.
- Not when the company has filed a quarterly or annual report after the one that reported
  the latest quarter the desk holds: that quarter's successor is already public, and the
  SEC's figures have not caught up. Added on 25 September 2026 (S-21), before any thesis
  had been written. Coca-Cola's June quarter was filed on 29 July but was not in the SEC's
  data on 25 September. JPMorgan's quarterly figures stop in 2014. Both were offered a
  thesis that could only ever be void.
- One per company per quarter, written once. There is no edit and no delete. It is a record of what was thought before the outcome was known.

## How it is scored

- When the quarter's figures arrive, revenue and operating income are compared with the
  same quarter a year before (the quarter ending 350–380 days earlier).
- A thesis is right when both directions are right, and wrong otherwise.
- It is void, and never scored, when the quarter's figures were already public before the
  thesis was written. That can happen when the desk's figures had not been refreshed; the
  first filing date of each quarter is stored to catch it.
- It is not scored, and says why, when the figures needed are not in the company's tagged
  filings.

## What is reported

- **The Brier score** (Brier 1950): the mean of (confidence − outcome)², where the outcome
  is 1 if right and 0 if wrong. 0 is perfect. Saying 50% every time scores 0.25.
- **Calibration**: stated confidence in bands of ten points (50–60, 60–70, 70–80, 80–90,
  90–95). For each band, how often the user was right, with the exact interval from
  `uncertainty.py` drawn against the mean confidence stated in that band. A band reads
  over- or under-confident only when its interval excludes what was said. Ten theses prove
  nothing, and the intervals say so.

## What it is not

It scores the user's forecasts of a company's own reported figures, not trades or
prices. Nothing here is a recommendation.
