"""Builds the Wind Creek demo mockup: static pages that follow windcreek.com's layout, with the Kai embed tag on every
page. Content is summarized from the public site (knowledge/windcreek/, fetched 2026-10-20); images are Wind Creek's
own public photos (img/) plus generated fillers (img/gen/). A private demo for Wind Creek only: every page carries the
mockup banner, the copyright footer, noindex, and an access-code gate. No sign-in, booking, payment or personal-data
inputs: those controls are inert "Demo only" buttons.

  python3 mockup/windcreek/build.py <out dir, e.g. vflights/public/windcreek>
"""

import html
import os
import sys

ACCESS_CODE = "WINDCREEK-DEMO"  # the gate's code: pages show only with ?code=<this> (kept in sessionStorage)
BASE = "/windcreek"  # where the mockup is served
# The one-line embed, written by a tiny loader so the presenter can pick the voice model for this tab with
# ?brain=gemini or ?brain=grok (kept in sessionStorage); the widget defaults to Grok.
EMBED = """<script>(function(){var q=new URLSearchParams(location.search).get('brain'),b='';
try{if(q==='gemini'||q==='grok')sessionStorage.setItem('wc-brain','wc-'+q);b=sessionStorage.getItem('wc-brain')||'';}catch(e){}
document.write('<script src="/embed/windcreek/kai.js" data-site-root="/windcreek/"'+(b?' data-brain="'+b+'"':'')+' defer><\\/script>');})();</script>"""
E = html.escape


def img(name: str) -> str:
    return f"{BASE}/img/{name}"


def gen(name: str) -> str:
    return f"{BASE}/img/gen/{name}"


def link(path: str) -> str:
    return BASE + (path if path != "/" else "/")


# ---------- layout ----------
GLOBAL_NAV = [("Locations", "/locations"), ("Rewards", "/rewards"), ("About Us", "/demo-only")]
BETH_NAV = [
    (
        "Casino",
        "/bethlehem/casino",
        [("Casino Overview", "/bethlehem/casino"), ("Wind Creek Rewards", "/bethlehem/casino/rewards")],
    ),
    (
        "Resort",
        "/bethlehem/resort/hotel-rooms-and-suites",
        [
            ("Hotel Rooms & Suites", "/bethlehem/resort/hotel-rooms-and-suites"),
            ("Hotel Packages", "/bethlehem/resort/hotel-packages"),
            ("Amenities", "/bethlehem/resort/amenities"),
            ("Kids Quest & Cyber Quest", "/bethlehem/resort/kids-quest-and-cyber-quest"),
        ],
    ),
    ("Spa", "/bethlehem/resort/spa", []),
    (
        "Dining",
        "/bethlehem/dining",
        [
            ("All Dining", "/bethlehem/dining"),
            ("Chop House at Wind Creek", "/bethlehem/dining/chop-house-at-wind-creek"),
            ("Urban Table", "/bethlehem/dining/urban-table"),
        ],
    ),
    (
        "Entertainment",
        "/bethlehem/entertainment",
        [("Entertainment", "/bethlehem/entertainment"), ("Event Center", "/bethlehem/entertainment/event-center")],
    ),
    (
        "Getting Here",
        "/bethlehem/getting-here",
        [
            ("Getting Here", "/bethlehem/getting-here"),
            ("FAQ", "/bethlehem/faq"),
            ("Property Schedule", "/bethlehem/property-schedule"),
        ],
    ),
]
LOCS = [
    ("atmore", "Atmore", "United States", "loc-atmore.jpg"),
    ("bethlehem", "Bethlehem", "United States", "loc-bethlehem.jpg"),
    ("montgomery", "Montgomery", "United States", "loc-montgomery.jpg"),
    ("wetumpka", "Wetumpka", "United States", "loc-wetumpka.jpg"),
    ("aruba", "Aruba", "The Caribbean", "loc-aruba.jpg"),
    ("curacao", "Curaçao", "The Caribbean", "loc-curacao.jpg"),
    ("chicagosouthland", "Chicago Southland", "United States", "loc-chicago.jpg"),
    ("miami", "Miami", "United States", "loc-miami.jpg"),
]


def header(prop: bool) -> str:
    logo = img("logo-bethlehem.svg") if prop else img("logo.svg")
    home = "/bethlehem" if prop else "/"
    if prop:
        items = []
        for label, href, sub in BETH_NAV:
            if sub:
                subs = "".join(f'<li><a href="{link(h)}">{E(t)}</a></li>' for t, h in sub)
                items.append(
                    f'<li class="dd"><a href="{link(href)}">{E(label)}<span class="caret" aria-hidden="true"></span></a><ul>{subs}</ul></li>'
                )
            else:
                items.append(f'<li><a href="{link(href)}">{E(label)}</a></li>')
        nav = "".join(items)
        cta = f'<a class="cta" href="{link("/bethlehem/book-now")}">Book Now</a><a class="cta" href="{link("/bethlehem/promotions")}">Promotions</a>'
    else:
        nav = "".join(f'<li><a href="{link(h)}">{E(t)}</a></li>' for t, h in GLOBAL_NAV)
        cta = f'<a class="cta" href="{link("/demo-only")}">Contact Us</a>'
    locs = "".join(f'<li><a href="{link("/" + s)}">{E(n)}</a></li>' for s, n, _, _ in LOCS)
    return f"""
<div class="demo-banner" role="note">Demo mockup prepared by LiveKit for Wind Creek Hospitality — not the official windcreek.com site.</div>
<header class="site-header">
  <div class="topbar">
    <button type="button" class="search" data-demo>Search site… <span aria-hidden="true">&#9906;</span></button>
    <details class="locs"><summary>Locations</summary><ul>{locs}</ul></details>
    <button type="button" class="btn-outline" data-demo>Sign In</button>
    <button type="button" class="btn-red" data-demo>Find a Job</button>
  </div>
  <div class="mainbar">
    <a class="logo" href="{link(home)}"><img src="{logo}" alt="Wind Creek{" Bethlehem" if prop else ""}"></a>
    <button type="button" class="burger" aria-label="Menu" onclick="document.body.classList.toggle('menu-open')">&#9776;</button>
    <nav aria-label="Primary"><ul class="nav">{nav}</ul><div class="ctas">{cta}</div></nav>
  </div>
</header>"""


def footer(prop: bool) -> str:
    cols = "".join(f'<li><a href="{link("/" + s)}">{E(n)}</a></li>' for s, n, _, _ in LOCS)
    addr = "77 Wind Creek Blvd, Bethlehem, PA 18015 · 877-726-3777" if prop else "Wind Creek Hospitality"
    return f"""
<footer class="site-footer">
  <div class="fwrap">
    <div><img src="{img("logo.svg")}" alt="Wind Creek" class="flogo"><p>{addr}</p><p class="rg">Must be 21 or older to gamble. Gambling problem? Call 1-800-GAMBLER.
      <a href="{link("/responsible-gambling")}">Responsible Gambling</a></p></div>
    <div><h2 class="fh">Locations</h2><ul>{cols}</ul></div>
    <div><h2 class="fh">Wind Creek</h2><ul><li><a href="{link("/rewards")}">Wind Creek Rewards</a></li><li><a href="{link("/locations")}">All Locations</a></li><li><a href="{link("/responsible-gambling")}">Responsible Gambling</a></li></ul></div>
  </div>
  <p class="credit">Content and images © Wind Creek Hospitality, reproduced from windcreek.com for a private demo to Wind Creek only. Some supplementary photos were generated for this mockup and are marked in <a href="{link("/credits")}">image credits</a>.</p>
</footer>"""


GATE = f"""<script>(function(){{var C={ACCESS_CODE!r},q=new URLSearchParams(location.search).get('code'),c=null;
try{{if(q)sessionStorage.setItem('wc-demo-code',q);c=sessionStorage.getItem('wc-demo-code');}}catch(e){{c=q;}}
if(c!==C)document.documentElement.className+=' gated';}})();</script>"""

GATE_BODY = """<div class="gate"><div class="gate-card"><h1>Private demo</h1><p>This is a private mockup prepared by LiveKit for Wind Creek Hospitality. Open it with the access link you were given.</p>
<form onsubmit="var v=this.c.value.trim();if(v){location.search='?code='+encodeURIComponent(v)}return false"><label>Access code <input name="c" autocomplete="off"></label><button>Open</button></form></div></div>"""

