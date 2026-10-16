"""What is on the shared screen, in words: the screen summary, what a click changed, and the feed that keeps the voice
model up to date (ScreenText)."""

import asyncio
import datetime
import logging
import os
import re
import time
from urllib.parse import urlparse

from demo_agent.brain import IS_GEMINI
from demo_agent.pagetext import page_text
from demo_agent.prompts import PRODUCT, PROMPT, feature_cards, storyline

log = logging.getLogger("agent.screen")

SCREEN_CHARS = int(os.getenv("SCREEN_TEXT_CHARS", 1500))
SETTLE_S = float(os.getenv("SETTLE_S", 2.0))  # after a click opens a new page: wait at most this long for its data

# The top layer: an open dialog or menu hides the page behind it, so only it counts.
TOP_LAYER = "[role=dialog]:visible, [aria-modal=true]:visible, [role=menu]:visible, [role=listbox]:visible"

# "url|open layers|main text length|name of the top layer": changes whenever a click visibly does something.
SIGNATURE_JS = """() => { const L = [...document.querySelectorAll('[role=dialog],[role=menu],[role=listbox],[aria-modal=true]')]
    .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });  // pages keep closed ones in the DOM
  const top = L.length ? L[L.length - 1] : null;
  const name = top ? (top.getAttribute('role') === 'menu' ? 'menu' : top.getAttribute('role') === 'listbox' ? 'list' : 'dialog') + ' "'
    + ((top.getAttribute('aria-label') || (top.querySelector('h1,h2,h3') || {}).innerText || '').trim().slice(0, 40)) + '"' : '';
  return location.href + '|' + L.length + '|' + (document.querySelector('main')||document.body).innerText.length + '|' + name; }"""

# A clicked element's label and whether it is now on (checked, selected, pressed, active).
STATE_JS = r"""(e) => { const a = (k) => e.getAttribute(k); const inp = e.matches('input') ? e : e.querySelector('input[type=radio],input[type=checkbox]');
  const on = a('aria-checked') === 'true' || a('aria-selected') === 'true' || a('aria-pressed') === 'true' || a('data-state') === 'checked'
    || a('data-state') === 'active' || (inp && inp.checked) || !!e.querySelector('[aria-checked=true],[data-state=checked]');
  const lab = (e.labels && e.labels[0] && e.labels[0].innerText) || e.innerText || a('aria-label') || (e.closest('label') || {}).innerText || e.value || '';
  return { label: lab.trim().split('\n')[0].slice(0, 60), on, expanded: a('aria-expanded') }; }"""

# Visible toasts/alerts that report an error.
TOASTS_JS = r"""() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sel = '[role=alert],[role=status],[aria-live=assertive],[aria-live=polite],[data-sonner-toast],[class*=toast],[class*=Toast],[class*=notification]';
  return [...new Set([...document.querySelectorAll(sel)].filter(e => vis(e) && (e.innerText || '').trim())
    .map(e => e.innerText.trim().replace(/\s+/g, ' ').slice(0, 200)))].filter(t => /error|fail|could not|couldn|unable|denied|limit|exceed|invalid|not allowed|exhausted/i.test(t)).slice(0, 2).join(' | '); }"""

# Validation messages inside the open dialog.
FORM_ERRORS_JS = r"""() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const root = [...document.querySelectorAll('[role=dialog],[aria-modal=true]')].filter(vis).pop(); if (!root) return '';
  return [...root.querySelectorAll('*')].filter(e => vis(e) && !e.children.length && /required|only letters|invalid|must|already/i.test(e.innerText || ''))
    .map(e => e.innerText.trim()).slice(0, 2).join(' | '); }"""

# The open dialog shows it is working (spinner, busy marker, disabled submit button).
BUSY_JS = """() => { const d = [...document.querySelectorAll('[role=dialog],[aria-modal=true]')].pop(); if (!d) return false;
  return !!d.querySelector('[aria-busy=true],svg[class*=animate-spin],[class*=spinner],[class*=loading]') ||
    [...d.querySelectorAll('button')].some(b => b.disabled && /create|save|deploy|submit|continue|next/i.test(b.innerText || '')); }"""


async def screen_summary(page, limit: int = SCREEN_CHARS) -> str:
    """The accessibility tree (roles, names, states such as [checked] or [selected]) of the top layer only."""
    try:
        layer = page.locator(TOP_LAYER)
        n = await layer.count()
        where = "an open dialog/menu" if n else "the page"
        root = layer.nth(n - 1) if n else page.locator("main").first
        if not n and not await root.count():
            root = page.locator("body")
        tree = await root.aria_snapshot(timeout=2000)
        tree = "\n".join(
            l
            for l in tree.splitlines()
            if not re.match(r"\s*- (img|separator|generic|/url:)\b|\s*- /url:", l)
            and l.strip() not in ("- generic", "- list")
        )
        title = await page.title()
        u = urlparse(page.url)
        return (
            f"PAGE: {title} ({(u.path + ('?' + u.query if u.query else ''))[:80]}). Showing {where}:\n" + tree[:limit]
        )
    except Exception:
        return await page_text(page, limit)


