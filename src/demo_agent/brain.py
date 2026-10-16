"""The realtime model that hears, talks and calls tools.

BRAIN=gemini-live (default): Gemini Live through the Google plugin, with a Gemini API key (GOOGLE_API_KEY) or else on
Vertex AI (GOOGLE_CLOUD_PROJECT and Application Default Credentials). It also watches the shared browser as video.
BRAIN=grok: MIN_RT_MODEL through LiveKit Inference. It knows the screen only as text (the screen summary).
"""

import asyncio
import logging
import os
import time

from livekit import rtc
from livekit.agents import AgentSession, inference
from livekit.agents.voice import io as agent_io
from livekit.plugins import silero

log = logging.getLogger("agent.brain")

BRAIN = os.getenv("BRAIN", "gemini-live")
IS_GEMINI = BRAIN == "gemini-live"
MODEL = (
    os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live") if IS_GEMINI else os.getenv("MIN_RT_MODEL", "xai/grok-voice-3.0")
)


def make_session() -> AgentSession:
    if IS_GEMINI:  # ScreenVideoInput paces the frames, so the session's own video sampler is off
        return AgentSession(llm=gemini_live(), vad=silero.VAD.load(), video_sampler=None)
    stall_watchdog()
    return AgentSession(llm=inference_realtime(), vad=silero.VAD.load())


def gemini_live():
    from google.genai import types as gt
    from livekit.plugins import google

    key = os.getenv("GOOGLE_API_KEY")
    if key:  # the Gemini API; Vertex AI doesn't take API keys
        auth = {"api_key": key, "vertexai": False}
    else:
        auth = {
            "vertexai": True,
            "project": os.getenv("GOOGLE_CLOUD_PROJECT"),
            "location": os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        }
    return google.realtime.RealtimeModel(
        model=MODEL,
        voice=os.getenv("GEMINI_VOICE", "Puck"),  # male, to match the avatar
        context_window_compression=gt.ContextWindowCompressionConfig(sliding_window=gt.SlidingWindow()),
        realtime_input_config=gt.RealtimeInputConfig(
            automatic_activity_detection=gt.AutomaticActivityDetection(
                end_of_speech_sensitivity=gt.EndSensitivity.END_SENSITIVITY_LOW,
                start_of_speech_sensitivity=getattr(
                    gt.StartSensitivity, os.getenv("GEMINI_START_SENS", "START_SENSITIVITY_HIGH")
                ),
                silence_duration_ms=int(os.getenv("GEMINI_SILENCE_MS", 700)),
            )
        ),
        session_resumption=gt.SessionResumptionConfig(),
        **auth,
    )


def inference_realtime():
    kw = {}
    if MODEL.startswith(("google/", "openai/")):
        from openai.types.realtime.realtime_audio_input_turn_detection import ServerVad

        kw["turn_detection"] = ServerVad(
            type="server_vad", silence_duration_ms=700, create_response=True, interrupt_response=True
        )
    if os.getenv("MIN_RT_VOICE"):
        kw["voice"] = os.environ["MIN_RT_VOICE"]
    elif MODEL.startswith("openai/"):
        kw["voice"] = "marin"
    elif MODEL.startswith("xai/"):
        kw["voice"] = "rex"  # male, to match the avatar
    return inference.RealtimeModel(model=MODEL, **kw)


def stall_watchdog():
    """Cancel an Inference realtime response whose events stop arriving (it may never send response.done)."""
    try:
        from livekit.agents.inference.realtime.openai import RealtimeSession as S
        from livekit.agents.llm._realtime.openai import _ResponseGeneration
        from openai.types.realtime import ResponseCancelEvent
    except Exception as e:
        log.warning("no stall watchdog: %s", e)
        return
    if getattr(S, "_min_wd", False):
        return
    S._min_wd = True

    def stamp(name, d=None):  # wrap a handler: note when the last event came, and how many output items are open
        orig = getattr(S, name)

        def h(self, ev, *a, **k):
            self._wd_t = time.monotonic()
            if name == "_handle_response_created":
                self._wd_id, self._wd_items = ev.response.id, 0
            if d is not None:
                self._wd_items = max(0, getattr(self, "_wd_items", 0) + d)
            r = orig(self, ev, *a, **k)
            if not getattr(self, "_wd_task", None):
                self._wd_task = asyncio.create_task(watch(self))
            return r

        setattr(S, name, h)

    async def watch(self):
        cancelled = None
        while True:
            await asyncio.sleep(0.5)
            g = self._current_generation
            if not isinstance(g, _ResponseGeneration) or g._done_fut.done():
                cancelled = None
                continue
            idle = time.monotonic() - self._wd_t
            if cancelled == self._wd_id:
                if idle > 1.5:
                    self._close_current_generation()
            elif idle > (2 if g.messages and self._wd_items == 0 else 6):
                log.warning("stalled response %s (%.1fs); cancelling", self._wd_id, idle)
                self.send_event(ResponseCancelEvent(type="response.cancel", response_id=self._wd_id))
                cancelled, self._wd_t = self._wd_id, time.monotonic()

    for n, d in (
        ("_handle_response_created", None),
        ("_handle_response_output_item_added", +1),
        ("_handle_response_output_item_done", -1),
        ("_handle_response_content_part_added", None),
        ("_handle_response_audio_delta", None),
    ):
        try:
            stamp(n, d)
        except AttributeError:
            pass


class ScreenVideoInput(agent_io.VideoInput):
    """The shared browser as Gemini's video input: the latest frame at `fps`, plus one ~350 ms after every screen step
    (kick), so the model sees the result of a click. Counts the frames sent, for the call log."""

    def __init__(self, last: dict, fps: float = 1.0):
        super().__init__(label="screen")
        self._last, self._dt = last, 1.0 / max(fps, 0.1)
        self._kick, self.sent, self.t0 = asyncio.Event(), 0, time.perf_counter()

    def kick(self):
        self._kick.set()

    async def __anext__(self) -> rtc.VideoFrame:
        try:
            await asyncio.wait_for(self._kick.wait(), self._dt)
            self._kick.clear()
            await asyncio.sleep(0.35)  # let the click render first
        except TimeoutError:
            pass
        while self._last["f"] is None:
            await asyncio.sleep(0.2)
        self.sent += 1
        return self._last["f"]

    def stats(self) -> dict:
        dt = time.perf_counter() - self.t0
        return {"frames_to_model": self.sent, "secs": round(dt), "fps": round(self.sent / max(dt, 1), 2)}
