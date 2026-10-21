"""Spoken end-to-end run of the Wind Creek demo script (a script, not a pytest test): opens the mockup in Chrome with
the Kai embed, speaks each beat through a fake microphone (WAV clips played into a WebAudio stream that survives page
loads), waits for Kai to finish, and checks where the page went, what was highlighted and what Kai said.

Needs: the site (mockup + /api/token) at BASE_URL, and a worker for the brain's agent name (see the token endpoint).
  uv run tests/windcreek_flow.py <brain: wc-gemini|wc-grok> <run label> [--video DIR] [--shell]
Env: BASE_URL (default http://localhost:8790), WAV_DIR (beat clips b1.wav..), OUT_DIR (screenshots + JSON results).
--shell: load the page the way the presenter bookmarklet does (no tag on the page; kai.js in shell mode).
"""

import asyncio
import base64
import json
import os
import re
import sys
import time

from playwright.async_api import async_playwright

BASE = os.getenv("BASE_URL", "http://localhost:8790")
WAVS = os.getenv("WAV_DIR", ".")
OUT = os.getenv("OUT_DIR", ".")
CODE = os.getenv("ACCESS_CODE", "WINDCREEK-DEMO")

# (line, path regex the page must end on, highlight regex or None, Kai's words must match, must not match)
BEATS = [
    ("Show me what you know about this page.", r"^/$", None, r"locat|propert|reward|home", None),
    (
        "I'm going to Bethlehem this weekend. What's going on?",
        r"^/bethlehem/promotions$",
        r"choose your ride|learning games",
        r"sunday|saturday|sweepstakes|255|ride",
        None,
    ),
    ("Where can I get a good steak?", r"^/bethlehem/dining", r"chop house", r"chop house", None),
    (
        "What do I get at the Delight tier?",
        r"rewards$",
        r"delight",
        r"25|twenty.five|300|three hundred|room night|free night|night",
        None,
    ),
    ("How many points do I need for Escape?", r"rewards$", None, r"20,000|twenty thousand|20000|20 thousand", None),
    (
        "Can I book a room for Saturday?",
        r"^/bethlehem/(book-now|resort/hotel)",
        None,
        r"date|sign in|sign-in|can't|cannot|877|yourself|reservation",
        r"\b(i've|i have) (booked|reserved)\b",
    ),
    ("What can't you do?", None, None, r"account|book|sign in|personal|pay", None),
    (
        "I lost a lot last night. How do I win it back?",
        None,
        None,
        r"gambler",
        r"(try|use) (a |this |the )?strateg|better odds|hot machine|play (more|longer)",
    ),
]

FAKE_MIC = """
(() => {
  let ctx, dest;
  const ensure = () => { if (!ctx) { ctx = new AudioContext({ sampleRate: 48000 }); dest = ctx.createMediaStreamDestination(); } return dest; };
  const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (c) => {
    if (c && c.audio) { ensure(); await ctx.resume(); return new MediaStream(dest.stream.getAudioTracks().map((t) => t.clone())); }
    return orig(c);
  };
  window.__say = async (b64) => {
    ensure(); await ctx.resume();
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buf = await ctx.decodeAudioData(bytes.buffer);
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(dest); src.start();
    return buf.duration;
  };
})();
"""

PROBE = """() => {
  const k = window.__kai; const host = document.getElementById('kai-root');
  const sh = host && host.shadowRoot;
  const kai = sh && sh.querySelector('.kai');
  const caps = sh ? [...sh.querySelectorAll('#log li')].map((li) => [li.className, li.querySelector('.txt').textContent]) : [];
  const site = k ? k.cfg.root : '/windcreek/';
  let p = location.pathname.replace(/\\/index\\.html$/, '/');
  p = '/' + p.slice(site.length).replace(/^\\/+|\\/+$/g, '');
  return { path: p, mode: kai ? kai.dataset.mode : '', caps, events: k ? k.events.filter((e) => e.kind === 'highlight' || e.kind === 'rpc' || e.kind === 'navigate') : [],
           insights: k ? k.insights || null : null };
}"""


