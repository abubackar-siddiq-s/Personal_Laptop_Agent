from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from app.core.db import get_db
from app.assistant.schemas import ReminderCreate, ReminderItem, ReminderSnoozeReq
from app.assistant.notifications import NotificationManager

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


class ReminderManager:
    """
    Manages intelligent reminders with recurrence, snooze, dismiss,
    timezone handling, missed-reminder recovery, and notification integration.
    """

    def __init__(self, notification_mgr: Optional[NotificationManager] = None) -> None:
        self.notification_mgr = notification_mgr or NotificationManager()

    def create_reminder(self, req: ReminderCreate) -> ReminderItem:
        reminder_id = f"rem_{uuid.uuid4().hex[:10]}"
        now = _utc_now_iso()
        meta_json = json.dumps(req.metadata or {})

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO assistant_reminders
                (id, title, description, reminder_type, due_at, interval_seconds, recurrence_rule, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    reminder_id,
                    req.title,
                    req.description or "",
                    req.reminder_type,
                    req.due_at,
                    req.interval_seconds,
                    req.recurrence_rule,
                    meta_json,
                    now,
                    now,
                ),
            )
            conn.commit()

        logger.info(f"[ReminderManager] Created reminder {reminder_id}: {req.title} due at {req.due_at}")
        return ReminderItem(
            id=reminder_id,
            title=req.title,
            description=req.description or "",
            reminder_type=req.reminder_type,
            due_at=req.due_at,
            interval_seconds=req.interval_seconds,
            recurrence_rule=req.recurrence_rule,
            status="pending",
            created_at=now,
        )

    def get_reminder(self, reminder_id: str) -> Optional[ReminderItem]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assistant_reminders WHERE id = ?", (reminder_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return ReminderItem(
                id=row["id"],
                title=row["title"],
                description=row["description"],
                reminder_type=row["reminder_type"],
                due_at=row["due_at"],
                interval_seconds=row["interval_seconds"],
                recurrence_rule=row["recurrence_rule"],
                status=row["status"],
                snoozed_until=row["snoozed_until"],
                last_triggered_at=row["last_triggered_at"],
                created_at=row["created_at"],
            )

    def list_reminders(self, status: Optional[str] = None, limit: int = 50) -> List[ReminderItem]:
        with get_db() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM assistant_reminders WHERE status = ? ORDER BY due_at ASC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM assistant_reminders ORDER BY due_at ASC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [
                ReminderItem(
                    id=r["id"],
                    title=r["title"],
                    description=r["description"],
                    reminder_type=r["reminder_type"],
                    due_at=r["due_at"],
                    interval_seconds=r["interval_seconds"],
                    recurrence_rule=r["recurrence_rule"],
                    status=r["status"],
                    snoozed_until=r["snoozed_until"],
                    last_triggered_at=r["last_triggered_at"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def snooze_reminder(self, reminder_id: str, snooze_minutes: int = 15, snooze_until: Optional[str] = None) -> Optional[ReminderItem]:
        if snooze_until:
            new_time = snooze_until
        else:
            dt = datetime.now(timezone.utc) + timedelta(minutes=snooze_minutes)
            new_time = dt.isoformat()

        now = _utc_now_iso()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE assistant_reminders
                SET status = 'snoozed', snoozed_until = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_time, now, reminder_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None

        return self.get_reminder(reminder_id)

    def dismiss_reminder(self, reminder_id: str) -> bool:
        now = _utc_now_iso()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE assistant_reminders
                SET status = 'dismissed', updated_at = ?
                WHERE id = ?
                """,
                (now, reminder_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def reschedule_reminder(self, reminder_id: str, new_due_at: str) -> Optional[ReminderItem]:
        now = _utc_now_iso()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE assistant_reminders
                SET due_at = ?, status = 'pending', snoozed_until = NULL, updated_at = ?
                WHERE id = ?
                """,
                (new_due_at, now, reminder_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_reminder(reminder_id)

    def evaluate_due_reminders(self) -> List[Dict[str, Any]]:
        """
        Called during background scheduler tick.
        Checks for reminders whose due_at or snoozed_until is in the past.
        Dispatches notifications and advances recurrence rules.
        """
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        triggered: List[Dict[str, Any]] = []

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM assistant_reminders
                WHERE (status = 'pending' AND due_at <= ?)
                   OR (status = 'snoozed' AND snoozed_until <= ?)
                """,
                (now_iso, now_iso),
            )
            due_rows = cursor.fetchall()

        for row in due_rows:
            r_id = row["id"]
            r_title = row["title"]
            r_desc = row["description"] or ""
            r_type = row["reminder_type"]
            due_at = row["due_at"]

            # Emit notification via NotificationManager (suppresses exact dupes automatically)
            notif = self.notification_mgr.create_notification(
                type="task_reminder",
                title=f"Reminder: {r_title}",
                message=r_desc if r_desc else f"Scheduled reminder due at {due_at}",
                severity="warning" if r_type == "deadline" else "info",
                source_id=r_id,
                metadata={"reminder_id": r_id, "reminder_type": r_type, "due_at": due_at},
            )

            # Determine next state: recurrence or triggered
            if r_type == "daily":
                next_dt = _parse_iso(due_at) + timedelta(days=1)
                while next_dt <= now_dt:
                    next_dt += timedelta(days=1)
                self._update_recurrence(r_id, next_dt.isoformat(), now_iso)
            elif r_type == "weekly":
                next_dt = _parse_iso(due_at) + timedelta(days=7)
                while next_dt <= now_dt:
                    next_dt += timedelta(days=7)
                self._update_recurrence(r_id, next_dt.isoformat(), now_iso)
            elif r_type == "interval" and row["interval_seconds"]:
                step = max(int(row["interval_seconds"]), 60)
                next_dt = _parse_iso(due_at) + timedelta(seconds=step)
                while next_dt <= now_dt:
                    next_dt += timedelta(seconds=step)
                self._update_recurrence(r_id, next_dt.isoformat(), now_iso)
            else:
                # one_time, deadline, follow_up -> mark as triggered
                with get_db() as conn:
                    conn.execute(
                        """
                        UPDATE assistant_reminders
                        SET status = 'triggered', last_triggered_at = ?, snoozed_until = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (now_iso, now_iso, r_id),
                    )
                    conn.commit()

            triggered.append({
                "id": r_id,
                "title": r_title,
                "type": r_type,
                "notification_id": notif.id,
            })

        if triggered:
            logger.info(f"[ReminderManager] Evaluated and triggered {len(triggered)} reminders")
        return triggered

    def _update_recurrence(self, reminder_id: str, next_due_at: str, now_iso: str) -> None:
        with get_db() as conn:
            conn.execute(
                """
                UPDATE assistant_reminders
                SET due_at = ?, status = 'pending', snoozed_until = NULL, last_triggered_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_due_at, now_iso, now_iso, reminder_id),
            )
            conn.commit()

    def recover_missed_reminders(self) -> List[Dict[str, Any]]:
        """
        Called once on backend startup.
        Finds pending reminders that became due while the backend was offline,
        marks them as 'missed', and notifies the user with catch-up alerts.
        """
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        recovered: List[Dict[str, Any]] = []

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM assistant_reminders
                WHERE status = 'pending' AND due_at < ?
                """,
                (now_iso,),
            )
            missed_rows = cursor.fetchall()

        for row in missed_rows:
            r_id = row["id"]
            r_title = row["title"]
            r_due = row["due_at"]

            # Create catch-up notification
            notif = self.notification_mgr.create_notification(
                type="task_reminder",
                title=f"Missed Reminder: {r_title}",
                message=f"This reminder was due at {r_due} while the system was offline.",
                severity="warning",
                source_id=r_id,
                metadata={"reminder_id": r_id, "missed": True, "original_due": r_due},
            )

            # Mark reminder as missed
            with get_db() as conn:
                conn.execute(
                    """
                    UPDATE assistant_reminders
                    SET status = 'missed', last_triggered_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, r_id),
                )
                conn.commit()

            recovered.append({
                "id": r_id,
                "title": r_title,
                "due_at": r_due,
                "notification_id": notif.id,
            })

        if recovered:
            logger.warning(f"[ReminderManager] Recovered {len(recovered)} missed reminders after restart")
        return recovered
