import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.db import init_db, conn
from app.core.approval import ApprovalLifecycle, ApprovalError
from app.core.emergency import clear_emergency_stop
from app.tools.registry import registry
from app.tools.native import register as reg_nat


class TestDurableOperationRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        reg_nat()
        clear_emergency_stop()

    def setUp(self):
        clear_emergency_stop()

    # 1. Durable Operation ID and Duplicate Client-Request Protection
    def test_01_duplicate_client_request_protection(self):
        """Identical operation ID must not create duplicate approval records."""
        op_id = f"op_test_dedup_{time.time()}"
        args = {"command_id": "whoami"}

        req1 = ApprovalLifecycle.create_request("native.terminal.diagnostic", args, operation_id=op_id)
        aid1 = req1["id"]

        # Duplicate request arrives with same operation_id
        req2 = ApprovalLifecycle.create_request("native.terminal.diagnostic", args, operation_id=op_id)
        aid2 = req2["id"]

        self.assertEqual(aid1, aid2)
        self.assertTrue(req2.get("deduplicated"))

    # 2. Completed Operation Result Reuse (Idempotency)
    def test_02_completed_operation_result_reuse(self):
        """When an operation has completed, subsequent requests with same operation_id reuse result without re-executing."""
        op_id = f"op_test_reuse_{time.time()}"
        args = {"command_id": "whoami"}

        req = ApprovalLifecycle.create_request("native.terminal.diagnostic", args, operation_id=op_id)
        aid = req["id"]

        # User approves and executes
        exec_res = asyncio.run(ApprovalLifecycle.approve_and_execute(aid))
        self.assertEqual(exec_res["status"], "executed")

        # Subsequent call with same op_id
        req_again = ApprovalLifecycle.create_request("native.terminal.diagnostic", args, operation_id=op_id)
        self.assertEqual(req_again["status"], "executed")
        self.assertTrue(req_again.get("reused"))
        self.assertIsNotNone(req_again.get("result"))

    # 3. Crash Before Operation Begins
    def test_03_crash_before_operation_begins(self):
        """Approvals created but interrupted before user approval remain pending or expire cleanly."""
        op_id = f"op_test_crash_pre_{time.time()}"
        req = ApprovalLifecycle.create_request("native.terminal.diagnostic", {"command_id": "whoami"}, operation_id=op_id)
        aid = req["id"]

        # Simulate backend reboot
        recovered = ApprovalLifecycle.recover_interrupted_executions()
        appr = ApprovalLifecycle.get_approval(aid)
        self.assertEqual(appr["status"], "pending")  # Safely pending user action

    # 4. Crash During Operation (Uncertain External Side Effect -> Manual Review Required)
    def test_04_crash_during_execution_enters_manual_review(self):
        """
        If server crashes while an operation is in 'executing' status, recovery MUST transition
        it to 'failed' requiring manual review. Destructive actions must NEVER be automatically rerun.
        """
        op_id = f"op_test_crash_during_{time.time()}"
        req = ApprovalLifecycle.create_request("native.terminal.diagnostic", {"command_id": "whoami"}, operation_id=op_id)
        aid = req["id"]

        # Manually simulate in-flight execution state right before crash
        with conn() as c:
            c.execute("UPDATE approvals SET status='executing' WHERE id=?", (aid,))

        # Simulate backend restart recovery
        recovered_count = ApprovalLifecycle.recover_interrupted_executions()
        self.assertGreaterEqual(recovered_count, 1)

        appr = ApprovalLifecycle.get_approval(aid)
        self.assertEqual(appr["status"], "failed")
        self.assertIn("Interrupted", appr["error"])
        self.assertIn("manual review required", appr["error"].lower())

        # Attempting to re-request this operation ID recognizes the uncertain crash state
        req_retry = ApprovalLifecycle.create_request("native.terminal.diagnostic", {"command_id": "whoami"}, operation_id=op_id)
        self.assertEqual(req_retry["status"], "failed")
        self.assertTrue(req_retry.get("uncertain_recovery"))

    # 5. Crash After External Effect Succeeds But Before Result Persisted
    def test_05_crash_after_external_effect_does_not_repeat(self):
        """
        If the external system received the effect but SQLite was not updated before crash:
        The record is recovered as failed (uncertain state) and NOT automatically repeated.
        """
        op_id = f"op_test_crash_post_effect_{time.time()}"
        req = ApprovalLifecycle.create_request("native.terminal.diagnostic", {"command_id": "whoami"}, operation_id=op_id)
        aid = req["id"]

        with conn() as c:
            c.execute("UPDATE approvals SET status='executing' WHERE id=?", (aid,))

        # Server restart
        ApprovalLifecycle.recover_interrupted_executions()

        appr = ApprovalLifecycle.get_approval(aid)
        # Guarantees at-most-once attempt: cannot be re-executed via approve_and_execute
        with self.assertRaises(ApprovalError) as ctx:
            asyncio.run(ApprovalLifecycle.approve_and_execute(aid))
        self.assertIn("invalid status 'failed'", str(ctx.exception).lower())

    # 6. Concurrent Duplicate Execution Protection (Atomic Lock)
    def test_06_atomic_claiming_prevents_concurrent_execution(self):
        """Two concurrent workers attempting to execute the same approval must result in exactly one execution."""
        op_id = f"op_test_atomic_{time.time()}"
        req = ApprovalLifecycle.create_request("native.terminal.diagnostic", {"command_id": "whoami"}, operation_id=op_id)
        aid = req["id"]

        async def attempt_exec():
            try:
                return await ApprovalLifecycle.approve_and_execute(aid)
            except ApprovalError as e:
                return {"status": "blocked", "error": str(e)}

        async def run_concurrent():
            return await asyncio.gather(attempt_exec(), attempt_exec())

        results = asyncio.run(run_concurrent())
        statuses = [r.get("status") for r in results]

        self.assertIn("executed", statuses)
        self.assertTrue(any(s in ("blocked", "failed") for s in statuses))


if __name__ == "__main__":
    unittest.main()
