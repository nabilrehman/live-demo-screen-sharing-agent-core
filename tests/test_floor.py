"""Tests for demo_agent/floor.py (FloorControl + Turns) and the DemoCallListener wake phrases. No room, no browser.

uv run pytest tests/test_floor.py
"""

import asyncio
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
os.environ.setdefault("FLOOR_AUTO_HANDOVER", "1")
from livekit.agents.llm import ChatContext

from demo_agent.demolistener import BACK, HI_END, NAMES, WAKE
from demo_agent.floor import NOTE, FloorControl, Turns

results = []


def check(name, ok, info=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}")


class FakeInput:
    def __init__(self):
        self.enabled = True

    def set_audio_enabled(self, e):
        self.enabled = e


class FakeAgent:
    def __init__(self):
        self.chat_ctx = ChatContext()

    async def update_chat_ctx(self, ctx):
        self.chat_ctx = ctx


class FakeSession:
    def __init__(self):
        self.input, self.agent_state, self.user_state = FakeInput(), "listening", "listening"
        self.replies, self.interrupts, self.cleared = [], 0, 0
        self.current_agent = FakeAgent()

    def generate_reply(self, instructions="", user_input=None):
        self.replies.append(instructions + (" | " + user_input if user_input else ""))

        async def speak():  # the model talks ~1 s
            await asyncio.sleep(0.2)
            self.agent_state = "speaking"
            await asyncio.sleep(1.0)
            self.agent_state = "listening"

        asyncio.create_task(speak())

    def interrupt(self):
        self.interrupts += 1
        self.agent_state = "listening"

    def clear_user_turn(self):
        self.cleared += 1


class FakeListener:
    def __init__(self):
        self.started = self.stopped = 0
        self.lines = []
        self.active = False

    def start(self):
        if not self.active:
            self.started += 1
            self.active = True

    async def stop(self):
        if self.active:
            self.stopped += 1
            self.active = False

    def transcript(self):
        return "Customer: Hi, I'd like to book a cleaning.\nTheir agent: Sure, what day works?"


def wakes(lines):
    """The listener's wake logic over a list of customer finals (split finals joined like _read does)."""
    recent = " ".join(lines)
    return bool(
        WAKE.search(recent)
        or HI_END.search(recent)
        or (BACK.search(recent) and re.search(rf"\b{NAMES}\b", recent, re.I))
    )


