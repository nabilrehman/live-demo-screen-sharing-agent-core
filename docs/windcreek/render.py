"""Renders a docs/windcreek/*.md file as a standalone, printable HTML page (noindex; optional access-code gate).

uv run --with markdown python docs/windcreek/render.py DEMO_SCRIPT.md <out.html> [--gate]
"""

import os
import sys

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "mockup", "windcreek"))
from build import GATE

CSS = """
:root{--ink:#1d1d1f;--muted:#5d5d5d;--line:#e2e2e2;--red:#a3162e;--bg:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--ink:#eee;--muted:#aaa;--line:#333;--red:#ff6b7f;--bg:#111}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Figtree",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
h1,h2{font-family:"Oswald",Impact,sans-serif;text-transform:uppercase;color:var(--red);letter-spacing:.01em;line-height:1.1}
h1{font-size:2.2rem;margin:.2em 0 .4em}h2{font-size:1.4rem;margin:1.6em 0 .5em;border-top:1px solid var(--line);padding-top:.8em}
table{border-collapse:collapse;width:100%;font-size:13.5px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:7px 9px;vertical-align:top;text-align:left}th{background:rgba(163,22,46,.06)}
code{font-size:.9em;background:rgba(127,127,127,.12);padding:1px 4px;border-radius:4px}
li{margin:.2em 0}.bm{display:inline-block;background:#111;color:#fff;padding:6px 14px;border-radius:999px;text-decoration:none}.gate{display:none}html.gated main{display:none}html.gated .gate{display:block;padding:40px;text-align:center}
@media print{body{font-size:11px}main{padding:0}h2{break-after:avoid}table{display:table;font-size:10px}tr{break-inside:avoid}a{color:inherit}}
"""


def main():
    src, out = sys.argv[1], sys.argv[2]
    md = open(os.path.join(HERE, src)).read()
    body = markdown.markdown(md, extensions=["tables", "sane_lists"])
    body = body.replace("[ ]", "&#9744;")
    bm = open(os.path.join(HERE, "bookmarklet.js")).read().strip()
    body = body.replace(
        "<!-- bookmarklet -->",
        f'<p><a class="bm" href="{bm}">Kai (Wind Creek demo)</a> &larr; drag this to your bookmarks bar.</p>',
    )
    title = md.splitlines()[0].lstrip("# ").strip()
    gate = GATE if "--gate" in sys.argv else ""
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{title}</title>{gate}
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@600&family=Figtree:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="gate">Private page. Open it with your access link.</div><main>{body}</main></body></html>"""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "w").write(html)
    print("wrote", out)


if __name__ == "__main__":
    main()
