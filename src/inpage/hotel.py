"""The hotel booking site Kai helps on (the fictional Lakeline Hotels demo): its data, prompt and greeting from
knowledge/hotel/ (HOTEL_KNOWLEDGE to swap in another), and what the customer's page shows now (the latest
page_context snapshot) as a short note.

lakeline_hotels.json is the page's data: the page's data.js is `window.LAKELINE_DATA = <this JSON>;`. To refresh the
page from it, from the page folder:
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));open('data.js','w').write('window.LAKELINE_DATA = '+json.dumps(d,ensure_ascii=False)+';\\n')" <repo>/knowledge/hotel/lakeline_hotels.json
"""

import datetime
import json
import os
import re
import time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE = os.getenv("HOTEL_KNOWLEDGE", os.path.join(ROOT, "knowledge", "hotel"))
RECENT_TOUCH_S = 15  # a click on a hotel or room counts as "this one" for this long
CALENDAR_DAYS = 35
DEICTIC = re.compile(r"^(it|this|that|this one|that one|the one|this room|that room|this hotel|that hotel|here)$")


def _load(name: str) -> str:
    with open(os.path.join(KNOWLEDGE, name)) as f:
        return f.read()


DATA: dict = json.loads(_load(next(n for n in sorted(os.listdir(KNOWLEDGE)) if n.endswith("_hotels.json"))))
HOTELS: dict[str, dict] = {h["id"]: h for h in DATA["hotels"]}
CITIES: dict[str, dict] = {c["id"]: c for c in DATA["cities"]}
BRANDS: dict[str, dict] = {b["id"]: b for b in DATA["brands"]}
RATES: dict[str, dict] = {r["id"]: r for r in DATA["rates"]}
LIVE = [c for c in DATA["cities"] if not c.get("coming_soon")]  # cities with hotels; the others are "coming soon"


def rooms_of(h: dict) -> list[dict]:
    """The hotel's rooms: its city's room set, only the ids the hotel lists."""
    by_id = {r["id"]: r for r in DATA["room_sets"][h["city"]]}
    return [by_id[i] for i in h["rooms"]]


def money(n: float | None) -> str:
    if n is None:
        return "-"
    return f"{n:,.2f} USD" if n != int(n) else f"{int(n):,} USD"


def room_line(r: dict) -> str:
    return (
        f"- {r['name']} [{r['id']}]: {r['bed']}, {r['size_sqft']} sq ft, {r['view']}, sleeps {r['max_guests']}. "
        f"Bathroom: {r['bath']}. Extra bed: {r['extra_bed']}. Accessibility: {r['accessibility']}. "
        f"In the room: {', '.join(r['features'])}. Photos: {', '.join(p['kind'] for p in r['photos'])}."
    )


def hotel_text(h: dict) -> str:
    a = h["amenities"]
    have = [k for k in ("pool", "spa", "fitness") if a.get(k)]
    fee = f"{h['fee_name']} {h['fee']} USD per night ({h['fee_covers']})" if h["fee"] else "no resort or hotel fee"
    lines = [
        f"### {h['name']} [{h['id']}] ({BRANDS[h['brand']]['name']})",
        f"{h['area']}, {h['distance_mi']} mi from {CITIES[h['city']]['center']}. {h['address']}. Rating {h['rating']} "
        f"({h['reviews']:,} reviews). {h['description']}",
        f"Free breakfast: {'yes' if a.get('breakfast') else 'no'}. Pool: {'yes' if a.get('pool') else 'no'}. "
        f"Pets: {'yes' if a.get('pets') else 'no'}. Parking: {a.get('parking')}. "
        + (f"Also: {', '.join(have)}." if have else ""),
        f"Check-in {h['check_in']}, check-out {h['check_out']}. Taxes {round(h['tax_rate'] * 100, 1)}%; {fee}."
        + (" Adults only (18+)." if h.get("adults_only") else ""),
        "Highlights: " + "; ".join(h["highlights"]) + ".",
        "Nearby: " + "; ".join(h["nearby"]) + ".",
        "Rooms: " + ", ".join(f"{r['name']} [{r['id']}]" for r in rooms_of(h)) + ".",
    ]
    return "\n".join(lines)


