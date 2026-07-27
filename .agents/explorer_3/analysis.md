# DevOps, Git & Cloud Run Deployment Analysis: `lenskart-memory-bot`

**Repository Path**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat`  
**Analyst**: Explorer 3 (DevOps, Git & Cloud Run Deployment Specialist)  
**Date**: 2026-07-24  

---

## 1. Git Repository & Branching Audit

### Current Repository State
- **Active Branch**: `mem0-implementation`
- **Upstream Synchronization**: Branch is strictly up-to-date with `origin/mem0-implementation`.
- **Latest Commit**:
  - `9e39a26` — *feat: upgrade Mem0 embedder to gemini-embedding-001 with output_dimensionality 768 and SIMILARITY_THRESHOLD 0.65*
  - Modified files in HEAD commit: `server/memory_function.py` (+2 lines, -2 lines), `server/test_memory_function.py` (+1 line, -1 line).
- **Branch Existence Verification**:
  - Local branches existing: `main`, `mem0-implementation`, `19-acres`, `computer_use`, `feat/multi-tenant-vertex-memory`, `feature/groww-prompt-chaining`, `feature/native-audio-eval`, `july_functional_updates`, `krisp-testing`, `live_updates`, `memory_layer`, `pre_warm`, `rag`, `the_rider`, `try-krisp-vad`.
  - Remote branch existing: `remotes/origin/mem0-implementation`.
  - Result: Target branch `mem0-implementation` **already exists** both locally and on remote. The repository is currently sitting on this branch.
- **Working Tree Cleanliness**:
  - Untracked directories/files:
    - `.agents/` (agent orchestration working directory)
    - `server/data/` (runtime local Vector/SQLite DB artifacts)
    - `server/user_memories_default_user.json` (local execution side effect file)
  - Production code workspace is clean (no modified uncommitted changes in tracked python/client files).

---

## 2. Container & Cloud Run Deployment Infrastructure Inspection

### Docker Blueprint (`/Dockerfile`)
The application utilizes a multi-stage Docker build optimized for Python server and React client co-location:

1. **Stage 1 (`client`)**:
   - Base image: `node:18-slim`
   - Working Dir: `/app/client`
   - Steps: Copies `package*.json`, runs `npm install`, copies client code, executes `npm run build` (producing Vite bundle at `/app/client/dist`).
2. **Stage 2 (`server`)**:
   - Base image: `python:3.12`
   - Working Dir: `/app`
   - OS Dependencies installed: `build-essential`, `libjpeg-dev`, `zlib1g-dev`, `libsndfile1-dev` (required for Pipecat audio processing, WebRTC, PyTorch/libsndfile).
   - Python dependencies: `server/requirements.txt` installed with `--no-cache-dir`.
   - Asset copying:
     - Python source files copied from `server/` to `/app`.
     - Client bundle copied from `client` build stage to `/app/client/dist`.
     - Voice cloning model credentials: `server/voice_cloning_key_m.txt` $\rightarrow$ `/app/voice_cloning_key_m.txt` and `server/voice_cloning_key_f.txt` $\rightarrow$ `/app/voice_cloning_key_f.txt`.
   - Container Ports & Entrypoint:
     - Exposed Port: `7860`
     - Env Configuration:
       - `CLONE_TTS_VOICE_KEY_MALE="/app/voice_cloning_key_m.txt"`
       - `CLONE_TTS_VOICE_KEY_FEMALE="/app/voice_cloning_key_f.txt"`
       - `GOOGLE_ENTRYPOINT="python server.py"`
     - Start Command: `CMD ["python", "server.py"]`

### Google Cloud & Docker Exclusion Files
- **`.gcloudignore`**: Filters out `node_modules/`, `venv/`, `__pycache__/`, `.git`, `.env*`, and build assets from `gcloud builds submit` contexts.
- **`.dockerignore`**: Excludes root node modules, dist, and temporary artifacts.

### GCP Project & Regional Topology
- **GCP Project ID**: `deep-clock-339817`
- **Primary Deployment Region**: `us-central1` (chosen for sub-millisecond local network fiber connectivity to Google Vertex AI `gemini-3.5-flash-lite`, `gemini-embedding-001`, and Vertex AI live WebSockets).
- **VPC & Private IP Configuration** (`docs/VPC_PRIVATE_IP_DEPLOYMENT.md`):
  - Cloud SQL / AlloyDB Instance: `vertex-router-db` (Allocated private IP `10.127.0.3:5432` / `10.127.13.2:5432`)
  - Direct VPC Egress Subnet: `default` with `--vpc-egress=private-ranges-only`.

---

## 3. Operational Playbook & Exact Steps

Below are the exact executable commands required for both Git lifecycle management and Cloud Run deployment for service **`lenskart-memory-bot`**.

### Operational Action A: Git Branching, Staging, & Committing

1. **Verify or Switch to Branch `mem0-implementation`**:
   ```bash
   cd /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat
   
   # Confirm active branch (if already on mem0-implementation, skip checkout)
   git status
   
   # If creating fresh from main:
   # git checkout main
   # git pull origin main
   # git checkout -b mem0-implementation
   
   # If switching to existing local/remote branch:
   git checkout mem0-implementation
   git pull origin mem0-implementation
   ```

2. **Stage Targeted Files for Milestone M1 / M2**:
   *Caution: Do NOT commit runtime state directories like `server/data/` or `user_memories_*.json`.*
   ```bash
   git add server/memory_function.py server/test_memory_function.py
   ```

3. **Commit and Push to Remote**:
   ```bash
   git commit -m "feat: upgrade Mem0 embedder to gemini-embedding-001 with output_dimensionality 768 and SIMILARITY_THRESHOLD 0.65"
   git push origin mem0-implementation
   ```

---

### Operational Action B: Container Build & Cloud Run Service Deployment (`lenskart-memory-bot`)

1. **Build and Tag Image via Google Cloud Build**:
   ```bash
   cd /usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat
   
   gcloud builds submit \
       --tag gcr.io/deep-clock-339817/lenskart-memory-bot:latest \
       --project=deep-clock-339817 \
       --timeout=20m
   ```

2. **Deploy Service `lenskart-memory-bot` to Cloud Run (`us-central1`)**:
   Attach internal Direct VPC Egress to communicate with high-performance AlloyDB / Cloud SQL private DSN (`10.127.13.2` / `10.127.0.3`):
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

3. **Verify Deployment & Revision Health Status**:
   ```bash
   # Check service configuration and active URL
   gcloud run services describe lenskart-memory-bot \
       --region=us-central1 \
       --project=deep-clock-339817 \
       --format="yaml(status.url, status.latestReadyRevisionName, status.conditions)"

   # Stream startup logs to verify container initialized server.py on port 7860
   gcloud logging read \
       "resource.type=cloud_run_revision AND resource.labels.service_name=lenskart-memory-bot" \
       --limit=30 \
       --project=deep-clock-339817 \
       --format="value(textPayload,jsonPayload.message)"
   ```
