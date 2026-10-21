"""Spoken end-to-end run of the Hard Rock Hotels demo script (a script, not a pytest test): opens the mockup in Chrome with
the LiveKit embed, speaks each beat through a fake microphone (WAV clips played into a WebAudio stream that survives page
loads), waits for LiveKit to finish, and checks where the page went, what was highlighted and what LiveKit said.

Needs: the site (mockup + /api/token) at BASE_URL, and a worker for the brain's agent name (see the token endpoint).
  uv run tests/hardrock_flow.py <brain: hardrock-grok|hr-local-grok> <run label> [--video DIR] [--shell] [--record]
Env: BASE_URL (default http://localhost:8790), WAV_DIR (beat clips b1.wav..), OUT_DIR (screenshots + JSON results).
--shell: load the page the way the presenter bookmarklet does (no tag on the page; livekit.js in shell mode).
--record (with --video and --shell): also record the guest's and LiveKit's voices and mux them onto the video (ffmpeg).
"""

import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time

from playwright.async_api import async_playwright

BASE = os.getenv("BASE_URL", "http://localhost:8791")
WAVS = os.getenv("WAV_DIR", ".")
OUT = os.getenv("OUT_DIR", ".")
CODE = os.getenv("ACCESS_CODE", "HARDROCK-DEMO")

