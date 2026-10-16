"""Minimal Kai: a LiveKit Inference realtime voice model + Jev, nothing else.

The model hears the customer and talks. It has one tool, act(goal): Jev does the goal in the shared Chromium and returns
what is on screen now. Inference realtime drops images, so the model knows the screen only as page text (tool results,
plus the page text folded into its instructions after every action).

  MIN_RT_MODEL   xai/grok-voice-3.0 (default) | google/gemini-3.8-live | openai/gpt-realtime-2.1
  AGENT_NAME     faan-live-d          WORKER_PORT  8085
"""
import asyncio, io, logging, os, random, re, time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from PIL import Image
from livekit import rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, function_tool, inference
from livekit.plugins import silero

from demo_agent.browser import BrowserController, W, H
from demo_agent.engines import JevEngine
from demo_agent.pagetext import page_text
from demo_agent.sesslog import SessionLog

log = logging.getLogger("minimal")
BRAIN = os.getenv("BRAIN", "gemini-live")               # gemini-live (default): Google plugin, sees the shared screen as video | grok: MIN_RT_MODEL via LiveKit Inference, screen as text only
GEM = BRAIN == "gemini-live"
MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live") if GEM else os.getenv("MIN_RT_MODEL", "xai/grok-voice-3.0")
START_URL = os.environ.get("DEMO_START_URL") or os.environ["TOUR_START_URL"]   # the page the demo opens on (config)
SCREEN_CHARS = int(os.getenv("SCREEN_TEXT_CHARS", 1500))
ACT_RUN_MAX = int(os.getenv("ACT_RUN_MAX", 3))            # act calls in a row with nothing said in between
SCREEN_FEED = os.getenv("SCREEN_FEED", "context")        # gemini-live: screen summary as context items (context) or in the instructions

def _kb_merge(key: str) -> dict:
    """Product data that lives in the knowledge files (e.g. option lists, screen display names), merged across areas."""
    import glob, json
    out = {}
    for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge", "*.json"))):
        d = json.load(open(f)); v = d.get(key) or {}
        for k, x in v.items(): out.update(x) if isinstance(x, dict) and key == "choices" else out.__setitem__(k, x)
    return out


CHOICES = _kb_merge("choices")        # named options the customer's use case picks from (e.g. Agent Builder templates)
SCREEN_NAMES = _kb_merge("screen_names")


def _load_kbs() -> list[dict]:
    """Every demo area's knowledge file (knowledge/*.json: features, verified click paths, demo storyline)."""
    import glob, json
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge")
    return [json.load(open(f)) for f in sorted(glob.glob(os.path.join(d, "*.json")))]


def _paths(kbs) -> str:
    return "\n".join(f'- [{kb.get("area")}] {f["goal"]}: ' + " -> ".join("<the option that fits them>" if st.get("click") in CHOICES
                     else (st.get("click") or st.get("do", "")) for st in f["steps"]) for kb in kbs for f in kb["clickmap"]["flows"])


def _feature_cards() -> list[dict]:
    cards = []
    for kb in _load_kbs():
        for f in kb["features"]:
            labels = list(f.get("labels") or []) + [f["name"]] + [w for w in re.split(r"\s*[&(),/]\s*", f["name"]) if len(w) > 3]
            cards.append({"labels": [l for l in labels if isinstance(l, str)], "area": kb.get("area"),
                          "card": f'- {f["name"]}: {f.get("does", "")[:220]} WHY IT MATTERS: {f.get("value", "")[:180]} '
                                  f'USE CASES: {", ".join(f.get("use_cases") or [])[:150]} LIMITS: {str(f.get("limits") or "")[:100]} '
                                  f'ASK: {f.get("ask", "")[:140]}'})
    return cards


async def update_profile(feed, lines: list[str], slog):
    """What the customer has told Kai (company, business, use case, priorities), kept in one line for the whole call."""
    from livekit.agents import llm as _llm
    c = _llm.ChatContext()
    c.add_message(role="system", content="From what a prospect said on a sales demo call, write ONE short line: their company, "
                  "industry, what they want an agent for, and what they care about (speed, cost, compliance...). Only facts they "
                  "stated; skip unknowns. No preamble.")
    c.add_message(role="user", content="\n".join(lines[-20:]))
    out = ""
    try:
        async for ch in inference.LLM(model=PLANNER_MODEL).chat(chat_ctx=c):
            if ch.delta and ch.delta.content: out += ch.delta.content
    except Exception as e:
        log.warning("profile: %s", e); return
    out = out.strip()[:300]
    if out and out != feed.profile_line:
        feed.profile_line = out; feed.kick(); slog.event("profile", line=out)


def _knowledge() -> str:
    kbs = _load_kbs()
    out = ["VERIFIED CLICK PATHS (each arrow is one step; adapt the template/option to the customer):\n" + _paths(kbs)]
    for kb in kbs:
        area = str(kb.get("area", "")).replace("_", " ").title()
        story = re.sub(r"\s+", " ", str(kb.get("demo_instructions", "")))[:900]
        feats = "\n".join(f'- {f["name"]} ({SCREEN_NAMES.get(f.get("screen"), f.get("screen"))}): {f.get("does", "")[:120]} '
                          f'Why it matters: {f.get("value", "")[:110]} Ask: {f.get("ask", "")[:100]}' for f in kb["features"])
        out.append(f"=== {area.upper()} ===\nSTORYLINE: {story}\nFEATURES:\n{feats}")
    return "\n\n".join(out)


PLANNER_PROMPT_HEAD = """You carry out ONE screen task in the LiveKit Cloud dashboard, one step at a time, for a live demo.
Each turn you get the task, the steps so far with what each one did, and the screen summary (only the top layer: when a
dialog or menu is open, only it is clickable). Call click_step with the single next step, or finish.
Rules:
- One action per click_step: one click, one choice, or typing into one field ("type <text> into the <field> field").
- Trust what each step did ("the dialog ... opened", "... is now selected"). Never repeat a step that worked.
- Follow the recipe for the task when there is one; adapt the template/option/name from the task.
- Follow any input rules in the knowledge (e.g. naming rules). If a form shows a validation message, fix that field and retry.
- If a step didn't work, try a different phrasing once; if still stuck, finish with done=false and say what blocked it.
- If an error message appeared (a limit, a permission, a failure), don't retry or look around: finish with done=false and
  quote the error.
- If what you need isn't on screen, close any open dropdown first, then go up a level: inside a sub-page the sidebar can be
  that item's own menu, so click the project name in the breadcrumb (or the logo/back link) to get the main navigation.
- To add to a field without replacing it, say "append <text> to the <field> field".
- Do only what the TASK asks. A recipe shows the path, not a list of places to visit: stop at the first screen that
  satisfies the task, even if the recipe goes further. Don't open views the task didn't ask for, and don't go back to a
  page you already left (PAGES VISITED lists them) unless the task says so.
- If a step says it was already done / already open, or a click changed nothing because that view is already showing,
  treat that part as done and move on (or finish); never click it again.
- Finish with done=true as soon as the task's end state is on screen. Never delete, deploy to production or buy anything.
- A test call task ("start a test call", "talk to the agent"): click the live preview's start/call button once, then finish
  with done=true as soon as the call is connecting or live (an End call / Disconnect button, a timer or "connecting" shows).
  Don't click anything else in the call.
"""


PROMPT = """You are Kai, a friendly, sharp LiveKit sales engineer giving a live demo of the LiveKit Cloud dashboard. You share
your screen (a real browser) and talk with the customer by voice. You can demo four areas, each with its own storyline in the
knowledge below: AGENT BUILDER (build a voice agent in the browser, then test-call it), SIMULATIONS (test agents with simulated
callers before shipping), OBSERVABILITY (debug real calls: transcripts, traces, recordings) and TELEPHONY (phone numbers, SIP
trunks, dispatch rules). Follow what they ask for; if they're open, start with the Agent Builder. Within an area, follow its
storyline but let their questions lead. Show, don't list: open the screen and explain what's on it.

The Agent Builder demo:
1. Find out what their agent should handle (e.g. booking appointments, answering patient questions) unless they already said.
   One short question, then wait.
2. Create their agent with do_task, e.g. do_task("create an agent from the Appointment scheduling template named
   bright-smiles-front-desk"), picking the template that fits their use case. While it runs, say in one sentence why it fits. Options: """ + "; ".join(f"{k} ({v})" for k, v in CHOICES.items()) + """.
   Agent names may only use letters, numbers, dashes and underscores; a unique 3-digit number is added when it's typed.
3. When the builder is open, name the tabs (Conversation, Models & Voice, Actions, Advanced), then go where they want. Explain
   what's on screen and why it matters for their business, using the knowledge below. Now and then ask that feature's question.
4. Test call: when they want to try their agent, do_task("start a test call in the live preview"). When it connects, stay
   silent while their agent greets; you'll then be told to hand over: one short line, then you're muted while they talk to
   it. When they say "Kai" you get the call's transcript: give a one or two sentence debrief and ask what they'd like to
   change. To hang up a test call yourself, use end_test_call.
5. Single clicks (open a tab, pick an option, type one field) use act. Anything with several steps (including a verified
   click path from the knowledge, in any area) uses do_task. When they
   ask for a change (switch the voice, edit the instructions, change the model), use act per click or field, e.g. "click the Models & Voice tab", "type <text> into the Instructions field".

Rules:
- Never read out long IDs or phone numbers digit by digit; summarise ("a local Pennsylvania number").
- Present like a top sales engineer, not a remote control: keep it short (one or two sentences, about 10 seconds; never a speech over 20 seconds) and keep
  the demo MOVING. When a new screen or feature appears, say what it is and why it matters, using the "FEATURES ON SCREEN
  NOW" notes. When it genuinely fits their business (about one time in three, never forced), tie the value to them using
  what they've told you, e.g. for a clinic: "the agent could look up the patient's record right there".
- Then lead to the next logical part of that area's storyline yourself ("next, let's see where you'd debug a slow turn"),
  and go there unless they want something else. Don't wait to be asked what's next. Check in with a short question every
  two or three screens.
- Give do_task ONE destination at a time: the screen or dialog the customer needs right now (e.g. "open the most recent
  real call's Agent insights", "open Rent a number and close it"), never a whole storyline. Walk the next parts one
  request at a time as they say okay, explaining each screen in between.
- While your assistant runs a task, say one sentence about what's coming; don't make your business point twice (once
  while it runs, then again when it lands). Say the business tie-in at most once per screen.
- You can't see their mouse. If they say "this" or "over here", ask which part, offering two things from the screen.
- No lists, markdown or URLs in speech.
- """ + ("""You also see the shared screen as live video (charts, layout, what just popped up): use it for what's visual, but
  trust the screen summary for exact labels and states, and the tool results for what happened. You know the screen
  from the screen summary""" if GEM else "You can't see images. You know the screen from the screen summary") + """ below (the top layer only: when a dialog is open, it is all that is clickable) and from what your tools return. Only describe what's
  actually there, and never say something happened until the tool result says so. If a tool says it didn't work, say you'll
  fix it and try again; don't move on as if it worked.
- Answer questions honestly and stay on track. Never invent features or numbers.

PRODUCT KNOWLEDGE (facts to explain in your own words):
""" + _knowledge()
PLANNER_PROMPT = PLANNER_PROMPT_HEAD + "\nVERIFIED CLICK PATHS:\n" + _paths(_load_kbs())