DEMO_JS = """<script>document.addEventListener('click',function(e){var b=e.target.closest('[data-demo]');if(!b)return;e.preventDefault();
var t=document.getElementById('demo-toast');t.hidden=false;clearTimeout(t._h);t._h=setTimeout(function(){t.hidden=true},2200);});
document.querySelectorAll('.tabs [role=tab]').forEach(function(tab){tab.addEventListener('click',function(){var l=tab.closest('.tabs');
l.querySelectorAll('[role=tab]').forEach(function(x){x.setAttribute('aria-selected',x===tab)});
l.parentElement.querySelectorAll('[role=tabpanel]').forEach(function(p){p.hidden=p.id!==tab.getAttribute('aria-controls')})})});</script>"""


def page(path: str, title: str, body: str, prop: bool = False, desc: str = "") -> tuple[str, str]:
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{E(title)} | Wind Creek Hospitality (demo mockup)</title>
<meta name="description" content="{E(desc or title)}">
{GATE}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600&family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{BASE}/assets/site.css">
{EMBED}
</head><body>
{GATE_BODY}
{header(prop)}
<main id="main">{body}</main>
{footer(prop)}
<div id="demo-toast" class="toast" role="status" hidden>Demo only: this mockup doesn't sign in, book or take personal details.</div>
{DEMO_JS}
</body></html>"""
    return path, doc


# ---------- components ----------
def hero(eyebrow, title, text, pic, cta=None):
    btn = f'<a class="btn-red big" href="{link(cta[1])}">{E(cta[0])}</a>' if cta else ""
    return f"""<section class="hero"><div class="hero-copy"><p class="eyebrow">{E(eyebrow)}</p><h1>{E(title)}</h1>
<p>{E(text)}</p>{btn}</div><div class="hero-pic"><span class="red-block" style="background-image:url({img("bg-red.jpg")})"></span><img src="{pic}" alt=""></div></section>"""


def section_head(eyebrow, title, more=None):
    m = f'<a class="more" href="{link(more[1])}">{E(more[0])}</a>' if more else ""
    return f'<div class="shead"><div><p class="eyebrow">{E(eyebrow)}</p><h2>{E(title)}</h2></div>{m}</div>'


def card(title, text, pic, href=None, meta="", tag="h3", extra=""):
    t = f'<a href="{link(href)}">{E(title)}</a>' if href else E(title)
    more = f'<a class="learn" href="{link(href)}">Learn More</a>' if href else ""
    return f"""<article class="card"><img src="{pic}" alt=""><div class="card-body">
