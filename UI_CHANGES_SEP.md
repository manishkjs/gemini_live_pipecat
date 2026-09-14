# Voice Studio: ui-changes-sep

This branch contains the complete Voice Studio UI from the demo plus generated Indian persona portraits, names, localized system instructions and matching sample conversations.

The implementation is isolated in `demos/voice-studio`. The original `client/`, `server/`, deployment configuration and dependency manifests are unchanged. Continue to run or deploy the original application with its existing workflow.

## Start the new UI in your IDE

After checking out `ui-changes-sep`, open the repository in your IDE. Use Node.js 22.13 or newer:

```bash
cd demos/voice-studio
npm ci
npm run dev
```

Open the local URL printed by Vite. The four persona previews run immediately with browser speech synthesis and no model credentials. Custom Agent lets you enter your own instructions.

For real audio, run the repository's existing backend with its usual credentials, then set its URL in Voice Studio's **Settings**. Use `http://localhost:7860` for local development or the deployed HTTPS address. Both **Gemini Live** and **Cascade** use that backend. Configure CORS to allow the UI origin.

## Existing UI and observability

The original client and its Observability tab, chart icon, configuration controls and `/diagnostics` console remain unchanged. Voice Studio adds an **Observability** chart icon that opens the configured backend's existing `/diagnostics` dashboard, plus an **Original UI** shortcut to the backend root. Both open in a separate tab and remain available during a voice session. If the server URL is missing or invalid, configure it in Settings first. Build the original `client/` for these server-hosted pages to be available.

## Personas

| Name | Role | Demo setting |
| --- | --- | --- |
| Meera | Debt Collector | A respectful payment discussion for fictional Sahaj Finance |
| Kavya | Reservation Agent | A birthday dinner request at fictional Aangan in Bengaluru |
| Kabir | Storyteller | Original, interactive stories with Indian settings when requested |
| Aisha | AI Companion | Warm everyday conversation in the user's preferred language |
| Custom Agent | Your own role | Supply instructions or keep the backend's existing prompt |

All portraits depict fictional adults and were AI-generated. They are checked into `demos/voice-studio/public/personas/`; there is no runtime dependency on an image service. Exact generation prompts and provenance are in `demos/voice-studio/docs/portrait-generation.json`.

## Where to continue editing

- `demos/voice-studio/src/lib/personas.ts`: names, image paths, prompts, sample conversations and demo journeys.
- `demos/voice-studio/src/components/voice-studio.tsx`: persona cards, compact agent display, transcript, session controls and settings.
- `demos/voice-studio/src/components/voice-studio.css`: layout, colors, responsive behavior and portrait sizing.
- `demos/voice-studio/src/lib/voice-session.ts`: validated connection parameters and prompt selection.
- `demos/voice-studio/src/lib/pipecat-session.ts`: microphone/audio transport and custom backend event adapter.
- `demos/voice-studio/tests/voice-contract.test.mjs`: connection and persona contract checks.

## Keep these integration constraints

- Keep the existing backend's `/connect` POST and protobuf WebSocket contract. Gemini Live uses `bot_type=gemini-live`; Cascade uses `bot_type=tts-llm-stt` with separate STT, LLM and TTS model parameters.
- The custom server does not emit the full `bot-ready` handshake. The adapter uses the public transport APIs and sends the repository's `start_trigger` greeting event.
- Audio input is 16 kHz; assistant output is 24 kHz. Stop microphone tracks, queued audio, timers and transport connections when ending a session.
- Blank Custom Agent instructions must omit `system_instruction` so the backend defaults survive. Editable overrides are limited to 1,000 characters because the existing backend only accepts complete prompts shorter than 1,500 characters.
- Presets are Indian in context but respect the selected language and user preference. Keep the reservations/payment demos fictional; no real booking or payment is claimed.
- Keep previews visibly labeled as scripted browser speech. They do not measure or simulate either model's response quality or latency.
- Keep the compact animation and wider transcript. Respect reduced motion, retain accessible controls and prevent persona/engine changes during an active session.
- Keep open-source dependency names and license notices in code; visible UI branding remains Voice Studio.

## Check before continuing

```bash
npm test
npm run build
```

The build includes TypeScript checking. Contract checks verify both engines, every agent, custom prompt handling, backend defaults, URL validation and portrait assets. Real backend audio still needs an end-to-end check with your own running backend and credentials; a successful build is not proof of a completed Gemini call.

## Scope

This branch is an additive, standalone UI. It does not replace the original client's default page or deploy anything automatically. If you later integrate it into the original client or server, do that as a separate reviewed change so the existing app remains available.
