"""Plain-English read on a company, written from the desk's own numbers.

The model never sees a price feed or the internet: it gets the figures this desk
already computed, and writes them up. It is told to name no target price and give
no buy or sell advice — this desk states facts, the person decides.

Key stays server-side (.env), never reaches the page. Default model is the
cheapest current one; override with OPENAI_MODEL.

Usage: python3 summarise.py NVDA
"""
import json, os, sys, urllib.error, urllib.request
from datetime import datetime, timezone
from env_config import load_env, atomic_write_json
import screen
import uncertainty

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY_FILE = os.path.join(HERE, "summaries.json")
URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"
MAX_OUTPUT_TOKENS = 700
TIMEOUT = 90

SYSTEM = """You write one short briefing on a company for the user of a personal \
research dashboard. You are given figures the dashboard computed from the company's \
own SEC filings, from daily prices, and from its earnings record.

Rules:
- Use only the figures given, exactly as written (they are already rounded and \
formatted). Never invent, estimate or re-round a number, and never use outside \
knowledge of recent events.
- No recommendation: never say buy, sell, hold, undervalued, overvalued, or name a \
target price. You describe, the reader decides.
- Plain English, no jargon. If you use a financial term, explain it in the same sentence.
- Four short paragraphs at most, under 180 words total: what the business reported, \
what the share price has done, what is coming up, and what to watch in the numbers.
- Where the data says a figure is missing, say it is not reported rather than guessing.
- Two different dates appear: the financial figures cover a reporting period that ended on one date, and the share price is from another. Never use one date for the other.
- Dates are already written the way a person would say them; repeat them as given.
- Past reactions are the middle (median) of the company's own history, not \
predictions; say so if you quote one.
- A count comes with its range. Where it says it cannot be told from chance, or that \
there are too few to establish a rate, say that in the same sentence, and never \
describe it as a pattern or a tendency."""


class SummaryError(Exception):
    pass


def api_key():
    load_env(os.path.join(HERE, ".env"))
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SummaryError("Add OPENAI_API_KEY=… to .env (the summaries, the weekly briefs and the chat use it)")
    return key


def model_name():
    return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


def _day(iso):
    """2026-06-30 → 30 June 2026 (the model repeats what it is given)."""
    try:
        y, m, d = str(iso)[:10].split("-")
        return f"{int(d)} {MONTHS[int(m) - 1]} {y}"
    except (ValueError, IndexError, TypeError):
        return "not reported"


def _pct(v, sign=False):
    if v is None:
        return "not reported"
    return ("+" if sign and v > 0 else "") + f"{v * 100:.1f}%"


def _range(iv, show):
    if iv.get("low") is None:
        return "too few to put a range on"
    return f"a {iv['level']} range of {show(iv['low'])} to {show(iv['high'])}"


def _count(p, noun):
    """A count read as a rate, with its range and what chance could give — as the
    page says it (Phase 5)."""
    if not p:
        return "not reported"
    share = uncertainty.UNCERTAINTY_DISPLAY["share"]
    text = f"{p['k']} of {p['n']} {noun}, {_range(p, lambda v: screen.format_with(share, v))}"
    if p.get("expected") is not None:
        return text + ("; more lopsided than chance would give" if p["distinguishable"]
                       else "; this cannot be told from chance")
    return text + ("; too few to establish a rate" if p["reads"] == "uncertain" else "")


def _covers(card):
    """Which period the revenue and margins cover, from how fundamentals.py built them
    — four quarters, or the last annual report when quarters stopped (J-07). JPMorgan's
    figure is its annual report; calling it "the last 12 months" was false."""
    basis, asof = card.get("revenue_basis"), _day(card.get("revenue_asof"))
    return ("the 12 months to " if basis == "quarters" else
            "the financial year to " if basis == "annual" else "the period to ") + asof


