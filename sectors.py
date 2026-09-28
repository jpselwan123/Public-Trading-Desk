"""What industry each company is in, and how it compares with the others in it.

Every figure on the Companies page currently stands alone. A 51% gross margin is
excellent for a grocer and poor for a software company, and without the peer group
the number cannot be read at all. This supplies the group.

Industry comes from the SIC code the company files under, taken from the SEC's own
quarterly Financial Statement Data Sets — one 79 MB download covering every filer,
against roughly a gigabyte to ask each company separately for the same field.

SIC is coarse and old — it was designed in the 1930s and last revised in 1987, so
it has four codes for different kinds of telephone company and one for all software
— but it is the classification the SEC actually assigns, it is free, and it comes
from the filing. The alternatives are proprietary.

Peers are taken from the narrowest grouping with enough members: the full 4-digit
industry where possible, then the 3-digit group, then the 2-digit major group.
Comparing a company with too few peers is worse than not comparing it, so the peer
count is reported with every figure and a percentile is withheld below MIN_PEERS.

Built by itself on the Mac when it is missing (27 Sep 2026): the company update fetches
the two latest quarters published (keep_up). By hand:

Usage: python3 sectors.py [--quarter 2025q2]
"""
import bisect, io, json, os, statistics, sys, urllib.error, urllib.request, zipfile
from datetime import date

from env_config import atomic_write_json, load_env, NO_SEC_CONTACT

HERE = os.path.dirname(os.path.abspath(__file__))
SECTORS_FILE = os.path.join(HERE, "sectors.json")
DERA = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"
TIMEOUT = 300
MIN_PEERS = 5                # below this a percentile says more about the group than the company
# Below this many companies reporting a measure (this one included), the page states a
# rank — "2nd highest of 6" — instead of a percentile. A percentile off n values moves
# in steps of 100/n, so under ten it claims a precision finer than the data has: "100"
# from five means "highest of five", which is a weaker statement (J-06). Ten is our
# choice, the review's "~10", not a published line.
RANK_BELOW = 10


class SectorError(Exception):
    pass


# The SIC divisions, as published by the SEC in its own code list. Used for a readable
# label, and to know a bank, insurer or property company, whose tagged revenue leaves
# out interest income (context.py, bridge.py, screen.py); the peer group is always the
# narrower numeric grouping.
FINANCIAL = "Finance, insurance and property"
DIVISIONS = (
    (100, 999, "Agriculture, forestry and fishing"),
    (1000, 1499, "Mining"),
    (1500, 1799, "Construction"),
    (2000, 3999, "Manufacturing"),
    (4000, 4999, "Transport, communications and utilities"),
    (5000, 5199, "Wholesale trade"),
    (5200, 5999, "Retail trade"),
    (6000, 6799, FINANCIAL),
    (7000, 8999, "Services"),
    (9100, 9729, "Public administration"),
)


# The SIC Manual's major groups, its two-digit codes (U.S. Department of Labor, Standard
# Industrial Classification Manual, 1987). A division puts Apple, Nvidia, Coca-Cola and
# Johnson & Johnson together as "Manufacturing"; a major group tells them apart.
MAJOR_GROUPS = {
    1: "Crop farming", 2: "Livestock farming", 7: "Agricultural services", 8: "Forestry", 9: "Fishing and hunting",
    10: "Metal mining", 12: "Coal mining", 13: "Oil and gas extraction", 14: "Mining and quarrying, except fuels",
    15: "Building construction", 16: "Heavy construction", 17: "Construction trades",
    20: "Food and drink products", 21: "Tobacco products", 22: "Textile mills", 23: "Apparel",
    24: "Lumber and wood products", 25: "Furniture and fixtures", 26: "Paper products", 27: "Printing and publishing",
    28: "Chemicals and drugs", 29: "Petroleum refining", 30: "Rubber and plastics products", 31: "Leather products",
    32: "Stone, clay and glass products", 33: "Primary metals", 34: "Fabricated metal products",
    35: "Industrial machinery and computer equipment", 36: "Electronic and electrical equipment",
    37: "Transportation equipment", 38: "Instruments, medical and optical goods", 39: "Miscellaneous manufacturing",
    40: "Railroads", 41: "Passenger transit", 42: "Trucking and warehousing", 43: "Postal service",
    44: "Water transportation", 45: "Air transportation", 46: "Pipelines, except natural gas",
    47: "Transportation services", 48: "Communications", 49: "Electric, gas and sanitary services",
    50: "Wholesale, durable goods", 51: "Wholesale, nondurable goods", 52: "Building materials and garden stores",
    53: "General merchandise stores", 54: "Food stores", 55: "Auto dealers and service stations",
    56: "Apparel stores", 57: "Home furnishing stores", 58: "Restaurants and bars", 59: "Miscellaneous retail",
    60: "Banks and savings institutions", 61: "Non-bank lenders", 62: "Brokers, dealers and exchanges",
    63: "Insurance carriers", 64: "Insurance agents and brokers", 65: "Real estate",
    67: "Holding and investment offices", 70: "Hotels and lodging", 72: "Personal services", 73: "Business services",
    75: "Auto repair and parking", 76: "Repair services", 78: "Motion pictures", 79: "Amusement and recreation",
    80: "Health services", 81: "Legal services", 82: "Education", 83: "Social services",
    84: "Museums and gardens", 86: "Membership organisations", 87: "Engineering, research and management services",
    88: "Private households", 89: "Other services", 91: "General government", 92: "Justice and public safety",
    93: "Public finance", 94: "Human resource programmes", 95: "Environment and housing programmes",
    96: "Economic programmes", 97: "National security", 99: "Not classified",
}


