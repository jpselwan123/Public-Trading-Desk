"""What every test file shares: the project on the path, its modules, and the helpers.
No network, no keys. Run: python3 -m unittest discover -s tests -t tests"""
import ast, contextlib, inspect, io, json, os, random, re, shutil, socket, ssl, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.parse, urllib.request, zipfile
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import prices as prices_module  # noqa: E402
import analysts, asof, t212, backtest, brief, bridge, build_desk, charts, chat, context, diffs, doctor, earnings, env_config, forecasts, fundamentals, habits, headlines, health, looks, news, plans, paper, phone, prices, rating, research, scores, screen, sectors, server, summarise, thesis, trade_check, uncertainty, universe, value, generate_demo_data  # noqa: E402
import phone_bundle  # noqa: E402


class NetworkInATest(BaseException):
    """Raised, past every `except Exception`, when a test reaches for a host outside this machine."""


def _keep_the_suite_off_the_network():
    """Three tests once asked the real SEC for a Form 4 (they gave the refresh a fake feed but not a fake text
    fetch) and passed whether it answered or not. A connection to anything but this machine now fails the
    test that made it, or the run: a tunnel through a proxy is judged by the host it is asked to reach."""
    import http.client
    connect = http.client.HTTPConnection.connect

    def guarded(self):
        host = getattr(self, "_tunnel_host", None) or self.host
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise NetworkInATest(f"a test asked the network for {host}: give it a stand-in")
        return connect(self)
    http.client.HTTPConnection.connect = guarded


_keep_the_suite_off_the_network()


def read(path):
    with open(path) as f:
        return f.read()


def page_source():
    """The page's whole source: desk_template.html's markup with page/'s styles and script."""
    return build_desk.template_source()


TODAY = date(2026, 9, 19)


class FakeResponse(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(json.dumps(body).encode())
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def run_javascript(program):
    """Run a JavaScript program and return what it prints. GitHub's Ubuntu runners
    have Node; a Mac has JavaScriptCore. A machine with neither fails these tests
    rather than skipping them (K-06): the suite said "OK" with the same count either
    way, so a green run meant different things on different machines."""
    import shutil, subprocess
    if shutil.which("node"):
        engine = ["node", "-e", program]
    elif sys.platform == "darwin" and shutil.which("osascript"):
        engine = ["osascript", "-l", "JavaScript", "-e", program]
    else:
        raise AssertionError("no JavaScript engine on this machine: the page's own code is tested "
                             "in one. Install Node (or run on a Mac); a skip is not a pass.")
    done = subprocess.run(engine, capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr)
    return done.stdout.strip()


def template_function(name, template=None):
    """The source of one function in the page (page_source), to the closing brace at the
    start of a line."""
    template = template or page_source()
    start = template.index(f"function {name}(")
    return template[start:template.index("\n}\n", start) + 2]
