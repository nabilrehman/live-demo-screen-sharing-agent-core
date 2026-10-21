"""Builds the Hard Rock Hotels demo mockup: static pages that follow hotel.hardrock.com's layout (captured 2026-10-21,
see ref/spec.md), with the LiveKit voice concierge embed on every page. Content is summarized from the public site
(knowledge/hardrock/); images are Hard Rock's own public photos (img/) plus generated fillers (img/gen/). A private
demo for Hard Rock Hotels only: every page carries the mockup banner, noindex and an access-code gate. No sign-in,
payment or personal-data inputs: those controls are inert "Demo only" buttons, and the booking engine stops before
guest details.

  python3 mockup/hardrock/build.py <out dir, e.g. ../vflights/public/hardrock>
"""

from __future__ import annotations

import html
import json
import os
import sys

ACCESS_CODE = "HARDROCK-DEMO"  # the gate's code: pages show only with ?code=<this> (kept in sessionStorage)
BASE = "/hardrock"  # where the mockup is served
EMBED = '<script src="/embed/hardrock/livekit.js" data-site-root="/hardrock/" data-brain="hardrock-grok" defer></script>'
HERE = os.path.dirname(os.path.abspath(__file__))
KNOW = os.path.join(HERE, "..", "..", "knowledge", "hardrock")
E = html.escape

# Hard Rock's own photos (img/, from hotel.hardrock.com) by role; a missing one falls back to a generated filler.
REAL: dict[str, str] = {}
if os.path.exists(os.path.join(HERE, "images.json")):
    with open(os.path.join(HERE, "images.json")) as f:
        REAL = json.load(f)


def img(key: str, fallback: str = "") -> str:
    if key in REAL:
        return f"{BASE}/img/{REAL[key]}"
    return f"{BASE}/img/gen/{fallback or key}"


def link(path: str) -> str:
    return BASE + (path if path != "/" else "/")


def demo_btn(label: str, cls: str = "btn-line dark") -> str:
    return f'<button type="button" class="{cls}" data-demo>{E(label)}</button>'


# ---------- nav ----------
NAV = [
    (
        "Destinations",
        "/destinations",
        [
            ("North America", "/destinations#north-america"),
            ("Central & South America, Caribbean", "/destinations#caribbean"),
            ("Europe, Middle East & Africa", "/destinations#europe"),
            ("Asia Pacific", "/destinations#asia"),
        ],
    ),
    (
        "Hotels & Resorts",
        "/hotels-and-resorts",
        [
            ("Overview", "/hotels-and-resorts"),
            ("All-Inclusive Resorts", "/hotels-and-resorts#all-inclusive"),
            ("City Hotels", "/hotels-and-resorts#city"),
            ("Resorts", "/hotels-and-resorts#resorts"),
        ],
    ),
    ("Casinos", "/demo-only", []),
    ("Experience", "/hotels-and-resorts#experience", [("Unity by Hard Rock", "/unity"), ("Sound of Your Stay®", "/hotels-and-resorts#experience")]),
    ("Meetings & Weddings", "/demo-only", []),
    ("Offers", "/offers", []),
]
HOTELS = {
    "new-york": {
        "name": "Hard Rock Hotel New York",
        "city": "New York",
        "addr": "159 West 48th Street, New York City, New York 10036, United States",
        "phone": "+1 212-970-1200",
    },
    "orlando": {
        "name": "Hard Rock Hotel Orlando",
        "city": "Orlando",
        "addr": "5800 Universal Blvd, Orlando, Florida 32819, United States",
        "phone": "+1 407-503-2000",
    },
}
HOTEL_NAV = [
    ("Rooms & Suites", "rooms-and-suites"),
    ("Amenities", "amenities"),
    ("Eat & Drink", "eat-and-drink"),
    ("Meetings & Events", None),
    ("Area Guide", "area-guide"),
    ("Offers", "offers"),
    ("Gallery", None),
]
LOGO = f'<img src="{BASE}/img/brand/logo.png" alt="Hard Rock Hotel &amp; Casino">'
HOTEL_LOGO = f'<img src="{BASE}/img/brand/logo-hotel.png" alt="Hard Rock Hotel">'


def util_bar(hotel: str | None) -> str:
    if hotel:
        left = f'<a href="{link("/")}">Hard Rock Hotels</a><span class="sep"></span><a href="{link("/unity")}">Unity™ By Hard Rock</a>'
        book = link(f"/book?hotel={hotel}") if hotel == "new-york" else "#"
    else:
        left = (
            '<button type="button" data-demo>Hardrock.com</button><span class="sep"></span>'
            + "".join(f'<button type="button" data-demo>{t}</button>' for t in ("Cafes",))
            + f'<a class="on" href="{link("/")}">Hotels</a>'
            + "".join(f'<button type="button" data-demo>{t}</button>' for t in ("Casinos", "Shop", "Games", "Bet Online"))
        )
        book = link("/book?hotel=new-york")
    book_attr = ' data-demo' if book == "#" else ""
    return f"""<div class="util"><div class="brands">{left}</div>
<div class="right"><span class="welcome">Welcome,&nbsp;<button type="button" data-demo><u>Sign In</u></button></span>
<span class="brg"><img src="{BASE}/img/brand/best-rate.png" alt="Best Rate Guarantee"></span><a class="book" href="{book}"{book_attr}>Book Now</a><a class="unity" href="{link("/unity")}">Unity™ Loyalty Program</a></div></div>"""


def header(hotel: str | None = None, cur: str = "") -> str:
    if hotel:
        h = HOTELS[hotel]
        items = [f'<li class="{"cur" if cur == "" else ""}"><a href="{link("/" + hotel)}">{E(h["city"])}</a></li>']
        for label, slug in HOTEL_NAV:
            href = link(f"/{hotel}/{slug}") if slug else link("/demo-only")
            items.append(f'<li class="{"cur" if cur == slug else ""}"><a href="{href}">{E(label)}</a></li>')
        nav = "".join(items)
        logo = f'<a class="logo" href="{link("/" + hotel)}">{HOTEL_LOGO}<span class="hname">{E(h["city"])}</span></a>'
    else:
        out = []
        for label, href, sub in NAV:
            mega = (
                '<ul class="mega">' + "".join(f'<li><a href="{link(h)}">{E(t)}</a></li>' for t, h in sub) + "</ul>"
                if sub
                else ""
            )
            out.append(f'<li class="{"cur" if cur == href else ""}"><a href="{link(href)}">{E(label)}</a>{mega}</li>')
        nav = "".join(out)
        logo = f'<a class="logo" href="{link("/")}">{LOGO}</a>'
    return f"""
<div class="demo-banner" role="note">Demo mockup prepared by LiveKit for Hard Rock Hotels, not the official site.</div>
{util_bar(hotel)}
<header class="site-header">
  <div class="mainbar">{logo}
    <button type="button" class="burger" aria-label="Menu" onclick="document.body.classList.toggle('menu-open')"><i></i><i></i><i></i></button>
    <nav aria-label="Primary"><ul class="nav">{nav}</ul></nav>
  </div>
</header>"""


def footer(hotel: str | None = None) -> str:
    if hotel:
        h = HOTELS[hotel]
        top = f"""<section class="addr-band"><h2>{E(h["name"])}</h2><p>{E(h["addr"])}<br>Phone: {E(h["phone"])}</p></section>"""
        cols = '<ul><li><a href="#" data-demo>Careers</a></li><li><a href="#" data-demo>Event Calendar</a></li><li><a href="#" data-demo>Gallery</a></li></ul><ul><li><a href="#" data-demo>Contact</a></li><li><a href="{}">Hotel Policies</a></li><li><a href="#" data-demo>Blog</a></li></ul>'.format(
            link(f"/{hotel}/amenities#hotel-policies")
        )
        flogo = f'<div class="flogo-wrap">{HOTEL_LOGO}<span class="hname">{E(h["city"])}</span></div>'
    else:
        top = ""
        cols = "<ul>" + "".join(f'<li><a href="#" data-demo>{t}</a></li>' for t in ("News", "Contact Us", "Careers", "Our Story", "Investors")) + "</ul><ul>" + "".join(f'<li><a href="#" data-demo>{t}</a></li>' for t in ("Residences", "Travel Advisors", "Corporate Travel", "Accessibility", "Sitemap")) + "</ul>"
        flogo = f'<div class="flogo-wrap">{LOGO}</div>'
    return f"""{top}
<section class="connect" aria-label="Stay connected"><div class="wrap"><div><h2>Stay<br>Connected</h2><p>Join our email list to receive special offers.</p></div>
<div><div class="row"><span class="fake" aria-hidden="true"></span><button type="button" data-demo>Sign Up</button></div>
<small>☐ I agree that I would like to receive info about Hard Rock International products and special offers by email. (Demo only: this mockup collects nothing.)</small></div></div></section>
<footer class="site-footer">
  <div class="fgrid">{flogo}<div class="cols">{cols}</div>
    <div class="social" aria-label="Social links"><span>f</span><span>𝕏</span><span>▶</span><span>◎</span></div></div>
  <div class="awards">{"".join(f'<img src="{BASE}/img/brand/{a}.png" alt="{t}">' for a, t in (("award-tl", "Travel + Leisure World's Best Awards"), ("award-jdp", "J.D. Power"), ("award-usn", "U.S. News Best Hotels"), ("award-ftg", "Forbes Travel Guide Recommended")))}</div>
  <p class="copy">Copyright © (2019-2026), Hard Rock International (USA), Inc.</p>
  <ul class="legal"><li><a href="#" data-demo>Hard Rock</a></li><li><a href="#" data-demo>Philanthropy</a></li><li><a href="#" data-demo>Legal Disclaimer</a></li><li><a href="#" data-demo>Privacy Policy</a></li><li><a href="#" data-demo>Terms &amp; Conditions</a></li></ul>
  <p class="credit">Demo mockup prepared by LiveKit for Hard Rock Hotels. Content and photos © Hard Rock International, reproduced from hotel.hardrock.com for a private demo to Hard Rock only. Some supplementary photos were generated for this mockup and are listed in <a href="{link("/credits")}">image credits</a>.</p>
</footer>
<a class="phone-book" href="{link("/book?hotel=" + (hotel or "new-york"))}">Book Now</a>"""


