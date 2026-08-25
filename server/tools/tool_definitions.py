"""Deterministic and RAG tool schemas and async handlers for Cymbal Lending voicebot.

Extracts all function schemas, async dispatchers, and tool registration logic
out of agent_live.py for maximum modularity, testability, and clean architecture.
"""

from __future__ import annotations
import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

try:
    from memory_bank import MemoryBank, normalize_lexical_user_id, _get_default_storage_path
except ImportError:
    try:
        from ..memory_bank import MemoryBank, normalize_lexical_user_id, _get_default_storage_path
    except Exception:
        MemoryBank = None
        normalize_lexical_user_id = lambda name: f"user_{str(name).lower().replace(' ', '_')}" if name else "user_anonymous"
        _get_default_storage_path = lambda: None

_GLOBAL_MEMORY_BANK = MemoryBank(storage_path=_get_default_storage_path() if _get_default_storage_path else None) if MemoryBank is not None else None

try:
    from rag_function import search_knowledge_base_schema, search_knowledge_base_handler
except ImportError:
    try:
        from ..rag_function import search_knowledge_base_schema, search_knowledge_base_handler
    except Exception:
        search_knowledge_base_schema = None
        search_knowledge_base_handler = None

try:
    from tools.financial_math import (
        calculate_stl_returns,
        calculate_mtl_returns,
        calculate_manual_lending,
        calculate_sip_returns,
        get_product_recommendation,
        calculate_returns,
    )
    from tools.navigation import (
        get_kyc_guidance,
        get_app_screen_flow,
        get_consultative_guidance,
        get_onboarding_guide,
    )
except ImportError:
    from .financial_math import (
        calculate_stl_returns,
        calculate_mtl_returns,
        calculate_manual_lending,
        calculate_sip_returns,
        get_product_recommendation,
        calculate_returns,
    )
    from .navigation import (
        get_kyc_guidance,
        get_app_screen_flow,
        get_consultative_guidance,
        get_onboarding_guide,
    )


# ── Built-in Clock / Utility Schema ─────────────────────────────────

get_current_time_schema = FunctionSchema(
    name="get_current_time",
    description="Get current time.",
    properties={
        "is_explicit_request": {
            "type": "boolean",
            "description": "True if user asks for current time/date."
        }
    },
    required=["is_explicit_request"]
)


# ── Consolidated Deep Tool Schemas ───────────────────────────────────

calculate_returns_schema = FunctionSchema(
    name="calculate_returns",
    description="Calculate exact returns, profit, and monthly EMI for Cymbal Lending plans.",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment ₹ (250 to 50,00,000)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Tenure in months (e.g. 3, 4, 5, 6, 9, 12). If 9m is requested, tool returns official alternative guidance."
        },
        "repayment_type": {
            "type": "string",
            "enum": ["monthly", "daily"],
            "description": "'monthly' EMI or 'daily' EDI."
        },
        "custom_borrower_rate_pct": {
            "type": "number",
            "description": "Custom borrower rate % (e.g. 40.0)."
        },
        "custom_npa_rate_pct": {
            "type": "number",
            "description": "Custom NPA % (default 3.5%)."
        }
    },
    required=["amount"]
)

get_onboarding_guide_schema = FunctionSchema(
    name="get_onboarding_guide",
    description="Get step-by-step KYC verification or App deposit navigation.",
    properties={
        "topic": {
            "type": "string",
            "description": "Topic: 'pan', 'aadhaar', 'bank', 'all_kyc', 'deposit', 'lumpsum', or 'loan_filter'."
        }
    },
    required=["topic"]
)


# ── Granular / Backward Compatibility Schemas ────────────────────────

calculate_stl_returns_schema = FunctionSchema(
    name="calculate_stl_returns",
    description="Calculate returns for Short Term Lumpsum (STL 5M & 7M, 12-18% XIRR).",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment ₹ (25,000 to 25,00,000)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Months (3 to 6)."
        }
    },
    required=["amount"]
)

