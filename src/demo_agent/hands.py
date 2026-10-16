"""The hands: carry out one plain-words step on the live page. Jev picks the element, then a straight click (or typing
into the named field), then wait until the page reacts and report what changed."""

import asyncio
import random
import re
import time

from demo_agent.prompts import PRODUCT
from demo_agent.screen import (
    FORM_ERRORS_JS,
    SIGNATURE_JS,
    STATE_JS,
    TOASTS_JS,
    TOP_LAYER,
    describe_change,
    layer_ids,
    quiet_network,
    until_changed,
)


def agent_slug(name: str) -> str:
    """A valid agent name (letters, numbers, underscores, dashes) with a random 3-digit suffix, so it never clashes
    with an agent created (or deleted) earlier."""
    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower())).strip("-_")[:32] or "demo-agent"
    return slug if re.search(r"-\d{3,}$", slug) else f"{slug}-{random.randint(100, 999)}"


def parse_typing(goal: str):
    """("text", "field") from a typing step, or None. Handles: type X into the Y field / type into the Y editor: "X" /
    enter "X" in the Y box / set the Y to "X" / clear the Y and type X."""
    if not re.search(r"\b(type|enter|write|fill|set|change|replace|put|append|add)\b", goal, re.I):
        return None
    q = re.search(r"[\"“‘']([^\"”’]{1,2000})[\"”’]", goal)
    END = r"(?:\s+(?:field|editor|box|textbox|input|text area)\b|\s*[:,.]|\s+(?:to|with|and|so|replacing)\b|$)"
    f = (
        # "into the X field" wins; a field noun after it ends the name, so a name may contain "to" ("Where to?")
        re.search(
            r"\binto\s+the\s+(?:open\s+)?['\"]?(.+?)['\"]?\s+(?:field|editor|box|textbox|input|text area)\b", goal, re.I
        )
        or re.search(r"\binto\s+the\s+(?:open\s+)?(.+?)" + END, goal, re.I)
        or re.search(r"\b(?:set|change|replace|clear|update)\s+the\s+(?:current\s+)?(.+?)" + END, goal, re.I)
        or (list(re.finditer(r"\b(?:in|to)\s+the\s+(?!open\b)(.+?)" + END, goal, re.I)) or [None])[-1]
    )
    text = q.group(1) if q else None
    if not text and (w := re.search(r"\bwith\s+(.+?)\s*$", goal, re.I)):
        text = w.group(1).strip(" .'\"")
    if not text:
        m = re.search(
            r"\b(?:type|enter|write|put)\s+(?!into\b|in\b)(.+?)\s+(?:into|in)\s+the\b", goal, re.I
        ) or re.search(r"\b(?:type|enter|write)\s+(?!into\b|in\b)(.+?)\s*$", goal, re.I)
        text = m.group(1).strip(" '\"") if m else None
    if not text or not f:
        return None
    field = re.sub(r"^(?:(?:open|focused|current|existing|main|same)\s+)+", "", f.group(1), flags=re.I).strip(" '\"")
    return (text, field) if field and len(field) < 40 else None


def is_append(goal: str) -> bool:
    return bool(
        re.search(
            r"\b(append|add (?:it |this |that )?to the end|add (?:a |another )?(?:line|sentence|rule)|at the end)\b",
            goal,
            re.I,
        )
    )


# The first input or editor after a visible heading/label whose text is exactly `name`; marks it and returns the mark.
FIELD_AFTER_HEADING_JS = r"""(name) => { const N = name.trim().toLowerCase(); const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ED = '.monaco-editor,.cm-editor,.ProseMirror';
  const ctrls = [...new Set([...document.querySelectorAll('textarea,input:not([type=hidden]):not([type=checkbox]):not([type=radio]),[contenteditable=true],' + ED)]
    .map(e => (e.closest && e.closest(ED)) || e))].filter(e => vis(e) && e.getAttribute('aria-hidden') !== 'true');
  const heads = [...document.querySelectorAll('label,h1,h2,h3,h4,h5,legend,p,span,div')].filter(e => vis(e) && e.children.length <= 2
    && (e.innerText || '').trim().toLowerCase().replace(/\s+/g, ' ') === N);
  for (const h of heads) { const c = ctrls.find(c => h.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING);
    if (c) { const id = 'f' + Math.random().toString(36).slice(2, 8); c.setAttribute('data-kai-field', id); return id; } }
  return null; }"""

