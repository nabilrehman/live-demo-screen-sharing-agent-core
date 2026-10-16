"""Voice bridge (design: docs/VOICE_BRIDGE.md, option A): let the customer talk to the agent being demoed INSIDE the shared
headless Chrome (Agent Builder 'Live preview' -> START CALL, Agent Console, any getUserMedia/WebRTC web app) and hear it.
No OS audio devices: runs the same on a Mac and in a LiveKit Cloud container.

  customer mic -> room -> RoomAudioRouter (humans only, mix, 48k mono) -> BrowserAudioBridge.push -> page getUserMedia stream
  page remote RTC / <audio srcObject> -> worklet tap -> __vbOut -> BrowserAudioBridge.on_out -> RoomAudioRouter 'demo-app-audio'

State: the page calls __vbState({mic, remote}) on every edge; BrowserAudioBridge merges frames and fires on_state(active, detail)
only on edges (no polling). FloorControl (faan/livecore.py) consumes those edges.
"""
import array, asyncio, base64, time
from typing import Callable

from livekit import rtc

SR = 48000
FRAME = 960                     # 20 ms @ 48 kHz

PAGE_JS = r"""(() => {
  if (window.__vbInstalled) return; window.__vbInstalled = true;
  const SR = 48000, JITTER = Math.round(SR * 0.06), MAXBUF = Math.round(SR * 0.4);
  let ctx = null, mic = null, workletOk = null;
  const fb = { q: [], len: 0, primed: false };                     // ScriptProcessor fallback ring
  const micTracks = new Set(), remote = new Map();                // our gUM tracks; tapped remote tracks by id
  let last = '';
  // diagnostics (reach the session log via __vbEv): getUserMedia calls, peer connections and their states, page errors
  const t0 = performance.now(), T = () => Math.round(performance.now() - t0);
  const dg = { gum: [], pcs: [], errs: [], enumN: 0 };
  const ev = (k, d) => { try { window.__vbEv && window.__vbEv(k, d); } catch (e) {} };
  const sj = v => { try { return JSON.stringify(v).slice(0, 300); } catch (e) { return String(v).slice(0, 300); } };
  window.addEventListener('error', e => { if (dg.errs.length < 20) { const m = String(e.message || e).slice(0, 200); dg.errs.push(m); ev('page_error', { m }); } });
  window.addEventListener('unhandledrejection', e => { if (dg.errs.length < 20) { const m = String((e.reason && (e.reason.stack || e.reason.message)) || e.reason).slice(0, 300); dg.errs.push(m); ev('page_rejection', { m }); } });
  const report = () => {
    const s = { mic: [...micTracks].some(t => t.readyState === 'live'), remote: [...remote.values()].some(r => r.track.readyState === 'live' && !r.track.muted) };
    const k = JSON.stringify(s); if (k === last) return; last = k;
    try { window.__vbState && window.__vbState(s); } catch (e) {} };
  window.__vbReport = () => { last = ''; report(); };

  const ac = () => { if (!ctx) { ctx = new AudioContext({ sampleRate: SR, latencyHint: 'interactive' });
      ctx.addEventListener('statechange', () => { if (ctx.state === 'suspended') ctx.resume().catch(() => {}); }); }
    if (ctx.state === 'suspended') ctx.resume().catch(() => {}); return ctx; };
  window.__vbCtxState = () => ctx ? ctx.state : 'none';
  const silentSink = () => { const g = ac().createGain(); g.gain.value = 0; g.connect(ctx.destination); return g; };

  const WORKLET = `
  class VbMic extends AudioWorkletProcessor {
    constructor() { super(); this.q = []; this.len = 0; this.primed = false;
      this.port.onmessage = e => { const f = e.data; this.q.push(f); this.len += f.length;
        while (this.len > ${MAXBUF} && this.q.length > 1) this.len -= this.q.shift().length; }; }
    process(_, outs) { const out = outs[0][0]; if (!out) return true;
      if (!this.primed) { if (this.len < ${JITTER}) { out.fill(0); return true; } this.primed = true; }
      let i = 0; while (i < out.length && this.q.length) { const h = this.q[0], k = Math.min(h.length, out.length - i);
        out.set(h.subarray(0, k), i); i += k; this.len -= k; if (k === h.length) this.q.shift(); else this.q[0] = h.subarray(k); }
      if (i < out.length) { out.fill(0, i); this.primed = false; }        // underrun: silence, re-prime the jitter buffer
      return true; } }
  class VbTap extends AudioWorkletProcessor {
    constructor() { super(); this.acc = new Float32Array(${960 * 4}); this.n = 0; }
    process(ins) { const inp = ins[0] && ins[0][0]; if (!inp) return true;
      this.acc.set(inp, this.n); this.n += inp.length;
      while (this.n >= 960) { this.port.postMessage(this.acc.slice(0, 960)); this.acc.copyWithin(0, 960, this.n); this.n -= 960; }
      return true; } }
  registerProcessor('vb-mic', VbMic); registerProcessor('vb-tap', VbTap);`;
  const loadWorklet = () => { if (workletOk !== null) return workletOk;
    const a = ac();
    workletOk = (async () => { try { const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
      await a.audioWorklet.addModule(url); return true; } catch (e) { return false; } })();   // CSP may block blob: -> ScriptProcessor
    return workletOk; };

  const b64ToF32 = b => { const s = atob(b), n = s.length >> 1, f = new Float32Array(n);
    for (let i = 0; i < n; i++) { let v = s.charCodeAt(2 * i) | (s.charCodeAt(2 * i + 1) << 8); if (v & 0x8000) v -= 0x10000; f[i] = v / 32768; } return f; };
  const f32ToB64 = f => { const u = new Uint8Array(f.length * 2);
    for (let i = 0; i < f.length; i++) { const v = Math.max(-1, Math.min(1, f[i])) * 32767 | 0; u[2 * i] = v & 255; u[2 * i + 1] = (v >> 8) & 255; }
    let s = ''; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  const emit = f => { try { window.__vbOut && window.__vbOut(f32ToB64(f)); } catch (e) {} };

  // ---- mic: getUserMedia(audio) -> our stream fed by __vbPush
  const ensureMic = async () => {
    if (mic) return mic; const a = ac(); const dest = a.createMediaStreamDestination(); let node;
    if (await loadWorklet()) node = new AudioWorkletNode(a, 'vb-mic', { numberOfInputs: 0, outputChannelCount: [1] });
    else { node = a.createScriptProcessor(1024, 1, 1);
      node.onaudioprocess = e => { const out = e.outputBuffer.getChannelData(0);
        if (!fb.primed) { if (fb.len < JITTER) { out.fill(0); return; } fb.primed = true; }
        let i = 0; while (i < out.length && fb.q.length) { const h = fb.q[0], k = Math.min(h.length, out.length - i);
          out.set(h.subarray(0, k), i); i += k; fb.len -= k; if (k === h.length) fb.q.shift(); else fb.q[0] = h.subarray(k); }
        if (i < out.length) { out.fill(0, i); fb.primed = false; } }; node.connect(silentSink()); }
    node.connect(dest); mic = { node, dest, worklet: node instanceof AudioWorkletNode };
    try { const an = a.createAnalyser(); an.fftSize = 2048; node.connect(an); const buf = new Float32Array(2048); let peak = 0;   // diagnostics:
      setInterval(() => { an.getFloatTimeDomainData(buf); for (const v of buf) peak = Math.max(peak, Math.abs(v)); }, 50);      // the mic's level
      window.__vbMicPeak = () => { const p = peak; peak = 0; return p; }; } catch (e) {}
    return mic; };
  window.__vbPush = b => { const f = b64ToF32(b);
    if (mic && mic.worklet) mic.node.port.postMessage(f, [f.buffer]);
    else { fb.q.push(f); fb.len += f.length; while (fb.len > MAXBUF && fb.q.length > 1) fb.len -= fb.q.shift().length; } };

  const md = navigator.mediaDevices;
  if (md && md.getUserMedia && !md.__vb) {
    md.__vb = true; const orig = md.getUserMedia.bind(md), origEnum = md.enumerateDevices && md.enumerateDevices.bind(md);
    md.getUserMedia = async c => {
      const g = { t: T(), c: sj(c) }; dg.gum.push(g); ev('gum_call', g);
      try { const r = await gum(c); g.ok = r.getTracks().map(x => x.kind + ':' + x.readyState).join(','); ev('gum_ok', g); return r; }
      catch (e) { g.err = String(e && (e.name + ': ' + e.message)); ev('gum_error', g); throw e; } };
    const gum = async c => {
      if (!c || !c.audio) return orig(c);
      const m = await ensureMic(); const t = m.dest.stream.getAudioTracks()[0].clone(); const out = new MediaStream([t]);
      if (c.video) (await orig({ video: c.video })).getVideoTracks().forEach(v => out.addTrack(v));
      const stop = t.stop.bind(t); t.stop = () => { stop(); report(); }; t.addEventListener('ended', report);
      micTracks.add(t); report(); return out; };
    if (origEnum) md.enumerateDevices = async () => { dg.enumN++; const d = (await origEnum()).filter(x => x.kind !== 'audioinput');
      return [{ deviceId: 'default', groupId: 'faan', kind: 'audioinput', label: 'Faan bridge microphone', toJSON() { return this; } }, ...d]; };
  }

  // ---- remote audio taps (RTCPeerConnection tracks + <audio>/<video> srcObject), deduped by track id.
  // ALL remote tracks are summed on ONE bus feeding ONE tap, so __vbOut is a single real-time 48 kHz stream (50 frames/s) no
  // matter how many tracks are tapped. (livekit-client pre-allocates 3 recvonly audio transceivers: one tap per track sent
  // 150 frames/s, i.e. the agent's 20 ms frames interleaved with two silent tracks' frames, which the router then thinned out.)
  let bus = null;
  const ensureBus = async () => { if (bus) return bus; const a = ac(); const g = a.createGain(); g.gain.value = 1; let node;
    if (await loadWorklet()) { node = new AudioWorkletNode(a, 'vb-tap', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
        channelCount: 1, channelCountMode: 'explicit', channelInterpretation: 'speakers' });
      node.port.onmessage = e => { if (remote.size) emit(e.data); }; }
    else { let acc = new Float32Array(0); node = a.createScriptProcessor(1024, 1, 1);
      node.onaudioprocess = e => { if (!remote.size) { acc = new Float32Array(0); return; } const inp = e.inputBuffer.getChannelData(0);
        const n = new Float32Array(acc.length + inp.length); n.set(acc); n.set(inp, acc.length); acc = n;
        while (acc.length >= 960) { emit(acc.slice(0, 960)); acc = acc.slice(960); } }; }
    if (bus) { try { node.disconnect(); } catch (e) {} return bus; }   // lost a race with another caller
    g.connect(node); node.connect(silentSink()); bus = { g, node }; return bus; };
  const tap = async track => {
    if (!track || track.kind !== 'audio' || remote.has(track.id)) return;
    const rec = { track }; remote.set(track.id, rec);
    const ms = new MediaStream([track]);
    try { const el = document.createElement('audio'); el.muted = true; el.__vbSkip = true; el.srcObject = ms; el.play().catch(() => {}); rec.el = el; } catch (e) {}   // Chrome: remote WebRTC audio is silent in WebAudio unless also on a media element
    const a = ac(), src = a.createMediaStreamSource(ms), b = await ensureBus();
    src.connect(b.g); rec.src = src;
    const end = () => { if (rec.done) return; rec.done = true; try { src.disconnect(); } catch (e) {} try { rec.el && (rec.el.srcObject = null); } catch (e) {}
      remote.delete(track.id); report(); };
    track.addEventListener('ended', end);
    track.addEventListener('mute', report); track.addEventListener('unmute', report);   // muted = no RTP yet / paused: temporary
    report();
    rec.iv = setInterval(() => { if (track.readyState !== 'live') { clearInterval(rec.iv); end(); } }, 1000); };   // remote 'ended' isn't always fired

  // receivers are polled too: a receiver's track can appear or change without a 'track' event reaching us
  const pcs = new Set();
  setInterval(() => { for (const pc of pcs) {
      if (pc.connectionState === 'closed') { pcs.delete(pc); continue; }
      try { pc.getReceivers().forEach(r => r.track && r.track.kind === 'audio' && r.track.readyState === 'live' && tap(r.track)); } catch (e) {} }
    if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {}); }, 500);

  const OrigPC = window.RTCPeerConnection;
  if (OrigPC && !OrigPC.__vb) {
    const PC = function (...args) { const pc = new OrigPC(...args); pcs.add(pc);
      const cfg = args[0] || {}, rec = { id: dg.pcs.length, t: T(), ice: (cfg.iceServers || []).map(x => sj(x.urls)).join(' ').slice(0, 300), policy: cfg.iceTransportPolicy || '' };
      dg.pcs.push(rec); rec.pc = pc; ev('pc_new', { id: rec.id, t: rec.t, ice: rec.ice, policy: rec.policy });
      const st = () => { const d = { id: rec.id, t: T(), conn: pc.connectionState, ice: pc.iceConnectionState, gather: pc.iceGatheringState, sig: pc.signalingState };
        const k = d.conn + d.ice + d.gather + d.sig; if (k !== rec.k) { rec.k = k; ev('pc_state', d); } };
      ['connectionstatechange', 'iceconnectionstatechange', 'icegatheringstatechange', 'signalingstatechange'].forEach(n => pc.addEventListener(n, st));
      pc.addEventListener('icecandidate', e => { const c = e.candidate; rec.lc = (rec.lc || 0) + 1;
        if (rec.lc <= 8) ev('pc_local_cand', { id: rec.id, t: T(), c: c ? String(c.candidate).slice(0, 120) : 'end-of-candidates' }); });
      const ra = pc.addIceCandidate.bind(pc); pc.addIceCandidate = (c, ...r) => { rec.rc = (rec.rc || 0) + 1;
        if (rec.rc <= 4) ev('pc_remote_cand', { id: rec.id, t: T(), c: c && c.candidate !== undefined ? String(c.candidate).slice(0, 120) : String(c) }); return ra(c, ...r); };
      pc.addEventListener('icecandidateerror', e => { if ((rec.ce = (rec.ce || 0) + 1) <= 5) ev('pc_ice_error', { id: rec.id, code: e.errorCode, text: String(e.errorText).slice(0, 80), url: e.url }); });
      pc.addEventListener('track', ev => tap(ev.track));
      pc.addEventListener('connectionstatechange', () => { if (pc.connectionState === 'closed' || pc.connectionState === 'failed')
        pc.getReceivers().forEach(r => r.track && remote.has(r.track.id) && r.track.dispatchEvent(new Event('ended'))); });
      return pc; };
    PC.prototype = OrigPC.prototype; Object.setPrototypeOf(PC, OrigPC); PC.__vb = true;
    window.RTCPeerConnection = PC; if (window.webkitRTCPeerConnection) window.webkitRTCPeerConnection = PC;
  }
  window.__vbDiag = () => ({ ctx: ctx ? ctx.state : 'none', worklet: workletOk === null ? null : 'loaded', mic: !!mic, enumN: dg.enumN,
    gum: dg.gum.slice(-4), errs: dg.errs.slice(-3), remote: [...remote.values()].map(r => r.track.readyState + (r.track.muted ? ':muted' : '')),
    micTracks: [...micTracks].map(t => t.readyState + (t.muted ? ':muted' : '') + (t.enabled ? '' : ':disabled')),
    pcs: dg.pcs.slice(-4).map(r => ({ id: r.id, conn: r.pc.connectionState, ice: r.pc.iceConnectionState, rx: r.pc.getReceivers().length, tx: r.pc.getSenders().filter(s => s.track).length })),
    fs: !!document.fullscreenElement, vis: document.visibilityState, focus: document.hasFocus() });
  const desc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'srcObject');
  if (desc && desc.set && !HTMLMediaElement.prototype.__vb) {
    HTMLMediaElement.prototype.__vb = true;
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', { configurable: true, enumerable: desc.enumerable, get: desc.get,
      set(v) { desc.set.call(this, v); if (!this.__vbSkip && v && v.getAudioTracks) v.getAudioTracks().forEach(tap); } });
  }
})();"""