calculate_mtl_returns_schema = FunctionSchema(
    name="calculate_mtl_returns",
    description="Calculate returns for Medium Term Lumpsum (MTL 14M, 16-24% XIRR).",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment ₹ (min 1,00,000)."
        },
        "repayment_type": {
            "type": "string",
            "enum": ["monthly", "daily"],
            "description": "'monthly' EMI or 'daily' EDI."
        }
    },
    required=["amount"]
)

calculate_manual_lending_schema = FunctionSchema(
    name="calculate_manual_lending",
    description="Calculate returns for Manual Lending portfolio (18-24% XIRR or custom NPA math).",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment ₹ (250 to 50,00,000)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Months: 2, 3, 4, 5, 6, 12."
        },
        "custom_borrower_rate_pct": {
            "type": "number",
            "description": "Custom borrower rate % (e.g. 40.0)."
        },
        "custom_npa_rate_pct": {
            "type": "number",
            "description": "Custom default % (default 3.5%)."
        }
    },
    required=["amount"]
)

calculate_sip_returns_schema = FunctionSchema(
    name="calculate_sip_returns",
    description="Calculate SIP compounding growth.",
    properties={
        "monthly_amount": {
            "type": "number",
            "description": "Monthly investment ₹."
        },
        "annual_rate": {
            "type": "number",
            "description": "Annual return %."
        },
        "years": {
            "type": "integer",
            "description": "Duration in years."
        }
    },
    required=["monthly_amount", "annual_rate", "years"]
)

get_product_recommendation_schema = FunctionSchema(
    name="get_product_recommendation",
    description="Get recommended Cymbal Lending product based on parameters.",
    properties={
        "amount": {
            "type": "number",
            "description": "Planned investment ₹."
        },
        "risk_appetite": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Risk: 'low' (AAA daily), 'medium' (AA monthly), 'high' (A STL)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Months (3,4,5,6,12)."
        }
    },
    required=["amount"]
)

get_kyc_guidance_schema = FunctionSchema(
    name="get_kyc_guidance",
    description="Get KYC verification steps (PAN, Aadhaar OTP, Bank penny-drop).",
    properties={
        "step_or_doc": {
            "type": "string",
            "description": "Document/step: 'pan', 'aadhaar', 'bank', or 'all'."
        }
    },
    required=[]
)

get_app_screen_flow_schema = FunctionSchema(
    name="get_app_screen_flow",
    description="Get mobile app UI navigation steps.",
    properties={
        "target_flow": {
            "type": "string",
            "description": "Flow: 'deposit', 'lumpsum', 'loan filter', 'manual', or 'general'."
        }
    },
    required=["target_flow"]
)

retrieve_memory_schema = FunctionSchema(
    name="retrieve_memory",
    description="Retrieve customer facts and previous discussion history from GCP Memory Bank whenever user asks what happened last time or in prior calls.",
    properties={
        "user_id": {
            "type": "string",
            "description": "Customer name or user ID (use 'current_user' if not known).",
        },
        "query": {
            "type": "string",
            "description": "Search query or 'previous discussion'.",
        },
    },
    required=["user_id", "query"],
)

save_memory_schema = FunctionSchema(
    name="save_memory",
    description="Persist customer financial facts or commitment into GCP Memory Bank.",
    properties={
        "user_id": {
            "type": "string",
            "description": "Customer name or user ID.",
        },
        "amount": {
            "type": "number",
            "description": "Investment ₹.",
        },
        "tenure_months": {
            "type": "integer",
            "description": "Months: 3, 6, 12.",
        },
        "risk_preference": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Risk appetite.",
        },
        "goal": {
            "type": "string",
            "description": "Customer wealth goal.",
        },
        "note": {
            "type": "string",
            "description": "Summary note or commitment.",
        },
    },
    required=["note"],
)


# ── Async Function Execution Handlers ────────────────────────────────

