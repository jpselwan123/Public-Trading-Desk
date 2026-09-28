"""Narrow every US filer down to the ones that meet conditions you chose.

A screener is not a recommendation and this one is careful not to become one. It
answers exactly one question — *which companies meet these conditions* — and the
conditions are either yours or come from a published screen with its author's own
thresholds. Nothing here ranks companies by how good an investment they are, picks
a top ten, sets a price target or suggests when to buy. Those are judgements, and
this file has no basis for making them.

Why the presets are cited rather than invented: this project's standing rule is
that every threshold comes from published work. "P/E under 20" sounds reasonable
and is arbitrary; Graham's number was published in 1973 with a stated rationale,
which at least lets you disagree with something specific.

Two stages, deliberately. Every condition here is computed from filings, so a
screen costs no market data at all — prices are only fetched for the handful that
survive, which is what makes screening thousands of companies practical.

Usage:
    python3 screen.py --list
    python3 screen.py piotroski
    python3 screen.py --where "revenue_growth>0.10,net_margin>0.15,debt_to_equity<0.5"
"""
import math, os, statistics, sys
from decimal import ROUND_HALF_UP, Decimal

import sectors
import universe
from env_config import atomic_write_json

HERE = os.path.dirname(os.path.abspath(__file__))
SCREEN_FILE = os.path.join(HERE, "screen.json")
MAX_RESULTS = 200             # a screen returning more than this is not a screen


class ScreenError(Exception):
    pass


# ---- measures, each computed from filings alone --------------------------------------
def at(row, figure, index=0):
    """One year's value of a figure, newest first. Exported because scores.py needs
    the same accessor and a second copy is how two files drift apart."""
    series = row.get(figure) or []
    return series[index] if index < len(series) else None


def latest_float(row):
    """The most recent usable public float the company filed, and how many years old.

    Not simply the newest year: AMD has a float on record for every year but the
    last, and an older float still catches a thirteenfold share-count mismatch.

    Usable means it is not a unit slip (S-11). Novanta files its float a thousand
    times too large in every year — 3.5 trillion dollars for a company with 1.8bn of
    assets — so its own history is steady and cannot catch it; the company's size
    can, by the same unit logic as SCALE_FLOOR: a float more than a thousand times
    the company's assets and revenue, or under a thousandth of them, is not a float
    this company could have. Defined here, where every row is read; value.py's share-basis check and the
    screener's size column both use it."""
    def fits(i, value):
        whole = size(row, i)
        return not whole or SCALE_FLOOR <= abs(value) / whole <= 1 / SCALE_FLOOR

    # Size only, not the float's own history: a float moves with the share price and
    # with capital raised — QXO's went from 48m to 13.7bn — and slips can span several
    # years, so a median of other years can be the wrong one (Woodward's middle three
    # are in thousands). Not caught: a float a thousand times too small that still
    # sits just above a thousandth of the company's size.
    for years_old, value in enumerate(row.get("public_float") or []):
        if value and fits(years_old, value):
            return value, years_old
    return None, None


def ratio(top, bottom):
    """None rather than an exception or a zero when the division is not meaningful."""
    if top is None or bottom in (None, 0):
        return None
    return top / bottom


_at, _ratio = at, ratio          # the names used throughout this module


def _growth(row, figure, years):
    """Compound annual growth, oldest to newest. None unless both ends are positive:
    a growth rate measured from a negative base is arithmetic without meaning."""
    series = [v for v in (row.get(figure) or [])]
    if len(series) <= years:
        return None
    new, old = series[0], series[years]
    if new is None or old is None or old <= 0 or new <= 0:
        return None
    if unreliable(row, [figure], years):
        return None                      # that year's figure does not add up
    return (new / old) ** (1.0 / years) - 1


# Some filers tag a figure in thousands while tagging the rest of the same filing in
# units — Applied Industrial Technologies files FY2025 net income as 392,988 against
# revenue of 4.6bn. The SEC frames API passes that through as filed. Screening on it
# silently is worse than not screening at all: the ratios all still look plausible.
#
# A slip runs either way. Too small makes a company look worse; too large makes it
# look better — a net income a thousand times too big is a spectacular return on
# assets — and that is the direction a screen rewards (J-01). Being unusual is not the
# same as being wrong, though: York Water really holds about $1,000 of cash, QXO's
# equity really went from 9m to 9.7bn when it raised capital, and Synopsys really
# borrowed 10bn to buy Ansys. So every piece of evidence has to say which figure is
# wrong before any figure is accused, and a verdict is only "confirmed" when the gap
# is close to the unit itself (J-02):
#
#   1. an accounting identity — net income is EPS times shares; liabilities are
#      assets less equity. Agreement clears the figure. A gap of a thousand or a
#      million is a slip, and the figure's own history says which side slipped: the
#      one that moved away from its usual level. Dillard's net income disagrees with
#      EPS × shares a thousandfold, but matches its own years — its share count is
#      the slip, not its profit.
#   2. its own other years, for a figure no identity covers. A drop to a thousandth
#      is the slip. A rise of a thousandfold is only suspected for a flow — a first
#      drug approval can do it — and for a balance-sheet figure is left to step 3,
#      because raised capital shows up in the total too and a slip does not.
#   3. a component against its total, which catches both directions and needs no
#      history. Strict — gross profit ≤ revenue, debt ≤ liabilities, cash ≤ current
#      assets ≤ assets, equity ≤ assets — cannot be broken by a correct filing, so any
#      breach sets both aside unless history finds the slip. Usual — operating income
#      ≤ gross profit, net income ≤ revenue, liabilities ≤ assets, revenue ≤ assets,
#      cash from operations ≤ revenue — are broken by real companies (gains, a bank's
#      revenue tag, the negative equity of Lowe's and Starbucks: 699 companies for the
#      last one alone; a retailer's turnover; a REIT's cash flow against its narrow
#      revenue tag), so only a breach of a unit's size counts. A breach of that size
#      that has been there every year is still one (K-01): steadiness only shows the
#      slip, or the tag describing something else, has always been there. The one
#      exception is a pair an accounting identity ties: a shell with $800 of assets
#      and $740,000 of liabilities has the negative equity that balances it.
#   4. a figure under a thousandth of the company's size that nothing above can
#      confirm or clear is set aside as unconfirmed.
#
# What none of this can catch, stated so it is not mistaken for coverage: a figure
# misfiled in every year whose slipped value real filings also reach. Cash from
# operations a thousand times too large is caught only where it is at least a third of
# revenue, since below that the slipped figure sits under 333 times revenue, where a
# REIT's narrow revenue tag also puts it. Cash, debt, operating income and cash from
# operations a thousand times too small in every year look like York Water's cash.
#
# The multiples are units, not estimates: a slip is thousands or millions tagged as
# ones. CONFIRM_TOLERANCE is how far from exactly 1,000 a gap may be and still be
# stated as a slip; out to SUSPECT_TOLERANCE it could be a slip or a huge real move,
# and the page says it cannot tell which. Both are set aside — what changes is only
# whether the desk claims to know why.
SCALE_FLOOR = 1e-3
SCALED = ("revenue", "gross_profit", "operating_income", "net_income",
          "operating_cash_flow", "equity", "debt", "cash", "liabilities")
