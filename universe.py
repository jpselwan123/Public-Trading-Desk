"""Fundamentals for every US filer, from the SEC itself → universe.json.

The rest of this project looks at a watchlist you type in. A screener cannot: it
has to start from everything and narrow down, or it is just a list of shares you
already thought of, which is the hindsight problem research.py exists to avoid.

Source is the SEC's XBRL **frames** API, which returns one concept across every
filer for one period — about 6,000 companies in a single 400 KB request. That is
the whole reason this is feasible without a paid data feed: the alternative,
companyfacts.zip, is well over a gigabyte and has to be re-downloaded to refresh.

What this is not: a price feed. Nothing here needs a market price, deliberately —
see screen.py, which filters on fundamentals first and only prices the survivors.

A real limit of this source, worth knowing before trusting a count: the frames API
omits a concept that a company reports only inside a dimensional breakdown. Coca-Cola
files LongTermDebt and LongTermDebtNoncurrent and appears in neither frame, so it has
no debt figure here. Barely a third of filers do. Nothing is wrong with the data that
is present; what is absent is simply absent, and screen.py reports per-condition
coverage so an unanswerable condition is never mistaken for a failed one.

The SEC asks automated requests to identify themselves, so set SEC_CONTACT in .env.

Kept up by itself on the Mac (27 Sep 2026): the company update rebuilds it when it is
missing, a month old, or a new year's annual reports have come in (due). By hand:

Usage: python3 universe.py [--years 5]
"""
import json, os, re, sys, time, urllib.error, urllib.request
from datetime import date, datetime, timedelta, timezone

from env_config import atomic_write_json, fetched_today, load_env, NO_SEC_CONTACT, unpacked

HERE = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_FILE = os.path.join(HERE, "universe.json")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# The same tickers with the exchange each trades on. The rating sets its breakpoints on
# NYSE-listed companies and leaves over-the-counter shares out, as its papers did.
EXCHANGES_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
LISTINGS_FILE = os.path.join(HERE, "listings.json")
FRAMES = "https://data.sec.gov/api/xbrl/frames"
TIMEOUT = 60
PAUSE = 0.15                 # the SEC asks for no more than 10 requests a second
DEFAULT_YEARS = 5


class UniverseError(Exception):
    pass


