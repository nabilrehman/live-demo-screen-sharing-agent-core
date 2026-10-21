"""Kai, a voice booking concierge on a hotel website (the fictional Lakeline Hotels demo). No shared browser: the page
sends its state up as a page_context text stream and registers RPC methods that Kai's tools call to act on it. The
checkout is a demo: its guest and payment fields only hold fake values and nothing is booked. Hotels, rooms, prices,
persona and greeting live in knowledge/hotel/.

  uv run src/hotel_agent.py dev        (AGENT_NAME, BRAIN=gemini-live|grok, WORKER_PORT; see brain.py for the models)
"""

import asyncio
import logging
import os
from typing import Literal

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))

from livekit.agents import AgentServer, JobContext, ToolError, cli, function_tool

from demo_agent.brain import BRAIN, IS_GEMINI, MODEL, make_session
from inpage.hotel import HotelPage, greeting, prompt
from inpage.live import PageAgent

if IS_GEMINI:  # a slow import (PIL): do it when the job process starts, not on the call's first second
    from google.genai import types as _genai_types  # noqa: F401

log = logging.getLogger("hotel")
Rate = Literal["flexible", "member", "prepaid"]
Sort = Literal["distance", "price", "rating"]


class HotelKai(PageAgent):
    page: HotelPage

    # ---------- search ----------
    @function_tool
    async def set_search(
        self,
        destination: str | None = None,
        check_in: str | None = None,
        check_out: str | None = None,
        adults: int | None = None,
        children: int | None = None,
    ) -> str:
        """Search hotels on the guest's page: sets destination, dates and guests, then shows the results. Pass
        everything the guest said in one call.

        Args:
            destination: A city, e.g. "New York".
            check_in: YYYY-MM-DD, from the calendar in your instructions.
            check_out: YYYY-MM-DD.
            adults: Number of adults (1 to 4).
            children: Number of children (0 to 3).
        """
        if not any((destination, check_in, check_out, adults, children is not None)):
            raise ToolError("Say what to search for.")
        note = await self.rpc(
            "set_search",
            destination=destination,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
        )
        return "Done; their page shows the search.\n" + note

    @function_tool
    async def filter_hotels(
        self,
        breakfast: bool = False,
        pool: bool = False,
        pets: bool = False,
        spa: bool = False,
        max_price: int | None = None,
    ) -> str:
        """Filter the hotel results (replaces any filters already on; pass nothing to clear them).

        Args:
            breakfast: Only hotels with free breakfast.
            pool: Only hotels with a pool.
            pets: Only pet-friendly hotels.
            spa: Only hotels with a spa.
            max_price: Only hotels from under this many US dollars per night.
        """
        note = await self.rpc("filter_hotels", breakfast=breakfast, pool=pool, pets=pets, spa=spa, max_price=max_price)
        return "Done; the results are filtered.\n" + note

    @function_tool
    async def sort_hotels(self, by: Sort) -> str:
        """Sort the hotel results by distance, price (low to high) or guest rating."""
        return "Done.\n" + await self.rpc("sort_hotels", by=by)

    @function_tool
    async def show_results(self) -> str:
        """Go back to the list of hotels for the current search."""
        return "Done.\n" + await self.rpc("show_results")

    @function_tool
    async def open_hotel(self, hotel: str) -> str:
        """Open a hotel's rooms and rates page.

        Args:
            hotel: The hotel id, its name, or "first" / "second" for its place in the results on their screen.
        """
        return "Done; the hotel's rooms are on their screen.\n" + await self.rpc(
            "open_hotel", hotel=self.page.resolve_hotel(hotel)
        )

    # ---------- rooms ----------
    @function_tool
    async def view_rates(self, room: str) -> str:
        """Open a room's rates (flexible, member and pay-now) on the hotel page.

        Args:
            room: The room id, or words like "king", "two doubles", "suite"; "this one" for the room being discussed.
        """
        return "Done; the room's rates are open.\n" + await self.rpc("view_rates", room=self.page.resolve_room(room))

    @function_tool
    async def toggle_taxes(self, on: bool) -> str:
        """Show prices on the hotel page with taxes and fees included (on) or before taxes (off)."""
        return "Done.\n" + await self.rpc("toggle_taxes", on=on)

    @function_tool
    async def open_room_details(self, room: str) -> str:
        """Open a room's details (size, beds, view, bathroom, accessibility, features) with its photos.

        Args:
            room: The room id or words like "king"; "this one" for the room being discussed.
        """
        return "Done; the room details are open.\n" + await self.rpc(
            "open_room_details", room=self.page.resolve_room(room)
        )

    @function_tool
    async def show_room_photos(self, room: str, which: str | None = None) -> str:
        """Open a room's photo gallery, large.

        Args:
            room: The room id or words like "king"; "this one" for the room being discussed.
            which: Optional photo to start on: "bathroom", "view", "bed", "living room", "club lounge" or a number.
        """
        note = await self.rpc("show_room_photos", room=self.page.resolve_room(room), which=which)
        return "Done; the photos are open.\n" + note

    @function_tool
    async def show_photo(self, which: str, room: str | None = None) -> str:
        """Jump to one photo of the room: "bathroom", "view", "bed", "living room", "club lounge" or a number.

        Args:
            which: The kind of photo or its number.
            room: Optional; the room whose photos are open is used by default.
        """
        note = await self.rpc("show_photo", which=which, room=self.page.resolve_room(room) if room else None)
        return "Done.\n" + note

    @function_tool
    async def next_photo(self) -> str:
        """Show the next photo in the open gallery."""
        return "Done.\n" + await self.rpc("next_photo")

    @function_tool
    async def prev_photo(self) -> str:
        """Show the previous photo in the open gallery."""
        return "Done.\n" + await self.rpc("prev_photo")

    @function_tool
    async def close_gallery(self) -> str:
        """Close the room photos or room details."""
        return "Done.\n" + await self.rpc("close_gallery")

    # ---------- booking (demo) ----------
    @function_tool
    async def select_rate(self, room: str, rate: Rate) -> str:
        """Choose a room and rate on the hotel page (it shows "Your Room" with the total).

        Args:
            room: The room id or words like "king"; "this one" for the room being discussed.
            rate: flexible, member or prepaid.
        """
        return "Done; it's selected.\n" + await self.rpc("select_rate", room=self.page.resolve_room(room), rate=rate)

    @function_tool
    async def go_to_checkout(self, room: str | None = None, rate: Rate | None = None) -> str:
        """Go to the (demo) checkout with a room and rate; without them, with the one already selected.

        Args:
            room: The room id or words like "king".
            rate: flexible, member or prepaid.
        """
        note = await self.rpc("go_to_checkout", room=self.page.resolve_room(room) if room else None, rate=rate)
        return "Done; the checkout page is on their screen.\n" + note

    @function_tool
    async def change_rate(self, rate: Rate) -> str:
        """Switch the chosen room to another rate (at checkout)."""
        return "Done.\n" + await self.rpc("change_rate", rate=rate)

    @function_tool
    async def add_room_request(self, item: str) -> str:
        """Add a room request at checkout: e.g. high floor, near elevator, crib, rollaway bed, roll-in shower, late
        arrival, early check-in, quiet room, feather-free bedding."""
        return "Done; the request is added.\n" + await self.rpc("add_room_request", item=item)

    @function_tool
    async def remove_room_request(self, item: str) -> str:
        """Remove a room request at checkout."""
        return "Done.\n" + await self.rpc("remove_room_request", item=item)

    @function_tool
    async def show_cancel_policy(self) -> str:
        """Point at the cancellation policy on the checkout page."""
        return "Done; the cancellation policy is highlighted.\n" + await self.rpc("show_cancel_policy")

    @function_tool
    async def fill_demo_guest(self) -> str:
        """Fill the checkout's guest and payment fields with the site's fake demo values (they can't hold anything
        else). Never use real details."""
        return "Done; the demo details are filled in.\n" + await self.rpc("fill_demo_guest")

    @function_tool
    async def book_demo(self) -> str:
        """Press "Book now (demo)": shows a demo confirmation. Only when the guest clearly asked to book. Nothing is
        reserved or charged."""
        return "Done; the demo confirmation is on their screen.\n" + await self.rpc("book_demo")

    @function_tool
    async def highlight(self, targets: list[str]) -> str:
        """Point things out on the guest's page: outlines them and scrolls to the first.

        Args:
            targets: Hotel ids, room ids, "room:rate" (e.g. "deluxe-king:flexible"), or sections: search, taxes,
                about, location, policies, cancellation, price, requests, guest, payment.
        """
        if not targets:
            raise ToolError("Say what to highlight.")
        return "Done; highlighted.\n" + await self.rpc("highlight", targets=targets)


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8098)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-hotel"))
async def entrypoint(ctx: JobContext):
    session = make_session()
    kai = HotelKai(ctx.room, HotelPage(), prompt())
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