BALANCES = ("equity", "debt", "cash", "liabilities")        # bounded by a total
UNIT_SLIPS = {1e3: "a thousand", 1e6: "a million"}
CONFIRM_TOLERANCE = 1.5      # 667–1,500 for a thousand: a slip, stated as fact
SUSPECT_TOLERANCE = 3.0      # out to 333–3,000: a slip or a very large real move
AGREES = 2.0                 # the two sides of an identity within a factor of 2
STRICT = (("gross_profit", "revenue"), ("debt", "liabilities"), ("cash", "current_assets"),
          ("current_assets", "assets"), ("equity", "assets"))
USUAL = (("operating_income", "gross_profit"), ("net_income", "revenue"),
         ("liabilities", "assets"), ("revenue", "assets"), ("operating_cash_flow", "revenue"))
NEVER_CONFIRMED = {("net_income", "revenue")}       # gains and asset sales are real
IMPLIED_FROM = {"net_income": ("eps", "shares"), "liabilities": ("assets", "equity"),
                "equity": ("assets", "liabilities")}


def _inputs(figure):
    return " and ".join("earnings per share" if f == "eps" else "share count" if f == "shares"
                        else _label(f) for f in IMPLIED_FROM[figure])


def _implied(row, figure, index=0):
    """The same figure worked out from others in the same filing, where an accounting
    identity allows it. Net income attributable to shareholders is EPS times shares;
    the balance sheet balances."""
    if figure == "net_income":
        eps, shares = _at(row, "eps", index), _at(row, "shares", index)
        return eps * shares if eps is not None and shares else None
    assets, equity = _at(row, "assets", index), _at(row, "equity", index)
    if figure == "liabilities" and assets is not None and equity is not None:
        return assets - equity
    filed = _at(row, "liabilities", index)   # the filed figure: a derived one is circular
    if figure == "equity" and assets is not None and filed is not None:
        return assets - filed
    return None


def _slip(ratio):
    """(words, grade) when |ratio| is one of the unit slips — "confirmed" close to the
    unit, "suspected" further out — else None. The ratio is taken as a size, so a
    figure too large and one too small are both found by passing the right way up."""
    size = abs(ratio)
    for tolerance, grade in ((CONFIRM_TOLERANCE, "confirmed"), (SUSPECT_TOLERANCE, "suspected")):
        for unit, words in UNIT_SLIPS.items():
            if unit / tolerance < size < unit * tolerance:
                return words, grade
    return None


def _off(value, against):
    """How `value` stands against `against` as a unit slip: (words, grade, "larger" or
    "smaller"), or None."""
    if not value or not against:
        return None
    ratio = abs(value / against)
    found = _slip(ratio) if ratio > 1 else _slip(1 / ratio)
    return (found[0], found[1], "larger" if ratio > 1 else "smaller") if found else None


def _history(row, figure, index):
    """The median of the figure's other years, or None without any."""
    others = [abs(v) for i, v in enumerate(row.get(figure) or []) if i != index and v]
    return statistics.median(others) if others else None


def _steady(value, typical):
    """True when the figure moved from its usual level by less than any slip could."""
    return typical is not None and bool(value) and \
        1 / (min(UNIT_SLIPS) / SUSPECT_TOLERANCE) <= abs(value) / typical <= min(UNIT_SLIPS) / SUSPECT_TOLERANCE


def _label(figure):
    return figure.replace("_", " ")


def _a(figure):
    label = _label(figure)
    return ("an " if label[0] in "aeiou" else "a ") + label


def _fault(figures, index, grade, note):
    figures = [figures] if isinstance(figures, str) else list(figures)
    return {"figure": figures[0], "figures": figures, "year": index,
            "confirmed": grade == "confirmed", "grade": grade, "note": note}


def _stated(figure, words, direction, basis):
    return (f"files its {_label(figure)} {words} times {direction} than {basis} — tagged "
            f"in the wrong unit — so every ratio built on it would be wrong")


def _suspected(figure, words, direction, basis):
    return (f"files its {_label(figure)} about {words} times {direction} than {basis} — "
            f"either a unit slip or a very large real move; its filings cannot tell which, "
            f"so every ratio built on it is set aside")


