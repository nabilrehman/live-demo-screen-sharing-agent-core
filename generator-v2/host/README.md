# generator-v2/host - hosted "generate a demo" (Vercel Sandbox + main demo page button)

**Flow:** main demo page (live-demos-sa, project `nabil-flights-demo`) -> sparkle **"Generate a demo from any website"** button
-> modal (URL, brand, slug, optional agent use case, mode, Gemini images, builder code) -> `POST /api/generate` on the
build host -> `generate_demo.py` runs inside the sandbox (quick: Playwright+Gemini; claude: Claude Code headless with the
demo-design skill, `templates/claude_prompt_sandbox.md`) -> the modal polls `/api/jobs/<slug>` (live log) -> when done the
demo is served at `https://<sandbox>.vercel.run/v2/<slug>/?code=<SLUG>-DEMO` with its own voice worker, and shows up as a
card in the modal + a chip under the demo tabs on the main page (`/api/demos`).

## Pieces
- `server.py` - the controller (aiohttp, :8080, public via the sandbox's exposed port). Jobs are detached subprocesses;
  state is on disk (`work/<slug>/job.json`) so a new session picks up finished demos and restarts their voice workers.
- `run_voice.sh` - starts `src/windcreek_agent.py` as agent `gen-<slug>` with `SITE_KNOWLEDGE=work/<slug>/knowledge`.
- `start_host.sh` - (re)start the controller; run it after every sandbox resume (processes do not survive a stop).
- `landing/aigen-snippet.html` - the additive block injected before `</body>` of the main page, plus the
  `<div class="aigen-row">` button row inserted right after `</nav>` of `.demos`. `API` const at the top of its script
  points at the sandbox URL.
- generator changes are env-overridable and keep Mac behaviour by default: `GEN_SCRATCH`, `GEN_WIDGET`, `PW_CHANNEL`
  (empty = bundled chromium), `GEN_CLAUDE_TEMPLATE`, `GEN_CLAUDE_CWD`, `GEN_CLAUDE_ADD_DIRS`, and `--wait` for claude mode.

## Sandbox (enterprise team, scope `livekit`)
`demo-gen-host`: 8 vCPU, 24 h session, port 8080 -> https://sb-mgs5l8pw3lep.vercel.run . Layout (HOME=/vercel):
`/vercel/gen/generator-v2` (this folder), `/vercel/gen/scratch` (widget, imggen), `/vercel/core` (template repo),
`/vercel/agent` (+ .venv via `uv sync`), `/vercel/venv` (Playwright/Pillow/aiohttp/livekit-api), `/vercel/.claude`.
Seeded from the `demo-gen-v3-test` setup (no secrets in git). Re-deploy code: tar this folder (minus work/) into
`/vercel/gen/generator-v2`, then `bash host/start_host.sh`.

## Auth today, and where per-user login plugs in
- Today (v1): ONE seeded login per sandbox - the Claude Code login copied into `/vercel/.claude/.credentials.json`
  (access token only, no refresh token: it expires; `/api/demos` returns only its `claude_login_expires` timestamp
  and claude-mode builds are refused 30 min before expiry), the Gemini key file and `/vercel/gen/.lk.env` (LiveKit).
  Starting a build needs the shared **builder code** in `/vercel/gen/.build_code` (stops random visitors from spending
  the login; it is an access code, not a credential). Viewing demos is anonymous behind each demo's access code.
- TODO(per-user): each LiveKit person gets their own persistent sandbox `demo-gen-<username>` (Okta email -> username).
  1. Front door: Vercel function on the enterprise team (OIDC auth to the Sandbox API) with `Sandbox.getOrCreate({name:
     "demo-gen-"+user, ports:[8080], onCreate: seed code + deps, onResume: start_host.sh})`.
  2. First use: run `claude setup-token`/`claude login` in that sandbox and stream its device-code URL to the modal; the
     user approves with their own Claude (Okta) account; the login stays in that sandbox's persisted filesystem.
  3. `server.py` is unchanged; the page's `API` becomes that user's `sandbox.domain(8080)` (returned by the function),
     and the builder code is replaced by the Okta session.

## Limits (v1)
- One sandbox session lasts <= 24 h; after a stop, run `start_host.sh` (finished demos + workers come back; in-flight
  builds do not). The `*.vercel.run` URL is served only while a session is up.
- `GEN_MAX_RUNNING=3` concurrent builds (8 vCPU / 16 GB). Quick ~5-15 min; claude 1-3 h.
- Generated demos live on the sandbox URL, not on live-demos-sa; promoting one = `deploy.py` (manual, opt-in).

## Button design notes
Gemini-inspired (references in `landing/ref/`: gemini.google.com + gemini.google overview, captured with Playwright
10/21/2026): smooth four-point sparkle, blue->violet->rose gradient, soft diffuse ambient glow, pill shape. Fused with
LiveKit: the gradient starts at LiveKit cyan `#1fd5f9`, sits on the page's near-black panels, Inter type, the same pill
language as the demo tabs. Animated conic border (6 s), slow light sweep, sparkle rotates 45 deg on hover; all motion
off under `prefers-reduced-motion`.

## Live
Deployed onto the existing main page (project `nabil-flights-demo`, alias live-demos-sa.vercel.app) on 10/21/2026.
The source page is `scratchpad/vflights/public/index.html` (snippet inlined); the pre-change copy is
`~/Downloads/live-demos-index.before-aigen.html`. Rollback: `vercel rollback` / promote the previous production
deployment `nabil-flights-demo-h3hvu5lpu-livekit-b9da233b.vercel.app`.
