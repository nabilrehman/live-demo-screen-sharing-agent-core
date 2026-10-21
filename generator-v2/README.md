# generator-v2 — paste a URL, get a LiveKit voice-copilot demo (DRAFT)

Isolated v2: lives only on branch `generator-v2` (worktree `~/Downloads/live-demo-agent-core-v2`), writes only under
`generator-v2/work/<slug>/`, serves under `/v2/<slug>/`. It does not modify the live demos (/, /hotel/, /windcreek/,
/flights/ …), their widgets (`embed/windcreek/kai.js`, `hotel/kai.js`) or their LiveKit agents. Pipeline recap: `../GENERATOR_NOTES.md`.

Python: `PY=~/Downloads/livekit-demo-agent/.venv/bin/python` (Playwright + Pillow + aiohttp). Gemini key: `~/Downloads/livekit-ops/gemini_key`.

## Run
    $PY generate_demo.py https://thehoxton.com/ hoxton --brand "The Hoxton" --pages 6            # quick mode
    $PY generate_demo.py https://hotel.hardrock.com/ hardrock --brand "Hard Rock Hotels" --mode claude   # full-quality, Claude Code + demo-design skill
    $PY preview.py hoxton      # http://localhost:8795/v2/hoxton/?code=HOXTON-DEMO
    $PY shot.py hoxton         # verify screenshots (1440 + 390) -> work/hoxton/verify/
    $PY server.py              # web form at http://localhost:8796/
    $PY deploy.py hoxton       # opt-in: copies into vflights/public/v2/hoxton/ and prints the agent/token/vercel steps

## Steps (quick mode)
1. `capture.py` — Playwright (channel chrome), home + N same-origin nav pages, full-page 1440/390 PNGs, text, images, nav, computed styles → `ref/capture.json`.
2. `design.py` — Gemini (`gemini-3.1-pro-preview`): `ref/spec.md`, `ref/tokens.json`, `ref/site.json` (site model from the real content + facts), `ref/images.json`.
3. images — `$S/imggen/gen.py ref/images.json` (gemini-3-pro-image, 30 parallel) for gap images (`gen:<file>` in the model).
4. `build.py` — static pages from tokens + model: LiveKit banner, noindex, access-code gate, inert "Demo only" buttons, the in-page copilot widget copied and renamed Kai → LiveKit (`livekit/livekit.js`, `window.LiveKitAgent`, `#lk-root`, "Talk to LiveKit"), plus the agent knowledge pack `knowledge/` (site.json assistant=LiveKit, facts.md, sitemap.md, prompt, greeting).
5. Voice: the generic agent `src/windcreek_agent.py` with `SITE_KNOWLEDGE=work/<slug>/knowledge AGENT_NAME=gen-<slug> BRAIN=grok` (local), or a cloud agent per `deploy.py`.

## Known gaps (draft)
- Quick mode is a generic template in the brand's tokens, not a pixel replica; claude mode is the high-fidelity path.
- No booking-engine replica / site_actions in quick mode; no scripted spoken-flow test yet (reuse `tests/windcreek_flow.py`).
- Cloud deploy is printed, not automated, on purpose (the Vercel deploy ships the whole shared live-demos-sa site).
