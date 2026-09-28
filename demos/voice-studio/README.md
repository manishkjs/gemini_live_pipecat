# Gemini Voice Studio

The React + Vite frontend for **Gemini Live + Pipecat**, featuring an animated `@pipecat-ai/voice-ui-kit` visualizer, Gemini 3.8 Live Avatar (`response_modalities=[VIDEO]` with MSE/ManagedMediaSource fMP4 streaming), Gemini 3.8 Zero-Shot Voice Cloning, a live transcript, microphone/speaker controls, real-time token/cost ledgers, monotonic SOP phase cards, and a Firestore-backed visit counter.

See the [repository root README](../../README.md) for full backend setup, Cloud Run deployment, and E2E verification instructions.

## Run locally

Requires Node.js 22.13 or newer.

```bash
cd demos/voice-studio
npm ci
npm run dev
```

Open the URL printed by Vite (`http://localhost:5173`).

## Personas, Live Avatar, and Voice Cloning

Choose from 7 prepared Indian enterprise personas or **Custom Agent**:
- **Meera — Debt Collector** (Sahaj Finance)
- **Kavya — Cymbal Kart Buddy** (Cymbal Smartglasses companion)
- **Kabir — Storyteller** (Atmospheric horror narrator)
- **Aisha — AI Companion** (Witty conversational partner)
- **Abhay — Car Negotiator** (Delhi/NCR AeroNxt EV dealer with server-enforced ₹14.5L floor)
- **Ananya — Mutual Fund Advisor** (Groww / Cymbal Investments wealth advisor with SOP phase tracker)
- **Pragya — Lamborghini Concierge** (Exotic supercar concierge with 4-phase SOP tracker and `CallSlots` booking state)
- **Custom Agent** (Bring-your-own-instructions sandbox; up to 1,000 characters)

Each prepared persona offers a **Play persona preview** button using browser speech synthesis (or text fallback) with zero Gemini API calls, plus generated WebP portraits in `public/personas/` (provenance in `docs/portrait-generation.json`).

### Gemini 3.8 Live Avatar (Live Engine Only)
- Toggle **Live Avatar** in the header or settings when running on `gemini-3.8-live-preview` / `gemini-3.8-live-extended-thinking-preview`.
- Choose from 8 prebuilt Vertex AI avatars (`Ben`, `Kira`, `Leo`, `Vera`, `Sam`, `Kai`, `Jay`, `Paul`) or upload a custom reference portrait (automatically center-cropped and normalized to `704×1280` 9:16 JPEG/PNG on the client and enforced by Pillow on the server).
- Streams fragmented MP4 (`fMP4` H.264 + AAC) via browser `MediaSource` (or `ManagedMediaSource` on iOS 17.1+ Safari with `disableRemotePlayback = true`), with post-speech phantom lip-flap suppression and automatic audio fallback if the browser lacks MSE support.

### Gemini 3.8 Zero-Shot Voice Cloning & Custom Voices
- **Gemini 3.8 Cloned Voice (`Gemini-Clone-Male`)**: Works across both **Gemini Live 3.8** (`replicated_voice_config` using a 24 kHz mono PCM WAV reference sample) and **Cascade 3.8 TTS** (`gemini-3.8-flash-tts` / `gemini-3.8-flash-lite-tts` via `voice_Prompt_audio` or `voiceCloningKey`).
- **Custom Live Voice (`Custom-Live-Voice`)**: Upload or record a 5–10s WAV reference sample in the browser; sent strictly in the `/connect` POST body (`custom_voice_audio`) and normalized to 24 kHz mono 16-bit WAV on the backend.
- **Chirp 3 Instant Custom Voices (`Clone-Male`, `Clone-Female`)**: Available in Cascade mode when `en-US-Chirp3-HD-InstantCustomVoice` keys are mounted.

## Connect to the backend

1. Run `server/server.py` using the repository's setup and credentials.
2. Choose a persona or **Custom Agent**.
3. Select **Gemini Live** for native duplex audio/video, or **Cascade** for STT → LLM → TTS.
4. Open **Settings** and enter `http://localhost:7860` for local development, or the HTTPS URL of your deployed FastAPI backend.
5. Select voice, language, thinking level, and model settings.
6. Click **Start Gemini Live** or **Start Cascade** and allow microphone access.

## Integration details

- Uses `@pipecat-ai/voice-ui-kit` (`CircularWaveform`) and Motion for interface transitions.
- Uses `@pipecat-ai/websocket-transport` and its protobuf serializer.
- Routes Gemini Live to `bot_type=gemini-live`, and Cascade to `bot_type=tts-llm-stt` with STT/LLM/TTS model parameters.
- Posts session settings, custom instructions, custom avatar images, and custom voice audio in the `/connect` POST body (never in query parameters) and consumes the returned `ws_url` + `session_token`.
- Tracks live studio visits via `GET /api/visits` and `POST /api/visits` (`page_load_id` deduplicated per tab load).

## Validation

```bash
npm test
npm run build
```

`npm test` runs 133 Node unit and contract tests (`tests/session-events.test.mjs` and `tests/voice-studio-contract.test.mjs`) covering all 8 personas across both engines, Live Avatar MSE/ManagedMediaSource streaming and fallback guards, Gemini 3.8 voice cloning contracts, token/cost reconciliation, SOP phase progression, and URL/WebSocket validation.

