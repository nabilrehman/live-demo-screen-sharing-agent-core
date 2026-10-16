# live-demo-screen-sharing-agent

A voice (and optional avatar) sales engineer that gives a **live demo of a real web product**: it shares a real browser,
talks with the prospect, and drives the product while it explains it. Built on **LiveKit Agents**, runs on **LiveKit Cloud**.

**Gemini sees, Jev clicks.**

- **Gemini Live** (Gemini API or Vertex AI) is the brain and the voice. It hears the prospect, **sees the shared screen
  as live video**, and decides what to show and say.
- **Jev** is the hands. Gemini (or the planner, for multi-step tasks) says what to do in plain words, e.g. "open the
  Settings tab". Jev picks the exact element on the live page, then the agent clicks it.
- The code knows how to operate *a* web app; nothing about the product's pages is hard-coded. The product (who Kai is,
  what each screen is, why it matters, how to demo it) lives in `knowledge/`.

```
 prospect (browser) ──voice──▶ LiveKit room ◀──voice, avatar, screen share──┐
                                                                           │
   ┌──────────────────────────── agent (LiveKit Agents) ───────────────────┴──────────┐
   │  Gemini Live  ◀── screen frames (video, ~1 fps) + screen summary (exact labels) ─┐ │
   │     │  tools: act(goal) · do_task(request) · stop_task() · end_test_call()        │ │
   │     ▼                                                                             │ │
   │  planner (text LLM, multi-step tasks) ──▶ Jev picks the element ──▶ click/type ──▶ Chromium
   │                                                ▲          (headless, logged in) ─┘ │
   │  every action reports what changed ────────────┘                                   │
   └─────────────────────────────────────────────────────────────────────────────────────┘
```

## Who does what

| Part | What it does | Where |
|---|---|---|
| **Worker** | Registers with LiveKit, starts the browser and screen share, wires the session, avatar and voice bridge. Defines the tools. | `src/agent.py` (`entrypoint`, `class Kai`) |
| **Brain** | Gemini Live (default) or Grok Voice via LiveKit Inference (`BRAIN=grok`). Gemini also gets the shared screen as video. | `src/demo_agent/brain.py` (`make_session`, `ScreenVideoInput`) |
| **Prompts and knowledge** | The voice prompt, the planner prompt and the debrief prompt, built from `knowledge/*.json`. | `src/demo_agent/prompts.py` |
| **Screen summary** | The page's accessibility tree (headings, buttons, tabs, fields, states such as *selected*), top layer only: if a dialog or menu is open, only that. It gives the model exact labels to go with the video. `ScreenText` sends it to the model when the screen changes. | `src/demo_agent/screen.py` (`screen_summary`, `ScreenText`) |
| **Planner** | For tasks with several steps ("create an agent from the Receptionist template"). Takes one step at a time, checks what each step did, retries or stops. The voice keeps talking while it works. | `src/demo_agent/planner.py` (`Planner`) |
| **Jev** | Chooses which element on the live page fulfils a step. | `src/demo_agent/engines.py` (`JevEngine.decide`) |
| **Hands** | Rules for closing, scrolling, going back and typing into a named field; otherwise a straight click on Jev's choice, then wait until the page reacts and report what changed ("the dialog 'Create new agent' opened", "the form says: …"). | `src/demo_agent/hands.py` (`fast_hands`) |
| **Nudges** | Self-prompted replies when a realtime model leaves a turn unanswered or something appears late on screen. | `src/demo_agent/nudges.py` |
| **Knowledge** | `product.json`: who Kai is and what is demoed. One file per area: features (what each does, why it matters, a question to ask), verified click paths, a demo storyline, presenter notes. | `knowledge/` |
| **Voice bridge** | The prospect can talk to the agent they just built in the product's in-browser test call. Kai mutes himself and comes back on "Kai, end the call". | `src/demo_agent/voicebridge.py`, `floor.py`, `demolistener.py` |
| **Avatar** (optional) | Anam (or another provider) renders Kai's voice as a face. | `src/demo_agent/avatar.py` |
| **Call log** | `sessions/<room>/events.jsonl`, `screen.mp4`, `summary.md`; uploaded during and after the call when `LOG_URL` is set. | `src/demo_agent/sesslog.py` |
| **Housekeeping** (optional) | LiveKit-dashboard specific: deletes Builder agents left by earlier demos so the project's agent quota has room. Not part of the demo path; off unless `DEMO_PROJECT_URL` is set. | `src/demo_agent/cleanup.py` |

### Rules the hands follow (general, not product-specific)

