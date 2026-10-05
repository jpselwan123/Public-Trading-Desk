"""Is the desk working? One report on everything it depends on, safe to paste into a chat.

    python3 doctor.py             the code, the keys, each data source, the stores, the ratings
    python3 doctor.py --account   your broker as well
    python3 doctor.py --offline   no network at all: the code, keys, stores and ratings

Nothing private is printed. A key is said to be set or missing, never shown, and any key
that turns up inside an error is blanked before printing. Trading 212 is said to answer,
never what the account holds. The tickers you follow are listed: they are what the report
is about. Each source is asked once, with a short wait, so the report takes a few seconds.
"""
import json, os, platform, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from env_config import load_env, moment, scrub  # noqa: E402
import health  # noqa: E402

WAIT = 10                       # seconds a source has to answer
KEYS = (("T212_API_KEY", "Trading 212 key", True), ("T212_API_SECRET", "Trading 212 secret", True),
        ("SEC_CONTACT", "SEC contact", True), ("TIINGO_API_KEY", "Tiingo", True),
        ("FINNHUB_API_KEY", "Finnhub", True), ("OPENAI_API_KEY", "OpenAI (summaries)", False))
NOT_RATED = {"financial": "banks, insurers and property companies", "otc": "over the counter",
             "misfiled": "misfiled", "too_few": "with too few themes"}
# (label, file, the field that dates it, what to count)
STORES = (("account", "t212_data.json", "synced_at"),
          ("filings", "news_data.json", "synced_at"),
          ("news", "headlines.json", "updated_at"),
          ("prices", "prices.json", "updated_at"),
          ("latest prices", "quotes.json", "fetched_at"),
          ("financials", "fundamentals.json", "updated_at"),
          ("results dates", "earnings_data.json", "updated_at"),
          ("analysts", "analysts_data.json", "updated_at"),
          ("research", "research.json", "generated_at"),
          ("plans", "plans.json", None),
          ("last looked", "looks.json", "last"),
          ("news in brief", "briefs.json", None),
          ("chat", "chat.json", None),
          ("chart requests", "charts.json", None),
          ("rating sample", "rating_sample.json", "drawn_at"),
          ("ratings log", "ratings_log.json", None),
          ("coverage", "watchlist.json", None))


# ---- the pieces -------------------------------------------------------------------
def on_iphone():
    try:
        return os.uname().machine.startswith(("iPhone", "iPad", "iPod"))
    except (AttributeError, OSError):
        return False


def ago(stamp, now):
    """"8 min ago", "22 h ago", "3 days ago" — or "no date"."""
    when = moment(stamp)
    if when is None:
        try:
            when = datetime.combine(date.fromisoformat(str(stamp)[:10]), datetime.min.time())
        except ValueError:
            return "no date"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    minutes = (now - when).total_seconds() / 60
    if minutes < 90:
        return f"{max(0, round(minutes))} min ago"
    if minutes < 48 * 60:
        return f"{round(minutes / 60)} h ago"
    return f"{round(minutes / 1440)} days ago"


def code(folder, run=subprocess.run, iphone=None):
    """Which code is running, and whether it can update itself."""
    rows = []
    iphone = on_iphone() if iphone is None else iphone
    if not iphone and os.path.isdir(os.path.join(folder, ".git")):
        def git(*args):
            try:
                return run(["git", *args], cwd=folder, capture_output=True, text=True, timeout=10).stdout.strip()
            except Exception:
                return ""
        edits = [l for l in git("status", "--porcelain", "--untracked-files=no").splitlines() if l.strip()]
        rows.append(("version", f"{git('log', '-1', '--format=%h %cd', '--date=short') or 'unknown'} "
                                f"on {git('rev-parse', '--abbrev-ref', 'HEAD') or '?'}, "
                                + (f"{len(edits)} local edits (updates wait until they are undone)" if edits
                                   else "no local edits")))
    else:
        try:
            with open(os.path.join(folder, "PHONE_BUNDLE.json")) as f:
                made = json.load(f)
            rows.append(("version", f"{made.get('commit') or 'unknown'}, packed {str(made.get('made_at'))[:10]}"))
        except (OSError, ValueError):
            rows.append(("version", "unknown (no git here, and no bundle record)"))
    try:
        with open(os.path.join(folder, "server.log")) as f:
            updates = [l.strip() for l in f if " update: " in l]
        if updates:
            rows.append(("last update", updates[-1]))
    except OSError:
        pass
    rows.append(("python", f"{platform.python_version()} on "
                           + ("iPhone" if iphone else f"{platform.system()} {platform.machine()}")))
    return rows


