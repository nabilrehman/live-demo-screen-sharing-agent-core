"""LiveKit, the host companion in the Hard Rock Host Companion demo (Hard Rock v2, /hardrock-v2/): a HOST-facing voice
agent for casino hosts on the floor. The Wind Creek site agent (windcreek_agent.py) with the hardrock-host knowledge pack
(knowledge/hardrock-host/, SITE_KNOWLEDGE: today's fictional VIP arrivals, comp authority, property facts) and the app's
own actions as tools in place of page navigation: open_player, show_section, next_player, back_to_briefing. The app is a
single page, so these are site actions (window.LiveKitAgent.registerAction in app.js); highlight still works as before.

  uv run src/hardrock_host_agent.py dev     (AGENT_NAME, BRAIN=gemini-live|grok, WORKER_PORT)
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SITE_KNOWLEDGE", os.path.join(ROOT, "knowledge", "hardrock-host"))

import windcreek_agent as base  # noqa: E402
from livekit.agents import AgentServer, JobContext, ToolError, cli, function_tool  # noqa: E402

from inpage.insights import Insights  # noqa: E402
from inpage.site import SITE  # noqa: E402

SECTIONS = {
    "profile": "profile",
    "comps": "comps",
    "comp": "comps",
    "preferences": "preferences",
    "prefs": "preferences",
    "recommendations": "recommendations",
    "tonight": "recommendations",
    "entertainment": "recommendations",
    "dining": "recommendations",
}


class HostCompanion(base.SiteKai):
    navigate = None  # one-page app: the screens are site actions
    open_promotions = None

    async def app(self, name: str, **args) -> str:
        note = await self.act("site_action", name=name, args=args)
        result = self.page.ctx.get("action_result") or ""
        if result.startswith(("No ", "Open a player first")):
            raise ToolError(result)
        return "Done; the screen shows it.\n" + note

    @function_tool
    async def open_player(self, player: str) -> str:
        """Open an arriving player's profile on the host's screen (it opens on Profile). Then summarize them briefly.

        Args:
            player: The player's last name, full name or Unity ID, e.g. "delane" or "Elena Marchetti".
        """
        return await self.app("open_player", player=player)

    @function_tool
    async def show_section(self, section: str) -> str:
        """On the open player's screen, show one section: profile, comps (authorized comps, limits, budget),
        preferences, or recommendations (tonight's dining and entertainment picks).

        Args:
            section: profile, comps, preferences or recommendations.
        """
        s = SECTIONS.get(section.lower().strip())
        if not s:
            raise ToolError(f"No section '{section}'. Sections: {', '.join(SITE['sections'])}.")
        return await self.app("show_section", section=s)

    @function_tool
    async def next_player(self) -> str:
        """Open the next arriving player after the one on screen (from the briefing: the first arrival)."""
        return await self.app("next_player")

    @function_tool
    async def back_to_briefing(self) -> str:
        """Go back to today's briefing: the list of VIP arrivals."""
        return await self.app("back_to_briefing")


class HostInsights(Insights):
    def summary(self, pages=None) -> dict:
        out = super().summary(pages)
        out["schema"] = "livekit.session_summary.v1"
        out["turns"] = {"host": self.user_turns, "assistant": self.agent_turns}
        out["personal_data"] = "none: the players are fictional sample data"
        return out


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8099)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-hardrock-host"))
async def entrypoint(ctx: JobContext):
    base.SiteKai, base.Insights = HostCompanion, HostInsights  # the Wind Creek entrypoint, with these
    await base.entrypoint(ctx)


if __name__ == "__main__":
    cli.run_app(server)

