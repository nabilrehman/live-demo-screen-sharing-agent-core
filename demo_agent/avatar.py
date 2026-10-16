"""Optional video avatar for Faan (Kai). Off unless AVATAR_PROVIDER is set. See docs/AVATAR.md.

How it fits: an avatar is a second participant (kind AGENT, attribute lk.publish_on_behalf = our identity). AvatarSession.start()
re-points the AgentSession's audio output (Gemini Live's 24 kHz speech) at that worker over a data stream. The worker publishes
lip-synced audio and video for the customer. Our screen-share track is untouched.

Order (the same as the demo-portal demos hospital-receptionist and olivia, LiveKit-Field/demo-portal):
    av = await start_avatar(session, room, log)          # 1. BEFORE session.start(): the avatar owns the audio tail
    await session.start(..., room_options=room_io.RoomOptions(audio_output=av is None))   # 2. avatar = only speech publisher
    await wait_avatar(av, log)                           # 3. AFTER session.start(): gate the first line on the face being live
start_avatar never raises. It returns None (voice-only) when the avatar is disabled, misconfigured, not installed, or the
provider/gateway refuses it (e.g. 403 "Inference Avatar is not enabled for this project").

Env:
  AVATAR_PROVIDER       off (default) | livekit | anam | bey | tavus    ("livekit" = LemonSlice via LiveKit Inference: no provider key,
                        billed to the LiveKit project, needs the project's Inference avatar feature)
  livekit: exactly ONE of LEMONSLICE_IMAGE_URL (public portrait, image/*, cropped to 368x560) or LEMONSLICE_AGENT_ID (a catalog id
           in LiveKit's LemonSlice account, not your own dashboard's). Optional LEMONSLICE_PROMPT, LEMONSLICE_IDLE_PROMPT,
           LEMONSLICE_IDLE_TIMEOUT (seconds, default 600: must outlast a FloorControl hand-over, max_hold_s=300, when the avatar gets no audio)
  anam:    ANAM_API_KEY, ANAM_AVATAR_ID. Optional ANAM_AVATAR_MODEL (default ANAM_DEFAULT_MODEL below; 'default' = let Anam
           pick), ANAM_VIDEO_W + ANAM_VIDEO_H (both or neither; default = native size), ANAM_API_URL, ANAM_AI_DISCLOSURE=1
  bey:     BEY_API_KEY, BEY_AVATAR_ID (required here: the plugin's default face is male)
  tavus:   TAVUS_API_KEY, TAVUS_REPLICA_ID, TAVUS_PERSONA_ID
  AVATAR_NAME           persona name for anam (default "Kai")
  AVATAR_JOIN_TIMEOUT_S wait_avatar's timeout (default 30, the SDK default)
  LIVEKIT_PUBLIC_URL    public wss:// URL for providers that dial in (bey needs it on LiveKit Cloud; Inference never does)
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable

OFF = {"", "off", "none", "0", "false", "no"}

# Speaking prompt and idle prompt, after olivia's presenter.json and kitt-tell's kit_agent.py, tuned for a screen-share presenter.
DEFAULT_PROMPT = ("Warm and engaged. Use natural, easy head movement while talking, as if presenting a product demo to a small "
                  "group, glancing now and then toward the shared screen.")
DEFAULT_IDLE_PROMPT = "Attentive and relaxed, listening with a friendly expression."

# provider -> (required env vars, pip package)
PROVIDERS: dict[str, tuple[tuple[str, ...], str]] = {
    "livekit": ((), "livekit-agents (built in)"),
    "anam": (("ANAM_API_KEY", "ANAM_AVATAR_ID"), "livekit-plugins-anam==1.8.7"),
    "bey": (("BEY_API_KEY", "BEY_AVATAR_ID"), "livekit-plugins-bey==1.8.7"),
    "tavus": (("TAVUS_API_KEY", "TAVUS_REPLICA_ID", "TAVUS_PERSONA_ID"), "livekit-plugins-tavus==1.8.7"),
}
DIALS_IN = {"anam", "bey", "tavus"}   # join the room from their own cloud; Inference is provisioned inside LiveKit and takes no URL


def _env(k: str) -> str:
    return (os.getenv(k) or "").strip()


def provider() -> str:
    p = _env("AVATAR_PROVIDER").lower()
    return "" if p in OFF else p


def missing(p: str) -> list[str]:
    """What stops provider p from working (empty = configured). Never reveals values."""
    if p not in PROVIDERS:
        return [f"unknown AVATAR_PROVIDER {p!r} (known: {', '.join(PROVIDERS)})"]
    out = [f"{k} not set" for k in PROVIDERS[p][0] if not _env(k)]
    if p == "livekit":   # both demo-portal demos refuse neither / both
        img, aid = _env("LEMONSLICE_IMAGE_URL"), _env("LEMONSLICE_AGENT_ID")
        if img and aid:
            out.append("set LEMONSLICE_IMAGE_URL or LEMONSLICE_AGENT_ID, not both")
        elif not img and not aid:
            out.append("LemonSlice has no stock faces: set LEMONSLICE_IMAGE_URL (public portrait) or LEMONSLICE_AGENT_ID")
    return out


def public_url() -> str | None:
    """A LiveKit URL an outside provider can dial. In a LiveKit Cloud container LIVEKIT_URL is cluster-internal, so set
    LIVEKIT_PUBLIC_URL as a secret there (teammates hit this with bey in demo-portal)."""
    u = _env("LIVEKIT_PUBLIC_URL")
    if u:
        return u
    u = _env("LIVEKIT_URL")
    if not u.startswith(("ws://", "wss://")):
        return None
    host = u.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()
    if host in {"localhost", "127.0.0.1"} or host.endswith((".local", ".internal", ".svc")):
        return None
    return u


def _build_livekit() -> Any:
    """LemonSlice through LiveKit Inference. Same constructor as demo-portal: a catalog id travels in the model string
    (hospital-receptionist), an image URL plus prompt/idle_timeout travel in LemonSliceOptions (hospital-receptionist + olivia)."""
    from livekit.agents import inference
    opts = inference.LemonSliceOptions()
    if img := _env("LEMONSLICE_IMAGE_URL"):
        opts["image_url"] = img
    opts["prompt"] = _env("LEMONSLICE_PROMPT") or DEFAULT_PROMPT
    opts["idle_prompt"] = _env("LEMONSLICE_IDLE_PROMPT") or DEFAULT_IDLE_PROMPT
    opts["idle_timeout"] = int(_env("LEMONSLICE_IDLE_TIMEOUT") or 600)
    aid = _env("LEMONSLICE_AGENT_ID")
    return inference.AvatarSession(f"lemonslice/{aid}" if aid else "lemonslice", extra_kwargs=opts)


# Anam defaults, chosen by measurement (experiments/avatar_bench.py, 2026-10-15; D = agent forwards a turn's first audio
# frame -> that audio's onset at a listener, n=19 turns each): unset 0.665 s median / 0.761 p90 (Leo's default IS cara-4, same
# 1152x768 output), cara-4 0.714 / 0.804 (vs unset: p=0.08, noise), cara-4-latest 0.761 / 0.822 (slower, p=0.03), cara-3
# 1.549 / 1.917 (2x slower, 720x480). Pinned to cara-4 so the persona can't silently drift to a slower model. Video size is not
# a lever: Anam only accepts the native sizes (cara-4 1152x768 or 768x1152, cara-3 720x480; 640x360 / 512x512 -> HTTP 400).
# Env overrides; "default" for ANAM_AVATAR_MODEL or ANAM_VIDEO_W/H means "send nothing, let Anam pick".
ANAM_DEFAULT_MODEL = "cara-4"
ANAM_DEFAULT_VIDEO = (0, 0)   # (0, 0) = the model's native size


def anam_model() -> str:
    m = _env("ANAM_AVATAR_MODEL") or ANAM_DEFAULT_MODEL
    return "" if m.lower() in OFF | {"default"} else m


def anam_video_size() -> tuple[int, int]:
    w, h = _env("ANAM_VIDEO_W"), _env("ANAM_VIDEO_H")
    if w.lower() in OFF | {"default"} or h.lower() in OFF | {"default"}:
        return 0, 0
    if w and h:
        return int(w), int(h)
    return ANAM_DEFAULT_VIDEO


def _build(p: str) -> Any:
    if p == "livekit":
        return _build_livekit()
    if p == "anam":
        from livekit.plugins import anam
        pc: dict[str, Any] = {"name": os.getenv("AVATAR_NAME", "Kai"), "avatarId": _env("ANAM_AVATAR_ID")}
        model = anam_model()
        if model:
            pc["avatarModel"] = model
        so: dict[str, Any] = {}
        w, h = anam_video_size()
        if w and h:
            so.update(video_width=w, video_height=h)
        if os.getenv("ANAM_AI_DISCLOSURE") == "1":
            so["show_ai_avatar_disclosure"] = True
        kw: dict[str, Any] = {"persona_config": anam.PersonaConfig(**pc)}
        if so:
            kw["session_options"] = anam.SessionOptions(**so)
        if _env("ANAM_API_URL"):   # the plugin reads it too; explicit so a blank value can't override the default
            kw["api_url"] = _env("ANAM_API_URL")
        return anam.AvatarSession(**kw)
    if p == "bey":
        from livekit.plugins import bey
        return bey.AvatarSession(avatar_id=_env("BEY_AVATAR_ID"))
    if p == "tavus":
        from livekit.plugins import tavus
        return tavus.AvatarSession(replica_id=_env("TAVUS_REPLICA_ID"), persona_id=_env("TAVUS_PERSONA_ID"))
    raise ValueError(p)


def _emit(log: Callable | None) -> Callable:
    """Accept SessionLog.event(name, **kw) or a logging.Logger."""
    if log is None:
        return lambda *a, **k: None
    if hasattr(log, "warning") and hasattr(log, "info"):
        return lambda ev, **kw: log.info("%s %s", ev, kw)
    return log


def _log_metrics(av: Any, ev: Callable, p: str) -> None:
    """AvatarMetrics -> avatar_metrics events: one join event (session start -> avatar video published) and one per agent
    turn (playback_latency = first audio frame forwarded to the avatar -> avatar reports playback started)."""
    def on_metrics(m: Any) -> None:
        try:
            kw: dict[str, Any] = {"provider": p}
            if m.avatar_joined_time and m.session_started_time:
                kw["join_s"] = round(m.avatar_joined_time - m.session_started_time, 3)
            else:
                kw["playback_latency_s"] = round(m.playback_latency, 3)
            ev("avatar_metrics", **kw)
        except Exception:
            pass
    try:
        av.on("metrics_collected", on_metrics)
    except Exception:
        pass


async def start_avatar(session: Any, room: Any, log: Callable | None = None) -> object | None:
    """Step 1, BEFORE session.start(): build and start the configured avatar. Returns the AvatarSession or None. Never raises.
    `avatar` is only returned when start() succeeded, because it decides who publishes the audio (hospital-receptionist)."""
    ev = _emit(log)
    p = provider()
    if not p:
        return None
    try:
        problems = missing(p)
        if problems:
            ev("avatar_off", provider=p, why="; ".join(problems))
            return None
        try:
            av = _build(p)
        except ImportError:
            ev("avatar_off", provider=p, why=f"plugin not installed: uv pip install --python .venv/bin/python '{PROVIDERS[p][1]}'")
            return None
        kw: dict[str, Any] = {}
        if p in DIALS_IN and (u := public_url()):
            kw["livekit_url"] = u
        t0 = time.perf_counter()
        await av.start(session, room=room, **kw)
        av._faan_t0 = t0   # for wait_avatar's join time
        _log_metrics(av, ev, p)
        ev("avatar_started", provider=p, identity=getattr(av, "avatar_identity", "?"), start_s=round(time.perf_counter() - t0, 2))
        if p == "anam" and getattr(av, "session_id", None):
            asyncio.create_task(_anam_limit(av.session_id, ev))   # surface the plan's hard cap in the session log
        return av
    except Exception as e:   # gateway 403 not_enabled, provider outage, bad key, concurrency limit: lose the face, keep the call
        ev("avatar_off", provider=p, why=f"{type(e).__name__}: {str(e)[:300]}")
        try:   # a start() that failed after re-pointing the audio must not leave Kai talking into nothing
            if type(session.output.audio).__name__ == "DataStreamAudioOutput":
                session.output.audio = None
        except Exception:
            pass
        return None


async def _anam_limit(session_id: str, ev: Callable) -> None:
    """Log Anam's per-session cap (personaConfig.maxSessionLengthSeconds: Free 180, Starter 300, Explorer 600). The avatar leaves
    the room exactly then (exitStatus CLOSED_BY_ENGINE), whatever the call is doing."""
    try:
        import aiohttp
        url = (os.getenv("ANAM_API_URL") or "https://api.anam.ai").rstrip("/") + f"/v1/sessions/{session_id}"
        async with aiohttp.ClientSession() as h, h.get(url, headers={"Authorization": f"Bearer {_env('ANAM_API_KEY')}"},
                                                       timeout=aiohttp.ClientTimeout(total=5)) as r:
            j = await r.json()
        cap = ((j.get("personaConfig") or {}).get("maxSessionLengthSeconds")) if isinstance(j, dict) else None
        if cap: ev("avatar_limit", provider="anam", max_session_s=cap)
    except Exception:
        pass


async def wait_avatar(av: object | None, log: Callable | None = None) -> str:
    """Step 3, AFTER session.start() (only then is the room connected, so only then can wait_for_join wait): gate the first
    line on the avatar's video. Returns "voice-only", "live" or "slow". A slow avatar keeps the session usable: the audio still
    goes to it and the face catches up."""
    ev = _emit(log)
    if av is None:
        return "voice-only"
    try:
        await av.wait_for_join(timeout=float(_env("AVATAR_JOIN_TIMEOUT_S") or 30))
        ev("avatar_joined", provider=getattr(av, "provider", "?"),
           join_s=round(time.perf_counter() - getattr(av, "_faan_t0", time.perf_counter()), 2))
        return "live"
    except (asyncio.TimeoutError, TimeoutError):
        ev("avatar_slow", provider=getattr(av, "provider", "?"))
        return "slow"
    except Exception as e:
        ev("avatar_wait_error", error=f"{type(e).__name__}: {str(e)[:200]}")
        return "slow"


def is_avatar(participant: Any) -> bool:
    """True for an avatar worker (kind AGENT, publishes on behalf of another agent). For filters such as RoomAudioRouter."""
    attrs = getattr(participant, "attributes", None) or {}
    return "lk.publish_on_behalf" in attrs


# ---------------------------------------------------------------------------------------------------------------------------
# Supervision. The avatar is a separate participant that can leave mid-call:
#   * Anam ends every session at the plan's conversation limit (Free 180 s, Starter 300 s, Explorer 600 s) with exitStatus
#     CLOSED_BY_ENGINE (seen 2026-10-15: faan-live-4cf39 and faan-live-97d2a both lost the avatar at exactly 180.28 s);
#   * provider outage, network, or an idle/inactivity rule on their side.
# While the avatar is gone, the AgentSession's audio tail is still a DataStreamAudioOutput aimed at a participant that no longer
# exists: speech goes nowhere, playback_finished never arrives (the agent stays "speaking" until an interruption's 5 s timeout),
# and every barge-in logs "failed to perform clear buffer rpc". The supervisor fixes that:
#   1. on the avatar's participant_disconnected, swap the audio tail to a normal room audio track at once (voice fallback),
#      and force-end a speech that was stuck waiting for the dead avatar;
#   2. optionally start a fresh avatar session in the background (backoff, capped), and swap back to it only after its
#      video is live AND Kai isn't mid-sentence;
#   3. emit avatar_state events for every hop: live, lost, voice_fallback, restarting, restored, gave_up.
# Env: AVATAR_RESTARTS (default 0 = voice fallback only), AVATAR_RESTART_BACKOFF_S (default "2,8,20").
# On Anam Free/Starter a restart only buys another 3/5-minute session and burns plan minutes (and the face visibly re-joins),
# so set AVATAR_RESTARTS=2 only on a plan whose limit is longer than a demo (Growth: 2 h).
# ---------------------------------------------------------------------------------------------------------------------------

class AvatarSupervisor:
    def __init__(self, session: Any, room: Any, av: Any, log: Callable | None = None, *, max_restarts: int | None = None,
                 backoff_s: tuple[float, ...] | None = None):
        self.s, self.room, self.av, self.ev = session, room, av, _emit(log)
        self.identity = getattr(av, "avatar_identity", "")
        self.provider = getattr(av, "provider", "?")
        self.max_restarts = int(_env("AVATAR_RESTARTS") or 0) if max_restarts is None else max_restarts
        self.backoff = backoff_s or tuple(float(x) for x in (_env("AVATAR_RESTART_BACKOFF_S") or "2,8,20").split(","))
        self.restarts = 0
        self.state = "live"
        self.t_live = time.perf_counter()
        self._voice_out: Any = None
        self._task: asyncio.Task | None = None
        self._closed = False
        room.on("participant_disconnected", self._on_left)
        self.ev("avatar_state", state="live", provider=self.provider)

    # ---- public
    @property
    def live(self) -> bool:
        return self.state == "live"

    async def aclose(self):
        self._closed = True
        try: self.room.off("participant_disconnected", self._on_left)
        except Exception: pass
        if self._task and not self._task.done(): self._task.cancel()

    # ---- internals
    def _on_left(self, p: Any):
        if self._closed or getattr(p, "identity", None) != self.identity or self.state != "live": return
        self.state = "lost"
        self.ev("avatar_state", state="lost", provider=self.provider, after_s=round(time.perf_counter() - self.t_live, 1),
                hint="Anam plan conversation limit (Free 180 s / Starter 300 s)" if self.provider == "anam" else "")
        self._task = asyncio.create_task(self._recover())

    async def _voice_fallback(self):
        """Point the session's audio tail at a normal room track. replace_audio_tail keeps RecorderIO and the
        TranscriptSynchronizer (auto-pointer) attached; the proxy clears the dead sink and closes its open segment."""
        if self._voice_out is None:
            from livekit import rtc
            from livekit.agents.voice.room_io._output import _ParticipantAudioOutput   # what RoomIO builds when audio_output=True
            self._voice_out = _ParticipantAudioOutput(
                self.room, sample_rate=24000, num_channels=1, track_name="roomio_audio",
                track_publish_options=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            await self._voice_out.start()
        self.s.output.replace_audio_tail(self._voice_out)
        # a speech that was waiting for the dead avatar's playback_finished would hold the agent in "speaking" (and every
        # TurnManager intent with it) until the 5 s interruption timeout: end it now; the TurnManager re-voices what's pending
        if getattr(self.s, "agent_state", "") == "speaking":
            try: self.s.interrupt(force=True)
            except Exception: pass
        self.state = "voice"
        self.ev("avatar_state", state="voice_fallback", provider=self.provider)

    async def _recover(self):
        try:
            await self._voice_fallback()
        except Exception as e:
            self.ev("avatar_state", state="fallback_error", error=f"{type(e).__name__}: {str(e)[:160]}")
            return
        while not self._closed and self.restarts < self.max_restarts:
            delay = self.backoff[min(self.restarts, len(self.backoff) - 1)]
            self.restarts += 1
            self.ev("avatar_state", state="restarting", attempt=self.restarts, in_s=delay)
            await asyncio.sleep(delay)
            try:
                if await self._restart(): return
            except Exception as e:
                self.ev("avatar_state", state="restart_failed", attempt=self.restarts, error=f"{type(e).__name__}: {str(e)[:160]}")
        if not self._closed:
            self.ev("avatar_state", state="gave_up", restarts=self.restarts)

    async def _restart(self) -> bool:
        p = provider()
        av = _build(p)
        kw: dict[str, Any] = {}
        if p in DIALS_IN and (u := public_url()): kw["livekit_url"] = u
        await av.start(self.s, room=self.room, **kw)     # NB: the plugin re-points the audio tail at the new avatar right away ...
        _log_metrics(av, self.ev, p)
        new_tail = self._tail()
        self.s.output.replace_audio_tail(self._voice_out)   # ... so keep speaking on the room track until its video is live
        await av.wait_for_join(timeout=float(_env("AVATAR_JOIN_TIMEOUT_S") or 30))
        for _ in range(100):                                # never switch outputs mid-sentence
            if getattr(self.s, "agent_state", "") != "speaking": break
            await asyncio.sleep(0.1)
        if new_tail is not None: self.s.output.replace_audio_tail(new_tail)
        self.av, self.identity, self.state, self.t_live = av, av.avatar_identity, "live", time.perf_counter()
        self.ev("avatar_state", state="restored", provider=p, attempt=self.restarts)
        return True

    def _tail(self) -> Any:
        """The current sink at the bottom of the audio chain (the DataStreamAudioOutput the plugin just installed)."""
        cur = self.s.output.audio; last = None
        while cur is not None:
            last = cur; cur = getattr(cur, "next_in_chain", None)
        return last


def supervise(session: Any, room: Any, av: object | None, log: Callable | None = None) -> AvatarSupervisor | None:
    """Call right after wait_avatar(). No-op (None) in voice-only mode."""
    return None if av is None else AvatarSupervisor(session, room, av, log)
