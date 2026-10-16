"""Self-prompted replies for moments a realtime model can leave silent. Each one checks that nobody is talking, no task is
running and no test call has the floor before it asks Kai to speak."""

import asyncio
import os
import re
import time

from demo_agent.screen import SIGNATURE_JS, describe_change

MISSED_TURN_S = float(os.getenv("MISSED_TURN_S", 3.5))


def floor_busy(kai) -> bool:
    """A test call has the floor: Kai is muted and must stay silent."""
    return kai.floor is not None and bool(kai.floor.busy)


def _talking(session) -> bool:
    return getattr(session, "user_state", "") == "speaking" or getattr(session, "agent_state", "") == "speaking"


async def watch_late_change(kai, before: str, what: str, secs: float = 15.0):
    """A click showed no change, but some things open seconds later. If the screen changes within `secs` (and no task is
    driving), have Kai mention it."""
    t = time.perf_counter()
    while time.perf_counter() - t < secs:
        await asyncio.sleep(0.5)
        try:
            now = await kai.bc.page.evaluate(SIGNATURE_JS)
        except Exception:
            return
        if now != before:
            if kai.planner.running:
                return
            desc = describe_change(before, now, None).replace("Clicked it: ", "")
            kai.slog.event("late_change", after=what, change=desc)
            kai.feed.kick()
            await asyncio.sleep(0.6)
            for _ in range(20):
                if not _talking(kai.session):
                    break
                await asyncio.sleep(0.25)
            if floor_busy(kai):
                return
            kai.session.generate_reply(
                instructions=f"After '{what}', {desc} just now on screen (it took a few seconds). Mention it "
                "naturally and explain what it shows, using the screen summary."
            )
            return


async def answer_if_ignored(kai, text: str, secs: float = 3.0):
    """A bare acknowledgement ("okay", "got it") can be taken as a backchannel and get no reply. If it gets none within
    `secs`, have Kai answer (for an acknowledgement: carry on with the demo). Longer turns always get an answer."""
    if len(re.findall(r"[A-Za-z']+", text)) > 4:
        return
    n_agent, n_user = len(kai.feed.agent_lines), kai.feed.user_turns
    await asyncio.sleep(secs)
    if (
        len(kai.feed.agent_lines) != n_agent
        or kai.feed.user_turns != n_user
        or getattr(kai.session, "agent_state", "") in ("speaking", "thinking")
        or getattr(kai.session, "user_state", "") == "speaking"
    ):
        return
    if floor_busy(kai):
        return
    kai.slog.event("unanswered_nudge", text=text[:80])
    kai.session.generate_reply(
        instructions=f'The customer said "{text[:200]}" and is waiting for you. Answer it; if it was just '
        "an acknowledgement, carry on to the next part of the demo in one or two sentences."
    )


async def missed_turn(kai, n_user: int, secs: float = MISSED_TURN_S):
    """Gemini Live's turn detection can miss the end of a short turn ("Okay."): no transcript, no reply. Our VAD heard
    the customer stop; if Gemini hasn't taken the turn `secs` later, ask it to answer."""
    await asyncio.sleep(secs)
    s = kai.session
    if (
        kai.feed.user_turns != n_user
        or getattr(s, "agent_state", "") in ("speaking", "thinking")
        or getattr(s, "user_state", "") == "speaking"
        or kai.planner.running
        or floor_busy(kai)
    ):
        return
    kai.slog.event("missed_turn_nudge")
    s.generate_reply(
        instructions="The customer just said something short (probably an acknowledgement like 'okay') and is "
        "waiting for you. Answer it; if it was an acknowledgement, carry on to the next part of the demo "
        "in one or two sentences."
    )
