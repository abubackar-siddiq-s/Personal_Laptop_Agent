import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.db import init_db, get_db
from app.core.emergency import trigger_emergency_stop, clear_emergency_stop, is_emergency_stopped
from app.tools.registry import registry
from app.assistant import (
    assistant_engine,
    ProfileManager,
    ReminderManager,
    DailyBriefingGenerator,
    MonitorManager,
    NotificationManager,
    TaskIntelligenceEngine,
    register_assistant_tools,
    ProfileItem,
    ReminderCreate,
    MonitorCreate,
    TaskNaturalCreate,
)
from app.assistant.schemas import ProfileUpdateReq


class TestPhase6Queue4ProactiveAssistance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        register_assistant_tools()
        clear_emergency_stop()

    def setUp(self):
        clear_emergency_stop()

    def test_01_profile_crud_and_categories(self):
        """Test profile creation, update, and retrieval by category."""
        pm = ProfileManager()
        req = ProfileUpdateReq(
            key="test_editor",
            value="VS Code Insiders",
            category="preferences",
            is_confirmed=True,
            confidence=1.0,
            source="user_explicit",
        )
        item = pm.update_profile_item(req)
        self.assertEqual(item.key, "test_editor")
        self.assertEqual(item.value, "VS Code Insiders")
        self.assertTrue(item.is_confirmed)

        profile = pm.get_full_profile()
        self.assertIn("test_editor", profile.preferences)
        self.assertEqual(profile.preferences["test_editor"], "VS Code Insiders")

    def test_02_confirmed_vs_inferred_preferences(self):
        """Test distinction between confirmed facts and inferred preferences."""
        pm = ProfileManager()
        # Inferred preference
        inferred = pm.update_profile_item(
            ProfileUpdateReq(
                key="suggested_language",
                value="Python",
                category="preferences",
                is_confirmed=False,
                confidence=0.75,
                source="assistant_inferred",
            )
        )
        self.assertFalse(inferred.is_confirmed)
        self.assertEqual(inferred.confidence, 0.75)

        # Confirm it explicitly
        confirmed = pm.update_profile_item(
            ProfileUpdateReq(
                key="suggested_language",
                value="Python",
                category="preferences",
                is_confirmed=True,
                confidence=1.0,
                source="user_confirmed",
            )
        )
        self.assertTrue(confirmed.is_confirmed)
        self.assertEqual(confirmed.confidence, 1.0)

    def test_03_credential_screening(self):
        """Verify that passwords, API keys, and sensitive tokens are rejected from profile."""
        pm = ProfileManager()
        sensitive_keys = [
            ("user_password", "supersecret123"),
            ("openai_api_key", "sk-proj-1234567890abcdef12345678"),
            ("aws_secret_access_key", "secret_value_here"),
            ("jwt_token", "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"),
        ]
        for key, val in sensitive_keys:
            with self.assertRaises(ValueError):
                pm.update_profile_item(
                    ProfileUpdateReq(
                        key=key,
                        value=val,
                        category="preferences",
                    )
                )

    def test_04_reminder_scheduling_and_types(self):
        """Test creation and retrieval of different reminder types."""
        rm = ReminderManager()
        now = datetime.now(timezone.utc)
        due_str = (now + timedelta(hours=2)).isoformat()

        # One-time
        r1 = rm.create_reminder(
            ReminderCreate(
                title="Review quarterly report",
                description="Check Q4 financial numbers",
                reminder_type="one_time",
                due_at=due_str,
            )
        )
        self.assertTrue(r1.id.startswith("rem_"))
        self.assertEqual(r1.status, "pending")

        # Daily
        r2 = rm.create_reminder(
            ReminderCreate(
                title="Morning standup",
                reminder_type="daily",
                due_at=due_str,
            )
        )
        self.assertEqual(r2.reminder_type, "daily")

        # Interval
        r3 = rm.create_reminder(
            ReminderCreate(
                title="Hydrate and stretch",
                reminder_type="interval",
                due_at=due_str,
                interval_seconds=3600,
            )
        )
        self.assertEqual(r3.interval_seconds, 3600)

        # List
        reminders = rm.list_reminders(status="pending")
        self.assertTrue(any(r.id == r1.id for r in reminders))

    def test_05_reminder_snooze_and_dismiss(self):
        """Test snoozing and dismissing reminders."""
        rm = ReminderManager()
        due = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        r = rm.create_reminder(ReminderCreate(title="Test Snooze", due_at=due))

        # Snooze for 30 minutes
        snoozed = rm.snooze_reminder(r.id, snooze_minutes=30)
        self.assertIsNotNone(snoozed)
        self.assertEqual(snoozed.status, "snoozed")
        self.assertIsNotNone(snoozed.snoozed_until)

        # Dismiss
        dismissed = rm.dismiss_reminder(r.id)
        self.assertTrue(dismissed)
        updated = rm.get_reminder(r.id)
        self.assertEqual(updated.status, "dismissed")

    def test_06_reminder_evaluation_and_recurrence(self):
        """Test that due reminders trigger and advance recurrence."""
        rm = ReminderManager()
        past_due = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()

        # Create due daily reminder
        r = rm.create_reminder(
            ReminderCreate(
                title="Daily sync due",
                reminder_type="daily",
                due_at=past_due,
            )
        )

        triggered = rm.evaluate_due_reminders()
        self.assertTrue(any(t["id"] == r.id for t in triggered))

        # Check that daily reminder advanced to next day
        updated = rm.get_reminder(r.id)
        self.assertEqual(updated.status, "pending")
        self.assertGreater(updated.due_at, datetime.now(timezone.utc).isoformat())

    def test_07_missed_reminder_recovery_on_startup(self):
        """Test recovery of reminders that became due while offline."""
        rm = ReminderManager()
        past_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

        r = rm.create_reminder(
            ReminderCreate(
                title="Offline deadline",
                reminder_type="deadline",
                due_at=past_time,
            )
        )

        missed = rm.recover_missed_reminders()
        self.assertTrue(any(m["id"] == r.id for m in missed))

        updated = rm.get_reminder(r.id)
        self.assertEqual(updated.status, "missed")

    def test_08_duplicate_notification_suppression(self):
        """Test that duplicate notifications are suppressed within cooldown window."""
        nm = NotificationManager()
        n1 = nm.create_notification(
            type="task_reminder",
            title="Duplicate Test",
            message="This should only alert once in window",
            severity="info",
            source_id="src_123",
            suppress_window_minutes=10,
        )

        # Immediate duplicate with exact same type, title, and source_id
        n2 = nm.create_notification(
            type="task_reminder",
            title="Duplicate Test",
            message="This should only alert once in window",
            severity="info",
            source_id="src_123",
            suppress_window_minutes=10,
        )
        self.assertEqual(n1.id, n2.id, "Second call should return existing notification without creating duplicate")

    def test_09_natural_task_creation_and_priority_reasoning(self):
        """Test NLP task parsing and automatic priority classification with reasoning."""
        tie = TaskIntelligenceEngine()

        # Critical task
        res_crit = tie.create_natural_task(
            TaskNaturalCreate(
                user_request="URGENT: Fix critical database deadlock in production immediately #backend"
            )
        )
        self.assertEqual(res_crit["priority"], "critical")
        self.assertIn("critical", res_crit["priority_reason"].lower())
        self.assertEqual(res_crit["project_name"], "backend")

        # Low task
        res_low = tie.create_natural_task(
            TaskNaturalCreate(
                user_request="Someday when free, cleanup optional unused icons in assets"
            )
        )
        self.assertEqual(res_low["priority"], "low")
        self.assertIn("low", res_low["priority_reason"].lower())

    def test_10_conflict_detection(self):
        """Test conflict detection for tasks scheduled outside working hours."""
        tie = TaskIntelligenceEngine()
        # Schedule deadline on Sunday at 11pm (outside 9-18 Mon-Fri)
        sunday_night = "2026-11-15T23:00:00"
        task = tie.create_natural_task(
            TaskNaturalCreate(
                user_request="Deploy weekend test patch",
                deadline=sunday_night,
            )
        )
        self.assertIsNotNone(task["conflict_warning"])
        self.assertIn("working", task["conflict_warning"].lower())

    def test_11_daily_and_weekly_planning(self):
        """Test daily and weekly schedule synthesis."""
        tie = TaskIntelligenceEngine()
        daily = tie.generate_daily_plan()
        self.assertIn("plan", daily)
        self.assertIn("total_tasks", daily)
        self.assertIn("total_estimated_hours", daily)

        weekly = tie.generate_weekly_plan()
        self.assertIn("schedule_by_day", weekly)
        self.assertEqual(len(weekly["schedule_by_day"]), 7)

    def test_12_daily_briefing_synthesis(self):
        """Test daily briefing generation strictly grounded in database data."""
        dbg = DailyBriefingGenerator()
        briefing = dbg.generate_briefing()
        self.assertIsNotNone(briefing.date)
        self.assertIsNotNone(briefing.greeting)
        self.assertIsNotNone(briefing.summary)
        self.assertTrue(len(briefing.actionable_next_steps) > 0)

        md = dbg.to_markdown(briefing)
        self.assertIn("Daily Briefing", md)
        self.assertIn("Actionable Next Steps", md)

    def test_13_proactive_monitors_lifecycle(self):
        """Test creating, toggling, evaluating, and deleting proactive monitors."""
        mm = MonitorManager()
        mon = mm.create_monitor(
            MonitorCreate(
                name="Test Overdue Monitor",
                monitor_type="task_overdue",
                threshold_seconds=1800,
            )
        )
        self.assertTrue(mon.id.startswith("mon_"))
        self.assertTrue(mon.enabled)

        # Toggle to disabled
        toggled = mm.toggle_monitor(mon.id, enabled=False)
        self.assertFalse(toggled.enabled)

        # Toggle back
        toggled2 = mm.toggle_monitor(mon.id, enabled=True)
        self.assertTrue(toggled2.enabled)

        # Evaluation runs without exceptions
        alerts = mm.evaluate_monitors()
        self.assertIsInstance(alerts, list)

        # Delete
        deleted = mm.delete_monitor(mon.id)
        self.assertTrue(deleted)

    def test_14_global_emergency_stop_integration(self):
        """Verify that Global Emergency Stop blocks assistant proactive ticks."""
        trigger_emergency_stop("Safety audit in test")
        self.assertTrue(is_emergency_stopped())

        # Assistant engine tick must skip execution when emergency stopped
        res = assistant_engine.tick()
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "emergency_stop")

        clear_emergency_stop()
        self.assertFalse(is_emergency_stopped())
        res_resumed = assistant_engine.tick()
        self.assertEqual(res_resumed["status"], "ok")

    def test_15_context_aware_query_resolution(self):
        """Verify answer_context_query distinguishes facts, evidence, and suggestions."""
        ans = assistant_engine.answer_context_query("What should I work on today?")
        self.assertIn("stored_facts", ans)
        self.assertIn("retrieved_evidence", ans)
        self.assertIn("assistant_suggestions", ans)
        self.assertIn("response", ans)
        self.assertTrue(len(ans["assistant_suggestions"]) > 0)

    def test_16_tool_registry_assistant_tools(self):
        """Verify all 15 assistant tools are registered in the central tool registry."""
        expected_tools = [
            "assistant.profile.get",
            "assistant.profile.update",
            "assistant.reminders.create",
            "assistant.reminders.list",
            "assistant.reminders.snooze",
            "assistant.reminders.dismiss",
            "assistant.briefing.get",
            "assistant.briefing.generate",
            "assistant.monitors.list",
            "assistant.monitors.create",
            "assistant.monitors.toggle",
            "assistant.tasks.create_natural",
            "assistant.tasks.prioritize",
            "assistant.notifications.list",
            "assistant.notifications.dismiss",
        ]
        all_registered = registry.list_all()
        registered_names = {t.name for t in all_registered}

        for exp in expected_tools:
            self.assertIn(exp, registered_names, f"Tool {exp} must be registered in tool registry.")

        # Test invoking one of the tools directly via registry
        profile_res = registry.invoke("assistant.profile.get", {})
        self.assertIn("preferences", profile_res)


if __name__ == "__main__":
    unittest.main()

