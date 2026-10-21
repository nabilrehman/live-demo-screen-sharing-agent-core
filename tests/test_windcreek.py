"""Kai on the Wind Creek site (src/inpage/site.py, insights.py): the prompt is complete, dates resolve, page snapshots
from a new page load replace the old page's, blocked pages stay blocked, and the session summary carries no personal
data."""

import datetime as dt
import json
import re

from inpage.insights import Insights, scrub
from inpage.site import SitePage, allowed_path, greeting, load, prompt, today


def snap(page_id, seq, path="/", loaded_at=1000, **kw):
    return {"page_id": page_id, "seq": seq, "path": path, "loaded_at": loaded_at, "title": "T", **kw}


def test_prompt_and_greeting_complete():
    p = prompt(dt.datetime(2026, 10, 20, 12))
    assert "{" not in p.split("# Facts about")[0]
    assert "Tuesday, October 20, 2026" in p and "Saturday October 24 and Sunday October 25" in p
    assert "1-800-GAMBLER" in p and "20,000" in p and "Chop House" in p
    g = greeting()
    assert "AI concierge" in g and "{" not in g


def test_weekend_on_sunday_is_today():
    assert "Saturday October 24 and Sunday October 25" in today(dt.datetime(2026, 10, 25, 9))


def test_rewards_numbers_match_the_site():
    r = load("rewards.md")
    for s in (
        "Escape: 20,000 to 74,999",
        "Delight: 75,000 to 199,999",
        "Fantasy: 200,000+",
        "$150 / $300 / $400",
        "10% / 15% / 25% / 50%",
    ):
        assert s in r, s


def test_new_page_replaces_old_even_with_lower_seq():
    p = SitePage()
    assert p.update(snap("a", 7, "/"))
    assert not p.update(snap("a", 3, "/"))  # older snapshot of the same page
    assert p.update(snap("b", 1, "/bethlehem/promotions", loaded_at=2000))
    assert p.loaded.is_set() and p.ctx["path"] == "/bethlehem/promotions"
    assert not p.update(snap("c", 9, "/old", loaded_at=1500))  # a page load from before the current one
    assert [v["path"] for v in p.visited] == ["/", "/bethlehem/promotions"]


def test_note_lists_page_highlights_and_links():
    p = SitePage()
    p.update(
        snap(
            "a",
            1,
            "/rewards",
            headings=["Wind Creek Rewards", "Tier Benefits"],
            section="Tier Benefits",
            highlighted=["Delight"],
            text="x" * 3000,
            links=[{"label": "Book Now", "href": "/bethlehem/book-now"}],
        )
    )
    n = p.note()
    assert "Page: T (/rewards)" in n and "Highlighted for them: Delight" in n and "Book Now -> /bethlehem/book-now" in n
    assert len(p.note()) < len(p.note(full=True))


def test_blocked_pages():
    for bad in ("/profile", "/profile/my-reservations", "/forgot-password", "/careers", "/sign-in", "/checkout"):
        assert not allowed_path(bad), bad
    for ok in ("/bethlehem/book-now", "/rewards", "/bethlehem/promotions"):
        assert allowed_path(ok), ok


def test_session_summary_has_intents_and_no_personal_data():
    ins = Insights("room", "gemini-live", "m")
    ins.user_said("I'm going to Bethlehem this weekend, what's going on?")
    ins.agent_said("The Choose Your Ride Sweepstakes is Sunday.")
    ins.user_said("My name is Dana, call me at 610 555 1234 about the spa menu prices for seniors")
    ins.agent_said("I don't see that on the site; call 877-726-3777.")
    ins.action("navigate", {"to": "/bethlehem/promotions"}, True, 85)
    ins.latency(1200)
    s = ins.summary([{"path": "/bethlehem/promotions", "title": "Promotions", "t": ins.t0 + 3}])
    assert s["intents"]["promotions_events"] == 1 and "spa_amenities" in s["intents"]
    assert "Bethlehem" in s["entities"]["properties"] and s["entities"]["promotions"]
    assert s["unanswered_questions"] and "Dana" not in json.dumps(s) and "555" not in json.dumps(s)
    assert any(h["reason"] == "phone_property" for h in s["handoffs"])
    assert s["latency_ms"]["p50"] == 1200 and s["pages_visited"][0]["path"] == "/bethlehem/promotions"


def test_scrub():
    assert scrub("email me at a.b@c.com or 484-555-0000") == "email me at [email] or [number]"
    assert re.search(r"\[name\]", scrub("my name is Pat"))
