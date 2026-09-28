"""The account from a CSV of its history, exported from any broker (BROKER=csv).

Almost every broker lets its customers download their transactions as a spreadsheet. Their
columns differ, so the desk reads one plain layout, with the usual names for each column
accepted (docs/BROKERS.md shows it, and how to arrange an export into it):

    date        2024-01-15, or 2024-01-15 14:30 (a date with slashes needs BROKER_CSV_DATES)
    type        buy, sell, deposit, withdrawal, dividend, interest, fee, tax
    symbol      the ticker (a trade, a dividend)
    market      where the line trades: US (the default), or LSE, XETRA, ...
    quantity    shares bought, sold, or paid a dividend on
    price       a share's price, in its own currency
    currency    that price's currency (the account's, if left out)
    amount      the money that moved, in the account's currency: what a purchase cost with its
                fees, what a sale or a dividend brought in, a deposit, a withdrawal, a fee
    fee         a trade's fees, in the account's currency (already in its amount)
    withheld    tax withheld from a dividend, in the account's currency (already out of its amount)
    id          the broker's reference for the row (optional)

    BROKER_CSV        the file, or a folder of them (every .csv in it, read together)
    BROKER_CURRENCY   the account's currency (USD if not given)
    BROKER_NAME       the broker's name, for the page (optional)
    BROKER_CSV_DATES  dmy or mdy, when dates are written with slashes

Nothing is guessed: a row the desk cannot read stops the import and names its line, because a
trade skipped quietly would be a wrong figure everywhere after it. The export holds no holdings
or totals, so the desk works them out from the trades (broker.complete) and its checks against
the broker cannot run: compare the total with the broker's own once after importing.
"""
import csv, glob, hashlib, io, os, re

import broker
from env_config import load_env

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(HERE, "account.csv")

# Each column the desk reads, and the names brokers' exports give it (compared lower-cased,
# without spaces, underscores or punctuation).
COLUMNS = {
    "date": ("date", "datetime", "time", "tradedate", "transactiondate", "rundate", "dateexecuted", "activitydate"),
    "type": ("type", "action", "activity", "activitytype", "transactiontype", "side"),
    "symbol": ("symbol", "ticker", "instrument", "security"),
    "market": ("market", "exchange", "listingexchange"),
    "quantity": ("quantity", "shares", "qty", "units", "noofshares"),
    "price": ("price", "priceshare", "pricepershare", "unitprice", "tradeprice", "sharepriceinfo"),
    "currency": ("currency", "pricecurrency", "currencypriceshare", "tradecurrency"),
    "amount": ("amount", "netamount", "total", "totalamount", "value", "netvalue", "amountusd"),
    "fee": ("fee", "fees", "commission", "commissions", "feesandcommissions"),
    "withheld": ("withheld", "withholding", "withholdingtax", "taxwithheld"),
    "id": ("id", "reference", "ref", "transactionid", "orderid", "tradeid"),
}
REQUIRED = ("date", "type", "amount")
# Each row's kind, from the words brokers use for it.
KINDS = {
    "buy": "BUY", "bought": "BUY", "purchase": "BUY", "marketbuy": "BUY", "limitbuy": "BUY", "youbought": "BUY",
    "sell": "SELL", "sold": "SELL", "sale": "SELL", "marketsell": "SELL", "limitsell": "SELL", "yousold": "SELL",
    "deposit": "DEPOSIT", "contribution": "DEPOSIT", "transferin": "DEPOSIT", "cashin": "DEPOSIT",
    "withdrawal": "WITHDRAW", "withdraw": "WITHDRAW", "transferout": "WITHDRAW", "cashout": "WITHDRAW",
    "dividend": "DIVIDEND", "dividends": "DIVIDEND", "dividendreceived": "DIVIDEND", "cashdividend": "DIVIDEND",
    "interest": "INTEREST", "interestoncash": "INTEREST", "creditinterest": "INTEREST",
    "fee": "FEE", "fees": "FEE", "charge": "FEE",
    "tax": "TAX", "withholding": "TAX", "withholdingtax": "TAX",
}
SLASH_DATE = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})")
ISO_DATE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})(?:[T ,;]+(\d{1,2}):?(\d{2})(?::?(\d{2}))?)?")


