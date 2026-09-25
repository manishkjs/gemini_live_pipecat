# Session telemetry contract

Updated: 2026-09-13 UTC. Applies to `ui-changes-sep`.

## What the numbers mean

| Field | Meaning | Availability |
| --- | --- | --- |
| `value_ms` for LLM / TTS / Live | Provider wrapper's request-to-first-output timer on a monotonic server clock | Structured event; can exist without a conversational turn ID |
| `vad_stop_to_first_server_audio_ms` | First audio emitted immediately before the server output transport, minus the observed VAD-stop event | Only when both timestamps belong to the same captured turn |
| `estimated_speech_end_to_first_server_audio_ms` | Above interval plus the configured VAD stop padding | Explicit estimate, with an `estimation_method`; not measured acoustic speech end |
| Caller-perceived latency | Speech end to actual browser playback | Unavailable: no verified playback instrumentation/clock contract |
| Continuous STT latency | Final transcript correlated with its originating utterance | Unavailable until the provider receive loop can preserve verified utterance identity |

Stage TTFBs are **never summed**, paired by array position, or filled with synthetic zero/120/180 ms values. The compatibility `total_turnaround` summary is empty. Very slow requests are no longer discarded by the former 15-second cap. Each legitimate TTS request remains a separate observation, including multiple sentences in one conversational turn.

## Correlation and lifecycle

`TurnBoundaryProcessor` owns the per-call turn counter. Local VAD stop creates one turn; later semantic stop events do not create another. Turn zero is the synthetic greeting and has no VAD interval. Frame metadata and the provider processing ContextVar carry the captured `Turn` object; audio is tagged before entering a long-lived output queue.

A new LLM context created by an aggregator is **not evidence** that it belongs to the current turn. Unknown STT/tool origins remain unknown instead of reading `tracker.current` when a delayed callback arrives. Their independent LLM/TTS request timers can still be recorded with `turn_id=null` and `attribution=unavailable`; they cannot produce a VAD-to-audio interval. This deliberately leaves most current Cascade turn intervals unavailable until the continuous STT/aggregator boundary supplies reliable origins.

Live reserves an output origin at the input-stop boundary, before its first output chunk. A later input cannot steal that reservation while the previous provider response is awaiting its ordered completion/interruption acknowledgement. The existing response ID still identifies usage; billing requests and conversational turn IDs serve different purposes.

Barge-in closes the previous turn as `interrupted`; disconnect closes an open turn as `abandoned`. Terminal turns cannot reopen, accept late audio, or acquire completed latency fields. A tool-only generation does not finish a spoken turn. Native Live ordering and actual transport queues still need the real-call checks below; unit tests do not establish provider behavior.

## Retention and access

- One process-wide `deque(maxlen=2000)` stores latency observations. Another bounded deque retains 1,500 diagnostic records. A long concurrent call can evict another call's records; missing records are not proof they never existed.
- All diagnostic reads, clears and trace lookups require a nonempty `session_id` and the matching `X-Session-Token`. Missing scope returns 422; invalid/missing capability returns 403.
- `/connect` returns a viewer capability and a separate five-minute, single-use websocket join. A supplied session ID cannot overwrite an existing owner. Direct websocket clients receive an isolated anonymous scope.
- Both UIs retain capabilities in memory and send them in headers. The original standalone dashboard receives access from its opener via an exact-window/exact-origin message handshake. Capabilities are not placed in dashboard URLs or browser storage.
- Access records expire after four hours and are capped at 1,000 per process. Unclaimed custom/preset prompts expire with them and are consumed once at connection; prompt text is no longer added to a generated websocket URL.
- `/connect` validates its body and prepares instructions before issuing a session. Rejected requests consume no session slots or voice profiles. If response preparation fails after allocation, both newly created handles are released; an existing owner's session is never removed by a rejected duplicate-ID request.
- Raw Loguru capture remains to preserve the existing log console. It captures structured message/level fields only; it does **not** extract metrics or tokens from text. The standard-logging global interceptor and all metric parsers/debounce state are removed.
- Standalone token counters use retained structured provider snapshots, replacing duplicate response snapshots. They are labelled retained responses, not a complete billing ledger. The per-call cost ledger remains separate.

These are process-local demo diagnostics, not account authentication, durable audit storage, cross-worker routing or invoice records. Deployments with multiple workers need session affinity/shared state appropriate to their hosting design.

## Startup and verification

Heavy media/provider imports and existing runtime compatibility patches are deferred to the selected pipeline factory. A fresh-process test asserts `server` imports without `pipecat`, `grpc`, `google.genai`, `vertexai` or Cloud Speech. The measured import in the task environment was about 0.22 seconds; it is not a deployment SLO or an explanation for port conflicts.

Tests cover explicit units, repeated fast TTS events, cross-session access/clears, bounded eviction, two-turn interruption, async task/audio queue origins, unattributed downstream/upstream context, delayed semantic VAD events, first-audio completion and disconnect cleanup. Real provider classes import with Pipecat 1.2.1 and Google GenAI 2.4.0; no paid call was made.

Before presenting latency or cost as production-complete, run:

1. Native Live, Live text → Chirp, normal Cascade, and Skip STT with a short call and a tool follow-up.
2. Interrupt before first audio and during playback, then disconnect during synthesis. Late A must not populate B or create a completed A interval.
3. Two concurrent calls: each browser can read and clear only its own diagnostics; reconnect uses fresh access. Open the original dashboard from a call.
4. Verify per-request LLM/TTS samples survive multi-sentence replies; unattributed STT/Cascade intervals remain unavailable.
5. Reconcile provider usage with billing as described in [cascade-pricing.md](cascade-pricing.md). Transcribe Live usage scope remains a separate unresolved gate.
