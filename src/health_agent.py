"""Kai explains one health plan page by voice, and points at the page while he talks.

The page (vflights/public/health) sends its text on the 'page_context' text stream when Kai joins, and the section in
view on 'page_view'. Kai points with RPC methods the page registers: highlight, scroll_to, clear_highlight. The RPCs
run in the background, so a tool call returns at once and doesn't hold up Kai's speech.

  BRAIN       gemini-live (default) | grok   (see demo_agent/brain.py)
  AGENT_NAME  default live-demo-health        WORKER_PORT  default 8096

  uv run src/health_agent.py dev
"""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

# before demo_agent reads env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))

from livekit import rtc
from livekit.agents import Agent, AgentServer, JobContext, RunContext, cli, function_tool

from demo_agent.brain import BRAIN, IS_GEMINI, MODEL, make_session
from demo_agent.planpage import GREETING, instructions, section_ids, viewing

log = logging.getLogger("health")
PAGE_WAIT_S = 8  # how long Kai waits for the page text before he starts anyway


class Page:
    """What the customer's browser told us: the page text, its section ids, the section in view (and the last one
    Kai knows about: where he pointed, or the last view he was told)."""

    def __init__(self):
        self.text, self.ids, self.identity = "", [], ""
        self.view = self.told = ""
        self.ready = asyncio.Event()


class Kai(Agent):
    def __init__(self, room: rtc.Room, page: Page):
        super().__init__(instructions=instructions(page.text, page.view))
        page.told = page.view
        self.room, self.page = room, page

    def _call_page(self, method: str, **args) -> None:
        async def call():
            try:
                res = await self.room.local_participant.perform_rpc(
                    destination_identity=self.page.identity,
                    method=method,
                    payload=json.dumps(args),
                    response_timeout=5.0,
                )
                log.info("rpc %s %s -> %s", method, args, res)
            except Exception as e:
                log.warning("rpc %s %s failed: %s", method, args, e)

        if self.page.identity:
            asyncio.create_task(call())

    def _check(self, section_id: str) -> str | None:
        sid = section_id.strip().lstrip("#")
        return sid if sid in self.page.ids else None

    @function_tool()
    async def highlight(self, context: RunContext, section_id: str, phrase: str = "") -> str:
        """Point at the part of the page you're talking about: scrolls to it and highlights the matching row.

        Args:
            section_id: A section id from the page, without '#', e.g. "drugs".
            phrase: A short phrase copied from the row, e.g. "Emergency room". Empty highlights the whole section.
        """
        sid = self._check(section_id)
        if not sid:
            return f"not found; sections are: {', '.join(self.page.ids)}"
        self._call_page("highlight", section_id=sid, phrase=phrase)
        self.page.view = self.page.told = sid
        return "ok"

    @function_tool()
    async def scroll_to(self, context: RunContext, section_id: str) -> str:
        """Scroll the page to a section without highlighting a row.

        Args:
            section_id: A section id from the page, without '#'.
        """
        sid = self._check(section_id)
        if not sid:
            return f"not found; sections are: {', '.join(self.page.ids)}"
        self._call_page("scroll_to", section_id=sid)
        self.page.view = self.page.told = sid
        return "ok"

    @function_tool()
    async def clear_highlight(self, context: RunContext) -> str:
        """Remove the highlight from the page."""
        self._call_page("clear_highlight")
        return "ok"


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8096)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-health"))
async def entrypoint(ctx: JobContext):
    page = Page()
    session = make_session()
    kai: Kai | None = None

    async def read_page(reader: rtc.TextStreamReader, identity: str):
        try:
            text = await reader.read_all()
        except Exception as e:
            log.warning("page_context failed: %s", e)
            return
        page.text, page.ids, page.identity = text, section_ids(text), identity
        log.info("page_context from %s: %d chars, sections %s", identity, len(text), page.ids)
        if kai is not None:  # the page sent its text again (it reconnected): keep Kai's prompt current
            await kai.update_instructions(instructions(text, page.view))
        page.ready.set()

    async def read_view(reader: rtc.TextStreamReader, identity: str):
        try:
            page.view = (await reader.read_all()).strip()
        except Exception:
            return
        log.info("page_view %s", page.view)
        await tell_view()

    async def tell_view():
        # The customer scrolled: tell Kai while he's listening, so it doesn't interrupt him and is there when the
        # customer speaks ("what does this part mean?"). Gemini gets a note in the conversation (an instructions
        # update would resend the whole prompt as a turn); Grok reads only its instructions.
        if kai is None or page.view in ("", page.told) or session.agent_state != "listening":
            return
        if session.user_state == "speaking":
            return
        page.told = page.view
        try:
            if IS_GEMINI:
                chat = kai.chat_ctx.copy()
                chat.add_message(role="user", content=f"(Page note, not spoken: {viewing(page.text, page.view)})")
                await kai.update_chat_ctx(chat)
            else:
                await kai.update_instructions(instructions(page.text, page.view))
            log.info("told Kai the customer is on #%s", page.view)
        except Exception as e:
            log.warning("page note failed: %s", e)

    # handlers before connect: the page sends its text as soon as Kai joins
    ctx.room.register_text_stream_handler("page_context", lambda r, who: asyncio.create_task(read_page(r, who)))
    ctx.room.register_text_stream_handler("page_view", lambda r, who: asyncio.create_task(read_view(r, who)))
    await ctx.connect()

    try:
        await asyncio.wait_for(page.ready.wait(), PAGE_WAIT_S)
    except TimeoutError:
        log.warning("no page_context after %ss; starting without the page", PAGE_WAIT_S)

    kai = Kai(ctx.room, page)

    @session.on("conversation_item_added")
    def _item(ev):
        if getattr(ev.item, "text_content", None):
            log.info("%s: %s", ev.item.role, ev.item.text_content)

    @session.on("agent_state_changed")
    def _state(ev):
        if ev.new_state == "listening":
            asyncio.create_task(tell_view())

    @session.on("function_tools_executed")
    def _tools(ev):
        for c in ev.function_calls:
            log.info("tool %s(%s)", c.name, c.arguments)

    await session.start(agent=kai, room=ctx.room)
    log.info("session started: brain=%s model=%s", BRAIN, MODEL)
    session.generate_reply(instructions=f'Say exactly: "{GREETING}"')


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli.run_app(server)