<{tag}>{t}</{tag}>{f'<p class="meta">{E(meta)}</p>' if meta else ""}<p>{E(text)}</p>{extra}{more}</div></article>"""


def info_box(rows):
    return '<dl class="info">' + "".join(f"<dt>{E(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def hours(rows):
    return (
        '<table class="hours"><tbody>'
        + "".join(f"<tr><td>{E(d)}</td><td>{E(h)}</td></tr>" for d, h in rows)
        + "</tbody></table>"
    )


# ---------- content ----------
PROMOS = [
    {
        "slug": "255000-choose-your-ride-sweepstakes",
        "title": "$255,000 Choose Your Ride Sweepstakes",
        "when": "Sunday, October 25th • 5PM – 9PM",
        "tag": "Free Entry · Electronic Drawing",
        "pic": "promo-ride.jpg",
        "lead": "Choose your ride, plus over 300 winners share $255,000 in cars, cash and Slot FREE Play.",
        "body": [
            (
                "How to Qualify",
                "First entry is free. Earn one more entry for every 25 tier-points from rated slot play while signed in to your Rewards account, Thursday, October 1st through 6:45pm Sunday, December 27th. Rewards Members get bonus entries: Fantasy 200, Delight 100, Escape 50, Play 10.",
            ),
            (
                "Details",
                "100 winners are drawn at Molten Lounge at 5pm, 6pm, 8pm and 9pm to share $25,000 Slot FREE Play. At 7pm, four players share $10,000 Slot FREE Play and one Grand Prize winner takes home a new car or $40,000 cash. Activate entries between 5pm and 8:45pm on Sunday, October 25th. Must be present to win.",
            ),
        ],
    },
    {
        "slug": "players-learning-games",
        "title": "Players Learning Games",
        "when": "Free Game Instruction Every Saturday | 12:00 PM–4:00 PM",
        "tag": "Free · Casino Floor",
        "pic": "promo-learning.jpg",
        "lead": "Ready to learn a new casino game?",
        "body": [
            (
                "Details",
                "Every Saturday from noon to 4pm, friendly dealers teach the basics at a dedicated learning table on the casino floor, with training chips and cards. Training only, no wagering. A Wind Creek Rewards card is required; space is limited.",
            )
        ],
    },
    {
        "slug": "monster-mash-bash",
        "title": "Monster Mash Bash",
        "when": "October 31st • 9pm",
        "tag": "Auto Win · Online Drawing",
        "pic": "promo-monster.jpg",
        "lead": "Casinoverse members, win a share of $5,000 Slot FREE Play.",
        "body": [
            (
                "How to Qualify",
                "Log in to Casinoverse daily from October 1st to 31st and claim your free online entry from Hot Picks in the WStore. The drawing is Saturday, October 31st at 9pm; prizes go straight to your Rewards account.",
            )
        ],
    },
    {
        "slug": "claim-the-crown",
        "title": "Claim the Crown",
        "when": "Sign-Up Starts September 1st",
        "tag": "Electronic Drawing · Property Quest",
        "pic": "promo-crown.jpg",
        "lead": "Win a share of over $500,000 and rule Casinoverse with a year of exclusive benefits.",
        "body": [
            (
                "How it works",
                "Sign up for your property team in the Casinoverse app, complete weekly Claim the Crown Quests in October and November, and earn entries from October 5th to November 30th (double entries December 1st to 5th). The drawing begins at 9pm on December 5th; weekly top earners join the finale at Wind Creek Aruba, January 18th to 22nd.",
            )
        ],
    },
    {
        "slug": "new-player",
        "title": "New Player Rewards",
        "when": "Limited Time Offer Beginning September 1st",
        "tag": "New Members",
        "pic": "promo-newplayer.jpg",
        "lead": "New members win a share of $80,000 Slot FREE Play, plus up to $120 in sign-up rewards.",
        "body": [
            (
                "$80,000 New Member Drawings",
                "On the first Saturday of each month, 80 new members from the prior month win $1,000 Slot FREE Play.",
            ),
            (
                "Sign-Up Rewards",
                "$80 Slot FREE Play for joining ($20 right away, then $20 a week for three weeks), a $10 food credit with a valid email and phone, $10 Slot FREE Play for downloading Casinoverse and $20 for linking your Rewards account. Sign up at Player Services on the casino floor.",
            ),
        ],
    },
]

DINING = [
    {
        "slug": "chop-house-at-wind-creek",
        "name": "Chop House at Wind Creek",
        "pic": img("d-chophouse.jpg"),
        "short": "A modern, upscale twist on the classic American steakhouse: only-the-best steaks, seafood, signature creations and handcrafted cocktails.",
        "where": "West of the Main Lobby",
        "phone": "877-726-3777",
        "hours": [("Mon", "Closed"), ("Tue, Wed, Thu, Fri & Sun", "5PM – 10PM"), ("Sat", "5PM – 11PM")],
        "note": "Reservations are recommended. 10% military discount with ID. Guests under 21 can't be escorted across the casino floor.",
        "menu": [
            (
                "Steaks",
                [
                    ("7oz Filet Mignon", "59"),
                    ("10oz Filet Mignon", "73"),
                    ("16oz New York Strip", "59"),
                    ("18oz Boneless Ribeye", "75"),
                    ("22oz Bone-In Ribeye", "84"),
                    ("26oz Dry Aged Porterhouse", "MKT"),
                    ("28oz Prime Tomahawk Ribeye", "MKT"),
                ],
            ),
            (
                "Wagyu",
                [
                    ("A-5 Japanese Wagyu Strip Loin", "MKT"),
                    ("M-7 Australian 12oz Wagyu Strip", "94"),
                    ("Domestic 14oz Boneless Ribeye Wagyu", "97"),
                ],
            ),
            (
                "Starters",
                [
                    ("Blue Crab Cake", "24"),
                    ("Oysters Rockefeller", "22"),
                    ("New Zealand Lamb Chops", "26"),
                    ("Lobster Bisque", "18"),
                ],
            ),
        ],
    },
    {
        "slug": "urban-table",
        "name": "Urban Table",
        "pic": img("d-urban.jpg"),
        "short": "Contemporary American with a menu for every palate: prime beef burgers, jumbo wings, land and sea favorites and over 10 rotating beers on tap.",
        "where": "Far Northeast Corner",
        "phone": "484-777-7964",
        "hours": [
            ("Mon – Tue", "Closed"),
            ("Wed – Thu", "11AM – 10PM"),
            ("Fri – Sat", "11AM – 11PM"),
            ("Sun", "11AM – 10PM"),
        ],
        "note": "Reservations are recommended. Minors welcome when entering through The Outlets or hotel.",
    },
    {
        "slug": "chopstick",
        "name": "Chopstick",
        "pic": img("d-chopstick.jpg"),
        "short": "Fresh Asian classics: fried rice, dumplings, noodles, spring rolls and more.",
        "where": "Casino floor",
        "phone": "877-726-3777",
        "hours": [("Daily", "12:30PM – 1:30AM")],
    },
    {
        "slug": "steelworks-buffet-and-grill",
        "name": "Steelworks Buffet and Grill",
        "pic": img("d-steelworks.jpg"),
        "short": "Reuben sandwiches, applewood-smoked bacon mac and cheese, ribs and other classics.",
        "where": "Casino level",
        "phone": "877-726-3777",
        "hours": [
            ("A la carte, Mon – Fri", "8AM – 9PM"),
            ("A la carte, Sat", "8AM – 11PM"),
            ("A la carte, Sun", "8AM – 9PM"),
            ("Buffet, Mon – Fri", "12PM – 4PM, 5PM – 8PM"),
            ("Buffet, Sat", "2PM – 8PM"),
            ("Buffet, Sun", "12PM – 5PM"),
        ],
    },
    {
        "slug": "the-market-gourmet-express",
        "name": "The Market",
        "pic": img("d-market.jpg"),
        "short": "All your favorites in one spot: burgers, hot dogs, sushi, pizza and salads, with dessert and coffee.",
        "where": "Casino level",
        "phone": "877-726-3777",
        "hours": [("Daily", "See property schedule")],
    },
    {
        "slug": "bethlehem-barrel-drafthouse",
        "name": "Bethlehem Barrel & Drafthouse",
        "pic": img("d-barrel.jpg"),
        "short": "A refined yet relaxed spot where rustic charm meets modern flair, for whiskey, beer and food lovers.",
        "where": "Casino level",
        "phone": "877-726-3777",
        "hours": [("Daily", "See property schedule")],
    },
    {
        "slug": "twisted-tees",
        "name": "Twisted Tees",
        "pic": img("d-twisted.jpg"),
        "short": "A golf-themed sports bar with elevated pub fare, local brews and state-of-the-art golf simulators.",
        "where": "The Outlets level",
        "phone": "877-726-3777",
        "hours": [
            ("Mon", "Closed"),
            ("Tue – Thu", "4PM – 10PM"),
            ("Fri", "11AM – 10PM"),
            ("Sat", "11AM – 11PM"),
            ("Sun", "11AM – 8PM"),
            ("Brunch, Sat – Sun", "From 11AM"),
        ],
    },
    {
        "slug": "signature-cakes-and-pies",
        "name": "Signature Cakes & Pies",
        "pic": img("d-cakes.jpg"),
        "short": "Baked fresh by the in-house pastry team.",
        "where": "Ask any outlet",
        "phone": "877-726-3777",
        "hours": [("Daily", "See property schedule")],
    },
    {
        "slug": "starbucks",
        "name": "Starbucks",
        "pic": gen("dining-coffee.jpg"),
        "short": "Handcrafted coffee, premium teas and treats.",
        "where": "Hotel lobby",
        "phone": "877-726-3777",
        "hours": [("Daily", "See property schedule")],
    },
    {
        "slug": "sweet-revenge",
        "name": "Sweet Revenge",
        "pic": gen("dining-dessert-shop.jpg"),
        "short": "New Orleans-style ice creams, coffee blends and baked goods.",
        "where": "The Outlets",
        "phone": "877-726-3777",
        "hours": [
            ("Sun", "10AM – 5PM"),
            ("Mon & Tue", "Closed"),
            ("Wed & Thu", "10AM – 7PM"),
            ("Fri & Sat", "10AM – 8PM"),
        ],
    },
]

ROOMS = [
    (
        "Deluxe Queen - North Tower",
        "400 SQ. FT. | 2 Beds | 4 Guests",
        img("r-dq-north.jpg"),
        "Newly redesigned in rich jewel tones, with two plush queen pillow-top beds, close to Spa at Wind Creek.",
    ),
    (
        "Deluxe Queen - South Tower",
        "400 SQ. FT. | 2 Beds | 4 Guests",
        img("r-dq-south.jpg"),
        "Two queen pillow-top beds, media hub, free Wi-Fi and in-room checkout.",
    ),
    (
        "Deluxe King - North Tower",
        "400 SQ. FT. | 1 Bed | 2 Guests",
        img("r-dk-north.jpg"),
        "A plush king pillow-top bed in the redesigned North Tower, near the spa.",
    ),
    (
        "Deluxe King - South Tower",
        "400 SQ. FT. | 1 Bed | 2 Guests",
        img("r-dk-south.jpg"),
        "A king pillow-top bed, media hub, free Wi-Fi and in-room checkout.",
    ),
    (
        "Grand King - North Tower",
        "635 SQ. FT. | 1 Bed | 2 Guests",
        img("r-gk-north.jpg"),
        "Lehigh River views, a sofa, two HDTVs and a king pillow-top bed.",
    ),
    (
        "Executive Suite - South Tower",
        "800 SQ. FT. | 1 Bed | 2 Guests",
        img("r-exec.jpg"),
        "A separate living and dining area, soaking tub and rainforest shower.",
    ),
    ("Presidential Suite", "Suite", img("r-pres.jpg"), "Expansive living space for entertaining."),
    ("Chairman's Suite", "Suite", img("r-chair.jpg"), "The resort's signature suite."),
]

PACKAGES = [
    (
        "Stay & Game",
        ["One night for two at the Wind Creek Hotel", "$10 Slot FREE Play per person, up to two people"],
        [("Sun – Thu", "$169"), ("Fri", "$229"), ("Sat", "$249")],
        img("p-stay.jpg"),
    ),
    (
        "Stay, Game & Dine",
        [
            "One night for two",
            "$50 food voucher for Chop House or Urban Table",
            "$10 Slot FREE Play per person, up to two",
        ],
        [("Sun – Thu", "$219"), ("Fri", "$279"), ("Sat", "$299")],
        img("p-dine.jpg"),
    ),
    (
        "Stay, Game & Dine - Extra",
        [
            "One night for two",
            "$100 food voucher for Chop House or Urban Table",
            "$10 Slot FREE Play per person, up to two",
        ],
        [("Sun – Thu", "$269"), ("Fri", "$329"), ("Sat", "$349")],
        img("p-dine-extra.jpg"),
    ),
    (
        "Celebration Package",
        [
            "One night for two",
            "A bottle of champagne",
            "Enhanced room décor",
            "$10 Slot FREE Play per person, up to two",
        ],
        [("Sun – Thu", "$239"), ("Fri", "$299"), ("Sat", "$319")],
        gen("package-romantic.jpg"),
    ),
    (
        "Kids Quest Hotel Package",
        [
            "One night for two adults",
            "$20 of play at Kids Quest / Cyber Quest",
            "$10 Slot FREE Play per person, up to two",
        ],
        [("Sun – Thu", "$189"), ("Fri", "$219"), ("Sat & holidays", "$249")],
        img("p-kids.jpg"),
    ),
    (
        "The Outlets Package",
        ["One night for two", "$50 Wind Creek gift card to The Outlets", "$10 Slot FREE Play per person, up to two"],
        [("Sun – Thu", "$219"), ("Fri", "$279"), ("Sat", "$299")],
        gen("outlets-shopping.jpg"),
    ),
    (
        "Spa Package",
        ["One night for two", "$150 Spa at Wind Creek voucher", "$10 Slot FREE Play per person, up to two"],
        [("Wed – Thu", "$289"), ("Fri", "$349"), ("Sat", "$369")],
        gen("spa-treatment-room.jpg"),
    ),
    (
        "Christkindlmarkt Package",
        [
            "One night for two or four",
            "Four Christkindlmarkt tickets",
            "$10 Slot FREE Play per person, up to two",
            "Thursday – Sunday, November 12th – December 20th, 2026",
        ],
        [("Thu & Sun", "$219"), ("Fri", "$299"), ("Sat", "$319")],
        img("p-christkindl.jpg"),
    ),
]

TIERS = [
    ("Play", "0–19,999 Tier-Points"),
    ("Escape", "20,000–74,999 Tier-Points"),
    ("Delight", "75,000–199,999 Tier-Points"),
    ("Fantasy", "200,000+ Tier-Points"),
]
NO = '<span class="no" aria-label="Not included">—</span>'
YES = '<span class="yes" aria-label="Included">✓</span>'
REWARD_TABLES = [
    (
        "gaming",
        "Gaming & Retail",
        [
            ("Earn Base-Points", "Redeemable for food & beverage or FREE Play", [YES, YES, YES, YES]),
            (
                "Food Credits",
                "After earning 300 Tier-Points during a visit",
                ["$10 valid for 7 days", "$10 valid for 7 days", "$20 valid for 7 days", "$25 valid for 7 days"],
            ),
            (
                "Exclusive Offers",
                "",
                [
                    "Personalized offers and hotel discounts based on rated play",
                    "Exclusive Escape member promotions",
                    "Exclusive Delight level promotions and parties",
                    "Exclusive Fantasy level promotions and parties",
                ],
            ),
            ("Discounts", "On cash purchases at Wind Creek properties", ["10% off", "15% off", "25% off", "50% off"]),
            (
                "Game Reserve Privileges",
                "",
                [NO, "30 minutes for one machine", "1 hour for one machine", "2 hours for one machine"],
            ),
            ("Birthday Bonus", "", [NO, "$150 FREE Play", "$300 FREE Play", "$400 FREE Play"]),
            ("Access to Spa Lounge and Fitness Room", "", [NO, NO, YES, YES]),
            ("VIP Parking or Valet Parking", "", [NO, NO, YES, YES]),
            ("Access to Lounge", "In high limit slots and table games salon", [NO, NO, YES, YES]),
            ("Free Room Nights", "At Wind Creek properties", [NO, NO, "1 night per month", "2 nights per month"]),
            ("Personal Host", "", [NO, NO, NO, YES]),
            ("Tier-Level FREE Play", "", [NO, NO, NO, "$200 per month"]),
            ("Priority Dining Reservations", "", [NO, NO, NO, YES]),
            ("No-Fee Check Cashing Privileges", "", [NO, NO, NO, YES]),
        ],
    ),
    (
        "online",
        "Online",
        [
            ("Access to Casinoverse", "Play as much as you want for free", [YES, YES, YES, YES]),
            (
                "Casinoverse WScore",
                "",
                ["50,000 each month", "100,000 each month", "250,000 each month", "500,000 each month"],
            ),
            ("Tournaments, Drawings & Auctions", "", [YES, YES, YES, YES]),
            ("Exclusive Tournaments, Drawings & Auctions by Tier", "", [NO, YES, YES, YES]),
        ],
    ),
    (
        "resort",
        "Resort Stay",
        [
            ("Personalized Offers & Hotel Discounts", "Based on rated play", [YES, YES, YES, YES]),
            ("Priority Line Service and Hotel Check-In", "", [NO, NO, YES, YES]),
            (
                "One Stay at Any Resort",
                "Booked by the Wind Creek Travel team",
                [
                    "3 nights discounted",
                    "3 nights complimentary",
                    "5 nights complimentary, for two",
                    "5 nights complimentary, all-inclusive for two",
                ],
            ),
            ("Ground Transportation", "To and from the airport, once each way", [NO, YES, YES, YES]),
            ("FREE Play or Match Play", "", [NO, NO, "$50 per trip", "$100 per trip"]),
            ("Airfare Credit for Two", "", [NO, NO, YES, YES]),
            ("Upgraded Room", "Based on availability", [NO, NO, YES, YES]),
        ],
    ),
    (
        "prime",
        "Prime Tokens",
        [
            (
                "Prime Tokens",
                "3 more at 400,000, 700,000 and 1,000,000 Tier-Points and every 500,000 after",
                [
                    NO,
                    "1 Prime Token upon achieving Escape status",
                    "2 Prime Tokens upon achieving Delight status",
                    "3 Prime Tokens upon achieving Fantasy status",
                ],
            ),
        ],
    ),
]


def rewards_body() -> str:
    cards = "".join(f'<img src="{img("card-" + t.lower() + ".png")}" alt="{t} card">' for t, _ in TIERS)
    tabs = "".join(
        f'<button type="button" role="tab" id="tab-{k}" aria-controls="panel-{k}" aria-selected="{str(i == 0).lower()}">{E(n)}</button>'
        for i, (k, n, _) in enumerate(REWARD_TABLES)
    )
    head = (
        '<thead><tr><th scope="col">Benefits</th>'
        + "".join(f'<th scope="col"><strong>{t}</strong><span>{r}</span></th>' for t, r in TIERS)
        + "</tr></thead>"
    )
    panels = ""
    for i, (k, n, rows) in enumerate(REWARD_TABLES):
        body = "".join(
            f'<tr><th scope="row"><strong>{E(b)}</strong>{f"<span>{E(s)}</span>" if s else ""}</th>'
            + "".join(f"<td>{c}</td>" for c in cells)
            + "</tr>"
            for b, s, cells in rows
        )
        panels += f'<div role="tabpanel" id="panel-{k}" aria-labelledby="tab-{k}"{"" if i == 0 else " hidden"}><div class="table-wrap"><table class="tiers"><caption>{E(n)} benefits by tier</caption>{head}<tbody>{body}</tbody></table></div></div>'
    earn = [
        ("$5 on any slot or electronic bingo machine", "1 Tier-Point & Base-Point"),
        ("$10 on any video poker machine", "1 Tier-Point & Base-Point"),
        ("$1 in table game theoretical", "2 Tier-Points & Base-Points"),
        ("$1 in retail spend", "3 Tier-Points & Base-Points"),
    ]
    earn_rows = "".join(f"<tr><td>{E(a)}</td><td>{E(b)}</td></tr>" for a, b in earn)
    perks = [
        "$20 Free Bet",
        "$20 Free Play",
        "$50 Spa Credit",
        "$50 Food Credit",
        "1 Room Night",
        "$40 Free Bet",
        "$50 Free Play",
        "$100 Spa Credit",
        "$100 Food Credit",
        "$200 Free Bet",
        "$200 Spa and $200 Food Credit",
        "$300 Free Play",
        "$400 Spa Credit",
        "$400 Food Credit",
    ]
    return f"""
