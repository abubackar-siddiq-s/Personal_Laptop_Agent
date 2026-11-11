import os
import sys
import unittest
import datetime
from pathlib import Path

# Setup path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.db import conn, init_db
from app.tools.native import register
from app.planner.scheduler import task_scheduler, TaskScheduler


class TestPersistentTaskScheduler(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        register()

    def test_01_persistence_and_restart_survival(self):
        """Test that scheduled tasks persist in SQLite and survive restart."""
        sched = task_scheduler.create_schedule(
            task_name="Restart Test Job",
            user_request="Show system telemetry",
            schedule_type="daily",
        )
        self.assertIsNotNone(sched)
        sid = sched["id"]
        self.assertEqual(sched["task_name"], "Restart Test Job")
        self.assertEqual(sched["schedule_type"], "daily")
        self.assertEqual(sched["enabled"], 1)

        # Simulate restart by reading directly from SQLite with a new connection
        with conn() as c:
            row = c.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (sid,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["id"], sid)
            self.assertEqual(row["user_request"], "Show system telemetry")

    def test_02_timezone_aware_calculation(self):
        """Test calculation of next run across recurrence types with timezone awareness."""
        now = datetime.datetime.now().astimezone()
        tz = now.tzinfo
        self.assertIsNotNone(tz)

        # 1. Interval (60 seconds)
        next_interval = task_scheduler.compute_next_run("interval", interval_seconds=60)
        dt_interval = datetime.datetime.fromisoformat(next_interval)
        self.assertIsNotNone(dt_interval.tzinfo)
        diff_sec = (dt_interval - now).total_seconds()
        self.assertTrue(55 <= diff_sec <= 65)

        # 2. Daily (24 hours)
        next_daily = task_scheduler.compute_next_run("daily")
        dt_daily = datetime.datetime.fromisoformat(next_daily)
        diff_days = (dt_daily - now).total_seconds() / 86400.0
        self.assertTrue(0.99 <= diff_days <= 1.01)

        # 3. Weekly (7 days)
        next_weekly = task_scheduler.compute_next_run("weekly")
        dt_weekly = datetime.datetime.fromisoformat(next_weekly)
        diff_weeks = (dt_weekly - now).total_seconds() / (86400.0 * 7)
        self.assertTrue(0.99 <= diff_weeks <= 1.01)

    async def test_03_duplicate_execution_prevention(self):
        """Test that due tasks execute once and next_run_at advances immediately, preventing duplicates."""
        # Create a task due right now
        sched = task_scheduler.create_schedule(
            task_name="Duplicate Prevention Test",
            user_request="Inspect CPU and RAM",
            schedule_type="interval",
            interval_seconds=300, # 5 minutes
            start_delay_seconds=0,
        )
        sid = sched["id"]
        orig_next_run = sched["next_run_at"]

        # First tick executes the due task
        await task_scheduler.tick()

        # Verify next_run_at advanced into the future
        refreshed = task_scheduler.get_schedule(sid)
        self.assertNotEqual(refreshed["next_run_at"], orig_next_run)
        self.assertGreater(refreshed["next_run_at"], orig_next_run)
        self.assertEqual(refreshed["last_status"], "success")

        # Second tick immediately afterwards must NOT execute it again
        runs_before = len(task_scheduler.get_schedule_history(sid))
        await task_scheduler.tick()
        runs_after = len(task_scheduler.get_schedule_history(sid))
        self.assertEqual(runs_before, runs_after, "Schedule must not execute twice in consecutive ticks")

    async def test_04_disabled_schedule_skipped(self):
        """Test that disabled schedules are never triggered by the scheduler loop."""
        sched = task_scheduler.create_schedule(
            task_name="Disabled Job Test",
            user_request="Show system overview",
            schedule_type="interval",
            interval_seconds=60,
            start_delay_seconds=0,
        )
        sid = sched["id"]

        # Disable
        task_scheduler.toggle_schedule(sid, enabled=False)
        disabled_sched = task_scheduler.get_schedule(sid)
        self.assertEqual(disabled_sched["enabled"], 0)

        # Tick
        await task_scheduler.tick()

        # Verify last_run_at is still None
        post_tick = task_scheduler.get_schedule(sid)
        self.assertIsNone(post_tick["last_run_at"], "Disabled schedule must not be executed")

    async def test_05_approval_required_scheduled_task(self):
        """Test that scheduled consequential tasks require user approval and are never auto-authorized."""
        sched = task_scheduler.create_schedule(
            task_name="Consequential Scheduled Action",
            user_request="Run diagnostic command whoami",
            schedule_type="interval",
            interval_seconds=600,
            start_delay_seconds=0,
        )
        sid = sched["id"]

        # Tick
        await task_scheduler.tick()

        # Check status is awaiting_approval (not auto-executed!)
        refreshed = task_scheduler.get_schedule(sid)
        self.assertEqual(refreshed["last_status"], "awaiting_approval")
        self.assertIn("approval", refreshed["last_error"].lower())

        # Check history recorded the awaiting_approval status
        history = task_scheduler.get_schedule_history(sid)
        self.assertTrue(len(history) >= 1)
        self.assertEqual(history[0]["status"], "awaiting_approval")


if __name__ == "__main__":
    unittest.main()
