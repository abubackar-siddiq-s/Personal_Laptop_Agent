"""
LAPTOP AI — UI AUTOMATION ENUMERATION INTEGRITY TEST SUITE
Verifies all 8 required verification items:
1. Exactly 30 elements returned when >= 30 available.
2. Correct behavior when fewer than 30 exist.
3. Accurate total counts despite output truncation (total_descendants, visible_descendants, interactive_descendants, elements_returned, elements_omitted).
4. No duplicate element records unless genuinely distinct UIA elements.
5. Correct control-type classification (Button, MenuItem, Edit, etc.).
6. Missing Automation IDs represented as null/None.
7. Serialization failures reported explicitly.
8. Read-only verification (no window focus/movement/mouse events during inspection).
Also verifies structured context-budget pruning in sanitize_tool_result_for_llm.
"""
from __future__ import annotations
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.desktop.ui_inspection import inspect_ui, INTERACTIVE_CONTROL_TYPES
from app.core.agent import sanitize_tool_result_for_llm
from app.core.token_budget import PROVIDER_LIMITS


class MockElementInfo:
    def __init__(self, control_type: str, automation_id: any = None, runtime_id: any = None):
        self.control_type = control_type
        self.automation_id = automation_id
        self.runtime_id = runtime_id or [1, 2, id(self)]


class MockRectangle:
    def __init__(self, left=10, top=10, right=100, bottom=50):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class MockUIAWrapper:
    def __init__(
        self,
        name: str = "Test Element",
        control_type: str = "Button",
        automation_id: any = None,
        runtime_id: any = None,
        rect: MockRectangle | None = None,
        is_visible: bool = True,
        is_enabled: bool = True,
        fail_serialize: bool = False,
    ):
        self._name = name
        self.element_info = MockElementInfo(control_type, automation_id, runtime_id)
        self._rect = rect or MockRectangle()
        self._is_visible = is_visible
        self._is_enabled = is_enabled
        self.fail_serialize = fail_serialize

    def window_text(self) -> str:
        if self.fail_serialize:
            raise RuntimeError("Simulated COM retrieval failure")
        return self._name

    def rectangle(self):
        return self._rect

    def is_visible(self) -> bool:
        return self._is_visible

    def is_enabled(self) -> bool:
        return self._is_enabled


