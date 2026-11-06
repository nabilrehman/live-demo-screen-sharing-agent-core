"""generator-v2: paste a URL -> a LiveKit voice-copilot demo of that site, the Wind Creek way (see ../GENERATOR_NOTES.md).
ISOLATED from the live demos: writes only under work/<slug>/; deploy (opt-in) only ADDS public/v2/<slug>/.

  python generate_demo.py <url> <slug> --brand "Hard Rock Hotels" [--code X] [--pages 8] [--mode quick|claude]
         [--skip capture,design,scenario,images] [--deploy] [--concept "use case text" | --concept-file use_case.txt]
         [--assistant Allie] [--voice female|male]

--assistant / --voice (optional): the agent's name and voice; otherwise the use case decides (quick mode), else "LiveKit".

--concept (optional): a free-text agent use case / scenario, e.g. "Casino hosts walk the floor managing high rollers; give
         each host an AI agent on their phone that briefs them on arriving VIPs". With it, the agent's persona, prompt,
         greeting and knowledge (synthetic sample data) are built around that scenario, plus a scenario screen in quick
         mode; without it, the generator behaves exactly as before (generic site-clone copilot).

quick  : capture (Playwright) -> Gemini spec/tokens/site model -> Gemini gap images -> generic builder -> knowledge pack.
claude : runs Claude Code headless with the demo-design skill and a filled-in version of templates/claude_prompt.md
         (the full-quality path, same as the Hard Rock build; takes 1-3 h).
Python: ~/Downloads/livekit-demo-agent/.venv/bin/python (has Playwright + Pillow).
"""
import os, subprocess, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
S = os.environ.get("GEN_SCRATCH", "/private/tmp/claude-501/-Users-nabilrehman-Downloads-livekit-demo-agent/3cb0ded0-74a9-4dff-b0b7-bb53c4643301/scratchpad")  # host/ sandbox sets GEN_SCRATCH
GEN = os.path.join(S, "imggen", "gen.py")


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


CLAUDE_CONCEPT = """
USE CASE (required; written by the LiveKit sales engineer, it shapes the agent more than the site clone does):
<<<
{text}
>>>
- Build the voice agent around this scenario, not as a generic website concierge: write knowledge/{slug}/livekit_prompt.md and
  greeting.md for that role (who the user is, what the agent does for them, how it should talk), and add realistic SYNTHETIC
  sample data the scenario needs (clearly fictional people/accounts, consistent numbers and limits, tied to {brand}'s real
  venues, offers and properties) as knowledge/{slug}/scenario.md, listed first in site.json "knowledge_files".
- If the scenario implies a bespoke app view rather than a public-site page (a staff dashboard, daily briefing, console, phone
  companion, ...), build that screen too: a page under /v2/{slug}/<name>/ in {brand}'s design tokens, phone-first at 390,
  linked first in the nav, gated like the rest, showing the same records as scenario.md, and make it what the agent opens
  first. Keep the site replica as supporting context where it helps (e.g. venues to recommend).
- Pick the 2-4 tasks the user will walk through with the agent. For each, list every detail the agent asks for or checks
  (date of birth, policy or account number, ZIP...). Every record in scenario.md, and on the app screen, MUST have every one
  of those details with a value; check this before testing. A missing detail makes the agent ask for it again and again.
- Adapt the scripted spoken-flow test so most of the ~12 checks exercise this scenario (ask for the core task, drill into
  one record, a policy/limit question, a recommendation), run each task end to end including any identity check, and fail
  the check if the agent asks for the same detail twice. List the scenario and its tasks in REPORT.md.
"""

PERSONA = """
AGENT PERSONA (set by the sales engineer; it overrides the defaults): {text}. Put it in knowledge/{slug}/site.json as
"assistant" (the name) and "voice" ("female" or "male"; the worker picks the matching voice), and use the name in the
prompt and greeting instead of "LiveKit".
"""


def concept_text():
    """--concept-file wins over --concept; empty string means no use case (old behaviour)."""
    f = arg("--concept-file")
    if f and os.path.exists(f):
        return open(f).read().strip()
    return (arg("--concept") or "").strip()