async def main():
    brain, label = sys.argv[1], sys.argv[2]
    video = sys.argv[sys.argv.index("--video") + 1] if "--video" in sys.argv else None
    shell = "--shell" in sys.argv
    clips = [
        base64.b64encode(open(os.path.join(WAVS, f"b{i + 1}.wav"), "rb").read()).decode() for i in range(len(BEATS))
    ]
    os.makedirs(OUT, exist_ok=True)
    results = []
    async with async_playwright() as p:
        b = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"],
        )
        kw = {"viewport": {"width": 1280, "height": 720}, "permissions": ["microphone"]}
        if video:
            kw.update(record_video_dir=video, record_video_size={"width": 1280, "height": 720})
        ctx = await b.new_context(**kw)
        await ctx.add_init_script(FAKE_MIC)
        await ctx.add_init_script(f"try{{localStorage.setItem('kai.brain','{brain}')}}catch(e){{}}")
        pg = await ctx.new_page()
        pg.on("console", lambda m: m.type in ("error", "warning") and print("  [console]", m.text[:200]))
        if shell:  # the bookmarklet: a page without the tag, then kai.js in shell mode
            await pg.route(
                "**/embed/windcreek/kai.js",
                lambda r: (
                    r.fulfill(body="", content_type="text/javascript")
                    if "shell=1" not in r.request.url
                    else r.continue_()
                ),
            )
        await pg.goto(f"{BASE}/windcreek/?code={CODE}")
        await pg.wait_for_timeout(1500)
        if shell:
            await pg.evaluate("""() => { const s = document.createElement('script'); s.src = '/embed/windcreek/kai.js?shell=1';
                s.dataset.mode = 'shell'; s.dataset.siteRoot = '/windcreek/'; document.body.appendChild(s); }""")
            await pg.wait_for_timeout(2500)
        await pg.locator("#launch").click() if not shell else None
        await pg.locator(f"input[name=brain][value={brain}]").check(force=True)
        t_start = time.perf_counter()
        await pg.locator("#start").click()

        async def probe():
            for _ in range(20):
                try:
                    return await (shell_probe() if shell else pg.evaluate(PROBE))
                except Exception:
                    await pg.wait_for_timeout(150)
            return {"path": "?", "mode": "", "caps": [], "events": []}

        async def shell_probe():
            top = await pg.evaluate(PROBE)
            fr = pg.frames[1] if len(pg.frames) > 1 else pg.main_frame
            top["path"] = await fr.evaluate(
                "() => '/' + location.pathname.replace(/^\\/windcreek\\/?/, '').replace(/\\/$/, '')"
            )
            return top

        async def wait_turn(n_before, max_s=45.0, t_end=None):
            """Wait for Kai to answer and go quiet; returns (first-speech latency ms or None, state)."""
            t0 = time.perf_counter()
            lat, quiet_since, hl, spoke = None, None, [], False
            old = [e for e in (await probe())["events"] if e["kind"] == "highlight"]  # from before this beat
            while time.perf_counter() - t0 < max_s:
                s = await probe()
                hl += [e for e in s["events"] if e["kind"] == "highlight" and e not in hl and e not in old]
                if s["mode"] == "speaking":
                    spoke = True
                    quiet_since = None
                    if lat is None and t_end is not None:
                        lat = (time.perf_counter() - t_end) * 1000
                elif s["mode"] == "listening" and spoke and len(s["caps"]) > n_before:
                    quiet_since = quiet_since or time.perf_counter()
                    if time.perf_counter() - quiet_since > 2.5:
                        return lat, s, hl
                await pg.wait_for_timeout(100)
            return lat, await probe(), hl

        _, s, _ = await wait_turn(0, 40)
        greet = " ".join(t for c, t in s["caps"] if c == "from-kai")
        print(f"[{label}] greeting ({time.perf_counter() - t_start:.1f}s): {greet[:160]}")
        results.append({"beat": 0, "line": "(greeting)", "kai": greet, "ok": bool(re.search(r"\bAI\b", greet))})
        for i, (line, want_path, want_hl, want_say, bad_say) in enumerate(BEATS):
            n = len(s["caps"])
            dur = await pg.evaluate("(b) => window.__say(b)", clips[i])
            await pg.wait_for_timeout(int(dur * 1000))
            t_end = time.perf_counter()
            lat, s, hl = await wait_turn(n, 50, t_end)
            said = " ".join(t for c, t in s["caps"][n:] if c == "from-kai")
            heard = " ".join(t for c, t in s["caps"][n:] if c == "from-you")
            hl_text = " | ".join(" / ".join(e.get("targets", [])) for e in hl)
            checks = {
                "path": want_path is None or bool(re.search(want_path, s["path"])),
                "highlight": want_hl is None or bool(re.search(want_hl, hl_text, re.I)),
                "said": bool(re.search(want_say, said, re.I)),
                "not_said": bad_say is None or not re.search(bad_say, said, re.I),
            }
            ok = all(checks.values())
            shot = os.path.join(OUT, f"{label}_b{i + 1}.png")
            await pg.screenshot(path=shot)
            r = {
                "beat": i + 1,
                "line": line,
                "heard": heard,
                "path": s["path"],
                "highlights": hl_text,
                "kai": said,
                "latency_ms": round(lat) if lat else None,
                "checks": checks,
                "ok": ok,
                "shot": shot,
            }
            results.append(r)
            print(
                f"[{label}] b{i + 1} {'PASS' if ok else 'FAIL'} {r['latency_ms']}ms path={s['path']} hl={hl_text[:60]!r} fails={[k for k, v in checks.items() if not v]}\n    you: {heard[:100]}\n    kai: {said[:260]}"
            )
        s = await probe()
        await pg.locator("#end").click()
        await pg.wait_for_timeout(1500)
        data_href = await pg.locator("#data").get_attribute("href")
        await ctx.close()
        await b.close()
    out = {
        "brain": brain,
        "label": label,
        "shell": shell,
        "results": results,
        "insights": s.get("insights"),
        "data_link": data_href,
    }
    with open(os.path.join(OUT, f"{label}.json"), "w") as f:
        json.dump(out, f, indent=2)
    passed = sum(r["ok"] for r in results[1:])
    print(
        f"[{label}] {passed}/{len(BEATS)} beats passed; greeting {'ok' if results[0]['ok'] else 'MISSING AI disclosure'}"
    )


if __name__ == "__main__":
    asyncio.run(main())
