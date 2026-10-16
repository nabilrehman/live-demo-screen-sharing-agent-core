"""The shared part of an in-page agent: call the page's RPC methods (each returns a fresh page snapshot) and keep the
model's view of the page current between turns. The page object needs update_json(text) -> bool, signature() and
note() (see inpage.bank.BankPage)."""

import asyncio
import json
import logging
import time
from typing import Protocol

from livekit import rtc
from livekit.agents import Agent, ToolError

from demo_agent.brain import IS_GEMINI

log = logging.getLogger("inpage")
RPC_TIMEOUT_S = 3.0
FEED_EVERY_S = 0.6
RETRYABLE = {
    rtc.RpcError.ErrorCode.CONNECTION_TIMEOUT,
    rtc.RpcError.ErrorCode.RESPONSE_TIMEOUT,
    rtc.RpcError.ErrorCode.SEND_FAILED,
}


class Page(Protocol):
    def update_json(self, text: str) -> bool: ...
    def signature(self) -> str: ...
    def note(self) -> str: ...


class PageAgent(Agent):
    def __init__(self, room: rtc.Room, page: Page, instructions: str):
        super().__init__(instructions=instructions)
        self.room, self.page, self.prompt = room, page, instructions
        self.acting = 0  # page actions in flight; their results carry the new page state
        self.posted = ""  # signature of the page state the model last got
        self.changed = asyncio.Event()

    def visitor(self) -> str | None:
        for p in self.room.remote_participants.values():
            if p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                return p.identity
        return None

    async def rpc(self, method: str, **args) -> str:
        """Call one of the page's methods; it returns the new page state, as a note. A timeout is retried once."""
        dest = self.visitor()
        if dest is None:
            raise ToolError("The customer's page isn't connected.")
        payload = json.dumps({k: v for k, v in args.items() if v is not None and v != ""})
        self.acting += 1
        try:
            for attempt in (1, 2):
                t = time.perf_counter()
                try:
                    resp = await self.room.local_participant.perform_rpc(
                        destination_identity=dest, method=method, payload=payload, response_timeout=RPC_TIMEOUT_S
                    )
                    log.info("rpc %s %s ok %.0f ms", method, payload, (time.perf_counter() - t) * 1000)
                    break
                except rtc.RpcError as e:
                    log.info("rpc %s %s error %s %s", method, payload, e.code, e.message)
                    if e.code in RETRYABLE and attempt == 1:
                        continue
                    if e.code in RETRYABLE or e.code >= 1400:
                        raise ToolError("Their page didn't respond. Say 'one sec' and try once more.") from e
                    raise ToolError(e.message) from e
        finally:
            self.acting -= 1
        self.page.update_json(resp)
        self.posted = self.page.signature()
        return self.page.note()

    async def post_page(self):
        """Tell the model what the page shows now. Gemini: one context item (re-sending the instructions would
        restart its turn); Inference realtime: the instructions plus the page note."""
        self.posted = self.page.signature()
        if IS_GEMINI:
            ctx = self.chat_ctx.copy()
            ctx.add_message(role="user", content=self.page.note())
            await self.update_chat_ctx(ctx)
        else:
            await self.update_instructions(
                self.prompt + "\n\n# What the customer's page shows now\n" + self.page.note()
            )

    async def feed(self):
        """Keep the model's view of the page current between turns (at most every FEED_EVERY_S)."""
        while True:
            await self.changed.wait()
            self.changed.clear()
            await asyncio.sleep(FEED_EVERY_S)
            if self.acting or self.page.signature() == self.posted:
                continue
            try:
                await self.post_page()
            except Exception as e:
                log.warning("page note: %s", e)

    def listen(self, topic: str = "page_context"):
        """Take the page's snapshots from its text stream (register before connecting)."""

        def on_page(reader: rtc.TextStreamReader, _from: str):
            async def read():
                if self.page.update_json(await reader.read_all()):
                    self.changed.set()

            asyncio.create_task(read())

        self.room.register_text_stream_handler(topic, on_page)
