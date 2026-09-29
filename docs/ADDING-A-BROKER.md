# Adding a broker

An **adapter** reads one broker's own source (an API, a report, a file) and writes the desk's one
account record. Everything else comes for free, because the whole desk works from that record: the
Overview, History, closed gains, holding costs, the checks against the broker, the habits, the
"as it was on a past day" view.

A broker that exports a CSV of its history probably works already (`BROKER=csv`,
[`BROKERS.md`](BROKERS.md)). Write an adapter when the broker has an API or a report format that
gives more than a CSV does: its own cash, holdings and total, so the checks can run.

## The rules an adapter keeps

1. **Read only.** No request that can place, change or cancel an order. Give the client an
   allowlist of read paths and refuse any other, as `broker_alpaca.Client` does. A test scans every
   `broker*.py` for `.post(`, `POST`, `DELETE`, `PATCH` and `PUT`, so a write fails the suite.
2. **Never guess.** A row, field or answer the adapter cannot read raises `broker.BrokerError`
   saying what and where, and nothing is changed. A trade skipped quietly makes every figure after
   it wrong.
3. **Keys stay in `.env`.** Never print one, log one, or put one in an error message.
4. **Standard library only, Python 3.9 compatible.** No `match`, no `X | Y`. Read every timestamp
   through `env_config.moment`.
5. **Money in the account's currency, prices in the line's own.** State what each field is.
6. **Read through `broker.read`.** Build the GET yourself, from your allowlisted paths, and pass it to
   `broker.read(request, opener, timeout, sleep)`. It asks again when a failure is one that passes (a rate
   limit, waiting as long as the service says, a busy server, a dropped connection) and never when the key
   is refused. Word the error it finally raises in your own adapter's terms, as `broker_alpaca` does.
   Take `sleep` as a parameter so a test does not wait.

## The steps

**1. Register it** in `broker.BROKERS`:

```python
"acme": {"name": "Acme Brokerage", "module": "broker_acme",
         "keys": ("ACME_API_KEY", "ACME_API_SECRET"),
         "connect": ("Where to generate the key, in the broker's own words.",
                     "Add `BROKER=acme`, `ACME_API_KEY` and `ACME_API_SECRET` to `.env`.",
                     "Press the round sync button above.")},
```

`connect` is what the page shows a user who has not synced yet, one line per step. `keys` is what
`doctor.py` checks is set.

**2. Write `broker_acme.py`.** `broker.py` calls an adapter's `sync` and `check`; a `credentials` reader keeps the key handling in one place:

```python
def credentials(environ=None): ...        # read the keys; BrokerError if missing, saying which to add
def sync(existing=None, environ=None): ...  # return the record (below)
def check(environ=None): ...              # ask the broker once; return a short phrase, e.g. "answered (live)"
```

`sync` builds the record with `broker.Record`, from the broker's answers:

```python
rec = broker.Record("acme", currency="USD")            # the account's currency
rec.trade(ref, when, code, "BUY", qty, price, net_value, price_currency="USD", fees=[("Commission", 1.0)])
rec.dividend(ref, when, code, amount_received, gross=amount_declared)   # gross - amount = tax withheld
rec.cash(ref, when, "DEPOSIT", 500.0)                   # DEPOSIT WITHDRAW FEE TRANSFER INTEREST_ON_FREE_CASH ADJUSTMENT
rec.position(code, qty, price, value, cost=None)        # a holding as the broker states it
return rec.finish(cash=cash, total=total, existing=existing)
```

- `when` is an ISO timestamp (`2026-03-04T15:30:00Z`); a day alone is `…T12:00:00Z`.
- `ref` is the broker's own id for the row. It is how a later sync merges with history already
  kept, so the same row is never counted twice.
- `code` comes from `broker.line_code(symbol, market)`: `AAPL_US_EQ` for a US listing,
  `VUSA_LSE_EQ` for another. Only `_US_EQ` lines are rated, priced or looked up as SEC filers.
- `net_value` is the money a fill moved, in the account's currency, fees included.
- Leave closed gains and holding costs alone: the broker's figures rarely mean the same thing,
  so `broker.complete` works them out the same way for every broker, against the average cost.
  Pass `cost` only if the broker states it in the account's currency.
- If the broker states no cash, total or holdings (a file of history only), call
  `rec.finish(derived=True, existing=existing)` and the desk works them out from the history,
  saying so. The checks then say they cannot run.

**3. Add its keys** to `.env.example` (commented out, like the others) and a section to
[`BROKERS.md`](BROKERS.md): where to get the key, what to put in `.env`, and anything the desk
does not read (options, futures, conversions).

**4. Test it against the truth.** This is what makes an adapter trustworthy, and a pull request
without it cannot be reviewed.

- In `tests/ledger.py`, add an exporter beside `csv_export`, `alpaca_answers` and
  `ibkr_statement`: it renders the simulated `Ledger` (whose right answers are known to the cent)
  in **the broker's own format**, as its documentation shows it.
- In `tests/test_brokers.py`, feed that through your adapter and call `assert_true_to`, as the
  existing broker tests do. The total, cash, deposits, withdrawals, closed gains, fees, tax
  withheld, dividends and every year History can price must come out as the ledger's.
- Add a test that a malformed answer raises `BrokerError` and changes nothing.

**5. Try it on a real account**, then run `python3 doctor.py --account` and look at the
Overview's *Checks against* row. That is the test a simulation cannot be. Put the doctor output
(it is safe to paste: no amounts, no holdings, no keys) in your pull request, and say which of
the checks agreed.

## What to keep true

`CONTRIBUTING.md` lists what every change must keep true. For an adapter, the ones that matter
most: the suite passes on Python 3.9 and a current 3.x, `python3 scripts/privacy_scan.py --staged`
is clean, and no account data, key or real broker file is in the commit. Use the simulated ledger
for tests, never a real export.
