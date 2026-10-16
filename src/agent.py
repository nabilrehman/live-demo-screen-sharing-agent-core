"""Kai, a voice sales engineer who gives a live demo of a web product in a shared browser.

The realtime model (demo_agent/brain.py) hears the customer, talks, and calls tools: act() for one step on screen,
do_task() for several (the planner), end_test_call(). Jev picks every element that gets clicked (demo_agent/hands.py).
This file is the LiveKit worker: it wires the browser, the screen share, the session, the avatar and the voice bridge.

  BRAIN       gemini-live (default) | grok        AGENT_NAME, WORKER_PORT: worker registration
  DEMO_START_URL (or TOUR_START_URL): the page the demo opens on
  KNOWLEDGE_DIR (default knowledge/): the folder with the product's knowledge files
"""

import asyncio
import difflib
import io
import logging
import os
import re
import subprocess
import time

from dotenv import load_dotenv

# before demo_agent reads env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))

import numpy as np
from livekit import rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, cli, function_tool, room_io
from PIL import Image

from demo_agent import cleanup
from demo_agent.avatar import start_avatar, supervise, wait_avatar
from demo_agent.brain import BRAIN, IS_GEMINI, MODEL, ScreenVideoInput, make_session
from demo_agent.browser import BrowserController, H, W
from demo_agent.demolistener import DemoCallListener
from demo_agent.engines import JevEngine
from demo_agent.floor import FloorControl, Turns
from demo_agent.hands import agent_slug, fast_hands, parse_typing
from demo_agent.nudges import answer_if_ignored, missed_turn, watch_late_change
from demo_agent.planner import Planner
from demo_agent.prompts import PRODUCT, PROMPT, compose_debrief, update_profile
from demo_agent.screen import TOP_LAYER, ScreenText, no_effect, no_effect_reason, quiet_network, screen_summary
from demo_agent.sesslog import SessionLog, upload_log
from demo_agent.voicebridge import BrowserAudioBridge, RoomAudioRouter

log = logging.getLogger("agent")
START_URL = os.environ.get("DEMO_START_URL") or os.environ["TOUR_START_URL"]
ACT_RUN_MAX = int(os.getenv("ACT_RUN_MAX", 3))  # act calls in a row with nothing said in between


