# Mem0 Text Embedding Configuration & Model Analysis

## 1. Executive Summary
This analysis identifies the locations of text embedding model configuration, output vector dimensions, vector store dimension settings, and similarity search threshold definitions in the `gemini_live_pipecat` repository.

The configuration currently targets Google Gemini embeddings with model `gemini-embedding-001`, a target embedding vector dimension of `768`, and a `SIMILARITY_THRESHOLD` of `0.65`.

---

## 2. Identified Configuration Locations

### 2.1 Embedder & Vector Store Configuration in `server/memory_function.py`
- **File Location**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/memory_function.py`
- **Global Similarity Threshold**:
  - **Line 25**: `SIMILARITY_THRESHOLD = 0.65`
  - **Usage**: Referenced in `process_extracted_fact` (Line 352) and `recall_user_memories` (Line 532 and Line 564) to filter vector recall matches by cosine similarity score.
- **Mem0 Configuration Function (`get_mem0_config()`)**:
  - **Pgvector Provider Config (Lines 37–44)**:
    ```python
    vector_store_config = {
        "provider": "pgvector",
        "config": {
            "connection_string": pg_dsn,
            "collection_name": "user_memories",
            "embedding_model_dims": 768
        }
    }
    ```
  - **Qdrant Fallback Provider Config (Lines 48–54)**:
    ```python
    vector_store_config = {
        "provider": "qdrant",
        "config": {
            "path": db_path,
            "embedding_model_dims": 768
        }
    }
    ```
  - **Embedder Configuration (Lines 76–83)**:
    ```python
    "embedder": {
        "provider": "gemini",
        "config": {
            "model": "gemini-embedding-001",
            "embedding_dims": 768,
            "api_key": api_key,
        }
    },
    ```
  - **Runtime Fallback Vector Store Dimensions (Lines 126 and 141)**:
    When PostgreSQL socket connection fails (Line 126) or pgvector initialization fails (Line 141), fallback Qdrant configurations also enforce `"embedding_model_dims": 768`.

### 2.2 Unit Test Assertions in `server/test_memory_function.py`
- **File Location**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/test_memory_function.py`
- **Imports (Lines 12–13)**: Imports `SIMILARITY_THRESHOLD` and `get_mem0_config` from `memory_function`.
- **Constant Assertion (Line 142)**:
  ```python
  self.assertEqual(SIMILARITY_THRESHOLD, 0.65)
  ```
- **Staging / Promotion Match Test (Lines 167–177)**:
  Note on inline comment mismatch: Line 170 comment says `# >= 0.80 SIMILARITY_THRESHOLD`, whereas code condition checks `>= SIMILARITY_THRESHOLD` (which is `0.65`).

### 2.3 AlloyDB / Cloud SQL Database Schema DDL in `server/init_alloydb.py`
- **File Location**: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/server/init_alloydb.py`
- **Vector Column Dimensions (Lines 48 and 50)**:
  ```sql
  CREATE TABLE IF NOT EXISTS user_memories (
      id UUID PRIMARY KEY,
      vector vector(768),
      payload JSONB,
      embedding vector(768),
      ...
  );
  ```
  Both `vector` and `embedding` pgvector columns are sized to `768` dimensions, matching `gemini-embedding-001` output.

---

## 3. Specific Exact Changes Required (Validation & Verification Plan)

To ensure smooth operation without 404 HTTP errors or dimensional mismatch errors:

1. **Text Embedding Model Name**:
   - Must be set to `"gemini-embedding-001"` in `config["embedder"]["config"]["model"]` in `server/memory_function.py` (Line 79).
   - *Rationale*: Alternate names like `"models/text-embedding-004"` or `"text-embedding-004"` trigger `404 Not Found` when called via Mem0's Gemini embedder provider if project/location authentication endpoints reject the Google AI v1/v1beta REST mapping. `gemini-embedding-001` works natively with Gemini REST/Vertex credentials.

2. **Output Dimensions (`768`)**:
   - Ensure explicit consistency across four places:
     - `server/memory_function.py` line 42 (`vector_store.config.embedding_model_dims` = `768`)
     - `server/memory_function.py` line 52 & lines 126, 141 (`qdrant` fallback `embedding_model_dims` = `768`)
     - `server/memory_function.py` line 80 (`embedder.config.embedding_dims` = `768`)
     - `server/init_alloydb.py` lines 48 & 50 (`vector(768)` in SQL DDL)

3. **Similarity Threshold (`0.65`)**:
   - In `server/memory_function.py` line 25: `SIMILARITY_THRESHOLD = 0.65`
   - In `server/test_memory_function.py` line 142: `self.assertEqual(SIMILARITY_THRESHOLD, 0.65)`
   - Fix inline test comment on line 170 of `server/test_memory_function.py` from `# >= 0.80 SIMILARITY_THRESHOLD` to `# >= 0.65 SIMILARITY_THRESHOLD` to avoid documentation drift.
