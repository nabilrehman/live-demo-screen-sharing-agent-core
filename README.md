# live-demo-screen-sharing-agent

A voice (and optional avatar) sales engineer that gives a **live demo of a real web product**: it shares a real browser,
talks with the prospect, and drives the product while it explains it. Built on **LiveKit Agents**, runs on **LiveKit Cloud**.

**Gemini sees, Jev clicks.**

- **Gemini Live** (Vertex AI) is the brain and the voice. It hears the prospect, **sees the shared screen as live video**, and
  decides what to show and say.
- **Jev** is the hands. Gemini (or the planner, for multi-step tasks) says what to do in plain words, e.g. "open the
  Models & Voice tab". Jev picks the exact element on the live page, then the agent clicks it.
- Nothing about the product's pages is hard-coded. The code knows how to operate *a* web app. The product (what each
  screen is, why it matters, how to demo it) lives in `knowledge/*.json`.

```
 prospect (browser) ──voice──▶ LiveKit room ◀──voice, avatar, screen share──┐
                                                                           │
   ┌──────────────────────────── agent (LiveKit Agents) ───────────────────┴──────────┐
   │  Gemini Live  ◀── screen frames (video, ~1 fps) + page summary (exact labels) ──┐ │
   │     │  tools: act(goal) · do_task(request) · end_test_call()                      │ │
   │     ▼                                                                             │ │
   │  planner (text LLM, multi-step tasks) ──▶ Jev picks the element ──▶ click/type ──▶ Chromium
   │                                                ▲          (headless, logged in) ─┘ │
   │  every action reports what changed ────────────┘                                   │
   └─────────────────────────────────────────────────────────────────────────────────────┘
```

## Who does what

| Part | What it does | Where |
|---|---|---|
| **Gemini Live** | Hears and speaks. Sees the screen share as video. Decides what to show, explains it, calls tools. | `agent.py` (brain setup, prompt, tools) |
| **Screen summary** | The page's accessibility tree (headings, buttons, tabs, fields, states such as *selected* or *disabled*), top layer only: if a dialog or menu is open, only that. It gives Gemini exact labels to go with the video. | `screen_summary()` in `agent.py` |
| **Planner** | For tasks with several steps ("create an agent from the Appointment scheduling template"). Takes one step at a time, checks what each step did, retries or stops. The voice keeps talking while it works. | `class Planner` |
| **Jev** | Chooses which element on the live page fulfils a step. | `demo_agent/engines.py` (`JevEngine.decide`) |
| **Clicking** | A straight click on Jev's choice, then wait until the page reacts and report what changed ("the dialog 'Create new agent' opened", "it now reads END CALL", "the form says: …"). | `fast_hands()` in `agent.py` |
| **Knowledge** | Per product area: features (what each does, why it matters, a question to ask), verified click paths, a demo storyline. | `knowledge/*.json` |
| **Voice bridge** | The prospect can talk to the agent they just built in the product's in-browser test call. The demo agent mutes itself and comes back on "Kai, end the call". | `demo_agent/voicebridge.py`, `floor.py`, `demolistener.py` |
| **Avatar** (optional) | Anam renders the agent's voice as a face (audio passthrough). | `demo_agent/avatar.py` |

### Rules the hands follow (general, not product-specific)

- Only the top layer counts: an open dialog or menu hides the page behind it.
- Text goes into the field the step names, found by its label or the heading above it, never into another box.
- After a click, wait for the page to react. For submit buttons, wait while the dialog shows it is busy.
- Report error messages that pop up instead of moving on.
- Close a menu that covers the target and look again. Never go back or scroll unless the step asks for it.
- If the same step does nothing twice, stop and explain instead of clicking again.
- Never delete, deploy to production, buy, or rent anything.

## Run it locally

```bash
cp .env.example .env      # fill in LiveKit, GCP project, Jev key, start URL
uv venv && uv pip install -r requirements.txt && .venv/bin/python -m playwright install chromium
gcloud auth application-default login                      # Gemini Live on Vertex AI, your GCP project
.venv/bin/python agent.py start                             # registers the worker with your LiveKit project
```

Then join a room that dispatches the agent. `web/` is a small join page (a Vercel function issues tokens) with voice/avatar
choice and captions.

The browser needs to be logged in to the product. Set `FAAN_STORAGE_STATE` to a Playwright `storage_state` JSON captured
once from a logged-in session.

## Deploy to LiveKit Cloud

```bash
lk agent create --secrets-file my.secrets .     # first time; afterwards: lk agent deploy --secrets-file my.secrets .
```

Secrets: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_CREDENTIALS_JSON_B64` (a base64 service-account key with
Vertex AI access; `entrypoint.sh` turns it into a credentials file), `JEV_OPENROUTER_API_KEY`, `DEMO_START_URL`,
`FAAN_STORAGE_STATE_B64`, and optionally the Anam and log-upload keys. LiveKit injects the LiveKit credentials itself.
Each worker takes one call at a time, because each call runs its own Chromium (`cloud_main.py`).

## Checking the claims

Every call writes `sessions/<room>/events.jsonl`. In LiveKit Cloud the agent uploads it during and after the call (`LOG_URL`).

- **Gemini sees:** `video_frames` events count the screen frames sent to Gemini and the frame rate.
- **Jev clicks:** every `pick` event is Jev's decision (`by: jev`), and `act_done.how` records what made each click.
- Visual questions ("what's the slowest part of this call?") are answered from the chart on screen.

## Honest limits

- **Latency.** Turns where Gemini also calls a tool take about 1–1.5 s before it speaks. A multi-step task (e.g. creating an
  agent) takes about 15–25 s of clicking, while the agent keeps talking.
- **Labelled web UIs work best.** Jev and the page summary rely on the accessibility tree. Canvas-only UIs are seen in the
  video but can't be clicked precisely.
- **Credentials.** Gemini Live needs a GCP project with Vertex AI. A switch (`BRAIN=grok`) runs the same hands with Grok
  Voice through LiveKit Inference instead (no Google credentials, faster, but it reads the screen as text only).
