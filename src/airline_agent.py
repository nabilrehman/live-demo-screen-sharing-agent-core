"""Kai (called "LiveKit" to the traveller), a voice booking assistant on an airline website (the fictional Aurelian Airways demo). No shared browser: the
page sends its state up as a page_context text stream and registers RPC methods that Kai's tools call to act on it.
Kai never touches payment: there is no tool for it, and the page never reports card details. Flights and fares come
from the page (generated deterministically from knowledge/airline/), the persona, policies and greeting from
knowledge/airline/.

  uv run src/airline_agent.py dev        (AGENT_NAME, BRAIN=gemini-live|grok, MIN_RT_VOICE, WORKER_PORT)
"""

import asyncio
import logging
import os
from typing import Literal

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))

from livekit.agents import AgentServer, JobContext, ToolError, cli, function_tool

from demo_agent.brain import BRAIN, IS_GEMINI, MODEL, make_session
from inpage.airline import AirlinePage, greeting, prompt
from inpage.live import PageAgent

if IS_GEMINI:  # a slow import (PIL): do it when the job process starts, not on the call's first second
    from google.genai import types as _genai_types  # noqa: F401

log = logging.getLogger("airline")
Sort = Literal["recommended", "cheapest", "earliest", "fastest"]
Window = Literal["any", "morning", "afternoon", "evening", "night"]
Fare = Literal["economy-convenience", "economy-comfort", "business-comfort", "business-elite"]


