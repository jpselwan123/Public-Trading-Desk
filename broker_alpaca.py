"""The account from Alpaca's trading API, read only (BROKER=alpaca).

    ALPACA_API_KEY, ALPACA_API_SECRET   a key pair from Alpaca's dashboard (API keys)
    ALPACA_ENV                          live (the default) or paper

Three reads, never a write: the account (its cash and its value), the positions, and every
account activity, a hundred a page: each fill, dividend and the tax withheld from it, deposit,
withdrawal, fee and interest payment. An Alpaca account is in dollars. A fill's money is its
shares times its price: Alpaca charges no commission on a trade, and its regulatory fees come
as activities of their own, counted as fees. A split, a symbol change or shares moved in from
another broker bring no money; shares that arrive without a trade show in the checks.
"""
import json, os, time, urllib.error, urllib.parse, urllib.request

import broker
from env_config import load_env, read, unpacked

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTS = {"live": "https://api.alpaca.markets", "paper": "https://paper-api.alpaca.markets"}
PAGE = 100                     # the most activities Alpaca gives a page
TIMEOUT = 30
MAX_PAGES = 500                # 50,000 activities: an answer that never ends is not the account
# Activities that move money, by what they are to the desk.
CASH = {"CSD": "DEPOSIT", "CSW": "WITHDRAW", "JNLC": "TRANSFER", "ACATC": "TRANSFER",
        "FEE": "FEE", "CFEE": "FEE", "INT": "INTEREST_ON_FREE_CASH"}
DIVIDENDS = ("DIV", "DIVCGL", "DIVCGS", "DIVROC", "DIVTXEX")
WITHHELD = ("DIVNRA", "DIVFT", "DIVTW")
NO_MONEY = ("SSP", "SSO", "SC", "SPLIT", "REORG", "ACATS", "MA", "NC", "OPASN", "OPEXP", "OPXRC")


def credentials(environ=None):
    if environ is None:
        load_env(os.path.join(HERE, ".env"))
        environ = os.environ
    key = str(environ.get("ALPACA_API_KEY") or "").strip()
    secret = str(environ.get("ALPACA_API_SECRET") or "").strip()
    env = str(environ.get("ALPACA_ENV") or "live").strip().lower()
    if env not in HOSTS:
        raise broker.BrokerError("ALPACA_ENV must be live or paper")
    if not key or not secret:
        raise broker.BrokerError("No Alpaca key yet: add ALPACA_API_KEY and ALPACA_API_SECRET to .env")
    return key, secret, env


