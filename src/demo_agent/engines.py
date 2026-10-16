"""Jev, the element picker. Ported from jev-guide (brain.js decide and cli.js Runner.runStep).

decide() asks Jev which single action fits a step, given the page's element table (jev_collect.js). run_goal() is the
fallback when the hands find nothing to do: Jev drives a few decisions itself until the step is done or stuck.
"""

import asyncio
import os
import re
import time
from dataclasses import dataclass, field

TEXT_KINDS = ("text field", "search box", "password field", "text area", "combo box", "dropdown")


@dataclass
class GoalResult:
    goal: str
    done: bool = False
    steps: int = 0
    total_s: float = 0.0
    final_url: str = ""
    error: str = ""
    log: list = field(default_factory=list)


NAV_ACTIONS = {
    "scroll_down": "Scroll the page down to reveal more content",
    "scroll_up": "Scroll the page up",
    "back": "Go back to the previous page",
    "wait": "Do nothing this step; the page is still loading or an action just completed and needs time",
    "done": "The step is already complete on the current page; nothing else needs to happen",
}


async def _sig(bc):
    """url, text length, selected/expanded count and input values: changes when an action did anything."""
    try:
        return await bc.page.evaluate("""() => { const v = [...document.querySelectorAll('input,textarea,select')].map(e => e.value).join('|');
          const st = [...document.querySelectorAll('[aria-selected=true],[aria-expanded=true],[aria-checked=true],:checked')].length;
          const t = document.body ? document.body.innerText : ''; return location.href + '#' + t.length + '#' + st + '#' + v; }""")
    except Exception:
        return ""


_LEX_STOP = {
    "the",
    "and",
    "then",
    "click",
    "open",
    "goto",
    "into",
    "onto",
    "please",
    "that",
    "this",
    "for",
    "with",
    "page",
    "button",
    "link",
    "tab",
    "menu",
    "console",
    "site",
    "website",
}


def lexical_answers(state, questions):
    """Offline answers when the Jev call fails: keyword overlap between the step and each choice."""
    instr = str(state["current_step_instruction"]).lower()
    words = [w for w in re.split(r"[^a-z0-9]+", instr) if len(w) > 2 and w not in _LEX_STOP]
    hist = state.get("history_of_actions_taken_for_this_step")
    hist = hist if isinstance(hist, list) else []
    out = {}
    for name, q in questions.items():
        if q["type"] == "noul":
            p = 0.05
            if name == "submit":
                p = 0.9 if re.search(r"search|look up|enter", instr) else 0.2
            if name == "goal_met":
                url = str(state["current_page"]["url"]).lower()
                if hist or (re.search(r"go to|open|navigate", instr) and any(w in url for w in words)):
                    p = 0.9
            if name == "stuck":
                p = 0.9 if len(hist) >= 5 else 0.05
            out[name] = {"noul": p}
            continue
        scores = {}
        for label, desc in q["criteria"].items():
            d = str(desc).lower()
            sc = 0.0
            for w in words:
                if w in d:
                    sc += 1 + len(w) / 10
            if label.startswith("click_") and re.search(r"click|press|tap|select|choose", instr):
                sc += 0.5
            if label.startswith("type_") and re.search(r"type|enter|search|write|fill", instr):
                sc += 1.5
            if label in ("scroll_down", "scroll_up") and "scroll" in instr:
                sc += 5
            if label == "back" and re.search(r"\bback\b", instr):
                sc += 5
            if label in ("done", "wait"):
                sc -= 1
            scores[label] = sc
        tot = sum(max(v, 0.001) for v in scores.values())
        best = max(scores, key=scores.get)
        out[name] = {"choice": best, "confidence": max(scores[best], 0.001) / tot}
    return out


