"""
LAPTOP AI — PHASE 6, QUEUE 1: TEST 1 FAILURE INVESTIGATION TEST SUITE
Verifies all 7 diagnostic and functional points:
1. Direct active-window inspection.
2. Desktop tool registration at startup.
3. Desktop tool inclusion in agent tool selection (intent-based scoping).
4. Desktop tool visibility in provider schemas (Gemini, Groq, OpenRouter).
5. End-to-end chat invocation (active window query returns real telemetry).
6. Emergency-stop enforcement.
7. Approval enforcement for consequential desktop actions.
"""
from __future__ import annotations
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from fastapi.testclient import TestClient
from app.main import app
from app.core.db import init_db
from app.core.emergency import is_emergency_stopped, trigger_emergency_stop, clear_emergency_stop
from app.core.approval import ApprovalLifecycle
from app.tools.registry import registry
from app.tools.native import register
from app.desktop import register_desktop_tools, get_active_window
from app.core.token_budget import filter_relevant_tools


class TestPhase6Test1Investigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        clear_emergency_stop()
        register()
        register_desktop_tools()

    def tearDown(self):
        clear_emergency_stop()

    # 1. Direct active-window inspection
    def test_01_direct_active_window_inspection(self):
        """Verify active-window function directly retrieves real telemetry."""
        res = get_active_window()
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("success"), res.get("error"))
        self.assertIn("has_active_window", res)
        self.assertIn("hwnd", res)
        self.assertIn("title", res)
        self.assertIn("process", res)
        self.assertIn("pid", res)
        self.assertIn("rect", res)
        self.assertIn("is_minimized", res)
        print(f" [PASS] 01. Direct active window inspection: {res.get('title')} ({res.get('process')}, HWND: {res.get('hwnd')})")

    # 2. Desktop tool registration at startup
    def test_02_desktop_tool_registration_at_startup(self):
        """Verify desktop.window.active is registered in the central registry."""
        self.assertIn("desktop.window.active", registry.items)
        spec = registry.items["desktop.window.active"]
        self.assertEqual(spec.source, "desktop")
        self.assertEqual(spec.risk, "read")
        self.assertTrue(callable(spec.handler))
        print(" [PASS] 02. Desktop tool registration at startup verified.")

    # 3. Desktop tool inclusion in agent tool selection
    def test_03_desktop_tool_scoping(self):
        """Verify intent-based scoping includes desktop.window.active for active window requests."""
        user_msg = "Identify my currently active Windows application. Return its window title, process name, PID, HWND, dimensions, and minimized status."
        raw_tools = registry.get_openai_tools()
        scoped = filter_relevant_tools(raw_tools, user_msg, provider="groq")
        scoped_names = [t["function"]["name"] for t in scoped]

        self.assertIn("desktop_window_active", scoped_names)
        self.assertIn("desktop_window_list", scoped_names)
        print(f" [PASS] 03. Intent-based tool scoping verified (selected: {scoped_names}).")

    # 4. Desktop tool visibility in provider schemas
    def test_04_provider_schema_visibility(self):
        """Verify desktop tools appear in schemas for Groq, OpenRouter, and Gemini."""
        # OpenAI format (Groq & OpenRouter)
        oai_tools = registry.get_openai_tools()
        oai_names = [t["function"]["name"] for t in oai_tools]
        self.assertIn("desktop_window_active", oai_names)
        self.assertIn("desktop_window_list", oai_names)
        self.assertIn("desktop_screen_capture", oai_names)

        # Gemini format
        gem_tools = registry.get_gemini_tools()
        self.assertTrue(len(gem_tools) > 0)
        gem_decl = gem_tools[0].get("functionDeclarations", [])
        gem_names = [d["name"] for d in gem_decl]
        self.assertIn("desktop_window_active", gem_names)
        self.assertIn("desktop_window_list", gem_names)
        self.assertIn("desktop_screen_capture", gem_names)

        # Name mapping bidirectional check
        p_name = registry.to_provider_name("desktop.window.active")
        self.assertEqual(p_name, "desktop_window_active")
        r_name = registry.from_provider_name("desktop_window_active")
        self.assertEqual(r_name, "desktop.window.active")
        print(" [PASS] 04. Provider schema visibility verified across Groq, OpenRouter, and Gemini.")

    # 5. End-to-end chat invocation
    def test_05_end_to_end_chat_invocation(self):
        """Verify /api/chat invokes desktop.window.active and returns actual Windows telemetry."""
        with TestClient(app) as client:
            payload = {
                "message": "Identify my currently active Windows application. Return its window title, process name, PID, HWND, dimensions, and minimized status.",
                "provider": "openrouter",
                "model": "openrouter/auto"
            }
            res = client.post("/api/chat", json=payload, headers={"origin": "http://127.0.0.1:5173"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            reply = data.get("reply", "")

            # Verify that the response does not claim tools are unavailable
            self.assertNotIn("none of the available tools", reply.lower())
            self.assertNotIn("no desktop window tool", reply.lower())

            # Verify presence of real window details in response
            has_window_telemetry = any(k in reply.lower() for k in ("hwnd", "pid", "window title", "dimensions", "process"))
            self.assertTrue(has_window_telemetry, f"Reply did not contain real window telemetry: {reply}")
            print(f" [PASS] 05. End-to-end chat invocation verified. Assistant replied with real telemetry.")

    # 6. Emergency-stop enforcement
    def test_06_emergency_stop_enforcement(self):
        """Verify Global Emergency Stop blocks desktop tool execution."""
        trigger_emergency_stop("Test emergency stop")
        self.assertTrue(is_emergency_stopped())

        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(registry.execute("desktop.window.active", {}))
        loop.close()

        self.assertFalse(res.get("success"))
        self.assertIn("emergency stop", res.get("error", "").lower())
        clear_emergency_stop()
        print(" [PASS] 06. Emergency stop enforcement verified.")

    # 7. Approval enforcement for consequential desktop actions
    def test_07_approval_enforcement(self):
        """Verify consequential desktop tools require user approval."""
        spec_focus = registry.items["desktop.window.focus"]
        self.assertEqual(spec_focus.risk, "approval")

        spec_click = registry.items["desktop.mouse.click"]
        self.assertEqual(spec_click.risk, "approval")

        spec_type = registry.items["desktop.keyboard.type"]
        self.assertEqual(spec_type.risk, "approval")

        # Verify approval creation
        appr = ApprovalLifecycle.create_request("desktop.window.focus", {"title": "Brave"})
        self.assertEqual(appr["status"], "pending")
        print(" [PASS] 07. Approval enforcement verified for consequential desktop actions.")


if __name__ == "__main__":
    unittest.main(verbosity=2)