class Kai(Agent):
    def __init__(self, bc: BrowserController, slog: SessionLog, feed: ScreenText):
        super().__init__(instructions=PROMPT)
        self.bc, self.slog, self.feed, self.jev = bc, slog, feed, JevEngine()
        self.lock = asyncio.Lock()
        self.planner = Planner(self)
        # what was configured during the demo (typed fields, selected options), for the debrief
        self.changes: list[str] = []
        self.floor = None  # FloorControl, once the voice bridge is up
        self.turns = None  # Turns: holds Kai's own replies while a test call has the floor
        self.chooser, self.choosers = "none", {}  # which component chose each click (for the evidence event)
        self.last_change, self.typed_note, self.late_before = "", "", None  # set by the hands
        self.act_run, self.act_mark, self.last_act = 0, None, None

    def _floor_guard(self) -> str | None:
        if self.floor is not None and self.floor.busy:
            self.slog.event("floor_guard", state=self.floor.state)
            return (
                "A test call is live on screen and the customer is talking to their agent. Don't change the screen; stay quiet. "
                "Only end_test_call is allowed."
            )
        return None

    async def do_step(self, goal: str) -> tuple[bool, str, str]:
        """One step on screen. Returns (ok, what happened, screen summary)."""
        async with self.lock:
            t = time.perf_counter()
            ok, err, how = False, "", "jev"
            self.chooser = "none"
            try:
                how = await fast_hands(self, goal)
                ok = how is not None
            except Exception as e:
                log.warning("fast hands: %s", e)
                how = None
            if not ok and parse_typing(goal):  # a typing step whose field isn't there: report it, never type elsewhere
                how, err = "none", f"couldn't find the '{parse_typing(goal)[1]}' field on screen"
            elif not ok and await self.bc.page.locator(TOP_LAYER).count():
                how, err = "none", "couldn't find that in the open dialog/menu"
            elif not ok:  # nothing fitted: Jev runs the step on its own (a few decisions)
                how = "jev"
                self.chooser = "jev-agent"
                try:
                    r = await asyncio.wait_for(self.jev.run_goal(goal, self.bc, max_steps=6), 25)
                    ok, err = r.done, r.error
                except Exception as e:
                    ok, err = False, f"{type(e).__name__}: {e}"[:160]
            txt = await screen_summary(self.bc.page)
            if ok and "a new page opened" in self.last_change:
                # a new page fills in its data a moment later: report the screen once its requests are done
                t1 = time.perf_counter()
                await quiet_network(self.bc.page)
                txt = await screen_summary(self.bc.page)
                self.slog.event("settle", s=round(time.perf_counter() - t1, 2))
            if how == "jev-click":
                change = self.last_change
            elif ok and str(how).startswith(("type", "jev-type")):
                change = f"Typed it{self.typed_note}."
            elif how == "already-there":
                change = "Nothing clicked: that already looks done/open on screen."
            else:
                change = ""
            self.last_change = ""
            if not ok and self.chooser.startswith("jev:"):
                self.chooser = "none"  # nothing was clicked
            self.slog.event(
                "act_done",
                goal=goal,
                ok=ok,
                how=how,
                chooser=self.chooser,
                brain=BRAIN,
                s=round(time.perf_counter() - t, 2),
                error=err,
                change=change,
            )
            self.choosers[self.chooser] = self.choosers.get(self.chooser, 0) + 1
            self.feed.kick()
            return ok, ((change or "Done.") if ok else f"Didn't fully work ({err or 'not reached'})."), txt

    @function_tool
    async def act(self, ctx: RunContext, goal: str) -> str:
        """Do ONE simple thing on the shared screen, described in plain words (examples: "open Settings", "click the
        Details tab", "type Acme Dental into the name field"). For anything with several steps, use do_task.
        Returns what happened and what the screen shows now."""
        if g := self._floor_guard():
            return g
        if self.planner.running:
            return f"A task is running ({self.planner.status}). Don't click yourself; talk about what's happening, or call stop_task."
        mark = (len(self.feed.agent_lines), self.feed.user_turns)  # count clicks in a row with nothing said in between
        self.act_run = self.act_run + 1 if mark == self.act_mark else 1
        self.act_mark = mark
        if self.act_run > ACT_RUN_MAX:
            self.slog.event("act_run_guard", goal=goal, run=self.act_run)
            return (
                f"Not done: you've made {self.act_run - 1} clicks in a row without saying anything, and the customer is waiting "
                "in silence. First tell them, in one sentence, what's on screen now. If you still need several steps, use "
                "do_task with the destination instead of clicking one by one."
            )
        self.slog.event("act", goal=goal)
        self.late_before = None
        _ok, what, txt = await self.do_step(goal)
        key = (re.sub(r"\W+", " ", goal.lower())[:60], what)
        if key == self.last_act and no_effect(what):
            return (
                no_effect_reason(what, txt)
                + " Don't try again; explain it from the screen summary instead.\nSCREEN NOW:\n"
                + txt
            )
        self.last_act = key
        if self.late_before:
            asyncio.create_task(watch_late_change(self, self.late_before, goal))
        return what + " Trust this result; don't redo a step that worked.\nSCREEN NOW:\n" + txt

    @function_tool
    async def do_task(self, ctx: RunContext, request: str) -> str:
        """Hand a multi-step task on the screen to your assistant, who does it step by step while you keep talking
        (examples: "create an item from the Receptionist template named acme-front-desk", "add a tool and cancel it",
        "start a test call"). Put every detail in the request (template, name, values). Returns at once; you'll get an update when it's done or stuck."""
        if g := self._floor_guard():
            return g
        if self.planner.running:  # never drop it: it starts when the current task is done
            self.planner.queued = request
            self.slog.event("task_queued", request=request)
            return (
                f"Queued: your assistant starts it as soon as the current task ({self.planner.status}) is done. Say that in a "
                "few words; don't call do_task again."
            )
        # a new item's name gets a random 3-digit suffix (names of earlier, even deleted, items can't be reused)
        if PRODUCT.get("unique_names"):
            request = re.sub(
                r"\b(named|called)\s+['\"]?([A-Za-z0-9][\w-]*)['\"]?",
                lambda m: f"{m.group(1)} {agent_slug(re.sub(r'-?\d{1,3}$', '', m.group(2)))}",
                request,
                count=1,
            )
        self.planner.start(request)
        return "Started. Say one sentence about why this fits them while it runs; don't click anything yourself."

    @function_tool
    async def stop_task(self, ctx: RunContext) -> str:
        """Stop the running screen task (the customer changed direction or asked you to stop)."""
        return await self.planner.stop()

    @function_tool
    async def end_test_call(self, ctx: RunContext) -> str:
        """Hang up the in-browser test call on screen."""
        ok = await self.bc.end_test_call()
        self.slog.event("test_call_ended", by="tool", ok=ok)
        return "The test call is ended." if ok else "No test call was running."


