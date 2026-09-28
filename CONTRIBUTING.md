# Contributing

Thank you. The most useful contribution is **a broker that works on a real account**: try yours,
run `python3 doctor.py --account`, and say what the Overview's *Checks against* row says. Adding
a new broker is a small, well-tested job: [`docs/ADDING-A-BROKER.md`](docs/ADDING-A-BROKER.md).

## Run the tests

```bash
python3 -m unittest discover -s tests -t tests     # no network, no keys; about a minute
python3 scripts/privacy_scan.py --staged           # must be clean before you push
```

The suite has to pass on **Python 3.9** and on a current 3.x (CI runs both), and the desk has
**no third-party dependencies**. No `match`, no `X | Y`. Read every timestamp through
`env_config.moment`.

## What a change must keep true

The full engineering rules are in [`CLAUDE.md`](CLAUDE.md). The ones a change is most likely to
touch:

- **Read only.** Nothing can place, change or cancel an order at any broker, and a test scans
  every broker module for a write. Pull requests that add an order path won't be merged.
- **Every rule and threshold comes from published research**, or is marked as the desk's own
  choice and why, in [`docs/EVIDENCE.md`](docs/EVIDENCE.md). A new measure in the rating needs its
  paper, and any change to how the rating is made is a new dated `rating.METHOD`.
- **A new figure gets a truth test**: set beside a second calculation, or a published value, in
  `tests/test_audit.py`. Numbers on someone's money should be right, not plausible.
- **Any count read as evidence carries its interval** (`uncertainty.py`); the page never compares
  an interval with chance itself.
- **One definition for any shared number.** A constant used in two modules is defined once, by its
  owner, with a test that the callers agree. This covers the page's template too.
- **Never break the page.** Every render survives an empty or unconnected account; a store that
  can't be read is never written over.
- **Colour says what a number is, never whether it is good.** No green or red on returns.

## Privacy

Never commit a real account file, key, statement or screenshot of a real account. Tests and
screenshots use the simulated ledger (`tests/ledger.py`) and `scripts/generate_demo_data.py`. If
you find something private already in the repository, say so through
[`SECURITY.md`](SECURITY.md), not in a public issue.

## Reporting a problem

Open an issue and paste the output of `python3 doctor.py` (add `--account` to include your broker).
It is written to be safe to paste: it shows which keys are set, never their values, and no
amounts or holdings.

## Licence

By contributing you agree that your contribution is licensed under the [MIT licence](LICENSE).