class Kai(Agent):
    def __init__(self, bc: BrowserController, slog: SessionLog, feed: "ScreenText"):
        super().__init__(instructions=PROMPT)
        self.bc, self.slog, self.feed, self.jev = bc, slog, feed, JevEngine()
        self.lock = asyncio.Lock()
        self.planner = Planner(self)
        self.changes: list[str] = []   # what was configured during the demo (typed fields, selected options), for the debrief
        self.floor = None   # FloorControl (faan/floor.py): set when the voice bridge is up
        self.turns = None   # Turns: Kai's own replies, held while a test call has the floor
        self.chooser, self.choosers = "none", {}   # evidence: which component chose each click (the brain never does)

    def _floor_guard(self) -> str | None:
        if self.floor is not None and self.floor.busy:
            self.slog.event("floor_guard", state=self.floor.state)
            return ("A test call is live on screen and the customer is talking to their agent. Don't change the screen; stay quiet. "
                    "Only end_test_call is allowed.")
        return None

    async def do_step(self, goal: str) -> tuple[bool, str, str]:
        """One step on screen (Jev picks, straight click, wait until the page reacts). Returns (ok, what happened, screen)."""
        async with self.lock:
            t = time.perf_counter()
            ok, err, how = False, "", "jev"; self.chooser = "none"
            if True:   # Jev chooses (with exact-name and closing rules first); see fast_hands
                try:
                    how = await self.fast(goal); ok = how is not None
                except Exception as e:
                    log.warning("fast hands: %s", e); how = None
            if not ok and parse_typing(goal):   # a typing step whose field isn't there: report it, never type elsewhere
                how, err = "none", f"couldn't find the '{parse_typing(goal)[1]}' field on screen"
            elif not ok and await self.bc.page.locator(TOP_LAYER).count():
                how, err = "none", "couldn't find that in the open dialog/menu"
            elif not ok:
                how = "jev"; self.chooser = "jev-agent"
                try:
                    r = await asyncio.wait_for(self.jev.run_goal(goal, self.bc, narrate=None, max_steps=6), 25)
                    ok, err = r.done, r.error
                except Exception as e:
                    ok, err = False, f"{type(e).__name__}: {e}"[:160]
            txt = await screen_summary(self.bc.page)
            change = getattr(self, "last_change", "") if how == "jev-click" else (f"Typed it{getattr(self, 'typed_note', '')}." if ok and str(how).startswith(("type", "jev-type"))
                     else "Nothing clicked: that already looks done/open on screen." if how == "already-there" else "")
            self.last_change = ""
            if not ok and self.chooser.startswith("jev:"): self.chooser = "none"   # nothing was clicked
            self.slog.event("act_done", goal=goal, ok=ok, how=how, chooser=self.chooser, brain=BRAIN, s=round(time.perf_counter() - t, 2), error=err, change=change)
            self.choosers[self.chooser] = self.choosers.get(self.chooser, 0) + 1
            self.feed.kick()
            return ok, ((change or "Done.") if ok else f"Didn't fully work ({err or 'not reached'})."), txt

    @function_tool
    async def act(self, ctx: RunContext, goal: str) -> str:
        """Do ONE simple thing on the shared screen, described in plain words (e.g. "open Sessions", "click the Models &
        Voice tab", "type Bright Smiles Dental into the agent name field"). For anything with several steps, use do_task.
        Returns what happened and what the screen shows now."""
        if (g := self._floor_guard()): return g
        if self.planner.running:
            return f"A task is running ({self.planner.status}). Don't click yourself; talk about what's happening, or call stop_task."
        mark = (len(self.feed.agent_lines), self.feed.user_turns)   # clicks in a row with nothing said in between
        self.act_run = self.act_run + 1 if mark == getattr(self, "act_mark", None) else 1; self.act_mark = mark
        if self.act_run > ACT_RUN_MAX:   # seen with Gemini Live: 30+ silent act calls (40 s of dead air) hunting for a session
            self.slog.event("act_run_guard", goal=goal, run=self.act_run)
            return (f"Not done: you've made {self.act_run - 1} clicks in a row without saying anything, and the customer is waiting "
                    "in silence. First tell them, in one sentence, what's on screen now. If you still need several steps, use "
                    "do_task with the destination instead of clicking one by one.")
        self.slog.event("act", goal=goal)
        self.late_before = None
        ok, what, txt = await self.do_step(goal)
        key = (re.sub(r"\W+", " ", goal.lower())[:60], what)
        if key == getattr(self, "last_act", None) and no_effect(what):
            return no_effect_reason(what, txt) + " Don't try again; explain it from the screen summary instead.\nSCREEN NOW:\n" + txt
        self.last_act = key
        if getattr(self, "late_before", None): asyncio.create_task(watch_late_change(self, self.late_before, goal))
        asyncio.create_task(nudge_if_silent(self, what))
        return what + " Trust this result; don't redo a step that worked.\nSCREEN NOW:\n" + txt

    @function_tool
    async def do_task(self, ctx: RunContext, request: str) -> str:
        """Hand a multi-step task on the screen to your assistant, who does it step by step while you keep talking (e.g.
        "create an agent from the Appointment scheduling template named bright-smiles-front-desk", "add an HTTP tool in
        Actions and cancel it", "start a test call in the live preview"). Put every detail in the request (template,
        name, values). Returns at once; you'll get an update when it's done or stuck."""
        if (g := self._floor_guard()): return g
        if self.planner.running:   # never drop it ("start a test call" asked while the agent is still being created)
            self.planner.queued = request; self.slog.event("task_queued", request=request)
            return (f"Queued: your assistant starts it as soon as the current task ({self.planner.status}) is done. Say that in a "
                    "few words; don't call do_task again.")
        # a name the model picks is often the same across calls ("-17"), and a recently deleted agent's name can't be reused:
        # give every new name a random 3-digit suffix
        request = re.sub(r"\b(named|called)\s+['\"]?([A-Za-z0-9][\w-]*)['\"]?",
                         lambda m: f"{m.group(1)} {agent_slug(re.sub(r'-?\d{1,3}$', '', m.group(2)))}", request, count=1)
        self.planner.start(request)
        return "Started. Say one sentence about why this fits them while it runs; don't click anything yourself."

    @function_tool
    async def stop_task(self, ctx: RunContext) -> str:
        """Stop the running screen task (the customer changed direction or asked you to stop)."""
        return await self.planner.stop()

    @function_tool
    async def end_test_call(self, ctx: RunContext) -> str:
        """Hang up the Agent Builder test call on screen (the live preview call)."""
        ok = await self.bc.end_test_call()
        self.slog.event("test_call_ended", by="tool", ok=ok)
        return "The test call is ended." if ok else "No test call was running."


PLANNER_MODEL = os.getenv("PLANNER_MODEL", "openai/gpt-5.4-mini")
PLANNER_SCREEN_CHARS = int(os.getenv("PLANNER_SCREEN_CHARS", 5000))


