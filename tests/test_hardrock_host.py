"""The Hard Rock Host Companion pack (knowledge/hardrock-host): the page's data and the agent's facts come from one
source and agree; every player is fictional; comps fit the policy; the agent has the app's tools, not navigate."""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOW = os.path.join(ROOT, "knowledge", "hardrock-host")
sys.path.insert(0, os.path.join(ROOT, "mockup", "hardrock-host"))

import data as D  # noqa: E402


def test_knowledge_is_current():
    with open(os.path.join(KNOW, "players.md")) as f:
        assert f.read() == D.players_md()
    with open(os.path.join(KNOW, "briefing.md")) as f:
        assert f.read() == D.briefing_md()
    with open(os.path.join(KNOW, "site.json")) as f:
        assert json.load(f)["players"] == [p["slug"] for p in D.players()]


def test_players_are_fictional_and_consistent():
    rate = {"X": 0.40, "Icon": 0.35, "Legend": 0.30}
    for p in D.players():
        assert re.fullmatch(r"UNITY-DEMO-\d{4}", p["id"])
        assert p["tier"] in D.TIERS
        assert abs(p["budget"] - p["trip_theo"] * rate[p["tier"]]) <= 0.02 * p["trip_theo"]  # the reinvestment rule
        assert len(p["tonight"]) == 3 and all(v["why"] for v in p["tonight"])
        if p.get("responsible_gaming"):
            assert not any(c["kind"] == "free_play" for c in p["comps"])


def test_page_data_matches(tmp_path):
    subprocess.run([sys.executable, os.path.join(ROOT, "mockup", "hardrock-host", "build.py"), str(tmp_path)], check=True, capture_output=True)
    js = (tmp_path / "assets" / "data.js").read_text()
    page = json.loads(js[js.index("{") : js.rindex("}") + 1])
    assert [p["id"] for p in page["players"]] == [p["id"] for p in D.players()]
    assert page["players"][0]["remaining"] == D.players()[0]["remaining"]
    html = (tmp_path / "index.html").read_text()
    assert "noindex" in html and "Demo mockup prepared by LiveKit for Hard Rock Hotels, not the official site" in html
    assert "/embed/hardrock-v2/livekit.js" in html and "HARDROCK-DEMO" in html


def test_agent_tools():
    env = {**os.environ, "SITE_KNOWLEDGE": KNOW}
    code = "import sys; sys.path.insert(0, 'src'); import hardrock_host_agent as h; print(h.HostCompanion.navigate, h.HostCompanion.open_promotions)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
    assert out.split() == ["None", "None"]
