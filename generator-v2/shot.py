"""Verify helper: desktop + 390 screenshots of every built page -> work/<slug>/verify/.  python shot.py <slug> [port]"""
import asyncio, json, os, sys
from playwright.async_api import async_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); slug = sys.argv[1]; port = sys.argv[2] if len(sys.argv) > 2 else "8795"
work = os.path.join(HERE, "work", slug); model = json.load(open(os.path.join(work, "ref", "site.json")))
code = open(os.path.join(work, "site", "index.html")).read().split("var C=")[1].split(",")[0].strip('"')
async def main():
    out = os.path.join(work, "verify"); os.makedirs(out, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome")
        for w, tag in ((1440, "desk"), (390, "phone")):
            pg = await b.new_page(viewport={"width": w, "height": 900})
            for i, pgm in enumerate(model["pages"]):
                path = (pgm.get("path") or "/").strip("/")
                url = f"http://localhost:{port}/v2/{slug}/{path + '/' if path else ''}?code={code}"
                await pg.goto(url); await pg.wait_for_timeout(1500)
                name = path.replace("/", "_") or "home"
                await pg.screenshot(path=os.path.join(out, f"{name}-{tag}.png"), full_page=True)
                print("shot", name, tag)
        await b.close()
asyncio.run(main())
