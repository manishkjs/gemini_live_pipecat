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

## HTTPS and WSS

A browser on an HTTPS page can only open a **secure** WebSocket (`wss://`). Serve
the backend over HTTPS so it returns `wss://` URLs. Cloud Run gives you a managed
HTTPS endpoint automatically.

## CORS

If your UI is hosted on a different origin than the backend (it usually is),
configure the backend to **allow that origin**. A missing CORS allowance is the
most common "it works locally but not in production" bug.

## Secrets

Never bake API keys into the image. Mount them at runtime:

```bash
gcloud run deploy voice-backend \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest"
```

## Keep the docs out of the app image

This documentation site is deployed **separately** to GitHub Pages and is
excluded from the application container and Cloud Build context. Your runtime
image should contain only the server (and, if applicable, the built client) —
nothing else.
