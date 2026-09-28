"""What changed between a company's last two annual reports, laid out the same way
every time (fourth review, Phase 7).

Four blocks, in the order an equity analysis reads them:

  revenue   the total change. A segment split is not attempted: the SEC's
            structured data this desk reads carries no dimensional breakdowns, and
            price, volume and mix are not tagged at all, so none is invented.
  margins   revenue to gross to operating to net, each margin's change in basis
            points, so the reader sees where the margin moved.
  cash      cash from operations against net income, with the gap named from the
            cash-flow statement's own lines: depreciation and share-based pay added
            back, and what is left, which is mostly working capital.
  debt      the long-term debt, when it falls due (the annual report's maturity
            table), and interest coverage — operating income over interest expense.

Everything is read from universe.py's store; the margins and growth are screen.py's
own measures, taken for each year by screen.history, so nothing here redefines them.
A figure the filings cannot reconcile (screen's unit-slip check) withholds only what
is built on it, and each figure this module adds is held inside a total it cannot
exceed, which catches a thousandfold slip upward (not one downward).

A bank, insurer or property company gets no bridge: its tagged revenue leaves out
interest, interest is its main cost rather than a burden on operating income, and
its operating cash flow is dominated by lending. None of the four blocks would mean
what it means elsewhere.

Stdlib only; computes, never recommends.
"""
import screen
import universe

SEGMENTS_NOTE = ("Segments: none shown. The SEC's structured data carries no segment "
                 "breakdowns, and price, volume and mix are not tagged at all.")
NOT_FOR_FINANCIALS = ("No bridge for a bank, insurer or property company: its tagged revenue "
                      "leaves out interest, interest is its main cost, and its operating cash "
                      "flow is dominated by lending, so none of the four blocks would mean what "
                      "it means elsewhere.")
MARGINS = ("gross_margin", "operating_margin", "net_margin")
ADD_BACKS = {"depreciation": "depreciation", "share_based_compensation": "share-based pay"}
WHEN = {"matures_1y": "within a year", "matures_2y": "in year two", "matures_3y": "in year three",
        "matures_4y": "in year four", "matures_5y": "in year five", "matures_later": "after five years"}

# How each quantity the bridge adds is shown; the ones it shares with the screener
# (revenue, net income, operating cash flow, debt, the margins) are screen.py's.
BRIDGE_DISPLAY = {
    "revenue_change":            {"kind": "money", "label": "Change in revenue"},
    "margin_change_bp":          {"kind": "ratio", "dp": 0, "signed": True, "label": "Change, basis points"},
    "depreciation":              {"kind": "money", "label": "Depreciation and amortisation"},
    "share_based_compensation":  {"kind": "money", "label": "Share-based pay"},
    "working_capital_and_other": {"kind": "money", "label": "Working capital and other items"},
    "cash_gap":                  {"kind": "money", "label": "Cash from operations less net income"},
    "cash_conversion":           {"kind": "ratio", "dp": 2, "label": "Cash conversion (operating cash ÷ net income)"},
    "interest_expense":          {"kind": "money", "label": "Interest expense"},
    "interest_coverage":         {"kind": "ratio", "dp": 1, "label": "Interest coverage (operating income ÷ interest)"},
    "maturing":                  {"kind": "money", "label": "Long-term debt falling due"},
}


class Reasons:
    """Why each blank in a block is blank, and which of them the desk withheld (a
    figure it holds but will not use) as against one never filed — the distinction
    the page colours (Phase 5)."""

    def __init__(self):
        self.why, self.held = {}, set()

    def blank(self, name, reason):
        self.why.setdefault(name, reason)

    def withhold(self, name, reason):
        self.why.setdefault(name, reason)
        self.held.add(name)

    def out(self):
        return {"why": self.why, "withheld": sorted(self.held)}


def _figure(row, name, index, within=None, notes=None):
    """One figure for one year, or None with the reason recorded: a unit slip
    screen.py found, or larger than the total it must sit inside."""
    value = screen.at(row, name, index)
    fault = screen.unreliable(row, [name], index)
    if fault:
        if notes:
            notes.withhold(name, "withheld: this company " + fault["note"])
        return None
    if value is not None and within is not None:
        total = screen.at(row, within, index)
        if total is not None and abs(value) > abs(total):
            if notes:
                notes.withhold(name, f"withheld: larger than its {within.replace('_', ' ')}, "
                                     f"which it cannot exceed — a unit slip")
            return None
    return value


def _depreciation(row, index, notes):
    """The cash-flow add-back for depreciation and amortisation: the combined line where
    it is tagged, else depreciation and amortisation of intangibles from the notes,
    together — never one alone, which would understate it and push the difference into
    working capital. What the notes leave out of the cash-flow line (AMD's "other"
    amortisation) stays in "working capital and other items"."""
    if screen.at(row, "depreciation", index) is not None:
        return _figure(row, "depreciation", index, within="assets", notes=notes)
    alone, amortisation = screen.at(row, "depreciation_alone", index), screen.at(row, "amortisation", index)
    if alone is None or amortisation is None:
        return None
    assets = screen.at(row, "assets", index)
    if assets is not None and abs(alone + amortisation) > abs(assets):
        notes.withhold("depreciation", "withheld: larger than its assets, which it cannot exceed — a unit slip")
        return None
    return alone + amortisation


def _ratio(top, bottom):
    return top / bottom if top is not None and bottom else None


