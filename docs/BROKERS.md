# Connecting your broker

The desk was built on Trading 212, and Trading 212 stays its default. It can also read an
account at **Alpaca**, at **Interactive Brokers**, or at **any broker that lets you download
your history as a CSV file**. Every page, figure and check works the same whichever broker
the account comes from.

The desk is **read only** with every broker: it never places, changes or cancels an order.

Choose the broker in `.env`:

```
BROKER=trading212     # the default, when BROKER is not set
BROKER=alpaca
BROKER=ibkr
BROKER=csv
```

Then press the round sync button, or run `./refresh.sh`. `python3 doctor.py --account` says
whether the broker answered.

## Trading 212

As before: `T212_API_KEY`, `T212_API_SECRET` and `T212_ENV` (see `.env.example`). Nothing about
it changed.

## Alpaca

1. In Alpaca's dashboard, generate an API key pair. For a paper account, switch to Paper first.
2. In `.env`:
   ```
   BROKER=alpaca
   ALPACA_API_KEY=...
   ALPACA_API_SECRET=...
   ALPACA_ENV=live        # or paper
   ```
3. Press sync.

The desk reads three things: the account (cash and value), the positions, and every account
activity (fills, dividends and the tax withheld from them, deposits, withdrawals, fees,
interest). **Alpaca's keys can also place orders.** The desk's Alpaca client can reach only those
three read paths, and a test holds it there. Still, keep `.env` private.

## Interactive Brokers

IBKR's Flex Web Service gives reports, never trading access.

1. In the Client Portal, go to **Performance & Reports → Flex Queries** and create an **Activity
   Flex Query** with these sections:
   - Account Information
   - Open Positions
   - Trades (executions)
   - Cash Transactions
   - Cash Report
   - Net Asset Value (NAV) in Base

   For the period, choose the last 365 calendar days. Keep the default date format.
2. Under **Flex Web Service Configuration**, turn the service on and generate a token.
3. In `.env`:
   ```
   BROKER=ibkr
   IBKR_FLEX_TOKEN=...
   IBKR_FLEX_QUERY=...    # the query's number, shown beside it
   ```
4. Press sync. IBKR takes a few seconds to make the report, and the desk waits for it.

Everything is read in the account's base currency, each amount through IBKR's own exchange rate.

**Older history.** A Flex query reaches back one year. The desk keeps what every sync has read,
so the history grows from your first sync. To bring in earlier years, set the query's period to
each earlier year in turn (a custom date range) and sync once for each, then set it back to the
last 365 days. Until the whole history is in, the check "each holding's shares" says so.

Stocks and ETFs are read. Currency conversions inside the account are left out: they change
nothing in the base currency. Options and futures are not read, and an account holding them will
not tie in the checks.

## Any other broker: a CSV export

Download your account's **whole** history from your broker as a CSV file: every year, every kind
of transaction. Save it as `account.csv` in the desk's folder, or put several files in a folder.
Then set:

```
BROKER=csv
BROKER_CSV=account.csv       # a file, or a folder of .csv files read together
BROKER_CURRENCY=USD          # the account's currency
BROKER_NAME=Fidelity         # optional: the name the page uses
BROKER_CSV_DATES=dmy         # only if dates are written with slashes: dmy or mdy
```

Press sync to read it. Press it again after saving a newer export.

### The columns

The desk reads one plain layout. Your broker's own column names are accepted where they are the
usual ones: *Trade Date*, *Action*, *Ticker*, *No. of shares*, *Price / share*, *Net Amount* and
the like. Otherwise, rename the headers in a spreadsheet.

| Column | What it holds |
|---|---|
| `date` | `2024-01-15`, or `2024-01-15 14:30` |
| `type` | `buy`, `sell`, `deposit`, `withdrawal`, `dividend`, `interest`, `fee`, `tax` |
| `symbol` | the ticker, for a trade or a dividend |
| `market` | where the line trades: `US` (the default), or `LSE`, `XETRA`, ... |
| `quantity` | shares bought, sold, or paid a dividend on |
| `price` | a share's price, in its own currency |
| `currency` | that price's currency (the account's, if left out) |
| `amount` | the money that moved, in the account's currency: what a purchase cost with its fees, what a sale or a dividend brought in, a deposit, a withdrawal, a fee |
| `fee` | a trade's fees, in the account's currency (already in its amount) |
| `withheld` | tax withheld from a dividend (already out of its amount) |
| `id` | the broker's reference for the row (optional) |

For example:

```
date,type,symbol,market,quantity,price,currency,amount,fee,withheld
2024-01-02,deposit,,,,,USD,5000,,
2024-01-03,buy,AAPL,US,10,185.20,USD,1852.00,0,
2024-03-15,dividend,AAPL,US,10,,USD,2.04,,0.36
2024-06-10,sell,AAPL,US,5,196.90,USD,984.50,0,
```

A tax row on the same day and line as a dividend counts as that dividend's withholding.
Overlapping exports are fine: a row in two files counts once, and two identical trades in one
file count twice.

**Nothing is guessed.** A row the desk cannot read stops the import and names its file and line,
because a trade skipped quietly would make every figure after it wrong.

**What an export does not say.** An export has no holdings, cash or totals of the broker's own.
The desk works them out from the history: each US line at its latest close, and a line listed
elsewhere at its cost (the page says which). So the checks against the broker cannot run. After
importing, compare the desk's total with your broker's once.

## What the desk works out for every broker but Trading 212

Trading 212 states a closed gain on each sale and a cost on each holding. Other brokers state
them differently, or not at all. The desk works them out as Trading 212 states them: against the
average cost of the holding, in the account's currency at the rates of the days bought, fees in,
with each split counted. So the figures mean the same whichever broker the account is at.

## How it is checked

`tests/test_brokers.py` gives the same simulated account in each broker's own format:
- as a CSV export;
- as Alpaca's answers;
- as an Interactive Brokers Flex statement.

The account's truth is known to the cent (`tests/ledger.py`), across dollars, euros and pounds,
with splits, a London line, fees, withheld tax and withdrawals. Each adapter must arrive at the
truth:
- total, cash, deposits and withdrawals;
- closed gains, fees, withheld tax, dividends;
- every year History can price.

On your real account, the Overview's **Checks against** row sets the desk's rebuilt figures
beside your broker's own, at every build.

This environment cannot reach Alpaca or Interactive Brokers. Their formats are read as their
documentation describes them. The checks, and `doctor.py --account`, test that reading on your
account.