async def main():
    ev = []

    def trace(kind, **d):
        return ev.append((time.perf_counter(), kind, d))  # same signature as SessionLog.event

    s = FakeSession()
    tm = Turns(s, trace)
    fc = FloorControl(s, tm, trace)
    li = FakeListener()
    fc.listener = li
    ended = []

    async def end_call():
        ended.append(time.perf_counter())
        return True

    fc.end_app_call = end_call
    seen = {}

    async def compose(transcript, opener):
        seen["t"] = transcript
        return f"{opener} It handled the cleaning request well. What would you like to change?"

    fc.compose = compose
    live_cb = []
    fc.on_live(lambda: live_cb.append(1))
    routed = []
    fc.on_floor(routed.append)
    greeting = {"until": 0.0}
    fc.app_speaking = lambda: time.perf_counter() < greeting["until"]

    # Kai is mid-sentence when the test call connects
    s.agent_state = "speaking"
    tm.request("task", "planner finished")
    t_live = time.perf_counter()
    greeting["until"] = t_live + 2.5  # the test agent greets for 2.5 s
    fc.on_app_audio(True)
    check("live: floor OFFERED, tools blocked", fc.state == fc.OFFERED and fc.busy)
    check("live: Kai interrupted", s.interrupts == 1)
    check("live: Kai muted right away (auto handover)", s.input.enabled is False)
    check("live: pending intents cleared, turns held", tm.held and not tm.intents)
    check("live: on_live callback (planner finishes)", live_cb == [1])
    await asyncio.sleep(1.5)
    check("greeting: no handover while the test agent talks", fc.state == fc.OFFERED and not s.replies)
    for _ in range(80):
        if fc.state == fc.DEMO_APP:
            break
        await asyncio.sleep(0.1)
    t_hand = time.perf_counter()
    check(
        "handover after greeting + ~1.2 s quiet",
        fc.state == fc.DEMO_APP and 3.5 < t_hand - t_live < 5.5,
        f"{t_hand - t_live:.1f}s",
    )
    check(
        "handover: one line, mentions muting and 'Kai'",
        len(s.replies) == 1 and "mute myself" in s.replies[0] and "Kai" in s.replies[0],
    )
    check("handover: router forwards customer mic", routed[-1] is True)
    check("listener started when the call went live (hears the greeting)", li.started == 1 and li.active)
    await asyncio.sleep(2.0)
    check("test call: Kai stays muted and silent", s.input.enabled is False and len(s.replies) == 1)
    tm.request("task", "something late")  # anything that wants Kai to speak during the call waits
    await asyncio.sleep(0.5)
    check("test call: Turns held, nothing spoken", len(s.replies) == 1)

    # "Kai, end the call"
    t_wake = time.perf_counter()
    await fc.wake("Kai, end the call")
    check("wake: test call hung up", len(ended) == 1)
    check("wake: floor back to Kai, unmuted", fc.state == fc.KAI and s.input.enabled is True and routed[-1] is False)
    check("wake: listener stopped", li.stopped == 1)
    for _ in range(30):
        if len(s.replies) >= 2:
            break
        await asyncio.sleep(0.1)
    debrief = s.replies[1] if len(s.replies) > 1 else ""
    check(
        "debrief spoken with the transcript",
        "book a cleaning" in seen.get("t", "") and "word for word" in debrief and "I've hung up. It handled" in debrief,
        f"{time.perf_counter() - t_wake:.1f}s after wake",
    )
    notes = [m.text_content for m in s.current_agent.chat_ctx.messages() if (m.text_content or "").startswith(NOTE)]
    check(
        "transcript of the test call added to Kai's context as a note",
        len(notes) == 1 and "book a cleaning" in notes[0],
    )
    fc.on_app_audio(False)
    await asyncio.sleep(2.0)
    check("call-ended edge after wake: no second debrief", fc.state == fc.KAI and len(s.replies) == 2)

    async def broken(transcript, opener):
        raise RuntimeError("llm down")

    fc.compose = broken
    # the test call ends by itself (the test agent hangs up): fallback line if the debrief writer fails
    fc.on_app_audio(True)
    greeting["until"] = 0
    for _ in range(100):
        if fc.state == fc.DEMO_APP:
            break
        await asyncio.sleep(0.1)
    n = len(s.replies)
    fc.on_app_audio(False)
    await asyncio.sleep(3.0)
    check(
        "app hangs up: floor back to Kai after debounce, fallback debrief",
        fc.state == fc.KAI and s.input.enabled and len(s.replies) == n + 1 and "that call has ended" in s.replies[-1],
    )

    # a call that ends during the greeting wait unmutes Kai
    fc.on_app_audio(True)
    greeting["until"] = time.perf_counter() + 5
    await asyncio.sleep(0.3)
    fc.on_app_audio(False)
    await asyncio.sleep(2.0)
    check("call drops during greeting: Kai unmuted, floor KAI", fc.state == fc.KAI and s.input.enabled and not tm.held)

    # wake phrases (STT splits finals)
    for lines, want in (
        (["Kai, end the call."], True),
        (["Alright, Kai.", "Can you please end the call?"], True),
        (["Okay Kai, I'm done."], True),
        (["Kai.", "And", "the call."], True),
        (["Hi, end the call."], True),
        (["Hi there, and the call center is closed?"], False),
        (["Hi, I'd like to book a cleaning."], False),
        (["Kai, back to you."], True),
        (["Guy, stop the call"], True),
        (["Hi, I'd like to book a cleaning for next Tuesday."], False),
        (["Can you end the call?"], False),
        (["Thanks, that's all for the appointment."], False),
    ):
        check(f"wake phrase {lines!r} -> {want}", wakes(lines) == want)

    print(f"\n{sum(results)}/{len(results)} passed -> {'PASS' if all(results) else 'FAIL'}")
    return all(results)


async def test_floor():
    results.clear()
    assert await main()


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
