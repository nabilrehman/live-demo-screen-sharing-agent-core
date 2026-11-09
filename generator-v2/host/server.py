"""generator-v2 HOSTED controller: runs inside a Vercel Sandbox (enterprise team "livekit"), exposed on port 8080.

  POST /api/generate   {url, brand, slug, concept?, mode: quick|claude, images: bool, build_code}  -> starts a build job
  GET  /api/jobs/<slug>                                    -> status + readable log tail (poll every few s)
  POST /api/demos/<slug>/edit {build_code, assistant?, voice?, change?} -> edits a finished demo, republishes its pack
  POST /api/demos/<slug>/delete {build_code}             -> takes it off Blob, moves it to work/.deleted/ (recoverable)
  GET  /api/demos                                          -> every demo built here (gallery feed for the main page)
  GET  /v2/<slug>/...                                      -> the generated, access-code-gated demo (static)
  GET  /api/token?brain=<slug>-grok                        -> LiveKit token for agent gen-<slug> (a sandbox worker: builds and
                                                              unpublished demos; published ones redirect to live-demos-sa)
  GET  /                                                   -> tiny status page

Builds are long (quick ~5-15 min, claude 1-3 h), so each one is a detached subprocess of generate_demo.py; this
server only starts it, tails its log and, when it finishes, starts the demo's voice worker (host/run_voice.sh).
State lives on disk (work/<slug>/job.json), so a restarted server (new sandbox session) picks everything back up.

AUTH SEAM (v1): every build runs Claude Code / Gemini with the ONE login seeded into this sandbox (~/.claude, the Gemini
key file, gen/.lk.env). TODO(per-user): replace `sandbox_for(request)` + the seeded login with a per-user sandbox
"demo-gen-<username>" in which that person ran `claude login` (device-code flow) themselves; see host/README.md.
Nothing here ever reads or prints the contents of those credential files.
"""
import datetime, html, json, os, re, secrets, subprocess, sys, threading, time, urllib.parse
from aiohttp import web

import publish  # finished demos -> Vercel Blob + the shared LiveKit Cloud agent (host/publish.py)

ROOT = os.environ.get("GEN_HOME", "/vercel/gen")
GEN = os.path.join(ROOT, "generator-v2")                 # this repo folder, copied into the sandbox
WORK = os.path.join(GEN, "work")
PY = os.environ.get("GEN_PY", "/vercel/venv/bin/python")
PORT = int(os.getenv("PORT", 8080))
MAX_RUNNING = int(os.getenv("GEN_MAX_RUNNING", 3))
BUILD_CODE_FILE = os.path.join(ROOT, ".build_code")      # shared "may start builds" code (not a credential)
RESERVED = {"hotel", "windcreek", "flights", "hardrock", "hardrock-v2", "air", "store", "health", "bank", "prod", "embed", "api", "v2"}
BUILD_ENV = {
    "GEN_SCRATCH": os.path.join(ROOT, "scratch"),
    "GEN_WIDGET": os.path.join(ROOT, "scratch", "vflights", "public", "embed", "windcreek"),
    "PW_CHANNEL": "",                                     # no Google Chrome in the sandbox: bundled chromium
    "GEN_CLAUDE_TEMPLATE": os.path.join(GEN, "templates", "claude_prompt_sandbox.md"),
    "GEN_CLAUDE_CWD": "/vercel/core",
    "GEN_CLAUDE_ADD_DIRS": f"{ROOT}:/vercel/agent",
    "PYTHONUNBUFFERED": "1",
}
PROCS = {}  # slug -> Popen (this session only; job.json is the durable record)


def build_code():
    try:
        return open(BUILD_CODE_FILE).read().strip()
    except OSError:
        return ""


def login_gated(req):
    """True when the product layer's sign-in middleware is installed on this app and requires a signed-in
    @ALLOWED_DOMAIN session for POST /api/generate: then the shared builder code is redundant (2026-10-22)."""
    prod = sys.modules.get("product")
    try:
        return bool(prod and prod.require_login() and any(getattr(m, "__module__", "") == "product" for m in req.app.middlewares))
    except Exception:  # noqa: BLE001
        return False


def jpath(slug):
    return os.path.join(WORK, slug, "job.json")


def load(slug):
    try:
        return json.load(open(jpath(slug)))
    except (OSError, ValueError):
        return None


def save(slug, j):
    tmp = jpath(slug) + ".tmp"
    json.dump(j, open(tmp, "w"), indent=1)
    os.replace(tmp, jpath(slug))


