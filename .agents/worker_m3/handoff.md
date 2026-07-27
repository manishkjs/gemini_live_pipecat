# Milestone 3 Handoff Report: Cloud Run Deployment

## 1. Observation

### Command 1: Trigger Google Cloud Build
- **Command Executed**:
  ```bash
  cd /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat
  gcloud builds submit \
      --tag gcr.io/deep-clock-339817/lenskart-memory-bot:latest \
      --project=deep-clock-339817 \
      --timeout=20m
  ```
- **Verbatim Output & Result**:
  ```
  Successfully built 6166fd988da7
  Successfully tagged gcr.io/deep-clock-339817/lenskart-memory-bot:latest
  PUSH
  Pushing gcr.io/deep-clock-339817/lenskart-memory-bot:latest
  ...
  latest: digest: sha256:4df921f3dda3c9ef00f729136bd82d48784411e11b068e59bbeb5cb610455ef9 size: 3476
  DONE
  --------------------------------------------------------------------------------
  ID                                    CREATE_TIME                DURATION  SOURCE                                                                                           IMAGES                                                  STATUS
  24ca57a9-f19d-41ee-883f-325656d133dd  2026-07-24T05:17:57+00:00  2M58S     gs://deep-clock-339817_cloudbuild/source/1784870190.990158-afecedb8d2f04180bd0d856fb7df5707.tgz  gcr.io/deep-clock-339817/lenskart-memory-bot (+1 more)  SUCCESS
  ```

### Command 2: Deploy to GCP Cloud Run
- **Command Executed**:
  ```bash
  gcloud run deploy lenskart-memory-bot \
      --image=gcr.io/deep-clock-339817/lenskart-memory-bot:latest \
      --region=us-central1 \
      --project=deep-clock-339817 \
      --port=7860 \
      --network=default \
      --subnet=default \
      --vpc-egress=private-ranges-only \
      --memory=4Gi \
      --cpu=2 \
      --min-instances=1 \
      --max-instances=10 \
      --allow-unauthenticated \
      --set-env-vars="^;^GCP_PROJECT_ID=deep-clock-339817;GCP_LOCATION=us-central1;USE_VERTEXAI=true;MEM0_LLM_MODEL=gemini-3.5-flash-lite;MEM0_DB_PATH=./data/mem0_qdrant_db;CLOUDSQL_PG_DSN=postgresql://postgres:Lenskart_Alloy_2026_x9k2P!@10.127.13.2:5432/lenskart_memory;ALLOYDB_PG_DSN=postgresql://postgres:Lenskart_Alloy_2026_x9k2P!@10.127.13.2:5432/lenskart_memory"
  ```
- **Verbatim Output & Result**:
  ```
  Routing traffic...done
  Done.
  Service [lenskart-memory-bot] revision [lenskart-memory-bot-00015-d65] has been deployed and is serving 100 percent of traffic.
  Service URL: https://lenskart-memory-bot-853612069841.us-central1.run.app
  ```

### Command 3: Describe & Verify Service Status
- **Command Executed**:
  ```bash
  gcloud run services describe lenskart-memory-bot \
      --region=us-central1 \
      --project=deep-clock-339817 \
      --format="value(status.url)"
  ```
- **Verbatim Output**:
  ```
  https://lenskart-memory-bot-xg2ecdh5wq-uc.a.run.app
  ```
- **Revision and Status Overview (`gcloud run services describe --format="yaml(status,metadata)"`)**:
  - `latestCreatedRevisionName`: `lenskart-memory-bot-00015-d65`
  - `latestReadyRevisionName`: `lenskart-memory-bot-00015-d65`
  - `conditions`:
    - `type: Ready`, `status: 'True'`, `lastTransitionTime: '2026-07-24T05:23:39.090175Z'`
    - `type: ConfigurationsReady`, `status: 'True'`
    - `type: RoutesReady`, `status: 'True'`
  - `traffic`: 100% routed to `lenskart-memory-bot-00015-d65`

## 2. Logic Chain

1. **Build Step Validation**:
   - Upstream repo code was packaged by Google Cloud Build into container image `gcr.io/deep-clock-339817/lenskart-memory-bot:latest`.
   - Build ID `24ca57a9-f19d-41ee-883f-325656d133dd` finished in `2M58S` with `STATUS: SUCCESS` and tag digest `sha256:4df921f3dda3c9ef00f729136bd82d48784411e11b068e59bbeb5cb610455ef9`.
2. **Deployment Step Validation**:
   - The built container image was deployed to Cloud Run service `lenskart-memory-bot` in `us-central1` with configuration `--port=7860`, `--memory=4Gi`, `--cpu=2`, `--min-instances=1`, `--max-instances=10`, `--vpc-egress=private-ranges-only`, and required environment variables (`GCP_PROJECT_ID`, `GCP_LOCATION`, `USE_VERTEXAI`, `MEM0_LLM_MODEL`, `MEM0_DB_PATH`, `CLOUDSQL_PG_DSN`, `ALLOYDB_PG_DSN`).
   - Deployment output confirmed revision `lenskart-memory-bot-00015-d65` deployed serving 100% traffic.
3. **Verification Step Validation**:
   - Querying `gcloud run services describe` returned status `Ready: True`, configuration ready, routes ready, and URLs:
     - `https://lenskart-memory-bot-853612069841.us-central1.run.app`
     - `https://lenskart-memory-bot-xg2ecdh5wq-uc.a.run.app`

## 3. Caveats

- Database connections configured via `CLOUDSQL_PG_DSN` and `ALLOYDB_PG_DSN` (`10.127.13.2:5432`) rely on VPC network accessibility (`--network=default --subnet=default --vpc-egress=private-ranges-only`) inside GCP. Runtime database connectivity tests depend on backend VPC subnet routing.

## 4. Conclusion

Milestone 3 deployment of `lenskart-memory-bot` to Google Cloud Run in `us-central1` completed successfully. Container image built and published to `gcr.io/deep-clock-339817/lenskart-memory-bot:latest`, revision `lenskart-memory-bot-00015-d65` is live and active.

## 5. Verification Method

To independently verify the deployed Cloud Run service and revision health:
```bash
gcloud run services describe lenskart-memory-bot \
    --region=us-central1 \
    --project=deep-clock-339817 \
    --format="value(status.url)"
```
Expected output:
```
https://lenskart-memory-bot-xg2ecdh5wq-uc.a.run.app
```

Check detailed condition statuses:
```bash
gcloud run revisions list \
    --service=lenskart-memory-bot \
    --region=us-central1 \
    --project=deep-clock-339817
```
Invalidation conditions:
- Service status `Ready` condition is not `True`.
- Latest revision `lenskart-memory-bot-00015-d65` does not hold 100% traffic allocation.
