"""Kai, a voice concierge embedded in a multi-page website (the Wind Creek demo). No shared browser: the embed widget
(kai.js) sends the page's state up as a page_context text stream and registers RPC methods that Kai's tools call:
navigate, scroll_to, highlight, read_section, clear_highlight. Every one returns a fresh page snapshot.

The site is multi-page, so the visitor leaves the room on every page load and rejoins it from the next page with the
same token. The session doesn't close when they leave; it waits AWAY_S for them to come back (navigate waits for the
new page's first snapshot), and ends when the widget says so (kai_control {"end": true}) or nobody returns.

Each call produces a structured session summary (inpage.insights): sent to the widget as it changes (kai_insights) and
written to sessions/<room>/summary.json at the end.

The brand, persona, greeting and facts are in knowledge/windcreek/.

  uv run src/windcreek_agent.py dev     (AGENT_NAME, BRAIN=gemini-live|grok, WORKER_PORT; see brain.py for the models)
"""

import asyncio
import json
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))

from livekit import rtc
from livekit.agents import AgentServer, JobContext, ToolError, cli, function_tool, room_io

from demo_agent.brain import BRAIN, IS_GEMINI, MODEL, make_session
from inpage.insights import Insights
from inpage.live import PageAgent
from inpage.site import SITE, SitePage, allowed_path, greeting, prompt

if IS_GEMINI:  # a slow import (PIL): do it when the job process starts, not on the call's first second
    from google.genai import types as _genai_types  # noqa: F401

