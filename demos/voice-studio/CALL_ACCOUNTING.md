## Call accounting and Pragya demo validation

Run the studio and backend from the same branch revision. Response identities
are added by the backend and consumed by the studio; an older backend can still
provide session totals, but the studio will not guess which reply owns late
usage without an identity.

- Each new call receives a fresh session ID. Starting twice cannot open two calls.
- Each finalized model response has a response ID and a stable usage event ID.
- The studio keeps one ledger entry per response/service. Replayed events are
  ignored; an explicitly newer revision replaces the previous entry.
- Call tokens sum provider-reported request totals. Previous conversation context
  can be processed again in subsequent requests, so this number is not the size
  of the current context window.
- Text/audio input/output breakdowns retain unattributed tokens. Partial output
  metadata is included in the estimate rather than silently dropped.
- Dollar amounts use the configured list-price rate cards. Missing text/audio
  attribution produces a range; invalid or unsupported pricing is unavailable.
  These estimates exclude external TTS, other services and billing adjustments.
- Latency and usage update an identified response, including if text arrives
  later. Uncorrelated legacy metrics remain session-level observations.
- Observability uses the same call counters, including a legitimate zero, and
  resolves the trace by session ID.

The call ledger lives in the current browser session. It is not a billing export
or a durable server-side accounting database. Usage not reported by the provider
or lost when the connection ends cannot be reconstructed from transcript text.

### Comparing prompt approaches

Use the same model/provider, voice, language, tools, compression settings and
roughly the same spoken script for each comparison. Start a new call each time.
Let the final reply complete before stopping, so its final usage can arrive.
Record call tokens, input/output breakdown, duration and any cost range.

Pragya has four phases: Opening in the root instruction, plus Discovery, Lounge
Visit, and Visit Confirmed cards. Gemini chooses `switch_phase(phase_id, ...)`
when the conversation changes. The server sends that card before acknowledging
the blocking tool call, then emits the existing phase event. No caller transcript
is parsed for phase selection or PIN extraction. Known booking fields come from
structured tool arguments; a product detour retains them and the booking record.
Pragya also bypasses the adapter's short-interruption repeat rule: Gemini handles
short agreements such as “आप बताइए” using the active card's conversation rules.

Every card begins with a current-phase override. New cards append to conversation
history; earlier cards are not evicted by this wording. The UI reports a successful
SDK write as **sent**, not proof that a particular audio response followed it.
Tool declarations, tool calls/results, and previously retained cards also consume
context. A smaller opening does not establish lower full-call cost.

The transport uses `send_client_content(..., turn_complete=False)` for quiet
Gemini 2.5 cards and realtime text for Gemini 3 mid-call cards. Blocking tools
pause generation until their function response. The integration tests verify
local send-before-response ordering with the provider boundary mocked. Actual
provider timing and speech behavior still require live calls.
[Live tools](https://ai.google.dev/gemini-api/docs/live-api/tools),
[Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

### Live demo script

1. Say “हाँ, दो मिनट बात करते हैं.” Expect Gemini to call `switch_phase` for Discovery.
2. Ask about a car. Say “आप बताइए” after it offers an explanation; it should answer,
   without repeating the permission question or fetching the same card every turn.
3. Say “बुक कर दो, मेरा PIN 560048 है.” Expect Lounge Visit with the PIN included;
   only day and time should remain to collect.
4. Detour: “पहले Urus के बारे में बताओ.” Expect Discovery, with the PIN retained.
5. Return to arranging the visit, provide a clear day/time, and agree to the readback.
   Expect a successful booking tool result, then Gemini's explicit switch to Booked.
6. Ask about a car again. Expect Discovery while the confirmed booking remains visible.
7. Try unclear audio: expect one clarification, not the previous question repeated.

The booking backend remains the existing in-memory demo stub, with sample lounge
records and prefix-based location mapping. It does not reserve inventory, send
messages, or cancel/reschedule appointments. Treat the implementer's repetition
transcripts as reported evidence; their proposed root cause is a hypothesis,
not a trace proving which instruction the model attended to.

For the cost comparison, use an agreed monolithic baseline and keep transcript
reinsertion/compression settings identical. No measured savings are claimed yet.

### Regression checks

From `demos/voice-studio`: `npm test` and `npm run build`.

From the repository root, with the backend test dependencies installed:

```sh
PYTHONPATH=server python -m pytest -q \
  server/tests/test_response_accounting.py \
  server/tests/test_negotiation.py \
  server/tests/test_persona_registry.py \
  server/tests/test_supercar_phases.py \
  server/tests/test_supercar_cards.py \
  server/tests/test_supercar_tools.py \
  server/tests/test_agent_live_pragya.py
```

The response-accounting tests use the real adapter methods with provider/media
boundaries mocked. They do not replace a live microphone/provider smoke test.
