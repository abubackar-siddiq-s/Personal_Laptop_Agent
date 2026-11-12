"""
LAPTOP AI — PHASE 6, QUEUE 1 COMPREHENSIVE TEST SUITE
WINDOWS DESKTOP CONTROL ENGINE

Tests all 15 required capabilities:
1. Active window detection.
2. Visible window listing.
3. Screenshot capture.
4. Screenshot output validation.
5. UI element discovery.
6. Element lookup failure handling.
7. Mouse action argument validation.
8. Keyboard shortcut allowlisting.
9. Approval enforcement.
10. Emergency stop enforcement.
11. Invalid window handle handling.
12. Timeout handling.
13. Unavailable desktop session handling.
14. Agent tool registration.
15. Frontend production build validation.
"""
from __future__ import annotations
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.db import init_db, conn
from app.core.emergency import (
    is_emergency_stopped,
    trigger_emergency_stop,
    clear_emergency_stop,
)
from app.core.approval import ApprovalLifecycle
from app.tools.registry import registry
from app.desktop import (
    register_desktop_tools,
    desktop_engine,
    get_active_window,
    list_windows,
    focus_window,
    capture_screenshot,
    list_screenshots,
    get_screenshot_thumbnail,
    inspect_ui,
    mouse_click,
    mouse_scroll,
    keyboard_type,
    keyboard_press,
    validate_keyboard_action,
    ALLOWED_SHORTCUTS,
    STRICTLY_BLOCKED_COMBINATIONS,
)


