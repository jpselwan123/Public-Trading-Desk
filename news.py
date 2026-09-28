"""Official company filings for your watchlist, from SEC EDGAR → news_data.json.

EDGAR is the primary source: a company's own filing appears here the moment it is
filed, before articles about it. Every item links back to the filing itself.

No API key. The SEC asks that automated requests declare a contact address
(https://www.sec.gov/os/webmaster-faq#developers), so set SEC_CONTACT in .env.

Usage: python3 news.py                   refresh filings for the companies followed
       python3 news.py --follow NVDA     follow one (dated), then refresh
"""
import json, os, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from env_config import load_env, atomic_write_json, moment, NO_SEC_CONTACT, unpacked

HERE = os.path.dirname(os.path.abspath(__file__))
NEWS_FILE = os.path.join(HERE, "news_data.json")
WATCHLIST_FILE = os.path.join(HERE, "watchlist.json")
CIK_CACHE = os.path.join(HERE, ".cik_map.json")

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
CIK_MAX_AGE_DAYS = 7
KEEP_DAYS = 365 * 6      # filing history kept per ticker (enough past events to measure reactions)
INSIDER_DAYS = 120       # how far back to read Form 4 detail (one fetch each, then cached)
REQUEST_GAP = 0.2        # SEC asks for no more than 10 requests a second
TIMEOUT = 30


class NewsError(Exception):
    pass


# ---- what each filing is, in plain words ------------------------------------------
FORMS = {
    "10-K": ("Annual report", "The full yearly report: business, risks, audited accounts."),
    "10-Q": ("Quarterly report", "The quarter's accounts in full."),
    "8-K": ("Company announcement", "Something the company must report between quarters."),
    "4": ("Insider trade", "A director or officer bought or sold their own company's shares."),
    "144": ("Planned insider sale", "Notice that an insider intends to sell shares."),
    "SC 13D": ("Big stake, active", "An investor crossed 5% and intends to influence the company."),
    "SC 13G": ("Big stake, passive", "An investor crossed 5% as a passive holder."),
    "DEF 14A": ("Shareholder meeting", "Voting agenda, board pay, and proposals."),
    "S-1": ("Share registration", "New shares registered for sale."),
    "S-3": ("Share registration", "New shares registered for sale."),
    "6-K": ("Company announcement", "Report from a company based outside the US."),
    "20-F": ("Annual report", "Yearly report from a company based outside the US."),
    # The rest of what a covered company's filing list actually holds (S-31), each in the
    # SEC's own terms from its form descriptions. EDGAR renamed "SC 13D" and "SC 13G" to
    # "SCHEDULE 13D" and "SCHEDULE 13G" in December 2024; both names are here.
    "10-K/A": ("Annual report, amended", "A correction or addition to an annual report."),
    "10-Q/A": ("Quarterly report, amended", "A correction or addition to a quarterly report."),
    "8-K/A": ("Company announcement, amended", "A correction or addition to an earlier announcement."),
    "3": ("Insider's first holdings", "A new director, officer or 10% owner reports the shares they hold."),
    "4/A": ("Insider trade, amended", "A correction to an earlier insider trade report."),
    "5": ("Insider's yearly report", "An insider's annual report of holdings changes not reported earlier."),
    "SCHEDULE 13D": ("Big stake, active", "An investor crossed 5% and intends to influence the company."),
    "SCHEDULE 13G": ("Big stake, passive", "An investor crossed 5% as a passive holder."),
    "SC 13D/A": ("Big stake, active: update", "An investor holding over 5% to influence the company updates its stake or plans."),
    "SCHEDULE 13D/A": ("Big stake, active: update", "An investor holding over 5% to influence the company updates its stake or plans."),
    "SC 13G/A": ("Big stake, passive: update", "A passive holder of over 5% updates its stake."),
    "SCHEDULE 13G/A": ("Big stake, passive: update", "A passive holder of over 5% updates its stake."),
    "DEFA14A": ("Shareholder meeting: more material", "Additional material the company filed for a shareholder vote."),
    "DFAN14A": ("Shareholder meeting: others' material", "Material for a shareholder vote filed by someone other than the company."),
    "PRE 14A": ("Shareholder meeting, draft", "A preliminary voting agenda, before the final one."),
    "PX14A6G": ("Shareholder campaign", "A shareholder's notice of exempt solicitation ahead of a vote."),
    "ARS": ("Annual report to shareholders", "The annual report as sent to shareholders."),
    "11-K": ("Employee plan accounts", "The yearly accounts of an employee share or savings plan."),
    "S-3ASR": ("Share registration", "Securities registered for sale by a large, established company, effective at once."),
    "S-8": ("Employee share registration", "Shares registered for employee pay and benefit plans."),
    "S-8 POS": ("Employee share registration, amended", "A change to an earlier employee share registration."),
    "EFFECT": ("Registration effective", "The SEC's notice that a registration statement took effect."),
    "25-NSE": ("Listing removed", "An exchange removes a security from listing, usually a bond that matured or was redeemed."),
    "13F-HR": ("Holdings report", "A large investment manager's quarterly list of the shares it holds."),
    "SD": ("Conflict minerals report", "Specialized disclosure, mostly on conflict minerals in its products."),
    "CORRESP": ("Letter to the SEC", "The company's reply to questions from the SEC's staff."),
    "UPLOAD": ("Letter from the SEC", "A letter from the SEC's staff about the company's filings."),
    "S-4": ("Merger registration", "Shares registered to pay for a merger or acquisition."),
    "425": ("Merger communication", "A public statement about a planned merger or acquisition."),
    "POSASR": ("Share registration, amended", "A change to an earlier automatic share registration."),
    "8-A12B": ("Listing registration", "A class of securities registered for listing on an exchange."),
    "15-12B": ("Registration ended", "The registration of a class of securities is withdrawn."),
    "CERT": ("Listing approved", "An exchange certifies that it has approved a security for listing."),
    "IRANNOTICE": ("Iran disclosure notice", "Notice that a periodic report discloses dealings covered by US Iran sanctions law."),
}
# Offering documents for one particular security, not news about the company. A bank
# files one for every structured note it issues: JPMorgan has 95,941 424B2 pricing
# supplements and 8,632 free-writing prospectuses on record, against 671 insider
# trades. Kept, they buried every other filing and made each page build take four
# minutes. A company's decision to raise money is still here — in the registration
# statement (S-1, S-3) and the 8-K that announces it; only the per-issue terms go.
SKIPPED_FORMS = {"424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8", "FWP"}


