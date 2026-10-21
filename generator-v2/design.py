"""Step 2 (demo-design §2): Gemini turns the captures into
  ref/spec.md      the human-readable design spec (tokens, components+states, layouts desk/phone, copy tone)
  ref/tokens.json  machine-readable tokens for the builder
  ref/site.json    the site model the builder renders (pages -> sections), from the captured real content
  ref/images.json  image jobs for gaps (fed to $S/imggen/gen.py)

  ref/scenario.json  (only with --scenario-only --concept-file F) the agent's role, greeting, rules, synthetic sample
                    data and a scenario screen, built around a free-text use case

  python design.py <workdir> --brand "Hard Rock Hotels"
  python design.py <workdir> --brand "Hard Rock Hotels" --scenario-only --concept-file <workdir>/concept.txt
"""
import json, os, sys
import gemini

SPEC_PROMPT = """You are a senior front-end designer. These are full-page screenshots (desktop 1440 and phone 390) of {brand}'s website, plus computed CSS styles as JSON.
Write a precise build spec (markdown) so an engineer can replicate it in plain HTML/CSS: design tokens (exact hex colors, fonts mapped to Google Fonts equivalents, sizes, weights, letter-spacing, radius, shadows, spacing scale); every component with its states (nav + mega menu, hero, search/booking card, cards, carousels, offer tiles, footer, buttons, chat widget if any); each page's layout at desktop and phone width; the copy tone. Be concrete with pixel values. No preamble."""

TOKENS_PROMPT = """From this design spec, output JSON only:
{"colors":{"bg":"#","surface":"#","text":"#","muted":"#","primary":"#","primaryText":"#","accent":"#","header":"#","headerText":"#","footer":"#","footerText":"#","border":"#"},
 "fonts":{"heading":"<Google Font family>","body":"<Google Font family>","headingWeight":700,"headingTransform":"uppercase|none","headingLetterSpacing":"0.02em"},
 "radius":"0px","buttonRadius":"0px","buttonTransform":"uppercase|none","shadow":"css box-shadow","maxWidth":"1280px"}
Spec:
"""

MODEL_PROMPT = """You are building a demo replica of {brand}'s website ({url}) for a private sales pitch to {brand}.
Below is the real text, headings, links and image URLs captured from {n} pages. Produce JSON only, the site model:
{{"brand":"{brand}","tagline":"...","nav":[{{"label":"...","path":"/..."}}],
 "pages":[{{"path":"/" or "/<slug>","title":"...","sections":[
   {{"type":"hero","heading":"...","body":"...","image":"<real image URL or gen:<file>.jpg>","cta":"..."}},
   {{"type":"search","heading":"...","fields":["Destination","Check-in","Check-out","Guests"],"cta":"Search"}},
   {{"type":"cards","heading":"...","items":[{{"title":"...","text":"...","image":"...","path":"/<slug> or null","price":"optional"}}]}},
   {{"type":"text","heading":"...","body":"..."}},
   {{"type":"split","heading":"...","body":"...","image":"...","cta":"..."}},
   {{"type":"faq","heading":"...","items":[{{"q":"...","a":"..."}}]}}]}}],
 "footer":{{"columns":[{{"heading":"...","links":["..."]}}],"legal":"..."}},
 "facts":"markdown: the key facts a concierge needs (properties/locations, rooms, offers with dates, amenities, policies, contact), in your own words, from the captured text only",
 "image_jobs":[{{"file":"<name>.jpg","prompt":"<detailed photographic scene, distinct angle/light, no text/logos>"}}]}}
Rules: use the REAL names, places, offers and numbers from the captured text; summarize in your own words (no long copied paragraphs). Keep 4-10 pages, the ones a guest would visit in a booking journey (home, destinations/hotels listing, one hotel detail, rooms, offers, booking). Paths must be unique. Prefer real image URLs from the capture; use "gen:<file>.jpg" only where there is no suitable real image, and add a matching image_jobs entry (max 24). Never include sign-in, account or payment pages.
CAPTURE:
"""