def run(*cmd):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); sys.exit(0 if len(sys.argv) > 1 else 2)
    url, slug = sys.argv[1], sys.argv[2]
    brand = arg("--brand", slug.title())
    code = arg("--code", slug.upper() + "-DEMO")
    mode = arg("--mode", "quick")
    skip = set((arg("--skip", "") or "").split(","))
    work = os.path.join(HERE, "work", slug)
    os.makedirs(work, exist_ok=True)
    concept = concept_text()
    cfile = os.path.join(work, "concept.txt")
    if concept:
        open(cfile, "w").write(concept + "\n")
        print(f"use case: {concept[:160]}{'...' if len(concept) > 160 else ''}", flush=True)
    elif os.path.exists(cfile):
        os.remove(cfile)  # a previous run's use case: this run has none
    assistant, voice = (arg("--assistant") or "").strip(), (arg("--voice") or "").strip().lower()
    if assistant or voice:  # build.py reads it; an edit later rewrites it
        os.makedirs(os.path.join(work, "ref"), exist_ok=True)
        json.dump({"assistant": assistant, "voice": voice}, open(os.path.join(work, "ref", "persona.json"), "w"))
    if mode == "claude":
        prompt = open(os.environ.get("GEN_CLAUDE_TEMPLATE", os.path.join(HERE, "templates", "claude_prompt.md"))).read()
        extra = CLAUDE_CONCEPT.strip("\n").replace("{text}", concept) if concept else ""
        if assistant or voice:
            who = ", ".join(x for x in (f"name {assistant}" if assistant else "", f"{voice} voice" if voice else "") if x)
            extra = (extra + "\n" + PERSONA.strip("\n").replace("{text}", who)).strip("\n")
        prompt = prompt.replace("{concept}", extra) if extra else prompt.replace("{concept}\n", "").replace("{concept}", "")
        for k, v in {"{url}": url, "{slug}": slug, "{brand}": brand, "{code}": code, "{S}": S}.items():
            prompt = prompt.replace(k, v)
        open(os.path.join(work, "PROMPT.md"), "w").write(prompt)
        log = open(os.path.join(work, "claude.log"), "w")
        extra = [d for d in os.environ.get("GEN_CLAUDE_ADD_DIRS", "").split(":") if d]
        p = subprocess.Popen(["claude", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose",
                              "--add-dir", S, "--add-dir", os.path.dirname(HERE), *sum((["--add-dir", d] for d in extra), [])],
                             cwd=os.path.expanduser(os.environ.get("GEN_CLAUDE_CWD", "~/Downloads/livekit-demo-agent")),
                             stdout=log, stderr=subprocess.STDOUT)
        print(f"claude build started pid {p.pid}; log {log.name}", flush=True)
        if "--wait" in sys.argv:  # host/: the job runner waits so its status reflects the build
            sys.exit(p.wait())
        return
    if "capture" not in skip:
        run(PY, os.path.join(HERE, "capture.py"), url, work, "--pages", arg("--pages", "8"))
    if "design" not in skip:
        run(PY, os.path.join(HERE, "design.py"), work, "--brand", brand)
    if concept and "scenario" not in skip:
        run(PY, os.path.join(HERE, "design.py"), work, "--brand", brand, "--scenario-only", "--concept-file", cfile)
    if "images" not in skip and os.path.exists(GEN):
        jobs = json.load(open(os.path.join(work, "ref", "images.json")))
        if jobs.get("jobs"):
            run(PY, GEN, os.path.join(work, "ref", "images.json"))
    run(PY, os.path.join(HERE, "build.py"), work, "--slug", slug, "--brand", brand, "--code", code, "--base", f"/v2/{slug}",
        *(["--concept-file", cfile] if concept else []))
    print(f"\nPreview: {PY} {os.path.join(HERE, 'preview.py')} {slug}   -> http://localhost:8795/v2/{slug}/?code={code}")
    if "--deploy" in sys.argv:
        run(PY, os.path.join(HERE, "deploy.py"), slug)


if __name__ == "__main__":
    main()
