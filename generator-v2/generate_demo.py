"""generator-v2: paste a URL -> a LiveKit voice-copilot demo of that site, the Wind Creek way (see ../GENERATOR_NOTES.md).
ISOLATED from the live demos: writes only under work/<slug>/; deploy (opt-in) only ADDS public/v2/<slug>/.

  python generate_demo.py <url> <slug> --brand "Hard Rock Hotels" [--code X] [--pages 8] [--mode quick|claude]
         [--skip capture,design,images] [--deploy]

quick  : capture (Playwright) -> Gemini spec/tokens/site model -> Gemini gap images -> generic builder -> knowledge pack.
claude : runs Claude Code headless with the demo-design skill and a filled-in version of templates/claude_prompt.md
         (the full-quality path, same as the Hard Rock build; takes 1-3 h).
Python: ~/Downloads/livekit-demo-agent/.venv/bin/python (has Playwright + Pillow).
"""
import os, subprocess, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
S = "/private/tmp/claude-501/-Users-nabilrehman-Downloads-livekit-demo-agent/3cb0ded0-74a9-4dff-b0b7-bb53c4643301/scratchpad"
GEN = os.path.join(S, "imggen", "gen.py")


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def run(*cmd):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    url, slug = sys.argv[1], sys.argv[2]
    brand = arg("--brand", slug.title())
    code = arg("--code", slug.upper() + "-DEMO")
    mode = arg("--mode", "quick")
    skip = set((arg("--skip", "") or "").split(","))
    work = os.path.join(HERE, "work", slug)
    os.makedirs(work, exist_ok=True)
    if mode == "claude":
        prompt = open(os.path.join(HERE, "templates", "claude_prompt.md")).read()
        for k, v in {"{url}": url, "{slug}": slug, "{brand}": brand, "{code}": code, "{S}": S}.items():
            prompt = prompt.replace(k, v)
        open(os.path.join(work, "PROMPT.md"), "w").write(prompt)
        log = open(os.path.join(work, "claude.log"), "w")
        p = subprocess.Popen(["claude", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose",
                              "--add-dir", S, "--add-dir", os.path.dirname(HERE)], cwd=os.path.expanduser("~/Downloads/livekit-demo-agent"),
                             stdout=log, stderr=subprocess.STDOUT)
        print(f"claude build started pid {p.pid}; log {log.name}")
        return
    if "capture" not in skip:
        run(PY, os.path.join(HERE, "capture.py"), url, work, "--pages", arg("--pages", "8"))
    if "design" not in skip:
        run(PY, os.path.join(HERE, "design.py"), work, "--brand", brand)
    if "images" not in skip and os.path.exists(GEN):
        jobs = json.load(open(os.path.join(work, "ref", "images.json")))
        if jobs.get("jobs"):
            run(PY, GEN, os.path.join(work, "ref", "images.json"))
    run(PY, os.path.join(HERE, "build.py"), work, "--slug", slug, "--brand", brand, "--code", code, "--base", f"/v2/{slug}")
    print(f"\nPreview: {PY} {os.path.join(HERE, 'preview.py')} {slug}   -> http://localhost:8795/v2/{slug}/?code={code}")
    if "--deploy" in sys.argv:
        run(PY, os.path.join(HERE, "deploy.py"), slug)


if __name__ == "__main__":
    main()
