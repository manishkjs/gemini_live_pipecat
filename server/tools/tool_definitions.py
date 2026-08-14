"""Deterministic and RAG tool schemas and async handlers for Cymbal Lending voicebot.

Extracts all function schemas, async dispatchers, and tool registration logic
out of agent_live.py for maximum modularity, testability, and clean architecture.
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

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
    description="Get the current time.",
    properties={
        "is_explicit_request": {
            "type": "boolean",
            "description": (
                "Return `true` ONLY if the user explicitly asks for the current time or date.\n\n"
                "- Explaining schedules or timelines.\n"
                "- Mentioning time casually in conversation."
            )
        }
    },
    required=["is_explicit_request"]
)


# ── Consolidated Deep Tool Schemas ───────────────────────────────────

calculate_returns_schema = FunctionSchema(
    name="calculate_returns",
    description="Calculate exact deterministic returns, profit, and monthly EMI for Cymbal Lending plans (STL 3-6m, MTL 12m, Manual Lending, or custom Rule 4 NPA).",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment amount in rupees (Min ₹250, Max ₹50,00,000)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Desired tenure in months (3, 4, 5, 6, 12). Note: 9 months is not available."
        },
        "repayment_type": {
            "type": "string",
            "enum": ["monthly", "daily"],
            "description": "'monthly' for monthly EMI (STL / MTL Monthly), 'daily' for daily EDI."
        },
        "custom_borrower_rate_pct": {
            "type": "number",
            "description": "Optional custom borrower interest % (e.g. 40.0) for Rule 4 custom math."
        },
        "custom_npa_rate_pct": {
            "type": "number",
            "description": "Optional custom NPA / default rate % (defaults to 3.5%)."
        }
    },
    required=["amount"]
)

get_onboarding_guide_schema = FunctionSchema(
    name="get_onboarding_guide",
    description="Get step-by-step guidance for KYC verification (PAN, Aadhaar OTP, Bank penny-drop) or App deposit navigation (UPI, NetBanking).",
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
    description="Calculate exact returns for Short Term Lumpsum (STL 5M & 7M) plans on Cymbal Lending (12%-18% annualized XIRR).",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment amount in rupees (Min ₹25,000, Max ₹25,00,000)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Tenure in months (3, 4, 5 for STL 5M; 4, 5, 6 for STL 7M). Optional - defaults to 5 months."
        }
    },
    required=["amount"]
)

calculate_mtl_returns_schema = FunctionSchema(
    name="calculate_mtl_returns",
    description="Calculate exact returns for Medium Term Lumpsum (MTL 14M) plans (12-month tenure, 16%-24% annualized XIRR).",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment amount in rupees (Min ₹1,00,000)."
        },
        "repayment_type": {
            "type": "string",
            "enum": ["monthly", "daily"],
            "description": "'monthly' for MTL 14M Monthly (21-24% XIRR EMI), 'daily' for MTL 14M Daily EDI (16-18% XIRR low risk)."
        }
    },
    required=["amount"]
)

calculate_manual_lending_schema = FunctionSchema(
    name="calculate_manual_lending",
    description="Calculate returns for Manual Lending (Standard 18%-24% XIRR or Custom Portfolio Rule 4 Step A-G breakdown with NPA and fee deductions).",
    properties={
        "amount": {
            "type": "number",
            "description": "Investment amount in rupees (Min ₹250, Max ₹50,00,000)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Tenure in months (2, 3, 4, 5, 6, or 12 months)."
        },
        "custom_borrower_rate_pct": {
            "type": "number",
            "description": "Optional custom borrower interest rate % (e.g. 40.0, 48.0) if user asks for custom portfolio math."
        },
        "custom_npa_rate_pct": {
            "type": "number",
            "description": "Optional custom NPA / default rate % (defaults to 3.5%)."
        }
    },
    required=["amount"]
)

calculate_sip_returns_schema = FunctionSchema(
    name="calculate_sip_returns",
    description="Calculate Systematic Investment Plan (SIP) compounding growth.",
    properties={
        "monthly_amount": {
            "type": "number",
            "description": "Monthly investment amount in rupees."
        },
        "annual_rate": {
            "type": "number",
            "description": "Annual return rate percentage."
        },
        "years": {
            "type": "integer",
            "description": "Investment duration in years."
        }
    },
    required=["monthly_amount", "annual_rate", "years"]
)

get_product_recommendation_schema = FunctionSchema(
    name="get_product_recommendation",
    description="Validate investment parameters and get the best recommended Cymbal Lending product.",
    properties={
        "amount": {
            "type": "number",
            "description": "Planned investment amount in rupees."
        },
        "risk_appetite": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "User's risk appetite: 'low' (AAA daily), 'medium' (AA monthly), 'high' (A STL)."
        },
        "tenure_months": {
            "type": "integer",
            "description": "Desired tenure in months (3, 4, 5, 6, or 12). Note: 9 months is not available."
        }
    },
    required=["amount"]
)

get_kyc_guidance_schema = FunctionSchema(
    name="get_kyc_guidance",
    description="Get step-by-step KYC verification guidance for PAN, Aadhaar OTP, or Bank penny-drop linking.",
    properties={
        "step_or_doc": {
            "type": "string",
            "description": "Specific document or step: 'pan', 'aadhaar', 'bank', or 'all'."
        }
    },
    required=[]
)

get_app_screen_flow_schema = FunctionSchema(
    name="get_app_screen_flow",
    description="Get mobile app UI navigation steps for depositing funds, selecting STL/MTL plans, manual lending, or loan filter options.",
    properties={
        "target_flow": {
            "type": "string",
            "description": "Flow to navigate: 'deposit', 'lumpsum', 'loan filter', 'manual', or 'general'."
        }
    },
    required=["target_flow"]
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


async def dynamic_tool_handler(params: FunctionCallParams):
    logger.info(f"Dynamic tool called: {params.function_name} with args: {params.arguments}")
    await params.result_callback({"status": "success", "message": f"Tool {params.function_name} called successfully"})


# ── Registry Helper ──────────────────────────────────────────────────

def get_standard_tools(dynamic_tools_json: Optional[str] = None) -> List[FunctionSchema]:
    """Returns the full list of registered tool schemas."""
    tools = [
        get_current_time_schema,
        search_knowledge_base_schema,
        calculate_returns_schema,
        get_onboarding_guide_schema,
        calculate_stl_returns_schema,
        calculate_mtl_returns_schema,
        calculate_manual_lending_schema,
        calculate_sip_returns_schema,
        get_product_recommendation_schema,
        get_kyc_guidance_schema,
        get_app_screen_flow_schema,
    ]

    if dynamic_tools_json:
        try:
            tools_data = json.loads(dynamic_tools_json)
            if isinstance(tools_data, list):
                for tool in tools_data:
                    if "name" in tool:
                        tools.append(FunctionSchema(
                            name=tool.get("name"),
                            description=tool.get("description", ""),
                            properties=tool.get("properties", {}),
                            required=tool.get("required", [])
                        ))
        except Exception as e:
            logger.error(f"Failed to parse dynamic tools: {e}")

    return tools


def register_all_tools(llm: Any, standard_tools: List[FunctionSchema], get_current_time_fn: Optional[Any] = None) -> None:
    """Registers all function handlers with the Gemini LLM service."""
    if get_current_time_fn:
        llm.register_function("get_current_time", get_current_time_fn)
    llm.register_function("search_knowledge_base", search_knowledge_base_handler)
    llm.register_function("calculate_returns", handle_calculate_returns)
    llm.register_function("get_onboarding_guide", handle_get_onboarding_guide)
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