<section class="hero hero-rewards"><div class="hero-copy"><p class="eyebrow">Wind Creek Rewards</p><h1>Aspire to Greater Rewards</h1>
<p>Every point you earn brings you closer to dining, getaways, giveaways, hotel stays and more, at every Wind Creek casino in the U.S. and at Wind Creek Aruba and Curaçao. Free to join at Player Services.</p></div>
<div class="card-fan">{cards}</div></section>
<section class="wrap"><h2>How It Works</h2><h3>Play more, earn more</h3>
<p>Four tiers of Rewards. Tier benefits are based on your play from January 1st until December 31st each year. Base-Points earned on tables are multiplied by card level: Fantasy 8X, Delight 7X, Escape 6X and Play 5X.</p>
<div class="table-wrap narrow"><table class="earn"><caption>How points are earned</caption><thead><tr><th scope="col">Play</th><th scope="col">Earn</th></tr></thead><tbody>{earn_rows}</tbody></table></div>
<p class="fine">Electronic bingo machines, video poker and table games are not available at all locations. Theoretical factors include time, average bet and type of game. Retail points at Wind Creek-owned outlets for cash or card purchases.</p></section>
<section class="wrap"><h2>Tier Benefits</h2><div class="tabs" role="tablist" aria-label="Benefit type">{tabs}</div>{panels}</section>
<section class="wrap"><h2>Prime Perk Benefits</h2><p>Earn Prime Tokens as you reach each tier and trade them for a monthly perk for 12 months. Redeem a token by January 31st of the following year; tokens can be saved and combined for larger perks.</p>
<ul class="chips">{"".join(f"<li>{E(p)} per month</li>" for p in perks)}</ul></section>
<section class="wrap split"><img src="{img("rewards-faq.jpg")}" alt=""><div><h2>Express Offers</h2>
<p>Personalized offers based on your recent play, added straight to your Rewards account. You're notified by email, text, mail or the Casinoverse app. Offers usually last two to six weeks, one of each type at a time; redeem one and you're eligible for the next.</p>
<button type="button" class="btn-outline" data-demo>Sign in to see your offers</button></div></section>"""


def promo_card(p):
    return f"""<article class="promo"><img src="{img(p["pic"])}" alt=""><div class="promo-body"><h3><a href="{link("/bethlehem/promotions/" + p["slug"])}">{E(p["title"])}</a></h3>
