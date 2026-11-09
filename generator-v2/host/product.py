"""LiveKit demo generator - PRODUCT LAYER (accounts, analytics, session replay, branded "demo ready" email).

Loaded by host/product_main.py, which imports server.py UNCHANGED and calls install(app, server) before run_app, so the
build controller keeps working exactly as before if this file is missing or broken (product_main falls back).

Routes (all JSON bodies; no custom headers, so server.py's existing CORS preflight already allows them):
  GET  /api/p/config                    -> {google_client_id, email_login, mailer}           (public)
  POST /api/p/auth/google {credential}  -> verifies a Google Identity Services ID token -> {session, user}
  POST /api/p/auth/clerk  {token}       -> verifies a Clerk session JWT (RS256 vs the instance JWKS) + reads the user's
                                           Google-verified email from the Clerk Backend API -> {session, user}
                                           (only ALLOWED_DOMAIN emails, default livekit.io; others -> 403 "LiveKit only")
  POST /api/p/auth/email  {email,name}  -> lightweight UNVERIFIED sign-in (fallback; OFF whenever Clerk is configured)
  POST /api/p/me          {session}     -> the person's "My demos": builds they started + their demo sessions
  POST /api/p/event       {session|uid, events:[...]}     (tracker on generated demos + main page)
  POST /api/p/replay/<sid> {events:[...]}                  (rrweb chunks from generated demos, same origin)
  POST /api/p/analytics   {session|code}                   -> dashboard data (admins only)
  POST /api/p/replay-get/<sid> {session|code}              -> rrweb events for the player (admins only)
                                                              + voice: [{room,t0,duration_s,url}] (signed 6 h audio URLs)
  POST /api/p/voice/<room>?slug&t0&dur  (audio/ogg)        <- the voice agent's call recording (HMAC with LIVEKIT_API_SECRET)
  GET  /api/p/voice-audio/<room>?k=<signed>                -> the OGG for the replay player (Range ok)
  GET  /api/p/email-preview?slug=<slug>                    -> the branded email rendered with sample/real data
  GET  /p/track.js, /p/rrweb-record.min.js                 -> tracker injected into every generated demo page

Middleware: (1) POST /api/generate -> records the signed-in owner of the build (body field lk_session);
            (2) /v2/<slug>/*.html -> injects <script src="/p/track.js"> before </body> (files on disk untouched).
Background loop (30 s): owned builds that finished -> branded HTML email to the owner (idempotent).
Patch: server.notify (if present) sends its notify_email through the same branded HTML template.

Env (in /vercel/gen/.product.env, never committed):
  CLERK_PUBLISHABLE_KEY / CLERK_SECRET_KEY   Clerk (dev instance: Sign in with Google via Clerk's shared OAuth app)
  ALLOWED_DOMAIN        default livekit.io - only these Google-verified emails may sign in / start builds
  REQUIRE_LOGIN         1 (default when Clerk is set) = POST /api/generate needs a signed-in ALLOWED_DOMAIN session
  BACKFILL_OWNER        default nabil.urrehman@livekit.io - demos with no owner are attributed to this person
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
    if not d or d.get("s") == "view":
        return None
    if require_login() and not (d.get("v") and domain_ok(d.get("e"))):
        return None
    return d


def cj(data, status=200):
    return S.cors(web.json_response(data, status=status))


async def body(req):
    try:
        raw = await req.read()
        return json.loads(raw or b"{}")
    except Exception:
        return {}


# ---------------- Clerk ----------------
def clerk_on():
    return bool(os.getenv("CLERK_SECRET_KEY") and os.getenv("CLERK_PUBLISHABLE_KEY"))


def clerk_fapi():
    pk = os.getenv("CLERK_PUBLISHABLE_KEY", "")
    try:
        return base64.b64decode(pk.split("_", 2)[2] + "==").decode().rstrip("$")
    except Exception:
        return ""


def allowed_domain():
    return os.getenv("ALLOWED_DOMAIN", "livekit.io").lower().lstrip("@")


def domain_ok(email):
    return bool(email) and email.lower().endswith("@" + allowed_domain())


def require_login():
    return os.getenv("REQUIRE_LOGIN", "1" if clerk_on() else "0") != "0"


_JWKS = {"t": 0, "keys": {}}


def _clerk_h():
    # Clerk's edge rejects the default Python-urllib user agent with 403
    return {"Authorization": "Bearer " + os.environ["CLERK_SECRET_KEY"], "User-Agent": "lk-demo-gen/1.0", "Accept": "application/json"}


def _jwks():
    if time.time() - _JWKS["t"] > 3600 or not _JWKS["keys"]:
        r = urllib.request.Request("https://api.clerk.com/v1/jwks", headers=_clerk_h())
        ks = json.loads(urllib.request.urlopen(r, timeout=10).read()).get("keys", [])
        _JWKS.update(t=time.time(), keys={k["kid"]: k for k in ks if k.get("kty") == "RSA"})
    return _JWKS["keys"]


_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _rs256_ok(signing_input, sig, jwk):
    """RSASSA-PKCS1-v1_5 / SHA-256 verification with the standard library only."""
    n = int.from_bytes(unb64(jwk["n"]), "big"); e = int.from_bytes(unb64(jwk["e"]), "big")
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = _SHA256_PREFIX + hashlib.sha256(signing_input).digest()
    want = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, want)


def clerk_verify(token):
    """-> claims of a valid, unexpired Clerk session token issued by OUR instance, else None."""
    try:
        h64, p64, s64 = token.split(".")
        hdr = json.loads(unb64(h64)); cl = json.loads(unb64(p64))
        if hdr.get("alg") != "RS256":
            return None
        jwk = _jwks().get(hdr.get("kid"))
        if not jwk or not _rs256_ok((h64 + "." + p64).encode(), unb64(s64), jwk):
            return None
        now = time.time()
        if cl.get("exp", 0) < now - 5 or cl.get("nbf", 0) > now + 5:
            return None
        if cl.get("iss") != "https://" + clerk_fapi():
            return None
        azp = cl.get("azp")
        okp = [x.strip() for x in os.getenv("CLERK_AUTHORIZED_PARTIES", "https://live-demos-sa.vercel.app,https://sb-mgs5l8pw3lep.vercel.run").split(",") if x.strip()]
        if azp and okp and azp not in okp:
            return None
        return cl
    except Exception:
        return None


def clerk_user(uid):
    r = urllib.request.Request("https://api.clerk.com/v1/users/" + urllib.parse.quote(uid), headers=_clerk_h())
    u = json.loads(urllib.request.urlopen(r, timeout=10).read())
    emails = u.get("email_addresses") or []
    prim = next((x for x in emails if x.get("id") == u.get("primary_email_address_id")), emails[0] if emails else None)
    if not prim:
        return None
    verified = (prim.get("verification") or {}).get("status") == "verified"
    google = any(a.get("provider") in ("oauth_google", "google") for a in (u.get("external_accounts") or []))
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or None
    return {"email": prim["email_address"].lower(), "name": name, "picture": u.get("image_url"), "verified": verified, "google": google}


async def auth_clerk(req):
    if not clerk_on():
        return cj({"error": "sign-in isn't configured yet (CLERK_SECRET_KEY)"}, 503)
    f = await body(req)
    loop = asyncio.get_running_loop()
    cl = await loop.run_in_executor(None, clerk_verify, str(f.get("token") or ""))
    if not cl or not cl.get("sub"):
        return cj({"error": "that sign-in couldn't be verified; try again"}, 401)
    try:
        u = await loop.run_in_executor(None, clerk_user, cl["sub"])
    except Exception:
        return cj({"error": "couldn't read your account from the sign-in service; try again"}, 502)
    if not u or not u["verified"]:
        return cj({"error": "your email isn't verified"}, 401)
    if not domain_ok(u["email"]):
        log_event({"t": "login_denied", "ts": int(time.time()), "uid": u["email"], "method": "clerk"})
        return cj({"error": "livekit_only", "message": f"The demo generator is LiveKit only for now. Sign in with your @{allowed_domain()} Google account."}, 403)
    tok, user = issue(u["email"], u["name"], u["picture"], True, "google" if u["google"] else "clerk")
    return cj({"session": tok, "view": view_token(verify(tok)), "user": user})


# ---------------- auth ----------------
async def config(req):
    return cj({"clerk_publishable_key": os.getenv("CLERK_PUBLISHABLE_KEY", "") if clerk_on() else "", "allowed_domain": allowed_domain(),
               "require_login": require_login(),
               "google_client_id": "" if clerk_on() else os.getenv("GOOGLE_CLIENT_ID", ""), "email_login": email_login_on(),
               "mailer": mailer_name(), "posthog_key": os.getenv("POSTHOG_KEY", ""), "posthog_host": os.getenv("POSTHOG_HOST", "https://us.i.posthog.com"), "now": time.time()})


def email_login_on():
    return os.getenv("ALLOW_EMAIL_LOGIN", "0" if clerk_on() else "1") != "0"


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
    if require_login() and not domain_ok(info["email"]):
        return cj({"error": "livekit_only", "message": f"The demo generator is LiveKit only for now. Sign in with your @{allowed_domain()} Google account."}, 403)
    tok, user = issue(info["email"], info.get("name"), info.get("picture"), True, "google")
    return cj({"session": tok, "view": view_token(verify(tok)), "user": user})


async def auth_email(req):
    if not email_login_on():
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
    allsess = sessions(read_events())
    slugs = {v["slug"] for v in mine}
    for v in mine:
        ss = [s for s in allsess if s.get("slug") == v["slug"]]
        v["stats"] = {"sessions": len(ss), "people": len({s["uid"] for s in ss}), "voice_calls": sum(s["voice_calls"] for s in ss),
                      "voice_s": sum(s["voice_s"] for s in ss), "time_s": sum(s["duration_s"] for s in ss),
                      "replays": sum(1 for s in ss if s["replay"]), "last": max((s["last"] for s in ss), default=None)}
    sess = [s for s in allsess if s["uid"] == d["e"] or s.get("slug") in slugs][:100]
    for s in sess:
        s["mine"] = s["uid"] == d["e"]
    return cj({"user": user_of(d), "view": view_token(d), "demos": mine, "sessions": sess, "mailer": mailer_name()})


# ---------------- events + replay ----------------
EV_TYPES = {"open", "hb", "voice_start", "voice_end", "page", "gallery_open", "generate_click", "unload"}


async def event(req):
    if internal(req):
        return cj({"ok": True, "skipped": "internal"})
    f = await body(req)
    d = verify(f.get("session")) if f.get("session") else None
    uid = d["e"] if d else re.sub(r"[^a-zA-Z0-9_@.+-]", "", str(f.get("uid") or ""))[:120] or "anon"
    name = d.get("n") if d else (str(f.get("name") or "")[:80] or None)
    now = int(time.time())
    for e in (f.get("events") or [])[:50]:
        if not isinstance(e, dict) or e.get("t") not in EV_TYPES:
            continue
        ev = {"t": e["t"], "ts": now, "uid": uid, "name": name, "verified": bool(d and d.get("v"))}
        for k in ("slug", "sid", "path", "title", "voice_s", "active_s", "demo", "href", "where", "room", "skew_ms"):
            if k in e:
                ev[k] = str(e[k])[:300] if not isinstance(e[k], (int, float)) else e[k]
        log_event(ev)
    return cj({"ok": True})


async def replay_put(req):
    sid = req.match_info["sid"]
    if not SID_RE.match(sid):
        return cj({"error": "bad sid"}, 400)
    if internal(req):
        return cj({"ok": True, "skipped": "internal"})
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
    sid = req.match_info["sid"]
    fn = p("replays", sid + ".jsonl")
    if not SID_RE.match(sid) or not os.path.exists(fn):
        return cj({"error": "no replay"}, 404) if admin_ok(f) else cj({"error": "analytics is for admins"}, 403)
    if not admin_ok(f):
        d = full(f.get("session")) if f.get("session") else None
        slug = None
        try:
            slug = json.loads(open(fn).readline()).get("_meta", {}).get("slug")
        except Exception:
            pass
        if not d or not slug or (owners().get(slug) or {}).get("email") != d["e"]:
            return cj({"error": "you can watch replays of your own demos"}, 403)
    evs = []
    for line in open(fn, errors="ignore"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if "_meta" not in e:
            evs.append(e)
    evs.sort(key=lambda e: e.get("timestamp", 0))
    return S.cors(web.json_response({"events": evs, "voice": voice_for_sid(sid)}, dumps=lambda o: json.dumps(o, separators=(",", ":"))))


# ---- voice recordings (voice replay) ----
# The demo's voice agent records the call (stereo OGG/Opus: visitor L, agent R) and POSTs it here when the call ends;
# signed with the LiveKit API secret both sides already have. Stored in voice/<room>.ogg + .json, served to the
# replay player with a short-lived signed URL. Port note: the same 3 routes + this store move as-is to any backend.
ROOM_RE = re.compile(r"^[a-zA-Z0-9_.:-]{3,128}$")
VOICE_CAP = 60 * 1024 * 1024


def voice_meta(room):
    if not room or not ROOM_RE.match(room):
        return None
    try:
        return json.load(open(p("voice", room + ".json")))
    except (OSError, ValueError):
        return None


async def voice_put(req):
    room = req.match_info["room"]
    t0 = req.query.get("t0", "")
    sec = os.getenv("LIVEKIT_API_SECRET", "")
    good = hmac.new(sec.encode(), f"{room}:{t0}".encode(), hashlib.sha256).hexdigest()
    if not sec or not ROOM_RE.match(room) or not hmac.compare_digest(req.headers.get("X-LK-Voice-Sig", ""), good):
        return cj({"error": "bad signature"}, 403)
    tmp, n = p("voice", room + ".ogg.part"), 0
    with open(tmp, "wb") as out:
        while True:
            chunk = await req.content.read(1 << 16)
            if not chunk:
                break
            n += len(chunk)
            if n > VOICE_CAP:
                out.close(); os.remove(tmp)
                return cj({"error": "too big"}, 413)
            out.write(chunk)
    os.replace(tmp, p("voice", room + ".ogg"))
    try:
        dur = float(req.query.get("dur") or 0)
    except ValueError:
        dur = 0.0
    meta = {"room": room, "slug": re.sub(r"[^a-z0-9-]", "", req.query.get("slug", ""))[:60], "t0": float(t0),
            "duration_s": round(dur, 1), "bytes": n, "ts": int(time.time())}
    wj(os.path.join("voice", room + ".json"), meta)
    log_event({"t": "voice_rec", "ts": int(time.time()), "uid": "agent", "room": room, "slug": meta["slug"], "voice_s": int(dur)})
    return cj({"ok": True, "bytes": n})


async def voice_get(req):
    room = req.match_info["room"]
    d = verify(req.query.get("k"))
    fn = p("voice", room + ".ogg")
    if not d or d.get("s") != "voice" or d.get("r") != room or not os.path.exists(fn):
        raise web.HTTPForbidden()
    return web.FileResponse(fn, headers={"Content-Type": "audio/ogg", "Cache-Control": "private, max-age=3600",
                                         "Access-Control-Allow-Origin": "*"})


def voice_for_sid(sid):
    rooms = {e["room"] for e in read_events() if e.get("sid") == sid and e.get("room")}
    out = []
    for r in sorted(rooms):
        m = voice_meta(r)
        if m and os.path.exists(p("voice", r + ".ogg")):
            k = sign({"s": "voice", "r": r, "x": int(time.time()) + 6 * 3600})
            out.append({"room": r, "t0": m["t0"], "duration_s": m.get("duration_s", 0),
                        "url": public_base().rstrip("/") + "/api/p/voice-audio/" + urllib.parse.quote(r) + "?k=" + urllib.parse.quote(k)})
    out.sort(key=lambda v: v["t0"])
    return out


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
        if e.get("room"):
            s.setdefault("rooms", set()).add(e["room"])
    out = []
    for s in by.values():
        s["pages"] = sorted(s["pages"])[:30]
        s["duration_s"] = max(s["last"] - s["start"], s["active_s"])
        s["replay"] = os.path.exists(p("replays", s["sid"] + ".jsonl"))
        s["replay_kb"] = int(os.path.getsize(p("replays", s["sid"] + ".jsonl")) / 1024) if s["replay"] else 0
        vv = [m for m in (voice_meta(r) for r in sorted(s.pop("rooms", set()))) if m]
        s["voice_rec"] = len(vv); s["voice_rec_s"] = int(sum(m.get("duration_s", 0) for m in vv))
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


def internal(req):
    """Requests from inside the sandbox (Claude's own Playwright checks hit localhost:8080): no tracker, no events."""
    return not req.headers.get("X-Forwarded-Host") and (req.host or "").split(":")[0] in ("localhost", "127.0.0.1", "0.0.0.0", "::1")


@web.middleware
async def mw(req, handler):
    if req.method == "POST" and req.path == "/api/generate":
        try:
            f = json.loads(await req.read() or b"{}")
        except ValueError:
            f = {}
        if require_login() and not internal(req):
            d0 = full(f.get("lk_session")) if f.get("lk_session") else None
            if not d0:
                return S.cors(web.json_response({"error": f"Sign in with your @{allowed_domain()} Google account to generate demos (LiveKit only for now).",
                                                 "login": "https://live-demos-sa.vercel.app/account/?next=/%3Fgenerate%3D1"}, status=401))
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
    if req.path.startswith("/v2/") and isinstance(resp, web.FileResponse) and resp.status == 200 and not internal(req):
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


def backfill_owners():
    """Demos built before sign-in existed have no owner: attribute them to BACKFILL_OWNER, and mark them as already
    emailed so nobody gets a 'demo ready' email for an old build."""
    who = os.getenv("BACKFILL_OWNER", "nabil.urrehman@livekit.io").strip().lower()
    if not who or not os.path.isdir(S.WORK):
        return
    own, sent, n = owners(), rj("emailed.json", {}), 0
    for slug in os.listdir(S.WORK):
        j = S.load(slug)
        if not j or (own.get(slug) or {}).get("created") == j.get("created"):
            continue
        own[slug] = {"email": who, "name": "Nabil Ur Rehman" if who.startswith("nabil") else None, "verified": True,
                     "created": j.get("created"), "ts": int(time.time()), "backfilled": True}
        sent.setdefault(f"{slug}:{j.get('created')}", {"ts": int(time.time()), "to": who, "via": "backfill-skip"}); n += 1
    if n:
        wj("emailed.json", sent); wj("owners.json", own)
        print(f"product: backfilled {n} demo owner(s) -> {who}", flush=True)


def install(app, server_module):
    global S
    S = server_module
    for d in ("", "events", "replays", "voice"):
        os.makedirs(p(d), exist_ok=True)
    secret_file(".secret"); secret_file(".analytics_code", 9)
    try:
        backfill_owners()
    except Exception as e:  # noqa: BLE001
        print("product backfill:", e, flush=True)
    app.middlewares.append(mw)
    app.on_startup.append(watcher)
    patch_notify()
    app.add_routes([web.get("/api/p/config", config), web.post("/api/p/auth/google", auth_google), web.post("/api/p/auth/clerk", auth_clerk), web.post("/api/p/auth/email", auth_email),
                    web.post("/api/p/me", me), web.post("/api/p/event", event), web.post("/api/p/replay/{sid}", replay_put),
                    web.post("/api/p/analytics", analytics), web.post("/api/p/replay-get/{sid}", replay_get),
                    web.get("/api/p/email-preview", email_preview), web.post("/api/p/voice/{room}", voice_put), web.get("/api/p/voice-audio/{room}", voice_get), web.get("/p/{name}", static_p)])
    print("product layer installed (store %s, clerk=%s, require_login=%s, domain=%s, mailer=%s)" % (STORE, clerk_on(), require_login(), allowed_domain(), mailer_name()), flush=True)
