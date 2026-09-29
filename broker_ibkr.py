"""The account from Interactive Brokers' Flex reports, read only (BROKER=ibkr).

    IBKR_FLEX_TOKEN   the Flex Web Service token (Client Portal: Performance & Reports → Flex
                      Queries → Flex Web Service Configuration)
    IBKR_FLEX_QUERY   the number of an Activity Flex Query with these sections: Account
                      Information, Open Positions, Trades (executions), Cash Transactions,
                      Cash Report, Net Asset Value (NAV) in Base (docs/BROKERS.md)

Two requests, as IBKR's service asks: one to have the statement made, one to collect it (tried
again while IBKR says it is still being made). Everything is read in the account's base
currency, each amount through the rate IBKR gives with it (fxRateToBase). Stocks and funds are
read; currency conversions inside the account move nothing in the base currency and are left
out; options and futures are not read, and an account holding them will not tie in the checks.

A Flex query reaches back a year at most. The desk keeps what each sync read (merged by IBKR's
own references), so the history grows from the first sync; for earlier years, run the query
once with an earlier period (docs/BROKERS.md). The account number is never kept.
"""
import os, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

import broker
from env_config import load_env, read, unpacked

HERE = os.path.dirname(os.path.abspath(__file__))
SEND = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
TIMEOUT = 60
WAITS = (3, 5, 8, 12, 20, 30)          # seconds between tries while IBKR makes the statement
IN_PROGRESS = ("1003", "1004", "1005", "1006", "1007", "1008", "1009", "1018", "1019", "1021")
STOCKS = ("STK", "FUND", "ETF")
DETAIL = ("EXECUTION", "DETAIL", "")      # a row per execution or movement, not a summary
DEPOSITS = ("depositswithdrawals", "depositsandwithdrawals")
DIVIDEND_TYPES = ("dividends", "paymentinlieuofdividends")
INTEREST_TYPES = ("brokerinterestreceived", "brokerinterestpaid", "bondinterestreceived", "bondinterestpaid")
FEE_TYPES = ("otherfees", "commissionadjustments", "advisorfees")


def credentials(environ=None):
    if environ is None:
        load_env(os.path.join(HERE, ".env"))
        environ = os.environ
    token = str(environ.get("IBKR_FLEX_TOKEN") or "").strip()
    query = str(environ.get("IBKR_FLEX_QUERY") or "").strip()
    if not token or not query:
        raise broker.BrokerError("No Interactive Brokers report yet: add IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY "
                                 "to .env (docs/BROKERS.md)")
    return token, query