# Codes the SEC assigns that are not the manual's, and would otherwise be read as the
# major group their first two digits happen to share (8888 is not a private household).
SEC_ONLY = {8888: "Foreign governments", 9995: "Non-operating establishments"}


def major_group(sic):
    """The SIC Manual's major group for a code, in words, or None."""
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return None
    return SEC_ONLY.get(code) or MAJOR_GROUPS.get(code // 100)


def division(sic):
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return None
    for low, high, name in DIVISIONS:
        if low <= code <= high:
            return name
    return None


def fetch_quarter(quarter, who, opener=None):
    """cik → SIC, from one quarter of the SEC's Financial Statement Data Sets."""
    url = DERA.format(quarter=quarter)
    req = urllib.request.Request(url, headers={"User-Agent": f"trading-desk ({who})"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            blob = r.read()
    except urllib.error.HTTPError as e:
        raise SectorError(f"The SEC returned HTTP {e.code} for {quarter}: that quarter's "
                          "data set may not be published yet") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SectorError(f"Could not reach the SEC: {e}") from None
    out = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
        archive.getinfo("sub.txt")
    except (zipfile.BadZipFile, KeyError):
        raise SectorError(f"The SEC's data set for {quarter} came back in a form the desk does not read") from None
    with archive:
        with archive.open("sub.txt") as f:
            columns = f.readline().decode("utf-8", "replace").strip().split("\t")
            try:
                cik_at, sic_at = columns.index("cik"), columns.index("sic")
            except ValueError:
                raise SectorError("the SEC's sub.txt no longer has cik and sic columns") from None
            for line in f:
                fields = line.decode("utf-8", "replace").rstrip("\n").split("\t")
                if len(fields) <= max(cik_at, sic_at):
                    continue
                sic = fields[sic_at].strip()
                if not sic:
                    continue                 # funds and trusts carry no industry code
                try:
                    out[int(fields[cik_at])] = int(sic)
                except ValueError:
                    continue
    return out


def build(quarters, who=None, opener=None, log=print):
    """Merge several quarters: a company only appears in a quarter it filed in."""
    load_env(os.path.join(HERE, ".env"))
    who = who or os.environ.get("SEC_CONTACT", "").strip()
    if not who:
        raise SectorError(NO_SEC_CONTACT)
    by_cik = {}
    for quarter in quarters:
        found = fetch_quarter(quarter, who, opener)
        by_cik.update(found)             # a later quarter wins: industries do change
        log(f"  {quarter}: {len(found):,} filers with an industry code")
    return {"sic_by_cik": {str(k): v for k, v in by_cik.items()},
            "quarters": list(quarters), "source": "SEC Financial Statement Data Sets"}


def recent_quarters(today=None, count=3):
    """The last `count` calendar quarters that have ended, newest first ("2026q2")."""
    today = today or date.today()
    y, q = today.year, (today.month - 1) // 3        # the quarter before the current one
    out = []
    for _ in range(count):
        if q == 0:
            y, q = y - 1, 4
        out.append(f"{y}q{q}")
        q -= 1
    return out


def keep_up(today=None, fetch=None, log=lambda *a: None):
    """Build the industry codes when none are stored, from the two latest quarters the
    SEC has published: a quarter's data set comes out weeks after it ends, so the newest
    that fails to arrive is skipped for the one before. Codes change rarely: once built,
    they are kept (python3 sectors.py refreshes them by hand)."""
    if load():
        return None
    load_env(os.path.join(HERE, ".env"))
    who = os.environ.get("SEC_CONTACT", "").strip()
    if not who:
        raise SectorError(NO_SEC_CONTACT)
    by_cik, used, last = {}, [], None
    for quarter in recent_quarters(today):
        try:
            found = (fetch or fetch_quarter)(quarter, who)
        except SectorError as e:
            last = e
            continue
        for cik, sic in found.items():
            by_cik.setdefault(cik, sic)                # the newer quarter's code wins
        used.append(quarter)
        if len(used) == 2:
            break
    if not used:
        raise last or SectorError("No quarter's data set could be read")
    data = {"sic_by_cik": {str(k): v for k, v in by_cik.items()}, "quarters": used,
            "source": "SEC Financial Statement Data Sets"}
    atomic_write_json(SECTORS_FILE, data)
    return data


def load(path=None):
    try:
        with open(path or SECTORS_FILE) as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return {}
    codes = stored.get("sic_by_cik") if isinstance(stored, dict) else None
    return {int(k): v for k, v in codes.items() if str(k).isdigit()} if isinstance(codes, dict) else {}


# ---- peer groups ---------------------------------------------------------------------
def peer_key(sic, width):
    """The first `width` digits of a 4-digit code: 3571 → 357 → 35."""
    if sic is None:
        return None
    text = f"{int(sic):04d}"
    return text[:width]


def groups(companies, sic_by_cik):
    """{width: {key: [tickers]}} for the 4-, 3- and 2-digit groupings."""
    out = {4: {}, 3: {}, 2: {}}
    for ticker, row in companies.items():
        sic = sic_by_cik.get(row.get("cik"))
        if sic is None:
            continue
        for width in out:
            out[width].setdefault(peer_key(sic, width), []).append(ticker)
    return out


def peers_for(ticker, companies, sic_by_cik, by_width=None, minimum=MIN_PEERS):
    """The narrowest peer group with enough members, and how it was chosen."""
    row = companies.get(ticker) or {}
    sic = sic_by_cik.get(row.get("cik"))
    if sic is None:
        return {"peers": [], "sic": None, "width": None,
                "why": "the SEC has not assigned this filer an industry code"}
    by_width = by_width or groups(companies, sic_by_cik)
    for width in (4, 3, 2):
        members = by_width[width].get(peer_key(sic, width)) or []
        if len(members) >= minimum:
            return {"peers": members, "sic": sic, "width": width,
                    "division": division(sic),
                    "why": f"{len(members)} companies share the first {width} digits "
                           f"of SIC {sic:04d}"}
    widest = by_width[2].get(peer_key(sic, 2)) or []
    return {"peers": widest, "sic": sic, "width": 2, "division": division(sic),
            "why": f"only {len(widest)} companies share this industry, fewer than the "
                   f"{minimum} a percentile needs"}


def ranked(values):
    """A function placing any value among `values`, 0 to 100. Ties count as half, so a
    company in a group where everyone reports the same figure lands at 50 rather than
    100. Sorted once, so thousands of companies can each be placed quickly."""
    known = sorted(v for v in values if v is not None)

    def place(value):
        if value is None or len(known) < 2:
            return None
        below, through = bisect.bisect_left(known, value), bisect.bisect_right(known, value)
        return 100.0 * (below + 0.5 * (through - below)) / len(known)
    return place


def percentile(value, others):
    """Where `value` sits among `others`, 0 to 100, ties counting half (`ranked`)."""
    return ranked(others)(value)


def compare(ticker, measure_of, companies, sic_by_cik, measures=None, minimum=MIN_PEERS):
    """One company's figures against its peer group, as percentiles and medians."""
    found = peers_for(ticker, companies, sic_by_cik, minimum=minimum)
    mine = measure_of(companies.get(ticker) or {})
    names = measures or sorted(mine)
    out = {"ticker": ticker, "sic": found["sic"], "division": found.get("division"),
           "peers": len(found["peers"]), "why": found["why"], "measures": {}}
    if len(found["peers"]) < minimum:
        return out
    peer_values = [measure_of(companies[t]) for t in found["peers"] if t != ticker]
    for name in names:
        others = [v.get(name) for v in peer_values]
        known = sorted(v for v in others if v is not None)
        value = mine.get(name)
        out["measures"][name] = {
            "value": value,
            "percentile": percentile(value, others),
            # 1 = the highest value among those reporting it, this company included —
            # a position, not a judgement: for debt, highest is not best
            "rank": None if value is None else 1 + sum(1 for v in known if v > value),
            "of": None if value is None else len(known) + 1,
            # the average of the middle two for an even count — known[n // 2] took the
            # upper one, so every even-sized group's "median" leaned high (S-04)
            "median": statistics.median(known) if known else None,
            "reported_by": len(known),
        }
    return out


def main(argv):
    quarters = ["2025q1", "2025q2"]
    if "--quarter" in argv:
        quarters = [argv[argv.index("--quarter") + 1]]
    print(f"Fetching industry codes from the SEC for {', '.join(quarters)}…")
    data = build(quarters)
    atomic_write_json(SECTORS_FILE, data)
    codes = data["sic_by_cik"]
    print(f"\n{len(codes):,} filers with an industry code")
    print(f"Written to {os.path.basename(SECTORS_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
