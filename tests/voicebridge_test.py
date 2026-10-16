"""Unit tests for faan/voicebridge.py (docs/VOICE_BRIDGE.md test plan, part 1). No LiveKit room needed.

  .venv/bin/python experiments/voicebridge_test.py            # bridge installed before the page loads
  LATE=1 .venv/bin/python experiments/voicebridge_test.py     # installed after the app page is already open

1. mic: page getUserMedia({audio}) gets our stream; a 440 Hz tone pushed through BrowserAudioBridge.push gives RMS > 0
2. remote: loopback RTCPeerConnection oscillator reaches __vbOut, not silent; <audio srcObject> of the same track not double-tapped
3. state: on_state edges fire (mic on/off, remote on/off) with no polling; navigation resets the frame's state
4. router: human-only filter; two participants mixed with clipping; 16 kHz stereo input resampled to 48 kHz mono
"""
import array, asyncio, math, os, struct, sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from livekit import rtc
from playwright.async_api import async_playwright
from demo_agent.voicebridge import BrowserAudioBridge, RoomAudioRouter, SR, FRAME, link

URL = "https://voicebridge.test/"   # served by route: getUserMedia needs a secure context
results = []


def check(name, ok, info=""):
    results.append(ok); print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}")


def tone(n, f=440.0, amp=12000, t0=[0]):
    out = b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * f * (t0[0] + i) / SR))) for i in range(n)); t0[0] += n
    return out


async def browser_tests():
    edges = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        ctx = await b.new_context(permissions=["microphone"])
        await ctx.route("https://voicebridge.test/**", lambda r: r.fulfill(status=200, content_type="text/html", body="<html><body>vb</body></html>"))
        page = await ctx.new_page()
        br = BrowserAudioBridge(page)
        br.on_state(lambda a, d: edges.append((a, d["mic"], d["remote"])))
        if os.getenv("LATE"): await page.goto(URL); await br.install()
        else: await br.install(); await page.goto(URL)

        # 1) mic path
        devs = await page.evaluate("async () => (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput').map(d => d.label)")
        check("enumerateDevices reports bridge mic", devs == ["Faan bridge microphone"], str(devs))
        meas = asyncio.create_task(page.evaluate("""async () => {
            const s = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true}});
            const a = new AudioContext(); const an = a.createAnalyser(); an.fftSize = 2048; a.createMediaStreamSource(s).connect(an);
            const buf = new Float32Array(an.fftSize); let peak = 0; const t0 = performance.now();
            while (performance.now() - t0 < 1200) { await new Promise(r => setTimeout(r, 50)); an.getFloatTimeDomainData(buf);
              let sum = 0; for (const v of buf) sum += v * v; peak = Math.max(peak, Math.sqrt(sum / buf.length)); }
            const w = !!(window.__vbInstalled); s.getTracks().forEach(t => t.stop()); return [peak, w]; }"""))
        await asyncio.sleep(0.3)
        for _ in range(60):   # 20 ms frames like the router produces
            br.push(tone(FRAME)); await asyncio.sleep(0.02)
        rms, _ = await meas
        await asyncio.sleep(0.2)
        check("mic: pushed tone audible via getUserMedia", rms > 0.05, f"RMS={rms:.3f} pushes={br.pushed}")
        check("state: mic on then off edges", (True, True, False) in edges and edges[-1] == (False, False, False), str(edges))

        # 2) remote path + <audio> dedupe
        n0 = br.out_frames; edges.clear()
        taps = await page.evaluate("""async () => {
            const a = new AudioContext(); const osc = a.createOscillator(); osc.frequency.value = 440;
            const g = a.createGain(); g.gain.value = 0.5; const d = a.createMediaStreamDestination(); osc.connect(g); g.connect(d); osc.start();
            const p1 = new RTCPeerConnection(), p2 = new RTCPeerConnection();
            p1.onicecandidate = e => e.candidate && p2.addIceCandidate(e.candidate);
            p2.onicecandidate = e => e.candidate && p1.addIceCandidate(e.candidate);
            const got = new Promise(r => p2.ontrack = e => r(e.track));
            d.stream.getAudioTracks().forEach(t => p1.addTrack(t, d.stream));
            const o = await p1.createOffer(); await p1.setLocalDescription(o); await p2.setRemoteDescription(o);
            const an = await p2.createAnswer(); await p2.setLocalDescription(an); await p1.setRemoteDescription(an);
            const tr = await got; const el = document.createElement('audio'); el.srcObject = new MediaStream([tr]);   // app plays it too
            window.__pcs = [p1, p2]; return 1; }""")
        await asyncio.sleep(2.5)
        got = br.out_frames - n0
        check("remote: loopback audio reaches __vbOut", got > 80 and br.out_peak > 2000, f"frames={got} peak={br.out_peak}")
        check("remote: <audio> of same track not double-tapped", got < 160, f"frames in 2.5 s={got} (single tap ~125)")
        check("state: remote on edge", (True, False, True) in edges, str(edges))

        # 3) navigation resets the frame's state (edge to inactive), and the shim is re-installed on the new document
        edges.clear()
        await page.goto(URL + "next")
        await asyncio.sleep(0.3)
        check("navigation: inactive edge", edges and edges[-1][0] is False, str(edges))
        check("navigation: shim present on new page", await page.evaluate("() => !!window.__vbInstalled && !!window.__vbPush"))
        await br.stop(); await b.close()


async def router_tests():
    r = RoomAudioRouter(None)
    mk = lambda kind, src, ident: (NS(kind=rtc.TrackKind.KIND_AUDIO), NS(source=src), NS(kind=kind, identity=ident))
    STD, AG = rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
    MIC, SS = rtc.TrackSource.SOURCE_MICROPHONE, rtc.TrackSource.SOURCE_SCREENSHARE_AUDIO
    check("router: human mic accepted", RoomAudioRouter.accepts(*mk(STD, MIC, "customer"), local_identity="faan"))
    check("router: agent mic rejected", not RoomAudioRouter.accepts(*mk(AG, MIC, "other-agent"), local_identity="faan"))
    check("router: screenshare audio rejected", not RoomAudioRouter.accepts(*mk(STD, SS, "customer"), local_identity="faan"))
    check("router: own tracks rejected", not RoomAudioRouter.accepts(*mk(STD, MIC, "faan"), local_identity="faan"))

    # mixing: two loud humans clip instead of wrapping
    r._bufs = {"a": bytearray(array.array("h", [20000] * FRAME).tobytes()), "b": bytearray(array.array("h", [20000] * FRAME).tobytes())}
    m = array.array("h", r.mix_once())
    check("router: 2-person mix clipped", len(m) == FRAME and m[0] == 32767, f"len={len(m)} v={m[0]}")
    check("router: nothing left to mix", r.mix_once() is None)

    # resample 16 kHz stereo -> 48 kHz mono
    rs = rtc.AudioResampler(16000, SR, num_channels=1)
    for _ in range(10):
        st = array.array("h"); [st.extend((v, v)) for v in array.array("h", tone(320))[:320]]
        r.feed("c", rtc.AudioFrame(st.tobytes(), 16000, 2, 320), rs)
    for f in rs.flush(): r._bufs["c"] += bytes(f.data)   # the resampler holds back its filter delay until flushed
    got = len(r._bufs["c"]) // 2
    check("router: 16k stereo -> 48k mono", abs(got - 9600) < 1000, f"{got} samples for 200 ms (expect ~9600)")


async def main():
    await browser_tests()
    await router_tests()
    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} passed ->", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


asyncio.run(main())
