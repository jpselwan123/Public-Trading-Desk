# CLAUDE.md — Public Trading Desk

A local research dashboard over the user's own brokerage account (Trading 212, Alpaca,
Interactive Brokers, or a CSV export from any broker) and public company data.
Python stdlib pipeline → static `index.html`, served by `server.py` on 127.0.0.1:8935.
Zero third-party dependencies. Python 3.9 compatible (no `match`, no `X | Y`).

## Commands
```bash
./desk.sh [--demo]                                   # start server + open page
./native_app/build.sh --install                      # Trading Desk.app into ~/Applications (macOS)
./refresh.sh                                         # sync the account + rebuild
./update.sh                                          # new code: fast-forward main (only with AUTO_UPDATE=1)
python3 scripts/phone_bundle.py [--code]             # pack for the iPhone (docs/IPHONE.md)
python3 phone.py [--demo|--update ZIP]               # on the iPhone, in a-Shell
python3 -m unittest discover -s tests -t tests       # no network, no keys (tests/test_*.py by subject; tests/support.py shared;
                                                     # tests/world.py simulates every source for test_update's whole runs)
python3 scripts/privacy_scan.py [--staged]           # must be clean before any push
python3 doctor.py [--account|--offline]              # the health report: safe to paste, nothing private
```

## Hard rules
- **Read only, at every broker.** Nothing in the desk can place, change or cancel an order.
  `t212.Client` has one method, `get`, and reaches `READ_PATHS` only; Alpaca's client reaches
  its three read paths only; Interactive Brokers is read through Flex reports, which give no
  trading access. `BrokerWiringTests::test_the_desk_reads_only_at_every_broker` scans every
  module that reaches a broker for a write. Don't weaken it; it is the boundary.
