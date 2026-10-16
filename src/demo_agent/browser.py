"""The shared browser: headless Chromium (Playwright), its CDP screencast, and a drawn cursor that glides to each target."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from collections.abc import Callable

from playwright.async_api import Page, async_playwright

from demo_agent import motion

W, H = int(os.getenv("SCREEN_W", 1280)), int(os.getenv("SCREEN_H", 720))
CHROME = os.getenv("CHROME_PATH", "/opt/google/chrome/chrome")

# The cursor lives in the page DOM so the screencast captures it. pointer-events:none, so it never takes a click.
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
  const S = window.__kcSize || 32;  // ~1.3x a system cursor: readable in a 720p screen share
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
  // play a precomputed trajectory: flat [t_ms,x,y, t_ms,x,y, ...] (motion.py); linear between ~16 ms samples
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
  ripple(x,y){ const d=document.createElement('div');
   Object.assign(d.style,{position:'fixed',left:(x-14)+'px',top:(y-14)+'px',width:'28px',height:'28px',borderRadius:'50%',border:'2.5px solid #1fd5f9',background:'rgba(31,213,249,.18)',zIndex:2147483646,pointerEvents:'none',transform:'scale(.5)',transition:'transform .42s cubic-bezier(.2,.7,.3,1), opacity .42s ease-out',opacity:'1'});
   document.documentElement.appendChild(d); requestAnimationFrame(()=>requestAnimationFrame(()=>{d.style.transform='scale(1.6)';d.style.opacity='0'})); setTimeout(()=>d.remove(),520); },
  highlight(x,y,w,h){ document.querySelectorAll('.__khl').forEach(o=>{o.style.opacity='0'; setTimeout(()=>o.remove(),250)});
   const d=document.createElement('div'); d.className='__khl';
   Object.assign(d.style,{position:'fixed',left:x+'px',top:y+'px',width:w+'px',height:h+'px',outline:'3px solid #ffb703',borderRadius:'6px',zIndex:2147483645,pointerEvents:'none',transition:'opacity .22s ease-out, transform .22s ease-out',transform:'scale(1.04)',opacity:'0'});
   document.documentElement.appendChild(d); requestAnimationFrame(()=>requestAnimationFrame(()=>{d.style.opacity='1';d.style.transform='scale(1)'}));
   setTimeout(()=>{d.style.transition='opacity .6s';d.style.opacity='0'},1500); setTimeout(()=>d.remove(),2200); }
 };
 // clicks that don't come through move_to (e.g. a locator click) still show the cursor and a ripple
 window.addEventListener('pointerdown', ev => { if (window.__kself) return; mk();
   const c=document.getElementById('__kcur'); ++gen; put(c, ev.clientX, ev.clientY); save(); window.__kc.ripple(ev.clientX,ev.clientY); }, true);
 if (document.readyState!=='loading') mk(); else document.addEventListener('DOMContentLoaded', mk);
})();
"""

VOICE_BRIDGE = os.getenv("VOICE_BRIDGE", "1") == "1"  # customer <-> in-browser app audio (voicebridge.py)
JEV_SETTLE_MS = int(os.getenv("JEV_SETTLE_MS", 900))  # pause after each of Jev's own clicks
WEBRTC_IP_POLICY = os.getenv("WEBRTC_IP_POLICY", "default_public_and_private_interfaces")  # "" = Chromium default


