from __future__ import annotations
import asyncio
import datetime
import logging
import time
import uuid
from typing import Optional, List, Dict, Any
from app.core.db import conn
from app.core.security import audit
from app.core.emergency import is_emergency_stopped
from app.planner.planner import task_planner
from app.planner.executor import task_executor

logger = logging.getLogger("laptop_ai.scheduler")

class TaskScheduler:
    def __init__(self):
        self._running = False
        self._task_handle: Optional[asyncio.Task] = None
        self._active_runs: set[str] = set()

    def start(self):
        """Start the background scheduler evaluation loop."""
        if self._running:
            return
        self._running = True
        self._task_handle = asyncio.create_task(self._scheduler_loop())
        logger.info("Task Scheduler started (polling tick: 10s)")

    def stop(self):
        """Stop the background scheduler loop."""
        self._running = False
        if self._task_handle:
            self._task_handle.cancel()
            self._task_handle = None
        logger.info("Task Scheduler stopped")

    async def _scheduler_loop(self):
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in scheduler tick: %s", e)
            await asyncio.sleep(10.0)

    async def tick(self) -> dict:
        """Evaluate scheduled tasks that are due for execution."""
        if is_emergency_stopped():
            return {"executed": 0, "skipped_due_to_emergency_stop": True}

        # Proactive Personal Assistance: Evaluate reminders and monitors on the same tick
        try:
            from app.assistant import assistant_engine
            assistant_engine.tick()
        except Exception as e:
            logger.error("Error in assistant_engine tick: %s", e)

        now_iso = datetime.datetime.now().astimezone().isoformat()
        with conn() as c:
            rows = c.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT 50
                """,
                (now_iso,),
            ).fetchall()

        for r in rows:
            sched_id = r["id"]
            if sched_id in self._active_runs:
                continue

            user_request = r["user_request"]
            sched_type = r["schedule_type"]
            interval_sec = r["interval_seconds"] or 3600

            # Compute next run time immediately to prevent duplicate execution across restarts
            next_iso = self.compute_next_run(sched_type, interval_sec)
            run_id = None
            with conn() as c:
                if sched_type == "once":
                    cur = c.execute(
                        "UPDATE scheduled_tasks SET enabled = 0, last_run_at = ?, last_status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND enabled = 1",
                        (now_iso, sched_id),
                    )
                else:
                    cur = c.execute(
                        "UPDATE scheduled_tasks SET next_run_at = ?, last_run_at = ?, last_status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND next_run_at <= ?",
                        (next_iso, now_iso, sched_id, now_iso),
                    )
                if cur.rowcount == 0:
                    continue  # Already claimed by another worker or disabled

                # Atomically record durable schedule_run entry upon claiming occurrence
                run_cur = c.execute(
                    "INSERT INTO schedule_runs (schedule_id, task_id, triggered_at, status, error) VALUES (?, NULL, ?, 'running', NULL)",
                    (sched_id, now_iso),
                )
                run_id = run_cur.lastrowid

            audit("scheduler.trigger", f"Scheduled task '{r['task_name']}' triggered execution (run #{run_id})")
            self._active_runs.add(sched_id)

            try:
                plan = await task_planner.create_plan(
                    user_request=user_request,
                    objective=f"Scheduled execution: {r['task_name']}",
                )
                plan_id = plan.get("id") if plan else None

                # Obey approval requirements: do NOT auto-authorize consequential operations
                if plan and plan.get("status") == "awaiting_approval":
                    with conn() as c:
                        c.execute(
                            "UPDATE scheduled_tasks SET last_status = 'awaiting_approval', last_error = 'Action paused for user approval.' WHERE id = ?",
                            (sched_id,),
                        )
                        c.execute(
                            "UPDATE schedule_runs SET task_id = ?, status = 'awaiting_approval', error = 'Action paused for user approval.' WHERE id = ?",
                            (plan_id, run_id),
                        )
                    audit("scheduler.awaiting_approval", f"Scheduled task '{r['task_name']}' plan #{plan_id} requires approval")
                    continue

                if plan:
                    exec_res = await task_executor.execute_task(plan["id"])
                    exec_status = exec_res.get("status", "unknown")
                    exec_err = exec_res.get("error")
                    status_label = "success" if exec_status == "completed" else exec_status
                    with conn() as c:
                        c.execute(
                            "UPDATE scheduled_tasks SET last_status = ?, last_error = ? WHERE id = ?",
                            (status_label, exec_err, sched_id),
                        )
                        c.execute(
                            "UPDATE schedule_runs SET task_id = ?, status = ?, error = ? WHERE id = ?",
                            (plan_id, status_label, exec_err, run_id),
                        )
            except Exception as e:
                err_msg = str(e)
                logger.error("Failed to execute scheduled task %s: %s", sched_id, err_msg)
                with conn() as c:
                    c.execute(
                        "UPDATE scheduled_tasks SET last_status = 'failed', last_error = ? WHERE id = ?",
                        (err_msg, sched_id),
                    )
                    c.execute(
                        "UPDATE schedule_runs SET status = 'failed', error = ? WHERE id = ?",
                        (err_msg, run_id),
                    )
            finally:
                self._active_runs.discard(sched_id)

        return {"executed": len(rows), "skipped_due_to_emergency_stop": False}

    @staticmethod
    def recover_interrupted_schedules():
        """
        Recover schedules and run history interrupted by backend restart:
        - Marks any stuck 'running' schedule_runs as 'failed' with restart explanation.
        - Resets scheduled_tasks last_status from 'running' to 'interrupted'.
        """
        with conn() as c:
            c.execute("""
            UPDATE schedule_runs
            SET status = 'failed', error = 'Interrupted by backend restart; check task execution state.'
            WHERE status = 'running'
            """)
            c.execute("""
            UPDATE scheduled_tasks
            SET last_status = 'interrupted', last_error = 'Interrupted by backend restart.'
            WHERE last_status = 'running'
            """)

    def compute_next_run(self, schedule_type: str, interval_seconds: int = 3600) -> str:
        """Calculate the next timezone-aware ISO timestamp based on schedule type."""
        now = datetime.datetime.now().astimezone()
        if schedule_type == "once":
            next_dt = now + datetime.timedelta(seconds=max(1, interval_seconds))
        elif schedule_type == "daily":
            next_dt = now + datetime.timedelta(days=1)
        elif schedule_type == "weekly":
            next_dt = now + datetime.timedelta(weeks=1)
        elif schedule_type == "interval":
            next_dt = now + datetime.timedelta(seconds=max(10, interval_seconds))
        else:
            next_dt = now + datetime.timedelta(days=1)
        return next_dt.isoformat()

    def create_schedule(
        self,
        task_name: str,
        user_request: str,
        schedule_type: str = "daily",
        interval_seconds: Optional[int] = None,
        start_delay_seconds: int = 0,
    ) -> dict:
        sched_id = f"sched_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        now = datetime.datetime.now().astimezone()
        start_time = now + datetime.timedelta(seconds=max(0, start_delay_seconds))
        next_run_at = start_time.isoformat()

        with conn() as c:
            c.execute(
                """
                INSERT INTO scheduled_tasks (
                    id, task_name, user_request, schedule_type,
                    interval_seconds, next_run_at, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (sched_id, task_name.strip(), user_request.strip(), schedule_type, interval_seconds, next_run_at),
            )

        audit("scheduler.created", f"Created schedule '{task_name}' ({schedule_type}) starting at {next_run_at}")
        return self.get_schedule(sched_id)

    def get_schedule(self, sched_id: str) -> Optional[dict]:
        with conn() as c:
            row = c.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (sched_id,)).fetchone()
            return dict(row) if row else None

    def list_schedules(self, enabled_only: bool = False) -> List[dict]:
        with conn() as c:
            sql = "SELECT * FROM scheduled_tasks"
            params: list = []
            if enabled_only:
                sql += " WHERE enabled = 1"
            sql += " ORDER BY next_run_at ASC"
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def toggle_schedule(self, sched_id: str, enabled: Optional[bool] = None) -> Optional[dict]:
        sched = self.get_schedule(sched_id)
        if not sched:
            return None
        new_state = (not bool(sched["enabled"])) if enabled is None else bool(enabled)
        with conn() as c:
            c.execute(
                "UPDATE scheduled_tasks SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if new_state else 0, sched_id),
            )
        audit("scheduler.toggled", f"Schedule {sched_id} enabled={new_state}")
        return self.get_schedule(sched_id)

    def delete_schedule(self, sched_id: str) -> bool:
        with conn() as c:
            cur = c.execute("DELETE FROM scheduled_tasks WHERE id = ?", (sched_id,))
            audit("scheduler.deleted", f"Schedule {sched_id} deleted")
            return cur.rowcount > 0

    def get_schedule_history(self, sched_id: str, limit: int = 20) -> List[dict]:
        """Retrieve execution run history for a scheduled task."""
        with conn() as c:
            rows = c.execute(
                "SELECT * FROM schedule_runs WHERE schedule_id = ? ORDER BY id DESC LIMIT ?",
                (sched_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

task_scheduler = TaskScheduler()
