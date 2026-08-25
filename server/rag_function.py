import asyncio
import os
import re
from loguru import logger
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from dotenv import load_dotenv
from redis_cache import rag_cache


# Schema definition
search_knowledge_base_schema = FunctionSchema(
    name="search_knowledge_base",
    description="Query knowledge base for policies, regulations, or data.",
    properties={
        "query_for_vector_search": {
            "type": "string",
            "description": "Search query."
        },
        "total_records": {
            "type": "integer",
            "description": "Count (default 3)."
        },
    },
    required=["query_for_vector_search"],
)

async def search_knowledge_base_handler(params: FunctionCallParams):
    """Handle search_knowledge_base function calls using Sub-Millisecond Sheet Memorystore/Redis RAG."""
    args = params.arguments if isinstance(params.arguments, dict) else {}
    raw_query = args.get("query_for_vector_search", "")
    query = str(raw_query).strip() if raw_query is not None else ""
    raw_records = args.get("total_records", 3)
    try:
        total_records = max(1, min(10, int(raw_records)))
    except (ValueError, TypeError):
        total_records = 3

    if not query:
        await params.result_callback({"content": "Please provide a search query to search Memorystore."})
        return

    # Sub-Millisecond Token-Ranked Search across Google Sheet Q&A items in Memorystore (<1ms)
    sheet_matches = await rag_cache.search_sheet_knowledge(query, top_k=total_records)
    if sheet_matches:
        logger.info(f"⚡ [RAG:Hit] Retrieved grounded Google Sheet Q&A for: '{query}'")
        await params.result_callback({"content": sheet_matches})
        return

    logger.info(f"⚡ [RAG:NoMatch] No direct matches found in Memorystore for: '{query}'")
    await params.result_callback({"content": f"No specific record found in Memorystore for '{query}'."})