# The code editor (Monaco, CodeMirror, ProseMirror) that contains or follows an element; marks it and returns the mark.
# Only a visible one: pages can keep a hidden 0x0 copy of an editor (e.g. one per form mode) before the shown one.
EDITOR_FOR_JS = r"""(e) => { const ED = '.monaco-editor,.cm-editor,.ProseMirror';
  const vis = x => { const r = x.getBoundingClientRect(); return r.width > 0 && r.height > 0; }; let ed = e.closest(ED);
  if (!ed) ed = [...document.querySelectorAll(ED)].find(x => vis(x) && (e.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING));
  if (!ed) return null; const id = 'ed' + Math.random().toString(36).slice(2, 7); ed.setAttribute('data-kai-ed', id); return id; }"""

# The text a field shows: an input's value, or the rendered lines of a code editor.
FIELD_TEXT_JS = r"""(e) => { if (e.matches('input,textarea') && !e.closest('.monaco-editor,.cm-editor')) return e.value;
  const ed = e.closest('.monaco-editor,.cm-editor,.ProseMirror') || e;
  return (ed.querySelector('.view-lines,.cm-content') || ed).innerText || ''; }"""

# The text of the focused input, or null when the focus isn't in one.
FOCUSED_TEXT_JS = (
    "() => { const a = document.activeElement; return a && a.matches('input,textarea') ? a.value : null; }"
)

# Blur the focused text input (not a search box, which waits for Enter, nor an autocomplete, whose list it would close).
BLUR_INPUT_JS = """() => { const a = document.activeElement;
  if (a && a.matches('input:not([type=search]):not([role=combobox]):not([aria-autocomplete])')) a.blur(); }"""
# The focused element is an autocomplete (its suggestions come a moment after typing).
FOCUSED_COMBO_JS = "() => !!document.activeElement?.matches('[role=combobox],[aria-autocomplete]')"


async def find_field(page, field: str):
    """The input or editor for a field name, in the top layer: by label, placeholder, textbox name, or the heading above it."""
    layer = page.locator(TOP_LAYER)
    n = await layer.count()
    scope = layer.nth(n - 1) if n else page
    for cand in (  # an exact name first: "Where" must not pick "Where from?" when "Where to?" was meant
        scope.get_by_label(field, exact=True),
        scope.get_by_placeholder(field, exact=True),
        scope.get_by_label(field, exact=False),
        scope.get_by_placeholder(field, exact=False),
        scope.get_by_role("textbox", name=re.compile(re.escape(field), re.I)),
    ):
        try:
            if await cand.count():
                return cand.first
        except Exception:
            pass
    try:
        fid = await page.evaluate(FIELD_AFTER_HEADING_JS, field)
        if fid:
            return page.locator(f'[data-kai-field="{fid}"]').first
    except Exception:
        pass
    return None


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


async def wait_for_field(page, field: str, secs: float = 4.0):
    """find_field, waiting a moment for a field that is still loading (editors often mount after the page)."""
    t = time.perf_counter()
    while (cand := await find_field(page, field)) is None and time.perf_counter() - t < secs:
        await asyncio.sleep(0.25)
    return cand


async def type_into(page, loc, text: str, append: bool = False) -> tuple[str, str | None]:
    """Type into a field, then check that it shows the text. Returns (how, None), or (how, what the field shows) when
    the text didn't land (e.g. an editor that re-rendered while it was typed into)."""
    how, target = await _type_once(page, loc, text, append)
    await asyncio.sleep(0.3)
    try:
        shown = await target.evaluate(FIELD_TEXT_JS, timeout=1000)
    except Exception:
        shown = ""
    # an editor renders only the lines in view (the end, after typing), wrapped: compare the end, ignoring whitespace
    if _squash(text)[-40:] in _squash(shown):
        return how, None
    # a combobox can hand the focus to a search input in its own pop-up, and the text lands there
    if _squash(text) in _squash(await page.evaluate(FOCUSED_TEXT_JS) or ""):
        return how + "-popup", None
    return how, shown


