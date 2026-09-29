# The accuracy audit of 28 September 2026

The question: is every figure as accurate as it can be, when someone relies on it with real
money?

Every number the desk shows was checked against an independent calculation, not against the
desk's own code. This page says what was checked, how, what was wrong and is now fixed, and what
cannot be proven from here.

## How it was checked

- **A simulated account whose truth is known** (`tests/ledger.py`). It lives day by day for nearly
  four years in dollars, euros or pounds: deposits, withdrawals, purchases and sales with the
  0.15% currency fee, dividends with 15% withheld, interest on cash, a 4-for-1 split, a 1-for-3
  reverse split and a London line. It writes out what Trading 212, Tiingo and FRED would give,
  and keeps its own truth: the value every day, every sale's result, what the S&P 500 would have
  done. The desk reads the records and must arrive at the truth. 24 accounts, in
  `tests/test_audit.py`.
- **Values computed elsewhere.** SciPy 1.17 for the statistics, the papers' own tables
  (Newcombe 1998, Conover 1999), Excel's XIRR example for the money-weighted return. They are
  written into the tests, so the desk still has no dependencies.
- **Simulated sources.** Tiingo restating its adjusted closes after each dividend and split,
  across 40 histories and many small updates; NVIDIA's EPS filings around its 2024 split.
- **The page itself.** Built from simulated accounts in three currencies, opened in Chromium,
  and every History cell read off the screen and set against its data.
- **Checks on the real account, at every build** (`checks.py`, new): see below.

## What was wrong, and is fixed

Most serious first.

