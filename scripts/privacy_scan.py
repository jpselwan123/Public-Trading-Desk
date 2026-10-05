"""Pre-push privacy scan: fails if anything personal is about to be committed.

Checks every tracked file (or staged files with --staged) for:
- any secret value from .env (Trading 212 key/secret, AI keys)
- order ids and transaction/dividend references from your real t212_data.json
- absolute home-directory paths and common key/token formats

Nothing personal is hardcoded here: identifiers are read at runtime from your
local, git-ignored files.

Usage: python3 scripts/privacy_scan.py [--staged]      exit 0 = clean, 1 = issues
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PATTERNS = {
    "home directory path": r"/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/",
    "OpenAI key": r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{20,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}
ALLOWED_FILES = {"scripts/privacy_scan.py"}  # contains the patterns themselves
NEVER_TRACK = {".env", "t212_data.json", "account.csv", "desk_data.json", "journal.json", "theses.json", "diffs.json", "index.html",
               "news_data.json", "headlines.json", "health.json", "looks.json", "plans.json", "rating_sample.json", "watchlist.json", ".cik_map.json", "fundamentals.json",
               "earnings_data.json", "prices.json", "summaries.json", "briefs.json", "paper.json", "research.json", "analysts_data.json", "orders.json", "power.json", "instruments.json",
               "quotes.json", "ratings_log.json", "chat.json", "charts.json", "TradingDesk-phone.zip", "PHONE_BUNDLE.json",
               "CLAUDE.local.md"}


def local_secrets():
    found = []
    if os.path.exists(".env"):
        for line in open(".env"):
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if len(value) >= 12 and "MODEL" not in key and "ENV" not in key:
                found.append((f".env {key.strip()}", value))
    if os.path.exists("t212_data.json"):
        try:
            data = json.load(open("t212_data.json"))
        except ValueError:
            data = {}
        if not data.get("demo_data"):
            for o in data.get("orders") or []:
                oid = str(((o or {}).get("order") or {}).get("id") or "")
                if len(oid) >= 8:
                    found.append(("real order id", oid))
            for name in ("dividends", "transactions"):
                for t in data.get(name) or []:
                    ref = str((t or {}).get("reference") or "")
                    if len(ref) >= 8:
                        found.append((f"real {name} reference", ref))
    return found


def files_to_scan(staged):
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    return [f for f in subprocess.check_output(cmd).decode().splitlines() if f and os.path.isfile(f)]


def main():
    staged = "--staged" in sys.argv
    secrets = local_secrets()
    issues = []
    for path in files_to_scan(staged):
        if os.path.basename(path) in NEVER_TRACK or path.startswith("demo/"):
            issues.append(f"{path}: personal/generated file must not be tracked")
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for label, value in secrets:
            if value in text:
                issues.append(f"{path}: contains {label}")
        if path in ALLOWED_FILES:
            continue
        for label, pat in PATTERNS.items():
            if re.search(pat, text):
                issues.append(f"{path}: looks like a {label}")
    if issues:
        print("Privacy scan FAILED:")
        for i in sorted(set(issues)):
            print("  - " + i)
        return 1
    print(f"Privacy scan clean ({'staged' if staged else 'tracked'} files, {len(secrets)} private values checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
