"""What changed in the wording of a company's annual report (fourth review, Phase 10).

Risk factors (Item 1A) and management's discussion (Item 7) of each covered
company's latest 10-K, set against the same sections of the one before: the passages
added and the passages removed, longest first, with a count of each. Nothing is
interpreted — what changed in the wording is the finding, and what it means is the
reader's to judge. Changes in exactly these sections are what Cohen, Malloy & Nguyen
(2020, 'Lazy Prices', Journal of Finance 75) found investors are slow to read.

How the text is read, and nothing more clever than this:

- The 10-K's main document, from the SEC, as news.py already lists it. Hidden inline
  XBRL (the ix:header block, anything styled display:none), scripts and styles are
  skipped; block elements become line breaks.
- A section runs from its "Item 1A" (or "Item 7") heading to the next item's heading.
  The table of contents holds the same headings a few lines apart, so of every such
  span the longest is the section.
- Page furniture is left out: lines that are only a page number, "Table of Contents"
  or a part heading, lines repeated within the section (running headers), and lines
  with no word in them (table cells of figures).
- The text is compared sentence by sentence (difflib, Python's standard library), so a
  year changed in one sentence marks that sentence, not its whole paragraph. A run of
  consecutive changed sentences is one passage.

Stdlib only. Stored in diffs.json (git-ignored): the latest filing's sentences, so the
next one can be compared without fetching this one again, and each comparison.
"""
import difflib
import json
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser

from env_config import atomic_write_json


HERE = os.path.dirname(os.path.abspath(__file__))
DIFFS_FILE = os.path.join(HERE, "diffs.json")
SECTIONS = {
    "risk_factors": {"label": "Risk factors (Item 1A)",
                     "start": r"item\s*1a\b", "end": r"item\s*1b\b|item\s*1c\b|item\s*2\b",
                     "title": r"risk factors\.?"},
    "mdna": {"label": "Management's discussion (Item 7)",
             "start": r"item\s*7\b(?!a)", "end": r"item\s*7a\b|item\s*8\b",
             "title": r"management'?s discussion and analysis of financial condition and results of operations\.?"},
}
BLOCK = {"p", "div", "br", "tr", "td", "li", "ul", "ol", "table", "section",
         "h1", "h2", "h3", "h4", "h5", "h6"}