<p class="when">{E(p["when"])}</p><p class="tag">{E(p["tag"])}</p><a class="btn-red" href="{link("/bethlehem/promotions/" + p["slug"])}">Learn More</a></div></article>"""


SVG = {
    "cal": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="1.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M4 9h16M8 3v4M16 3v4" stroke="currentColor" stroke-width="2"/><path d="M8 13h2M11 13h2M14 13h2" stroke="currentColor" stroke-width="2"/></svg>',
    "bed": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 18V8m0 6h18v4M21 14v-2a3 3 0 0 0-3-3h-7v5" fill="none" stroke="currentColor" stroke-width="2.2"/><circle cx="7" cy="11" r="2" fill="currentColor"/></svg>',
    "check": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 10 17l9-10" fill="none" stroke="currentColor" stroke-width="2.6"/></svg>',
    "bag": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="7" width="12" height="13" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 7V4h6v3M10 11v6M14 11v6" stroke="currentColor" stroke-width="2"/></svg>',
    "arrow": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>',
    "back": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12H5m6-6-6 6 6 6" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>',
    "x": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.4"/></svg>',
    "pen": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z" fill="currentColor"/></svg>',
    "access": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="4" r="2" fill="currentColor"/><path d="M5 8h14M12 8v6m0 0-3 8m3-8 3 8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
}
STEPS = [
    ("dates", "Dates of Stay", "cal"),
    ("rooms", "Accommodations", "bed"),
    ("confirm", "Confirm", "check"),
    ("booked", "Booked!", "bag"),
]
ON = ' class="on current"'
STEPPER = (
    '<ol class="wcb-stepper" aria-label="Booking steps">'
    + "".join(
        f'<li data-step="{k}"{ON if k == "dates" else ""}><span class="ico">{SVG[i]}</span><span class="lbl">{E(t)}</span></li>'
        for k, t, i in STEPS
    )
    + "</ol>"
)
STAY_FIELDS = f"""<div class="wcb-field"><span class="lab">Check-In</span><span class="val wcb-in ph">mm/dd/yyyy</span>{SVG["cal"]}</div>
<span class="wcb-arrow">{SVG["arrow"]}</span>
<div class="wcb-field"><span class="lab">Check-Out</span><span class="val wcb-out ph">mm/dd/yyyy</span>{SVG["cal"]}</div>"""
BOOKING_BODY = f"""<div class="wcb" data-kai-region="booking">
{STEPPER}
<section class="wcb-step" id="wcb-dates">
  <div class="wcb-cols">
    <div class="wcb-main">
      <h1 class="wcb-h">Select the Dates of Your Stay</h1>
      <div class="wcb-boxes"><div class="wcb-box wcb-dates">{STAY_FIELDS}</div>
        <div class="wcb-box"><div class="wcb-field wide"><span class="lab">Discount Code</span><span class="val ph">Enter Code</span></div></div></div>
      <div class="wcb-row"><button type="button" class="wcb-text" id="wcb-clear">{SVG["x"]} Clear Selection</button>
        <button type="button" class="wcb-primary" id="wcb-next" disabled>Next {SVG["arrow"]}</button></div>
      <div class="wcb-cal" aria-label="Calendar">
        <div class="wcb-cal-head"><button type="button" id="wcb-prev" aria-label="Previous month">&#8249;</button><h2 id="wcb-month">October 2026</h2><button type="button" id="wcb-nextm" aria-label="Next month">&#8250;</button></div>
        <div class="wcb-dow"><span>Sun</span><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span></div>
        <div class="wcb-days" id="wcb-days"></div>
      </div>
      <p class="wcb-fine">Prices shown are the "from" nightly prices on Wind Creek's booking engine on Oct 20, 2026, reproduced for this demo.</p>
    </div>
    <aside class="wcb-rewards" aria-label="Rewards sign-in (demo only)">
      <p>Are you a rewards member?</p>
      <h2>Sign in to be eligible for an award upon checkin</h2>
      <button type="button" class="wcb-outline" data-demo>Sign in using your PIN instead</button>
      <div class="wcb-fake"><span class="lab">Email</span><span class="input">Email</span></div>
      <div class="wcb-fake"><span class="lab">Password</span><span class="input">Enter Password</span></div>
      <button type="button" class="wcb-primary sm" data-demo>Sign In</button>
      <button type="button" class="wcb-plain" data-demo>Forgot Password?</button>
      <p class="wcb-fine">Demo only: sign-in is not part of this mockup and Kai never uses it.</p>
    </aside>
  </div>
</section>
<section class="wcb-step" id="wcb-rooms" hidden>
  <button type="button" class="wcb-text wcb-back" data-to="dates">{SVG["back"]} Back</button>
  <div class="wcb-cols">
    <div class="wcb-main">
      <h1 class="wcb-h">Select a Room</h1><p class="wcb-count" id="wcb-count">9 MATCHES</p>
      <div id="wcb-roomlist"></div>
    </div>
    <aside class="wcb-stay" aria-label="Your stay">
      <div class="wcb-stay-head"><h2>Your Stay</h2><button type="button" class="wcb-outline" id="wcb-change" data-to="dates">{SVG["pen"]} Change Dates</button></div>
      <div class="wcb-stay-box">{STAY_FIELDS}</div>
      <h3 class="wcb-lab">Number of Guests</h3>
      <div class="wcb-stepnum"><button type="button" id="wcb-minus" aria-label="Fewer guests">&minus;</button><span id="wcb-guests">1</span><button type="button" id="wcb-plus" aria-label="More guests">+</button></div>
      <h3 class="wcb-lab">Preferred Room Type</h3>
      <select id="wcb-type" aria-label="Preferred room type"><option>All</option><option>King</option><option>Queen</option><option>Suite</option></select>
      <label class="wcb-check"><input type="checkbox" id="wcb-accessible"> Accessible {SVG["access"]}</label>
    </aside>
  </div>
</section>
<section class="wcb-step" id="wcb-confirm" hidden>
  <button type="button" class="wcb-text wcb-back" data-to="rooms">{SVG["back"]} Back</button>
  <div class="wcb-cols"><div class="wcb-main"><h1 class="wcb-h">Confirm Your Stay</h1><div class="wcb-summary" id="wcb-summary"></div>
    <p class="wcb-fine">Demo mockup: on windcreek.com you'd enter guest and payment details here. This page collects nothing.</p>
    <button type="button" class="wcb-primary" id="wcb-book">Complete Reservation (demo) {SVG["arrow"]}</button></div>
    <aside class="wcb-rewards"><p>Questions about your stay?</p><h2>Call 877-726-3777</h2></aside></div>
</section>
<section class="wcb-step" id="wcb-booked" hidden>
  <div class="wcb-done"><span class="ico">{SVG["bag"]}</span><h1 class="wcb-h">Booked!</h1><p>Demo confirmation <strong id="wcb-conf"></strong>. No reservation was made and nothing was charged.</p>
  <a class="wcb-outline" href="{BASE}/bethlehem">Back to Wind Creek Bethlehem</a></div>
</section>
</div>
<script src="{BASE}/assets/booking-data.js"></script><script src="{BASE}/assets/bookflow.js" defer></script>"""


def build() -> list[tuple[str, str]]:
    pages = []
    add = lambda *a, **k: pages.append(page(*a, **k))  # noqa: E731

    # home
    loc_cards = "".join(
        f'<a class="loc" href="{link("/" + s)}"><img src="{img(pic)}" alt=""><span class="loc-label"><small>{E(region)}</small><h3>{E(n)}</h3></span></a>'
        for s, n, region, pic in LOCS
    )
    rewards_band = f"""<section class="rewards-band" style="background-image:url({img("bg-red.jpg")})"><div><h2>Wind Creek Rewards</h2><p class="eyebrow light">More points. More rewards. More Winning Moments.</p>