def _one_figure(row, figure, index, reference, rises=False):
    """Steps 1, 2 and 4 for one figure. A flow's rise is only looked at when rises is
    set, after step 3 has had the chance to find the same slip with better evidence."""
    value = _at(row, figure, index)
    if not value:
        return None
    typical = _history(row, figure, index)
    implied = _implied(row, figure, index)
    if implied:
        if 1 / AGREES < abs(implied / value) < AGREES:
            return None                                  # its own identity agrees
        gap = _off(value, implied)
        if gap:
            return _identity_side(row, figure, index, reference, value, implied, typical, gap)
    if typical:
        own = _off(value, typical)
        if own:
            words, grade, direction = own
            if direction == "smaller":
                note = (_stated if grade == "confirmed" else _suspected)(
                    figure, words, direction, "in its other years")
                return _fault(figure, index, grade, note)
            if rises and figure not in BALANCES:         # a rise: real growth can do it
                return _fault(figure, index, "suspected",
                              _suspected(figure, words, direction, "in its other years"))
            return None                                  # step 3, or the rises pass, decides
        if _steady(value, typical):
            return None
    if abs(value) / reference < SCALE_FLOOR:
        return _fault(figure, index, "unconfirmed",
                      f"files a figure for {_label(figure)} under a thousandth of its size, "
                      f"and nothing else in its filings can confirm it, so a ratio built on "
                      f"it could be out by a factor of a thousand")
    return None


def _implied_history(row, figure, index):
    years = len(row.get(figure) or [])
    others = [abs(v) for i in range(years) if i != index
              for v in [_implied(row, figure, i)] if v]
    return statistics.median(others) if others else None


def _out_of_size(value, reference, direction):
    """A figure that cannot be this company's: under a thousandth of its size when
    too small, bigger than the whole company when too large."""
    return abs(value) / reference < SCALE_FLOOR if direction == "smaller" else abs(value) > reference


def _identity_side(row, figure, index, reference, value, implied, typical, gap):
    """An identity disagrees by a unit. Which side slipped: the one that left its own
    history; failing that — a company that files in the wrong unit every year keeps a
    steady wrong history — the one that cannot be this company's size. AIT's net
    income of 392,988 on 4.6bn of sales is the odd side; Dillard's EPS × shares is."""
    words, grade, direction = gap
    back = "smaller" if direction == "larger" else "larger"
    moved = _off(value, typical) if typical else None
    implied_typical = _implied_history(row, figure, index)
    inputs_moved = _off(implied, implied_typical) if implied_typical else None
    value_side = bool(moved) and moved[2] == direction
    inputs_side = bool(inputs_moved) and inputs_moved[2] == back
    if value_side == inputs_side:                        # history cannot tell
        value_side = _out_of_size(value, reference, direction)
        inputs_side = _out_of_size(implied, reference, back)
    if value_side and not inputs_side:
        note = (_stated if grade == "confirmed" else _suspected)(
            figure, words, direction, "its other figures imply")
        return _fault(figure, index, grade, note)
    if inputs_side and not value_side:
        return _fault(IMPLIED_FROM[figure], index, "unconfirmed",
                      f"files {_a(figure)} that its {_inputs(figure)} put {words} "
                      f"times {back}, and it is the {_inputs(figure)} that cannot be right "
                      f"for a company this size — one of them is misfiled, and the filing "
                      f"cannot say which; every ratio built on them is set aside")
    return _fault((figure,) + IMPLIED_FROM[figure], index, "unconfirmed",
                  f"files {_a(figure)} {words} times {direction} than its "
                  f"{_inputs(figure)} imply, and nothing in its filings says which side "
                  f"slipped, so every ratio built on any of them is set aside")


def _figure(row, name, index):
    return liabilities(row, index) if name == "liabilities" else _at(row, name, index)


def _component_breach(row, part, total, index, strict):
    """Step 3 for one component-and-total pair."""
    a, b = _figure(row, part, index), _figure(row, total, index)
    if a is None or b is None or b <= 0 or a <= b:
        return None
    gap = _slip(a / b)
    if not gap:
        if not strict:
            return None                                  # real companies do this
        return _fault((part, total), index, "unconfirmed",
                      f"files {_a(part)} larger than its {_label(total)}, which a "
                      f"correct filing cannot do — one of the two tags describes something "
                      f"else — so every ratio built on either is set aside")
    words = gap[0]
    part_off = _off(a, _history(row, part, index))
    total_off = _off(b, _history(row, total, index))
    part_slipped = bool(part_off) and part_off[2] == "larger"
    total_slipped = bool(total_off) and total_off[2] == "smaller"
    if part_slipped != total_slipped:                    # exactly one left its own history
        # How far that figure moved from its own years is the size of the slip; the
        # breach only says there is one — a component and its total differ in size.
        figure, (words, grade, direction) = (part, part_off) if part_slipped else (total, total_off)
        if (part, total) in NEVER_CONFIRMED and grade == "confirmed":
            grade = "suspected"
        note = (_stated if grade == "confirmed" else _suspected)(
            figure, words, direction, "in its other years, and more than its "
            + _label(total) if part_slipped else "in its other years, and less than its " + _label(part))
        return _fault(figure, index, grade, note)
    if not strict and _balances(row, part, total, index):
        return None               # the balance sheet balances: negative equity, not a slip
    if not strict and not part_off and not total_off:
        return _fault((part, total), index, "unconfirmed",
                      f"files {_a(part)} about {words} times its {_label(total)}, and has in "
                      f"every year it filed — a unit slip that has always been there, or a tag "
                      f"that describes something else; its filings cannot tell which, so every "
                      f"ratio built on either is set aside")
    return _fault((part, total), index, "unconfirmed",
                  f"files {_a(part)} {words} times its {_label(total)}, which cannot be "
                  f"— one of the two is misfiled and its filings cannot tell which — so "
                  f"every ratio built on either is set aside")


def _balances(row, part, total, index):
    """Whether an accounting identity ties the pair and holds: filed liabilities
    within a factor of AGREES of assets less equity. Only then is a unit-sized breach
    the company's own figures rather than a slip (K-01)."""
    if (part, total) != ("liabilities", "assets") or _at(row, "liabilities", index) is None:
        return False                                     # a derived figure would prove itself
    implied, filed = _implied(row, "liabilities", index), _at(row, "liabilities", index)
    return bool(implied and filed) and 1 / AGREES < abs(implied / filed) < AGREES