class Planner:
    """jev-guide's split: the voice (Grok) talks; this background loop does multi-step screen work. Each turn: read the
    task, the steps so far (with what each click did) and the screen summary -> one next step (Jev clicks it) or finish.
    Progress goes into Grok's instructions (one status line); the outcome comes back as one generated reply."""
    MAX_STEPS = 12

    def __init__(self, kai: "Kai"):
        self.kai, self.task, self.status, self.history = kai, None, "", []
        self.queued = None   # one task asked for while another ran: starts right after it

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, request: str):
        self.kai.feed.task_line = ""
        self.request, self.history, self.status, self.pages = request, [], "starting", []
        self.said_from = len(self.kai.feed.agent_lines)
        self.task = asyncio.create_task(self._run())

    def on_app_live(self):
        """The test call went live (voice bridge: the page opened its mic). A 'start a test call' task ends here, silently:
        FloorControl owns what Kai says next (wait out the greeting, one handover line)."""
        self.queued = None
        if not self.running: return
        self.task.cancel(); self._set("")
        self.kai.slog.event("task_done", request=self.request, done=True, outcome="The test call is live.", steps=len(self.history),
                            why="test call live")

    async def stop(self) -> str:
        self.queued = None
        if not self.running: return "Nothing is running."
        self.task.cancel(); self.status = ""
        self.kai.feed.task_line = ""; self.kai.feed.kick()
        self.kai.slog.event("task_stopped", request=self.request)
        return "Stopped. The screen stays where it is."

    def _set(self, status: str):
        self.status = status
        self.kai.feed.task_line = (f"TASK RUNNING (your assistant is doing it; don't click): {self.request} | now: {status}" if status else "")
        self.kai.feed.kick()

    async def _decide(self, screen: str):
        from livekit.agents import llm
        @function_tool
        async def click_step(goal: str) -> str:
            """Do ONE step on screen: a single click, choice, or typing into one field ("type <text> into the <field> field")."""
            return ""
        @function_tool
        async def finish(outcome: str, done: bool) -> str:
            """The task is complete (done=true) or can't be completed (done=false). outcome: one sentence for the customer."""
            return ""
        c = llm.ChatContext()
        c.add_message(role="system", content=PLANNER_PROMPT)
        steps = "\n".join(f"{i+1}. {g} -> {r}" for i, (g, r) in enumerate(self.history)) or "none yet"
        pages = " > ".join(dict.fromkeys(p.split(" (")[0] for p in self.pages)) or "only the current one"
        c.add_message(role="user", content=f"TASK: {self.request}\n\nSTEPS SO FAR (what each did):\n{steps}\n\nPAGES VISITED: {pages}\n\n{screen}")
        for m in (PLANNER_MODEL, "google/gemini-3-flash"):
            try:
                calls = []
                async for ch in inference.LLM(model=m).chat(chat_ctx=c, tools=[click_step, finish]):
                    if ch.delta and ch.delta.tool_calls: calls += ch.delta.tool_calls
                if calls:
                    import json
                    return calls[0].name, json.loads(calls[0].arguments or "{}")
            except Exception as e:
                log.warning("planner %s: %s", m, e)
        return "finish", {"outcome": "I couldn't work out the next step.", "done": False}

    async def _run(self):
        k, t0, outcome, done = self.kai, time.perf_counter(), "", False
        k.slog.event("task_start", request=self.request)
        try:
            screen = await screen_summary(k.bc.page, PLANNER_SCREEN_CHARS)
            for n in range(self.MAX_STEPS):
                t = time.perf_counter()
                name, args = await self._decide(screen)
                k.slog.event("plan", step=n + 1, decision=name, args=args, ms=round((time.perf_counter() - t) * 1000))
                if name == "finish":
                    outcome, done = args.get("outcome", ""), bool(args.get("done")); break
                goal = args.get("goal", "")
                self._set(f"step {n + 1}: {goal}")
                ok, what, screen = await k.do_step(goal)
                try: screen = await screen_summary(k.bc.page, PLANNER_SCREEN_CHARS)   # the builder's Start call sits past 1500 chars
                except Exception: pass
                self.history.append((goal, what if ok else what))
                self.pages.append(screen.split("\n", 1)[0][6:80])
                stuck = [w for _, w in self.history[-2:]]
                if len(stuck) == 2 and stuck[0] == stuck[1] and no_effect(stuck[0]):
                    reason = no_effect_reason(stuck[0], screen)
                    outcome, done = reason + " Explain it from the screen instead of clicking.", reason.startswith("That's already")
                    break
            else:
                outcome = "That took more steps than expected, so I stopped."
        except asyncio.CancelledError:
            raise
        except Exception as e:
            outcome = f"Something went wrong: {type(e).__name__}"; log.exception("planner")
        self._set("")
        # the result stays in Kai's instructions (a reply to the customer may come before ours, and must know it)
        k.feed.task_line = f"LAST SCREEN TASK ({'done' if done else 'NOT completed'}): {self.request[:120]} -> {outcome}"
        k.feed.kick()
        k.slog.event("task_done", request=self.request, done=done, outcome=outcome, steps=len(self.history), s=round(time.perf_counter() - t0, 1))
        nxt, self.queued = self.queued, None
        if nxt and done:   # the queued task starts now; one short line covers both
            self.start(nxt)
            text = (f"Your assistant finished: {outcome} It is now doing what they asked next: {nxt}. Say both in one short "
                    "sentence; don't call do_task.")
            if k.turns is not None: k.turns.request("task", text)
            else: k.session.generate_reply(instructions=text)
            return
        if k.floor is not None and k.floor.busy: return   # a test call has the floor: FloorControl speaks next
        n_user, user_spoke = k.feed.user_turns, False
        for _ in range(40):   # don't talk over the customer, or over Kai's own line about this task
            us = getattr(k.session, "user_state", "")
            user_spoke = user_spoke or us == "speaking"
            if us != "speaking" and getattr(k.session, "agent_state", "") != "speaking": break
            await asyncio.sleep(0.2)
        if user_spoke or k.feed.user_turns != n_user:   # the customer talked: Kai's answer to them carries the result
            k.slog.event("task_reply_skipped", why="customer spoke"); return
        said = len(k.feed.agent_lines) > self.said_from   # (quoting those lines back made Grok say them again verbatim)
        if done and len(" ".join(k.feed.agent_lines[self.said_from:]).split()) >= 15:
            # Kai already explained this while it ran; a second reply came out as the same point again (even when told not
            # to). The result is in his instructions; the customer's next turn picks it up.
            k.slog.event("task_reply_skipped", why="already explained"); return
        text = (
            f"Your assistant finished the screen task ({'done' if done else 'not completed'}): {outcome} "
            + ("You were already talking while it ran: don't restate anything you said and don't make another business "
               "tie-in. In ONE short sentence, " if said else "In one or two short sentences, ")
            + "say what's on screen now that you haven't mentioned, then lead to the next step.")
        if nxt and not done: text += f" (Their next request, '{nxt}', was not started because this one didn't complete.)"
        if k.turns is not None: k.turns.request("task", text); return   # fires when nobody is speaking, never during a test call
        k.session.generate_reply(instructions=text)


def no_effect(what: str) -> bool:
    return "no visible change" in what or "already looks done" in what or "still open" in what


def no_effect_reason(what: str, screen: str) -> str:
    """Why a repeated step changed nothing: usually the view is already open/selected, sometimes it just isn't clickable."""
    m = re.search(r"Clicked '([^']+)'", what); lab = m.group(1) if m else ""
    head = screen.split("\n", 1)[0].lower()
    nav = lab and re.search(r"-\s*(?:link|tab)\s+\"" + re.escape(lab) + r"\"", screen, re.I)   # a nav link/tab that does nothing = we're on it
    if "already looks done" in what or "is now selected" in what or (lab and lab.lower() in head) or nav:
        return f"That's already open on screen{f' ({lab})' if lab else ''}: clicking it again changes nothing, so that part is done."
    what_ = f"'{lab}'" if lab else "that"
    return f"Clicking {what_} twice changed nothing: it isn't something that opens here."


def agent_slug(name: str) -> str:
    """The dashboard only accepts letters, numbers, underscores and dashes; a random suffix avoids clashing with older agents."""
    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower())).strip("-_")[:32] or "demo-agent"
    return slug if re.search(r"-\d{3,}$", slug) else f"{slug}-{random.randint(100, 999)}"


TOASTS_JS = r"""() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sel = '[role=alert],[role=status],[aria-live=assertive],[aria-live=polite],[data-sonner-toast],[class*=toast],[class*=Toast],[class*=notification]';
  return [...new Set([...document.querySelectorAll(sel)].filter(e => vis(e) && (e.innerText || '').trim())
    .map(e => e.innerText.trim().replace(/\s+/g, ' ').slice(0, 200)))].filter(t => /error|fail|could not|couldn|unable|denied|limit|exceed|invalid|not allowed|exhausted/i.test(t)).slice(0, 2).join(' | '); }"""


FORM_ERRORS_JS = r"""() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const root = [...document.querySelectorAll('[role=dialog],[aria-modal=true]')].filter(vis).pop(); if (!root) return '';
  return [...root.querySelectorAll('*')].filter(e => vis(e) && !e.children.length && /required|only letters|invalid|must|already/i.test(e.innerText || ''))
    .map(e => e.innerText.trim()).slice(0, 2).join(' | '); }"""


def parse_typing(goal: str):
    """("text", "field") from a typing step, or None. Handles: type X into the Y field / type into the Y editor: "X" /
    enter "X" in the Y box / set the Y to "X" / clear the Y and type X."""
    if not re.search(r"\b(type|enter|write|fill|set|change|replace|put|append|add)\b", goal, re.I): return None
    q = re.search(r"[\"\u201c\u2018']([^\"\u201d\u2019]{1,2000})[\"\u201d\u2019]", goal)
    END = r"(?:\s+(?:field|editor|box|textbox|input|text area)\b|\s*[:,.]|\s+(?:to|with|and|so|replacing)\b|$)"
    f = (re.search(r"\binto\s+the\s+(?:open\s+)?(.+?)" + END, goal, re.I)                       # "into the X field" wins
         or re.search(r"\b(?:set|change|replace|clear|update)\s+the\s+(?:current\s+)?(.+?)" + END, goal, re.I)
         or ([m for m in re.finditer(r"\b(?:in|to)\s+the\s+(?!open\b)(.+?)" + END, goal, re.I)] or [None])[-1])
    text = q.group(1) if q else None
    if not text and (w := re.search(r"\bwith\s+(.+?)\s*$", goal, re.I)): text = w.group(1).strip(" .'\"")
    if not text:
        m = re.search(r"\b(?:type|enter|write|put)\s+(?!into\b|in\b)(.+?)\s+(?:into|in)\s+the\b", goal, re.I) \
            or re.search(r"\b(?:type|enter|write)\s+(?!into\b|in\b)(.+?)\s*$", goal, re.I)
        text = m.group(1).strip(" '\"") if m else None
    if not text or not f: return None
    field = re.sub(r"^(?:(?:open|focused|current|existing|main|same)\s+)+", "", f.group(1), flags=re.I).strip(" '\"")
    return (text, field) if field and len(field) < 40 else None