class JevEngine:
    def __init__(self):
        if os.getenv("TYPESAFE_API_KEY"):
            self.url, self.key = "https://api.typesafe.ai/v1/systemone", os.environ["TYPESAFE_API_KEY"]
        elif os.getenv("JEV_OPENROUTER_API_KEY"):
            self.url, self.key = "https://openrouter.ai/api/v1/systemone", os.environ["JEV_OPENROUTER_API_KEY"]
        else:
            raise RuntimeError("missing JEV_OPENROUTER_API_KEY (or TYPESAFE_API_KEY)")
        self.model = os.getenv("JEV_MODEL", "jev-latest")
        self._http = None
        self.last_source = "jev"  # "jev", or "lexical (<error>)" when the call failed

    async def _post(self, body):
        import aiohttp

        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "HTTP-Referer": "https://github.com/jev-guide",
                    "X-Title": "jev-guide",
                }
            )
        async with self._http.post(self.url, json=body, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                raise RuntimeError(f"jev {r.status}: {(await r.text())[:200]}")
            return await r.json()

    async def decide(self, step, all_steps, idx, snap, history, text_candidates):
        criteria = {}
        BUDGET = 250
        if text_candidates:
            criteria["press_enter"] = "Press Enter to submit what was just typed"
        criteria.update(NAV_ACTIONS)
        for e in snap["elements"]:
            if len(criteria) >= BUDGET - 1:
                break
            desc = (
                f'{e["kind"]}: "{e["label"]}"'
                + (f" ({e['extra']})" if e["extra"] else "")
                + ("" if e["inViewport"] else " [off-screen]")
            )
            if e["kind"] in TEXT_KINDS:
                if text_candidates and e["kind"] != "dropdown":
                    criteria["type_" + e["id"]] = "Type into " + desc
                criteria["click_" + e["id"]] = "Click/focus " + desc
            else:
                criteria["click_" + e["id"]] = "Click " + desc
        state = {
            "current_step_instruction": step,
            "full_instruction_sequence": [
                f"{i + 1}. {s}" + ("   <-- current step" if i == idx else "") for i, s in enumerate(all_steps)
            ],
            "step_hints": [],
            "current_page": {"url": snap["url"], "title": snap["title"]},
            "page_text_excerpt": snap["text"],
            "history_of_actions_taken_for_this_step": history or "none yet",
            "text_that_could_be_typed": text_candidates or "none",
            "note": "Prefer acting on the current page when the requested control is present. Choose done only when the step is already satisfied.",
        }
        q = {
            "action": {
                "type": "choice",
                "instructions": "Which single action best advances the current step instruction on the current page?",
                "criteria": criteria,
            },
            "goal_met": {
                "type": "noul",
                "instructions": "Is the current step instruction already fully satisfied by what is on the current page (no further action needed)?",
            },
            "stuck": {
                "type": "noul",
                "instructions": "Do the previous actions for this step show no progress (repeating, looping, or the page not responding)?",
            },
        }
        if text_candidates:
            q["submit"] = {
                "type": "noul",
                "instructions": "After typing, should Enter be pressed to submit (e.g. a search or a form)?",
            }
        t = time.perf_counter()
        try:
            res = await asyncio.wait_for(
                self._post({"model": self.model, "state": state, "questions": q}),
                float(os.getenv("JEV_CALL_TIMEOUT", 8)),
            )
            a = res["answers"]
            self.last_source = "jev"
        except Exception as e:  # a slow or failed call still acts
            a = lexical_answers(state, q)
            self.last_source = f"lexical ({type(e).__name__})"
        ms = (time.perf_counter() - t) * 1000
        return {
            "action": a["action"]["choice"],
            "confidence": a["action"].get("confidence", 0),
            "goal": a["goal_met"].get("noul", 0),
            "stuck": a["stuck"].get("noul", 0),
            "submit": (a.get("submit") or {}).get("noul", 0) > 0.5,
        }, ms

    async def run_goal(self, goal, bc, max_steps=12, all_steps=None, idx=0, text=None) -> GoalResult:
        r = GoalResult(goal)
        t0 = time.perf_counter()
        all_steps = all_steps or [goal]
        tc = [text] if text else []
        focus = [w for w in re.split(r"[^a-zA-Z0-9]+", goal) if len(w) > 2]
        history = []
        noop = 0
        for n in range(max_steps):
            snap = await bc.snapshot(240, focus)
            if n == 0:  # slow screens render controls late: wait briefly if the target isn't there yet
                for _ in range(3):
                    labs = " ".join(e["label"].lower() for e in snap["elements"])
                    if not focus or any(w.lower() in labs for w in focus if w[0].isupper() or len(w) > 5):
                        break
                    await asyncio.sleep(1.0)
                    snap = await bc.snapshot(240, focus)
            sig0 = await _sig(bc)
            d, ms = await self.decide(goal, all_steps, idx, snap, history, tc)
            r.steps += 1
            act = d["action"]
            m = re.match(r"^(click|type)_(.+)$", act)
            kind, tid = (m.group(1), m.group(2)) if m else (act, None)
            tgt = next((e for e in snap["elements"] if e["id"] == tid), None)
            desc = f'{kind} {tgt["kind"]} "{tgt["label"]}"' if tgt else act
            r.log.append(
                {
                    "op": desc,
                    "src": self.last_source,
                    "ms": round(ms),
                    "p": round(d["confidence"], 2),
                    "goal": round(d["goal"], 2),
                    "stuck": round(d["stuck"], 2),
                }
            )
            tr = getattr(bc, "trace", None)
            if tr:
                tr(
                    "jev_decision",
                    step=goal,
                    n=n + 1,
                    url_before=snap["url"],
                    n_elements=len(snap["elements"]),
                    top_elements=[f"{e['kind']}:{e['label'][:30]}" for e in snap["elements"][:15]],
                    **r.log[-1],
                )
            # stop conditions
            if d["goal"] > 0.85 and (history or act == "done"):
                r.done = True
                break
            if act == "done" and tc and not any(h["action"].startswith("type") for h in history) and d["goal"] < 0.85:
                # the step carries text but nothing was typed yet: type into the best-matching visible field instead of giving up
                fields = [
                    e
                    for e in snap["elements"]
                    if e["kind"] in ("text field", "search box", "text area", "combo box") and e["inViewport"]
                ]
                gw = {w.lower() for w in focus}
                fields.sort(key=lambda e: -len(gw & set(re.findall(r"[a-z0-9]+", e["label"].lower()))))
                if fields:
                    tgt = fields[0]
                    tid = tgt["id"]
                    kind = "type"
                    act = "type_" + tid
                    desc = f'type {tgt["kind"]} "{tgt["label"]}" (fallback)'
                    d["submit"] = False
            if act == "done" and d["goal"] < 0.5:
                fw = {w.lower() for w in focus if len(w) > 3} - {
                    "click",
                    "open",
                    "the",
                    "tab",
                    "button",
                    "page",
                    "show",
                    "left",
                    "sidebar",
                    "agent",
                    "builder",
                }

                def lab(e):
                    return set(re.findall(r"[a-z0-9]+", e["label"].lower()))

                # the target is already selected (e.g. "click the Conversation tab" while it is the active tab)
                if not history and any(("selected" in e["extra"]) and fw & lab(e) for e in snap["elements"]):
                    d["goal"] = 0.9
                # the last click hit an element matching the step and the page visibly changed (e.g. a session row opened)
                elif history and history[-1]["page_changed"] and history[-1]["action"].startswith("click"):
                    hit = bool(fw & set(re.findall(r"[a-z0-9]+", history[-1]["action"].lower())))
                    row = bool(fw & {"first", "row", "latest", "session", "recent"}) and "/sessions/RM_" in bc.page.url
                    if hit or row:
                        d["goal"] = 0.9
            if act == "done":
                # done needs goal >= 0.5, or >= 0.3 right after an action that visibly changed the page (Jev scores a
                # result that opens a new dialog low)
                if d["goal"] >= 0.5 or (history and history[-1]["page_changed"] and d["goal"] >= 0.3):
                    r.done = True
                else:
                    r.error = f"model gave up (goal {d['goal']:.2f})"
                break
            if d["stuck"] > 0.85 and len(history) >= 2:
                r.error = "stuck"
                break
            outcome = "ok"
            try:
                if (
                    kind == "click"
                    and tgt
                    and tc
                    and tgt["kind"] in ("text field", "search box", "text area", "combo box")
                    and not any(h["action"].startswith("type") for h in history)
                ):
                    # the step carries text and Jev picked the field: type into it now (saves a decision round)
                    await bc.type_jev(tid, tc[0], submit=False)
                    kind = "type"
                    desc = f'type {tgt["kind"]} "{tgt["label"]}"'
                    try:
                        v = await bc.page.locator(f'[data-jev-id="{tid}"]').first.input_value(timeout=1000)
                    except Exception:
                        v = None
                    if v is not None and v.strip() == tc[0].strip():
                        history.append(
                            {
                                "n": n + 1,
                                "action": desc,
                                "outcome": "ok (value verified)",
                                "page_changed": True,
                                "url_after": bc.page.url,
                            }
                        )
                        r.done = True
                        break
                elif kind == "click" and tgt:
                    await bc.click_jev(tid)
                elif kind == "type" and tgt and tc:
                    await bc.type_jev(tid, tc[0], submit=d["submit"])
                    # check the value directly: Jev's goal_met often stays low for typed values
                    try:
                        v = await bc.page.locator(f'[data-jev-id="{tid}"]').first.input_value(timeout=1000)
                    except Exception:
                        v = None
                    if v is not None and v.strip() == tc[0].strip() and not d["submit"]:
                        history.append(
                            {
                                "n": n + 1,
                                "action": desc,
                                "outcome": "ok (value verified)",
                                "page_changed": True,
                                "url_after": bc.page.url,
                            }
                        )
                        r.done = True
                        break
                elif act == "scroll_down":
                    await bc.scroll(600)
                    await asyncio.sleep(0.15)
                elif act == "scroll_up":
                    await bc.scroll(-600)
                    await asyncio.sleep(0.15)
                elif act == "back":
                    await bc.go_back()
                    await bc.settle_jev()
                elif act == "press_enter":
                    await bc.page.keyboard.press("Enter")
                    await bc.settle_jev()
                elif act == "wait":
                    await asyncio.sleep(1.5)
                else:
                    outcome = "unknown action"
            except Exception as e:
                outcome = f"failed: {str(e).splitlines()[0][:120]}"
            try:
                after_url = bc.page.url
                after_txt = await bc.page.evaluate("(document.body?.innerText||'').replace(/\\s+/g,' ').slice(0,200)")
            except Exception:
                after_url, after_txt = bc.page.url, ""
            # url + first 200 characters misses typed values and tab switches, so the full signature counts too
            changed = f"{after_url}|{after_txt}" != f"{snap['url']}|{snap['text'][:200]}" or (await _sig(bc)) != sig0
            if not changed and kind == "click" and tgt and outcome == "ok":
                # a click that did nothing (often a page still loading) gets one retry on the DOM element
                await asyncio.sleep(1.0)
                if (await _sig(bc)) == sig0:
                    try:
                        await bc.page.locator(f'[data-jev-id="{tid}"]').first.click(timeout=3000)
                        await bc.settle_jev()
                        outcome = "ok (retried)"
                    except Exception:
                        pass
                changed = (await _sig(bc)) != sig0
                after_url = bc.page.url
            noop = 0 if (changed or act == "wait") else noop + 1
            history.append(
                {"n": n + 1, "action": desc, "outcome": outcome, "page_changed": changed, "url_after": after_url}
            )
            if noop >= 3:
                r.error = "no visible progress after 3 actions"
                break
        else:
            r.error = "max steps reached"
        r.total_s = time.perf_counter() - t0
        r.final_url = bc.page.url
        tr = getattr(bc, "trace", None)
        if tr:
            if history:
                tr("jev_history", step=goal, history=history)
            tr("jev_step_end", step=goal, done=r.done, error=r.error, s=round(r.total_s, 2), url_after=r.final_url)
        return r