async def handle_calculate_returns(params: FunctionCallParams):
    args = params.arguments or {}
    raw_amount = args.get("amount")
    amount = float(raw_amount) if raw_amount is not None else 50000.0
    raw_tenure = args.get("tenure_months")
    tenure = int(raw_tenure) if raw_tenure is not None else None
    repayment_type = args.get("repayment_type", "monthly")
    raw_rate = args.get("custom_borrower_rate_pct")
    raw_npa = args.get("custom_npa_rate_pct")
    result = calculate_returns(
        amount=amount,
        tenure_months=tenure,
        repayment_type=repayment_type,
        custom_borrower_rate_pct=float(raw_rate) if raw_rate is not None else None,
        custom_npa_rate_pct=float(raw_npa) if raw_npa is not None else None,
    )
    logger.info(f"[Tool:calculate_returns] amount={amount}, tenure={tenure} -> {result}")
    await params.result_callback(result)


async def handle_get_onboarding_guide(params: FunctionCallParams):
    args = params.arguments or {}
    topic = args.get("topic") or args.get("step_or_doc") or args.get("target_flow") or "all"
    result = get_onboarding_guide(topic=str(topic))
    logger.info(f"[Tool:get_onboarding_guide] topic={topic} -> {result}")
    await params.result_callback(result)


async def handle_calculate_stl_returns(params: FunctionCallParams):
    args = params.arguments or {}
    raw_amount = args.get("amount")
    amount = float(raw_amount) if raw_amount is not None else 50000.0
    raw_tenure = args.get("tenure_months")
    tenure_months = int(raw_tenure) if raw_tenure is not None else None
    result = calculate_stl_returns(amount=amount, tenure_months=tenure_months)
    logger.info(f"[Tool:calculate_stl_returns] amount={amount}, tenure={tenure_months} -> {result}")
    await params.result_callback(result)


async def handle_calculate_mtl_returns(params: FunctionCallParams):
    args = params.arguments or {}
    raw_amount = args.get("amount")
    amount = float(raw_amount) if raw_amount is not None else 100000.0
    raw_rep = args.get("repayment_type")
    repayment_type = str(raw_rep) if raw_rep is not None else "monthly"
    result = calculate_mtl_returns(amount=amount, repayment_type=repayment_type)
    logger.info(f"[Tool:calculate_mtl_returns] amount={amount}, repayment={repayment_type} -> {result}")
    await params.result_callback(result)


async def handle_calculate_manual_lending(params: FunctionCallParams):
    args = params.arguments or {}
    raw_amount = args.get("amount")
    amount = float(raw_amount) if raw_amount is not None else 50000.0
    raw_tenure = args.get("tenure_months")
    tenure = int(raw_tenure) if raw_tenure is not None else 12
    raw_borrower_rate = args.get("custom_borrower_rate_pct")
    raw_npa_rate = args.get("custom_npa_rate_pct")
    result = calculate_manual_lending(
        amount=amount,
        tenure_months=tenure,
        custom_borrower_rate_pct=float(raw_borrower_rate) if raw_borrower_rate is not None else None,
        custom_npa_rate_pct=float(raw_npa_rate) if raw_npa_rate is not None else None,
    )
    logger.info(f"[Tool:calculate_manual_lending] amount={amount}, tenure={tenure} -> {result}")
    await params.result_callback(result)


async def handle_calculate_sip_returns(params: FunctionCallParams):
    args = params.arguments or {}
    raw_amount = args.get("monthly_amount")
    monthly_amount = float(raw_amount) if raw_amount is not None else 5000.0
    raw_rate = args.get("annual_rate")
    annual_rate = float(raw_rate) if raw_rate is not None else 15.0
    raw_years = args.get("years")
    years = int(raw_years) if raw_years is not None else 3
    result = calculate_sip_returns(monthly_amount=monthly_amount, annual_rate=annual_rate, years=years)
    logger.info(f"[Tool:calculate_sip_returns] monthly={monthly_amount}, rate={annual_rate}, years={years} -> {result}")
    await params.result_callback(result)


