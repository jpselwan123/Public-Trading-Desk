"""Ask: a few questions about what is on the screen, answered by the owner's OpenAI model from the
figures the desk holds (the owner, 5 Oct 2026: "a chat where I can ask any questions ... that way it
can help me analyse different things and what to look at").

The model never sees the internet or a price feed. It is given, with each question, the facts the
page itself shows for the companies in play: the company card's figures (summarise.facts_for), the
desk's own rating, the week's headlines (brief.facts_for), and what the chart on show shows
(charts.summary). The owner's holdings and followed list go only when the owner ticks "include my
holdings", and then as shares and percentages, never amounts. Like every piece of writing here it
names no target and never says buy or sell: its rules say so, and an answer that gives advice
anyway is asked for again once, then replaced by a plain refusal. Nothing it says is ever acted on:
no order, no follow, no write to any store but its own conversation, chat.json.

The conversation is kept in chat.json (personal, never committed, the last MAX_TURNS turns) with
when each question was asked, so that the day's cap holds; the key stays in .env.
"""
import json, os, re
from datetime import date, datetime, timedelta, timezone
from env_config import atomic_write_json, read_for_writing

import brief, charts, summarise

CHAT_FILE = "chat.json"               # {"turns": [{"role", "text", "at", ...}], "asked": [when each question was asked]}
MAX_TURNS = 60                        # kept; the last HISTORY_SENT go to the model with each question
HISTORY_SENT = 6
MAX_QUESTION = 600
PER_DAY = 100                         # the desk's choice: a cap on what a stray loop or a long evening can cost
MAX_OUTPUT_TOKENS = 450
MAX_TICKERS = 3
NEWS_DAYS = 5                         # sessions of headlines per company, newest

SYSTEM = """You answer questions for the owner of a personal research dashboard, in a chat beside \
the page they are looking at. You are given facts the dashboard holds: figures from companies' SEC \
filings, prices, the week's headlines, what the chart on show shows, the dashboard's own rating of \
a company, and, only if the owner allowed it, their holdings as shares and percentages (never \
amounts).

Rules:
- Short and plain: under 110 words, at most three short paragraphs or bullets, no jargon (if you \
must use a term, explain it in the same sentence). The reader is deciding where to look next.
- Every number about a company, a price or the owner's holdings comes only from the facts given, \
exactly as written. If a fact is not given, say the dashboard does not have it. Never estimate, and \
never use outside knowledge of recent events, prices or news.
- You may explain what a measure means, what a chart shows, and what is worth checking next on the \
dashboard, naming the place: the card's Key figures, Past results, the News fold, the Filings page, \
the chart's volume, the rating's record.
- No recommendation: never say buy, sell, hold, avoid, undervalued or overvalued, never say the \
owner should or should not do something, and name no target price. If asked what to do, say you \
do not advise, and say what to look at instead. The dashboard's own rating (Buy, Hold, Sell) is \
the dashboard's, made from published measures: you may repeat it as given and say whose it is.
- Never say that a news story or event moved a share price. You may put a move and a headline side \
by side.
- A chart shows what happened, not what will. If asked to predict, say so.
- Plain text only: no tables, no headings."""

REFUSAL = ("I can describe what the dashboard shows and what is worth checking next, but I don't "
           "advise on what to do. Ask me what to look at instead.")
RETRY = ("Your last answer advised the owner or recommended an action. Write it again as a plain "
         "description of what the facts show and what to check next, with no recommendation.")

# What an answer must not do. Phrases, not words: the dashboard's own rating says "Buy" and "Sell"
# as a label, and an answer may repeat it.
ADVICE = re.compile(
    r"\byou\s+(should|shouldn'?t|ought|must|need to|had better)\b|\b(i|we)\s+(would\s+)?(recommend|suggest|advise|urge)\b"
    r"|\b(i|we)\s+would\s+(buy|sell|hold|avoid)\b|\b(price|analyst)\s+target\b|\btarget\s+price\b"
    r"|\b(under|over)valued\b|\b(good|great|bad|poor)\s+(buy|investment)\b|\bworth\s+(buying|selling)\b"
    r"|\b(buy|sell|hold|avoid)\s+(it|this|now|more|the dip|shares|the stock)\b|\bdon'?t\s+(buy|sell)\b", re.I)