def revenue_block(row, lines):
    now, before = lines["revenue"][-1], lines["revenue"][-2]
    return {"now": now, "before": before,
            "change": now - before if now is not None and before is not None else None,
            "growth": lines["revenue_growth"][-1],
            "segments": SEGMENTS_NOTE}


def margin_walk(lines):
    """Each margin now and a year before, and the move in basis points. A margin the
    filings do not support says so (S-30): Starbucks files no gross profit, and its
    row was three bare dashes."""
    steps = []
    for name in MARGINS:
        now, before = lines[name][-1], lines[name][-2]
        missing = (now is None) + (before is None)
        steps.append({"name": name, "now": now, "before": before,
                      "change_bp": (now - before) * 1e4 if not missing else None,
                      "why": (None if not missing else "not in its tagged filings" if missing == 2
                              else "not in its tagged filings for one of the two years")})
    return steps


def cash_block(row, index=0):
    """Operating cash flow against net income, the gap named from the cash-flow
    statement's own lines. Conversion is not stated for a loss: a ratio over a
    negative profit reads backwards."""
    notes = Reasons()
    income = _figure(row, "net_income", index, notes=notes)
    cash = _figure(row, "operating_cash_flow", index, notes=notes)
    depreciation, basis = _depreciation(row, index, notes), "tagged"
    if depreciation is not None and screen.at(row, "depreciation", index) is None:
        basis = "summed"
    stock_pay = _figure(row, "share_based_compensation", index, notes=notes)
    if stock_pay is not None:
        size = screen.size(row, index)                  # the one definition of the company's size
        if size and abs(stock_pay) > size:
            notes.withhold("share_based_compensation",
                           "withheld: larger than the company's assets and revenue — a unit slip")
            stock_pay = None
    for name, value in (("net_income", income), ("operating_cash_flow", cash),
                        ("depreciation", depreciation), ("share_based_compensation", stock_pay)):
        if value is None:
            notes.blank(name, "not in its tagged filings")
    gap = cash - income if cash is not None and income is not None else None
    named = [("depreciation", depreciation), ("share_based_compensation", stock_pay)]
    rest = (gap - sum(v for _, v in named if v is not None)
            if gap is not None and all(v is not None for _, v in named) else None)
    if gap is not None and rest is None:
        notes.blank("working_capital_and_other",
                    "not separable without " + " and ".join(ADD_BACKS[n] for n, v in named if v is None))
    before_income = _figure(row, "net_income", index + 1)
    before_cash = _figure(row, "operating_cash_flow", index + 1)
    if income is not None and income <= 0:
        notes.withhold("cash_conversion", "a loss: conversion over a negative profit reads backwards")
    return dict({"net_income": income, "operating_cash_flow": cash, "cash_gap": gap,
                 "lines": [{"name": n, "value": v} for n, v in named] +
                          [{"name": "working_capital_and_other", "value": rest}],
                 "depreciation_basis": basis if depreciation is not None else None,
                 "cash_conversion": _ratio(cash, income) if (income or 0) > 0 else None,
                 "cash_conversion_before": (_ratio(before_cash, before_income)
                                            if (before_income or 0) > 0 else None)}, **notes.out())


def debt_block(row, index=0):
    """The long-term debt, when it falls due, and interest coverage, each now and a
    year before."""
    notes = Reasons()
    schedule = [{"name": m, "when": WHEN[m], "amount": _figure(row, m, index, notes=notes)}
                for m in universe.MATURITIES]
    filed = [s["amount"] for s in schedule if s["amount"] is not None]
    total = sum(filed) if filed else None
    liabilities = screen.at(row, "liabilities", index)
    if total is not None and liabilities is not None and total > abs(liabilities):
        notes.withhold("maturing", "withheld: the schedule adds up to more than all its liabilities — a unit slip")
        schedule, total = [dict(s, amount=None) for s in schedule], None
    if not filed:
        notes.blank("maturing", "no maturity table in its tagged filings")
    for step in schedule if filed else ():
        if step["amount"] is None:                     # a year the table leaves out (S-23)
            notes.blank(step["name"], "not in its tagged filings")

    def coverage(i):
        operating = _figure(row, "operating_income", i)
        interest = _figure(row, "interest_expense", i, within="liabilities",
                           notes=notes if i == index else None)
        return (operating / interest if operating is not None and interest else None), interest

    now, interest = coverage(index)
    before, interest_before = coverage(index + 1)
    if interest is None:
        notes.blank("interest_expense", "no interest expense in its tagged filings")
        notes.blank("interest_coverage", "no interest expense in its tagged filings")
    debt = _figure(row, "debt", index, notes=notes)
    if debt is None:
        notes.blank("debt", "not in its tagged filings")
    return dict({"debt": debt, "debt_before": _figure(row, "debt", index + 1),
                 "maturities": schedule, "maturing": total,
                 "interest_expense": interest, "interest_expense_before": interest_before,
                 "interest_coverage": now, "interest_coverage_before": before}, **notes.out())


def for_company(row, financial=False):
    """The bridge for one company from its stored filings, or the reason there is none."""
    if financial:
        return {"why_not": NOT_FOR_FINANCIALS}
    lines = screen.history(row, ("revenue", "revenue_growth") + MARGINS)
    if len(lines["revenue"]) < 2:
        return {"why_not": "fewer than two annual reports stored"}
    return {"why_not": None,
            "revenue": revenue_block(row, lines),
            "margins": margin_walk(lines),
            "cash": cash_block(row),
            "debt": debt_block(row)}
