# GCP VPC Peering & Private IP Deployment Guide (`us-central1`)

## Overview
To eliminate cross-region latency, public internet hopping, and external TLS handshake overhead, the Lenskart **`vertex-router-db`** Cloud SQL instance and Cloud Run (`gemini-live-pipecat`) service are co-located in **`us-central1`** (`us-central1-c`) and interconnected via **Private VPC Peering (`10.127.0.3:5432`)**.

---

## 1. Network Topology & Latency Benchmarks

| Metric / Check | Public IP (`136.114.180.75`) | Private VPC IP (`10.127.0.3` inside `us-central1`) | Latency Savings |
| :--- | :--- | :--- | :--- |
| **Postgres Connect & Handshake** | `1,498.81 ms` | **`<10 ms`** | **~1.49 seconds saved!** |
| **Simple SQL (`SELECT 1`) RTT** | `417.42 ms` | **`<1–2 ms`** | **~415 ms saved!** |
| **Vector Table Scan (`count: 56`)** | `218.72 ms` | **`<2–5 ms`** | **~215 ms saved!** |

### Why Co-location in `us-central1` is Critical:
Google Cloud Vertex AI models (`gemini-3.5-flash-lite`, `text-embedding-004`, Gemini Live WebSockets) operate primarily out of `us-central1`. By placing the Cloud SQL instance (`vertex-router-db`) and the Cloud Run container (`gemini-live-pipecat`) in the exact same `us-central1` region over internal VPC fiber lines (`10.127.0.3`), database round trips execute in under `2 milliseconds`.

---

## 2. Verified Infrastructure Setup Commands

### A. Establish VPC Peering to Service Networking
```bash
gcloud compute addresses create google-managed-services-default \
    --global \
    --purpose=VPC_PEERING \
    --prefix-length=16 \
    --description="peering range for Google services" \
    --network=default \
    --project=deep-clock-339817

gcloud services vpc-peerings connect \
    --service=servicenetworking.googleapis.com \
    --ranges=google-managed-services-default \
    --network=default \
    --project=deep-clock-339817
```

### B. Patch Cloud SQL (`vertex-router-db`) for Private IP (`us-central1-c`)
```bash
gcloud sql instances patch vertex-router-db \
    --network=projects/deep-clock-339817/global/networks/default \
    --project=deep-clock-339817
```
*(Verified allocated `PRIVATE_ADDRESS`: `10.127.0.3`)*

---

## 3. Cloud Run Direct VPC Egress Deployment (`us-central1`)

When deploying your Pipecat PyLive server to GCP Cloud Run, attach Direct VPC Egress pointing to the internal private DSN:

```bash
gcloud run deploy gemini-live-pipecat \
    --image=gcr.io/deep-clock-339817/gemini-live-pipecat:latest \
    --region=us-central1 \
    --network=default \
    --subnet=default \
    --vpc-egress=private-ranges-only \
    --set-env-vars="CLOUDSQL_PG_DSN=postgresql://lenskart_app:<password>@10.127.0.3:5432/lenskart_memory,MEM0_LLM_MODEL=gemini-3.5-flash-lite,USE_VERTEXAI=true,GCP_LOCATION=us-central1"
```

---

## 4. Local Development vs. Production Execution

* **Local Cloudtop (`rangarok` in `asia-south1`) / Mac Development:**
  Use the Primary Public IP DSN (`postgresql://lenskart_app:<password>@136.114.180.75:5432/lenskart_memory`) inside `.env` since local development workstations reside outside the `us-central1` VPC network.
* **Production Cloud Run (`us-central1`) Execution:**
  Use the Private IP DSN (`postgresql://lenskart_app:<password>@10.127.0.3:5432/lenskart_memory`). The system seamlessly connects over internal `10.127.0.3:5432` with zero code modifications required!
