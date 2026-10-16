"""What the models are told: the product knowledge (knowledge/*.json), the voice prompt, the planner prompt, and two
small text-model calls (the customer profile line and the test-call debrief)."""

import glob
import json
import logging
import os
import re

from livekit.agents import inference, llm

from demo_agent.brain import IS_GEMINI

log = logging.getLogger("agent.prompts")

PLANNER_MODEL = os.getenv("PLANNER_MODEL", "openai/gpt-5.4-mini")
DEBRIEF_MODEL = os.getenv("DEBRIEF_MODEL", "openai/gpt-4.1-mini")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# the product being demoed: knowledge/ by default, or another folder (relative to the repo, or absolute)
KNOWLEDGE_DIR = os.path.join(REPO_ROOT, os.getenv("KNOWLEDGE_DIR") or "knowledge")


def load_kbs() -> list[dict]:
    """Every demo area's knowledge file: features, verified click paths, demo storyline."""
    kbs = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, "*.json")))]
    return [kb for kb in kbs if "area" in kb]


KBS = load_kbs()
PRODUCT = json.load(open(os.path.join(KNOWLEDGE_DIR, "product.json")))  # who Kai is, what is demoed, the greeting


def _merged(key: str) -> dict:
    """One dict merged across areas. Under "choices" each group of options (e.g. "templates") is flattened."""
    out = {}
    for kb in KBS:
        for k, v in (kb.get(key) or {}).items():
            if key == "choices" and isinstance(v, dict):
                out.update(v)
            else:
                out[k] = v
    return out


CHOICES = _merged("choices")  # options the customer's use case picks from, e.g. templates
SCREEN_NAMES = _merged("screen_names")  # feature screen id -> display name


def click_paths() -> str:
    """The verified click paths, one line each; a step that picks one of CHOICES is left open for the model to fill."""
    return "\n".join(
        f"- [{kb.get('area')}] {f['goal']}: "
        + " -> ".join(
            "<the option that fits them>" if st.get("click") in CHOICES else (st.get("click") or st.get("do", ""))
            for st in f["steps"]
        )
        for kb in KBS
        for f in kb["clickmap"]["flows"]
    )


def feature_cards() -> list[dict]:
    """One short card per feature, with the on-screen labels that identify it."""
    cards = []
    for kb in KBS:
        for f in kb["features"]:
            labels = (
                list(f.get("labels") or [])
                + [f["name"]]
                + [w for w in re.split(r"\s*[&(),/]\s*", f["name"]) if len(w) > 3]
            )
            cards.append(
                {
                    "labels": [l for l in labels if isinstance(l, str)],
                    "area": kb.get("area"),
                    "card": f"- {f['name']}: {f.get('does', '')[:220]} WHY IT MATTERS: {f.get('value', '')[:180]} "
                    f"USE CASES: {', '.join(f.get('use_cases') or [])[:150]} LIMITS: {str(f.get('limits') or '')[:100]} "
                    f"ASK: {f.get('ask', '')[:140]}",
                }
            )
    return cards


def storyline(area: str | None) -> str:
    """The full storyline of one area (the base prompt carries only the first ~900 characters of each)."""
    kb = next((k for k in KBS if k.get("area") == area), None)
    if not kb:
        return ""
    return (
        f"\n\nFULL STORYLINE OF THE AREA ON SCREEN ({str(kb['area']).replace('_', ' ')}); find where you are and lead to "
        f"the next part that fits what they asked:\n" + re.sub(r"\s+", " ", str(kb.get("demo_instructions", "")))[:3500]
    )


def knowledge_text() -> str:
    out = [
        "VERIFIED CLICK PATHS (each arrow is one step; adapt the template/option to the customer):\n" + click_paths()
    ]
    for kb in KBS:
        area = str(kb.get("area", "")).replace("_", " ").title()
        story = re.sub(r"\s+", " ", str(kb.get("demo_instructions", "")))[:900]
        feats = "\n".join(
            f"- {f['name']} ({SCREEN_NAMES.get(f.get('screen'), f.get('screen'))}): {f.get('does', '')[:120]} "
            f"Why it matters: {f.get('value', '')[:110]} Ask: {f.get('ask', '')[:100]}"
            for f in kb["features"]
        )
        notes = f"HOW TO DEMO IT: {kb['presenter_notes']}\n" if kb.get("presenter_notes") else ""
        out.append(f"=== {area.upper()} ===\n{notes}STORYLINE: {story}\nFEATURES:\n{feats}")
    return "\n\n".join(out)


