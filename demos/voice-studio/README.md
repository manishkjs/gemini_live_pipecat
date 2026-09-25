# Gemini Voice Studio demo

A standalone React + Vite demo for this repository. It adds an animated Pipecat Voice UI Kit visualizer, a live transcript, microphone/speaker controls, and session configuration without modifying `client/` or `server/`.

This work is on `ui-changes-sep`. See [the branch handoff](../../UI_CHANGES_SEP.md) for the integration map and IDE workflow.

## Run locally

Requires Node.js 22.13 or newer.

```bash
cd demos/voice-studio
npm ci
npm run dev
```

Open the URL printed by Vite.

## Persona and custom journeys

Choose **Meera — Debt Collector**, **Kavya — Reservation Agent**, **Kabir — Storyteller**, or **Aisha — AI Companion** for a prepared role, prompt, opening cue and short scenario. Each persona offers a **Play persona preview** button. These are scripted English conversations using browser speech synthesis, with a text fallback when browser voices are unavailable. They make no Gemini API calls and do not emulate either engine's audio or latency.

Choose **Custom Agent** for the bare-bones flow. Write your own system instructions directly beside the session controls, then select either engine. Leaving instructions blank omits the override and keeps the backend's current system prompt. Custom instructions are retained in tab memory when switching away from and back to Custom Agent. The demo limits overrides to 1,000 characters so the complete instruction remains below this backend's `/connect` limit of 1,500 characters. Custom Agent has no scripted preview, because a canned conversation would not reflect your instructions.

The animation is 132px on desktop and 102px on mobile. The transcript occupies the wider panel and uses readable conversation text. UI branding is Voice Studio; underlying open-source package names and license notices remain intact.

The four fictional Indian agents have generated portraits bundled in `public/personas/`, localized prompts that follow the selected language, and updated Indian demo scenarios. Portraits appear on cards, beside agent controls and in transcripts without enlarging the animation. The Custom Agent option keeps a neutral icon and preserves the blank-instruction behavior. Exact image prompts and generation provenance are in `docs/portrait-generation.json`.

## Connect to the existing backend

1. Run `server/server.py` using the repository's existing setup and credentials.
2. Choose a persona or **Custom Agent**.
3. Select **Gemini Live** for native audio, or **Cascade** for speech recognition → language model → voice.
4. Open **Settings** and enter `http://localhost:7860` for local development, or the HTTPS URL of your deployed FastAPI backend.
5. Select voice, language and the relevant model settings. Persona prompts are supplied automatically; optional instructions replace the preset.
6. Click **Start Gemini Live** or **Start Cascade** and allow microphone access.

An HTTPS-hosted demo requires an HTTPS backend returning a matching `wss://` URL. The backend must allow the demo origin with CORS. No credentials are stored or sent through the demo's hosting service; the browser connects directly to the chosen backend. Gemini usage and backend hosting retain their normal costs.

## Existing functionality and observability

The existing `client/` and `server/` are unchanged, including the original Observability tab, metrics panel, configuration options and diagnostics console. The header's **Observability** chart icon opens your configured server's `/diagnostics`; **Original UI** opens its existing client. These shortcuts open in a separate tab without ending the current voice session. Set a valid server URL in Settings first, and ensure the backend is serving the original built client.

## Integration details

- Uses the official `@pipecat-ai/voice-ui-kit` `CircularWaveform` and Motion for interface transitions.
- Uses the public APIs of `@pipecat-ai/websocket-transport` and its protobuf serializer.
- Routes Gemini Live to `bot_type=gemini-live`, and Cascade to `bot_type=tts-llm-stt` with STT/LLM/TTS model parameters.
- Sends custom or persona instructions in the `/connect` POST body; an empty Custom Agent sends no prompt override. The existing backend transfers accepted compact prompts to the WebSocket URL.
- Posts session settings to the existing `/connect` endpoint, consumes its `ws_url`, then sends `client-ready` followed by this repository's custom `start_trigger` greeting message.
- Adapts the repository's custom `server-message` transcription/metrics events. It does not wait for a `bot-ready` event, which the current custom server pipeline does not emit.
- Receives 24 kHz PCM output and sends 16 kHz microphone audio. A small `DailyMediaManager` subclass routes output into a MediaStreamTrack, enabling the Pipecat visualizer and the speaker mute control to share audio.
- Response time is client-observed time from receipt of a finalized user transcript to the first received bot audio chunk. It is not server TTFB. Sample mode never shows invented latency or token metrics.
- The transcript exists in tab memory and can be copied. It is not persisted.
- Model values come from the existing repository. Availability depends on the connected backend and Google account.

## Validation

```bash
npm test
npm run build
```

The contract checks cover all five agent choices with both engines, persona instructions, custom overrides, default-prompt preservation, prompt size, backend URL validation, WebSocket destinations, local development compatibility, and bundled portrait assets. A successful build checks application TypeScript and bundles the client.

Live microphone/Gemini calls have not been end-to-end tested in this environment because no deployed backend address or runtime credentials were supplied. Sample mode is usable independently.

## Documentation recommendation

Use Astro + Starlight for a separate documentation site. Suggested navigation: Getting started, Voice playground, Architecture, Gemini Live configuration, Tools, Deployment, Diagnostics, and Troubleshooting. Keep long architecture explanations in documentation and short task-specific help in this voice UI.

## Licenses

Pipecat Voice UI Kit and the Pipecat client packages use BSD-2-Clause. Motion, React, Vite, Tailwind, and shadcn/ui use MIT licences. Their packages retain their respective notices. No paid UI templates are required.