def _git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


BUILD_SHA = os.getenv("BUILD_SHA") or _git_sha()
server = AgentServer(port=int(os.getenv("WORKER_PORT", 8085)), num_idle_processes=1)


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-lean"))
async def entrypoint(ctx: JobContext):
    t0 = time.perf_counter()
    await ctx.connect()
    slog = _session_log(ctx.room.name)
    slog.event(
        "build",
        sha=BUILD_SHA,
        flags={"brain": BRAIN, "model": MODEL, "screen_feed": "context" if IS_GEMINI else "instructions"},
    )

    # the browser's screencast -> the screen-share track (and the last frame, for Gemini's video input)
    src, last = rtc.VideoSource(W, H), {"f": None, "t": 0.0}

    def on_frame(jpeg: bytes, t: float):
        if t - last["t"] < 1 / 24:
            return
        img = Image.open(io.BytesIO(jpeg)).convert("RGBA")
        if img.size != (W, H):
            img = img.resize((W, H))
        f = rtc.VideoFrame(W, H, rtc.VideoBufferType.RGBA, img.tobytes())
        src.capture_frame(f)
        last["f"], last["t"] = f, t
        slog.frame(jpeg)

    bc = BrowserController(on_frame=on_frame)
    bc.trace = slog.event
    feed = ScreenText(bc, slog)

    async def browser_up():
        await bc.start(START_URL)
        await bc.settle()
        track = rtc.LocalVideoTrack.create_video_track("screen", src)
        await ctx.room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(
                source=rtc.TrackSource.SOURCE_SCREENSHARE,
                video_encoding=rtc.VideoEncoding(max_framerate=30, max_bitrate=2_500_000),
            ),
        )
        slog.event("screen_share_published", s=round(time.perf_counter() - t0, 2))
        feed.kick()
        # free the project's agent quota: delete agents earlier demos created
        if os.getenv("CLEAN_AT_START", "1") == "1":
            asyncio.create_task(cleanup.clean(bc.page.context, slog.event))

    browser = asyncio.create_task(browser_up())

    async def keepalive():  # a static page produces no screencast frames: repeat the last one
        while True:
            await asyncio.sleep(0.2)
            if last["f"] is not None and time.perf_counter() - last["t"] > 0.2:
                src.capture_frame(last["f"])

    asyncio.create_task(keepalive())

    session = make_session()
    kai: Kai | None = None  # created below; the handlers only fire once the session has started
    said: list[str] = []  # the customer's substantive lines, for the profile
    user_spoke_at = [0.0]

    @session.on("conversation_item_added")
    def _item(ev):
        it = ev.item
        if getattr(it, "role", None) not in ("user", "assistant") or not getattr(it, "text_content", None):
            return
        text = it.text_content
        if it.role == "user" and text.startswith("(Note from the demo system"):  # our own notes, not the customer
            slog.event("say_note", text=text[:200])
            return
        if it.role == "user" and is_echo(text, feed.agent_lines):
            # Gemini Live sometimes transcribes a short reply ("Okay.") as one of Kai's own lines, even an old one.
            # The customer didn't say it: keep it out of the profile, the nudges and the turn count.
            slog.event("user_transcript_echo", text=text[:200])
            return
        slog.event("user" if it.role == "user" else "agent", text=text)
        if it.role == "assistant":
            feed.agent_lines.append(text)
            return
        if kai.floor is not None:
            kai.floor.on_customer_line(text)
        feed.user_turns += 1
        asyncio.create_task(answer_if_ignored(kai, text))
        if len(text.split()) >= 5:
            said.append(text)
            asyncio.create_task(update_profile(feed, said, slog))

    @session.on("agent_state_changed")
    def _agent_state(ev):
        slog.event("agent_state", state=ev.new_state)

    @session.on("user_state_changed")
    def _user_state(ev):
        slog.event("user_state", state=ev.new_state)
        if ev.new_state == "speaking":
            user_spoke_at[0] = time.perf_counter()
        elif IS_GEMINI and ev.old_state == "speaking" and time.perf_counter() - user_spoke_at[0] > 0.25:
            asyncio.create_task(missed_turn(kai, feed.user_turns))

    # voice or avatar: the join page sets the customer's 'faan.mode' attribute (test rooms are voice-only)
    mode = os.getenv("FAAN_DEFAULT_MODE", "voice")
    if not ctx.room.name.startswith("faan-livevoice"):
        try:
            cust = await asyncio.wait_for(ctx.wait_for_participant(), 3)
            for _ in range(15):
                if cust.attributes.get("faan.mode"):
                    mode = cust.attributes["faan.mode"]
                    break
                await asyncio.sleep(0.1)
        except Exception:
            pass
    slog.event("call_mode", mode=mode)
    # before session.start: it owns the audio
    av = await start_avatar(session, ctx.room, slog.event) if mode == "avatar" else None

    kai = Kai(bc, slog, feed)
    feed.agent = kai
    await session.start(agent=kai, room=ctx.room, room_options=room_io.RoomOptions(audio_output=av is None))
    await wait_avatar(av, slog.event)
    avsup = supervise(session, ctx.room, av, slog.event)  # the avatar leaves -> Kai keeps talking by voice
    if avsup is not None:
        ctx.add_shutdown_callback(avsup.aclose)
    vin = None
    if IS_GEMINI:  # Gemini watches the shared browser (not the customer's camera)
        session.input.video = vin = ScreenVideoInput(last, float(os.getenv("SCREEN_TO_MODEL_FPS", 1)))
        feed.vin = vin
    slog.event("session_start", model=MODEL, brain=BRAIN, video_to_model=vin is not None)
    asyncio.create_task(feed.run())
    session.generate_reply(instructions=PRODUCT["greeting"])
    slog.event("greeting_sent", s=round(time.perf_counter() - t0, 2))

    def evidence():  # "Gemini sees, Jev clicks", from the call itself
        slog.event(
            "evidence",
            brain=BRAIN,
            model=MODEL,
            video=vin.stats() if vin else None,
            click_choosers=dict(kai.choosers),
            clicks_chosen_by_brain=0,
        )

    async def finish():
        evidence()
        slog.event("session_end")
        await upload_log(slog, ctx.room.name)  # first, in case the shutdown is cut short
        try:  # never leave a test call running after the demo
            if kai.floor is not None and kai.floor.app_live and await bc.end_test_call():
                slog.event("test_call_ended", by="shutdown")
        except Exception:
            pass
        try:
            await bc.close()
        except Exception:
            pass
        slog.close()

    ctx.add_shutdown_callback(finish)

    async def upload_loop():  # keep the stored log current during the call
        while True:
            await asyncio.sleep(30)
            evidence()
            await upload_log(slog, ctx.room.name)

    asyncio.create_task(upload_loop())
    await browser
    if os.getenv("VOICE_BRIDGE", "1") == "1":
        await voice_bridge(ctx, session, kai, bc, slog)


