"""End-to-end clone check against the live Cloud Run service (deploy verification gate).

Usage: ../venv/bin/python scripts/e2e_clone_check.py [Custom-Male Custom-Female ...]
Env: V2V_HOST (default v2v-demo prod host), GCLOUD_ACCOUNT (default admin@manishkjs.altostrat.com).
Exit code is non-zero if any voice fails.

Opens a real /ws Cascade session with a cloned voice (keys come from the /keys GCS mount),
sends RTVI client-ready + start_trigger exactly like the browser, and measures bot audio returned.
"""
import asyncio, os, subprocess, sys, time

import websockets
from pipecat.frames.frames import OutputTransportMessageFrame, OutputAudioRawFrame
from pipecat.serializers.protobuf import ProtobufFrameSerializer

HOST = os.environ.get("V2V_HOST", "v2v-demo-853612069841.us-central1.run.app")
ACCOUNT = os.environ.get("GCLOUD_ACCOUNT", "admin@manishkjs.altostrat.com")
token = subprocess.check_output(
    ["gcloud", "auth", "print-identity-token", f"--account={ACCOUNT}"], text=True).strip()


async def run(voice: str) -> bool:
    ser = ProtobufFrameSerializer()
    url = (f"wss://{HOST}/ws?bot_type=tts-llm-stt&tts_voice={voice}&tts_model=google-tts"
           f"&stt_language=hi-IN&llm_model=gemini-3.5-flash-lite")
    audio_bytes, texts = 0, []
    async with websockets.connect(url, extra_headers={"Authorization": f"Bearer {token}"},
                                  max_size=None, open_timeout=30) as ws:
        t0 = time.time()
        for msg in (
            {"label": "rtvi-ai", "type": "client-ready", "id": "cr1",
             "data": {"version": "2.1.0", "about": {"library": "e2e-clone-check"}}},
            {"type": "start_trigger", "id": "st1"},
        ):
            await ws.send(await ser.serialize(OutputTransportMessageFrame(message=msg)))
        first_audio = None
        while time.time() - t0 < 20:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                if audio_bytes:
                    break
                continue
            frame = await ser.deserialize(raw)
            if frame is None:
                continue
            audio = getattr(frame, "audio", None)
            if audio:
                audio_bytes += len(audio)
                first_audio = first_audio or time.time() - t0
            msg = getattr(frame, "message", None)
            if isinstance(msg, dict):
                data = msg.get("data") or {}
                if msg.get("type") in ("error", "error-response") or data.get("type") == "error":
                    texts.append(f"ERROR: {msg}")
                elif data.get("type") == "transcription" and data.get("payload", {}).get("participant") == "Bot":
                    texts.append(data["payload"].get("text", ""))
    secs = audio_bytes / 2 / 24000
    verdict = "PASS" if secs > 0.5 and not any(t.startswith("ERROR") for t in texts) else "FAIL"
    print(f"[{voice}] {verdict}: {secs:.2f}s bot audio, first audio at {first_audio or 0:.2f}s")
    for t in texts[:6]:
        print("   ", t[:160])
    return verdict == "PASS"


async def main() -> int:
    results = [await run(v) for v in sys.argv[1:] or ["Custom-Male", "Custom-Female"]]
    return 0 if all(results) else 1

sys.exit(asyncio.run(main()))