<p>Every point you earn brings you closer to amazing dining experiences, incredible getaways and giveaways, luxurious hotel stays, and more.</p><a class="btn-white" href="{link("/rewards")}">Learn More</a></div>
<div class="card-fan">{"".join(f'<img src="{img("card-" + t.lower() + ".png")}" alt="{t} card">' for t, _ in TIERS)}</div></section>"""
    add(
        "/",
        "Wind Creek Casinos & Resorts",
        hero(
            "Wind Creek Casinos & Resorts",
            "Elevate Your Every Experience",
            "Every Wind Creek Casino is a player's paradise. With properties where you already live and play, and more on the way, we make it more rewarding to find your Winning Moment. Explore our locations across the United States and the Caribbean.",
            img("home-hero.jpg"),
        )
        + f'<section class="wrap">{section_head("", "Locations", ("View All Locations", "/locations"))}<div class="locs-grid">{loc_cards}</div></section>'
        + rewards_band,
    )
    # locations
    blurbs = {
        "atmore": "Over 1,700 games, a AAA Four Diamond resort, spa, outdoor amphitheater, infinity pool, movie theatre, RV park and FIRE, the top steakhouse in Alabama.",
        "bethlehem": "Our Pennsylvania flagship: over 3,000 slots, 200 table games, a AAA Four-Diamond hotel, spa, live entertainment, sportsbook, outlet shopping and award-winning restaurants.",
        "montgomery": "A 65,000-square-foot casino with over 2,200 games, B.B. King's Blues Club and Itta Bena fine dining.",
        "wetumpka": "Over 2,000 of the newest games, a AAA Four Diamond hotel and FIRE, the top-rated steakhouse in Alabama.",
        "aruba": "Two casinos, Wind Creek Crystal and Wind Creek Seaport, and a private island where flamingos roam free.",
        "curacao": "Casino and resort in Willemstad on the Caribbean coast, with a Renaissance hotel, shopping, bars and restaurants.",
        "miami": "Magic City Casino: over 800 slot machines, electronic table games, poker and Miami's best outdoor concert venue.",
        "chicagosouthland": "1,400+ slots, table games, a Food Bazaar by Fabio Viviani, Alto Italian steakhouse and more, with a free daily Chinatown shuttle.",
    }
    loc_list = "".join(
        f'<article class="loc-row"><img src="{img(pic)}" alt=""><div><p class="eyebrow">{E(region)}</p><h2><a href="{link("/" + s)}">{E(n)}</a></h2><p>{E(blurbs[s])}</p><a class="btn-red" href="{link("/" + s)}">Explore Wind Creek {E(n)}</a></div></article>'
        for s, n, region, pic in LOCS
    )
    add(
        "/locations",
        "Locations",
        f'<section class="wrap"><p class="eyebrow">Wind Creek Hospitality</p><h1 class="page-title">Locations</h1>{loc_list}</section>',
    )
    add("/rewards", "Wind Creek Rewards", rewards_body())
    add("/bethlehem/casino/rewards", "Wind Creek Rewards", rewards_body(), prop=True)

    # Bethlehem
    tiles = [
        ("Hotel & Resort", "A Luxurious Escape", img("tile-hotel.jpg"), "/bethlehem/resort/hotel-rooms-and-suites"),
        ("Dining", "A Taste for Every Palate", img("tile-dining.jpg"), "/bethlehem/dining"),
        ("Spa at Wind Creek", "Melt Away Stress", img("tile-spa.jpg"), "/bethlehem/resort/spa"),
        ("Entertainment", "Fun for Everyone", img("tile-ent.jpg"), "/bethlehem/entertainment"),
        ("Event Planning", "Let's Get Together!", img("tile-events.jpg"), "/demo-only"),
    ]
    tile_html = "".join(
        f'<a class="tile" href="{link(h)}"><img src="{p}" alt=""><span><small>{E(a)}</small><strong>{E(b)}</strong><em>Explore {E(a)}</em></span></a>'
        for a, b, p, h in tiles
    )
    sched = [
        ("Chop House", "Tue – Sun from 5PM (closed Mon)"),
        ("Urban Table", "Wed – Sun from 11AM"),
        ("Chopstick", "Daily 12:30PM – 1:30AM"),
        ("Spa at Wind Creek", "Tue – Sun (closed Mon)"),
        ("Poker Room", "24 hours"),
        ("Kids Quest", "Daily from 3PM (11AM weekends)"),
    ]
    add(
        "/bethlehem",
        "Wind Creek Bethlehem",
        hero(
            "Welcome to Wind Creek Bethlehem",
            "Hottest Games. Highest Payouts. Epic Rewards.",
            "Pennsylvania's premier integrated resort on the historic Bethlehem Steel site: casino, AAA Four-Diamond hotel, spa, dining, entertainment and The Outlets, 90 minutes from New York City.",
            img("beth-hero.jpg"),
            ("View Promotions", "/bethlehem/promotions"),
        )
        + f'<section class="wrap">{section_head("Promotions & Events", "What's Happening at Wind Creek", ("View Calendar", "/bethlehem/promotions"))}<div class="carousel">{"".join(promo_card(p) for p in PROMOS)}</div></section>'
        + f'<section class="wrap">{section_head("", "About Wind Creek Bethlehem")}<div class="tiles">{tile_html}</div></section>'
        + f'<section class="wrap"><h2>Property Schedule</h2>{hours(sched)}<a class="more" href="{link("/bethlehem/property-schedule")}">Full property schedule</a></section>'
        + rewards_band.replace(link("/rewards"), link("/bethlehem/casino/rewards")),
        prop=True,
    )
    add(
        "/bethlehem/promotions",
        "Promotions & Events",
        f'<section class="wrap"><p class="eyebrow">Wind Creek Bethlehem</p><h1 class="page-title">Promotions &amp; Events</h1><p>There\'s always something happening at Wind Creek Bethlehem. Check our calendar for casino promotions with giveaways, FREE Play and more.</p><h2>Featured Promotions</h2><div class="promo-list">{"".join(promo_card(p) for p in PROMOS)}</div></section>',
        prop=True,
    )
    for p in PROMOS:
        secs = "".join(f"<h2>{E(h)}</h2><p>{E(t)}</p>" for h, t in p["body"])
        add(
            f"/bethlehem/promotions/{p['slug']}",
            p["title"],
            f'<section class="wrap promo-detail"><p class="eyebrow">Promotions &amp; Events</p><h1 class="page-title">{E(p["title"])}</h1><img class="banner" src="{img(p["pic"])}" alt=""><p class="lead">{E(p["lead"])}</p><p class="when">{E(p["when"])}</p>{secs}<p class="fine">Must be 21 or older. Gambling problem? Call 1-800-GAMBLER.</p><a class="more" href="{link("/bethlehem/promotions")}">Back to Promotions &amp; Events</a></section>',
            prop=True,
        )
    games = [
        ("Slots", "The latest, greatest and most sought-after slot machines.", img("c-slots.jpg")),
        (
            "Table Games",
            "$10 live blackjack all day, every day, plus roulette, Three Card Poker, Caribbean Stud and more.",
            gen("casino-floor.jpg"),
        ),
        ("Poker Room", "The new and improved poker room is open 24 hours.", img("c-poker.jpg")),
        ("Live Dealer Stadium Gaming", "$5 minimum. All day. Every day.", img("c-live.jpg")),
        ("Sportsbook", "Bar, grill and lounge seating for every game.", img("c-sportsbook.jpg")),
    ]
    add(
        "/bethlehem/casino",
        "Bethlehem Casino",
        hero(
            "Bethlehem Casino",
            "The Casino That Goes All In for Guests",
            "Over 3,000 slots and 200+ table games on a floor built for comfort, with monthly promotions. Must be 21 or older to gamble.",
            img("c-slots.jpg"),
        )
        + f'<section class="wrap"><h2>Game Offerings</h2><div class="cards">{"".join(card(a, b, c) for a, b, c in games)}</div></section>',
        prop=True,
    )
    dcards = "".join(card(d["name"], d["short"], d["pic"], f"/bethlehem/dining/{d['slug']}") for d in DINING)
    add(
        "/bethlehem/dining",
        "Bethlehem Dining",
        hero(
            "Bethlehem Dining",
            "A Taste for Every Palate",
            "From quick bites to signature culinary creations, Wind Creek Bethlehem's restaurants hit the spot.",
            img("dining-hero.jpg"),
        )
        + f'<section class="wrap"><div class="cards">{dcards}</div></section>',
        prop=True,
    )
    for d in DINING:
        menu = ""
        for sec, items in d.get("menu", []):
            menu += (
                f'<h3>{E(sec)}</h3><ul class="menu">'
                + "".join(f"<li><span>{E(n)}</span><span>{E(pr)}</span></li>" for n, pr in items)
                + "</ul>"
            )
        menu_html = (
            f'<section class="wrap"><h2>Menu</h2><p class="fine">Selected items; prices as published on windcreek.com.</p>{menu}</section>'
            if menu
            else ""
        )
        pic2 = img("d-chophouse-room.jpg") if d["slug"] == "chop-house-at-wind-creek" else d["pic"]
        add(
            f"/bethlehem/dining/{d['slug']}",
            d["name"],
            hero("Bethlehem Dining", d["name"], d["short"], pic2)
            + f'<section class="wrap two-col"><div><h2>Information</h2>{info_box([("Getting Here", E(d["where"]) + "<br>77 Wind Creek Blvd, Bethlehem, PA 18015"), ("Phone", E(d["phone"]))])}{f"<p class=note>{E(d.get('note'))}</p>" if d.get("note") else ""}<button type="button" class="btn-red" data-demo>Find a Table</button></div><div><h2>Hours</h2>{hours(d["hours"])}</div></section>'
            + menu_html,
            prop=True,
        )
    room_cards = "".join(
        card(
            n,
            d,
            p,
            meta=m,
            extra='<a class="btn-outline" href="' + link("/bethlehem/book-now") + '">Check Your Rate</a>',
        )
        for n, m, p, d in ROOMS
    )
    add(
        "/bethlehem/resort/hotel-rooms-and-suites",
        "Hotel Rooms & Suites",
        hero(
            "Hotel Rooms & Suites",
            "Find Your Luxurious Escape",
            "Our AAA Four-Diamond hotel has two towers with over 550 rooms, including 50 suites, with premier bedding, free high-speed internet, concierge services and the spa, all under one roof.",
            img("hotel-hero.jpg"),
            ("Book Your Stay", "/bethlehem/book-now"),
        )
        + f'<section class="wrap"><h2>Hotel Info</h2>{info_box([("Check-in", "4PM"), ("Check-out", "11AM"), ("Pets", "Pet and animal-free property; ADA service animals welcome")])}</section>'
        + f'<section class="wrap"><h2>Rooms &amp; Suites</h2><div class="cards">{room_cards}</div></section>'
        + f'<section class="wrap gallery">{"".join(f"<img src={img(f'h-gal{i}.jpg')} alt=''>" for i in range(1, 6))}</section>',
        prop=True,
    )
    pk = ""
    for n, inc, prices, pic in PACKAGES:
        pr = "".join(f"<li><span>{E(d)}</span><strong>Starting at {E(v)}</strong></li>" for d, v in prices)
        pk += f'<article class="card package"><img src="{pic}" alt=""><div class="card-body"><h3>{E(n)}</h3><p class="meta">Package includes:</p><ul>{"".join(f"<li>{E(i)}</li>" for i in inc)}</ul><ul class="prices">{pr}</ul><button type="button" class="btn-red" data-demo>Call to Book: 877-726-3777</button></div></article>'
    add(
        "/bethlehem/resort/hotel-packages",
        "Hotel Packages",
        hero(
            "Bethlehem Resort",
            "Hotel Packages",
            "So many ways to play: gaming, dining, shopping or the spa, with a night at our AAA Four-Diamond hotel. Call to book: 877-726-3777.",
            img("h-robes.jpg"),
        )
        + f'<section class="wrap"><div class="cards">{pk}</div><p class="fine">Prices are per night, as published on windcreek.com; Chop House is closed Mondays and Urban Table Mondays and Tuesdays.</p></section>',
        prop=True,
    )
    add("/bethlehem/book-now", "Book Now", BOOKING_BODY, prop=True)
    add(
        "/bethlehem/resort/spa",
        "Spa at Wind Creek",
        hero(
            "Spa at Wind Creek Bethlehem",
            "Feel the Stressors of Every Day Melt Away",
            "14,000 square feet of calm: relaxation pools, swinging chairs over a wading pool, infrared saunas, aromatherapy steam rooms and views of Bethlehem.",
            img("spa-hero.jpg"),
        )
        + f'<section class="wrap two-col"><div><h2>Reservations</h2>{info_box([("Call to book", "877-726-3777")])}<div class="cards">{card("Elemis Pro-Glow Age Defy", "Holistic facial, 50 minutes, $200.", gen("spa-relaxation-lounge.jpg"))}</div></div><div><h2>Hours</h2>{hours([("Mon", "Closed"), ("Tue", "11AM – 6PM"), ("Wed – Fri", "11AM – 8PM"), ("Sat", "8AM – 8PM"), ("Sun", "8:30AM – 8PM")])}</div></section>',
        prop=True,
    )
    add(
        "/bethlehem/resort/amenities",
        "Resort Amenities",
        hero(
            "Bethlehem Resort",
            "Resort Amenities",
            "A heated indoor pool, 24-hour fitness center, the W Store and in-room dining.",
            gen("resort-exterior-dusk.jpg"),
        )
        + f'<section class="wrap"><div class="cards">{card("Pool", "Heated indoor pool, daily 7AM – 10PM.", img("h-gal3.jpg"))}{card("Fitness Center", "Open 24 hours.", img("h-gal4.jpg"))}{card("W Store", "Apparel, collectibles, snacks and travel needs. Sun – Thu 9AM – 10PM, Fri – Sat 9AM – 12AM.", gen("outlets-shopping.jpg"))}{card("In-Room Dining", "Daily 7AM – 9PM.", img("h-gal5.jpg"))}</div></section>',
        prop=True,
    )
    add(
        "/bethlehem/resort/kids-quest-and-cyber-quest",
        "Kids Quest & Cyber Quest",
        hero(
            "Family-Friendly Gaming",
            "Kids Quest & Cyber Quest",
            "Hourly child care and entertainment for ages 30 months to 12 years, plus the Cyber Quest arcade.",
            img("kq-front.jpg"),
        )
        + f'<section class="wrap two-col"><div><h2>Rates &amp; Discounts</h2>{info_box([("Hourly child care", "$13.50 per hour, ages 30 months – 12 years"), ("Rewards discount", "Play 5% · Escape 10% · Delight 15% · Fantasy 20%"), ("Kids Quest", "610-625-2300"), ("Cyber Quest", "610-625-2306")])}</div><div><h2>Hours</h2>{hours([("Mon – Thu", "3PM – 10PM"), ("Fri", "3PM – 12AM"), ("Sat", "11AM – 12AM"), ("Sun", "11AM – 10PM")])}</div></section>'
        + f'<section class="wrap gallery">{"".join(f"<img src={p} alt=''>" for p in (img("e-kidsquest.jpg"), gen("kids-activity-center.jpg"), img("p-kids.jpg")))}</section>',
        prop=True,
    )
    ent = [
        (
            "Event Center",
            "A-list, nationally known acts and events of all sizes.",
            img("e-eventcenter.jpg"),
            "/bethlehem/entertainment/event-center",
        ),
        (
            "Nightlife",
            "Molten Lounge with free live entertainment, MIXX, and Coil on the casino floor.",
            img("e-nightlife.jpg"),
            None,
        ),
        ("The Outlets", "Upscale brands in Pennsylvania's premier outlet center.", img("e-outlets.jpg"), None),
        (
            "Kids Quest & Cyber Quest",
            "Family fun and arcade games.",
            img("e-kidsquest.jpg"),
            "/bethlehem/resort/kids-quest-and-cyber-quest",
        ),
        (
            "Angry Jack's Axe Throwing Club",
            "Grab your friends for axe throwing at The Outlets.",
            img("e-axe.jpg"),
            None,
        ),
        (
            "Twisted Tees",
            "Pub fare, local brews and golf simulators.",
            img("d-twisted.jpg"),
            "/bethlehem/dining/twisted-tees",
        ),
    ]
    add(
        "/bethlehem/entertainment",
        "Bethlehem Entertainment",
        hero(
            "Bethlehem Entertainment",
            "Fun for Everyone",
            "Concerts, nightlife, shopping and family fun.",
            img("e-club.jpg"),
        )
        + f'<section class="wrap"><div class="cards">{"".join(card(a, b, c, h) for a, b, c, h in ent)}</div></section>',
        prop=True,
    )
    add(
        "/bethlehem/entertainment/event-center",
        "Event Center",
        hero(
            "Entertainment",
            "Wind Creek Event Center",
            "Your favorite names in music, comedy and sports. Box office 610-297-7414, or buy online.",
            gen("event-center-concert.jpg"),
        )
        + f'<section class="wrap two-col"><div><h2>Getting Here</h2>{info_box([("Location", "Northwest, street level · 77 Wind Creek Blvd")])}<button type="button" class="btn-red" data-demo>Buy Tickets</button></div><div><h2>Box Office Hours</h2>{hours([("Mon – Fri", "10AM – 4PM"), ("Sat", "10AM – 2PM"), ("Show days", "Extended hours")])}</div></section>',
        prop=True,
    )
    add(
        "/bethlehem/getting-here",
        "Getting Here",
        hero(
            "Bethlehem",
            "Getting Here",
            "77 Wind Creek Blvd, Bethlehem, PA 18015: about 90 minutes from New York City and an hour from Philadelphia.",
            img("loc-bethlehem.jpg"),
        )
        + '<section class="wrap"><h2>Parking and Accessibility</h2><p>3,300 spaces in the self-park garage and 1,400 on the surface lot, plus valet and EV charging. All entrances are accessible. Mobility scooters rent for $45 a day (hotel valet 484-777-7973, casino valet 484-777-7547).</p><h2>By Bus</h2><p>Trans-Bridge Lines runs daily round trips from the Port Authority Bus Terminal in New York (610-868-6001). Scheduled line runs serve the tri-state area, and motor coach groups are welcome (877-726-3777).</p></section>',
        prop=True,
    )
    faq = [
        ("Where is Wind Creek Bethlehem?", "77 Wind Creek Blvd, Bethlehem, PA 18015, about 90 minutes from NYC."),
        (
            "Are minors allowed in Chop House or Chopstick?",
            "No. Minors can't be escorted across the casino floor; they're welcome at Urban Table, Steelworks or The Market via The Outlets or hotel entrance with an adult.",
        ),
        ("Is smoking allowed?", "In designated areas of the gaming floor. Cigars and pipes are not allowed."),
        ("Are pets allowed?", "No. ADA service animals are welcome."),
        ("Do you have a Rewards card?", "Yes, and it's free to join at Player Services."),
        (
            "What games do you offer?",
            "Over 3,000 slots, 200+ table games, live dealer stadium gaming, poker and a sportsbook.",
        ),
        (
            "How do Express Offers work?",
            "Offers based on your play are added to your Rewards account; redeem one to become eligible for the next.",
        ),
    ]
    add(
        "/bethlehem/faq",
        "Frequently Asked Questions",
        '<section class="wrap"><p class="eyebrow">Wind Creek Bethlehem</p><h1 class="page-title">Frequently Asked Questions</h1>'
        + "".join(f"<details class=faq><summary><h2>{E(q)}</h2></summary><p>{E(a)}</p></details>" for q, a in faq)
        + "</section>",
        prop=True,
    )
    full_sched = [
        ("Poker Room", "Daily, 24 hours"),
        ("Chop House", "Mon closed · Tue–Fri & Sun 5PM–10PM · Sat 5PM–11PM"),
        ("Urban Table", "Mon–Tue closed · Wed–Thu 11AM–10PM · Fri–Sat 11AM–11PM · Sun 11AM–10PM"),
        ("Chopstick", "Daily 12:30PM–1:30AM"),
        ("Steelworks Buffet", "Mon–Fri 12PM–4PM & 5PM–8PM · Sat 2PM–8PM · Sun 12PM–5PM"),
        ("Twisted Tees", "Mon closed · Tue–Thu 4PM–10PM · Fri 11AM–10PM · Sat 11AM–11PM · Sun 11AM–8PM"),
        ("Sweet Revenge", "Mon–Tue closed · Wed–Thu 10AM–7PM · Fri–Sat 10AM–8PM · Sun 10AM–5PM"),
        ("Spa at Wind Creek", "Mon closed · Tue 11AM–6PM · Wed–Fri 11AM–8PM · Sat 8AM–8PM · Sun 8:30AM–8PM"),
        ("Pool", "Daily 7AM–10PM"),
        ("Kids Quest", "Mon–Thu 3PM–10PM · Fri 3PM–12AM · Sat 11AM–12AM · Sun 11AM–10PM"),
    ]
    add(
        "/bethlehem/property-schedule",
        "Property Schedule",
        f'<section class="wrap"><p class="eyebrow">Wind Creek Bethlehem</p><h1 class="page-title">Property Schedule</h1>{hours(full_sched)}</section>',
        prop=True,
    )

    # other properties
    other = {
        "atmore": (
            "Make Every Moment Your Winning Moment",
            [
                ("Win a New Acura Integra", "October 31st • 5PM – 9PM"),
                ("Monster Mash Bash", "October 31st • 8pm"),
                ("Claim the Crown", "Sign-Up Starts September 1st"),
            ],
        ),
        "wetumpka": (
            "Make Every Moment Your Winning Moment",
            [
                ("Wicked Double Winnings", "October 10th & 31st • 7pm – 10pm"),
                ("Winners Circle Plus", "December 27th • 2pm – 7pm"),
                ("Monster Mash Bash", "October 31st • 8pm"),
            ],
        ),
        "montgomery": (
            "Make Every Moment Your Winning Moment",
            [
                ("Operation Cash Money", "Fridays in October • 7pm – 9pm"),
                ("Smoking Hot Ladies Night", "Thursdays in October • 5pm – 8pm"),
                ("Bloody Good Time", "October 31st • 7pm – 10pm"),
            ],
        ),
        "chicagosouthland": (
            "Make Every Moment Your Winning Moment",
            [
                ("$100K Mystique at the Manor", "October 31st • 8pm – 11pm"),
                ("Pumpkin Patch Scratch", "Wednesdays in October • 2pm – 8pm"),
                ("New Player Rewards", "Offer Valid Now"),
            ],
        ),
        "aruba": (
            "Elevate Your Game to Fabulous",
            [
                ("Entangled Luck", "Tuesdays in October • 6pm – 8pm"),
                ("Mummy Free Play", "Wednesdays in October • 6pm – 8pm"),
                ("Monster Mash Bash", "October 31st • 9pm"),
            ],
        ),
        "curacao": ("Elevate Your Game to Fabulous", [("Claim the Crown", "Sign-Up Starts September 1st")]),
        "miami": (
            "Magic City Casino",
            [("Claim the Crown", "Sign-Up Starts September 1st"), ("Monster Mash Bash", "October 31st")],
        ),
    }
    for s, n, _region, pic in LOCS:
        if s == "bethlehem":
            continue
        tag, promos = other[s]
        plist = "".join(
            f'<article class="card"><div class="card-body"><h3>{E(t)}</h3><p class="when">{E(w)}</p></div></article>'
            for t, w in promos
        )
        body = (
            hero(f"Welcome to Wind Creek {n}", tag, blurbs[s], img(pic))
            + f'<section class="wrap"><h2>Promotions &amp; Events</h2><div class="cards">{plist}</div><p class="fine">This mockup focuses on Wind Creek Bethlehem; other properties are summarized.</p></section>'
        )
        add(f"/{s}", f"Wind Creek {n}", body)
        add(
            f"/{s}/promotions",
            f"Promotions & Events · {n}",
            f'<section class="wrap"><p class="eyebrow">Wind Creek {E(n)}</p><h1 class="page-title">Promotions &amp; Events</h1><div class="cards">{plist}</div></section>',
        )
    add(
        "/responsible-gambling",
        "Responsible Gambling",
        '<section class="wrap"><h1 class="page-title">Responsible Gambling</h1><p>Gambling should be fun. Set limits before you start, and never gamble to win back losses, pay bills or escape problems.</p><h2>How to Get Help</h2><p>If you or someone you know has a gambling problem, call 1-800-GAMBLER (free and confidential, 24/7) or the National Problem Gambling Helpline Network at 1-800-522-4700.</p></section>',
    )
    add(
        "/demo-only",
        "Demo only",
        '<section class="wrap"><h1 class="page-title">Not part of this demo</h1><p>This page isn\'t included in the mockup. On windcreek.com it would be here.</p></section>',
    )
    add(
        "/credits",
        "Image credits",
        '<section class="wrap"><h1 class="page-title">Image credits</h1><p>Photos in <code>/windcreek/img/</code> are Wind Creek Hospitality\'s own, reproduced from windcreek.com for this private demo. Photos in <code>/windcreek/img/gen/</code> were generated for this mockup (Gemini image model) to fill gaps, and do not show Wind Creek venues.</p></section>',
    )
    return pages


def main():
    out = sys.argv[1]
    for path, doc in build():
        d = os.path.join(out, path.strip("/"))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(doc)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "bookflow.js")) as f, open(os.path.join(out, "assets", "bookflow.js"), "w") as g:
        g.write(f.read())
    with open(os.path.join(here, "..", "..", "knowledge", "windcreek", "booking.json")) as f:
        data = f.read()
    with open(os.path.join(out, "assets", "booking-data.js"), "w") as g:
        g.write("window.WC_BOOKING = " + data.strip() + ";\n")
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site.css")
    with open(src) as f, open(os.path.join(out, "assets", "site.css"), "w") as g:
        g.write(f.read())
    print(f"{len(build())} pages -> {out}")


if __name__ == "__main__":
    main()