class Client:
    """GET only: the three reads above."""
    PATHS = ("/v2/account", "/v2/positions", "/v2/account/activities")

    def __init__(self, key, secret, env="live", opener=None, sleep=time.sleep):
        self.host, self.env = HOSTS[env], env
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                         "Accept": "application/json", "Accept-Encoding": "gzip",
                         "User-Agent": "trading-desk (personal, read only)"}
        self._open, self._sleep = opener, sleep

    def get(self, path, params=None):
        if path not in self.PATHS:
            raise broker.BrokerError(f"Refusing to read {path}: not a path this desk uses")
        url = self.host + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers=self._headers)
        try:
            body, r = read(req, self._open, TIMEOUT, self._sleep)
            return json.loads(unpacked(body, r) or b"null")
        except urllib.error.HTTPError as e:
            words = {401: "the key was refused", 403: "the key may not read this account",
                     429: "too many requests for now: try again in a minute"}.get(e.code, f"HTTP {e.code}")
            raise broker.BrokerError(f"Alpaca: {words}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise broker.BrokerError(f"Alpaca did not answer ({getattr(e, 'reason', e)})") from None


def activities(client, after=None):
    """Every account activity, newest first, page by page (Alpaca's page_token: the last id)."""
    out, token = [], None
    for _ in range(MAX_PAGES):
        params = {"direction": "desc", "page_size": PAGE}
        if token:
            params["page_token"] = token
        if after:
            params["after"] = after
        page = client.get("/v2/account/activities", params)
        if not isinstance(page, list):
            raise broker.BrokerError("Alpaca answered without the account's activities; nothing was changed")
        out.extend(page)
        if len(page) < PAGE:
            return out
        token = page[-1].get("id")
    raise broker.BrokerError("Alpaca's activities did not end; nothing was changed")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _when(item):
    stamp = str(item.get("transaction_time") or item.get("date") or "")
    return stamp if "T" in stamp else stamp[:10] + "T12:00:00Z"


def _code(item):
    symbol = item.get("symbol") or ""
    crypto = item.get("asset_class") == "crypto" or "/" in symbol
    return broker.line_code(symbol, "CRYPTO" if crypto else "US")


def record(account, positions, items, env="live", existing=None):
    """The record from Alpaca's three answers."""
    if not isinstance(account, dict) or not account.get("currency"):
        raise broker.BrokerError("Alpaca answered without the account in it; nothing was changed")
    if not isinstance(positions, list):
        raise broker.BrokerError("Alpaca answered without the positions; nothing was changed")
    rec = broker.Record("alpaca", account["currency"], env=env)
    withheld = {}
    for item in items:
        kind = item.get("activity_type")
        if kind in WITHHELD:
            key = (item.get("symbol"), str(item.get("date") or "")[:10])
            withheld[key] = withheld.get(key, 0.0) + abs(_num(item.get("net_amount")))
    for item in items:
        kind, ref, when = item.get("activity_type"), item.get("id"), _when(item)
        if kind == "FILL":
            qty, price = abs(_num(item.get("qty"))), _num(item.get("price"))
            side = "SELL" if str(item.get("side") or "").lower().startswith("sell") else "BUY"
            rec.trade(ref, when, _code(item), side, qty, price, qty * price, price_currency="USD",
                      name=item.get("symbol"))
        elif kind in DIVIDENDS:
            gross = _num(item.get("net_amount"))
            key = (item.get("symbol"), str(item.get("date") or "")[:10])
            net = gross - withheld.pop(key, 0.0)
            rec.dividend(ref, when, _code(item), net, gross=gross)
        elif kind in CASH:
            amount = _num(item.get("net_amount"))
            rec.cash(ref, when, CASH[kind], amount)
        elif kind in WITHHELD or kind in NO_MONEY:
            continue
        elif _num(item.get("net_amount")):
            rec.cash(ref, when, "ADJUSTMENT", _num(item.get("net_amount")))
    for (symbol, day), amount in withheld.items():             # tax with no dividend beside it
        rec.cash(f"withheld-{symbol}-{day}", day + "T12:00:00Z", "ADJUSTMENT", -amount)
    for p in positions:
        qty = _num(p.get("qty"))
        rec.position(_code(p), qty, _num(p.get("current_price")), _num(p.get("market_value")),
                     price_currency="USD", name=p.get("symbol"), average=_num(p.get("avg_entry_price")))
    return rec.finish(cash=_num(account.get("cash")),
                      total=_num(account.get("portfolio_value") or account.get("equity")), existing=existing)


def sync(existing=None, environ=None, opener=None, sleep=time.sleep):
    key, secret, env = credentials(environ)
    client = Client(key, secret, env, opener, sleep)
    if (existing or {}).get("env") != env:
        existing = {}                                   # live and paper are two accounts
    account, positions = client.get("/v2/account"), client.get("/v2/positions")
    # after the first sync, from a week before the last: what came since, merged with what is kept
    last = str((existing or {}).get("synced_at") or "")[:10]
    after = None
    if last:
        from datetime import date, timedelta
        after = (date.fromisoformat(last) - timedelta(days=7)).isoformat()
    return record(account, positions, activities(client, after), env, existing)


def check(environ=None, opener=None, sleep=time.sleep):
    key, secret, env = credentials(environ)
    account = Client(key, secret, env, opener, sleep).get("/v2/account") or {}
    return f"answered ({env}), account currency {account.get('currency', '?')}"