GATE = f"""<script>(function(){{var C={ACCESS_CODE!r},q=new URLSearchParams(location.search).get('code'),c=null;
try{{if(q)sessionStorage.setItem('hr-demo-code',q);c=sessionStorage.getItem('hr-demo-code');}}catch(e){{c=q;}}
if(c!==C)document.documentElement.className+=' gated';}})();</script>"""

GATE_BODY = """<div class="gate"><div class="gate-card"><h1>Private demo</h1><p>This is a private mockup prepared by LiveKit for Hard Rock Hotels. Open it with the access link you were given.</p>
<form onsubmit="var v=this.c.value.trim();if(v){location.search='?code='+encodeURIComponent(v)}return false"><label>Access code <input name="c" autocomplete="off"></label><button>Open</button></form></div></div>"""

DEMO_JS = """<script>document.addEventListener('click',function(e){var b=e.target.closest('[data-demo]');if(!b)return;e.preventDefault();
var t=document.getElementById('demo-toast');t.hidden=false;clearTimeout(t._h);t._h=setTimeout(function(){t.hidden=true},2400);});
document.querySelectorAll('.tabs [role=tab]').forEach(function(tab){tab.addEventListener('click',function(){var l=tab.closest('.tabs');
l.querySelectorAll('[role=tab]').forEach(function(x){x.setAttribute('aria-selected',x===tab)});var f=tab.dataset.filter;
document.querySelectorAll('[data-kind]').forEach(function(r){r.hidden=f!=='all'&&r.dataset.kind.indexOf(f)<0})})});
document.querySelectorAll('.toggle[aria-controls]').forEach(function(b){b.addEventListener('click',function(){var p=document.getElementById(b.getAttribute('aria-controls'));
var open=b.getAttribute('aria-expanded')!=='true';b.setAttribute('aria-expanded',open);p.hidden=!open;})});
(function(){var h=document.querySelector('.hero');if(!h)return;var s=[].slice.call(h.querySelectorAll('.slide')),d=[].slice.call(h.querySelectorAll('.dots button')),i=0,t;
function go(n){i=(n+s.length)%s.length;s.forEach(function(x,k){x.classList.toggle('on',k===i)});d.forEach(function(x,k){x.classList.toggle('on',k===i)});clearTimeout(t);t=setTimeout(function(){go(i+1)},7000)}
h.querySelector('.prev').onclick=function(){go(i-1)};h.querySelector('.next').onclick=function(){go(i+1)};d.forEach(function(x,k){x.onclick=function(){go(k)}});go(0)})();
(function(){var f=document.getElementById('bookbar');if(!f)return;f.addEventListener('submit',function(e){e.preventDefault();var h=f.hotel.value;
if(h!=='new-york'){var t=document.getElementById('demo-toast');t.hidden=false;t.textContent='Demo only: this mockup books Hard Rock Hotel New York. Choose New York.';setTimeout(function(){t.hidden=true},2600);return}
var q='?hotel='+h+(f.arrive.value?'&in='+f.arrive.value:'')+(f.depart.value?'&out='+f.depart.value:'')+'&adults='+f.adults.value+'&children='+f.children.value;location.href='"""+ BASE + """/book'+q;})})();</script>"""


def page(path: str, title: str, body: str, hotel: str | None = None, cur: str = "", desc: str = "", plain: bool = False) -> tuple[str, str]:
    site = HOTELS[hotel]["name"] if hotel else "Hard Rock Hotels"
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{E(title)} | {E(site)} (demo mockup)</title>
<meta name="description" content="{E(desc or title)}">
{GATE}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{BASE}/assets/site.css"><link rel="icon" href="{BASE}/img/brand/favicon.png">
{EMBED}
</head><body class="{"page-plain" if plain else ""}">
{GATE_BODY}
{header(hotel, cur)}
<main id="main">{body}</main>
{footer(hotel)}
<div id="demo-toast" class="toast" role="status" hidden>Demo only: this mockup doesn't sign in, take reservations or collect personal details.</div>
{DEMO_JS}
</body></html>"""
    return path, doc


# ---------- components ----------
def carousel(slides, short=False) -> str:
    out = []
    for i, (small, big, text, pic, href) in enumerate(slides):
        more = f' <a href="{link(href)}">Learn More</a>' if href else ""
        out.append(
            f'<div class="slide{" on" if i == 0 else ""}"><img src="{pic}" alt=""><div class="cap"><h2><small>{E(small)}</small>{E(big)}</h2><p>{E(text)}{more}</p></div></div>'
        )
    dots = "".join(f'<button type="button" aria-label="Slide {i + 1}"></button>' for i in range(len(slides)))
    return f"""<section class="hero{" short" if short else ""}" aria-label="Hero carousel">{"".join(out)}
<button type="button" class="arrow prev" aria-label="Previous slide">&#8249;</button><button type="button" class="arrow next" aria-label="Next slide">&#8250;</button>
<div class="dots">{dots}</div></section>"""


def bookbar(hotel: str | None = None) -> str:
    opts = []
    for region, cities in DESTS:
        opts.append(f'<optgroup label="{E(region)}">')
        for c in cities:
            slug = c[3]
            sel = " selected" if hotel and slug == hotel else ""
            opts.append(f'<option value="{E(slug or c[0])}"{sel}>{E(c[0])}</option>')
        opts.append("</optgroup>")
    dest = (
        f'<label class="f dest">Destinations<select class="v" name="hotel"><option value="" disabled{"" if hotel else " selected"}></option>{"".join(opts)}</select></label>'
        if not hotel
        else f'<input type="hidden" name="hotel" value="{hotel}">'
    )
    num = lambda name, label, rng, v: (  # noqa: E731
        f'<label class="f n">{label}<select class="v" name="{name}">'
        + "".join(f'<option{" selected" if x == v else ""}>{x}</option>' for x in rng)
        + "</select></label>"
    )
    go = "Check Availability" if hotel else "Book Now"
    return f"""<form class="bookbar" id="bookbar" aria-label="Book a stay">{dest}
