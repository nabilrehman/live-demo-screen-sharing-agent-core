"""Step 3+4 (demo-design §3-4), quick mode: render ref/site.json + ref/tokens.json into a static, gated, noindex demo
with the LiveKit banner, inert "Demo only" buttons and the LiveKit in-page voice copilot embed on every page.
Also writes the agent's knowledge pack (knowledge/<slug>/) for src/windcreek_agent.py via SITE_KNOWLEDGE.

  python build.py <workdir> --slug hardrock --brand "Hard Rock Hotels" --code HARDROCK-DEMO [--base /v2/hardrock]
                  [--concept-file <workdir>/concept.txt]
With --concept-file and ref/scenario.json (design.py --scenario-only), the agent is built around that use case: role
prompt (templates/livekit_prompt_scenario.md), greeting (templates/greeting_scenario.md), knowledge/scenario.md with the
synthetic sample data, and a scenario screen page (nav first when the use case is an app view). Without it: unchanged.
Output: <workdir>/site/  (serve at --base)   <workdir>/knowledge/
"""
import html, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
E = html.escape
DENY = re.compile(r"(sign|log[-_ ]?in|account|register|password|checkout|payment|join|enroll)", re.I)


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def img_url(src, base):
    if not src:
        return ""
    return f"{base}/img/gen/{src[4:]}" if src.startswith("gen:") else src


def page_href(path, base):
    path = path or "/"
    return base + ("/" if path == "/" else "/" + path.strip("/") + "/")


def button(label, href=None, base=""):
    label = label or "Learn more"
    if href and not DENY.search(label):
        return f'<a class="btn" href="{E(page_href(href, base))}">{E(label)}</a>'
    return f'<button class="btn" type="button" data-demo-only>{E(label)}</button>'


def section(s, base):
    t = s.get("type")
    h = E(s.get("heading") or "")
    body = E(s.get("body") or "")
    if t == "hero":
        return f'''<section class="hero" style="background-image:linear-gradient(rgba(0,0,0,.35),rgba(0,0,0,.45)),url('{E(img_url(s.get("image"), base))}')">
  <div class="wrap"><h1>{h}</h1><p>{body}</p>{button(s.get("cta"), None, base) if s.get("cta") else ""}</div></section>'''
    if t == "search":
        fields = "".join(f'<label><span>{E(f)}</span><input disabled placeholder="{E(f)}"></label>' for f in s.get("fields") or [])
        return f'<section class="search wrap"><h2>{h}</h2><div class="search-row">{fields}{button(s.get("cta") or "Search", None, base)}</div></section>'
    if t == "cards":
        items = []
        for it in s.get("items") or []:
            im = img_url(it.get("image"), base)
            inner = (f'<div class="card-img" style="background-image:url(\'{E(im)}\')"></div>' if im else "") + \
                f'<div class="card-body"><h3>{E(it.get("title") or "")}</h3><p>{E(it.get("text") or "")}</p>' + \
                (f'<div class="price">{E(it["price"])}</div>' if it.get("price") else "") + "</div>"
            items.append(f'<a class="card" href="{E(page_href(it["path"], base))}">{inner}</a>' if it.get("path") else f'<div class="card">{inner}</div>')
        return f'<section class="cards wrap"><h2>{h}</h2><div class="grid">{"".join(items)}</div></section>'
    if t == "split":
        return f'''<section class="split wrap"><div class="split-img" style="background-image:url('{E(img_url(s.get("image"), base))}')"></div>
  <div><h2>{h}</h2><p>{body}</p>{button(s.get("cta"), None, base) if s.get("cta") else ""}</div></section>'''
    if t == "faq":
        qs = "".join(f'<details><summary>{E(i.get("q",""))}</summary><p>{E(i.get("a",""))}</p></details>' for i in s.get("items") or [])
        return f'<section class="faq wrap"><h2>{h}</h2>{qs}</section>'
    if t == "scenario":
        return scenario_section(s)
    return f'<section class="text wrap"><h2>{h}</h2><p>{body}</p></section>'