async def _type_once(page, loc, text: str, append: bool):
    """Replace (or append to) a field's text; returns (how, the element typed into). Plain inputs take fill(). Code
    editors don't, and Control+A is "line start" on macOS, so: click into the editor, select all with ControlOrMeta+A,
    then insert the text."""
    if await loc.evaluate("e => e.matches('input,textarea') && !e.closest('.monaco-editor,.cm-editor')"):
        if append:
            await loc.click(timeout=3000)
            await page.keyboard.press("ControlOrMeta+End")
            await page.keyboard.insert_text(text)
            return "append", loc
        await loc.fill(text, timeout=3000)
        return "fill", loc
    ed = await loc.evaluate(EDITOR_FOR_JS)
    if not ed:
        await loc.fill(text, timeout=3000)
        return "fill", loc
    box = page.locator(f'[data-kai-ed="{ed}"]').first
    await box.click(timeout=3000)
    if append:  # keep what's there, add at the end on a new line
        await page.keyboard.press("ControlOrMeta+End")
        await page.keyboard.press("Enter")
        await page.keyboard.insert_text(text)
        return "editor-append", box
    await page.keyboard.press("ControlOrMeta+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.insert_text(text)
    return "editor", box


# "set the Maximum price slider to 400", "move the volume slider to 30"
SLIDER_RE = r"\b(?:set|move|drag|slide|change)\s+the\s+['\"]?(.+?)['\"]?\s+(?:slider\s+)?to\s+\$?(-?[\d.,]+)"
SLIDER_VALUE_JS = "e => parseFloat(e.matches('input') ? e.value : e.getAttribute('aria-valuenow'))"


async def set_slider(page, name: str, target: float) -> str | None:
    """Move a slider (a range input or an ARIA slider) with the arrow keys, as a person would, until it reaches the
    target or the end of its range. Returns what it shows then, or None when no slider has that name."""
    layer = page.locator(TOP_LAYER)
    n = await layer.count()
    scope = layer.nth(n - 1) if n else page
    s = scope.get_by_role("slider", name=re.compile(re.escape(re.sub(r"\s+slider$", "", name, flags=re.I)), re.I))
    if not await s.count():
        return None
    s = s.first
    await s.focus()
    now = await s.evaluate(SLIDER_VALUE_JS)
    at_end = False
    for _ in range(200):
        if now == target:
            break
        down = now > target
        await page.keyboard.press("ArrowLeft" if down else "ArrowRight")
        new = await s.evaluate(SLIDER_VALUE_JS)
        if new == now:  # the end of its range
            at_end = True
            break
        now = new
        if new <= target if down else new >= target:
            break
    await quiet_network(page, 1.5)
    shown = await s.evaluate(
        "e => e.getAttribute('aria-valuetext') || (e.matches('input') ? e.value : e.getAttribute('aria-valuenow'))"
    )
    shown = shown or str(now)
    if at_end:
        shown += f" (that is as {'low' if now > target else 'high'} as this slider goes; don't try again)"
    return shown


# "set Adults to 2", "set the number of guests to 3": a counter with -/+ buttons
STEPPER_RE = (
    r"\bset\s+(?:the\s+)?(?:number\s+of\s+)?['\"]?(.+?)['\"]?\s+(?:count\s+)?to\s+(\d+)"
    r"(?=\s*$|\s*[.,;]|\s+(?:in|on|and|then|using|with)\b)"
)

# The counter row whose label starts with the given text: the nearest ancestor of the label holding exactly two buttons
# (- and +), in the top layer. A label that matches no row is shortened word by word while that finds exactly one row
# (the page may word it differently: "Children Aged 2 to 11" vs "Children Aged 2-11"). Marks the row and its buttons
# and returns the mark, or null.
STEPPER_JS = r"""(label) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const layers = [...document.querySelectorAll('[role=dialog],[aria-modal=true],[role=menu],[role=listbox]')].filter(vis);
  const root = layers.length ? layers[layers.length - 1] : document.body;
  const txt = e => (e.innerText || e.getAttribute('aria-label') || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const btns = e => [...e.querySelectorAll('button,[role=button]')].filter(vis);
  const rows = L => { const out = new Set();
    for (const h of root.querySelectorAll('*')) {
      if (!vis(h) || h.closest('button,[role=button]') || !txt(h).startsWith(L) || [...h.children].some(c => txt(c).startsWith(L))) continue;
      let row = h;
      while (row && row !== root.parentElement && btns(row).length < 2) row = row.parentElement;
      if (row && btns(row).length === 2) out.add(row); }
    return [...out]; };
  const words = label.trim().toLowerCase().split(/\s+/);
  for (let k = words.length; k > 0; k--) {
    const found = rows(words.slice(0, k).join(' '));
    if (!found.length || (k < words.length && found.length > 1)) continue;
    const row = found[0], isDec = e => /remove|decrease|minus|fewer|less|subtract|^[-\u2212\u2013]$/i.test(txt(e));
    let [dec, inc] = btns(row);  // the usual order is "- count +"
    if (isDec(inc) && !isDec(dec)) [dec, inc] = [inc, dec];
    const id = 's' + Math.random().toString(36).slice(2, 7);
    row.setAttribute('data-kai-row', id); dec.setAttribute('data-kai-dec', id); inc.setAttribute('data-kai-inc', id);
    return id; }
  return null; }"""

# The number a counter row shows: its input or spinbutton, else the last bare number outside its buttons.
COUNT_JS = r"""(row) => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sp = row.querySelector('input,[role=spinbutton]');
  if (sp) return parseFloat(sp.matches('input') ? sp.value : sp.getAttribute('aria-valuenow'));
  const n = [...row.querySelectorAll('*')].filter(e => vis(e) && !e.children.length && !e.closest('button,[role=button]')
    && /^\d+$/.test((e.innerText || '').trim()));
  return n.length ? parseInt(n[n.length - 1].innerText) : null; }"""


async def set_stepper(page, label: str, target: int) -> str | None:
    """Set a counter (a number between - and + buttons) by clicking its buttons, as a person would, checking the number
    after every click. Returns what it shows then, or None when there is no such counter."""
    sid = await page.evaluate(STEPPER_JS, label)
    if not sid:
        return None
    row = page.locator(f'[data-kai-row="{sid}"]')
    now = await row.evaluate(COUNT_JS)
    if now is None:
        return None
    for _ in range(20):
        if now == target:
            break
        try:
            await page.locator(f'[data-kai-{"dec" if now > target else "inc"}="{sid}"]').click(timeout=1000)
        except Exception:  # a disabled button: the end of its range
            break
        await asyncio.sleep(0.25)
        new = await row.evaluate(COUNT_JS)
        if new == now:
            break
        now = new
    return f"{now}" if now == target else f"{now} (it doesn't go to {target}; don't try again)"


async def set_steppers(page, goal: str) -> list[str] | None:
    """Every counter a step sets ("set Adults to 2 and Children to 1"): what each shows after, or None if none."""
    m = re.search(r"\bset\s+(.+)", goal, re.I)  # also "click Add child to set Children to 1"
    if not m:
        return None
    shown = []
    for part in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1)):
        if (c := re.search(STEPPER_RE, "set " + part, re.I)) and (
            n := await set_stepper(page, c.group(1), int(c.group(2)))
        ):
            shown.append(f"'{c.group(1)}' now shows {n}")
    return shown or None


