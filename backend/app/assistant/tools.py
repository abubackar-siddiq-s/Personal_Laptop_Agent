from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from app.tools.registry import Spec, registry
from app.assistant.engine import assistant_engine
from app.assistant.schemas import (
    ProfileUpdateReq,
    ReminderCreate,
    ReminderSnoozeReq,
    MonitorCreate,
    TaskNaturalCreate,
)

logger = logging.getLogger(__name__)


def register_assistant_tools():
    """Register all Proactive Personal Assistance tools in the central tool registry."""

    # 1. assistant.profile.get
    registry.add(
        Spec(
            name="assistant.profile.get",
            description="Retrieve the complete user profile including preferences, working hours, goals, projects, and routines.",
            source="assistant",
            risk="read",
            schema={"type": "object", "properties": {}},
            handler=lambda **kwargs: assistant_engine.profile_mgr.get_full_profile().model_dump(),
        )
    )

    # 2. assistant.profile.update
    registry.add(
        Spec(
            name="assistant.profile.update",
            description="Update or store a preference, goal, or routine in the user profile. Screens out passwords/credentials automatically.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Profile key identifier, e.g. 'preferred_name', 'theme', 'goal_q4'"},
                    "value": {"description": "Value to store (string, list, or object)"},
                    "category": {"type": "string", "description": "Category: preferences, goals, projects, routines, working_hours"},
                    "is_confirmed": {"type": "boolean", "description": "Whether explicitly confirmed by user (true) or inferred (false)", "default": True},
                },
                "required": ["key", "value"],
            },
            handler=lambda key, value, category="preferences", is_confirmed=True, **kwargs: (
                assistant_engine.profile_mgr.update_profile_item(
                    ProfileUpdateReq(
                        key=key,
                        value=value,
                        category=category,
                        is_confirmed=is_confirmed,
                        confidence=1.0 if is_confirmed else 0.8,
                        source="user_explicit" if is_confirmed else "assistant_inferred",
                    )
                ).model_dump()
            ),
        )
    )

    # 3. assistant.reminders.create
    registry.add(
        Spec(
            name="assistant.reminders.create",
            description="Create an intelligent reminder (one_time, daily, weekly, interval, deadline, follow_up) with timezone awareness.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title of the reminder"},
                    "description": {"type": "string", "description": "Optional detailed reminder description"},
                    "reminder_type": {
                        "type": "string",
                        "enum": ["one_time", "daily", "weekly", "interval", "deadline", "follow_up"],
                        "default": "one_time",
                    },
                    "due_at": {"type": "string", "description": "ISO timestamp for when the reminder is due"},
                    "interval_seconds": {"type": "integer", "description": "Interval in seconds if reminder_type is 'interval'"},
                    "recurrence_rule": {"type": "string", "description": "Optional recurrence rule description"},
                },
                "required": ["title", "due_at"],
            },
            handler=lambda title, due_at, description="", reminder_type="one_time", interval_seconds=None, recurrence_rule=None, **kwargs: (
                assistant_engine.reminder_mgr.create_reminder(
                    ReminderCreate(
                        title=title,
                        description=description,
                        reminder_type=reminder_type,
                        due_at=due_at,
                        interval_seconds=interval_seconds,
                        recurrence_rule=recurrence_rule,
                    )
                ).model_dump()
            ),
        )
    )

    # 4. assistant.reminders.list
    registry.add(
        Spec(
            name="assistant.reminders.list",
            description="List scheduled reminders filtered by status (pending, snoozed, triggered, dismissed, missed).",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status: pending, snoozed, triggered, dismissed, or omit for all"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
            handler=lambda status=None, limit=20, **kwargs: [
                r.model_dump() for r in assistant_engine.reminder_mgr.list_reminders(status=status, limit=limit)
            ],
        )
    )

    # 5. assistant.reminders.snooze
    registry.add(
        Spec(
            name="assistant.reminders.snooze",
            description="Snooze a reminder by minutes or to an exact timestamp.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "ID of the reminder to snooze"},
                    "snooze_minutes": {"type": "integer", "description": "Minutes to snooze from now", "default": 15},
                    "snooze_until": {"type": "string", "description": "Optional explicit ISO timestamp to snooze until"},
                },
                "required": ["reminder_id"],
            },
            handler=lambda reminder_id, snooze_minutes=15, snooze_until=None, **kwargs: (
                item.model_dump() if (item := assistant_engine.reminder_mgr.snooze_reminder(reminder_id, snooze_minutes, snooze_until)) else {"error": "Reminder not found"}
            ),
        )
    )

    # 6. assistant.reminders.dismiss
    registry.add(
        Spec(
            name="assistant.reminders.dismiss",
            description="Dismiss an active or triggered reminder.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "ID of the reminder to dismiss"},
                },
                "required": ["reminder_id"],
            },
            handler=lambda reminder_id, **kwargs: {
                "dismissed": assistant_engine.reminder_mgr.dismiss_reminder(reminder_id),
                "reminder_id": reminder_id,
            },
        )
    )

    # 7. assistant.briefing.get
    registry.add(
        Spec(
            name="assistant.briefing.get",
            description="Generate and return today's daily briefing with tasks, deadlines, overdue items, approvals, and actionable steps.",
            source="assistant",
            risk="read",
            schema={"type": "object", "properties": {}},
            handler=lambda **kwargs: assistant_engine.briefing_gen.generate_briefing().model_dump(),
        )
    )

    # 8. assistant.briefing.generate
    registry.add(
        Spec(
            name="assistant.briefing.generate",
            description="Generate a formatted Markdown daily briefing ready for reading or display.",
            source="assistant",
            risk="read",
            schema={"type": "object", "properties": {}},
            handler=lambda **kwargs: {"markdown": assistant_engine.briefing_gen.to_markdown()},
        )
    )

    # 9. assistant.monitors.list
    registry.add(
        Spec(
            name="assistant.monitors.list",
            description="List all proactive monitors (task_overdue, scheduler_failure, pending_approval, file_change, recurring_due).",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "enabled_only": {"type": "boolean", "default": False},
                },
            },
            handler=lambda enabled_only=False, **kwargs: [
                m.model_dump() for m in assistant_engine.monitor_mgr.list_monitors(enabled_only=enabled_only)
            ],
        )
    )

    # 10. assistant.monitors.create
    registry.add(
        Spec(
            name="assistant.monitors.create",
            description="Create a proactive system monitor to watch for task overdues, scheduler failures, pending approvals, or file changes.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Descriptive monitor name"},
                    "monitor_type": {
                        "type": "string",
                        "enum": ["task_overdue", "scheduler_failure", "pending_approval", "file_change", "recurring_due"],
                    },
                    "target_identifier": {"type": "string", "description": "Path or pattern (for file_change) or identifier", "default": "*"},
                    "threshold_seconds": {"type": "integer", "description": "Threshold or check age in seconds", "default": 3600},
                },
                "required": ["name", "monitor_type"],
            },
            handler=lambda name, monitor_type, target_identifier="*", threshold_seconds=3600, **kwargs: (
                assistant_engine.monitor_mgr.create_monitor(
                    MonitorCreate(
                        name=name,
                        monitor_type=monitor_type,
                        target_identifier=target_identifier,
                        threshold_seconds=threshold_seconds,
                    )
                ).model_dump()
            ),
        )
    )

    # 11. assistant.monitors.toggle
    registry.add(
        Spec(
            name="assistant.monitors.toggle",
            description="Enable or disable a proactive monitor.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "monitor_id": {"type": "string", "description": "ID of the monitor"},
                    "enabled": {"type": "boolean", "description": "Optional explicit target state"},
                },
                "required": ["monitor_id"],
            },
            handler=lambda monitor_id, enabled=None, **kwargs: (
                item.model_dump() if (item := assistant_engine.monitor_mgr.toggle_monitor(monitor_id, enabled)) else {"error": "Monitor not found"}
            ),
        )
    )

    # 12. assistant.tasks.create_natural
    registry.add(
        Spec(
            name="assistant.tasks.create_natural",
            description="Create a task from natural language with automatic priority assessment, deadline extraction, and conflict detection.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "user_request": {"type": "string", "description": "Natural language task description"},
                    "project_name": {"type": "string", "description": "Optional project association"},
                    "deadline": {"type": "string", "description": "Optional explicit deadline timestamp"},
                    "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "estimated_duration_minutes": {"type": "integer", "default": 30},
                },
                "required": ["user_request"],
            },
            handler=lambda user_request, project_name=None, deadline=None, priority=None, estimated_duration_minutes=30, **kwargs: (
                assistant_engine.task_intel.create_natural_task(
                    TaskNaturalCreate(
                        user_request=user_request,
                        project_name=project_name,
                        deadline=deadline,
                        priority=priority,
                        estimated_duration_minutes=estimated_duration_minutes,
                    )
                )
            ),
        )
    )

    # 13. assistant.tasks.prioritize
    registry.add(
        Spec(
            name="assistant.tasks.prioritize",
            description="Update the priority classification and transparent reason for a task.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "ID of the task"},
                    "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "reason": {"type": "string", "description": "Explanation for why this priority was assigned"},
                },
                "required": ["task_id", "priority", "reason"],
            },
            handler=lambda task_id, priority, reason, **kwargs: (
                res if (res := assistant_engine.task_intel.prioritize_task(task_id, priority, reason)) else {"error": "Task not found"}
            ),
        )
    )

    # 14. assistant.notifications.list
    registry.add(
        Spec(
            name="assistant.notifications.list",
            description="List in-app notifications (task reminders, approvals pending, monitor alerts).",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "unread_only": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "default": 30},
                },
            },
            handler=lambda unread_only=False, limit=30, **kwargs: [
                n.model_dump() for n in assistant_engine.notification_mgr.list_notifications(unread_only=unread_only, limit=limit)
            ],
        )
    )

    # 15. assistant.notifications.dismiss
    registry.add(
        Spec(
            name="assistant.notifications.dismiss",
            description="Dismiss an in-app notification by ID.",
            source="assistant",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "notification_id": {"type": "string", "description": "ID of the notification to dismiss"},
                },
                "required": ["notification_id"],
            },
            handler=lambda notification_id, **kwargs: {
                "dismissed": assistant_engine.notification_mgr.dismiss_notification(notification_id),
                "notification_id": notification_id,
            },
        )
    )

    logger.info("[assistant.tools] Registered 15 Proactive Personal Assistance tools.")
