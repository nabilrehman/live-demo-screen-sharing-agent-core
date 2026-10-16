"""Who has the floor during an in-browser test call (ported from version B, faan/livecore.py FloorControl).

FAAN: normal. OFFERED: the demoed agent's call just went live in the shared browser; Kai is silent while it greets.
DEMO_APP: Kai said one handover line and is muted (no input to the realtime model); the voice bridge carries the customer's
voice to the page's microphone, and the page's audio comes back as the 'demo-app-audio' track. A DemoCallListener
(faan/demolistener.py) transcribes both sides silently and wakes on "Kai, end the call": FloorControl hangs up the test call,
unmutes Kai and asks for a short debrief.

Turns is the small stand-in for B's TurnManager: the only place that makes Kai speak on its own (generate_reply), held while
the demoed agent has the floor so Kai never talks over it.
"""
import asyncio, os, re, time

NOTE = "(Note from the demo system, not the customer: "


def say_verbatim(session, line: str):
    """Make the realtime model say one exact line. Grok via LiveKit Inference often ignores per-response instructions and
    answers the conversation instead (the debrief came out as "Connecting you now."), so the line also goes in as a
    conversation item, which it does follow. Callers must not treat NOTE items as customer speech."""
    session.generate_reply(user_input=f'{NOTE}say exactly this to the customer now, word for word, and nothing else: "{line}")',
                           instructions=f'Say exactly this, word for word, and nothing else: "{line}"')


class Turns:
    """At most one pending spoken intent per kind; fires when Kai is listening and the customer isn't speaking, never while held."""
    PRIORITY = {"answer": 0, "task": 1}
    EXPIRE_S = 60.0

    def __init__(self, session, trace):
        self.s, self.tr = session, trace
        self.held = False
        self.intents: dict[str, tuple[float, str]] = {}
        self.user_speech_end = self.agent_speech_end = 0.0
        self.idle_nudges = 0
        self._task = asyncio.create_task(self._loop())

    def request(self, kind: str, text: str):
        self.intents[kind] = (time.perf_counter(), text)
        self.tr("intent", what=kind, held=self.held, alive=not self._task.done())

    def clear(self, *kinds):
        for k in (kinds or list(self.intents)): self.intents.pop(k, None)

    async def _loop(self):
        while True:
            try: await self._tick()
            except asyncio.CancelledError: raise
            except Exception as e: self.tr("turns_error", error=f"{type(e).__name__}: {e}"[:160]); await asyncio.sleep(0.5)

    async def _tick(self):
        if True:
            await asyncio.sleep(0.1)
            if self.held or not self.intents: return
            now = time.perf_counter()
            for k, (t, _) in list(self.intents.items()):
                if now - t > self.EXPIRE_S: self.intents.pop(k, None); self.tr("intent_expired", what=k)
            if not self.intents: return
            if getattr(self.s, "agent_state", "") in ("speaking", "thinking") or getattr(self.s, "user_state", "") == "speaking": return
            k = min(self.intents, key=lambda x: self.PRIORITY.get(x, 5))
            _, text = self.intents.pop(k)
            self.tr("intent_fire", what=k)
            try:
                if text.startswith("SAY:"): say_verbatim(self.s, text[4:])
                else: self.s.generate_reply(instructions=text)
            except Exception as e: self.tr("intent_error", what=k, error=f"{type(e).__name__}: {e}"[:120])
            await asyncio.sleep(1.0)