def is_append(goal: str) -> bool:
    return bool(re.search(r"\b(append|add (?:it |this |that )?to the end|add (?:a |another )?(?:line|sentence|rule)|at the end)\b", goal, re.I))


FIELD_AFTER_HEADING_JS = r"""(name) => { const N = name.trim().toLowerCase(); const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ED = '.monaco-editor,.cm-editor,.ProseMirror';
  const ctrls = [...new Set([...document.querySelectorAll('textarea,input:not([type=hidden]):not([type=checkbox]):not([type=radio]),[contenteditable=true],' + ED)]
    .map(e => (e.closest && e.closest(ED)) || e))].filter(e => vis(e) && e.getAttribute('aria-hidden') !== 'true');
  const heads = [...document.querySelectorAll('label,h1,h2,h3,h4,h5,legend,p,span,div')].filter(e => vis(e) && e.children.length <= 2
    && (e.innerText || '').trim().toLowerCase().replace(/\s+/g, ' ') === N);
  for (const h of heads) { const c = ctrls.find(c => h.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING);
    if (c) { const id = 'f' + Math.random().toString(36).slice(2, 8); c.setAttribute('data-faan-field', id); return id; } }
  return null; }"""


async def find_field(page, field: str):
    """The input/editor for a field name, in the top layer: by label, placeholder, textbox name, or the heading above it."""
    layer = page.locator(TOP_LAYER); n = await layer.count()
    scope = layer.nth(n - 1) if n else page
    for cand in (scope.get_by_label(field, exact=False), scope.get_by_placeholder(field, exact=False),
                 scope.get_by_role("textbox", name=re.compile(re.escape(field), re.I))):
        try:
            if await cand.count(): return cand.first
        except Exception:
            pass
    try:
        fid = await page.evaluate(FIELD_AFTER_HEADING_JS, field)
        if fid: return page.locator(f'[data-faan-field="{fid}"]').first
    except Exception:
        pass
    return None


EDITOR_FOR_JS = r"""(e) => { const ED = '.monaco-editor,.cm-editor,.ProseMirror'; let ed = e.closest(ED);
  if (!ed) ed = [...document.querySelectorAll(ED)].find(x => e.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING);
  if (!ed) return null; const id = 'ed' + Math.random().toString(36).slice(2, 7); ed.setAttribute('data-faan-ed', id); return id; }"""


async def type_into(page, loc, text: str, append: bool = False) -> str:
    """Inputs take fill(); the builder's Instructions / Welcome message are code editors (Monaco), where fill() fails and
    Control+A is "line start" on macOS: click into the editor, select all with ControlOrMeta+A, then insert the text."""
    if await loc.evaluate("e => e.matches('input,textarea') && !e.closest('.monaco-editor,.cm-editor')"):
        if append: await loc.click(timeout=3000); await page.keyboard.press("ControlOrMeta+End"); await page.keyboard.insert_text(text); return "append"
        await loc.fill(text, timeout=3000); return "fill"
    ed = await loc.evaluate(EDITOR_FOR_JS)
    if not ed: await loc.fill(text, timeout=3000); return "fill"
    box = page.locator(f'[data-faan-ed="{ed}"]').first
    await box.click(timeout=3000)
    if append:   # keep what's there, add at the end on a new line
        await page.keyboard.press("ControlOrMeta+End"); await page.keyboard.press("Enter"); await page.keyboard.insert_text(text); return "editor-append"
    await page.keyboard.press("ControlOrMeta+A"); await page.keyboard.press("Backspace")
    await page.keyboard.insert_text(text); return "editor"


_SIG_JS = """() => { const L = [...document.querySelectorAll('[role=dialog],[role=menu],[role=listbox],[aria-modal=true]')];
  const top = L.length ? L[L.length - 1] : null;
  const name = top ? (top.getAttribute('role') === 'menu' ? 'menu' : top.getAttribute('role') === 'listbox' ? 'list' : 'dialog') + ' "'
    + ((top.getAttribute('aria-label') || (top.querySelector('h1,h2,h3') || {}).innerText || '').trim().slice(0, 40)) + '"' : '';
  return location.href + '|' + L.length + '|' + (document.querySelector('main')||document.body).innerText.length + '|' + name; }"""


STATE_JS = r"""(e) => { const a = (k) => e.getAttribute(k); const inp = e.matches('input') ? e : e.querySelector('input[type=radio],input[type=checkbox]');
  const on = a('aria-checked') === 'true' || a('aria-selected') === 'true' || a('aria-pressed') === 'true' || a('data-state') === 'checked'
    || a('data-state') === 'active' || (inp && inp.checked) || !!e.querySelector('[aria-checked=true],[data-state=checked]');
  const lab = (e.labels && e.labels[0] && e.labels[0].innerText) || e.innerText || a('aria-label') || (e.closest('label') || {}).innerText || e.value || '';
  return { label: lab.trim().split('\n')[0].slice(0, 60), on,
           expanded: a('aria-expanded') }; }"""


TOP_LAYER = "[role=dialog]:visible, [aria-modal=true]:visible, [role=menu]:visible, [role=listbox]:visible"


async def screen_summary(page, limit: int = SCREEN_CHARS) -> str:
    """What's on screen, from the page source: the accessibility tree (roles, names, states like [checked]/[selected]) of the
    TOP layer only. An open dialog or menu hides the page behind it, so Kai and Jev must not see that page (Jev picked the
    background 'Deploy new agent' button while the template dialog was open and closed it)."""
    try:
        layer = page.locator(TOP_LAYER)
        n = await layer.count()
        where = "an open dialog/menu" if n else "the page"
        root = layer.nth(n - 1) if n else page.locator("main").first
        if not n and not await root.count(): root = page.locator("body")
        tree = await root.aria_snapshot(timeout=2000)
        tree = "\n".join(l for l in tree.splitlines() if not re.match(r"\s*- (img|separator|generic|/url:)\b|\s*- /url:", l) and l.strip() not in ("- generic", "- list"))
        title = await page.title()
        return f"PAGE: {title} ({page.url.split('cloud.livekit.io')[-1][:80]}). Showing {where}:\n" + tree[:limit]
    except Exception as e:
        return await page_text(page, limit)


async def layer_ids(page) -> set | None:
    """data-jev-id values inside the top layer, or None when nothing is layered on top."""
    layer = page.locator(TOP_LAYER)
    n = await layer.count()
    if not n: return None
    return set(await layer.nth(n - 1).evaluate("e => [...e.querySelectorAll('[data-jev-id]')].map(x => x.getAttribute('data-jev-id'))"))


def describe_change(before: str, after: str, st: dict | None) -> str:
    """Say in words what a click did, so the planner doesn't have to infer it from page text (it re-clicked selected cards)."""
    (u0, d0, _, n0), (u1, d1, _, n1) = before.split("|", 3), after.split("|", 3)
    what = ("a new page opened" + (f" with the {n1} open" if n1 else "") if u0 != u1 else
            f"the {n1 or 'dialog or menu'} opened" if int(d1) > int(d0) or (n1 and n1 != n0) else
            f"the {n0 or 'dialog or menu'} closed" if int(d1) < int(d0) else "the page content changed" if before != after else "no visible change")
    lab = f"'{st['label']}'" if st and st.get("label") else "it"
    sel = f"; {lab} is now selected" if st and st.get("on") else ""
    return f"Clicked {lab}: {what}{sel}."


BUSY_JS = """() => { const d = [...document.querySelectorAll('[role=dialog],[aria-modal=true]')].pop(); if (!d) return false;
  return !!d.querySelector('[aria-busy=true],svg[class*=animate-spin],[class*=spinner],[class*=loading]') ||
    [...d.querySelectorAll('button')].some(b => b.disabled && /create|save|deploy|submit|continue|next/i.test(b.innerText || '')); }"""


async def until_changed(page, before: str, limit: float = 1.0, busy_limit: float = 0.0):
    """Return as soon as the page visibly reacts to the click (route, dialog/menu, or content change), at most `limit` s.
    With busy_limit: keep waiting (up to busy_limit s) while an open dialog shows it is working (spinner, disabled submit):
    creating an agent takes a few seconds server-side, and a second Create click in that time breaks the dialog."""
    t = time.perf_counter()
    while True:
        el = time.perf_counter() - t
        if el >= limit:
            if not busy_limit or el >= busy_limit: break
            try:
                if not await page.evaluate(BUSY_JS): break
            except Exception: break
        await asyncio.sleep(0.05)
        try:
            now = await page.evaluate(_SIG_JS)
            if now != before:
                if now.split("|")[0] != before.split("|")[0]:   # new page: wait out skeleton/loading placeholders (max 4 s)
                    try: await page.wait_for_function("() => !document.querySelector('[class*=skeleton],[class*=shimmer],[aria-busy=true]')", timeout=4000)
                    except Exception: pass
                await asyncio.sleep(0.15); return round(time.perf_counter() - t, 2)
        except Exception:
            pass
    return None