def is_echo(text: str, agent_lines: list[str]) -> bool:
    """A customer line that is nearly the same as something Kai said."""
    low = text.lower()
    return any(difflib.SequenceMatcher(None, low, a.lower()).ratio() > 0.8 for a in agent_lines)


def _session_log(room: str) -> SessionLog:
    """The call's SessionLog; its events also go to the worker log (except the frequent state and screen ones)."""
    slog = SessionLog(room)
    write = slog.event

    def event(kind, **data):
        write(kind, **data)
        if kind not in ("agent_state", "user_state", "screen_text"):
            log.info("EV %s %s %s", room, kind, {k: (v[:160] if isinstance(v, str) else v) for k, v in data.items()})

    slog.event = event
    return slog


async def voice_bridge(ctx: JobContext, session: AgentSession, kai: Kai, bc: BrowserController, slog: SessionLog):
    """Let the customer talk to the agent being tested in the shared browser.

    customer mic -> the page's getUserMedia; the page's audio -> the 'demo-app-audio' track. FloorControl mutes Kai after
    the test agent's greeting (one handover line); DemoCallListener transcribes both sides and wakes on "Kai, end the call".
    """
    kai.turns = Turns(session, slog.event)
    floor = FloorControl(session, kai.turns, slog.event)
    vb = BrowserAudioBridge(bc.page, log=slog.event)
    router = RoomAudioRouter(ctx.room, log=slog.event)
    router.on_mic(vb.push)  # customer mic (humans only) -> the app's microphone
    vb.on_out(router.play)  # the app's voice -> 'demo-app-audio' track for the customer
    # the app opened a mic: a test call
    vb.on_state(lambda active, d: floor.on_app_audio(bool(active and d.get("mic", True))))
    floor.on_floor(router.set_active)  # forward the customer's voice only while the app has the floor
    floor.on_live(kai.planner.on_app_live)  # "start a test call" is done once it's live
    floor.listener = DemoCallListener(slog.event, on_wake=lambda text: asyncio.create_task(floor.wake(text)))
    floor.end_app_call = bc.end_test_call
    floor.compose = lambda transcript, opener: compose_debrief(transcript, opener, kai.changes)

    app_voice_at = [0.0]

    def app_level(pcm: bytes):  # energy on the app's audio: its agent is talking (FloorControl waits out the greeting)
        a = np.frombuffer(pcm, dtype=np.int16)
        if a.size and int(np.abs(a).max()) > 1200:
            app_voice_at[0] = time.time()

    vb.on_out(app_level)
    floor.app_speaking = lambda: time.time() - app_voice_at[0] < 0.35
    router.on_mic(floor.listener.push_customer)
    vb.on_out(floor.listener.push_app)
    await vb.install()
    await router.start()
    kai.floor = floor
    lp = ctx.room.local_participant
    floor.publish = lambda st: asyncio.create_task(lp.set_attributes({"faan.floor": st}))

    async def stats():  # while a test call is live: is the customer's audio reaching the page's microphone?
        last = 0
        while True:
            await asyncio.sleep(5)
            if not floor.app_live:
                continue
            peaks = []
            for fr in bc.page.frames:  # the page mic's peak level (0..1) since the last check, per frame that opened it
                try:
                    p = await fr.evaluate("() => window.__vbMicPeak ? window.__vbMicPeak() : null")
                    if p is not None:
                        peaks.append(round(p, 3))
                except Exception:
                    pass
            try:
                ctx_state = await bc.page.evaluate("() => window.__vbCtxState ? window.__vbCtxState() : 'none'")
            except Exception:
                ctx_state = "?"
            slog.event(
                "vb_in_stats",
                pushed=vb.pushed - last,
                router_in=router.active,
                audio_ctx=ctx_state,
                floor=floor.state,
                mic_peak=peaks,
            )
            last = vb.pushed

    st = asyncio.create_task(stats())

    async def stop_bridge():
        st.cancel()
        await router.stop()
        await vb.stop()

    ctx.add_shutdown_callback(stop_bridge)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli.run_app(server)
