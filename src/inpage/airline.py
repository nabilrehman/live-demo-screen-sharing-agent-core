"""The airline booking site Kai helps on (the fictional Aurelian Airways demo): its data, prompt and greeting from
knowledge/airline/ (AIRLINE_KNOWLEDGE to swap in another), and what the traveller's page shows now (the latest
page_context snapshot) as a short note.

aurelian_airways.json is the page's data: the page's data.js is `window.AURELIAN_DATA = <this JSON>;`. The page derives
each day's flights and fares from it deterministically, so Kai learns flights and prices only from the page's notes."""

import datetime
import json
import os
import re
import time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE = os.getenv("AIRLINE_KNOWLEDGE", os.path.join(ROOT, "knowledge", "airline"))
RECENT_TOUCH_S = 15  # a click on a flight counts as "this one" for this long
CALENDAR_DAYS = 42
DEICTIC = re.compile(r"^(it|this|that|this one|that one|the one|this flight|that flight|here)$")


def _load(name: str) -> str:
    with open(os.path.join(KNOWLEDGE, name)) as f:
        return f.read()


DATA: dict = json.loads(_load(next(n for n in sorted(os.listdir(KNOWLEDGE)) if n.endswith(".json"))))
AIRPORTS: dict[str, dict] = {a["code"]: a for a in DATA["airports"]}
FARES: dict[str, dict] = {f["id"]: f for f in DATA["fares"]}


def money(n: float | None) -> str:
    if n is None:
        return "-"
    return f"{n:,.2f} USD" if round(n, 2) != int(n) else f"{int(n):,} USD"


ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _two(n: int) -> str:
    return ONES[n] if n < 20 else TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")


def spoken(n: float) -> str:
    """How people say a dollar amount: 1356 -> "thirteen fifty-six", 678 -> "six seventy-eight", 2000 -> "two
    thousand". Given next to totals because the voice model misreads digit strings ("fifteen thirty-six" for 1,356)."""
    n = round(n)
    if n < 100 or n >= 10000:
        return f"{n:,}"
    hi, lo = divmod(n, 100)
    if lo == 0:
        return f"{ONES[n // 1000]} thousand" if n % 1000 == 0 else f"{_two(hi)} hundred"
    return f"{_two(hi)} {'oh ' + ONES[lo] if lo < 10 else _two(lo)}"


def dollars(n: float | None) -> str:
    """Whole dollars, the way the page's price boxes show them, with how to say it."""
    return "-" if n is None else f"{round(n):,} USD ({spoken(n)})"


def summary(flights: list[dict]) -> str:
    """The facts Kai says first after a search, worked out here so it doesn't misread the list."""
    if not flights:
        return "Summary: no flights shown."
    cheap = min(flights, key=lambda f: f["economy_total"])
    nonstop = [f for f in flights if f["stops"] == "non-stop"]
    ns = (
        f"{len(nonstop)} non-stop: "
        + "; ".join(f"#{f['n']} {f['flights']} at {f['depart']} {dollars(f['economy_total'])}" for f in nonstop)
        if nonstop
        else "no non-stop flights"
    )
    return (
        f"Summary: {len(flights)} flight{'s' if len(flights) != 1 else ''}. Cheapest economy: #{cheap['n']} "
        f"{cheap['flights']} at {cheap['depart']}, {cheap['stops']}, {dollars(cheap['economy_total'])} total "
        f"({dollars(cheap['economy_per_adult'])} per adult). {ns}."
    )


def network_text() -> str:
    hub = DATA["hub"]
    lines = []
    for a in DATA["airports"]:
        out = [AIRPORTS[l["to"]]["city"] for l in DATA["legs"] if l["from"] == a["code"]]
        lines.append(f"- {a['city']} ({a['code']}, {a['name']}, {a['country']}): non-stop to {', '.join(out)}.")
    lines.append(
        f"Every other pair connects with one stop, usually via {AIRPORTS[hub]['city']} ({hub}). Schedules vary by day; "
        "the results page shows the flights for the chosen date."
    )
    return "\n".join(lines)


def fares_text() -> str:
    rows = {r["id"]: r["label"] for r in DATA["fare_rows"]}
    out = []
    for f in DATA["fares"]:
        cells = "; ".join(f"{rows[k]}: {v}" for k, v in f["rows"].items())
        info = " ".join(f.get("info", {}).values())
        out.append(
            f"- {f['name']} [{f['id']}] ({f['cabin']}): {cells}. Earns {int(f['earn'] * 100)}% of miles flown in "
            f"{DATA['miles']}. {info}".strip()
        )
    return "\n".join(out)