def scenario_section(s):
    """The use-case screen (e.g. a host's daily VIP briefing): title, try-asking chips, one card per sample record."""
    asks = "".join(f'<span class="sc-ask">&ldquo;{E(q)}&rdquo;</span>' for q in s.get("sample_questions") or [])
    cards = []
    for i, it in enumerate(s.get("items") or []):
        badges = "".join(f'<span class="sc-badge">{E(str(b))}</span>' for b in it.get("badges") or [])
        fields = "".join(f'<dt>{E(str(f.get("label", "")))}</dt><dd>{E(str(f.get("value", "")))}</dd>' for f in it.get("fields") or [] if isinstance(f, dict))
        note = f'<p class="sc-note">{E(it["note"])}</p>' if it.get("note") else ""
        cards.append(f'<article class="sc-card" id="record-{i + 1}"><h3>{E(it.get("title") or "")}</h3>'
                     f'<p class="sc-sub">{E(it.get("subtitle") or "")}</p><div>{badges}</div><dl>{fields}</dl>{note}</article>')
    return (f'<section class="scenario wrap"><p class="sc-kicker">Demo scenario &middot; sample data</p><h1>{E(s.get("heading") or "")}</h1>'
            f'<p class="sc-subtitle">{E(s.get("body") or "")}</p>' + (f'<div class="sc-asks"><b>Try asking:</b> {asks}</div>' if asks else "") +
            f'<div class="sc-grid">{"".join(cards)}</div></section>')


SCENARIO_CSS = """.scenario h1{font-size:clamp(28px,4vw,44px);margin:6px 0}.sc-kicker{text-transform:uppercase;font-size:12px;letter-spacing:.08em;color:var(--muted);margin:0}
.sc-subtitle{color:var(--muted);margin:0 0 18px}.sc-asks{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 22px;font-size:14px}
.sc-ask{background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:6px 12px}
.sc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
.sc-card{background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow);padding:18px;border-top:4px solid var(--primary)}
.sc-card h3{margin:0 0 4px;font-size:20px}.sc-sub{margin:0 0 10px;color:var(--muted);font-size:14px}
.sc-badge{display:inline-block;background:var(--accent);color:#fff;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;border-radius:3px;padding:3px 7px;margin:0 6px 6px 0}
.sc-card dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:10px 0;font-size:14px}.sc-card dt{color:var(--muted)}.sc-card dd{margin:0;font-weight:600}
.sc-note{margin:8px 0 0;font-size:14px;border-left:3px solid var(--accent);padding-left:10px}
@media(max-width:760px){.sc-grid{grid-template-columns:1fr}}
"""


def load_scenario(work):
    """ref/scenario.json, only when the build was given a use case (--concept-file). None = the old generic copilot."""
    cf, sp = arg("--concept-file"), os.path.join(work, "ref", "scenario.json")
    if not cf or not os.path.exists(cf) or not open(cf).read().strip() or not os.path.exists(sp):
        return None
    sc = json.load(open(sp))
    sc["concept"] = open(cf).read().strip()
    return sc


def add_scenario_page(model, sc):
    """Add the scenario screen to the site model (nav first for an app-style use case) and return its path."""
    pn = sc.get("panel") or {}
    if not pn.get("items"):
        return None
    taken = {(p.get("path") or "/").strip("/") for p in model.get("pages") or []}
    slug = re.sub(r"[^a-z0-9-]+", "-", (pn.get("path") or "").lower()).strip("-") or "briefing"
    if DENY.search(slug):
        slug = "briefing"
    while slug in taken:
        slug += "-demo"
    path = "/" + slug
    model.setdefault("pages", []).append({"path": path, "title": pn.get("title") or "Briefing", "sections": [
        {"type": "scenario", "heading": pn.get("title") or "", "body": pn.get("subtitle") or "", "items": pn.get("items") or [],
         "sample_questions": sc.get("sample_questions") or []}]})
    item = {"label": pn.get("nav") or pn.get("title") or "Briefing", "path": path}
    nav = model.setdefault("nav", [])
    nav.insert(0, item) if sc.get("view") == "app" else nav.append(item)
    return path


