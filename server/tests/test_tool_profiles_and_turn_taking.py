"""Unit tests for Requirement R4 (Lean Tool Profile) and Requirement R5 (Configurable Turn-Taking & Environment Contract)."""

import os
import json
import unittest
from unittest.mock import patch

from tools.tool_definitions import (
    get_tools_for_profile,
    get_live_streaming_tools,
    get_standard_tools,
    calculate_returns_schema,
    search_knowledge_base_schema,
    retrieve_memory_schema,
    save_memory_schema,
    get_current_time_schema,
    get_onboarding_guide_schema,
)


class TestToolProfilesAndTurnTaking(unittest.TestCase):
    """Verifies R4 lean vs full tool profiles, dynamic tools parsing, and R5 configuration."""

    def test_lean_tool_profile_returns_4_tools(self):
        """Lean profile must return exactly the 4 real-time conversational tools."""
        tools = get_tools_for_profile(profile="lean")
        self.assertEqual(len(tools), 4)
        tool_names = [t.name for t in tools]
        expected_names = [
            "calculate_returns",
            "search_knowledge_base",
            "retrieve_memory",
            "save_memory",
        ]
        self.assertEqual(tool_names, expected_names)

    def test_full_tool_profile_returns_6_tools(self):
        """Full profile must return all 6 tools."""
        tools = get_tools_for_profile(profile="full")
        self.assertEqual(len(tools), 6)
        tool_names = [t.name for t in tools]
        expected_names = [
            "get_current_time",
            "search_knowledge_base",
            "calculate_returns",
            "get_onboarding_guide",
            "retrieve_memory",
            "save_memory",
        ]
        self.assertEqual(tool_names, expected_names)

    def test_default_profile_is_lean_when_env_unset(self):
        """When profile is omitted and TOOL_PROFILE env is unset, default must be lean (4 tools)."""
        with patch.dict(os.environ, {}, clear=True):
            tools = get_tools_for_profile()
            self.assertEqual(len(tools), 4)
            tool_names = [t.name for t in tools]
            self.assertIn("calculate_returns", tool_names)
            self.assertIn("search_knowledge_base", tool_names)
            self.assertIn("retrieve_memory", tool_names)
            self.assertIn("save_memory", tool_names)
            self.assertNotIn("get_current_time", tool_names)
            self.assertNotIn("get_onboarding_guide", tool_names)

    def test_env_tool_profile_override(self):
        """When profile is omitted, get_tools_for_profile must respect TOOL_PROFILE env."""
        with patch.dict(os.environ, {"TOOL_PROFILE": "full"}):
            tools = get_tools_for_profile()
            self.assertEqual(len(tools), 6)
            self.assertEqual([t.name for t in tools], [
                "get_current_time",
                "search_knowledge_base",
                "calculate_returns",
                "get_onboarding_guide",
                "retrieve_memory",
                "save_memory",
            ])

        with patch.dict(os.environ, {"TOOL_PROFILE": "lean"}):
            tools = get_tools_for_profile()
            self.assertEqual(len(tools), 4)

    def test_case_and_whitespace_insensitivity(self):
        """Profile string matching must be case and whitespace insensitive."""
        tools_lean_caps = get_tools_for_profile("  LEAN  ")
        self.assertEqual(len(tools_lean_caps), 4)

        tools_full_caps = get_tools_for_profile("  FULL  ")
        self.assertEqual(len(tools_full_caps), 6)

    def test_dynamic_tools_json_parsing_lean(self):
        """Dynamic tools JSON must append custom schemas to lean profile."""
        dynamic_json = json.dumps([
            {
                "name": "custom_forex_rates",
                "description": "Get forex conversion rates.",
                "properties": {"currency": {"type": "string"}},
                "required": ["currency"],
            }
        ])
        tools = get_tools_for_profile("lean", dynamic_tools_json=dynamic_json)
        self.assertEqual(len(tools), 5)
        self.assertEqual(tools[-1].name, "custom_forex_rates")
        self.assertEqual(tools[-1].description, "Get forex conversion rates.")

    def test_dynamic_tools_json_parsing_full(self):
        """Dynamic tools JSON must append custom schemas to full profile."""
        dynamic_json = json.dumps([
            {
                "name": "custom_forex_rates",
                "description": "Get forex conversion rates.",
            }
        ])
        tools = get_tools_for_profile("full", dynamic_tools_json=dynamic_json)
        self.assertEqual(len(tools), 7)
        self.assertEqual(tools[-1].name, "custom_forex_rates")

    def test_malformed_dynamic_tools_json_resilience(self):
        """Malformed JSON must not raise and should return standard profile tools."""
        tools = get_tools_for_profile("lean", dynamic_tools_json="INVALID_JSON{}}")
        self.assertEqual(len(tools), 4)

    def test_get_live_streaming_tools_delegation(self):
        """get_live_streaming_tools must delegate to get_tools_for_profile using TOOL_PROFILE env."""
        with patch.dict(os.environ, {"TOOL_PROFILE": "lean"}):
            tools = get_live_streaming_tools()
            self.assertEqual(len(tools), 4)
            self.assertEqual([t.name for t in tools], [
                "calculate_returns",
                "search_knowledge_base",
                "retrieve_memory",
                "save_memory",
            ])

        with patch.dict(os.environ, {"TOOL_PROFILE": "full"}):
            tools = get_live_streaming_tools()
            self.assertEqual(len(tools), 6)

    def test_get_standard_tools_delegation(self):
        """get_standard_tools must return all 6 tools from the full profile."""
        tools = get_standard_tools()
        self.assertEqual(len(tools), 6)
        self.assertEqual([t.name for t in tools], [
            "get_current_time",
            "search_knowledge_base",
            "calculate_returns",
            "get_onboarding_guide",
            "retrieve_memory",
            "save_memory",
        ])


if __name__ == "__main__":
    unittest.main()
