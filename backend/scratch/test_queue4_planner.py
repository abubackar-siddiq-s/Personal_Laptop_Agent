import os
import sys
import unittest
import json
from pathlib import Path

# Setup path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.db import conn, init_db
from app.planner.models import StepDefinition
from app.planner.planner import task_planner, TaskPlanner


class TestIntelligentTaskPlanner(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    async def test_01_plan_generation_and_persistence(self):
        """Test generating structured multi-step plan from natural language and verifying SQLite persistence."""
        plan = await task_planner.create_plan(
            user_request="Audit system health, inspect high-CPU processes, and capture a screenshot",
            objective="Inspect hardware telemetry and capture desktop screen",
        )
        self.assertIsNotNone(plan)
        task_id = plan["id"]
        self.assertTrue(task_id.startswith("task_"))
        self.assertGreaterEqual(len(plan["steps"]), 2)
        self.assertEqual(plan["objective"], "Inspect hardware telemetry and capture desktop screen")

        # Verify steps are ordered
        step_indices = [s["step_index"] for s in plan["steps"]]
        self.assertEqual(step_indices, sorted(step_indices))

        # Verify persistence across fresh raw sqlite3 connection (restart simulation)
        with conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["id"], task_id)
            self.assertIn("Audit system health", row["user_request"])

            step_rows = c.execute("SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_index ASC", (task_id,)).fetchall()
            self.assertEqual(len(step_rows), len(plan["steps"]))

    async def test_02_dependency_ordering_and_validation(self):
        """Test valid sequential dependencies pass validation."""
        valid_steps = [
            StepDefinition(
                step_index=1,
                title="Step 1",
                tool_name="native.system.overview",
                dependencies=[],
            ),
            StepDefinition(
                step_index=2,
                title="Step 2",
                tool_name="native.system.processes",
                dependencies=[1],
            ),
            StepDefinition(
                step_index=3,
                title="Step 3",
                tool_name="native.files.search",
                dependencies=[1, 2],
            ),
        ]
        is_valid, err = task_planner.validate_plan(valid_steps)
        self.assertTrue(is_valid)
        self.assertIsNone(err)

    def test_03_circular_dependency_detection(self):
        """Test circular dependency detection catches direct and indirect cycles."""
        # Direct self-dependency
        self_dep_steps = [
            StepDefinition(
                step_index=1,
                title="Self cycle",
                tool_name="native.system.overview",
                dependencies=[1],
            ),
        ]
        is_valid, err = task_planner.validate_plan(self_dep_steps)
        self.assertFalse(is_valid)
        self.assertIn("Circular dependency", err)

        # 2-step cycle: 1 depends on 2, 2 depends on 1
        two_cycle_steps = [
            StepDefinition(
                step_index=1,
                title="Step 1",
                tool_name="native.system.overview",
                dependencies=[2],
            ),
            StepDefinition(
                step_index=2,
                title="Step 2",
                tool_name="native.system.processes",
                dependencies=[1],
            ),
        ]
        is_valid_2, err_2 = task_planner.validate_plan(two_cycle_steps)
        self.assertFalse(is_valid_2)
        self.assertIn("Circular dependency", err_2)

        # Missing step dependency index
        missing_dep_steps = [
            StepDefinition(
                step_index=1,
                title="Step 1",
                tool_name="native.system.overview",
                dependencies=[99],
            ),
        ]
        is_valid_3, err_3 = task_planner.validate_plan(missing_dep_steps)
        self.assertFalse(is_valid_3)
        self.assertIn("non-existent step index 99", err_3)

    async def test_04_risk_classification_and_consequential_approval(self):
        """Test read-only tools have low risk; consequential tools require explicit approval."""
        # Read-only request: system overview
        read_plan = await task_planner.create_plan(
            user_request="Show CPU and memory telemetry",
        )
        self.assertEqual(read_plan["risk_level"], "low")
        self.assertFalse(read_plan["approval_required"])
        self.assertEqual(read_plan["status"], "planned")

        # Consequential request: launching notepad application
        conseq_plan = await task_planner.create_plan(
            user_request="Launch notepad application on windows",
        )
        self.assertEqual(conseq_plan["risk_level"], "consequential")
        self.assertTrue(conseq_plan["approval_required"])
        self.assertEqual(conseq_plan["status"], "awaiting_approval")
        # Ensure planning did NOT execute the tool automatically
        step_1 = conseq_plan["steps"][0]
        self.assertEqual(step_1["status"], "awaiting_approval")
        self.assertTrue(step_1["requires_approval"])

    async def test_05_plan_inspection_and_editing(self):
        """Test inspecting and updating an existing task plan before execution."""
        plan = await task_planner.create_plan(
            user_request="Draft task for inspection and editing",
        )
        tid = plan["id"]

        # Inspect
        fetched = task_planner.get_task(tid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], tid)

        # Edit plan with updated objective and new steps
        new_steps = [
            {
                "step_index": 1,
                "title": "Custom Step 1",
                "tool_name": "native.system.overview",
                "arguments": {},
                "dependencies": [],
            },
            {
                "step_index": 2,
                "title": "Custom Step 2",
                "tool_name": "native.system.network",
                "arguments": {},
                "dependencies": [1],
            },
        ]
        updated = task_planner.edit_plan(
            task_id=tid,
            title="Updated Title For Task",
            objective="Updated Objective",
            steps=new_steps,
        )
        self.assertEqual(updated["title"], "Updated Title For Task")
        self.assertEqual(updated["objective"], "Updated Objective")
        self.assertEqual(len(updated["steps"]), 2)
        self.assertEqual(updated["steps"][1]["title"], "Custom Step 2")
        self.assertEqual(updated["steps"][1]["dependencies"], [1])

    def test_06_invalid_edit_rejection(self):
        """Test editing a plan with invalid or circular dependencies is rejected."""
        plan_id = "test_invalid_edit_task"
        with conn() as c:
            c.execute("INSERT OR REPLACE INTO tasks(id, title, user_request, objective, status) VALUES (?, 'Test', 'Req', 'Obj', 'planned')", (plan_id,))

        invalid_cycle_steps = [
            {"step_index": 1, "tool_name": "native.system.overview", "dependencies": [2]},
            {"step_index": 2, "tool_name": "native.system.processes", "dependencies": [1]},
        ]
        with self.assertRaises(ValueError):
            task_planner.edit_plan(task_id=plan_id, steps=invalid_cycle_steps)


if __name__ == "__main__":
    unittest.main()