class ChatError(Exception):
    pass


def advice_in(text):
    return bool(ADVICE.search(text or ""))


# ---- the conversation -------------------------------------------------------------------------
def _path(folder):
    return os.path.join(folder, CHAT_FILE)


def load(folder):
    """The kept conversation, or ChatError when the file is there but cannot be read (it is not written over)."""
    try:
        kept = read_for_writing(_path(folder), dict, {})
    except Exception as e:
        raise ChatError(str(e)) from None
    turns = [t for t in kept.get("turns") or [] if isinstance(t, dict) and t.get("role") in ("user", "assistant")
             and isinstance(t.get("text"), str)]
    asked = [a for a in kept.get("asked") or [] if isinstance(a, str)]
    return {"turns": turns, "asked": asked}


def turns(folder):
    """The turns as the page shows them."""
    return [{k: t.get(k) for k in ("role", "text", "at", "ticker", "model")} for t in load(folder)["turns"]][-MAX_TURNS:]


def clear(folder):
    kept = load(folder)
    atomic_write_json(_path(folder), {"turns": [], "asked": kept["asked"]}, indent=1)     # today's count stays


def today_count(asked, now):
    day = now.date().isoformat()
    return sum(1 for a in asked if a[:10] == day)


def left_today(folder, now=None):
    return max(0, PER_DAY - today_count(load(folder)["asked"], now or datetime.now(timezone.utc)))


# ---- what the model is given ------------------------------------------------------------------
def known_tickers(data):
    rows = (data.get("positions") or {}).get("rows") or []
    return ({c.get("ticker") for c in data.get("companies") or []} | {r.get("ticker") for r in rows} | {"SPY"}) - {None}


def mentioned(message, data):
    """The tickers the question names that the dashboard knows, as typed in capitals or after a $."""
    known = known_tickers(data)
    found = []
    for word in re.findall(r"\$([A-Za-z][A-Za-z.\-]{0,6})\b|\b([A-Z][A-Z.\-]{0,6})\b", message or ""):
        t = (word[0] or word[1]).upper()
        if t in known and t not in found:
            found.append(t)
    return found


def _today(data):
    try:
        return date.fromisoformat(data.get("today") or "")
    except ValueError:
        return datetime.now(timezone.utc).date()


def company_facts(data, ticker):
    """What the dashboard holds about one company, or None when it is not covered."""
    card = next((c for c in data.get("companies") or [] if c.get("ticker") == ticker), None)
    if not card:
        return None
    facts = summarise.facts_for(card)
    rating = card.get("rating") or {}
    facts["the_dashboards_own_rating"] = (
        f"{rating['label']} (made by the dashboard from published measures, not advice)" if rating.get("label")
        else "not rated" + (f": {rating['why_not']}" if rating.get("why_not") else ""))
    told = ((data.get("company_news") or {}).get("companies") or {}).get(ticker)
    days = brief.week(told, _today(data))
    if days:
        week = brief.facts_for(ticker, card.get("name"), days, (data.get("company_news") or {}).get("level"))
        week["days"] = [dict(d, headlines=d["headlines"][:4]) for d in week["days"][-NEWS_DAYS:]]
        facts["this_weeks_news"] = week["days"]
    return facts


