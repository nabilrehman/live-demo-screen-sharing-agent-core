"""Builds the Hard Rock Host Companion demo (Hard Rock v2, served at /hardrock-v2/): a host-facing casino-floor app
with the LiveKit voice companion. One page (index.html) with screens drawn by app.js from data.js, which is written here
from data.py, the same source as the agent's knowledge pack, so the page and the agent always agree.

Brand: Hard Rock's tokens from the v1 build (Lato, black/charcoal, gold #87601b, Unity purple #3f396d, square corners),
Seminole Hard Rock Hollywood's logo and public photos (img/real/, list.txt), generated fillers (img/gen/). A private demo
for Hard Rock only: mockup banner, noindex, access-code gate, inert "Demo only" buttons, fictional players.

  python3 mockup/hardrock-host/build.py <out dir, e.g. ../vflights/public/hardrock-v2> [<real photo dir>]
"""

from __future__ import annotations

import html
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data as D  # noqa: E402

ACCESS_CODE = "HARDROCK-DEMO"
BASE = "/hardrock-v2"
EMBED = '<script src="/embed/hardrock-v2/livekit.js" data-site-root="/hardrock-v2/" data-brain="hardrock-host-grok" defer></script>'
E = html.escape

GATE = f"""<script>(function(){{var C={ACCESS_CODE!r},q=new URLSearchParams(location.search).get('code'),c=null;
try{{if(q)sessionStorage.setItem('hr-demo-code',q);c=sessionStorage.getItem('hr-demo-code');}}catch(e){{c=q;}}
if(c!==C)document.documentElement.className+=' gated';}})();</script>"""

GATE_BODY = """<div class="gate"><div class="gate-card"><h1>Private demo</h1><p>This is a private mockup prepared by LiveKit for Hard Rock Hotels. Open it with the access link you were given.</p>
<form onsubmit="var v=this.c.value.trim();if(v){location.search='?code='+encodeURIComponent(v)}return false"><label>Access code <input name="c" autocomplete="off"></label><button>Open</button></form></div></div>"""

TRY = [
    "Give me today's briefing.",
    "Pull up Marcus Delane.",
    "What can I comp him tonight?",
    "Can I give him a suite upgrade and two show tickets?",
    "What would he enjoy tonight?",
    "He just sat down at high-limit baccarat.",
    "Who's next?",
    "She's celebrating an anniversary, what should I do?",
    "Back to the briefing.",
]


def page() -> str:
    tries = "".join(f"<li>“{E(t)}”</li>" for t in TRY)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><title>Host Companion | Seminole Hard Rock Hollywood (demo mockup)</title>
<meta name="description" content="Hard Rock Host Companion: a voice AI companion for casino hosts (demo mockup by LiveKit).">
<meta name="theme-color" content="#0f0f0f">
{GATE}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:ital,wght@0,300;0,400;0,700;0,900;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{BASE}/assets/app.css"><link rel="icon" href="{BASE}/img/brand/favicon.png">
{EMBED}
</head><body>
{GATE_BODY}
<div class="demo-banner" role="note">Demo mockup prepared by LiveKit for Hard Rock Hotels, not the official site.</div>
<div class="stage">
  <aside class="pitch" aria-label="About this demo" data-lk-ignore>
    <img class="pitch-logo" src="{BASE}/img/brand/logo-hollywood.png" alt="Seminole Hard Rock Hotel &amp; Casino Hollywood">
    <p class="eyebrow">Hard Rock · v2 concept</p>
    <h1>Host Companion</h1>
    <p class="lede">Every casino host gets a voice AI companion on their phone. It talks to the host as they walk the floor: today's VIP arrivals, each player's profile, the comps they're authorized to offer, preferences, and what to recommend tonight.</p>
    <ul class="points">
      <li><b>Daily briefing</b> of arriving Unity by Hard Rock VIPs</li>
      <li><b>Player profile</b>: tier, theo / ADT, games, win/loss</li>
      <li><b>Comp authority</b> with limits, budget and approvals</li>
      <li><b>Preferences</b> and tonight's dining and entertainment</li>
      <li><b>Responsible gaming</b> guardrails built in</li>
    </ul>
    <p class="try-h">Try saying</p>
    <ol class="try">{tries}</ol>
    <p class="fine">Sample data: six fictional players, made-up IDs and numbers. Venues and Hard Rock Live dates are from seminolehardrockhollywood.com (Oct 21, 2026). The hotel booking demo is <a href="/hardrock/">v1</a>.</p>
  </aside>
  <div class="device"><div class="app" id="app">
    <header class="appbar">
      <a class="brand" href="#/briefing" aria-label="Briefing"><img src="{BASE}/img/brand/logo-hollywood-wide.png" alt="Seminole Hard Rock Hotel &amp; Casino Hollywood"></a>
      <div class="who"><strong>Host Companion</strong><span>{E(D.HOST['name'])} · {E(D.HOST['role'])}</span></div>
    </header>
    <div class="sample-pill" role="note">Sample data — fictional players</div>
    <main id="main" aria-live="polite"></main>
    <footer class="appfoot"><p>Demo mockup prepared by LiveKit for Hard Rock. Players, IDs, numbers and comps are fictional; nothing here posts to any account. Venue facts and photos © Seminole Hard Rock / Hard Rock International, used for a private demo. Gambling problem? Call or text 1-833-PLAYWISE.</p></footer>
  </div></div>
