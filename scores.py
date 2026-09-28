"""Published scoring models, computed exactly as their authors defined them.

Each of these is a number a named paper says how to calculate and what it found
when it did. This file computes the number and reports the paper's own finding
alongside it. It does not convert either into advice, because the papers do not:
Piotroski's result is a spread between decile *portfolios* over twenty years of
firm-years, not a statement about any single company on any particular day.

That distinction is the whole point of showing the components. A score of 8 is
not a verdict — it is eight specific things being true, each of which you can
read, check against the filing, and disagree with.

Everything here is computed from filings alone. No prices, no forecasts.

Usage: python3 scores.py AAPL
"""
import os, sys

import screen
import universe

HERE = os.path.dirname(os.path.abspath(__file__))


# One definition of each of these, in screen.py, imported rather than rewritten —
# the standing rule after the same quantity was computed twice in two files and the
# copies drifted apart.
_at, _ratio = screen.at, screen.ratio


def _rose(now, before):
    """True when it went up, False when it did not, None when unknowable. A missing
    year is not a failed test — it is an absent one, and the score says so."""
    if now is None or before is None:
        return None
    return now > before


# ---- Piotroski F-score ---------------------------------------------------------------
PIOTROSKI = {
    "source": "Piotroski (2000), 'Value Investing: The Use of Historical Financial "
              "Statement Information to Separate Winners from Losers', Journal of "
              "Accounting Research 38",
    "found": "Among high book-to-market firms in 1976-1996, a portfolio of the "
             "highest-scoring companies outperformed the lowest-scoring by roughly "
             "23% a year before costs. The result is a spread between portfolios of "
             "many firms, not a claim about any one of them.",
    "caveats": "Measured on high book-to-market (value) firms only, before costs, "
               "and before the paper was published — the effect is smaller in later "
               "samples. Nine binary signals, so the score is coarse by design. "
               "The dilution signal here uses the weighted average diluted share "
               "count, which is a proxy: Piotroski's own test was whether common "
               "equity was issued in the year, and a buyback can mask an issue.",
    "range": (0, 9),
}


def _names(figures):
    words = [{"eps": "earnings per share", "shares": "share count"}.get(f, f.replace("_", " "))
             for f in figures]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def piotroski(row):
    """The nine signals, each named, each True, False or unknown.

    Signals are Piotroski's own, in his order: four on profitability, three on
    leverage and liquidity, two on operating efficiency."""
    # Six signals compare this year with last. When a figure in last year's filing
    # does not reconcile, a comparison built on it is between a real number and one
    # out by a thousand — so that signal is unknown, and the card says why. Only the
    # signals built on the figures named are affected: a misfiled share count says
    # nothing about the margin.
    unreliable = sorted({f for fault in screen.scale_faults(row, 1) for f in fault["figures"]})
    before = lambda figure: None if figure in unreliable else _at(row, figure, 1)
    roa = _ratio(_at(row, "net_income"), _at(row, "assets"))
    roa_before = _ratio(before("net_income"), before("assets"))
    cash_flow = _at(row, "operating_cash_flow")
    cfo_to_assets = _ratio(cash_flow, _at(row, "assets"))
    leverage = _ratio(_at(row, "debt"), _at(row, "assets"))
    leverage_before = _ratio(before("debt"), before("assets"))
    current = _ratio(_at(row, "current_assets"), _at(row, "current_liabilities"))
    current_before = _ratio(before("current_assets"), before("current_liabilities"))
    shares, shares_before = _at(row, "shares"), before("shares")
    margin = _ratio(_at(row, "gross_profit"), _at(row, "revenue"))
    margin_before = _ratio(before("gross_profit"), before("revenue"))
    turnover = _ratio(_at(row, "revenue"), _at(row, "assets"))
    turnover_before = _ratio(before("revenue"), before("assets"))

    signals = [
        ("profitable", "made a profit on its assets", None if roa is None else roa > 0),
        ("cash generating", "operating cash flow was positive",
         None if cash_flow is None else cash_flow > 0),
        ("improving returns", "return on assets rose", _rose(roa, roa_before)),
        ("earnings backed by cash", "cash flow exceeded reported profit",
         None if (cfo_to_assets is None or roa is None) else cfo_to_assets > roa),
        ("less indebted", "long-term debt fell as a share of assets",
         None if (leverage is None or leverage_before is None) else leverage < leverage_before),
        ("more liquid", "the current ratio rose", _rose(current, current_before)),
        ("no dilution", "no new shares were issued",
         None if (shares is None or shares_before is None) else shares <= shares_before),
        ("wider margin", "gross margin rose", _rose(margin, margin_before)),
        ("more efficient", "revenue per unit of assets rose", _rose(turnover, turnover_before)),
    ]
    scored = [s for s in signals if s[2] is not None]
    return {
        "score": sum(1 for s in scored if s[2]),
        "out_of": len(scored),
        "complete": len(scored) == len(signals),
        "unknown": [s[0] for s in signals if s[2] is None],
        "prior_year": None if not unreliable else (
            f"last year's {_names(unreliable)} "
            f"{'does' if len(unreliable) == 1 else 'do'} not reconcile with the rest of "
            f"that year's filing, so the signals comparing "
            f"{'it' if len(unreliable) == 1 else 'them'} with this year are unknown"),
        "signals": [{"name": n, "says": d, "passed": v} for n, d, v in signals],
    }