<label class="f date">Arrive (mm/dd/yyyy)<input class="v" type="date" name="arrive"></label><span class="dash">—</span>
<label class="f date">Depart (mm/dd/yyyy)<input class="v" type="date" name="depart"></label><span class="divider"></span>
{num("rooms", "Rooms", range(1, 6), 1)}{num("adults", "Adults", range(1, 5), 2)}{num("children", "Children", range(0, 5), 0)}
<button class="go" type="submit">{go}</button></form>"""


def tile(title, text, pic, href, btn="Learn More", cls="") -> str:
    h = link(href) if href else "#"
    demo = "" if href else " data-demo"
    return f"""<article class="tile {cls}"><img src="{pic}" alt=""><div class="tcap"><h3>{title}</h3>{f"<p>{E(text)}</p>" if text else ""}<a class="btn-line" href="{h}"{demo}>{E(btn)}</a></div></article>"""


def card(title, text, pic, acts="", meta="", hid="") -> str:
    return f"""<article class="card"{f' id="{hid}"' if hid else ""}><img src="{pic}" alt=""><div class="cb"><h3>{E(title)}</h3>{f'<p class="meta">{E(meta)}</p>' if meta else ""}<p>{E(text)}</p><div class="acts">{acts}</div></div></article>"""


def split(title, text, pic, acts, flip=False, sub="") -> str:
    a = f'<img src="{pic}" alt="">'
    b = f'<div>{f"<p class=eyebrow-dark>{E(sub)}</p>" if sub else ""}<h2>{title}</h2><p>{E(text)}</p>{acts}</div>'
    return f'<section class="hcols{" flip" if flip else ""}">{a + b if flip else b + a}</section>'


def subhero(title, pic, crumbs=None) -> str:
    c = ""
    if crumbs:
        c = '<nav class="crumbs" aria-label="Breadcrumb">' + " / ".join(f'<a href="{link(h)}">{E(t)}</a>' for t, h in crumbs) + f" / {E(title)}</nav>"
    return f'<section class="subhero"><img src="{pic}" alt=""><div class="cap"><h1>{E(title)}</h1></div></section>{c}'


def gallery(pics) -> str:
    return '<section class="whats"><h2 class="center">What\'s Happening<br>at Hard Rock Hotels</h2><div class="grid-gallery">' + "".join(
        f'<img src="{p}" alt=""{" class=big" if i == 2 else ""}>' for i, p in enumerate(pics)
    ) + "</div></section>"


# ---------- content ----------
# (city, hotel name, kind, mockup slug or "", pic key, fallback gen image)
DESTS = [
    (
        "North America",
        [
            ("Atlanta - REVERB", "Reverb by Hard Rock Atlanta", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
            ("Atlantic City", "Hard Rock Hotel & Casino Atlantic City", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("Biloxi", "Hard Rock Hotel & Casino Biloxi", "Casino Resort", "", "dest-beach-cabanas.jpg"),
            ("Bristol", "Hard Rock Hotel & Casino Bristol", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("Cancun", "Hard Rock Hotel Cancun", "All-Inclusive Resort", "", "dest-caribbean-pool.jpg"),
            ("Daytona Beach", "Hard Rock Hotel Daytona Beach", "Resort Hotel", "", "dest-beach-cabanas.jpg"),
            ("Deadwood", "Hard Rock Hotel & Casino Deadwood", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("Guadalajara", "Hard Rock Hotel Guadalajara", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
            ("Hollywood", "Seminole Hard Rock Hotel & Casino Hollywood", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("Immokalee", "Seminole Casino Hotel Immokalee", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("London, Ontario", "Hard Rock Hotel London, Ontario", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
            ("Los Cabos", "Hard Rock Hotel Los Cabos", "All-Inclusive Resort", "", "dest-beach-dinner.jpg"),
            ("New York", "Hard Rock Hotel New York", "City Hotel", "new-york", "ny-midtown-street-night.jpg"),
            ("Orlando", "Hard Rock Hotel Orlando", "Resort Hotel", "orlando", "dest-family-pool-slides.jpg"),
            ("Riviera Maya", "Hard Rock Hotel Riviera Maya", "All-Inclusive Resort", "", "dest-caribbean-pool.jpg"),
            ("Sacramento at Fire Mountain", "Hard Rock Hotel & Casino Sacramento", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("San Diego", "Hard Rock Hotel San Diego", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
            ("Sioux City", "Hard Rock Hotel & Casino Sioux City", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("Tampa", "Seminole Hard Rock Hotel & Casino Tampa", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("Tulsa", "Hard Rock Hotel & Casino Tulsa", "Casino Resort", "", "dest-concert-stage.jpg"),
            ("Vallarta", "Hard Rock Hotel Vallarta", "All-Inclusive Resort", "", "dest-beach-dinner.jpg"),
        ],
    ),
    ("Central & South America, Caribbean", [("Punta Cana", "Hard Rock Hotel & Casino Punta Cana", "All-Inclusive Resort", "", "dest-caribbean-pool.jpg")]),
    (
        "Europe, Middle East, Africa",
        [
            ("Davos", "Hard Rock Hotel Davos", "Resort Hotel", "", "dest-spa-room.jpg"),
            ("Hamburg - REVERB", "Reverb by Hard Rock Hamburg", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
            ("Madrid", "Hard Rock Hotel Madrid", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
            ("Malta", "Hard Rock Hotel Malta", "Resort Hotel", "", "dest-mediterranean-terrace.jpg"),
            ("Marbella", "Hard Rock Hotel Marbella", "Resort Hotel", "", "dest-mediterranean-terrace.jpg"),
            ("Tenerife", "Hard Rock Hotel Tenerife", "Resort Hotel", "", "dest-mediterranean-terrace.jpg"),
        ],
    ),
    (
        "Asia Pacific",
        [
            ("Bali", "Hard Rock Hotel Bali", "Resort Hotel", "", "dest-bali-infinity.jpg"),
            ("Dalian", "Hard Rock Hotel Dalian", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
            ("Desaru Coast", "Hard Rock Hotel Desaru Coast", "Resort Hotel", "", "dest-bali-infinity.jpg"),
            ("Goa", "Hard Rock Hotel Goa", "Resort Hotel", "", "dest-beach-cabanas.jpg"),
            ("Maldives", "Hard Rock Hotel Maldives", "Resort Hotel", "", "dest-bali-infinity.jpg"),
            ("Pattaya", "Hard Rock Hotel Pattaya", "Resort Hotel", "", "dest-family-pool-slides.jpg"),
            ("Penang", "Hard Rock Hotel Penang", "Resort Hotel", "", "dest-beach-cabanas.jpg"),
            ("Shenzhen", "Hard Rock Hotel Shenzhen", "City Hotel", "", "dest-city-skyline-hotel.jpg"),
        ],
    ),
]
REGIONS = {
    "North America": ("north-america", "United States, Mexico, Canada", "Your North American experience comes with a classic rock, a recent rap and a funky-town feel through cities and suburbs alike."),
    "Central & South America, Caribbean": ("caribbean", "Dominican Republic", "There's a distinct beat throughout the Dominican Republic that brings out your best self at Hard Rock."),
    "Europe, Middle East, Africa": ("europe", "Germany, Malta, Spain, Switzerland", "Mix it up … shaken, not stirred, when joining the party and the culture across Europe, the Middle East and Africa."),
    "Asia Pacific": ("asia", "China, India, Indonesia, Malaysia, Maldives, Thailand", "Exotic and offbeat is the Hard Rock experience in the Asia Pacific area, where mod tunes and a certain chic fuse."),
}

# brand offers: (hotel, title, text, pic, link to the hotel's offer page or None)
BRAND_OFFERS = [
    ("Hard Rock Hotel Cancun", "Epic Flight and Stay Bundles", "Bundles that won't break the bank, from the US to Cancun. We've got your ticket to paradise!", ("offer-cancun", "dest-caribbean-pool.jpg"), None),
    ("Hard Rock Hotel Daytona Beach", "Toast & Jam", "Our very own twist on the traditional Bed and Breakfast package.", ("offer-daytona", "ny-brunch-plate.jpg"), None),
    ("Hard Rock Hotel Marbella", "Unity: VIP Backstage Access", "A Unity member offer at our Costa del Sol resort: member perks and backstage-style extras.", ("offer-marbella", "dest-mediterranean-terrace.jpg"), None),
    ("Hard Rock Hotel New York", "Fall for New York", "Fall for New York with up to 20% off, a $50 food and beverage credit, and added perks in Midtown Manhattan.", ("ny-offer-fall", "offer-rooftop-sunset.jpg"), "/new-york/offers"),
    ("Hard Rock Hotel New York", "Stay for a Cause Room Package", "Make your stay mean a little more this Pinktober. Reserve your room by 10/31/2026 to enjoy exclusive perks in the heart of Midtown Manhattan.", ("ny-offer-pink", "offer-champagne.jpg"), "/new-york/offers"),
    ("Hard Rock Hotel New York", "Live the High Life", "Reserve Rock Star Suite, our two-level loft penthouse, and enjoy daily breakfast for two.", ("ny-rockstar", "ny-penthouse-terrace.jpg"), "/new-york/offers"),
    ("Hard Rock Hotel & Casino Punta Cana", "Kids Stay Free", "Bring the whole crew and turn up the fun! Kids stay free at Hard Rock Hotel & Casino Punta Cana.", ("offer-puntacana", "dest-family-pool-slides.jpg"), None),
    ("Hard Rock Hotel & Casino Punta Cana", "Extra Perks, Extra Fun", "Found a better rate? We'll match it and reward you with a complimentary upgrade + 10% off.", ("offer-puntacana2", "offer-pool-float.jpg"), None),
    ("Hard Rock Hotel Riviera Maya", "Epic Flight and Stay Bundles to Riviera Maya", "Bundles that won't break the bank, from the US to the Riviera Maya. We've got your ticket to paradise!", ("offer-rivieramaya", "dest-beach-cabanas.jpg"), None),
    ("Hard Rock Hotel Shenzhen", "Double Afternoon Tea Room Package", "Enjoy a relaxing stay with afternoon tea at Hard Rock Cafe.", ("offer-shenzhen", "ny-cocktail-closeup.jpg"), None),
    ("Hard Rock Hotel Orlando", "Save 15% off a 5+ Night Stay", "Save 15% (up to 30%) off the Flexible Rate when you stay five or more consecutive nights next to Universal Orlando.", ("orl-hero", "dest-family-pool-slides.jpg"), "/orlando/offers"),
]

NY_OFFERS = [
    (
        "Featured Offer",
        "Fall for New York",
        "Fall for New York with exclusive savings and added perks in the heart of Midtown Manhattan.",
        ["Up to 20% off Best Available Rate", "$50 food and beverage credit per stay", "Early check-in, late checkout and room upgrade based on availability"],
        "Book October 1 to 31, 2026 for stays through March 31, 2027. Two-night minimum. Non-cancelable and non-refundable. Promo code PROFALL.",
        ("ny-offer-fall", "offer-rooftop-sunset.jpg"),
    ),
    (
        "Featured Offer",
        "Stay for a Cause Room Package",
        "Make your Midtown Manhattan stay mean a little more this Pinktober with exclusive perks.",
        ["Pink Chef amenity", "Two Pinktober mocktails at Sessions Restaurant", "Custom embroidered take-home robe", "Priority access to a specially curated Pinktober WAX® collection"],
        "Book and stay October 1 to 31, 2026. Three days' advance booking, two-night minimum. Non-cancelable and non-refundable.",
        ("ny-offer-pink", "offer-champagne.jpg"),
    ),
    (
        "Member Exclusive",
        "Unity Member Rate",
        "Join Unity by Hard Rock and enjoy exclusive member benefits.",
        ["Unlock an additional 10% member savings on best available rates", "Earn Unity points on eligible stays", "Free membership"],
        "Check-in through December 31, 2026. Must be a Unity member.",
        ("ny-offer-unity", "ny-turntable.jpg"),
    ),
    (
        "",
        "Live the High Life",
        "Reserve Rock Star Suite, our two-level loft penthouse, and enjoy daily breakfast for two.",
        ["Full prepayment required", "Based on availability"],
        "Daily breakfast for two at Sessions Restaurant.",
        ("ny-rockstar", "ny-penthouse-terrace.jpg"),
    ),
]

ORL_OFFERS = [
    ("Save 15% off a 5+ Night Stay", "Save 15% (up to 30%) off the Flexible Rate for five or more consecutive nights.", "Travel September 8 to December 25, 2026 and January 3 to March 15, 2027.", ("orl-pool", "dest-family-pool-slides.jpg")),
    ("Toast & Jam", "Daily breakfast for two at The Kitchen with your stay in a Garden View room.", "Most Sunday to Thursday nights. Book at least 24 hours ahead.", ("orl-kitchen", "ny-brunch-plate.jpg")),
    ("Romance Package", "Welcome amenity for two, a $55 late-night food and beverage credit, breakfast in bed for two one morning, a turndown snack and late checkout based on availability.", "Two-night minimum. Book at least 24 hours ahead.", ("orl-room", "offer-champagne.jpg")),
]

NY_ROOM_PICS = {
    "Classic King": ("ny-room-classic-king", "ny-room-king.jpg"),
    "Deluxe Queens": ("ny-room-deluxe-queens", "ny-room-double-queen.jpg"),
    "Superior King": ("ny-room-superior-king", "ny-room-corner-king.jpg"),
    "Deluxe King": ("ny-room-deluxe-king", "ny-bathroom-rain-shower.jpg"),
    "Studio": ("ny-room-studio", "ny-suite-living.jpg"),
    "Platinum Suite": ("ny-room-platinum", "ny-suite-living.jpg"),
    "Superior Balcony": ("ny-room-superior-balcony", "ny-penthouse-terrace.jpg"),
    "Studio Balcony": ("ny-room-studio-balcony", "ny-rooftop-day.jpg"),
    "Platinum Suite Balcony": ("ny-room-platinum-balcony", "ny-penthouse-terrace.jpg"),
    "Rock Star Suite": ("ny-rockstar", "ny-penthouse-terrace.jpg"),
    "Accessible Rooms": ("ny-room-accessible", "ny-room-king.jpg"),
}
# the rooms page, as published (bed | sleeps | size; description; kinds for the tabs)
NY_ROOMS = [
    ("Classic King", "1 king bed", "Sleeps 2", "Room Size 265 sq. ft.", "The classics never go out of style. Work, dine, or play from the built-in banquette while the floor-to-ceiling windows showcase the energy of the city.", "rooms"),
    ("Deluxe Queens", "2 beds", "Sleeps 2 - 4", "Room Size 317 sq. ft.", 'Press play on your stay with two custom queen beds (79" x 57"). Friends and families alike will enjoy the extra space.', "rooms"),
    ("Superior King", "1 king bed", "Sleeps 2", "Room Size 265 sq. ft.", "View the neighborhood from a new perspective. Enjoy the same layout and perks as Classic rooms plus a privacy divider.", "rooms"),
    ("Deluxe King", "1 king bed", "Sleeps 2", "Room Size 341 - 389 sq. ft.", "Make it deluxe with a soaking tub.", "rooms"),
    ("Studio", "1 king bed", "Sleeps 2 - 3", "Room Size 365 - 394 sq. ft.", "Let our Studios serve as the backdrop for your next adventure. Bring the band and enjoy the sofa bed or start a new adventure by traveling solo.", "suites"),
    ("Platinum Suite", "1 king bed", "Sleeps 2 - 3", "Room Size 758 sq. ft.", "Mingle with your entourage in the separate living area complete with a sofa bed and a half bath or retreat to your private oasis and unwind in the deep-soaking tub.", "suites"),
    ("Superior Balcony", "1 king bed", "Sleeps 2", "Room Size 280 sq. ft.", "Elevate the Superior stay with a 100 sq. ft. outdoor balcony in the heart of Midtown Manhattan.", "rooms balcony"),
    ("Studio Balcony", "1 king bed", "Sleeps 2", "Room Size 313 - 389 sq. ft.", "Unwind on the nearly 200 sq. ft. balcony while enjoying the same layout and perks as the Studios.", "suites balcony"),
    ("Platinum Suite Balcony", "1 king bed", "Sleeps 2 - 3", "Room Size 526 sq. ft.", "A rare find among Times Square hotels, step out onto the 370 sq. ft. of outdoor space in the heart of Midtown. Enjoy pre-show cocktails in the separate living area (complete with a sofa bed) or press pause on your stay within the well-appointed bedroom.", "suites balcony"),
    ("Rock Star Suite", "1 king bed", "Sleeps 2 - 3", "Room Size 3,765 sq. ft.", "Elevate your stay for a truly legendary experience. The Rock Star Suite is your sky high, bi-level penthouse with original artwork and music memorabilia from some of the world's greatest performers: double-height floor-to-ceiling windows, an open-plan living and dining space with bar and butler pantry, an 1,800 sq. ft. terrace, private VIP access to RT60 Rooftop Bar & Lounge, a freestanding tub and private elevator banks.", "suites"),
    ("Accessible Rooms", "King or queen beds", "Sleeps 2 - 4", "Wide doorframes, roll-in showers", "We're pleased to provide accessible spaces and user-friendly accommodations to ensure everyone is welcome here. We offer specialized rooms with wide doorframes, wheelchair-accessible spaces, lowered bed and bath items, roll-in shower, grab bars, visual smoke detectors, and more.", "rooms"),
]
ORL_ROOMS = [
    ("Standard Rooms", "2 queen beds", "Sleeps 5 with rollaway", "375 sq. ft.", "Rock-inspired rooms with two queen beds, a short walk from Universal CityWalk and the parks.", "rooms", ("orl-room-standard", "ny-room-double-queen.jpg")),
    ("Garden View Rooms", "2 queen beds", "Sleeps 5 with rollaway", "375 sq. ft.", "Two queen beds overlooking the hotel's gardens; the rooms for guests travelling with pets.", "rooms", ("orl-room-garden", "dest-pet-friendly-room.jpg")),
    ("Pool View Rooms", "2 queen beds", "Sleeps 5 with rollaway", "375 sq. ft.", "Two queen beds overlooking the 12,000 sq. ft. pool with its sand beach and 260-foot waterslide.", "rooms", ("orl-room-pool", "dest-family-pool-slides.jpg")),
    ("Deluxe King Rooms", "1 king bed", "Sleeps 3 with rollaway", "400 sq. ft.", "A king bed and a lounge area to unwind after a day at the parks.", "rooms", ("orl-room-king", "ny-room-king.jpg")),
    ("Deluxe Queen Rooms", "2 queen beds", "Sleeps 5", "500 sq. ft.", "Extra space for the whole band with two queen beds.", "rooms", ("orl-room-dq", "ny-room-double-queen.jpg")),
    ("Future Rock Star Suite", "1 king + 2 twins", "Sleeps 5", "800 sq. ft.", "A king bedroom for the grown-ups and a kids' room with two twin beds and a color-changing stage.", "suites", ("orl-room-frs", "ny-suite-living.jpg")),
    ("King Suites", "1 king bed", "Sleeps 3", "650 sq. ft.", "A king suite with a separate living space.", "suites", ("orl-room-ks", "ny-suite-living.jpg")),
    ("Graceland Suite", "1 king bed", "Sleeps 2", "2,000 sq. ft.", "A baby grand piano, a fireplace and a whirlpool tub, in tribute to the King.", "suites", ("orl-room-graceland", "ny-penthouse-terrace.jpg")),
]


def offer_card(where, title, text, pic, href, perks=None, terms="", label="") -> str:
    p = "".join(f"<li>{E(x)}</li>" for x in perks or [])
    book = f'<a class="btn-gold" href="{link("/book?hotel=new-york")}">Book Now</a>' if "New York" in where or where == "new-york" else demo_btn("Book Now", "btn-gold")
    more = f'<a class="btn-line dark" href="{link(href)}">Learn More</a>' if href else demo_btn("Learn More")
    return f"""<article class="offer"><img src="{pic}" alt=""><div class="ob">{f'<p class="where">{E(label or where)}</p>' if (label or where) else ""}<h3>{E(title)}</h3>