async def fast_hands(self, goal: str, _retry: bool = True):
    """Rules for scroll/back, else one small-LLM pick over the visible elements. Returns how it acted, or None (-> Jev)."""
    g = goal.lower()
    # closing by Escape only when the step IS "close/dismiss ..." -- not "click 'Yes, discard changes' to close the dialog"
    if re.match(r"\s*(?:close|dismiss|escape|press escape|click outside|click away)\b", g) and await self.bc.page.locator(TOP_LAYER).count() \
            and not re.search(r"\bclick (?:the )?['\"]?(?:close|cancel)\b", g):
        self.chooser = "escape"
        n0 = await self.bc.page.locator(TOP_LAYER).count()   # closing a menu/dropdown/dialog: Escape, and say if it worked
        await self.bc.page.keyboard.press("Escape"); await asyncio.sleep(0.3)
        n1 = await self.bc.page.locator(TOP_LAYER).count()
        self.last_change = "Closed it." if n1 < n0 else "Pressed Escape but it's still open."
        return "jev-click"
    if re.search(r"\bscroll", g):
        self.chooser = "rule"
        up = bool(re.search(r"\bup\b|\btop\b", g)); far = bool(re.search(r"bottom|top|all the way|lot", g)); bit = "bit" in g or "little" in g
        await self.bc.scroll((-1 if up else 1) * (3000 if far else 300 if bit else 600)); return "scroll"
    if re.search(r"\bgo back\b|\bback\b$|previous page", g):
        self.chooser = "rule"; await self.bc.go_back(); return "back"
    tgt = parse_typing(goal)
    if tgt:   # typing: the text (quoted, or after "type") goes into the field named after "into/in the" -- never another box
        text, field = tgt
        if re.search(r"\bagent name\b|^name$", field, re.I):   # a name an earlier demo used (even deleted) fails Create with an
            text = agent_slug(text)                            # "[internal]" error: make it unique (random 3-digit suffix)
        cand = await find_field(self.bc.page, field); self.chooser = "exact-name"
        if cand is None:
            self.slog.event("type_no_field", field=field); return None
        add = is_append(goal)
        self.typed_note = f" ({'added to' if add else 'set'} '{field}': '{text[:60]}')"
        self.changes.append(f"{'added to' if add else 'set'} {field}: {text[:200]}")
        return "type-" + await type_into(self.bc.page, cand, text, append=add)
    words = [w for w in re.split(r"[^a-zA-Z0-9]+", goal) if len(w) > 2]
    snap = await self.bc.snapshot(240, words)
    if (ids := await layer_ids(self.bc.page)) is not None:   # a dialog/menu is open: only its controls are clickable
        snap["elements"] = [e for e in snap["elements"] if e["id"] in ids] or snap["elements"]
    typed = (re.search(r"\b(?:type|enter|write)\s+[\"']?(.+?)[\"']?\s+(?:in|into)\s+the\b", goal, re.I)   # "type X into the name field"
             or re.search(r"\b(?:type|enter|write)\s+[\"']?(.+?)[\"']?\s*$", goal, re.I))                    # "clear the name and type X"
    for attempt in range(3):
        t = time.perf_counter()
        d, _ = await self.jev.decide(goal, [goal], 0, snap, None, [typed.group(1)] if typed else [])   # Jev only chooses
        ms = round((time.perf_counter() - t) * 1000)
        act = d["action"]; self.chooser = f"jev:{self.jev.last_source}"; self.slog.event("pick", goal=goal, decision=act, conf=round(d["confidence"], 2), ms=ms, by=self.jev.last_source)
        if act not in ("scroll_down", "scroll_up") or re.search(r"\bscroll", g): break
        await self.bc.scroll(600 if act == "scroll_down" else -600)   # the target is off-screen: reveal it, then pick again
        snap = await self.bc.snapshot(240, words)
        if (ids := await layer_ids(self.bc.page)) is not None:
            snap["elements"] = [e for e in snap["elements"] if e["id"] in ids] or snap["elements"]
    if not act.startswith(("click_", "type_")) and (ids := await layer_ids(self.bc.page)) is not None:
        # a dialog/menu is open and Jev didn't pick (seen: scroll_down on the template dialog): the option named in quotes
        # ('Appointment scheduling') matches exactly one control of the top layer -> click it
        layer = [e for e in snap["elements"] if e["id"] in ids]
        quoted = re.findall(r"['\"\u201c\u2018]([^'\"\u201d\u2019]{3,60})['\"\u201d\u2019]", goal)
        named = lambda e: e["label"].split(" - ")[0].strip().lower()   # option cards: "Appointment scheduling - Capture ..."
        hit = [e for e in layer if any(e["label"].lower().startswith(q.lower().strip()) for q in quoted)] or \
              [e for e in layer if len(named(e)) >= 6 and re.search(r"\b" + re.escape(named(e)) + r"\b", goal.lower())]
        if len(hit) == 1:
            act = "click_" + hit[0]["id"]; self.chooser = "exact-name"; self.slog.event("pick", goal=goal, decision=act, by="layer-label", layer=len(layer))
        else:
            self.slog.event("pick_miss", goal=goal, decision=act, layer=len(layer), elements=len(snap["elements"]),
                            labels=[e["label"][:30] for e in layer][:12])
    loc = lambda jid: self.bc.page.locator(f'[data-jev-id="{jid}"]').first
    if typed and act.startswith(("click_", "type_")):   # Jev often picks "click/focus <field>" (or its label) for a typing goal
        return "jev-type-" + await type_into(self.bc.page, loc(act.split("_", 1)[1]), typed.group(1))
    if act.startswith("click_"):
        before = await self.bc.page.evaluate(_SIG_JS)
        try: toast0 = await self.bc.page.evaluate(TOASTS_JS)
        except Exception: toast0 = ""
        el = loc(act[6:])
        try: clicked_label = await el.evaluate("e => e.matches('button,[role=button]') ? (e.innerText || e.getAttribute('aria-label') || '') : ''", timeout=300)
        except Exception: clicked_label = ""
        try: await el.click(timeout=600)   # straight click: no glide, hover or fixed wait
        except Exception:   # covered by an animating dialog/overlay: click where the element is
            await el.scroll_into_view_if_needed(timeout=1000)
            box = await el.bounding_box()
            if not box: raise
            await self.bc.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        # a submit-like BUTTON in a dialog (by the clicked element's own label, not the step's wording)
        submit = bool('|dialog "' in before and re.match(r"\s*(create|save|submit|continue|next|done|confirm|deploy|add|apply)\b",
                                                         clicked_label, re.I))
        landed = await until_changed(self.bc.page, before, 3.0 if submit else (6.0 if clicked_label else 1.0), 12.0 if submit else 0.0)
        try: st = await el.evaluate(STATE_JS, timeout=300)   # a clicked menu item is gone: don't wait the default 30 s
        except Exception: st = None
        after = await self.bc.page.evaluate(_SIG_JS)
        if submit and after.split("|")[0] == before.split("|")[0] and int(after.split("|")[1]) < int(before.split("|")[1]):
            # the dialog closed but we're still on the same page: creating/saving usually navigates a moment later (the
            # builder opens ~1-5 s after Create). Wait for that instead of reporting "closed" and letting the planner wander.
            try: await self.bc.page.wait_for_url(lambda u: u.split("?")[0] != before.split("|")[0].split("?")[0], timeout=8000)
            except Exception: pass
            await until_changed(self.bc.page, after, 0.3)
            after = await self.bc.page.evaluate(_SIG_JS)
        self.last_change = describe_change(before, after, st)
        if st and st.get("on") and st.get("label"): self.changes.append(f"selected {st['label']}")
        if after == before: self.late_before = before   # watch for something appearing later (see watch_late_change)
        try:   # a toggle (START CALL <-> END CALL) changes its own label: say so, so it isn't clicked again
            now_label = await el.evaluate("e => (e.innerText || e.getAttribute('aria-label') || '').trim().split('\\n')[0].slice(0, 40)", timeout=300)
            if st and st.get("label") and now_label and now_label.lower() != st["label"].lower():
                self.last_change += f" The button now reads '{now_label}'."
        except Exception:
            pass
        try: toast = await self.bc.page.evaluate(TOASTS_JS)   # an error pop-up after any click (e.g. a quota error on Create)
        except Exception: toast = ""
        if toast and toast != toast0: self.last_change += f" An error message appeared: {toast}"   # only a new one, not a lingering toast
        if submit and after == before:   # a submit that did nothing: say why (validation message in the dialog)
            try: errs = await self.bc.page.evaluate(FORM_ERRORS_JS)
            except Exception: errs = ""
            if errs: self.last_change += f" The form says: {errs}"
        self.slog.event("landed", s=landed, change=self.last_change); return "jev-click"
    if act in ("scroll_down", "scroll_up"):
        if re.search(r"\bscroll", g):
            await self.bc.scroll(600 if act == "scroll_down" else -600); return act
        act = "none"   # it couldn't find the target: don't wander (a covering menu is closed below)
    if act == "back":
        if re.search(r"\bback\b|previous", g):
            await self.bc.go_back(); return "back"
        act = "none"
    if act in ("done", "wait") and _retry and await self.bc.page.locator(TOP_LAYER).count() \
            and not re.search(r"\b(menu|dropdown|dialog|list|option)\b", g):
        act = "none"   # "already done" while an unrelated menu covers the page: it's in the way, close it below
    if act == "done" and re.search(r"\b(close|cancel|dismiss)\b", g) and await self.bc.page.locator(TOP_LAYER).count():
        # "already done" for a close/cancel step while a dialog is still open is wrong (seen with Rent a number): close it
        n0 = await self.bc.page.locator(TOP_LAYER).count(); self.chooser = "escape"
        await self.bc.page.keyboard.press("Escape"); await asyncio.sleep(0.3)
        self.last_change = "Closed it." if await self.bc.page.locator(TOP_LAYER).count() < n0 else "Pressed Escape but it's still open."
        return "jev-click"
    if act == "done":
        return "already-there"
    if _retry and await self.bc.page.locator(TOP_LAYER).count():
        # the target isn't in the open menu/list/dialog: it may be a leftover dropdown covering the page. Close it, look again.
        await self.bc.page.keyboard.press("Escape"); await asyncio.sleep(0.3)
        self.slog.event("escape_retry", goal=goal)
        return await fast_hands(self, goal, _retry=False)
    return None