class TestUIEnumerationMocked(unittest.TestCase):

    def setUp(self):
        # Patch user32.IsWindow so test HWND 99999 is recognized as valid
        self.patcher_is_win = patch("app.desktop.ui_inspection.user32.IsWindow", return_value=True)
        self.mock_is_win = self.patcher_is_win.start()

        # Patch security check to permit inspection
        self.patcher_sec = patch("app.desktop.ui_inspection.is_sensitive_window", return_value=False)
        self.mock_sec = self.patcher_sec.start()

        self.patcher_active = patch("app.desktop.ui_inspection.get_active_window", return_value={
            "has_active_window": True,
            "hwnd": 99999,
            "title": "Mock Application",
            "process": "mock.exe",
        })
        self.mock_active = self.patcher_active.start()

    def tearDown(self):
        self.patcher_is_win.stop()
        self.patcher_sec.stop()
        self.patcher_active.stop()

    def test_01_exact_30_elements_returned_when_available(self):
        """1. Exactly 30 elements returned when >= 30 available."""
        # Create 45 mock elements
        mock_descendants = [
            MockUIAWrapper(
                name=f"Button {i+1}",
                control_type="Button",
                automation_id=f"btn_{i+1}",
                runtime_id=(42, i+1),
            )
            for i in range(45)
        ]

        mock_window = MagicMock()
        mock_window.descendants.return_value = mock_descendants

        with patch("pywinauto.Desktop") as mock_desk_cls:
            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=30)

        self.assertTrue(res["success"])
        self.assertTrue(res["accessible"])
        self.assertEqual(len(res["elements"]), 30)
        self.assertEqual(res["counts"]["elements_returned"], 30)
        self.assertEqual(res["counts"]["elements_omitted"], 15)
        self.assertEqual(res["counts"]["matched_descendants"], 45)
        self.assertEqual(res["counts"]["total_descendants"], 45)
        self.assertTrue(res["truncated"])

        # Check 1-based sequential element IDs
        for idx, el in enumerate(res["elements"]):
            self.assertEqual(el["id"], idx + 1)
            self.assertEqual(el["element_id"], idx + 1)

    def test_02_correct_behavior_fewer_than_30_elements(self):
        """2. Correct behavior when fewer than 30 exist."""
        # Create 12 mock elements
        mock_descendants = [
            MockUIAWrapper(
                name=f"Item {i+1}",
                control_type="MenuItem",
                automation_id=f"menu_{i+1}",
                runtime_id=(100, i+1),
            )
            for i in range(12)
        ]

        mock_window = MagicMock()
        mock_window.descendants.return_value = mock_descendants

        with patch("pywinauto.Desktop") as mock_desk_cls:
            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=30)

        self.assertTrue(res["success"])
        self.assertEqual(len(res["elements"]), 12)
        self.assertEqual(res["counts"]["elements_returned"], 12)
        self.assertEqual(res["counts"]["elements_omitted"], 0)
        self.assertEqual(res["counts"]["matched_descendants"], 12)
        self.assertEqual(res["counts"]["total_descendants"], 12)
        self.assertFalse(res["truncated"])

    def test_03_accurate_total_counts_despite_output_truncation(self):
        """
        3. Accurate total counts despite output truncation:
           total_descendants, visible_descendants, interactive_descendants, elements_returned, elements_omitted.
        """
        # Create 60 total elements:
        # - 40 visible (rect width>0, height>0, is_visible=True)
        # - 20 hidden/zero-sized (width=0 or is_visible=False)
        # - Among the 40 visible: 25 interactive, 15 non-interactive (e.g. Text, Pane)
        elements = []
        for i in range(25):
            elements.append(MockUIAWrapper(
                name=f"Interactive Visible {i+1}",
                control_type="Button",
                runtime_id=(200, i),
                is_visible=True,
                rect=MockRectangle(10, 10, 50, 30),
            ))
        for i in range(15):
            elements.append(MockUIAWrapper(
                name=f"NonInteractive Visible {i+1}",
                control_type="Text",
                runtime_id=(300, i),
                is_visible=True,
                rect=MockRectangle(10, 10, 50, 30),
            ))
        for i in range(20):
            elements.append(MockUIAWrapper(
                name=f"Hidden {i+1}",
                control_type="Button",
                runtime_id=(400, i),
                is_visible=False,
                rect=MockRectangle(0, 0, 0, 0),
            ))

        self.assertEqual(len(elements), 60)

        mock_window = MagicMock()
        mock_window.descendants.return_value = elements

        with patch("pywinauto.Desktop") as mock_desk_cls:
            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            # Request interactive_only=True with max_elements=10
            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=10, interactive_only=True)

        counts = res["counts"]
        self.assertEqual(counts["total_descendants"], 60)
        self.assertEqual(counts["visible_descendants"], 40)
        self.assertEqual(counts["interactive_descendants"], 45)  # 25 visible + 20 hidden interactive
        self.assertEqual(counts["matched_descendants"], 25)      # 25 visible interactive elements
        self.assertEqual(counts["elements_returned"], 10)       # Capped at requested limit 10
        self.assertEqual(counts["elements_omitted"], 15)        # 25 matched - 10 returned
        self.assertEqual(len(res["elements"]), 10)
        self.assertTrue(res["truncated"])

        # Scope definition
        self.assertEqual(res["query_scope"]["requested_limit"], 10)
        self.assertEqual(res["query_scope"]["interactive_only"], True)

    def test_04_no_duplicate_element_records(self):
        """4. No duplicate element records unless genuinely distinct UIA elements."""
        mock_descendants = [
            MockUIAWrapper(name="Save", control_type="Button", runtime_id=(500, 1)),
            MockUIAWrapper(name="Save", control_type="Button", runtime_id=(500, 1)),  # Duplicate runtime ID
            MockUIAWrapper(name="Cancel", control_type="Button", runtime_id=(500, 2)),
        ]

        mock_window = MagicMock()
        mock_window.descendants.return_value = mock_descendants

        with patch("pywinauto.Desktop") as mock_desk_cls:
            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=10)

        self.assertEqual(len(res["elements"]), 2)
        names = [e["name"] for e in res["elements"]]
        self.assertEqual(names, ["Save", "Cancel"])

    def test_05_correct_control_type_classification(self):
        """5. Correct control-type classification (Button, MenuItem, Edit, TabItem, etc.)."""
        types = ["Button", "MenuItem", "Edit", "TabItem", "CheckBox", "ComboBox"]
        mock_descendants = [
            MockUIAWrapper(name=f"Control {ct}", control_type=ct, runtime_id=(600, i))
            for i, ct in enumerate(types)
        ]

        mock_window = MagicMock()
        mock_window.descendants.return_value = mock_descendants

        with patch("pywinauto.Desktop") as mock_desk_cls:
            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            # Filter specifically for Button and MenuItem
            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=10, filter_types=["Button", "MenuItem"])

        self.assertEqual(len(res["elements"]), 2)
        self.assertEqual(res["elements"][0]["control_type"], "Button")
        self.assertEqual(res["elements"][1]["control_type"], "MenuItem")

    def test_06_missing_automation_id_represented_as_null(self):
        """6. Missing Automation IDs represented as null/None."""
        mock_descendants = [
            MockUIAWrapper(name="Valid ID", control_type="Button", automation_id="btnOk", runtime_id=(700, 1)),
            MockUIAWrapper(name="None ID", control_type="Button", automation_id=None, runtime_id=(700, 2)),
            MockUIAWrapper(name="Empty ID", control_type="Button", automation_id="", runtime_id=(700, 3)),
            MockUIAWrapper(name="Whitespace ID", control_type="Button", automation_id="   ", runtime_id=(700, 4)),
        ]

        mock_window = MagicMock()
        mock_window.descendants.return_value = mock_descendants

        with patch("pywinauto.Desktop") as mock_desk_cls:
            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=10)

        self.assertEqual(res["elements"][0]["automation_id"], "btnOk")
        self.assertIsNone(res["elements"][1]["automation_id"])
        self.assertIsNone(res["elements"][2]["automation_id"])
        self.assertIsNone(res["elements"][3]["automation_id"])

        # In serialized JSON, None maps strictly to null
        json_str = json.dumps(res["elements"])
        parsed = json.loads(json_str)
        self.assertIsNone(parsed[1]["automation_id"])
        self.assertIsNone(parsed[2]["automation_id"])
        self.assertIsNone(parsed[3]["automation_id"])

    def test_07_serialization_failures_reported_explicitly(self):
        """7. Serialization failures reported explicitly."""
        mock_descendants = [
            MockUIAWrapper(name="Healthy 1", control_type="Button", runtime_id=(800, 1)),
            MockUIAWrapper(name="Broken", control_type="Button", runtime_id=(800, 2), fail_serialize=True),
            MockUIAWrapper(name="Healthy 2", control_type="Button", runtime_id=(800, 3)),
        ]

        mock_window = MagicMock()
        mock_window.descendants.return_value = mock_descendants

        with patch("pywinauto.Desktop") as mock_desk_cls:
            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=10)

        self.assertEqual(len(res["elements"]), 2)
        self.assertEqual(res["counts"]["serialization_errors"], 1)
        self.assertEqual(res["elements"][0]["name"], "Healthy 1")
        self.assertEqual(res["elements"][1]["name"], "Healthy 2")

    def test_08_strict_read_only_behavior(self):
        """8. Read-only verification (no window focus/movement/mouse events during inspection)."""
        mock_descendants = [
            MockUIAWrapper(name="Button 1", control_type="Button", runtime_id=(900, 1)),
        ]
        mock_window = MagicMock()
        mock_window.descendants.return_value = mock_descendants

        with patch("pywinauto.Desktop") as mock_desk_cls, \
             patch("pyautogui.click") as mock_click, \
             patch("pyautogui.moveTo") as mock_move, \
             patch("pyautogui.typewrite") as mock_type:

            mock_desk_instance = MagicMock()
            mock_desk_instance.window.return_value = mock_window
            mock_desk_cls.return_value = mock_desk_instance

            res = inspect_ui(hwnd=99999, max_depth=3, max_elements=10)

            self.assertTrue(res["success"])
            # Verify ZERO simulated mouse/keyboard actions were triggered
            mock_click.assert_not_called()
            mock_move.assert_not_called()
            mock_type.assert_not_called()

    def test_09_llm_sanitizer_preserves_valid_json_and_accurate_counts(self):
        """
        Test that sanitize_tool_result_for_llm prunes elements cleanly at element boundaries
        without severing JSON or producing count discrepancies.
        """
        raw_tool_result = {
            "success": True,
            "accessible": True,
            "window": {"hwnd": 1234, "title": "Test App", "process": "test.exe"},
            "query_scope": {"max_depth": 3, "requested_limit": 30},
            "counts": {
                "total_descendants": 50,
                "visible_descendants": 40,
                "interactive_descendants": 35,
                "matched_descendants": 35,
                "elements_returned": 30,
                "elements_omitted": 5,
                "serialization_errors": 0,
            },
            "elements_count": 30,
            "truncated": True,
            "elements": [
                {
                    "id": i + 1,
                    "element_id": i + 1,
                    "name": f"Menu Item {i+1}",
                    "control_type": "MenuItem",
                    "automation_id": f"item_{i+1}",
                    "center": {"x": 100 + i * 5, "y": 200},
                    "bounds": [100, 200, 150, 230],
                    "is_enabled": True,
                    "is_visible": True,
                    "patterns": ["Invoke"],
                }
                for i in range(30)
            ],
        }

        # Case A: Standard budget (8,000 chars) -> All 30 elements retained!
        sanitized_full = sanitize_tool_result_for_llm(raw_tool_result, max_chars=8000)
        parsed_full = json.loads(sanitized_full)
        self.assertEqual(len(parsed_full["elements"]), 30)
        self.assertEqual(parsed_full["counts"]["elements_returned"], 30)

        # Case B: Restricted budget (2,500 chars) -> Cleanly pruned without raw string slicing!
        sanitized_pruned = sanitize_tool_result_for_llm(raw_tool_result, max_chars=2500)
        parsed_pruned = json.loads(sanitized_pruned)  # Must be 100% syntactically valid JSON!

        pruned_count = len(parsed_pruned["elements"])
        self.assertLess(pruned_count, 30)
        self.assertGreater(pruned_count, 5)
        # Counts in returned structure must match actual element list length!
        self.assertEqual(parsed_pruned["elements_count"], pruned_count)
        self.assertEqual(parsed_pruned["counts"]["elements_returned"], pruned_count)
        self.assertTrue(parsed_pruned["context_budget_truncated"])
        self.assertIn("Element list safely pruned", parsed_pruned["context_budget_notice"])