async def _escape(kai) -> str:
    """Close the top layer with Escape and say whether it worked."""
    page = kai.bc.page
    n0 = await page.locator(TOP_LAYER).count()
    kai.chooser = "escape"
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.3)
    kai.last_change = (
        "Closed it." if await page.locator(TOP_LAYER).count() < n0 else "Pressed Escape but it's still open."
    )
    return "jev-click"


async def _snapshot(kai, words):
    """Jev's element table; while a dialog or menu is open, only its controls."""
    snap = await kai.bc.snapshot(240, words)
    if (ids := await layer_ids(kai.bc.page)) is not None:
        snap["elements"] = [e for e in snap["elements"] if e["id"] in ids] or snap["elements"]
    return snap


async def fast_hands(kai, goal: str, _retry: bool = True):
    """Do one step. Rules first (close, scroll, back, typing into a named field), otherwise Jev picks the element and it
    is clicked. Returns how it acted, or None when nothing fitted (the caller then lets Jev run the step itself).
    Sets kai.chooser (who picked the click) and kai.last_change (what the click did)."""
    page, g = kai.bc.page, goal.lower()

    def has_layer():
        return page.locator(TOP_LAYER).count()

    # "close/dismiss ..." closes the top layer with Escape (but "click 'Cancel' to close" is a click)
    if (
        re.match(r"\s*(?:close|dismiss|escape|press escape|click outside|click away)\b", g)
        and await has_layer()
        and not re.search(r"\bclick (?:the )?['\"]?(?:close|cancel)\b", g)
    ):
        return await _escape(kai)
    if re.search(r"\bscroll", g):
        kai.chooser = "rule"
        up = bool(re.search(r"\bup\b|\btop\b", g))
        far = bool(re.search(r"bottom|top|all the way|lot", g))
        bit = "bit" in g or "little" in g
        await kai.bc.scroll((-1 if up else 1) * (3000 if far else 300 if bit else 600))
        return "scroll"
    # "go back" uses browser Back, but "click the breadcrumb to go back to ..." names something to click
    if re.search(r"\bgo back\b|\bback\b$|previous page", g) and not re.match(r"\s*(click|select|open|press|tap)\b", g):
        kai.chooser = "rule"
        await kai.bc.go_back()
        return "back"

    if (m := re.search(SLIDER_RE, goal, re.I)) and (
        shown := await set_slider(page, m.group(1), float(m.group(2).replace(",", "")))
    ):
        kai.chooser = "exact-name"
        kai.last_change = f"Moved the '{m.group(1)}' slider; it now shows: {shown}."
        kai.changes.append(f"set {m.group(1)}: {shown}")
        return "jev-click"

    if shown := await set_steppers(page, goal):
        kai.chooser = "exact-name"
        kai.last_change = "Used the counters' buttons: " + "; ".join(shown) + "."
        kai.changes += [f"set {x}" for x in shown]
        return "jev-click"

    # typing: the text goes into the field the step names, never into another box
    if tgt := parse_typing(goal):
        text, field = tgt
        if PRODUCT.get("unique_names") and re.search(r"\bagent name\b|^name$", field, re.I):
            text = agent_slug(text)
        kai.chooser = "exact-name"
        cand = await wait_for_field(page, field)
        if cand is None:
            kai.slog.event("type_no_field", field=field)
            return None
        add = is_append(goal)
        how, shown = await type_into(page, cand, text, append=add)
        if shown is not None and not add and (cand := await wait_for_field(page, field)):  # once more, on a fresh find
            kai.slog.event("type_retry", field=field, shown=shown[:120])
            how, shown = await type_into(page, cand, text)
        kai.typed_note = f" ({'added to' if add else 'set'} '{field}': '{text[:60]}')"
        if shown is not None:
            kai.slog.event("type_unverified", field=field, shown=shown[:120])
            kai.typed_note += f", but the field shows '{shown[:80]}', not the full text"
        else:
            kai.changes.append(f"{'added to' if add else 'set'} {field}: {text[:200]}")
        suggestions = page.locator("[role=listbox]:visible")
        if await page.evaluate(FOCUSED_COMBO_JS):
            try:
                await suggestions.first.wait_for(timeout=1500)
            except Exception:
                pass
        if await suggestions.count():  # an autocomplete: the value counts once one is picked
            kai.typed_note += ". A list of suggestions opened: pick the one that fits"
        else:  # many inputs (dates, numbers) only take a typed value on blur, as when a person moves on to the next one
            await page.evaluate(BLUR_INPUT_JS)
            await quiet_network(page, 1.5)  # the app may check or apply the value with a request first
        return "type-" + how

    # Jev picks; if it says the target is off-screen, scroll and ask again
    words = [w for w in re.split(r"[^a-zA-Z0-9]+", goal) if len(w) > 2]
    snap = await _snapshot(kai, words)
    # the text of "type X into the name field" or "clear the name and type X"
    typed = re.search(r"\b(?:type|enter|write)\s+[\"']?(.+?)[\"']?\s+(?:in|into)\s+the\b", goal, re.I) or re.search(
        r"\b(?:type|enter|write)\s+[\"']?(.+?)[\"']?\s*$", goal, re.I
    )
    for _ in range(3):
        t = time.perf_counter()
        d, _ms = await kai.jev.decide(goal, [goal], 0, snap, None, [typed.group(1)] if typed else [])
        act = d["action"]
        kai.chooser = f"jev:{kai.jev.last_source}"
        kai.slog.event(
            "pick",
            goal=goal,
            decision=act,
            conf=round(d["confidence"], 2),
            ms=round((time.perf_counter() - t) * 1000),
            by=kai.jev.last_source,
        )
        if act not in ("scroll_down", "scroll_up") or re.search(r"\bscroll", g):
            break
        await kai.bc.scroll(600 if act == "scroll_down" else -600)
        snap = await _snapshot(kai, words)

    # Jev didn't pick a control: click the one element the step names exactly. In an open dialog or menu, a quoted or
    # spelled-out option name; on the page, a quoted label of something not already selected (e.g. a tab).
    quoted = re.findall(r"['\"“‘]([^'\"”’]{3,60})['\"”’]", goal)
    ids = None if act.startswith(("click_", "type_")) else await layer_ids(page)
    if not act.startswith(("click_", "type_")) and (ids is not None or quoted):
        pool = [e for e in snap["elements"] if e["id"] in ids] if ids is not None else snap["elements"]

        def named(e):
            return e["label"].split(" - ")[0].strip().lower()  # option cards read "Name - description"

        hit = [
            e
            for e in pool
            if any(e["label"].lower().startswith(q.lower().strip()) for q in quoted)
            and (ids is not None or "selected" not in e["extra"])
        ]
        if not hit and ids is not None:
            hit = [
                e for e in pool if len(named(e)) >= 6 and re.search(r"\b" + re.escape(named(e)) + r"\b", goal.lower())
            ]
        if len(hit) == 1:
            act = "click_" + hit[0]["id"]
            kai.chooser = "exact-name"
            kai.slog.event("pick", goal=goal, decision=act, by="layer-label" if ids is not None else "page-label")
        else:
            kai.slog.event(
                "pick_miss",
                goal=goal,
                decision=act,
                layer=len(pool) if ids is not None else None,
                elements=len(snap["elements"]),
                labels=[e["label"][:30] for e in pool][:12],
            )

    def loc(jid):
        return page.locator(f'[data-jev-id="{jid}"]').first

    # a typing step where Jev picked the field (or its label): type into it
    if typed and act.startswith(("click_", "type_")):
        how, shown = await type_into(page, loc(act.split("_", 1)[1]), typed.group(1))
        kai.typed_note = "" if shown is None else f" (but the field shows '{shown[:80]}', not the full text)"
        return "jev-type-" + how
    if act.startswith("click_"):
        await _click(kai, loc(act[6:]))
        return "jev-click"

    if act in ("scroll_down", "scroll_up"):
        if re.search(r"\bscroll", g):
            await kai.bc.scroll(600 if act == "scroll_down" else -600)
            return act
        act = "none"  # Jev couldn't find the target: don't wander off
    if act == "back":
        if re.search(r"\bback\b|previous", g):
            await kai.bc.go_back()
            return "back"
        act = "none"
    if (
        act in ("done", "wait")
        and _retry
        and await has_layer()
        and not re.search(r"\b(menu|dropdown|dialog|list|option)\b", g)
    ):
        act = "none"  # "already done" while an unrelated menu covers the page: close it below and look again
    if act == "done" and re.search(r"\b(close|cancel|dismiss)\b", g) and await has_layer():
        return await _escape(kai)  # a close step isn't done while the dialog is still open
    if act == "done":
        return "already-there"
    if _retry and await has_layer():
        # the target isn't in the open layer: it may be a leftover dropdown covering the page. Close it, look again.
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
        kai.slog.event("escape_retry", goal=goal)
        return await fast_hands(kai, goal, _retry=False)
    return None