def _get(url, opener=None, sleep=time.sleep):
    req = urllib.request.Request(url, headers={"User-Agent": "trading-desk (personal, read only)",
                                               "Accept-Encoding": "gzip"})
    try:
        body, r = read(req, opener, TIMEOUT, sleep)
        return ET.fromstring(unpacked(body, r))
    except urllib.error.HTTPError as e:
        raise broker.BrokerError(f"Interactive Brokers: HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise broker.BrokerError(f"Interactive Brokers did not answer ({getattr(e, 'reason', e)})") from None
    except ET.ParseError:
        raise broker.BrokerError("Interactive Brokers answered with something that is not a report") from None


def _said(root):
    return (root.findtext("Status") or "").strip(), (root.findtext("ErrorCode") or "").strip(), \
        (root.findtext("ErrorMessage") or "").strip()


def fetch(token, query, opener=None, sleep=time.sleep):
    """The statement, as IBKR's Flex Web Service gives it: asked for, then collected."""
    root = _get(SEND + "?" + urllib.parse.urlencode({"t": token, "q": query, "v": 3}), opener, sleep)
    status, code, message = _said(root)
    if status != "Success":
        raise broker.BrokerError(f"Interactive Brokers refused the report: {message or status} ({code})")
    reference, url = root.findtext("ReferenceCode"), root.findtext("Url")
    if not reference or not url:
        raise broker.BrokerError("Interactive Brokers gave no reference to collect the report by")
    for wait in (0,) + WAITS:
        if wait:
            sleep(wait)
        statement = _get(url + "?" + urllib.parse.urlencode({"t": token, "q": reference, "v": 3}), opener, sleep)
        if statement.tag == "FlexQueryResponse":
            return statement
        status, code, message = _said(statement)
        if code not in IN_PROGRESS:
            raise broker.BrokerError(f"Interactive Brokers: {message or status} ({code})")
    raise broker.BrokerError("Interactive Brokers was still making the report: sync again in a minute")


def _num(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _plain(text):
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def when(row):
    """An ISO time from IBKR's date and time as the query writes them (20240115;093000,
    2024-01-15, 09:30:00, 20240115): the exchange's own day kept as it is."""
    raw = str(row.get("dateTime") or row.get("tradeDate") or row.get("reportDate") or row.get("settleDate") or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 8:
        raise broker.BrokerError(f"a report row with no date it can be placed on ({raw!r})")
    time_part = (digits[8:14] + "000000")[:6] if len(digits) > 8 else "120000"
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}Z"


def _rate(row, base):
    """Base currency per unit of the row's own: IBKR's rate, 1 for the base itself."""
    if (row.get("currency") or base) == base:
        return 1.0
    rate = _num(row.get("fxRateToBase"))
    if not rate:
        raise broker.BrokerError(f"a {row.get('currency')} amount with no rate to the account's currency")
    return rate


def _code(row):
    return broker.line_code(row.get("symbol"), row.get("listingExchange") or row.get("exchange") or "US")


def _rows(statement, section, element):
    """Every `element` row under the statement's `section` (or anywhere, if the query nests it otherwise)."""
    found = statement.find(section) if statement is not None else None
    return [dict(e.attrib) for e in (found if found is not None else statement).iter(element)] \
        if statement is not None else []


def record(response, existing=None):
    """The record from one Flex statement, in the account's base currency."""
    statement = response.find(".//FlexStatement") if response is not None else None
    if statement is None:
        raise broker.BrokerError("the report holds no statement: check the Flex query (docs/BROKERS.md)")
    info = next(iter(_rows(statement, "AccountInformation", "AccountInformation")), {})
    base = (info.get("currency") or "").upper()
    if not base:
        raise broker.BrokerError("the report does not say the account's base currency: add Account "
                                 "Information to the Flex query (docs/BROKERS.md)")
    rec = broker.Record("ibkr", base, env="live")
    trades = [t for t in _rows(statement, "Trades", "Trade") if t.get("assetCategory") in STOCKS]
    executions = [t for t in trades if (t.get("levelOfDetail") or "").upper() in DETAIL]
    for t in executions or [t for t in trades if (t.get("levelOfDetail") or "").upper() == "ORDER"]:
        rate = _rate(t, base)
        net = t.get("netCash")
        net = _num(net) if net not in (None, "") else _num(t.get("proceeds")) + _num(t.get("ibCommission"))
        fee = abs(_num(t.get("ibCommission")))
        fee_rate = 1.0 if (t.get("ibCommissionCurrency") or base) == base else rate
        side = "SELL" if (t.get("buySell") or "").upper().startswith("SELL") or _num(t.get("quantity")) < 0 else "BUY"
        rec.trade(t.get("tradeID") or t.get("transactionID") or t.get("ibExecID"), when(t), _code(t), side,
                  _num(t.get("quantity")), _num(t.get("tradePrice")), abs(net) * rate,
                  price_currency=t.get("currency"), name=t.get("description") or t.get("symbol"),
                  fees=[("COMMISSION", fee * fee_rate)] if fee else ())
    cash = [c for c in _rows(statement, "CashTransactions", "CashTransaction")
            if (c.get("levelOfDetail") or "").upper() in DETAIL]
    withheld = {}
    for c in cash:
        if _plain(c.get("type")) == "withholdingtax":
            key = (c.get("symbol"), when(c)[:10])
            withheld[key] = withheld.get(key, 0.0) + _num(c.get("amount")) * _rate(c, base)
    for c in cash:
        kind, rate = _plain(c.get("type")), _rate(c, base)
        amount, ref, at = _num(c.get("amount")) * rate, c.get("transactionID"), when(c)
        if kind in DEPOSITS:
            rec.cash(ref, at, "DEPOSIT" if amount > 0 else "WITHDRAW", amount)
        elif kind in DIVIDEND_TYPES:
            key = (c.get("symbol"), at[:10])
            net = amount + withheld.pop(key, 0.0)
            rec.dividend(ref, at, _code(c), net, gross=amount)
        elif kind in INTEREST_TYPES:
            rec.cash(ref, at, "INTEREST_ON_FREE_CASH", amount)
        elif kind == "withholdingtax":
            continue
        elif kind in FEE_TYPES and amount < 0:
            rec.cash(ref, at, "FEE", amount)
        elif amount:
            rec.cash(ref, at, "ADJUSTMENT", amount)
    for (symbol, day), amount in withheld.items():      # tax with no dividend beside it (a refund, a reclaim)
        rec.cash(f"withheld-{symbol}-{day}", day + "T12:00:00Z", "ADJUSTMENT", amount)
    for p in _rows(statement, "OpenPositions", "OpenPosition"):
        if p.get("assetCategory") not in STOCKS or (p.get("levelOfDetail") or "SUMMARY").upper() != "SUMMARY":
            continue
        rate = _rate(p, base)
        rec.position(_code(p), _num(p.get("position")), _num(p.get("markPrice")), _num(p.get("positionValue")) * rate,
                     price_currency=p.get("currency"), name=p.get("description") or p.get("symbol"))
    cash_now = next((_num(r.get("endingCash")) for r in _rows(statement, "CashReport", "CashReportCurrency")
                     if (r.get("currency") or "").upper() == "BASE_SUMMARY"), None)
    nav = _rows(statement, "EquitySummaryInBase", "EquitySummaryByReportDateInBase")
    last = max(nav, key=lambda r: "".join(ch for ch in str(r.get("reportDate") or "") if ch.isdigit()), default=None)
    if cash_now is None and last:
        cash_now = _num(last.get("cash"))
    if cash_now is None:
        raise broker.BrokerError("the report does not say the account's cash: add the Cash Report to the "
                                 "Flex query (docs/BROKERS.md)")
    total = _num(last.get("total")) if last and last.get("total") not in (None, "") else None
    return rec.finish(cash=cash_now, total=total, existing=existing)


def sync(existing=None, environ=None, opener=None, sleep=time.sleep):
    token, query = credentials(environ)
    return record(fetch(token, query, opener, sleep), existing)


def check(environ=None, opener=None, sleep=time.sleep):
    token, query = credentials(environ)
    statement = fetch(token, query, opener, sleep).find(".//FlexStatement")
    return "answered: the report was made" + ("" if statement is not None else ", but holds no statement")
