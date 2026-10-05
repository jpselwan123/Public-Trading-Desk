"""Local server for the Trading Desk page. Binds to 127.0.0.1 only.

  GET  /           the dashboard (index.html)
  GET  /data       desk_data.json (fresh numbers without reloading)
  GET  /asof       ?date=YYYY-MM-DD: the desk as it was at the end of a past day, built in
                   memory from what was known then (asof.py); read-only
  POST /refresh    {part: "account"}: pull Trading 212 (read-only) + rebuild, when sync is pressed;
                   {part: "market"}: filings, prices, financials, ratings, research + rebuild,
                   run by the page on opening and every build_desk.MARKET_EVERY_MINUTES
                   Answered as it goes: one JSON line per step, the result on the last
  POST /journal    save a trade note {id, note, look_again} to journal.json
  POST /watchlist  {follow, replaces} or {unfollow}: the coverage list (news.py's rules)
  POST /fetch      {ticker}: load one company just followed, answered as it goes like /refresh
  POST /thesis     write a thesis once, before a covered company reports (thesis.py's rules)
  POST /plan       write a plan once, before its trade {ticker, side, why, wrong_if, review_by} (plans.py)
  POST /summary    write the plain-English read on one company
  POST /brief      {ticker, refresh}: the week's news about one company in brief (brief.py)
  POST /paper      a practice trade
  POST /screen     run a screen over the stored universe
  POST /check      {ticker, side, amount}: the facts about a trade before it is placed (trade_check.py);
                   reads only, sends nothing

Requests from other websites are refused (Host and Origin must be this server), so a
page elsewhere can't trigger a refresh or write notes. The one other way in is opt-in:
the Mac's Tailscale name, set in .env as DESK_HOSTS, for the user's own phone to open
this desk through `tailscale serve` (docs/ONE-DESK.md).

Usage: python3 server.py [--demo]     then open http://127.0.0.1:8935/
"""
import json, os, re, subprocess, sys, threading, time, traceback
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from env_config import atomic_write_json, load_env, read_for_writing, UnreadableStore, PARTLY, SETUP_STEPS, scrub
from health import timing   # noqa: F401  (the refresh's "Took …" line; health.py owns it)
import analysts, asof, brief, broker, build_desk, context, diffs, earnings, fundamentals, headlines, health, looks, news, paper, plans, prices, rating, research, screen, sectors, summarise, t212, thesis, trade_check, universe, value

HOST, PORT = "127.0.0.1", 8935
HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
# A Tailscale machine name (MagicDNS: the-mac.tailnet-name.ts.net), and nothing else: the
# server still listens on this Mac alone, and `tailscale serve` hands it the user's own
# devices' requests under that name (26 Sep 2026: one desk for the Mac and the phone).
TAILNET_NAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net$")


def desk_hosts(environ=None):
    """The names in .env's DESK_HOSTS (comma separated) that are Tailscale machine names;
    anything else in it is ignored."""
    environ = os.environ if environ is None else environ
    names = (n.strip().lower() for n in str(environ.get("DESK_HOSTS") or "").split(","))
    return frozenset(n for n in names if TAILNET_NAME.match(n))
REFRESH_TIMEOUT = 900        # first sync walks all history at 6 pages/min
# phone.py sets this: an iPhone app cannot start another program, so there the sync runs
# inside the server itself, and each request's own timeout stands in for the process's
IN_PROCESS_SYNC = False
# phone.py sets this too: the rating's universe and industry codes are large downloads,
# built on the Mac and brought to the phone in a bundle, never fetched on the phone
ON_PHONE = False
ON_THE_PAGE = ("Prices on the page", "Filings on the page")      # the steps of a company update that rebuild the page early
HEARTBEAT = 10               # seconds between blank lines while a refresh runs, so no
                             # browser, web view or network takes the connection for dead
MAX_BODY = 16 * 1024
# Two refreshes, apart, so the company data never depends on the broker. The account: the
# broker alone, when the user presses sync. The market: filings, prices, financials,
# results, ratings and research, which reach no broker; the page runs it on opening and
# every build_desk.MARKET_EVERY_MINUTES.
account_lock = threading.Lock()
market_lock = threading.Lock()
journal_lock = threading.Lock()
build_lock = threading.Lock()         # one page build at a time: two refreshes may end together
health_lock = threading.Lock()        # both refreshes record what their steps did
looks_lock = threading.Lock()         # the page's opening and its reloads record the user's visits
briefs_lock = threading.Lock()        # two briefs written at once each keep the other


class Merge:
    """What a step returns in place of a whole store when it changes part of one: `apply(stored)`
    is the store with the change made, from whatever the store holds when it is written. It must
    be a change that can be made twice (a company's entries put in, never added to). `load` reads
    the store (build_desk.load_json's by default); `partly` is why part of it could not be read."""
    def __init__(self, apply, load=None, partly=None):
        self.apply, self.load, self.partly = apply, load, partly


class Stores:
    """One writer at a time for each store, and nothing lost between two, so a company's figures
    load at once. A company followed
    is loaded at once, beside a company update that may be running, which it used to wait for:
    its changes are made to each store as it stands (Merge), and the update, which writes a
    store from what it read before, makes every change made since it began again on what it
    writes. Its own pruning of the companies it did not know of is undone the same way."""
    def __init__(self):
        self._guard = threading.Lock()
        self._locks = {}
        self._changes = []              # (number, path, Merge), in the order made
        self._open = {}                 # each update under way: the number it began at
        self._number = 0

    def _lock(self, path):
        with self._guard:
            return self._locks.setdefault(os.path.abspath(path), threading.Lock())

    def begin(self):
        """An update begins: the changes made from now on are kept until it ends."""
        with self._guard:
            token = object()
            self._open[token] = self._number
            return token

    def end(self, token):
        with self._guard:
            self._open.pop(token, None)
            oldest = min(self._open.values(), default=self._number)
            self._changes = [c for c in self._changes if c[0] > oldest]

    def write(self, path, data, since=None):
        """Write `data` to `path`: a Merge made on the store as it stands, or a whole store read
        before, with each change made since `since` (a begin()) made again on it."""
        path = os.path.abspath(path)
        with self._lock(path):
            if isinstance(data, Merge):
                result = data.apply(data.load(path) if data.load else build_desk.load_json(path, {}))
                with self._guard:
                    self._number += 1
                    if self._open:
                        self._changes.append((self._number, path, data))
            else:
                result = data
                with self._guard:
                    start = self._open.get(since)
                    again = [] if start is None else [c for n, p, c in self._changes if p == path and n > start]
                for change in again:
                    result = change.apply(result)
            atomic_write_json(path, result)
            return result