def keys(environ):
    """Each key: set or missing, never its value; and the order settings in words. The broker's
    keys are needed; another broker's, and Trading 212's when another is named, are not."""
    import broker
    try:
        chosen, problem = broker.current(environ), None
    except broker.BrokerError as e:
        chosen, problem = broker.DEFAULT, str(e)
    rows = [("Broker", problem or broker.BROKERS[chosen]["name"] + ("" if environ.get("BROKER", "").strip()
                                                                     else " (BROKER not set: the default)"))]
    for name, label, needed in KEYS:
        if name in broker.BROKERS[broker.DEFAULT]["keys"] and chosen != broker.DEFAULT:
            continue                                     # Trading 212's, and another broker is named
        rows.append((label, "set" if environ.get(name, "").strip()
                     else "MISSING" if needed else "not set (optional)"))
    if chosen != broker.DEFAULT:
        for name in broker.BROKERS[chosen]["keys"]:
            rows.append((name, "set" if environ.get(name, "").strip()
                         else "not set: account.csv in the desk's folder" if name == "BROKER_CSV" else "MISSING"))
    else:
        env = environ.get("T212_ENV", "live").strip().lower() or "live"
        rows.append(("Trading 212 account", env if env in ("live", "demo") else f"'{env}' is not live or demo"))
    import server
    named, usable = environ.get("DESK_HOSTS", "").strip(), server.desk_hosts(environ)
    rows.append(("Phone through Tailscale", "set" if usable else
                 "set, but not a Tailscale name (it must end .ts.net): ignored" if named else "not set (optional)"))
    return rows


def ask(url, headers=None, opener=None, clock=time.monotonic):
    """(ok, what happened, seconds) for one GET."""
    started = clock()
    try:
        req = urllib.request.Request(url, headers=dict({"User-Agent": "trading-desk doctor"}, **(headers or {})))
        with (opener or urllib.request.urlopen)(req, timeout=WAIT) as r:
            r.read(1)
        return True, "ok", clock() - started
    except urllib.error.HTTPError as e:
        why = {401: "the key was refused", 403: "refused (a key, or the SEC contact, is wrong)",
               429: "the free limit is used up for now", 404: "not found"}.get(e.code, "an error")
        return False, f"{why} (HTTP {e.code})", clock() - started
    except Exception as e:
        reason = getattr(e, "reason", None) or e
        return False, f"cannot connect ({str(reason)[:120]})", clock() - started


