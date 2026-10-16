"""Headless Chrome (Playwright) + CDP screencast + drawn-in animated cursor."""
from __future__ import annotations
import asyncio, base64, io, math, os, random, re, time, json
from dataclasses import dataclass, field
from typing import Callable, Optional
from playwright.async_api import async_playwright, Page
from demo_agent import motion

W, H = int(os.getenv("SCREEN_W", 1280)), int(os.getenv("SCREEN_H", 720))
CHROME = os.getenv("CHROME_PATH", "/opt/google/chrome/chrome")
CDP_PORT = int(os.getenv("CDP_PORT", 0)) or __import__("random").randint(9300, 9899)  # per-process port

# Cursor overlay lives in the page DOM so the screencast captures it.  It is
# pointer-events:none so it never steals clicks.  Re-injected on every navigation.
CURSOR_JS = r"""
(() => {
 if (window.__kc) return;
 // remember the cursor across full page loads so it never jumps back to the centre after a navigation
 try { const p = JSON.parse(sessionStorage.getItem('__kpos') || 'null'); if (p && window.__kx == null) { window.__kx = p[0]; window.__ky = p[1]; } } catch (e) {}
 const save = () => { try { sessionStorage.setItem('__kpos', JSON.stringify([window.__kx, window.__ky])); } catch (e) {} };
 const put = (c, x, y, s) => { c.style.transform = `translate(${x}px,${y}px)` + (s && s !== 1 ? ` scale(${s})` : ''); window.__kx = x; window.__ky = y; };
 const mk = () => {
  if (document.getElementById('__kcur')) return;
  const c = document.createElement('div'); c.id='__kcur';
  const S = window.__kcSize || 32;  // ~1.3x a system cursor, like Screen Studio's default: readable in a 720p screen-share
  c.innerHTML = `<svg width="${S}" height="${S}" viewBox="0 0 24 24"><path d="M3 2l7 19 2.5-7.5L20 11z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  Object.assign(c.style,{position:'fixed',left:(-3*S/24)+'px',top:(-2*S/24)+'px',zIndex:2147483647,pointerEvents:'none',transformOrigin:(3*S/24)+'px '+(2*S/24)+'px',willChange:'transform',transform:`translate(${window.__kx??640}px,${window.__ky??360}px)`,filter:'drop-shadow(0 1px 1px rgba(0,0,0,.6)) drop-shadow(0 3px 6px rgba(0,0,0,.35))'});
  document.documentElement.appendChild(c);
 };
 let gen = 0;
 // after a glide the hand relaxes: one slow ~1.5 px drift over ~0.6 s, then perfectly still (no idle jitter/wandering)
 const settle = (c, my) => { const x0=window.__kx, y0=window.__ky, s=performance.now();
   const g=(now)=>{ if (my!==gen) return; const k=Math.min(1,(now-s)/600), e=1-Math.pow(1-k,3);
     put(c, x0+1.2*e, y0+0.9*e); if (k<1) requestAnimationFrame(g); else save(); };
   setTimeout(()=>requestAnimationFrame(g), 120); };
 window.__kc = {
  // play a precomputed trajectory: flat [t_ms,x,y, t_ms,x,y, ...] (faan/motion.py); linear between ~16 ms samples
  play(p){ mk(); const c=document.getElementById('__kcur'); const my=++gen; const n=p.length/3;
   if (!n) return Promise.resolve();
   // leaving the current target: its outline/spotlight fades as the cursor departs (never lingers on the old target)
   if (n > 1) { document.querySelectorAll('.__khl').forEach(o=>{o.style.transition='opacity .2s';o.style.opacity='0';setTimeout(()=>o.remove(),250)});
     const sp=document.getElementById('__kbeat'); if (sp) sp.style.opacity='0'; }
   const x0=window.__kx??p[1], y0=window.__ky??p[2], T=p[(n-1)*3], t0=performance.now();
   return new Promise(r=>{ const f=(now)=>{ if (my!==gen) return r();
     const t=Math.min(T, now-t0); let i=0; while (i<n-1 && p[i*3]<t) i++;
     const ta=i?p[(i-1)*3]:0, xa=i?p[(i-1)*3+1]:x0, ya=i?p[(i-1)*3+2]:y0, tb=p[i*3];
     const k=tb>ta?Math.max(0,Math.min(1,(t-ta)/(tb-ta))):1;
     put(c, xa+(p[i*3+1]-xa)*k, ya+(p[i*3+2]-ya)*k);
     if (t<T) requestAnimationFrame(f); else { save(); r(); if (T>200) settle(c, my); } }; requestAnimationFrame(f); }); },
  // legacy: curved min-jerk glide computed in-page
  move(x,y,ms){ mk(); const c=document.getElementById('__kcur'); const my=++gen;
   const x0=window.__kx??640, y0=window.__ky??360; const dx=x-x0, dy=y-y0, d=Math.hypot(dx,dy)||1;
   const bow=Math.min(150,0.18*d)*(dx>=0?1:-1); const cx=x0+dx*0.5-dy/d*bow, cy=y0+dy*0.5+dx/d*bow;
   const t0=performance.now(); ms=Math.max(1,ms||400);
   return new Promise(r=>{ const f=(now)=>{ if (my!==gen) return r(); let t=Math.min(1,(now-t0)/ms); const e=t*t*t*(10-15*t+6*t*t);
     put(c,(1-e)*(1-e)*x0+2*(1-e)*e*cx+e*e*x,(1-e)*(1-e)*y0+2*(1-e)*e*cy+e*e*y);
     if(t<1) requestAnimationFrame(f); else { save(); r(); } }; requestAnimationFrame(f); }); },
  // click feedback: the arrow dips (pressed) for ~110 ms
  press(){ mk(); const c=document.getElementById('__kcur'); const x=window.__kx??640, y=window.__ky??360;
   c.style.transition='transform 90ms ease-out'; put(c,x,y,0.84);
   setTimeout(()=>{ put(c,window.__kx,window.__ky,1); setTimeout(()=>{c.style.transition='';},100); },110);
   // the click is the payoff: the target outline fades shortly after so it never lingers through a page transition
   setTimeout(()=>document.querySelectorAll('.__khl').forEach(o=>{o.style.transition='opacity .3s';o.style.opacity='0';setTimeout(()=>o.remove(),350)}),280); },
  ripple(x,y){ const d=document.createElement('div');
   Object.assign(d.style,{position:'fixed',left:(x-14)+'px',top:(y-14)+'px',width:'28px',height:'28px',borderRadius:'50%',border:'2.5px solid #1fd5f9',background:'rgba(31,213,249,.18)',zIndex:2147483646,pointerEvents:'none',transform:'scale(.5)',transition:'transform .42s cubic-bezier(.2,.7,.3,1), opacity .42s ease-out',opacity:'1'});
   document.documentElement.appendChild(d); requestAnimationFrame(()=>requestAnimationFrame(()=>{d.style.transform='scale(1.6)';d.style.opacity='0'})); setTimeout(()=>d.remove(),520); },
  highlight(x,y,w,h){ document.querySelectorAll('.__khl').forEach(o=>{o.style.opacity='0'; setTimeout(()=>o.remove(),250)});
   const d=document.createElement('div'); d.className='__khl';
   Object.assign(d.style,{position:'fixed',left:x+'px',top:y+'px',width:w+'px',height:h+'px',outline:'3px solid #ffb703',borderRadius:'6px',zIndex:2147483645,pointerEvents:'none',transition:'opacity .22s ease-out, transform .22s ease-out',transform:'scale(1.04)',opacity:'0'});
   document.documentElement.appendChild(d); requestAnimationFrame(()=>requestAnimationFrame(()=>{d.style.opacity='1';d.style.transform='scale(1)'}));
   setTimeout(()=>{d.style.transition='opacity .6s';d.style.opacity='0'},1500); setTimeout(()=>d.remove(),2200); }
 };
 // Clicks made by *other* engines (e.g. Browser Use via CDP) still show a cursor + ripple.
 window.addEventListener('pointerdown', ev => { if (window.__kself) return; mk();
   const c=document.getElementById('__kcur'); ++gen; put(c, ev.clientX, ev.clientY); save(); window.__kc.ripple(ev.clientX,ev.clientY); }, true);
 if (document.readyState!=='loading') mk(); else document.addEventListener('DOMContentLoaded', mk);
})();
"""

