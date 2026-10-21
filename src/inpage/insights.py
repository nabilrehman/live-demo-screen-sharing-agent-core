"""A structured summary of one conversation, for analytics: intents, entities, pages visited, actions taken, questions
Kai couldn't answer, handoffs (where a human or the guest takes over) and response latency. No personal data: guest
words are only kept for unanswered questions, with digits, emails and names-after-"my name is" removed.

The intent, entity and handoff vocabularies are in knowledge/<site>/insights.json; the logic is generic.
"""

import json
import re
import statistics
import time

from .site import load

CFG: dict = json.loads(load("insights.json"))
SCRUB = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"\d[\d\s().-]{3,}\d"), "[number]"),
    (re.compile(r"(my name is|i'm called|this is)\s+\w+", re.I), r"\1 [name]"),
]


def scrub(text: str) -> str:
    for rx, sub in SCRUB:
        text = rx.sub(sub, text)
    return text.strip()


def _hits(text: str, words: list[str]) -> bool:
    low = f" {text.lower()} "
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in words)


class Insights:
    def __init__(self, room: str, brain: str, model: str):
        self.t0 = time.time()
        self.room, self.brain, self.model = room, brain, model
        self.intents: dict[str, int] = {}
        self.entities: dict[str, set[str]] = {k: set() for k in CFG["entities"]}
        self.actions: list[dict] = []
        self.unanswered: list[str] = []
        self.handoffs: list[dict] = []
        self.latencies: list[int] = []  # ms, end of guest speech -> Kai starts speaking
        self.user_turns = 0
        self.agent_turns = 0
        self.last_question = ""
        self.last_intent = ""
        self.pages: list[dict] = []

    def _at(self) -> float:
        return round(time.time() - self.t0, 1)

    def _entities(self, text: str):
        low = text.lower()
        for kind, table in CFG["entities"].items():
            for key, name in table.items():
                if key in low:
                    self.entities[kind].add(name)

    def user_said(self, text: str):
        if not text.strip():
            return
        self.user_turns += 1
        self.last_question = text
        for intent, words in CFG["intents"].items():
            if _hits(text, words):
                self.intents[intent] = self.intents.get(intent, 0) + 1
                self.last_intent = intent
        self._entities(text)

    def agent_said(self, text: str):
        if not text.strip():
            return
        self.agent_turns += 1
        self._entities(text)
        if _hits(text, CFG["unanswered"]) and self.last_question:
            q = scrub(self.last_question)
            if q not in self.unanswered:
                self.unanswered.append(q)
        for reason, words in CFG["handoffs"].items():
            if _hits(text, words) and not any(
                h["reason"] == reason and h["intent"] == self.last_intent for h in self.handoffs
            ):
                self.handoffs.append({"reason": reason, "intent": self.last_intent or "general", "at_s": self._at()})

    def action(self, tool: str, args: dict, ok: bool, ms: float, error: str = ""):
        a = {"tool": tool, "args": {k: v for k, v in args.items() if v not in (None, "")}, "ok": ok, "ms": round(ms)}
        if error:
            a["error"] = error[:160]
        a["at_s"] = self._at()
        self.actions.append(a)
        if tool == "navigate" and not ok and "isn't allowed" in error:
            self.handoffs.append(
                {"reason": "blocked_page", "intent": self.last_intent or "general", "at_s": self._at()}
            )

    def latency(self, ms: float):
        if 0 < ms < 30000:
            self.latencies.append(round(ms))

    def summary(self, pages: list[dict] | None = None) -> dict:
        lat = sorted(self.latencies)
        pct = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))] if lat else None  # noqa: E731
        return {
            "schema": "kai.session_summary.v1",
            "session": self.room,
            "brain": self.brain,
            "model": self.model,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.t0)),
            "duration_s": self._at(),
            "turns": {"guest": self.user_turns, "kai": self.agent_turns},
            "intents": dict(sorted(self.intents.items(), key=lambda kv: -kv[1])),
            "entities": {k: sorted(v) for k, v in self.entities.items()},
            "pages_visited": [
                {"path": p["path"], "title": p.get("title", ""), "at_s": round(p["t"] - self.t0, 1)}
                for p in (pages or [])
                if p["t"] >= self.t0 - 5
            ],
            "actions": self.actions,
            "unanswered_questions": self.unanswered,
            "handoffs": self.handoffs,
            "latency_ms": {
                "turns": len(lat),
                "p50": round(statistics.median(lat)) if lat else None,
                "p90": pct(0.9),
                "max": lat[-1] if lat else None,
            },
            "personal_data": "none collected (no names, contact details, account or payment data)",
        }
