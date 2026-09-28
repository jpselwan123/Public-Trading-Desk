# Security

The desk runs on your own computer and reads your brokerage account, so its security is mostly
about your keys and your data staying where they are.

## What it does to protect them

- The server binds to `127.0.0.1` only, and refuses requests whose host or origin is not its own.
  The one opt-in exception is a Tailscale machine name you put in `DESK_HOSTS`
  ([`docs/ONE-DESK.md`](docs/ONE-DESK.md)).
- Keys live in `.env`, are never printed, logged or sent to the page, and any that appears in an
  error is blanked. `python3 doctor.py` is written to be safe to paste.
- The desk reads your broker and cannot trade. A test scans every module that reaches a broker
  for a write.
- Account data, notes and keys are git-ignored, and `scripts/privacy_scan.py` fails if one is
  staged.

## Reporting a vulnerability

Please **don't open a public issue** for a security problem. Use GitHub's private reporting:
the **Security** tab of this repository, then **Report a vulnerability**. Say what you found, how
to reproduce it, and what it lets someone do. Never include a real key or real account data; a
description or a simulated example is enough.

Things that count: a way for a web page on another site to read the desk's data, a key or
account detail leaking into a log, an error message or the page, a path to a write at a broker,
or private data that has ended up in the repository.

## Alpaca

Alpaca offers no read-only API key: a key can trade. The desk's Alpaca client reaches only its
three read paths, and a test holds it there, but anyone who can read your `.env` can use the key.
Keep `.env` private (`chmod 600 .env`), and use a paper account first if you are unsure.