def _net_env() -> dict:
    """The host's network view (WebRTC ICE needs usable interfaces): logged once so cloud/local differences are visible."""
    import os, platform, socket
    out = {"os": platform.platform()[:60]}
    try: out["ifaces"] = [n for _, n in socket.if_nameindex()][:8]
    except Exception as e: out["ifaces"] = f"err {type(e).__name__}"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 53)); out["route_ip"] = s.getsockname()[0]; s.close()
    except Exception as e: out["route_ip"] = f"err {type(e).__name__}"
    try: out["kernel"] = open("/proc/version").read()[:80]
    except Exception: pass
    return out


class BrowserAudioBridge:
    """Page side. Bindings live on the browser CONTEXT, so new pages/tabs/frames and navigations are covered."""

    def __init__(self, page, log: Callable = None, batch_ms: int = 40):
        self.page, self.ctx = page, page.context
        self.log = log or (lambda *a, **k: None)
        self.batch = SR * 2 * batch_ms // 1000
        self._frames: dict = {}                        # frame -> {"mic": bool, "remote": bool}
        self._out_cbs: list[Callable] = []
        self._state_cbs: list[Callable] = []
        self._buf = bytearray()
        self._flush_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.active = False
        self.out_frames = 0; self.out_peak = 0; self.pushed = 0

    # ---- public API
    def on_out(self, cb: Callable[[bytes], None]): self._out_cbs.append(cb)
    def on_state(self, cb: Callable[[bool, dict], None]): self._state_cbs.append(cb)

    @property
    def mic_active(self) -> bool: return any(s.get("mic") for s in self._frames.values())
    @property
    def remote_active(self) -> bool: return any(s.get("remote") for s in self._frames.values())

    async def install(self):
        for name, fn in (("__vbOut", self._b_out), ("__vbState", self._b_state), ("__vbEv", self._b_ev)):
            try: await self.ctx.expose_binding(name, fn)
            except Exception as e:
                if "already registered" not in str(e): raise
        await self.ctx.add_init_script(PAGE_JS)
        for fr in self.page.frames:   # documents already open: init scripts only run on the next navigation
            try: await fr.evaluate(PAGE_JS)
            except Exception: pass
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda e: self._diag_log("page_exception", m=str(e)[:300]))
        self.page.on("framenavigated", self._reset_frame)
        self.page.on("framedetached", self._reset_frame)
        self._flush_task = asyncio.create_task(self._flush_loop())
        self.log("voicebridge_installed", **_net_env())

    def push(self, pcm: bytes):
        """Customer audio (int16 48 kHz mono) for the page's microphone; batched ~40 ms. Dropped unless the page's mic is live."""
        if self.mic_active:
            self._buf += pcm
            if len(self._buf) > SR * 2: del self._buf[:len(self._buf) - SR]   # page stalled: keep the newest 0.5 s

    async def stop(self):
        if self._flush_task: self._flush_task.cancel()
        if self._burst: self._burst.cancel()
        self._frames.clear(); self._emit_state()

    # ---- internals
    def _b_out(self, source, b64: str):
        pcm = base64.b64decode(b64); self.out_frames += 1
        now = time.perf_counter()
        if now - getattr(self, "_out_t", 0) >= 5:   # vb_out_frames: the page tap's rate (50/s = real time; 150/s was the 3-tap bug)
            if getattr(self, "_out_t", 0): self.log("vb_out_frames", fps=round((self.out_frames - self._out_n) / (now - self._out_t), 1), peak=self.out_peak)
            self._out_t, self._out_n, self.out_peak = now, self.out_frames, 0
        if self.out_frames % 25 == 1:
            a = array.array("h", pcm); self.out_peak = max(self.out_peak, max(map(abs, a), default=0))
        for cb in self._out_cbs:
            try: cb(pcm)
            except Exception as e: self.log("voicebridge_out_cb_error", error=f"{type(e).__name__}: {e}"[:120])

    # ---- diagnostics: page events (gUM, peer connections, errors) + a 30 s snapshot burst once a call starts
    _diag_n = 0
    _burst: "asyncio.Task | None" = None

    def _diag_log(self, kind: str, **kw):
        self._diag_n += 1
        if self._diag_n <= 400: self.log("vb_" + kind, **kw)   # bounded: a broken page can't flood the session log

    def _b_ev(self, source, kind: str, d: dict):
        fr = source.get("frame"); url = (getattr(fr, "url", "") or "")[:80]
        self._diag_log(kind, frame=url if fr is not self.page.main_frame else "main", **(d or {}))
        if kind in ("gum_call", "pc_new") and (self._burst is None or self._burst.done()):
            self._burst = asyncio.create_task(self._diag_burst())

    def _on_console(self, msg):
        try:
            if msg.type in ("error", "warning") and self._diag_n < 300:
                self._diag_log("console", level=msg.type, text=msg.text[:240])
        except Exception: pass

    async def diag_snapshot(self) -> dict:
        frames = []
        for fr in self.page.frames:
            try: d = await fr.evaluate("() => window.__vbDiag ? window.__vbDiag() : null")
            except Exception as e: d = f"err {type(e).__name__}"
            frames.append({"url": (fr.url or "")[:80], "diag": d})
        try:
            status = await self.page.evaluate(r"""() => { const t = document.body ? document.body.innerText : '';
              const m = t.split('\n').filter(l => /connect|call|microphone|mic\b|error|fail|permission|listening|speaking|disconnect/i.test(l));
              return m.slice(0, 8).map(l => l.slice(0, 80)); }""")
        except Exception: status = None
        return {"frames": frames, "status": status, "state": self._last_detail if hasattr(self, "_last_detail") else None}

    async def _diag_burst(self, every_s: float = 2.0, total_s: float = 30.0):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < total_s:
            try: self._diag_log("diag", s=round(time.perf_counter() - t0, 1), **(await self.diag_snapshot()))
            except Exception as e: self._diag_log("diag_error", error=f"{type(e).__name__}: {e}"[:120])
            await asyncio.sleep(every_s)

    def _b_state(self, source, s: dict):
        self._frames[source["frame"]] = {"mic": bool(s.get("mic")), "remote": bool(s.get("remote"))}
        self._emit_state()

    def _reset_frame(self, frame):
        if self._frames.pop(frame, None) is not None: self._emit_state()

    def _emit_state(self):
        """Edges of mic OR remote (not only of 'active'): the app's audio often goes live before its mic opens."""
        a = self.mic_active or self.remote_active
        detail = {"mic": self.mic_active, "remote": self.remote_active}
        if detail == getattr(self, "_last_detail", None): return
        self._last_detail = detail
        self.active = a
        if not a: self._buf.clear()
        self.log("voicebridge_state", active=a, **detail)
        for cb in self._state_cbs:
            try: cb(a, detail)
            except Exception as e: self.log("voicebridge_state_cb_error", error=f"{type(e).__name__}: {e}"[:120])

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(0.04)
            if not self._buf: continue
            chunk = bytes(self._buf); self._buf.clear()
            b64 = base64.b64encode(chunk).decode()
            for fr, st in list(self._frames.items()):
                if not st.get("mic"): continue
                try: await fr.evaluate("b => window.__vbPush && window.__vbPush(b)", b64); self.pushed += 1
                except Exception: pass   # frame navigating/detached