def _as_of(row, years_back):
    """The row as it stood `years_back` filed years ago: every series shifted so that
    year is the newest."""
    return {k: (v[years_back:] if isinstance(v, list) else v) for k, v in row.items()}


def history(row, names, without=()):
    """Each named measure in every stored year, oldest first — measures() applied to
    the filings as they stood that year, so a sparkline and the definition behind it
    are one. A figure that year's filings cannot reconcile (a unit slip) is removed
    before the measures are taken, so the measures built on it are gaps and the rest
    of that year still draws — not a thousandfold spike. Figures named in `without`
    are removed from every year, for a company whose filings of them mean something
    else (a bank's revenue tag)."""
    depth = max((len(v) for v in row.values() if isinstance(v, list)), default=0)
    lines = {name: [] for name in names}
    for back in reversed(range(depth)):
        year = _as_of(row, back)
        for figure in without:
            year.pop(figure, None)
        for fault in scale_faults(year):
            for figure in fault["figures"]:
                if year.get(figure):
                    year[figure] = [None] + list(year[figure][1:])
        taken = measures(year)
        for name in names:
            lines[name].append(taken.get(name))
    return lines


SIZE_FROM = ("assets", "revenue")


def size(row, index=0, leave_out=()):
    """The company's size that year, which a figure too small or too large to be this
    company's is judged against: the larger of its assets and its revenue, leaving out
    either one already found slipped (K-02) — an inflated revenue would otherwise let
    a too-large figure pass as smaller than the whole company. That year's own values,
    not a median of years: SPACs, first sales and crypto treasuries really do grow a
    thousandfold in a year, and a median would judge them by a size they no longer
    have. Measured on the stored universe: a median of years cleared 7 companies, set
    aside 2, re-named the figure for 16 and moved 18 float checks; falling back to the history only when a year left it by a unit still
    refused five real SPAC floats. None when nothing is left to measure by."""
    sizes = [abs(_at(row, figure, index) or 0.0) for figure in SIZE_FROM if figure not in leave_out]
    return max(sizes, default=0.0) or None


def scale_faults(row, index=0):
    """Every fault found in one year's figures, in the order scale_fault checks them.
    An older year's faults blank only the measures built on the figures they name —
    a share count misfiled three years ago says nothing about revenue growth. When a
    fault names assets or revenue alone, the checks are run again with the company's
    size taken without it (K-02)."""
    reference = size(row, index)
    if not reference:
        return []
    found = _faults(row, index, reference)
    slipped = {f["figure"] for f in found if len(f["figures"]) == 1} & set(SIZE_FROM)
    without = size(row, index, slipped) if slipped else None
    return _faults(row, index, without) if without and without != reference else found


def _faults(row, index, reference):
    """Each fault once, the first check to find it speaking for it: a figure named by
    its own history and again by a total it breaks is one slip, not two (S-18)."""
    found = [_one_figure(row, f, index, reference) for f in SCALED]
    found += [_component_breach(row, part, total, index, strict)
              for pairs, strict in ((STRICT, True), (USUAL, False)) for part, total in pairs]
    found += [_one_figure(row, f, index, reference, rises=True) for f in SCALED]
    once, named = [], set()
    for fault in found:
        if fault and tuple(fault["figures"]) not in named:
            once.append(fault)
            named.add(tuple(fault["figures"]))
    return once


def unreliable(row, figures, index):
    """The fault that makes any of these figures unreliable in that year, or None."""
    return next((f for f in scale_faults(row, index) if set(f["figures"]) & set(figures)), None)


def scale_fault(row, index=0):
    """None when every figure for one year can be reconciled with the company's own
    filings. Otherwise {"figure", "figures", "year", "confirmed", "grade", "note"} for
    the first that cannot. grade is "confirmed" (the slip is stated as fact),
    "suspected" (a slip or a huge real move) or "unconfirmed" (something is wrong and
    the filings cannot say what); confirmed is True only for the first. Reported
    rather than repaired: the right value is not recoverable from this data, only
    its unreliability is.

    Year 0 decides whether a company can be screened at all. An older year is checked
    only by the measures that read it — a growth rate, Piotroski's year-on-year
    signals — which then say they are unknown rather than refuse the company."""
    faults = scale_faults(row, index)
    return faults[0] if faults else None


def liabilities(row, index=0):
    """Total liabilities, filed or derived.

    Many companies never tag Liabilities, filing only assets and equity — AMD and
    Nike both do. Assets = liabilities + equity is an accounting identity, so the
    remainder is exact rather than an estimate, and without it Altman's Z'' could be
    computed for barely half the universe."""
    filed = at(row, "liabilities", index)
    if filed is not None:
        return filed
    assets, equity = at(row, "assets", index), at(row, "equity", index)
    if assets is None or equity is None:
        return None
    return assets - equity


def _debt_to_working_capital(row):
    current, owed = _at(row, "current_assets"), _at(row, "current_liabilities")
    if current is None or owed is None or current - owed <= 0:
        return None
    return _ratio(_at(row, "debt"), current - owed)