<p>{E(text)}</p>{f'<ul class="perks-list">{p}</ul>' if p else ""}{f'<p class="code">{E(terms)}</p>' if terms else ""}<div class="acts">{book}{more}</div></div></article>"""


def room_block(name, bed, sleeps, size, desc, kind, pic, hotel, price=None) -> str:
    book = f'<a class="btn-gold" href="{link("/book?hotel=new-york&room=" + name.replace(" ", "+"))}">Book Now</a>' if hotel == "new-york" else demo_btn("Book Now", "btn-gold")
    pr = f'<p class="from">From <b>${price:,}</b> per night, before taxes and fees</p>' if price else ""
    return f"""<article class="room" data-kind="{kind}"><div class="rpic"><img src="{pic}" alt="{E(name)}"></div><div class="rb"><h3>{E(name)}</h3>
<ul class="spec"><li>{E(bed)}</li><li>{E(sleeps)}</li><li>{E(size)}</li></ul><p>{E(desc)}</p>{pr}<div class="acts">{book}{demo_btn("Take a 360 Tour")}</div></div></article>"""


def load_booking() -> dict:
    with open(os.path.join(KNOW, "booking.json")) as f:
        return json.load(f)


def hotel_intro_box(hotel) -> str:
    h = HOTELS[hotel]
    return f'<section class="addr-inline"><h2>{E(h["name"])}</h2><p>{E(h["addr"])} · {E(h["phone"])}</p></section>'


BOOK_BODY = f"""<div class="be" data-lk-region="booking">
<section class="be-hero"><img id="be-hero-img" src="" alt=""><div class="card-in"><h1 id="be-hotel">Hard Rock Hotel New York</h1>
<div id="be-addr">159 W 48th Street, New York, New York, United States, 10036</div><div id="be-phone">1-212-970-1200</div></div></section>
<div class="be-wrap">
 <div>
  <ol class="be-steps" aria-label="Booking steps"><li data-step="dates" class="on">1. Dates</li><li data-step="rooms">2. Rooms</li><li data-step="rates">3. Rates</li><li data-step="guest">4. Guest details</li></ol>
  <section class="be-search" id="be-dates" aria-label="Dates of stay">
   <div class="be-fields">
    <div><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg><span><b>Guests</b><span id="be-guests">2 guests, 1 room</span></span></div>
    <div><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16"/><path d="M3 10h18M8 3v4M16 3v4"/></svg><span><b>Check-in</b><span id="be-in">Select a date</span></span></div>
    <div><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16"/><path d="M3 10h18M8 3v4M16 3v4"/></svg><span><b>Check-out</b><span id="be-out">Select a date</span></span></div>
   </div>
   <div class="be-body">
    <p class="be-note">We're showing the best available price per room (in USD) for 1 night, based on the number of guests.</p>
    <div class="be-cals"><button type="button" class="be-nav prev" id="be-prev" aria-label="Previous month">&#8249;</button><button type="button" class="be-nav next" id="be-next" aria-label="Next month">&#8250;</button>
     <div class="be-cal"><h3 id="be-m0"></h3><div class="dow"><span>S</span><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span></div><div class="days" id="be-d0"></div></div>
     <div class="be-cal"><h3 id="be-m1"></h3><div class="dow"><span>S</span><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span></div><div class="days" id="be-d1"></div></div></div>
    <div class="be-legend"><span>▧ Sold out</span><span>Prices are the lowest nightly rate for 2 adults, before taxes and the $40 destination fee.</span></div>
    <div class="be-acts"><span class="be-guests-ctl">Adults <button type="button" class="be-step" data-g="adults" data-d="-1" aria-label="Fewer adults">−</button> <b id="be-adults">2</b> <button type="button" class="be-step" data-g="adults" data-d="1" aria-label="More adults">+</button>
     &nbsp; Children <button type="button" class="be-step" data-g="children" data-d="-1" aria-label="Fewer children">−</button> <b id="be-children">0</b> <button type="button" class="be-step" data-g="children" data-d="1" aria-label="More children">+</button></span>
     <button type="button" class="cancel" id="be-clear">Clear</button><button type="button" class="be-btn" id="be-search" disabled>Search</button></div>
   </div>
  </section>
  <section id="be-rooms" hidden aria-label="Select a room">
   <h2 class="be-h">Select a Room</h2>
   <div class="be-filter" id="be-filter" role="group" aria-label="Room type"><button type="button" data-f="All" aria-pressed="true">All rooms</button><button type="button" data-f="King" aria-pressed="false">King</button><button type="button" data-f="Queen" aria-pressed="false">Queens</button><button type="button" data-f="Suite" aria-pressed="false">Suites</button><button type="button" data-f="Balcony" aria-pressed="false">Balcony</button></div>
   <div id="be-roomlist"></div>
  </section>
  <section id="be-guest" hidden aria-label="Guest details">
   <div class="be-guest"><h2>Guest Details</h2><p>This is where a guest enters their name, contact and payment details on the official booking site.</p>
   <p><strong>Demo mockup: this step collects nothing, and LiveKit never fills it in.</strong></p>
   <button type="button" class="be-btn" data-demo>Continue to Payment</button> <button type="button" class="cancel be-back" data-to="rooms">Back to rooms</button></div>
  </section>
 </div>
 <aside class="be-side">
  <div class="be-cart" id="be-cart"><div>Your Cart: <span id="be-count">0 Items</span></div><div id="be-cartbody"></div></div>
  <div class="be-unity"><div class="uh">Reward Yourself with<br>Unity by Hard Rock*</div><ul>
   <li><b>Members Only Rate</b>Save up to 10% off Hard Rock's best available rates at participating locations</li>
   <li><b>Rewards</b>Earn and redeem Unity Points toward free nights, dining experiences, spa, gaming &amp; more</li>
   <li><b>Exclusive Benefits</b>Enjoy exclusive member benefits, starting with your very first stay</li></ul>
   <p class="be-fine" style="padding:0 22px 14px">*Available at participating locations. Unity log-in isn't part of this demo.</p></div>
 </aside>