def holdings_facts(data):
    """The owner's holdings as shares and percentages, never amounts; what is new; what is due."""
    rows = (data.get("positions") or {}).get("rows") or []
    account = data.get("account") or {}
    total = account.get("total") or 0
    out = {"holdings": [
        f"{r.get('ticker')}: {(r.get('weight') or 0) * 100:.1f}% of the holdings; "
        + ("not priced" if r.get("pl_pct") is None else f"{r['pl_pct'] * 100:+.1f}% on cost")
        + f"; held {r.get('days_held')} days; the dashboard's rating: "
        + ((r.get("rating") or {}).get("label") or "not rated")
        for r in rows[:15]]}
    if total:
        out["cash_share_of_the_account"] = f"{(account.get('cash') or 0) / total * 100:.1f}%"
    digest = data.get("digest") or {}
    new = []
    for key, what in (("important", "important filing"), ("insider_buys", "insider purchase")):
        for i in digest.get(key) or []:
            new.append(f"{what}: {i.get('ticker')} {i.get('headline') or i.get('label')} ({summarise._day(i.get('date'))})")
    for r in digest.get("ratings") or []:
        new.append(f"rating change: {r.get('ticker')} {r.get('was') or 'unrated'} to {r.get('label')}")
    for m in digest.get("moves") or []:
        new.append(f"{m.get('ticker')} moved {m['change'] * 100:+.1f}% between {summarise._day(m.get('from'))} and {summarise._day(m.get('to'))}")
    if new:
        out["new_since_the_owner_last_looked"] = new[:10]
    soon = [f"{c['ticker']}: results on {summarise._day(c['next_earnings']['date'])}" for c in data.get("companies") or []
            if (c.get("next_earnings") or {}).get("date") and _today(data).isoformat() <= c["next_earnings"]["date"]]
    if soon:
        out["results_coming_up_for_companies_followed"] = sorted(soon, key=lambda s: s.split("results on ")[-1])[:8]
    return out


def facts(data, tickers, mine=False, chart=None):
    """The facts the question is answered from: what the dashboard holds about each company in play,
    what the chart on show shows, and (only with `mine`) the owner's holdings."""
    out = {}
    for t in tickers[:MAX_TICKERS]:
        got = company_facts(data, t)
        out[t] = got if got else "the dashboard holds no figures for this company: it is not followed or held"
    if chart:
        out["the_chart_on_show"] = charts.summary(chart)
    if mine:
        out["the_owners_holdings"] = holdings_facts(data)
    return out


# ---- a question -------------------------------------------------------------------------------
def ask(folder, data, message, ticker=None, range_=None, mine=False, key=None, model=None, opener=None, now=None):
    """Answer one question, keep both turns, and give the conversation: {"turns", "left_today"}.
    A ChatError says in words why not."""
    now = now or datetime.now(timezone.utc)
    message = " ".join(str(message or "").split())
    if not message:
        raise ChatError("Type a question.")
    if len(message) > MAX_QUESTION:
        raise ChatError(f"Keep the question under {MAX_QUESTION} characters.")
    kept = load(folder)
    if today_count(kept["asked"], now) >= PER_DAY:
        raise ChatError(f"That is today's limit of {PER_DAY} questions; it starts again tomorrow.")
    ticker = charts.clean_ticker(ticker)
    tickers = ([ticker] if ticker else []) + [t for t in mentioned(message, data) if t != ticker]
    chart = charts.cached(ticker, range_) if ticker and range_ else None
    given = facts(data, tickers, mine=mine, chart=chart)
    text = ("Facts the dashboard holds:\n" + json.dumps(given, indent=1, ensure_ascii=False) + "\n\nQuestion: " + message
            if given else "Question: " + message)
    earlier = [(t["role"], t["text"]) for t in kept["turns"]][-HISTORY_SENT:]
    try:
        said, used = summarise.ask(SYSTEM, text, key=key, model=model, max_tokens=MAX_OUTPUT_TOKENS, opener=opener,
                                   history=earlier)
        if advice_in(said):                 # once more, told what was wrong; then a plain refusal
            said, used = _again(text, said, earlier, key, model, opener)
            if advice_in(said):
                said = REFUSAL
    except summarise.SummaryError as e:
        raise ChatError(str(e)) from None
    stamp = now.isoformat(timespec="seconds")
    mine_turn = {"role": "user", "text": message, "at": stamp, "ticker": ticker}
    answer = {"role": "assistant", "text": said, "at": stamp, "ticker": ticker, "model": used}
    atomic_write_json(_path(folder), {"turns": (kept["turns"] + [mine_turn, answer])[-MAX_TURNS:],
                                      "asked": [a for a in kept["asked"] if a > (now - timedelta(days=2)).isoformat()] + [stamp]},
                      indent=1)
    return {"turns": turns(folder), "left_today": left_today(folder, now)}


def _again(text, said, earlier, key, model, opener):
    """The question once more, after an answer that advised."""
    return summarise.ask(SYSTEM, RETRY, key=key, model=model, max_tokens=MAX_OUTPUT_TOKENS, opener=opener,
                         history=earlier + [("user", text), ("assistant", said)])

