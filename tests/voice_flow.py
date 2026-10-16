"""Spoken end-to-end test (a script, not a pytest test): TTS'd customer lines go into a room with a running agent worker.

After each line it waits until the agent has answered (spoken, then listening for QUIET_S), max 60 s. A line may carry
options as a third element: {"wait_floor": "demo_app", "after_s": 6} waits (max 150 s) until the agent's 'faan.floor'
attribute has that value, then after_s more, before speaking. Saves end-state screen-share frames and a mixed recording.
Rooms are named faan-livevoice-*; the agent treats them as voice-only. The call log is in sessions/<room>/events.jsonl.

  set -a && . ./.env.local && set +a && \
  QUIET_S=6 AGENT_NAME=<worker's agent name> FLOWS='[["Hi Kai, ...", "."], ["Hi, I'd like to book...", ".", {"wait_floor": "demo_app", "after_s": 2}]]' \
  uv run tests/voice_flow.py"""

import asyncio
import json
import os
import time
import uuid

import aiohttp
import numpy as np
from livekit import api, rtc
from livekit.agents import inference, utils
from PIL import Image

SR = 48000
REQS = (
    [tuple(x) for x in json.loads(os.environ["FLOWS"])]
    if os.getenv("FLOWS")
    else [
        ("Can you show me how to change the STT model?", r"/agents|/voices|model|builder"),
        ("Can you show me the new observability features?", r"/sessions|observability|insights"),
    ]
)


async def synth(text):
    t = inference.TTS(
        model="cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc", language="en", sample_rate=SR
    )
    f = rtc.combine_audio_frames([f.frame async for f in t.synthesize(text)])
    a = np.frombuffer(f.data, np.int16).astype(
        np.float32
    )  # the TTS often clips at full scale; a real mic peaks far lower
    a = (a * (float(os.getenv("CUSTOMER_PEAK", 0.3)) * 32767 / max(1.0, np.abs(a).max()))).astype(np.int16)
    return rtc.AudioFrame(a.tobytes(), f.sample_rate, 1, len(a))


async def transcribe(pcm):
    s = inference.STT(model="deepgram/nova-3", language="en")
    st = s.stream()
    out = []

    async def rd():
        async for ev in st:
            if ev.type.name == "FINAL_TRANSCRIPT":
                out.append(ev.alternatives[0].text)

    task = asyncio.create_task(rd())
    n = SR // 50
    for i in range(0, len(pcm), n):
        ch = pcm[i : i + n]
        ch = np.pad(ch, (0, n - len(ch))) if len(ch) < n else ch
        st.push_frame(rtc.AudioFrame(ch.tobytes(), SR, 1, n))
        await asyncio.sleep(0.001)
    for _ in range(100):
        st.push_frame(rtc.AudioFrame(np.zeros(n, np.int16).tobytes(), SR, 1, n))
    st.end_input()
    await task
    return " ".join(out)


