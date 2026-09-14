---
title: Deployment
description: Ship a Gemini Live voice backend to Cloud Run with HTTPS, WSS, and CORS.
---

A voice backend is a **long-lived WebSocket** server. That one fact drives most
deployment decisions.

## Containerize

Package your backend as a container that listens on a single port and speaks
WebSocket. Keep the image lean — install only what the server needs.

## Deploy to Cloud Run

```bash
gcloud run deploy voice-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --timeout 3600 \
  --session-affinity \
  --cpu 2 --memory 2Gi
```

What matters for real-time voice:

- **`--timeout 3600`** — a voice session is one long request. The default 5-minute
  timeout will cut calls off mid-conversation.
- **`--session-affinity`** — keep a client pinned to the same instance for the life
  of the WebSocket.
- **CPU and memory** — audio processing is CPU-bound; provision accordingly and
  load-test before launch.
- **Concurrency** — each active call consumes an instance slot. Size max instances
  to your expected concurrent-call peak.

## When Cloud Run is not enough

Cloud Run is the fastest way to ship, and it is genuinely fine for many voice
workloads. But a voice session is **stateful**, and three Cloud Run behaviors
work against that:

- **Scale-to-zero cold starts** add seconds to the first call after idle.
- **Reconnects can land on a different instance.** Session affinity is
  best-effort; if in-memory session state does not follow the socket, the
  reconnect resumes into an empty context.
- **Request timeouts** cap session length even at the maximum.

:::tip[Move to GKE when reconnect correctness matters]
Deploy on GKE with `sessionAffinity: ClientIP` to pin a client to a specific pod
for the life of the WebSocket, and scale with an HPA driven by **active socket
count** rather than CPU. A voice pod can be CPU-idle while saturated with calls.
:::

The durable fix, on either platform, is to **stop keeping session state only in
process memory**. Persist the resumption handle and conversation state in Redis
or a database keyed by the stable session ID, and any instance can pick up a
reconnect.

## Sizing

Each active call occupies a slot for its entire duration — this is not
request/response traffic where concurrency multiplies throughput.

```text
instances_needed ≈ peak_concurrent_calls / concurrency_per_instance
```

Set `--concurrency` to what one instance can genuinely carry (audio processing is
CPU-bound; measure it), keep `--min-instances 1` to avoid cold starts on the
first call, and load-test at your real peak before launch.

## HTTPS and WSS

A browser on an HTTPS page can only open a **secure** WebSocket (`wss://`). Serve
the backend over HTTPS so it returns `wss://` URLs. Cloud Run gives you a managed
HTTPS endpoint automatically.

## CORS

If your UI is hosted on a different origin than the backend (it usually is),
configure the backend to **allow that origin**. A missing CORS allowance is the
most common "it works locally but not in production" bug.

## Credentials

**On Vertex AI (recommended), you ship no API key at all.** Cloud Run and GKE
workloads authenticate as their **service account** through Application Default
Credentials — grant that account `roles/aiplatform.user` and the SDK finds the
credentials automatically. Nothing to mount, nothing to leak.

```bash
gcloud run deploy voice-backend \
  --service-account="voice-backend@$PROJECT_ID.iam.gserviceaccount.com"
```

Only the **AI Studio** path needs an API key — and even then it belongs in Secret
Manager, never in the image:

```bash
gcloud run deploy voice-backend \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest"
```

## Keep the docs out of the app image

This documentation site is deployed **separately** to GitHub Pages and is
excluded from the application container and Cloud Build context. Your runtime
image should contain only the server (and, if applicable, the built client) —
nothing else.