</div>
<p class="be-fine wrap" style="margin-top:18px">Demo mockup of reservations.hardrockhotels.com. Room names, sizes and sample prices come from Hard Rock Hotel New York's public site and booking engine on Oct 21, 2026; calendar prices for other dates are illustrative.</p>
</div>
<script src="{BASE}/assets/booking-data.js"></script><script src="{BASE}/assets/bookflow.js" defer></script>"""


def build() -> list[tuple[str, str]]:
    pages = []
    add = lambda *a, **k: pages.append(page(*a, **k))  # noqa: E731
    bk = load_booking()
    ny_from = {r["name"]: r["from_weekday"] for r in bk["hotels"]["new-york"]["rooms"]}
    orl_from = {r["name"]: r["from_weekday"] for r in bk["hotels"]["orlando"]["rooms"]}
    G = lambda name: img(name.rsplit(".", 1)[0], name)  # noqa: E731

    # ---- home ----
    hero = carousel(
        [
            ("Now Open", "Hard Rock Hotel Malta", "Experience a bold new Mediterranean destination where music, entertainment and immersive hospitality come together.", img("home-hero-malta", "dest-mediterranean-terrace.jpg"), "/destinations#europe"),
            ("Rewards", "Built Around U", "Unity by Hard Rock lets you earn and redeem incredible rewards at participating hotels, casinos, cafes, and Rock Shops worldwide. Enjoy exclusive rates and benefits at hotels.", img("home-hero-unity", "dest-caribbean-pool.jpg"), "/unity"),
            ("Pinktober®", "Stronger Together", "This October, embrace the power of pink and help create a space for unity, strength, and hope. Join us in stepping up and staying stronger together.", img("home-hero-pink", "offer-champagne.jpg"), "/offers"),
        ]
    )
    intro = """<section class="intro"><div><h1 class="sr">Welcome to Hard Rock Hotels</h1><h2>Feel Like a Star<br>Hard Rock Hotels &amp; Casinos</h2></div>
<p>Music is a force—a kinetic spirit that's ageless and electric. And each Hard Rock Hotel is a monument to that spirit, creating destinations where anything is possible. A weekend of poolside lounging by day and hotel club-crawls by night? Yes. Incredible outdoor recreation for the whole family and kids-only clubs that are actually cool? Yes. An all-inclusive experience you'll never forget? Yes. Indulgent spa treatments and cuisine from Michelin-star chefs? Yes. A mind-melting event experience? Yes. Whatever your destination, when you stay at Hard Rock, you have arrived.</p></section>"""
    tiles = (
        '<section class="tiles">'
        + tile("Music Brings Us Together", "Programs and experiences that can only be found at a Hard Rock Hotel.", img("home-music", "ny-turntable.jpg"), "/hotels-and-resorts#experience")
        + tile("Family Programming", "Signature hangouts and activities designed for fans of all ages to connect and have fun.", img("home-family", "dest-family-pool-slides.jpg"), "/hotels-and-resorts#resorts")
        + tile("Stay and Save", "Exclusive rates and special offers around the globe.", img("home-save", "offer-pool-float.jpg"), "/offers", "Offers")
        + "</section>"
    )
    dests = f"""<section class="band"><div class="shead"><h2>Destinations Near and Far</h2><a href="{link("/destinations")}">View All Destinations</a></div>