def skipped(form):
    return str(form or "").upper() in SKIPPED_FORMS


# 8-K item codes → plain words (SEC Form 8-K, items 1.01–9.01)
ITEMS = {
    "1.01": "Signed a major agreement",
    "1.02": "Ended a major agreement",
    "1.03": "Bankruptcy",
    "2.01": "Completed a purchase or sale of a business",
    "2.02": "Results announced",
    "2.03": "Took on debt",
    "2.04": "Debt terms triggered",
    "2.05": "Restructuring costs",
    "2.06": "Assets written down",
    "3.01": "Listing or rules problem",
    "3.02": "Sold shares privately",
    "3.03": "Shareholder rights changed",
    "4.01": "Changed auditor",
    "4.02": "Past accounts can't be relied on",
    "5.01": "Change of control",
    "5.02": "Leadership change",
    "5.03": "Company rules changed",
    "5.07": "Shareholder vote results",
    "7.01": "Company statement",
    "8.01": "Other news",
    "9.01": "Documents attached",
}
MATERIAL = {"2.02", "1.01", "5.02", "2.01", "4.02", "1.03", "2.05", "2.06", "3.01", "5.01"}


def label_for(form, items):
    base = form.upper()[:-2] if form.upper().endswith("/A") else None
    if form.upper() not in FORMS and base in FORMS:     # an amendment of a known form
        name, why = FORMS[base][0] + ", amended", "A correction or addition to an earlier filing of this kind."
    else:
        name, why = FORMS.get(form.upper(), (form, "Filed with the SEC."))
    codes = [c.strip() for c in (items or "").split(",") if c.strip()]
    plain = [ITEMS[c] for c in codes if c in ITEMS]
    if plain:
        return name, "; ".join(plain), any(c in MATERIAL for c in codes)
    return name, why, form.upper() in ("10-K", "10-Q", "SC 13D", "SCHEDULE 13D")


# ---- fetching ----------------------------------------------------------------------
def user_agent():
    load_env(os.path.join(HERE, ".env"))
    contact = os.environ.get("SEC_CONTACT", "").strip()
    if not contact:
        raise NewsError(NO_SEC_CONTACT)
    return f"trading-desk personal research ({contact})"


