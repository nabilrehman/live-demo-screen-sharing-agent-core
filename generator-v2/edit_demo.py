"""Change a finished demo without rebuilding it: the agent's name and voice, or a plain-English change to its data and
behaviour ("add a date of birth to every customer", "she should greet in Spanish first").

  python edit_demo.py <slug> [--assistant Allie] [--voice female|male] [--change "what to change"]
                      [--brand X --code Y]   (default: from work/<slug>/job.json, else the slug)

Quick-mode demos with a use case keep their source in ref/scenario.json: the change is applied there and build.py
re-renders the scenario screen and the knowledge pack from it, so the page and the agent stay in step (no capture,
design or image calls). Other demos (claude mode, no use case): the change is applied to the knowledge pack's text
files directly; their pages are left as they are. Every edit backs up what it changes to work/<slug>/history/<time>/.
The caller restarts the demo's voice worker afterwards (host/server.py does).
Prints one JSON line at the end: {"ok": true, "summary": "...", "changed": [...]}.
"""
import datetime, json, os, shutil, subprocess, sys, time

import design, gemini

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TEXT_FILES = ("livekit_prompt.md", "greeting.md", "scenario.md")  # what a change may rewrite in a knowledge pack

SCENARIO_EDIT = """You maintain the sample data and agent design (JSON below) of a LiveKit voice-agent sales demo.
Apply this change requested by the sales engineer, and nothing else:
<<<
{change}
>>>
Today is {today}. Keep every other field, record and value exactly as it is. Keep the same JSON shape. If the change adds a detail the agent
asks for or checks, add it to the matching flow's asks_for and give EVERY panel item and every data_md record a value for it.
Everyone stays fictional. Output JSON only: {{"scenario": <the full updated JSON>, "summary": "one sentence: what you changed"}}
JSON:
"""

FILES_EDIT = """You maintain the knowledge pack of a LiveKit voice-agent sales demo: the agent's prompt, greeting and sample
data, as files (below). Apply this change requested by the sales engineer, and nothing else:
<<<
{change}
>>>
Keep placeholders such as {{assistant}}, {{brand}}, {{today}} and {{knowledge}} exactly as they are. If the change adds a
detail the agent asks for or checks, give every sample record a realistic fictional value for it. Return only the files you
changed, complete. Output JSON only: {{"files": {{"<file name>": "<full new content>"}}, "summary": "one sentence: what you changed"}}
FILES:
"""


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def backup(work, paths):
    dst = os.path.join(work, "history", time.strftime("%Y%m%d-%H%M%S"))
    for p in paths:
        if os.path.isfile(p):
            rel = os.path.relpath(p, work)
            os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
            shutil.copy2(p, os.path.join(dst, rel))
    return dst


def set_persona(work, assistant, voice):
    """ref/persona.json is what build.py reads; knowledge/site.json is what the running worker reads."""
    pp = os.path.join(work, "ref", "persona.json")
    try:
        p = json.load(open(pp))
    except (OSError, ValueError):
        p = {}
    if assistant:
        p["assistant"] = assistant
    if voice:
        p["voice"] = voice
    os.makedirs(os.path.dirname(pp), exist_ok=True)
    json.dump(p, open(pp, "w"))
    sj = os.path.join(work, "knowledge", "site.json")
    site = json.load(open(sj))
    if assistant:
        site["assistant"] = assistant
    if voice:
        site["voice"] = voice
    json.dump(site, open(sj, "w"), indent=1)
    return [x for x in (f"name {assistant}" if assistant else "", f"{voice} voice" if voice else "") if x]


def edit_scenario(work, change):
    sp = os.path.join(work, "ref", "scenario.json")
    sc = json.load(open(sp))
    concept = sc.pop("concept", "")
    r = gemini.generate([{"text": SCENARIO_EDIT.format(change=change, today=datetime.date.today().strftime("%B %d, %Y")) + json.dumps(sc)}], json_out=True)
    new = r.get("scenario") if isinstance(r, dict) else None
    if not isinstance(new, dict) or not (new.get("panel") or new.get("data_md")):
        raise RuntimeError("the model returned no usable scenario")
    new = design.complete_records(new)
    new["concept"] = concept
    json.dump(new, open(sp, "w"), indent=1)
    return r.get("summary") or "updated the scenario"


def edit_files(work, change):
    kd = os.path.join(work, "knowledge")
    files = {n: open(os.path.join(kd, n)).read() for n in TEXT_FILES if os.path.isfile(os.path.join(kd, n))}
    r = gemini.generate([{"text": FILES_EDIT.format(change=change) + json.dumps(files)}], json_out=True)
    changed = {n: c for n, c in ((r or {}).get("files") or {}).items() if n in files and isinstance(c, str) and c.strip()}
    for n, c in changed.items():
        open(os.path.join(kd, n), "w").write(c)
        if n == "livekit_prompt.md":  # site.py loads kai_prompt.md
            open(os.path.join(kd, "kai_prompt.md"), "w").write(c)
    return (r or {}).get("summary") or "no change", sorted(changed)


def rebuild(work, slug, brand, code):
    cf = os.path.join(work, "concept.txt")
    subprocess.run([PY, os.path.join(HERE, "build.py"), work, "--slug", slug, "--brand", brand, "--code", code, "--base", f"/v2/{slug}",
                    *(["--concept-file", cf] if os.path.exists(cf) else [])], check=True, stdout=sys.stderr)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); sys.exit(0 if len(sys.argv) > 1 else 2)
    slug = sys.argv[1]
    work = os.path.join(HERE, "work", slug)
    if not os.path.isfile(os.path.join(work, "knowledge", "site.json")):
        sys.exit(f"{slug}: no finished demo at {work}")
    try:
        job = json.load(open(os.path.join(work, "job.json")))
    except (OSError, ValueError):
        job = {}
    brand, code = arg("--brand", job.get("brand") or slug.title()), arg("--code", job.get("code") or slug.upper() + "-DEMO")
    assistant, voice, change = (arg("--assistant") or "").strip(), (arg("--voice") or "").strip().lower(), (arg("--change") or "").strip()
    if voice and voice not in ("female", "male"):
        sys.exit("--voice must be female or male")
    kd = os.path.join(work, "knowledge")
    backup(work, [os.path.join(work, "ref", n) for n in ("scenario.json", "persona.json")]
           + [os.path.join(kd, n) for n in ("site.json", "kai_prompt.md", *TEXT_FILES)])
    summary, changed = [], []
    if assistant or voice:
        summary.append("set " + " and ".join(set_persona(work, assistant, voice))); changed.append("site.json")
    if change:
        if os.path.isfile(os.path.join(work, "ref", "scenario.json")) and os.path.isfile(os.path.join(work, "ref", "tokens.json")):
            summary.append(edit_scenario(work, change))
            rebuild(work, slug, brand, code)  # re-renders the screen + knowledge from the edited scenario (keeps persona)
            changed += ["ref/scenario.json", "knowledge/", "site/"]
        else:
            s, files = edit_files(work, change)
            summary.append(s); changed += [f"knowledge/{n}" for n in files]
    print(json.dumps({"ok": True, "summary": "; ".join(x for x in summary if x) or "nothing to change", "changed": changed}))


if __name__ == "__main__":
    main()
