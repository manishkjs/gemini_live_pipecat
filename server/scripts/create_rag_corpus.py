import sys
import vertexai
from vertexai.preview import rag

project_id = "deep-clock-339817"
regions = ["asia-south1", "us-west1", "europe-west1", "europe-west4"]

print("Starting Vertex AI RAG Corpus provisioning...", flush=True)

created_corpus = None
active_region = None

for reg in regions:
    print(f"--> Attempting RAG Corpus creation in region: {reg}...", flush=True)
    try:
        vertexai.init(project=project_id, location=reg)
        corpus = rag.create_corpus(
            display_name=f"ldc_p2p_kb_{reg}",
            description="Cymbal Lending P2P Knowledge Base from Google Sheet",
            vector_db=rag.RagManagedDb(),
        )
        print(f"✅ SUCCESS! Created corpus in {reg}: {corpus.name}", flush=True)
        created_corpus = corpus
        active_region = reg
        break
    except Exception as e:
        print(f"❌ Failed in {reg} with RagManagedDb: {e}", flush=True)
        try:
            corpus = rag.create_corpus(
                display_name=f"ldc_p2p_kb_{reg}",
                description="Cymbal Lending P2P Knowledge Base from Google Sheet",
            )
            print(f"✅ SUCCESS (default db) in {reg}: {corpus.name}", flush=True)
            created_corpus = corpus
            active_region = reg
            break
        except Exception as e2:
            print(f"❌ Failed in {reg} with default db: {e2}", flush=True)

if created_corpus and active_region:
    print(f"Importing files into {created_corpus.name} in {active_region}...", flush=True)
    try:
        resp = rag.import_files(
            corpus_name=created_corpus.name,
            paths=["gs://genai-rangarok-stuff/rag/ldc_p2p_kb.csv"],
            chunk_size=512,
            chunk_overlap=50,
        )
        print(f"✅ SUCCESS! Import Response: {resp}", flush=True)
        print(f"FINAL_RAG_CORPUS_ID={created_corpus.name}", flush=True)
        print(f"FINAL_RAG_LOCATION={active_region}", flush=True)
    except Exception as ie:
        print(f"❌ Import error: {ie}", flush=True)
else:
    print("❌ Could not create corpus in any region.", flush=True)