def site_text() -> str:
    ac = "; ".join(
        f"{v['name']}: business is {v['business']}{', Starlink Wi-Fi' if v['wifi'] else ''}"
        for v in DATA["aircraft"].values()
    )
    extras = "; ".join(f"{x['name']} {x['price']} USD per {x['per']}" for x in DATA["extras"])
    return "\n".join(
        [
            f"Loyalty club: {DATA['club']} (free); miles are called {DATA['miles']}. Business product: {DATA['suite']}. "
            f"Hub: {AIRPORTS[DATA['hub']]['city']} ({DATA['hub']}). Promo code for members: {DATA['promo_code']}.",
            "## Where we fly",
            network_text(),
            "## Fare families (the page's comparison table)",
            fares_text(),
            "## Aircraft",
            ac + ".",
            "## Extras (Seats & extras step)",
            extras + ".",
            "## Policies",
            *[f"- {p['title']}: {p['text']}" for p in DATA["policies"]],
            f"- Booking limits in this demo: up to {DATA['limits']['max_passengers']} seated passengers, one infant per "
            "adult, return or one way (multi-city isn't available).",
        ]
    )


def today_in(tz: str = "America/Chicago") -> datetime.date:
    return datetime.datetime.now(ZoneInfo(tz)).date()


def calendar_text(today: datetime.date) -> str:
    """The next weeks as 'Thu Oct 29 = 2026-10-29', so relative dates ('next Thursday') need no arithmetic."""
    days = [today + datetime.timedelta(days=i) for i in range(CALENDAR_DAYS)]
    weeks, week = [], []
    for d in days:
        week.append(f"{d:%a %b} {d.day} = {d.isoformat()}" + (" (today)" if d == today else ""))
        if d.weekday() == 6:
            weeks.append(", ".join(week))
            week = []
    if week:
        weeks.append(", ".join(week))
    return "\n".join(weeks)


def _fill(text: str) -> str:
    return (
        text.replace("{brand}", DATA["brand"])
        .replace("{assistant}", DATA["assistant"])
        .replace("{cities}", ", ".join(f"{a['city']} ({a['code']})" for a in DATA["airports"]))
    )


def prompt(today: datetime.date | None = None) -> str:
    today = today or today_in()
    return (
        _fill(_load("kai_prompt.md"))
        .replace("{today}", f"{today:%A, %B} {today.day}, {today.year} ({today.isoformat()})")
        .replace("{calendar}", calendar_text(today))
        .replace("{site}", site_text())
    )


def greeting() -> str:
    return _fill(_load("greeting.md").strip())