SCENARIO_PROMPT = """You are designing the AI voice agent for a private LiveKit sales demo to {brand} ({url}).
The LiveKit sales engineer described the use case this demo must show:
<<<
{concept}
>>>
Design the agent around THIS use case (not a generic website concierge), grounded in {brand}'s real properties, venues,
offers and brand voice (from the website summary below) wherever they fit. Output JSON only:
{{"user":"who talks to the agent, short (e.g. 'a Hard Rock casino host')",
 "role":"one or two sentences, second person: who the agent is and what it does for that user (e.g. 'You are the host companion on the casino host's phone: ...')",
 "intro":"what the agent calls itself after 'Hi, I'm LiveKit, ' (e.g. \"{brand}'s host companion\")",
 "greeting_followup":"one instruction for the rest of the greeting, e.g. 'offer to run through today's arriving VIPs, starting with the top one.'",
 "view":"app or site",
 "instructions":["5-9 short behaviour rules specific to this role: what to lead with, how to prioritise, limits it must respect (e.g. never offer comps above the host's authority), when to recommend what"],
 "data_md":"markdown: realistic SYNTHETIC sample data the agent needs for this use case (e.g. today's records with profiles, preferences, history, limits/policies), 6-12 records, clearly fictional names, consistent numbers, tied to real {brand} venues/offers/shows where relevant",
 "panel":{{"path":"/<short-slug>","nav":"short nav label","title":"screen title","subtitle":"one line",
   "items":[{{"title":"record name","subtitle":"one line","badges":["short tag"],"fields":[{{"label":"...","value":"..."}}],"note":"one line suggestion"}}]}},
 "sample_questions":["4-6 short things the user might say to the agent"]}}
Rules: view is "app" when the use case is a staff/internal tool or a bespoke screen (dashboard, briefing, console, phone
companion) rather than a customer browsing {brand}'s public site, otherwise "site". panel.items show the same records as
data_md (max 12, 3-6 fields each). Everyone is fictional: no real customer data, no real staff names. No URLs, no markdown
in instructions. The panel path must not be a sign-in, account, checkout or payment page.
WEBSITE SUMMARY:
"""


def scenario(work, brand, concept):
    """The use-case step: one Gemini call -> ref/scenario.json (site model facts give it the real venues/offers)."""
    ref = os.path.join(work, "ref")
    ctx, url = {}, ""
    cp = os.path.join(ref, "capture.json")
    if os.path.exists(cp):
        url = json.load(open(cp)).get("url", "")
    sp = os.path.join(ref, "site.json")
    if os.path.exists(sp):
        m = json.load(open(sp))
        ctx = {"facts": m.get("facts"), "pages": [{"path": p.get("path"), "title": p.get("title")} for p in m.get("pages") or []]}
    if not ctx and os.path.exists(cp):
        ctx = {n: (p.get("text") or "")[:4000] for n, p in json.load(open(cp))["pages"].items()}
    print("gemini: scenario", flush=True)
    sc = gemini.generate([{"text": SCENARIO_PROMPT.format(brand=brand, url=url, concept=concept) + json.dumps(ctx)[:120000]}], json_out=True)
    sc["concept"] = concept
    json.dump(sc, open(os.path.join(ref, "scenario.json"), "w"), indent=1)
    print(f"scenario: view={sc.get('view')} user={sc.get('user')!r} {len((sc.get('panel') or {}).get('items') or [])} records")


def main(work, brand):
    ref = os.path.join(work, "ref")
    cap = json.load(open(os.path.join(ref, "capture.json")))
    pages = cap["pages"]
    names = list(pages)[:6]
    parts = [{"text": SPEC_PROMPT.format(brand=brand)}]
    for n in names:
        for tag in ("desk", "phone"):
            f = os.path.join(ref, f"{n}-{tag}.png")
            if os.path.exists(f):
                parts += [{"text": f"Screenshot {n}-{tag}"}, gemini.image_part(f)]
    parts.append({"text": "Computed styles: " + json.dumps({n: pages[n].get("styles") for n in names})[:20000]})
    print("gemini: spec", flush=True)
    spec = gemini.generate(parts)
    open(os.path.join(ref, "spec.md"), "w").write(spec)
    print("gemini: tokens", flush=True)
    tokens = gemini.generate([{"text": TOKENS_PROMPT + spec[:30000]}], json_out=True)
    json.dump(tokens, open(os.path.join(ref, "tokens.json"), "w"), indent=1)
    slim = {n: {k: p.get(k) for k in ("url", "title", "headings", "images", "bgImages", "nav")} | {"text": (p.get("text") or "")[:6000]}
            for n, p in pages.items()}
    print("gemini: site model", flush=True)
    model = gemini.generate([{"text": MODEL_PROMPT.format(brand=brand, url=cap["url"], n=len(pages)) + json.dumps(slim)[:400000]}], json_out=True)
    json.dump(model, open(os.path.join(ref, "site.json"), "w"), indent=1)
    jobs = model.get("image_jobs") or []
    json.dump({"outdir": os.path.join(work, "site", "img", "gen"),
               "style": "Style: premium hospitality marketing photography, photorealistic, magazine quality. Absolutely no text, letters, numbers, logos, signage or watermarks. No identifiable faces.",
               "jobs": [{"file": j["file"], "prompt": j["prompt"], "size": 1280} for j in jobs]},
              open(os.path.join(ref, "images.json"), "w"), indent=1)
    print(f"spec {len(spec)} chars, {len(model.get('pages', []))} pages, {len(jobs)} image jobs")


if __name__ == "__main__":
    brand = sys.argv[sys.argv.index("--brand") + 1] if "--brand" in sys.argv else "the company"
    if "--scenario-only" in sys.argv:
        cf = sys.argv[sys.argv.index("--concept-file") + 1]
        scenario(sys.argv[1], brand, open(cf).read().strip())
    else:
        main(sys.argv[1], brand)