def _plain(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def settings(environ=None):
    if environ is None:
        load_env(os.path.join(HERE, ".env"))
        environ = os.environ
    path = str(environ.get("BROKER_CSV") or "").strip() or DEFAULT_FILE
    if not os.path.isabs(path):
        path = os.path.join(HERE, path)
    dates = str(environ.get("BROKER_CSV_DATES") or "").strip().lower() or None
    if dates not in (None, "dmy", "mdy"):
        raise broker.BrokerError("BROKER_CSV_DATES must be dmy or mdy")
    return {"path": path, "currency": str(environ.get("BROKER_CURRENCY") or "USD").strip().upper(),
            "name": str(environ.get("BROKER_NAME") or "").strip() or None, "dates": dates}


def files(path):
    if os.path.isdir(path):
        found = sorted(glob.glob(os.path.join(path, "*.csv")))
        if not found:
            raise broker.BrokerError(f"no .csv file in {os.path.basename(path)}/ (BROKER_CSV)")
        return found
    if not os.path.exists(path):
        raise broker.BrokerError(f"{os.path.basename(path)} is not there: export your history from your broker "
                                 "and save it there, or name it in BROKER_CSV (docs/BROKERS.md)")
    return [path]


def number(text, line, column, required=False):
    """A figure as brokers write it: 1,234.56, 1.234,56, (12.50), $1,234, -3."""
    raw = str(text or "").strip()
    if not raw or raw in ("-", "--", "n/a", "N/A"):
        if required:
            raise broker.BrokerError(f"line {line}: no {column}")
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9,.\-+]", "", raw.strip("()"))
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")    # 1.234,56
        else:
            cleaned = cleaned.replace(",", "")                       # 1,234.56
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "") if re.match(r"^[-+]?\d{1,3}(,\d{3})+$", cleaned) else cleaned.replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        raise broker.BrokerError(f"line {line}: {column} {raw!r} is not a number") from None
    return -abs(value) if negative else value


def moment(text, line, order):
    """An ISO time the desk reads, from the row's date: the exchange's own day kept as it is."""
    raw = str(text or "").strip()
    m = ISO_DATE.match(raw)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
    else:
        s = SLASH_DATE.match(raw)
        if not s:
            raise broker.BrokerError(f"line {line}: {raw!r} is not a date the desk reads (2024-01-15)")
        if not order:
            raise broker.BrokerError(f"line {line}: {raw!r} could be day/month or month/day: set "
                                     "BROKER_CSV_DATES=dmy or mdy in .env")
        a, b, y = s.groups()
        d, mo = (a, b) if order == "dmy" else (b, a)
        y = y if len(y) == 4 else "20" + y
        rest = ISO_DATE.match("2000-01-01 " + raw[s.end():].strip(" ,T")) if raw[s.end():].strip() else None
        hh, mm, ss = (rest.groups()[3:] if rest else (None, None, None))
    try:
        from datetime import datetime
        when = datetime(int(y), int(mo), int(d), int(hh or 12), int(mm or 0), int(ss or 0))
    except ValueError:
        raise broker.BrokerError(f"line {line}: {raw!r} is not a date") from None
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _header(rows):
    """The row that names the columns (an export may open with a title or the account's name),
    and each column's place in it."""
    for i, row in enumerate(rows[:30]):
        where = {}
        for j, cell in enumerate(row):
            for column, names in COLUMNS.items():
                if _plain(cell) in names and column not in where:
                    where[column] = j
        if all(c in where for c in REQUIRED):
            return i, where
    raise broker.BrokerError("no header row naming a date, a type and an amount in its first 30 lines "
                             "(docs/BROKERS.md shows the columns)")