async def main():
    async with aiohttp.ClientSession():
        utils.http_context._new_session_ctx()
        clips = [await synth(r[0]) for r in REQS]
        room_name = "faan-livevoice-" + uuid.uuid4().hex[:5]
        lk = api.LiveKitAPI()
        tok = (
            api.AccessToken()
            .with_identity("customer-test")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        room = rtc.Room()
        recv = []
        last_frame = {}
        t0 = time.time()
        sent = []  # sent: (time, customer clip) for the mixed recording

        async def cap_audio(track):
            async for ev in rtc.AudioStream(track, sample_rate=SR, num_channels=1):
                recv.append((time.time(), np.frombuffer(ev.frame.data, np.int16).copy()))

        async def cap_video(track):
            async for ev in rtc.VideoStream(track):
                last_frame["f"] = ev.frame

        floor = {"v": "faan"}
        agent_state = {
            "v": "initializing",
            "t": time.time(),
            "spoke": 0.0,
        }  # LiveKit agents publish lk.agent.state as a participant attribute

        @room.on("participant_attributes_changed")
        def _attrs(changed, participant):
            if "lk.agent.state" in changed:
                agent_state["v"] = changed["lk.agent.state"]
                agent_state["t"] = time.time()
                if agent_state["v"] == "speaking":
                    agent_state["spoke"] = time.time()
            if "faan.floor" in changed:
                floor["v"] = changed["faan.floor"]
                print(f"{time.time() - t0:6.1f}s floor -> {floor['v']}", flush=True)

        @room.on("track_subscribed")
        def _(track, pub, p):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.ensure_future(cap_audio(track))
            elif pub.source == rtc.TrackSource.SOURCE_SCREENSHARE:
                asyncio.ensure_future(cap_video(track))

        await room.connect(os.environ["LIVEKIT_URL"], tok)
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=os.getenv("AGENT_NAME", "faan-live"), room=room_name)
        )
        src = rtc.AudioSource(SR, 1)
        await room.local_participant.publish_track(
            rtc.LocalAudioTrack.create_audio_track("mic", src),
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        n = SR // 100
        sil = rtc.AudioFrame(np.zeros(n, np.int16).tobytes(), SR, 1, n)

        async def pump(sec):
            for _ in range(int(sec * 100)):
                await src.capture_frame(sil)

        def loud(a, b):
            return [t for t, d in recv if a < t < b and np.abs(d).max() > 1500]

        await pump(12)  # greeting
        results = []
        for k, (req, clip) in enumerate(zip(REQS, clips, strict=False)):
            q, expect = req[0], req[1]
            opts = req[2] if len(req) > 2 else {}
            if opts.get("wait_floor"):
                tw = time.time()
                while floor["v"] != opts["wait_floor"] and time.time() - tw < 150:
                    await pump(0.1)
                print(
                    f"{time.time() - t0:6.1f}s waited {time.time() - tw:.1f}s for floor={opts['wait_floor']} (now {floor['v']})",
                    flush=True,
                )
            if opts.get("after_s"):
                await pump(float(opts["after_s"]))
            print(f"{time.time() - t0:6.1f}s customer: {q}", flush=True)
            pd = np.frombuffer(clip.data, np.int16)
            sent.append((time.time(), pd.copy()))
            for i in range(0, len(pd), n):
                ch = pd[i : i + n]
                ch = np.pad(ch, (0, n - len(ch))) if len(ch) < n else ch
                await src.capture_frame(rtc.AudioFrame(ch.tobytes(), SR, 1, n))
            tend = time.time()
            # a real prospect replies ~QUIET_S after the agent goes back to listening (agent state from LiveKit, not loudness)
            quiet_s = float(os.getenv("QUIET_S", 2.5))
            while True:
                await pump(0.1)
                el = time.time() - tend
                answered = agent_state["spoke"] > tend or el > 60  # the agent answered (or isn't going to)
                if (
                    el > 2.5
                    and answered
                    and agent_state["v"] == "listening"
                    and time.time() - agent_state["t"] > quiet_s
                ):
                    break
                if opts.get("no_wait") and el > 2.5:
                    break
                if el > 120:
                    break
            l = loud(tend, time.time())
            pcm = np.concatenate([d for t, d in recv if t > tend][-3000:]) if l else np.zeros(1, np.int16)
            try:
                said = (
                    await asyncio.wait_for(transcribe(pcm), 40)
                    if os.getenv("TRANSCRIBE_AGENT", "0") == "1"
                    else "(see events.jsonl)"
                )
            except Exception as e:
                said = f"(transcribe failed: {e!r})"
            png = os.getenv("PNG_PREFIX", "e2e_req") + f"{k + 1}_end.png"
            f = last_frame.get("f")
            if f:
                fr = f.convert(rtc.VideoBufferType.RGBA)
                Image.frombytes("RGBA", (fr.width, fr.height), bytes(fr.data)).save(png)
            results.append(
                {
                    "total_s": round((l[-1] if l else time.time()) - tend, 1),
                    "request": q,
                    "first_speech_after_user_stopped_s": round(l[0] - tend, 2) if l else None,
                    "agent_said": said,
                    "frame": png,
                    "expect": expect,
                }
            )
        await room.disconnect()
        await lk.aclose()
        # mixed call audio (agent + customer) on one wall-clock timeline, for the video judge
        try:
            import wave

            end = max([t for t, _ in recv] + [t + len(d) / SR for t, d in sent] + [t0]) + 1
            mix = np.zeros(int((end - t0) * SR) + SR, np.int32)
            for t, d in recv:
                i = int((t - t0) * SR)
                mix[i : i + len(d)] += d[: max(0, len(mix) - i)]
            for t, d in sent:
                i = int((t - t0) * SR)
                mix[i : i + len(d)] += d[: max(0, len(mix) - i)]
            w = wave.open(os.getenv("PNG_PREFIX", "e2e_req") + "mix.wav", "wb")
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(np.clip(mix, -32768, 32767).astype(np.int16).tobytes())
            w.close()
            json.dump({"t0": t0, "room": room_name}, open(os.getenv("PNG_PREFIX", "e2e_req") + "mix.json", "w"))
        except Exception as e:
            print("mix failed", e)
        print("ROOM", room_name)
        print(json.dumps(results, indent=1))


asyncio.run(main())