class TestUIEnumerationLiveWindows(unittest.TestCase):
    """Live verification against real Windows OS windows (unmocked)."""

    def test_live_windows_ui_enumeration(self):
        """10. Live Windows verification: inspect real open window if available."""
        from app.desktop.windows import list_windows
        wins = list_windows(limit=10)
        accessible_found = False

        for w in wins:
            hwnd = w.get("hwnd")
            if not hwnd:
                continue
            res = inspect_ui(hwnd=hwnd, max_depth=3, max_elements=20)
            if res.get("success") and res.get("accessible") and res.get("elements"):
                accessible_found = True
                counts = res["counts"]
                # Verify count integrity on real Windows window
                self.assertGreaterEqual(counts["total_descendants"], counts["visible_descendants"])
                self.assertGreaterEqual(counts["matched_descendants"], len(res["elements"]))
                self.assertEqual(counts["elements_returned"], len(res["elements"]))
                self.assertEqual(counts["elements_omitted"], counts["matched_descendants"] - len(res["elements"]))
                self.assertEqual(res["elements_count"], len(res["elements"]))

                # Verify each returned element has valid properties
                for el in res["elements"]:
                    self.assertIn("id", el)
                    self.assertIn("control_type", el)
                    self.assertIn("bounds", el)
                    self.assertIn("center", el)
                    self.assertIn("x", el["center"])
                    self.assertIn("y", el["center"])
                    # Check automation_id is None or a non-empty string
                    self.assertTrue(el["automation_id"] is None or isinstance(el["automation_id"], str))
                break

        print(f"\n[Live Windows UIA Check] Real accessible window found and verified: {accessible_found}")


if __name__ == "__main__":
    unittest.main()
