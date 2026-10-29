"""Live E2E check of a spoken user turn: STT latency + STT cost reach the client.

Usage: ../venv/bin/python scripts/e2e_stt_turn_check.py path/to/speech.wav [voice]
Env:   V2V_HOST, GCLOUD_ACCOUNT (same as e2e_clone_check.py).

Streams the WAV as real-time 16 kHz mic audio after the greeting, then silence so the VAD
closes the turn. PASS requires:
  * an `stt_latency` metric (speech end -> first Transcribe Live byte) between 0 and 3 s,
  * a final user transcription,
  * a cascade_cost snapshot whose STT stage is priced (> $0, estimated).
It also prints the client-side view (last voiced chunk sent -> first user text seen) as a
sanity check; that includes network time, so it should be >= the server figure.
"""
import asyncio, os, subprocess, sys, time, wave

import numpy as np
import websockets
from pipecat.frames.frames import OutputAudioRawFrame, OutputTransportMessageFrame
from pipecat.serializers.protobuf import ProtobufFrameSerializer

HOST = os.environ.get("V2V_HOST", "v2v-demo-853612069841.us-central1.run.app")
ACCOUNT = os.environ.get("GCLOUD_ACCOUNT", "admin@manishkjs.altostrat.com")
RATE, CHUNK_MS = 16000, 20


def load_pcm16k(path: str) -> bytes:
    with wave.open(path) as w:
        src = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() > 1:
            src = src.reshape(-1, w.getnchannels()).mean(axis=1).astype(np.int16)
        rate = w.getframerate()
    if rate != RATE:
        x = np.linspace(0, len(src), int(len(src) * RATE / rate), endpoint=False)
        src = np.interp(x, np.arange(len(src)), src).astype(np.int16)
    return src.tobytes()


async def main(wav: str, voice: str) -> int:
    token = subprocess.check_output(
        ["gcloud", "auth", "print-identity-token", f"--account={ACCOUNT}"], text=True).strip()
    ser = ProtobufFrameSerializer()
    speech = load_pcm16k(wav)
    url = (f"wss://{HOST}/ws?bot_type=tts-llm-stt&tts_voice={voice}&tts_model=google-tts"
           f"&stt_language=hi-IN&llm_model=gemini-3.5-flash-lite")
    state = {"greeting_done": asyncio.Event(), "stt_latency": [], "user_text": [], "cost": None,
             "speech_end": None, "client_first_text": None, "errors": []}

    async with websockets.connect(url, extra_headers={"Authorization": f"Bearer {token}"},
                                  max_size=None, open_timeout=30) as ws:
        async def send_msg(msg):
            await ws.send(await ser.serialize(OutputTransportMessageFrame(message=msg)))

        async def receiver():
            async for raw in ws:
                frame = await ser.deserialize(raw)
                msg = getattr(frame, "message", None)
                if not isinstance(msg, dict):
                    continue
                data = msg.get("data") or {}
                if msg.get("type") == "bot-stopped-speaking":
                    state["greeting_done"].set()
                if msg.get("type") in ("error", "error-response") or data.get("type") == "error":
                    state["errors"].append(msg)
                payload = data.get("payload") or {}
                kind = data.get("type")
                if kind in ("interim_transcription", "interim_input_transcription", "transcription") \
                        and (data.get("participant") or "").lower() in ("user", "") and data.get("text"):
                    if state["speech_end"] and state["client_first_text"] is None:
                        state["client_first_text"] = time.time() - state["speech_end"]
                    if kind == "transcription" and (data.get("participant") or "").lower() == "user":
                        state["user_text"].append(data["text"])
                if kind == "metrics" and payload.get("type") == "stt_latency":
                    state["stt_latency"].append(payload.get("value"))
                if kind == "metrics" and payload.get("type") == "cascade_cost":
                    if not state["cost"] or payload["revision"] > state["cost"]["revision"]:
                        state["cost"] = payload

        rx = asyncio.create_task(receiver())
        await send_msg({"label": "rtvi-ai", "type": "client-ready", "id": "cr1",
                        "data": {"version": "2.1.0", "about": {"library": "e2e-stt-turn-check"}}})
        await send_msg({"type": "start_trigger", "id": "st1"})
        try:
            await asyncio.wait_for(state["greeting_done"].wait(), timeout=20)
        except asyncio.TimeoutError:
            print("WARN: greeting did not finish within 20s; speaking anyway")
        await asyncio.sleep(0.5)

        step = RATE * 2 * CHUNK_MS // 1000
        silence = b"\0" * step
        for chunk in [speech[i:i + step] for i in range(0, len(speech), step)] + [silence] * (4000 // CHUNK_MS):
            if chunk is silence and state["speech_end"] is None:
                state["speech_end"] = time.time()
            await ws.send(await ser.serialize(OutputAudioRawFrame(audio=chunk, sample_rate=RATE, num_channels=1)))
            await asyncio.sleep(CHUNK_MS / 1000)
        await asyncio.sleep(2)
        rx.cancel()

    stt = next((s for s in (state["cost"] or {}).get("stages", []) if s["stage"] == "stt"), None)
    lat = state["stt_latency"][-1] if state["stt_latency"] else None
    checks = {
        "stt_latency metric in (0, 3s)": lat is not None and 0 < lat < 3,
        "final user transcription": bool(state["user_text"]),
        "STT stage priced (estimated)": bool(stt and float(stt["known_usd"]) > 0 and stt.get("estimated")),
        "no error messages": not state["errors"],
    }
    print(f"server stt_latency (speech end -> first byte): {None if lat is None else int(lat * 1000)} ms")
    cft = state["client_first_text"]
    print(f"client view (last voiced chunk sent -> first user text): {None if cft is None else int(cft * 1000)} ms")
    print(f"user transcript: {state['user_text'][-1:]}")
    if state["cost"]:
        print("cost:", state["cost"]["known_usd"], {s["stage"]: (s["known_usd"], s["complete"], s.get("estimated"))
                                                    for s in state["cost"]["stages"]})
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Custom-Female")))
