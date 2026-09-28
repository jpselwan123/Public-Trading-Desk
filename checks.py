"""The desk's figures checked against the broker's own (Trading 212's, or another's: broker.py),
on the user's real records, at every build.

The desk derives much of what it shows from the account's records: each sale's result, each
year's value, the turnover, the costs. Each derivation rests on reading the records rightly (a
fill's net value is the money that moved, a split restates a holding's shares, a dividend's
amount is what arrived). Tests check the arithmetic on simulated accounts whose truth is known;
these check the reading on the real one, by rebuilding from the records what Trading 212 also
states itself, and setting the two side by side:

  shares      each holding's shares, rebuilt from every fill (a US line's splits counted),
              against the count Trading 212 holds
  cash        every deposit, withdrawal, fill, dividend, interest payment and fee, summed,
              against the cash Trading 212 holds
  total       the shares at Trading 212's prices and the rebuilt cash, against its total
              (history.check, the one the History tab is built on)
  closed      each sale's closed gain, summed, against the account's closed gain
  holdings    the holdings' values, summed, against the invested figure; cash and invested
              against the total
  prices      each US holding's latest close in the desk against Trading 212's price for it:
              a split missed or a ticker read as another company shows here first

Each check says whether it holds and, when it does not, what differs, as a share of the account,
never an amount. `detail` names the tickers for the page; `plain` only counts them, for doctor.py,
whose report never says what the account holds.
"""
from datetime import date

import broker
import prices as price_store

import history

SHARES_WITHIN = 1e-4          # shares: fractional fills are rounded in the record (the desk's choice)
PRICE_WITHIN = 0.10           # a close against Trading 212's price: more than a day's usual move (the desk's choice)
PRICE_RECENT_DAYS = 5         # a close older than this is not compared: a holiday, a stale price


def checks(raw, account, prices, today):
    """{"checks": [{name, label, ok, detail}], "failed": [names]} for each check that can be made;
    None without an account."""
    import build_desk
    raw, account = raw or {}, account or {}
    if not account.get("total") or not raw.get("summary"):
        return None
    source = broker.name_of(raw)
    if raw.get("derived"):
        # an export's holdings and totals are the desk's own, worked out from its history: set
        # beside themselves they would always agree, which says nothing
        return {"checks": [], "failed": [], "source": source,
                "none_because": "the export holds no holdings or totals of the broker's own to check against: "
                                "compare the desk's total with your broker's once after importing"}
    fills = history._fills(raw.get("orders"))
    moves, unknown = history._cash_moves(raw.get("transactions"), raw.get("dividends"), fills)
    out = []

    # shares
    positions = {}
    for p in raw.get("positions") or []:
        ticker = (p.get("instrument") or {}).get("ticker") or p.get("ticker")
        if ticker:
            positions[ticker] = positions.get(ticker, 0.0) + build_desk.num(p.get("quantity"))
    splits = price_store.SplitsRead(prices or {})
    rebuilt = history._held(fills, today.isoformat(), splits)
    off = sorted(history._short(t) for t in set(rebuilt) | set(positions)
                 if abs(rebuilt.get(t, 0.0) - positions.get(t, 0.0)) > SHARES_WITHIN)
    out.append({"name": "shares", "label": "Each holding's shares, rebuilt from every trade", "ok": not off,
                "detail": (f"all {len(positions)} match {source}'s" if not off else
                           "differ for " + ", ".join(off) +
                           ": a split the desk has no closes for, or a trade missing from the history"),
                "plain": (f"all {len(positions)} match" if not off else f"{len(off)} differ")})

    # cash, against the cash and the spending pot Trading 212 holds
    cash = account.get("cash", 0.0) + account.get("spending_pot", 0.0)
    rebuilt_cash = sum(a for _, a in moves)
    tolerance = history.CHECK_TOLERANCE * abs(account["total"])
    out.append({"name": "cash", "label": "Cash, rebuilt from every movement of money",
                "ok": abs(rebuilt_cash - cash) <= tolerance,
                "detail": _share("apart by", rebuilt_cash - cash, account["total"]) +
                          (f"; movements of a kind the desk does not know: {', '.join(unknown)}" if unknown else "")})

    # the total, the History tab's own check
    checked = history.check(fills, moves, unknown, raw.get("positions"), account, splits, today, source)
    if checked:
        out.append({"name": "total", "label": "The account's total, rebuilt",
                    "ok": checked["ok"], "detail": _share("apart by", checked["difference"],
                                                          account["total"])})

    # closed gains
    closed = sum(f[5] for f in fills if f[5] is not None)
    stated = account.get("realized")
    if stated is not None:
        out.append({"name": "closed", "label": "Closed gains, summed sale by sale",
                    "ok": abs(closed - stated) <= tolerance,
                    "detail": _share("apart by", closed - stated, account["total"])})

    # holdings add up, and the total is cash and holdings
    values = sum(build_desk.num((p.get("walletImpact") or {}).get("currentValue")) for p in raw.get("positions") or [])
    parts = account.get("cash", 0.0) + account.get("invested", 0.0) + account.get("spending_pot", 0.0)
    out.append({"name": "holdings", "label": "Holdings, cash and total add up",
                "ok": abs(values - account.get("invested", 0.0)) <= tolerance and abs(parts - account["total"]) <= tolerance,
                "detail": _share("the holdings and the invested figure apart by", values - account.get("invested", 0.0),
                                 account["total"])})

    # prices: the desk's latest close for each US holding against Trading 212's price
    compared, far = 0, []
    recent = today.toordinal() - PRICE_RECENT_DAYS
    for p in raw.get("positions") or []:
        ticker = (p.get("instrument") or {}).get("ticker") or p.get("ticker") or ""
        theirs = build_desk.num(p.get("currentPrice"))
        if not ticker.endswith("_US_EQ") or theirs <= 0:
            continue
        closes = price_store.series(prices, history._short(ticker), "c")
        if not closes:
            continue
        day = max(closes)
        if date.fromisoformat(day).toordinal() < recent:
            continue
        compared += 1
        if abs(closes[day] / theirs - 1) > PRICE_WITHIN:
            far.append(f"{history._short(ticker)} ({closes[day] / theirs - 1:+.0%})")
    if compared:
        out.append({"name": "prices", "label": f"The desk's prices against {source}'s", "ok": not far,
                    "detail": (f"all {compared} within {PRICE_WITHIN:.0%} of {source}'s" if not far else
                               "further apart than a usual day for " + ", ".join(far) +
                               ": a split the desk has not got, or the ticker read as another company"),
                    "plain": (f"all {compared} within {PRICE_WITHIN:.0%}" if not far else
                              f"{len(far)} further apart than {PRICE_WITHIN:.0%}")})
    for c in out:
        c.setdefault("plain", c["detail"])
    return {"checks": out, "failed": [c["name"] for c in out if not c["ok"]], "source": source}


def _share(words, difference, total):
    """A difference as a share of the account: never an amount, so it can be pasted."""
    return f"{words} {abs(difference) / abs(total):.2%} of the account" if total else words + " an unknown share"