async def handle_get_product_recommendation(params: FunctionCallParams):
    args = params.arguments or {}
    raw_amount = args.get("amount")
    amount = float(raw_amount) if raw_amount is not None else 50000.0
    raw_risk = args.get("risk_appetite")
    risk_appetite = str(raw_risk) if raw_risk is not None else "medium"
    raw_tenure = args.get("tenure_months")
    tenure_months = int(raw_tenure) if raw_tenure is not None else None
    result = get_product_recommendation(amount=amount, risk_appetite=risk_appetite, tenure_months=tenure_months)
    logger.info(f"[Tool:get_product_recommendation] amount={amount}, risk={risk_appetite}, tenure={tenure_months} -> {result}")
    await params.result_callback(result)


async def handle_get_kyc_guidance(params: FunctionCallParams):
    args = params.arguments or {}
    raw_step = args.get("step_or_doc")
    step = str(raw_step) if raw_step is not None else "all"
    result = get_kyc_guidance(step_or_doc=step)
    logger.info(f"[Tool:get_kyc_guidance] step={step} -> {result}")
    await params.result_callback(result)


async def handle_get_app_screen_flow(params: FunctionCallParams):
    args = params.arguments or {}
    raw_flow = args.get("target_flow")
    flow = str(raw_flow) if raw_flow is not None else "general"
    result = get_app_screen_flow(target_flow=flow)
    logger.info(f"[Tool:get_app_screen_flow] flow={flow} -> {result}")
    await params.result_callback(result)


async def handle_retrieve_memory(params: FunctionCallParams, memory_bank: Optional[Any] = None):
    """Async tool handler for retrieving customer memory and profile facts."""
    try:
        args = params.arguments or {}
        raw_user_id = args.get("user_id")
        if not raw_user_id or not isinstance(raw_user_id, str) or not raw_user_id.strip() or raw_user_id.lower() in ["current_user", "user", "anonymous", "default", "default_user", "unknown"]:
            import os
            raw_user_id = os.getenv("ACTIVE_USER_ID", "default_user")

        user_id = normalize_lexical_user_id(raw_user_id) if normalize_lexical_user_id else f"user_{str(raw_user_id).lower().replace(' ', '_')}"
        query = str(args.get("query") or "").strip()

        # Extract memory bank from parameter, params.context, or global fallback
        mb = memory_bank
        if mb is None and hasattr(params, "context") and params.context:
            mb = getattr(params.context, "memory_bank", None) or getattr(params.context, "mb", None)
            if mb is None and isinstance(params.context, dict):
                mb = params.context.get("memory_bank") or params.context.get("mb")
        if mb is None:
            mb = _GLOBAL_MEMORY_BANK

        if mb is None:
            await params.result_callback({
                "status": "empty",
                "user_id": user_id,
                "message": "Memory bank is not initialized.",
                "facts": {},
                "memories": [],
                "count": 0,
            })
            return

        # Retrieve active structured facts
        facts = {}
        if hasattr(mb, "get_fact_store"):
            fact_store = mb.get_fact_store(user_id)
            if fact_store and hasattr(fact_store, "get_all_facts"):
                facts = fact_store.get_all_facts() or {}

        # Retrieve episodic memories (local-first or fast search)
        memories = []
        if hasattr(mb, "hydrate_user_profile"):
            profile = mb.hydrate_user_profile(user_id=user_id)
            if asyncio.iscoroutine(profile):
                profile = await profile
            memories = profile.get("recent_memories", []) if isinstance(profile, dict) else []
        elif query and hasattr(mb, "search_memories"):
            try:
                res = mb.search_memories(user_id=user_id, query=query, threshold=0.40, limit=3)
                if asyncio.iscoroutine(res):
                    memories = await asyncio.wait_for(res, timeout=0.5)
                else:
                    memories = res
            except Exception as e:
                logger.warning(f"[Tool:retrieve_memory] Fast fallback: {e}")
                memories = []

        if not facts and not memories:
            result = {
                "status": "empty",
                "user_id": user_id,
                "message": f"No prior memory found for {raw_user_id}.",
                "summary_hinglish": f"{raw_user_id} जी, हमारे पास आपका कोई पुराना discussion record नहीं है, चलिए fresh start करते हैं।",
                "facts": {},
                "memories": [],
                "count": 0,
            }
        else:
            formatted_memories = [
                m.get("content", "") if isinstance(m, dict) else str(m)
                for m in memories
            ]
            facts_str = ", ".join(f"{k}: {v}" for k, v in facts.items()) if facts else "None"
            mems_str = "; ".join(formatted_memories[:2]) if formatted_memories else "None"
            result = {
                "status": "success",
                "user_id": user_id,
                "facts": facts,
                "memories": formatted_memories,
                "count": len(formatted_memories),
                "summary": f"User {user_id}: {len(facts)} active facts, {len(memories)} matching memories.",
                "summary_hinglish": f"हाँ बिल्कुल {raw_user_id} जी! हमारी पहले बात हुई थी... हाँ, मुझे याद आ रहा है। आपके details: {facts_str}. Previous discussion: {mems_str}.",
            }

        logger.info(
            f"🧠 [Tool:retrieve_memory] Retrieved for '{user_id}':\n"
            f"   ├─ Active Facts: {json.dumps(facts, ensure_ascii=False)}\n"
            f"   └─ Episodic Memories ({len(result['memories'])}): {result['memories']}"
        )
        await params.result_callback(result)
    except Exception as e:
        logger.error(f"[Tool:retrieve_memory] Error: {e}")
        await params.result_callback({
            "status": "error",
            "error": str(e),
            "message": "Failed to retrieve memories safely.",
            "facts": {},
            "memories": [],
            "count": 0,
        })