# ---- Altman Z''-score ----------------------------------------------------------------
ALTMAN = {
    "source": "Altman (1968), 'Financial Ratios, Discriminant Analysis and the "
              "Prediction of Corporate Bankruptcy', Journal of Finance 23; the Z'' "
              "revision for non-manufacturers in Altman (1993, 2000)",
    "found": "The original model classified 94% of bankrupt manufacturers correctly "
             "one year ahead. Z'' is the revision that drops asset turnover and uses "
             "book equity, so it applies to service and non-manufacturing firms and "
             "needs no market price.",
    "bands": "Above 2.6 is the 'safe' range, 1.1 to 2.6 the grey zone, below 1.1 the "
             "distress zone — Altman's own cut-offs for the Z'' model.",
    "caveats": "Built on US manufacturers of the 1960s and re-fitted since; it is a "
               "measure of balance-sheet distress, not of whether a company is a good "
               "investment. Financial firms are outside its intended scope.",
    "weights": "6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4",
}
ALTMAN_SAFE, ALTMAN_DISTRESS = 2.6, 1.1
MIN_PROFIT_YEARS = 3         # fewer years on record cannot establish a pattern


def deficit_is_payout_driven(row, deficit):
    """Whether a book deficit was built by paying shareholders rather than by losing
    money, measured from the cash-flow statement over the stored years (J-03b).

    Payout-driven when the company earned money over those years AND its dividends
    and buybacks alone are at least as large as the deficit: payouts could have
    produced it with no loss at all — Starbucks, Amgen, Apple. A company that lost
    money over the years, or paid out too little to explain the hole, built it the
    way Altman's model assumes.

    This does not depend on the window covering the company's whole history, which
    is what broke the profitability test: a company that lost heavily before the
    window and profits now passed that test and had its band wrongly withheld.

    Returns (True | False, facts) or (None, None) when either payout series is not in
    the filings as the SEC publishes them."""
    earned, paid, years = 0.0, 0.0, 0
    dividends, buybacks = row.get("dividends_paid") or [], row.get("buybacks") or []
    if not any(v is not None for v in dividends) or not any(v is not None for v in buybacks):
        return None, None
    for i, net in enumerate(row.get("net_income") or []):
        if net is None:
            continue
        years += 1
        earned += net
        paid += abs(_at(row, "dividends_paid", i) or 0.0) + abs(_at(row, "buybacks", i) or 0.0)
    if years < MIN_PROFIT_YEARS:
        return None, None
    facts = {"years": years, "earned": earned, "paid": paid, "deficit": abs(deficit)}
    return (earned > 0 and paid >= abs(deficit)), facts


def consistently_profitable(row, minimum=MIN_PROFIT_YEARS):
    """A profit in every stored year, over enough years to call it a record."""
    years = [v for v in (row.get("net_income") or []) if v is not None]
    return len(years) >= minimum and all(v > 0 for v in years)


