# What the desk connects to

The desk is code that runs on your computer, and it reads a brokerage account, so you should be
able to check for yourself where it talks to. This is the complete list. A test
(`tests/test_network.py`) fails if any host appears in the code and not here, so a contributor
cannot add a new destination without documenting it.

**There is no server run by the author.** Nothing to sign up for, no account, no analytics, no
telemetry, no crash reports. The page you look at is served by a small program on
`127.0.0.1` (your own computer), and it loads nothing from the internet: no scripts, no fonts, no
images. Its two typefaces (Archivo and IBM Plex Sans, under the SIL Open Font License) are files in
`page/fonts/` that the build puts into the page, so the page is complete the moment it arrives.
`tests/test_network.py` checks that too, on the source and on the built page.

## Every host

| Host | What for | What it is sent | When |
|---|---|---|---|
| `live.trading212.com`, `demo.trading212.com` | Your Trading 212 account (`BROKER=trading212`). Reads only | Your API key and secret; read requests for the summary, positions and history | When you press sync |
| `api.alpaca.markets`, `paper-api.alpaca.markets` | Your Alpaca account (`BROKER=alpaca`). Three read paths | Your API key pair | When you press sync |
| `ndcdyn.interactivebrokers.com` | Your Interactive Brokers Flex report (`BROKER=ibkr`). Reports only | Your Flex token and query number | When you press sync |
| `www.sec.gov`, `data.sec.gov` | Filings, company financials, the list of companies and exchanges, industry codes | A company's number or ticker. The SEC asks automated requests to name a contact, so your `SEC_CONTACT` email is in the request's `User-Agent` | Company updates: when the desk opens and every 30 minutes while open |
| `api.tiingo.com` | Daily prices and after-hours quotes; the Chart tab's candles and the day's bars | Tickers of shares you hold, follow or have traded, and a start date; any ticker you type into the Chart tab; your Tiingo key | Company updates, and when you open a chart (a live one on show asks again every few minutes while the market is open, within Tiingo's free allowance) |
| `finnhub.io` | Results dates, analysts' estimates, company news; a real-time quote for the Chart tab | A ticker and a date range, or the ticker of a chart you have open; your Finnhub key, in a request header | Company updates, and every few seconds while a live chart is on show |
| `query1.finance.yahoo.com` | The Chart tab's whole-market price and minute bars, **only if you set `YAHOO_CHART=1` in `.env`**. Yahoo has no public interface for this and can change or close it without notice; the request is made as a browser would make it | The ticker of a chart you have open | Every 10 seconds at most while a live chart is on show |
| `data.alpaca.markets` | The Chart tab's IEX trades and bars down to the minute, only if you put an Alpaca key pair in `.env`. Reads only; nothing is traded | The ticker of a chart you have open and a start date; your Alpaca key pair, in request headers | Every few seconds while a live chart is on show |
| `fred.stlouisfed.org` | The Treasury bill rate and exchange rates, as public CSV files | A series name. No key | Company updates |
| `news.google.com` | News from the FT, Reuters, Bloomberg and others, through Google News's search feed | Search terms: the company's name, an outlet's domain and a number of days. No key | Company updates |
| `api.openai.com` | A plain-English company summary, a week's news brief, or an answer in the Ask chat | The company's public figures (from filings and prices) or its headlines; for Ask, your question, the last few turns of the talk, and the figures the desk holds for the company on show; your OpenAI key. **Only when you ask.** It is never sent your trades or notes. Your holdings go only if you tick "Include my holdings" in Ask, and then as each holding's ticker, share of the holdings, gain on cost in percent, days held and the desk's rating: no quantity, value or balance | On request only |
| `github.com` | New code for the desk, with `git fetch` | Nothing but the request. **Only if you set `AUTO_UPDATE=1`** | When the desk opens, if you turned it on |

Tickers and companies in these requests reveal to those services which shares you follow or hold.
That is inherent in asking for their prices and filings, and it is why each request is made
under your own key. If that matters to you, follow only what you are comfortable with, or use the
demo.

## What is never sent anywhere

Your balances, your holdings' quantities and values, your trades, your account number, your notes,
plans and theses. They are read from your broker into files on your computer and stay there. (The one
opt-in: Ask's "Include my holdings" box, which sends tickers and percentages, never amounts, as the table says.)

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