# Element table (Jev-style indexed action space) of visible interactive elements.
ELEMENTS_JS = r"""
() => {
 const sel='a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=treeitem],[onclick],[tabindex]:not([tabindex="-1"]),[role=row],tr[class],[data-span-id],[data-testid*=span]';
 const out=[]; let i=0; document.querySelectorAll('[data-kid]').forEach(e=>e.removeAttribute('data-kid'));
 // if a modal/dialog/menu is open, only offer what's inside it (what a human could click)
 const dlg=[...document.querySelectorAll('[role=dialog],[aria-modal=true],dialog[open],[role=menu],[role=listbox]')].filter(d=>{const r=d.getBoundingClientRect();return r.width>40&&r.height>40}).pop();
 const root=dlg||document;
 const extra=dlg?[...dlg.querySelectorAll('label,[role=radio],[role=option],[role=checkbox],[data-state]')]:[];
 for (const e of [...new Set([...root.querySelectorAll(sel), ...extra])]) {
  const r=e.getBoundingClientRect(); if(r.width<4||r.height<4) continue;
  const off=(r.bottom<0||r.top>innerHeight||r.right<0||r.left>innerWidth); if(off && !dlg && (r.top>innerHeight*2.5||r.bottom<-innerHeight*1.5)) continue;
  const st=getComputedStyle(e); if(st.visibility==='hidden'||st.display==='none'||+st.opacity===0) continue;
  let t=(e.getAttribute('aria-label')||e.innerText||e.value||e.placeholder||e.title||'').replace(/\s+/g,' ').trim().slice(0,70);
  if(!t) continue; i++; e.setAttribute('data-kid',i);
  const href=e.getAttribute('href')||''; out.push({i, href:href.startsWith('http')?href.replace(location.origin,''):href, tag:(e.getAttribute('role')||e.tagName).toLowerCase(), text:t, off, x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2), w:Math.round(r.width), h:Math.round(r.height)});
  if(i>=int_max) break;
 }
 return {url:location.href, title:document.title, modal: dlg ? (dlg.getAttribute('aria-label')||(dlg.querySelector('h1,h2,h3')||{}).innerText||'dialog') : null, ...(()=>{const sc=[...document.querySelectorAll('main,section,div')].filter(q=>q.scrollHeight>q.clientHeight+4&&/(auto|scroll)/.test(getComputedStyle(q).overflowY)).sort((a,b)=>b.clientHeight*b.clientWidth-a.clientHeight*a.clientWidth)[0];return sc?{scrollY:Math.round(sc.scrollTop),maxScroll:Math.round(sc.scrollHeight-sc.clientHeight)}:{scrollY:Math.round(scrollY),maxScroll:Math.round(document.documentElement.scrollHeight-innerHeight)}})(), elements:out,
   headings:[...document.querySelectorAll('h1,h2,h3')].filter(h=>{const r=h.getBoundingClientRect();return r.top>=0&&r.top<innerHeight}).map(h=>h.innerText.trim().slice(0,60)).slice(0,8)};
}
""".replace("int_max", "150")


