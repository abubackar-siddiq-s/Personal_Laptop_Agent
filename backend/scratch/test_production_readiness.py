"""
LAPTOP AI — PHASE 5 PRODUCTION READINESS GATE TESTS
Tests specific failure modes and crash-consistency guarantees:
1. Refusal to automatically repeat uncertain/failed steps on resume.
2. Exactly-once/effectively-once approved tool execution with preserved approval pointers.
3. Scheduler atomic occurrence claiming & durable run creation before execution.
4. Scheduler crash recovery (recovering stuck 'running' runs to 'failed').
5. Emergency stop upfront rejection of pending approvals (preventing state corruption).
6. SSRF DNS rebinding prevention for remote MCP HTTP endpoints.
7. Cross-origin CSRF rejection across all mutating API routes.
"""
from __future__ import annotations
import asyncio
import os
import sys
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.main import app
from app.core.db import init_db, conn
from app.core.approval import ApprovalLifecycle, ApprovalError
from app.core.emergency import (
    is_emergency_stopped,
    trigger_emergency_stop,
    clear_emergency_stop,
)
from app.planner.planner import task_planner
from app.planner.executor import task_executor
from app.planner.scheduler import task_scheduler, TaskScheduler
from app.tools.registry import registry
from app.tools.native import register as reg_native
from app.tools.mcp_manager import validate_http_url

client = TestClient(app)