VOID = {"br", "img", "meta", "link", "input", "hr", "col", "wbr", "area", "base", "source"}
FURNITURE = re.compile(r"^(table of contents|part [ivx]+|page \d+|\d+|[ivx]+)$", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z]{2,}")
SENTENCE_END = re.compile(r'(?<=[.!?;])\s+(?=[A-Z"(•◦])|\s*[•◦]\s*')
QUOTES = {"\xa0": " ", "’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.hidden = [], None           # [tag, depth] of the element being skipped

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            if tag == self.hidden[0] and tag not in VOID:
                self.hidden[1] += 1
            return
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if tag in ("script", "style", "ix:header") or "display:none" in style:
            if tag not in VOID:
                self.hidden = [tag, 1]
            return
        if tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[0]:
                self.hidden[1] -= 1
                if not self.hidden[1]:
                    self.hidden = None
            return
        if tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.out.append(data)


def lines(document):
    """The visible text of an HTML filing, one line per block, whitespace collapsed."""
    parser = _Text()
    parser.feed(document or "")
    parser.close()
    text = "".join(parser.out)
    for odd, plain in QUOTES.items():
        text = text.replace(odd, plain)
    return [line for line in (" ".join(raw.split()) for raw in text.split("\n")) if line]


def section(all_lines, key):
    """The lines of one section, heading excluded, or None when it is not found."""
    spec, best = SECTIONS[key], None
    for i, line in enumerate(all_lines):
        if not re.match(spec["start"], line, re.IGNORECASE):
            continue
        end = next((j for j in range(i + 1, len(all_lines))
                    if re.match(spec["end"], all_lines[j], re.IGNORECASE)), None)
        if end is not None and (best is None or end - i > best[1] - best[0]):
            best = (i, end)
    return all_lines[best[0] + 1:best[1]] if best else None


def sentences(section_lines):
    """The section's language, sentence by sentence, without page furniture."""
    counts = Counter(section_lines)
    out = []
    for line in section_lines:
        if counts[line] > 1 or FURNITURE.match(line) or not WORD.search(line):
            continue
        out.extend(s.strip() for s in SENTENCE_END.split(line) if s.strip() and WORD.search(s))
    return out


def extract(document):
    """Each section's sentences, or None when the main document does not hold it —
    including when all it holds is the section's own title, a pointer to the annual
    report to shareholders (JPMorgan's Item 7): two identical pointers would otherwise
    read as "nothing changed"."""
    found, out = lines(document), {}
    for key, spec in SECTIONS.items():
        part = section(found, key)
        said = sentences(part) if part is not None else []
        out[key] = said if any(not re.fullmatch(spec["title"], s, re.IGNORECASE) for s in said) else None
    return out


def compare(old, new):
    """Added and removed passages, longest first, and how much carried over."""
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    added, removed = [], []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op in ("delete", "replace"):
            removed.append(" ".join(old[i1:i2]))
        if op in ("insert", "replace"):
            added.append(" ".join(new[j1:j2]))
    return {"added": sorted(added, key=len, reverse=True),
            "removed": sorted(removed, key=len, reverse=True),
            "kept": sum(block.size for block in matcher.get_matching_blocks()),
            "sentences_before": len(old), "sentences_now": len(new)}


def annual_reports(items, ticker):
    """The company's 10-Ks news.py has listed, newest first (amendments left out: a
    10-K/A is usually a part, not the report)."""
    return sorted((i for i in items or [] if i.get("ticker") == ticker
                   and (i.get("form") or "").upper() == "10-K" and i.get("url")),
                  key=lambda i: i.get("date") or "", reverse=True)


def load(path=None):
    try:
        with open(path or DIFFS_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def merge_company(stored, fresh, ticker):
    """`stored` with one company's comparison taken from `fresh`, an update run for it alone
    (prune=False), the others' as they were. Made twice, it changes nothing more."""
    out = dict(stored or {})
    ticker = str(ticker).upper()
    if ticker in ((fresh or {}).get("companies") or {}):
        out["companies"] = dict(out.get("companies") or {}, **{ticker: fresh["companies"][ticker]})
    return out


def update(tickers, items, ua, fetch_text, stored=None, prune=True):
    """Compare each covered company's latest two 10-Ks, fetching only what is not
    already held. With the whole coverage list (`prune`), companies no longer covered
    are dropped. Returns the store; the caller writes it, like every refresh step."""
    stored = load() if stored is None else stored
    companies = stored.setdefault("companies", {})
    for ticker in tickers or []:
        reports = annual_reports(items, ticker)
        if len(reports) < 2:
            companies[ticker] = {"why_not": "fewer than two annual reports listed for it"}
            continue
        newest, before = reports[0], reports[1]
        held = companies.get(ticker) or {}
        if held.get("new", {}).get("url") == newest["url"] and held.get("sections"):
            continue
        if held.get("new", {}).get("url") == before["url"] and held.get("text"):
            old_text = held["text"]                    # last year's newest is this year's older
        else:
            old_doc = fetch_text(before["url"], ua)
            if not old_doc:
                continue                               # fetched next refresh; nothing guessed
            old_text = extract(old_doc)
        new_doc = fetch_text(newest["url"], ua)
        if not new_doc:
            continue
        new_text = extract(new_doc)
        result = {"new": {"url": newest["url"], "date": newest["date"]},
                  "old": {"url": before["url"], "date": before["date"]},
                  "text": new_text, "sections": {}}
        for key, spec in SECTIONS.items():
            if not old_text.get(key) or not new_text.get(key):
                result["sections"][key] = {"label": spec["label"], "why_not":
                                           "the section is not in the filing's main document — it may be "
                                           "incorporated from the annual report to shareholders"}
                continue
            result["sections"][key] = dict(compare(old_text[key], new_text[key]), label=spec["label"])
        companies[ticker] = result
    for ticker in list(companies) if prune else []:
        if ticker not in (tickers or []):
            del companies[ticker]                      # no longer covered
    return stored


def for_card(stored, ticker):
    """What the page shows: the comparison without the stored text."""
    held = ((stored or {}).get("companies") or {}).get(ticker)
    if not held:
        return None
    return {k: v for k, v in held.items() if k != "text"}


def main(argv):
    """python3 diffs.py [TICKER ...]: compare the covered companies' latest two 10-Ks."""
    import news
    tickers = [a.upper() for a in argv] or news.load_watchlist()
    items = (load_news() or {}).get("items") or []
    stored = update(tickers, items, news.user_agent(), news.fetch_text, prune=not argv)
    atomic_write_json(DIFFS_FILE, stored)
    for ticker in tickers:
        held = (stored.get("companies") or {}).get(ticker) or {}
        for key, part in (held.get("sections") or {}).items():
            print(f"{ticker} {part['label']}: " + (part.get("why_not") or
                  f"{len(part['added'])} passages added, {len(part['removed'])} removed"))
    return 0


def load_news():
    try:
        with open(os.path.join(HERE, "news_data.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
