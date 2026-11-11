import os
import sys
import unittest
import json
import asyncio

# Setup path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.db import conn, init_db
from app.tools.registry import registry
from app.core.approval import ApprovalLifecycle
from app.planner.models import StepDefinition
from app.planner.planner import task_planner
from app.planner.executor import task_executor, TaskExecutor


class TestTaskExecutionEngine(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        from app.tools.native import register
        register()

    async def test_01_execution_dependency_ordering(self):
        """Test multi-step tasks execute in strict dependency order with step checkpoints."""
        # Create a 2-step plan with dependency 1 -> 2
        plan = await task_planner.create_plan(
            user_request="Collect system overview and list network interfaces",
            objective="Telemetry inspection",
        )
        tid = plan["id"]

        # Execute
        result = await task_executor.execute_task(tid)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed_steps"], 2)

        # Check step results
        steps = result["steps"]
        self.assertEqual(steps[0]["status"], "completed")
        self.assertIsNotNone(steps[0]["result"])
        self.assertEqual(steps[1]["status"], "completed")
        self.assertIsNotNone(steps[1]["result"])
        self.assertGreaterEqual(steps[1]["started_at"], steps[0]["started_at"])

    async def test_02_idempotency_and_no_duplicate_execution(self):
        """Test completed steps are preserved and never re-executed upon repeated execute_task calls."""
        plan = await task_planner.create_plan(
            user_request="Show CPU and memory telemetry",
        )
        tid = plan["id"]

        # Run once
        res1 = await task_executor.execute_task(tid)
        self.assertEqual(res1["status"], "completed")
        step_1_id = res1["steps"][0]["id"]
        completed_at_1 = res1["steps"][0]["completed_at"]

        # Run again
        res2 = await task_executor.execute_task(tid)
        self.assertEqual(res2["status"], "completed")
        step_1_res2 = next(s for s in res2["steps"] if s["id"] == step_1_id)
        self.assertEqual(step_1_res2["completed_at"], completed_at_1, "Completed step must not be re-executed")

    async def test_03_approval_gating_and_exactly_once_execution(self):
        """Test consequential steps create an approval and execute exactly once upon approval."""
        plan = await task_planner.create_plan(
            user_request="Run diagnostic command whoami",
        )
        tid = plan["id"]

        # First execution attempt should pause for approval
        res = await task_executor.execute_task(tid)
        self.assertEqual(res["status"], "awaiting_approval")
        step = res["steps"][0]
        self.assertEqual(step["status"], "awaiting_approval")
        self.assertTrue(step["checkpoint_data"].startswith("approval:"))

        appr_id = int(step["checkpoint_data"].split("approval:")[1])
        appr_rec = ApprovalLifecycle.get_approval(appr_id)
        self.assertEqual(appr_rec["status"], "pending")

        # Approve and execute via ApprovalLifecycle
        appr_res = await ApprovalLifecycle.approve_and_execute(appr_id)
        self.assertEqual(appr_res["status"], "executed")
        self.assertIn("returncode", appr_res["result"])

        # Second execute_task call should pick up the executed approval result without executing again
        res_after = await task_executor.execute_task(tid)
        self.assertEqual(res_after["status"], "completed")
        step_after = res_after["steps"][0]
        self.assertEqual(step_after["status"], "completed")
        self.assertIn("returncode", step_after["result"])

    async def test_04_pause_resume_and_cancellation(self):
        """Test pause, resume, and cancellation controls."""
        plan = await task_planner.create_plan(
            user_request="Inspect system overview and list processes",
        )
        tid = plan["id"]

        # Pause
        paused = task_executor.pause_task(tid)
        self.assertEqual(paused["status"], "paused")

        # Resume
        resumed = await task_executor.resume_task(tid)
        self.assertEqual(resumed["status"], "completed")

        # Create another task and cancel it
        plan2 = await task_planner.create_plan(user_request="Show CPU overview")
        tid2 = plan2["id"]
        cancelled = task_executor.cancel_task(tid2)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_05_safe_restart_recovery_manual_review(self):
        """Test that tasks/steps stuck in 'running' across backend restart are marked for manual review."""
        fake_task_id = "test_stuck_task_restart"
        fake_step_id = "test_stuck_step_restart"

        with conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO tasks(id, title, user_request, objective, status) VALUES (?, 'Stuck Task', 'Req', 'Obj', 'running')",
                (fake_task_id,),
            )
            c.execute(
                "INSERT OR REPLACE INTO task_steps(id, task_id, step_index, title, tool_name, arguments, status) VALUES (?, ?, 1, 'Stuck Step', 'native.terminal.diagnostic', '{}', 'running')",
                (fake_step_id, fake_task_id),
            )

        # Trigger restart recovery
        TaskExecutor.recover_interrupted_tasks()

        # Verify task is paused and step is failed (marked for manual review, not re-run)
        t = task_planner.get_task(fake_task_id)
        self.assertEqual(t["status"], "paused")
        self.assertIn("Interrupted by backend restart", t["error"])

        s = t["steps"][0]
        self.assertEqual(s["status"], "failed")
        self.assertEqual(s["checkpoint_data"], "interrupted_manual_review")
        self.assertIn("manual review required", s["error"])


if __name__ == "__main__":
    unittest.main()