def site_text() -> str:
    out = []
    for c in LIVE:
        out.append(f"## {c['label']} (destination id {c['id']})")
        out.append(f"Room types at {c['name']} hotels (each hotel lists which it has):")
        out += [room_line(r) for r in DATA["room_sets"][c["id"]]]
        out += [hotel_text(h) for h in DATA["hotels"] if h["city"] == c["id"]]
    soon = [c["name"] for c in DATA["cities"] if c.get("coming_soon")]
    if soon:
        out.append(f"\nComing soon (no hotels in this demo yet): {', '.join(soon)}.")
    out.append("\n## Rates (every room has these three)")
    out += [f"- {r['name']} [{r['id']}]: {r['explain']}." for r in DATA["rates"]]
    out.append("\n## Policies (all hotels)")
    out += [f"- {p['title']}: {p['text']}" for p in DATA["policies"]]
    lim = DATA["limits"]
    out.append(
        f"- Booking limits in this demo: one room, up to {lim['max_adults']} adults and {lim['max_children']} "
        f"children, up to {lim['max_nights']} nights."
    )
    return "\n".join(out)


def today_in(tz: str = "America/Chicago") -> datetime.date:
    return datetime.datetime.now(ZoneInfo(tz)).date()


def calendar_text(today: datetime.date) -> str:
    """The next weeks as 'Fri Oct 23 = 2026-10-23', so relative dates ('next Friday') need no arithmetic."""
    days = [today + datetime.timedelta(days=i) for i in range(CALENDAR_DAYS)]
    weeks, week = [], []
    for d in days:
        week.append(f"{d:%a %b} {d.day} = {d.isoformat()}" + (" (today)" if d == today else ""))
        if d.weekday() == 6:  # a line per week, Monday to Sunday
            weeks.append(", ".join(week))
            week = []
    if week:
        weeks.append(", ".join(week))
    return "\n".join(weeks)


def prompt(today: datetime.date | None = None) -> str:
    today = today or today_in()
    return (
        _load("kai_prompt.md")
        .replace("{brand}", DATA["brand"])
        .replace("{assistant}", DATA["assistant"])
        .replace("{cities}", ", ".join(c["label"] for c in LIVE))
        .replace("{today}", f"{today:%A, %B} {today.day}, {today.year} ({today.isoformat()})")
        .replace("{calendar}", calendar_text(today))
        .replace("{site}", site_text())
    )


def greeting() -> str:
    return (
        _load("greeting.md")
        .strip()
        .replace("{brand}", DATA["brand"])
        .replace("{assistant}", DATA["assistant"])
        .replace("{cities}", ", ".join(c["name"] for c in LIVE))
    )


