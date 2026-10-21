"""generator-v2 web form (local only): paste a URL -> runs generate_demo.py -> live log -> preview link.
  python server.py   ->  http://localhost:8796/
Previews are served by this same server at /v2/<slug>/ (static only; voice needs preview.py + a local worker).
"""
import html, os, re, subprocess, sys
from aiohttp import web
HERE = os.path.dirname(os.path.abspath(__file__)); JOBS = {}
FORM = """<!doctype html><meta charset=utf-8><title>LiveKit demo generator v2</title>
<style>body{font:16px system-ui;max-width:760px;margin:40px auto;padding:0 16px}input,select{padding:10px;width:100%;margin:6px 0 14px}button{padding:12px 22px;background:#000;color:#fff;border:0;border-radius:6px}pre{background:#111;color:#ddd;padding:14px;white-space:pre-wrap;max-height:60vh;overflow:auto}</style>
<h1>LiveKit demo generator <small>v2 draft</small></h1><p>Paste a website; get a gated mockup with the LiveKit voice copilot (Wind Creek pipeline).</p>
<form method=post action=/run><label>Website URL<input name=url required placeholder="https://hotel.hardrock.com/"></label>
<label>Brand name<input name=brand required placeholder="Hard Rock Hotels"></label><label>Slug<input name=slug required pattern="[a-z0-9-]+" placeholder="hardrock"></label>
<label>Mode<select name=mode><option value=quick>quick (generic builder, ~10 min)</option><option value=claude>claude (Claude Code + demo-design skill, 1-3 h)</option></select></label>
<label><input type=checkbox name=images style="width:auto"> generate Gemini gap images</label><br><button>Generate</button></form>{jobs}"""

async def index(req):
    rows = "".join(f'<li><a href="/job/{s}">{s}</a> ({"running" if p.poll() is None else "exit " + str(p.returncode)})</li>' for s, p in JOBS.items())
    return web.Response(text=FORM.format(jobs=f"<h2>Jobs</h2><ul>{rows}</ul>" if rows else ""), content_type="text/html")

async def run(req):
    f = await req.post(); slug = re.sub(r"[^a-z0-9-]", "", f["slug"].lower())
    cmd = [sys.executable, os.path.join(HERE, "generate_demo.py"), f["url"], slug, "--brand", f["brand"], "--mode", f.get("mode", "quick")]
    if not f.get("images"): cmd += ["--skip", "images"]
    os.makedirs(os.path.join(HERE, "work", slug), exist_ok=True)
    JOBS[slug] = subprocess.Popen(cmd, stdout=open(os.path.join(HERE, "work", slug, "job.log"), "w"), stderr=subprocess.STDOUT)
    raise web.HTTPFound(f"/job/{slug}")

async def job(req):
    slug = req.match_info["slug"]; log = os.path.join(HERE, "work", slug, "job.log")
    txt = open(log).read()[-8000:] if os.path.exists(log) else ""
    p = JOBS.get(slug); done = p is not None and p.poll() is not None
    code = slug.upper() + "-DEMO"
    link = f'<p><a href="/v2/{slug}/?code={code}">Open the preview</a> (code {code})</p>' if os.path.exists(os.path.join(HERE, "work", slug, "site", "index.html")) else ""
    refresh = "" if done else '<meta http-equiv=refresh content=5>'
    return web.Response(text=f"<!doctype html>{refresh}<body style='font:15px system-ui;max-width:900px;margin:30px auto'><a href=/>&larr; back</a><h2>{slug}</h2>{link}<pre style='background:#111;color:#ddd;padding:12px;white-space:pre-wrap'>{html.escape(txt)}</pre>", content_type="text/html")

async def static(req):
    slug, rel = req.match_info["slug"], req.match_info["tail"]
    site = os.path.join(HERE, "work", slug, "site"); p = os.path.normpath(os.path.join(site, rel))
    if not p.startswith(site): raise web.HTTPForbidden()
    for c in (p, os.path.join(p, "index.html")):
        if os.path.isfile(c): return web.FileResponse(c)
    raise web.HTTPNotFound()

app = web.Application()
app.add_routes([web.get("/", index), web.post("/run", run), web.get("/job/{slug}", job), web.get("/v2/{slug}/{tail:.*}", static)])
if __name__ == "__main__": web.run_app(app, host="127.0.0.1", port=8796)
