"""Per-room session logging: sessions/<room>/{events.jsonl, screen.mp4, summary.md}."""
import json, os, subprocess, time, datetime, threading

# DEBUG_SHOTS=1 (default): the live screen frame is saved for every key event, named after it (shots/0042_action_landed.jpg),
# so what was said, what was clicked and what the screen showed line up exactly when reviewing a session.
DEBUG_SHOTS = os.getenv("DEBUG_SHOTS", "1") == "1"
SHOT_KINDS = {"user", "agent", "tool_start", "action_landed", "action_failed", "flow_step", "intent_fired", "step_guard",
              "where_mismatch", "claim_without_action", "said_not_done_click", "floor_change", "click_on_screen", "type_on_screen",
              "point_on_screen", "landing_brief", "voicebridge_state", "session_start"}
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions")

def _ts():
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")

class SessionLog:
    def __init__(self, room: str, fps: int = 8):
        self.dir = os.path.join(ROOT, room); os.makedirs(self.dir, exist_ok=True)
        self.f = open(os.path.join(self.dir, "events.jsonl"), "a", buffering=1)
        self.fps, self.last_jpeg, self.events = fps, None, []
        self.ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(fps),
                                    "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                                    "-movflags", "+faststart", os.path.join(self.dir, "screen.mp4")], stdin=subprocess.PIPE)
        self._stop = False
        threading.Thread(target=self._rec, daemon=True).start()
        self.event("session_start", room=room)

    def frame(self, jpeg: bytes):
        self.last_jpeg = jpeg

    def _rec(self):  # constant-rate writer: repeat last frame so the mp4 runs in real time
        nxt = time.monotonic()
        while not self._stop:
            if self.last_jpeg:
                try: self.ff.stdin.write(self.last_jpeg)
                except Exception: return
            nxt += 1 / self.fps; time.sleep(max(0, nxt - time.monotonic()))

    def event(self, kind: str, **data):
        e = {"ts": _ts(), "kind": kind, **data}
        if DEBUG_SHOTS and kind in SHOT_KINDS and self.last_jpeg:
            try:
                d = os.path.join(self.dir, "shots"); os.makedirs(d, exist_ok=True)
                self._shot_n = getattr(self, "_shot_n", 0) + 1
                name = f"{self._shot_n:04d}_{kind}.jpg"
                with open(os.path.join(d, name), "wb") as fh: fh.write(self.last_jpeg)
                e["shot"] = name
            except Exception: pass
        self.events.append(e)
        try: self.f.write(json.dumps(e, default=str) + "\n")
        except Exception: pass

    def close(self):
        self._stop = True; time.sleep(0.3)
        try: self.ff.stdin.close(); self.ff.wait(20)
        except Exception: pass
        self.event("session_end"); self.f.close()
        write_summary(self.dir, self.events)

def write_summary(d, events):
    L = [f"# Session {os.path.basename(d)}", ""]
    for e in events:
        t = e["ts"][11:19]; k = e["kind"]
        if k == "user": L.append(f"- {t} **User:** {e.get('text')}")
        elif k == "agent": L.append(f"- {t} **Agent:** {e.get('text')}")
        elif k == "tool_call": L.append(f"- {t} TOOL `{e.get('name')}`({e.get('args')})")
        elif k == "plan": L.append(f"- {t} PLAN ({e.get('timing')}): " + " | ".join(s.get("goal", "") for s in e.get("plan", {}).get("steps", [])))
        elif k == "jev_decision": L.append(f"  - {t} jev [{e.get('step')}] {e.get('op')} p={e.get('p')} goal={e.get('goal')} stuck={e.get('stuck')} ({e.get('ms')} ms, {e.get('n_elements')} els)")
        elif k == "jev_step_end": L.append(f"  - {t} step {'DONE' if e.get('done') else 'FAILED'}: {e.get('step')} {e.get('error') or ''}")
        elif k == "request_end": L.append(f"- {t} RESULT timings={e.get('timings')} failed={e.get('failed')}")
        elif k == "error": L.append(f"- {t} **ERROR** {e.get('msg')}")
        elif k in ("session_start", "session_end"): L.append(f"- {t} {k}")
    if os.path.exists(os.path.join(d, "screen.mp4")): L += ["", "Recording: screen.mp4"]
    head = ""
    try:   # [PROFILE] the MEDDPICC CRM note (faan/profile.py finalize) goes on top when it was written first
        pf = os.path.join(d, "profile_summary.md")
        if os.path.exists(pf): head = open(pf).read()
    except Exception: pass
    open(os.path.join(d, "summary.md"), "w").write(head + "\n".join(L) + "\n")
