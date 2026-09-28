"""A company's week of news in brief, a few lines written when the user asks, to get the
gist quickly.

The model is given what the News fold already shows for the last WEEK_DAYS: each day's
headlines and the outlets that carried them, the company's important filings, and the
shares' move against the market that day with whether it was unusual (build_desk.unusual).
It writes what the headlines were about. It never sees an article, only its headline, and
is told so; it may set a day's move beside that day's headlines but never say one caused
the other, as the page never does; and, like every piece of writing here, it names no
target and never says buy or sell. The news never enters the desk's rating.

Written only on request (POST /brief) and kept with the stories it was written from
(`stories`), so the page can say how many have come since and a second request for the
same stories costs nothing. (The Overview's "since you last looked" is build_desk.build_digest,
another thing.)
"""
import json, os
from datetime import datetime, timedelta, timezone

import summarise
from env_config import atomic_write_json

BRIEF_FILE = "briefs.json"
WEEK_DAYS = 7               # the desk's choice: a week of sessions, today's among them
MAX_OUTPUT_TOKENS = 450

SYSTEM = """You write a short brief on one company's news over the past week for the \
owner of a personal research dashboard. You are given, for each day: the headlines about \
the company and which outlets carried each, the company's important filings with the SEC, \
and how its shares moved that day against the market, with whether that move was unusual \
for them.

Rules:
- Use only what is given. You have the headlines, not the articles: never claim to know \
what an article says beyond its headline, and never use outside knowledge of the company \
or of recent events.
- Say what the headlines were about, grouped into at most three themes, the most covered \
first. Name an outlet only where it matters (one outlet alone reporting something, say).
- Never say or suggest that a story caused a move in the shares, even on an unusual day. \
You may set them side by side: "on the day the shares fell 3.1% against the market, the \
headlines were about ...".
- Where headlines disagree, say they disagree.
- No recommendation: never say buy, sell, hold, undervalued, overvalued, or that anyone \
should do anything, and name no target price. You describe, the reader decides.
- Plain English, no jargon. Under 130 words, in two short paragraphs at most.
- Repeat figures and dates exactly as given."""


def week(company, today):
    """This week's sessions in a company's news (build_desk.build_headlines' `days`,
    newest first): those after the day WEEK_DAYS before `today`."""
    start = (today - timedelta(days=WEEK_DAYS)).isoformat()
    return [d for d in (company or {}).get("days") or [] if (d.get("session") or "") > start]


def story_ids(days):
    """What a brief is written from: every story's and filing's link (its headline when it
    has none), sorted. The same list means the same news."""
    return sorted({i.get("url") or i.get("headline") for d in days or []
                   for i in (d.get("items") or []) + (d.get("filings") or []) if i.get("url") or i.get("headline")})


def _unusual(day, level):
    if day.get("unusual") is None:
        return "not measured (too little price history, or no move that day)"
    return (f"yes: outside the {level} range of its ordinary days" if day["unusual"]
            else "no: within its ordinary range")


def facts_for(ticker, name, days, level):
    """What the model may use, oldest day first, written the way it should repeat it."""
    return {"company": name or ticker, "ticker": ticker, "days": [{
        "day": summarise._day(d.get("session")),
        "shares_against_the_market": summarise._pct(d.get("move"), sign=True),
        "was_that_move_unusual": _unusual(d, level),
        "headlines": [{"headline": s.get("headline"), "carried_by": ", ".join(s.get("sources") or [])}
                      for s in d.get("items") or []],
        "filings": [f"{f.get('headline')} ({f.get('form')})" for f in d.get("filings") or []],
    } for d in sorted(days, key=lambda d: d.get("session") or "")]}


def write(ticker, name, days, level, key=None, model=None, opener=None):
    """The brief on `days` (week's answer), with the stories it was written from."""
    text, model = summarise.ask(SYSTEM, "This week's news about the company:\n" +
                                json.dumps(facts_for(ticker, name, days, level), indent=1),
                                key=key, model=model, max_tokens=MAX_OUTPUT_TOKENS, opener=opener)
    sessions = sorted(d.get("session") for d in days)
    return {"text": text, "model": model, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "from": sessions[0], "to": sessions[-1], "stories": story_ids(days),
            "headlines": sum(len(d.get("items") or []) for d in days)}


def for_page(stored, company, today):
    """A kept brief as the page shows it: without its list of stories, and with how many of
    this week's came after it was written. None without one."""
    if not stored or not stored.get("text"):
        return None
    ids = set(stored.get("stories") or [])
    shown = {k: v for k, v in stored.items() if k != "stories"}
    shown["new_since"] = sum(1 for i in story_ids(week(company, today)) if i not in ids)
    return shown


def load(folder):
    try:
        with open(os.path.join(folder, BRIEF_FILE)) as f:
            data = json.load(f)
        return {t: b for t, b in data.items() if isinstance(b, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(folder, briefs):
    atomic_write_json(os.path.join(folder, BRIEF_FILE), briefs, indent=1)