def altman(row):
    """Altman's Z'' for non-manufacturers, which needs no market price."""
    assets = _at(row, "assets")
    if not assets:
        return None
    working_capital = None
    current_assets, current_liabilities = _at(row, "current_assets"), _at(row, "current_liabilities")
    if current_assets is not None and current_liabilities is not None:
        working_capital = current_assets - current_liabilities
    parts = {
        "X1 working capital / assets": _ratio(working_capital, assets),
        "X2 retained earnings / assets": _ratio(_at(row, "retained_earnings"), assets),
        "X3 operating income / assets": _ratio(_at(row, "operating_income"), assets),
        "X4 equity / liabilities": _ratio(_at(row, "equity"), screen.liabilities(row)),
    }
    if any(v is None for v in parts.values()):
        return {"score": None, "parts": parts,
                "missing": [k for k, v in parts.items() if v is None]}
    weights = (6.56, 3.26, 6.72, 1.05)
    score = sum(w * v for w, v in zip(weights, parts.values()))
    band = ("safe" if score > ALTMAN_SAFE else
            "distress" if score < ALTMAN_DISTRESS else "grey")

    # Two of the four inputs are equity and retained earnings, and a company that has
    # returned capital through buybacks and dividends reduces both mechanically — no
    # deterioration in the business required. Altman fitted the model where they went
    # negative through losses; it cannot tell the two apart. Amgen earned 7.7bn last
    # year and scores 0.14, "distress", because a decade of payouts left retained
    # earnings at -25bn. Starbucks scores -0.37 on the same mechanism through equity.
    #
    # So the question is what built the deficit, and the cash-flow statement answers
    # it directly (J-03b): payouts large enough to explain it, from a company that
    # earned money over the years on record. A deficit built by losses — BeOne, or a
    # company that listed with paid-in capital and lost money before turning a profit
    # (J-03a) — keeps its band, with X2 carrying the deficit as designed.
    equity, retained = _at(row, "equity"), _at(row, "retained_earnings")
    which, deficit = ((("book equity", equity) if (equity or 0) <= 0 else
                       ("retained earnings", retained) if (retained or 0) <= 0 else (None, None)))
    if which:
        payout, facts = deficit_is_payout_driven(row, deficit)
        if payout:
            money = lambda v: screen.format_measure("net_income", v)
            return {"score": score, "band": None, "raw_band": band, "applies": False,
                    "parts": parts, "missing": [], "test": "payouts",
                    "why_not": f"over the {facts['years']} years on record this company earned "
                               f"{money(facts['earned'])} and paid out {money(facts['paid'])} in "
                               f"dividends and buybacks — enough on its own to explain its "
                               f"{money(-facts['deficit'])} of {which} — so the deficit was built "
                               f"by paying shareholders, not by losing money. Two of the model's "
                               f"four inputs are those figures, and it was fitted where they went "
                               f"negative through losses. The score is shown, the band is not."}
        if payout is None and which == "book equity" and consistently_profitable(row):
            # the payouts are not in the filings as published, so the older test stands
            return {"score": score, "band": None, "raw_band": band, "applies": False,
                    "parts": parts, "missing": [], "test": "profitability",
                    "why_not": "this company made a profit in every year on record yet has "
                               "negative book equity, so it most likely got there by paying "
                               "out, not by losing money — its buybacks or dividends are not "
                               "in its filings as the SEC publishes them, so this is judged "
                               "from its profits alone. Two of the model's four inputs are "
                               "those figures, and it was fitted where they went negative "
                               "through losses. The score is shown, the band is not."}
    return {"score": score, "band": band, "applies": True, "parts": parts, "missing": []}


# ---- reporting -----------------------------------------------------------------------
def for_company(ticker, store=None):
    """Every score for one company, or why it cannot be scored."""
    companies = (store or universe.load()).get("companies") or {}
    row = companies.get(str(ticker).upper())
    if not row:
        return {"ticker": ticker, "error": "not in the stored universe — run universe.py"}
    fault = screen.scale_fault(row)
    if fault:
        return {"ticker": ticker, "name": row.get("name"),
                "error": "this company " + fault["note"]}
    return {"ticker": row["ticker"], "name": row.get("name"),
            "piotroski": piotroski(row), "altman": altman(row)}


def _tick(value):
    return "yes" if value is True else "no" if value is False else "not filed"


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[-1])
        return 1
    out = for_company(argv[0])
    if out.get("error"):
        print(f"{out['ticker']}: {out['error']}")
        return 1
    print(f"{out['ticker']} — {out['name']}\n")

    f = out["piotroski"]
    print(f"Piotroski F-score: {f['score']} of {f['out_of']}"
          + ("" if f["complete"] else f"  ({len(f['unknown'])} signals not filed)"))
    for s in f["signals"]:
        print(f"    {_tick(s['passed']):<9} {s['says']}")
    print(f"\n  {PIOTROSKI['source']}")
    print(f"  What it found: {PIOTROSKI['found']}")
    print(f"  Caveats: {PIOTROSKI['caveats']}\n")

    a = out["altman"]
    if a and a.get("score") is not None:
        zone = f" — {a['band']} zone" if a.get("band") else " — no band"
        print(f"Altman Z''-score: {a['score']:.2f}{zone}")
        for name, value in a["parts"].items():
            print(f"    {value:>8.3f}  {name}")
        if not a.get("applies", True):
            print(f"\n  Why no band: {a['why_not']}")
        print(f"\n  {ALTMAN['source']}")
        print(f"  Bands: {ALTMAN['bands']}")
        print(f"  Caveats: {ALTMAN['caveats']}")
    else:
        missing = ", ".join((a or {}).get("missing") or ["everything"])
        print(f"Altman Z''-score: cannot be computed — {missing} not filed")

    print("\nThese are what two published models say about this company's filings.\n"
          "Neither is a recommendation, and neither author claimed it was one.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