- **The desk's own rating, and no other advice.** `rating.py` gives Buy / Hold / Sell from
  published measures grouped into the themes of the most thorough re-test of them (Jensen,
  Kelly & Pedersen 2023: of their thirteen themes, the four among the ten with significant weight
  that the desk measures well — Value: book to market and share issuance; Momentum; Quality:
  gross profitability; Accruals — each measure one that also held in Hou, Xue & Zhang 2020;
  asset growth, the F-score and low risk are left out and say why, `rating.LEFT_OUT`).
  - Value and momentum need a price and are placed against a fixed random sample of 200 NYSE
    companies, drawn once by `rating.keep_sample` and never redrawn. The sample is also logged
    and scored as the rating's fair record, judged as `docs/RATING.md` set down before any result.
  - Each measure is placed the way its paper found against NYSE-listed companies (the papers'
    breakpoints: Fama & French 2008, Hou, Xue & Zhang 2020; over-the-counter shares are not
    rated; the SEC's exchange list, `universe.update_listings`, is fetched once a day). Measures
    are averaged within their theme, the themes averaged with equal weights, the average placed
    among companies resting on as many themes, and cut into thirds (as Jensen, Kelly & Pedersen
    build every factor). Every part is shown with its paper and its limits.
  - Every rating given to a covered or held company is logged in `ratings_log.json` (added, never
    edited, each entry with the definition that gave it) and scored against the market with
    intervals — only the present definition's ratings. A new measure needs its paper, and any
    change to how the rating is made is a new dated `rating.METHOD`.
  - The rating never places an order (`RatingTests` checks). Nothing else advises: no target
    prices, no "you should" wording, the AI summary never says buy or sell, and published analyst
    ratings are other people's opinions, shown with their known bias to "buy".
  - "The week in brief" (`brief.py`, `POST /brief`) is written only when asked, from the last
    `brief.WEEK_DAYS` days' headlines, filings and moves the News fold shows and nothing else; it
    is told it has headlines, not articles, never to say a story moved the shares, and never buy
    or sell; kept in `briefs.json` with the stories it was written from.
  - News (`headlines.py`) is shown beside each day's move against the market and never enters the
    rating: the evidence on news tone is about days (Tetlock, Saar-Tsechansky & Macskassy 2008;
    Heston & Sinha 2017), the rating's about a year. It comes from Finnhub and, through Google
    News's search, the FT, Reuters, Bloomberg and Dow Jones's papers; keeps only stories that name
    the company in the headline or first 25 words (Tetlock et al.'s rule, `headlines.about`);
    shows a story once however many outlets carried it that day; marks a day's move unusual
    outside the 95% range of the shares' own moves against the market over the 250 trading days
    before (MacKinlay 1997, `build_desk.unusual`); and puts the company's important filings on the
    session they could move. A big move on a news day is never said to be caused by the news.
- **Every rule and threshold from published research**; where none exists, show a plain fact.
  `docs/EVIDENCE.md` is the register: every number that could steer a decision, with its study,
  or marked as the desk's choice and why. A new one goes in it; `EvidenceRegisterTests` checks the
  rating's measures and the screener's screens are there. Prefer what survives the strict
  re-tests (Hou, Xue & Zhang 2020; Jensen, Kelly & Pedersen 2023) to a single paper.
- **Evidence rules (research.py), never relaxed to make a rule look better:** the test
  universe is fixed in code and never the watchlist — rule H's shares too
  (`research.EVENT_SAMPLE`, frozen at the run of record, S-16); only the held-out last 30% is
  reported; costs and cash interest always applied; p-values come from a stationary
  block bootstrap (Politis & Romano 1994) and are corrected for multiple testing
  (Benjamini & Hochberg 1995). "Clears" = positive held-out edge AND q < 0.05.
- **Privacy.** Never commit `.env`, `t212_data.json`, `account.csv`, `desk_data.json`,
  `journal.json`, `index.html` or any other store in `.gitignore`. The account number is dropped
  at sync. Tests and screenshots use `scripts/generate_demo_data.py`. Keys stay in `.env`: never
  printed, logged or sent to the page, and every key a broker adds goes in `env_config.SECRET_NAMES`
  so `scrub` blanks it from any error (`test_every_brokers_secrets_are_blanked...` ties the two).
  - Every file the desk writes is made by `env_config.atomic_write`, readable by its owner alone
    (0600); nothing else opens a file for writing (`PrivateFileTests`).
  - The page loads nothing from the internet, and every host the code names is in
    `docs/NETWORK.md` (`tests/test_network.py`). A new destination is documented in the same change.
  - Text from outside (a broker file, a news feed, a filing) reaches the page only through `esc()`.
    What a broker supplies as a currency, symbol or market is checked where it is read
    (`broker.currency_code`, `broker.line_code`) and refused with its line number if it is not one.
    Strings in `DATA` that the page inserts as HTML are composed by Python from numbers and fixed
    labels, never from outside text.
- **The account only when the user syncs; the company data by itself.** Two refreshes, apart
  (`POST /refresh {part}`):
  - `account` is the broker alone (`server.refresh_account`, through `broker.configured()`), only
    when the round button is pressed.
  - `market` is filings, prices, financials, results, ratings and research
    (`server.refresh_market`), which reach no broker. The page runs it on opening and every
    `build_desk.MARKET_EVERY_MINUTES` while it is open — the one timer (`setInterval` in the
    template, `CompanyDataOnItsOwnTests`), never for the demo or a past day, and never redrawing
    under a field being typed in. No module on the market path imports a broker's client.
  - Following a company loads it at once (`server.fetch_company`), beside a market update under
    way, never waiting for it: each of its changes is a `server.Merge` made on the store as it
    stands, and the update, writing a store from what it read before, makes every change since it
    began again on it (`server.Stores`) — so a merge must be one that can be made twice. Its
    figures and price come first and the page is rebuilt as soon as they are in
    (`{"built": true}`), before its news.
- **Each source in its own lane** (`server.run_steps`): steps given a lane run side by side with
  the other lanes', one at a time within it, so a source's limits still hold; a step that reads
  what another writes names it in `after`, and two steps writing one store whole are never in
  lanes that can overlap. Every source is asked for gzip and read through `env_config.unpacked`.
- **Never break the page.** Every render survives an empty or unconnected account; each
  `renderX()` runs inside `safe()`. Every loader checks the shape it reads
  (`build_desk.load_json`, `records`; `test_stores` builds with each store damaged six ways), a
  fault in one update step fails that step alone (`server.run_steps`), and a store holding the
  user's own record — plans, theses, notes, the ratings log, the followed list, the practice
  book — that is there but cannot be read is never written over (`env_config.read_for_writing`).
- **The demo is apart from the desk.** Every write it makes goes to its own folder (summaries,
  practice trades priced from its own closes, its own followed list).
- **Checked against the broker at every build, and against a known truth in the tests**
  (`docs/AUDIT.md`). `checks.py` rebuilds shares, cash, total, closed gains and prices from the
  real records and sets each beside the broker's own (the Overview's "Checks against …", and
  doctor.py without amounts or holdings); a record derived from an export has no totals of the
  broker's own, and the checks say so (`none_because`). `tests/ledger.py` simulates accounts in
  three currencies whose truth is known; `tests/test_audit.py` sets every account figure,
  statistic and split rule beside a second calculation or a published value. A new figure gets a
  truth test there. Per-share figures are restated in the shares of the day they are read for
  (`fundamentals.in_shares_of`), and a filed share count in the price's (`value.splits_since`).
- **Every broker through one record.** `.env`'s `BROKER` names the broker, `trading212` when
  unset (`broker.current`). Each adapter (`t212`, `broker_csv`, `broker_alpaca`, `broker_ibkr`)
  writes the record Trading 212's sync writes (`t212_data.json`, in its shape, with `broker` set),
  so every figure downstream has one code path. What a broker does not state is worked out at
  build as Trading 212 states it (`broker.complete`: closed gains and holding costs against the
  average cost, in the account's currency, splits counted; an export's holdings and totals, marked
  `derived`). The page names the broker (`brokerName()`, `DATA.broker`) and shows its connect
  steps from `broker.BROKERS`. A new broker needs an adapter, an exporter in `tests/ledger.py`
  and a truth test in `tests/test_brokers.py`. `docs/BROKERS.md`, `docs/ADDING-A-BROKER.md`.
- **A broker is optional.** With none connected the desk is still a working desk: the Overview says
  so (the card in `renderHeader`, its wording data from `broker.for_page`: it names no broker until
  keys, a `BROKER` or an account say one was chosen), Companies and Research need no account, and a
  key not yet added is a step to take, not a failure (`env_config.SETUP_STEPS`; `refresh_market`
  reports them apart as `setup`, `health.py` as `waiting`). The connection steps show once keys
  are in `.env`.
- **Diagnose from the user's report, not a guess.** A development container may not reach the
  SEC, Tiingo, Finnhub or a broker; the user's machine can. `doctor.py` prints the code version,
  which keys are set (never their values; any that appears in an error is blanked), each source
  asked once, what every step did at the last updates (`health.json`, written by
  `server.record_health`, shown as the Overview's "Data sources" row), each store's age and
  counts, and the ratings' spread. A new source or store is added to it. Its report must stay
  safe to paste.

## Gotchas
- **A sync can be slow**, and every request may be a new connection. So `POST /refresh` answers
  as it goes, in JSON lines (`server._stream`), the account's page rebuilt as soon as the broker
  has answered; its blank heartbeat lines keep a long request alive.
- **Nothing is fetched that cannot have changed**, the more so since the company data updates
  every half hour:
  - financials only after a new 10-Q/10-K (`fundamentals.holds_latest_report`);
  - a company's older filing lists once (`news.filings_for`'s `known`: only the latest list is
    asked again);
  - the research only on a new fingerprint (`research.fingerprint`);
  - daily closes only once a session has ended and the benchmark has its close
    (`prices.update`). Tiingo's free key allows 50 requests an hour: every request is counted in
    the store and an update stops at the hour's and the day's budget
    (`prices.TIINGO_PER_HOUR`/`_PER_DAY` less `SPARE`);
  - the rating's sample is priced once a month; the rating's universe is rebuilt monthly and the
    industry codes built when missing, on a computer only (`universe.keep_up`,
    `sectors.keep_up`), never on a phone;
  - what changes at most daily, once a day (`env_config.fetched_today`: the cash rate, analyst
    ratings, the exchange list, earnings unless results are due).

  A new source follows the same rule.
- **Adjusted closes are restated, and splits kept**:
  - each price update asks Tiingo from the last stored day again and re-bases the stored adjusted
    closes by the ratio on it (`prices._merge`), so a later dividend or split is never lost from
    a return;
  - a split's day keeps Tiingo's `splitFactor` as `"s"` (`prices.splits`, `prices.split_factor`);
  - a ticker not in `_whole` is fetched whole once, and each US share ever traded
    (`server.traded_us_shares`) is fetched whole from its first trade, once;
  - a trade before a split is counted in the later trade's shares
    (`build_desk.build_closed_trades`, one row a sale, after fees), and a practice holding is
    restated (`paper.apply_splits`). Only a US line's splits are applied.
- **"Since you last looked" is since the user's last visit** (`looks.py`): every opening of the
  page and every reload it makes while open belong to one visit until the desk has been closed
  for `looks.VISIT_GAP`; the digest counts from the end of the visit before, and a new visit
  rebuilds the page before it is served.
- **Python 3.9 is a Mac's** (`python3` there is Apple's 3.9): the suite must pass on a real 3.9,
  not only a newer one (CI runs both). Every timestamp is read by `env_config.moment` — 3.9's
  `datetime.fromisoformat` reads neither a "Z" nor Tiingo's nine digits, and a test fails on any
  other direct call.