class RoomAudioRouter:
    """Room side. Customer (human) mics in -> mixed 20 ms int16 48 kHz mono frames to on_mic; app audio out as 'demo-app-audio'."""
    OUT_MAX_FRAMES = 10   # 200 ms of app audio queued at most

    def __init__(self, room: "rtc.Room | None", log: Callable = None, track_name: str = "demo-app-audio"):
        self.room, self.log, self.track_name = room, log or (lambda *a, **k: None), track_name
        self.active = False
        self.source: "rtc.AudioSource | None" = None
        self._pub = None
        self._readers: dict[str, asyncio.Task] = {}
        self._bufs: dict[str, bytearray] = {}
        self._mic_cbs: list[Callable] = []
        self._outq: asyncio.Queue = asyncio.Queue()
        self.in_frames = self.out_frames = self.dropped = self.out_speech = 0
        self._tasks: list[asyncio.Task] = []

    def on_mic(self, cb: Callable[[bytes], None]): self._mic_cbs.append(cb)

    def set_active(self, a: bool, *_):
        if a == self.active: return
        self.active = a
        for b in self._bufs.values(): b.clear()
        self.log("router_active", active=a)

    def play(self, pcm: bytes):
        """App audio (int16 48 kHz mono) to publish to the room. Never gated on the floor: when the app speaks, it is heard.
        Real-time stream: if the page ever produces faster than real time, drop the OLDEST frames and keep latency <= ~200 ms
        (it used to drop the newest at a 2 s backlog, which turned speech into clicks when 3 taps were interleaved)."""
        self.in_frames += 1
        while self._outq.qsize() >= self.OUT_MAX_FRAMES:
            try: self._outq.get_nowait(); self.dropped += 1
            except asyncio.QueueEmpty: break
        self._outq.put_nowait(pcm)

    async def start(self):
        if self.room is not None:
            self.source = rtc.AudioSource(SR, 1, queue_size_ms=200)
            track = rtc.LocalAudioTrack.create_audio_track(self.track_name, self.source)
            self._pub = await self.room.local_participant.publish_track(
                track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_UNKNOWN))
            self.room.on("track_subscribed", self._on_track)
            self.room.on("track_unsubscribed", lambda t, pub, p: self._drop(t.sid))
            self.room.on("participant_disconnected", lambda p: [self._drop(pub.sid) for pub in p.track_publications.values()])
            for p in self.room.remote_participants.values():
                for pub in p.track_publications.values():
                    if pub.track is not None: self._on_track(pub.track, pub, p)
        self._tasks += [asyncio.create_task(self._mix_loop()), asyncio.create_task(self._out_loop()), asyncio.create_task(self._stats_loop())]

    async def stop(self):
        for t in self._tasks + list(self._readers.values()): t.cancel()
        self._tasks.clear(); self._readers.clear(); self._bufs.clear()
        if self._pub is not None and self.room is not None:
            try: await self.room.local_participant.unpublish_track(self._pub.sid)
            except Exception: pass

    # ---- filter: only humans' microphones
    @staticmethod
    def accepts(track, pub, participant, local_identity: str | None = None) -> bool:
        return (track.kind == rtc.TrackKind.KIND_AUDIO
                and getattr(pub, "source", None) == rtc.TrackSource.SOURCE_MICROPHONE
                and participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
                and participant.identity != local_identity)

    def _on_track(self, track, pub, participant):
        local = self.room.local_participant.identity if self.room is not None else None
        if not self.accepts(track, pub, participant, local) or track.sid in self._readers: return
        self._bufs[track.sid] = bytearray()
        self._readers[track.sid] = asyncio.create_task(self._read(track))
        self.log("router_mic", participant=participant.identity, track=track.sid)

    def _drop(self, sid):
        t = self._readers.pop(sid, None); self._bufs.pop(sid, None)
        if t: t.cancel()

    async def _read(self, track):
        stream = rtc.AudioStream(track)   # native rate/channels; resampled below with rtc.AudioResampler
        rs, rate = None, None
        try:
            async for ev in stream:
                f = ev.frame
                if not self.active: continue
                if f.sample_rate != rate:   # (re)create the resampler when the input rate changes
                    rate = f.sample_rate; rs = rtc.AudioResampler(rate, SR, num_channels=1) if rate != SR else None
                self.feed(track.sid, f, rs)
        finally:
            await stream.aclose()

    def feed(self, key: str, frame: "rtc.AudioFrame", resampler: "rtc.AudioResampler | None" = None):
        """Add one input frame for a participant track: downmix to mono, resample to 48 kHz."""
        pcm = array.array("h", bytes(frame.data))
        if frame.num_channels > 1:
            c = frame.num_channels
            pcm = array.array("h", (sum(pcm[i:i + c]) // c for i in range(0, len(pcm), c)))
        if frame.sample_rate != SR:
            resampler = resampler or rtc.AudioResampler(frame.sample_rate, SR, num_channels=1)
            out = b"".join(bytes(f.data) for f in resampler.push(rtc.AudioFrame(pcm.tobytes(), frame.sample_rate, 1, len(pcm))))
        else:
            out = pcm.tobytes()
        b = self._bufs.setdefault(key, bytearray()); b += out
        if len(b) > SR: del b[:len(b) - SR // 2]   # >0.5 s backlog: keep newest

    def mix_once(self) -> bytes | None:
        """One 20 ms mixed frame from every participant buffer that has audio (sum with clipping)."""
        n = FRAME * 2
        ready = [b for b in self._bufs.values() if len(b) >= n]
        if not ready: return None
        acc = [0] * FRAME
        for b in ready:
            a = array.array("h", bytes(b[:n])); del b[:n]
            for i, v in enumerate(a): acc[i] += v
        return array.array("h", (max(-32768, min(32767, v)) for v in acc)).tobytes()

    async def _mix_loop(self):
        nxt = time.perf_counter()
        while True:
            nxt += 0.02
            await asyncio.sleep(max(0, nxt - time.perf_counter()))
            if not self.active: continue
            while (f := self.mix_once()) is not None:
                for cb in self._mic_cbs:
                    try: cb(f)
                    except Exception: pass

    async def _out_loop(self):
        while True:
            pcm = await self._outq.get()
            if self.source is None: continue
            try:
                await self.source.capture_frame(rtc.AudioFrame(pcm, SR, 1, len(pcm) // 2)); self.out_frames += 1
                a = array.array("h", pcm)
                if a and max(map(abs, a[::8])) > 300: self.out_speech += 1   # ~-40 dBFS: frames that carry sound
            except Exception: pass

    async def _stats_loop(self, every_s: float = 5.0):
        """Observability per hop: page tap -> router in -> published track. Logged only while app audio flows."""
        last = (0, 0, 0, 0)
        while True:
            await asyncio.sleep(every_s)
            cur = (self.in_frames, self.out_frames, self.dropped, self.out_speech)
            if cur[0] != last[0]:
                d = [c - l for c, l in zip(cur, last)]
                self.log("router_out_frames", in_fps=round(d[0] / every_s, 1), out_fps=round(d[1] / every_s, 1), dropped=d[2],
                         speech_frames=d[3], backlog=self._outq.qsize(), subscribed=bool(self._pub and getattr(self._pub, "track", None)))
            last = cur


def link(bridge: BrowserAudioBridge, router: RoomAudioRouter):
    """Customer mic -> page; page audio -> room; router forwards only while the bridge is active."""
    router.on_mic(bridge.push)
    bridge.on_out(router.play)
    bridge.on_state(router.set_active)