async def layer_ids(page) -> set | None:
    """data-jev-id values inside the top layer, or None when nothing is layered on top."""
    layer = page.locator(TOP_LAYER)
    n = await layer.count()
    if not n:
        return None
    return set(
        await layer.nth(n - 1).evaluate(
            "e => [...e.querySelectorAll('[data-jev-id]')].map(x => x.getAttribute('data-jev-id'))"
        )
    )


def describe_change(before: str, after: str, st: dict | None) -> str:
    """What a click did, in words, from the page signatures before and after (and the clicked element's state)."""
    (u0, d0, _, n0), (u1, d1, _, n1) = before.split("|", 3), after.split("|", 3)
    what = (
        "a new page opened" + (f" with the {n1} open" if n1 else "")
        if u0 != u1
        else f"the {n1 or 'dialog or menu'} opened"
        if int(d1) > int(d0) or (n1 and n1 != n0)
        else f"the {n0 or 'dialog or menu'} closed"
        if int(d1) < int(d0)
        else "the page content changed"
        if before != after
        else "no visible change"
    )
    lab = f"'{st['label']}'" if st and st.get("label") else "it"
    sel = f"; {lab} is now selected" if st and st.get("on") else ""
    return f"Clicked {lab}: {what}{sel}."


async def until_changed(page, before: str, limit: float = 1.0, busy_limit: float = 0.0):
    """Return as soon as the page visibly reacts (route, dialog/menu or content change), after at most `limit` s.
    With busy_limit, keep waiting up to busy_limit s while an open dialog shows it is working: a second click on a
    submit button in that time would break the dialog."""
    t = time.perf_counter()
    while True:
        el = time.perf_counter() - t
        if el >= limit:
            if not busy_limit or el >= busy_limit:
                break
            try:
                if not await page.evaluate(BUSY_JS):
                    break
            except Exception:
                break
        await asyncio.sleep(0.05)
        try:
            now = await page.evaluate(SIGNATURE_JS)
            if now != before:
                # new page: wait out skeleton/loading placeholders (max 4 s)
                if now.split("|")[0] != before.split("|")[0]:
                    try:
                        await page.wait_for_function(
                            "() => !document.querySelector('[class*=skeleton],[class*=shimmer],[aria-busy=true]')",
                            timeout=4000,
                        )
                    except Exception:
                        pass
                await asyncio.sleep(0.15)
                return round(time.perf_counter() - t, 2)
        except Exception:
            pass
    return None


async def quiet_network(page, limit: float = SETTLE_S, quiet: float = 0.4):
    """Wait until the page has had no fetch/XHR in flight for `quiet` s, at most `limit` s. (Playwright's networkidle
    only covers full navigations, not a single-page app's route change.)"""
    if not hasattr(page, "_inflight"):
        page._inflight = set()
        page.on("request", lambda r: r.resource_type in ("fetch", "xhr") and page._inflight.add(r))
        page.on("requestfinished", lambda r: page._inflight.discard(r))
        page.on("requestfailed", lambda r: page._inflight.discard(r))
        await asyncio.sleep(0.15)  # requests already in flight weren't seen: give new ones a moment to start
    t, idle = time.perf_counter(), None
    while time.perf_counter() - t < limit:
        if page._inflight:
            idle = None
        elif idle is None:
            idle = time.perf_counter()
        elif time.perf_counter() - idle >= quiet:
            return
        await asyncio.sleep(0.05)


def today_line() -> str:
    """Today's date, for products where dates matter ("needs_today" in product.json); else empty."""
    d = datetime.date.today()
    return f"TODAY IS {d:%A, %B} {d.day}, {d.year}." if PRODUCT.get("needs_today") else ""


def no_effect(what: str) -> bool:
    return "no visible change" in what or "already looks done" in what or "still open" in what


def no_effect_reason(what: str, screen: str) -> str:
    """Why a repeated step changed nothing: usually the view is already open or selected, sometimes it isn't clickable."""
    m = re.search(r"Clicked '([^']+)'", what)
    lab = m.group(1) if m else ""
    head = screen.split("\n", 1)[0].lower()
    # a nav link/tab that does nothing: we're on it
    nav = lab and re.search(r"-\s*(?:link|tab)\s+\"" + re.escape(lab) + r"\"", screen, re.I)
    if "already looks done" in what or "is now selected" in what or (lab and lab.lower() in head) or nav:
        return f"That's already open on screen{f' ({lab})' if lab else ''}: clicking it again changes nothing, so that part is done."
    what_ = f"'{lab}'" if lab else "that"
    return f"Clicking {what_} twice changed nothing: it isn't something that opens here."