class BrowserController:
    def __init__(self, on_frame: Callable[[bytes, float], None] | None = None):
        self.on_frame = on_frame  # (jpeg_bytes, t_received)
        self.page: Page | None = None
        self.trace = None  # SessionLog.event, for Jev's decisions
        self._kxy = None  # where the drawn cursor is

    async def start(self, start_url: str, storage_state: str | None = None):
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            executable_path=CHROME if os.path.exists(CHROME) else None,
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--renderer-process-limit=2",
                "--js-flags=--max-old-space-size=1024",
                # in-browser test calls need a microphone, and headless has none
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ]
            + ([] if VOICE_BRIDGE else ["--use-fake-device-for-media-stream"])  # the voice bridge supplies the mic
            # in a LiveKit Cloud container Chromium finds no network adapters, so WebRTC gathers no ICE candidates;
            # this policy binds to the default route instead
            + ([f"--force-webrtc-ip-handling-policy={WEBRTC_IP_POLICY}"] if WEBRTC_IP_POLICY else []),
        )
        # logged in: FAAN_STORAGE_STATE is a Playwright storage_state JSON file, FAAN_STORAGE_STATE_B64 the same as base64
        ss = storage_state or os.getenv("FAAN_STORAGE_STATE")
        b64 = os.getenv("FAAN_STORAGE_STATE_B64")
        if b64 and not (ss and os.path.exists(ss)):
            import tempfile

            fd, ss = tempfile.mkstemp(suffix=".json")
            os.write(fd, base64.b64decode(b64))
            os.close(fd)
        # bypass_csp: an app's CSP would block the voice bridge's AudioWorklet module
        self.ctx = await self.browser.new_context(
            viewport={"width": W, "height": H},
            storage_state=ss if ss and os.path.exists(ss) else None,
            device_scale_factor=1,
            permissions=["microphone", "camera"],
            bypass_csp=VOICE_BRIDGE,
        )
        await self.ctx.add_init_script(CURSOR_JS)
        if VOICE_BRIDGE:  # before the first page, so even the start page is bridged
            from demo_agent.voicebridge import PAGE_JS

            await self.ctx.add_init_script(PAGE_JS)
        self.page = await self.ctx.new_page()

        async def _new_tab(pg):  # links that open a new tab (target=_blank): show them in the shared tab instead
            try:
                if pg is self.page:
                    return
                if await pg.opener() is None:
                    return  # not a link pop-up (e.g. cleanup.py's own tab): leave it alone
                await pg.wait_for_load_state("domcontentloaded", timeout=5000)
                url = pg.url
                await pg.close()
                if url and url != "about:blank":
                    await self.page.goto(url)
            except Exception:
                pass

        self.ctx.on("page", lambda pg: asyncio.ensure_future(_new_tab(pg)))
        await self.page.goto(start_url, wait_until="domcontentloaded")
        await self._start_screencast()

    async def _start_screencast(self):
        self.cdp = await self.ctx.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._on_cast)
        await self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 70,
                "maxWidth": W,
                "maxHeight": H,
                "everyNthFrame": int(os.getenv("SCREENCAST_NTH", 2)),
            },
        )

    def _on_cast(self, p):
        now = time.perf_counter()
        asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))
        if self.on_frame:
            self.on_frame(base64.b64decode(p["data"]), now)

    async def move_to(self, x: float, y: float):
        """Glide the drawn cursor and the real mouse along the same human-like path (motion.py)."""
        try:
            cur = await self.page.evaluate("[window.__kx, window.__ky]")
        except Exception:
            cur = [None, None]
        if cur[0] is None:
            cur = list(self._kxy or (W / 2, H / 2))
        pts = motion.path(cur[0], cur[1], x, y)
        self._kxy = (x, y)
        flat = [round(v, 1) for p in pts for v in p]

        async def real_mouse():  # follow the same path with the real pointer (hover effects along the way)
            t0 = time.perf_counter()
            for t, px, py in pts[1::3] if len(pts) > 3 else []:
                lag = t / 1000 - (time.perf_counter() - t0)
                if lag > 0:
                    await asyncio.sleep(lag)
                elif lag < -0.06:
                    continue  # running behind: skip, never rush
                try:
                    await self.page.mouse.move(px, py)
                except Exception:
                    return

        try:
            await asyncio.gather(self.page.evaluate("(p)=>window.__kc&&window.__kc.play(p)", flat), real_mouse())
        except Exception:
            pass
        try:
            await self.page.mouse.move(x, y)  # exact final hover (menus, tooltips)
        except Exception:
            pass

    _MAIN_SCROLLER_JS = """() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
      const dlg = [...document.querySelectorAll('[role=dialog],[aria-modal=true]')].filter(vis).pop();   // an open dialog owns the wheel
      const root = dlg || document;
      const sc = [...(dlg ? [dlg] : []), ...root.querySelectorAll('main,section,div,form')].filter(q => q.scrollHeight > q.clientHeight + 4
      && /(auto|scroll)/.test(getComputedStyle(q).overflowY)).sort((a, b) => b.clientHeight * b.clientWidth - a.clientHeight * a.clientWidth)[0];
      if (!sc) return null; const r = sc.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }"""

    async def scroll(self, dy: int):
        """Wheel-scroll the main content: the wheel scrolls whatever is under the pointer, so point at the biggest scroller first."""
        try:
            c = await self.page.evaluate(self._MAIN_SCROLLER_JS)
            if c:
                await self.page.mouse.move(*c)
        except Exception:
            pass
        await self.page.mouse.wheel(0, dy)
        await asyncio.sleep(0.35)

    # Jev's element table (from jev-guide's collectElements); snapshot() ranks it by the step's words
    _COLLECT = open(os.path.join(os.path.dirname(__file__), "jev_collect.js")).read()

    async def snapshot(self, max_elements=240, focus_words=()):
        try:
            raw = await self.page.evaluate(self._COLLECT)
        except Exception:
            await asyncio.sleep(0.5)
            raw = await self.page.evaluate(self._COLLECT)
        words = [w.lower() for w in focus_words if len(w) > 2]

        def score(i_e):
            i, e = i_e
            l = (e["label"] + " " + e["extra"]).lower()
            s = (
                sum(3 for w in words if w in l)
                + (2 if e["inViewport"] else 0)
                + (1 if e["kind"] in ("text field", "search box", "dropdown", "select") else 0)
            )
            return (-s, i)

        ranked = [e for _, e in sorted(enumerate(raw), key=score)][:max_elements]
        try:
            text = await self.page.evaluate("(document.body?.innerText||'').replace(/\\s+/g,' ').slice(0,1500)")
        except Exception:
            text = ""
        return {
            "url": self.page.url,
            "title": await self.page.title(),
            "elements": ranked,
            "truncated": len(raw) > len(ranked),
            "text": text,
        }

    async def point_at(self, jid: str):
        """Scroll the element into view, glide the cursor there, settle, then outline it; HOVER_S in total."""
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
        # arrive, settle, then the outline lands (never before arrival)
        settle = min(motion.SETTLE_MS / 1000, hover * 0.4)
        await asyncio.sleep(settle)
        await self.page.evaluate(
            "([x,y,w,h])=>window.__kc&&window.__kc.highlight(x,y,w,h)",
            [box["x"] - 3, box["y"] - 3, box["width"] + 6, box["height"] + 6],
        )
        await asyncio.sleep(max(0.0, hover - settle))
        return x, y

    async def click_jev(self, jid: str):
        pt = await self.point_at(jid)
        if not pt:
            raise RuntimeError("element not visible")
        await self.page.evaluate("([x,y])=>{window.__kself=1;window.__kc&&window.__kc.ripple(x,y)}", list(pt))
        u0 = self.page.url
        dlg = await self.page.evaluate("()=>!!document.querySelector('[role=dialog],[aria-modal=true]')")
        try:
            await self.page.mouse.click(*pt)
        except Exception:
            await self.page.locator(f'[data-jev-id="{jid}"]').first.click(timeout=5000, force=True)
        await self.settle_jev()
        if dlg:  # only submit-like buttons close a modal; fields, dropdowns and tabs inside it never do
            try:
                what = await self.page.evaluate(
                    """(id) => { const e = document.querySelector(`[data-jev-id="${id}"]`); if (!e) return '';
                    return (e.tagName + ' ' + (e.getAttribute('type') || '') + ' ' + (e.innerText || e.value || e.getAttribute('aria-label') || '')).slice(0, 80); }""",
                    jid,
                )
            except Exception:
                what = ""
            dlg = (
                bool(
                    re.match(r"(BUTTON|A)\b", what)
                    and re.search(
                        r"\b(create|save|confirm|submit|add|deploy|done|apply|continue|next|ok|rent|buy|generate)\b",
                        what,
                        re.I,
                    )
                )
                or " submit" in what.lower()
            )
        # a submit button in a dialog: wait while it works, until it closes or navigates
        if dlg and self.page.url == u0:
            for _ in range(16):
                if self.page.url != u0 or not await self.page.evaluate(
                    "()=>!!document.querySelector('[role=dialog],[aria-modal=true]')"
                ):
                    break
                if not await self.page.evaluate(
                    "()=>!!document.querySelector('[role=dialog] [aria-busy=true],[role=dialog] svg[class*=animate-spin],[role=dialog] [class*=spinner],[role=dialog] button:disabled')"
                ):
                    break
                await asyncio.sleep(0.5)
        if self.page.url != u0:  # route change: give the new screen time to render
            try:
                await self.page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass

    async def type_jev(self, jid: str, text: str, submit=False):
        pt = await self.point_at(jid)
        if pt:
            await self.page.mouse.click(*pt)
        loc = self.page.locator(f'[data-jev-id="{jid}"]').first
        await loc.focus()
        # replace, never append (ControlOrMeta+A: on macOS Control+A only moves to the line start)
        await self.page.keyboard.press("ControlOrMeta+A")
        await self.page.keyboard.press("Backspace")
        try:
            if await loc.evaluate("e => (e.closest('.monaco-editor') ? 1 : 0)"):
                text_left = await loc.evaluate(
                    "e => (e.closest('.monaco-editor').querySelector('.view-lines')?.innerText || '').trim()"
                )
                if text_left:  # still not empty: select the editor's whole model once more
                    await self.page.keyboard.press("ControlOrMeta+A")
                    await self.page.keyboard.press("Backspace")
        except Exception:
            pass
        if len(text) > 60 or "\n" in text:
            await self.page.keyboard.insert_text(text)
        else:
            await self.page.keyboard.type(text, delay=35)
        if submit:
            await self.page.keyboard.press("Enter")
        await self.settle_jev()

    async def settle_jev(self, ms=JEV_SETTLE_MS):
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(ms / 1000)
        await self.dismiss_banners()

    async def settle(self, timeout=4000):
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        await asyncio.sleep(float(os.getenv("SETTLE_S", 0.6)))
        await self.dismiss_banners()

    async def dismiss_banners(self):
        """Click away cookie/consent banners: they cover the page."""
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
        if not self.page.url.startswith("http"):  # backed out of the app (about:blank): return
            await self.page.goto(before, wait_until="domcontentloaded")

    async def end_test_call(self) -> bool:
        """Hang up an in-browser test call if one is active."""
        try:
            b = self.page.get_by_role("button", name=re.compile(r"^(end call|disconnect|hang up|stop call)$", re.I))
            if await b.count():
                await b.first.click(timeout=3000)
                await asyncio.sleep(1)
                return True
        except Exception:
            pass
        return False

    async def close(self):
        try:
            await self.browser.close()
            await self._pw.stop()
        except Exception:
            pass