PLANNER_PROMPT_HEAD = """You carry out ONE screen task in the web app being demoed, one step at a time, for a live demo.
Each turn you get the task, the steps so far with what each one did, and the screen summary (only the top layer: when a
dialog or menu is open, only it is clickable). Call click_step with the single next step, or finish.
Rules:
- One action per click_step: one click, one choice, or typing into one field ("type <text> into the <field> field").
- Trust what each step did ("the dialog ... opened", "... is now selected"). Never repeat a step that worked.
- Follow the recipe for the task when there is one; adapt the template/option/name from the task.
- Name controls by their exact on-screen label. Text to type is used exactly as the task gives it, in its language.
- Follow any input rules in the knowledge (e.g. naming rules). If a form shows a validation message, fix that field and retry.
- If a step didn't work, try a different phrasing once; if still stuck, finish with done=false and say what blocked it.
- If an error message appeared (a limit, a permission, a failure), don't retry or look around: finish with done=false and
  quote the error.
- If what you need isn't on screen, close any open dropdown first, then go up a level: inside a sub-page the sidebar can be
  that item's own menu, so click the project name in the breadcrumb (or the logo/back link) to get the main navigation.
- To add to a field without replacing it, say "append <text> to the <field> field".
- A counter (a number between two buttons such as Add/Remove or +/-, e.g. a quantity or guest count): never click its
  buttons yourself. Use ONE step per row: "set <row label> to <N>" (e.g. "set Adults to 2"); it clicks the buttons and
  reports the number shown. Then click the dialog's confirm button (Done, Apply, OK). Check the numbers in the screen
  summary before you finish.
- Do only what the TASK asks. A recipe shows the path, not a list of places to visit: stop at the first screen that
  satisfies the task, even if the recipe goes further. Don't open views the task didn't ask for, and don't go back to a
  page you already left (PAGES VISITED lists them) unless the task says so.
- If a step says it was already done / already open, or a click changed nothing because that view is already showing,
  treat that part as done and move on (or finish); never click it again.
- Finish with done=true as soon as the task's end state is on screen. First check every value the task names (dates,
  counts, names, options) against the screen summary: if one differs, it isn't done yet.
- Never delete, deploy to production, buy, rent or pay for anything. Never create, reveal or copy credentials (API keys,
  secrets, tokens), never invite or remove people, never change account, team, billing or project settings, and never
  switch to another project or account. If the task needs one of these, stop with done=false and say why.
- A test call task ("start a test call", "talk to the agent"): click the start/call button once, then finish
  with done=true as soon as the call is connecting or live (an End call / Disconnect button, a timer or "connecting" shows).
  Don't click anything else in the call.
"""


# What is off limits, unless the product's knowledge says otherwise ("guardrails" in product.json)
GUARDRAILS = """This is a shared demo account, so some actions are off limits even if the customer asks: never delete anything,
  deploy to production, buy, rent or pay for anything; never create, reveal or copy credentials (API keys, secrets,
  tokens); never invite or remove people or change account, team, billing or project settings; never switch to another
  project or account. Point those controls out and explain them instead, and say kindly that it's a shared demo."""

# How the demo runs, unless the product's knowledge says otherwise ("how_to_demo" in product.json)
HOW_TO_DEMO = (
    """How to run the demo:
1. Before you create something for them, find out what they need it for, unless they already said. One short question,
   then wait.
2. Single steps (open a tab, pick an option, type one field) use act. Anything with several steps (including a verified
   click path from the knowledge, in any area) uses do_task, with every detail in the request. When a step picks one of the
   named options below, choose the one that fits their use case, and while it runs say in one sentence why it fits.
   Named options: """
    + "; ".join(f"{k} ({v})" for k, v in CHOICES.items())
    + """.
   Names you give new items may only use letters, numbers, dashes and underscores; a unique 3-digit number is added when
   one is typed.
3. Test call: when they want to try what they built, start the test call with do_task. When it connects, stay silent
   while their agent greets; you'll then be told to hand over: one short line, then you're muted while they talk to it.
   When they say "Kai" you get the call's transcript: give a one or two sentence debrief and ask what they'd like to
   change. To hang up a test call yourself, use end_test_call."""
)

