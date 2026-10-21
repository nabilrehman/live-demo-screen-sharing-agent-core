"""Spoken end-to-end run of the Hard Rock Host Companion demo (Hard Rock v2, /hardrock-v2/), a script, not a pytest
test: opens the host app in Chrome with the LiveKit embed, speaks each beat of a host's floor walk through a fake
microphone, waits for LiveKit to finish, and checks which screen the app shows (window.LiveKitContext), what was
highlighted and what LiveKit said. 12 checks: the greeting plus 11 beats.

Needs: the site (mockup + /api/token) at BASE_URL, and a worker for the brain's agent name.
  uv run tests/hardrock_host_flow.py <brain: hardrock-host-grok|hrh-local-grok> <run label> [--width 390]
Env: BASE_URL (default http://localhost:8793), WAV_DIR (beat clips b1.wav..), OUT_DIR (screenshots + JSON results).
Make the clips with: python tests/hardrock_host_flow.py --say WAV_DIR  (macOS say + afconvert)
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

BASE = os.getenv("BASE_URL", "http://localhost:8793")
WAVS = os.getenv("WAV_DIR", ".")
OUT = os.getenv("OUT_DIR", ".")
CODE = os.getenv("ACCESS_CODE", "HARDROCK-DEMO")

NAMES = ("delane", "marchetti", "castellano", "liang", "brooks", "bellamy")
YES_FREE_PLAY = r"\b(yes|sure),? (you can|that's within|go ahead)|within your authority[^.]*free play"
# (line, screen state regex over "screen|player|section", LiveKit's words must match, must not match)
BEATS = [
    ("Give me today's briefing.", r"^briefing", lambda s: sum(n in s.lower() for n in NAMES) >= 4, None),
    ("Pull up Marcus Delane.", r"^player\|Marcus Delane.*\|profile", r"baccarat|eighteen|18|X card|unity x", None),
    ("What can I comp him tonight?", r"\|comps$", r"suite", None),
    ("Can I give him a suite upgrade and two show tickets?", r"Delane", r"within|yes|you can|authori[sz]ed|covered", r"\b(both|that) needs? (manager )?approval"),
    ("And can I give him ten thousand in free play?", r"Delane", r"approv|manager", YES_FREE_PLAY),
    ("What would he enjoy tonight?", r"Delane.*\|recommendations$", r"council oak|light show|blake shelton", None),
    ("He just sat down at high-limit baccarat.", r"Delane", r"macallan|celeste|mr\.? delane|suite|council oak|blake", None),
    ("Who's next?", r"Elena Marchetti", r"marchetti|elena", None),
    ("She's celebrating an anniversary, what should I do?", r"Marchetti", r"anniversar|champagne|roses|kuro|swim-up|suite", None),
    (
        "Sofia Bellamy seems upset, she says she's down a lot tonight. Should I offer her some free play?",
        None,
        r"play ?wise|1-833|limit|no free play|not offer|don't offer|shouldn't|wouldn't|won't|avoid",
        YES_FREE_PLAY,
    ),
    ("Back to the briefing.", r"^briefing", r".", None),
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
  const c = window.LiveKitContext ? window.LiveKitContext() : {};
  return { path: [c.screen, c.player || '', c.section || ''].join('|'), mode: w ? w.dataset.mode : '',
           caps, events: k ? k.events.filter((e) => e.kind === 'highlight' || e.kind === 'rpc' || e.kind === 'navigate') : [],
           insights: k ? k.insights || null : null };
}"""


