# Voice Studio on ui-changes-sep

Updated: 13 September 2026. Work stays on `ui-changes-sep`; main is unchanged.

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
| Ranvir | Car Negotiator | Server-owned concession ladder |
| Ananya | Mutual Fund Advisor | Mock portfolio/NAV/SIP tools; four Live prompt cards |
| Pragya | Lamborghini Concierge | Model-selected Live cards; mock booking tool |
| Custom Agent | Your instructions | Existing basic implementation flow |

Pragya, Ananya and Kavya load cards on demand in Live and use the existing monolithic prompt choice in Cascade. Each journey declares its own phase IDs. Failed/pending card delivery leaves the last successfully delivered topic selected. Phase selection is model-driven; no transcript regex router is used.

The seven fictional portraits ship as 400×400 WebP files, approximately 105 KB combined. Original generated PNGs remain in git history; generation provenance and derivative settings are in `demos/voice-studio/docs/portrait-generation.json`.

## Where to edit

- `server/persona_prompt_cards/`: canonical session presets, root prompts and phase cards. Existing professional/signature styles are preserved. Custom instructions override editable personas; architecture-owned prompts remain locked.
- `server/persona_tools/`: execution engines and domain state. `server/persona_registry.py` is the application facade.
- `demos/voice-studio/src/lib/personas.ts`: display metadata, offline/older-backend preset fallback, journey phase IDs and sample conversations. Connected preset requests resolve through the backend and use its prompt preview.
- `demos/voice-studio/src/components/studio/`: persona picker, compact conversation display, transcript, settings and cost panel.
- `server/cascade_pricing.py` and `cascade_metering.py`: exact model/provider rates and provider-request accounting. See [pricing mechanisms and limits](docs/cascade-pricing.md).
- `server/turn_telemetry.py`, `processors/turn_telemetry.py` and `diagnostic_buffer.py`: lifecycle, explicit metric emission and bounded diagnostics. See [telemetry contract](docs/telemetry.md).

## Integration constraints

Keep the observability icon, original UI shortcut, both session engines, custom instructions, compact animation, readable transcript and reduced-motion support. Stop microphone tracks, queued audio, timers and transport connections when a call ends.

A custom clone key is credential text sent in the POST body only. It applies only to Custom-Key; male/female clones use configured server files. Missing keys fail explicitly. Cascade cloning requires Chirp 3 HD, and Gemini TTS has its own named-voice picker. Live text-to-Chirp still requires a provider/model that supports text output; this change does not assert support on native-audio-only models.

Diagnostics require the call's `session_id` and in-memory `X-Session-Token`. Open the original standalone dashboard from an active call so it receives its capability. A bookmarked dashboard without that capability cannot read a call's data. Raw logs remain available, but numeric metrics never come from log parsing.

Custom instructions retain the existing 4,000 estimated-token editor limit. Generated websocket URLs carry a one-use connection handle; prompt text is stored briefly on the server. API/list-price estimates are not Cloud Billing invoices. Transcribe Live usage scope, continuous STT turn correlation and caller-perceived playback latency remain explicit verification gates.

## Verification

```bash
# From the repository root, in your backend environment:
PYTHONPATH=server python -m pytest -q server/tests
# From each frontend directory:
npm test       # Voice Studio
npm run build  # Voice Studio and original client
```

This checkpoint passed 167 backend tests plus two subtests, 100 Voice Studio tests and both production builds. Existing dependency deprecation and bundle-size warnings remain. The task browser could not open the local preview (`ERR_BLOCKED_BY_CLIENT`), so no full browser visual/microphone validation is claimed. Follow the real-call checklist in `docs/telemetry.md` before presenting the demo as production-verified.