def read(path, order):
    """[(key, row)] for every row of one file, each row a dict of the columns read."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        text = f.read()
    # the separator is the one that gives a header row: a title line above it misleads a guess
    found = None
    for delimiter in (",", ";", "\t"):
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        try:
            found = (rows,) + _header(rows)
            break
        except broker.BrokerError:
            continue
    if not found:
        raise broker.BrokerError(f"{os.path.basename(path)}: no header row naming a date, a type and an amount "
                                 "in its first 30 lines (docs/BROKERS.md shows the columns)")
    rows, start, where = found
    out = []
    for i, row in enumerate(rows[start + 1:], start=start + 2):
        if not any(cell.strip() for cell in row):
            continue
        cell = lambda c: row[where[c]].strip() if c in where and where[c] < len(row) else ""
        out.append({"line": f"{os.path.basename(path)}:{i}", **{c: cell(c) for c in COLUMNS}})
    return out


def _key(row):
    return "|".join(row[c] for c in ("date", "type", "symbol", "quantity", "price", "amount", "id"))


def sync(existing=None, environ=None):
    """The record from the export: every row read, or none."""
    config = settings(environ)
    counts, rows = {}, []
    for path in files(config["path"]):
        here = {}
        for row in read(path, config["dates"]):
            here.setdefault(_key(row), []).append(row)
        for key, same in here.items():                 # overlapping exports agree: a row once
            if len(same) > len(counts.get(key, [])):
                counts[key] = same
    for key, same in counts.items():
        for n, row in enumerate(same):
            rows.append((hashlib.sha1(f"{key}#{n}".encode()).hexdigest()[:16], row))
    record = broker.Record("csv", config["currency"], env="export", broker_name=config["name"])
    account = config["currency"]
    taxes = []
    for ref, row in rows:
        line = row["line"]
        kind = KINDS.get(_plain(row["type"]))
        if kind is None:
            raise broker.BrokerError(f"line {line}: {row['type']!r} is not a kind the desk reads "
                                     "(buy, sell, deposit, withdrawal, dividend, interest, fee, tax)")
        when = moment(row["date"], line, config["dates"])
        amount = number(row["amount"], line, "amount")
        ref = row["id"] or ref
        if kind in ("BUY", "SELL"):
            if not row["symbol"]:
                raise broker.BrokerError(f"line {line}: a {kind.lower()} with no symbol")
            qty = number(row["quantity"], line, "quantity", required=True)
            price = number(row["price"], line, "price")
            currency = (row["currency"] or account).upper()
            fee = abs(number(row["fee"], line, "fee") or 0.0)
            if amount is None:
                if currency != account or price is None:
                    raise broker.BrokerError(f"line {line}: no amount, and the price is not in the account's "
                                             "currency, so what the trade cost the account cannot be told")
                amount = abs(qty) * price + (fee if kind == "BUY" else -fee)
            if price is None:
                price = abs(amount) / abs(qty) if qty else 0.0
            code = broker.line_code(row["symbol"], row["market"] or "US")
            record.trade(ref, when, code, kind, qty, price, abs(amount), price_currency=currency,
                         fees=[("COMMISSION", fee)] if fee else ())
        elif kind == "DIVIDEND":
            if amount is None:
                raise broker.BrokerError(f"line {line}: a dividend with no amount")
            if not row["symbol"]:
                raise broker.BrokerError(f"line {line}: a dividend with no symbol")
            withheld = abs(number(row["withheld"], line, "withheld") or 0.0)
            qty = number(row["quantity"], line, "quantity")
            code = broker.line_code(row["symbol"], row["market"] or "US")
            record.dividend(ref, when, code, abs(amount), gross=abs(amount) + withheld)
        elif kind == "TAX":
            taxes.append((ref, when, row, amount))
        else:
            if amount is None:
                raise broker.BrokerError(f"line {line}: no amount")
            moves = {"DEPOSIT": ("DEPOSIT", abs(amount)), "WITHDRAW": ("WITHDRAW", -abs(amount)),
                     "FEE": ("FEE", -abs(amount)), "INTEREST": ("INTEREST_ON_FREE_CASH", amount)}
            record.cash(ref, when, *moves[kind])
    # a tax row on a dividend's day and line is that dividend's withholding; any other is money out
    for ref, when, row, amount in taxes:
        if amount is None:
            raise broker.BrokerError(f"line {row['line']}: a tax with no amount")
        code = broker.line_code(row["symbol"], row["market"] or "US") if row["symbol"] else None
        paid = next((d for d in record.out["dividends"] if code and d["ticker"] == code
                     and d["paidOn"][:10] == when[:10]), None)
        if paid:
            paid["amount"] -= abs(amount)
            paid.setdefault("grossAmount", paid["amount"] + abs(amount))
        else:
            record.cash(ref, when, "ADJUSTMENT", -abs(amount))
    return record.finish(derived=True)


def check(environ=None):
    config = settings(environ)
    rows = sum(len(read(p, config["dates"])) for p in files(config["path"]))
    return f"export read: {rows:,} rows"