</div>
<div id="demo-toast" class="toast" role="status" hidden>Demo only: this mockup doesn't post comps or change any account.</div>
<script src="{BASE}/assets/data.js"></script>
<script src="{BASE}/assets/app.js" defer></script>
</body></html>"""


def data_js() -> str:
    d = {
        "property": D.PROPERTY,
        "date": D.BRIEFING_DATE,
        "day": D.BRIEFING_DAY,
        "host": D.HOST,
        "approver": D.APPROVER,
        "players": D.players(),
        "shows": D.SHOWS,
        "venues": D.VENUES,
        "tiers": D.TIERS,
        "policy": D.POLICY,
        "base": BASE,
    }
    return "/* generated by mockup/hardrock-host/build.py from data.py: fictional sample players */\nwindow.HRH_DATA = " + json.dumps(d, ensure_ascii=False, indent=1) + ";\n"


REAL = {  # role -> file in the real photo dir (Seminole Hard Rock Hollywood public photos)
    "casino-floor.jpg": "casino-floor.jpg",
    "casino-floor-wide.jpg": "casino-floor-wide.jpg",
    "guitar-hotel.jpg": "guitar-hotel.jpg",
    "oasis-tower.jpg": "oasis-tower.jpg",
    "hard-rock-live.jpg": "hard-rock-live.jpg",
    "daer.jpg": "daer.jpg",
    "spa.jpg": "spa.jpg",
    "bars-lounges.jpg": "bars-lounges.jpg",
    "slots-closeup.jpg": "slots-closeup.jpg",
}


def copy_images(out: str, real_dir: str | None):
    from PIL import Image

    if real_dir and os.path.isdir(real_dir):
        os.makedirs(os.path.join(out, "img", "real"), exist_ok=True)
        os.makedirs(os.path.join(out, "img", "brand"), exist_ok=True)
        for dst, src in REAL.items():
            im = Image.open(os.path.join(real_dir, src)).convert("RGB")
            if im.width > 1600:
                im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)
            im.save(os.path.join(out, "img", "real", dst), "JPEG", quality=82, progressive=True, optimize=True)
        if os.path.exists(os.path.join(real_dir, "list.txt")):
            shutil.copy(os.path.join(real_dir, "list.txt"), os.path.join(out, "img", "real", "list.txt"))
        shutil.copy(os.path.join(real_dir, "logo.png"), os.path.join(out, "img", "brand", "logo-hollywood.png"))
        shutil.copy(os.path.join(real_dir, "logo-mobile.png"), os.path.join(out, "img", "brand", "logo-hollywood-wide.png"))
        fav = os.path.join(HERE, "..", "..", "..", "vflights", "public", "hardrock", "img", "brand", "favicon.png")
        if os.path.exists(fav):
            shutil.copy(fav, os.path.join(out, "img", "brand", "favicon.png"))
    # small copies for cards
    for sub in ("gen", "real"):
        d = os.path.join(out, "img", sub)
        if not os.path.isdir(d):
            continue
        os.makedirs(os.path.join(d, "s"), exist_ok=True)
        for f in os.listdir(d):
            if f.endswith(".jpg"):
                t = os.path.join(d, "s", f)
                if not os.path.exists(t) or os.path.getmtime(t) < os.path.getmtime(os.path.join(d, f)):
                    im = Image.open(os.path.join(d, f)).convert("RGB")
                    im.thumbnail((720, 720))
                    im.save(t, "JPEG", quality=78, progressive=True, optimize=True)


def main():
    out = os.path.abspath(sys.argv[1])
    real_dir = sys.argv[2] if len(sys.argv) > 2 else None
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(page())
    with open(os.path.join(out, "assets", "data.js"), "w") as f:
        f.write(data_js())
    for n in ("app.css", "app.js"):
        shutil.copy(os.path.join(HERE, n), os.path.join(out, "assets", n))
    copy_images(out, real_dir)
    D.write_knowledge()
    print(f"built {out}")


if __name__ == "__main__":
    main()