# (line, path regex the page must end on, highlight regex or None, LiveKit's words must match, must not match)
NOT_BOOKED = r"\b(i've|i have) (booked|reserved|completed)\b|you're (all )?booked|reservation is confirmed"
BEATS = [
    ("What can you see on this page?", r"^/$", None, r"destination|hotel|book|unity|hard rock|malta", None),
    (
        "I'm going to New York next weekend. What hotels do you have there?",
        r"^/(new-york|destinations)",
        r"new york",
        r"new york|midtown|times square",
        None,
    ),
    ("What rooms are there?", r"^/new-york/rooms-and-suites$", r"king|queen|suite", r"king|queen|suite", None),
    ("Which one has the best view?", None, None, r"view|skyline|terrace|window|penthouse|corner", None),
    ("Any deals right now?", r"offers$", r".", r"percent|%|off|credit|save|rate|offer", None),
    ("Where can I get a drink with a view?", r"^/new-york", r"rt60|rooftop", r"rt60|rooftop|r\.?t\.? ?sixty", None),
    ("Can I bring my dog?", None, None, r"pet|dog|unleashed", None),
    (
        "Book a king room for Saturday.",
        r"^/book",
        None,
        r"king",
        NOT_BOOKED,
    ),
    (
        "Just put in my credit card and finish the booking for me.",
        None,
        None,
        r"can't|cannot|can not|won't|yourself|you'll|you can|your details|you enter",
        NOT_BOOKED,
    ),
    ("What do I get with Unity?", r"unity|member", None, r"unity|member|point|rate|rewards", None),
    ("Thanks, that's all for now.", None, None, r".", None),
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
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(dest); if (recDest) src.connect(recDest); src.start();
    return buf.duration;
  };
  // --record: mix the guest's clips and LiveKit's voice into one audio file (single-document runs: --shell)
  let rec, recDest, chunks = [];
  const seen = new WeakSet();
  window.__recStart = () => {
    ensure(); recDest = ctx.createMediaStreamDestination();
    rec = new MediaRecorder(recDest.stream, { mimeType: 'audio/webm;codecs=opus' });
    rec.ondataavailable = (e) => chunks.push(e.data); rec.start(1000); window.__recT0 = performance.now();
    setInterval(() => {
      const r = document.getElementById('lk-root');
      (r && r.shadowRoot ? r.shadowRoot.querySelectorAll('audio') : []).forEach((el) => {
        if (!seen.has(el) && el.srcObject) { seen.add(el); try { ctx.createMediaStreamSource(el.srcObject).connect(recDest); } catch (e) {} }
      });
    }, 200);
    return window.__recT0;
  };
  window.__recStop = () => new Promise((res) => {
    rec.onstop = async () => {
      const buf = new Uint8Array(await new Blob(chunks, { type: 'audio/webm' }).arrayBuffer());
      let out = ''; for (let i = 0; i < buf.length; i += 0x8000) out += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      res(btoa(out));
    };
    rec.stop();
  });
})();
"""

PROBE = """() => {
  const k = window.__lkAgent; const host = document.getElementById('lk-root');
  const sh = host && host.shadowRoot;
  const w = sh && sh.querySelector('.lk');
  const caps = sh ? [...sh.querySelectorAll('#log li')].filter((li) => li.querySelector('.txt')).map((li) => [li.className, li.querySelector('.txt').textContent, li.dataset.seg]) : [];
  const site = k ? k.cfg.root : '/hardrock/';
  let p = location.pathname.replace(/\\/index\\.html$/, '/');
  p = '/' + p.slice(site.length).replace(/^\\/+|\\/+$/g, '');
  return { path: p, mode: w ? w.dataset.mode : '', caps, events: k ? k.events.filter((e) => e.kind === 'highlight' || e.kind === 'rpc' || e.kind === 'navigate') : [],
           insights: k ? k.insights || null : null };
}"""


async def main():
    brain, label = sys.argv[1], sys.argv[2]
    video = sys.argv[sys.argv.index("--video") + 1] if "--video" in sys.argv else None
    shell = "--shell" in sys.argv
    record = "--record" in sys.argv and video and shell  # audio is mixed in one document, so shell mode only
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
        await ctx.add_init_script(f"try{{localStorage.setItem('lk.brain','{brain}')}}catch(e){{}}")
        pg = await ctx.new_page()
        pg.on("console", lambda m: m.type in ("error", "warning") and print("  [console]", m.text[:200]))
        if shell:  # the bookmarklet: a page without the tag, then livekit.js in shell mode
            await pg.route(
                "**/embed/hardrock/livekit.js",
                lambda r: (
                    r.fulfill(body="", content_type="text/javascript")
                    if "shell=1" not in r.request.url
                    else r.continue_()
                ),
            )
        await pg.goto(f"{BASE}/hardrock/?code={CODE}")
        await pg.wait_for_timeout(1500)
        if shell:
            await pg.evaluate("""() => { const s = document.createElement('script'); s.src = '/embed/hardrock/livekit.js?shell=1';
                s.dataset.mode = 'shell'; s.dataset.siteRoot = '/hardrock/'; document.body.appendChild(s); }""")
            await pg.wait_for_timeout(2500)

        # the widget picks its brain from the tag (data-brain); runs pin it on the token request instead
        async def pin_brain(route):
            u = route.request.url
            await route.continue_(
                url=re.sub(r"brain=[^&]*", f"brain={brain}", u) if "brain=" in u else u + f"&brain={brain}"
            )

        await pg.route("**/api/token*", pin_brain)
        t_start = time.perf_counter()
        rec_t0 = await pg.evaluate("window.__recStart()") if record else None
        await pg.locator("#launch").click()  # one click: opens the panel and starts the call
        await pg.wait_for_timeout(1200)
        if await pg.locator("#start").is_visible():  # older widget: a separate Start button
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
                "() => '/' + location.pathname.replace(/^\\/hardrock\\/?/, '').replace(/\\/$/, '')"
            )
            return top

        async def wait_turn(n_before, max_s=45.0, t_end=None):
            """Wait for LiveKit to answer and go quiet; returns (first-speech latency ms or None, state)."""
            t0 = time.perf_counter()
            lat, quiet_since, hl, spoke = None, None, [], False
            first = await probe()
            old = [e for e in first["events"] if e["kind"] == "highlight"]  # from before this beat

            def answered(st):  # LiveKit said more than a "let me pull that up" since the beat began
                said = " ".join(t for c, t, g in st["caps"] if g not in n_before and c == "from-agent")
                return len(said.split()) > 14
            while time.perf_counter() - t0 < max_s:
                s = await probe()
                hl += [e for e in s["events"] if e["kind"] == "highlight" and e not in hl and e not in old]
                if s["mode"] == "speaking":
                    spoke = True
                    quiet_since = None
                    if lat is None and t_end is not None:
                        lat = (time.perf_counter() - t_end) * 1000
                elif s["mode"] == "listening" and spoke and any(g not in n_before for _, _, g in s["caps"]):
                    quiet_since = quiet_since or time.perf_counter()
                    # after a page load the answer comes from the new page: give it longer than a pause
                    moved = s["path"] != first["path"]  # events reset on a page load; the path tells
                    if time.perf_counter() - quiet_since > (6.0 if moved and not answered(s) else 2.5):
                        return lat, s, hl
                await pg.wait_for_timeout(100)
            return lat, await probe(), hl

        _, s, _ = await wait_turn(set(), 40)
        greet = " ".join(t for c, t, _ in s["caps"] if c == "from-agent")
        print(f"[{label}] greeting ({time.perf_counter() - t_start:.1f}s): {greet[:160]}")
        results.append({"beat": 0, "line": "(greeting)", "agent": greet, "ok": bool(re.search(r"\bAI\b", greet) and re.search(r"livekit", greet, re.I) and not re.search(r"\bkai\b", greet, re.I))})
        for i, (line, want_path, want_hl, want_say, bad_say) in enumerate(BEATS):
            n = {g for _, _, g in s["caps"]}
            dur = await pg.evaluate("(b) => window.__say(b)", clips[i])
            await pg.wait_for_timeout(int(dur * 1000))
            t_end = time.perf_counter()
            lat, s, hl = await wait_turn(n, 50, t_end)
            said = " ".join(t for c, t, g in s["caps"] if g not in n and c == "from-agent")
            heard = " ".join(t for c, t, g in s["caps"] if g not in n and c == "from-you")
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
                "agent": said,
                "latency_ms": round(lat) if lat else None,
                "checks": checks,
                "ok": ok,
                "shot": shot,
            }
            results.append(r)
            print(
                f"[{label}] b{i + 1} {'PASS' if ok else 'FAIL'} {r['latency_ms']}ms path={s['path']} hl={hl_text[:60]!r} fails={[k for k, v in checks.items() if not v]}\n    you: {heard[:100]}\n    agent: {said[:260]}"
            )
        s = await probe()
        audio = await pg.evaluate("window.__recStop()") if record else None
        if await pg.locator("#end").is_visible():
            await pg.locator("#end").click()
        else:
            await pg.locator("#launch").click()  # the launcher is the End button during a call
        await pg.wait_for_timeout(1500)
        data_href = await pg.locator("#data").get_attribute("href")
        vpath = await pg.video.path() if video else None
        await ctx.close()
        await b.close()
    if audio:  # put the mixed audio on the page video, starting where the recorder started
        a = os.path.join(OUT, f"{label}_audio.webm")
        open(a, "wb").write(base64.b64decode(audio))
        out_v = os.path.join(OUT, f"{label}_demo.webm")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                vpath,
                "-itsoffset",
                f"{rec_t0 / 1000:.3f}",
                "-i",
                a,
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "libopus",
                out_v,
            ],
            check=True,
        )
        print(f"[{label}] video with audio: {out_v}")
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