class AirlineKai(PageAgent):
    page: AirlinePage

    # ---------- search ----------
    @function_tool
    async def search_flights(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        adults: int = 1,
        return_date: str = "",
        children: int = 0,
        infants: int = 0,
        cabin: str = "economy",
    ) -> str:
        """Search flights on the traveller's page and show the departure results. Pass everything they said in one
        call (to change one thing, pass the current search with that change). With return_date it's a return trip;
        without it, one way.

        Args:
            origin: City or airport code, e.g. "New York" or "JFK".
            destination: City or airport code, e.g. "Doha".
            depart_date: YYYY-MM-DD, from the calendar in your instructions.
            adults: Adults (12+), 1 to 9.
            return_date: YYYY-MM-DD for a return trip; empty for one way.
            children: Children 2 to 11.
            infants: Infants under 2 (on a lap, one per adult).
            cabin: "economy" or "business".
        """
        note = await self.rpc(
            "search_flights",
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            return_date=return_date,
            trip="return" if return_date else "one_way",
            adults=adults,
            children=children,
            infants=infants,
            cabin=cabin,
        )
        return "Done; their page shows the flights.\n" + note

    @function_tool
    async def change_date(self, date: str) -> str:
        """Show the flights for another day of the date strip (the leg on screen: departure or return).

        Args:
            date: YYYY-MM-DD.
        """
        return "Done; the flights for that day are on screen.\n" + await self.rpc("change_date", date=date)

    @function_tool
    async def sort_flights(self, by: Sort) -> str:
        """Sort the flight results: recommended, cheapest (lowest price), earliest departure or fastest."""
        return "Done.\n" + await self.rpc("sort_flights", by=by)

    @function_tool
    async def filter_flights(self, nonstop_only: bool = False, depart_window: Window = "any") -> str:
        """Filter the flight results (replaces the filters on; pass nothing to clear them).

        Args:
            nonstop_only: Only non-stop flights.
            depart_window: Departure time: any, morning (5-12), afternoon (12-18), evening (18-24) or night (0-5).
        """
        note = await self.rpc("filter_flights", nonstop_only=nonstop_only, depart_window=depart_window)
        return "Done; the results are filtered.\n" + note

    @function_tool
    async def show_results(self, leg: str = "") -> str:
        """Go back to the flight results; leg "departure" or "return" (empty: the one shown last)."""
        return "Done.\n" + await self.rpc("show_results", leg=leg)

    # ---------- flights and fares ----------
    @function_tool
    async def compare_fares(self, flight: str, cabin: str = "economy") -> str:
        """Open a flight's fare comparison (Economy Convenience vs Comfort, or Business Comfort vs Elite) with
        prices, seats left, bags, changes, cancellation and Aurels earned.

        Args:
            flight: The flight id, flight number ("AU702"), departure time ("11:20"), "first" / "second" for its place
                on screen, "cheapest non-stop", or "this one" for the flight being discussed.
            cabin: "economy" or "business".
        """
        note = await self.rpc("compare_fares", flight=self.page.resolve_flight(flight), cabin=cabin)
        return "Done; the fare comparison is open.\n" + note

    @function_tool
    async def flight_details(self, flight: str) -> str:
        """Open a flight's details (flight numbers, aircraft, connection time).

        Args:
            flight: As for compare_fares.
        """
        return "Done.\n" + await self.rpc("flight_details", flight=self.page.resolve_flight(flight))

    @function_tool
    async def select_fare(self, fare: Fare, flight: str = "") -> str:
        """Select a fare on a flight and continue: on a return trip to the return flights, otherwise to the passenger
        page. Only when the traveller chose it.

        Args:
            fare: economy-convenience, economy-comfort, business-comfort or business-elite.
            flight: As for compare_fares; leave empty for the flight whose fares are open.
        """
        note = await self.rpc("select_fare", fare=fare, flight=self.page.resolve_flight(flight) if flight else None)
        return "Done; the fare is selected and the next step is on screen.\n" + note

    # ---------- booking steps ----------
    @function_tool
    async def open_passenger(self, passenger: str) -> str:
        """Open a passenger's card on "Who's travelling?".

        Args:
            passenger: "1", "adult 2", "child 1", or "next" for the first one without details.
        """
        return "Done; the passenger form is open.\n" + await self.rpc("open_passenger", passenger=passenger)

    @function_tool
    async def fill_passenger_name(self, passenger: str, full_name: str) -> str:
        """Fill a passenger's title, first and last name, ONLY with what the traveller said out loud for that
        passenger. Never guess or invent names; never fill dates of birth or loyalty numbers.

        Args:
            passenger: "1", "adult 2", "child 1".
            full_name: Title (if said) then given name(s) then surname, as said or spelled, e.g. "Mr Nabil Rehman".
        """
        if not full_name.strip():
            raise ToolError("Say the name to fill.")
        note = await self.rpc("fill_passenger_name", passenger=passenger, full_name=full_name)
        return "Done; the name is filled in.\n" + note

    @function_tool
    async def continue_booking(self) -> str:
        """Press the page's continue button: Continue (after a fare), Continue to contact details, Continue to seats &
        extras, or Continue to payment. Never pays."""
        return "Done; the next step is on screen.\n" + await self.rpc("continue_booking")

    @function_tool
    async def go_to_step(self, step: Literal["flights", "passengers", "contact", "extras", "payment", "home"]) -> str:
        """Go back to an earlier booking step (or the home page)."""
        return "Done.\n" + await self.rpc("go_to_step", step=step)

    @function_tool
    async def choose_seat(self, seat: str, passenger: str = "", flight: str = "") -> str:
        """Choose a seat on the Seats & extras step.

        Args:
            seat: Like "32A" (economy rows 30-44, A-K) or "3K" (business rows 1-8, A/E/F/K).
            passenger: "1", "adult 2"; default: the one selected on the page.
            flight: Flight number like "AU702", or "1"/"2" for the order; default: the map on screen.
        """
        return "Done.\n" + await self.rpc("choose_seat", seat=seat, passenger=passenger, flight=flight)

    @function_tool
    async def add_extra(self, item: Literal["bag", "lounge", "insurance"], quantity: int = 1) -> str:
        """Set an extra on the Seats & extras step (quantity 0 removes it): bag = extra checked bags (each 120 USD per flight),
        lounge = passes in Doha (150 USD each) or insurance = travel protection (64 USD per passenger, on or off)."""
        return "Done.\n" + await self.rpc("add_extra", item=item, quantity=quantity)

    @function_tool
    async def show_trip_summary(self, open: bool = True) -> str:
        """Open (or close) the payment summary with the flights and the price breakdown."""
        return "Done.\n" + await self.rpc("show_trip_summary", open=open)

    @function_tool
    async def close_popups(self) -> str:
        """Close any open menu, dialog or the modify-search panel."""
        return "Done.\n" + await self.rpc("close_popups")

    @function_tool
    async def highlight(self, targets: list[str]) -> str:
        """Point things out on the traveller's page: outlines them and scrolls to the first.

        Args:
            targets: Flights ("AU702", "first", "cheapest non-stop"), a flight's price box ("AU702:business"), fares
                ("economy-comfort", when a comparison is open), or sections: dates, sort, search, total, trip,
                continue, extras, payment, passenger-1.
        """
        if not targets:
            raise ToolError("Say what to highlight.")
        return "Done; highlighted.\n" + await self.rpc("highlight", targets=targets)


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8099)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-airline"))
async def entrypoint(ctx: JobContext):
    session = make_session()
    kai = AirlineKai(ctx.room, AirlinePage(), prompt())
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