STORES = Stores()


class Handler(BaseHTTPRequestHandler):
    folder = HERE
    demo = False
    remote_hosts = frozenset()           # desk_hosts(), set when the server starts
    pressed = False                      # this company update was asked for by the button: news is asked afresh
    unfinished = frozenset()             # the steps of the run in hand that have not ended (run_steps)

    def log_message(self, *args):        # keep the terminal quiet
        pass

    # ---- guards ----
    def _where(self):
        """"here" for this Mac, "tailnet" for the user's device through Tailscale, None for
        anything else. The Origin, when a browser sends one, must be the same place. A
        proxy may pass the request on under this Mac's own name, so a Tailscale origin, or
        the user header `tailscale serve` adds, also marks it as the tailnet's."""
        host, origin = self.headers.get("Host", "").lower(), self.headers.get("Origin")
        tailnet_origins = {"https://" + name for name in self.remote_hosts}
        through_tailscale = bool(self.headers.get("Tailscale-User-Login"))
        if host in ALLOWED_HOSTS:
            if origin is None or origin.split("://", 1)[-1] in ALLOWED_HOSTS:
                return "tailnet" if through_tailscale else "here"
            return "tailnet" if origin in tailnet_origins else None
        if host in self.remote_hosts:
            return "tailnet" if origin in (None, "https://" + host) else None
        return None

    def _local(self):
        return self._where() is not None

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, name, ctype):
        path = os.path.join(self.folder, name)
        if not os.path.exists(path):
            return self._send(404, {"error": f"{name} not built yet: run ./refresh.sh"})
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- routes ----
    def do_GET(self):
        if not self._local():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            if self.look():
                self.build()                  # a new visit: "since you last looked" moves on
            return self._file("index.html", "text/html; charset=utf-8")
        if path == "/data":
            self.look()                       # the open page's reloads keep the visit going
            return self._file("desk_data.json", "application/json")
        if path == "/asof":
            return self._send(*self.as_of(self.path.partition("?")[2]))
        self._send(404, {"error": "not found"})

    def look(self):
        """Record this moment of use (looks.py); True when it began a new visit."""
        with looks_lock:
            stored, new_visit = looks.record(looks.load(self.folder))
            try:
                atomic_write_json(os.path.join(self.folder, looks.LOOKS_FILE), stored)
            except OSError:
                return False                  # a folder that cannot be written is still served
        return new_visit and bool(stored.get("previous"))

    def as_of(self, query):
        """The desk rebuilt as it was at the end of a past day (asof.py). Read-only:
        built in memory, nothing written."""
        from urllib.parse import parse_qs
        day = asof.valid((parse_qs(query).get("date") or [""])[0], datetime.now(timezone.utc).date())
        if not day:
            return 400, {"error": "bad date", "message": "Choose a real day before today."}
        return 200, build_desk.as_of(self.folder, day)

    def do_POST(self):
        if not self._local():
            return self._send(403, {"error": "forbidden"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            return self._send(400, {"error": "bad length"})
        if length > MAX_BODY:
            return self._send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})
        if not isinstance(body, dict):                  # every endpoint reads named fields
            return self._send(400, {"error": "the body must be a JSON object"})
        path = self.path.split("?", 1)[0]
        if path == "/refresh":
            # {"part": "account"} syncs the broker; {"part": "market"} the company data.
            # Sent with neither (an older page, ./refresh.sh's habit), it is the account.
            part = body.get("part") if body.get("part") in ("account", "market") else "account"
            self.pressed = body.get("pressed") is True
            lock, work = ((account_lock, self.refresh_account) if part == "account"
                          else (market_lock, self.refresh_market))
            if not lock.acquire(blocking=False):
                return self._send(409, {"ok": False, "busy": True,
                                        "message": "Already syncing the account" if part == "account"
                                        else "Company data is already updating"})
            try:
                return self._stream(work)
            finally:
                lock.release()
        if path == "/fetch":
            # at once, beside a company update under way: neither refused (it stayed empty until the
            # next refresh, 26 Sep) nor kept waiting for the update to end (28 Sep); see Stores
            return self._stream(lambda report: self.fetch_company(body.get("ticker"), report))
        if path == "/journal":
            return self._send(*self.save_note(body))
        if path == "/watchlist":
            return self._send(*self.save_watchlist(body))
        if path == "/thesis":
            return self._send(*self.write_thesis(body))
        if path == "/plan":
            return self._send(*self.write_plan(body))
        if path == "/summary":
            return self._send(*self.summary(body))
        if path == "/brief":
            return self._send(*self.write_brief(body))
        if path == "/paper":
            return self._send(*self.paper_trade(body))
        if path == "/screen":
            return self._send(*self.run_screen(body))
        if path == "/check":
            return self._send(*self.check_trade(body))
        self._send(404, {"error": "not found"})

    def _stream(self, work):
        """Answer as the work goes: each event `work` reports is one JSON line, the
        result is the last, and a blank line goes out every HEARTBEAT seconds between.
        A page that goes away does not stop the work; its lines are dropped."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        writing, finished = threading.Lock(), threading.Event()

        def line(event=None):
            with writing:
                try:
                    self.wfile.write(b"\n" if event is None else (json.dumps(event) + "\n").encode())
                    self.wfile.flush()
                except OSError:
                    pass

        def heartbeat():
            while not finished.wait(HEARTBEAT):
                line()
        threading.Thread(target=heartbeat, daemon=True).start()
        try:
            line(work(line)[1])
        except Exception:
            line({"ok": False, "message": "The refresh stopped on an error in the desk itself; server.log has it"})
            raise                                  # into server.log, as before
        finally:
            finished.set()

    def build(self):
        """Rebuild the page from the stores. One at a time: the account sync and the
        market refresh can end together."""
        with build_lock:
            build_desk.main([self.folder])

    def refresh_account(self, report=lambda event: None):
        """The account, from the broker .env names (broker.py): the page is rebuilt as soon as
        it has answered. `report` hears each step start and end."""
        timed, began = [], time.monotonic()
        if self.demo:
            self.build()
            return 200, {"ok": True, "message": None, "timing": None}
        key, problem = broker.configured()
        if problem:
            return 200, {"ok": False, "message": problem}
        name = broker.BROKERS[key]["name"]
        failed = self.run_steps([(name[:1].upper() + name[1:], self.sync_account)], report, timed)
        wall = time.monotonic() - began
        self.record_health("account", timed, failed, wall)
        if failed:
            return 200, {"ok": False, "message": failed[0][1]}
        self.build()
        report({"built": True})
        return 200, {"ok": True, "message": None, "timing": timing(timed, wall)}

    @staticmethod
    def failures(problems):
        """Steps that failed, in words: those that failed for one reason named together, in
        the order they ran ("Filings, industry codes and prices: …"), so a key missing from
        .env reads once, not once for every step that needs it."""
        by_reason = {}
        for name, why in problems:
            by_reason.setdefault(why, []).append(name)
        def names(group):
            group = [group[0]] + [n[:1].lower() + n[1:] for n in group[1:]]
            return group[0] if len(group) == 1 else ", ".join(group[:-1]) + " and " + group[-1]
        return "; ".join(f"{names(group)}: {why}" for why, group in by_reason.items()) or None

    def record_health(self, part, timed, failed, wall=None):
        """What each step did, and how long the run took by the clock, for the page's "Data sources"
        row and doctor.py."""
        with health_lock:
            atomic_write_json(os.path.join(self.folder, health.HEALTH_FILE),
                              health.record(health.load(self.folder), part, timed, failed, wall=wall))

    def refresh_market(self, report=lambda event: None):
        """Everything but the account: filings, prices, financials, results, ratings and
        research. No step reaches the broker."""
        timed, began = [], time.monotonic()
        problems = [] if self.demo else self.update_research(report, timed)
        wall = time.monotonic() - began
        if not self.demo:
            self.record_health("market", timed, problems, wall)
        self.build()
        # a key not added yet is a step to take, said apart from what failed
        failed = [p for p in problems if p[1] not in SETUP_STEPS]
        setup = list(dict.fromkeys(why for _, why in problems if why in SETUP_STEPS))
        return 200, {"ok": True, "message": self.failures(failed), "setup": setup, "timing": timing(timed, wall)}

    def sync_account(self):
        """t212.py in its own process, as ./refresh.sh runs it; on a phone, in this one. Another
        broker's sync (broker.py) the same way."""
        if broker.current() != broker.DEFAULT:
            return self.sync_other()
        if IN_PROCESS_SYNC:
            try:
                t212.sync_to_file()
            except t212.T212Error:
                raise
            except Exception as e:                  # as the process's exit would have said it
                raise t212.T212Error(f"Sync failed: {e}"[:300]) from None
            return None, None
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "t212.py")], cwd=HERE,
                               capture_output=True, text=True, timeout=REFRESH_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise t212.T212Error("Trading 212 took too long; press sync again to continue") from None
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            raise t212.T212Error((msg[-1] if msg else "Sync failed")[:300])
        return None, None

    def sync_other(self):
        """The account from the broker .env names (broker.py), in its own process on the Mac."""
        if IN_PROCESS_SYNC:
            try:
                broker.sync_to_file(os.path.join(self.folder, "t212_data.json"))
            except broker.BrokerError:
                raise
            except Exception as e:
                raise broker.BrokerError(f"Sync failed: {e}"[:300]) from None
            return None, None
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "broker.py")], cwd=HERE,
                               capture_output=True, text=True, timeout=REFRESH_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise broker.BrokerError("The broker took too long; press sync again to continue") from None
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            raise broker.BrokerError((msg[-1] if msg else "Sync failed")[:300])
        return None, None

    def run_steps(self, steps, report, timed, since=None):
        """Run the steps, each reported as it starts and ends and timed into `timed`. A step
        returns (data, the file to write it to, or None): a whole store, or a Merge. Returns
        [(name, what went wrong)] for the sources that failed; the rest still run.

        A step given as (name, step, lane, after) runs side by side with the other lanes' (28 Sep
        2026: one source after another, an update took the sum of their waits on a slow connection):
        each lane's steps in their turn, each once the steps named in `after`, which come before
        it, have ended. A source's requests stay in one lane, one at a time, as its limits ask.
        Steps given as (name, step) run in their turn, as one lane. `since` is the update's
        Stores.begin(): every change made to a store since then is made again on what is written."""
        steps = [tuple(s) + ((None, ()) if len(s) == 2 else ()) for s in steps]
        place = {s[0]: i for i, s in enumerate(steps)}
        for i, (name, _, _, after) in enumerate(steps):
            if any(place.get(a, i) >= i for a in after):
                raise ValueError(f"{name} waits for a step that does not come before it")
        ended = {s[0]: threading.Event() for s in steps}
        failed, times = {}, {}
        # for a step that asks whether it is nearly the last (update_research); a plain set, read and changed
        # by C-level operations that the interpreter does not interrupt
        self.unfinished = left = {s[0] for s in steps}

        def run(i, name, step):
            report({"step": name, "state": "running"})
            started, state = time.monotonic(), "done"
            try:
                data, filename = step()
                partly = (data.partly if isinstance(data, Merge)
                          else data.pop(PARTLY, None) if isinstance(data, dict) else None)
                if filename:
                    STORES.write(os.path.join(self.folder, filename), data, since)
                if partly:                       # what was read is kept; the rest is reported
                    failed[i] = (name, scrub(partly))
                    state = "failed"
            except (news.NewsError, prices.PriceError, earnings.EarningsError, t212.T212Error, broker.BrokerError,
                    universe.UniverseError, sectors.SectorError, headlines.PressError,
                    paper.PaperError, news.CoverageError, UnreadableStore) as e:
                failed[i] = (name, scrub(e))                # never a key, on the page or in health.json
                state = "failed"
            except Exception:
                # a fault in the desk's own code fails this step alone: the other sources still
                # update, the page says which step it was, and server.log has the detail
                traceback.print_exc()
                failed[i] = (name, "an error in the desk itself; server.log has the detail")
                state = "failed"
            finally:
                times[i] = (name, time.monotonic() - started)
                left.discard(name)
                try:
                    report({"step": name, "state": state, "seconds": round(times[i][1], 1)})
                finally:
                    ended[name].set()

        lanes = {}
        for i, (name, step, lane, after) in enumerate(steps):
            lanes.setdefault(lane, []).append((i, name, step, after))

        def work(queue):
            for i, name, step, after in queue:
                for a in after:
                    ended[a].wait()
                run(i, name, step)
        if len(lanes) <= 1:
            for queue in lanes.values():
                work(queue)
        else:
            threads = [threading.Thread(target=work, args=(q,), daemon=True) for q in lanes.values()]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        timed.extend(times[i] for i in sorted(times))
        return [failed[i] for i in sorted(failed)]

    def show_partway(self, report):
        """The prices, or the filings, are in: the page is rebuilt now and says so, so that they are on it while
        the rest of the update (the slowest part, the news) is still being asked for. Not when only the desk's own
        last steps remain, which the update's own rebuild follows at once."""
        if not (self.unfinished - set(ON_THE_PAGE) - {"Ratings", "Research"}):
            return None, None
        self.build()
        report({"built": True})
        return None, None

    def update_research(self, report, timed):
        """Filings, news, prices, fundamentals, earnings, ratings and research. A source
        that fails is reported; the rest still update."""
        with journal_lock:
            try:
                news.date_undated(path=self.coverage_file())     # S-29, now without a reason asked
            except news.CoverageError:
                pass                                          # an unreadable list is left as it is
        watchlist = news.load_watchlist(os.path.join(self.folder, "watchlist.json"))
        # practice holdings still need prices even if they leave the watchlist, and the
        # research's fixed sample needs them whatever is followed (S-20)
        try:
            book = paper.load(os.path.join(self.folder, "paper.json"))
        except paper.PaperError:
            book = {}                                         # an unreadable book prices nothing
        # the US shares held are priced too, so each rating logged for one can be scored
        held = self.held_us_shares()
        priced = list(dict.fromkeys(watchlist + sorted(book.get("positions") or {}) + research.sample() + held))
        # the companies whose data is kept: those followed, and the ones held that are not, so a
        # holding not followed still has its filings, news and results dates.
        # A holding is covered without counting toward news.MAX_COVERAGE.
        also = self.held_companies(held, watchlist)
        covered = watchlist + also
        news_file, headlines_file = os.path.join(self.folder, "news_data.json"), os.path.join(self.folder, "headlines.json")
        # a company's news is asked again no sooner than headlines.ASK_AGAIN, unless the button was pressed
        again = None if self.pressed else headlines.ASK_AGAIN
        # A story counts when it names the company (headlines.about), by the name its filings give. The companies
        # whose filings have named them already are asked for their stories at once, beside the filings; those the
        # filings have not named yet (first time covered) once this update's filings have, as before (5 Oct 2026:
        # the news waited for the filings, the slowest chain of the update, for names it mostly had).
        filed = self.filed_names()
        named = [t for t in covered if filed.get(t)]
        new = [t for t in covered if t not in named]
        late = (("News (companies new to the desk)", lambda: (headlines.update(
                    covered, stored=build_desk.load_json(headlines_file, {}), names=self.filed_names(), skip_within=again,
                    ask=new), "headlines.json"), "finnhub", ("Filings", "News from the FT and the press")),
                ("News from the FT and the press (companies new to the desk)", lambda: (headlines.update_press(
                    covered, stored=build_desk.load_json(headlines_file, {}), names=self.filed_names(), skip_within=again,
                    ask=new), "headlines.json"), "press", ("News (companies new to the desk)",))) if new else ()
        show = lambda: self.show_partway(report)
        # each source in its own lane, one request at a time as its limits ask, the lanes side by
        # side; a step reading what an earlier one writes waits for it (run_steps)
        steps = (
            # the SEC: filings first, then the figures they tell of, then the rest
            ("Filings", lambda: (dict(news.refresh(covered, insiders=(build_desk.load_json(news_file, {}).get("insiders") or {}),
                                                   stored=build_desk.load_json(news_file, {})), held=also),
                                 "news_data.json"), "sec", ()),
            ("Financials", lambda: (fundamentals.update(
                covered, stored=build_desk.load_json(os.path.join(self.folder, "fundamentals.json"), {}),
                filings=build_desk.load_json(news_file, {}).get("items")), "fundamentals.json"), "sec", ()),
            ("Annual report wording", lambda: (diffs.update(
                covered, (build_desk.load_json(news_file, {}).get("items")), news.user_agent(), news.fetch_text,
                stored=build_desk.load_json(os.path.join(self.folder, "diffs.json"), {})), "diffs.json"), "sec", ()),
            # which exchange each company trades on: the rating's breakpoints (once a day); the
            # rating's universe of SEC filers, rebuilt monthly (universe.due), and the industry
            # codes, built when missing: on the Mac, never on a phone; and the rating's fixed
            # sample, drawn from its NYSE companies the first time only
            ("Stock exchanges", lambda: (universe.update_listings(universe.load_listings()), "listings.json"), "sec", ()),
            ("Industry codes", lambda: (None if ON_PHONE else sectors.keep_up(), None), "sec", ()),
            ("Company universe", lambda: (None if ON_PHONE else universe.keep_up() and None, None), "sec", ()),
            ("Rating sample", lambda: (rating.keep_sample(self.folder, universe.load(), sectors.load(),
                                                          universe.load_listings()) and None, None), "sec", ()),
            # Tiingo: the closes, the latest prices, then the rating sample's closes, once it is drawn
            ("Prices", lambda: (prices.update(priced, stored=prices.load(self.prices_file()), currency=self.account_currency(),
                                              slow=self.sold_lately(), traded=self.traded_us_shares(book)),
                                "prices.json"), "tiingo", ()),
            ("Latest prices", lambda: (prices.fetch_latest(covered), "quotes.json"), "tiingo", ()),
            ("Rating sample prices", lambda: (prices.update([], stored=prices.load(self.prices_file()), cash=None, fx=None,
                                                            slow=rating.load_sample(self.folder).get("tickers") or []),
                                              "prices.json"), "tiingo", ("Rating sample",)),
            # Finnhub: results dates, analysts' ratings, and what was written about each company
            # since the last update; the FT and the press (Google News) in a lane of their own,
            # once Finnhub's stories are written, since both write the one store of stories
            ("Earnings", lambda: (earnings.update(
                covered, stored=build_desk.load_json(os.path.join(self.folder, "earnings_data.json"), {})),
                "earnings_data.json"), "finnhub", ()),
            ("Analyst ratings", lambda: (analysts.update(covered, stored=build_desk.load_json(
                os.path.join(self.folder, "analysts_data.json"), {})), "analysts_data.json"), "finnhub", ()),
            ("News", lambda: (headlines.update(covered, stored=build_desk.load_json(headlines_file, {}),
                                               names=self.filed_names(), skip_within=again, ask=named), "headlines.json"),
             "finnhub", ()),
            ("News from the FT and the press", lambda: (headlines.update_press(covered, stored=build_desk.load_json(
                headlines_file, {}), names=self.filed_names(), skip_within=again, ask=named), "headlines.json"),
             "press", ("News",)),
            *late,
            # each shown as soon as it is in, while the lanes still asking go on (5 Oct 2026, the owner: "update
            # companies and refresh the desk faster": the page waited for the slowest chain to end)
            (ON_THE_PAGE[0], show, "page: prices", ("Prices", "Latest prices")),
            (ON_THE_PAGE[1], show, "page: filings", ("Filings", "Financials")),
            # the desk's own work, once what it reads is in
            ("Ratings", self.log_ratings(watchlist + held), "desk",
             ("Prices", "Stock exchanges", "Industry codes", "Company universe", "Rating sample", "Rating sample prices")),
            ("Research", lambda: (research.update(
                news_items=(build_desk.load_json(news_file, {}).get("items")),
                stored=build_desk.load_json(os.path.join(self.folder, "research.json"), {})), "research.json"),
             "desk", ("Filings", "Prices")),
        )
        began = STORES.begin()
        try:
            return self.run_steps(steps, report, timed, since=began)
        finally:
            STORES.end(began)

    def log_ratings(self, tickers, with_sample=True):
        """A step logging each rating new or changed: for `tickers`, and the fixed sample's
        (rating.py) at the company update. Made on the log as it stands when written (a Merge),
        so a company followed during the update and the update itself each add their own."""
        def step():
            sample, stored = rating.load_sample(self.folder), prices.load(self.prices_file())
            ratings = rating.rate_all(universe.load(), sectors.load(), universe.load_listings(), stored, sample)
            names = list(tickers) + (list(sample.get("tickers") or []) if with_sample else [])
            today = datetime.now(timezone.utc).date()
            return Merge(lambda entries: rating.log(entries, ratings, names, stored, today, sample=sample),
                         load=rating.load_log_for_writing), "ratings_log.json"
        return step

    def fetch_company(self, ticker, report=lambda event: None):
        """One company, as soon as it is followed: its filings, news, annual report wording, prices,
        latest price, financials, results dates, analysts' ratings and the desk's rating,
        each merged into its store beside the other companies', whose own fetch times are
        kept, so the next refresh still fetches what is due for them. Pressed, not timed:
        it runs because a ticker was followed. Returns (status, result) like refresh.

        At once, never after a company update under way: each change is a Merge, which the update
        makes again on what it writes (Stores). The sources are asked side by side, its figures
        and price first, and the page is rebuilt as soon as they are in, before its news."""
        ticker = str(ticker or "").strip().upper()
        if ticker not in news.load_watchlist(self.coverage_file()):
            return 200, {"ok": False, "message": f"{ticker or 'That company'} is not one you follow."}
        if self.demo:
            self.build()
            return 200, {"ok": True, "message": "The demo account loads nothing new."}
        load = lambda name: build_desk.load_json(os.path.join(self.folder, name), {})

        def filings():
            fresh = news.refresh([ticker], insiders=load("news_data.json").get("insiders") or {})

            def apply(stored):
                followed = news.load_watchlist(self.coverage_file())
                held = [t for t in stored.get("held") or [] if t not in followed]
                # stopped following while it loaded: its filings are not put in
                mine = fresh["items"] if ticker in followed or ticker in held else []
                items = [i for i in stored.get("items") or [] if i.get("ticker") != ticker] + mine
                items.sort(key=lambda r: (r.get("filed_at") or "", r.get("ticker") or ""), reverse=True)
                return dict(stored, tickers=followed + held, held=held, items=items,
                            companies=dict(stored.get("companies") or {}, **fresh["companies"]),
                            read=dict(stored.get("read") or {}, **(fresh.get("read") or {})),
                            unknown=[t for t in stored.get("unknown") or [] if t != ticker] + fresh["unknown"],
                            insiders=dict(stored.get("insiders") or {}, **(fresh.get("insiders") or {})))
            return Merge(apply), "news_data.json"

        def merged(name, update):
            """A store of {companies: {ticker: ...}}: this company's entry put in, the others' and
            the store's own fetch time as they are."""
            def step():
                fresh = update(load(name))

                def apply(stored):
                    out = dict(stored, companies=dict(stored.get("companies") or {},
                                                      **{t: v for t, v in (fresh.get("companies") or {}).items() if t == ticker}))
                    if "unknown" in fresh:
                        out["unknown"] = sorted(set(stored.get("unknown") or []) - {ticker} | set(fresh["unknown"]))
                    out.setdefault("updated_at", fresh.get("updated_at"))     # the others' fetch time stands
                    return out
                return Merge(apply, partly=fresh.pop(PARTLY, None) if isinstance(fresh, dict) else None), name
            return step

        def stories(update):
            def step():
                fresh = update([ticker], stored=load("headlines.json"), prune=False, names=self.filed_names())
                return Merge(lambda stored: headlines.merge_company(stored, fresh, ticker),
                             partly=fresh.pop(PARTLY, None)), "headlines.json"
            return step

        def wording():
            fresh = diffs.update([ticker], load("news_data.json").get("items"), news.user_agent(), news.fetch_text,
                                 stored=load("diffs.json"), prune=False)
            return Merge(lambda stored: diffs.merge_company(stored, fresh, ticker)), "diffs.json"

        def closes():
            # a company just followed may use the requests the company update keeps spare
            fresh = prices.update([ticker], stored=prices.load(self.prices_file()), cash=None, fx=None, spare=0)
            return Merge(lambda stored: prices.merge_ticker(stored, fresh, ticker), load=prices.load,
                         partly=fresh.pop(PARTLY, None)), "prices.json"

        def latest():
            fresh = prices.fetch_latest([ticker])
            return Merge(lambda stored: dict(stored, quotes=dict(stored.get("quotes") or {}, **fresh["quotes"]),
                                             fetched_at=stored.get("fetched_at") or fresh["fetched_at"])), "quotes.json"

        def show():
            """Its figures and price are in: the page is rebuilt now, and says so."""
            self.build()
            report({"built": True})
            return None, None
        steps = (
            ("Financials", merged("fundamentals.json", lambda stored: fundamentals.update(
                [ticker], stored=stored, filings=load("news_data.json").get("items"))), "sec", ()),
            ("Filings", filings, "sec", ()),
            ("Annual report wording", wording, "sec", ()),
            ("Prices", closes, "tiingo", ()),
            ("Latest price", latest, "tiingo", ()),
            ("Earnings", merged("earnings_data.json", lambda stored: earnings.update([ticker], stored=stored)), "finnhub", ()),
            ("Analyst ratings", merged("analysts_data.json", lambda stored: analysts.update([ticker], stored=stored)),
             "finnhub", ()),
            # its stories once its filings have named it: a story counts when it names the company
            ("News", stories(headlines.update), "finnhub", ("Filings",)),
            ("News from the FT and the press", stories(headlines.update_press), "press", ("News",)),
            ("Its figures on the page", show, "desk", ("Financials", "Prices", "Latest price")),
            ("Rating", self.log_ratings([ticker], with_sample=False), "desk", ()),
        )
        failed = self.run_steps(steps, report, [])
        self.build()
        return 200, {"ok": True, "ticker": ticker,
                     "message": (f"{ticker} loaded, except " + self.failures(failed)[:1].lower() + self.failures(failed)[1:])
                     if failed else None}

    def save_note(self, body):
        oid = str(body.get("id") or "").strip()
        note = str(body.get("note") or "").strip()[:build_desk.MAX_JOURNAL_CHARS]
        # the day to look at the trade again: a plain YYYY-MM-DD day, or none
        look = str(body.get("look_again") or "").strip()
        look = look if len(look) == 10 and asof.dated(look) else None
        if not oid or len(oid) > 40:
            return 400, {"ok": False, "message": "missing trade id"}
        with journal_lock:
            path = os.path.join(self.folder, "journal.json")
            try:
                journal = read_for_writing(path, dict, {})
            except UnreadableStore as e:
                return 200, {"ok": False, "message": str(e)}
            if note or look:
                journal[oid] = {"note": note, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                if look:
                    journal[oid]["look_again"] = look
            else:
                journal.pop(oid, None)
            atomic_write_json(path, journal, indent=1)
            os.chmod(path, 0o600)
            self.build()
        return 200, {"ok": True}


    def filed_names(self):
        """{ticker: the name its filings give}, from this folder's filings store: which
        stories are about each company (headlines.about)."""
        return headlines.filed_names(os.path.join(self.folder, "news_data.json"))

    def account_currency(self):
        """The account's currency, from the last sync: an account in euros or pounds is
        compared with the S&P 500 through FRED's exchange rates."""
        raw = build_desk.load_json(os.path.join(self.folder, "t212_data.json"), {})
        return (raw.get("summary") or {}).get("currency")

    def traded_us_shares(self, book=None):
        """{short ticker: the first day it was traded}, for each US share traded in the account
        or the practice book: each is priced whole once, so a split while it was held is known
        (prices.update's `traded`)."""
        raw = build_desk.load_json(os.path.join(self.folder, "t212_data.json"), {})
        first = {}
        for item in raw.get("orders") or []:
            order, fill = item.get("order") or {}, item.get("fill") or {}
            code = order.get("ticker") or ((order.get("instrument") or {}).get("ticker")) or ""
            day = build_desk.day_of(fill.get("filledAt") or order.get("createdAt"))
            if code.endswith("_US_EQ") and day:
                ticker = build_desk.short_ticker(code)
                first[ticker] = min(first.get(ticker, day), day)
        for t in (book or {}).get("trades") or []:
            if t.get("ticker") and t.get("date"):
                first[t["ticker"]] = min(first.get(t["ticker"], t["date"]), t["date"])
        return first

    def held_companies(self, held, followed):
        """The US shares held and not followed that are companies in the SEC's universe of
        filers: a fund (QQQ, VOO) files no company accounts, and its card would be blank.
        With no universe stored, every one held."""
        store = universe.load()
        companies = store.get("companies") or {}
        return [t for t in dict.fromkeys(held) if t not in followed and (not companies or t in companies)]

    def covered(self):
        """Every company the desk keeps data for: those followed, then those held (news_data's
        `held`, set by the last company update)."""
        followed = news.load_watchlist(self.coverage_file())
        also = build_desk.load_json(os.path.join(self.folder, "news_data.json"), {}).get("held") or []
        return followed + [t for t in also if t not in followed]

    def sold_lately(self):
        """The US shares sold in the last habits.AFTER_DAYS trading days and a margin: still
        priced, monthly, so the year after each sale can be measured (habits.replaced)."""
        raw = build_desk.load_json(os.path.join(self.folder, "t212_data.json"), {})
        since = (datetime.now(timezone.utc).date() - timedelta(days=400)).isoformat()
        out = []
        for item in raw.get("orders") or []:
            order, fill = item.get("order") or {}, item.get("fill") or {}
            code = order.get("ticker") or ((order.get("instrument") or {}).get("ticker")) or ""
            day = build_desk.day_of(fill.get("filledAt") or order.get("createdAt"))
            if code.endswith("_US_EQ") and day >= since and (order.get("side") == "SELL" or (fill.get("quantity") or 0) < 0):
                out.append(build_desk.short_ticker(code))
        return list(dict.fromkeys(out))

    def held_us_shares(self):
        """The short tickers of the US shares in the account, from the last sync."""
        raw = build_desk.load_json(os.path.join(self.folder, "t212_data.json"), {})
        codes = [((p.get("instrument") or {}).get("ticker") or "") for p in raw.get("positions") or []]
        return [build_desk.short_ticker(c) for c in codes if c.endswith("_US_EQ")]

    def check_trade(self, body):
        """The facts about a trade before it is placed (trade_check.py). Reads only: nothing
        is written, proposed or sent."""
        ticker = str(body.get("ticker") or "").strip().upper()
        side = str(body.get("side") or "BUY").strip().upper()
        amount = _number(body.get("amount"))
        if not news.TICKER.match(ticker):
            return 200, {"ok": False, "message": "Type a ticker, like NVDA."}
        if side not in ("BUY", "SELL"):
            return 200, {"ok": False, "message": "Buy or sell?"}
        if not amount or amount <= 0:
            return 200, {"ok": False, "message": "Type the amount."}
        data = build_desk.load_json(os.path.join(self.folder, "desk_data.json"), {})
        card = next((c for c in data.get("companies") or [] if c.get("ticker") == ticker), None)
        store, codes, ratings, price, split = universe.load(), sectors.load(), None, None, 1.0
        if card is None:                       # not covered: placed from the universe, priced if the desk has it
            stored = prices.load(self.prices_file())
            ratings = rating.rate_all(store, codes, universe.load_listings(), stored, rating.load_sample(self.folder))
            closes = prices.series(stored, ticker, "c")
            price = closes[max(closes)] if closes else None
            row = ((store or {}).get("companies") or {}).get(ticker)
            if row and closes:
                split = value.splits_since(row, stored, ticker, max(closes), (store or {}).get("built"))
        return 200, {"ok": True, "check": trade_check.check(ticker, side, amount, data, card=card, ratings=ratings,
                                                             store=store, codes=codes, price=price, split=split)}

    def run_screen(self, body):
        """Which companies meet the conditions asked for. Reads only.

        Prices are not fetched here. A screen runs over every filer and pricing
        thousands of them would spend a month of the free Tiingo allowance on one
        button press; the Value column is a separate, deliberate step."""
        preset = str(body.get("preset") or "").strip()
        where = [w.strip() for w in str(body.get("where") or "").split(",") if w.strip()]
        try:
            # every match, sorted, so the page can re-sort all of them — not only the
            # first page of an alphabetical list
            codes = sectors.load()
            out = (screen.preset(preset, limit=None, codes=codes) if preset
                   else screen.run(where, limit=None, codes=codes))
        except screen.ScreenError as e:
            return 200, {"ok": False, "message": str(e)}
        context.for_screen(out, codes)
        return 200, {"ok": True, "screen": out,
                     "presets": {k: {"name": v["name"], "source": v["source"],
                                     "where": v["where"], "omits": v["omits"]}
                                 for k, v in screen.PRESETS.items()},
                     "measures": sorted(screen.measures({}))}

    def paper_trade(self, body):
        """Practice trades only: pretend money, real prices, no broker involved."""
        with journal_lock:
            action = str(body.get("action") or "").strip().lower()
            try:
                if action == "reset":                  # a new book: the old one need not be readable
                    book = paper.reset()
                elif action in ("buy", "sell"):
                    book = paper.load(os.path.join(self.folder, "paper.json"))
                    # this folder's closes: a practice trade in the demo is priced from the demo
                    book = paper.trade(book, prices.load(self.prices_file()),
                                       body.get("ticker"), action.upper(),
                                       amount=_number(body.get("amount")),
                                       quantity=_number(body.get("quantity")),
                                       reason=body.get("reason"))
                else:
                    return 400, {"ok": False, "message": "action must be buy, sell or reset"}
            except paper.PaperError as e:
                return 200, {"ok": False, "message": str(e)}
            paper.save(book, os.path.join(self.folder, "paper.json"))
            self.build()
            fresh = build_desk.load_json(os.path.join(self.folder, "desk_data.json"), {})
        return 200, {"ok": True, "paper": fresh.get("paper")}

    def prices_file(self):
        """This folder's closes: the desk's own on the Mac, the demo's in the demo."""
        return os.path.join(self.folder, "prices.json")

    def coverage_file(self):
        """This folder's own coverage list. A folder whose filings were gathered before it
        had one starts from the tickers those filings are for — the companies its cards
        show — so neither a follow nor a thesis ever disagrees with the page (S-15)."""
        where = os.path.join(self.folder, "watchlist.json")
        if not os.path.exists(where):
            stored = build_desk.load_json(os.path.join(self.folder, "news_data.json"), {})
            news.save_watchlist([t for t in stored.get("tickers") or [] if t not in (stored.get("held") or [])],
                                path=where)
        return where

    def write_thesis(self, body):
        """Record one thesis, once, for a company the user covers. The rules are
        thesis.py's; this only carries them."""
        ticker = str(body.get("ticker") or "").strip().upper()[:8]
        with journal_lock:
            if ticker not in self.covered():
                return 400, {"ok": False, "message": f"{ticker or 'That company'} is not one you cover."}
            funds = build_desk.load_json(os.path.join(self.folder, "fundamentals.json"), {})
            dated = build_desk.load_json(os.path.join(self.folder, "earnings_data.json"), {})
            next_report = (((dated.get("companies") or {}).get(ticker) or {}).get("next") or {}).get("date")
            try:
                thesis.write(ticker, body, (funds.get("companies") or {}).get(ticker), next_report,
                             path=os.path.join(self.folder, "theses.json"),
                             filings=build_desk.load_json(os.path.join(self.folder, "news_data.json"), {}).get("items"))
            except thesis.ThesisError as e:
                return 200, {"ok": False, "message": str(e)}
            self.build()
            fresh = build_desk.load_json(os.path.join(self.folder, "desk_data.json"), {})
        return 200, {"ok": True, "theses": fresh.get("theses")}

    def write_plan(self, body):
        """Record one plan, once, before its trade. The rules are plans.py's; this only
        carries them. A plan sends nothing."""
        with journal_lock:
            try:
                plans.write(self.folder, body)
            except plans.PlanError as e:
                return 200, {"ok": False, "message": str(e)}
            self.build()
            fresh = build_desk.load_json(os.path.join(self.folder, "desk_data.json"), {})
        return 200, {"ok": True, "plans": fresh.get("plans")}

    def summary(self, body):
        """Write (or re-use) the plain-English read on one company."""
        ticker = str(body.get("ticker") or "").strip().upper()[:8]
        data = build_desk.load_json(os.path.join(self.folder, "desk_data.json"), {})
        card = next((c for c in data.get("companies") or [] if c.get("ticker") == ticker), None)
        if not card:
            return 400, {"ok": False, "message": "not on the watchlist"}
        # this folder's summaries: one written in the demo is the demo's, never the desk's
        path = os.path.join(self.folder, "summaries.json")
        store = summarise.load(path)
        if not body.get("refresh") and store.get(ticker):
            return 200, {"ok": True, "summary": store[ticker], "cached": True}
        try:
            store[ticker] = summarise.write_summary(card)
            summarise.save(store, path)
        except summarise.SummaryError as e:
            return 200, {"ok": False, "message": str(e)}
        return 200, {"ok": True, "summary": store[ticker]}

    def write_brief(self, body):
        """The week's news about one covered company in brief (brief.py): the kept one when it
        was written from the same stories, else a new one. Only the headlines the page shows
        are sent, never the account."""
        ticker = str(body.get("ticker") or "").strip().upper()[:8]
        data = build_desk.load_json(os.path.join(self.folder, "desk_data.json"), {})
        told = ((data.get("company_news") or {}).get("companies") or {}).get(ticker)
        card = next((c for c in data.get("companies") or [] if c.get("ticker") == ticker), None)
        if not card:
            return 400, {"ok": False, "message": "not a company the desk covers"}
        try:
            today = date.fromisoformat(data.get("today") or "")
        except ValueError:
            today = datetime.now(timezone.utc).date()
        days = brief.week(told, today)
        if not days:
            return 200, {"ok": False, "message": "No news about it this week."}
        kept = brief.load(self.folder).get(ticker)
        if not body.get("refresh") and kept and kept.get("stories") == brief.story_ids(days):
            return 200, {"ok": True, "brief": brief.for_page(kept, told, today), "cached": True}
        try:
            written = brief.write(ticker, card.get("name"), days, (data.get("company_news") or {}).get("level"))
        except summarise.SummaryError as e:
            return 200, {"ok": False, "message": str(e)}
        with briefs_lock:
            briefs = brief.load(self.folder)
            briefs[ticker] = written
            brief.save(self.folder, briefs)
        return 200, {"ok": True, "brief": brief.for_page(written, told, today)}

    def save_watchlist(self, body):
        """Follow one company (at the cap, naming the one it replaces), or stop following
        one. The rules are news.py's; this only carries them. The page
        then asks /fetch for the new company's data."""
        wanted = [k for k in ("follow", "unfollow") if isinstance(body.get(k), str) and body.get(k)]
        if len(wanted) != 1:
            return 400, {"ok": False, "message": "send follow or unfollow"}
        with journal_lock:
            where = self.coverage_file()
            try:
                if wanted[0] == "follow":
                    saved = news.follow(body["follow"], replaces=body.get("replaces") or None, path=where)
                else:
                    saved = news.unfollow(body["unfollow"], path=where)
            except news.CoverageError as e:
                return 200, {"ok": False, "message": str(e)}
            def cover(stored):
                """The filings store names what is covered now; a company no longer covered has
                its filings taken out. Made again by a company update under way (Stores)."""
                held = [t for t in stored.get("held") or [] if t not in saved]
                tickers = saved + held
                return dict(stored, held=held, tickers=tickers,
                            items=[i for i in stored.get("items") or [] if i.get("ticker") in tickers])
            stored = STORES.write(os.path.join(self.folder, "news_data.json"), Merge(cover))
            self.build()
            fresh = build_desk.load_json(os.path.join(self.folder, "desk_data.json"), {})
        return 200, {"ok": True, "news": fresh.get("news"),
                     "pending": any(t not in {i.get("ticker") for i in stored.get("items") or []} for t in saved)}


def _number(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def main(argv):
    if "--demo" in argv:
        Handler.folder, Handler.demo = os.path.join(HERE, "demo"), True
        build_desk.keep_apart(Handler.folder)
    load_env(os.path.join(HERE, ".env"))
    Handler.remote_hosts = desk_hosts()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Trading Desk on http://{HOST}:{PORT}/" + ("  (demo data)" if Handler.demo else ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
