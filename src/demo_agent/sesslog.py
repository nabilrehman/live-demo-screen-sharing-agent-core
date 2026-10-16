"""Per-call log: sessions/<room>/events.jsonl, screen.mp4 (the shared screen), shots/ and summary.md."""

import datetime
import json
import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("agent.sesslog")

# With DEBUG_SHOTS=1 (default) the screen frame is saved for these events (shots/0042_agent.jpg), so speech and screen
# line up when a call is reviewed.
DEBUG_SHOTS = os.getenv("DEBUG_SHOTS", "1") == "1"
SHOT_KINDS = {"user", "agent", "floor_change", "voicebridge_state", "session_start"}
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sessions")


def _ts():
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


class SessionLog:
    def __init__(self, room: str, fps: int = 8):
        self.dir = os.path.join(ROOT, room)
        os.makedirs(self.dir, exist_ok=True)
        self.f = open(os.path.join(self.dir, "events.jsonl"), "a", buffering=1)
        self.fps, self.last_jpeg, self.events, self._shot_n = fps, None, [], 0
        self.ff = subprocess.Popen(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "image2pipe",
                "-framerate",
                str(fps),
                "-c:v",
                "mjpeg",
                "-i",
                "-",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                os.path.join(self.dir, "screen.mp4"),
            ],
            stdin=subprocess.PIPE,
        )
        self._stop = False
        threading.Thread(target=self._rec, daemon=True).start()
        self.event("session_start", room=room)

    def frame(self, jpeg: bytes):
        self.last_jpeg = jpeg

    def _rec(self):  # constant-rate writer: repeats the last frame so the mp4 runs in real time
        nxt = time.monotonic()
        while not self._stop:
            if self.last_jpeg:
                try:
                    self.ff.stdin.write(self.last_jpeg)
                except Exception:
                    return
            nxt += 1 / self.fps
            time.sleep(max(0, nxt - time.monotonic()))

    def event(self, kind: str, **data):
        e = {"ts": _ts(), "kind": kind, **data}
        if DEBUG_SHOTS and kind in SHOT_KINDS and self.last_jpeg:
            try:
                d = os.path.join(self.dir, "shots")
                os.makedirs(d, exist_ok=True)
                self._shot_n += 1
                name = f"{self._shot_n:04d}_{kind}.jpg"
                with open(os.path.join(d, name), "wb") as fh:
                    fh.write(self.last_jpeg)
                e["shot"] = name
            except Exception:
                pass
        self.events.append(e)
        try:
            self.f.write(json.dumps(e, default=str) + "\n")
        except Exception:
            pass

    def close(self):
        self._stop = True
        time.sleep(0.3)
        try:
            self.ff.stdin.close()
            self.ff.wait(20)
        except Exception:
            pass
        self.event("session_end")
        self.f.close()
        write_summary(self.dir, self.events)


def write_summary(d, events):
    """summary.md: the conversation, the planner's steps and Jev's decisions, one line each."""
    L = [f"# Session {os.path.basename(d)}", ""]
    for e in events:
        t = e["ts"][11:19]
        k = e["kind"]
        if k == "user":
            L.append(f"- {t} **User:** {e.get('text')}")
        elif k == "agent":
            L.append(f"- {t} **Agent:** {e.get('text')}")
        elif k == "plan":
            L.append(f"- {t} PLAN step {e.get('step')}: {e.get('decision')} {e.get('args')}")
        elif k == "jev_decision":
            L.append(
                f"  - {t} jev [{e.get('step')}] {e.get('op')} p={e.get('p')} goal={e.get('goal')} stuck={e.get('stuck')} ({e.get('ms')} ms, {e.get('n_elements')} els)"
            )
        elif k == "jev_step_end":
            L.append(f"  - {t} step {'DONE' if e.get('done') else 'FAILED'}: {e.get('step')} {e.get('error') or ''}")
        elif k in ("session_start", "session_end"):
            L.append(f"- {t} {k}")
    if os.path.exists(os.path.join(d, "screen.mp4")):
        L += ["", "Recording: screen.mp4"]
    open(os.path.join(d, "summary.md"), "w").write("\n".join(L) + "\n")


async def upload_log(slog: SessionLog, room: str):
    """Send events.jsonl to the store behind LOG_URL (in the cloud the container's disk is gone after the call).
    Without LOG_URL/LOG_SECRET the log stays in sessions/ only."""
    url, secret = os.getenv("LOG_URL"), os.getenv("LOG_SECRET")
    if not (url and secret):
        log.info("call log upload skipped: LOG_URL/LOG_SECRET not set")
        return
    try:
        import aiohttp

        data = open(os.path.join(slog.dir, "events.jsonl"), "rb").read()
        async with (
            aiohttp.ClientSession() as http,
            http.post(
                f"{url}?room={room}",
                data=data,
                headers={"x-log-secret": secret, "Content-Type": "application/x-ndjson"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r,
        ):
            log.info("call log upload %s: %s", room, r.status)
    except Exception as e:
        log.warning("call log upload failed: %s", e)