def fetch_json(url, ua, opener=None, sleep=time.sleep):
    req = urllib.request.Request(url, method="GET", headers={
        "User-Agent": ua, "Accept": "application/json", "Accept-Encoding": "gzip"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            body = unpacked(r.read(), r)
            sleep(REQUEST_GAP)
            return json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 403:
            raise NewsError("The SEC refused the request: check SEC_CONTACT in .env") from None
        if e.code == 429:
            raise NewsError("The SEC asked the desk to slow down (HTTP 429); the next update carries on") from None
        raise NewsError(f"SEC returned HTTP {e.code}") from None
    except Exception as e:                       # network, timeout, bad JSON
        raise NewsError(f"Can't reach the SEC ({e})") from None


def cik_map(ua, fetch=fetch_json):
    """ticker → CIK, cached for a week (the file is ~800 KB)."""
    try:
        cached = json.load(open(CIK_CACHE))
        age = datetime.now(timezone.utc) - moment(cached["fetched_at"])
        if age < timedelta(days=CIK_MAX_AGE_DAYS):
            return cached["map"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raw = fetch(TICKERS_URL, ua) or {}
    mapping = {str(v["ticker"]).upper(): int(v["cik_str"]) for v in raw.values()}
    atomic_write_json(CIK_CACHE, {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  "map": mapping})
    return mapping


# ---- Form 4: what the insider actually did ----------------------------------------
# SEC Form 4 transaction codes (General Instruction 8 to Form 4)
TX_CODES = {
    "P": ("Bought on the open market", True),
    "S": ("Sold", False),
    "A": ("Received a share award", False),
    "M": ("Exercised options", False),
    "F": ("Shares withheld for tax", False),
    "G": ("Gift", False),
    "C": ("Converted a security", False),
    "X": ("Exercised options", False),
    "D": ("Returned shares to the company", False),
}


def raw_form4_url(cik, accession, primary_doc):
    """The submissions feed points at the styled view (xslF345X03/...); the plain
    XML sits beside it, without that folder."""
    doc = (primary_doc or "").split("/")[-1]
    if not doc.endswith(".xml"):
        return None
    return FILING_URL.format(cik=cik, acc_nodash=accession.replace("-", ""), doc=doc)


def fetch_text(url, ua, opener=None, sleep=time.sleep):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": ua, "Accept": "application/xml",
                                                             "Accept-Encoding": "gzip"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            body = unpacked(r.read(), r).decode("utf-8", "replace")
            sleep(REQUEST_GAP)
            return body
    except Exception:
        return None


def parse_form4(xml_text):
    """→ {'person', 'role', 'actions': [...]} or None. Money figures are the
    filing's own share count × price per share."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None
    name = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or "An insider"
    rel = root.find(".//reportingOwnerRelationship")
    role = ""
    if rel is not None:
        title = (rel.findtext("officerTitle") or "").strip()
        if title:
            role = title
        elif (rel.findtext("isDirector") or "0") == "1":
            role = "Director"
        elif (rel.findtext("isTenPercentOwner") or "0") == "1":
            role = "10% shareholder"
    planned = (root.findtext(".//aff10b5One") or "0") == "1"
    actions = []
    for t in root.findall(".//nonDerivativeTransaction"):
        code = t.findtext(".//transactionCoding/transactionCode") or ""
        shares = _val(t, ".//transactionShares")
        price = _val(t, ".//transactionPricePerShare")
        label, is_buy = TX_CODES.get(code.upper(), ("Other transaction", False))
        if code.upper() == "S" and planned:
            label = "Sold under a preset plan"
        actions.append({
            "code": code.upper(), "what": label, "buy": is_buy, "planned": planned,
            "shares": shares, "price": price,
            "value": (shares or 0) * (price or 0) if shares and price else None,
            "date": t.findtext(".//transactionDate/value") or "",
        })
    return {"person": name.title(), "role": role, "actions": actions,
            "bought": any(a["buy"] for a in actions)}


def _val(node, path):
    el = node.find(path)
    if el is None:
        return None
    text = (el.findtext("value") if el.find("value") is not None else el.text) or ""
    try:
        return float(text)
    except ValueError:
        return None


def describe_insider(detail, company_currency="USD"):
    """One plain line: who did what."""
    if not detail:
        return None, False
    who = detail["person"] + (f" ({detail['role']})" if detail["role"] else "")
    parts = []
    for a in detail["actions"]:
        n = f"{a['shares']:,.0f} shares" if a["shares"] else "shares"
        money = f" (~${a['value']:,.0f})" if a.get("value") else ""
        parts.append(f"{a['what'].lower()}: {n}{money}")
    if not parts:
        return f"{who} filed an insider report", False
    return f"{who} — " + "; ".join(parts), detail["bought"]


def filings_for(ticker, cik, ua, since, fetch=fetch_json, insiders=None, get_text=fetch_text,
                insider_since=None, known=None):
    """(the filer's name, its filings since `since`). EDGAR keeps a company's latest filings
    in one list (at least a year of them, or its last thousand) and the older ones in more
    files. Those files cannot change, so with `known` — (the day this company's filings
    were last read in full, the filings stored then) — they are not asked for again when that
    day is on or after the oldest filing in the latest list: every older filing was already
    read then, and the stored ones stand for them. A bank's older files were dozens of
    downloads every half hour (27 Sep 2026)."""
    data = fetch(SUBMISSIONS_URL.format(cik=cik), ua)
    if not data:
        return None, []
    filings = data.get("filings") or {}
    recent = filings.get("recent") or {}
    out = _rows(ticker, cik, ua, since, recent, data, insiders, get_text, insider_since)
    oldest = min((d for d in recent.get("filingDate") or [] if d), default="")
    read_on, stored = known if known else (None, None)
    if read_on and oldest and read_on >= oldest:
        listed = {i["id"] for i in out}
        return data.get("name") or ticker, out + [i for i in stored or [] if i.get("ticker") == ticker
                                                   and i.get("id") not in listed and (i.get("date") or "") <= oldest
                                                   and (i.get("date") or "") >= since]
    # EDGAR splits long histories: older filings live in extra JSON files
    for extra in (filings.get("files") or []):
        if (extra.get("filingTo") or "9999") >= since and extra.get("name"):
            older = fetch(f"https://data.sec.gov/submissions/{extra['name']}", ua)
            if older:
                out.extend(_rows(ticker, cik, ua, since, older, data, insiders, get_text, insider_since))
    return data.get("name") or ticker, out


def filed_moment(stamp, clock=None):
    """When a filing was accepted, as an aware time in New York, or None.

    The SEC writes acceptance times like "2026-09-18T16:05:00.000Z", but the clock is its
    own, New York's: EDGAR takes filings from 6:00 to 22:00 Eastern time, and those are the
    hours its times fall in, not four or five hours later. So the "Z" is not read as UTC. An
    earnings release filed at 16:05 is after that day's close, and moves the next session.
    A filing with a date alone has no time, and is None: when in the day it came is unknown.
    doctor.py reports the hours the stored times span, which checks this reading."""
    m = re.match(r"^(\d{4}-\d\d-\d\d)T(\d\d):(\d\d)(?::(\d\d))?", str(stamp or ""))
    if not m:
        return None
    try:
        local = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4) or '00'}")
    except ValueError:
        return None
    if clock is None:
        from prices import MARKET_TZ as clock          # here: prices reads this module
    return local.replace(tzinfo=clock)


def _rows(ticker, cik, ua, since, recent, data, insiders, get_text, insider_since):
    out = []
    for i, form in enumerate(recent.get("form") or []):
        day = (recent.get("filingDate") or [])[i]
        if day < since or skipped(form):
            continue
        acc = (recent.get("accessionNumber") or [])[i]
        doc = (recent.get("primaryDocument") or [])[i] if recent.get("primaryDocument") else ""
        name, why, material = label_for(form, (recent.get("items") or [""] * (i + 1))[i])
        if form.upper() == "4" and insiders is not None and day >= (insider_since or since):
            detail = insiders.get(acc)
            if detail is None:
                url = raw_form4_url(cik, acc, doc)
                text = get_text(url, ua) if url else None
                detail = parse_form4(text) if text else {}
                insiders[acc] = detail          # cache even a failure, so it is tried once
            line, bought = describe_insider(detail or None)
            if line:
                why = line
                material = bought              # open-market purchases are the notable ones
                name = "Insider bought" if bought else "Insider trade"
        out.append({
            "ticker": ticker,
            "company": data.get("name") or ticker,
            "form": form,
            "label": name,
            "what": why,
            "material": material,
            "date": day,
            "filed_at": (recent.get("acceptanceDateTime") or [""] * (i + 1))[i] or day,
            "id": acc,
            "url": FILING_URL.format(cik=cik, acc_nodash=acc.replace("-", ""), doc=doc) if doc else
                   f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}",
        })
    return out


# ---- coverage: the companies followed, and since when ---------------------------------
# A watchlist is a list; a coverage list is a commitment (fourth review, Phase 6). The
# cap is what makes it one: a sixteenth company must name the one it replaces. The number
# is the review's, not a published one — a count a person can keep up with. A reason was
# required until 26 Sep 2026 and optional until 27 Sep, when the user removed it: a
# ticker alone follows a company. Reasons stored before then are left in the file, unread.
MAX_COVERAGE = 15
TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,7}$")


class CoverageError(NewsError):
    pass


def load_coverage(path=None, strict=False):
    """{"tickers": [...], "coverage": {TICKER: {"followed_at"}}, "past": [...]}.
    A list saved before coverage was kept has tickers with no record: followed before
    the desk kept dates. `strict`, for a change about to be written: a list that is there
    but cannot be read raises CoverageError, so its companies and their dates are never
    written over."""
    try:
        with open(path or WATCHLIST_FILE) as f:
            wl = json.load(f)
    except FileNotFoundError:
        wl = {}
    except (OSError, ValueError):
        wl = None
    if strict and not isinstance(wl, (dict, list)):
        raise CoverageError(f"{os.path.basename(path or WATCHLIST_FILE)} cannot be read, so nothing was written "
                            "over it: open it to mend it, or move it aside to start a new list.")
    if isinstance(wl, list):
        wl = {"tickers": wl}
    if not isinstance(wl, dict):
        wl = {}
    tickers = [str(t).upper() for t in wl.get("tickers") or []]
    coverage = {str(k).upper(): v for k, v in (wl.get("coverage") or {}).items()
                if str(k).upper() in tickers and isinstance(v, dict)}
    return {"tickers": tickers, "coverage": coverage, "past": list(wl.get("past") or [])}


def load_watchlist(path=None):
    return load_coverage(path)["tickers"]


def save_watchlist(tickers, coverage=None, past=None, path=None):
    """The one writer. Refuses more than MAX_COVERAGE companies. Records not passed in
    are kept as stored, so saving a list never erases a follow date."""
    if coverage is None or past is None:
        stored = load_coverage(path, strict=True)
        coverage = stored["coverage"] if coverage is None else coverage
        past = stored["past"] if past is None else past
    seen, out = set(), []
    for t in tickers:
        t = str(t).strip().upper()
        if t and t not in seen and TICKER.match(t):
            seen.add(t)
            out.append(t)
    if len(out) > MAX_COVERAGE:
        raise CoverageError(f"The desk covers at most {MAX_COVERAGE} companies; "
                            f"name the one this replaces.")
    record = {"tickers": out, "coverage": {t: v for t, v in (coverage or {}).items() if t in seen}}
    if past:
        record["past"] = past
    atomic_write_json(path or WATCHLIST_FILE, record, indent=1)
    return out


def follow(ticker, replaces=None, today=None, path=None):
    """Start following a company, dated today. At the cap, only by naming the company it
    replaces, which leaves with its record kept.

    A company on the list from before follow dates were kept has no record, and a past
    day cannot place it (K-03). Following it again dates it today — the earliest day the
    desk can vouch for (S-29). Stopping and re-following would have written a stop that
    never happened into `past`."""
    ticker = str(ticker or "").strip().upper()
    if not TICKER.match(ticker):
        raise CoverageError(f"{ticker or 'That'} is not a ticker.")
    state = load_coverage(path, strict=True)
    tickers, coverage, past = state["tickers"], state["coverage"], state["past"]
    if ticker in tickers and (coverage.get(ticker) or {}).get("followed_at"):
        raise CoverageError(f"You already follow {ticker}.")
    today = (today or datetime.now(timezone.utc).date()).isoformat()
    record = {"followed_at": today}
    if ticker in tickers:                              # on the list, never dated: record it now
        coverage[ticker] = record
        return save_watchlist(tickers, coverage, past, path)
    if replaces:
        replaces = str(replaces).strip().upper()
        if replaces not in tickers:
            raise CoverageError(f"{replaces} is not one you follow.")
        tickers = [t for t in tickers if t != replaces]
        past.append(dict(coverage.pop(replaces, {}), ticker=replaces, stopped_at=today,
                         replaced_by=ticker))
    elif len(tickers) >= MAX_COVERAGE:
        raise CoverageError(f"You already follow {MAX_COVERAGE} companies, the most the desk "
                            f"covers. Name the one {ticker} replaces.")
    coverage[ticker] = record
    return save_watchlist(tickers + [ticker], coverage, past, path)


def date_undated(today=None, path=None):
    """Date every company on the list from before follow dates were kept, from today: the
    earliest day the desk can vouch for (S-29). A past day still cannot place it before
    then. Done through follow(), so nothing is written into `past`. Returns those dated."""
    state = load_coverage(path, strict=True)
    undated = [t for t in state["tickers"] if not (state["coverage"].get(t) or {}).get("followed_at")]
    for ticker in undated:
        follow(ticker, today=today, path=path)
    return undated


def unfollow(ticker, today=None, path=None):
    """Stop following. The dates are kept in `past`, not discarded: what was followed,
    and when, is part of the record of judgement."""
    ticker = str(ticker or "").strip().upper()
    state = load_coverage(path, strict=True)
    if ticker not in state["tickers"]:
        raise CoverageError(f"{ticker} is not one you follow.")
    today = (today or datetime.now(timezone.utc).date()).isoformat()
    past = state["past"] + [dict(state["coverage"].get(ticker, {}), ticker=ticker, stopped_at=today)]
    return save_watchlist([t for t in state["tickers"] if t != ticker],
                          state["coverage"], past, path)


def refresh(tickers=None, ua=None, fetch=fetch_json, today=None, insiders=None, get_text=fetch_text, stored=None):
    """Each company's filings of the last KEEP_DAYS. With `stored` (the last news_data.json),
    a company's older filings are kept from it rather than downloaded again when they cannot
    have changed (filings_for)."""
    ua = ua or user_agent()
    tickers = tickers or load_watchlist()
    today = today or datetime.now(timezone.utc).date()
    since = (today - timedelta(days=KEEP_DAYS)).isoformat()
    insider_since = (today - timedelta(days=INSIDER_DAYS)).isoformat()
    insiders = {} if insiders is None else insiders
    ciks = cik_map(ua, fetch=fetch)
    read = dict((stored or {}).get("read") or {})
    items, companies, unknown = [], {}, []
    for t in tickers:
        cik = ciks.get(t.upper())
        if not cik:
            unknown.append(t)
            continue
        known = (read.get(t.upper()), (stored or {}).get("items")) if read.get(t.upper()) else None
        name, rows = filings_for(t.upper(), cik, ua, since, fetch=fetch, insiders=insiders,
                                 get_text=get_text, insider_since=insider_since, known=known)
        companies[t.upper()] = name or t.upper()
        items.extend(rows)
        read[t.upper()] = today.isoformat()
    items.sort(key=lambda r: (r["filed_at"], r["ticker"]), reverse=True)
    return {
        "tickers": [t.upper() for t in tickers],
        "companies": companies,
        "unknown": unknown,
        "items": items,
        "insiders": insiders,
        # the day each company's filings were last read: what the next update may keep
        "read": {t: d for t, d in read.items() if t in {x.upper() for x in tickers}},
        "source": "SEC EDGAR",
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


FOLLOW_USAGE = "python3 news.py --follow NVDA"


def main(argv):
    """python3 news.py: pull the covered companies' filings. With --follow TICKER,
    follow one first — through follow(), like the page, so it has its date (S-17: a bare
    ticker here once joined the list with none)."""
    try:
        if argv[:1] == ["--follow"]:
            if len(argv) < 2:
                print("Which company? " + FOLLOW_USAGE, file=sys.stderr)
                return 2
            follow(argv[1])
        elif argv:
            print("To follow a company: " + FOLLOW_USAGE, file=sys.stderr)
            return 2
        watchlist = load_watchlist()
        if not watchlist:
            print("No company followed yet: " + FOLLOW_USAGE, file=sys.stderr)
            return 2
        stored = {}
        try:
            with open(NEWS_FILE) as f:
                stored = json.load(f)
        except (OSError, ValueError):
            pass
        data = refresh(watchlist, insiders=stored.get("insiders") or {})
        atomic_write_json(NEWS_FILE, data)
        print(f"{len(data['items'])} filings for {len(watchlist)} tickers"
              + (f" (unknown: {', '.join(data['unknown'])})" if data["unknown"] else ""))
        return 0
    except NewsError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
