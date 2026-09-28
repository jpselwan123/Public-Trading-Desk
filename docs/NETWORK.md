# What the desk connects to

The desk is code that runs on your computer, and it reads a brokerage account, so you should be
able to check for yourself where it talks to. This is the complete list. A test
(`tests/test_network.py`) fails if any host appears in the code and not here, so a contributor
cannot add a new destination without documenting it.

**There is no server run by the author.** Nothing to sign up for, no account, no analytics, no
telemetry, no crash reports. The page you look at is served by a small program on
`127.0.0.1` (your own computer), and it loads nothing from the internet: no scripts, no fonts, no
images. `tests/test_network.py` checks that too.

## Every host

| Host | What for | What it is sent | When |
|---|---|---|---|
| `live.trading212.com`, `demo.trading212.com` | Your Trading 212 account (`BROKER=trading212`). Reads only | Your API key and secret; read requests for the summary, positions and history | When you press sync |
| `api.alpaca.markets`, `paper-api.alpaca.markets` | Your Alpaca account (`BROKER=alpaca`). Three read paths | Your API key pair | When you press sync |
| `ndcdyn.interactivebrokers.com` | Your Interactive Brokers Flex report (`BROKER=ibkr`). Reports only | Your Flex token and query number | When you press sync |
| `www.sec.gov`, `data.sec.gov` | Filings, company financials, the list of companies and exchanges, industry codes | A company's number or ticker. The SEC asks automated requests to name a contact, so your `SEC_CONTACT` email is in the request's `User-Agent` | Company updates: when the desk opens and every 30 minutes while open |
| `api.tiingo.com` | Daily prices and after-hours quotes | Tickers of shares you hold, follow or have traded, and a start date; your Tiingo key | Company updates |
| `finnhub.io` | Results dates, analysts' estimates, company news | A ticker and a date range; your Finnhub key | Company updates |
| `fred.stlouisfed.org` | The Treasury bill rate and exchange rates, as public CSV files | A series name. No key | Company updates |
| `news.google.com` | News from the FT, Reuters, Bloomberg and others, through Google News's search feed | Search terms: the company's name, an outlet's domain and a number of days. No key | Company updates |
| `api.openai.com` | A plain-English company summary, or a week's news brief | The company's public figures (from filings and prices) or its headlines; your OpenAI key. **Only when you ask for one.** It is never sent your holdings, trades or notes | On request only |
| `github.com` | New code for the desk, with `git fetch` | Nothing but the request. **Only if you set `AUTO_UPDATE=1`** | When the desk opens, if you turned it on |

Tickers and companies in these requests reveal to those services which shares you follow or hold.
That is inherent in asking for their prices and filings, and it is why each request is made
under your own key. If that matters to you, follow only what you are comfortable with, or use the
demo.

## What is never sent anywhere

Your balances, your holdings' quantities and values, your trades, your account number, your notes,
plans and theses. They are read from your broker into files on your computer and stay there.

## Check it yourself

You don't have to take any of this on trust:

- **Start with no keys at all.** `./desk.sh --demo` runs on made-up data. Or use a CSV export
  (`BROKER=csv`, [`BROKERS.md`](BROKERS.md)), which needs no key and no connection to your broker.
- **Read the network code.** Every request goes through Python's `urllib`. Search the code for
  `urlopen` and `Request(`. The broker readers are short: `t212.py`, `broker_alpaca.py`,
  `broker_ibkr.py`, `broker_csv.py`.
- **Watch it.** Run the desk behind a firewall that shows outgoing connections (Little Snitch or
  LuLu on a Mac, `ss -tp` or OpenSnitch on Linux) and compare what you see with the table above.
- **Run it offline.** Turn off your network and run `./desk.sh --demo`: it works, because it needs
  nothing from the internet.
- **Give it the least it needs.** For Trading 212, make the API key without the *Orders*
  permission: then the broker itself refuses to trade with it, whatever any code does. You can
  also restrict the key to your own IP address. Interactive Brokers' Flex reports cannot trade.
  Alpaca has no read-only key, so try it on a paper account first.
- **Pin what you run.** Clone a specific release or commit you have read, and leave
  `AUTO_UPDATE` off (its default), so the code only changes when you change it.
