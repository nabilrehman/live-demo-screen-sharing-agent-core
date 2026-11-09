"""Generated demos on one shared hosted agent (AGENT_NAME=demo-gen on LiveKit Cloud).

Each call's dispatch metadata names its demo: {"slug": "airbnb", "v": "20261109-170102"} (set by the page's
/api/gen-token). The demo's knowledge pack lives at GEN_PACK_BASE/<slug>/<v>/ (Vercel Blob, written by
generator-v2/host/publish.py; files listed in manifest.json). It is downloaded once per process and swapped in before
the session starts, so an Edit is a new pack version and the next call picks it up: nothing to restart or redeploy.

Without GEN_PACK_BASE nothing happens: the classic one-demo-per-worker mode (SITE_KNOWLEDGE) is unchanged.
"""

import json
import logging
import os
import re
import shutil

import aiohttp

from inpage import insights, site

log = logging.getLogger("gen-pack")
BASE = os.getenv("GEN_PACK_BASE", "").rstrip("/")
CACHE = os.getenv("GEN_PACK_CACHE", "/tmp/gen-packs")
SAFE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FILE = re.compile(r"^[\w.-]{1,80}$")


def wanted(ctx) -> tuple[str, str] | None:
    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except ValueError:
        return None
    slug, v = str(meta.get("slug", "")), str(meta.get("v", ""))
    return (slug, v) if SAFE.match(slug) and SAFE.match(v) else None


async def fetch(slug: str, v: str) -> str:
    d = os.path.join(CACHE, slug, v)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    if os.path.isfile(os.path.join(d, "site.json")):
        return d
    url = f"{BASE}/{slug}/{v}/"
    tmp = f"{d}.{os.getpid()}.tmp"  # complete or absent: a half download never looks like a pack
    os.makedirs(tmp, exist_ok=True)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
        async with http.get(url + "manifest.json") as r:
            r.raise_for_status()
            names = [n for n in json.loads(await r.text())["files"] if FILE.match(n)]
        for n in names:
            async with http.get(url + n) as r:
                r.raise_for_status()
                body = await r.read()
            with open(os.path.join(tmp, n), "wb") as f:
                f.write(body)
    try:
        os.rename(tmp, d)
    except OSError:  # another process got there first
        shutil.rmtree(tmp, ignore_errors=True)
    return d


async def select(ctx) -> str | None:
    """Load this call's demo; returns its slug (None in classic mode). Raises if the demo's pack can't be loaded:
    better no agent than the wrong demo's agent."""
    if not BASE:
        return None
    w = wanted(ctx)
    if not w:
        raise RuntimeError(f"no demo in the job metadata: {ctx.job.metadata!r}")
    slug, v = w
    site.use_knowledge(await fetch(slug, v))
    insights.reload()
    log.info("call %s: demo %s (pack %s, %s)", ctx.room.name, slug, v, site.SITE.get("brand"))
    return slug
