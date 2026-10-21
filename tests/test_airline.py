"""Kai on the airline site (src/inpage/airline.py): the data is consistent, the prompt is complete, and the page note
and "this one" resolution work on real snapshots from the page (tests/fixtures/airline_snapshots.json)."""

import datetime
import json
import os
import time

from inpage.airline import AIRPORTS, DATA, FARES, AirlinePage, calendar_text, greeting, prompt

SNAP = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "airline_snapshots.json")))


def test_network_and_fares_line_up():
    assert DATA["hub"] in AIRPORTS and len(AIRPORTS) >= 10
    for leg in DATA["legs"]:
        assert leg["from"] in AIRPORTS and leg["to"] in AIRPORTS and leg["flights"]
        assert 30 < leg["minutes"] < 20 * 60 and leg["miles"] > 100
    hub = DATA["hub"]
    for code in AIRPORTS:  # every city reaches the hub and back
        assert code == hub or any(l["from"] == code and l["to"] == hub for l in DATA["legs"])
        assert code == hub or any(l["from"] == hub and l["to"] == code for l in DATA["legs"])
    rows = {r["id"] for r in DATA["fare_rows"]}
    assert set(FARES) == {"economy-convenience", "economy-comfort", "business-comfort", "business-elite"}
    assert all(set(f["rows"]) == rows for f in DATA["fares"])


def test_prompt_and_greeting_complete():
    p = prompt(datetime.date(2026, 10, 20))
    assert "{" not in p.split("# Aurelian Airways (fictional")[0]
    assert "Thu Oct 29 = 2026-10-29" in p and "Tuesday, October 20, 2026" in p
    assert "Economy Comfort [economy-comfort]" in p and "TOTALS FOR ALL PASSENGERS" in p
    assert "never press Pay" in p
    g = greeting()
    assert "Kai" in g and "Aurelian Airways" in g and "{" not in g


def test_calendar_has_a_line_per_week():
    lines = calendar_text(datetime.date(2026, 10, 20)).splitlines()
    assert lines[0].startswith("Tue Oct 20 = 2026-10-20 (today)") and lines[0].endswith("Sun Oct 25 = 2026-10-25")


def test_note_shows_results_totals_and_per_adult():
    p = AirlinePage()
    p.update(SNAP["results"])
    n = p.note()
    assert "Prices are totals for all 2 passengers" in n
    assert "1. [AU702] AU702, departs 01:20" in n and "per adult" in n
    assert "Fare comparison open for flight 1 [AU702], economy: Economy Convenience" in n
    assert "Date strip" in n
    assert (
        "Summary: 6 flights. Cheapest economy: #4 AU7712 + AU12" in n
        and "3 non-stop: #1 AU702 at 01:20 1,583 USD (fifteen eighty-three)" in n
    )


def test_note_shows_passengers():
    p = AirlinePage()
    p.update(SNAP["passengers"])
    n = p.note()
    assert "1. Adult 1: Mr Nabil Rehman (complete)" in n and "2. Adult 2: no details yet (incomplete)" in n
    assert "grand total" in n


def test_this_one_and_signature():
    p = AirlinePage()
    p.update(SNAP["results"])
    assert p.resolve_flight("the cheapest non-stop") == "the cheapest non-stop"  # words go to the page as said
    assert p.resolve_flight("this one") == "AU702"  # the flight whose fares are open
    p.update(
        {
            **SNAP["results"],
            "seq": 50,
            "fares_open": None,
            "last_interaction": {"id": "AU704", "kind": "flight", "ms_ago": 100},
        }
    )
    assert p.resolve_flight("that flight") == "AU704"
    p.at = time.monotonic() - 60
    assert p.resolve_flight("it") == "it"
    sig = p.signature()
    p.update(
        {
            **SNAP["results"],
            "seq": 51,
            "fares_open": None,
            "last_interaction": {"id": "AU704", "kind": "flight", "ms_ago": 900},
        }
    )
    assert p.signature() == sig
    assert not p.update({**SNAP["results"], "seq": 3})


def test_spoken_dollars():
    from inpage.airline import spoken

    assert (
        spoken(1356) == "thirteen fifty-six" and spoken(678) == "six seventy-eight" and spoken(2000) == "two thousand"
    )
    assert spoken(1905) == "nineteen oh five" and spoken(1100) == "eleven hundred" and spoken(12450) == "12,450"