| What | How wrong | Fixed in |
|---|---|---|
| **EPS across a split.** Twelve months' EPS summed quarters as each was filed, some in old shares and some in new. | After NVIDIA's 10-for-1 split its twelve-month EPS read over $17, not $2.54; its P/E about 8, not about 50. Any split, for up to a year. | Audit D |
| **Market value across a split.** Today's price times the share count on the last filing's cover, in the shares before a split since. | Market value, P/E, price to book and the rating's book to market out by the split factor until the next filing. | Audit D |
| **A closed trade's result** was worked out in the share's currency, not the account's. | Up to 43 points off in a euro account. | Audit A |
| **Turnover** divided a month's purchases by the holdings before them. | Money put in and invested in a small account read as many times its turnover. Now Barber & Odean's own definition. | Audits A, B |
| **The money-weighted return** had no answer when more had been taken out than put in, above 1,000% a year, or below −99.99%. | No return shown for, say, 10% in a fortnight or an account that took profits out. Now solved exactly. | Audit B |
| **Past reactions to filings** measured from the close on the filing's day. | A morning's results moved that day's session, which was left out. Now from the close before. | Audit C |
| **The trade check** read a US company's rating for a London line held under the same letters. | The wrong company's rating. | Audit A |
| **Gains and losses sold** (Odean) set a holding against its first lots' price after a partial sale. | A different reference from Odean's and Trading 212's average price. | Audit B |
| **The year against the market** used the S&P's newest close even when the share's was older. | The two returns over different days. | Audit C |
| **A quote the morning after a split** read as a fall. | −50% for a 2-for-1 split. Now flagged: "check it in" the broker. | Audit C |
| **Two trades in one second** sorted arbitrarily; **London and US lots** could mix; **the practice book** ignored a split between two trades; **the S&P beside a year** opened on the wrong day; **prices** carried no currency on the page. | Smaller, each fixed and tested. | Audits A, F |
| `screen.py --price` | Could not run (read three fields of Tiingo's four). | Audit D |

## What was checked and found right

- **The account**: total, cash, deposits, withdrawals, fees, withheld tax, dividends, interest,
  the S&P 500 with the same money, every year's value, return and S&P return in History: equal
  to the truth in all 24 accounts.
- **Statistics**: the exact interval, the sign test, the median interval, Newcombe's difference,
  Benjamini–Hochberg and the family level agree with SciPy and the papers to 1e-12; the median
  interval covers 95% or more in simulation at every size.
- **Prices**: the stored adjusted closes equal Tiingo's whole restated history to 1e-15; every
  split kept; momentum reads month −13 to month −2.
- **The rating**: its five measures, their directions, the ranking; Piotroski's nine signals;
  Altman's Z'' weights and cut-offs.
- **The page**: all 132 History cells in three currencies equal their data.

## Checks on your real account (new)

Tests can only prove the arithmetic on simulated records. Whether the desk reads your real
records rightly is checked on them, at every build, and shown on the Overview as **Checks against**
your broker (for a CSV export, which states no totals, they cannot run):

| Check | Rebuilt from your records | Against the broker's |
|---|---|---|
| Shares | every fill, splits counted | the shares it holds |
| Cash | every deposit, withdrawal, trade, dividend, interest payment and fee | its cash |
| Total | the shares at its prices and the rebuilt cash | its total |
| Closed gains | each sale's gain | its closed gain |
| Holdings | the holdings' values | its invested figure and total |
| Prices | the desk's latest close of each US holding | its price, within 10% |

Each says "agrees" or names what does not, as a share of the account. `python3 doctor.py` prints
the same, without amounts or holdings, so it can be pasted. **If any says "does not agree", check
the figure at your broker before relying on the desk's.**

## What cannot be proven from here

- **The real formats.** A development container may not reach the brokers, the SEC or Tiingo. The desk
  reads them as their documentation and past answers describe; the checks above and `doctor.py`
  test that reading on your machine.
- **Lines listed outside the US** have no daily closes in the desk (Tiingo covers US shares).
  While one is held, History cannot rebuild that year's value and says so; turnover is measured
  on your US shares and says so.
- **The share count's date** is kept from the next universe build (monthly, on the Mac). Until
  then a count is dated at the end of the year it was read for; a split in the weeks between that
  day and the filing could be counted twice. The float check still catches a gross error.
- **Published findings shrink** (McLean & Pontiff 2016). The rating's measures are the
  best-replicated there are; that is not a promise about any one company.

## Choices kept, and why

- The rule tests' p-value (the centred bootstrap) and interval (percentiles) are computed two
  ways, as pre-registered; they can differ at the edge. Nothing has come near clearing.
- The rule tests correct for an effective number of tests, which is less strict than
  Benjamini–Hochberg's own count; with the full count, still 0 of 52 clear.
- Piotroski's and Altman's ratios use each year's closing assets where the papers used the
  opening or average; this can move a borderline signal, never the direction of a ratio.
- A day's move is "unusual" beyond 1.96 of its own standard deviations (MacKinlay 1997); share
  moves have fat tails, so somewhat more than one day in twenty is marked.
- Closed trades are matched first in, first out; Trading 212 uses the average price. The page
  says so.

## Second audit, 29 September 2026: security, privacy and the public copy

The first audit was about numbers. This one asked whether the desk is safe to point at a
brokerage account, and whether this public copy is the private desk with only the order code
and the personal context taken out.

**How it was checked.**
- A clean clone of the public repository, run the way the README says: all tests on Python 3.9,
  3.10, 3.11, 3.12 and 3.13, then `./desk.sh --demo`, then `git status` to see what a run leaves
  behind (nothing).
- Static analysis of both codebases (undefined names, syntax, unused code; the page's scripts as
  one program). Every page element the scripts look up exists.
- The two codebases compared by structure, ignoring comments and docstrings: only 8 Python files
  differ in code, and every difference is the order path, a name, or this desk's first-run card.
  The test suites compared by name and body: the tests only the private desk has are about
  orders, or are its twins of tests this desk has under another name. The fixes below were made
  in both.
- A live server sent hostile requests: another site's Host and Origin, DNS-rebinding names,
  path traversal, oversized and malformed bodies, bad dates. Every one was refused.
- A full simulated update run under seven failure modes with recognisable fake keys set, then
  every file the desk writes, its output and its report searched for the keys: none found.
- A real browser loaded the page built from poisoned inputs (attack text in every name, headline,
  label, note, currency and link a broker or a news feed can supply).

**What was wrong, and is fixed.**

| Found | Why it mattered | Fixed |
|---|---|---|
| The page fetched two web fonts from Google each time it opened. | A page showing an account made a request to a third party. | Uses the system's fonts; a test fails if the page loads anything from outside. |
| A currency code the browser did not recognise was printed into the page unescaped, and nothing checked what a broker file called a currency or a symbol. | A hostile CSV could have injected script into the page. It was the only path found. | The fallback is escaped; currencies, symbols and markets are checked where a broker's data is read, with the line number. |
| The list of keys blanked from errors (and from the `doctor.py` report meant for pasting) named Trading 212's, Tiingo's, Finnhub's and OpenAI's, not Alpaca's or Interactive Brokers'. | An error quoting one of them would have shown it. None does today. | All are listed, and a test ties the list to the broker registry. |
| Files holding holdings, follow lists and trades were readable by other users of a shared computer. | Only the account file and the notes were private. | Every file is written readable by its owner alone; a test stops any other way of creating files. |
| A desk with no keys reported ten red failures. | To a newcomer it looked broken, and it made a broker sound compulsory. | A key not added yet is a step to take, said calmly, and the desk says plainly that it works with no broker. |

**Not a finding, but worth saying.** The page inserts some strings from Python as HTML (interval
wording, fixed labels). Those are built from numbers and constants, never from outside text;
every piece of outside text goes through `esc()`.