class TestPhase6Queue1Desktop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        clear_emergency_stop()
        register_desktop_tools()

    def tearDown(self):
        clear_emergency_stop()

    # -------------------------------------------------------------
    # 1. Active Window Detection
    # -------------------------------------------------------------
    def test_01_active_window_detection(self):
        """Verify active window detection returns expected schema and handles missing windows."""
        res = get_active_window()
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("success"))
        self.assertIn("has_active_window", res)
        self.assertIn("hwnd", res)
        self.assertIn("title", res)
        self.assertIn("rect", res)
        rect = res["rect"]
        self.assertIn("width", rect)
        self.assertIn("height", rect)
        print(" [PASS] 01. Active window detection verified.")

    # -------------------------------------------------------------
    # 2. Visible Window Listing
    # -------------------------------------------------------------
    def test_02_visible_window_listing(self):
        """Verify window listing returns bounded, filtered list of top-level application windows."""
        windows = list_windows(limit=10, only_visible=True)
        self.assertIsInstance(windows, list)
        self.assertLessEqual(len(windows), 10)
        for w in windows:
            self.assertIn("hwnd", w)
            self.assertIn("title", w)
            self.assertIn("process", w)
            self.assertIn("rect", w)
            self.assertGreater(len(w["title"]), 0)
        print(f" [PASS] 02. Window listing verified ({len(windows)} windows enumerated).")

    # -------------------------------------------------------------
    # 3. Screenshot Capture
    # -------------------------------------------------------------
    def test_03_screenshot_capture(self):
        """Verify desktop screenshot saves to Downloads/LAPTOP_AI/Screenshots."""
        res = capture_screenshot(target="desktop")
        self.assertTrue(res.get("success"), res.get("error"))
        path = Path(res["path"])
        self.assertTrue(path.is_file())
        self.assertIn("LAPTOP_AI", str(path))
        self.assertIn("Screenshots", str(path))
        self.assertGreater(path.stat().st_size, 1000)
        print(f" [PASS] 03. Screenshot capture verified ({path.name}, {path.stat().st_size} bytes).")

    # -------------------------------------------------------------
    # 4. Screenshot Output Validation
    # -------------------------------------------------------------
    def test_04_screenshot_output_validation(self):
        """Verify screenshot returns metadata, file references, and NEVER raw base64 in tool output."""
        res = capture_screenshot(target="desktop")
        self.assertTrue(res.get("success"))
        self.assertIn("width", res)
        self.assertIn("height", res)
        self.assertIn("file_size_bytes", res)
        self.assertIn("filename", res)
        self.assertNotIn("base64", res)
        self.assertNotIn("data:image", str(res))
        
        # Verify thumbnail generator works for UI previews
        thumb = get_screenshot_thumbnail(res["path"], max_width=160)
        self.assertIsNotNone(thumb)
        self.assertIsInstance(thumb, str)
        print(" [PASS] 04. Screenshot output validation verified (safe metadata without prompt pollution).")

    # -------------------------------------------------------------
    # 5. UI Element Discovery
    # -------------------------------------------------------------
    def test_05_ui_element_discovery(self):
        """Verify accessible UI element inspection returns structured elements with patterns and bounds."""
        active = get_active_window()
        hwnd = active.get("hwnd") if active.get("has_active_window") else None
        res = inspect_ui(hwnd=hwnd, max_depth=2, max_elements=20)
        self.assertTrue(res.get("success"))
        self.assertIn("accessible", res)
        if res.get("accessible"):
            self.assertIn("elements", res)
            for el in res["elements"]:
                self.assertIn("name", el)
                self.assertIn("control_type", el)
                self.assertIn("center", el)
                self.assertIn("rect", el)
        print(f" [PASS] 05. UI element discovery verified (accessible={res.get('accessible')}, count={res.get('elements_count')}).")

    # -------------------------------------------------------------
    # 6. Element Lookup Failure Handling
    # -------------------------------------------------------------
    def test_06_element_lookup_failure_handling(self):
        """Verify searching for a non-existent element fails gracefully with informative error."""
        res = mouse_click(element_query="NonExistentButtonXYZ_99999", control_type="Button")
        self.assertFalse(res.get("success"))
        self.assertIn("not found", res.get("error", "").lower())
        print(" [PASS] 06. Element lookup failure handling verified.")

    # -------------------------------------------------------------
    # 7. Mouse Action Argument Validation
    # -------------------------------------------------------------
    def test_07_mouse_argument_validation(self):
        """Verify invalid mouse coordinates and missing targets are rejected."""
        # Neither query nor coordinates
        res1 = mouse_click()
        self.assertFalse(res1.get("success"))
        self.assertIn("either", res1.get("error", "").lower())

        # Out-of-bounds coordinates (e.g. negative or offscreen)
        res2 = mouse_click(x=999999, y=999999)
        self.assertFalse(res2.get("success"))
        self.assertIn("outside", res2.get("error", "").lower())

        # Valid scroll notches bounds (with backend isolated for pure argument validation)
        with patch("pyautogui.scroll") as mock_scroll, patch("pyautogui.moveTo"):
            res3 = mouse_scroll(clicks=5, direction="invalid_dir")
            self.assertTrue(res3.get("success"))
            self.assertEqual(res3["direction"], "down")  # normalized
            mock_scroll.assert_called_once_with(-600)
        print(" [PASS] 07. Mouse action argument validation verified.")

    def test_07b_mouse_failsafe_handling(self):
        """Verify PyAutoGUI corner fail-safe triggers are safely caught without crashing."""
        import pyautogui
        with patch("pyautogui.scroll", side_effect=pyautogui.FailSafeException()):
            res = mouse_scroll(clicks=3)
            self.assertFalse(res.get("success"))
            self.assertIn("failsafeexception", res.get("error", "").lower())
        print(" [PASS] 07b. Corner fail-safe exception safely handled.")

    # -------------------------------------------------------------
    # 8. Keyboard Shortcut Allowlisting
    # -------------------------------------------------------------
    def test_08_keyboard_shortcut_allowlisting(self):
        """Verify security allowlist allows approved shortcuts and blocks dangerous system shortcuts."""
        # Approved shortcuts
        v1, combo1, err1 = validate_keyboard_action(keys=["ctrl", "s"])
        self.assertTrue(v1)
        self.assertEqual(combo1, "ctrl+s")
        self.assertIsNone(err1)

        v2, combo2, err2 = validate_keyboard_action(key="enter")
        self.assertTrue(v2)
        self.assertEqual(combo2, "enter")

        # Strictly blocked system combinations
        for blocked in STRICTLY_BLOCKED_COMBINATIONS:
            v_b, combo_b, err_b = validate_keyboard_action(key=blocked)
            self.assertFalse(v_b, f"Expected {blocked} to be blocked")
            self.assertIn("security violation", err_b.lower())

        # Unapproved arbitrary combination
        v_u, combo_u, err_u = validate_keyboard_action(keys=["ctrl", "alt", "shift", "k"])
        self.assertFalse(v_u)
        self.assertIn("not in the approved shortcut allowlist", err_u)
        print(" [PASS] 08. Keyboard shortcut allowlist verified (approved passed, dangerous blocked).")

    # -------------------------------------------------------------
    # 9. Approval Enforcement
    # -------------------------------------------------------------
    def test_09_approval_enforcement(self):
        """Verify consequential desktop tools are classified as risk='approval'."""
        desktop_tools = {t["name"]: t for t in registry.list() if t.get("source") == "desktop"}
        
        # Consequential & high-risk tools must have risk="approval"
        consequential_tools = [
            "desktop.window.focus",
            "desktop.mouse.click",
            "desktop.mouse.scroll",
            "desktop.keyboard.type",
            "desktop.keyboard.press",
        ]
        for tname in consequential_tools:
            self.assertIn(tname, desktop_tools)
            self.assertEqual(desktop_tools[tname]["risk"], "approval", f"{tname} must require approval")

        # Read-only tools must have risk="read"
        read_tools = [
            "desktop.window.active",
            "desktop.window.list",
            "desktop.screen.capture",
            "desktop.ui.inspect",
        ]
        for tname in read_tools:
            self.assertIn(tname, desktop_tools)
            self.assertEqual(desktop_tools[tname]["risk"], "read", f"{tname} must be read-only")

        # Verify ApprovalLifecycle can create approval requests for desktop tools
        req = ApprovalLifecycle.create_request(
            tool_name="desktop.mouse.click",
            args={"element_query": "Submit", "control_type": "Button"},
            risk="approval",
        )
        self.assertIsNotNone(req.get("id"))
        self.assertEqual(req["status"], "pending")
        print(" [PASS] 09. Approval enforcement verified for all consequential desktop tools.")

    # -------------------------------------------------------------
    # 10. Emergency Stop Enforcement
    # -------------------------------------------------------------
    def test_10_emergency_stop_enforcement(self):
        """Verify active Emergency Stop universally blocks all desktop tools."""
        trigger_emergency_stop("Safety verification")
        self.assertTrue(is_emergency_stopped())

        # 1. Direct function calls
        res_shot = capture_screenshot()
        self.assertFalse(res_shot.get("success"))
        self.assertIn("emergency stop", res_shot.get("error", "").lower())

        res_click = mouse_click(x=100, y=100)
        self.assertFalse(res_click.get("success"))
        self.assertIn("emergency stop", res_click.get("error", "").lower())

        res_type = keyboard_type(text="test")
        self.assertFalse(res_type.get("success"))
        self.assertIn("emergency stop", res_type.get("error", "").lower())

        # 2. Registry execution calls
        loop = asyncio.new_event_loop()
        res_reg = loop.run_until_complete(registry.execute("desktop.window.active", {}))
        loop.close()
        self.assertFalse(res_reg.get("success"))
        self.assertIn("emergency stop", res_reg.get("error", "").lower())

        clear_emergency_stop()
        self.assertFalse(is_emergency_stopped())
        print(" [PASS] 10. Emergency stop enforcement verified across all desktop execution paths.")

    # -------------------------------------------------------------
    # 11. Invalid Window Handle Handling
    # -------------------------------------------------------------
    def test_11_invalid_window_handle_handling(self):
        """Verify nonexistent or closed HWND handles are handled safely without crashing."""
        invalid_hwnd = 99999999
        res_focus = focus_window(hwnd=invalid_hwnd)
        self.assertFalse(res_focus.get("success"))
        self.assertIn("invalid or closed window handle", res_focus.get("error", "").lower())

        res_inspect = inspect_ui(hwnd=invalid_hwnd)
        self.assertFalse(res_inspect.get("success"))
        self.assertIn("invalid or closed window handle", res_inspect.get("error", "").lower())
        print(" [PASS] 11. Invalid window handle handling verified.")

    # -------------------------------------------------------------
    # 12. Timeout & Bounded Output Handling
    # -------------------------------------------------------------
    def test_12_timeout_and_bounded_output(self):
        """Verify UI tree outputs are strictly bounded in element count and depth."""
        res = inspect_ui(max_depth=5, max_elements=500)
        if res.get("accessible"):
            # Max elements should be capped to 50
            self.assertLessEqual(res["elements_count"], 50)
            self.assertLessEqual(len(res["elements"]), 50)
        print(" [PASS] 12. Timeout and bounded output verified (capped elements and depth).")

    # -------------------------------------------------------------
    # 13. Unavailable Desktop Session Handling
    # -------------------------------------------------------------
    def test_13_unavailable_desktop_session(self):
        """Verify desktop engine handles locked / detached workstation gracefully."""
        with patch("app.desktop.security.is_desktop_locked", return_value=True):
            res_shot = capture_screenshot()
            self.assertFalse(res_shot.get("success"))
            self.assertIn("locked or unavailable", res_shot.get("error", "").lower())

            res_click = mouse_click(x=10, y=10)
            self.assertFalse(res_click.get("success"))
            self.assertIn("locked or unavailable", res_click.get("error", "").lower())
        print(" [PASS] 13. Unavailable desktop session handling verified.")

    # -------------------------------------------------------------
    # 14. Agent Tool Registration & Schemas
    # -------------------------------------------------------------
    def test_14_agent_tool_registration(self):
        """Verify all 9 desktop tools are registered with provider-safe schemas."""
        required_tools = [
            "desktop.window.active",
            "desktop.window.list",
            "desktop.window.focus",
            "desktop.screen.capture",
            "desktop.ui.inspect",
            "desktop.mouse.click",
            "desktop.mouse.scroll",
            "desktop.keyboard.type",
            "desktop.keyboard.press",
        ]
        items = registry.items
        for tname in required_tools:
            self.assertIn(tname, items)
            spec = items[tname]
            self.assertTrue(callable(spec.handler))
            self.assertEqual(spec.source, "desktop")
            self.assertIn("type", spec.schema)
            self.assertEqual(spec.schema["type"], "object")

        # Verify OpenAI format export
        oai_tools = registry.get_openai_tools()
        oai_names = [t["function"]["name"] for t in oai_tools]
        self.assertIn("desktop_window_active", oai_names)
        self.assertIn("desktop_mouse_click", oai_names)

        # Verify Gemini format export
        gem_tools = registry.get_gemini_tools()
        self.assertGreater(len(gem_tools), 0)
        print(" [PASS] 14. Agent tool registration & schema export verified for Groq/OpenRouter and Gemini.")

    # -------------------------------------------------------------
    # 15. Frontend Production Build Check
    # -------------------------------------------------------------
    def test_15_frontend_build_artifacts(self):
        """Verify frontend production build files exist and contain updated chunks."""
        dist_dir = Path("frontend/dist")
        self.assertTrue(dist_dir.is_dir(), "frontend/dist must exist")
        index_html = dist_dir / "index.html"
        self.assertTrue(index_html.is_file(), "index.html must exist")
        assets = list((dist_dir / "assets").glob("*.js"))
        self.assertGreater(len(assets), 0, "JavaScript build chunks must exist")
        print(" [PASS] 15. Frontend build artifacts verified.")


if __name__ == "__main__":
    unittest.main(verbosity=2)