# Each figure, and the XBRL tags companies actually file it under. A company may
# use any one of them, so every tag is fetched and the first that has a value for
# that company wins — the same approach fundamentals.py takes per company.
#
# "flow" figures cover a period (a year of revenue); "level" figures are a balance
# at an instant (what was owed on the last day). The SEC frames API spells those
# differently — CY2024 against CY2024Q4I — which is why the kind is recorded here.
FIGURES = {
    "revenue": ("flow", ["RevenueFromContractWithCustomerExcludingAssessedTax",
                         "Revenues", "SalesRevenueNet"]),
    "gross_profit": ("flow", ["GrossProfit"]),
    "operating_income": ("flow", ["OperatingIncomeLoss"]),
    "net_income": ("flow", ["NetIncomeLoss"]),
    "operating_cash_flow": ("flow", ["NetCashProvidedByUsedInOperatingActivities",
                                     "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
    "capex": ("flow", ["PaymentsToAcquirePropertyPlantAndEquipment"]),
    "dividends_paid": ("flow", ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]),
    # What a company spent buying back its own shares. With dividends, it is what
    # tells a deficit built by paying shareholders from one built by losing money,
    # which Altman's model cannot tell apart (scores.deficit_is_payout_driven).
    "buybacks": ("flow", ["PaymentsForRepurchaseOfCommonStock"]),
    # The cash-flow statement's own lines between net income and cash from operations,
    # for the bridge (Phase 7). Depreciation as the cash-flow add-back: "Depreciation"
    # alone leaves out amortisation, so it is not read. Share-based pay as added back,
    # then as expensed. The total working-capital change is tagged by under a hundred
    # filers, so the bridge names what is left as working capital and other items.
    "depreciation": ("flow", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                              "DepreciationAmortizationAndAccretionNet"]),
    # Many large filers (AMD, Microsoft) tag that cash-flow line under their own name,
    # outside the standard taxonomy, and tag its two parts in the notes. Where the
    # combined line is missing, the bridge uses these two together — never one alone.
    "depreciation_alone": ("flow", ["Depreciation"]),
    "amortisation": ("flow", ["AmortizationOfIntangibleAssets"]),
    "share_based_compensation": ("flow", ["ShareBasedCompensation",
                                          "AllocatedShareBasedCompensationExpense"]),
    # Interest expense for interest coverage; the cash interest paid is a different
    # figure and is not a substitute.
    "interest_expense": ("flow", ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"]),
    "eps": ("flow", ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]),
    "shares": ("flow", ["WeightedAverageNumberOfDilutedSharesOutstanding",
                        "WeightedAverageNumberOfSharesOutstandingBasic"]),
    "assets": ("level", ["Assets"]),
    "current_assets": ("level", ["AssetsCurrent"]),
    "liabilities": ("level", ["Liabilities"]),
    "current_liabilities": ("level", ["LiabilitiesCurrent"]),
    "equity": ("level", ["StockholdersEquity"]),
    "debt": ("level", ["LongTermDebtNoncurrent", "LongTermDebt"]),
    "cash": ("level", ["CashAndCashEquivalentsAtCarryingValue"]),
    "retained_earnings": ("level", ["RetainedEarningsAccumulatedDeficit"]),
    # The actual share count on the cover of the filing, which is what a market
    # capitalisation needs. `shares` above is the weighted average used for earnings
    # per share — a different number, averaged over the year, and wrong for this.
    # Coverage is lower, so market cap falls back to `shares` and says which it used.
    "shares_outstanding": ("level", ["EntityCommonStockSharesOutstanding"]),
    # The company's own statement of what its publicly held shares were worth, filed
    # on the 10-K cover. It is the only market value in this data that comes from the
    # filer, which makes it the one independent check on a market capitalisation
    # computed here — see value.py. It is measured on the last business day of the
    # company's second *fiscal* quarter, which is June only for a December year:
    # Microsoft's is 31 December and Nike's 30 November. Reading only the Q2 frame
    # silently dropped the check for every company with another year end.
    "public_float": ("level", ["EntityPublicFloat"]),
    # When the long-term debt falls due, from the maturity table in the annual report.
    # Only a 10-K carries it, so, like the float, every quarter's frame is tried.
    "matures_1y": ("level", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"]),
    "matures_2y": ("level", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"]),
    "matures_3y": ("level", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree"]),
    "matures_4y": ("level", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour"]),
    "matures_5y": ("level", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive"]),
    "matures_later": ("level", ["LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"]),
}
# Figures whose day of measurement is kept beside them, as figure + DATED_SUFFIX: a share
# count read against a later price must be restated for any split between the two
# (value.splits_since), and the frame's name alone does not say the day (a cover's count
# is dated when the report was filed, weeks after the year it closes).
DATED = ("shares_outstanding",)
DATED_SUFFIX = "_on"
MATURITIES = ("matures_1y", "matures_2y", "matures_3y", "matures_4y", "matures_5y", "matures_later")
UNITS = {"eps": "USD-per-shares", "shares": "shares", "shares_outstanding": "shares"}
TAXONOMY = {"shares_outstanding": "dei", "public_float": "dei"}   # the rest are us-gaap
# Level figures are read at the calendar year end unless listed here. A figure dated
# by the company's own fiscal calendar can sit in any quarter's frame, so every one is
# tried, latest first, and the first that has a value wins.
QUARTERS = {"public_float": (4, 3, 2, 1), **{m: (4, 3, 2, 1) for m in MATURITIES}}


def _request(url, contact):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"trading-desk ({contact})", "Accept": "application/json",
        "Accept-Encoding": "gzip"})                   # a frame is a tenth of the size compressed
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(unpacked(r.read(), r))


def contact():
    load_env(os.path.join(HERE, ".env"))
    who = os.environ.get("SEC_CONTACT", "").strip()
    if not who:
        raise UniverseError(NO_SEC_CONTACT)
    return who


def tickers(who=None, fetch=_request):
    """{cik: ticker}. A company can have several share classes; the first listing
    wins, which is the ordinary common stock in every case the SEC file covers."""
    rows = fetch(TICKERS_URL, who or contact()) or {}
    out = {}
    for row in (rows.values() if isinstance(rows, dict) else rows):
        cik = row.get("cik_str")
        if cik is not None:
            out.setdefault(int(cik), {"ticker": (row.get("ticker") or "").upper(),
                                      "name": row.get("title") or ""})
    return out


def listings(who=None, fetch=_request):
    """{TICKER: exchange} from the SEC's list of tickers with their exchange: "NYSE",
    "Nasdaq", "CBOE", "OTC", or none. Refused when the list is not the shape it has."""
    try:
        data = fetch(EXCHANGES_URL, who or contact()) or {}
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UniverseError(f"Can't reach the SEC for its exchange list ({e})") from None
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, list) or "ticker" not in fields or "exchange" not in fields:
        raise UniverseError("The SEC's exchange list came back in a form the desk does not read")
    t, x = fields.index("ticker"), fields.index("exchange")
    out = {}
    for row in data.get("data") or []:
        if isinstance(row, list) and len(row) > max(t, x) and row[t]:
            out.setdefault(str(row[t]).upper(), str(row[x] or ""))
    return out


def update_listings(stored=None, today=None, fetch=_request):
    """The exchange list, fetched at most once a day: listings change rarely."""
    today = today or datetime.now(timezone.utc).date()
    if stored and stored.get("exchanges") and fetched_today(stored.get("updated_at"), today):
        return stored
    return {"exchanges": listings(fetch=fetch),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def load_listings(path=None):
    """The stored exchange list, {"exchanges": {TICKER: exchange}, "updated_at"}, or {}."""
    try:
        with open(path or LISTINGS_FILE) as f:
            stored = json.load(f)
        return stored if isinstance(stored, dict) else {}
    except (OSError, ValueError):
        return {}


RETRIES = 3                  # a build is ~145 requests; one dropped connection must not end it
BACKOFF = 2.0                # seconds, doubling each attempt


def frame(concept, unit, period, who, fetch=_request, taxonomy="us-gaap", sleep=time.sleep):
    """One concept, every filer, one period. Missing frames are normal: not every
    concept exists in every period, and the caller simply gets nothing.

    A transient failure — a reset connection, a timeout, a server error — is retried
    with a growing pause. Without that, the SEC resetting one connection threw away a
    three-minute build partway through, and the failure was easy to miss. A refusal
    (403) is not transient and is reported at once."""
    url = f"{FRAMES}/{taxonomy}/{concept}/{unit}/{period}.json"
    last = None
    for attempt in range(RETRIES + 1):
        try:
            return (fetch(url, who) or {}).get("data") or []
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            if e.code == 403:
                raise UniverseError("The SEC refused the request: check SEC_CONTACT in .env") from None
            if e.code != 429 and e.code < 500:
                raise UniverseError(f"The SEC returned HTTP {e.code} for {concept} {period}") from None
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
        if attempt < RETRIES:
            sleep(BACKOFF * (2 ** attempt))
    raise UniverseError(f"Could not reach the SEC for {concept} {period} after "
                        f"{RETRIES + 1} attempts: {last}")


# A year's annual reports are in from April of the next: a 10-K is due 60 to 90 days after
# the year ends, by the filer's size (SEC Form 10-K, General Instruction A.(2)), and most
# companies' years end in December. Before April, the year before last is the latest
# whole year; asked for sooner, most companies would have no figures for it yet.
FILED_BY_MONTH = 4
# The desk's choice: rebuilt monthly, a rating is at most a month behind the filings.
REBUILD_DAYS = 30


def latest_year(today=None):
    today = today or date.today()
    return today.year - 1 if today.month >= FILED_BY_MONTH else today.year - 2


def periods(kind, years, today=None, quarter=4):
    """The frame names to ask for, newest first: the latest whole year whose annual
    reports are in (latest_year), and the years before it."""
    latest = latest_year(today)
    if kind == "flow":
        return [f"CY{y}" for y in range(latest, latest - years, -1)]
    return [f"CY{y}Q{quarter}I" for y in range(latest, latest - years, -1)]


def frames_for(figure, kind, years, today=None):
    """(year index, frame name) pairs to read for one figure, newest first."""
    out = []
    for quarter in QUARTERS.get(figure, (4,)):
        for index, period in enumerate(periods(kind, years, today, quarter)):
            out.append((index, period))
    # within a year, the later quarter first, so the newest measurement wins
    return sorted(out, key=lambda pair: (pair[0], -int(pair[1][-2]) if kind != "flow" else 0))


def collect(years=DEFAULT_YEARS, who=None, fetch=_request, log=print, sleep=time.sleep):
    """Every figure for every filer, newest year first.

    Returns {cik: {figure: [values, newest first]}}. A company that did not file a
    figure simply has no entry for it — never a zero, which would read as a real
    number meaning something different."""
    who = who or contact()
    facts, asked = {}, 0
    for figure, (kind, concepts) in FIGURES.items():
        unit, taxonomy = UNITS.get(figure, "USD"), TAXONOMY.get(figure, "us-gaap")
        latest = set()
        for index, period in frames_for(figure, kind, years):
            for concept in concepts:
                rows = frame(concept, unit, period, who, fetch, taxonomy)
                asked += 1
                for row in rows:
                    cik, value = row.get("cik"), row.get("val")
                    if cik is None or value is None:
                        continue
                    series = facts.setdefault(int(cik), {}).setdefault(figure, {})
                    if index not in series:                  # first tag to report wins
                        series[index] = float(value)
                        if figure in DATED:
                            facts[int(cik)].setdefault(figure + DATED_SUFFIX, {})[index] = \
                                str(row.get("end") or "")[:10] or None
                    if index == 0:
                        latest.add(int(cik))
                sleep(PAUSE)
        log(f"  {figure}: {len(latest):,} filers in the latest period")
    return facts, asked


def build(years=DEFAULT_YEARS, who=None, fetch=_request, log=print, sleep=time.sleep):
    """Join the figures to ticker symbols and flatten each series into a list."""
    who = who or contact()
    names = tickers(who, fetch)
    facts, asked = collect(years, who, fetch, log, sleep)
    companies = {}
    for cik, figures in facts.items():
        listed = names.get(cik)
        if not listed or not listed["ticker"]:
            continue                      # a filer with no listed common stock
        row = {"cik": cik, "ticker": listed["ticker"], "name": listed["name"]}
        for figure, by_index in figures.items():
            row[figure] = [by_index.get(i) for i in range(years)]
        companies[listed["ticker"]] = row
    return {"companies": companies, "years": years, "requests": asked,
            "built": date.today().isoformat(),
            "source": "SEC XBRL frames API (data.sec.gov)"}


# Company names arrive as the SEC holds them: "ABBOTT LABORATORIES" beside "Airbnb,
# Inc." (Phase 4). A name in capitals is shown in title case; a name the company
# filed in mixed case is left exactly as filed. Acronyms of legal form and a few
# short joining words keep their usual case. Brand capitals the SEC flattened
# ("JPMORGAN") cannot be recovered and read "Jpmorgan".
KEEP_UPPER = {"LLC", "PLC", "LP", "LLP", "ETF", "REIT", "USA", "US", "NV", "SA", "AG", "SE", "II",
              "III", "IV", "VI", "ADR", "ADS", "AB", "ASA", "NA", "BDC", "SPAC", "UK", "AI", "HK"}
JOINING = {"of", "the", "and", "for", "in", "on", "at", "by", "to", "de", "la", "du"}
# Words of three letters or fewer are usually initials (EQT, CVS, TCP) and stay in
# capitals — except these ordinary words.
SHORT_WORDS = {"INC", "CO", "COM", "LTD", "NEW", "ONE", "TWO", "OIL", "GAS", "BIO", "AIR", "SEA", "SUN",
               "BAY", "BIG", "TOP", "RED", "ART", "CAR", "BOX", "LAB", "NET", "PET", "WAY",
               "ACT", "AGE", "ALL", "ARK", "BAR", "CAP", "DAY", "DOG", "EYE", "FIT", "FOX",
               "HUB", "ICE", "INN", "JET", "KEY", "LIFE", "MAX", "OAK", "OWL", "PAY", "PRO",
               "RAY", "SKY", "TEA", "TEN", "TIN", "VAN", "WEB", "WIN", "ZEN", "GOLD", "PLUS"}
# Where incorporated, as the SEC appends it: "INC/CA", "KEYCORP /NEW/", "CORP. I/CAYMAN",
# "INC. / DELAWARE", "BANCORP \\DE\\", "INC.\\NEW", "(DE)", or a lone trailing slash. Keyed
# on the place — a US state or territory code, NEW, or a registry — so a slash inside a
# name is never touched: Cullen/Frost, Data I/O, M/I Homes, 20/20, Novo Nordisk A/S.
PLACES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE "
          "NV NH NJ NM NY NC ND OH OK OR PA PR RI SC SD TN TX UT VT VA WA WV WI WY NEW").split() + [
          "CAYMAN ISLANDS", "CAYMAN", "MARSHALL ISLANDS", "DELAWARE", "DEL", "CANADA", "CAN", "CN",
          "UK", "HK", "CI", "FI"]   # every mark found in the stored universe, 2026-09-24
_PLACE = "|".join(PLACES)
STATE_MARK = re.compile(r"\s*(?:[/\\]\s*(?:" + _PLACE + r")\s*[/\\]?|\((?:" + _PLACE + r")\)|/)\s*$",
                        re.IGNORECASE)


def _word(word, first):
    core = word.strip(",.()/")
    letters = core.replace(".", "").upper()
    if letters in KEEP_UPPER or ("&" in core and core.upper() == core and len(core) <= 5):
        return word                                          # LLC, PLC, AT&T
    if core.isalpha() and len(core) <= 3 and core.upper() not in SHORT_WORDS \
            and core.lower() not in JOINING:
        return word                                          # EQT, CVS, TCP
    if not first and word.lower() in JOINING:
        return word.lower()
    return "".join(part[:1].upper() + part[1:].lower() if part.isalpha() else part
                   for part in _pieces(word))


def _pieces(word):
    """Letters and everything else, alternately: "O'REILLY" → O ' REILLY."""
    out, run = [], ""
    for ch in word:
        if run and ch.isalpha() != run[-1].isalpha():
            out.append(run)
            run = ""
        run += ch
    return out + [run] if run else out


def display_name(name):
    """The company name for a page: capitals made readable, anything else as filed.
    The one place a name's case is decided — the screener and the company cards both
    use it."""
    if not name:
        return name
    name = STATE_MARK.sub("", name)
    if name != name.upper():
        return name
    return " ".join(_word(w, i == 0) for i, w in enumerate(name.split(" ")))


def load(path=None):
    """The stored universe, or one with no companies when it is missing or not its shape."""
    try:
        with open(path or UNIVERSE_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"companies": {}}
    if not isinstance(data, dict) or not isinstance(data.get("companies"), dict):
        return {"companies": {}}
    data["companies"] = {t: c for t, c in data["companies"].items() if isinstance(c, dict)}
    return data


def due(store, today=None):
    """Whether the universe should be rebuilt: none stored, REBUILD_DAYS old, or built
    before a new year's annual reports came in."""
    today = today or date.today()
    try:
        built = date.fromisoformat(str((store or {}).get("built") or "")[:10])
    except ValueError:
        return True
    return (not (store or {}).get("companies") or today - built >= timedelta(days=REBUILD_DAYS)
            or latest_year(built) != latest_year(today))


def keep_up(today=None, build_it=None, log=lambda *a: None):
    """Rebuild and store the universe when it is due; the stored one otherwise."""
    stored = load()
    if not due(stored, today):
        return stored
    try:
        data = (build_it or build)(log=log)
    except (urllib.error.URLError, OSError, ValueError) as e:     # the ticker list, or a bad answer
        raise UniverseError(f"Could not rebuild the universe from the SEC ({e}); the stored one is kept") from None
    if not data.get("companies"):
        raise UniverseError("The SEC returned no companies; the stored universe is kept")
    atomic_write_json(UNIVERSE_FILE, data)
    return data


def main(argv):
    years = DEFAULT_YEARS
    if "--years" in argv:
        years = int(argv[argv.index("--years") + 1])
    print(f"Fetching {years} years of fundamentals for every US filer from the SEC…")
    data = build(years)
    atomic_write_json(UNIVERSE_FILE, data)
    companies = data["companies"]
    with_revenue = sum(1 for c in companies.values() if (c.get("revenue") or [None])[0])
    print(f"\n{len(companies):,} listed companies · {with_revenue:,} with revenue for the "
          f"latest full year · {data['requests']} requests")
    print(f"Written to {os.path.basename(UNIVERSE_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
