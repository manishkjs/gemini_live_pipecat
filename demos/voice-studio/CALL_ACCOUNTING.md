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

Pragya still uses the existing four phases and transcript-based forward-only
tracker. This repair does not modify her cards, booking rules, phase transitions
or prompt injection. Sending a new card appends to the existing conversation;
the highlighted phase is not proof that previous cards were evicted.

Design decisions to agree before changing the architecture:

1. Should the active card follow the current topic and allow returning to an
   earlier phase, while completed booking milestones remain recorded?
2. Should automatic transcript reinsertion after inferred compression be removed
   from this experiment? It can reintroduce context and obscure the savings.
3. What monolithic-prompt baseline and common script should be used to measure
   savings? A smaller initial prompt alone does not establish lower full-call cost.

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