log = logging.getLogger("site")
AWAY_S = float(os.getenv("AWAY_S", 30))  # how long the session waits for the visitor to come back from a page load
NAV_WAIT_S = 15.0  # how long navigate waits for the new page's first snapshot
VISITOR_WAIT_S = 10.0  # how long an action waits for the visitor to rejoin (they may be mid page load)
SETTLE_S = 0.6  # after a new page's first snapshot, a moment for its scripts to register site actions
QUIET_AFTER_TOOLS_S = 1.5  # Kai silent this long after its last page action: ask for the answer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SiteKai(PageAgent):
    page: SitePage

    def __init__(self, room: rtc.Room, page: SitePage, instructions: str, insights: Insights):
        super().__init__(room, page, instructions)
        self.insights = insights
        self.on_change = lambda: None  # set by the entrypoint: push the summary to the page

    async def wait_visitor(self, timeout: float = VISITOR_WAIT_S) -> bool:
        t = time.monotonic()
        while self.visitor() is None:
            if time.monotonic() - t > timeout:
                return False
            await asyncio.sleep(0.1)
        return True

    async def act(self, method: str, **args) -> str:
        """Call a page method (waiting for the visitor if they're between pages); log it for the session summary."""
        t = time.perf_counter()
        try:
            if not await self.wait_visitor():
                raise ToolError("Their page isn't connected right now.")
            await self.rpc(method, **args)
        except ToolError as e:
            self.insights.action(method, args, False, (time.perf_counter() - t) * 1000, str(e))
            self.on_change()
            raise
        self.insights.action(method, args, True, (time.perf_counter() - t) * 1000)
        self.on_change()
        return self.page.note(full=True)

    @function_tool
    async def navigate(self, to: str) -> str:
        """Open another page of the site for the guest. Say one short phrase first ("Let me pull that up.").

        Args:
            to: A path from the site map, e.g. "/bethlehem/promotions" or "/rewards", or the words of a link on the
                current page, e.g. "Book Now".
        """
        if to.startswith(("/", "http")) and not allowed_path(to):
            self.insights.action("navigate", {"to": to}, False, 0, "isn't allowed")
            raise ToolError(
                "That page isn't allowed (sign-in, account, careers or payment pages). Explain what you can do instead."
            )
        self.page.loaded.clear()
        note = await self.act("navigate", to=to)
        if self.page.ctx.get("navigating"):  # the page is loading the new one; it rejoins from there
            if not await self.page.next_load(NAV_WAIT_S):
                return "The new page is still loading; tell them it's on its way.\n" + note
            await asyncio.sleep(SETTLE_S)  # the page registers its own actions just after it loads
            note = self.page.note(full=True)
            self.on_change()
        return "Done; the page is open.\n" + note

    @function_tool
    async def open_promotions(self, property: str) -> str:
        """Open a property's promotions and events page.

        Args:
            property: bethlehem, atmore, wetumpka, montgomery, chicagosouthland, aruba or curacao.
        """
        slug = property.lower().replace(" ", "").replace("ç", "c").removeprefix("windcreek")
        slug = "chicagosouthland" if slug.startswith("chicago") else slug
        if slug not in SITE["properties"]:
            raise ToolError(f"No property '{property}'. Properties: {', '.join(SITE['properties'])}.")
        return await self.navigate(f"/{slug}/promotions")

    @function_tool
    async def highlight(self, targets: list[str]) -> str:
        """Point things out on the current page: scrolls to the first and outlines them all until the next action.

        Args:
            targets: The words of each thing as shown on the page: a heading, a card or promotion title, a restaurant
                name, a table column such as "Delight", a table row such as "Birthday Bonus", or a button label.
        """
        if not targets:
            raise ToolError("Say what to highlight.")
        return "Done; highlighted.\n" + await self.act("highlight", targets=targets)

    @function_tool
    async def scroll_to(self, heading: str) -> str:
        """Scroll the current page to a heading or section.

        Args:
            heading: The heading's words as shown on the page.
        """
        return "Done.\n" + await self.act("scroll_to", heading=heading)

    @function_tool
    async def read_section(self, heading: str) -> str:
        """Read one section of the current page in full (everything under that heading) and scroll to it.

        Args:
            heading: The heading's words as shown on the page.
        """
        return await self.act("read_section", heading=heading)

    @function_tool
    async def site_action(self, name: str, args_json: str = "{}") -> str:
        """Run one of the actions the current page offers (listed under "Site actions on this page"), for example
        select_dates on the hotel booking page. Only listed actions exist.

        Args:
            name: The action's name as listed.
            args_json: Its arguments as a JSON object, as the listing describes, e.g. {"check_in": "2026-10-24", "check_out": "2026-10-25"}.
        """
        try:
            args = json.loads(args_json or "{}")
        except ValueError as e:
            raise ToolError("args_json must be a JSON object.") from e
        listed: set = set()
        for _ in range(20):  # a page that just loaded may still be registering its actions
            listed = {a.get("name") for a in self.page.ctx.get("site_actions") or []}
            if name in listed:
                break
            await asyncio.sleep(0.1)
        if name not in listed:
            raise ToolError(f"This page has no action '{name}'. Actions: {', '.join(sorted(listed)) or 'none'}.")
        return "Done.\n" + await self.act("site_action", name=name, args=args)

    @function_tool
    async def clear_highlight(self) -> str:
        """Remove the highlights from the page."""
        return "Done.\n" + await self.act("clear_highlight")