def worker_running(slug):
    """True if a voice worker with AGENT_NAME=gen-<slug> is alive (started by us or by Claude's own test)."""
    want = f"AGENT_NAME=gen-{slug}".encode()
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:  # no /proc off Linux (local testing)
        if pid.isdigit():
            try:
                if want in open(f"/proc/{pid}/environ", "rb").read().split(b"\0"):
                    return True
            except OSError:
                pass
    return False


def start_worker(slug):
    if worker_running(slug) or not os.path.isdir(os.path.join(WORK, slug, "knowledge")):
        return
    port = 8100 + (sum(map(ord, slug)) % 800)
    subprocess.Popen(["bash", os.path.join(GEN, "host", "run_voice.sh"), slug, str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_worker(slug):
    """SIGTERM the demo's own voice worker processes (found by their AGENT_NAME), so the next call loads the edit."""
    want = f"AGENT_NAME=gen-{slug}".encode()
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if pid.isdigit():
            try:
                if want in open(f"/proc/{pid}/environ", "rb").read().split(b"\0"):
                    os.kill(int(pid), 15)
            except OSError:
                pass
    for _ in range(20):
        if not worker_running(slug):
            return
        time.sleep(0.5)


def refresh(slug, j):
    """Update a running job's status from its process (or, after a restart, from its log / site)."""
    if j.get("status") != "running":
        return j
    p = PROCS.get(slug)
    rc = p.poll() if p else None
    if p is None:  # server restarted mid-build: the build died with the previous session unless its pid is alive
        alive = j.get("pid") and os.path.exists(f"/proc/{j['pid']}")
        if alive:
            return j
        rc = 0 if os.path.isfile(os.path.join(WORK, slug, "site", "index.html")) else 1
    elif rc is None:
        return j
    j["status"] = "done" if rc == 0 and os.path.isfile(os.path.join(WORK, slug, "site", "index.html")) else "failed"
    j["finished"] = int(time.time()); j["exit"] = rc
    save(slug, j)
    if j["status"] == "done":
        publish_bg(slug)
    return j


def hosted(slug):
    """Published demos run off the sandbox: pages on live-demos-sa, calls on the LiveKit Cloud agent demo-gen."""
    return publish.enabled() and bool((load(slug) or {}).get("published", {}).get("url"))


def publish_bg(slug, pages=True):
    """Publish in the background (a few seconds to a minute). Without Blob credentials the demo keeps its sandbox worker."""
    if not publish.enabled():
        start_worker(slug)
        return

    def run():
        try:
            publish.publish(slug, pages=pages)
        except Exception as e:  # noqa: BLE001 - recorded on the job; the sandbox copy keeps working meanwhile
            j = load(slug)
            if j:
                j["publish_error"] = scrub(str(e))[:300]; save(slug, j)
            start_worker(slug)
    threading.Thread(target=run, daemon=True).start()


def readable_claude(path, n=40):
    """stream-json -> short human lines (like gen/prog.py)."""
    ev = []
    try:
        for line in open(path, errors="ignore"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "assistant":
                for c in d["message"].get("content", []):
                    if c.get("type") == "text" and c["text"].strip():
                        ev.append("Claude: " + c["text"].strip().replace("\n", " ")[:300])
                    elif c.get("type") == "tool_use":
                        inp = c.get("input") or {}
                        what = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                        ev.append(f"  [{c['name']}] {str(what).splitlines()[0][:160] if what else ''}")
            elif d.get("type") == "result":
                ev.append("RESULT " + str(d.get("subtype")) + ": " + str(d.get("result", ""))[:1200])
    except OSError:
        pass
    return ev[-n:]


def scrub(text):
    """Belt and braces: never echo anything that looks like a key/token in a log tail."""
    return re.sub(r"(?i)(key|token|secret|authorization|bearer)([\"'=: ]+)[A-Za-z0-9._\-]{16,}", r"\1\2<redacted>", text)


def public_base(req):
    host = req.headers.get("X-Forwarded-Host") or req.host
    return f"https://{host}"


def view(req, slug, j):
    j = refresh(slug, j)
    base = public_base(req)
    out = {k: j.get(k) for k in ("slug", "brand", "url", "mode", "status", "code", "concept", "created", "finished", "images", "edits")}
    out["persona"] = persona(slug)
    out["preview"] = f"{base}/v2/{slug}/?code={urllib.parse.quote(j['code'])}" if j.get("status") == "done" else None
    pub = j.get("published") or {}
    out["hosted"] = bool(pub.get("url")) and publish.enabled()
    if out["hosted"]:
        out["preview"] = pub["url"]  # the persistent copy: works while this sandbox is stopped
    out["publish_error"] = j.get("publish_error")
    out["elapsed_s"] = int((j.get("finished") or time.time()) - j.get("created", time.time()))
    out["thumb"] = f"{base}/thumb/{slug}" if thumb_src(slug) else None
    return out


def persona(slug):
    """The agent's current name and voice, from the knowledge pack the worker loads."""
    try:
        s = json.load(open(os.path.join(WORK, slug, "knowledge", "site.json")))
        return {"assistant": s.get("assistant"), "voice": s.get("voice")}
    except (OSError, ValueError):
        return None


thumb_src = publish.thumb_src


def cors(resp):
    resp.headers.update({"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                         "Access-Control-Allow-Headers": "Content-Type", "Cache-Control": "no-store"})
    return resp


def jerr(status, msg):
    return cors(web.json_response({"error": msg}, status=status))


async def options(req):
    return cors(web.Response())


async def demos(req):
    items = []
    if os.path.isdir(WORK):
        for slug in os.listdir(WORK):
            j = load(slug)
            if j:
                items.append(view(req, slug, j))
    items.sort(key=lambda x: x.get("created") or 0, reverse=True)
    return cors(web.json_response({"demos": items, "claude_login_expires": claude_expiry()}))


def claude_expiry():
    """Only the expiry timestamp of the seeded Claude login (no token content leaves this function)."""
    try:
        return json.load(open("/vercel/.claude/.credentials.json"))["claudeAiOauth"].get("expiresAt")
    except Exception:
        return None


async def generate(req):
    try:
        f = await req.json()
    except Exception:
        return jerr(400, "send JSON")
    need = build_code()
    if need and not login_gated(req) and (f.get("build_code") or "").strip() != need:
        return jerr(403, "wrong builder code")
    url = (f.get("url") or "").strip()
    if not re.match(r"^https?://[^\s/$.?#][^\s]*$", url):
        return jerr(400, "enter a full website URL (https://...)")
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost",) or re.match(r"^(127\.|10\.|192\.168\.|169\.254\.|0\.)", host) or host.endswith(".internal"):
        return jerr(400, "public websites only")
    brand = (f.get("brand") or "").strip()[:80] or host.removeprefix("www.").split(".")[0].title()
    slug = re.sub(r"[^a-z0-9-]", "", (f.get("slug") or brand).lower().replace(" ", "-"))[:40].strip("-")
    if len(slug) < 2 or slug in RESERVED:
        return jerr(400, "pick another slug")
    mode = "claude" if f.get("mode") == "claude" else "quick"
    concept = (f.get("concept") or "").strip()[:4000]
    assistant = re.sub(r"[^\w .'-]", "", (f.get("assistant") or "").strip())[:40]
    voice = (f.get("voice") or "").strip().lower()
    if voice not in ("", "female", "male"):
        return jerr(400, "voice is female or male")
    old = load(slug)
    if old and refresh(slug, old).get("status") == "running":
        return jerr(409, f"{slug} is already building")
    running = [s for s in os.listdir(WORK) if (load(s) or {}).get("status") == "running"] if os.path.isdir(WORK) else []
    if len(running) >= MAX_RUNNING:
        return jerr(429, f"{len(running)} builds are already running ({', '.join(running)}); try again later")
    if mode == "claude" and (claude_expiry() or 0) < time.time() * 1000 + 30 * 60 * 1000:
        return jerr(503, "the Claude login in the build sandbox has expired; use quick mode or ask Nabil to re-seed it")
    work = os.path.join(WORK, slug)
    os.makedirs(work, exist_ok=True)
    code = slug.upper() + "-DEMO"
    cmd = [PY, os.path.join(GEN, "generate_demo.py"), url, slug, "--brand", brand, "--code", code, "--mode", mode, "--wait"]
    if not f.get("images"):
        cmd += ["--skip", "images"]
    if assistant:
        cmd += ["--assistant", assistant]
    if voice:
        cmd += ["--voice", voice]
    pj = os.path.join(work, "ref", "persona.json")
    if not (assistant or voice) and os.path.exists(pj):
        os.remove(pj)  # a previous build's persona: this build has none
    cf = os.path.join(work, "concept.txt")
    if concept:
        open(cf, "w").write(concept + "\n"); cmd += ["--concept-file", cf]
    elif os.path.exists(cf):
        os.remove(cf)
    log = open(os.path.join(work, "job.log"), "w")
    p = subprocess.Popen(cmd, cwd=GEN, env={**os.environ, **BUILD_ENV}, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    PROCS[slug] = p
    j = {"slug": slug, "brand": brand, "url": url, "mode": mode, "code": code, "concept": concept, "images": bool(f.get("images")),
         "status": "running", "created": int(time.time()), "pid": p.pid}
    save(slug, j)
    return cors(web.json_response(view(req, slug, j)))


async def edit(req):
    """Change a finished demo in about a minute instead of rebuilding it (generator-v2/edit_demo.py does the work)."""
    import asyncio
    slug = req.match_info["slug"]
    try:
        f = await req.json()
    except Exception:
        return jerr(400, "send JSON")
    need = build_code()
    if need and (f.get("build_code") or "").strip() != need:
        return jerr(403, "wrong builder code")
    j = load(slug)
    if not j or refresh(slug, j).get("status") != "done":
        return jerr(409, "only a finished demo can be edited")
    if j.get("editing") and time.time() - j["editing"] < 600:
        return jerr(409, "an edit is already running")
    assistant = re.sub(r"[^\w .'-]", "", (f.get("assistant") or "").strip())[:40]
    voice = (f.get("voice") or "").strip().lower()
    change = (f.get("change") or "").strip()[:2000]
    if voice not in ("", "female", "male"):
        return jerr(400, "voice is female or male")
    if not (assistant or voice or change):
        return jerr(400, "nothing to change")
    cmd = [PY, os.path.join(GEN, "edit_demo.py"), slug, "--brand", j["brand"], "--code", j["code"]]
    for k, v in (("--assistant", assistant), ("--voice", voice), ("--change", change)):
        if v:
            cmd += [k, v]
    j["editing"] = int(time.time()); save(slug, j)
    try:
        p = await asyncio.to_thread(subprocess.run, cmd, cwd=GEN, env={**os.environ, **BUILD_ENV}, capture_output=True, text=True, timeout=540)
    finally:
        j = load(slug); j.pop("editing", None); save(slug, j)
    open(os.path.join(WORK, slug, "edit.log"), "a").write(p.stderr[-20000:] + p.stdout)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return jerr(500, "the edit failed: " + scrub(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "no output")[:300])
    if hosted(slug):  # the hosted agent picks the new pack up on the next call; pages too if the edit rebuilt them
        try:
            await asyncio.to_thread(publish.publish, slug, any(c.startswith("site") for c in res.get("changed") or []))
        except Exception as e:  # noqa: BLE001
            return jerr(502, "edited, but publishing it failed: " + scrub(str(e))[:200])
    else:
        await asyncio.to_thread(stop_worker, slug)
        start_worker(slug)
    j = load(slug)
    j.setdefault("edits", []).append({"at": int(time.time()), "assistant": assistant, "voice": voice, "change": change, "summary": res.get("summary")})
    save(slug, j)
    return cors(web.json_response({**view(req, slug, j), "summary": res.get("summary"), "changed": res.get("changed")}))


async def delete(req):
    """Take a demo down: stop its voice worker and move its folder to work/.deleted/<slug>-<time> (restore = move it back)."""
    import asyncio, shutil
    slug = req.match_info["slug"]
    try:
        f = await req.json()
    except Exception:
        return jerr(400, "send JSON")
    need = build_code()
    if need and (f.get("build_code") or "").strip() != need:
        return jerr(403, "wrong builder code")
    j = load(slug)
    if not j or not re.match(r"^[a-z0-9-]+$", slug):
        return jerr(404, "no such demo")
    if refresh(slug, j).get("status") == "running" or j.get("editing"):
        return jerr(409, "it is still building or being edited; try again when it's done")
    if (j.get("published") or {}) and publish.enabled():
        try:
            await asyncio.to_thread(publish.node, "delete", slug)
        except Exception as e:  # noqa: BLE001
            return jerr(502, "could not take it off the hosted copy: " + scrub(str(e))[:200])
    await asyncio.to_thread(stop_worker, slug)
    dst = os.path.join(WORK, ".deleted", f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(os.path.join(WORK, slug), dst)
    PROCS.pop(slug, None)
    if publish.enabled():
        await asyncio.to_thread(publish.index)
    return cors(web.json_response({"deleted": slug}))


async def job(req):
    slug = req.match_info["slug"]
    j = load(slug)
    if not j:
        return jerr(404, "no such build")
    out = view(req, slug, j)
    lines = []
    lp = os.path.join(WORK, slug, "job.log")
    if os.path.exists(lp):
        lines += open(lp, errors="ignore").read()[-6000:].splitlines()[-60:]
    if j.get("mode") == "claude":
        lines += readable_claude(os.path.join(WORK, slug, "claude.log"))
    out["log"] = scrub("\n".join(lines))
    return cors(web.json_response(out))


async def thumb(req):
    slug = req.match_info["slug"]
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise web.HTTPNotFound()
    out = publish.make_thumb(slug)
    if not out:
        raise web.HTTPNotFound()
    return web.FileResponse(out, headers={"Cache-Control": "max-age=120", "Access-Control-Allow-Origin": "*"})


async def token(req):
    from livekit import api
    m = re.match(r"^([a-z0-9-]+?)-grok$", req.query.get("brain", ""))
    slug = m.group(1) if m else None
    if not slug:
        m = re.search(r"/v2/([a-z0-9-]+)/", req.headers.get("Referer", ""))
        slug = m.group(1) if m else None
    if not slug or not os.path.isdir(os.path.join(WORK, slug)):
        raise web.HTTPBadRequest(text="unknown demo")
    start_worker(slug)
    room = f"gen-{slug}-" + secrets.token_hex(3)
    t = (api.AccessToken().with_identity("customer").with_name("Customer").with_ttl(datetime.timedelta(hours=2))
         .with_grants(api.VideoGrants(room_join=True, room=room, can_update_own_metadata=True))
         .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=f"gen-{slug}")])))
    return web.json_response({"url": os.environ["LIVEKIT_URL"], "token": t.to_jwt(), "room": room}, headers={"Cache-Control": "no-store"})


async def static(req):
    m = re.match(r"^/v2/([a-z0-9-]+)(/.*)?$", req.path)
    if not m:
        raise web.HTTPNotFound()
    slug, rel = m.group(1), (m.group(2) or "/")
    if hosted(slug) and req.host.split(":")[0] not in ("localhost", "127.0.0.1"):  # builds/verify use localhost
        q = ("?" + req.query_string) if req.query_string else ""
        raise web.HTTPFound(f"{publish.PUBLIC}/v2/{slug}{rel}{q}")
    if rel == "/" and not req.path.endswith("/"):
        raise web.HTTPFound(req.path + "/" + (("?" + req.query_string) if req.query_string else ""))
    site = os.path.join(WORK, slug, "site")
    p = os.path.normpath(os.path.join(site, rel.lstrip("/")))
    if not p.startswith(site):
        raise web.HTTPForbidden()
    for c in (p, os.path.join(p, "index.html")):
        if os.path.isfile(c):
            return web.FileResponse(c, headers={"Cache-Control": "no-store"})
    raise web.HTTPNotFound()


async def index(req):
    rows = ""
    if os.path.isdir(WORK):
        for slug in sorted(os.listdir(WORK)):
            j = load(slug)
            if j:
                v = view(req, slug, j)
                link = f' <a href="{html.escape(v["preview"])}">open</a> (code {html.escape(v["code"])})' if v["preview"] else ""
                rows += f"<li><b>{html.escape(v['brand'])}</b> /v2/{slug}/ [{v['mode']}] {v['status']}{link}</li>"
    return web.Response(content_type="text/html", text=f"<!doctype html><meta charset=utf-8><title>LiveKit demo generator (sandbox)</title>"
        f"<body style='font:15px system-ui;max-width:800px;margin:40px auto;background:#070707;color:#e8e9eb'><h2>LiveKit demo generator: build host</h2>"
        f"<p>This is the build backend. Start builds from the main demo page (the sparkle <i>Generate a demo</i> button).</p><ul>{rows}</ul>")


async def on_start(app):
    os.makedirs(WORK, exist_ok=True)
    for slug in os.listdir(WORK):  # new session: bring the voice workers of finished demos back
        j = load(slug)
        if j and refresh(slug, j).get("status") == "done" and not hosted(slug):
            publish_bg(slug)  # publishes it (or, without Blob credentials, starts its sandbox worker as before)


app = web.Application()
app.on_startup.append(on_start)
app.add_routes([web.get("/", index), web.get("/api/demos", demos), web.post("/api/generate", generate), web.get("/api/jobs/{slug}", job),
                web.post("/api/demos/{slug}/edit", edit), web.post("/api/demos/{slug}/delete", delete),
                web.get("/thumb/{slug}", thumb), web.get("/api/token", token), web.route("OPTIONS", "/api/{tail:.*}", options),
                web.route("*", "/v2/{tail:.*}", static)])
if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)
