# One desk: the Mac's desk on your phone

The phone can run its own copy of the desk (`docs/IPHONE.md`), but then there are two
desks. A note, a plan or a thesis written on one is not on the other, and each keeps its
own ratings log. The alternative is one desk: the Mac runs it, and the
phone opens the Mac's page through **Tailscale**, a free app that joins your own devices
into a private network. Nothing is opened to the internet. Only devices signed in to your
Tailscale account can reach the desk, and the desk itself still listens on the Mac alone.

What changes:

- **One set of notes, plans, theses and ratings.** Everything written from the phone is
  written on the Mac.
- **The Mac must be on and awake, with the desk open.** If it is asleep, the phone gets
  nothing. The phone's own copy still works on its own.
- **Everything works from the phone:** the account sync, the company update, following a
  company, notes, plans and theses.

## Setting it up, once

**1. Tailscale on both.** Install Tailscale on the Mac (tailscale.com/download, or the
Mac App Store) and on the iPhone (App Store). Sign in with the same account on both, and
leave it on.

**2. On the Mac, hand the desk to Tailscale.** Open Terminal and type:

```bash
tailscale serve --bg 8935
```

If Terminal says `tailscale: command not found`, the App Store version keeps it inside the
app. Type this instead:

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8935
```

The first time, it may print a link that asks you to turn on HTTPS for your devices.
Open it, allow it, and run the command again. It then prints the Mac's address, like
`https://my-mac.tail1234.ts.net/`. `--bg` makes Tailscale keep serving it after Terminal
is closed and after a restart.

**3. Tell the desk that name.** In the desk's `.env` on the Mac, add the name without
`https://` and without the final `/`:

```
DESK_HOSTS=my-mac.tail1234.ts.net
```

Then quit and reopen Trading Desk. The desk accepts that one name and still refuses every
other website. `python3 doctor.py` shows "Phone through Tailscale: set" when it is right.

**4. On the iPhone,** with Tailscale on, open that address in Safari. Share › Add to Home
Screen gives it an icon.

## If it does not open

- **Is the Mac awake, with the desk open?** Tailscale reaches the Mac only while it is on.
- **Tailscale on the phone:** it is a VPN on iOS, and an iPhone runs one VPN at a time.
  While Tailscale is on, any other VPN on the phone is off, which is fine: the Mac does the
  account sync.
- **A VPN on the Mac:** some VPN apps do not let Tailscale through while they are on.
  If the phone cannot reach the desk while the Mac's VPN is on, turn that VPN off.
- **"forbidden":** the name in `DESK_HOSTS` does not match the address you opened, or it
  does not end in `.ts.net`. Copy it exactly as `tailscale serve` printed it.

To stop: `tailscale serve reset` on the Mac (or turn Tailscale off), and remove
`DESK_HOSTS` from `.env`.