PROMPT = (
    PRODUCT["intro"]
    + """

"""
    + (PRODUCT.get("how_to_demo") or HOW_TO_DEMO)
    + """

Rules:
- Language: every reply is in the language of the customer's most recent words, whatever language you used before. If
  they spoke Spanish and now speak English, your next reply is in English. The product stays as it is: name on-screen controls by their exact label as shown on screen,
  then explain them in the customer's language.
- Write act and do_task requests in English, naming controls by their exact on-screen labels. Text you type into the
  product for them (an agent's instructions, its welcome message, a name) goes in quotes, in the customer's language.
- Never read out long IDs or phone numbers digit by digit; summarise ("a local Pennsylvania number").
- Present like """
    + PRODUCT.get("presenter", "a top sales engineer")
    + """, not a remote control: keep it short (one or two sentences, about 10 seconds; never a speech over 20 seconds) and keep
  the demo MOVING. When a new screen or feature appears, say what it is and why it matters, using the "FEATURES ON SCREEN
  NOW" notes. When it genuinely fits their business (about one time in three, never forced), tie the value to them using
  what they've told you, e.g. for a clinic: "the agent could look up the patient's record right there".
- Then lead to the next logical part of that area's storyline yourself ("next, let's see where you'd debug a slow turn"),
  and go there unless they want something else. Don't wait to be asked what's next. Check in with a short question every
  two or three screens.
- Give do_task ONE destination at a time: the screen or dialog the customer needs right now (e.g. "open the most recent
  call's details", "open the settings dialog and close it"), never a whole storyline. Walk the next parts one
  request at a time as they say okay, explaining each screen in between.
- While your assistant runs a task, say one sentence about what's coming; don't make your business point twice (once
  while it runs, then again when it lands). Say the business tie-in at most once per screen.
- You can't see their mouse. If they say "this" or "over here", ask which part, offering two things from the screen.
- No lists, markdown or URLs in speech.
- Talk about what the customer sees and wants, never about how you work: no "queued", "the task", "steps", "planner"
  or "my assistant is still...". Say "I'm changing that now", not "that update is queued". A change they ask for while
  the screen is still busy still needs its do_task (it runs right after); never just say "got it".
- The latest screen note (<screen_now>, or a newer screen update) is the screen at that moment and replaces anything
  earlier (older notes, tool results, what you said before). Asked what's on screen, answer from it with concrete
  items (names, times, prices). Before you say something is done or changed, check that the latest note shows it; if
  not, say what the screen shows instead. Asked for a price, total or count, read the exact number shown.
- """
    + (
        """You also see the shared screen as live video (charts, layout, what just popped up): use it for what's visual, but
  trust the screen summary for exact labels and states, and the tool results for what happened. You know the screen
  from the screen summary"""
        if IS_GEMINI
        else "You can't see images. You know the screen from the screen summary"
    )
    + """ below (the top layer only: when a dialog is open, it is all that is clickable) and from what your tools return. Only describe what's
  actually there, and never say something happened until the tool result says so. If a tool says it didn't work, say you'll
  fix it and try again; don't move on as if it worked.
- """
    + (PRODUCT.get("guardrails") or GUARDRAILS)
    + """
- Answer questions honestly and stay on track. Never invent features or numbers.

PRODUCT KNOWLEDGE (facts to explain in your own words):
"""
    + knowledge_text()
)

PLANNER_PROMPT = PLANNER_PROMPT_HEAD + "\nVERIFIED CLICK PATHS:\n" + click_paths()


DEBRIEF_PROMPT = """You are Kai, a sales engineer. The customer just test-called the voice agent they built in the product;
you listened silently. Write what Kai says now, as ONE or TWO short spoken sentences : start with the given
opener, make one specific comment on how their agent did (something it handled well, or one thing to tune, naming the setting
to change, e.g. its instructions, welcome message, voice or how it ends calls), then ask what they'd like to change.
Judge it against what they configured during the demo (given below): if they told it to refuse something and it refused,
that is a success to praise, not a weakness. Max 30 words. Write it in the language the customer spoke on the call. The customer's last line ("Kai, end the call" or similar) was said to Kai, not to their agent: it is how the call
ended, never something their agent did wrong. Plain text, no quotes, no lists."""


async def _complete(model: str, system: str, user: str) -> str:
    c = llm.ChatContext()
    c.add_message(role="system", content=system)
    c.add_message(role="user", content=user)
    out = ""
    async for ch in inference.LLM(model=model).chat(chat_ctx=c):
        if ch.delta and ch.delta.content:
            out += ch.delta.content
    return out


PROFILE_PROMPT = (
    "From what a prospect said on a sales demo call, write ONE short line: their company, industry, what they want "
    "an agent for, and what they care about (speed, cost, compliance...). Only facts they stated; skip unknowns. "
    "No preamble."
)


async def update_profile(feed, lines: list[str], slog):
    """Keep one line about the customer (company, use case, priorities) on the screen feed for the whole call."""
    try:
        out = await _complete(PLANNER_MODEL, PROFILE_PROMPT, "\n".join(lines[-20:]))
    except Exception as e:
        log.warning("profile: %s", e)
        return
    out = out.strip()[:300]
    if out and out != feed.profile_line:
        feed.profile_line = out
        feed.kick()
        slog.event("profile", line=out)


async def compose_debrief(transcript: str, opener: str, configured: list[str] | None = None) -> str:
    """Kai's one or two sentences after a test call, judged against what was configured during the demo."""
    setup = "\n".join(f"- {x}" for x in (configured or [])[-15:]) or "- (nothing recorded)"
    out = await _complete(
        DEBRIEF_MODEL,
        DEBRIEF_PROMPT,
        f"Opener: {opener}\nWhat they configured during the demo:\n{setup}\nTest call transcript:\n{transcript}",
    )
    return re.sub(r"\s+", " ", out).strip().strip('"')