class AirlinePage:
    def __init__(self):
        self.ctx: dict = {}
        self.at = 0.0  # when the snapshot arrived (monotonic)

    def update(self, ctx: dict) -> bool:
        """Keep the newest snapshot (the page numbers them); False if it's older than the one we have."""
        if ctx.get("seq", 0) < self.ctx.get("seq", 0):
            return False
        self.ctx, self.at = ctx, time.monotonic()
        return True

    def update_json(self, text: str) -> bool:
        try:
            return self.update(json.loads(text))
        except (ValueError, TypeError):
            return False

    def signature(self) -> str:
        """What the model should hear about again when it changes (not timings or sequence numbers)."""
        c = {k: v for k, v in self.ctx.items() if k not in ("seq", "last_interaction")}
        li = self.ctx.get("last_interaction")
        return json.dumps([c, li and li["id"]], sort_keys=True)

    def touched(self) -> str | None:
        """The flight the traveller clicked in the last few seconds."""
        li = self.ctx.get("last_interaction")
        if not li or li.get("kind") != "flight":
            return None
        age = li.get("ms_ago", 0) / 1000 + time.monotonic() - self.at
        return li["id"] if age < RECENT_TOUCH_S else None

    def resolve_flight(self, ref: str | None) -> str | None:
        """A flight id for "this one" / "it": the flight whose fares are open, then one just clicked, then the one whose
        details are open. Anything else goes to the page as said (an id, a flight number, a time, "the cheapest
        non-stop", "the second one")."""
        low = (ref or "").lower().strip(" .?!")
        if low and not DEICTIC.match(low):
            return ref
        c = self.ctx
        return (c.get("fares_open") or {}).get("flight") or self.touched() or c.get("details_open") or ref

    def note(self) -> str:
        c = self.ctx
        if not c:
            return "<page_now>The page hasn't reported yet.</page_now>"
        s = c.get("search") or {}
        who = f"{s.get('adults', 1)} adult{'s' if s.get('adults', 1) != 1 else ''}"
        if s.get("children"):
            who += f", {s['children']} child{'ren' if s['children'] != 1 else ''}"
        if s.get("infants"):
            who += f", {s['infants']} infant{'s' if s['infants'] != 1 else ''}"
        trip = f"return {s.get('depart')} to {s.get('return')}" if s.get("return") else f"one way {s.get('depart')}"
        lines = [
            f"Step: {c.get('step')}. Search: {s.get('from') or '?'} to {s.get('to') or 'no destination yet'}; {trip}; "
            f"{who}; {s.get('cabin', 'economy')}."
        ]
        if d := c.get("search_form_draft"):
            lines.append(f"Search form (not searched yet): {json.dumps(d)}")
        if c.get("notice"):
            lines.append(f"The page says: {c['notice']}")
        if c.get("open_menu"):
            lines.append(f"Open on the page: the {c['open_menu']} menu.")
        if r := c.get("results"):
            lines.append(
                f"{r['leg'].capitalize()} flights {r['route']} on {r['date']}: {r['shown']} of {r['total']} shown, sorted "
                f"by {r['sort']}, filters: {', '.join(r['filters']) or 'none'}. Prices are {r['prices_are']}."
            )
            for f in r.get("flights") or []:
                lines.append(
                    f"{f['n']}. [{f['id']}] {f['flights']}, departs {f['depart']}, arrives {f['arrive']}, {f['duration']}, "
                    f"{f['stops']}{', ' + f['connection'] + ' connection' if f.get('connection') else ''}; {f['aircraft']}"
                    f"{'; Aurora Suite' if f.get('suite') else ''}. Economy from {dollars(f['economy_total'])} total "
                    f"({dollars(f['economy_per_adult'])} per adult); Business from {dollars(f['business_total'])} "
                    f"total ({dollars(f['business_per_adult'])} per adult)."
                )
            lines.append(summary(r.get("flights") or []))
            if r.get("date_strip"):
                lines.append("Date strip (lowest total per day): " + "; ".join(r["date_strip"]) + ".")
        if fo := c.get("fares_open"):
            fares = "; ".join(
                f"{f['name']} {dollars(f['total'])} total ({dollars(f['per_adult'])} per adult), {f['seats_left']} seats "
                f"left, earns {f['earn_aurels']:,} Aurels"
                for f in fo["fares"]
            )
            lines.append(f"Fare comparison open for flight {fo['n']} [{fo['flight']}], {fo['cabin']}: {fares}.")
        if c.get("details_open"):
            lines.append(f"Flight details open for [{c['details_open']}].")
        if c.get("selection_sheet"):
            lines.append(c["selection_sheet"] + ".")
        for leg, x in (c.get("selected") or {}).items():
            lines.append(
                f"Selected {leg}: {x['flights']} on {x['date']}, {x['depart']} to {x['arrive']}, {x['fare']}, "
                f"{dollars(x['total'])} total."
            )
        if pax := c.get("passengers"):
            lines.append(
                "Passengers: "
                + "; ".join(
                    f"{p['n']}. {p['label']}: "
                    + (
                        " ".join(x for x in (p.get("title"), p.get("first_name"), p.get("last_name")) if x)
                        or "no details yet"
                    )
                    + (" (complete)" if p.get("complete") else " (incomplete)")
                    + (" (form open)" if p.get("form_open") else "")
                    for p in pax
                )
                + "."
            )
        if t := c.get("totals"):
            lines.append(
                f"Totals: fares {money(t['fares'])}, seats {money(t['seats'])}, extras {money(t['extras'])}, grand total "
                f"{money(t['grand_total'])}."
            )
        if co := c.get("contact"):
            lines.append(
                f"Contact form: email {'entered' if co['email_entered'] else 'empty'}, phone "
                f"{'entered' if co['phone_entered'] else 'empty'} (the traveller types these)."
            )
        if c.get("seat_flights"):
            lines.append(
                "Seat maps: "
                + "; ".join(c["seat_flights"])
                + ". Seats: "
                + ("; ".join(c.get("seats") or []) or "none chosen")
                + "."
            )
        if x := c.get("extras"):
            lines.append(
                f"Extras: {x['extra_bags']} extra bags, {x['lounge_passes']} lounge passes, travel protection "
                f"{'on' if x['travel_protection'] else 'off'}."
            )
        if p := c.get("payment"):
            lines.append(f"Payment form (demo): {p['fields_filled_by_traveller']} filled by the traveller. {p['note']}")
        if cf := c.get("confirmation"):
            lines.append(f"Demo confirmation shown: reference {cf['reference']} ({cf['note']}).")
        if c.get("open_dialog"):
            lines.append(f"Open: the {c['open_dialog']}.")
        if hl := c.get("highlighted"):
            lines.append("Highlighted: " + ", ".join(hl) + ".")
        if t := self.touched():
            lines.append(f"Traveller just clicked the flight [{t}].")
        return "<page_now>\n" + "\n".join(lines) + "\n</page_now>"