def measures(row):
    """Every figure a condition may be written against, computed once per company.

    A measure is None when the filings do not support it. None never passes a
    condition — a missing number is not evidence, and silently treating it as zero
    is how screens end up full of companies that simply did not report."""
    revenue, assets = _at(row, "revenue"), _at(row, "assets")
    equity, net_income = _at(row, "equity"), _at(row, "net_income")
    cash_flow, capex = _at(row, "operating_cash_flow"), _at(row, "capex")
    free_cash_flow = None if cash_flow is None else cash_flow - (capex or 0.0)
    return {
        "revenue": revenue,
        "net_income": net_income,
        "assets": assets,
        "equity": equity,
        "cash": _at(row, "cash"),
        # what the company itself said its public shares were worth — the one size
        # figure every filer has without a price, which a screen cannot spend on
        # thousands of companies (Phase 4)
        "public_float": latest_float(row)[0],
        "debt": _at(row, "debt"),
        "eps": _at(row, "eps"),
        "shares": _at(row, "shares"),
        "operating_cash_flow": cash_flow,
        "free_cash_flow": free_cash_flow,
        "gross_margin": _ratio(_at(row, "gross_profit"), revenue),
        "operating_margin": _ratio(_at(row, "operating_income"), revenue),
        "net_margin": _ratio(net_income, revenue),
        "return_on_assets": _ratio(net_income, assets),
        # Equity at or below zero makes both of these meaningless rather than extreme:
        # AutoZone has bought back so much stock that equity is -3.2bn, which turned
        # debt/equity into -2.67 and let 8.6bn of debt pass a "below 1" condition.
        # Negative equity is its own measure so it can be screened for deliberately.
        "return_on_equity": _ratio(net_income, equity) if (equity or 0) > 0 else None,
        "gross_profitability": _ratio(_at(row, "gross_profit"), assets),
        "debt_to_equity": _ratio(_at(row, "debt"), equity) if (equity or 0) > 0 else None,
        "negative_equity": None if equity is None else float(equity <= 0),
        "debt_to_assets": _ratio(_at(row, "debt"), assets),
        "current_ratio": _ratio(_at(row, "current_assets"), _at(row, "current_liabilities")),
        # long-term debt over working capital: Graham's test for an industrial company is that the
        # first should not exceed the second. With no working capital it fails, so it has no value.
        "debt_to_working_capital": _debt_to_working_capital(row),
        "cash_to_debt": _ratio(_at(row, "cash"), _at(row, "debt")),
        # Earnings minus the cash from operations, over assets: Sloan (1996), the
        # definition Piotroski's accrual signal uses. It was built on free cash flow,
        # which takes capital spending out as well and is not his measure (J-05).
        "accruals": (None if cash_flow is None or net_income is None
                     else _ratio(net_income - cash_flow, assets)),
        "dividend_cover": _ratio(free_cash_flow, abs(_at(row, "dividends_paid") or 0.0) or None),
        "revenue_growth": _growth(row, "revenue", 1),
        "revenue_growth_3y": _growth(row, "revenue", 3),
        "revenue_growth_4y": _growth(row, "revenue", 4),
        "earnings_growth": _growth(row, "net_income", 1),
        "shares_change": _growth(row, "shares", 1),
        "asset_growth": _growth(row, "assets", 1),
    }


# How each measure is shown, declared once, here, by the module that owns the measures.
# The page and the command line both format from this and decide nothing themselves:
# return on assets read 5.8% on a company card and 0.0018 on the screener when each
# chose its own format (J-04). Kinds:
#   percent    a fraction shown ×100 with %    ratio      a plain ratio
#   money      dollars, scaled to m/bn/tn      count      a number, scaled the same
#   per_share  dollars and cents               flag       yes / no
# "signed" puts + on a positive value, for changes; "dp" is decimal places.
MEASURE_DISPLAY = {
    "revenue":             {"kind": "money",     "label": "Revenue"},
    "net_income":          {"kind": "money",     "label": "Net income"},
    "assets":              {"kind": "money",     "label": "Total assets"},
    "equity":              {"kind": "money",     "label": "Shareholders' equity"},
    "cash":                {"kind": "money",     "label": "Cash"},
    "public_float":        {"kind": "money",     "label": "Public float (as filed)"},
    "debt":                {"kind": "money",     "label": "Long-term debt"},
    "eps":                 {"kind": "per_share", "label": "Earnings per share"},
    "shares":              {"kind": "count",     "label": "Diluted shares"},
    "operating_cash_flow": {"kind": "money",     "label": "Operating cash flow"},
    "free_cash_flow":      {"kind": "money",     "label": "Free cash flow"},
    "gross_margin":        {"kind": "percent",   "label": "Gross margin", "dp": 1},
    "operating_margin":    {"kind": "percent",   "label": "Operating margin", "dp": 1},
    "net_margin":          {"kind": "percent",   "label": "Net margin", "dp": 1},
    "return_on_assets":    {"kind": "percent",   "label": "Return on assets", "dp": 1},
    "return_on_equity":    {"kind": "percent",   "label": "Return on equity", "dp": 1},
    # Novy-Marx states gross profits-to-assets as a ratio (his cut is 0.33), so it
    # stays one here and reads the way the paper does.
    "gross_profitability": {"kind": "ratio",     "label": "Gross profitability", "dp": 2},
    "debt_to_equity":      {"kind": "ratio",     "label": "Debt to equity", "dp": 2},
    "negative_equity":     {"kind": "flag",      "label": "Negative equity"},
    "debt_to_assets":      {"kind": "percent",   "label": "Debt to assets", "dp": 1},
    "current_ratio":       {"kind": "ratio",     "label": "Current ratio", "dp": 2},
    "debt_to_working_capital": {"kind": "ratio", "label": "Long-term debt to working capital", "dp": 2},
    "cash_to_debt":        {"kind": "ratio",     "label": "Cash to debt", "dp": 2},
    "accruals":            {"kind": "ratio",     "label": "Accruals", "dp": 3},
    "dividend_cover":      {"kind": "ratio",     "label": "Dividend cover", "dp": 2},
    "revenue_growth":      {"kind": "percent",   "label": "Revenue growth", "dp": 1, "signed": True},
    "revenue_growth_3y":   {"kind": "percent",   "label": "Revenue growth a year, over 3 years", "dp": 1, "signed": True},
    "revenue_growth_4y":   {"kind": "percent",   "label": "Revenue growth a year, over 4 years", "dp": 1, "signed": True},
    "earnings_growth":     {"kind": "percent",   "label": "Earnings growth", "dp": 1, "signed": True},
    "shares_change":       {"kind": "percent",   "label": "Share count change", "dp": 1, "signed": True},
    "asset_growth":        {"kind": "percent",   "label": "Asset growth", "dp": 1, "signed": True},
}
MINUS = "\u2212"


