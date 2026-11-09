"""Voice recording for demo replays (host-independent: works the same on the build sandbox and on LiveKit Cloud agents).

The agent records the call itself with the Agents SDK RecorderIO (AgentSession.start(record=...)): one stereo OGG/Opus
file, visitor on the left channel, agent on the right, placed on the agent's wall clock (t0 = recording start, epoch s).
No Egress, no extra LiveKit minutes, no storage credentials in the agent. When the call ends the file is POSTed to the
product backend, which stores it next to the DOM replays and serves it to the replay player:

  POST {VOICE_REC_URL}<room>?slug=<slug>&t0=<epoch s>&dur=<s>    body: audio/ogg
  header X-LK-Voice-Sig: hex HMAC-SHA256(LIVEKIT_API_SECRET, "<room>:<t0>")   (the secret the worker already has)

Env: VOICE_REC=0 turns it off; VOICE_REC_URL (default http://127.0.0.1:8080/api/p/voice/ = the sandbox controller; on
LiveKit Cloud set it to the backend's public URL). If the upload fails the file is kept in sessions/<room>/voice.ogg.
"""
import hashlib
import hmac
import logging
import os
import shutil
import urllib.parse

import aiohttp

log = logging.getLogger("voice_rec")
ON = os.getenv("VOICE_REC", "1") != "0"
URL = os.getenv("VOICE_REC_URL", "http://127.0.0.1:8080/api/p/voice/")


def record_options(ctx):
    """For session.start(record=...): always record audio locally; leave traces/logs/transcript to the project setting."""
    if not ON:
        return ctx.job.enable_recording
    rec = bool(ctx.job.enable_recording)
    return {"audio": True, "traces": rec, "logs": rec, "transcript": rec}


async def upload(ctx, session, slug: str, keep_dir: str | None = None) -> None:
    """Call from a shutdown callback: closes the session (finishing the OGG) and ships it to the backend."""
    if not ON:
        return
    try:
        await session.aclose()
    except Exception as e:  # already closed / closing
        log.debug("session close: %s", e)
    try:
        rep = ctx.make_session_report(session)
        path, t0 = rep.audio_recording_path, rep.audio_recording_started_at
    except Exception as e:
        log.warning("voice rec: no session report: %s", e)
        return
    if not path or not t0 or not os.path.exists(path) or os.path.getsize(path) < 1000:
        log.info("voice rec: nothing recorded for %s", ctx.room.name)
        return
    room = ctx.room.name
    dur = max(0.0, (rep.timestamp or t0) - t0)
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    t0s = f"{t0:.3f}"
    sig = hmac.new(secret.encode(), f"{room}:{t0s}".encode(), hashlib.sha256).hexdigest()
    q = urllib.parse.urlencode({"slug": slug, "t0": t0s, "dur": f"{dur:.1f}"})
    try:
        with open(path, "rb") as f:
            data = f.read()
        async with aiohttp.ClientSession() as http:
            async with http.post(URL + urllib.parse.quote(room) + "?" + q, data=data,
                                 headers={"Content-Type": "audio/ogg", "X-LK-Voice-Sig": sig},
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    log.info("voice rec: uploaded %s (%d KB, %.0fs)", room, len(data) // 1024, dur)
                    return
                log.warning("voice rec: upload %s -> HTTP %s %s", room, r.status, (await r.text())[:200])
    except Exception as e:
        log.warning("voice rec: upload failed for %s: %s", room, e)
    if keep_dir:  # keep it for a manual retry
        try:
            os.makedirs(keep_dir, exist_ok=True)
            shutil.copy(path, os.path.join(keep_dir, "voice.ogg"))
            with open(os.path.join(keep_dir, "voice.json"), "w") as f:
                f.write(f'{{"room": "{room}", "slug": "{slug}", "t0": {t0s}, "dur": {dur:.1f}}}')
        except OSError:
            pass
