"""The planner: does a multi-step screen task in the background while the voice keeps talking.

Each turn a text model reads the task, the steps so far (with what each one did) and the screen summary, and picks one
next step (the hands do it) or finishes. Progress shows in the voice model's screen feed as one status line; the outcome
comes back as one spoken reply.
"""

import asyncio
import json
import logging
import os
import time

from livekit.agents import function_tool, inference, llm

from demo_agent.prompts import PLANNER_MODEL, PLANNER_PROMPT
from demo_agent.screen import no_effect, no_effect_reason, screen_summary

log = logging.getLogger("agent.planner")

PLANNER_FALLBACK_MODEL = "google/gemini-3-flash"
# more than the voice gets: buttons further down count
PLANNER_SCREEN_CHARS = int(os.getenv("PLANNER_SCREEN_CHARS", 5000))


@function_tool
async def click_step(goal: str) -> str:
    """Do ONE step on screen: a single click, choice, or typing into one field ("type <text> into the <field> field")."""
    return ""


@function_tool
async def finish(outcome: str, done: bool) -> str:
    """The task is complete (done=true) or can't be completed (done=false). outcome: one sentence for the customer."""
    return ""


class Planner:
    MAX_STEPS = 12

    def __init__(self, kai):
        self.kai, self.task, self.status, self.history = kai, None, "", []
        self.request, self.pages, self.said_from = "", [], 0
        self.queued = None  # a task asked for while another ran: starts right after it

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, request: str):
        self.kai.feed.task_line = ""
        self.request, self.history, self.status, self.pages = request, [], "starting", []
        self.said_from = len(self.kai.feed.agent_lines)
        self.task = asyncio.create_task(self._run())

    def on_app_live(self):
        """The test call went live: a 'start a test call' task ends here, silently (FloorControl speaks next)."""
        self.queued = None
        if not self.running:
            return
        self.task.cancel()
        self._set("")
        self.kai.slog.event(
            "task_done",
            request=self.request,
            done=True,
            outcome="The test call is live.",
            steps=len(self.history),
            why="test call live",
        )

    async def stop(self) -> str:
        self.queued = None
        if not self.running:
            return "Nothing is running."
        self.task.cancel()
        self.status = ""
        self.kai.feed.task_line = ""
        self.kai.feed.kick()
        self.kai.slog.event("task_stopped", request=self.request)
        return "Stopped. The screen stays where it is."

    def _set(self, status: str):
        self.status = status
        self.kai.feed.task_line = (
            f"TASK RUNNING (your assistant is doing it; don't click): {self.request} | now: {status}" if status else ""
        )
        self.kai.feed.kick()

    async def _decide(self, screen: str):
        c = llm.ChatContext()
        c.add_message(role="system", content=PLANNER_PROMPT)
        steps = "\n".join(f"{i + 1}. {g} -> {r}" for i, (g, r) in enumerate(self.history)) or "none yet"
        pages = " > ".join(dict.fromkeys(p.split(" (")[0] for p in self.pages)) or "only the current one"
        c.add_message(
            role="user",
            content=f"TASK: {self.request}\n\nSTEPS SO FAR (what each did):\n{steps}\n\nPAGES VISITED: {pages}\n\n{screen}",
        )
        for m in (PLANNER_MODEL, PLANNER_FALLBACK_MODEL):
            try:
                calls = []
                async for ch in inference.LLM(model=m).chat(chat_ctx=c, tools=[click_step, finish]):
                    if ch.delta and ch.delta.tool_calls:
                        calls += ch.delta.tool_calls
                if calls:
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
                    outcome, done = args.get("outcome", ""), bool(args.get("done"))
                    break
                goal = args.get("goal", "")
                self._set(f"step {n + 1}: {goal}")
                _, what, screen = await k.do_step(goal)
                try:
                    screen = await screen_summary(k.bc.page, PLANNER_SCREEN_CHARS)
                except Exception:
                    pass
                self.history.append((goal, what))
                self.pages.append(screen.split("\n", 1)[0][6:80])
                last2 = [w for _, w in self.history[-2:]]
                # the same step did nothing twice: stop
                if len(last2) == 2 and last2[0] == last2[1] and no_effect(last2[0]):
                    reason = no_effect_reason(last2[0], screen)
                    outcome, done = (
                        reason + " Explain it from the screen instead of clicking.",
                        reason.startswith("That's already"),
                    )
                    break
            else:
                outcome = "That took more steps than expected, so I stopped."
        except asyncio.CancelledError:
            raise
        except Exception as e:
            outcome = f"Something went wrong: {type(e).__name__}"
            log.exception("planner")
        self._set("")
        # the result stays in the screen feed: a reply to the customer may come before ours, and must know it
        k.feed.task_line = (
            f"LAST SCREEN TASK ({'done' if done else 'NOT completed'}): {self.request[:120]} -> {outcome}"
        )
        k.feed.kick()
        k.slog.event(
            "task_done",
            request=self.request,
            done=done,
            outcome=outcome,
            steps=len(self.history),
            s=round(time.perf_counter() - t0, 1),
        )
        await self._report(done, outcome)

    async def _report(self, done: bool, outcome: str):
        """Start the queued task, or have Kai say the outcome (unless someone is talking or he already covered it)."""
        k = self.kai
        nxt, self.queued = self.queued, None
        if nxt and done:  # the queued task starts now; one short line covers both
            self.start(nxt)
            self._say(
                f"Your assistant finished: {outcome} It is now doing what they asked next: {nxt}. Say both in one short "
                "sentence; don't call do_task."
            )
            return
        if k.floor is not None and k.floor.busy:
            return  # a test call has the floor: FloorControl speaks next
        n_user, user_spoke = k.feed.user_turns, False
        for _ in range(40):  # don't talk over the customer, or over Kai's own line about this task
            us = getattr(k.session, "user_state", "")
            user_spoke = user_spoke or us == "speaking"
            if us != "speaking" and getattr(k.session, "agent_state", "") != "speaking":
                break
            await asyncio.sleep(0.2)
        if user_spoke or k.feed.user_turns != n_user:  # the customer talked: Kai's answer to them carries the result
            k.slog.event("task_reply_skipped", why="customer spoke")
            return
        said = len(k.feed.agent_lines) > self.said_from
        if done and len(" ".join(k.feed.agent_lines[self.said_from :]).split()) >= 15:
            # Kai already explained it while it ran; the result is in the screen feed for his next turn
            k.slog.event("task_reply_skipped", why="already explained")
            return
        text = (
            f"Your assistant finished the screen task ({'done' if done else 'not completed'}): {outcome} "
            + (
                "You were already talking while it ran: don't restate anything you said and don't make another business "
                "tie-in. In ONE short sentence, "
                if said
                else "In one or two short sentences, "
            )
            + "say what's on screen now that you haven't mentioned, then lead to the next step."
        )
        if nxt and not done:
            text += f" (Their next request, '{nxt}', was not started because this one didn't complete.)"
        self._say(text)

    def _say(self, text: str):
        if self.kai.turns is not None:
            self.kai.turns.request("task", text)  # fires when nobody is speaking, never during a test call
        else:
            self.kai.session.generate_reply(instructions=text)
