"""Run the Trading Desk on an iPhone, inside the free a-Shell app.

An iPhone pauses any app that is not on screen, so a server left running in a terminal
stops the moment Safari comes to the front. Here the desk runs inside a-Shell and shows
itself in a-Shell's own browser: the app serving the page is the app on screen. Refresh,
notes, coverage and the rest work as on the Mac, and the broker is reached from the
phone itself. Step by step: docs/IPHONE.md.

    python3 phone.py                 open the desk (your account)
    python3 phone.py --demo          the synthetic demo account
    python3 phone.py --update ZIP    new code from a bundle (the zip, or the folder Files
                                     unpacks it into); your notes, logs,
                                     theses, orders and keys on the phone are never replaced
    python3 phone.py --keys          type your API keys into the phone's .env, one question
                                     at a time (return keeps what is there)
    python3 phone.py --no-browser    serve only, for trying it on a computer

Nothing here sends anything on its own: the page and its buttons are the Mac's, and the
desk never places an order.
"""
import getpass, json, os, re, ssl, sys, threading, time, webbrowser, zipfile
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = "PHONE_BUNDLE.json"      # inside a bundle: which entries are code and which data
# os.system's answer came this long after the page opened: it waited for the page to be
# closed, so the desk closes with it. Sooner means the call only opened it.
WAITED_FOR_CLOSE = 3.0


def on_iphone():
    """An iPhone or iPad: its kernel names the hardware model (iPhone14,2)."""
    try:
        return os.uname().machine.startswith(("iPhone", "iPad", "iPod"))
    except (AttributeError, OSError):
        return False


def certificates(environ=None, verify_paths=None, find_certifi=None):
    """HTTPS needs a list of the authorities that sign websites' certificates. A Mac has
    one; Python on a phone may not, and then every source fails with "certificate
    verify failed". Returns None when there is one (or one was found), else what to do."""
    environ = os.environ if environ is None else environ
    paths = verify_paths or ssl.get_default_verify_paths()
    if (paths.cafile and os.path.exists(paths.cafile)) or (paths.capath and os.path.isdir(paths.capath)
                                                           and os.listdir(paths.capath)):
        return None
    try:
        where = (find_certifi or _certifi)()
    except ImportError:
        where = None
    if where and os.path.exists(where):
        environ["SSL_CERT_FILE"] = where        # read by every HTTPS request that follows
        return None
    return ("This Python has no list of certificate authorities, so HTTPS will fail. "
            "Type: pip install certifi   then start the desk again.")


def _certifi():
    import certifi
    return certifi.where()


def open_page(url, iphone=None, system=os.system, browser=webbrowser.open, clock=time.monotonic):
    """Show the desk. On an iPhone, in a-Shell's own browser (`internalbrowser`), so a-Shell
    stays on screen and keeps serving; Python's webbrowser is a-Shell's second way in.
    Returns how long the call took: a long one waited for the page to be closed."""
    started = clock()
    if iphone if iphone is not None else on_iphone():
        if system("internalbrowser " + url) != 0:
            browser(url)
    else:
        browser(url)
    return clock() - started


SETTING = re.compile(r"^([A-Z][A-Z0-9_]*)=(\S*)\s*(#.*)?$")
# the order settings keep .env.example's safe values, set by hand; DESK_HOSTS is the Mac's
ASKED_NOT = ("DESK_HOSTS",)


def _hidden(prompt, iphone=None, hide=getpass.getpass, show=input):
    """A key typed without showing it — except on an iPhone. getpass reads the terminal
    device itself, and a-Shell's terminal is not one: the question appeared and no typing
    ever reached it (the user, 26 Sep 2026). There the key shows as it is typed."""
    if iphone if iphone is not None else on_iphone():
        return show(prompt)
    try:
        return hide(prompt)
    except Exception:                                # no terminal to hide it on
        return show(prompt)


def keys(template=None, path=None, ask=input, ask_secret=_hidden, log=print):
    """Write .env from .env.example, asking for each key in turn — for a phone with no
    Mac to copy .env from. .env.example's own comments say where each key comes from,
    so they are shown as the questions come. Return keeps what .env already has (or the
    example's value); a key already saved is never shown. The order settings are not asked: they keep
    the example's values, dry run on and nothing tradeable, until changed by hand."""
    template = template or os.path.join(HERE, ".env.example")
    path = path or os.path.join(HERE, ".env")
    have, extra = {}, []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                m = SETTING.match(line.strip())
                if m:
                    have[m.group(1)] = m.group(2)
    out, named = [], set()
    with open(template) as f:
        for line in f:
            line = line.rstrip("\n")
            m = SETTING.match(line.strip())
            if not m:
                out.append(line)
                if line.startswith("#") and not line.startswith(("# Copy", "# OPENAI_MODEL")):
                    log(line.lstrip("# "))
                continue
            name, default, note = m.group(1), m.group(2), m.group(3)
            named.add(name)
            value = have.get(name, default)
            if not name.startswith(ASKED_NOT):
                secret = name.endswith(("_KEY", "_SECRET"))
                hint = " (set: return keeps it)" if secret and value else (f" [{value}]" if value else "")
                answer = (ask_secret if secret else ask)(f"{name}{hint}: ").strip()
                value = answer or value
            if note:                                  # a comment on its own line: the file's reader
                out.append(note)                      # does not strip one after a value
            out.append(f"{name}={value}")
    extra = [f"{k}={v}" for k, v in have.items() if k not in named]
    text = "\n".join(out + (["", "# kept from the earlier .env"] + extra if extra else [])) + "\n"
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.chmod(path + ".tmp", 0o600)
    os.replace(path + ".tmp", path)
    log(f"Saved {path}. Start the desk with: python3 phone.py")
    return path


