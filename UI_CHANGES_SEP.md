# Voice Studio on ui-changes-sep

Updated: 27 September 2026. Work stays on `ui-changes-sep` / `ui-changes-sep-premerge`; `main` is unchanged.

This branch now includes Voice Studio, backend persona/tool execution, provider usage accounting and scoped diagnostics. The original client remains available. There is no automatic deployment.

## Run locally

Use Node.js 22.13 or newer:

```bash
cd demos/voice-studio
npm ci
npm run dev
```

Run the backend with its configured Google credentials, then select its URL in Voice Studio Settings. For local development the backend normally listens at `http://localhost:7860`. Build `client/` for the original server-hosted interface and `/diagnostics` page.

Both Gemini Live and Cascade keep the existing `/connect` POST and protobuf websocket contract. Sample conversations use browser speech; they are scripted previews, not model or latency benchmarks. Custom Agent accepts your own instructions or leaves the backend default in place when blank.

## Current personas

| Agent | Demo role | Execution |
| --- | --- | --- |
| Meera | Debt Collector | Editable static preset |
| Kavya | Glass Buddy | Smartglasses demo tools; four Live prompt cards |
| Kabir | Storyteller | Editable static preset |
| Aisha | AI Companion | Editable static preset |
| Abhay | Car Negotiator | Server-owned rupee concession ladder (AeroNxt EV) |
| Ananya | Mutual Fund Advisor | Mock portfolio/NAV/SIP tools; four Live prompt cards |
| Pragya | Lamborghini Concierge | Model-selected Live cards; mock booking tool |
| Custom Agent | Your instructions | Existing basic implementation flow |

Pragya, Ananya and Kavya load cards on demand in Live and use the existing monolithic prompt choice in Cascade. Each journey declares its own phase IDs. Failed/pending card delivery leaves the last successfully delivered topic selected. Phase selection is model-driven; no transcript regex router is used.

The seven fictional portraits ship as 400×400 WebP files, approximately 105 KB combined. Original generated PNGs remain in git history; generation provenance and derivative settings are in `demos/voice-studio/docs/portrait-generation.json`.

## Where to edit

- `server/persona_prompt_cards/`: canonical session presets, root prompts and phase cards. Existing professional/signature styles are preserved. Custom instructions override editable personas; architecture-owned prompts remain locked.
- `server/persona_tools/`: execution engines and domain state. `server/persona_registry.py` is the application facade.
- `server/persona_identity.py`: shared canonical IDs and compatibility aliases for architecture, prompts and card lookup. Existing UI IDs and `wealth-manager` remain supported.
- `demos/voice-studio/src/lib/personas.ts`: display metadata, offline/older-backend preset fallback, journey phase IDs and sample conversations. Connected preset requests resolve through the backend and use its prompt preview.
- `demos/voice-studio/src/components/studio/`: persona picker, compact conversation display, transcript, settings and cost panel.
- `server/cascade_pricing.py` and `cascade_metering.py`: exact model/provider rates and provider-request accounting. See [pricing mechanisms and limits](docs/cascade-pricing.md).
- `server/turn_telemetry.py`, `processors/turn_telemetry.py` and `diagnostic_buffer.py`: lifecycle, explicit metric emission and bounded diagnostics. See [telemetry contract](docs/telemetry.md).
- `server/session_access.py`: expiring diagnostic/join capabilities and one-use instructions. `/connect` validates configuration before allocation and releases newly allocated sessions and voice profiles if setup fails.

## Integration constraints

Keep the observability icon, original UI shortcut, both session engines, custom instructions, compact animation, readable transcript and reduced-motion support. Stop microphone tracks, queued audio, timers and transport connections when a call ends.

A custom clone key (`Custom-Key`) or reference audio payload (`Custom-Live-Voice` via `custom_voice_audio`) is credential/media data sent in the POST body only. `Custom-Key` applies to Chirp 3 HD custom keys, `Clone-Male` / `Clone-Female` use configured server files, and Gemini 3.8 supports zero-shot reference-audio voice cloning (`Gemini-Clone-Male` server asset or `Custom-Live-Voice` upload) in both Gemini 3.8 Live and Cascade Gemini 3.8 TTS alongside its named-voice picker. Missing keys or reference audio fail explicitly. Live text-to-Chirp still requires a provider/model that supports text output; this change does not assert support on native-audio-only models.

Diagnostics require the call's `session_id` and in-memory `X-Session-Token`. Open the original standalone dashboard from an active call so it receives its capability. A bookmarked dashboard without that capability cannot read a call's data. Raw logs remain available, but numeric metrics never come from log parsing.

Custom instructions retain the existing 4,000 estimated-token editor limit. Generated websocket URLs carry a one-use connection handle; prompt text is stored briefly on the server. API/list-price estimates are not Cloud Billing invoices. Unpriced modalities (such as Live Avatar `VIDEO` tokens) are surfaced explicitly as unpriced token counts with a partial subtotal and total marked unavailable. Transcribe Live usage scope, continuous STT turn correlation and caller-perceived playback latency remain explicit verification gates.

`temp.md` has been removed from the tracked working tree. Root and server Docker ignore files and `.gcloudignore` retain exclusions for scratch/coordination files as defense-in-depth. Keep durable implementation contracts in `docs/`.

## Verification

```bash
# From the repository root, in your pinned backend environment (google-genai==2.25.0):
PYTHONPATH=server server/venv/bin/python -m unittest discover -s server/tests -p "test_*.py"
# From each frontend directory:
npm test       # Voice Studio (node --test tests/*.test.mjs)
npm run build  # Voice Studio, original client, and docs-site
```

The backend UI-contract test imports the real Voice Studio persona exports with Node.js 22.13+ and checks backend IDs, editor locks and phase cards. It skips explicitly if Node is absent; run the combined check with Node available before merging.

This checkpoint passed 305 backend tests (in `server/venv` with `google-genai==2.25.0`), 132 Voice Studio tests, and production builds for `demos/voice-studio`, `client`, and `docs-site`. Existing dependency deprecation and bundle-size warnings remain. Docker/gcloud are unavailable in the local cloudtop environment, so `Dockerfile` pins (`npm ci` and `google-genai==2.25.0` via `server/requirements.txt`) were verified against the pinned virtualenv without a container image build or deployment. Follow the real-call checklist in `docs/telemetry.md` before presenting the demo as production-verified.