def _fixed(x, places):
    """x to a fixed number of places, a tie rounding up — what JavaScript's toFixed
    does, so the page and the command line cannot print different digits."""
    return str(Decimal(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _scaled(x):
    if x >= 1e12:
        return _fixed(x / 1e12, 2) + "tn"
    if x >= 1e9:
        return _fixed(x / 1e9, 1) + "bn"
    if x >= 1e6:
        return _fixed(x / 1e6, 0) + "m"
    return f"{int(Decimal(_fixed(x, 0))):,}"


def format_with(spec, value):
    """One value, shown the way its declaration says. formatWith in the page is the
    same function, and a test runs both on the same inputs."""
    if value is None or not math.isfinite(value):
        return "–"
    if not spec:
        return str(value)
    kind, size, negative = spec["kind"], abs(value), value < 0
    if kind == "flag":
        return "yes" if value else "no"
    if kind in ("percent", "ratio"):
        x = size * 100 if kind == "percent" else size
        text = _fixed(x, spec.get("dp", 1 if kind == "percent" else 2))
        if x > 0 and float(text) == 0:
            # two significant figures: a return on assets of 0.0004 shown as 0.0% reads
            # as failing a "greater than zero" condition it passes
            text = _fixed(x, min(6, 1 - math.floor(math.log10(x))))
        sign = MINUS if negative and float(text) != 0 else ("+" if spec.get("signed") and value > 0 else "")
        return sign + text + ("%" if kind == "percent" else "")
    if kind in ("money", "count"):
        return (MINUS if negative else "") + ("$" if kind == "money" else "") + _scaled(size)
    if kind == "per_share":
        return (MINUS if negative else "") + "$" + _fixed(size, 2)
    return str(value)


def format_measure(name, value):
    return format_with(MEASURE_DISPLAY.get(name), value)


# ---- conditions ----------------------------------------------------------------------
OPERATORS = (">=", "<=", ">", "<", "==")


def condition(text):
    """'net_margin>0.15' → a callable. The measure name must exist, so a typo is an
    error rather than a condition that quietly passes everything."""
    for op in OPERATORS:
        if op in text:
            name, _, value = text.partition(op)
            name, value = name.strip(), value.strip()
            if name not in measures({}):
                raise ScreenError(f"there is no measure called '{name}'")
            try:
                threshold = float(value)
            except ValueError:
                raise ScreenError(f"'{value}' is not a number") from None
            return {"measure": name, "op": op, "value": threshold}
    raise ScreenError(f"'{text}' is not a condition: use one of {', '.join(OPERATORS)}")


def holds(rule, values):
    got = values.get(rule["measure"])
    if got is None:
        return False                     # missing is never passing
    op, want = rule["op"], rule["value"]
    if op == ">":
        return got > want
    if op == "<":
        return got < want
    if op == ">=":
        return got >= want
    if op == "<=":
        return got <= want
    return got == want


# ---- published screens ---------------------------------------------------------------
# Each carries its source and the author's own thresholds. Where a criterion cannot be
# computed from the figures collected here, it is listed under `omits` rather than
# quietly dropped — a screen missing a third of its conditions is not that screen.
# Graham's $100 million of annual sales (1973 revision, figures of 1972) in today's dollars: the
# US consumer price index's 1972 average, 41.8, against 2025's, 317.7 (BLS CPI-U; 2025's without
# October, which BLS did not publish).
GRAHAM_SALES = 100e6 * 317.7 / 41.8
PRESETS = {
    "piotroski": {
        # Named for what it applies (J-05): it was titled "Piotroski F-score components"
        # and applied four loose conditions, two of them not his — free cash flow where
        # he uses cash from operations, in both the cash signal and the accrual one.
        "name": "Four of Piotroski's nine signals",
        "source": "Piotroski (2000), 'Value Investing: The Use of Historical Financial "
                  "Statement Information to Separate Winners from Losers'",
        "about": "The four signals that read one year's filing: a profit on assets (ROA), "
                 "cash from operations (CFO), earnings backed by that cash (ACCRUAL), and "
                 "no rise in the share count — the nearest the filings come to his "
                 "EQ_OFFER, since an equity issue is not tagged. This is not the F-score.",
        "where": ["return_on_assets>0", "operating_cash_flow>0", "accruals<0",
                  "shares_change<=0"],
        "omits": ["the five signals that compare with last year's filing — return on "
                  "assets rose, leverage fell, the current ratio rose, gross margin rose, "
                  "asset turnover rose. A condition here reads one year's figures; each "
                  "company's card scores all nine"],
    },
    "graham": {
        # Graham's own numbers for an industrial company (28 Sep 2026: the screen had
        # debt-to-equity under 1, which is not his rule, and $500m of sales, which is not his
        # $100m in any year's dollars). A book's rules, not a tested finding: said so below.
        "name": "Graham's defensive criteria (financial strength only)",
        "source": "Graham, 'The Intelligent Investor' (1973 revision), chapter 14: a book's rules for "
                  "a defensive investor, not a finding tested on returns",
        "about": "The balance-sheet half of Graham's test for an industrial company: sales of at "
                 f"least $100 million in 1972's dollars (${GRAHAM_SALES / 1e6:,.0f} million today, by the US "
                 "consumer price index), "
                 "current assets at least twice current liabilities, long-term debt no more than "
                 "working capital, and a profit in the latest year.",
        "where": [f"revenue>={GRAHAM_SALES:.0f}", "current_ratio>=2", "debt_to_working_capital<=1",
                  "net_income>0"],
        "omits": ["a profit in each of the last ten years, twenty years of dividends and a third's "
                  "growth in earnings per share over ten years, which need more years than a screen "
                  "reads; and the price limits (under 15 times earnings, 1.5 times book), which need a "
                  "market price"],
    },
    "profitable": {
        # 28 Sep 2026: this was "gross profitability over 0.33 with three years of revenue growth".
        # The growth condition is not Novy-Marx's, and a fixed cut drifts from the breakpoint
        # it stood for; the cut is now the NYSE's own top third on the day (top_third below).
        "name": "Gross profitability, the NYSE's top third",
        "source": "Novy-Marx (2013), 'The Other Side of Value: The Gross Profitability "
                  "Premium'; a measure that held in Hou, Xue & Zhang's (2020) re-test",
        "about": "Novy-Marx found gross profits over assets predicts returns as well as "
                 "book-to-market. The cut is the top third of NYSE-listed companies on the measure "
                 "today, the breakpoints the papers use.",
        "top_third": "gross_profitability",
        "where": [],
        "omits": [],
    },
    "dividend_cover": {
        "name": "Dividends covered by free cash flow",
        "source": "Standard coverage analysis; the 1.0 line is arithmetic, not a "
                  "judgement — below it the dividend is not funded by the business",
        "about": "Companies paying a dividend that free cash flow actually covers.",
        "where": ["dividend_cover>1", "free_cash_flow>0"],
        "omits": ["dividend yield, which needs a market price"],
    },
}


# ---- running a screen ----------------------------------------------------------------
# A bank's, insurer's or property company's tagged revenue leaves out interest income
# (ASC 606 covers revenue from contracts with customers), so a margin or a growth rate
# built on it does not mean what it means elsewhere: 74 of the 110 companies a "net
# margin above 100%" screen found were in that division, UDR's reading 2,200%. The
# card compares them on return on assets alone and builds them no bridge; the screener
# does not judge them on these measures either (S-19). Which companies they are is the
# SEC's own division for the industry code each files under (sectors.py).
ON_REVENUE = ("revenue", "gross_margin", "operating_margin", "net_margin",
              "revenue_growth", "revenue_growth_3y", "revenue_growth_4y")
NOT_FOR_FINANCIALS = ("the revenue they tag leaves out interest income, so a condition "
                      "built on it does not mean what it means elsewhere")


def run(where, store=None, limit=MAX_RESULTS, codes=None):
    """Every company meeting every condition, with the measures that decided it.
    `codes` is each company's industry code by CIK (sectors.load): with it, a bank,
    insurer or property company is not judged on a measure built on revenue. Without
    it the divisions are unknown, and the result says so."""
    rules = [condition(w) if isinstance(w, str) else w for w in where]
    if not rules:
        raise ScreenError("a screen with no conditions is just a list of every company")
    companies = (store or universe.load()).get("companies") or {}
    if not companies:
        raise ScreenError("no fundamentals stored yet — run: python3 universe.py")
    hits, unusable = [], {}
    # How many companies could be judged on each condition at all. Without this the
    # result reads as "everyone else was tested and failed", which is false: the SEC's
    # frames API omits a concept a company reports only inside a dimensional
    # breakdown, so barely a third of filers have a long-term debt figure. A
    # condition on debt is answered for those and silent about the rest.
    evaluated = {r["measure"]: 0 for r in rules}
    on_revenue = any(r["measure"] in ON_REVENUE for r in rules)
    financial, not_judged = {cik for cik, sic in (codes or {}).items()
                             if sectors.division(sic) == sectors.FINANCIAL}, 0
    for ticker, row in companies.items():
        fault = scale_fault(row)
        if fault:
            unusable[ticker] = fault["grade"]
            continue
        values = measures(row)
        if row.get("cik") in financial:
            values.update(dict.fromkeys(ON_REVENUE))
            not_judged += on_revenue
        for rule in rules:
            if values.get(rule["measure"]) is not None:
                evaluated[rule["measure"]] += 1
        if all(holds(rule, values) for rule in rules):
            hits.append({"ticker": ticker, "name": universe.display_name(row.get("name")),
                         "cik": row.get("cik"),
                         "measures": {r["measure"]: values[r["measure"]] for r in rules},
                         "public_float": values["public_float"]})
    # By the first condition the user set, highest first: the answer to the question
    # asked, not an opinion. Alphabetical was a choice too, and the least useful one.
    first = rules[0]["measure"]
    hits.sort(key=lambda h: (-h["measures"][first], h["ticker"]))
    usable = len(companies) - len(unusable)
    return {"where": [f"{r['measure']}{r['op']}{r['value']:g}" for r in rules],
            "rules": [{"measure": r["measure"], "op": r["op"], "value": r["value"]} for r in rules],
            "tested": len(companies), "usable": usable,
            "excluded": len(unusable), "matched": len(hits),
            "misfiled": sum(1 for g in unusable.values() if g == "confirmed"),
            "suspected": sum(1 for g in unusable.values() if g == "suspected"),
            "unconfirmed": sum(1 for g in unusable.values() if g == "unconfirmed"),
            "evaluated": evaluated,
            "narrowest": min(evaluated.values()) if evaluated else 0,
            # banks, insurers and property companies left unjudged on a condition built
            # on revenue; None when the divisions were not known
            "financial_not_judged": not_judged if codes else None,
            "financial_note": NOT_FOR_FINANCIALS,
            "sorted_by": first,
            "results": hits if limit is None else hits[:limit],
            "truncated": 0 if limit is None else max(0, len(hits) - limit)}


def top_third(measure, store=None, codes=None, listings=None):
    """The value the top third of NYSE-listed companies (banks, insurers and property companies
    aside, as the papers do) reach on a measure: its 2/3 quantile. Without the exchange list,
    every filer's. (value, the group it was set on)."""
    companies = (store or universe.load()).get("companies") or {}
    exchanges = {str(k).upper(): str(v or "").upper()
                 for k, v in ((listings if listings is not None else universe.load_listings()).get("exchanges") or {}).items()}
    financial = {cik for cik, sic in (codes or {}).items() if sectors.division(sic) == sectors.FINANCIAL}
    known = lambda rows: sorted(v for v in (measures(r).get(measure) for t, r in rows
                                            if r.get("cik") not in financial and not scale_fault(r)) if v is not None)
    values, group = known((t, r) for t, r in companies.items() if exchanges.get(t) == "NYSE"), "NYSE"
    if len(values) < sectors.MIN_PEERS:
        values, group = known(companies.items()), "every filer"
    if not values:
        raise ScreenError(f"no company has a {measure} figure to set a breakpoint on")
    return values[min(len(values) - 1, int(len(values) * 2 / 3))], group


def preset(name, store=None, limit=MAX_RESULTS, codes=None, listings=None):
    if name not in PRESETS:
        raise ScreenError(f"no screen called '{name}': try {', '.join(sorted(PRESETS))}")
    spec = dict(PRESETS[name])
    if spec.get("top_third"):
        cut, group = top_third(spec["top_third"], store, codes, listings)
        spec["where"] = [f"{spec['top_third']}>={cut:.6g}"] + list(spec["where"])
        spec["about"] += f" Today that is {cut:.3g}, set on {group} companies."
    out = run(spec["where"], store, limit, codes)
    out.update({"preset": name, "name": spec["name"], "source": spec["source"],
                "about": spec["about"], "omits": spec["omits"]})
    return out


def main(argv):
    if "--list" in argv or not argv:
        print("Published screens (each applies its author's own thresholds):\n")
        for key, spec in sorted(PRESETS.items()):
            print(f"  {key:<20} {spec['name']}")
            print(f"  {'':<20} {spec['source']}")
            print(f"  {'':<20} conditions: {', '.join(spec['where'])}")
            if spec["omits"]:
                print(f"  {'':<20} omits: {spec['omits'][0]}")
            print()
        print("Or write your own:  python3 screen.py --where \"net_margin>0.2,current_ratio>2\"")
        print("Measures available:  " + ", ".join(sorted(measures({}))))
        return 0
    try:
        if "--where" in argv:
            out = run([w for w in argv[argv.index("--where") + 1].split(",") if w.strip()], codes=sectors.load())
        else:
            out = preset(argv[0], codes=sectors.load())
    except ScreenError as e:
        print(f"screen: {e}")
        return 1
    if "--price" in argv:
        # Only the survivors are priced, which is the point of screening on filings
        # first: a free Tiingo key is a few hundred symbols a month.
        import value
        try:
            out["valuation"] = value.for_tickers([h["ticker"] for h in out["results"]])
        except Exception as e:                # noqa: BLE001 — the screen still stands
            out["valuation_error"] = str(e)
    out["measure_display"] = MEASURE_DISPLAY
    atomic_write_json(SCREEN_FILE, out)
    if out.get("name"):
        print(f"{out['name']}\n{out['source']}\n")
        if out.get("omits"):
            print(f"Not applied: {'; '.join(out['omits'])}\n")
    print(f"{out['matched']:,} companies meet: {', '.join(out['where'])}\n")
    print(f"{'condition':<26} {'companies that report it':>26}")
    for rule, reported in sorted(out["evaluated"].items(), key=lambda kv: kv[1]):
        share = reported / out["usable"] if out["usable"] else 0
        print(f"{rule:<26} {reported:>14,} of {out['usable']:,} ({share:.0%})")
    print(f"\nThe narrowest condition could be judged for {out['narrowest']:,} companies. "
          f"The rest are\nnot failures — the figure is simply not in their filings as the "
          f"SEC publishes them.")
    if out.get("financial_not_judged"):
        print(f"Of those, {out['financial_not_judged']:,} are banks, insurers and property companies, "
              f"not judged because {out['financial_note']}.")
    if out.get("excluded"):
        print(f"{out['excluded']:,} more were set aside: {out['misfiled']:,} file a figure in "
              f"the wrong unit, which their own filings show;\n{out['suspected']:,} file one "
              f"about a thousand or a million times off — a slip or a huge real move; and "
              f"\n{out['unconfirmed']:,} file figures that do not add up, or one too small to check.")
    print()
    columns = list(out["results"][0]["measures"]) if out["results"] else []
    print(f"{'ticker':<8} {'company':<34} " + " ".join(f"{c[:13]:>14}" for c in columns))
    for hit in out["results"][:40]:
        name = (hit["name"] or "")[:33]
        print(f"{hit['ticker']:<8} {name:<34} "
              + " ".join(f"{format_measure(c, hit['measures'][c]):>14}" for c in columns))
    if out.get("valuation_error"):
        print(f"\nNo prices: {out['valuation_error']}")
    elif out.get("valuation"):
        import value
        print(f"\n{'ticker':<8} {'price':>9} {'mkt cap':>10} {'P/E':>7} {'P/B':>7} "
              f"{'yield':>7}   Graham P/E 15 / P/B 1.5")
        for hit in out["results"][:40]:
            v = out["valuation"].get(hit["ticker"]) or {}
            if v.get("error"):
                print(f"{hit['ticker']:<8} {v['error']}")
                continue
            g = v["graham"]
            marks = {True: "within", False: "above", None: "–"}
            print(f"{hit['ticker']:<8} {value.format_value('price', v['price']):>9} "
                  f"{value.format_value('market_cap', v['market_cap']):>10} "
                  f"{value.format_value('price_to_earnings', v['price_to_earnings']):>7} "
                  f"{value.format_value('price_to_book', v['price_to_book']):>7} "
                  f"{value.format_value('dividend_yield', v['dividend_yield']):>7}   "
                  f"{marks[g['price_to_earnings']['passes']]:<7} "
                  f"{marks[g['price_to_book']['passes']]}")
    if out["truncated"]:
        print(f"\n… and {out['truncated']:,} more (raise --limit to see them)")
    print("\nThis is a list of companies meeting conditions, not advice and not a "
          "recommendation.\nWhat to do about any of them is your judgement.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
