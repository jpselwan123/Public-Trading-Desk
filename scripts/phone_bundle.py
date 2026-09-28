"""Pack the desk into one file for the iPhone (docs/IPHONE.md): run on the Mac, send the
file by AirDrop, and phone.py unpacks it.

    python3 scripts/phone_bundle.py            the code, your data and your keys: the first time
    python3 scripts/phone_bundle.py --code     the code alone: every time after
    python3 scripts/phone_bundle.py --no-keys  without .env (put the keys on the phone yourself)

The first bundle carries your account data, notes, logs and .env, so send it by AirDrop
only — not by email, messages or a cloud drive — and delete it from the phone's
Downloads once unpacked. On the phone, `phone.py --update` never replaces a data file
the phone already has, so its own notes and logs stay its own.
"""
import json, os, subprocess, sys, zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import phone  # noqa: E402

NAME = "TradingDesk-phone.zip"
# rebuilt on the phone, or the Mac's alone: never sent
NOT_SENT = {"index.html", "desk_data.json", "server.log", "CLAUDE.local.md", NAME, ".DS_Store", phone.MANIFEST,
            "health.json", "looks.json"}
MAC_ONLY = ("native_app/",)          # the Mac app


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def code_files():
    """Every file the repository tracks, the Mac app aside."""
    return [p for p in _git("ls-files").splitlines() if p and not p.startswith(MAC_ONLY)]


def data_files(keys=True):
    """The desk's own files in its folder that git ignores: the account, notes, logs,
    stores and (unless keys=False) .env. Read from git's ignore list, so a store added
    to .gitignore travels without a second list here."""
    ignored = _git("ls-files", "--others", "--ignored", "--exclude-standard").splitlines()
    out = []
    for path in ignored:
        if "/" in path or path in NOT_SENT or path.endswith((".tmp", ".log")):
            continue                 # folders (demo/, caches) and what is rebuilt
        if path == ".env" and not keys:
            continue
        out.append(path)
    return sorted(out)


def build(out, code, data, commit=""):
    """Write the bundle: the files, and a manifest saying which are code and which data."""
    manifest = {"made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": commit,
                "code": code, "data": data}
    with zipfile.ZipFile(out + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(phone.MANIFEST, json.dumps(manifest, indent=1))
        for path in code + data:
            z.write(os.path.join(ROOT, path), path)
    os.replace(out + ".tmp", out)
    os.chmod(out, 0o600)
    return manifest


def main(argv):
    desktop = os.path.expanduser("~/Desktop")
    out = os.path.join(desktop if os.path.isdir(desktop) else ROOT, NAME)
    data = [] if "--code" in argv else data_files(keys="--no-keys" not in argv)
    manifest = build(out, code_files(), data, _git("rev-parse", "--short", "HEAD").strip())
    size = os.path.getsize(out) / 1e6
    print(f"{out}  ({size:.1f} MB: {len(manifest['code'])} code files, {len(data)} data files)")
    if ".env" in data:
        print("It holds your API keys and account: send it by AirDrop only, and delete it from the "
              "phone's Downloads once it is unpacked.")
    print("On the phone, in a-Shell: " + ("cd ~/Documents/trading-desk && python3 phone.py --update ~/Documents/"
                                         + NAME if "--code" in argv else
                                         "python3 -m zipfile -e " + NAME + " trading-desk"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
