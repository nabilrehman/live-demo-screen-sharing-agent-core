"""While the customer talks to an app being demoed (voice bridge, DEMO_APP floor), Faan's realtime model is muted so it can't
blurt into their call. This listener keeps Faan *aware* without speaking:

- it transcribes both sides of the test call: the customer's mic (the frames the bridge forwards) and the app's voice (the
  frames the bridge captures from the page), with a separate streaming STT (LiveKit Inference), app-agnostic
- it spots the wake phrase ("Kai, end the call", "okay Kai, back to you", "Kai, I'm done"), so FloorControl can take the floor
  back, end the app's call and debrief
- it keeps the transcript, so the hand-back can explain what happened in the test call
"""
import asyncio, re, time
from typing import Callable

from livekit import rtc

SR = 48000
NAMES = r"(?:kai|kye|ky|chi|guy|kite|k\.?i\.?)"   # how STT tends to hear "Kai"
WAKE = re.compile(rf"\b{NAMES}\b[ ,.!?-]*(?:can you |could you |please |let'?s |okay |ok )*"
                  r"(?:end|stop|hang up|finish|wrap|come back|back to you|take over|i'?m done|we'?re done|that'?s (?:it|enough|good))", re.I)
BACK = re.compile(r"\b(?:back to you|over to you|(?:end|and) (?:the|this) (?:call|test)|hang up|i'?m done (?:with|testing))\b", re.I)   # STT: "Kai." / "And" / "the call."
HI_END = re.compile(r"\b(?:hi|hey)\b[ ,.!?-]*(?:can you |could you |please )*(?:end|hang up) (?:the|this) call\b", re.I)   # "Kai" heard as "Hi"


class DemoCallListener:
    def __init__(self, log: Callable, on_wake: Callable[[str], None], model: str = "deepgram/nova-3", language: str = "en"):
        self.log, self.on_wake = log, on_wake
        self.model, self.language = model, language
        self.lines: list[tuple[float, str, str]] = []      # (t, who, text)
        self.active = False
        self._streams: dict[str, object] = {}
        self._tasks: list[asyncio.Task] = []
        self._woke = False

    # ---- lifecycle (FloorControl drives it)
    def start(self):
        if self.active: return
        from livekit.agents import inference
        self.active, self._woke, self.lines = True, False, []
        for who in ("customer", "app"):
            try:
                st = inference.STT(model=self.model, language=self.language).stream()
                self._streams[who] = st
                self._tasks.append(asyncio.create_task(self._read(who, st)))
            except Exception as e:
                self.log("demo_listener_error", who=who, error=f"{type(e).__name__}: {e}"[:160])
        self.log("demo_listener", state="started")

    async def stop(self):
        if not self.active: return
        self.active = False
        for st in self._streams.values():
            try: st.end_input()
            except Exception: pass
        await asyncio.sleep(0.8)   # let final transcripts land
        for t in self._tasks: t.cancel()
        for st in self._streams.values():
            try: await st.aclose()
            except Exception: pass
        self._streams.clear(); self._tasks.clear()
        self.log("demo_listener", state="stopped", lines=len(self.lines))

    # ---- audio in (int16 48 kHz mono PCM from the bridge)
    def push_customer(self, pcm: bytes): self._push("customer", pcm)
    def push_app(self, pcm: bytes): self._push("app", pcm)

    def _push(self, who: str, pcm: bytes):
        st = self._streams.get(who)
        if not (self.active and st and pcm): return
        n = len(pcm) // 2
        try: st.push_frame(rtc.AudioFrame(pcm, SR, 1, n))
        except Exception: pass

    async def _read(self, who: str, st):
        from livekit.agents import stt
        try:
            async for ev in st:
                if ev.type != stt.SpeechEventType.FINAL_TRANSCRIPT or not ev.alternatives: continue
                text = (ev.alternatives[0].text or "").strip()
                if not text: continue
                self.lines.append((time.time(), who, text))
                self.log("demo_call_line", who=who, text=text[:200])
                # STT often splits "Alright, Kai. Can you please end the call?" into two finals: match over the last few seconds
                recent = " ".join(t for tt, w, t in self.lines if w == "customer" and time.time() - tt < 8)
                if who == "customer" and not self._woke and (WAKE.search(recent) or HI_END.search(recent) or (BACK.search(recent) and re.search(rf"\b{NAMES}\b", recent, re.I))):
                    self._woke = True
                    self.log("demo_wake", text=recent[-120:])
                    try: self.on_wake(recent[-200:])
                    except Exception as e: self.log("demo_listener_error", who="wake", error=type(e).__name__)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log("demo_listener_error", who=who, error=f"{type(e).__name__}: {e}"[:160])

    def transcript(self, max_chars: int = 2500) -> str:
        """The test call as 'Customer:/Agent:' lines (most recent kept if long)."""
        out = [f"{'Customer' if w == 'customer' else 'Their agent'}: {t}" for _, w, t in self.lines]
        s = "\n".join(out)
        return s[-max_chars:]