async def _click(kai, el):
    """Click an element, wait until the page reacts, and set kai.last_change to what happened."""
    page = kai.bc.page
    before = await page.evaluate(SIGNATURE_JS)
    try:
        toast0 = await page.evaluate(TOASTS_JS)
    except Exception:
        toast0 = ""
    try:
        clicked_label = await el.evaluate(
            "e => e.matches('button,[role=button]') ? (e.innerText || e.getAttribute('aria-label') || '') : ''",
            timeout=300,
        )
    except Exception:
        clicked_label = ""
    try:
        await el.click(timeout=600)
    except Exception:  # covered by an animating dialog or overlay: click where the element is
        await el.scroll_into_view_if_needed(timeout=1000)
        box = await el.bounding_box()
        if not box:
            raise
        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    # a submit-like button in a dialog (judged by the button's own label, not the step's wording)
    submit = bool(
        '|dialog "' in before
        and re.match(r"\s*(create|save|submit|continue|next|done|confirm|deploy|add|apply)\b", clicked_label, re.I)
    )
    landed = await until_changed(
        page, before, 3.0 if submit else (6.0 if clicked_label else 1.0), 12.0 if submit else 0.0
    )
    try:
        st = await el.evaluate(STATE_JS, timeout=300)  # a clicked menu item is gone: don't wait the default 30 s
    except Exception:
        st = None
    after = await page.evaluate(SIGNATURE_JS)
    if submit and after.split("|")[0] == before.split("|")[0] and int(after.split("|")[1]) < int(before.split("|")[1]):
        # the dialog closed on the same page: creating or saving usually navigates a moment later, so wait for that
        try:
            await page.wait_for_url(lambda u: u.split("?")[0] != before.split("|")[0].split("?")[0], timeout=8000)
        except Exception:
            pass
        await until_changed(page, after, 0.3)
        after = await page.evaluate(SIGNATURE_JS)
    kai.last_change = describe_change(before, after, st)
    if st and st.get("on") and st.get("label"):
        kai.changes.append(f"selected {st['label']}")
    if after == before:
        kai.late_before = before  # the caller watches for something appearing later
    try:  # a toggle (Start call <-> End call) changes its own label: say so, so it isn't clicked again
        now_label = await el.evaluate(
            "e => (e.innerText || e.getAttribute('aria-label') || '').trim().split('\\n')[0].slice(0, 40)", timeout=300
        )
        if st and st.get("label") and now_label and now_label.lower() != st["label"].lower():
            kai.last_change += f" The button now reads '{now_label}'."
    except Exception:
        pass
    try:
        toast = await page.evaluate(TOASTS_JS)
    except Exception:
        toast = ""
    if toast and toast != toast0:
        kai.last_change += f" An error message appeared: {toast}"  # only a new one
    if submit and after == before:  # a submit that did nothing: report the form's validation message
        try:
            errs = await page.evaluate(FORM_ERRORS_JS)
        except Exception:
            errs = ""
        if errs:
            kai.last_change += f" The form says: {errs}"
    kai.slog.event("landed", s=landed, change=kai.last_change)
