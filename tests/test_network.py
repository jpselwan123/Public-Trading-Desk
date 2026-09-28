"""What the desk connects to (docs/NETWORK.md) is everything it connects to, and its page loads
nothing from the internet. A reader deciding whether to trust the desk with a brokerage account
relies on both, so a contribution that adds a destination must document it."""
from support import *  # noqa: F401,F403
import re

# Not destinations: an XML namespace, a property-list schema, this computer.
NOT_A_DESTINATION = {"127.0.0.1", "localhost", "www.w3.org", "www.apple.com"}
CODE = (".py", ".js", ".html", ".css", ".sh", ".swift")


def source_files():
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("tests", ".git", "__pycache__", "demo", "build")]
        for name in names:
            if name.endswith(CODE):
                yield os.path.join(folder, name)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class NetworkTests(unittest.TestCase):
    def test_every_host_in_the_code_is_in_the_list_of_what_the_desk_connects_to(self):
        doc = read(os.path.join(ROOT, "docs", "NETWORK.md"))
        found = {}
        for path in source_files():
            for host in re.findall(r"https?://([A-Za-z0-9][A-Za-z0-9.-]*)", read(path)):
                if host not in NOT_A_DESTINATION:
                    found.setdefault(host, os.path.relpath(path, ROOT))
        self.assertTrue({"data.sec.gov", "api.tiingo.com", "api.alpaca.markets"} <= set(found), found)
        for host, where in sorted(found.items()):
            self.assertIn("`" + host + "`", doc, f"{host} (in {where}) is not listed in docs/NETWORK.md")

    def test_the_page_loads_nothing_from_the_internet(self):
        """No stylesheet, script, font, image or frame is fetched from anywhere but the desk's own server."""
        files = [os.path.join(ROOT, "desk_template.html"), os.path.join(ROOT, "page", "desk.css")]
        files += [os.path.join(ROOT, "page", n) for n in sorted(os.listdir(os.path.join(ROOT, "page"))) if n.endswith(".js")]
        loads = (r"<(?:link|script|img|iframe|source|video|audio|embed|object)\b[^>]*\b(?:src|href|data)\s*=\s*[\"']?https?:",
                 r"@import", r"url\(\s*[\"']?https?:", r"\bfetch\(\s*[\"'`]https?:", r"\bXMLHttpRequest\b",
                 r"new\s+(?:Image|WebSocket|EventSource)\(", r"\bimport\(\s*[\"']https?:", r"sendBeacon")
        for path in files:
            text = read(path)
            for pattern in loads:
                self.assertIsNone(re.search(pattern, text), f"{os.path.relpath(path, ROOT)} matches {pattern}")

    def test_the_code_reaches_the_network_only_through_urllib(self):
        """One way to read: nothing to look for but urllib, and no library that could phone home."""
        never = re.compile(r"^\s*(?:import|from)\s+(?:requests|httpx|aiohttp|urllib3|websockets?|smtplib|ftplib|telnetlib)\b", re.M)
        for path in source_files():
            if path.endswith(".py"):
                self.assertIsNone(never.search(read(path)), os.path.relpath(path, ROOT))


if __name__ == "__main__":
    unittest.main()
