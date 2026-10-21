"""Step 1 (demo-design §1): Playwright capture of a reference site, read-only.
Visits the home page plus up to N same-origin pages linked from it (nav first), never sign-in/account/checkout pages.
Writes ref/<page>-desk.png (1440) and ref/<page>-phone.png (390), and ref/capture.json: per page url, title, headings,
visible text, image URLs (+alt), nav links, and computed styles (fonts, colors, radius, button text-transform).

  python capture.py <url> <workdir> [--pages 8]
"""
import asyncio, json, os, re, sys
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

DENY = re.compile(r"(sign[-_]?in|log[-_]?in|login|sign[-_]?up|register|password|account|profile|checkout|payment|cart|careers?|apply|privacy|terms|cookie|mailto:|tel:|javascript:)", re.I)

JS_FACTS = r"""() => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const cs = (sel) => { const e = document.querySelector(sel); if (!e) return null; const s = getComputedStyle(e);
    return {font: s.fontFamily, size: s.fontSize, weight: s.fontWeight, color: s.color, bg: s.backgroundColor, radius: s.borderRadius, transform: s.textTransform, letter: s.letterSpacing}; };
  const btn = [...document.querySelectorAll('button, a[class*=btn], a[class*=button], [role=button]')].find(vis);
  let btnStyle = null; if (btn) { const s = getComputedStyle(btn); btnStyle = {font: s.fontFamily, color: s.color, bg: s.backgroundColor, radius: s.borderRadius, transform: s.textTransform, weight: s.fontWeight, letter: s.letterSpacing, border: s.border}; }
  return {
    title: document.title,
    headings: [...document.querySelectorAll('h1,h2,h3')].filter(vis).map(h => ({tag: h.tagName, text: h.innerText.trim().replace(/\s+/g,' ')})).filter(h => h.text).slice(0, 80),
    text: document.body.innerText.replace(/\n{3,}/g, '\n\n').slice(0, 20000),
    images: [...document.images].filter(i => i.naturalWidth >= 300).map(i => ({src: i.currentSrc || i.src, alt: i.alt, w: i.naturalWidth, h: i.naturalHeight})).slice(0, 60),
    bgImages: [...document.querySelectorAll('section, div, header')].map(e => getComputedStyle(e).backgroundImage).filter(b => b && b.startsWith('url(')).map(b => b.slice(5, -2)).slice(0, 30),
    nav: [...document.querySelectorAll('header a, nav a')].filter(vis).map(a => ({label: a.innerText.trim().replace(/\s+/g,' '), href: a.href})).filter(a => a.label).slice(0, 60),
    links: [...document.querySelectorAll('main a, a')].filter(vis).map(a => ({label: a.innerText.trim().replace(/\s+/g,' ').slice(0, 80), href: a.href})).filter(a => a.label).slice(0, 200),
    styles: {body: cs('body'), header: cs('header') || cs('nav'), h1: cs('h1'), h2: cs('h2'), link: cs('main a') || cs('a'), footer: cs('footer'), button: btnStyle},
  };
}"""


def slugify(url, home):
    p = urlparse(url).path.strip("/")
    return "home" if not p or url.rstrip("/") == home.rstrip("/") else re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-")[:60]


async def shoot(ctx_desk, ctx_phone, url, name, ref):
    out = {}
    for ctx, tag in ((ctx_desk, "desk"), (ctx_phone, "phone")):
        pg = await ctx.new_page()
        try:
            r = await pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            await pg.wait_for_timeout(3500)
            for _ in range(8):  # trigger lazy images
                await pg.mouse.wheel(0, 1400); await pg.wait_for_timeout(250)
            await pg.evaluate("window.scrollTo(0,0)"); await pg.wait_for_timeout(500)
            await pg.screenshot(path=os.path.join(ref, f"{name}-{tag}.png"), full_page=True)
            if tag == "desk":
                out = await pg.evaluate(JS_FACTS)
                out.update(url=pg.url, status=r.status if r else None)
        except Exception as e:
            print(f"  ! {name} {tag}: {str(e)[:150]}", flush=True)
        finally:
            await pg.close()
    return out


async def main(url, work, n_pages):
    ref = os.path.join(work, "ref"); os.makedirs(ref, exist_ok=True)
    host = urlparse(url).netloc
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(channel=os.getenv("PW_CHANNEL", "chrome") or None)
        except Exception:
            b = await p.chromium.launch()
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0 Safari/537.36"
        desk = await b.new_context(viewport={"width": 1440, "height": 900}, user_agent=ua)
        phone = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        pages = {}
        home = await shoot(desk, phone, url, "home", ref)
        pages["home"] = home
        cands, seen = [], {url.rstrip("/")}
        for l in (home.get("nav") or []) + (home.get("links") or []):
            h = l["href"].split("#")[0].rstrip("/")
            if urlparse(h).netloc == host and h not in seen and not DENY.search(h):
                seen.add(h); cands.append(h)
        for h in cands[:n_pages]:
            name = slugify(h, url)
            if name in pages: continue
            print(f"capture {name}  {h}", flush=True)
            pages[name] = await shoot(desk, phone, h, name, ref)
        await b.close()
    json.dump({"url": url, "pages": pages}, open(os.path.join(ref, "capture.json"), "w"), indent=1)
    print(f"captured {len(pages)} pages -> {ref}")


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 8
    asyncio.run(main(sys.argv[1], sys.argv[2], n))