Kai.fast = fast_hands


def floor_busy(kai) -> bool:
    """A test call has the floor (Kai is muted and must stay silent): no self-prompted lines."""
    fl = getattr(kai, "floor", None)
    return fl is not None and bool(getattr(fl, "busy", False))


async def watch_late_change(kai, before: str, what: str, secs: float = 15.0):
    """A click reported 'no visible change', but some things open seconds later. If the screen changes within `secs`
    (and no planner task is driving), prompt Kai to mention it, as a person would when it pops up."""
    t = time.perf_counter()
    while time.perf_counter() - t < secs:
        await asyncio.sleep(0.5)
        try: now = await kai.bc.page.evaluate(_SIG_JS)
        except Exception: return
        if now != before:
            if kai.planner.running: return
            desc = describe_change(before, now, None).replace("Clicked it: ", "")
            kai.slog.event("late_change", after=what, change=desc)
            kai.feed.kick(); await asyncio.sleep(0.6)
            for _ in range(20):
                if getattr(kai.session, "user_state", "") != "speaking" and getattr(kai.session, "agent_state", "") != "speaking": break
                await asyncio.sleep(0.25)
            if floor_busy(kai): return
            kai.session.generate_reply(instructions=f"After '{what}', {desc} just now on screen (it took a few seconds). Mention it "
                                                    "naturally and explain what it shows, using the screen summary.")
            return


async def nudge_if_silent(kai, what: str, secs: float = 3.0):
    """The realtime model sometimes drops the reply after a tool result (a stray VAD blip cancels it) and the call goes
    silent with the new screen unexplained. If nobody has said anything `secs` after an act, prompt Kai to carry on."""
    if len(re.findall(r"[A-Za-z']+", text)) > 4: return   # only bare acks ("okay", "got it"): real questions always get an
    # answer, and nudging one collided with Grok's own reply in progress (first answer 9 s late in faan-livevoice-3e5f4)
    n_agent, n_user = len(kai.feed.agent_lines), kai.feed.user_turns
    await asyncio.sleep(secs)
    for _ in range(10):
        if getattr(kai.session, "agent_state", "") != "speaking" and getattr(kai.session, "user_state", "") != "speaking": break
        await asyncio.sleep(0.3)
    if (len(kai.feed.agent_lines) != n_agent or kai.feed.user_turns != n_user or kai.planner.running
            or getattr(kai.session, "agent_state", "") in ("speaking", "thinking")):
        return
    if floor_busy(kai): return
    kai.slog.event("silence_nudge", after=what[:80])
    kai.session.generate_reply(instructions=f"Your last screen step: {what[:200]} In one or two short sentences, explain what's "
                                            "on screen now, then lead to the next step.")


async def answer_if_ignored(kai, text: str, secs: float = 3.0):
    """Grok sometimes treats a bare "okay" as a backchannel and doesn't answer, so the demo stalls. If the customer's turn
    gets no reply within `secs`, prompt Kai to answer it (for an "okay": carry on to the next part)."""
    if len(re.findall(r"[A-Za-z']+", text)) > 4: return   # only bare acks ("okay", "got it"): real questions always get an
    # answer, and nudging one collided with Grok's own reply in progress (first answer 9 s late in faan-livevoice-3e5f4)
    n_agent, n_user = len(kai.feed.agent_lines), kai.feed.user_turns
    await asyncio.sleep(secs)
    if (len(kai.feed.agent_lines) != n_agent or kai.feed.user_turns != n_user
            or getattr(kai.session, "agent_state", "") in ("speaking", "thinking") or getattr(kai.session, "user_state", "") == "speaking"):
        return
    if floor_busy(kai): return   # the customer is talking to the test agent, not to Kai
    kai.slog.event("unanswered_nudge", text=text[:80])
    kai.session.generate_reply(instructions=f'The customer said "{text[:200]}" and is waiting for you. Answer it; if it was just '
                                            "an acknowledgement, carry on to the next part of the demo in one or two sentences.")


async def missed_turn(kai, n_user: int, secs: float = float(os.getenv("MISSED_TURN_S", 3.5))):
    """Gemini Live's server-side turn detection sometimes never ends a short turn ("Okay."): no transcript, no reply, and the
    customer waits in silence (45 s in faan-livevoice-be498). Our own VAD heard them stop: if Gemini hasn't taken the turn
    `secs` later, ask it to answer."""
    await asyncio.sleep(secs)
    s = kai.session
    if (kai.feed.user_turns != n_user or getattr(s, "agent_state", "") in ("speaking", "thinking")
            or getattr(s, "user_state", "") == "speaking" or kai.planner.running or floor_busy(kai)):
        return
    kai.slog.event("missed_turn_nudge")
    s.generate_reply(instructions="The customer just said something short (probably an acknowledgement like 'okay') and is "
                                  "waiting for you. Answer it; if it was an acknowledgement, carry on to the next part of the demo "
                                  "in one or two sentences.")


class ScreenText:
    """Folds the browser's page text into the agent instructions when the page structure changes (the only screen
    channel an Inference realtime model reads)."""
    HDR = "\n\nWHAT IS ON YOUR SHARED SCREEN RIGHT NOW (page text):\n"

    def __init__(self, bc, slog):
        self.bc, self.slog, self.agent, self._last, self._kick = bc, slog, None, None, asyncio.Event()
        self.task_line = ""
        self.profile_line = ""
        self.vin = None   # ScreenVideoInput (gemini-live)
        self.agent_lines: list[str] = []   # what Kai said, so a task-done reply doesn't repeat it
        self.user_turns = 0
        self.cards = _feature_cards()

    def kick(self):
        self._kick.set()
        if self.vin is not None: self.vin.kick()   # and send Gemini a fresh frame of the result

    def on_screen(self, txt: str) -> str:
        """The knowledge cards for features whose labels are on screen now (max 2), so Kai talks about what's actually shown."""
        low = txt.lower(); hits = []
        for c in self.cards:
            score = sum(1 for l in c["labels"] if len(l) > 3 and l.lower() in low)
            if score: hits.append((score, c))
        hits.sort(key=lambda x: -x[0])
        self.area = hits[0][1]["area"] if hits else None
        return "\n".join(h[1]["card"] for h in hits[:2])

    def storyline(self) -> str:
        """The full storyline of the area on screen (the base prompt only has the first ~900 characters of each), so Kai
        can lead to the next part of it instead of stalling or jumping elsewhere."""
        kb = next((k for k in _load_kbs() if k.get("area") == getattr(self, "area", None)), None)
        if not kb: return ""
        return (f"\n\nFULL STORYLINE OF THE AREA ON SCREEN ({str(kb['area']).replace('_', ' ')}); find where you are and lead to "
                f"the next part that fits what they asked:\n" + re.sub(r"\s+", " ", str(kb.get("demo_instructions", "")))[:3500])

    async def post_context(self, txt: str, cards: str) -> int:
        """Gemini Live: update_instructions re-sends the WHOLE prompt (~33k chars) as a conversation turn on every call (the
        plugin's mid-session instruction update), so a screen change would add ~10k tokens to the context each time. Instead
        the base prompt stays the system instruction and each screen change goes in as one short context item (no reply)."""
        parts, area0 = [], getattr(self, "_posted_area", None)
        if self.profile_line and self.profile_line != getattr(self, "_posted_profile", None):
            parts.append(f"WHAT YOU KNOW ABOUT THEM: {self.profile_line}"); self._posted_profile = self.profile_line
        if self.task_line != getattr(self, "_posted_task", ""):
            parts.append(self.task_line or "No screen task is running now."); self._posted_task = self.task_line
        if cards: parts.append(f"FEATURES ON SCREEN NOW (talk about these specifically):\n{cards}")
        if getattr(self, "area", None) and self.area != area0:
            parts.append(self.storyline().strip()); self._posted_area = self.area
        parts.append(self.HDR.strip() + "\n" + txt)
        body = ("<screen_update>(From the demo system, not the customer. Don't reply to this; use it for what's on your screen now.)\n"
                + "\n\n".join(parts) + "\n</screen_update>")
        ctx = self.agent.chat_ctx.copy(); ctx.add_message(role="user", content=body)
        await self.agent.update_chat_ctx(ctx)
        return len(body)

    async def run(self):
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), 2.0); self._kick.clear(); await asyncio.sleep(0.35)
            except asyncio.TimeoutError:
                pass
            if not self.agent or not self.bc.page: continue
            try:
                txt = await screen_summary(self.bc.page)
                sig = re.sub(r"\d", "", txt) + self.task_line + self.profile_line   # timers/metrics alone don't re-send
                if sig == self._last or txt.startswith("(page text failed"): continue
                self._last = sig
                cards = self.on_screen(txt)
                t = time.perf_counter()
                if GEM and SCREEN_FEED == "context":
                    n = await self.post_context(txt, cards)
                    self.slog.event("screen_text", page=txt.split("\n", 1)[0][:80], feed="context", chars=n, text=txt,
                                    ms=round((time.perf_counter() - t) * 1000, 1), agent_state=getattr(self.agent.session, "agent_state", ""))
                    continue
                await self.agent.update_instructions(PROMPT + (f"\n\nWHAT YOU KNOW ABOUT THEM: {self.profile_line}" if self.profile_line else "")
                                                     + (f"\n\n{self.task_line}" if self.task_line else "")
                                                     + (f"\n\nFEATURES ON SCREEN NOW (talk about these specifically):\n{cards}" if cards else "")
                                                     + self.storyline()
                                                     + self.HDR + txt)
                self.slog.event("screen_text", page=txt.split("\n", 1)[0][:80], feed="instructions", chars=len(PROMPT) + len(txt), text=txt,
                                ms=round((time.perf_counter() - t) * 1000, 1))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("screen text: %s", e)