- **The SEC's acceptance times are New York's**, whatever their "Z" says (EDGAR takes filings from
  6:00 to 22:00 Eastern): `news.filed_moment` reads them so, and `doctor.py` reports the hours the
  stored times span.
- **Google News's search is unofficial** (no key, marked for personal, non-commercial reading): the
  press step fails on its own (`headlines.PressError`) and Finnhub's stories keep coming; it is
  asked gently (`headlines.REQUEST_GAP`), two searches a company, and doctor.py asks it once.
- **The desk also runs on an iPhone** (`phone.py` in a-Shell, `docs/IPHONE.md`): the page shows
  in a-Shell's own browser, because iOS pauses an app that is not on screen. What an iPhone's
  Python lacks is designed around, and must stay so:
  - no second process (`server.IN_PROCESS_SYNC` runs the sync in the server);
  - possibly no time-zone data (`prices.USEastern`, the US rule itself, behind `MARKET_TZ`);
  - possibly no certificate list (`phone.certificates`).

  No new module may start a process or need a C extension outside the standard library on the
  refresh or page path. `phone.py --update` replaces code and never a data file the phone
  already has.
- **One desk, opt-in** (`docs/ONE-DESK.md`): a phone may open a computer's desk through
  `tailscale serve`. The server still binds 127.0.0.1 only; `.env`'s `DESK_HOSTS` names the
  computer's Tailscale machine name (`*.ts.net` only, `server.desk_hosts`), the one host beside
  localhost that the host and origin checks accept.
