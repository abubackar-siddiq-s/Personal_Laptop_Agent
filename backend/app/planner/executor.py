from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from app.core.db import conn
from app.core.security import audit
from app.core.approval import ApprovalLifecycle
from app.core.emergency import is_emergency_stopped
from app.tools.registry import registry
from app.planner.planner import task_planner

logger = logging.getLogger("laptop_ai.executor")

class TaskExecutor:
    def __init__(self):
        self._running_tasks: set[str] = set()
        self._paused_tasks: set[str] = set()
        self._cancelled_tasks: set[str] = set()

    async def execute_task(self, task_id: str) -> dict:
        """
        Execute a planned task step-by-step.
        - Enforces dependency order.
        - Checkpoints every step in SQLite.
        - Pauses for required approvals.
        - Blocks if Global Emergency Stop is engaged.
        - Never repeats completed steps or executed approval actions.
        """
        if is_emergency_stopped():
            task_planner.update_task_status(task_id, "paused", error="Execution blocked: Global Emergency Stop is engaged.")
            return task_planner.get_task(task_id) or {}

        task = task_planner.get_task(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found.")

        if task["status"] in ("completed", "cancelled"):
            return task

        if task_id in self._running_tasks:
            logger.warning("Task %s is already running; duplicate concurrent execution blocked.", task_id)
            return task

        task_planner.update_task_status(task_id, "running")
        self._running_tasks.add(task_id)

        try:
            steps = task.get("steps", [])
            step_map = {s["step_index"]: s for s in steps}

            for s in steps:
                # Check cancellation or pause requests
                if task_id in self._cancelled_tasks:
                    self._cancelled_tasks.discard(task_id)
                    task_planner.update_task_status(task_id, "cancelled", error="Cancelled by user.")
                    return task_planner.get_task(task_id) or {}

                if task_id in self._paused_tasks:
                    self._paused_tasks.discard(task_id)
                    task_planner.update_task_status(task_id, "paused", error="Paused by user.")
                    return task_planner.get_task(task_id) or {}

                # Check emergency stop before every single step
                if is_emergency_stopped():
                    audit("executor.emergency_aborted", f"Task {task_id} aborted mid-execution by Emergency Stop")
                    task_planner.update_task_status(task_id, "paused", error="Global Emergency Stop was engaged during execution.")
                    return task_planner.get_task(task_id) or {}

                # 1. Skip already completed steps (Never repeat!)
                if s["status"] == "completed":
                    continue

                # 2. Skip explicitly operator-skipped steps
                if s["status"] == "skipped":
                    continue

                # 3. If a step is failed or cancelled, do not automatically re-execute it.
                # Operator must explicitly retry via retry_step or resolve via manual_recover_step.
                if s["status"] in ("failed", "cancelled"):
                    err_msg = (
                        s.get("error")
                        or f"Step #{s['step_index']} ({s['title']}) is {s['status']}. Operator must resolve or retry this step before resuming."
                    )
                    task_planner.update_task_status(task_id, "failed", error=err_msg)
                    return task_planner.get_task(task_id) or {}

                # 4. Check dependencies
                deps = s.get("dependencies", [])
                unmet_deps = []
                for dep_idx in deps:
                    dep_step = step_map.get(dep_idx)
                    if not dep_step or dep_step["status"] not in ("completed", "skipped"):
                        unmet_deps.append(dep_idx)

                if unmet_deps:
                    err_msg = f"Dependencies not met: step(s) {unmet_deps} must complete first."
                    self._update_step(s["id"], status="failed", error=err_msg)
                    task_planner.update_task_status(task_id, "failed", error=err_msg)
                    return task_planner.get_task(task_id) or {}

                # 5. Check Approval Gates
                tool_name = s["tool_name"]
                tool_spec = registry.items.get(tool_name)
                is_approval_needed = (
                    s.get("requires_approval")
                    or (tool_spec and getattr(tool_spec, "risk", "normal") == "approval")
                )

                if is_approval_needed:
                    chk = str(s.get("checkpoint_data") or "")
                    appr_id = None
                    if "approval:" in chk:
                        try:
                            # Extracts ID even from 'interrupted_manual_review:approval:105'
                            appr_str = chk.split("approval:")[1].strip().split()[0].rstrip(";,:.")
                            appr_id = int(appr_str)
                        except (ValueError, IndexError):
                            pass

                    appr_rec = ApprovalLifecycle.get_approval(appr_id) if appr_id else None

                    # If no approval requested yet, create unique approval for this step
                    if not appr_rec:
                        new_appr = ApprovalLifecycle.create_request(
                            tool_name=tool_name,
                            args=s.get("arguments", {}),
                            conversation_id=task.get("conversation_id"),
                            risk="approval",
                        )
                        appr_id = new_appr["id"]
                        self._update_step(
                            s["id"],
                            status="awaiting_approval",
                            checkpoint_data=f"approval:{appr_id}",
                        )
                        task_planner.update_task_status(
                            task_id,
                            "awaiting_approval",
                            error=f"Step #{s['step_index']} ({tool_name}) requires approval. Queued Approval #{appr_id}.",
                        )
                        audit("executor.approval_paused", f"Task {task_id} paused at step #{s['step_index']} for approval #{appr_id}")
                        return task_planner.get_task(task_id) or {}

                    # If approval is still pending
                    if appr_rec["status"] == "pending":
                        self._update_step(
                            s["id"],
                            status="awaiting_approval",
                            checkpoint_data=f"approval:{appr_id}",
                        )
                        task_planner.update_task_status(
                            task_id,
                            "awaiting_approval",
                            error=f"Step #{s['step_index']} ({tool_name}) awaiting user approval (Approval #{appr_id}).",
                        )
                        return task_planner.get_task(task_id) or {}

                    # If approval was rejected
                    if appr_rec["status"] == "rejected":
                        self._update_step(s["id"], status="failed", error=f"Approval #{appr_id} was rejected by user.")
                        task_planner.update_task_status(task_id, "failed", error=f"Step #{s['step_index']} approval rejected.")
                        return task_planner.get_task(task_id) or {}

                    # If approval was executed, record its result and DO NOT repeat execution
                    if appr_rec["status"] == "executed":
                        res_val = appr_rec.get("result")
                        try:
                            res_parsed = json.loads(res_val) if isinstance(res_val, str) else res_val
                        except Exception:
                            res_parsed = res_val
                        self._update_step(s["id"], status="completed", result=res_parsed, error=None)
                        with conn() as c:
                            c.execute("UPDATE tasks SET completed_steps = completed_steps + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
                        step_map[s["step_index"]]["status"] = "completed"
                        audit("executor.step_completed", f"Task {task_id} step #{s['step_index']} completed via Approval #{appr_id}")
                        continue

                    # If approval failed
                    if appr_rec["status"] == "failed":
                        self._update_step(s["id"], status="failed", error=appr_rec.get("error", "Approval execution failed"))
                        task_planner.update_task_status(task_id, "failed", error=f"Step #{s['step_index']} execution failed.")
                        return task_planner.get_task(task_id) or {}

                # 4. Execute Step Tool (for unapproved / read-only steps)
                self._update_step(s["id"], status="running", checkpoint_data="Executing tool")
                audit("executor.step_started", f"Task {task_id} step #{s['step_index']}: invoking {tool_name}")

                exec_result = await registry.execute(tool_name, s.get("arguments", {}), timeout=60.0)

                if not exec_result.get("success"):
                    err_detail = exec_result.get("error", "Unknown execution error")
                    self._update_step(s["id"], status="failed", error=err_detail)
                    task_planner.update_task_status(task_id, "failed", error=f"Step #{s['step_index']} failed: {err_detail}")
                    audit("executor.step_failed", f"Task {task_id} step #{s['step_index']} failed: {err_detail}")
                    return task_planner.get_task(task_id) or {}

                # Step Succeeded: Record checkpoint
                res_data = exec_result.get("result")
                self._update_step(s["id"], status="completed", result=res_data, error=None)
                with conn() as c:
                    c.execute("UPDATE tasks SET completed_steps = completed_steps + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
                step_map[s["step_index"]]["status"] = "completed"
                audit("executor.step_completed", f"Task {task_id} step #{s['step_index']} completed successfully")

            # All steps completed successfully
            task_planner.update_task_status(
                task_id,
                "completed",
                result=f"All {len(steps)} steps executed successfully.",
            )
            audit("executor.task_completed", f"Task {task_id} completed successfully")
            return task_planner.get_task(task_id) or {}

        finally:
            self._running_tasks.discard(task_id)

    def _update_step(
        self,
        step_id: str,
        status: str,
        result: Any = None,
        error: Optional[str] = None,
        checkpoint_data: Optional[str] = None,
    ):
        with conn() as c:
            updates = ["status = ?"]
            params = [status]

            if result is not None:
                updates.append("result = ?")
                params.append(json.dumps(result) if not isinstance(result, str) else result)

            if error is not None:
                updates.append("error = ?")
                params.append(error)

            if checkpoint_data is not None:
                updates.append("checkpoint_data = ?")
                params.append(checkpoint_data)

            if status == "running":
                updates.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
            elif status in ("completed", "failed", "cancelled"):
                updates.append("completed_at = CURRENT_TIMESTAMP")

            params.append(step_id)
            c.execute(f"UPDATE task_steps SET {', '.join(updates)} WHERE id = ?", params)

    def pause_task(self, task_id: str) -> dict:
        t = task_planner.get_task(task_id)
        if not t:
            raise KeyError(f"Task '{task_id}' not found.")
        self._paused_tasks.add(task_id)
        task_planner.update_task_status(task_id, "paused", error="Paused by user.")
        audit("executor.task_paused", f"Task {task_id} paused by user")
        return task_planner.get_task(task_id) or {}

    async def resume_task(self, task_id: str) -> dict:
        t = task_planner.get_task(task_id)
        if not t:
            raise KeyError(f"Task '{task_id}' not found.")
        self._paused_tasks.discard(task_id)
        self._cancelled_tasks.discard(task_id)
        audit("executor.task_resumed", f"Task {task_id} resumed by user")
        return await self.execute_task(task_id)

    def cancel_task(self, task_id: str) -> dict:
        t = task_planner.get_task(task_id)
        if not t:
            raise KeyError(f"Task '{task_id}' not found.")
        self._cancelled_tasks.add(task_id)
        task_planner.update_task_status(task_id, "cancelled", error="Cancelled by user.")
        with conn() as c:
            c.execute("UPDATE task_steps SET status = 'cancelled' WHERE task_id = ? AND status IN ('pending', 'awaiting_approval', 'running')", (task_id,))
        audit("executor.task_cancelled", f"Task {task_id} cancelled by user")
        return task_planner.get_task(task_id) or {}

    async def retry_step(self, task_id: str, step_id: str) -> dict:
        with conn() as c:
            c.execute(
                """
                UPDATE task_steps
                SET status = 'pending', error = NULL, retry_count = retry_count + 1
                WHERE id = ? AND task_id = ?
                """,
                (step_id, task_id),
            )
            c.execute("UPDATE tasks SET status = 'running', error = NULL WHERE id = ?", (task_id,))
        audit("executor.step_retried", f"Task {task_id} step {step_id} queued for retry")
        return await self.execute_task(task_id)

    def manual_recover_step(
        self, task_id: str, step_id: str, resolution: str = "resolve", notes: str = ""
    ) -> dict:
        """
        Operator manual recovery for an interrupted or uncertain step.
        Resolutions:
          - 'resolve': mark as completed with manual override result
          - 'skip': mark as completed (skipped) to unblock downstream dependent steps
          - 'retry': reset step status to pending, clear error, increment retry count
        """
        with conn() as c:
            if resolution == "resolve":
                c.execute(
                    """
                    UPDATE task_steps
                    SET status = 'completed',
                        result = ?,
                        error = NULL,
                        completed_at = CURRENT_TIMESTAMP,
                        checkpoint_data = 'manual_recovery_resolved'
                    WHERE id = ? AND task_id = ?
                    """,
                    (
                        json.dumps({
                            "manual_override": True,
                            "notes": notes or "Manually marked as resolved by operator.",
                        }),
                        step_id,
                        task_id,
                    ),
                )
            elif resolution == "skip":
                c.execute(
                    """
                    UPDATE task_steps
                    SET status = 'completed',
                        result = ?,
                        error = 'Skipped via manual recovery.',
                        completed_at = CURRENT_TIMESTAMP,
                        checkpoint_data = 'manual_recovery_skipped'
                    WHERE id = ? AND task_id = ?
                    """,
                    (
                        json.dumps({
                            "manual_override": True,
                            "skipped": True,
                            "notes": notes or "Manually skipped by operator.",
                        }),
                        step_id,
                        task_id,
                    ),
                )
            elif resolution == "retry":
                c.execute(
                    """
                    UPDATE task_steps
                    SET status = 'pending',
                        error = NULL,
                        retry_count = retry_count + 1,
                        checkpoint_data = 'manual_recovery_retry'
                    WHERE id = ? AND task_id = ?
                    """,
                    (step_id, task_id),
                )
            else:
                raise ValueError(
                    f"Unknown resolution '{resolution}'. Must be 'resolve', 'skip', or 'retry'."
                )

        audit(
            "executor.manual_recovery",
            f"Task {task_id} step {step_id} manual recovery applied: action={resolution}",
        )
        return task_planner.get_task(task_id) or {}

    @staticmethod
    def recover_interrupted_tasks():
        """
        Safe recovery on backend startup:
        - Detect tasks stuck in 'running'.
        - Mark them 'paused' with an explanation.
        - Steps stuck in 'running' are marked 'failed' with checkpoint_data='interrupted_manual_review',
          requiring manual review and preventing automatic rerun of uncertain operations.
        """
        with conn() as c:
            c.execute("""
            UPDATE tasks
            SET status = 'paused', error = 'Interrupted by backend restart. Check step results and click Resume.', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'running'
            """)
            c.execute("""
            UPDATE task_steps
            SET status = 'failed',
                error = 'Interrupted during execution: Operation state uncertain; manual review required. Not automatically rerun.',
                checkpoint_data = CASE 
                    WHEN checkpoint_data LIKE '%approval:%' THEN 'interrupted_manual_review:' || checkpoint_data 
                    ELSE 'interrupted_manual_review' 
                END
            WHERE status = 'running'
            """)

task_executor = TaskExecutor()