class Server(ThreadingHTTPServer):
    # a refresh or an order under way is finished, not cut off, when the desk closes
    daemon_threads = False


def _open_bundle(bundle):
    """A bundle's manifest, and a way to read each file in it: from the zip itself, or from
    the folder the Files app makes of the zip when it is tapped."""
    if os.path.isdir(bundle):
        path = os.path.join(bundle, MANIFEST)
        if not os.path.isfile(path):
            raise SystemExit(f"{bundle} is not a desk bundle: it has no {MANIFEST}")
        with open(path) as f:
            manifest = json.load(f)

        def read(name):
            source = os.path.join(bundle, name)
            if not os.path.isfile(source):
                return None
            with open(source, "rb") as f:
                return f.read()
        return manifest, read
    with zipfile.ZipFile(bundle) as z:
        try:
            manifest = json.loads(z.read(MANIFEST))
        except KeyError:
            raise SystemExit(f"{bundle} is not a desk bundle: it has no {MANIFEST}")
        files = {name: z.read(name) for name in z.namelist() if not name.endswith("/")}
    return manifest, files.get


def update(bundle, folder=HERE, log=print):
    """Unpack a bundle made on the Mac (scripts/phone_bundle.py) into the desk's folder.
    Code always replaces what is here. Data only fills what is missing: the phone's own
    notes, ratings log, theses, orders and keys are never overwritten by the Mac's. Only
    what the bundle's manifest names is taken, and nothing outside the desk's folder."""
    manifest, read = _open_bundle(bundle)
    data = set(manifest.get("data") or [])
    replaced = kept = added = 0
    for name in list(manifest.get("code") or []) + sorted(data):
        target = os.path.realpath(os.path.join(folder, name))
        if not target.startswith(os.path.realpath(folder) + os.sep):
            log(f"skipped {name}: outside the desk's folder")
            continue
        if name in data and os.path.exists(target):
            kept += 1
            continue
        content = read(name)
        if content is None:
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target + ".tmp", "wb") as out:
            out.write(content)
        os.replace(target + ".tmp", target)
        if name in data:
            os.chmod(target, 0o600)
            added += 1
        else:
            replaced += 1
    # which code this is, for doctor.py: a phone has no git to ask
    with open(os.path.join(folder, MANIFEST), "w") as f:
        json.dump({"commit": manifest.get("commit"), "made_at": manifest.get("made_at")}, f)
    log(f"Updated {replaced} code files; added {added} data files; kept {kept} of your own unchanged.")
    return {"code": replaced, "added": added, "kept": kept}


def main(argv):
    # a bundle named from the folder a-Shell is in (pickFolder's), before moving to the desk's
    where = {i: os.path.abspath(os.path.expanduser(a)) for i, a in enumerate(argv) if i and argv[i - 1] == "--update"}
    os.chdir(HERE)
    if "--keys" in argv:
        keys()
        return 0
    if "--update" in argv:
        i = argv.index("--update")
        if i + 1 >= len(argv):
            print("Usage: python3 phone.py --update path/to/TradingDesk-phone.zip")
            return 2
        update(where[i + 1])
        print("Done. Start the desk with: python3 phone.py")
        return 0
    problem = certificates()
    if problem:
        print(problem)
    sys.path.insert(0, HERE)
    import build_desk, server
    server.IN_PROCESS_SYNC = server.ON_PHONE = True
    demo = "--demo" in argv
    if demo:
        import runpy
        saved, sys.argv = sys.argv, ["generate_demo_data.py"]
        try:
            runpy.run_path(os.path.join(HERE, "scripts", "generate_demo_data.py"), run_name="__main__")
        finally:
            sys.argv = saved
        server.Handler.folder, server.Handler.demo = os.path.join(HERE, "demo"), True
    else:
        server.Handler.folder, server.Handler.demo = HERE, False
    # always rebuilt, as desk.sh does: new code may have arrived since the page was built
    build_desk.main([server.Handler.folder])
    url = f"http://{server.HOST}:{server.PORT}/"
    try:
        httpd = Server((server.HOST, server.PORT), server.Handler)
    except OSError:
        print("The desk is already running in another a-Shell window; opening it.")
        if "--no-browser" not in argv:
            open_page(url)
        return 0
    print(f"Trading Desk on {url}" + ("  (demo data)" if demo else ""))
    print("Keep a-Shell on screen while the desk updates or syncs: the iPhone pauses it otherwise.")
    print("To stop: close the page, or press ctrl-C here.")

    def show():
        if open_page(url) > WAITED_FOR_CLOSE:        # the page has been closed
            print("Page closed; finishing anything under way, then stopping.")
            httpd.shutdown()
    if "--no-browser" not in argv:
        threading.Thread(target=show, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()                          # waits for a refresh or an order to finish
    print("The desk is closed. Open it again with: python3 phone.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