- **Code updates are opt-in**: with `AUTO_UPDATE=1` in `.env`, `update.sh` runs first in
  `desk.sh` and in the Mac app — main only, a fast-forward only (never a merge, never over a
  local edit, never a data file), the download given up after 20 s. A change to `native_app/`
  rebuilds the app in the background for the next opening.
- Trading 212's history endpoints are newest-first, cursor-paginated via `nextPagePath` (max
  50/page); orders/dividends/transactions allow 6 requests/min. Respect `x-ratelimit-*` headers.
- Money values in `walletImpact` / summary are in the account currency; `price` /
  `averagePricePaid` are in the instrument currency: label them separately.
- Tickers look like `AAPL_US_EQ`, London lines like `VUSAl_EQ` → `short_ticker()`; another
  broker's lines are coded the same way (`broker.line_code`). A short ticker names a US filer only
  when the code ends `_US_EQ` (a holding's `us_line`): a London line can share one with an
  unrelated US company, so it is never rated, priced or placed by it.
- Money-weighted return: don't annualise under 12 months (GIPS).
- UI: clean over dense, one idea per card, click not hover, works at 375px with no horizontal
  scroll, respects `prefers-reduced-motion`, reuse `:root` tokens (no colour written anywhere
  else). A dim slate page: soft light ink on deep blue-grey, one blue accent, text 12px or
  larger, labels in words not spaced capitals, figures in the text face, every text colour at
  4.5:1 or better, and ink on the page between 12:1 and 17:1 — never white on black
  (`LookTests`). Detail opens on click: a company card shows its price and key figures, and every
  other section is a row (`foldOpen`) with a plain title and a one-line gist; each research rule
  likewise.
- **One definition for any shared number**: a constant or derived quantity used in two modules
  is defined once, exported by its owner, with a test that the callers agree. Finding a second
  copy, deleting it is the fix. `context.py` computes nothing.
- **The one-definition rule covers the template as well as the Python** (J-04). Any quantity
  appearing in both a computation and a rendering has exactly one owner and one declaration. A
  second copy is deleted, not corrected. How a measure looks is declared by its owning module
  (`screen.MEASURE_DISPLAY`, `value.VALUE_DISPLAY`), shipped in `desk_data.json` as
  `measure_display`, and read only by `formatMeasure` in the template — no page picks a measure's
  format or label. A number the Python owns (a cost, a window, an interval level, a count of
  funds) reaches the page as data; the template never types it in, and never carries a fallback
  guess — a missing value reads "not recorded". The formatter exists twice only because the page
  and the command line are different languages (`formatWith` / `screen.format_with`);
  `MeasureDisplayTests` runs both on the same inputs.
- **Every count read as evidence carries its interval.** `uncertainty.py` owns every interval on
  a count or a median: the exact binomial (Clopper–Pearson) and the order-statistic median, which
  invert the same sign test, so "the median moved" and "up after k of n" on one line cannot
  disagree. The page draws `intervalBar()` and words `distinguishable`; it never compares an
  interval with chance itself. Any other "k of n" in the template carries a `/* not a rate: … */`
  comment saying why (a census, a rank, tests already corrected) — `IntervalPageTests` fails on
  an unmarked one. Records shown side by side share `uncertainty.family_level` (Benjamini &
  Yekutieli 2005). A past-reaction event counts only outside the last one's longest window
  (S-12): filings cluster, and overlapping windows are one price move.
- **Coverage, not a watchlist**: at most `news.MAX_COVERAGE` (15) companies, each followed with
  a date and nothing else; a sixteenth names the one it replaces, and a company that leaves keeps
  its record in `past`. `news.follow` / `news.unfollow` are the only ways in, `save_watchlist`
  the only writer, and each served folder has its own `watchlist.json` — the demo never edits the
  real list (`server.coverage_file`). Every US company held and not followed is covered too
  (`server.held_companies`: in the SEC's universe, so not a fund), without counting toward the
  cap. `news_data.json`'s `held` names them; the coverage list never takes one in.
- **Theses are write-once** (`docs/THESES.md`): no edit or delete path may be added, a thesis is
  refused on or after the results date, and one whose quarter was public before it was written
  is void. `theses.json` is personal and never committed.
- **Plans are write-once too** (`plans.py`): the user's reason and what would prove it wrong,
  written before a trade; no edit or delete path. Matched to the first trade in that company, on
  that side, within `plans.MATCH_DAYS`; scored from that trade to the review day against the
  S&P 500, and only a plan past its day is counted. `plans.json` is personal and never committed.
- **As of a past day**: `asof.py` is the one place each store's date rule lives, and every rule
  decides with `asof.known` — a record with no date, or one that is not a YYYY-MM-DD day, is never
  shown for a past day (K-03). A new store needs its rule there and a seeded observation in
  `AsOfTests.inputs`, which each store gets twice: dated after the day, and undated. Financials
  are placed by filing date, never period end (`asof.company`); the practice book is replayed by
  `paper.replay`. A company followed before follow dates were kept is named on a past page, never
  shown as covered then; the next company update dates it from that day (`news.date_undated`,
  through `news.follow`), and never writes a stop into `past` (S-29). A figure not known then is
  left out, never filled with today's. The as-of page is read-only.
- **Colour says what a number is, never whether it is good**: `--measured`, `--uncertain`,
  `--withheld`; no green or red on returns. Withheld is decided by the module that writes the
  reason (`withheld` beside `why`), never guessed by the page from its wording.
- SEC frames API: omits a figure filed only inside a dimensional breakdown (KO has no debt
  figure), dates `dei` cover facts by the company's fiscal calendar (public float is read from
  every quarter), and passes filer unit slips through as filed (`screen.scale_fault`).
- `dei:EntityPublicFloat` × 10 is the share-basis check; a depositary listing fails it and its
  market-value figures are withheld, never shown beside a warning.
- Financial firms (SIC division "Finance, insurance and property"): Piotroski and Altman do not
  apply; the card says so rather than scoring them.
- Verifying a clean checkout (`git archive | tar -x`): run with
  `python3 -X pycache_prefix=<fresh dir>`. The system Python keeps bytecode in one central cache,
  and two commits made in the same second with a same-length edit reuse the stale bytecode — a
  false failure.

## Page structure
The page is `desk_template.html` (markup) with `page/desk.css` and `page/*.js` put in by
`build_desk.template_source`: one script split by subject, run in `build_desk.PAGE_SCRIPTS`
order, so a file may use at load only what earlier files declare. Tests read the joined source
(`page_source()` in `tests/support.py`), never one file.

Six tabs with hash routing (`TABS` in the template), each one subject:
- **Overview.**
- **Portfolio.**
- **History:** the account year by year (`history.py`). Each past year-end is rebuilt from the
  record — shares at that day's close, cash from every movement — and used only while the same
  rebuild to today ties to the broker's total within `history.CHECK_TOLERANCE`; a year it cannot
  price says why.
- **Companies:** a follow box and one sortable table of every company covered (price, the last
  day and the year against the market, the desk's rating, P/E against its own five years, next
  results, latest news); a row's click shows that company's card below. Then News, then Filings.
- **Research:** the desk's Buy list (`rating.buy_list`: every company the rating labels Buy,
  highest place first, each a click from being followed — the rating's own label, never a second
  cut-off), the rule tests and the rating's record, then the Screener.
- **Trades:**
  - "Check a trade" (`trade_check.py`, `POST /check`): a ticker and an amount give the facts
    before a trade is placed at the broker — the holding and its industry before and after, the
    rating, results, fees from the user's own record, dividend and tax withheld. It reads only;
    nothing is written or sent.
  - The user's trades, and "Your habits" (`habits.py`): turnover (Barber & Odean 2000), gains
    against losses sold (Odean 1998, with `uncertainty.difference`, Newcombe 1998) and what
    replaced what was sold (Odean 1999), each beside the paper's own figures
    (`habits.PUBLISHED`), which reach the page as data.
  - Practice.

Nothing on the page asks the user to justify a trade: a note, a plan or a thesis is theirs to
write when they want one. An old address (`#journal`, `#filings`) opens the tab that holds it,
at that section. Keep sections self-contained; `renderAll()` runs every `renderX` inside `safe()`.
