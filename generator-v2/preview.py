"""Local preview of a generated demo at http://localhost:8795/v2/<slug>/ ; /api/token mints a token for a LOCAL worker
(agent name gen-<slug>) when LIVEKIT_URL/KEY/SECRET are in the env. Start the worker with:
  SITE_KNOWLEDGE=<work>/knowledge AGENT_NAME=gen-<slug> BRAIN=grok WORKER_PORT=8097 uv run src/windcreek_agent.py dev
  python preview.py <slug> [port]
"""
import datetime, os, secrets, sys
from aiohttp import web

HERE = os.path.dirname(os.path.abspath(__file__))
SLUG = sys.argv[1]; PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8795
SITE = os.path.join(HERE, "work", SLUG, "site")


async def token(req):
    from livekit import api
    room = f"gen-{SLUG}-" + secrets.token_hex(3)
    t = (api.AccessToken().with_identity("customer").with_name("Customer").with_ttl(datetime.timedelta(hours=2))
         .with_grants(api.VideoGrants(room_join=True, room=room, can_update_own_metadata=True))
         .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=f"gen-{SLUG}")])))
    return web.json_response({"url": os.environ["LIVEKIT_URL"], "token": t.to_jwt(), "room": room}, headers={"Cache-Control": "no-store"})


async def static(req):
    rel = req.path.removeprefix(f"/v2/{SLUG}").lstrip("/")
    p = os.path.normpath(os.path.join(SITE, rel))
    if not p.startswith(SITE):
        raise web.HTTPForbidden()
    for c in (p, os.path.join(p, "index.html")):
        if os.path.isfile(c):
            return web.FileResponse(c, headers={"Cache-Control": "no-store"})
    raise web.HTTPNotFound()

app = web.Application(); app.router.add_get("/api/token", token); app.router.add_route("*", "/{tail:.*}", static)
print(f"http://localhost:{PORT}/v2/{SLUG}/"); web.run_app(app, port=PORT, print=None)