def make_clips(out: str):
    os.makedirs(out, exist_ok=True)
    for i, (line, *_rest) in enumerate(BEATS):
        a, w = os.path.join(out, f"b{i + 1}.aiff"), os.path.join(out, f"b{i + 1}.wav")
        subprocess.run(["say", "-v", "Samantha", "-r", "185", "-o", a, line], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@48000", "-c", "1", a, w], check=True)
    print(f"{len(BEATS)} clips in {out}")


async def main():
    brain, label = sys.argv[1], sys.argv[2]
    width = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 390
    clips = [base64.b64encode(open(os.path.join(WAVS, f"b{i + 1}.wav"), "rb").read()).decode() for i in range(len(BEATS))]
    os.makedirs(OUT, exist_ok=True)
    results = []
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True, args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"])
        ctx = await b.new_context(viewport={"width": width, "height": 844 if width < 768 else 900}, permissions=["microphone"])
        await ctx.add_init_script(FAKE_MIC)
        pg = await ctx.new_page()
        pg.on("console", lambda m: m.type in ("error", "warning") and print("  [console]", m.text[:200]))

        async def pin_brain(route):
            u = route.request.url
            await route.continue_(url=re.sub(r"brain=[^&]*", f"brain={brain}", u) if "brain=" in u else u + f"&brain={brain}")

        await pg.route("**/api/token*", pin_brain)
        await pg.goto(f"{BASE}/hardrock-v2/?code={CODE}#/briefing")
        await pg.wait_for_timeout(1500)
        t_start = time.perf_counter()
        await pg.locator("#lk-root").locator("#launch").click()

        async def probe():
            for _ in range(20):
                try:
                    return await pg.evaluate(PROBE)
                except Exception:
                    await pg.wait_for_timeout(150)
            return {"path": "?", "mode": "", "caps": [], "events": []}

        async def wait_turn(n_before, max_s=45.0, t_end=None):
            t0 = time.perf_counter()
            lat, quiet_since, hl, spoke = None, None, [], False
            first = await probe()
            old = [e for e in first["events"] if e["kind"] == "highlight"]
            while time.perf_counter() - t0 < max_s:
                s = await probe()
                hl += [e for e in s["events"] if e["kind"] == "highlight" and e not in hl and e not in old]
                if s["mode"] == "speaking":
                    spoke, quiet_since = True, None
                    if lat is None and t_end is not None:
                        lat = (time.perf_counter() - t_end) * 1000
                elif s["mode"] == "listening" and spoke and any(g not in n_before for _, _, g in s["caps"]):
                    quiet_since = quiet_since or time.perf_counter()
                    if time.perf_counter() - quiet_since > 2.8:
                        return lat, s, hl
                await pg.wait_for_timeout(100)
            return lat, await probe(), hl

        _, s, _ = await wait_turn(set(), 40)
        greet = " ".join(t for c, t, _ in s["caps"] if c == "from-agent")
        print(f"[{label}] greeting ({time.perf_counter() - t_start:.1f}s): {greet[:200]}")
        g_ok = bool(re.search(r"\bAI\b", greet) and re.search(r"livekit", greet, re.I) and re.search(r"brief|arriv|VIP", greet, re.I))
        results.append({"beat": 0, "line": "(greeting)", "agent": greet, "ok": g_ok})
        for i, (line, want_state, want_say, bad_say) in enumerate(BEATS):
            n = {g for _, _, g in s["caps"]}
            dur = await pg.evaluate("(b) => window.__say(b)", clips[i])
            await pg.wait_for_timeout(int(dur * 1000))
            t_end = time.perf_counter()
            lat, s, hl = await wait_turn(n, 50, t_end)
            said = " ".join(t for c, t, g in s["caps"] if g not in n and c == "from-agent")
            heard = " ".join(t for c, t, g in s["caps"] if g not in n and c == "from-you")
            hl_text = " | ".join(" / ".join(e.get("targets", [])) for e in hl)
            checks = {
                "screen": want_state is None or bool(re.search(want_state, s["path"])),
                "said": want_say(said) if callable(want_say) else bool(re.search(want_say, said, re.I)),
                "not_said": bad_say is None or not re.search(bad_say, said, re.I),
            }
            ok = all(checks.values())
            shot = os.path.join(OUT, f"{label}_b{i + 1}.png")
            await pg.screenshot(path=shot)
            r = {"beat": i + 1, "line": line, "heard": heard, "screen": s["path"], "highlights": hl_text, "agent": said,
                 "latency_ms": round(lat) if lat else None, "checks": checks, "ok": ok, "shot": shot}
            results.append(r)
            print(f"[{label}] b{i + 1} {'PASS' if ok else 'FAIL'} {r['latency_ms']}ms screen={s['path']} hl={hl_text[:60]!r} fails={[k for k, v in checks.items() if not v]}\n    you: {heard[:110]}\n    agent: {said[:300]}")
        s = await probe()
        await pg.locator("#lk-root").locator("#launch").click()  # the launcher is the End button during a call
        await pg.wait_for_timeout(1500)
        await ctx.close()
        await b.close()
    lats = sorted(r["latency_ms"] for r in results[1:] if r.get("latency_ms"))
    out = {"brain": brain, "label": label, "results": results, "insights": s.get("insights"),
           "latency_p50_ms": lats[len(lats) // 2] if lats else None}
    with open(os.path.join(OUT, f"{label}.json"), "w") as f:
        json.dump(out, f, indent=2)
    passed = sum(r["ok"] for r in results)
    print(f"[{label}] {passed}/{len(results)} checks passed (greeting {'ok' if results[0]['ok'] else 'FAIL'}); p50 first word {out['latency_p50_ms']} ms")


if __name__ == "__main__":
    if sys.argv[1] == "--say":
        make_clips(sys.argv[2])
    else:
        asyncio.run(main())
