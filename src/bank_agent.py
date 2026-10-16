"""Kai, a voice account assistant inside the customer's own bank page (the Harborline Bank demo). No shared browser:
the page sends its state up as a page_context text stream and registers RPC methods that Kai's tools call to act on
it. Kai explains and points; it has no tool that moves money or files anything. The bank, persona, greeting, data and
fees live in knowledge/bank/.

  uv run src/bank_agent.py dev        (AGENT_NAME, BRAIN=gemini-live|grok, WORKER_PORT; see brain.py for the models)
"""

import asyncio
import logging
import os
from typing import Literal

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))

from livekit.agents import AgentServer, JobContext, ToolError, cli, function_tool

from demo_agent.brain import BRAIN, IS_GEMINI, MODEL, make_session
from inpage.bank import BankPage, greeting, prompt
from inpage.live import PageAgent

if IS_GEMINI:  # a slow import (PIL): do it when the job process starts, not on the call's first second
    from google.genai import types as _genai_types  # noqa: F401

log = logging.getLogger("bank")
Tab = Literal["activity", "statements", "fees", "alerts"]
AlertId = Literal["low_balance", "large_purchase", "deposits"]


class BankKai(PageAgent):
    page: BankPage

    @function_tool
    async def filter_activity(
        self,
        category: str | None = None,
        merchant: str | None = None,
        type: str | None = None,
        date_range: str | None = None,
    ) -> str:
        """Filter the Activity list on the customer's page (replaces any filters already on).

        Args:
            category: A category from the page, e.g. "Restaurants", "Groceries", "Fees", "Income".
            merchant: Words from the merchant name, e.g. "Driftwood", "Harvest Lane".
            type: card, direct_deposit, ach, bill_pay, zelle, atm, transfer or fee.
            date_range: this-month, last-month, last-7-days, all (the last 30 days) or YYYY-MM-DD..YYYY-MM-DD.
        """
        if not any((category, merchant, type, date_range)):
            raise ToolError("Say what to filter by, or use clear_filters.")
        note = await self.rpc("filter_activity", category=category, merchant=merchant, type=type, date_range=date_range)
        return "Done; their list is filtered.\n" + note

    @function_tool
    async def clear_filters(self) -> str:
        """Show the whole Activity list again (removes all filters)."""
        return "Done.\n" + await self.rpc("clear_filters")

    @function_tool
    async def open_transaction(self, transaction: str) -> str:
        """Open one transaction's details drawer on the customer's page.

        Args:
            transaction: The transaction id from the account data, or "this one" for the one being discussed.
        """
        return "Done; its details are open.\n" + await self.rpc("open_transaction", id=self.page.resolve(transaction))

    @function_tool
    async def close_details(self) -> str:
        """Close the transaction details drawer."""
        return "Done.\n" + await self.rpc("close_transaction")

    @function_tool
    async def highlight(self, targets: list[str]) -> str:
        """Point things out on the customer's page: scrolls to them and outlines them until the next action. Pass every
        row you're talking about in one call (e.g. a fee and the transaction that caused it). All targets must be on one
        tab; the page switches to it.

        Args:
            targets: Transaction ids, fee section ids (maintenance, overdraft, protection, foreign, atm, wires, limits,
                zelle, savings, pending, disputes), alert ids (low_balance, large_purchase, deposits), or "balances" /
                "pending-balance" for the balance boxes.
        """
        if not targets:
            raise ToolError("Say what to highlight.")
        return "Done; highlighted.\n" + await self.rpc("highlight", targets=[self.page.resolve(t) for t in targets])

    @function_tool
    async def switch_tab(self, tab: Tab) -> str:
        """Switch the account page to another tab.

        Args:
            tab: activity, statements, fees (Fees & limits) or alerts.
        """
        return "Done.\n" + await self.rpc("switch_tab", tab=tab)

    @function_tool
    async def set_alert(self, alert: AlertId, threshold: float | None = None, on: bool = True) -> str:
        """Turn one of the page's alert switches on or off (a demo switch: no alerts are really sent).

        Args:
            alert: low_balance (when the available balance drops below the amount), large_purchase (card purchases
                over the amount) or deposits (no amount).
            threshold: The dollar amount they said, e.g. 100 for "a hundred dollars". Omit to keep the current amount.
            on: False to turn it off.
        """
        note = await self.rpc("set_alert", type=alert, threshold=threshold, on=on)
        return "Done; the switch on their page changed and a confirmation is showing.\n" + note

    @function_tool
    async def dispute_info(self, transaction: str) -> str:
        """Open the panel that explains how to dispute a charge. It only explains the steps; nothing is filed.

        Args:
            transaction: The transaction id, or "this one".
        """
        note = await self.rpc("dispute_info", id=self.page.resolve(transaction))
        return "Done; the how-to-dispute steps are open. Nothing was filed.\n" + note


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8097)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-bank"))
async def entrypoint(ctx: JobContext):
    session = make_session()
    kai = BankKai(ctx.room, BankPage(), prompt())
    kai.listen()  # the page's snapshots, from before it connects

    await ctx.connect()
    await ctx.wait_for_participant()
    log.info("call %s: brain %s (%s)", ctx.room.name, BRAIN, MODEL)
    await session.start(agent=kai, room=ctx.room)
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


if __name__ == "__main__":
    cli.run_app(server)
