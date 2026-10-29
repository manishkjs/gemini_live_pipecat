"""Tools and schemas for Ananya (Cymbal MF Advisor).

Provides portfolio queries, scheme NAV lookups, SIP order management,
and phase switching with mock data and RTVI event broadcasting.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional
from google.genai import types


# ---------------------------------------------------------------------------
# Tool Schemas
# ---------------------------------------------------------------------------

get_portfolio_summary_schema = types.FunctionDeclaration(
    name="get_portfolio_summary",
    description=(
        "Retrieve the investor's current Cymbal Mutual Funds portfolio summary, "
        "including total invested amount, current valuation, total returns, XIRR, "
        "and list of active SIPs."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

get_fund_nav_details_schema = types.FunctionDeclaration(
    name="get_fund_nav_details",
    description=(
        "Look up the latest NAV, 1-year and 3-year performance CAGR, expense ratio, "
        "and risk classification for a Cymbal Mutual Fund scheme."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "scheme_name": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Name or keyword of the fund scheme, e.g. 'Cymbal Flexi Cap', "
                    "'Cymbal Large & Mid Cap', 'Cymbal ELSS', 'Cymbal Liquid'."
                ),
            ),
        },
        required=["scheme_name"],
    ),
)

manage_sip_order_schema = types.FunctionDeclaration(
    name="manage_sip_order",
    description=(
        "Create, modify, or pause a Systematic Investment Plan (SIP) in a Cymbal Mutual Fund scheme. "
        "Returns an official order reference ID upon confirmation."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "scheme_name": types.Schema(
                type=types.Type.STRING,
                description="The target Cymbal mutual fund scheme name.",
            ),
            "monthly_amount": types.Schema(
                type=types.Type.STRING,
                description="Monthly installment amount in Rupees (e.g. '₹5,000' or '5000').",
            ),
            "debit_date": types.Schema(
                type=types.Type.STRING,
                description="Preferred monthly debit day (e.g. '5th', '10th', '15th').",
            ),
            "action": types.Schema(
                type=types.Type.STRING,
                description="Action to perform: 'create', 'modify_amount', 'modify_date', 'pause', 'cancel'. Default is 'create'.",
            ),
        },
        required=["scheme_name", "monthly_amount", "debit_date"],
    ),
)

switch_phase_schema = types.FunctionDeclaration(
    name="switch_phase",
    description=(
        "Transition the active advisory conversation phase. Allowed phases: "
        "'SOP_01_OVERVIEW', 'SOP_02_SCHEME_DETAILS', 'SOP_03_SIP_PLANNING', 'SOP_04_CONFIRMATION'."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "phase_id": types.Schema(
                type=types.Type.STRING,
                description="Target phase identifier.",
            ),
        },
        required=["phase_id"],
    ),
)


# ---------------------------------------------------------------------------
# Mock Catalog & Storage
# ---------------------------------------------------------------------------

MOCK_FUNDS = {
    "flexi": {
        "scheme_name": "Cymbal Flexi Cap Fund",
        "nav": "₹78.45",
        "cagr_1y": "+22.4%",
        "cagr_3y": "+21.4%",
        "category": "Equity - Flexi Cap",
        "risk_rating": "Very High",
        "expense_ratio": "0.72%",
        "min_sip": "₹1,000",
    },
    "large_mid": {
        "scheme_name": "Cymbal Large & Mid Cap Fund",
        "nav": "₹64.20",
        "cagr_1y": "+19.1%",
        "cagr_3y": "+18.8%",
        "category": "Equity - Large & Mid Cap",
        "risk_rating": "Very High",
        "expense_ratio": "0.68%",
        "min_sip": "₹1,000",
    },
    "elss": {
        "scheme_name": "Cymbal ELSS Tax Saver Fund",
        "nav": "₹92.10",
        "cagr_1y": "+20.5%",
        "cagr_3y": "+19.2%",
        "category": "Equity - ELSS (80C Tax Saver)",
        "risk_rating": "Very High",
        "expense_ratio": "0.65%",
        "min_sip": "₹500",
        "lock_in": "3 Years",
    },
    "liquid": {
        "scheme_name": "Cymbal Liquid Overnight Fund",
        "nav": "₹1,124.50",
        "cagr_1y": "+6.9%",
        "cagr_3y": "+6.5%",
        "category": "Debt - Liquid",
        "risk_rating": "Low",
        "expense_ratio": "0.18%",
        "min_sip": "₹500",
        "redemption": "Instant (up to ₹50,000)",
    },
}


class AnanyaMFExecutionEngine:
    """Manages Ananya's tool executions, idempotent order creation, and phase steering."""

    def __init__(self, broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self._broadcast = broadcast
        self.active_phase = "SOP_01_OVERVIEW"
        self._last_order_key: Optional[str] = None
        self._last_order_result: Optional[Dict[str, Any]] = None
        self._lock = asyncio.Lock()

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self._broadcast:
            try:
                self._broadcast({
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        "persona": "ananya",
                        "event": event_type,
                        **data,
                    },
                })
            except Exception:
                pass

    async def get_portfolio_summary(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch mock portfolio summary."""
        result = {
            "status": "success",
            "portfolio": {
                "investor_name": "Valued Investor",
                "total_invested": "₹4,85,000",
                "current_value": "₹5,72,400",
                "unrealized_gain": "+₹87,400",
                "xirr": "18.02%",
                "active_sips": [
                    {"scheme": "Cymbal Flexi Cap Fund", "monthly_amount": "₹5,000", "debit_date": "5th"},
                    {"scheme": "Cymbal ELSS Tax Saver Fund", "monthly_amount": "₹5,000", "debit_date": "10th"},
                ],
            },
        }
        self._emit("portfolio_viewed", result)
        return result

    async def get_fund_nav_details(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch details for a requested fund scheme."""
        query = str(params.get("scheme_name", "")).lower()
        matched = None
        for key, fund in MOCK_FUNDS.items():
            if key in query or any(word in fund["scheme_name"].lower() for word in query.split()):
                matched = fund
                break
        if not matched:
            matched = MOCK_FUNDS["flexi"]

        result = {"status": "success", "fund": matched}
        self._emit("fund_nav_fetched", {"scheme": matched["scheme_name"], "nav": matched["nav"]})
        return result

    async def manage_sip_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute or modify an SIP order idempotently."""
        async with self._lock:
            scheme = str(params.get("scheme_name", "Cymbal Flexi Cap Fund")).strip()
            amount = str(params.get("monthly_amount", "₹5,000")).strip()
            date = str(params.get("debit_date", "5th")).strip()
            action = str(params.get("action", "create")).strip()

            order_key = f"{scheme.lower()}:{amount.lower()}:{date.lower()}:{action.lower()}"
            if self._last_order_key == order_key and self._last_order_result:
                return self._last_order_result

            order_id = f"CYMBAL-SIP-{abs(hash(order_key)) % 90000 + 10000}"
            result = {
                "status": "confirmed",
                "order_id": order_id,
                "action": action,
                "scheme_name": scheme,
                "monthly_amount": amount,
                "debit_date": date,
                "message": f"SIP mandate successfully registered for {scheme} at {amount}/month on {date} of every month.",
            }
            self._last_order_key = order_key
            self._last_order_result = result

            self._emit("sip_order_confirmed", result)
            return result