def css(tok):
    c, f = tok.get("colors", {}), tok.get("fonts", {})
    return f""":root{{--bg:{c.get('bg','#fff')};--surface:{c.get('surface','#f5f5f5')};--text:{c.get('text','#111')};--muted:{c.get('muted','#666')};
--primary:{c.get('primary','#000')};--primary-text:{c.get('primaryText','#fff')};--accent:{c.get('accent','#c00')};--header:{c.get('header','#000')};
--header-text:{c.get('headerText','#fff')};--footer:{c.get('footer','#111')};--footer-text:{c.get('footerText','#ddd')};--border:{c.get('border','#ddd')};
--radius:{tok.get('radius','4px')};--btn-radius:{tok.get('buttonRadius','2px')};--max:{tok.get('maxWidth','1280px')};--shadow:{tok.get('shadow','0 2px 12px rgba(0,0,0,.08)')}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 '{f.get('body','Inter')}',system-ui,sans-serif}}
h1,h2,h3{{font-family:'{f.get('heading','Oswald')}',sans-serif;font-weight:{f.get('headingWeight',700)};text-transform:{f.get('headingTransform','none')};letter-spacing:{f.get('headingLetterSpacing','0')};line-height:1.15}}
a{{color:inherit}}.wrap{{max-width:var(--max);margin:0 auto;padding:0 24px}}
.lk-banner{{background:#111;color:#fff;font:13px/1.4 system-ui;text-align:center;padding:6px 12px}}
header.site{{background:var(--header);color:var(--header-text);position:sticky;top:0;z-index:20}}
header.site .wrap{{display:flex;align-items:center;gap:28px;height:72px}}.logo{{font-family:'{f.get('heading','Oswald')}';font-size:22px;font-weight:800;text-decoration:none;text-transform:uppercase;white-space:nowrap}}
header.site nav{{display:flex;gap:22px;overflow:auto}}header.site nav a{{text-decoration:none;font-size:14px;text-transform:{tok.get('buttonTransform','uppercase')};letter-spacing:.04em;white-space:nowrap}}
.btn{{display:inline-block;background:var(--primary);color:var(--primary-text);border:0;border-radius:var(--btn-radius);padding:12px 26px;font:600 14px/1 inherit;text-transform:{tok.get('buttonTransform','uppercase')};letter-spacing:.06em;text-decoration:none;cursor:pointer}}
.hero{{min-height:560px;display:flex;align-items:flex-end;background-size:cover;background-position:center;color:#fff;padding:80px 0}}.hero h1{{font-size:clamp(36px,6vw,72px);margin:0 0 12px}}.hero p{{max-width:640px;font-size:18px}}
section{{margin:56px auto}}.hero{{margin:0}}.search{{background:var(--surface);padding:24px;border-radius:var(--radius);box-shadow:var(--shadow);margin-top:-40px;position:relative}}
.search-row{{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}}.search label{{flex:1;min-width:160px;display:flex;flex-direction:column;font-size:12px;text-transform:uppercase;color:var(--muted)}}.search input{{padding:12px;border:1px solid var(--border);border-radius:var(--radius);background:#fff}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:24px}}.card{{background:var(--surface);border-radius:var(--radius);overflow:hidden;text-decoration:none;box-shadow:var(--shadow);display:flex;flex-direction:column}}
.card-img{{aspect-ratio:4/3;background-size:cover;background-position:center}}.card-body{{padding:18px}}.card-body h3{{margin:0 0 8px;font-size:20px}}.card-body p{{margin:0;color:var(--muted);font-size:15px}}.price{{margin-top:10px;font-weight:700;color:var(--accent)}}
.split{{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:center}}.split-img{{aspect-ratio:3/2;background-size:cover;border-radius:var(--radius)}}
details{{border-bottom:1px solid var(--border);padding:14px 0}}summary{{font-weight:600;cursor:pointer}}
footer.site{{background:var(--footer);color:var(--footer-text);padding:48px 0;margin-top:80px;font-size:14px}}footer.site .cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:24px}}footer.site h4{{margin:0 0 10px;text-transform:uppercase}}footer.site ul{{list-style:none;padding:0;margin:0}}
#gate{{position:fixed;inset:0;background:#0b0b0b;color:#fff;display:none;align-items:center;justify-content:center;z-index:100;font-family:system-ui}}#gate form{{display:flex;gap:8px}}#gate input{{padding:10px}}
@media(max-width:760px){{.split{{grid-template-columns:1fr}}header.site .wrap{{height:60px;gap:14px}}header.site nav{{font-size:12px}}.hero{{min-height:420px}}}}
"""


GATE = """<script>(function(){var C=%s,K='demo-code';var q=new URLSearchParams(location.search).get('code');
try{if(q)sessionStorage.setItem(K,q);}catch(e){}var ok=false;try{ok=sessionStorage.getItem(K)===C;}catch(e){}
if(!ok){document.documentElement.style.visibility='hidden';addEventListener('DOMContentLoaded',function(){var g=document.getElementById('gate');
document.documentElement.style.visibility='';g.style.display='flex';g.querySelector('form').onsubmit=function(ev){ev.preventDefault();
if(g.querySelector('input').value.trim()===C){sessionStorage.setItem(K,C);location.reload();}else{g.querySelector('p').textContent='That code is not right.';}};});}})();</script>"""

