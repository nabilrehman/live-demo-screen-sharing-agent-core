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

## Agent use case (optional `--concept`)
By default the agent is a voice concierge for the cloned site. Add a free-text **use case** to build the agent around a
specific scenario instead — in the web form it's the "Agent use case" box; on the CLI `--concept "..."` or `--concept-file f.txt`:

    $PY generate_demo.py https://hotel.hardrock.com/ hardrock-hosts --brand "Hard Rock Hotels" \
      --concept "Casino hosts walk the floor managing loyalty members and high rollers. Give each host an AI agent on their phone that gives them a daily briefing of the customers coming in that day: gambling profile, the comps they're allowed to offer, preferences, and entertainment recommendations."

What changes with a use case (works for any scenario, not just casinos):
- **quick mode** — `design.py --scenario-only` (one Gemini call, ~3 min) writes `ref/scenario.json`: who the user is, the
  agent's role, greeting, role-specific rules, realistic **synthetic** sample data (6-12 fictional records tied to the
  brand's real venues/offers) and a scenario screen. `build.py --concept-file` then writes the knowledge pack from
  `templates/livekit_prompt_scenario.md` + `templates/greeting_scenario.md` (plus `knowledge/scenario.md`, listed first in
  `knowledge_files`) and renders the screen as an extra page (e.g. `/v2/<slug>/briefing/`: "Try asking" chips + one card per
  record). If Gemini judges it an app view (staff tool, dashboard, briefing) the page goes first in the nav and the agent opens it first.
- **claude mode** — `templates/claude_prompt.md` gets a USE CASE block (`{concept}`) telling Claude to build the agent
  prompt/greeting/scenario data around it, build any bespoke screen (phone-first), and point the spoken-flow test at it.
- Without a use case, output is byte-identical to before (same knowledge pack, pages, CSS and Claude prompt).
- Skip/redo: `--skip scenario` skips the Gemini scenario call (reuses an existing `ref/scenario.json`).
- Limits: the quick-mode screen is one generic card-grid layout in the brand's tokens (no charts, filters or live data);
  richer bespoke UIs need claude mode. All scenario people/data are fictional.

## Agent name and voice (optional `--assistant`, `--voice`)
`--assistant Allie --voice female` (form: "Agent name", "Agent voice") is saved to `ref/persona.json` and written to the
knowledge pack's `site.json` (`assistant`, `voice`); `src/windcreek_agent.py` passes `voice` to `brain.make_session`
(female/male -> the model's voice: Grok eve/rex, Gemini Aoede/Puck, OpenAI marin/cedar). Without them, quick mode takes the
name and voice the use case implies (`agent_name`, `voice` in `ref/scenario.json`), else "LiveKit" with the default male voice.

## Sample data the flows need
With a use case, `ref/scenario.json` also lists 2-4 `flows`, each with `asks_for`: every detail the agent asks the user for
or checks (date of birth, policy number...). `design.complete_records` checks every panel item and `data_md` has each of
them and, if not, asks Gemini to fill the gaps (up to twice) before the build continues. The tasks go into
`knowledge/scenario.md`. Separately, `src/inpage/site.py` appends demo rules to every prompt: never ask for the same detail
more than twice; if it isn't in the data or doesn't match, accept it for the demo and carry on.

## Edit a finished demo (no rebuild, about a minute)
    $PY edit_demo.py hoxton --voice female --assistant Allie --change "Add a date of birth to every guest; the agent verifies it."
Quick-mode demos with a use case: the change is applied to `ref/scenario.json` and `build.py` re-renders the scenario
screen and knowledge pack from it. Other demos (claude mode): the change is applied to the knowledge pack's text files
(`livekit_prompt.md`, `greeting.md`, `scenario.md`); pages stay as they are. Backups in `work/<slug>/history/<time>/`.
Hosted: the **Edit** button on each finished demo in the modal -> `POST /api/demos/<slug>/edit`, which also restarts the
demo's voice worker so the next call uses the change.

## Steps (quick mode)
1. `capture.py` — Playwright (channel chrome), home + N same-origin nav pages, full-page 1440/390 PNGs, text, images, nav, computed styles → `ref/capture.json`.
2. `design.py` — Gemini (`gemini-3.1-pro-preview`): `ref/spec.md`, `ref/tokens.json`, `ref/site.json` (site model from the real content + facts), `ref/images.json`.
2b. `design.py --scenario-only` — only with a use case: `ref/scenario.json` (see above).
3. images — `$S/imggen/gen.py ref/images.json` (gemini-3-pro-image, 30 parallel) for gap images (`gen:<file>` in the model).
4. `build.py` — static pages from tokens + model: LiveKit banner, noindex, access-code gate, inert "Demo only" buttons, the in-page copilot widget copied and renamed Kai → LiveKit (`livekit/livekit.js`, `window.LiveKitAgent`, `#lk-root`, "Talk to LiveKit"), plus the agent knowledge pack `knowledge/` (site.json assistant=LiveKit, facts.md, sitemap.md, prompt, greeting).
5. Voice: the generic agent `src/windcreek_agent.py` with `SITE_KNOWLEDGE=work/<slug>/knowledge AGENT_NAME=gen-<slug> BRAIN=grok` (local), or a cloud agent per `deploy.py`.

## Known gaps (draft)
- Quick mode is a generic template in the brand's tokens, not a pixel replica; claude mode is the high-fidelity path.
- No booking-engine replica / site_actions in quick mode; no scripted spoken-flow test yet (reuse `tests/windcreek_flow.py`).
- Cloud deploy is printed, not automated, on purpose (the Vercel deploy ships the whole shared live-demos-sa site).