class HotelPage:
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

    def touched(self, kind: str) -> str | None:
        """The hotel or room the customer clicked in the last few seconds."""
        li = self.ctx.get("last_interaction")
        if not li or li.get("kind") != kind:
            return None
        age = li.get("ms_ago", 0) / 1000 + time.monotonic() - self.at
        return li["id"] if age < RECENT_TOUCH_S else None

    def resolve_room(self, ref: str | None) -> str | None:
        """A room id for "this one" / "it": the room whose photos or details are open, then a room just clicked, then
        the selected room. Anything else goes to the page as said (an id, or words it matches against room names)."""
        low = (ref or "").lower().strip(" .?!")
        if low and not DEICTIC.match(low):
            return ref
        c = self.ctx
        pick = (
            (c.get("room_details") or {}).get("room") or self.touched("room") or (c.get("selected") or {}).get("room")
        )
        return pick or ref

    def resolve_hotel(self, ref: str | None) -> str | None:
        low = (ref or "").lower().strip(" .?!")
        if low and not DEICTIC.match(low):
            return ref
        return (self.ctx.get("hotel") or {}).get("id") or self.touched("hotel") or ref

    def note(self) -> str:
        c = self.ctx
        if not c:
            return "<page_now>The page hasn't reported yet.</page_now>"
        s = c.get("search") or {}
        stay = (
            f"{s['check_in']} to {s['check_out']} ({s['nights']} night{'s' if s['nights'] != 1 else ''})"
            if s.get("nights")
            else "no dates yet"
        )
        who = f"{s.get('adults', 1)} adult{'s' if s.get('adults', 1) != 1 else ''}, {s.get('children', 0)} children"
        lines = [
            f"Step: {c.get('step')}. Search: {s.get('destination') or 'no destination yet'}; {stay}; {who}; "
            f"{s.get('rooms', 1)} room."
        ]
        if c.get("notice"):
            lines.append(f"The page says: {c['notice']}")
        if c.get("open_menu"):
            lines.append(f"Open on the page: the {c['open_menu']} menu.")
        if r := c.get("results"):
            f = r.get("filters") or []
            extra = [f"under {r['max_price']} USD"] if r.get("max_price") else []
            extra += [f"brand {b}" for b in r.get("brands") or []]
            lines.append(
                f"Results: {r['shown']} of {r['total']} hotels, sorted by {r['sort']}, "
                f"filters: {', '.join(f + extra) or 'none'}{'; map view' if r.get('view') == 'map' else ''}."
            )
            for h in r.get("hotels") or []:
                price = (
                    f"from {money(h['from_per_night'])}/night before taxes"
                    if h.get("from_per_night") is not None
                    else "not available for this search"
                )
                lines.append(
                    f"{h['n']}. {h['name']} [{h['id']}]: {h['rating']} ({h['reviews']:,} reviews), "
                    f"{h['distance_mi']} mi, {price}; {', '.join(h['amenities']) or 'no listed extras'}"
                    + ("; adults only" if h.get("adults_only") else "")
                )
        if h := c.get("hotel"):
            lines.append(
                f"Hotel open: {h['name']} [{h['id']}]; taxes {round(h['tax_rate'] * 100, 1)}%, fee: {h['fee']}."
            )
        if c.get("step") == "hotel":
            lines.append(f"Prices shown {'with' if c.get('taxes_shown') else 'before'} taxes and fees.")
            for r in c.get("rooms") or []:
                head = f"- {r['name']} [{r['id']}], sleeps {r['sleeps']}"
                if r.get("available") is False:
                    lines.append(f"{head}: {r['why']}.")
                elif r.get("rates"):
                    rates = "; ".join(
                        f"{RATES[k]['name'] if k in RATES else k} {money(v['per_night'])}/night, "
                        f"total with taxes and fees {money(v['total_with_taxes'])}"
                        for k, v in r["rates"].items()
                    )
                    lines.append(f"{head}{' (rates open)' if r.get('expanded') else ''}: {rates}.")
                else:
                    lines.append(f"{head}: add dates for prices.")
        if g := c.get("room_details"):
            mode = "photo gallery" if g.get("mode") == "photos" else "room details with photos"
            lines.append(
                f"Open: {mode} for {g['name']} [{g['room']}], photo {g['photo']} of {g['of']} ({g.get('kind', '')}): "
                f"{g['caption']}"
            )
        if sel := c.get("selected"):
            lines.append(
                f"Selected: {sel['room']} with the {sel['rate']} rate, total {money(sel['total_with_taxes'])} with taxes."
            )
        if co := c.get("checkout"):
            lines.append(
                f"Booking: {co['room']}, {co['rate']}; {co['check_in']} to {co['check_out']}, {co['nights']} nights, "
                f"{co['guests']}. Per night: {'; '.join(co['per_night'])}. Room {money(co['room_total'])}, taxes and fees "
                f"{money(co['taxes_and_fees'])}, total for stay {money(co['total'])}, due now {money(co['due_now'])}. "
                f"Cancel policy: {co['cancel_policy']} Room requests: {', '.join(co.get('requests') or []) or 'none'}."
            )
            if "hold_left" in co:
                lines.append(
                    f"Checkout page (demo): room held for {co['hold_left']}; demo guest details "
                    f"{'filled' if co.get('demo_details_filled') else 'not filled yet'}; book button: {co['book_button']}."
                )
        if cf := c.get("confirmation"):
            lines.append(f"Demo confirmation shown: number {cf['number']} ({cf['note']}).")
        if hl := c.get("highlighted"):
            lines.append("Highlighted: " + ", ".join(hl) + ".")
        for kind in ("hotel", "room"):
            if t := self.touched(kind):
                lines.append(f"Customer just clicked the {kind} [{t}].")
        return "<page_now>\n" + "\n".join(lines) + "\n</page_now>"