def sources(environ, opener=None, today=None, run=subprocess.run, account=False, iphone=None, folder=HERE, streamer=None):
    """Each source asked once. Those without their key are skipped, and say why."""
    today = today or datetime.now(timezone.utc).date()
    rows = []

    def check(label, needs, url, headers=None):
        if needs and not environ.get(needs, "").strip():
            rows.append((label, "skipped", f"no {needs} in .env", None))
            return
        ok, what, seconds = ask(url, headers, opener)
        rows.append((label, "ok" if ok else "FAILED", what, seconds))
    contact = environ.get("SEC_CONTACT", "").strip()
    check("SEC EDGAR", "SEC_CONTACT",
          "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/dei/EntityCommonStockSharesOutstanding.json",
          {"User-Agent": f"trading-desk personal research ({contact})"})
    check("Tiingo (prices)", "TIINGO_API_KEY", "https://api.tiingo.com/tiingo/daily/spy",
          {"Authorization": f"Token {environ.get('TIINGO_API_KEY', '').strip()}"})
    import charts
    check("Tiingo (chart bars)", "TIINGO_API_KEY", charts.IEX_URL.format(
        ticker="spy", start=(today - timedelta(days=7)).isoformat(), minutes=5),
          {"Authorization": f"Token {environ.get('TIINGO_API_KEY', '').strip()}"})
    import feeds
    if feeds.ALPACA in feeds.keys(environ):
        check("Alpaca (chart data)", None, feeds.ALPACA_TRADE.format(symbol="SPY"),
              {"APCA-API-KEY-ID": environ.get("ALPACA_API_KEY", "").strip(),
               "APCA-API-SECRET-KEY": environ.get("ALPACA_API_SECRET", "").strip()})
    else:
        rows.append(("Alpaca (chart data)", "skipped", "no Alpaca key pair in .env (optional)", None))
    if feeds.YAHOO in feeds.keys(environ):
        check("Yahoo (chart data)", None, feeds.YAHOO_CHART_URL.format(symbol="SPY", minutes=1, days=1),
              {"User-Agent": feeds.BROWSER})
    else:
        rows.append(("Yahoo (chart data)", "skipped", "YAHOO_CHART is not 1 in .env (optional, unofficial)", None))
    import stream
    for feed, label in ((feeds.ALPACA, "Alpaca (live trades)"), (feeds.FINNHUB, "Finnhub (live trades)")):
        have = feeds.keys(environ)
        if feed not in have:
            rows.append((label, "skipped", f"no {feed} key in .env (optional)", None))
        elif not feeds.stream_enabled(environ):
            rows.append((label, "skipped", "LIVE_STREAM=0 in .env", None))
        else:
            ok, what, seconds = (streamer or stream.check)(feed, have[feed])
            rows.append((label, "ok" if ok else "FAILED", what, seconds))
    check("Finnhub (results, news)", "FINNHUB_API_KEY",
          f"https://finnhub.io/api/v1/quote?symbol=SPY&token={environ.get('FINNHUB_API_KEY', '').strip()}")
    import headlines
    check("Google News (FT, press)", None, headlines.SEARCH_URL.format(
        query=urllib.parse.quote(headlines.press_queries("AAPL", "Apple Inc.", 7)[0])),
          {"User-Agent": headlines.USER_AGENT})
    check("FRED (cash rate)", None, "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3&cosd="
          + (today - timedelta(days=14)).isoformat())
    check("OpenAI (summaries)", "OPENAI_API_KEY", "https://api.openai.com/v1/models",
          {"Authorization": f"Bearer {environ.get('OPENAI_API_KEY', '').strip()}"})
    iphone = on_iphone() if iphone is None else iphone
    if not iphone and os.path.isdir(os.path.join(folder, ".git")):
        started = time.monotonic()
        try:
            done = run(["git", "ls-remote", "--heads", "origin", "main"], cwd=folder, capture_output=True,
                       text=True, timeout=20, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
            ok = done.returncode == 0 and bool(done.stdout.strip())
            rows.append(("GitHub (updates)", "ok" if ok else "FAILED",
                         "ok" if ok else (done.stderr.strip().splitlines() or ["no answer"])[-1][:120],
                         time.monotonic() - started))
        except Exception as e:
            rows.append(("GitHub (updates)", "FAILED", f"no answer ({type(e).__name__})", time.monotonic() - started))
    import broker
    try:
        chosen = broker.current(environ)
    except broker.BrokerError as e:
        rows.append(("Broker", "FAILED", str(e)[:160], None))
        return rows
    if chosen != broker.DEFAULT:
        # another broker (broker.py): asked with --account; an export is a file, read every time
        label = broker.BROKERS[chosen]["name"]
        label = label[:1].upper() + label[1:]
        if account or chosen == "csv":
            started = time.monotonic()
            try:
                rows.append((label, "ok", broker.adapter(chosen).check(environ), time.monotonic() - started))
            except Exception as e:
                rows.append((label, "FAILED", str(e)[:160], time.monotonic() - started))
        else:
            rows.append((label, "skipped", "run with --account", None))
    elif account:
        started = time.monotonic()
        try:
            import t212
            key, secret, env = t212.credentials()
            t212.Client(key, secret, env).get("/equity/account/summary")
            rows.append(("Trading 212", "ok", f"the {env} account answered", time.monotonic() - started))
        except Exception as e:
            rows.append(("Trading 212", "FAILED", str(e)[:160], time.monotonic() - started))
    else:
        rows.append(("Trading 212", "skipped", "run with --account", None))
    return rows


def last_updates(folder, now):
    """What each step did at the last company update and account sync (health.json)."""
    rows = []
    for part in health.for_page(health.load(folder)):
        failed = [s for s in part["steps"] if not s.get("ok")]
        rows.append((part["label"], f"{str(part['at'])[:16].replace('T', ' ')} UTC ({ago(part['at'], now)}), "
                                    f"{len(part['steps']) - len(failed)} of {len(part['steps'])} steps ok"))
        timed = [(s["name"], s["seconds"]) for s in part["steps"] if isinstance(s.get("seconds"), (int, float))]
        if timed:                       # where the time went, as the page's Data sources row has it: names and seconds only
            rows.append(("", health.timing(timed, part.get("seconds"))))
        for s in failed:
            rows.append(("", f"{'WAITING FOR A KEY' if s.get('setup') else 'FAILED'} {s['name']}: {s.get('why')}; last worked "
                             + (ago(s['last_ok'], now) if s.get("last_ok") else "never")))
    return rows or [("", "no update recorded yet (the page records one each time it updates)")]


def stores(folder, now):
    """Each store: its age, and the counts that say whether it holds what it should."""
    rows = []

    def load(name):
        try:
            with open(os.path.join(folder, name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    for label, name, field in STORES:
        data = load(name)
        if data is None:
            rows.append((f"{label} ({name})", "not there yet"))
            continue
        parts = []
        if field:
            parts.append(ago(data.get(field), now) if isinstance(data, dict) and data.get(field) else "no date")
        if name == "t212_data.json":
            parts += [f"{len(data.get('positions') or [])} positions", f"{len(data.get('orders') or [])} orders"]
        elif name == "news_data.json":
            parts += [f"{len(data.get('tickers') or [])} companies", f"{len(data.get('items') or [])} filings",
                      filing_hours(data.get("items"))]
            if data.get("unknown"):
                parts.append("not found at the SEC: " + ", ".join(data["unknown"]))
        elif name in ("headlines.json", "fundamentals.json", "earnings_data.json", "analysts_data.json"):
            companies = data.get("companies") or {}
            parts.append(f"{len(companies)} companies")
            if name == "headlines.json":
                parts.append(", ".join(f"{t} {len(v or [])} ({sum(1 for i in v or [] if i.get('via') == 'press')} press)"
                                       for t, v in companies.items()))
            if data.get("unknown"):
                parts.append("none found for: " + ", ".join(data["unknown"]))
        elif name == "prices.json":
            tickers = [k for k, v in data.items() if isinstance(v, dict) and not k.startswith(("_", "fx_"))
                       and k != "cash_rates"]
            spy = data.get("SPY") or {}
            parts += [f"{len(tickers)} tickers", f"SPY's last close {max(spy) if spy else 'none'}"]
            if data.get("_waiting"):
                parts.append(f"{data['_waiting']} waiting for Tiingo's hourly limit")
        elif name == "quotes.json":
            parts.append(f"{len(data.get('quotes') or {})} tickers")
        elif name == "research.json":
            parts.append(f"{data.get('tested', '?')} tests")
        elif name == "rating_sample.json":
            parts.append(f"{len(data.get('tickers') or [])} companies, drawn from {data.get('eligible', '?')}")
        elif name == "briefs.json":
            parts.append(f"{len(data)} {'company' if len(data) == 1 else 'companies'}, latest written " + ago(max((b or {}).get("written_at") or "" for b in data.values()), now)
                         if isinstance(data, dict) and data else "none written")
        elif name == "chat.json":      # how many turns and questions, never what was said
            turns = data.get("turns") if isinstance(data, dict) else None
            asked = [a for a in (data.get("asked") if isinstance(data, dict) else None) or [] if isinstance(a, str)]
            parts.append("unreadable" if turns is None else f"{len(turns)} turns, {sum(1 for a in asked if a[:10] == now.date().isoformat())} questions today")
        elif name == "charts.json":
            hour = (now - timedelta(hours=1)).isoformat()
            asked = [a for a in (data.get("asked") if isinstance(data, dict) else None) or [] if isinstance(a, str)]
            parts.append(f"{sum(1 for a in asked if a > hour)} in the last hour, {len(asked)} in the last day")
        elif name == "plans.json":
            count = len(data.get("plans") or []) if isinstance(data, dict) else None
            parts.append("unreadable" if count is None else f"{count} plan" + ("" if count == 1 else "s"))
        elif name == "ratings_log.json":
            entries = data if isinstance(data, list) else []
            parts.append(f"{len(entries)} entries" + (f", latest {max(e.get('date', '') for e in entries)}"
                                                      if entries else ""))
        elif name == "watchlist.json":
            parts.append(f"{len(data.get('tickers') or [])} followed: " + ", ".join(data.get("tickers") or []))
        rows.append((f"{label} ({name})", " · ".join(p for p in parts if p)))
    return rows


# EDGAR takes filings from 6:00 to 22:00 New York time; news.filed_moment reads the SEC's
# times on that clock, and the hours stored should fall inside it.
EDGAR_HOURS = ("06:00", "22:00")


def filing_hours(items):
    """The earliest and latest time of day among the filings' acceptance times, as the SEC
    wrote them, and whether they fit the reading of them as New York time."""
    times = sorted(str(i.get("filed_at"))[11:16] for i in items or []
                   if re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d", str(i.get("filed_at") or "")))
    if not times:
        return ""
    fits = EDGAR_HOURS[0] <= times[0] and times[-1] <= EDGAR_HOURS[1]
    return (f"filed between {times[0]} and {times[-1]} as the SEC writes it, "
            + ("inside EDGAR's New York hours, as the desk reads them" if fits
               else "outside EDGAR's 06:00-22:00 New York hours: the desk's reading of SEC times needs checking"))


def ratings(folder, rated=None, tickers=None):
    """How the rated companies split, and each followed company's rating and parts —
    what "almost everything is a Hold" needs to be checked against."""
    import rating, universe, sectors, news, prices
    try:
        if rated is None:
            store = universe.load()
            if not (store or {}).get("companies"):
                return [("", "no universe yet: the next company update on the Mac builds it (a few minutes, "
                             "once), or python3 universe.py")]
            rated = rating.rate_all(store, sectors.load(), universe.load_listings(),
                                    prices.load(os.path.join(folder, "prices.json")),
                                    rating.load_sample(folder))
        tickers = tickers if tickers is not None else news.load_watchlist(os.path.join(folder, "watchlist.json"))
    except Exception as e:
        return [("", f"could not rate ({type(e).__name__}: {str(e)[:120]})")]
    if not rated.get("rated"):
        return [("", "nothing rated: " + rating.WHY_NOT[rated.get("missing") or "no_universe"])]
    labels = [c["label"] for c in rated["companies"].values()]
    against = "NYSE-listed companies" if rated.get("breakpoints") == rating.BREAKPOINT_EXCHANGE else \
        "every US filer (no exchange list yet: it comes with the next company update)"
    built = (universe.load() or {}).get("built")
    rows = [("", f"universe of SEC filers built {built} (rebuilt monthly by the company update on the Mac)")
            ] if built else []
    rows += [("", f"{rated['rated']:,} rated against {against} (definition of {rating.METHOD}): "
                 + ", ".join(f"{label} {labels.count(label):,}" for label in rating.LABELS)),
            ("", "not rated: " + (", ".join(f"{n:,} {NOT_RATED.get(why, why)}"
                                            for why, n in (rated.get("not_rated") or {}).items() if n) or "none"))]
    sample = rated.get("sample") or {}
    need = rating.ready_at(sample.get("size") or 0)
    placed = min((sample.get("placed") or {}).values() or [0])
    rows.append(("", (f"fixed sample: {sample.get('priced', 0)} of {sample.get('size', 0)} priced; value and momentum "
                      + ("placed" if placed >= need else f"placed from {need}"))
                     if sample.get("size") else "fixed sample: not drawn yet (it is, at the next company update)"))
    for ticker in tickers:
        r = rating.for_page(rated, ticker)
        if not r.get("label"):
            rows.append((ticker, "not rated: " + r["why_not"]))
            continue
        parts = ", ".join(f"{f['name'].replace('_', ' ')} "
                          + ("–" if r["factors"][f["name"]]["place"] is None else f"{r['factors'][f['name']]['place']:.0f}")
                          for f in rating.FACTORS)
        rows.append((ticker, f"{r['label']} {r['place']:.0f} among {r['among']:,} ({parts})"))
    return rows


def account_checks(folder, today):
    """The desk's figures rebuilt from the account's records against Trading 212's own
    (checks.py): whether each agrees, and by what share of the account, never an amount or a
    holding's name."""
    import broker, build_desk, checks
    try:
        raw = build_desk.load_json(os.path.join(folder, "t212_data.json"), {})
        if not raw.get("summary"):
            return [("", "no account synced yet")]
        prices = build_desk.load_json(os.path.join(folder, "prices.json"), {})
        raw = broker.complete(raw, prices, today)
        account = build_desk.build_account(raw["summary"], raw.get("positions") or [])
        made = checks.checks(raw, account, prices, today)
    except Exception as e:
        return [("", f"could not check ({type(e).__name__}: {str(e)[:120]})")]
    if not made:
        return [("", "no account total to check against")]
    if made.get("none_because"):
        return [("", made["none_because"])]
    return ([(c["name"], ("agrees" if c["ok"] else "DOES NOT AGREE") + " · " + c["plain"]) for c in made["checks"]]
            + weekly_line(raw, account, prices, today))


def weekly_line(raw, account, prices, today):
    """Whether the Overview's weekly line and the History's risk figures can be drawn, and how many weeks they rest
    on: counts and a category only. The reason the page gives can carry an amount, so it is not repeated here."""
    import history
    try:
        h = history.build(raw, account, prices, today)
    except Exception as e:
        return [("weekly", f"could not be worked out ({type(e).__name__})")]
    if not h:
        return [("weekly", "no money put in yet")]
    curve, risk = h["curve"], h["risk"]
    if "why" in curve:
        check = h.get("check")
        return [("weekly", "withheld · " + ("the rebuilt history does not tie to the account's total (History says by how much)"
                                                 if check and not check["ok"] else "too many weeks without a close, or no total to check against"))]
    rows = [("weekly", f"drawn · {len(curve['days'])} weeks, {curve['skipped']} left out for want of a close")]
    rows.append(("risk", "withheld · fewer than %d whole weeks, or the S&P 500 did not move" % history.RISK_MIN_WEEKS
                 if "why" in risk else f"shown · {risk['weeks']} whole weeks"))
    return rows


def account_source(folder):
    """The broker the stored account came from, by name (broker.py)."""
    import broker, build_desk
    return broker.name_of(build_desk.load_json(os.path.join(folder, "t212_data.json"), {}))


def report(folder=HERE, environ=None, now=None, offline=False, account=False, opener=None, run=subprocess.run,
           rated=None, iphone=None, streamer=None):
    environ = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
    out = [f"Trading Desk health check, {now.strftime('%d %b %Y %H:%M')} UTC",
           "Nothing private below: no keys, no amounts. Safe to paste.", ""]

    def section(title, rows, width=None):
        out.append(title)
        width = width or max([len(r[0]) for r in rows] + [0])
        for row in rows:
            out.append(("  " + row[0].ljust(width) + "  " + row[1]).rstrip() if row[0] else "  " + row[1])
        out.append("")
    section("Code", code(folder, run=run, iphone=iphone))
    section("Keys (.env)", keys(environ))
    if offline:
        section("Sources", [("", "not asked (--offline)")])
    else:
        rows = sources(environ, opener=opener, today=now.date(), run=run, account=account, iphone=iphone,
                       folder=folder, streamer=streamer)
        section("Sources (each asked once)",
                [(label, f"{state:<7} {what}" + (f" · {seconds:.1f} s" if seconds is not None and state != "skipped"
                                                 else "")) for label, state, what, seconds in rows])
    section("Last updates", last_updates(folder, now))
    section("Stores", stores(folder, now))
    section("Checks against " + account_source(folder), account_checks(folder, now.date()))
    section("Ratings", ratings(folder, rated=rated))
    return scrub("\n".join(out).rstrip() + "\n", environ)


def main(argv):
    load_env(os.path.join(HERE, ".env"))
    text = report(offline="--offline" in argv, account="--account" in argv)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
