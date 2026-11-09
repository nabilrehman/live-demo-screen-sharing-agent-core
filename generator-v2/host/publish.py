"""Publish finished demos so they stay up without the build sandbox (its sessions stop after 24 h).

Pages -> Vercel Blob gen/<slug>/site/, served by live-demos-sa at /v2/<slug>/ (vercel.json rewrites). Knowledge pack ->
a new version under <GEN_PACK_PREFIX>/<slug>/ that the shared LiveKit Cloud agent demo-gen downloads on every call
(live-demos-sa /api/gen-token passes it the newest version). Gallery feed -> gen/demos.json, which the main page reads
when the build host is off. The Blob work is done by blob/publish.mjs (official SDK).

  python host/publish.py <slug> [<slug> ...]   publish (or re-publish) demos
  python host/publish.py --all                 every finished demo
  python host/publish.py --pack <slug>         knowledge only (what an Edit changes)
  python host/publish.py --delete <slug>       take a demo off Blob
Env: BLOB_READ_WRITE_TOKEN, GEN_PACK_PREFIX (start_host.sh loads them from /vercel/gen/.blob.env). GEN_HOME as server.py.
"""
import json, os, subprocess, sys, time, urllib.parse

ROOT = os.environ.get("GEN_HOME", "/vercel/gen")
WORK = os.path.join(ROOT, "generator-v2", "work")
HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.getenv("GEN_PUBLIC_BASE", "https://live-demos-sa.vercel.app")


def enabled():
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN") and os.getenv("GEN_PACK_PREFIX"))


def node(*args):
    p = subprocess.run(["node", os.path.join(HERE, "blob", "publish.mjs"), *args], cwd=os.path.join(HERE, "blob"),
                       capture_output=True, text=True, timeout=900)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out = {"ok": False, "error": (p.stderr or p.stdout).strip()[-300:]}
    if not out.get("ok"):
        raise RuntimeError(f"publish {args[0]} failed: {out.get('error')}")
    return out


def load(slug):
    try:
        return json.load(open(os.path.join(WORK, slug, "job.json")))
    except (OSError, ValueError):
        return None


def save(slug, j):
    tmp = os.path.join(WORK, slug, "job.json.tmp")
    json.dump(j, open(tmp, "w")); os.replace(tmp, os.path.join(WORK, slug, "job.json"))


def public_url(slug, code):
    return f"{PUBLIC}/v2/{slug}/?code={urllib.parse.quote(code)}"


def thumb_src(slug):
    d = os.path.join(WORK, slug)
    for sub in ("verify", "ref"):
        try:
            names = sorted(os.listdir(os.path.join(d, sub)))
        except OSError:
            continue
        for n in names:
            if n.endswith(".png") and n.startswith("home") and ("desk" in n or "1440" in n):
                return os.path.join(d, sub, n)
    return None


def make_thumb(slug):
    """The gallery thumbnail (top of the desktop home screenshot) as work/<slug>/thumb.jpg, or None."""
    src = thumb_src(slug)
    if not src:
        return None
    out = os.path.join(WORK, slug, "thumb.jpg")
    if not os.path.isfile(out) or os.path.getmtime(out) < os.path.getmtime(src):
        from PIL import Image
        im = Image.open(src).convert("RGB")
        w = im.width; im = im.crop((0, 0, w, min(im.height, int(w * 0.62))))
        im.thumbnail((720, 720)); im.save(out, "JPEG", quality=78)
    return out


def persona(slug):
    try:
        s = json.load(open(os.path.join(WORK, slug, "knowledge", "site.json")))
        return {"assistant": s.get("assistant"), "voice": s.get("voice")}
    except (OSError, ValueError):
        return None


def index():
    """gen/demos.json: what the main page shows when the build host is off (same fields as /api/demos)."""
    items = []
    for slug in sorted(os.listdir(WORK)) if os.path.isdir(WORK) else []:
        j = load(slug)
        if not j or j.get("status") != "done" or not j.get("published"):
            continue
        items.append({k: j.get(k) for k in ("slug", "brand", "url", "mode", "status", "code", "concept", "created", "finished")}
                     | {"persona": persona(slug), "preview": public_url(slug, j["code"]), "hosted": True,
                        "thumb": f"{PUBLIC}/v2/{slug}/_thumb.jpg" if j["published"].get("thumb") else None})
    items.sort(key=lambda x: x.get("created") or 0, reverse=True)
    path = os.path.join(WORK, ".demos.json")
    json.dump({"demos": items, "updated": int(time.time())}, open(path, "w"))
    return node("index", path)


def pack(slug):
    """Upload the knowledge pack as a new version (the next call to the demo uses it)."""
    out = node("pack", slug, os.path.join(WORK, slug, "knowledge"))
    j = load(slug)
    j.setdefault("published", {})["v"] = out["v"]; j["published"]["at"] = int(time.time())
    save(slug, j)
    return out


def publish(slug, pages=True):
    j = load(slug)
    if not j or j.get("status") != "done":
        raise RuntimeError(f"{slug}: not a finished demo")
    res = {}
    if pages:
        res["site"] = node("site", slug, os.path.join(WORK, slug, "site"))
        if not res["site"]["widgets_patched"]:
            raise RuntimeError(f"{slug}: no LiveKit widget (livekit.js with the default token URL) found in its pages")
        th = make_thumb(slug)
        if th:
            node("thumb", slug, th)
    res["pack"] = pack(slug)
    j = load(slug)
    j["published"].update(url=public_url(slug, j["code"]), thumb=bool(pages and thumb_src(slug)) or j["published"].get("thumb", False))
    j.pop("publish_error", None)
    save(slug, j)
    index()
    return res


def unpublish(slug):
    out = node("delete", slug)
    index()
    return out


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); sys.exit(0 if args else 2)
    if args[0] == "--delete":
        print(json.dumps(unpublish(args[1]))); return
    if args[0] == "--pack":
        print(json.dumps(pack(args[1]))); index(); return
    slugs = [s for s in sorted(os.listdir(WORK)) if (load(s) or {}).get("status") == "done"] if args[0] == "--all" else args
    for s in slugs:
        t = time.time()
        print(s, json.dumps(publish(s)), f"{time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