class ScreenText:
    """Keeps the voice model up to date with the screen. When the screen summary changes, it sends the summary, the
    knowledge cards of the features on screen, the area's storyline, the running task and the customer profile.
    Gemini gets it as a context item; the Inference model gets it folded into its instructions."""

    HDR = "\n\nWHAT IS ON YOUR SHARED SCREEN RIGHT NOW (page text):\n"

    def __init__(self, bc, slog):
        self.bc, self.slog, self.agent = bc, slog, None
        self._last, self._kick = None, asyncio.Event()
        self.task_line = ""  # the planner's status or last result
        self.profile_line = ""  # what we know about the customer
        self.vin = None  # ScreenVideoInput (Gemini only)
        self.agent_lines: list[str] = []  # what Kai said, so a task-done reply doesn't repeat it
        self.user_turns = 0
        self.area = None  # demo area of the features on screen
        self.cards = feature_cards()
        self._posted_area = self._posted_profile = self._posted_today = None
        self._posted_task = ""

    def kick(self):
        self._kick.set()
        if self.vin is not None:
            self.vin.kick()  # and send Gemini a fresh frame of the result

    def on_screen(self, txt: str) -> str:
        """The knowledge cards of the features whose labels are on screen now (at most 2)."""
        low = txt.lower()
        hits = []
        for c in self.cards:
            score = sum(1 for l in c["labels"] if len(l) > 3 and l.lower() in low)
            if score:
                hits.append((score, c))
        hits.sort(key=lambda x: -x[0])
        self.area = hits[0][1]["area"] if hits else None
        return "\n".join(h[1]["card"] for h in hits[:2])

    async def post_context(self, txt: str, cards: str) -> int:
        """Gemini: add the update as one short context item. (Updating the instructions would re-send the whole prompt
        as a new turn every time.) Only parts that changed are sent again."""
        parts = []
        if (today := today_line()) and today != self._posted_today:
            parts.append(today)
            self._posted_today = today
        if self.profile_line and self.profile_line != self._posted_profile:
            parts.append(f"WHAT YOU KNOW ABOUT THEM: {self.profile_line}")
            self._posted_profile = self.profile_line
        if self.task_line != self._posted_task:
            parts.append(self.task_line or "No screen task is running now.")
            self._posted_task = self.task_line
        if cards:
            parts.append(f"FEATURES ON SCREEN NOW (talk about these specifically):\n{cards}")
        if self.area and self.area != self._posted_area:
            parts.append(storyline(self.area).strip())
            self._posted_area = self.area
        parts.append(self.HDR.strip() + "\n" + txt)
        body = (
            "<screen_update>(From the demo system, not the customer. Don't reply to this; use it for what's on your screen now.)\n"
            + "\n\n".join(parts)
            + "\n</screen_update>"
        )
        ctx = self.agent.chat_ctx.copy()
        ctx.add_message(role="user", content=body)
        await self.agent.update_chat_ctx(ctx)
        return len(body)

    async def post_instructions(self, txt: str, cards: str) -> int:
        """Inference realtime: the instructions are the base prompt plus the current state of the screen."""
        await self.agent.update_instructions(
            PROMPT
            + (f"\n\n{today_line()}" if today_line() else "")
            + (f"\n\nWHAT YOU KNOW ABOUT THEM: {self.profile_line}" if self.profile_line else "")
            + (f"\n\n{self.task_line}" if self.task_line else "")
            + (f"\n\nFEATURES ON SCREEN NOW (talk about these specifically):\n{cards}" if cards else "")
            + storyline(self.area)
            + self.HDR
            + txt
        )
        return len(PROMPT) + len(txt)

    async def run(self):
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), 2.0)
                self._kick.clear()
                await asyncio.sleep(0.35)
            except TimeoutError:
                pass
            if not self.agent or not self.bc.page:
                continue
            try:
                txt = await screen_summary(self.bc.page)
                # timers and metrics alone don't re-send
                sig = re.sub(r"\d", "", txt) + self.task_line + self.profile_line
                if sig == self._last or txt.startswith("(page text failed"):
                    continue
                self._last = sig
                cards = self.on_screen(txt)
                t = time.perf_counter()
                post = self.post_context if IS_GEMINI else self.post_instructions
                n = await post(txt, cards)
                extra = {"agent_state": getattr(self.agent.session, "agent_state", "")} if IS_GEMINI else {}
                self.slog.event(
                    "screen_text",
                    page=txt.split("\n", 1)[0][:80],
                    feed="context" if IS_GEMINI else "instructions",
                    chars=n,
                    text=txt,
                    ms=round((time.perf_counter() - t) * 1000, 1),
                    **extra,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("screen text: %s", e)