class FloorControl:
    FAAN, OFFERED, DEMO_APP = "faan", "offered", "demo_app"
    CONSENT_RX = re.compile(r"^\W*(?:yes|yeah|yep|yup|sure|absolutely|of course|definitely|go ahead|let'?s (?:do it|try it)|please do|why not)\b", re.I)
    DECLINE_RX = re.compile(r"^\W*(?:no|nope|nah|not now|not really|no thanks|you (?:do|go|talk)|i'?ll (?:just )?(?:watch|listen))\b", re.I)
    APP_ADDRESS_RX = re.compile(r"^\W*(?:(?:hi|hello|hey)\b.{0,30})?(?:can|do) you hear me\b|^\W*(?:hi|hello|hey)(?: there)?\W*$", re.I)
    AUTO = os.getenv("FLOOR_AUTO_HANDOVER", "1") == "1"

    def __init__(self, session, tm: Turns, trace, max_hold_s: float = 300, release_debounce_s: float = 1.5,
                 offer_timeout_s: float = 45):
        self.s, self.tm, self.tr = session, tm, trace
        self.state = self.FAAN
        self.app_live = False
        self.consented = False
        self.max_hold_s, self.debounce, self.offer_timeout_s = max_hold_s, release_debounce_s, offer_timeout_s
        self._since = 0.0
        self._live_t = 0.0
        self._pending: asyncio.Task | None = None
        self._listeners: list = []
        self._live_cbs: list = []
        self.listener = None       # DemoCallListener
        self.end_app_call = None   # async () -> bool: hang up the app's call on screen
        self.app_speaking = lambda: False
        self._muted = False
        self.publish = None        # cb(state)
        self.compose = None        # async (transcript, opener) -> debrief line (1-2 short sentences)
        self._watch = asyncio.create_task(self._watchdog())

    def on_floor(self, cb):
        """cb(app_has_floor: bool) on every change, e.g. the voice router's forwarding gate."""
        self._listeners.append(cb)

    def on_live(self, cb):
        """cb() when a test call goes live (e.g. the planner finishes a 'start a test call' task)."""
        self._live_cbs.append(cb)

    def _set(self, state: str, **kw):
        self.state = state; self.tr("floor_change", to=state, **kw)
        if self.publish:   # e.g. the 'faan.floor' participant attribute, for the join page and the spoken test harness
            try: self.publish(state)
            except Exception: pass
        for cb in self._listeners:
            try: cb(state == self.DEMO_APP)
            except Exception as e: self.tr("floor_listener_error", error=type(e).__name__)

    @property
    def busy(self) -> bool:
        """Screen tools (act / do_task) are blocked: a test call is live or about to be handed over."""
        return self.state != self.FAAN

    @property
    def app_has_floor(self) -> bool:
        return self.state == self.DEMO_APP

    # ---- Kai's realtime input (Grok via LiveKit Inference): muting = stop feeding it the customer's audio
    def _mute(self, on: bool):
        if on == self._muted: return
        self._muted = on
        try: self.s.input.set_audio_enabled(not on)
        except Exception as e: self.tr("faan_input_error", error=f"{type(e).__name__}: {e}"[:120])
        if on:
            try: self.s.clear_user_turn()   # drop any half-heard customer turn so the model doesn't answer it later
            except Exception: pass
        self.tr("faan_input", enabled=not on)

    async def _forget_interrupted(self, delay: float = 0.0):
        """Grok (LiveKit Inference realtime) continues an interrupted sentence on its next reply, whatever the instructions
        ("Silent now while it connects." came back as the debrief). Drop Kai's last message from the model's context if it
        was cut off, so the next reply starts fresh."""
        if delay: await asyncio.sleep(delay)
        try:
            ag = self.s.current_agent; ctx = ag.chat_ctx.copy()
            for it in reversed(ctx.items):
                if getattr(it, "type", "") == "message" and it.role == "assistant":
                    if not it.interrupted: return
                    ctx.items.remove(it); await ag.update_chat_ctx(ctx)
                    self.tr("forgot_interrupted", text=(it.text_content or "")[:80]); return
        except Exception as e:
            self.tr("forget_error", error=f"{type(e).__name__}: {e}"[:120])

    def on_customer_line(self, text: str):
        """Final transcripts while Kai can hear them (only matters with FLOOR_AUTO_HANDOVER=0: a yes/no to the offer)."""
        t = (text or "").strip()
        if not t or self.state == self.DEMO_APP or t.startswith(NOTE): return
        explicit = bool(re.search(r"\b(?:let me|i(?:'d| would)? (?:like|want|wanna) to|can i)\s+(?:talk|speak|try|test|chat)\b|"
                                  r"\b(?:talk|speak) to (?:it|the agent) (?:myself|directly)\b", t, re.I))
        if self.state == self.OFFERED and not self.AUTO and self.DECLINE_RX.search(t):
            self.tm.clear("answer"); self._set(self.FAAN, why="declined"); self.tm.held = False; return
        short_yes = self.CONSENT_RX.search(t) and len(t.split()) <= 6
        if (self.state == self.OFFERED and not self.AUTO and (short_yes or self.APP_ADDRESS_RX.search(t))) or (explicit and self.app_live and self.state == self.FAAN):
            self.tr("floor_consent", how="transcript", text=t[:80])
            asyncio.create_task(self._hand_over(announce=True))
        elif explicit and not self.app_live:
            self.consented = True; self.tr("floor_consent_pending", how="transcript")

    async def _release_then_offer(self):
        try: await self._offer_after_greeting()
        finally:
            if self.state != self.DEMO_APP: self.tm.held = False

    async def _offer_after_greeting(self):
        """Don't talk over the demoed agent's greeting: wait until its audio has been quiet ~1.2 s (max ~12 s)."""
        quiet_since, t0, heard = None, time.perf_counter(), False
        while time.perf_counter() - t0 < 12 and self.state == self.OFFERED and self.app_live:
            speaking = bool(self.app_speaking())
            if speaking: quiet_since, heard = None, True
            elif quiet_since is None: quiet_since = time.perf_counter()
            elif time.perf_counter() - quiet_since > 1.2 and time.perf_counter() - t0 > 2.0 and (heard or time.perf_counter() - t0 > 6): break
            await asyncio.sleep(0.1)
        self.tr("app_greeting_done", waited_s=round(time.perf_counter() - t0, 1), heard=heard)
        if self.state != self.OFFERED: return
        if self.AUTO:   # demo flow: no question, Kai says it's muting and hands over
            await self._hand_over(announce=True)
        else:
            self.tm.held = False; self.offer(speak=True)

    def offer(self, speak: bool = True):
        if self.state == self.FAAN:
            self._set(self.OFFERED); self._offered_t = time.perf_counter()
        if not speak or self.state != self.OFFERED: return
        self.tm.request("answer", "A test call with the agent is live on screen. Ask them in one short sentence whether they'd like to "
                                  "talk to it themselves, and say you'll mute yourself if so. Then wait.")

    def on_app_audio(self, active: bool):
        """Edge from the voice bridge (the page's mic went live / ended)."""
        was = self.app_live
        self.app_live = active
        if self._pending and not self._pending.done(): self._pending.cancel()
        if active and not was:
            self._live_t = time.perf_counter()
            for cb in self._live_cbs:
                try: cb()
                except Exception as e: self.tr("floor_live_cb_error", error=type(e).__name__)
        if active and self.state == self.DEMO_APP:
            return
        if active and self.consented:
            self._pending = asyncio.create_task(self._hand_over(announce=True))
        elif active:
            self.offer(speak=False)                  # tools blocked from the first moment of the app's call
            self.tm.clear(); self.tm.held = True     # let the app's agent greet: nobody from our side talks over it
            if getattr(self.s, "agent_state", "") == "speaking":   # Kai mid-sentence as the call connects: stop, don't talk over the greeting
                try: self.s.interrupt(); self.tr("faan_interrupted", why="test call live")
                except Exception: pass
                asyncio.create_task(self._forget_interrupted(0.8))
            if self.AUTO: self._mute(True)           # it's handed over in a moment anyway: don't let the model answer the greeting wait
            if self.listener: self.listener.start()  # from the first moment, so the debrief knows the test agent's greeting too
            self._pending = asyncio.create_task(self._release_then_offer())
        elif self.state in (self.OFFERED, self.DEMO_APP):
            self._pending = asyncio.create_task(self._to_faan("app call ended", self.debounce))

    async def accept(self) -> str:
        if self.state == self.DEMO_APP: return "They already have the floor."
        if not self.app_live:
            self.consented = True; self.tr("floor_consent_pending")
            return "Noted. Start the test call now; you'll hand over automatically as soon as it's live."
        return await self._hand_over(announce=False)

    async def _hand_over(self, announce: bool) -> str:
        self.consented = False
        self._since = time.perf_counter()
        self.tm.clear(); self.tm.held = True
        self._set(self.DEMO_APP, after_live_s=round(self._since - self._live_t, 1))
        if self.listener: self.listener.start()   # Kai keeps listening (silently) to the test call
        if announce:
            say_verbatim(self.s, "The call's live. I'll mute myself so you can talk to it directly; just say 'Kai' when you're done.")
            self.tr("handover_line")
        async def mute_after_line():
            await asyncio.sleep(0.6)
            for _ in range(150):   # let the hand-off sentence finish playing (it doesn't need input), then stay muted
                await asyncio.sleep(0.1)
                if getattr(self.s, "agent_state", "") not in ("speaking", "thinking"): break
            if self.state == self.DEMO_APP: self._mute(True)
        asyncio.create_task(mute_after_line())
        return "Handed over. Say nothing more until they call you back."

    async def wake(self, text: str):
        """The customer called Kai during the test call ("Kai, end the call"): hang up the app's call and take the floor back."""
        if self.state not in (self.DEMO_APP, self.OFFERED): return
        self.tr("floor_wake", said=text[:120])
        ended = False
        if self.end_app_call:
            try: ended = bool(await self.end_app_call())
            except Exception as e: self.tr("floor_end_call_error", error=type(e).__name__)
        self.tr("test_call_ended", by="wake", ok=ended)
        await self._to_faan("customer called Kai" + ("" if ended else " (app call still up)"))

    async def _to_faan(self, why: str, delay: float = 0.0):
        if delay: await asyncio.sleep(delay)   # debounce: a track flapping during the app's own setup isn't the end of the call
        was = self.state
        self.consented = False
        if was == self.FAAN: return
        self._set(self.FAAN, why=why, held_s=round(time.perf_counter() - self._since, 1) if was == self.DEMO_APP else 0)
        self._mute(False)
        self.tm.clear()   # anything queued during the call is stale now
        await self._forget_interrupted()
        heard = ""
        if self.listener and self.listener.active:
            await self.listener.stop(); heard = self.listener.transcript()
        if was == self.DEMO_APP or "Customer:" in heard:
            # Grok follows a verbatim line reliably, but with open instructions it tends to resume whatever it was saying
            # before the call: a small text model writes the debrief, Kai says it word for word
            opener = "Okay, I've hung up." if "called Kai" in why else "Okay, that call has ended."
            line = f"{opener} How did that feel? What would you like to change?"
            if heard and self.compose:
                try: line = await asyncio.wait_for(self.compose(heard, opener), 4.0) or line
                except Exception as e: self.tr("debrief_compose_error", error=f"{type(e).__name__}: {e}"[:120])
            self.tr("debrief", line=line)
            self.tm.request("answer", "SAY:" + line)
        now = time.perf_counter()
        self.tm.user_speech_end = self.tm.agent_speech_end = now; self.tm.idle_nudges = 0
        self.tm.held = False

    async def _watchdog(self):
        while True:
            await asyncio.sleep(1)
            if self.state == self.OFFERED and not self.AUTO and time.perf_counter() - getattr(self, "_offered_t", 0) > self.offer_timeout_s:
                self.tm.clear("answer"); self._set(self.FAAN, why="offer timed out"); self._mute(False); self.tm.held = False
            if self.state == self.DEMO_APP and time.perf_counter() - self._since > self.max_hold_s:
                if self.end_app_call:
                    try: await self.end_app_call()
                    except Exception: pass
                await self._to_faan("max hold reached")