<div class="duo">{tile("Discover<br>Hard Rock Hotels in Spain", "", img("home-spain", "dest-mediterranean-terrace.jpg"), "/destinations#europe", "View Hotels")}{tile("Iconic Entertainment<br>The Guitar Hotel", "", img("home-guitar", "dest-concert-stage.jpg"), "/destinations#north-america", "View Hotel")}</div>
<div class="duo one">{tile("Center Stage in Midtown<br>Hard Rock Hotel New York", "446 rooms and suites with floor-to-ceiling windows, steps from Broadway and Times Square.", img("dest-new-york", "ny-rooftop-night.jpg"), "/new-york", "View Hotel", "wide")}</div></section>"""
    feature = f"""<section class="feature"><div class="fcopy"><h2>Unleashed<br>VIP Pet Program</h2><p>Introducing Unleashed, our VIP pet program that delivers custom pet playlists, sWAG bags, and designated places just for them. Star treatment for your bestie, Hard Rock style.</p><a class="btn-purple" href="{link("/hotels-and-resorts#experience")}">Learn More</a></div><img src="{img("home-pet", "dest-pet-friendly-room.jpg")}" alt=""></section>"""
    news = f"""<section class="news"><div class="lead"><h2>#Facts<br>For the Record</h2><p>Stay up to date on the latest announcements, press releases and happenings at Hard Rock Hotel.</p>{demo_btn("View the Blog", "more-btn")}</div>
<article><img src="{img("news-pink", "offer-champagne.jpg")}" alt=""><div><h3>Hard Rock International Launches 27th Annual PINKTOBER Campaign</h3><p>Hard Rock International has launched its 27th annual PINKTOBER campaign for Breast Cancer Awareness Month.</p><a class="more" href="#" data-demo>Read This Post ›</a></div></article>
<article><img src="{img("news-malta", "dest-mediterranean-terrace.jpg")}" alt=""><div><h3>Hard Rock Hotel Malta Celebrates Star-Studded Grand Opening</h3><p>Hard Rock's first hotel in Malta welcomes guests to a luxurious new Mediterranean destination.</p><a class="more" href="#" data-demo>Read This Post ›</a></div></article></section>"""
    gal = gallery([G(x) for x in ("dest-beach-dinner.jpg", "ny-lobby-memorabilia.jpg", "dest-caribbean-pool.jpg", "ny-cocktail-closeup.jpg", "dest-bali-infinity.jpg", "dest-spa-room.jpg", "ny-rooftop-night.jpg", "offer-pool-float.jpg", "dest-wedding-table.jpg")])
    add("/", "Luxury Hotels & Resorts Around the World", hero + bookbar() + intro + tiles + dests + feature + news + gal, desc="Hard Rock Hotels: luxury hotels and resorts around the world.")

    # ---- destinations ----
    regions = []
    for i, (region, cities) in enumerate(DESTS):
        rid, countries, txt = REGIONS[region]
        cards = "".join(
            f"""<a class="city" href="{link("/" + slug) if slug else link("/demo-only")}"{"" if slug else " data-demo"}><img src="{img("dest-" + slug, pic) if slug else G(pic)}" alt=""><div><h3>{E(city)}</h3><small>{E(name)}</small><span class="tag">{E(kind)}</span></div></a>"""
            for city, name, kind, slug, pic in cities
        )
        regions.append(
            f"""<section class="region" id="{rid}"><div class="rhead"><div><h2>{E(region)}</h2><p class="countries">{E(countries)}</p></div><p class="rtxt">{E(txt)}</p>
<button type="button" class="toggle" aria-expanded="{"true" if i == 0 else "false"}" aria-controls="cities-{rid}">Destinations</button></div>
<div class="citygrid" id="cities-{rid}"{"" if i == 0 else " hidden"}>{cards}</div></section>"""
        )
    filt = """<section class="filters" aria-label="Filter destinations (demo only)"><div class="wrap">
<div><h4>Type of Destination</h4><label><i></i>All-Inclusive</label><label><i></i>City Hotel</label><label><i></i>Resort Hotel</label><label><i></i>Casino</label><label><i></i>Casino Resort</label></div>
<div><h4>Type of Vacation</h4><label><i></i>Romantic Vacation</label><label><i></i>Family Vacation</label><label><i></i>Spa Vacation</label><label><i></i>Beach Vacation</label><label><i></i>Golf Vacation</label></div>
<div><h4>Filter by Region</h4><label><i></i>North America</label><label><i></i>Central &amp; South America, Caribbean</label><label><i></i>Europe, Middle East, Africa</label><label><i></i>Asia Pacific</label></div>
<div class="search"><h4>Search for Your Destination</h4><div class="fake">Search by country, city, or state</div><button type="button" class="btn-line" data-demo>Search</button></div></div></section>"""
    add(
        "/destinations",
        "Destinations",
        f'<section class="subhero"><img src="{img("dest-hero", "dest-beach-cabanas.jpg")}" alt=""></section><section class="page-intro"><h1>Explore<br>Our Destinations</h1><p>Pick your place in the world and a Hard Rock Hotel is there, or nearby. Music-inspired themes, niche artistry and legendary memorabilia are the happy find in each of our destinations across the globe. Every city, resort and casino hotel is tuned-in to the culture, from the Americas to Africa, and Europe to Asia.</p></section>'
        + filt
        + f'<div class="regions">{"".join(regions)}</div>',
        cur="/destinations",
    )

    # ---- hotels & resorts ----
    kinds = [
        ("all-inclusive", "All-Inclusive Resorts", "All-inclusive resorts in Mexico and the Caribbean: oceanfront pools, endless dining and nightlife, all in one stay.", "All-Inclusive Resort"),
        ("city", "City Hotels", "In the center of it all: music-filled hotels in the world's great cities.", "City Hotel"),
        ("resorts", "Resorts", "Beach, mountain and theme-park resorts where the whole family can turn it up.", "Resort Hotel"),
        ("casino", "Casino Resorts", "Hotel and casino resorts with headline entertainment, dining and gaming.", "Casino Resort"),
    ]
    blocks = []
    for kid, title, text, k in kinds:
        names = [(c, n, s) for _, cs in DESTS for c, n, kk, s, _ in cs if kk == k]
        li = "".join(f'<li><a href="{link("/" + s) if s else link("/demo-only")}"{"" if s else " data-demo"}>{E(n)}</a></li>' for c, n, s in names)
        blocks.append(f'<section class="kind" id="{kid}"><h2>{E(title)}</h2><p>{E(text)}</p><ul class="kind-list">{li}</ul></section>')
    exp = f"""<section class="kind" id="experience"><h2>The Hard Rock Experience</h2><p>Sound of Your Stay®: stream curated playlists with Tracks®, spin vinyl with Wax®, or have a Fender guitar delivered to your room with Picks®. Rock Om® in-room yoga, Body Rock® fitness, Rock Spa®, Unleashed VIP pet program, and kids' programming at our resorts.</p></section>"""
    add(
        "/hotels-and-resorts",
        "Hotels & Resorts",
        subhero("Hotels & Resorts", img("hotels-hero", "dest-bali-infinity.jpg")) + f'<div class="wrap kinds">{"".join(blocks)}{exp}</div>',
        cur="/hotels-and-resorts",
    )

    # ---- offers ----
    oc = "".join(offer_card(w, t, x, img(*p), h) for w, t, x, p, h in BRAND_OFFERS)
    add(
        "/offers",
        "Hotel Offers & Deals",
        subhero("Book Direct for the Best Deals", img("offers-hero", "offer-pool-float.jpg"))
        + f"""<section class="page-intro"><p>View specials at our destinations around the globe. From vacation packages to extended-stay discounts, make your next getaway memorable at Hard Rock Hotels.</p></section>
<section class="hcols"><div><h2>Exclusive Rates for Unity Members</h2><p>Join Unity by Hard Rock and enjoy exclusive member rates with up to 10% savings on best available rates at participating hotels when you book at hardrockhotels.com. Plus, earn points on eligible stays to redeem with Hard Rock experiences at our hotels, cafes, casinos, Rock Shops, and more around the world.</p><a class="btn-purple" href="{link("/unity")}">Learn More</a></div><img src="{img("offers-unity", "ny-turntable.jpg")}" alt=""></section>
<div class="shead"><h2>Find an Offer by Region</h2></div><div class="tabs" role="tablist"><button role="tab" aria-selected="true" type="button" data-filter="all">All</button><button role="tab" aria-selected="false" type="button" data-demo>North America</button><button role="tab" aria-selected="false" type="button" data-demo>Central &amp; South America / Caribbean</button><button role="tab" aria-selected="false" type="button" data-demo>Europe / Middle East / Africa</button><button role="tab" aria-selected="false" type="button" data-demo>Asia Pacific</button></div>
<section class="offers">{oc}</section>""",
        cur="/offers",
    )

    # ---- unity ----
    add(
        "/unity",
        "Unity by Hard Rock: Member Rates",
        f"""<section class="unity-hero"><p class="mark">Unity by Hard Rock</p><h1>Rewards Built Around U</h1><p>Earn and redeem rewards at participating hotels, casinos, cafes and Rock Shops worldwide. Membership is free.</p>{demo_btn("Join Now", "btn-gold")} {demo_btn("Sign In", "btn-line")}</section>
<section class="perks"><div class="perk" id="member-rates"><h3>Members Only Rate</h3><p>Save up to 10% off Hard Rock's best available rates at participating hotels when you book direct at hardrockhotels.com.</p></div>
<div class="perk"><h3>Earn Unity Points</h3><p>Earn points on eligible stays, dining, spa and Rock Shop purchases, and redeem them toward free nights, dining experiences, spa, gaming and more.</p></div>
<div class="perk"><h3>Exclusive Benefits</h3><p>Enjoy exclusive member benefits starting with your very first stay, and climb tiers for more perks.</p></div></section>
<section class="page-intro"><h2>How Member Rates Work</h2><p>Look for the Unity rate on the booking page: at Hard Rock Hotel New York it's an extra 10% off best available rates, with points on eligible stays, for check-in through December 31, 2026. Unity log-in and your points balance live in your account, which this demo doesn't use.</p>
<a class="btn-gold" href="{link("/book?hotel=new-york")}">Book Hard Rock Hotel New York</a></section>""",
        cur="/unity",
    )

    # ---- New York ----
    ny = "new-york"
    ny_hero = carousel(
        [
            ("", "Fall for New York", "Plan your Midtown Manhattan getaway with up to 20% off our Best Available Rates and a $50 dining credit per stay.", img("ny-hero-fall", "ny-midtown-street-night.jpg"), "/new-york/offers"),
            ("", "The City That Never Sleeps Is Calling", "Check into Midtown style with bold rooms, skyline views, and Broadway just steps away.", img("ny-hero-city", "ny-rooftop-night.jpg"), "/new-york/rooms-and-suites"),
        ]
    )
    latest = "".join(
        card(t, x, img(*p), f'<a class="btn-purple" href="{link(h)}">Learn More</a>')
        for t, x, p, h in [
            ("Fall for New York", "Fall for New York with exclusive savings and added perks in the heart of Midtown Manhattan for stays through March 31st, 2027.", ("ny-offer-fall", "offer-rooftop-sunset.jpg"), "/new-york/offers"),
            ("Pinktober®", "This October, join us in turning awareness into action with meaningful ways to stay, sip, dine and give back.", ("ny-offer-pink", "offer-champagne.jpg"), "/new-york/offers"),
            ("Your Stay, Your Sound", "Stream playlists, spin vinyl, or borrow a Fender guitar to personalize your in-room experience.", ("ny-sound", "ny-turntable.jpg"), "/new-york/amenities"),
        ]
    )
    body = (
        ny_hero
        + bookbar(ny)
        + """<section class="intro"><div><p class="eyebrow-dark">At Center Stage</p><h1>Hard Rock Hotel<br>New York</h1></div><div><h2 class="h4">An Award-Worthy NYC Experience in Midtown Manhattan</h2>
<p>Immerse yourself in the vibrant essence of the city at Hard Rock Hotel New York. Our award-winning design by Jeffrey Beers International and legendary memorabilia pay homage to New York's iconic music scene. From Sessions Restaurant &amp; Bar, where the open plan, light-filled space represents the soundtrack of the city, to the breathtaking views and masterfully crafted cocktails at RT60 Rooftop Bar &amp; Lounge, each moment promises an unforgettable experience. Discover our event spaces, indulge in music infused amenities like the Sound of Your Stay® program, and retreat to our 446 exquisitely designed guest rooms and suites, each offering floor-to-ceiling windows that showcase the energy of the city. Just steps away from Broadway and Rockefeller Center.</p></div></section>"""
        + '<section class="facts" aria-label="Hotel facts"><div><b>446</b><span>Rooms &amp; suites</span></div><div><b>34th</b><span>Floor rooftop bar</span></div><div><b>3 PM</b><span>Check-in</span></div><div><b>11 AM</b><span>Check-out</span></div></section>'
        + f'<section class="band"><div class="shead"><h2>The Latest at Hard Rock Hotel New York</h2></div><div class="cards">{latest}</div></section>'
        + split("Rooms &amp; Suites", "The stage is set with well-appointed rooms and suites that offer floor-to-ceiling windows, city views, and a set of musical amenities exclusive to Hard Rock Hotels.", img("ny-rooms", "ny-room-king.jpg"), f'<a class="btn-purple" href="{link("/new-york/rooms-and-suites")}">View Rooms &amp; Suites</a>')
        + split("Rock Star Suite", "Elevate your stay for a truly legendary experience. The Rock Star Suite is your sky high, two-level loft penthouse with original artwork and music memorabilia from some of the world's greatest performers. Perfect for private events or special weekend stays.", img("ny-rockstar", "ny-penthouse-terrace.jpg"), f'<a class="btn-purple" href="{link("/new-york/rooms-and-suites")}#rock-star-suite">Learn More</a>', flip=True)
        + split("Cocktails", "Eat & Drink options include farm-fresh all-day dining at Sessions Restaurant and RT60 Rooftop Bar and Lounge with sweeping Midtown Manhattan views from two expansive terraces.", img("ny-rt60", "ny-rooftop-night.jpg"), f'<a class="btn-purple" href="{link("/new-york/eat-and-drink")}">View Eat &amp; Drink</a>')
        + split("Amenities", "Find your rhythm with in-room Rock Om® yoga or let music be your motivating force at Body Rock® gym. Play your own Fender guitar, listen to music on your Crosley record player, or download Tracks® and take our curated playlists with you as you explore New York City. We have musical experiences for little Rockstars, too and a red carpet welcome for four-legged paws.", img("ny-amenities", "ny-turntable.jpg"), f'<a class="btn-purple" href="{link("/new-york/amenities")}">View Amenities</a>', flip=True)
        + split("Explore New York City", "Within walking distance from Hard Rock Hotel New York are some of the world's most iconic sights and sounds: Times Square, Broadway, Rockefeller Center, the Javits Center and Fifth Avenue. We're in the center of it all.", img("ny-area", "ny-times-square-bokeh.jpg"), f'<a class="btn-purple" href="{link("/new-york/area-guide")}">Learn More</a>')
        + gallery([G(x) for x in ("ny-rooftop-night.jpg", "ny-music-hallway.jpg", "ny-lobby-memorabilia.jpg", "ny-cocktail-closeup.jpg", "ny-midtown-street-night.jpg", "ny-brunch-plate.jpg", "ny-times-square-bokeh.jpg", "ny-turntable.jpg", "ny-restaurant-sessions.jpg")]).replace("at Hard Rock Hotels", "at Hard Rock Hotel New York")
    )
    add("/new-york", "NYC Hotels in Midtown Manhattan", body, hotel=ny, cur="")

    rooms_html = "".join(
        room_block(n, b, s, z, d, k, img(*NY_ROOM_PICS[n]), ny, ny_from.get(n) if n != "Accessible Rooms" else ny_from.get("Accessible Classic King")).replace(
            '<article class="room"', f'<article class="room" id="{n.lower().replace(" ", "-")}"', 1
        )
        for n, b, s, z, d, k in NY_ROOMS
    )
    tabs = '<div class="tabs" role="tablist" aria-label="Room types"><button role="tab" aria-selected="true" type="button" data-filter="all">All Rooms</button><button role="tab" aria-selected="false" type="button" data-filter="rooms">Rooms</button><button role="tab" aria-selected="false" type="button" data-filter="suites">Suites</button><button role="tab" aria-selected="false" type="button" data-filter="balcony">Balcony Rooms &amp; Suites</button></div>'
    add(
        "/new-york/rooms-and-suites",
        "NYC Rooms & Suites",
        subhero("NYC Rooms & Suites", img("ny-rooms-hero", "ny-room-corner-king.jpg"))
        + """<section class="page-intro"><p>Our NYC hotel rooms and suites connect you to the rhythm of the city from music-inspired soundwave headboards to the Sound of Your Stay®. Appreciate music as it was intended on a vinyl record player with Wax®, listen to music with Tracks® featuring curated playlists, or jam with Picks® and request a guitar of your choice delivered to your room with over-ear headphones and an amplifier.</p></section>"""
        + f"""<section class="rooms-list"><div class="shead"><h2>Pick Your Favorite</h2><p class="lede">Spacious King and Double Queen rooms with floor-to-ceiling windows, city views, and a comfortable banquette to work and dine. Kimono robes, Lavazza® espresso, Rock Spa® bath products, and Wi-Fi complete the act®.</p></div>{tabs}{rooms_html}
<p class="be-fine center">"From" prices are Hard Rock Hotel New York's published weekday Best Flexible Rate for 2 adults (Nov 10, 2026), before taxes and the $40 destination fee; some are illustrative.</p></section>
<section class="faq wrap"><h2 class="center">Frequently Asked Questions</h2><details><summary>Do the rooms have mini refrigerators?</summary><p>Rooms have a cooler drawer rather than a refrigerator.</p></details><details><summary>Can I request a mini refrigerator for my room?</summary><p>Yes: a mini fridge can be requested from Housekeeping, based on availability.</p></details></section>""",
        hotel=ny,
        cur="rooms-and-suites",
    )

    ny_oc = "".join(offer_card(ny, t, x, img(*p), None, perks, terms, label) for label, t, x, perks, terms, p in NY_OFFERS)
    add(
        "/new-york/offers",
        "New York Hotel Offers",
        subhero("New York Hotel Offers", img("ny-offers-hero", "offer-rooftop-sunset.jpg"))
        + f'<section class="page-intro"><p>Make us your destination for your next trip to NYC. Our exclusive offers and packages are designed to elevate your stay — whether you\'re planning a romantic weekend, a business visit, or an unforgettable escape at our centrally located Times Square hotel.</p></section><section class="offers">{ny_oc}</section>',
        hotel=ny,
        cur="offers",
    )

    dine = [
        ("RT60 Rooftop Bar & Lounge", "Take music to new heights from the 34th floor of RT60. Our showstopping bar & lounge in the heart of Times Square features two outdoor terraces that offer north and south facing city views. Pair crushable cocktails and appetizers with unexpected mixes from new to well-known DJs.", [("Sun & Mon", "Closed"), ("Tue - Sat", "5:00PM - 12:00AM")], "Dress code: polished; no athleisure, flip-flops or baseball caps.", ("ny-rt60", "ny-rooftop-night.jpg")),
        ("Sessions Restaurant", "Sessions Restaurant & Bar represents the soundtrack of the city with classic dishes for breakfast, lunch, and dinner. Located on the second floor this light-filled atrium is adorned with art and music memorabilia.", [("Open Daily", "7:00AM - 10:00PM"), ("Breakfast", "7:00AM - 11:00AM"), ("Happy Hour", "Mon - Fri 3:00PM - 6:00PM")], "Breakfast, all-day dining, drink and kids menus.", ("ny-sessions", "ny-restaurant-sessions.jpg")),
        ("In Room Dining", "Enjoy an array of culinary offerings in the comfort of your hotel room.", [("Mon - Fri", "6:00AM - 11:00PM"), ("Sat - Sun", "7:00AM - 11:00PM")], "", ("ny-ird", "ny-brunch-plate.jpg")),
    ]
    dhtml = "".join(
        f"""<section class="venue" id="{n.lower().replace(" ", "-").replace("&", "and")}"><img src="{img(*p)}" alt=""><div><h2>{E(n)}</h2><p>{E(t)}</p><p class="h4 hours-lab">Hours</p><table class="hours"><tbody>{"".join(f"<tr><td>{E(a)}</td><td>{E(b)}</td></tr>" for a, b in hrs)}</tbody></table>{f"<p class=note>{E(nt)}</p>" if nt else ""}<div class="acts">{demo_btn("Reserve Now", "btn-gold")}{demo_btn("Menu")}</div></div></section>"""
        for n, t, hrs, nt, p in dine
    )
    add(
        "/new-york/eat-and-drink",
        "Eat & Drink",
        subhero("Eat & Drink", img("ny-dining-hero", "ny-cocktail-closeup.jpg"))
        + f'<section class="page-intro"><p>Indulge in craft cocktails and shareable bites at RT60 Rooftop Bar &amp; Lounge, or delight in classic dishes in a music-inspired setting at Sessions Restaurant.</p></section><div class="venues">{dhtml}</div>',
        hotel=ny,
        cur="eat-and-drink",
    )

    amen = [
        ("Sound of Your Stay®", "Stream curated playlists with Tracks®, spin vinyl on a Crosley turntable with Wax®, or have a Fender guitar, headphones and an amp delivered with Picks®.", ("ny-sound", "ny-turntable.jpg")),
        ("Body Rock® Gym", "Let music be your motivating force at our Technogym-equipped fitness center, open daily.", ("ny-gym", "ny-fitness-center.jpg")),
        ("Rock Om®", "In-room yoga with Manduka mats and guided sessions set to music.", ("ny-rockom", "dest-spa-room.jpg")),
        ("Unleashed Pet Program", "Dogs are welcome: up to two pets totaling 50 lb per room in designated rooms, with a $175 cleaning fee per stay (part donated to the Humane Society).", ("ny-pets", "dest-pet-friendly-room.jpg")),
        ("Concierge Services", "Show tickets, restaurant reservations and transport, from a team that knows Midtown.", ("ny-concierge", "ny-lobby-memorabilia.jpg")),
        ("Sensory Inclusive", "Certified Sensory Inclusive with KultureCity: sensory bags and quiet spaces on request.", ("ny-hall", "ny-music-hallway.jpg")),
    ]
    ahtml = "".join(card(t, x, img(*p)) for t, x, p in amen)
    pol = [
        ("Check-in / Check-out", "Check-in 3:00 PM, check-out 11:00 AM. Early check-in and late check-out based on availability. Minimum check-in age 18."),
        ("Destination Fee", "$40 per night plus tax, including a $20 daily food and beverage credit, Wi-Fi, in-room Lavazza coffee, daily bottled water, Body Rock gym, Rock Om and Sound of Your Stay."),
        ("Cancellation", "Free cancellation until 24 hours before arrival unless your rate says otherwise; promotional rates can be non-refundable."),
        ("Pets", "Dogs welcome through Unleashed: up to 2 pets totaling 50 lb per room, designated rooms, $175 cleaning fee per stay."),
        ("Parking", "No on-site parking. Valet through a nearby garage: $85 a day for sedans, $95 for SUVs, no in-and-out."),
        ("Payment", "Cashless hotel. A card hold for incidentals is released at check-out."),
        ("Smoking", "Smoke-free building ($500 cleaning fee)."),
    ]
    add(
        "/new-york/amenities",
        "Amenities",
        subhero("Amenities", img("ny-amen-hero", "ny-lobby-memorabilia.jpg"))
        + f'<section class="page-intro"><p>Find your rhythm at Hard Rock Hotel New York: music-infused amenities in every room, Alexa, Sleep Like a Rock® beds, rainfall showers and Rock Spa® bath products.</p></section><div class="cards">{ahtml}</div>'
        + '<section id="hotel-policies"><h2 class="center">Hotel Policies</h2><dl class="info">' + "".join(f"<dt>{E(k)}</dt><dd>{E(v)}</dd>" for k, v in pol) + "</dl></section>",
        hotel=ny,
        cur="amenities",
    )

    area = [
        ("Times Square", "The crossroads of the world, a few blocks south.", ("ny-ts", "ny-times-square-bokeh.jpg")),
        ("Broadway", "The Theatre District starts at our door: catch a show and be back for a nightcap at RT60.", ("ny-bway", "ny-midtown-street-night.jpg")),
        ("Rockefeller Center", "The ice rink, the holiday tree and Top of the Rock, a short walk east.", ("ny-rock", "dest-city-skyline-hotel.jpg")),
        ("Radio City Music Hall", "The legendary venue is around the corner on Sixth Avenue.", ("ny-radio", "dest-concert-stage.jpg")),
        ("Fifth Avenue", "Flagship shopping from Rockefeller Center to Central Park.", ("ny-5th", "ny-midtown-street-night.jpg")),
        ("Bryant Park", "Lawn, seasonal markets and the New York Public Library, between 40th and 42nd Streets.", ("ny-bp", "dest-wedding-table.jpg")),
    ]
    add(
        "/new-york/area-guide",
        "Area Guide",
        subhero("Area Guide", img("ny-area", "ny-times-square-bokeh.jpg"))
        + '<section class="page-intro"><p>Within walking distance from Hard Rock Hotel New York are some of the world\'s most iconic sights and sounds. Also nearby: MoMA, Central Park, the Empire State Building, SUMMIT One Vanderbilt, Madison Square Garden, the High Line and the Javits Center.</p></section>'
        + f'<div class="cards">{"".join(card(t, x, img(*p)) for t, x, p in area)}</div>',
        hotel=ny,
        cur="area-guide",
    )

    # ---- Orlando ----
    orl = "orlando"
    add(
        "/orlando",
        "Orlando Hotel at Universal Orlando Resort",
        carousel([("", "Rock Your Universal Vacation", "Stay steps from Universal CityWalk with free Universal Express Unlimited ride access and Early Park Admission.", img("orl-hero", "dest-family-pool-slides.jpg"), "/orlando/offers")])
        + bookbar(orl)
        + """<section class="intro"><div><p class="eyebrow-dark">Inside Universal Orlando Resort</p><h1>Hard Rock Hotel<br>Orlando</h1></div><div><p>Rock-star style meets theme-park fun: 650 rooms including 29 suites, a 12,000 sq. ft. pool with a sand beach and a 260-foot waterslide, The Palm steakhouse and The Kitchen, and the world's largest Hard Rock Cafe a short walk away. Every stay includes free Universal Express Unlimited at Universal Studios Florida and Universal Islands of Adventure, Early Park Admission, and free water taxis and shuttles (valid park admission required).</p></div></section>"""
        + split("Rooms &amp; Suites", "From Pool View rooms to the Future Rock Star Suite with a kids' stage, there's a room for the whole band.", img("orl-room", "ny-room-double-queen.jpg"), f'<a class="btn-purple" href="{link("/orlando/rooms-and-suites")}">View Rooms &amp; Suites</a>')
        + split("Offers", "Save on 5+ night stays, add breakfast with Toast &amp; Jam, or make it a Romance Package.", img("orl-pool", "dest-family-pool-slides.jpg"), f'<a class="btn-purple" href="{link("/orlando/offers")}">View Offers</a>', flip=True),
        hotel=orl,
    )
    orooms = "".join(room_block(n, b, s, z, d, k, img(*p), orl, orl_from.get(n)) for n, b, s, z, d, k, p in ORL_ROOMS)
    add(
        "/orlando/rooms-and-suites",
        "Orlando Rooms & Suites",
        subhero("Rooms & Suites", img("orl-rooms-hero", "ny-room-double-queen.jpg"))
        + f'<section class="rooms-list">{orooms}<p class="be-fine center">Hard Rock Hotel Orlando books through Universal Orlando Resort (888-832-7155). Prices are illustrative "from" nightly rates.</p></section>',
        hotel=orl,
        cur="rooms-and-suites",
    )
    add(
        "/orlando/offers",
        "Orlando Hotel Offers",
        subhero("Orlando Hotel Offers", img("orl-offers-hero", "offer-pool-float.jpg"))
        + '<section class="offers">' + "".join(offer_card(orl, t, x, img(*p), None, None, terms) for t, x, terms, p in ORL_OFFERS) + "</section>",
        hotel=orl,
        cur="offers",
    )
    for slug, title, text in [
        ("eat-and-drink", "Eat & Drink", "The Kitchen (New American comfort food), The Palm (classic steakhouse), Velvet Bar, Beachclub poolside bar and grill, and Emack & Bolio's Marketplace. 24-hour room service."),
        ("amenities", "Amenities", "12,000 sq. ft. pool with sand beach and 260-foot waterslide, Body Rock fitness center, Rock Om, Sound of Your Stay, game room, Rock Shop, and Universal theme park benefits. Pets: up to 2 pets, 50 lb, $150 per stay, Garden View rooms only."),
        ("area-guide", "Area Guide", "Inside Universal Orlando Resort: walk or take the free water taxi to Universal CityWalk, Universal Studios Florida and Universal Islands of Adventure."),
    ]:
        add(f"/orlando/{slug}", title, subhero(title, img("orl-" + slug, "dest-family-pool-slides.jpg")) + f'<section class="page-intro"><p>{E(text)}</p></section>', hotel=orl, cur=slug)

    # ---- booking engine ----
    add("/book", "Book Your Stay", BOOK_BODY, hotel=ny, cur="book", plain=True)

    add(
        "/demo-only",
        "Demo only",
        '<section class="page-intro" style="padding:120px 15px"><h1>Demo only</h1><p>This page isn\'t part of the mockup. The demo covers the Hard Rock Hotels home page, destinations, offers, Unity, Hard Rock Hotel New York (rooms, offers, eat &amp; drink, amenities, area guide, booking) and Hard Rock Hotel Orlando.</p><a class="btn-gold" href="'
        + link("/")
        + '">Back to Home</a></section>',
    )
    add(
        "/credits",
        "Image credits",
        '<section class="page-intro"><h1>Image credits</h1><p>Photos in <code>/hardrock/img/</code> are Hard Rock International\'s own, reproduced from hotel.hardrock.com for this private demo. Photos in <code>/hardrock/img/gen/</code> were generated for this mockup (Gemini image model) to fill gaps, and do not show Hard Rock venues.</p></section>',
    )
    return pages


def main():
    out = sys.argv[1]
    pages = build()
    for path, doc in pages:
        d = os.path.join(out, path.strip("/"))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(doc)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    for name in ("site.css", "bookflow.js"):
        with open(os.path.join(HERE, name)) as f, open(os.path.join(out, "assets", name), "w") as g:
            g.write(f.read())
    bk = load_booking()
    pics = {}
    for h, rooms in (("new-york", NY_ROOM_PICS),):
        for name, (key, fb) in rooms.items():
            pics[name] = img(key, fb)
    pics["Accessible Classic King"] = pics["Accessible Rooms"]
    bk["pics"] = pics
    bk["hero"] = img("ny-book-hero", "ny-lobby-memorabilia.jpg")
    with open(os.path.join(out, "assets", "booking-data.js"), "w") as g:
        g.write("window.HR_BOOKING = " + json.dumps(bk) + ";\n")
    print(f"{len(pages)} pages -> {out}")


if __name__ == "__main__":
    main()
