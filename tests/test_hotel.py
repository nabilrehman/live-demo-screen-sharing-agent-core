"""Kai on the hotel site (src/inpage/hotel.py): the data is consistent, the prompt is complete, and the page note and
"this one" resolution work."""

import datetime
import time

from inpage.hotel import CITIES, DATA, HOTELS, LIVE, HotelPage, calendar_text, greeting, prompt, rooms_of

CHECKOUT = {
    "seq": 9,
    "step": "checkout",
    "today": "2026-10-20",
    "search": {"destination": "New York, NY", "check_in": "2026-10-23", "check_out": "2026-10-25", "nights": 2, "adults": 2, "children": 1, "rooms": 1},
    "hotel": {"id": "nyc-park-avenue", "name": "Lakeline Park Avenue", "tax_rate": 0.163, "fee": "none", "check_in": "4:00 PM", "check_out": "12:00 PM"},
    "selected": {"room": "deluxe-king", "rate": "flexible", "total_with_taxes": 1076.94},
    "checkout": {
        "room": "Deluxe King, Guest room, 1 King, City view", "rate": "Flexible Rate", "check_in": "Fri, October 23, 2026",
        "check_out": "Sun, October 25, 2026", "nights": 2, "guests": "2 adults, 1 children", "per_night": ["Fri, Oct 23 463", "Sat, Oct 24 463"],
        "room_total": 926, "taxes_and_fees": 150.94, "total": 1076.94, "due_now": 0, "cancel_policy": "You may cancel for no charge before 11:59 PM.",
        "requests": ["Crib"], "hold_left": "14 min", "demo_details_filled": False, "book_button": "disabled until demo details are filled",
    },
}  # fmt: skip


def test_hotels_rooms_and_prices_line_up():
    assert LIVE and all(c["id"] in DATA["room_sets"] for c in LIVE)
    for h in HOTELS.values():
        assert h["city"] in CITIES and h["rooms"]
        for r in rooms_of(h):
            weekday, weekend = h["rooms"][r["id"]]
            assert 300 < weekday <= weekend < 2000, (h["id"], r["id"])
            assert r["photos"] and all(p["file"] and p["caption"] for p in r["photos"])
    assert {x["id"] for x in DATA["rates"]} == {"flexible", "member", "prepaid"}


def test_prompt_and_greeting_complete():
    p = prompt(datetime.date(2026, 10, 20))
    assert "{" not in p.split("# The hotels")[0]
    assert "Fri Oct 23 = 2026-10-23" in p and "Tuesday, October 20, 2026" in p
    assert "Lakeline Park Avenue [nyc-park-avenue]" in p and "Coming soon" in p
    g = greeting()
    assert "Kai" in g and "{" not in g


def test_calendar_has_a_line_per_week():
    lines = calendar_text(datetime.date(2026, 10, 20)).splitlines()
    assert lines[0].startswith("Tue Oct 20 = 2026-10-20 (today)") and lines[0].endswith("Sun Oct 25 = 2026-10-25")
    assert lines[1].startswith("Mon Oct 26")


def test_note_shows_checkout():
    p = HotelPage()
    p.update(CHECKOUT)
    n = p.note()
    assert "total for stay 1,076.94 USD" in n and "Room requests: Crib." in n
    assert "room held for 14 min" in n and "not filled yet" in n


def test_this_one_and_signature():
    p = HotelPage()
    p.update(CHECKOUT)
    assert p.resolve_room("the king") == "the king"  # words go to the page as said
    assert p.resolve_room("this one") == "deluxe-king"  # the selected room
    p.update({**CHECKOUT, "seq": 10, "room_details": {"room": "park-king"}})
    assert p.resolve_room("it") == "park-king"
    p.update({**CHECKOUT, "seq": 11, "last_interaction": {"id": "gallery-suite", "kind": "room", "ms_ago": 200}})
    assert p.resolve_room("that room") == "gallery-suite"
    p.at = time.monotonic() - 60  # an old click no longer counts
    assert p.resolve_room("that room") == "deluxe-king"
    assert p.resolve_hotel("this hotel") == "nyc-park-avenue"
    sig = p.signature()
    p.update({**CHECKOUT, "seq": 12, "last_interaction": {"id": "gallery-suite", "kind": "room", "ms_ago": 900}})
    assert p.signature() == sig  # timings and sequence numbers don't count as changes
    assert not p.update({**CHECKOUT, "seq": 3})  # older snapshots are ignored
