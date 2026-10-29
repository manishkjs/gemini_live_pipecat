"""Unit tests for Ananya (Cymbal Mutual Fund Advisor) architecture, tools, and cards."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from persona_tools.mf_advisor import (
    AnanyaMFExecutionEngine,
    get_portfolio_summary_schema,
    get_fund_nav_details_schema,
    manage_sip_order_schema,
    switch_phase_schema,
)
from persona_registry import (
    AnanyaMFAdvisorArchitecture,
    ArchitecturePattern,
    get_persona_architecture,
    resolve_persona_architecture,
)


class TestAnanyaMFAdvisor(unittest.IsolatedAsyncioTestCase):

    async def test_execution_engine_portfolio_summary(self):
        broadcast_mock = MagicMock()
        engine = AnanyaMFExecutionEngine(broadcast=broadcast_mock)

        result = await engine.get_portfolio_summary({})
        self.assertEqual(result["status"], "success")
        portfolio = result["portfolio"]
        self.assertEqual(portfolio["total_invested"], "₹4,85,000")
        self.assertEqual(portfolio["current_value"], "₹5,72,400")
        self.assertEqual(portfolio["xirr"], "18.02%")
        self.assertEqual(len(portfolio["active_sips"]), 2)
        broadcast_mock.assert_called_once()

    async def test_execution_engine_fund_nav(self):
        broadcast_mock = MagicMock()
        engine = AnanyaMFExecutionEngine(broadcast=broadcast_mock)

        result = await engine.get_fund_nav_details({"scheme_name": "Flexi Cap"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["fund"]["scheme_name"], "Cymbal Flexi Cap Fund")
        self.assertEqual(result["fund"]["nav"], "₹78.45")

        # ELSS fund lookup
        elss_res = await engine.get_fund_nav_details({"scheme_name": "ELSS Tax Saver"})
        self.assertEqual(elss_res["fund"]["scheme_name"], "Cymbal ELSS Tax Saver Fund")

    async def test_execution_engine_manage_sip_order_idempotent(self):
        broadcast_mock = MagicMock()
        engine = AnanyaMFExecutionEngine(broadcast=broadcast_mock)

        params = {
            "scheme_name": "Cymbal Flexi Cap Fund",
            "monthly_amount": "₹5,000",
            "debit_date": "10th",
            "action": "create",
        }
        res1 = await engine.manage_sip_order(params)
        self.assertEqual(res1["status"], "confirmed")
        order_id = res1["order_id"]
        self.assertTrue(order_id.startswith("CYMBAL-SIP-"))

        # Idempotent re-run returns exact same order
        res2 = await engine.manage_sip_order(params)
        self.assertEqual(res2["order_id"], order_id)

    def test_architecture_resolution(self):
        arch_type = resolve_persona_architecture("ananya-advisor")
        self.assertEqual(arch_type, ArchitecturePattern.JIT_MF_ADVISOR)

        # Alias resolution
        alias_type = resolve_persona_architecture("groww-advisor")
        self.assertEqual(alias_type, ArchitecturePattern.JIT_MF_ADVISOR)

        arch = get_persona_architecture("ananya-advisor")
        self.assertIsInstance(arch, AnanyaMFAdvisorArchitecture)
        self.assertTrue(arch.has_exclusive_tools())

    def test_tool_schemas_live_vs_cascade(self):
        arch = AnanyaMFAdvisorArchitecture()

        live_tools = arch.get_tool_schemas(engine="live")
        self.assertEqual(len(live_tools), 4)
        names = [t.name for t in live_tools]
        self.assertIn("switch_phase", names)
        self.assertIn("get_portfolio_summary", names)
        self.assertIn("get_fund_nav_details", names)
        self.assertIn("manage_sip_order", names)

        cascade_tools = arch.get_tool_schemas(engine="cascade")
        self.assertEqual(len(cascade_tools), 3)
        c_names = [t.name for t in cascade_tools]
        self.assertNotIn("switch_phase", c_names)
        self.assertIn("manage_sip_order", c_names)

    def test_system_prompt_composition(self):
        arch = AnanyaMFAdvisorArchitecture()

        live_prompt = arch.compose_system_prompt(None, engine="live")
        self.assertIn("Cymbal Investments", live_prompt)
        self.assertNotIn("Groww", live_prompt)

        cascade_prompt = arch.compose_system_prompt(None, engine="cascade")
        self.assertIn("Cymbal Investments", cascade_prompt)
        self.assertIn("Cymbal Flexi Cap Fund", cascade_prompt)
        self.assertNotIn("Groww", cascade_prompt)

    async def test_switch_phase_live(self):
        arch = AnanyaMFAdvisorArchitecture()
        mock_llm = MagicMock()
        mock_llm.inject_directive = AsyncMock(return_value=True)
        broadcast_mock = AsyncMock()

        arch.register_handlers(mock_llm, broadcast=broadcast_mock, engine="live")

        result = await arch._switch_phase({"phase_id": "SOP_02_SCHEME_DETAILS"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["delivery_status"], "sent")
        mock_llm.inject_directive.assert_awaited_once()
        broadcast_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
