import asyncio
import os
import re
from loguru import logger
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
import vertexai
from vertexai.preview import rag
import google.auth

# RAG Configuration Helpers
def get_rag_config():
    """Dynamically fetch RAG configuration."""
    corpus_id = os.getenv("RAG_CORPUS_RESOURCE_ID")
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    
    def extract_location(cid):
        if not cid: return "us-central1"
        match = re.search(r"locations/([^/]+)/ragCorpora", cid)
        return match.group(1) if match else "us-central1"
    
    location = extract_location(corpus_id)
    return corpus_id, project_id, location

# Lazy initialization flag
_vertex_initialized = False

def initialize_vertex_if_needed():
    """Initialize Vertex AI dynamically if not already done."""
    global _vertex_initialized
    if _vertex_initialized:
        return True
    
    corpus_id, project_id, location = get_rag_config()
    
    try:
        if project_id and location:
            vertexai.init(project=project_id, location=location)
            _vertex_initialized = True
            logger.info(f"[RAG] Vertex AI initialized - Project: {project_id}, Location: {location}")
            return True
        else:
            logger.warning(f"[RAG] Missing config for init - Project: {project_id}, Location: {location}")
            return False
    except Exception as e:
        logger.error(f"[RAG] Failed to initialize Vertex AI: {e}")
        return False

# Schema definition
search_knowledge_base_schema = FunctionSchema(
    name="search_knowledge_base",
    description=(
        "Retrieve information from knowledge base with first-person query matching. "
        "Use for: Definitions, 'How it works', Company info, Safety/Risk questions, Objections."
    ),
    properties={
        "query_for_vector_search": {
            "type": "string",
            "description": (
                "The search query rewritten in FIRST-PERSON PERSPECTIVE. CRITICAL RULES: "
                "1. REMOVE ALL brand terms (LenDenClub/Lendenclub) by converting to first-person: 'LenDenClub' -> 'you/your'. "
                "2. Convert third-person to first-person: 'LenDenClub's NPA' -> 'your NPA', 'in LenDenClub' -> remove or 'here'. "
                "3. Only translate Hindi to English - maintain user's intent exactly. "
                "4. For pronouns (it, this, that, tumhara, uska), use conversation context to resolve reference. "
                "5. NEVER add brand/domain terms that user didn't mention. "
                "Examples: "
                "'NPA rate of Lendenclub' -> 'what is your NPA rate', "
                "'How to invest in LenDenClub' -> 'how can I invest', "
                "'Lendenclub ka disbursement' -> 'what is your disbursement value', "
                "'What services does LenDenClub provide' -> 'what services do you provide', "
                "'tumhara kitna hai?' (after NPA discussion) -> 'what is your NPA rate'"
            ),
        },
        "total_records": {
            "type": "integer",
            "description": (
                "Number of records to retrieve based on query type. "
                "Use 3 for specific single-point queries (definitions, features). "
                "Use 10 for Multiple questions, NPA rates questions, Disbursement values questions, time-range queries (data since/between specific dates, monthly/quarterly data, last six months). "
                "Use 15 for trend/historical/comparative queries (over years, YoY, trends, comparisons, changes over time). "
                "Examples: 'How does repayment process work' -> 3, 'what is your NPA rate in 2024' -> 10, 'disbursement value from Jan 2025 to Oct 2025' -> 15, 'NPA trend last 2024 october to 2025 october' -> 15. "
                "Examples: 'what are the payment options' -> 3, 'what is repeat loan, filling fast, daily repayment, monthly repayment' -> 10, 'Give me the trend of disbursement value from March 2024 to March 2025' -> 15"
            ),
        },
    },
    required=["query_for_vector_search", "total_records"],
)

async def search_knowledge_base_handler(params: FunctionCallParams):
    """Handle search_knowledge_base function calls using Vertex AI RAG."""
    query = params.arguments.get("query_for_vector_search", "")
    total_records = params.arguments.get("total_records", 5)

    # Resolve config dynamically
    corpus_id, project_id, location = get_rag_config()

    if not corpus_id:
        logger.warning("[RAG] RAG_CORPUS_RESOURCE_ID not set")
        await params.result_callback({"content": "Knowledge base not configured."})
        return

    # Ensure Vertex AI is initialized
    if not initialize_vertex_if_needed():
        logger.error("[RAG] Vertex AI initialization failed")
        await params.result_callback({"content": "Knowledge base service unavailable."})
        return

    logger.info(f"[RAG] Query: {query}, Records: {total_records}, Location: {location}")

    try:
        # Query RAG corpus
        # Run in executor to avoid blocking event loop
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: rag.retrieval_query(
                rag_resources=[rag.RagResource(rag_corpus=corpus_id)],
                text=query,
                similarity_top_k=total_records,
            )
        )

        # Extract results
        results = []
        if response.contexts and response.contexts.contexts:
            for ctx in response.contexts.contexts:
                text = ctx.text
                if "Answer:" in text:
                    answer = text.split("Answer:")[-1].strip()
                    results.append(answer)
                else:
                    results.append(text)

        if not results:
            result = "No relevant information found in the knowledge base."
        else:
            unique_results = list(dict.fromkeys(results))
            result = "\n\n".join(f"{i}. {r}" for i, r in enumerate(unique_results, 1))

        logger.info(f"[RAG] Found {len(results)} results")

        # Save result to file for inspection
        try:
            file_path = os.path.join(os.path.dirname(__file__), "rag_last_result.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(result)
            logger.info(f"[RAG] Saved result to {file_path} (Length: {len(result)})")
        except Exception as e:
            logger.error(f"Failed to save RAG result: {e}")

    except Exception as e:
        logger.error(f"Knowledge base search error: {e}")
        result = "Knowledge base search failed. Please try again."

    await params.result_callback({"content": result})
