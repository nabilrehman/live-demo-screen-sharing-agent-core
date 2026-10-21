# How the Wind Creek demo was generated (recap for a reusable generator)

Reconstructed 2026-10-21 from Claude Code history (`~/.claude/history.jsonl`, session `3cb0ded0…` in
`~/.claude/projects/-Users-nabilrehman-Downloads-livekit-demo-agent/`, subagent `agent-a2e4d9ced3e3e332e`) and the
`windcreek` branch. Scratchpad root (call it `$S`):
`/private/tmp/claude-501/-Users-nabilrehman-Downloads-livekit-demo-agent/3cb0ded0-74a9-4dff-b0b7-bb53c4643301/scratchpad`

## Real paths (the skill text has some stale ones)
| Skill says | Real |
|---|---|
| `~/Downloads/livekit-demo-agent/.venv/bin/python` (Playwright, channel="chrome") | exists and is what was used for captures |
| `~/Downloads/livekit-ops/gemini_key` | exists |
| `scratchpad/vflights/` | `$S/vflights` (Vercel project `nabil-flights-demo`, scope `livekit-b9da233b`, alias live-demos-sa.vercel.app) |
| `scratchpad/lk-design`, `scratchpad/agents-ui` | `$S/lk-design`, `$S/agents-ui` |
| image generator | `$S/imggen/gen.py` (+ `windcreek.json` jobs file) |

## Pipeline, in order (Oct 20, ~19:34–21:58 CDT)
1. **Prompt** (Nabil): "copy one for windcreek … search their website in detail first … it is being pitched to them, realistic … replicate their website … with a demo script". Main session spawned parallel subagents: site builder + image generator.
2. **Worktree**: `git worktree add $S/windcreek -b windcreek origin/banking` (in-page agent pattern: `src/inpage/live.py`, `brain.py make_session`, BRAIN=gemini-live|grok).
3. **Research / knowledge pack** (read-only, no sign-in): curl/WebFetch + bs4 text of home, /locations, /rewards, /bethlehem/* (casino, hotel rooms, packages, dining venues, entertainment, promotions, FAQ, getting-here), other properties. Written in own words to `knowledge/windcreek/{SOURCES.md,site.json,kai_prompt.md,greeting.md,promotions.md,rewards.md,bethlehem.md,properties.md,booking.json,insights.json}` with a fetch-date stamp.
4. **Playwright captures** (`~/Downloads/livekit-demo-agent/.venv/bin/python`, `chromium.launch(channel="chrome")`): full-page 1440 + 390 screenshots of each page (`$S/wcshots`, booking engine `$S/wcbook/ref/*-desk.png|*-phone.png`), DOM probes, image URL + alt listing, computed styles JSON (`ref/capture.json`).
5. **Real images**: downloaded the site's public photos (`$S/wcimg/list.txt` maps file → source path), resized into `public/windcreek/img/`.
6. **Gemini design spec**: `$S/wcbook/spec.py` → POST `generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent` with screenshots (inlineData PNG) + computed styles → `ref/spec.md` (tokens, components+states, layouts desk/phone, copy tone).
7. **Gemini imagery** (separate background agent): `python3 $S/imggen/gen.py $S/imggen/windcreek.json` — `gemini-3-pro-image` (fallback `gemini-3.1-flash-image`), `responseModalities:["IMAGE"]`, aspect 16:9, 30 concurrent, one detailed prompt per image + shared "no text/logos/people" style suffix, outputs to `public/windcreek/img/gen/` + `manifest.json`; contact sheets (`sheet.py`) reviewed, weak ones regenerated.
8. **Build**: `mockup/windcreek/build.py` (pure-Python static generator, ~1260 lines: nav tree, page templates, `site.css`, `bookflow.js` booking-engine replica) → `uv run python mockup/windcreek/build.py ../vflights/public/windcreek`. Every page: banner "Demo mockup prepared by LiveKit for Wind Creek, not the official site", noindex, access-code gate (`ACCESS_CODE="WINDCREEK-DEMO"`, `?code=` kept in sessionStorage), inert "Demo only" buttons, and the embed tag `/embed/windcreek/kai.js data-site-root="/windcreek/"` (?brain=grok|gemini loader).
9. **Widget**: `vflights/public/embed/windcreek/{kai.js,kai.css,livekit-client.umd.js,fonts}` — generic DOM reader → `page_context` text stream; RPCs navigate/scroll_to/highlight/read_section/clear_highlight/site_action (+ `window.Kai.registerAction`); one-click "Talk to …" → "End call"; rejoins the same room after each page load.
10. **Agent**: `src/windcreek_agent.py` (generic: content via `SITE_KNOWLEDGE` dir, `src/inpage/site.py`), `windcreek.Dockerfile` (CMD `python src/windcreek_agent.py start`).
11. **Local test**: `$S/wc_server.py` (serves vflights/public + local `/api/token` dispatching a local worker), `say` → WAV beats, `tests/windcreek_flow.py` (Playwright fake mic `--use-file-for-fake-audio-capture`), 3 runs per brain, screenshots `$S/wcmock`, `$S/wcruns`.
12. **Agent deploy (LiveKit Cloud, project nabil-demo)**: secrets file `AGENT_NAME=live-demo-windcreek-grok`, `BRAIN=grok`, `MIN_RT_VOICE=eve`; `git worktree add --detach $S/wc-grok origin/windcreek; cp windcreek.Dockerfile Dockerfile; printf '[project]\n  subdomain = "nabil-demo-bi6vuv0i"\n\n[agent]\n' > livekit.toml; lk agent create --project nabil-demo --region us-east --secrets-file $S/wc_grok.secrets --silent .` Redeploys: `lk agent deploy --project nabil-demo .`
13. **Token mapping**: `vflights/api/token.js` AGENTS `'wc-grok': 'live-demo-windcreek-grok'` (+ gemini).
14. **Site deploy**: `cd $S/vflights && npx vercel deploy --prod --yes --force --scope livekit-b9da233b`; redirect `/windcreek` → `/windcreek/` in `vercel.json`.
15. **Verify**: desktop/390 screenshots vs ref, spoken eval runs (beats: Bethlehem weekend → steak → Delight tier → Escape points → book a room), commit + push `windcreek`.
16. Afterwards Nabil asked to save the method as the `demo-design` skill (20:28) and (Oct 21 08:29) to rename Kai → LiveKit (rn-hotel / rn-windcreek worktrees, pushed to origin hotel/windcreek, three agents redeployed).

## What a generator must parameterize
slug, brand, URL, page list to capture, access code, assistant name, agent name/brain, knowledge files, image job list. Generic pieces reusable as-is: `inpage/site.py` + `windcreek_agent.py` (via SITE_KNOWLEDGE), the embed widget (via data-site-root/data-brain/data-code), gen.py, the spec call, token.js mapping, vercel deploy.