async def upload_log(slog, room: str):
    """Cloud calls: send this call's step log to the private store behind LOG_URL (the container's disk is gone after the
    call), so it can be reviewed later. Local runs without LOG_URL keep it in sessions/ only."""
    url, secret = os.getenv("LOG_URL"), os.getenv("LOG_SECRET")
    if not (url and secret):
        log.info("call log upload skipped: LOG_URL/LOG_SECRET not set"); return
    try:
        import aiohttp
        data = open(os.path.join(slog.dir, "events.jsonl"), "rb").read()
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{url}?room={room}", data=data, headers={"x-log-secret": secret, "Content-Type": "application/x-ndjson"},
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
                log.info("call log upload %s: %s", room, r.status)
    except Exception as e:
        log.warning("call log upload failed: %s", e)


def stall_watchdog():
    """Inference realtime sometimes never sends response.done (seen with Gemini); cancel a response whose events stop."""
    try:
        from livekit.agents.inference.realtime.openai import RealtimeSession as S
        from livekit.agents.llm._realtime.openai import _ResponseGeneration
        from openai.types.realtime import ResponseCancelEvent
    except Exception as e:
        log.warning("no stall watchdog: %s", e); return
    if getattr(S, "_min_wd", False): return
    S._min_wd = True

    def stamp(name, d=None):
        orig = getattr(S, name)
        def h(self, ev, *a, **k):
            self._wd_t = time.monotonic()
            if name == "_handle_response_created": self._wd_id, self._wd_items = ev.response.id, 0
            if d is not None: self._wd_items = max(0, getattr(self, "_wd_items", 0) + d)
            r = orig(self, ev, *a, **k)
            if not getattr(self, "_wd_task", None): self._wd_task = asyncio.create_task(watch(self))
            return r
        setattr(S, name, h)

    async def watch(self):
        cancelled = None
        while True:
            await asyncio.sleep(0.5)
            g = self._current_generation
            if not isinstance(g, _ResponseGeneration) or g._done_fut.done(): cancelled = None; continue
            idle = time.monotonic() - self._wd_t
            if cancelled == self._wd_id:
                if idle > 1.5: self._close_current_generation()
            elif idle > (2 if g.messages and self._wd_items == 0 else 6):
                log.warning("stalled response %s (%.1fs); cancelling", self._wd_id, idle)
                self.send_event(ResponseCancelEvent(type="response.cancel", response_id=self._wd_id))
                cancelled, self._wd_t = self._wd_id, time.monotonic()

    for n, d in (("_handle_response_created", None), ("_handle_response_output_item_added", +1),
                 ("_handle_response_output_item_done", -1), ("_handle_response_content_part_added", None),
                 ("_handle_response_audio_delta", None)):
        try: stamp(n, d)
        except AttributeError: pass


def grok_session() -> AgentSession:
    kw = {}
    if MODEL.startswith("google/") or MODEL.startswith("openai/"):
        from openai.types.realtime.realtime_audio_input_turn_detection import ServerVad
        kw["turn_detection"] = ServerVad(type="server_vad", silence_duration_ms=700, create_response=True, interrupt_response=True)
    if os.getenv("MIN_RT_VOICE"): kw["voice"] = os.environ["MIN_RT_VOICE"]
    elif MODEL.startswith("openai/"): kw["voice"] = "marin"
    elif MODEL.startswith("xai/"): kw["voice"] = "rex"   # male, to match the avatar (Grok's default "eve" is female)
    return AgentSession(llm=inference.RealtimeModel(model=MODEL, **kw), vad=silero.VAD.load())


def gemini_live():
    from livekit.plugins import google
    from google.genai import types as gt
    vertex = bool(os.getenv("GOOGLE_CLOUD_PROJECT")) and not os.getenv("GOOGLE_API_KEY")
    return google.realtime.RealtimeModel(
        model=MODEL, voice=os.getenv("GEMINI_VOICE", "Puck"),   # male, to match the avatar
        context_window_compression=gt.ContextWindowCompressionConfig(sliding_window=gt.SlidingWindow()),
        realtime_input_config=gt.RealtimeInputConfig(automatic_activity_detection=gt.AutomaticActivityDetection(
            end_of_speech_sensitivity=gt.EndSensitivity.END_SENSITIVITY_LOW,
            start_of_speech_sensitivity=getattr(gt.StartSensitivity, os.getenv("GEMINI_START_SENS", "START_SENSITIVITY_HIGH")), silence_duration_ms=int(os.getenv("GEMINI_SILENCE_MS", 700)))),
        session_resumption=gt.SessionResumptionConfig(),
        vertexai=vertex, **({"project": os.getenv("GOOGLE_CLOUD_PROJECT"), "location": os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")} if vertex else {}))


from livekit.agents.voice import io as agent_io


class ScreenVideoInput(agent_io.VideoInput):
    """The shared browser as Gemini's video input (as in version B): the latest rendered frame at `fps`, plus one ~350 ms
    after every screen step (kick) so it sees the result, not a stale screen. Counts frames sent, for the call log."""
    def __init__(self, last: dict, fps: float = 1.0):
        super().__init__(label="faan-screen"); self._last, self._dt = last, 1.0 / max(fps, 0.1)
        self._kick, self.sent, self.t0 = asyncio.Event(), 0, time.perf_counter()

    def kick(self): self._kick.set()

    async def __anext__(self) -> rtc.VideoFrame:
        try:
            await asyncio.wait_for(self._kick.wait(), self._dt)
            self._kick.clear(); await asyncio.sleep(0.35)   # let the click render first
        except asyncio.TimeoutError:
            pass
        while self._last["f"] is None: await asyncio.sleep(0.2)
        self.sent += 1
        return self._last["f"]

    def stats(self) -> dict:
        dt = time.perf_counter() - self.t0
        return {"frames_to_model": self.sent, "secs": round(dt), "fps": round(self.sent / max(dt, 1), 2)}


def _git_sha() -> str:
    import subprocess
    try: return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=os.path.dirname(os.path.abspath(__file__)),
                               capture_output=True, text=True, timeout=5).stdout.strip() or "unknown"
    except Exception: return "unknown"
BUILD_SHA = os.getenv("BUILD_SHA") or _git_sha()


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8085)), num_idle_processes=1)


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "faan-live-d"))
async def entrypoint(ctx: JobContext):
    t0 = time.perf_counter()
    await ctx.connect()
    slog = SessionLog(ctx.room.name)
    _ev = slog.event
    def _event(kind, **data):
        _ev(kind, **data)
        if kind not in ("agent_state", "user_state", "screen_text"):
            log.info("EV %s %s %s", ctx.room.name, kind, {k: (v[:160] if isinstance(v, str) else v) for k, v in data.items()})
    slog.event = _event
    slog.event("build", sha=BUILD_SHA, tag="lite-gemini", flags={"brain": BRAIN, "model": MODEL, "screen_feed": SCREEN_FEED if GEM else "instructions"})
    src, last = rtc.VideoSource(W, H), {"f": None, "t": 0.0}

    def on_frame(jpeg: bytes, t: float):
        if t - last["t"] < 1 / 24: return
        img = Image.open(io.BytesIO(jpeg)).convert("RGBA")
        if img.size != (W, H): img = img.resize((W, H))
        f = rtc.VideoFrame(W, H, rtc.VideoBufferType.RGBA, img.tobytes())
        src.capture_frame(f); last["f"], last["t"] = f, t
        slog.frame(jpeg)

    bc = BrowserController(on_frame=on_frame); bc.trace = slog.event
    feed = ScreenText(bc, slog)

    async def browser_up():
        await bc.start(START_URL); await bc.settle()
        track = rtc.LocalVideoTrack.create_video_track("screen", src)
        await ctx.room.local_participant.publish_track(track, rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_SCREENSHARE, video_encoding=rtc.VideoEncoding(max_framerate=30, max_bitrate=2_500_000)))
        slog.event("screen_share_published", s=round(time.perf_counter() - t0, 2))
        feed.kick()
        if os.getenv("CLEAN_AT_START", "1") == "1":   # free the project's agent quota: delete agents earlier demos created
            from demo_agent import cleanup
            asyncio.create_task(cleanup.clean(bc.page.context, slog.event))
    browser = asyncio.create_task(browser_up())

    async def keepalive():   # static pages produce no screencast frames
        while True:
            await asyncio.sleep(0.2)
            if last["f"] is not None and time.perf_counter() - last["t"] > 0.2: src.capture_frame(last["f"])
    asyncio.create_task(keepalive())

    if GEM:   # Gemini Live (Google plugin, Vertex + ADC): hears the customer, talks, and watches the shared screen as video
        session = AgentSession(llm=gemini_live(), vad=silero.VAD.load(), video_sampler=None)   # ScreenVideoInput paces the frames
    else:
        stall_watchdog()   # Inference-only patch
        session = grok_session()

    said: list[str] = []


    @session.on("conversation_item_added")
    def _item(ev):
        it = ev.item
        if getattr(it, "role", None) in ("user", "assistant") and getattr(it, "text_content", None):
            if it.role == "user" and it.text_content.startswith("(Note from the demo system"):
                slog.event("say_note", text=it.text_content[:200]); return
            slog.event("user" if it.role == "user" else "agent", text=it.text_content)
            if it.role == "user" and kai.floor is not None: kai.floor.on_customer_line(it.text_content)
            if it.role == "assistant": feed.agent_lines.append(it.text_content)
            else:
                feed.user_turns += 1
                asyncio.create_task(answer_if_ignored(kai, it.text_content))
            if it.role == "user" and len(it.text_content.split()) >= 5:   # substantive: refresh what we know about them
                said.append(it.text_content); asyncio.create_task(update_profile(feed, said, slog))

    @session.on("agent_state_changed")
    def _st(ev): slog.event("agent_state", state=ev.new_state)

    @session.on("user_state_changed")
    def _ust(ev):
        slog.event("user_state", state=ev.new_state)
        if ev.new_state == "speaking": _ust.t = time.perf_counter()
        elif GEM and ev.old_state == "speaking" and time.perf_counter() - getattr(_ust, "t", 0) > 0.25:
            asyncio.create_task(missed_turn(kai, feed.user_turns))

    # avatar (Anam Leo) when the join page picked "With avatar" (participant attribute faan.mode); voice-only otherwise
    from demo_agent.avatar import start_avatar, wait_avatar, supervise
    from livekit.agents import room_io
    mode = os.getenv("FAAN_DEFAULT_MODE", "voice")
    if not ctx.room.name.startswith("faan-livevoice"):
        try:
            cust = await asyncio.wait_for(ctx.wait_for_participant(), 3)
            for _ in range(15):
                if cust.attributes.get("faan.mode"): mode = cust.attributes["faan.mode"]; break
                await asyncio.sleep(0.1)
        except Exception: pass
    slog.event("call_mode", mode=mode)
    av = await start_avatar(session, ctx.room, slog.event) if mode == "avatar" else None

    kai = Kai(bc, slog, feed); feed.agent = kai
    await session.start(agent=kai, room=ctx.room, room_options=room_io.RoomOptions(audio_output=av is None))
    await wait_avatar(av, slog.event)
    avsup = supervise(session, ctx.room, av, slog.event)   # avatar leaves -> Kai keeps talking by voice
    if avsup is not None: ctx.add_shutdown_callback(avsup.aclose)
    vin = None
    if GEM:   # Gemini watches the same browser the customer sees (not the customer's camera)
        session.input.video = vin = ScreenVideoInput(last, float(os.getenv("SCREEN_TO_MODEL_FPS", 1))); feed.vin = vin
    slog.event("session_start", model=MODEL, brain=BRAIN, video_to_model=vin is not None)
    asyncio.create_task(feed.run())
    session.generate_reply(instructions="Greet them as Kai from LiveKit and ask what they are building or working on, in one short sentence, e.g. 'Hi, I'm Kai from LiveKit. What are you building or working on?'")
    slog.event("greeting_sent", s=round(time.perf_counter() - t0, 2))

    def evidence():   # the claim "Gemini sees, Jev clicks", from the call log
        slog.event("evidence", brain=BRAIN, model=MODEL, video=vin.stats() if vin else None, click_choosers=dict(kai.choosers),
                   clicks_chosen_by_brain=0)

    async def finish():
        evidence()
        slog.event("session_end")
        await upload_log(slog, ctx.room.name)   # first: in the cloud the shutdown can be cut off before later steps run
        try:   # never leave a test call (and its compute) running after the demo
            if kai.floor is not None and kai.floor.app_live and await bc.end_test_call(): slog.event("test_call_ended", by="shutdown")
        except Exception: pass
        try: await bc.close()
        except Exception: pass
        slog.close()
    ctx.add_shutdown_callback(finish)

    async def upload_loop():   # keep the stored log current during the call, so a cut-off shutdown loses at most 30 s
        while True:
            await asyncio.sleep(30)
            evidence()
            await upload_log(slog, ctx.room.name)
    asyncio.create_task(upload_loop())
    await browser
    if os.getenv("VOICE_BRIDGE", "1") == "1":
        await voice_bridge(ctx, session, kai, bc, slog)


