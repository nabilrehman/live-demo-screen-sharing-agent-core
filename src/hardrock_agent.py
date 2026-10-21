"""LiveKit, the voice concierge on the Hard Rock Hotels demo mockup. The Wind Creek site agent (windcreek_agent.py)
with the Hard Rock knowledge pack (knowledge/hardrock/, SITE_KNOWLEDGE) and one Hard Rock tool, open_hotel, in place of
Wind Creek's open_promotions. The session summary says "assistant" where Wind Creek's says "kai".

  uv run src/hardrock_agent.py dev     (AGENT_NAME, BRAIN=gemini-live|grok, WORKER_PORT)
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SITE_KNOWLEDGE", os.path.join(ROOT, "knowledge", "hardrock"))

import windcreek_agent as base  # noqa: E402
from livekit.agents import AgentServer, JobContext, ToolError, cli, function_tool  # noqa: E402

from inpage.insights import Insights  # noqa: E402
from inpage.site import SITE  # noqa: E402

HOTEL_PAGES = ("rooms-and-suites", "offers", "eat-and-drink", "amenities", "area-guide")


class HardRockConcierge(base.SiteKai):
    open_promotions = None  # Wind Creek's properties; Hard Rock has open_hotel

    @function_tool
    async def open_hotel(self, hotel: str, page: str = "") -> str:
        """Open one hotel's page: its home page, or its rooms and suites, offers, eat and drink, amenities or area guide.

        Args:
            hotel: The hotel's city, e.g. "new-york".
            page: "" for the hotel's home page, or rooms-and-suites, offers, eat-and-drink, amenities, area-guide.
        """
        slug = hotel.lower().strip().removeprefix("hard rock hotel").strip().replace(" ", "-")
        slug = {"nyc": "new-york", "manhattan": "new-york"}.get(slug, slug)
        if slug not in SITE["hotels"]:
            raise ToolError(f"No hotel '{hotel}' in this site. Hotels: {', '.join(SITE['hotels'])}.")
        page = page.strip().strip("/").lower().replace(" ", "-")
        if page and page not in HOTEL_PAGES:
            raise ToolError(f"No page '{page}'. Pages: {', '.join(HOTEL_PAGES)}.")
        return await self.navigate(f"/{slug}/{page}" if page else f"/{slug}")


class HardRockInsights(Insights):
    def summary(self, pages=None) -> dict:
        out = super().summary(pages)
        out["schema"] = "livekit.session_summary.v1"
        out["turns"] = {"guest": self.user_turns, "assistant": self.agent_turns}
        return out


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8099)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-hardrock"))
async def entrypoint(ctx: JobContext):
    base.SiteKai, base.Insights = HardRockConcierge, HardRockInsights  # the Wind Creek entrypoint, with these
    await base.entrypoint(ctx)


if __name__ == "__main__":
    cli.run_app(server)
