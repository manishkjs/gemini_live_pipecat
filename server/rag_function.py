import asyncio
import os
import re
from loguru import logger
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
try:
    import vertexai
    from vertexai.preview import rag
except ImportError:
    vertexai = None
    rag = None
import google.auth
from dotenv import load_dotenv

load_dotenv()

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

from redis_cache import rag_cache

# ── Authoritative Grounded Domain Fallback ──────────────────────────────
CANONICAL_DOMAIN_KNOWLEDGE: dict[str, str] = {
    "rbi": (
        "Cymbal Lending is an RBI-registered NBFC-P2P platform operating under strict regulatory oversight. "
        "Funds are managed via an independent RBI-regulated Trustee Escrow Account (ICICI Trusteeship / IDBI Trustee). "
        "The platform never holds customer funds directly (lender -> escrow -> borrower)."
    ),
    "escrow": (
        "Lender and borrower capital is securely managed via an independent RBI-regulated Trustee Escrow Account (ICICI Trusteeship). "
        "This ensures platform insolvency bankruptcy protection: even in an extreme scenario with the platform, customer funds in escrow remain completely safe and untouched."
    ),
    "track_record": (
        "Track Record & Scale: 10 years vintage, ₹18,792+ Crore disbursed since inception till March 2026, "
        "40 Lakh+ registered lenders, 3 Crore+ registered users, 96.18% historical recovery rate, and 4.4-star rating."
    ),
    "npa": (
        "NPA & Risk Mitigation: Unsecured loans carry credit risk, which is mitigated through AI pre-screening (650+ data points) "
        "and spreading investments across 100+ vetted borrowers (₹250 to ₹4,000 max per loan). "
        "Platform NPA is ~3.50% (as of March 2026). Quoted returns (12%-24% XIRR) are already net of historical NPA provisions."
    ),
    "recovery_protocol": (
        "Default & Recovery Protocol: 3-tier recovery framework (Automated soft reminders & digital notices -> Field collection agency mediation -> Legal Section 138 NACH bounce & arbitration proceedings). Historical recovery rate is 96.18%."
    ),
    "tds_taxation": (
        "Taxation & Form 26AS: TDS @ 10% is deducted on annual interest income exceeding ₹5,000 under Section 194A. "
        "TDS credit is fully reflected in your Form 26AS / AIS, and Cymbal Lending provides an annual TDS certificate (Form 16A) for seamless income tax return filing."
    ),
    "nri_regulations": (
        "NRI & Overseas Investors: NRI investments are permitted through NRE and NRO bank accounts under RBI FEMA guidelines. "
        "Returns and principal are credited to the linked NRE/NRO account with standard repatriation compliance."
    ),
    "fd_comparison": (
        "Bank FDs offer 6.5%-7.5% taxable returns, barely beating inflation. "
        "Cymbal Lending P2P offers 12%-24% p.a. returns with continuous cash flow (monthly EMI or daily EDI), providing 2x-3x higher wealth generation."
    ),
    "limits": (
        "Lending Limits: Absolute minimum is ₹250 (Manual Lending). STL minimum is ₹25,000 to ₹25 Lakhs. "
        "MTL Monthly/Daily minimum is ₹1,00,000 to ₹25 Lakhs. "
        "RBI statutory ceiling across all P2P platforms per PAN is ₹50 Lakhs."
    ),
    "tenure": (
        "Available Tenures: 2, 3, 4, 5, 6, and 12 months. 9-month tenures are STRICTLY NOT AVAILABLE on the platform."
    ),
    "kyc": (
        "3-Step Instant KYC: 1. PAN card verification, 2. Aadhaar Digilocker OTP, 3. Bank account penny-drop linking. Completed in 2 minutes inside the app."
    )
}

def _get_fallback_domain_knowledge(query: str) -> str:
    """Retrieve grounded canonical domain knowledge when vector search is sparse."""
    q = (query or "").lower()
    matches = []
    if any(w in q for w in ["tds", "26as", "226as", "form 26", "tax", "income tax", "194a", "16a"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["tds_taxation"])
    if any(w in q for w in ["nri", "nre", "nro", "fema", "repatriat", "overseas"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["nri_regulations"])
    if any(w in q for w in ["rbi", "regist", "regulat", "legal", "complian", "approv"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["rbi"])
    if any(w in q for w in ["escrow", "trustee", "bankrupt", "safe", "security", "protect"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["escrow"])
    if any(w in q for w in ["recovery", "court", "legal notice", "section 138", "arbitrat", "cheque bounce", "nach bounce"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["recovery_protocol"])
    if any(w in q for w in ["npa", "default", "loss", "risk", "delay", "recover"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["npa"])
    if any(w in q for w in ["track", "vintage", "year", "disburse", "crore", "lender", "user"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["track_record"])
    if any(w in q for w in ["fd", "fixed deposit", "mutual fund", "bank"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["fd_comparison"])
    if any(w in q for w in ["limit", "minimum", "maximum", "ceiling", "50 lakh", "250"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["limits"])
    if any(w in q for w in ["tenure", "month", "duration", "9 month", "period"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["tenure"])
    if any(w in q for w in ["kyc", "pan", "aadhaar", "penny", "document", "onboard", "branch"]):
        matches.append(CANONICAL_DOMAIN_KNOWLEDGE["kyc"])

    if not matches:
        matches = [CANONICAL_DOMAIN_KNOWLEDGE["rbi"], CANONICAL_DOMAIN_KNOWLEDGE["track_record"]]

    return "\n\n".join(f"{i}. {m}" for i, m in enumerate(dict.fromkeys(matches), 1))


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
    query = params.arguments.get("query_for_vector_search", "")
    total_records = params.arguments.get("total_records", 3)

    # 1. Exact Cache Lookup in L1/L2 Redis (<0.01ms)
    cached_result = await rag_cache.get(query)
    if cached_result:
        logger.info(f"⚡ [RAG:ExactCacheHit] Instant Redis/L1 cached result for: '{query}'")
        await params.result_callback({"content": cached_result})
        return

    # 2. Sub-Millisecond Token-Ranked Search across 913 Google Sheet Q&A items (<1ms)
    sheet_matches = await rag_cache.search_sheet_knowledge(query, top_k=total_records)
    if sheet_matches:
        logger.info(f"⚡ [RAG:SheetMemorystoreHit] Retrieved grounded Google Sheet Q&A for: '{query}'")
        await rag_cache.set(query, sheet_matches)
        await params.result_callback({"content": sheet_matches})
        return

    # 3. Canonical Domain Knowledge Fallback (<0.01ms)
    logger.info(f"⚡ [RAG:CanonicalFallback] Using canonical domain knowledge fallback for: '{query}'")
    result = _get_fallback_domain_knowledge(query)
    await rag_cache.set(query, result)
    await params.result_callback({"content": result})
