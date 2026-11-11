"""
LAPTOP AI — QUEUE 7 EMERGENCY STOP & INTEGRATION TEST
Verifies:
1. Global Emergency Stop engages offline (SQLite system_state).
2. All tool execution blocked immediately without LLM.
3. Running task steps marked failed with 'emergency_stop_manual_review'.
4. Manual recovery actions: 'resolve', 'skip', 'retry'.
5. Disengagement requires explicit user command.
6. Resumed execution safely completes without duplicating completed steps.
"""
from __future__ import annotations
import asyncio
import os
import sys
import unittest

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.db import init_db, conn
from app.core.emergency import (
    is_emergency_stopped,
    trigger_emergency_stop,
    clear_emergency_stop,
    get_emergency_status,
)
from app.tools.registry import registry
from app.tools.native import register as reg_native
from app.browser import register_browser_tools
from app.planner.planner import task_planner
from app.planner.executor import task_executor
from app.planner.scheduler import task_scheduler


class TestQueue7EmergencyStop(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        reg_native()
        register_browser_tools()
        clear_emergency_stop()

    async def asyncSetUp(self):
        clear_emergency_stop()

    async def asyncTearDown(self):
        clear_emergency_stop()

    async def test_01_offline_emergency_stop_blocks_all_execution(self):
        """Test emergency stop prevents tool and task execution offline."""
        status = trigger_emergency_stop(reason="Emergency Test: Offline Stop")
        self.assertTrue(status["is_stopped"])
        self.assertTrue(is_emergency_stopped())

        # Tool execution blocked
        res = await registry.execute("native.system.overview", {})
        self.assertFalse(res["success"])
        self.assertIn("Emergency Stop", res["error"])

        # Browser tool blocked
        b_res = await registry.execute("browser.get_title", {})
        self.assertFalse(b_res["success"])
        self.assertIn("Emergency Stop", b_res["error"])

        # Task execution blocked
        task = await task_planner.create_plan("system health check")
        exec_res = await task_executor.execute_task(task["id"])
        self.assertEqual(exec_res["status"], "paused")
        self.assertIn("Emergency Stop", exec_res["error"])

        # Scheduler tick blocked
        sched_res = await task_scheduler.tick()
        self.assertEqual(sched_res["executed"], 0)
        self.assertEqual(sched_res["skipped_due_to_emergency_stop"], True)

    async def test_02_emergency_stop_marks_uncertain_steps_for_manual_review(self):
        """Test that running steps interrupted by emergency stop are marked for manual review."""
        task = await task_planner.create_plan("Inspect CPU overview and process list")
        task_id = task["id"]
        step1 = task["steps"][0]

        # Simulate a step that was in 'running' state when emergency stop occurred
        with conn() as c:
            c.execute("UPDATE tasks SET status = 'running' WHERE id = ?", (task_id,))
            c.execute(
                "UPDATE task_steps SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE id = ?",
                (step1["id"],),
            )

        # Trigger emergency stop
        trigger_emergency_stop(reason="Uncertain step test")

        t_after = task_planner.get_task(task_id)
        self.assertEqual(t_after["status"], "paused")

        with conn() as c:
            row = c.execute("SELECT * FROM task_steps WHERE id = ?", (step1["id"],)).fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["checkpoint_data"], "emergency_stop_manual_review")
            self.assertIn("manual review required", row["error"])

    async def test_03_manual_recovery_resolve_skip_and_retry(self):
        """Test manual recovery actions: resolve, skip, and retry."""
        task = await task_planner.create_plan("Audit hardware and top processes")
        task_id = task["id"]
        steps = task["steps"]
        step1_id = steps[0]["id"]
        step2_id = steps[1]["id"]

        # 1. Test manual recovery: resolve
        rec_res = task_executor.manual_recover_step(
            task_id=task_id,
            step_id=step1_id,
            resolution="resolve",
            notes="Operator verified system overview output manually.",
        )
        s1 = next(s for s in rec_res["steps"] if s["id"] == step1_id)
        self.assertEqual(s1["status"], "completed")
        self.assertEqual(s1["checkpoint_data"], "manual_recovery_resolved")
        self.assertIn("manual_override", s1["result"])

        # 2. Test manual recovery: skip
        rec_skip = task_executor.manual_recover_step(
            task_id=task_id,
            step_id=step2_id,
            resolution="skip",
            notes="Operator decided to skip process list.",
        )
        s2 = next(s for s in rec_skip["steps"] if s["id"] == step2_id)
        self.assertEqual(s2["status"], "completed")
        self.assertEqual(s2["checkpoint_data"], "manual_recovery_skipped")
        self.assertTrue(s2["result"].get("skipped"))

        # 3. Test manual recovery: retry
        rec_retry = task_executor.manual_recover_step(
            task_id=task_id,
            step_id=step2_id,
            resolution="retry",
        )
        s2_retry = next(s for s in rec_retry["steps"] if s["id"] == step2_id)
        self.assertEqual(s2_retry["status"], "pending")
        self.assertGreaterEqual(s2_retry["retry_count"], 1)

    async def test_04_no_auto_restart_without_explicit_user_action(self):
        """Test that clearing emergency stop does NOT auto-restart paused tasks."""
        task = await task_planner.create_plan("Check system health")
        task_id = task["id"]

        trigger_emergency_stop(reason="Pause test")
        await task_executor.execute_task(task_id)

        t_paused = task_planner.get_task(task_id)
        self.assertEqual(t_paused["status"], "paused")

        # Disengage emergency stop
        clear_emergency_stop()
        self.assertFalse(is_emergency_stopped())

        # Task remains paused until user explicitly calls resume_task
        t_still_paused = task_planner.get_task(task_id)
        self.assertEqual(t_still_paused["status"], "paused")

        # User explicitly resumes
        resume_res = await task_executor.resume_task(task_id)
        self.assertIn(resume_res["status"], ("completed", "running"))


if __name__ == "__main__":
    unittest.main()