def track(session, kai: SiteKai, ins: Insights):
    """Feed the session summary: what the guest and Kai said, and how long Kai took to start answering."""
    state = {"user_end": None, "nudge": None}

    @session.on("user_input_transcribed")
    def _user(ev):
        if ev.is_final:
            ins.user_said(ev.transcript)
            kai.on_change()

    @session.on("conversation_item_added")
    def _item(ev):
        item = ev.item
        if getattr(item, "role", None) == "assistant" and (text := item.text_content):
            ins.agent_said(text)
            kai.on_change()

    @session.on("user_state_changed")
    def _ustate(ev):
        if ev.old_state == "speaking" and ev.new_state == "listening":
            state["user_end"] = time.perf_counter()

    @session.on("agent_state_changed")
    def _astate(ev):
        if ev.new_state == "speaking":
            if state["nudge"]:
                state["nudge"].cancel()
                state["nudge"] = None
            if state["user_end"] is not None:
                ins.latency((time.perf_counter() - state["user_end"]) * 1000)
                state["user_end"] = None

    async def nudge():
        """A realtime model sometimes ends its turn after a chain of page actions without saying anything. If Kai
        is still quiet a few seconds after its last action, ask for the answer once."""
        await asyncio.sleep(QUIET_AFTER_TOOLS_S)
        state["nudge"] = None
        if session.agent_state != "speaking" and session.current_speech is None:
            log.info("quiet after page actions; asking for the answer")
            session.generate_reply(
                instructions="Answer the guest now in one to three sentences from what their screen shows after your "
                "actions. Don't repeat the actions."
            )

    @session.on("function_tools_executed")
    def _tools(_ev):
        if state["nudge"]:
            state["nudge"].cancel()
        state["nudge"] = asyncio.create_task(nudge())


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8099)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-windcreek"))
async def entrypoint(ctx: JobContext):
    session = make_session()
    page = SitePage()
    ins = Insights(ctx.room.name, BRAIN, MODEL)
    kai = SiteKai(ctx.room, page, prompt(), ins)
    kai.listen()  # the page's snapshots, from before it connects
    done = asyncio.Event()
    away: dict = {"task": None}

    async def push():
        await asyncio.sleep(0.4)  # debounce
        dest = kai.visitor()
        if dest:
            try:
                await ctx.room.local_participant.send_text(
                    json.dumps(ins.summary(page.visited)), topic="kai_insights", destination_identities=[dest]
                )
            except Exception as e:
                log.debug("insights push: %s", e)

    pending: dict = {"task": None}

    def on_change():
        if pending["task"] is None or pending["task"].done():
            pending["task"] = asyncio.create_task(push())

    kai.on_change = on_change

    def on_control(reader: rtc.TextStreamReader, _from: str):
        async def read():
            try:
                msg = json.loads(await reader.read_all())
            except ValueError:
                return
            if msg.get("end"):
                log.info("call %s: ended by the visitor", ctx.room.name)
                done.set()

        asyncio.create_task(read())

    ctx.room.register_text_stream_handler("kai_control", on_control)

    async def wait_return():
        await asyncio.sleep(AWAY_S)
        if kai.visitor() is None:
            log.info("call %s: visitor didn't come back in %.0fs", ctx.room.name, AWAY_S)
            done.set()

    @ctx.room.on("participant_disconnected")
    def _left(p: rtc.RemoteParticipant):
        if p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT and kai.visitor() is None:
            log.info("call %s: visitor left (page load?); waiting %.0fs", ctx.room.name, AWAY_S)
            away["task"] = asyncio.create_task(wait_return())

    @ctx.room.on("participant_connected")
    def _back(p: rtc.RemoteParticipant):
        if away["task"] and not away["task"].done():
            away["task"].cancel()
            log.info("call %s: visitor back", ctx.room.name)

    await ctx.connect()
    await ctx.wait_for_participant()
    log.info("call %s: brain %s (%s)", ctx.room.name, BRAIN, MODEL)
    await session.start(agent=kai, room=ctx.room, room_options=room_io.RoomOptions(close_on_disconnect=False))
    track(session, kai, ins)
    hello = greeting()
    try:  # the page's state before the greeting, in case its first snapshot came before we listened
        note = await kai.rpc("get_context")
        if IS_GEMINI:  # into the greeting turn: a context update just before it can start a turn of its own on Gemini
            hello += "\n\n" + note
        else:
            await kai.post_page()
    except Exception as e:
        log.warning("no page context at start: %s", e)
    asyncio.create_task(kai.feed())
    session.generate_reply(instructions=hello)

    async def finish():
        summary = ins.summary(page.visited)
        log.info("session summary %s", json.dumps(summary))
        try:
            d = os.path.join(ROOT, "sessions", ctx.room.name)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "summary.json"), "w") as f:
                json.dump(summary, f, indent=2)
        except OSError as e:
            log.warning("summary not written: %s", e)

    ctx.add_shutdown_callback(finish)
    await done.wait()
    ctx.shutdown(reason="visitor ended or left")


if __name__ == "__main__":
    cli.run_app(server)