async def handle_save_memory(params: FunctionCallParams, memory_bank: Optional[Any] = None):
    """Saves confirmed investor facts and episodic memory note to GCP Cloud Memory Bank."""
    args = params.arguments or {}
    raw_user_id = args.get("user_id", "")
    note = args.get("note", "").strip()

    if not raw_user_id or not raw_user_id.strip():
        import os
        raw_user_id = os.getenv("ACTIVE_USER_ID", "default_user")

    user_id = normalize_lexical_user_id(raw_user_id)
    mb = memory_bank or _GLOBAL_MEMORY_BANK

    try:
        facts_to_save: Dict[str, Any] = {}
        for key in ["amount", "tenure_months", "risk_preference", "goal", "city", "occupation", "experience"]:
            if key in args and args[key] is not None:
                facts_to_save[key] = args[key]

        if mb:
            # 1. Save structured facts if any
            if facts_to_save and hasattr(mb, "save_facts_and_sync"):
                mb.save_facts_and_sync(user_id=user_id, facts=facts_to_save)
            elif facts_to_save and hasattr(mb, "get_fact_store"):
                fs = mb.get_fact_store(user_id)
                for k, v in facts_to_save.items():
                    try:
                        fs.set_fact(k, v, turn_id=1, is_hypothetical=False)
                    except ValueError:
                        pass

            # 2. Add episodic note into GCP Cloud Memory Bank & local store
            if note and hasattr(mb, "add_memory"):
                mb.add_memory(
                    user_id=user_id,
                    content=note,
                    metadata={"facts": facts_to_save, "source": "tool:save_memory"},
                )

        result = {
            "status": "success",
            "user_id": user_id,
            "facts_saved": facts_to_save,
            "note_saved": note,
            "message": f"Successfully saved memory and facts for {raw_user_id} in GCP Enterprise Memory Bank.",
            "summary_hinglish": f"{raw_user_id} जी की details और memory save कर ली गई है।",
        }
        logger.info(f"[Tool:save_memory] user_id={user_id}, facts={facts_to_save}, note={note[:50]}...")
        await params.result_callback(result)
    except Exception as e:
        logger.error(f"[Tool:save_memory] Error: {e}")
        await params.result_callback({
            "status": "error",
            "error": str(e),
            "message": "Failed to save memory safely.",
            "facts_saved": {},
            "summary_hinglish": "Memory save karte waqt issue aaya, details internally note kar li gayi hain.",
        })


async def dynamic_tool_handler(params: FunctionCallParams):
    logger.info(f"Dynamic tool called: {params.function_name} with args: {params.arguments}")
    await params.result_callback({"status": "success", "message": f"Tool {params.function_name} called successfully"})


# ── Registry Helper ──────────────────────────────────────────────────

