"""LiveKit demo generator - PRODUCT LAYER (accounts, analytics, session replay, branded "demo ready" email).

Loaded by host/product_main.py, which imports server.py UNCHANGED and calls install(app, server) before run_app, so the
build controller keeps working exactly as before if this file is missing or broken (product_main falls back).

Routes (all JSON bodies; no custom headers, so server.py's existing CORS preflight already allows them):
  GET  /api/p/config                    -> {google_client_id, email_login, mailer}           (public)
  POST /api/p/auth/google {credential}  -> verifies a Google Identity Services ID token -> {session, user}
  POST /api/p/auth/email  {email,name}  -> lightweight UNVERIFIED sign-in (fallback while Google isn't configured)
  POST /api/p/me          {session}     -> the person's "My demos": builds they started + their demo sessions
  POST /api/p/event       {session|uid, events:[...]}     (tracker on generated demos + main page)
  POST /api/p/replay/<sid> {events:[...]}                  (rrweb chunks from generated demos, same origin)
  POST /api/p/analytics   {session|code}                   -> dashboard data (admins only)
  POST /api/p/replay-get/<sid> {session|code}              -> rrweb events for the player (admins only)
  GET  /api/p/email-preview?slug=<slug>                    -> the branded email rendered with sample/real data
  GET  /p/track.js, /p/rrweb-record.min.js                 -> tracker injected into every generated demo page

Middleware: (1) POST /api/generate -> records the signed-in owner of the build (body field lk_session);
            (2) /v2/<slug>/*.html -> injects <script src="/p/track.js"> before </body> (files on disk untouched).
Background loop (30 s): owned builds that finished -> branded HTML email to the owner (idempotent).
Patch: server.notify (if present) sends its notify_email through the same branded HTML template.

Env (in /vercel/gen/.product.env, never committed):
  GOOGLE_CLIENT_ID      OAuth 2.0 Web client id (public id, not a secret); origin https://live-demos-sa.vercel.app
  ADMIN_EMAILS          comma list of Google-verified emails that may open /analytics/ (default: any @ADMIN_DOMAIN)
  ADMIN_DOMAIN          default livekit.io
  ALLOW_EMAIL_LOGIN     1 (default) = allow the unverified email sign-in fallback; 0 = Google only
  RESEND_API_KEY / NOTIFY_FROM, or NOTIFY_SMTP_HOST/PORT/USER/PASS + NOTIFY_FROM   (same as server.py notify)
  POSTHOG_KEY, POSTHOG_HOST optional: also send events + PostHog session recording from the demos
  PUBLIC_BASE           default https://sb-mgs5l8pw3lep.vercel.run (used in emails)
Store: /vercel/gen/product/ (users.json, owners.json, emailed.json, events/<day>.jsonl, replays/<sid>.jsonl, .secret,
       .analytics_code). Nothing here reads Claude/Gemini/LiveKit credential files.
"""
import asyncio, base64, glob, hashlib, hmac, html, json, os, re, secrets, smtplib, time, urllib.parse, urllib.request
from email.message import EmailMessage
from aiohttp import web

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("GEN_HOME", "/vercel/gen")
STORE = os.environ.get("PRODUCT_STORE", os.path.join(ROOT, "product"))
STATIC = os.path.join(HERE, "product_static")
MAIN_SITE = "https://live-demos-sa.vercel.app"
LOGO = MAIN_SITE + "/lk/livekit-wordmark.png"
REPLAY_CAP = 30 * 1024 * 1024
S = None  # the server.py module
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[a-z]{2,}$", re.I)
SID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


# ---------------- store ----------------
def p(*a):
    return os.path.join(STORE, *a)


def rj(name, default):
    try:
        return json.load(open(p(name)))
    except (OSError, ValueError):
        return default


def wj(name, data):
    tmp = p(name + ".tmp")
    json.dump(data, open(tmp, "w"), indent=1)
    os.replace(tmp, p(name))


