"""A simulated network for the tests: every source the desk reads (the SEC, Tiingo,
FRED, Finnhub, Google News, Trading 212 and OpenAI), answering in the shape it does, from
one seeded world (28 Sep 2026). A company update can then run whole, twice, as it runs on
the owner's Mac: the fault it found (the exchange list's step failing on every update
after the first) was in no single module's test.

    restore = world.install()          # every urlopen in the desk now reaches the world
    world.FAULTS["tiingo"] = "429"     # a source failing: timeout, refused, 401, 403, 404,
                                       # 429, 500, garbage, html, empty
    world.ASKED                        # Counter of requests by source
    restore()

Nothing leaves the machine: a key in .env reaches this world and no further.
"""
import collections, email.utils, io, json, math, os, random, re, socket, threading, time, urllib.error, urllib.parse, urllib.request, zipfile, zlib
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

TODAY = datetime.now(timezone.utc).date()
FAULTS = {}
ASKED = collections.Counter()
LOG = []

# ---- the world -------------------------------------------------------------------------
REAL = [  # ticker, cik, name, exchange, sic, start price, drift, vol, revenue ($bn a year)
    ("AAPL", 320193, "Apple Inc.", "Nasdaq", 3571, 150.0, 0.12, 0.27, 390.0),
    ("MSFT", 789019, "MICROSOFT CORP", "Nasdaq", 7372, 280.0, 0.14, 0.25, 250.0),
    ("NVDA", 1045810, "NVIDIA CORP", "Nasdaq", 3674, 40.0, 0.45, 0.50, 130.0),
    ("AMZN", 1018724, "AMAZON COM INC", "Nasdaq", 5961, 100.0, 0.12, 0.32, 620.0),
    ("JNJ", 200406, "JOHNSON & JOHNSON", "NYSE", 2834, 160.0, 0.02, 0.16, 88.0),
    ("KO", 21344, "COCA COLA CO", "NYSE", 2080, 58.0, 0.04, 0.14, 46.0),
    ("TSLA", 1318605, "Tesla, Inc.", "Nasdaq", 3711, 200.0, 0.05, 0.60, 97.0),
    ("PYPL", 1633917, "PayPal Holdings, Inc.", "Nasdaq", 7389, 70.0, -0.05, 0.40, 31.0),
    ("AMD", 2488, "ADVANCED MICRO DEVICES INC", "Nasdaq", 3674, 100.0, 0.20, 0.45, 26.0),
    ("XOM", 34088, "EXXON MOBIL CORP", "NYSE", 2911, 105.0, 0.03, 0.22, 340.0),
    ("JPM", 19617, "JPMORGAN CHASE & CO", "NYSE", 6021, 140.0, 0.08, 0.22, 160.0),
]
FUNDS = ["SPY", "VOO", "QQQ", "SCHD", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
SPLITS = {"NVDA": ("2024-06-10", 10.0)}          # a 10-for-1, to exercise the split code
OUTLETS = ["Financial Times", "Reuters", "Bloomberg", "The Wall Street Journal", "Barron's", "MarketWatch"]


def _companies():
    rnd = random.Random(7)
    out = [dict(ticker=t, cik=c, name=n, exchange=x, sic=s, p0=p, drift=d, vol=v, revenue=r * 1e9)
           for t, c, n, x, s, p, d, v, r in REAL]
    sics = [2834, 3674, 7372, 6021, 2911, 3711, 5961, 4911, 6798, 3571, 2080, 1311, 3841, 4813, 5812]
    for i in range(1, 261):
        ex = "NYSE" if i % 3 else ("Nasdaq" if i % 2 else "OTC")
        out.append(dict(ticker=f"Q{i:03d}", cik=900000 + i, name=f"QA COMPANY {i} INC", exchange=ex,
                        sic=rnd.choice(sics), p0=rnd.uniform(5, 300), drift=rnd.uniform(-0.2, 0.3),
                        vol=rnd.uniform(0.15, 0.6), revenue=rnd.uniform(0.05, 50) * 1e9))
    return out


COMPANIES = _companies()
BY_TICKER = {c["ticker"]: c for c in COMPANIES}
BY_CIK = {c["cik"]: c for c in COMPANIES}
DEMO = False
NAME_WORDS = (("Alder", "Birch", "Cedar", "Delta", "Ember", "Falcon", "Granite", "Harbor", "Iris", "Juniper", "Krypton", "Lumen",
               "Maple", "Nimbus", "Onyx", "Pioneer", "Quartz", "Ridge", "Summit", "Tundra", "Umber", "Vertex", "Willow", "Zephyr"),
              ("Analytics", "Biotech", "Capital", "Dynamics", "Energy", "Foods", "Freight", "Labs", "Logistics", "Materials",
               "Networks", "Power", "Robotics", "Semiconductor", "Systems", "Therapeutics", "Utilities", "Works"),
              ("Inc.", "Corp.", "Holdings", "Group", "Co."))


def use_demo_roster():
    """The demo's market (scripts/generate_demo_data.py): companies that do not exist, in place of the
    real names above, so nothing the desk shows for them is a real company's figure. The eleven the
    demo names are its own; the rest are filler, named from word lists. No stories come from a real
    outlet, and none of these companies has a split. Returns what puts the real roster back."""
    import generate_demo_data as g
    global DEMO, OUTLETS
    before = (list(COMPANIES), dict(BY_TICKER), dict(BY_CIK), dict(SPLITS), OUTLETS, DEMO)
    rnd = random.Random(7)
    out = [dict(ticker=t, cik=cik, name=name, exchange=ex, sic=sic, p0=p0, drift=mu, vol=vol, revenue=rev * 1e9, featured=True)
           for t, name, ex, sic, cik, rev, p0, mu, vol, _ in g.DEMO_COMPANIES]
    sics = [2834, 3674, 7372, 6021, 2911, 3711, 5961, 4911, 6798, 3571, 2080, 1311, 3841, 4813, 5812]
    names = set(c["name"] for c in out)
    for i in range(1, 261):
        while True:
            name = f"{rnd.choice(NAME_WORDS[0])} {rnd.choice(NAME_WORDS[1])} {rnd.choice(NAME_WORDS[2])}"
            if name not in names:
                names.add(name)
                break
        ex = "NYSE" if i % 3 else ("Nasdaq" if i % 2 else "OTC")
        out.append(dict(ticker=f"Q{i:03d}", cik=9000100 + i, name=name, exchange=ex, sic=rnd.choice(sics),
                        p0=rnd.uniform(5, 300), drift=rnd.uniform(-0.2, 0.3), vol=rnd.uniform(0.15, 0.6),
                        revenue=rnd.uniform(0.05, 50) * 1e9))
    COMPANIES[:] = out
    BY_TICKER.clear(); BY_TICKER.update({c["ticker"]: c for c in COMPANIES})
    BY_CIK.clear(); BY_CIK.update({c["cik"]: c for c in COMPANIES})
    SPLITS.clear(); _SERIES.clear(); _ACCOUNT.clear()
    _DEMO_CLOSES.clear()
    DEMO = True
    OUTLETS = ["Demo Wire", "Example Ledger", "Sample Post"]

    def restore():
        global DEMO, OUTLETS
        COMPANIES[:] = before[0]
        BY_TICKER.clear(); BY_TICKER.update(before[1])
        BY_CIK.clear(); BY_CIK.update(before[2])
        SPLITS.clear(); SPLITS.update(before[3])
        OUTLETS, DEMO = before[4], before[5]
        _SERIES.clear(); _ACCOUNT.clear(); _DEMO_CLOSES.clear()
    return restore


def sessions(start=date(2019, 1, 2), end=None):
    """Weekdays up to the last session that has closed (New York 16:00 ≈ 20:00 UTC)."""
    now = datetime.now(timezone.utc)
    end = end or (now.date() if now.hour >= 21 else now.date() - timedelta(days=1))
    d, out = start, []
    while d <= end:
        if d.weekday() < 5 and (d.month, d.day) not in ((1, 1), (7, 4), (12, 25)):
            out.append(d)
        d += timedelta(days=1)
    return out


_SERIES = {}


def series(ticker):
    """[(day, raw close, adjusted close, split factor)] — a seeded random walk."""
    if ticker in _SERIES:
        return _SERIES[ticker]
    if DEMO and ticker in _demo_closes():
        # the account's lines: the closes its trades were filled at, and SPY along the S&P 500 fund's walk
        _SERIES[ticker] = [(d, v["c"], v["a"], 1.0) for d, v in sorted(_demo_closes()[ticker].items())]
        return _SERIES[ticker]
    c = BY_TICKER.get(ticker) or dict(p0=100 + (zlib.crc32(ticker.encode()) % 300), drift=0.08, vol=0.18)
    rnd = random.Random(ticker)
    days, price, out = sessions(), c["p0"], []
    split_day, factor = SPLITS.get(ticker, (None, 1.0))
    later_splits = factor if split_day else 1.0
    for d in days:
        price *= math.exp((c["drift"] - c["vol"] ** 2 / 2) / 252 + c["vol"] / math.sqrt(252) * rnd.gauss(0, 1))
        adj = price
        s = 1.0
        if split_day and d.isoformat() >= split_day:
            later_splits = 1.0
        if split_day and d.isoformat() == split_day:
            s = factor
        raw = adj * later_splits                       # before the split, the printed price was higher
        out.append((d.isoformat(), round(raw, 4), round(adj, 4), s))
    _SERIES[ticker] = out
    return out


def demo_prices(today=None, seed=None, universe=None):
    """The demo's own closes, as prices.json keeps them: each line at the prices its trades were
    filled at, weekdays only, and the S&P 500 (SPY) along the Vanguard S&P 500 fund's walk, so
    the demo's comparisons with the market and its History have closes to read. No splits."""
    import generate_demo_data as g
    today = today or datetime.now(timezone.utc).date()
    _, prices = g.walks(random.Random(g.SEED if seed is None else seed), today, universe)
    store = {}
    for t, series in prices.items():
        store[t.split("_")[0]] = {d.isoformat(): {"c": round(p, 4), "a": round(p, 4)}
                                  for d, p in series.items() if d.weekday() < 5}
    store["SPY"] = dict(store["VOO"])
    first = min(min(v) for v in store.values())
    names = sorted(store)
    store.update({"_whole": {t: today.isoformat() for t in names}, "_starts": {t: first for t in names},
                  "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return store


_DEMO_CLOSES = {}


def _demo_closes():
    if not _DEMO_CLOSES:
        import generate_demo_data as g
        store = demo_prices(TODAY, universe=g.DEMO_UNIVERSE)
        _DEMO_CLOSES.update({k: v for k, v in store.items() if isinstance(v, dict) and k not in ("_whole", "_starts")})
    return _DEMO_CLOSES


def quarters_for(c, n=24):
    """Fiscal quarters ending on calendar quarter ends, oldest first, each filed 35 days later,
    only those filed by today."""
    rnd = random.Random(c["cik"])
    out, q_end = [], date(TODAY.year, ((TODAY.month - 1) // 3) * 3 + 1, 1) - timedelta(days=1)
    ends = []
    for _ in range(n + 2):
        ends.append(q_end)
        first = date(q_end.year, ((q_end.month - 1) // 3) * 3 + 1, 1)
        q_end = first - timedelta(days=1)
    for end in reversed(ends):
        filed = end + timedelta(days=35)
        if filed > TODAY:
            continue
        rev = c["revenue"] / 4 * (1 + rnd.uniform(-0.05, 0.12)) * (1.02 ** (len(out) / 4))
        gm = 0.25 + (c["cik"] % 50) / 100
        out.append({"start": (end - timedelta(days=90)).isoformat(), "end": end.isoformat(), "filed": filed.isoformat(),
                    "revenue": rev, "gross_profit": rev * gm, "operating_income": rev * (gm - 0.15),
                    "net_income": rev * (gm - 0.2), "eps": rev * (gm - 0.2) / 1.5e9,
                    "assets": rev * 6, "cash": rev * 0.8, "debt": rev * 1.2, "equity": rev * 2.5,
                    "liabilities": rev * 3.5, "annual": end.month == 12})
    return out


# ---- answers ---------------------------------------------------------------------------
class Answer(io.BytesIO):
    def __init__(self, body, status=200, headers=None, url=""):
        super().__init__(body if isinstance(body, bytes) else body.encode())
        self.status, self.code, self.url = status, status, url
        self.headers = dict(headers or {})
        self.headers.setdefault("Content-Type", "application/json")

    def getcode(self):
        return self.status

    def info(self):
        return self.headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _json(data, headers=None):
    return Answer(json.dumps(data), headers=headers)


def sec_submissions(c):
    """The company's filings: a 10-Q or 10-K for each quarter, an 8-K with each result, and
    some Form 4s; newest first, as EDGAR lists them."""
    rows = []
    for q in quarters_for(c):
        form = "10-K" if q["annual"] else "10-Q"
        acc = f"0000{c['cik'] % 100000:05d}-{q['filed'][2:4]}-{q['filed'][5:7]}{q['filed'][8:10]}01"
        rows.append((q["filed"], form, acc, f"{c['ticker'].lower()}-{q['end'].replace('-', '')}.htm", "",
                     f"{q['filed']}T16:05:12.000Z"))
        acc8 = acc[:-2] + "02"
        rows.append((q["filed"], "8-K", acc8, f"{c['ticker'].lower()}-8k.htm", "2.02,9.01", f"{q['filed']}T16:04:30.000Z"))
    rnd = random.Random(c["cik"] + 4)
    for k in range(10):
        d = TODAY - timedelta(days=rnd.randint(1, 360))
        acc = f"0000{c['cik'] % 100000:05d}-{d.strftime('%y')}-{d.strftime('%m%d')}{40 + k:02d}"
        rows.append((d.isoformat(), "4", acc, f"xslF345X05/wk-form4_{k}.xml", "", f"{d.isoformat()}T18:{10 + k}:00.000Z"))
    rows.sort(key=lambda r: r[0], reverse=True)
    recent = {"form": [], "filingDate": [], "accessionNumber": [], "primaryDocument": [], "items": [], "acceptanceDateTime": []}
    for day, form, acc, doc, items, accepted in rows:
        recent["form"].append(form); recent["filingDate"].append(day); recent["accessionNumber"].append(acc)
        recent["primaryDocument"].append(doc); recent["items"].append(items); recent["acceptanceDateTime"].append(accepted)
    return {"cik": str(c["cik"]), "name": c["name"], "sic": str(c["sic"]), "tickers": [c["ticker"]],
            "filings": {"recent": recent, "files": []}}


FORM4 = """<?xml version="1.0"?><ownershipDocument><issuer><issuerCik>{cik}</issuerCik></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>Chief Financial Officer</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>{day}</value></transactionDate>
<transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>{shares}</value></transactionShares><transactionPricePerShare><value>{price}</value></transactionPricePerShare></transactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""


def ten_k(c, year):
    risks = ["Competition could reduce our margins.", "Supply chains may be disrupted.",
             "Changes in trade policy may affect our sales." if year % 2 else "New regulation may raise our costs.",
             f"Demand in {year} may differ from our expectations."]
    mdna = [f"Revenue grew in fiscal {year}.", "Gross margin was stable.",
            "We invested in capacity." if year % 2 else "We returned cash to shareholders."]
    p = lambda xs: "".join(f"<p>{x}</p>" for x in xs)
    return (f"<html><body><p>Table of Contents</p><p>Item 1A. Risk Factors</p>{p(risks)}<p>Item 1B. Unresolved Staff Comments</p>"
            f"<p>None.</p><p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>"
            f"{p(mdna)}<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p><p>Rates.</p>"
            f"<p>Item 8. Financial Statements</p></body></html>")


CONCEPTS = {  # the first tag fundamentals.py and universe.py try for each figure
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("revenue", "USD", "flow"),
    "GrossProfit": ("gross_profit", "USD", "flow"), "OperatingIncomeLoss": ("operating_income", "USD", "flow"),
    "NetIncomeLoss": ("net_income", "USD", "flow"), "EarningsPerShareDiluted": ("eps", "USD/shares", "flow"),
    "CashAndCashEquivalentsAtCarryingValue": ("cash", "USD", "level"), "LongTermDebtNoncurrent": ("debt", "USD", "level"),
    "StockholdersEquity": ("equity", "USD", "level"), "Assets": ("assets", "USD", "level"),
    "Liabilities": ("liabilities", "USD", "level"),
}


def concept(c, tag):
    if tag not in CONCEPTS:
        return None
    figure, unit, kind = CONCEPTS[tag]
    rows = []
    qs = quarters_for(c)
    for i, q in enumerate(qs):
        form = "10-K" if q["annual"] else "10-Q"
        if kind == "flow":
            rows.append({"start": q["start"], "end": q["end"], "val": round(q[figure], 2), "form": form, "filed": q["filed"],
                         "fy": int(q["end"][:4]), "fp": "FY" if q["annual"] else "Q"})
            if q["annual"] and i >= 3:
                year = qs[i - 3:i + 1]
                rows.append({"start": year[0]["start"], "end": q["end"], "val": round(sum(x[figure] for x in year), 2),
                             "form": "10-K", "filed": q["filed"], "fy": int(q["end"][:4]), "fp": "FY"})
        else:
            rows.append({"end": q["end"], "val": round(q[figure], 2), "form": form, "filed": q["filed"],
                         "fy": int(q["end"][:4]), "fp": "FY" if q["annual"] else "Q"})
    return {"cik": c["cik"], "taxonomy": "us-gaap", "tag": tag, "units": {unit: rows}}


def frame(tag, unit, period):
    """Every company's value for one concept and one calendar period, as the frames API gives it."""
    m = re.match(r"CY(\d{4})(Q4I)?$", period)
    if not m or tag not in CONCEPTS and tag not in ("PaymentsToAcquirePropertyPlantAndEquipment",
                                                   "NetCashProvidedByUsedInOperatingActivities",
                                                   "WeightedAverageNumberOfDilutedSharesOutstanding",
                                                   "EntityCommonStockSharesOutstanding", "EntityPublicFloat",
                                                   "AssetsCurrent", "LiabilitiesCurrent", "RetainedEarningsAccumulatedDeficit"):
        return None
    year = int(m.group(1))
    data = []
    for c in COMPANIES:
        rnd = random.Random(f"{c['cik']}-{year}-{tag}")
        grow = 1.06 ** (year - 2020)
        rev = c["revenue"] * grow * rnd.uniform(0.95, 1.05)
        gm = 0.25 + (c["cik"] % 50) / 100
        values = {"RevenueFromContractWithCustomerExcludingAssessedTax": rev, "GrossProfit": rev * gm,
                  "OperatingIncomeLoss": rev * (gm - 0.15), "NetIncomeLoss": rev * (gm - 0.2) * rnd.uniform(0.8, 1.2),
                  "EarningsPerShareDiluted": rev * (gm - 0.2) / 1.5e9, "CashAndCashEquivalentsAtCarryingValue": rev * 0.8,
                  "LongTermDebtNoncurrent": rev * rnd.uniform(0.2, 1.5), "StockholdersEquity": rev * 2.5, "Assets": rev * 6,
                  "Liabilities": rev * 3.5, "AssetsCurrent": rev * 1.5, "LiabilitiesCurrent": rev * 1.0,
                  "RetainedEarningsAccumulatedDeficit": rev * 1.2,
                  "PaymentsToAcquirePropertyPlantAndEquipment": rev * 0.06,
                  "NetCashProvidedByUsedInOperatingActivities": rev * (gm - 0.1),
                  "WeightedAverageNumberOfDilutedSharesOutstanding": 1.5e9 * rnd.uniform(0.97, 1.03),
                  "EntityCommonStockSharesOutstanding": 1.5e9,
                  "EntityPublicFloat": 1.5e9 * series(c["ticker"])[-1][1] * 0.9 if c.get("featured") or c["cik"] < 900000 else rev * 3}
        data.append({"accn": "x", "cik": c["cik"], "entityName": c["name"], "loc": "US-CA",
                     "end": f"{year}-12-31", "val": round(values[tag], 4)})
    return {"taxonomy": "us-gaap", "tag": tag, "ccp": period, "uom": unit, "pts": len(data), "data": data}


def dera_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        lines = ["adsh\tcik\tname\tsic\tcountryba"]
        lines += [f"x-{c['cik']}\t{c['cik']}\t{c['name']}\t{c['sic']}\tUS" for c in COMPANIES]
        z.writestr("sub.txt", "\n".join(lines) + "\n")
    return buf.getvalue()


def short_name(c):
    """What a story calls the company: its first word for the real names (Apple), and for the invented
    ones the name without its legal form (Alder Devices), which is what the desk looks for."""
    if not DEMO:
        return c["name"].split(" ")[0].title()
    words = c["name"].replace(",", "").split(" ")
    while len(words) > 1 and words[-1] in ("Inc.", "Corp.", "Co.", "Holdings", "Group"):
        words.pop()
    return " ".join(words)


def headline_for(c, k, day):
    subjects = ["reports quarterly results", "shares move after analyst day", "faces regulator questions",
                "announces new product", "signs supply agreement", "names new finance chief"]
    return f"{short_name(c)} {subjects[(k + day.day) % len(subjects)]}"


def finnhub(path, query):
    t = (query.get("symbol") or [""])[0]
    c = BY_TICKER.get(t)
    if path == "company-news":
        if not c:
            return []
        start = date.fromisoformat(query["from"][0]); end = date.fromisoformat(query["to"][0])
        out, rnd = [], random.Random(f"news-{t}")
        d = start
        while d <= end:
            if rnd.random() < 0.5:
                at = datetime(d.year, d.month, d.day, rnd.randint(11, 23), rnd.randint(0, 59), tzinfo=timezone.utc)
                if at <= datetime.now(timezone.utc):
                    k = rnd.randint(0, 99)
                    out.append({"id": int(at.timestamp()), "datetime": int(at.timestamp()), "headline": headline_for(c, k, d),
                                "url": f"https://news.example.com/{t}/{d.isoformat()}/{k}", "source": rnd.choice(OUTLETS if DEMO else ["Yahoo", "SeekingAlpha", "Reuters"]),
                                "summary": f"{short_name(c)} said on {d.isoformat()} that business continued.", "category": "company"})
            d += timedelta(days=1)
        return sorted(out, key=lambda r: -r["datetime"])
    if path == "calendar/earnings":
        if not c:
            return {"earningsCalendar": []}
        last = quarters_for(c)[-1]
        nxt = date.fromisoformat(last["end"]) + timedelta(days=92 + 35 + (c["cik"] % 19 if DEMO else 0))
        if nxt <= TODAY:
            nxt = TODAY + timedelta(days=20)
        return {"earningsCalendar": [{"date": nxt.isoformat(), "hour": "amc", "epsEstimate": 1.23, "symbol": t,
                                      "quarter": 3, "year": nxt.year, "revenueEstimate": 1e9}]}
    if path == "stock/earnings":
        if not c:
            return []
        rnd = random.Random(f"eps-{t}")
        return [{"period": q["end"], "actual": round(q["eps"], 2), "estimate": round(q["eps"] * rnd.uniform(0.9, 1.1), 2),
                 "surprise": 0.01, "surprisePercent": 1.0, "symbol": t} for q in reversed(quarters_for(c)[-8:])]
    if path == "stock/recommendation":
        if not c:
            return []
        first = TODAY.replace(day=1)
        return [{"period": (first - timedelta(days=31 * i)).replace(day=1).isoformat(), "strongBuy": 10, "buy": 20, "hold": 8,
                 "sell": 1, "strongSell": 0, "symbol": t} for i in range(4)]
    return {}


def rss(query):
    if DEMO:              # no invented company has press coverage, and none is attributed to a real paper
        return '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>search</title></channel></rss>'
    m = re.search(r'"([^"]+)"', query)
    name = m.group(1) if m else query.split()[0]
    c = next((x for x in COMPANIES if x["name"].split(" ")[0].title().lower() == name.lower().split(" ")[0]), None)
    rnd = random.Random(f"rss-{query}")
    items = []
    for k in range(rnd.randint(2, 8)):
        at = datetime.now(timezone.utc) - timedelta(hours=rnd.randint(2, 24 * 25))
        outlet = OUTLETS[0] if "ft.com" in query else rnd.choice(OUTLETS[1:])
        title = f"{name.title()} {['wins contract', 'shares fall on outlook', 'sets out plans', 'weighs sale of unit'][k % 4]}"
        items.append(f"<item><title>{escape(title)} - {escape(outlet)}</title><link>https://news.google.com/rss/articles/{abs(hash((query, k)))}</link>"
                     f"<pubDate>{email.utils.format_datetime(at)}</pubDate><source url=\"https://example.com\">{escape(outlet)}</source></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>search</title>'
            + "".join(items) + "</channel></rss>")


# ---- Trading 212 ------------------------------------------------------------------------
_ACCOUNT = {}


def account():
    if not _ACCOUNT:
        import generate_demo_data
        _ACCOUNT.update(generate_demo_data.generate(TODAY, universe=generate_demo_data.DEMO_UNIVERSE if DEMO else None))
    return _ACCOUNT


def t212(path, query):
    a = account()
    if path == "/equity/account/summary":
        return dict(a["summary"], id=12345678)
    if path == "/equity/positions":
        return a["positions"]
    if path == "/equity/orders":
        return []
    if path == "/equity/metadata/instruments":
        return [{"ticker": p["instrument"]["ticker"], "name": p["instrument"]["name"], "type": "STOCK",
                 "currencyCode": "USD", "isin": ""} for p in a["positions"]] + [
                {"ticker": f"{c['ticker']}_US_EQ", "name": c["name"], "type": "STOCK", "currencyCode": "USD"}
                for c in COMPANIES[:11]]
    key = {"/equity/history/orders": "orders", "/equity/history/dividends": "dividends",
           "/equity/history/transactions": "transactions"}.get(path)
    if key:
        items, limit = a[key], int((query.get("limit") or ["50"])[0])
        start = int((query.get("cursor") or ["0"])[0])
        page = items[start:start + limit]
        nxt = f"/api/v0{path}?limit={limit}&cursor={start + limit}" if start + limit < len(items) else None
        return {"items": page, "nextPagePath": nxt}
    raise urllib.error.HTTPError("x", 404, "Not Found", {}, io.BytesIO(b""))


# ---- the router ------------------------------------------------------------------------
def source_of(url):
    host = urllib.parse.urlsplit(url).netloc
    if "trading212" in host: return "t212"
    if "tiingo" in host: return "tiingo"
    if "finnhub" in host: return "finnhub"
    if "news.google" in host: return "google"
    if "stlouisfed" in host: return "fred"
    if "openai" in host: return "openai"
    if "dera" in url: return "dera"
    if "/frames/" in url: return "frames"
    if "sec.gov" in host: return "sec"
    return "other:" + host


_COUNTING = threading.Lock()          # sources are asked side by side (server.run_steps' lanes)


def _count(source, url):
    with _COUNTING:
        ASKED[source] += 1
        LOG.append((source, re.sub(r"token=[^&]+", "token=…", url)))


def fault(source, url):
    mode = FAULTS.get(source)
    if not mode:
        return None
    if mode == "timeout":
        raise urllib.error.URLError(socket.timeout("timed out"))
    if mode == "refused":
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
    if mode.isdigit():
        body = b"Access Denied" if mode == "403" else b'{"error": "fault"}'
        headers = {"Retry-After": "1", "x-ratelimit-reset": str(time.time() + 0.5)}
        raise urllib.error.HTTPError(url, int(mode), "fault", headers, io.BytesIO(body))
    if mode == "garbage":
        return Answer(b"\x1f\x8b\x00garbage{{{")
    if mode == "html":
        return Answer(b"<html><body><h1>Your VPN session has expired</h1></body></html>", headers={"Content-Type": "text/html"})
    if mode == "empty":
        return Answer(b"")
    return None


def urlopen(req, timeout=None, **kw):
    """The answer, packed with gzip when the request asks for it, as the real sources do."""
    url = req.full_url if hasattr(req, "full_url") else str(req)
    source = source_of(url)
    _count(source, url)
    broken = fault(source, url)
    if broken is not None:
        return broken
    answer = _answer(req, url, source)
    asked = req.get_header("Accept-encoding") if hasattr(req, "get_header") else None
    if "gzip" in (asked or "") and isinstance(answer, Answer):
        import gzip
        packed = Answer(gzip.compress(answer.getvalue()), answer.status, dict(answer.headers, **{"Content-Encoding": "gzip"}))
        return packed
    return answer


def _answer(req, url, source):
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parts.query)
    path = parts.path
    if source == "t212":
        headers = {"x-ratelimit-remaining": "5", "x-ratelimit-reset": str(int(time.time()) + 60)}
        return _json(t212(path.replace("/api/v0", ""), query), headers)
    if source == "tiingo":
        if path.startswith("/iex"):
            tickers = (query.get("tickers") or [""])[0].split(",")
            now = datetime.now(timezone.utc)
            return _json([{"ticker": t.upper(), "tngoLast": series(t.upper())[-1][1] * 1.01, "last": None,
                           "timestamp": now.isoformat().replace("+00:00", "Z")} for t in tickers if t])
        m = re.match(r"/tiingo/daily/([^/]+)/prices", path)
        t = m.group(1).upper()
        if t not in BY_TICKER and t not in FUNDS:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"[]"))
        start = (query.get("startDate") or ["2000-01-01"])[0]
        rows = [{"date": d + "T00:00:00.000Z", "close": raw, "adjClose": adj, "splitFactor": s, "divCash": 0.0,
                 "open": raw, "high": raw, "low": raw, "volume": 1000000}
                for d, raw, adj, s in series(t) if d >= start]
        return _json(rows)
    if source == "fred":
        sid = (query.get("id") or [""])[0]
        base = {"DTB3": 4.2, "DEXUSEU": 1.09, "DEXUSUK": 1.27}.get(sid, 1.0)
        lines = [f"observation_date,{sid}"] + [f"{d.isoformat()},{base + (d.toordinal() % 7) / 100:.4f}" for d in sessions(date(2019, 1, 2))]
        return Answer("\n".join(lines) + "\n", headers={"Content-Type": "text/csv"})
    if source == "finnhub":
        return _json(finnhub(path.replace("/api/v1/", ""), query))
    if source == "google":
        return Answer(rss((query.get("q") or [""])[0]), headers={"Content-Type": "application/rss+xml"})
    if source == "openai":
        body = json.loads(req.data or b"{}")
        text = body.get("input", [{}])[0].get("content", [{}])[0].get("text", "")
        return _json({"output_text": "QA brief: the headlines were about " + ("results" if "result" in text.lower() else "the business") + "."})
    if source == "dera":
        return Answer(dera_zip(), headers={"Content-Type": "application/zip"})
    if source == "frames":
        m = re.match(r"/api/xbrl/frames/([^/]+)/([^/]+)/([^/]+)/([^/.]+)\.json", path)
        data = frame(m.group(2), m.group(3), m.group(4)) if m else None
        if data is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
        return _json(data)
    if source == "sec":
        if path.endswith("company_tickers.json"):
            return _json({str(i): {"cik_str": c["cik"], "ticker": c["ticker"], "title": c["name"]} for i, c in enumerate(COMPANIES)})
        if path.endswith("company_tickers_exchange.json"):
            return _json({"fields": ["cik", "name", "ticker", "exchange"],
                          "data": [[c["cik"], c["name"], c["ticker"], c["exchange"]] for c in COMPANIES]})
        m = re.match(r"/submissions/CIK(\d+)\.json", path)
        if m:
            c = BY_CIK.get(int(m.group(1)))
            if not c:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            return _json(sec_submissions(c))
        m = re.match(r"/api/xbrl/companyconcept/CIK(\d+)/us-gaap/([^/]+)\.json", path)
        if m:
            c = BY_CIK.get(int(m.group(1)))
            data = concept(c, m.group(2)) if c else None
            if data is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            return _json(data)
        if "companyfacts" in path:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
        m = re.match(r"/Archives/edgar/data/(\d+)/(\d+)/(.+)$", path)
        if m:
            c = BY_CIK.get(int(m.group(1)))
            doc = m.group(3)
            if doc.endswith(".xml"):
                rnd = random.Random(doc + m.group(2))
                return Answer(FORM4.format(cik=c["cik"], day=TODAY.isoformat(), code=rnd.choice("PSMA"),
                                           shares=rnd.randint(100, 20000), price=series(c["ticker"])[-1][1]),
                              headers={"Content-Type": "text/xml"})
            if "8k" in doc:
                return Answer("<html><body><p>Results of operations.</p></body></html>", headers={"Content-Type": "text/html"})
            year = int(re.search(r"(\d{4})\d{4}\.htm", doc).group(1)) if re.search(r"(\d{4})\d{4}\.htm", doc) else TODAY.year
            return Answer(ten_k(c, year), headers={"Content-Type": "text/html"})
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
    raise urllib.error.URLError(f"QA world has no {source}")


def install():
    """Every request the desk makes reaches this world; returns what puts things back."""
    import news, prices, headlines, earnings, universe
    saved = {"urlopen": urllib.request.urlopen, "gaps": (news.REQUEST_GAP, prices.REQUEST_GAP, headlines.REQUEST_GAP,
             earnings.REQUEST_GAP, universe.PAUSE, universe.BACKOFF), "env": dict(os.environ)}
    urllib.request.urlopen = urlopen
    news.REQUEST_GAP = prices.REQUEST_GAP = headlines.REQUEST_GAP = earnings.REQUEST_GAP = 0
    universe.PAUSE, universe.BACKOFF = 0, 0.01
    os.environ.update({"SEC_CONTACT": "qa@example.com", "TIINGO_API_KEY": "qa-tiingo", "FINNHUB_API_KEY": "qa-finnhub",
                       "OPENAI_API_KEY": "qa-openai", "T212_API_KEY": "qa-key", "T212_API_SECRET": "qa-secret",
                       "T212_ENV": "demo", "DESK_ENV_OVERRIDE": "1"})   # these win over a real .env
    FAULTS.clear(); ASKED.clear(); del LOG[:]

    def restore():
        urllib.request.urlopen = saved["urlopen"]
        (news.REQUEST_GAP, prices.REQUEST_GAP, headlines.REQUEST_GAP, earnings.REQUEST_GAP,
         universe.PAUSE, universe.BACKOFF) = saved["gaps"]
        os.environ.clear(); os.environ.update(saved["env"])
        FAULTS.clear()
    return restore
