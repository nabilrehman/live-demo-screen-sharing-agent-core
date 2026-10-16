# AGENTS.md

A LiveKit Agents project (Python, `uv`). See README.md for what it does.

## Layout

- `src/agent.py`: the worker entrypoint. `class Kai` (tools: act, do_task, stop_task, end_test_call), session wiring,
  voice bridge wiring. `src/cloud_main.py`: the LiveKit Cloud entrypoint (one call per worker).
- `src/demo_agent/`: brain.py (realtime model), prompts.py (prompts from `knowledge/`), screen.py (screen summary and
  the screen feed), hands.py (one step on the page), engines.py (Jev), planner.py (multi-step tasks), nudges.py,
  floor.py / voicebridge.py / demolistener.py (in-browser test calls), avatar.py, browser.py, sesslog.py, cleanup.py.
- `knowledge/`: the product. Product-specific text belongs here, not in code.
- `src/shop_agent.py` + `src/inpage/`: a separate agent, a shopping guide inside a store page (page_context text stream
  up, RPC actions down; no browser). Store-agnostic: the store, assistant and products come from the store's
  catalog.json (`CATALOG_URL`; fallback `knowledge/shop/catalog.json`), the prompt template is `knowledge/shop/prompt.md`.
  Keep store and product names out of its code. Deploy it from `shop.Dockerfile`.

## Run and test

- `uv sync`, `uv run playwright install chromium`, `uv run src/agent.py dev`
- `uv run pytest`; `uv run ruff check` and `uv run ruff format` before committing.
- `tests/voice_flow.py`: a spoken end-to-end run against a running worker (see its docstring).

## Conventions

- Session log event kinds (`pick`, `act_done`, `evidence`, ...) and the participant attributes `faan.mode` and
  `faan.floor` are read by other tools: don't rename them.
- Comments explain the code (what and why), not its history.
- Refer to the LiveKit docs (`lk docs`, or the docs MCP server) for LiveKit Agents APIs.