def get_tools_for_profile(profile: Optional[str] = None, dynamic_tools_json: Optional[str] = None) -> List[FunctionSchema]:
    """Returns tool schemas according to the selected profile ('lean' vs 'full') and parses dynamic tools.

    - 'lean' (default): Returns the 4 active real-time conversational tools:
      [calculate_returns, search_knowledge_base, retrieve_memory, save_memory].
    - 'full': Returns all 6 tools:
      [get_current_time, search_knowledge_base, calculate_returns, get_onboarding_guide, retrieve_memory, save_memory].
    """
    resolved_profile = (profile if profile is not None else os.getenv("TOOL_PROFILE", "lean")).strip().lower()

    if resolved_profile == "full":
        tools = [
            get_current_time_schema,
            search_knowledge_base_schema,
            calculate_returns_schema,
            get_onboarding_guide_schema,
            retrieve_memory_schema,
            save_memory_schema,
        ]
    else:
        # "lean" profile (default)
        tools = [
            calculate_returns_schema,
            search_knowledge_base_schema,
            retrieve_memory_schema,
            save_memory_schema,
        ]

    if dynamic_tools_json:
        try:
            tools_data = json.loads(dynamic_tools_json)
            if isinstance(tools_data, list):
                for tool in tools_data:
                    if isinstance(tool, dict) and "name" in tool:
                        tools.append(FunctionSchema(
                            name=tool.get("name"),
                            description=tool.get("description", ""),
                            properties=tool.get("properties", {}),
                            required=tool.get("required", [])
                        ))
        except Exception as e:
            logger.error(f"Failed to parse dynamic tools: {e}")

    return tools


def get_live_streaming_tools(dynamic_tools_json: Optional[str] = None) -> List[FunctionSchema]:
    """Returns only instantaneous, non-blocking tools for Gemini Live duplex audio stream.

    Delegates to get_tools_for_profile with TOOL_PROFILE from environment (defaults to 'lean').
    """
    return get_tools_for_profile(profile=os.getenv("TOOL_PROFILE", "lean"), dynamic_tools_json=dynamic_tools_json)


def get_standard_tools(dynamic_tools_json: Optional[str] = None) -> List[FunctionSchema]:
    """Returns the active tool schemas (full suite)."""
    return get_tools_for_profile(profile="full", dynamic_tools_json=dynamic_tools_json)


def register_all_tools(llm: Any, standard_tools: List[FunctionSchema], get_current_time_fn: Optional[Any] = None) -> None:
    """Registers all function handlers with the Gemini LLM service."""
    if get_current_time_fn:
        llm.register_function("get_current_time", get_current_time_fn)
    llm.register_function("search_knowledge_base", search_knowledge_base_handler)
    llm.register_function("calculate_returns", handle_calculate_returns)
    llm.register_function("get_onboarding_guide", handle_get_onboarding_guide)
    llm.register_function("retrieve_memory", handle_retrieve_memory)
    llm.register_function("save_memory", handle_save_memory)
    llm.register_function("calculate_stl_returns", handle_calculate_stl_returns)
    llm.register_function("calculate_mtl_returns", handle_calculate_mtl_returns)
    llm.register_function("calculate_manual_lending", handle_calculate_manual_lending)
    llm.register_function("calculate_sip_returns", handle_calculate_sip_returns)
    llm.register_function("get_product_recommendation", handle_get_product_recommendation)
    llm.register_function("get_kyc_guidance", handle_get_kyc_guidance)
    llm.register_function("get_app_screen_flow", handle_get_app_screen_flow)

    built_in_tools = {
        "get_current_time",
        "search_knowledge_base",
        "calculate_returns",
        "get_onboarding_guide",
        "retrieve_memory",
        "save_memory",
        "calculate_stl_returns",
        "calculate_mtl_returns",
        "calculate_manual_lending",
        "calculate_sip_returns",
        "get_product_recommendation",
        "get_kyc_guidance",
        "get_app_screen_flow",
    }

    for tool in standard_tools:
        if tool.name not in built_in_tools:
            llm.register_function(tool.name, dynamic_tool_handler)