DEBRIEF_PROMPT = """You are Kai, a LiveKit sales engineer. The customer just test-called the voice agent they built in the Agent
Builder; you listened silently. Write what Kai says now, as ONE or TWO short spoken sentences : start with the given
opener, make one specific comment on how their agent did (something it handled well, or one thing to tune, naming the builder
setting: instructions, welcome message, data collection fields, voice, call ending), then ask what they'd like to change.
Judge it against what they configured during the demo (given below): if they told it to refuse something and it refused,
that is a success to praise, not a weakness. Max 30 words. The customer's last line ("Kai, end the call" or similar) was said to Kai, not to their agent: it is how the call
ended, never something their agent did wrong. Plain text, no quotes, no lists."""


async def compose_debrief(transcript: str, opener: str, configured: list[str] | None = None) -> str:
    from livekit.agents import llm
    c = llm.ChatContext()
    c.add_message(role="system", content=DEBRIEF_PROMPT)
    setup = "\n".join(f"- {x}" for x in (configured or [])[-15:]) or "- (nothing recorded)"
    c.add_message(role="user", content=f"Opener: {opener}\nWhat they configured during the demo:\n{setup}\nTest call transcript:\n{transcript}")
    out = ""
    async for ch in inference.LLM(model=os.getenv("DEBRIEF_MODEL", "openai/gpt-4.1-mini")).chat(chat_ctx=c):
        if ch.delta and ch.delta.content: out += ch.delta.content
    return re.sub(r"\s+", " ", out).strip().strip('"')


async def voice_bridge(ctx: JobContext, session: AgentSession, kai: "Kai", bc: BrowserController, slog: SessionLog):
    """The customer talks to the agent being tested in the shared browser (ported from version B, docs in faan/voicebridge.py):
    customer mic -> page getUserMedia; page audio -> 'demo-app-audio' track; FloorControl mutes Kai after the test agent's
    greeting with one handover line; DemoCallListener transcribes both sides and wakes on "Kai, end the call"."""
    import numpy as np
    from demo_agent.floor import FloorControl, Turns
    from demo_agent.voicebridge import BrowserAudioBridge, RoomAudioRouter
    from demo_agent.demolistener import DemoCallListener
    kai.turns = Turns(session, slog.event)
    floor = FloorControl(session, kai.turns, slog.event)
    vb = BrowserAudioBridge(bc.page, log=slog.event); router = RoomAudioRouter(ctx.room, log=slog.event)
    router.on_mic(vb.push)                                   # customer mic (humans only) -> the app's microphone
    vb.on_out(router.play)                                   # the app's voice -> 'demo-app-audio' track for the customer
    vb.on_state(lambda active, d: floor.on_app_audio(bool(active and d.get("mic", True))))   # app opened a mic: a test call
    floor.on_floor(router.set_active)                        # forward the customer's voice only while the app has the floor
    floor.on_live(kai.planner.on_app_live)                   # "start a test call" is done once it's live
    floor.listener = DemoCallListener(slog.event, on_wake=lambda text: asyncio.create_task(floor.wake(text)))
    floor.end_app_call = bc.end_test_call
    floor.compose = lambda transcript, opener: compose_debrief(transcript, opener, kai.changes)
    app_voice = {"t": 0.0}
    def _app_level(pcm: bytes):   # the demoed agent is talking (energy on its audio): FloorControl waits out its greeting
        a = np.frombuffer(pcm, dtype=np.int16)
        if a.size and int(np.abs(a).max()) > 1200: app_voice["t"] = time.time()
    vb.on_out(_app_level)
    floor.app_speaking = lambda: time.time() - app_voice["t"] < 0.35
    router.on_mic(floor.listener.push_customer); vb.on_out(floor.listener.push_app)
    await vb.install(); await router.start()
    kai.floor = floor
    lp = ctx.room.local_participant
    floor.publish = lambda st: asyncio.create_task(lp.set_attributes({"faan.floor": st}))

    async def stats():   # while a test call is live: is the customer's audio reaching the page's microphone?
        last = 0
        while True:
            await asyncio.sleep(5)
            if not floor.app_live: continue
            peaks = []
            for fr in bc.page.frames:   # the page mic's peak level (0..1) since the last check, per frame that opened it
                try:
                    p = await fr.evaluate("() => window.__vbMicPeak ? window.__vbMicPeak() : null")
                    if p is not None: peaks.append(round(p, 3))
                except Exception: pass
            try: ctx_state = await bc.page.evaluate("() => window.__vbCtxState ? window.__vbCtxState() : 'none'")
            except Exception: ctx_state = "?"
            slog.event("vb_in_stats", pushed=vb.pushed - last, router_in=router.active, audio_ctx=ctx_state, floor=floor.state, mic_peak=peaks)
            last = vb.pushed
    st = asyncio.create_task(stats())

    async def stop_bridge():
        st.cancel()
        await router.stop(); await vb.stop()
    ctx.add_shutdown_callback(stop_bridge)


if __name__ == "__main__":
    from livekit.agents import cli
    logging.basicConfig(level=logging.INFO)
    cli.run_app(server)