DEMO_ONLY = """<script>document.addEventListener('click',function(e){var b=e.target.closest('[data-demo-only]');if(!b)return;e.preventDefault();
var t=b.textContent;b.textContent='Demo only';setTimeout(function(){b.textContent=t;},1400);});</script>"""


def render(model, tok, page, base, slug, brand, code, brain):
    nav = "".join(f'<a href="{E(page_href(n.get("path"), base))}">{E(n.get("label",""))}</a>' for n in model.get("nav") or [] if not DENY.search(n.get("label", "")))
    ft = model.get("footer") or {}
    cols = "".join(f'<div><h4>{E(c.get("heading",""))}</h4><ul>' + "".join(f"<li>{E(l)}</li>" for l in c.get("links") or []) + "</ul></div>" for c in ft.get("columns") or [])
    f = tok.get("fonts", {})
    fonts = "|".join({f.get("heading", "Oswald"), f.get("body", "Inter")})
    body = "\n".join(section(s, base) for s in page.get("sections") or [])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{E(page.get('title') or brand)} | {E(brand)} (LiveKit demo)</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{'&'.join('family=' + x.replace(' ', '+') + ':wght@400;600;700;800' for x in fonts.split('|'))}&display=swap">
<link rel="stylesheet" href="{base}/site.css">{GATE % json.dumps(code)}</head><body>
<div class="lk-banner">Demo mockup prepared by LiveKit for {E(brand)}, not the official site</div>
<header class="site"><div class="wrap"><a class="logo" href="{base}/">{E(model.get('brand') or brand)}</a><nav>{nav}</nav></div></header>
<main>{body}</main>
<footer class="site"><div class="wrap"><div class="cols">{cols}</div><p>{E(ft.get('legal') or '')} Demo mockup by LiveKit; content summarized from the public {E(brand)} website.</p></div></footer>
<div id="gate"><div><h2>{E(brand)} demo</h2><p>Enter the access code.</p><form><input placeholder="Access code" autocomplete="off"><button class="btn">Enter</button></form></div></div>
{DEMO_ONLY}<script src="{base}/livekit/livekit.js" data-site-root="{base}/" data-brain="{brain}" data-code="{E(code)}" defer></script>
</body></html>"""


def rebrand_widget(src_dir, out_dir):
    """Copy the in-page copilot widget and rename Kai -> LiveKit in everything visible and in its wiring."""
    os.makedirs(out_dir, exist_ok=True)
    for fn in os.listdir(src_dir):
        if fn.endswith(".html"):
            continue
        s = os.path.join(src_dir, fn)
        if fn in ("kai.js", "kai.css"):
            t = open(s).read()
            for a, b in (("window.KaiContext", "window.LiveKitContext"), ("window.Kai", "window.LiveKitAgent"), ("__kai", "__lkagent"),
                         ("data-kai-", "data-lk-"), ("kai-root", "lk-root"), ("'kai.", "'lk."), ('"kai.', '"lk.'), ("Talk to Kai", "Talk to LiveKit"),
                         ("kai_", "kai_"), ("Kai", "LiveKit")):
                t = t.replace(a, b)
            t = t.replace("/kai\\.js", "/livekit\\.js").replace("kai.css", "livekit.css")
            open(os.path.join(out_dir, fn.replace("kai", "livekit")), "w").write(t)
        else:
            shutil.copy(s, os.path.join(out_dir, fn))


def scenario_knowledge(model, out, brand, url, sc, panel_path):
    """Knowledge pack for a use case: role prompt + greeting filled now; {assistant} {brand} {today} {knowledge} stay for site.py."""
    tpl = os.path.join(HERE, "templates")
    files = ["scenario.md", "facts.md", "sitemap.md"]
    json.dump({"brand": brand, "assistant": "LiveKit", "timezone": "America/New_York", "knowledge_files": files, "properties": [], "source": url,
               "concept": sc["concept"], "view": sc.get("view", "site"), "scenario_path": panel_path},
              open(os.path.join(out, "site.json"), "w"), indent=1)
    where = f"\n\nThe scenario screen is at {panel_path} (open it with navigate; each record is a card you can highlight by name)." if panel_path else ""
    open(os.path.join(out, "scenario.md"), "w").write(f"# Scenario: {sc.get('user') or 'the user'}\n\n{sc.get('role') or ''}{where}\n\n" + (sc.get("data_md") or ""))
    rules = "\n".join("- " + str(r).strip().lstrip("- ") for r in sc.get("instructions") or [] if str(r).strip())
    if sc.get("view") == "app" and panel_path:
        rules = f"- Start on the scenario screen ({panel_path}): open it when the conversation starts or when they ask for the overview.\n" + rules
    fill = {"{role}": sc.get("role") or "", "{user}": sc.get("user") or "the user", "{concept}": sc["concept"], "{instructions}": rules,
            "{intro}": sc.get("intro") or f"{brand}'s AI assistant", "{followup}": sc.get("greeting_followup") or "ask how you can help."}
    for src, dst in (("livekit_prompt_scenario.md", "livekit_prompt.md"), ("greeting_scenario.md", "greeting.md")):
        t = open(os.path.join(tpl, src)).read()
        for k, v in fill.items():
            t = t.replace(k, v)
        open(os.path.join(out, dst), "w").write(t)
    shutil.copy(os.path.join(out, "livekit_prompt.md"), os.path.join(out, "kai_prompt.md"))  # site.py loads kai_prompt.md


def knowledge(model, out, slug, brand, url, sc=None, panel_path=None):
    os.makedirs(out, exist_ok=True)
    tpl = os.path.join(HERE, "templates")
    json.dump({"brand": brand, "assistant": "LiveKit", "timezone": "America/New_York", "knowledge_files": ["facts.md", "sitemap.md"], "properties": [], "source": url},
              open(os.path.join(out, "site.json"), "w"), indent=1)
    open(os.path.join(out, "facts.md"), "w").write("# Facts\n\n" + (model.get("facts") or ""))
    sm = "\n".join(f"- {p.get('path')}: {p.get('title')}" for p in model.get("pages") or [])
    open(os.path.join(out, "sitemap.md"), "w").write("# Site map (paths you can open with navigate)\n\n" + sm)
    shutil.copy(os.path.join(tpl, "livekit_prompt.md"), os.path.join(out, "kai_prompt.md"))  # site.py loads kai_prompt.md; content names LiveKit
    shutil.copy(os.path.join(tpl, "livekit_prompt.md"), os.path.join(out, "livekit_prompt.md"))
    shutil.copy(os.path.join(tpl, "greeting.md"), os.path.join(out, "greeting.md"))
    open(os.path.join(out, "SOURCES.md"), "w").write(f"# Sources\n\nCaptured read-only from {url} by generator-v2.\n")
    if sc:
        scenario_knowledge(model, out, brand, url, sc, panel_path)
        open(os.path.join(out, "SOURCES.md"), "a").write("scenario.md is synthetic sample data generated for the demo use case (all fictional).\n")


def main():
    work = sys.argv[1]
    slug, brand = arg("--slug"), arg("--brand")
    code = arg("--code", slug.upper() + "-DEMO")
    base = arg("--base", f"/v2/{slug}").rstrip("/")
    brain = arg("--brain", f"{slug}-grok")
    widget_src = arg("--widget", "/private/tmp/claude-501/-Users-nabilrehman-Downloads-livekit-demo-agent/3cb0ded0-74a9-4dff-b0b7-bb53c4643301/scratchpad/vflights/public/embed/windcreek")
    ref = os.path.join(work, "ref")
    model, tok = json.load(open(os.path.join(ref, "site.json"))), json.load(open(os.path.join(ref, "tokens.json")))
    site = os.path.join(work, "site"); os.makedirs(site, exist_ok=True)
    sc = load_scenario(work)
    panel_path = add_scenario_page(model, sc) if sc else None
    open(os.path.join(site, "site.css"), "w").write(css(tok) + (SCENARIO_CSS if panel_path else ""))
    for p in model.get("pages") or []:
        d = os.path.join(site, (p.get("path") or "/").strip("/"))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w").write(render(model, tok, p, base, slug, brand, code, brain))
    rebrand_widget(widget_src, os.path.join(site, "livekit"))
    knowledge(model, os.path.join(work, "knowledge"), slug, brand, model.get("url", ""), sc, panel_path)
    print(f"built {len(model.get('pages') or [])} pages -> {site} (base {base}, code {code}, brain {brain})"
          + (f"; use case: {sc.get('user')!r}, view={sc.get('view')}, screen {panel_path}" if sc else ""))


if __name__ == "__main__":
    main()