VOICE_BRIDGE = os.getenv("VOICE_BRIDGE", "1") == "1"   # customer <-> in-browser app audio (faan/voicebridge.py)
WEBRTC_IP_POLICY = os.getenv("WEBRTC_IP_POLICY", "default_public_and_private_interfaces")   # "" = Chromium default (see start())


@dataclass
class Stats:
    frames: int = 0
    first_frame_t: float = 0.0
    last_frame_t: float = 0.0
    click_to_visible_ms: list = field(default_factory=list)

    def fps(self) -> float:
        dt = self.last_frame_t - self.first_frame_t
        return (self.frames - 1) / dt if dt > 0 and self.frames > 1 else 0.0


class BrowserController:
    def __init__(self, on_frame: Optional[Callable[[bytes, float], None]] = None):
        self.on_frame = on_frame  # (jpeg_bytes, t_received)
        self.stats = Stats()
        self.page: Page | None = None
        self._pending_click_t: float | None = None
        self.checkpoints: dict[str, str] = {}

    async def start(self, start_url: str, storage_state: str | None = None):
        self._pw = await async_playwright().start()
        # One Chrome, exposed on a CDP port so other engines (Browser Use) can drive the SAME tab.
        self.browser = await self._pw.chromium.launch(
            executable_path=CHROME if os.path.exists(CHROME) else None, headless=True,
            args=[f"--remote-debugging-port={CDP_PORT}", "--disable-dev-shm-usage", "--no-sandbox",
                  "--disable-gpu", "--renderer-process-limit=2", "--js-flags=--max-old-space-size=1024",
                  # in-browser test calls (Agent Builder / Console "Start a session") need a microphone: headless has none
                  "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"]
                 + ([] if VOICE_BRIDGE else ["--use-fake-device-for-media-stream"])   # the voice bridge supplies the mic
                 # WebRTC in a LiveKit Cloud container (gVisor): Chromium's network-adapter enumeration finds nothing there, so a
                 # page's RTCPeerConnection gathered ZERO local ICE candidates and in-browser test calls never connected (ICE
                 # stuck at 'new'). This policy skips enumeration and binds to the default route (any-address sockets) instead.
                 + ([f"--force-webrtc-ip-handling-policy={WEBRTC_IP_POLICY}"] if WEBRTC_IP_POLICY else []))
        # Logged-in later: point FAAN_STORAGE_STATE at a saved Playwright storage_state JSON
        # (cookies + localStorage) captured once on a machine where Okta SSO works.
        ss = storage_state or os.getenv("FAAN_STORAGE_STATE")
        b64 = os.getenv("FAAN_STORAGE_STATE_B64")  # LiveKit Cloud secret (base64 of the storage_state JSON)
        if b64 and not (ss and os.path.exists(ss)):
            import base64, tempfile
            fd, ss = tempfile.mkstemp(suffix=".json"); os.write(fd, base64.b64decode(b64)); os.close(fd)
        self.ctx = await self.browser.new_context(viewport={"width": W, "height": H},
                                                  storage_state=ss if ss and os.path.exists(ss) else None,
                                                  device_scale_factor=1, permissions=["microphone", "camera"],
                                                  bypass_csp=VOICE_BRIDGE)   # the bridge's AudioWorklet module is blocked by app CSPs
        await self.ctx.add_init_script(CURSOR_JS)
        if VOICE_BRIDGE:   # before the first page, so even the start page is bridged (docs/VOICE_BRIDGE.md)
            from demo_agent.voicebridge import PAGE_JS
            await self.ctx.add_init_script(PAGE_JS)
        self.blocked_writes: list[str] = []; self.writes: list[str] = []
        if os.getenv("FAAN_PAID_GUARD", "1") == "1":
            await self.ctx.route("**/*", self._guard)
        self.page = await self.ctx.new_page()

        async def _new_tab(pg):   # links that open a new tab (target=_blank): show them in the shared tab instead
            try:
                if pg is self.page: return
                if await pg.opener() is None: return   # our own hidden tabs (faan/cleanup.py) aren't link pop-ups: leave them alone
                await pg.wait_for_load_state("domcontentloaded", timeout=5000)
                url = pg.url
                await pg.close()
                if url and url != "about:blank":
                    await self.page.goto(url); self.new_tab_redirects = getattr(self, "new_tab_redirects", 0) + 1
            except Exception:
                pass
        self.ctx.on("page", lambda pg: asyncio.ensure_future(_new_tab(pg)))
        await self.page.goto(start_url, wait_until="domcontentloaded")
        self.checkpoints["start"] = start_url
        await self._start_screencast()

    # Paid-compute guard (network level): the dashboard talks Connect-RPC (POST .../Service/Method).
    # Create/Update/Save pass; methods that deploy/run/start/dispatch/buy/bill/delete are aborted.
    _PAID = __import__("re").compile(r"/[A-Za-z_.]+Service/[A-Za-z]*(Deploy|Simulat|Dial|Egress|"
                                     r"Buy|Purchase|Billing|Payment|Checkout|Subscription|Upgrade|Delete|Remove|Revoke)[A-Za-z]*$")

    async def _guard(self, route):
        # Nabil (2026-10-14): NO blocks for the demo agent. Only record dashboard writes for the session log.
        rq = route.request
        if rq.method not in ("GET", "HEAD", "OPTIONS") and "cloud-api" in rq.url:
            self.writes.append(f"{rq.method} {rq.url.split('?')[0].rsplit('/', 2)[-2:]}")
        return await route.continue_()

    async def _start_screencast(self):
        self.cdp = await self.ctx.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._on_cast)
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 70,
                                                     "maxWidth": W, "maxHeight": H, "everyNthFrame": int(os.getenv("SCREENCAST_NTH", 2))})

    def _on_cast(self, p):
        now = time.perf_counter()
        asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))
        s = self.stats
        if not s.frames:
            s.first_frame_t = now
        s.frames += 1; s.last_frame_t = now
        if self._pending_click_t is not None:
            s.click_to_visible_ms.append((now - self._pending_click_t) * 1000)
            self._pending_click_t = None
        if self.on_frame:
            self.on_frame(base64.b64decode(p["data"]), now)

    # ---------- cursor-aware actions ----------
    async def move_to(self, x: float, y: float):
        """Glide the drawn cursor AND the real mouse along the same human-like path (faan/motion.py): Fitts-scaled
        duration, minimum-jerk speed profile, slight arc, tiny overshoot/settle on long moves. Never teleports."""
        if getattr(self, "last_move_start_t", None) is None:
            self.last_move_start_t = time.perf_counter()  # first move since reset (agent resets to None per request)
        try:
            cur = await self.page.evaluate("[window.__kx, window.__ky]")
        except Exception:
            cur = [None, None]
        if cur[0] is None:
            cur = list(getattr(self, "_kxy", None) or (W / 2, H / 2))
        pts = motion.path(cur[0], cur[1], x, y)
        self._kxy = (x, y)
        flat = [round(v, 1) for p in pts for v in p]

        async def real_mouse():   # follow the same path with the real pointer (hover effects along the way)
            t0 = time.perf_counter()
            for t, px, py in pts[1::3] if len(pts) > 3 else []:
                lag = t / 1000 - (time.perf_counter() - t0)
                if lag > 0: await asyncio.sleep(lag)
                elif lag < -0.06: continue          # running behind: skip, never rush
                try: await self.page.mouse.move(px, py)
                except Exception: return
        try:
            await asyncio.gather(self.page.evaluate("(p)=>window.__kc&&window.__kc.play(p)", flat), real_mouse())
        except Exception:
            pass
        try:
            await self.page.mouse.move(x, y)  # exact final hover (menus, tooltips)
        except Exception:
            pass

    async def click_fx(self, x: float, y: float):
        """Subtle click animation at (x, y): arrow dips + small ripple. Marks the next pointerdown as ours."""
        try:
            await self.page.evaluate("([x,y])=>{window.__kself=1;if(window.__kc){window.__kc.press&&window.__kc.press();window.__kc.ripple(x,y)}}", [x, y])
        except Exception:
            pass

    async def click_xy(self, x: float, y: float, pause_ms: int = 120):
        await self.move_to(x, y)
        await asyncio.sleep(pause_ms / 1000)  # hover pause before click
        await self.page.evaluate("([x,y])=>{window.__kself=1;window.__kc&&window.__kc.ripple(x,y)}", [x, y])
        self._pending_click_t = time.perf_counter()
        if getattr(self, "first_click_t", None) is None:
            self.first_click_t = self._pending_click_t
        await self.page.mouse.click(x, y)
        try:
            await self.page.evaluate("window.__kself=0")
        except Exception:
            pass

    async def reveal(self, el: dict) -> dict:
        """Scroll an off-screen element (e.g. a modal's Create button) into view; return fresh coordinates."""
        covered = await self.page.evaluate("""([k,x,y])=>{const e=document.querySelector(`[data-kid="${k}"]`); if(!e) return false;
            const h=document.elementFromPoint(x,y); return !(h && (e===h || e.contains(h) || h.contains(e)))}""", [el["i"], el["x"], el["y"]])
        if not el.get("off") and not covered:
            return el
        await self.page.evaluate("""(k)=>{const e=document.querySelector(`[data-kid="${k}"]`); if(!e) return null;
            e.scrollIntoView({block:'center',behavior:'smooth'}); return true}""", el["i"])
        await asyncio.sleep(0.5)
        r = await self.page.evaluate("""(k)=>{const e=document.querySelector(`[data-kid="${k}"]`); if(!e) return null;
            const r=e.getBoundingClientRect(); return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2), w:r.width, h:r.height}}""", el["i"])
        return {**el, **(r or {}), "off": False}

    async def hover_xy(self, x, y, w=0, h=0, dwell_ms=900):
        await self.move_to(x, y)
        if w and h:
            await self.page.evaluate("([x,y,w,h])=>window.__kc&&window.__kc.highlight(x,y,w,h)", [x - w / 2, y - h / 2, w, h])
        await asyncio.sleep(dwell_ms / 1000)

    _MAIN_SCROLLER_JS = """() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
      const dlg = [...document.querySelectorAll('[role=dialog],[aria-modal=true]')].filter(vis).pop();   // an open modal owns the wheel
      const root = dlg || document;
      const sc = [...(dlg ? [dlg] : []), ...root.querySelectorAll('main,section,div,form')].filter(q => q.scrollHeight > q.clientHeight + 4
      && /(auto|scroll)/.test(getComputedStyle(q).overflowY)).sort((a, b) => b.clientHeight * b.clientWidth - a.clientHeight * a.clientWidth)[0];
      if (!sc) return null; const r = sc.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }"""

    async def scroll(self, dy: int):
        """Wheel-scroll the page's main content (the dashboard scrolls an inner container, and the wheel scrolls whatever is under the pointer)."""
        try:
            c = await self.page.evaluate(self._MAIN_SCROLLER_JS)
            if c: await self.page.mouse.move(*c)
        except Exception:
            pass
        await self.page.mouse.wheel(0, dy); await asyncio.sleep(0.35)

    # ---- jev-guide port: exact element extraction (src/browser.js collectElements + rankElements) ----
    _COLLECT = open(os.path.join(os.path.dirname(__file__), "jev_collect.js")).read()

    async def snapshot(self, max_elements=240, focus_words=()):
        try:
            raw = await self.page.evaluate(self._COLLECT)
        except Exception:
            await asyncio.sleep(0.5); raw = await self.page.evaluate(self._COLLECT)
        words = [w.lower() for w in focus_words if len(w) > 2]
        def score(i_e):
            i, e = i_e; l = (e["label"] + " " + e["extra"]).lower()
            s = sum(3 for w in words if w in l) + (2 if e["inViewport"] else 0) + (1 if e["kind"] in ("text field", "search box", "dropdown", "select") else 0)
            return (-s, i)
        ranked = [e for _, e in sorted(enumerate(raw), key=score)][:max_elements]
        try:
            text = await self.page.evaluate("(document.body?.innerText||'').replace(/\\s+/g,' ').slice(0,1500)")
        except Exception:
            text = ""
        return {"url": self.page.url, "title": await self.page.title(), "elements": ranked, "truncated": len(raw) > len(ranked), "text": text}

    async def point_at(self, jid: str):
        """jev-guide pointAt: scrollIntoViewIfNeeded, glide the cursor there, settle, THEN outline it; hover HOVER_S total."""
        loc = self.page.locator(f'[data-jev-id="{jid}"]').first
        try:
            await loc.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        box = await loc.bounding_box()
        if not box:
            return None
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        await self.move_to(x, y)
        hover = float(os.getenv("HOVER_S", 0.45))
        settle = min(motion.SETTLE_MS / 1000, hover * 0.4)   # arrive, settle, then the outline lands (never before arrival)
        await asyncio.sleep(settle)
        await self.page.evaluate("([x,y,w,h])=>window.__kc&&window.__kc.highlight(x,y,w,h)", [box["x"] - 3, box["y"] - 3, box["width"] + 6, box["height"] + 6])
        await asyncio.sleep(max(0.0, hover - settle))        # visible hover on the outlined target (pre-click dwell in click_jev)
        return x, y

    async def click_jev(self, jid: str):
        pt = await self.point_at(jid)
        if not pt:
            raise RuntimeError("element not visible")
        await self.page.evaluate("([x,y])=>{window.__kself=1;window.__kc&&window.__kc.ripple(x,y)}", list(pt))
        self._pending_click_t = time.perf_counter()
        if getattr(self, "first_click_t", None) is None:
            self.first_click_t = self._pending_click_t
        u0 = self.page.url
        dlg = await self.page.evaluate("()=>!!document.querySelector('[role=dialog],[aria-modal=true]')")
        try:
            await self.page.mouse.click(*pt)
        except Exception:
            await self.page.locator(f'[data-jev-id="{jid}"]').first.click(timeout=5000, force=True)
        await self.settle_jev()
        if dlg:   # only submit-like buttons close a modal; fields, dropdowns and tabs inside it never do
            try:
                what = await self.page.evaluate("""(id) => { const e = document.querySelector(`[data-jev-id="${id}"]`); if (!e) return '';
                    return (e.tagName + ' ' + (e.getAttribute('type') || '') + ' ' + (e.innerText || e.value || e.getAttribute('aria-label') || '')).slice(0, 80); }""", jid)
            except Exception:
                what = ""
            dlg = bool(re.match(r"(BUTTON|A)\b", what) and re.search(r"\b(create|save|confirm|submit|add|deploy|done|apply|continue|next|ok|rent|buy|generate)\b", what, re.I)) or " submit" in what.lower()
        if dlg and self.page.url == u0:   # submit buttons in a modal (e.g. Create agent): wait for it to close or navigate
            for _ in range(16):
                if self.page.url != u0 or not await self.page.evaluate("()=>!!document.querySelector('[role=dialog],[aria-modal=true]')"): break
                if not await self.page.evaluate("()=>!!document.querySelector('[role=dialog] [aria-busy=true],[role=dialog] svg[class*=animate-spin],[role=dialog] [class*=spinner],[role=dialog] button:disabled')"): break
                await asyncio.sleep(0.5)
        if self.page.url != u0:   # SPA route change: give the new screen time to render (Agent Builder loads slowly)
            try: await self.page.wait_for_load_state("networkidle", timeout=3000)
            except Exception: pass

    async def type_jev(self, jid: str, text: str, submit=False):
        pt = await self.point_at(jid)
        if pt:
            await self.page.mouse.click(*pt)
        loc = self.page.locator(f'[data-jev-id="{jid}"]').first
        await loc.focus()
        # replace, never append: "Control+A" is select-all on Linux/Windows but "move to line start" on macOS (Emacs binding), which
        # inserted the new text IN FRONT of the old one in Monaco fields (Agent Builder Instructions / Welcome message)
        await self.page.keyboard.press("ControlOrMeta+A"); await self.page.keyboard.press("Backspace")
        try:
            if await loc.evaluate("e => (e.closest('.monaco-editor') ? 1 : 0)"):
                text_left = await loc.evaluate("e => (e.closest('.monaco-editor').querySelector('.view-lines')?.innerText || '').trim()")
                if text_left:   # still not empty: select the editor's whole model once more
                    await self.page.keyboard.press("ControlOrMeta+A"); await self.page.keyboard.press("Backspace")
        except Exception:
            pass
        if len(text) > 60 or "\n" in text:
            await self.page.keyboard.insert_text(text)
        else:
            await self.page.keyboard.type(text, delay=35)
        if submit:
            await self.page.keyboard.press("Enter")
        await self.settle_jev()

    async def settle_jev(self, ms=int(os.getenv("JEV_SETTLE_MS", 900))):
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(ms / 1000)
        await self.dismiss_banners()

    async def observe(self) -> dict:
        try:
            return await self.page.evaluate(ELEMENTS_JS)
        except Exception:
            await asyncio.sleep(0.5); await self.page.wait_for_load_state("domcontentloaded"); return await self.page.evaluate(ELEMENTS_JS)

    async def settle(self, timeout=4000):
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        await asyncio.sleep(float(os.getenv("SETTLE_S", 0.6)))
        await self.dismiss_banners()

    async def dismiss_banners(self):
        # cookie/consent overlays intercept clicks and confuse engines; dismiss before observing
        try:
            await self.page.evaluate("""() => { for (const b of document.querySelectorAll('button,[role=button]')) {
              const t=(b.innerText||'').trim(); if (/^(Accept|Accept all|Accept All|I agree|Got it)$/.test(t) || b.getAttribute('aria-label')==='Dismiss announcement') { b.click(); } } }""")
        except Exception:
            pass

    async def go_back(self):
        before = self.page.url
        try:
            await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
        except Exception:
            pass
        if not self.page.url.startswith("http"):   # backed out of the app (about:blank): return
            await self.page.goto(before, wait_until="domcontentloaded")

    async def save_checkpoint(self, name: str):
        self.checkpoints[name] = self.page.url

    async def reset(self, name: str = "start"):
        await self.page.goto(self.checkpoints.get(name, self.checkpoints["start"]), wait_until="domcontentloaded")

    async def screenshot_jpeg(self, width=1280, quality=70) -> bytes | None:
        try:
            b = await self.page.screenshot(type="jpeg", quality=quality, timeout=3000)
            from PIL import Image
            im = Image.open(io.BytesIO(b))
            if im.width != width:
                im = im.convert("RGB").resize((width, int(width * im.height / im.width))); o = io.BytesIO()
                im.save(o, "JPEG", quality=quality); b = o.getvalue()
            return b
        except Exception:
            return None

    async def end_test_call(self) -> bool:
        """Hang up a builder/console test call if one is active (so no compute lingers)."""
        try:
            b = self.page.get_by_role("button", name=__import__("re").compile(r"^(end call|disconnect|hang up|stop call)$", 2))
            if await b.count():
                await b.first.click(timeout=3000); await asyncio.sleep(1); return True
        except Exception:
            pass
        return False

    async def close(self):
        try:
            await self.browser.close(); await self._pw.stop()
        except Exception:
            pass