def secret_file(name, n=32):
    f = p(name)
    if not os.path.exists(f):
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, secrets.token_urlsafe(n).encode()); os.close(fd)
    return open(f).read().strip()


def log_event(ev):
    day = time.strftime("%Y-%m-%d", time.gmtime(ev.get("ts", time.time())))
    with open(p("events", day + ".jsonl"), "a") as f:
        f.write(json.dumps(ev, separators=(",", ":")) + "\n")


def read_events(days=30):
    out = []
    for fn in sorted(glob.glob(p("events", "*.jsonl")))[-days:]:
        for line in open(fn, errors="ignore"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


# ---------------- sessions (HMAC-signed, stateless) ----------------
def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload):
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = b64(hmac.new(secret_file(".secret").encode(), body.encode(), hashlib.sha256).digest()[:24])
    return body + "." + mac


def verify(tok):
    try:
        body, mac = (tok or "").split(".")
        good = b64(hmac.new(secret_file(".secret").encode(), body.encode(), hashlib.sha256).digest()[:24])
        if not hmac.compare_digest(mac, good):
            return None
        d = json.loads(unb64(body))
        return d if d.get("x", 0) > time.time() else None
    except Exception:
        return None


def user_of(d):
    return {"email": d["e"], "name": d.get("n") or d["e"].split("@")[0], "picture": d.get("p"), "verified": bool(d.get("v")),
            "method": d.get("m"), "admin": is_admin(d)}


def is_admin(d):
    if not d or not d.get("v"):
        return False
    e = d["e"].lower()
    allow = [x.strip().lower() for x in os.getenv("ADMIN_EMAILS", "").split(",") if x.strip()]
    if allow:
        return e in allow
    return e.endswith("@" + os.getenv("ADMIN_DOMAIN", "livekit.io").lower())


def issue(email, name, picture, verified, method):
    email = email.strip().lower()
    users = rj("users.json", {})
    u = users.get(email) or {"email": email, "first_seen": int(time.time()), "logins": 0}
    u.update({"name": name or u.get("name") or email.split("@")[0], "picture": picture or u.get("picture"),
              "verified": bool(verified) or bool(u.get("verified")), "method": method, "last_login": int(time.time())})
    u["logins"] = u.get("logins", 0) + 1
    users[email] = u; wj("users.json", users)
    log_event({"t": "login", "ts": int(time.time()), "uid": email, "name": u["name"], "method": method, "verified": bool(verified)})
    d = {"e": email, "n": u["name"], "p": picture, "v": bool(verified), "m": method, "x": int(time.time()) + 30 * 86400}
    return sign(d), user_of(d)


def view_token(d):
    """Scoped token appended to generated-demo links (lk_u=...): only attributes analytics events, can't read anything."""
    return sign({"e": d["e"], "n": d.get("n"), "v": d.get("v"), "s": "view", "x": int(time.time()) + 30 * 86400})


def full(tok):
    d = verify(tok)
    return d if d and d.get("s") != "view" else None


def cj(data, status=200):
    return S.cors(web.json_response(data, status=status))


async def body(req):
    try:
        raw = await req.read()
        return json.loads(raw or b"{}")
    except Exception:
        return {}


