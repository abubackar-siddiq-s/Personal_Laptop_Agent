from __future__ import annotations
import datetime
import json
import uuid
from typing import Any, Dict, List, Optional
from app.core.db import conn
from app.core.security import audit
from app.assistant.schemas import NotificationItem


class NotificationManager:
    """
    Manages persistent in-app notifications with duplicate suppression,
    read/unread status, and recovery after restart.
    """

    def __init__(self):
        pass

    def create_notification(
        self,
        type: str,
        title: str,
        message: str,
        severity: str = "info",
        source_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        suppress_window_minutes: int = 15,
    ) -> NotificationItem:
        """Create a notification, returning existing active notification if suppressed."""
        res = self.emit(
            notif_type=type,
            title=title,
            message=message,
            severity=severity,
            source_id=source_id,
            metadata=metadata,
            suppress_window_minutes=suppress_window_minutes,
        )
        if res is not None:
            return res

        # If duplicate was suppressed, return existing active notification
        with conn() as c:
            row = c.execute(
                """
                SELECT * FROM notifications
                WHERE source_id = ? AND type = ? AND dismissed = 0
                ORDER BY created_at DESC LIMIT 1
                """,
                (source_id, type),
            ).fetchone()
            if row:
                return NotificationItem(
                    id=row["id"],
                    type=row["type"],
                    title=row["title"],
                    message=row["message"],
                    severity=row["severity"],
                    source_id=row["source_id"],
                    read_status=bool(row["read_status"]),
                    dismissed=bool(row["dismissed"]),
                    created_at=row["created_at"],
                )

        now = datetime.datetime.now().astimezone().isoformat()
        return NotificationItem(
            id=f"notif_{uuid.uuid4().hex[:8]}",
            type=type,
            title=title,
            message=message,
            severity=severity,
            source_id=source_id,
            created_at=now,
        )

    def emit(
        self,
        notif_type: str,
        title: str,
        message: str,
        severity: str = "info",
        source_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        suppress_window_minutes: int = 15,
    ) -> Optional[NotificationItem]:
        """
        Create a new persistent in-app notification with duplicate suppression.
        If an identical notification from the same source was emitted within suppress_window_minutes,
        it suppresses the duplicate to prevent notification fatigue.
        """
        now = datetime.datetime.now().astimezone()
        cutoff = (now - datetime.timedelta(minutes=suppress_window_minutes)).isoformat()

        with conn() as c:
            # Check for duplicate
            if source_id:
                recent = c.execute(
                    """
                    SELECT id FROM notifications
                    WHERE source_id = ? AND type = ? AND created_at >= ? AND dismissed = 0
                    LIMIT 1
                    """,
                    (source_id, notif_type, cutoff),
                ).fetchone()
                if recent:
                    return None  # Duplicate suppressed

            notif_id = f"notif_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            meta_json = json.dumps(metadata or {})

            c.execute(
                """
                INSERT INTO notifications(id, type, title, message, severity, source_id, read_status, dismissed, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (notif_id, notif_type, title, message, severity, source_id, meta_json, now.isoformat()),
            )

        audit("notification.emitted", f"Notification '{title}' ({notif_type}, {severity})")

        return NotificationItem(
            id=notif_id,
            type=notif_type,
            title=title,
            message=message,
            severity=severity,
            source_id=source_id,
            read_status=False,
            dismissed=False,
            created_at=now.isoformat(),
        )

    def list_notifications(
        self,
        include_dismissed: bool = False,
        limit: int = 50,
        unread_only: bool = False,
    ) -> List[NotificationItem]:
        """List in-app notifications with filtering options."""
        query = "SELECT * FROM notifications WHERE 1=1"
        params: List[Any] = []

        if not include_dismissed:
            query += " AND dismissed = 0"
        if unread_only:
            query += " AND read_status = 0"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))

        with conn() as c:
            rows = c.execute(query, params).fetchall()

        items = []
        for r in rows:
            items.append(
                NotificationItem(
                    id=r["id"],
                    type=r["type"],
                    title=r["title"],
                    message=r["message"],
                    severity=r["severity"],
                    source_id=r["source_id"],
                    read_status=bool(r["read_status"]),
                    dismissed=bool(r["dismissed"]),
                    created_at=r["created_at"],
                )
            )
        return items

    def mark_as_read(self, notif_id: str) -> bool:
        """Mark a notification as read."""
        with conn() as c:
            cur = c.execute("UPDATE notifications SET read_status = 1 WHERE id = ?", (notif_id,))
            return cur.rowcount > 0

    mark_read = mark_as_read

    def mark_all_read(self) -> int:
        """Mark all active notifications as read."""
        with conn() as c:
            cur = c.execute("UPDATE notifications SET read_status = 1 WHERE read_status = 0")
            return cur.rowcount

    def dismiss(self, notif_id: str) -> bool:
        """Dismiss a notification."""
        with conn() as c:
            cur = c.execute("UPDATE notifications SET dismissed = 1, read_status = 1 WHERE id = ?", (notif_id,))
            return cur.rowcount > 0

    dismiss_notification = dismiss

    def dismiss_all(self) -> int:
        """Dismiss all notifications."""
        with conn() as c:
            cur = c.execute("UPDATE notifications SET dismissed = 1, read_status = 1 WHERE dismissed = 0")
            return cur.rowcount

    def get_unread_count(self) -> int:
        """Get the count of active unread notifications."""
        with conn() as c:
            row = c.execute("SELECT COUNT(*) AS cnt FROM notifications WHERE read_status = 0 AND dismissed = 0").fetchone()
            return row["cnt"] if row else 0


notification_manager = NotificationManager()
