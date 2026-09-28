"""The iPhone copy (phone.py, its bundle) and the Mac app."""
from support import *  # noqa: F401,F403


class PhoneTests(unittest.TestCase):
    """The desk on an iPhone, inside a-Shell (docs/IPHONE.md). No iPhone runs here, so
    what the phone lacks is taken away and the desk is shown to cope: no second process,
    no time-zone data, no certificate list — and its own data never overwritten."""

    def test_new_yorks_clock_without_time_zone_data(self):
        from zoneinfo import ZoneInfo
        ny, rule = ZoneInfo("America/New_York"), prices.USEastern()
        moment = datetime(2007, 1, 1, tzinfo=timezone.utc)
        while moment < datetime(2031, 1, 1, tzinfo=timezone.utc):
            self.assertEqual(moment.astimezone(rule).strftime("%Y-%m-%d %H:%M"),
                             moment.astimezone(ny).strftime("%Y-%m-%d %H:%M"), moment)
            moment += timedelta(minutes=173)            # every hour of the day, and each change
        real = prices.ZoneInfo

        def missing(name):
            raise LookupError(name)
        prices.ZoneInfo = missing
        try:
            self.assertIsInstance(prices._market_clock(), prices.USEastern)
        finally:
            prices.ZoneInfo = real
        # a quote at 09:00 New York time on a summer day and a winter one
        self.assertEqual(prices.session(datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc)), "Pre-market")
        self.assertEqual(datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc).astimezone(rule).strftime("%H:%M"), "09:00")

    def test_the_sync_runs_inside_the_server_on_a_phone(self):
        calls, real = [], (t212.sync_to_file, server.subprocess.run, server.IN_PROCESS_SYNC)

        def no_process(*a, **k):
            raise AssertionError("an iPhone app cannot start another program")
        t212.sync_to_file, server.subprocess.run, server.IN_PROCESS_SYNC = (lambda: calls.append(1)), no_process, True
        try:
            self.assertEqual(server.Handler.sync_account(None), (None, None))
            self.assertEqual(calls, [1])

            def broken():
                raise ValueError("t212_data.json is not JSON")
            t212.sync_to_file = broken
            with self.assertRaises(t212.T212Error) as caught:           # reported as the step's failure
                server.Handler.sync_account(None)
            self.assertIn("Sync failed: t212_data.json is not JSON", str(caught.exception))
        finally:
            t212.sync_to_file, server.subprocess.run, server.IN_PROCESS_SYNC = real
        self.assertIn("sync_to_file()", inspect.getsource(t212.main))       # one sync, two ways in
        self.assertFalse(server.IN_PROCESS_SYNC)                            # the Mac keeps its own process
        self.assertFalse(phone.Server.daemon_threads)                      # closing finishes a refresh

    def test_nothing_the_phone_runs_starts_a_process_or_needs_time_zone_data(self):
        """An iPhone app cannot start a program, and its Python may have no time-zone
        data. server.py's process is behind IN_PROCESS_SYNC, doctor.py asks git only off
        an iPhone, power.py is run by hand on the Mac (research reads its file inside a
        try), and scripts/ are the Mac's."""
        allowed = {"subprocess": {"server.py", "doctor.py"}, "multiprocessing": {"power.py"}, "ZoneInfo": {"prices.py"}}
        for name in sorted(os.listdir(ROOT)):
            if not name.endswith(".py"):
                continue
            source = read(os.path.join(ROOT, name))
            for word, owners in allowed.items():
                if re.search(r"^\s*(import|from)\s[^#\n]*\b" + word + r"\b", source, re.M):
                    self.assertIn(name, owners, f"{name} imports {word}")
        self.assertIn("except Exception", inspect.getsource(research._power))

    def test_an_update_replaces_code_and_never_the_phones_own_data(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "desk")
            os.makedirs(folder)
            for name, text in (("journal.json", "the phone's notes"), (".env", "phone keys"), ("phone.py", "old")):
                with open(os.path.join(folder, name), "w") as f:
                    f.write(text)
            bundle = os.path.join(root, "b.zip")
            with zipfile.ZipFile(bundle, "w") as z:
                z.writestr(phone.MANIFEST, json.dumps({"code": ["phone.py", "scripts/x.py", "../evil.py"],
                                                       "data": ["journal.json", ".env", "watchlist.json"]}))
                for name, text in (("phone.py", "new"), ("scripts/x.py", "x"), ("../evil.py", "no"),
                                   ("journal.json", "the Mac's notes"), (".env", "mac keys"), ("watchlist.json", "w"),
                                   ("unlisted.py", "not in the manifest")):
                    z.writestr(name, text)
            said = []
            got = phone.update(bundle, folder, log=said.append)
            read_back = lambda name: read(os.path.join(folder, name))
            self.assertEqual((read_back("phone.py"), read_back("scripts/x.py")), ("new", "x"))
            self.assertEqual((read_back("journal.json"), read_back(".env")), ("the phone's notes", "phone keys"))
            self.assertEqual(read_back("watchlist.json"), "w")                 # missing data is filled in
            self.assertFalse(os.path.exists(os.path.join(root, "evil.py")))    # nothing outside the folder
            self.assertFalse(os.path.exists(os.path.join(folder, "unlisted.py")))
            self.assertEqual(got, {"code": 2, "added": 1, "kept": 2})
            self.assertTrue(any("outside" in line for line in said))
            # the Files app unpacks a tapped zip into a folder: that is a bundle too
            unpacked = os.path.join(root, "TradingDesk-phone")
            with zipfile.ZipFile(bundle) as z:
                z.extractall(unpacked, [n for n in z.namelist() if not n.startswith("..")])
            with open(os.path.join(unpacked, "phone.py"), "w") as f:
                f.write("newer")
            os.remove(os.path.join(folder, "watchlist.json"))
            again = phone.update(unpacked, folder, log=said.append)
            self.assertEqual((read_back("phone.py"), read_back("journal.json")), ("newer", "the phone's notes"))
            self.assertEqual(again, {"code": 2, "added": 1, "kept": 2})
        # a bundle named from the folder a-Shell was in, not the desk's own
        seen, real = [], phone.update
        phone.update = lambda path, *a, **k: seen.append(path)
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as elsewhere:
                os.chdir(elsewhere)
                phone.main(["--update", "TradingDesk-phone.zip"])
                self.assertEqual(seen, [os.path.join(os.path.realpath(elsewhere), "TradingDesk-phone.zip")])
        finally:
            phone.update = real
            os.chdir(cwd)

    def test_https_finds_a_certificate_list_or_says_how_to_get_one(self):
        none = ssl.DefaultVerifyPaths(None, None, "", "", "", "")
        env = {}
        with tempfile.NamedTemporaryFile() as pem:
            self.assertIsNone(phone.certificates(env, none, lambda: pem.name))
            self.assertEqual(env["SSL_CERT_FILE"], pem.name)

        def absent():
            raise ImportError("certifi")
        self.assertIn("pip install certifi", phone.certificates({}, none, absent))
        with tempfile.NamedTemporaryFile() as bundle:                        # a Mac's own list: left alone
            env = {}
            self.assertIsNone(phone.certificates(env, ssl.DefaultVerifyPaths(bundle.name, None, "", "", "", ""), absent))
            self.assertEqual(env, {})

    def test_keys_are_asked_for_one_at_a_time_and_never_shown(self):
        """With no Mac to copy .env from, the phone asks for each key, and a key already there
        is kept on return; a setting of the user's own is kept."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, ".env")
            with open(path, "w") as f:
                f.write("TIINGO_API_KEY=old-tiingo\nMY_OWN=1\nEXECUTE_DRY_RUN=1\n")
            asked, said = [], []
            answers = {"T212_API_KEY": "k-123", "T212_API_SECRET": "s-456", "T212_ENV": "", "SEC_CONTACT": "me@x.org",
                       "TIINGO_API_KEY": "", "FINNHUB_API_KEY": "f-789", "OPENAI_API_KEY": ""}

            def ask(prompt):
                asked.append(prompt)
                return answers[prompt.split(" ")[0].rstrip(":")]
            phone.keys(os.path.join(ROOT, ".env.example"), path, ask=ask, ask_secret=ask, log=said.append)
            text = read(path)
            env = dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))
            self.assertEqual((env["T212_API_KEY"], env["T212_API_SECRET"], env["T212_ENV"]), ("k-123", "s-456", "live"))
            self.assertEqual((env["TIINGO_API_KEY"], env["FINNHUB_API_KEY"]), ("old-tiingo", "f-789"))
            self.assertFalse(any(p.startswith(("EXECUTE_", "DESK_HOSTS")) for p in asked))
            self.assertEqual(env["MY_OWN"], "1")                                     # nothing of theirs lost
            self.assertIn("TIINGO_API_KEY (set: return keeps it): ", asked)        # a key is never shown
            self.assertFalse(any("old-tiingo" in p or "k-123" in p for p in asked + said))
            self.assertFalse(any("#" in v for v in env.values()))                  # load_env keeps a trailing comment
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            saved = dict(os.environ)
            try:
                env_config.load_env(path)
                self.assertEqual(os.environ.get("EXECUTE_DRY_RUN"), "1")
            finally:
                os.environ.clear()
                os.environ.update(saved)

    def test_on_an_iphone_a_key_is_read_as_typed(self):
        """getpass waits on the terminal device, which a-Shell does not give it: the
        question sat there and took no typing. On an iPhone the key is read as typed."""
        hide = lambda prompt: self.fail("getpass must not be used on an iPhone")
        self.assertEqual(phone._hidden("K: ", iphone=True, hide=hide, show=lambda p: "typed"), "typed")
        self.assertEqual(phone._hidden("K: ", iphone=False, hide=lambda p: "hidden", show=input), "hidden")

        def no_terminal(prompt):
            raise OSError("no tty")
        self.assertEqual(phone._hidden("K: ", iphone=False, hide=no_terminal, show=lambda p: "typed"), "typed")

    def test_on_an_iphone_the_page_opens_inside_a_shell(self):
        seen = []
        phone.open_page("u", iphone=True, system=lambda c: seen.append(c) or 0, browser=seen.append)
        self.assertEqual(seen, ["internalbrowser u"])                      # a-Shell stays on screen
        seen.clear()
        phone.open_page("u", iphone=True, system=lambda c: seen.append(c) or 1, browser=seen.append)
        self.assertEqual(seen, ["internalbrowser u", "u"])                 # Python's webbrowser, a-Shell's other way
        seen.clear()
        phone.open_page("u", iphone=False, system=seen.append, browser=seen.append)
        self.assertEqual(seen, ["u"])

    def test_the_bundle_carries_the_desks_files_and_nothing_rebuilt(self):
        listing = {("ls-files",): "phone.py\nnative_app/main.swift\ntests/test_account.py\n",
                   ("ls-files", "--others", "--ignored", "--exclude-standard"):
                       ".env\njournal.json\nindex.html\ndesk_data.json\nserver.log\nprices.json.tmp\n"
                       "demo/t212_data.json\n__pycache__/x.pyc\nTradingDesk-phone.zip\nuniverse.json\n"}
        real = phone_bundle._git
        phone_bundle._git = lambda *args: listing[args]
        try:
            self.assertEqual(phone_bundle.code_files(), ["phone.py", "tests/test_account.py"])
            self.assertEqual(phone_bundle.data_files(), [".env", "journal.json", "universe.json"])
            self.assertEqual(phone_bundle.data_files(keys=False), ["journal.json", "universe.json"])
        finally:
            phone_bundle._git = real
        for name in ("TradingDesk-phone.zip", "PHONE_BUNDLE.json"):
            self.assertIn(name, read(os.path.join(ROOT, ".gitignore")))


class NativeAppTests(unittest.TestCase):
    """Trading Desk.app (native_app/): a window onto the same local server. Swift cannot
    import server.py, so the port it types in is a second copy; this keeps it the same."""

    def read(self, name):
        with open(os.path.join(ROOT, name)) as f:
            return f.read()

    def test_the_app_and_desk_sh_use_the_servers_port(self):
        swift, desk = self.read("native_app/main.swift"), self.read("desk.sh")
        self.assertIn(f"let port = {server.PORT}\n", swift)
        self.assertIn(f"PORT={server.PORT}\n", desk)
        self.assertEqual(server.HOST, "127.0.0.1")
        self.assertIn('"http://127.0.0.1:\\(port)/"', swift)

    def test_the_app_can_reach_the_server_and_names_no_one(self):
        """macOS refuses plain http to 127.0.0.1 without NSAllowsLocalNetworking (a
        lesson from another app). The desk is found from the user's home, not a typed path."""
        self.assertIn("<key>NSAllowsLocalNetworking</key>", self.read("native_app/build.sh"))
        swift = self.read("native_app/main.swift")
        self.assertIn('NSHomeDirectory() + "/trading-desk"', swift)
        self.assertNotIn("/Users/", swift)
        self.assertIn("server.terminate()", swift)                    # nothing left on the port
        self.assertIn("runJavaScriptConfirmPanelWithMessage", swift)  # confirm() is not "no"

    def test_the_page_is_rebuilt_from_the_code_on_every_start(self):
        """The user pulled the light redesign and still saw the dark page: desk.sh and
        the app built index.html only when it was missing, so the page built before the
        pull was served on. Both now build it on every start; a failed build still
        leaves the last page served."""
        app, desk = self.read("native_app/main.swift"), self.read("desk.sh")
        self.assertIn("python3 build_desk.py >> server.log 2>&1 || true; } ", app)
        self.assertIn("\n  python3 build_desk.py >/dev/null\n", desk)
        for source in (app, desk):
            self.assertNotIn("[ -f index.html ] ||", source)

    def test_new_code_comes_in_on_every_start_and_never_over_a_local_edit(self):
        """Off unless .env says AUTO_UPDATE=1. Then update.sh runs before the page is built,
        from the app and from desk.sh; it only fast-forwards main, and a download that stalls
        gives up and the desk opens on the code it has."""
        app, desk = self.read("native_app/main.swift"), self.read("desk.sh")
        self.assertLess(app.index("./update.sh >> server.log 2>&1 || true; }"), app.index("python3 build_desk.py"))
        self.assertLess(desk.index("./update.sh >> server.log 2>&1"), desk.index("python3 build_desk.py"))
        self.assertIn("self.tries < 240", app)                 # a minute: an update may take 20 s
        with tempfile.TemporaryDirectory() as root:
            git = lambda where, *a: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
                                                   cwd=where, capture_output=True, text=True)
            origin, dev, mac = (os.path.join(root, n) for n in ("origin.git", "dev", "mac"))
            git(root, "init", "-q", "--bare", origin)
            git(root, "init", "-q", "-b", "main", dev)
            shutil.copy(os.path.join(ROOT, "update.sh"), dev)
            with open(os.path.join(dev, "file.txt"), "w") as f:
                f.write("v1")
            git(dev, "add", "-A"); git(dev, "commit", "-qm", "v1")
            git(dev, "remote", "add", "origin", origin); git(dev, "push", "-q", "origin", "main")
            git(root, "clone", "-q", "-b", "main", origin, mac)
            run = lambda: subprocess.run(["bash", os.path.join(mac, "update.sh")], capture_output=True, text=True,
                                         env=dict(os.environ, UPDATE_WAIT="5")).stdout
            self.assertIn("off (AUTO_UPDATE=1 in .env turns it on)", run())
            with open(os.path.join(mac, ".env"), "w") as f:
                f.write("AUTO_UPDATE=1\n")
            self.assertIn("up to date", run())
            with open(os.path.join(dev, "file.txt"), "w") as f:
                f.write("v2")
            git(dev, "commit", "-qam", "v2"); git(dev, "push", "-q", "origin", "main")
            self.assertIn("updated to", run())
            self.assertEqual(read(os.path.join(mac, "file.txt")), "v2")
            with open(os.path.join(dev, "file.txt"), "w") as f:
                f.write("v3")
            git(dev, "commit", "-qam", "v3"); git(dev, "push", "-q", "origin", "main")
            with open(os.path.join(mac, "file.txt"), "w") as f:
                f.write("mine")
            self.assertIn("a local edit is in the way", run())
            self.assertEqual(read(os.path.join(mac, "file.txt")), "mine")          # never overwritten
            git(mac, "checkout", "-q", "file.txt")
            git(mac, "checkout", "-q", "-b", "other")
            self.assertIn("not on main", run())

    def test_the_icon_is_drawn_from_its_one_source(self):
        """icon.html says build.sh --icon draws AppIcon.icns from it. That step exists,
        draws that page, and refuses a drawing that would put the icon on a square."""
        self.assertIn("build.sh --icon", self.read("native_app/icon.html"))
        build = self.read("native_app/build.sh")
        self.assertIn("--icon) ICON=1", build)
        self.assertIn('build/render_icon "$(pwd)/icon.html"', build)
        self.assertIn("iconutil -c icns", build)
        self.assertLess(build.index("iconutil -c icns"), build.index('cp AppIcon.icns'))  # the app gets the new one
        render = self.read("native_app/render_icon.swift")
        self.assertIn("the corner is not clear", render)
        self.assertNotIn("/Users/", render)


if __name__ == "__main__":
    unittest.main()