# ---------------- auth ----------------
async def config(req):
    return cj({"google_client_id": os.getenv("GOOGLE_CLIENT_ID", ""), "email_login": os.getenv("ALLOW_EMAIL_LOGIN", "1") != "0",
               "mailer": mailer_name(), "posthog_key": os.getenv("POSTHOG_KEY", ""), "posthog_host": os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")})


def _google_tokeninfo(cred):
    u = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(cred)
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def auth_google(req):
    cid = os.getenv("GOOGLE_CLIENT_ID", "")
    if not cid:
        return cj({"error": "Google sign-in isn't configured yet (GOOGLE_CLIENT_ID)"}, 503)
    f = await body(req)
    try:
        info = await asyncio.get_running_loop().run_in_executor(None, _google_tokeninfo, f.get("credential", ""))
    except Exception:
        return cj({"error": "Google didn't accept that sign-in; try again"}, 401)
    if info.get("aud") != cid or info.get("iss") not in ("accounts.google.com", "https://accounts.google.com") \
            or str(info.get("email_verified")).lower() != "true" or int(info.get("exp", 0)) < time.time():
        return cj({"error": "that Google sign-in couldn't be verified"}, 401)
    tok, user = issue(info["email"], info.get("name"), info.get("picture"), True, "google")
    return cj({"session": tok, "view": view_token(verify(tok)), "user": user})


async def auth_email(req):
    if os.getenv("ALLOW_EMAIL_LOGIN", "1") == "0":
        return cj({"error": "email sign-in is off; use Google"}, 403)
    f = await body(req)
    e = (f.get("email") or "").strip()[:200]
    if not EMAIL_RE.match(e):
        return cj({"error": "enter a valid email"}, 400)
    tok, user = issue(e, (f.get("name") or "").strip()[:80], None, False, "email")
    return cj({"session": tok, "view": view_token(verify(tok)), "user": user})


def owners():
    return rj("owners.json", {})


def demo_view(req, slug):
    j = S.load(slug)
    if not j:
        return None
    v = S.view(req, slug, j)
    o = owners().get(slug)
    if o and o.get("created") == j.get("created"):
        v["owner"] = {"email": o["email"], "name": o.get("name")}
    return v


async def me(req):
    f = await body(req)
    d = full(f.get("session"))
    if not d:
        return cj({"error": "signed out"}, 401)
    mine = []
    for slug, o in owners().items():
        if o.get("email") == d["e"]:
            v = demo_view(req, slug)
            if v and v.get("owner"):
                mine.append(v)
    mine.sort(key=lambda x: x.get("created") or 0, reverse=True)
    sess = [s for s in sessions(read_events()) if s["uid"] == d["e"]][:50]
    return cj({"user": user_of(d), "view": view_token(d), "demos": mine, "sessions": sess})


# ---------------- events + replay ----------------
EV_TYPES = {"open", "hb", "voice_start", "voice_end", "page", "gallery_open", "generate_click", "unload"}


async def event(req):
    f = await body(req)
    d = verify(f.get("session")) if f.get("session") else None
    uid = d["e"] if d else re.sub(r"[^a-zA-Z0-9_@.+-]", "", str(f.get("uid") or ""))[:120] or "anon"
    name = d.get("n") if d else (str(f.get("name") or "")[:80] or None)
    now = int(time.time())
    for e in (f.get("events") or [])[:50]:
        if not isinstance(e, dict) or e.get("t") not in EV_TYPES:
            continue
        ev = {"t": e["t"], "ts": now, "uid": uid, "name": name, "verified": bool(d and d.get("v"))}
        for k in ("slug", "sid", "path", "title", "voice_s", "active_s", "demo", "href", "where"):
            if k in e:
                ev[k] = str(e[k])[:300] if not isinstance(e[k], (int, float)) else e[k]
        log_event(ev)
    return cj({"ok": True})


async def replay_put(req):
    sid = req.match_info["sid"]
    if not SID_RE.match(sid):
        return cj({"error": "bad sid"}, 400)
    raw = await req.read()
    fn = p("replays", sid + ".jsonl")
    if len(raw) > 4 * 1024 * 1024 or (os.path.exists(fn) and os.path.getsize(fn) > REPLAY_CAP):
        return cj({"ok": False, "capped": True})
    try:
        f = json.loads(raw)
        evs = f.get("events") or []
        meta = {"slug": str(f.get("slug") or "")[:60], "uid": str(f.get("uid") or "")[:120]}
    except ValueError:
        return cj({"error": "bad json"}, 400)
    with open(fn, "a") as out:
        if os.path.getsize(fn) == 0:
            out.write(json.dumps({"_meta": meta, "ts": int(time.time())}) + "\n")
        for e in evs:
            out.write(json.dumps(e, separators=(",", ":")) + "\n")
    return cj({"ok": True})


def admin_ok(f):
    d = full(f.get("session")) if f.get("session") else None
    if is_admin(d):
        return True
    code = (f.get("code") or "").strip()
    return bool(code) and hmac.compare_digest(code, secret_file(".analytics_code", 9))


async def replay_get(req):
    f = await body(req)
    if not admin_ok(f):
        return cj({"error": "analytics is for admins"}, 403)
    sid = req.match_info["sid"]
    fn = p("replays", sid + ".jsonl")
    if not SID_RE.match(sid) or not os.path.exists(fn):
        return cj({"error": "no replay"}, 404)
    evs = []
    for line in open(fn, errors="ignore"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if "_meta" not in e:
            evs.append(e)
    evs.sort(key=lambda e: e.get("timestamp", 0))
    return S.cors(web.json_response({"events": evs}, dumps=lambda o: json.dumps(o, separators=(",", ":"))))


def sessions(events):
    by = {}
    for e in events:
        sid = e.get("sid")
        if not sid:
            continue
        s = by.setdefault(sid, {"sid": sid, "uid": e["uid"], "name": e.get("name"), "slug": e.get("slug"), "start": e["ts"], "last": e["ts"],
                                "voice_s": 0, "active_s": 0, "pages": set(), "voice_calls": 0, "verified": e.get("verified")})
        if e["uid"] != "anon" and (s["uid"] == "anon" or "@" in e["uid"]):
            s["uid"], s["name"], s["verified"] = e["uid"], e.get("name") or s["name"], e.get("verified")
        s["start"], s["last"] = min(s["start"], e["ts"]), max(s["last"], e["ts"])
        s["slug"] = s["slug"] or e.get("slug")
        if e.get("path"):
            s["pages"].add(e["path"])
        for k in ("voice_s", "active_s"):
            if isinstance(e.get(k), (int, float)):
                s[k] = max(s[k], int(e[k]))
        if e["t"] == "voice_start":
            s["voice_calls"] += 1
    out = []
    for s in by.values():
        s["pages"] = sorted(s["pages"])[:30]
        s["duration_s"] = max(s["last"] - s["start"], s["active_s"])
        s["replay"] = os.path.exists(p("replays", s["sid"] + ".jsonl"))
        s["replay_kb"] = int(os.path.getsize(p("replays", s["sid"] + ".jsonl")) / 1024) if s["replay"] else 0
        out.append(s)
    out.sort(key=lambda s: s["start"], reverse=True)
    return out


async def analytics(req):
    f = await body(req)
    if not admin_ok(f):
        return cj({"error": "analytics is for admins: sign in with a LiveKit Google account or enter the analytics code"}, 403)
    evs = read_events()
    sess = [s for s in sessions(evs) if s.get("slug")]
    users = rj("users.json", {})
    logins = [e for e in evs if e["t"] == "login"][-300:][::-1]
    demos = []
    if os.path.isdir(S.WORK):
        for slug in os.listdir(S.WORK):
            v = demo_view(req, slug)
            if v:
                v["sessions"] = sum(1 for s in sess if s["slug"] == slug)
                v["voice_s"] = sum(s["voice_s"] for s in sess if s["slug"] == slug)
                demos.append(v)
    demos.sort(key=lambda x: x.get("created") or 0, reverse=True)
    gallery = {}
    for e in evs:
        if e["t"] == "gallery_open":
            g = gallery.setdefault(e.get("demo") or "?", {"demo": e.get("demo"), "opens": 0, "people": set(), "last": 0})
            g["opens"] += 1; g["people"].add(e["uid"]); g["last"] = max(g["last"], e["ts"])
    gal = sorted(({**g, "people": len(g["people"])} for g in gallery.values()), key=lambda g: -g["opens"])
    people = {}
    for e, u in users.items():
        people[e] = {"email": e, "name": u.get("name"), "picture": u.get("picture"), "verified": u.get("verified"), "method": u.get("method"),
                     "first_seen": u.get("first_seen"), "last_login": u.get("last_login"), "logins": u.get("logins", 0),
                     "built": [], "ran": {}, "time_s": 0, "voice_s": 0}
    for v in demos:
        o = v.get("owner")
        if o and o["email"] in people:
            people[o["email"]]["built"].append(v["slug"])
    for s in sess:
        if s["uid"] in people:
            pp = people[s["uid"]]; pp["ran"][s["slug"]] = pp["ran"].get(s["slug"], 0) + 1
            pp["time_s"] += s["duration_s"]; pp["voice_s"] += s["voice_s"]
    ppl = sorted(people.values(), key=lambda x: -(x.get("last_login") or 0))
    kpi = {"people": len(users), "builds": len(demos), "builds_done": sum(1 for d in demos if d["status"] == "done"),
           "sessions": len(sess), "voice_min": round(sum(s["voice_s"] for s in sess) / 60, 1),
           "demo_min": round(sum(s["duration_s"] for s in sess) / 60, 1), "logins_7d": sum(1 for e in logins if e["ts"] > time.time() - 7 * 86400)}
    return cj({"kpi": kpi, "people": ppl, "logins": logins[:100], "demos": demos, "sessions": sess[:300], "gallery": gal,
               "posthog": bool(os.getenv("POSTHOG_KEY")), "generated_at": int(time.time())})


# ---------------- branded email ----------------
def mailer_name():
    if os.getenv("NOTIFY_SMTP_HOST") and os.getenv("NOTIFY_FROM"):
        return "smtp"
    if os.getenv("RESEND_API_KEY") and os.getenv("NOTIFY_FROM"):
        return "resend"
    return None


def public_base():
    return os.getenv("PUBLIC_BASE", "https://sb-mgs5l8pw3lep.vercel.run").rstrip("/")


def render_email(j, to_name=None, lk_u=None):
    tpl = open(os.path.join(HERE, "email_demo_ready.html")).read()
    base = public_base()
    link = f"{base}/v2/{j['slug']}/?code={urllib.parse.quote(j['code'])}" + (f"&lk_u={lk_u}" if lk_u else "")
    thumb = f"{base}/thumb/{j['slug']}" if S and S.thumb_src(j["slug"]) else ""
    mins = max(1, int(((j.get("finished") or time.time()) - j.get("created", time.time())) / 60))
    host = urllib.parse.urlparse(j.get("url") or "").hostname or ""
    vals = {"BRAND": j["brand"], "LINK": link, "CODE": j["code"], "SOURCE": host.removeprefix("www."), "SOURCE_URL": j.get("url", ""),
            "MODE": "Claude Code (high fidelity)" if j.get("mode") == "claude" else "Quick", "MINUTES": str(mins),
            "HELLO": ("Hi " + to_name.split()[0] + ",") if to_name else "Hi there,", "THUMB": thumb, "LOGO": LOGO,
            "MAIN": MAIN_SITE, "ACCOUNT": MAIN_SITE + "/account/", "CONCEPT": (j.get("concept") or "")[:220]}
    out = tpl
    for k, v in vals.items():
        out = out.replace("{{" + k + "}}", html.escape(str(v), quote=True))
    out = re.sub(r"<!--IF_THUMB-->(.*?)<!--/IF_THUMB-->", r"\1" if thumb else "", out, flags=re.S)
    out = re.sub(r"<!--IF_CONCEPT-->(.*?)<!--/IF_CONCEPT-->", r"\1" if vals["CONCEPT"] else "", out, flags=re.S)
    text = (f"{vals['HELLO']}\n\nYour LiveKit voice demo for {j['brand']} is ready.\n\nOpen it: {link}\nAccess code: {j['code']}\n\n"
            f"Built from {vals['SOURCE']} in {mins} min ({vals['MODE']}). Click 'Talk to LiveKit' on any page to start a voice session.\n"
            f"All your demos: {MAIN_SITE}/account/\n\n- LiveKit demo generator")
    return f"Your {j['brand']} voice demo is ready", out, text


def send_html(to, subj, html_body, text_body):
    sender = os.getenv("NOTIFY_FROM", "")
    if os.getenv("NOTIFY_SMTP_HOST") and sender:
        m = EmailMessage(); m["From"], m["To"], m["Subject"] = sender, to, subj
        m.set_content(text_body); m.add_alternative(html_body, subtype="html")
        with smtplib.SMTP(os.environ["NOTIFY_SMTP_HOST"], int(os.getenv("NOTIFY_SMTP_PORT", 587)), timeout=20) as s:
            s.starttls()
            if os.getenv("NOTIFY_SMTP_USER"):
                s.login(os.environ["NOTIFY_SMTP_USER"], os.getenv("NOTIFY_SMTP_PASS", ""))
            s.send_message(m)
        return "smtp"
    if os.getenv("RESEND_API_KEY") and sender:
        r = urllib.request.Request("https://api.resend.com/emails", method="POST",
            data=json.dumps({"from": sender, "to": [to], "subject": subj, "html": html_body, "text": text_body}).encode(),
            headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"], "Content-Type": "application/json"})
        urllib.request.urlopen(r, timeout=20).read()
        return "resend"
    raise LookupError("no email credential (set RESEND_API_KEY+NOTIFY_FROM or NOTIFY_SMTP_HOST+NOTIFY_FROM[+USER/PASS])")


def email_owner(slug, j):
    """Branded email to the signed-in person who started the build. Idempotent per build (slug+created)."""
    o = owners().get(slug)
    if not o or o.get("created") != j.get("created") or j.get("status") != "done":
        return
    key = f"{slug}:{j.get('created')}"
    sent = rj("emailed.json", {})
    if key in sent:
        return
    if (j.get("notify") or {}).get("email", "").lower() == o["email"]:  # server.notify sends it (branded, via the patch)
        sent[key] = {"ts": int(time.time()), "to": o["email"], "via": "notify"}; wj("emailed.json", sent); return
    subj, h, t = render_email(j, o.get("name"), view_token({"e": o["email"], "n": o.get("name"), "v": o.get("verified")}))
    try:
        via = send_html(o["email"], subj, h, t)
        sent[key] = {"ts": int(time.time()), "to": o["email"], "via": via}
    except Exception as e:  # noqa: BLE001
        sent[key] = {"ts": int(time.time()), "to": o["email"], "via": "queued", "reason": str(e)[:200]}
        with open(p("email_queue.jsonl"), "a") as q:
            q.write(json.dumps({"ts": int(time.time()), "slug": slug, "to": o["email"], "subject": subj, "reason": str(e)[:200]}) + "\n")
    wj("emailed.json", sent)
    log_event({"t": "build_done", "ts": int(time.time()), "uid": o["email"], "name": o.get("name"), "slug": slug, "email": sent[key]["via"]})
    print(f"product: owner email {slug} -> {sent[key]['via']}", flush=True)


async def watcher(app):
    async def loop():
        while True:
            await asyncio.sleep(30)
            try:
                for slug in list(owners()):
                    j = S.load(slug)
                    if j:
                        j = S.refresh(slug, j)
                        email_owner(slug, j)
            except Exception as e:  # noqa: BLE001
                print("product watcher:", e, flush=True)
    app["product_watcher"] = asyncio.create_task(loop())


def patch_notify():
    """server.notify (other worker's notify-on-done) -> its email goes out with the branded template too."""
    if not hasattr(S, "notify") or getattr(S.notify, "_branded", False):
        return
    orig = S.notify

    def notify(slug, j):
        if j.get("status") != "done":
            return orig(slug, j)
        n = j.get("notify") or {}
        orig_send = getattr(S, "send_email", None)
        o = owners().get(slug) or {}

        def branded(to, subj, body):
            mine = o.get("email") == to.lower() and o.get("created") == j.get("created")
            s2, h, t = render_email(j, o.get("name") if mine else None,
                                    view_token({"e": o["email"], "n": o.get("name"), "v": o.get("verified")}) if mine else None)
            return send_html(to, s2, h, t)
        if n.get("email") and orig_send:
            S.send_email = branded
        try:
            return orig(slug, j)
        finally:
            if orig_send:
                S.send_email = orig_send
    notify._branded = True
    S.notify = notify


async def email_preview(req):
    slug = req.query.get("slug", "")
    j = S.load(slug) if re.match(r"^[a-z0-9-]+$", slug) else None
    if not j:
        j = {"slug": "hoxton-hosted", "brand": "The Hoxton", "code": "HOXTON-HOSTED-DEMO", "url": "https://thehoxton.com/",
             "mode": "claude", "created": time.time() - 3600, "finished": time.time(), "concept": ""}
    _, h, _ = render_email({**j, "status": "done"}, req.query.get("name") or "Nabil")
    return web.Response(text=h, content_type="text/html")


# ---------------- static tracker + middleware ----------------
async def static_p(req):
    name = req.match_info["name"]
    if name not in ("track.js", "rrweb-record.min.js"):
        raise web.HTTPNotFound()
    return web.FileResponse(os.path.join(STATIC, name), headers={"Cache-Control": "max-age=300", "Access-Control-Allow-Origin": "*",
                                                                 "Content-Type": "application/javascript"})


TAG = b'<script src="/p/track.js" defer data-lk-track="1"></script>'


@web.middleware
async def mw(req, handler):
    if req.method == "POST" and req.path == "/api/generate":
        try:
            f = json.loads(await req.read() or b"{}")
        except ValueError:
            f = {}
        resp = await handler(req)
        try:
            d = full(f.get("lk_session")) if f.get("lk_session") else None
            if d and resp.status == 200:
                out = json.loads(resp.body)
                slug = out["slug"]; j = S.load(slug) or {}
                own = owners(); own[slug] = {"email": d["e"], "name": d.get("n"), "verified": bool(d.get("v")), "created": j.get("created"),
                                             "ts": int(time.time())}
                wj("owners.json", own)
                log_event({"t": "build_start", "ts": int(time.time()), "uid": d["e"], "name": d.get("n"), "slug": slug,
                           "mode": j.get("mode"), "url": j.get("url")})
        except Exception as e:  # noqa: BLE001 - never break a build start
            print("product owner capture:", e, flush=True)
        return resp
    resp = await handler(req)
    if req.path.startswith("/v2/") and isinstance(resp, web.FileResponse) and resp.status == 200:
        fp = str(getattr(resp, "_path", ""))
        if fp.endswith(".html"):
            try:
                b = open(fp, "rb").read()
                if b"data-lk-track" not in b:
                    i = b.lower().rfind(b"</body>")
                    b = b[:i] + TAG + b[i:] if i >= 0 else b + TAG
                return web.Response(body=b, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-store"})
            except OSError:
                pass
    return resp


def install(app, server_module):
    global S
    S = server_module
    for d in ("", "events", "replays"):
        os.makedirs(p(d), exist_ok=True)
    secret_file(".secret"); secret_file(".analytics_code", 9)
    app.middlewares.append(mw)
    app.on_startup.append(watcher)
    patch_notify()
    app.add_routes([web.get("/api/p/config", config), web.post("/api/p/auth/google", auth_google), web.post("/api/p/auth/email", auth_email),
                    web.post("/api/p/me", me), web.post("/api/p/event", event), web.post("/api/p/replay/{sid}", replay_put),
                    web.post("/api/p/analytics", analytics), web.post("/api/p/replay-get/{sid}", replay_get),
                    web.get("/api/p/email-preview", email_preview), web.get("/p/{name}", static_p)])
    print("product layer installed (store %s, google=%s, mailer=%s)" % (STORE, bool(os.getenv("GOOGLE_CLIENT_ID")), mailer_name()), flush=True)
