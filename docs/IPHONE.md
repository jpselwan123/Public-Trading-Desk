# The desk on your iPhone

Two ways. **This page:** the whole desk runs on the phone, a second desk with its own notes.
**Or one desk:** the phone opens the Mac's desk through Tailscale, so everything is in one
place, and the Mac has to be on. That one is set up in `docs/ONE-DESK.md`.

The whole desk runs on the phone, inside the free **a-Shell** app, and syncs your broker
from the phone itself. No Mac is needed once it is set up. The page is the same
one, built for a phone's width.

Why a-Shell: an iPhone pauses any app that is not on screen, so a server running in one
app cannot feed a page in Safari. a-Shell runs Python *and* has its own browser, so the
desk serves the page and shows it in the same app (`phone.py`).

## What you need

- **a-Shell** from the App Store (free, by Nicolas Holzschuch). Not "a-Shell mini": it
  has no Python.
- Your Mac, once, to pack the desk. AirDrop between the two.

## The first time

**On the Mac**, in Terminal:

```bash
cd ~/trading-desk && git pull
python3 scripts/phone_bundle.py
```

This makes **TradingDesk-phone.zip** on your Desktop. It holds the desk, your account
data, notes, ratings log, theses and your API keys, so the phone starts where the Mac
is. Because of the keys, send it by **AirDrop only**: not by email, messages or a cloud
drive.

The ratings' data (the SEC's universe of filers and their industry codes) is built by
the Mac itself, with its company updates. Open the desk on the Mac once first, so the
bundle carries it.

**AirDrop** the file to your iPhone. It lands in the **Files** app, under Downloads.
In Files, move it to **On My iPhone › a-Shell** (long-press it › Move).

**On the iPhone**, open a-Shell and type these one at a time:

```
python3 -m zipfile -e TradingDesk-phone.zip trading-desk
rm TradingDesk-phone.zip
cd trading-desk
python3 phone.py
```

The desk opens inside a-Shell, and the companies' data updates by itself.
To bring in your account, press the round sync button, as on the Mac.

Only use the `zipfile -e` line this first time. Unpacked again later, it would replace
the phone's notes with the Mac's. Updates have their own command, below.

## The first time, without the Mac

A copy of the code alone (no account data, no keys) can come straight to the phone, for
example as a file Claude sends in the Claude app. Tap it, then **Save to Files ›
On My iPhone › a-Shell**. In a-Shell, type each line in turn:

```
cd ~/Documents
python3 -m zipfile -e TradingDesk-phone.zip trading-desk
rm TradingDesk-phone.zip
cd trading-desk
python3 phone.py --keys
python3 phone.py
```

`--keys` asks for each key in turn (your broker's keys, your email for the
SEC, Tiingo, Finnhub, and OpenAI if you use summaries). Each question says where the key
comes from. Return keeps what is there. On the iPhone a key shows as you type it (a-Shell
cannot hide typing), so type it where no one is looking. Never paste a key into a chat.

This desk starts empty, so its first sync fetches the account's whole history, and its
first company update every price history: allow several minutes each, with a-Shell on
screen. The phone does not build the ratings' data
itself (it is a large download): bring it from the Mac, as below under "Nothing is
rated". Or build it in a-Shell by hand: `python3 universe.py`, then `python3 sectors.py`
(about 80 MB).

## Every time after

Open a-Shell and type:

```
cd ~/Documents/trading-desk && python3 phone.py
```

The up-arrow key above the keyboard brings back the last command.

**A home-screen icon, so it is one tap:**

1. Open the Shortcuts app and tap **+**. Tap Add Action, search for **a-Shell**, and choose
   **Execute Command**.
2. Type the command as two lines:
   `cd ~/Documents/trading-desk`
   `python3 phone.py`
3. Set it to run **in the app**, not in the extension: the extension cannot show the page.
4. Name it "Trading Desk". Then tap the share button and choose **Add to Home Screen**.

**To stop the desk:** close the page (the desk stops with it), or press ctrl-C in a-Shell
(the ctrl key above the keyboard, then C).
If a sync or an update is under way, it finishes first.

## New code

When the desk gets new features, a new **TradingDesk-phone.zip** comes either from the Mac
(`cd ~/trading-desk && git pull && python3 scripts/phone_bundle.py --code`, then AirDrop)
or as a file from Claude.

1. Tap the file, then **Save to Files › On My iPhone › a-Shell**: a-Shell's own folder, the
   one it opens in. If the Files app unpacks it into a folder called TradingDesk-phone,
   that works too.
2. In a-Shell, type each line in turn:

   ```
   cd ~/Documents
   python3 trading-desk/phone.py --update TradingDesk-phone.zip
   rm TradingDesk-phone.zip
   cd trading-desk
   python3 phone.py
   ```

   For the unpacked folder, use `--update TradingDesk-phone`, then `rm -r TradingDesk-phone`.
   Removing it keeps the next update's file from being saved as "TradingDesk-phone 2".

Saved somewhere else, such as Downloads: type `pickFolder`, go to the folder that holds the
file and tap **Open** there. `pickFolder` picks a folder, so the file itself is greyed out and
cannot be tapped. Then type `python3 ~/Documents/trading-desk/phone.py --update
TradingDesk-phone.zip`.

`--update` replaces the code only. Your phone's notes, ratings log, theses, coverage
and keys are never overwritten. A data file the phone lacks is added.

## Worth knowing

- **Keep a-Shell on screen while a sync or an update runs.** The iPhone pauses apps in
  the background, and one left paused can time out: if a sync fails, press sync again;
  the company data tries again by itself. For the first long sync, set Settings › Display
  & Brightness › Auto-Lock to Never, and back afterwards.
- **The phone and the Mac become two separate desks.** A note written on the phone is
  not on the Mac, and each keeps its own ratings log. Write
  notes and theses on one of them.
- **Broker keys with an IP restriction:** if you limited the key to certain
  addresses when you made it, the phone has to come through an allowed one. Otherwise the broker refuses the sync.

## If something goes wrong

First, in a-Shell: `cd ~/Documents/trading-desk && python3 doctor.py`. It checks the keys,
every data source, the stored data and the ratings, and says what is wrong. Its report holds
nothing private, so it can be pasted into a chat as it is.

- **A sync or an update says "certificate verify failed".** This Python has no list of the
  authorities that sign websites. In a-Shell, type `pip install certifi`, then start the
  desk again. `phone.py` finds it by itself.
- **The page opens in Safari instead of inside a-Shell.** It stops working as soon as
  Safari is in front, because a-Shell is paused behind it. Go back to a-Shell. Close the
  desk with ctrl-C, then open it by hand: `cd ~/Documents/trading-desk` and
  `python3 phone.py --no-browser` in one a-Shell window (on an iPad), and
  `internalbrowser http://127.0.0.1:8935/` in another.
- **"The desk is already running in another a-Shell window"**: it is open in another
  window; the page opens from that one.
- **Nothing is rated:** the ratings need `universe.json` and `sectors.json`, which the Mac
  builds with its company updates. Run `phone_bundle.py` on the Mac without `--code`, and
  `--update` on the phone: the files the phone lacks are added. To replace older copies the
  phone already has, delete them first (`rm universe.json sectors.json`).
