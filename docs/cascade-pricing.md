# Cascade API pricing and verification

Reviewed 2026-09-13 UTC. This feature reports public USD API estimates for one call. It does not report an invoice or allocate account credits, free tiers, negotiated discounts, hosting, tax, cache-storage charges or external tool fees.

## Reviewed rate card

All token rates below are USD per million tokens. LLM prices use standard on-demand global requests; output includes reasoning.

| Vertex LLM | Text input | Audio input | Output | Cached text / audio |
| --- | ---: | ---: | ---: | ---: |
| Gemini 3.5 Flash-Lite | 0.30 | 0.30 | 2.50 | 0.03 / 0.03 |
| Gemini 3.7 Flash, through 2026-12-31 | 0.75 | 0.75 | 3.75 | 0.075 / 0.075 |
| Gemini 3.7 Flash, from 2027-01-01 | 1.50 | 1.50 | 7.50 | 0.15 / 0.15 |
| Gemini 2.5 Flash | 0.30 | 1.00 | 2.50 | 0.03 / 0.10 |
| Gemini 2.5 Flash-Lite | 0.10 | 0.30 | 0.40 | 0.01 / 0.03 |

The rate resolver applies the published 10% non-global premium for these 3.x LLMs using the actual service location and request date. [Google Vertex pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

| Speech service | Input | Output |
| --- | ---: | ---: |
| Gemini 3.5 Transcribe Live | $3.50 / million audio tokens | $21 / million text tokens |
| Gemini 3.1 Flash TTS Preview | $1 / million text tokens | $20 / million audio tokens |
| Gemini 2.5 Pro TTS | $1 / million text tokens | $20 / million audio tokens |
| Gemini 2.5 Flash / Flash-Lite Preview TTS | $0.50 / million text tokens | $10 / million audio tokens |
| Chirp 3 HD named voice | $30 / million characters | — |
| Instant Custom Voice cloning key | $60 / million characters | — |
| Cloud Speech v2 standard recognition, including Chirp 3 | $0.016 / billed audio minute, first monthly tier | — |

Sources: [Transcribe Live paid pricing](https://ai.google.dev/gemini-api/docs/pricing), [Google TTS pricing](https://cloud.google.com/text-to-speech/pricing), [Cloud Speech pricing](https://cloud.google.com/speech-to-text/pricing). Cloud Speech's higher-volume tiers are account-wide and are not inferred from one call. Cloned voices use their own SKU; the named Chirp voice rate is not applicable.

## How this implementation measures

- `server/cascade_pricing.py` owns rates, Decimal arithmetic and a ledger per session. Each provider generation/request gets its own key. Streaming updates replace that request's snapshot; separate requests add. A conversational turn may contain several LLM tool generations and several TTS requests.
- LLM and Gemini TTS usage is captured at the SDK stream boundary, including final usage-only chunks. Final counters must reconcile: `total = prompt + candidates + thoughts`. Cached tokens are a subset of prompt tokens and are subtracted before applying the ordinary input rate. Thinking is charged once. Missing modality data for different audio/text rates makes that request unpriced.
- Cloud Speech uses `metadata.total_billed_duration`, including metadata-only responses. Streaming request totals replace earlier totals under the same key. Missing protobuf duration is unknown, not zero. An active/interrupted stream cannot claim a complete total. The [Speech v2 RPC contract](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2) also exposes billing metadata on synchronous recognition responses.
- Cloud TTS counts the actual submitted, post-filter synthesis text after successful stream completion. It does not infer cost from transcript display or speaker playback. Interrupted requests with unconfirmed billing stay partial.
- **Skip STT still invokes `AudioAccumulator._run_parallel_stt` for display transcripts.** Those Cloud Speech requests are charged in the STT row, alongside the LLM's audio-input usage. Empty transcription is not proof of zero cost. This patch preserves that existing behavior.
- The browser accepts only matching-session snapshots with increasing revisions. It displays STT, LLM and TTS separately, with a known subtotal and explicit missing-usage reasons. `complete` means the recorded requests have priceable usage so far; it is not a call-closed or invoice-final flag. Live pricing and latency calculations are separate.

## Open production gate: Transcribe Live

Rates are verified, but this checkout has no authenticated runtime trace establishing whether this model's `usage_metadata` messages are cumulative for a connection or incremental per committed segment. The [Transcribe Live guide](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe) does not specify that metering contract. The published blended cost per audio-minute is not used as a billing unit.

The adapter therefore captures usage metadata and exposes the rate, but deliberately leaves its STT amount unavailable. Do not enable `scope_verified` merely because counters are present. Establish the aggregation boundary and final-versus-interim semantics first, then implement that adapter and its trace-based regression test. Until then, Transcribe Live Cascade calls have a **partial total**.

## Local verification before production use

1. Run `PYTHONPATH=server python -m pytest -q server/tests/test_cascade_pricing.py` with the repo's pinned SDK dependencies and pytest installed. Run `npm test` and `npm run build` inside `demos/voice-studio`.
2. Run short calls using both Transcribe Live providers, Chirp 3 STT, Flash-Lite LLM, Gemini 3.1 TTS, named Chirp and each cloned voice. Verify actual model, provider, region and SKU in the expanded cost panel. Include a tool follow-up, multi-sentence reply, empty transcription, barge-in and reconnect.
3. For Transcribe Live, retain timestamped **usage metadata only**, connection boundaries and final-transcript event markers for two utterances separated by silence, then a reconnect. The `Cascade usage` log includes session and request keys. Do not share credentials, audio or transcript text. Use this to establish counter scope and capture a fixture.
4. Reconcile completed provider requests against billing exports for an isolated test window. Confirm that final usage reaches the UI before disconnect. Browser telemetry is not durable billing storage; persist final call records separately before using this feature for invoicing or spend enforcement.

Automated checks exercise the actual provider wrapper methods with fake streams and actual Google SDK tool-schema conversion. No paid voice session or Cloud Billing reconciliation was performed in this workspace.