- Only the top layer counts: an open dialog or menu hides the page behind it.
- Text goes into the field the step names, found by its label or the heading above it, never into another box.
- After a click, wait for the page to react. For submit buttons, wait while the dialog shows it is busy.
- Report error messages that pop up instead of moving on.
- Close a menu that covers the target and look again. Never go back or scroll unless the step asks for it.
- If the same step does nothing twice, stop and explain instead of clicking again.

### Safety

- **Prompt-based only.** The voice prompt and the planner prompt tell the model never to delete, deploy to production,
  buy or rent anything (point such buttons out instead), and to stop at the first screen that satisfies a request. The
  knowledge marks such steps as point-out-only.
- Nothing in code prevents a click: if the model ignores these instructions, the hands will click whatever it asks for.
  Run the demo in a project where a stray click can't do lasting harm.

## Dev setup

Install the [LiveKit CLI](https://docs.livekit.io/intro/basics/cli/) and [uv](https://docs.astral.sh/uv/), then:

```console
lk cloud auth
lk app env --write --destination .env.local     # LiveKit URL and keys; fill in the rest of .env.local from .env.example
uv sync
uv run playwright install chromium
```

Gemini Live needs one of:

- `GOOGLE_API_KEY`: a Gemini API key (AI Studio). With it set, `brain.py` uses the Gemini API.
- Otherwise Vertex AI: `GOOGLE_CLOUD_PROJECT` (and `GOOGLE_CLOUD_LOCATION`) plus `gcloud auth application-default login`.
  That login is personal and expires; re-login (and redeploy) when it does.

The browser needs to be logged in to the product: set `FAAN_STORAGE_STATE` to a Playwright `storage_state` JSON captured
once from a logged-in session.

Run the agent:

```console
uv run src/agent.py dev       # development: reloads on code changes
uv run src/agent.py start     # production mode
```

Then join a room that dispatches the agent (`AGENT_NAME`). `web/` is a small join page (a Vercel function issues tokens)
with a voice/avatar choice and captions.

## Tests

```console
uv run pytest                 # floor control, wake phrases, voice bridge (a headless Chromium, no LiveKit room)
uv run ruff check && uv run ruff format --check
```

`tests/voice_flow.py` is a spoken end-to-end script, not a pytest test: it speaks TTS'd customer lines into a room with a
running worker and waits for each answer. See its docstring for `FLOWS`, `QUIET_S` and `AGENT_NAME`.

## Deploy to LiveKit Cloud

```console
lk agent create --secrets-file my.secrets .     # first time; afterwards: lk agent deploy --secrets-file my.secrets .
```

Or `./deploy.sh` (builds the secrets file from `.env.local`, creates or deploys), or the GitHub workflow
`.github/workflows/deploy.yml` (Actions → "Deploy to LiveKit Cloud").

Secrets: `GOOGLE_API_KEY` (Gemini API key), or for Vertex AI instead `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` and
`GOOGLE_CREDENTIALS_JSON_B64` (base64 Google credentials; `entrypoint.sh` turns it into a credentials file; without an API
key `deploy.sh` fills it from your local `gcloud auth application-default login` file), `JEV_OPENROUTER_API_KEY`, `DEMO_START_URL`,
`FAAN_STORAGE_STATE_B64`, and optionally the Anam and log-upload keys. LiveKit injects the LiveKit credentials itself.
Each worker takes one call at a time, because each call runs its own Chromium (`src/cloud_main.py`).

## Checking the claims

Every call writes `sessions/<room>/events.jsonl`. In LiveKit Cloud the agent uploads it during and after the call (`LOG_URL`).

- **Gemini sees:** `evidence` events count the screen frames sent to Gemini and the frame rate.
- **Jev clicks:** every `pick` event is Jev's decision (`by: jev`), `act_done.chooser` records what chose each click, and
  `evidence.clicks_chosen_by_brain` is always 0.
- Visual questions ("what's the slowest part of this call?") are answered from the chart on screen.

## Honest limits

- **Latency** (measured). Gemini Live: talk-only replies median 0.62 s; turns with a tool call median 2.0 s, p90 5.4 s.
  Grok Voice: talk-only replies median 0.91 s. A multi-step task (e.g. creating an agent) takes about 15–25 s of clicking,
  while the agent keeps talking.
- **Labelled web UIs work best.** Jev and the screen summary rely on the accessibility tree. Canvas-only UIs are seen in the
  video but can't be clicked precisely.
- **Credentials.** Gemini Live needs a Gemini API key or a GCP project with Vertex AI. `BRAIN=grok` runs the same hands with Grok Voice through
  LiveKit Inference instead (no Google credentials, but it reads the screen as text only).
