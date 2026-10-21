"""Kai on a multi-page website (the Wind Creek demo): what the visitor's page shows, from the embed widget's
page_context snapshots, as a short note for the model. Nothing here knows the site's markup: the widget reports
generic DOM facts (url, title, headings, the section in view, visible text, links in view, highlights, last click).

The brand, persona, greeting and facts live in knowledge/windcreek/ (SITE_KNOWLEDGE to swap in another site).

Snapshots are numbered per page load: `page_id` changes on every load and `seq` counts up within one, so a snapshot
from the page Kai just opened always replaces the old page's, even though its seq starts again at 1.
"""

import asyncio
import datetime as dt
import json
import os
import re
import time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE = os.getenv("SITE_KNOWLEDGE", os.path.join(ROOT, "knowledge", "windcreek"))
RECENT_CLICK_S = 15  # a click counts as "this" for this long
NOTE_TEXT_CHARS = 1500  # visible text in the between-turns note (tool results carry up to the page's 4 KB)
NOTE_LINKS = 14

# Never opened for the visitor, whatever the page links to: sign-in, accounts, profiles, job applications, payment.
DENY_PATH = re.compile(
    r"(sign[-_]?in|log[-_]?in|login|sign[-_]?up|register|forgot|password|/profile|my[-_]account|/account|"
    r"my[-_]reservations|win[-_]loss|careers?|/apply|application|checkout|payment|/cart)",
    re.I,
)


def load(name: str) -> str:
    with open(os.path.join(KNOWLEDGE, name)) as f:
        return f.read()


SITE: dict = json.loads(load("site.json"))
# the persona prompt: livekit_prompt.md for packs that name the assistant LiveKit, else the older kai_prompt.md
PROMPT_FILE = "livekit_prompt.md" if os.path.exists(os.path.join(KNOWLEDGE, "livekit_prompt.md")) else "kai_prompt.md"
# text-stream topics shared with the embed widget (the Wind Creek widget uses the kai_* names)
INSIGHTS_TOPIC = SITE.get("insights_topic", "kai_insights")
CONTROL_TOPIC = SITE.get("control_topic", "kai_control")


def today(now: dt.datetime | None = None) -> str:
    """Today in the site's time zone, with the weekday and the coming weekend's dates (for "this weekend")."""
    now = now or dt.datetime.now(ZoneInfo(SITE.get("timezone", "America/New_York")))
    d = dt.date.fromisoformat(os.environ["SITE_TODAY"]) if os.getenv("SITE_TODAY") else now.date()
    sat = d + dt.timedelta(days=(5 - d.weekday()) % 7)
    if d.weekday() == 6:  # on a Sunday, "this weekend" is today
        sat = d - dt.timedelta(days=1)
    fmt = lambda x: f"{x:%A}, {x:%B} {x.day}, {x.year}"  # noqa: E731
    return f"Today is {fmt(d)}. This weekend is Saturday {sat:%B} {sat.day} and Sunday {(sat + dt.timedelta(days=1)):%B} {(sat + dt.timedelta(days=1)).day}."


def prompt(now: dt.datetime | None = None) -> str:
    facts = "\n\n".join(load(n) for n in SITE["knowledge_files"])
    out = load(PROMPT_FILE)
    for k, v in (("{brand}", SITE["brand"]), ("{assistant}", SITE["assistant"]), ("{today}", today(now))):
        out = out.replace(k, v)
    return out.replace("{knowledge}", facts)


def greeting() -> str:
    return load("greeting.md").strip().replace("{brand}", SITE["brand"]).replace("{assistant}", SITE["assistant"])


def allowed_path(path: str) -> bool:
    return not DENY_PATH.search(path or "")


class SitePage:
    def __init__(self):
        self.ctx: dict = {}
        self.at = 0.0  # when the snapshot arrived (monotonic)
        self.loaded = asyncio.Event()  # set when a snapshot from a new page load arrives
        self.visited: list[dict] = []  # page loads, in order: {path, title, t}

    def update(self, ctx: dict) -> bool:
        """Keep the newest snapshot; False if it's older than the one we have. A new page_id is a new page load and
        replaces the old one unless it's from before it (loaded_at)."""
        if not isinstance(ctx, dict) or "path" not in ctx:
            return False
        cur = self.ctx
        if ctx.get("page_id") != cur.get("page_id"):
            if ctx.get("loaded_at", 0) < cur.get("loaded_at", 0):
                return False
            self.visited.append({"path": ctx["path"], "title": ctx.get("title", ""), "t": time.time()})
            self.loaded.set()
        elif ctx.get("seq", 0) < cur.get("seq", 0):
            return False
        self.ctx, self.at = ctx, time.monotonic()
        return True

    def update_json(self, text: str) -> bool:
        try:
            return self.update(json.loads(text))
        except (ValueError, TypeError):
            return False

    async def next_load(self, timeout: float) -> bool:
        """Wait for a snapshot from a new page load (call self.loaded.clear() before starting the navigation)."""
        try:
            await asyncio.wait_for(self.loaded.wait(), timeout)
            return True
        except TimeoutError:
            return False

    def signature(self) -> str:
        """What the model should hear about again when it changes: the page, the section in view, highlights, a new
        click. Not timings, sequence numbers or every scroll pixel."""
        c = self.ctx
        lc = c.get("last_click") or {}
        return json.dumps(
            [c.get("page_id"), c.get("path"), c.get("section"), c.get("highlighted"), lc.get("text"), lc.get("at")],
            sort_keys=True,
        )

    def clicked(self) -> str | None:
        lc = self.ctx.get("last_click")
        if not lc:
            return None
        age = lc.get("ms_ago", 0) / 1000 + time.monotonic() - self.at
        return lc.get("text") if age < RECENT_CLICK_S else None

    def note(self, full: bool = False) -> str:
        """The page as a short note. full: all of the visible text the page sent (tool results), else trimmed."""
        c = self.ctx
        if not c:
            return "<page_now>The page hasn't reported yet.</page_now>"
        lines = [f"Page: {c.get('title', '')} ({c.get('path')})"]
        if c.get("navigating"):
            lines.append(f"The page is loading {c['navigating']}.")
        heads = [h for h in c.get("headings") or [] if h]
        if heads:
            lines.append("Headings on this page: " + " | ".join(heads[:40]))
        if c.get("section"):
            lines.append(f"In view now: {c['section']}")
        if c.get("highlighted"):
            lines.append("Highlighted for them: " + "; ".join(c["highlighted"]))
        if c.get("section_text"):
            lines.append(f"Section text ({c.get('section_heading', '')}): {c['section_text']}")
        text = (c.get("text") or "").strip()
        if text:
            cap = 4000 if full else NOTE_TEXT_CHARS
            lines.append("Visible text: " + (text if len(text) <= cap else text[:cap] + " …"))
        links = c.get("links") or []
        if links:
            lines.append(
                "Links in view: " + "; ".join(f"{l.get('label')} -> {l.get('href')}" for l in links[:NOTE_LINKS])
            )
        if acts := c.get("site_actions"):
            lines.append(
                "Site actions on this page (call with site_action): "
                + "; ".join(f"{a['name']}: {a.get('description', '')}" for a in acts)
            )
        if sc := c.get("site_context"):
            lines.append("Site data: " + json.dumps(sc)[:1500])
        if c.get("action_result"):
            lines.append(f"Action result: {c['action_result']}")
        if t := self.clicked():
            lines.append(f"They just clicked: {t}")
        return "<page_now>\n" + "\n".join(lines) + "\n</page_now>"
