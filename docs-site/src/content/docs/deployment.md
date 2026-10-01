---
title: Cloud Run & GKE Production Deployment
description: Deploying stateful, long-lived Gemini Live WebSocket servers on Google Cloud Run and GKE.
---

Deploying a real-time bidirectional voice server is fundamentally different from deploying stateless REST APIs. Each active voice call holds an open WebSocket connection, continuous audio buffers, and asyncio tasks for 5 to 60 minutes.

---

## 1. Cloud Run deployment checklist for stateful WebSockets

Standard Cloud Run defaults (like CPU throttling between requests and 300-second request timeouts) will break live voice calls unless you override them explicitly:

| Setting | Default | Required for Gemini Live | Why |
| :--- | :--- | :--- | :--- |
| **CPU Allocation** | CPU only allocated during request processing | **`--no-cpu-throttling` (CPU always allocated)** | Ensures background asyncio tasks, tool callbacks, and heartbeats never freeze between audio frames. |
| **Request Timeout** | `300s` (5 minutes) | **`--timeout=3600`** (60 minutes) | Prevents Cloud Run's front-end load balancer from severing active calls at the 5-minute mark. |
| **Session Affinity** | Disabled | **`--session-affinity`** | Routes reconnect attempts (`sessionResumption`) back to the same container instance holding in-memory call state. |
| **Concurrency** | `80` requests/instance | **`--concurrency=15` to `25`** (for DSP/Pipecat) | Real-time audio resampling and VAD per call consume continuous CPU/RAM; capping concurrency prevents audio jitter under load. |
| **Min Instances** | `0` (scale to zero) | **`--min-instances=1`** (or higher) | Eliminates 2–4 second cold-start delays when an inbound phone call rings. |

### Reference `gcloud run deploy` command

```bash
gcloud run deploy gemini-live-voice-gateway \
  --source . \
  --region us-central1 \
  --no-cpu-throttling \
  --timeout 3600 \
  --session-affinity \
  --concurrency 20 \
  --cpu 2 \
  --memory 2Gi \
  --min-instances 1 \
  --max-instances 50 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=your-project-id,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=TRUE"
```

---

## 2. Regional co-location (`us-central1`)

Every millisecond of network distance between your media gateway and the Vertex AI Gemini Live endpoint adds directly to turn latency:
- **Always deploy your Cloud Run / GKE backend in `us-central1`** when connecting to the `us-central1` Vertex AI Live API endpoint.
- Use **WebRTC edge relays** (such as Daily or LiveKit global PoPs) or **Twilio Media Streams regional edges** to terminate the caller's last-mile audio close to the user, then traverse Google's backbone to `us-central1`.

---

## 3. Graceful container draining (`SIGTERM`)

When you deploy a new revision or Cloud Run scales down an instance, Google Cloud sends a `SIGTERM` signal and gives the container up to **10 seconds** before `SIGKILL`.

For zero-downtime deployments:
1. Catch `SIGTERM` in your FastAPI / asyncio server.
2. Mark readiness probes as unhealthy so no *new* calls are routed to the draining instance.
3. Proactively trigger a clean session checkpoint (`sessionResumptionUpdate.newHandle`) or persist the active `FactStore` to Redis so reconnecting clients resume without losing context.

---

## 4. IAM permissions for Vertex AI Live API

Your Cloud Run runtime service account needs the **Vertex AI User** role (`roles/aiplatform.user`) to open `BidiGenerateContent` WebSocket sessions:

```bash
gcloud projects add-iam-policy-binding your-project-id \
  --member="serviceAccount:your-runtime-sa@your-project-id.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```