def facts_for(card):
    """The figures the model may use — already written the way they should appear,
    so it repeats them rather than rounding or reformatting. The company's figures
    are formatted from the measures' own declarations (screen.MEASURE_DISPLAY), as the
    page formats them, and a blank one carries the page's reason."""
    price = card.get("price") or {}
    r = card.get("results_reaction") or {}

    def figure(name):
        if card.get(name) is not None:
            return screen.format_measure(name, card[name])
        why = (card.get("why") or {}).get(name)
        return f"not shown: {why}" if why else "not reported"

    facts = {
        "ticker": card.get("ticker"),
        "company": card.get("name"),
        "revenue": figure("revenue"),
        "revenue_and_margins_cover": _covers(card),
        "revenue_growth_vs_year_before": figure("revenue_growth"),
        "gross_margin": figure("gross_margin"),
        "operating_margin": figure("operating_margin"),
        "net_margin": figure("net_margin"),
        "debt_compared_with_equity": figure("debt_to_equity"),
        "cash": figure("cash"),
        "earnings_per_share": figure("eps"),
        "share_price": ("not reported" if price.get("close") is None else f"${price['close']:,.2f}"),
        "share_price_as_of": _day(price.get("as_of")),
        "price_change_over_1_year": _pct(price.get("year"), sign=True),
        "against_the_market_over_1_year": _pct(price.get("year_vs_market"), sign=True),
        "next_results_date": (_day((card.get("next_earnings") or {}).get("date"))
                              if (card.get("next_earnings") or {}).get("date") else "not announced"),
        "beat_expectations": _count(card.get("beats"), "reports beat the consensus estimate"),
    }
    window = str(r.get("window")) if r else None
    moved, ups = ((r.get("moves") or {}).get(window), (r.get("ups") or {}).get(window)) if r else (None, None)
    if moved and ups:
        facts["after_past_results_announcements"] = (
            f"over {r['n']} past announcements the median move against the market in the "
            f"following {r['window']} days was {_pct(moved['estimate'], sign=True)}, "
            f"{_range(moved, lambda v: _pct(v, sign=True))}; up after {ups['k']} of them; "
            + ("more consistent than chance would give" if ups["distinguishable"]
               else "this cannot be told from no reaction"))
    return facts


def ask(instructions, text, key=None, model=None, max_tokens=MAX_OUTPUT_TOKENS, opener=None, history=None):
    """One request to OpenAI: the instructions and the text, and the model's answer; with
    the model that wrote it. Every piece of writing on the desk goes through here. `history` is
    the conversation so far, [(role, text)] with the role "user" or "assistant" (the chat, chat.py)."""
    key, model = key or api_key(), model or model_name()
    earlier = [{"role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": said}]}
               for role, said in history or [] if role in ("user", "assistant") and said]
    body = json.dumps({
        "model": model,
        "instructions": instructions,
        "input": earlier + [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
        "max_output_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SummaryError("OpenAI rejected the key: check OPENAI_API_KEY in .env") from None
        if e.code == 429:
            raise SummaryError("OpenAI rate limit or quota reached; try again later") from None
        raise SummaryError(f"OpenAI returned HTTP {e.code}") from None
    except Exception as e:
        raise SummaryError(f"Can't reach OpenAI ({e})") from None
    text = extract_text(data)
    if not text:
        raise SummaryError("The model returned an empty summary; try again")
    return text, model


def write_summary(card, key=None, model=None, opener=None):
    text, model = ask(SYSTEM, "Figures for this company:\n" + json.dumps(facts_for(card), indent=1),
                      key=key, model=model, opener=opener)
    return {"text": text, "model": model,
            "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "as_of": card.get("revenue_asof"), "price": (card.get("price") or {}).get("as_of")}


def extract_text(data):
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    parts = []
    for item in data.get("output") or []:
        for chunk in item.get("content") or []:
            if chunk.get("type") in ("output_text", "text") and chunk.get("text"):
                parts.append(chunk["text"])
    return "\n".join(parts).strip()


def load(path=None):
    try:
        with open(path or SUMMARY_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(summaries, path=None):
    atomic_write_json(path or SUMMARY_FILE, summaries, indent=1)


def main(argv):
    tickers = [a.upper() for a in argv if not a.startswith("-")]
    if not tickers:
        print("Usage: python3 summarise.py NVDA", file=sys.stderr)
        return 2
    try:
        cards = {c["ticker"]: c for c in json.load(open(os.path.join(HERE, "desk_data.json")))["companies"]}
    except (OSError, ValueError, KeyError):
        print("Build the desk first: python3 build_desk.py", file=sys.stderr)
        return 2
    store = load()
    try:
        for t in tickers:
            if t not in cards:
                print(f"{t} is not on the watchlist", file=sys.stderr)
                continue
            store[t] = write_summary(cards[t])
            print(f"\n{t}:\n{store[t]['text']}\n")
        save(store)
        return 0
    except SummaryError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
