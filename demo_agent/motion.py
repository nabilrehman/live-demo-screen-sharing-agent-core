"""Human-like cursor motion for the drawn demo cursor (and the real Playwright mouse).

Timing model (Fitts' law, Shannon form):  MT = A + B * log2(D / W + 1), clamped to [MIN, MAX], scaled by CURSOR_SPEED.
  defaults A=200 ms, B=150 ms, W=40 px, clamp [300, 980]  ->  ~320 ms for a 30 px hop, ~650 ms for 300 px, ~900-960 ms across the screen.
Path: quadratic Bezier with a small perpendicular bow (wrist arc: control point offset 18% of the distance, i.e. the path bulges ~9% / max 75 px), traversed with the
minimum-jerk profile 10t^3 - 15t^4 + 6t^5 (Flash & Hogan) on t^0.9, so speed rises fast and homes in slowly like a hand.  Moves longer than
~100 px drift 4-12 px past the target (peaking ~86% through) and ease back in the same continuous motion.
Everything is deterministic (no random wandering, no idle jitter).

Env knobs: CURSOR_SPEED (multiplier on durations, default 1.0), CURSOR_MS_A, CURSOR_MS_B, CURSOR_MS_MIN, CURSOR_MS_MAX,
CURSOR_DWELL_MS (pre-click hover dwell, default 200), CURSOR_SETTLE_MS (pause after arrival before a spotlight, default 170).
"""
from __future__ import annotations
import math, os


def _f(name, default):
    try: return float(os.getenv(name, default))
    except ValueError: return float(default)


A, B = _f("CURSOR_MS_A", 200), _f("CURSOR_MS_B", 150)
MS_MIN, MS_MAX = _f("CURSOR_MS_MIN", 300), _f("CURSOR_MS_MAX", 980)
SPEED = _f("CURSOR_SPEED", 1.0)
DWELL_MS = _f("CURSOR_DWELL_MS", 200)
SETTLE_MS = _f("CURSOR_SETTLE_MS", 170)
STEP_MS = 16.0


def duration_ms(dist: float, width: float | None = None) -> float:
    """Fitts-like glide time. 0 for sub-3px nudges (no visible motion needed)."""
    if dist < 3: return 0.0
    w = min(120.0, max(16.0, width or 40.0))
    ms = A + B * math.log2(dist / w + 1.0)
    return max(MS_MIN, min(MS_MAX, ms)) * SPEED


def _minjerk(t: float) -> float:
    return t * t * t * (10 - 15 * t + 6 * t * t)


def _aimed(t: float) -> float:
    """Minimum-jerk with the velocity peak pulled slightly earlier (~45% of the time): quick launch, long gentle homing-in,
    the asymmetry measured in real aimed pointing movements."""
    return _minjerk(t ** 0.9)


def path(x0: float, y0: float, x1: float, y1: float, ms: float | None = None, width: float | None = None):
    """Return [(t_ms, x, y), ...] sampled every ~16 ms, ending exactly at (x1, y1)."""
    dx, dy = x1 - x0, y1 - y0
    d = math.hypot(dx, dy)
    if ms is None: ms = duration_ms(d, width)
    if d < 3 or ms <= 0: return [(0.0, x1, y1)]
    ux, uy = dx / d, dy / d
    px_, py_ = -uy, ux                                      # unit perpendicular
    # bow perpendicular to travel; consistent handedness (right-hand wrist arc). Control point sits a bit before the
    # chord midpoint so the path leaves at an angle and straightens out while homing in.
    # deterministic per-move variety (hash of the endpoints): humans never draw the same arc twice, but nothing random at rest
    h = (int(x0) * 73856093 ^ int(y0) * 19349663 ^ int(x1) * 83492791 ^ int(y1) * 2654435761) & 0xFFFF
    r1, r2, r3 = (h & 0xFF) / 255, ((h >> 8) & 0xFF) / 255, ((h * 7919) & 0xFF) / 255
    ms *= 0.93 + 0.14 * ((h >> 4) & 0xFF) / 255             # +-7% tempo variation
    hand = (1 if dx >= 0 else -1) * (-1 if r1 < 0.25 else 1)
    bow = min(150.0, max(6.0, (0.12 + 0.12 * r2) * d)) * hand
    cx, cy = x0 + dx * 0.42 + px_ * bow, y0 + dy * 0.42 + py_ * bow
    # deterministic low-frequency S-wobble (~2% of the distance), phase/sign derived from the endpoints - no randomness
    wob = min(18.0, 0.02 * d) * (1 if (int(x1) * 7 + int(y1) * 13) % 2 else -1)
    ov = min(12.0, 3.0 + 0.01 * d) * (0.6 + 0.6 * r3) if d > 100 and r3 > 0.2 else 0.0
    # overshoot as a smooth bump layered on the main glide (peaks ~80% of the way through, gone by the end): the cursor
    # drifts a few px past/aside the target and eases back in one continuous motion - no stop-and-correct hitch
    PK, LO = 0.86, 0.62                                      # bump peak / start (fraction of the move time)
    fwd = ov + d * (1 - _aimed(PK)) if ov else 0.0          # so the cursor really sits ~ov px past the target at the peak
    ox, oy = ux * fwd + px_ * 0.35 * hand * ov, uy * fwd + py_ * 0.35 * hand * ov
    pts, n = [], max(2, int(round(ms / STEP_MS)))
    for i in range(1, n + 1):
        t = ms * i / n
        u = t / ms
        e = _aimed(u)
        w = wob * math.sin(2 * math.pi * e) * math.sin(math.pi * e)
        b = 0.0
        if ov and u > LO:
            b = math.sin(0.5 * math.pi * (u - LO) / (PK - LO)) ** 2 if u <= PK else math.cos(0.5 * math.pi * (u - PK) / (1 - PK)) ** 2
        px = (1 - e) ** 2 * x0 + 2 * (1 - e) * e * cx + e * e * x1 + px_ * w + ox * b
        py = (1 - e) ** 2 * y0 + 2 * (1 - e) * e * cy + e * e * y1 + py_ * w + oy * b
        pts.append((t, px, py))
    pts[-1] = (ms, float(x1), float(y1))
    return pts