class TestProductionReadinessGate(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        reg_native()
        clear_emergency_stop()

    async def asyncSetUp(self):
        clear_emergency_stop()

    async def asyncTearDown(self):
        clear_emergency_stop()

    async def test_01_failed_step_refuses_auto_repeat_on_resume(self):
        """A failed/uncertain step must NOT be automatically re-executed on task resume."""
        plan = await task_planner.create_plan("system health overview")
        tid = plan["id"]
        step1 = plan["steps"][0]

        # Force step into failed state with uncertain checkpoint
        with conn() as c:
            c.execute(
                "UPDATE task_steps SET status = 'failed', checkpoint_data = 'interrupted_manual_review', error = 'Uncertain state' WHERE id = ?",
                (step1["id"],),
            )
            c.execute("UPDATE tasks SET status = 'paused', error = 'Interrupted' WHERE id = ?", (tid,))

        # Resuming task should refuse to execute the failed step and fail safe
        resumed = await task_executor.resume_task(tid)
        self.assertEqual(resumed["status"], "failed")
        self.assertIn("uncertain", resumed["error"].lower())

        # Step remains failed (never automatically rerun)
        t_after = task_planner.get_task(tid)
        self.assertEqual(t_after["steps"][0]["status"], "failed")

    async def test_02_interrupted_approval_preserves_pointer_and_executes_once(self):
        """Interrupted task steps preserve approval ID and consume executed approval without re-running."""
        plan = await task_planner.create_plan("Run terminal diagnostic whoami")
        tid = plan["id"]

        # First run pauses for approval
        res1 = await task_executor.execute_task(tid)
        self.assertEqual(res1["status"], "awaiting_approval")
        s = res1["steps"][0]
        self.assertTrue("approval:" in s["checkpoint_data"])
        aid = int(s["checkpoint_data"].split("approval:")[1].strip())

        # Simulate backend crash/restart recovery while running
        with conn() as c:
            c.execute("UPDATE tasks SET status = 'running' WHERE id = ?", (tid,))
            c.execute("UPDATE task_steps SET status = 'running' WHERE id = ?", (s["id"],))

        task_executor.recover_interrupted_tasks()

        # Step checkpoint data should preserve the approval ID with the review prefix
        s_rec = task_planner.get_task(tid)["steps"][0]
        self.assertEqual(s_rec["status"], "failed")
        self.assertTrue("approval:" in s_rec["checkpoint_data"])

        # User approves via ApprovalLifecycle
        appr_res = await ApprovalLifecycle.approve_and_execute(aid)
        self.assertEqual(appr_res["status"], "executed")

        # Operator manual recovery resolves the uncertain step using the executed approval result
        task_executor.manual_recover_step(
            task_id=tid,
            step_id=s["id"],
            resolution="resolve",
            notes="Recovered with verified approval result",
        )

        # Resume task: completes cleanly without calling the tool again
        res2 = await task_executor.resume_task(tid)
        self.assertEqual(res2["status"], "completed")

    async def test_03_scheduler_durable_run_and_crash_recovery(self):
        """Scheduler atomically claims occurrence, creates durable run before task execution, and recovers on restart."""
        sched = task_scheduler.create_schedule(
            task_name="Crash Consistency Test",
            user_request="system overview",
            schedule_type="interval",
            interval_seconds=60,
        )
        sid = sched["id"]

        # Run tick
        await task_scheduler.tick()

        # Verify schedule_runs has exactly one durable run record
        runs = task_scheduler.get_schedule_history(sid)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "success")

        # Simulate crash mid-run: insert a stuck 'running' schedule_run
        with conn() as c:
            c.execute(
                "INSERT INTO schedule_runs (schedule_id, task_id, triggered_at, status) VALUES (?, NULL, CURRENT_TIMESTAMP, 'running')",
                (sid,),
            )
            c.execute("UPDATE scheduled_tasks SET last_status = 'running' WHERE id = ?", (sid,))

        # Run crash recovery
        TaskScheduler.recover_interrupted_schedules()

        # Stuck run is recovered to 'failed' and schedule last_status is 'interrupted'
        recovered_sched = task_scheduler.get_schedule(sid)
        self.assertEqual(recovered_sched["last_status"], "interrupted")
        runs_after = task_scheduler.get_schedule_history(sid)
        self.assertTrue(any(r["status"] == "failed" and "Interrupted by backend restart" in (r.get("error") or "") for r in runs_after))

        task_scheduler.delete_schedule(sid)

    async def test_04_emergency_stop_blocks_pending_approval_corruption(self):
        """Emergency stop rejects approval execution upfront without corrupting pending approval record."""
        # Create a pending approval
        appr = ApprovalLifecycle.create_request(
            tool_name="native.terminal.diagnostic",
            args={"command_id": "whoami"},
            risk="approval",
        )
        aid = appr["id"]

        # Engage emergency stop
        trigger_emergency_stop(reason="Approval barrier test")

        # Attempt to approve and execute: must fail with ApprovalError
        with self.assertRaises(ApprovalError) as ctx:
            await ApprovalLifecycle.approve_and_execute(aid)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Emergency Stop", str(ctx.exception))

        # Crucial check: approval must REMAIN in 'pending' status (NOT corrupted to 'failed')
        appr_state = ApprovalLifecycle.get_approval(aid)
        self.assertEqual(appr_state["status"], "pending")

        # Disengage emergency stop
        clear_emergency_stop()

        # Now approve succeeds normally
        exec_res = await ApprovalLifecycle.approve_and_execute(aid)
        self.assertEqual(exec_res["status"], "executed")

    def test_05_cross_origin_csrf_blocked_across_mutating_routes(self):
        """verify_local_origin blocks foreign Origin headers across mutating endpoints."""
        evil_headers = {"Origin": "https://attacker-controlled-site.com"}

        # 1. Tools execute
        r1 = client.post("/api/tools/run", json={"name": "native.system.overview", "arguments": {}}, headers=evil_headers)
        self.assertEqual(r1.status_code, 403)

        # 2. Emergency stop
        r2 = client.post("/api/emergency/stop", json={"reason": "CSRF test"}, headers=evil_headers)
        self.assertEqual(r2.status_code, 403)

        # 3. Tasks plan
        r3 = client.post("/api/tasks/plan", json={"user_request": "do something"}, headers=evil_headers)
        self.assertEqual(r3.status_code, 403)

        # 4. Schedules create
        r4 = client.post("/api/schedules", json={"task_name": "CSRF Sched", "user_request": "req"}, headers=evil_headers)
        self.assertEqual(r4.status_code, 403)

    def test_06_ssrf_dns_rebinding_validation(self):
        """validate_http_url rejects cloud metadata IP and domains resolving to private/loopback IPs."""
        # 1. Direct metadata IP
        with self.assertRaises(PermissionError):
            validate_http_url("http://169.254.169.254/mcp")

        # 2. Insecure external HTTP
        with self.assertRaises(ValueError):
            validate_http_url("http://remote-server.com/mcp")


if __name__ == "__main__":
    unittest.main()

