from __future__ import annotations
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.db import get_db
from app.assistant.schemas import MonitorCreate, MonitorItem
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


class MonitorManager:
    """
    Manages user-configurable proactive monitors:
    - Task overdue checks
    - Scheduler execution failure alerts
    - Pending approval age warnings
    - File/directory modification monitors
    - Recurring automation health checks
    Evaluates in bounded, non-blocking ticks and emits structured notifications.
    """

    def __init__(self, notification_mgr: Optional[NotificationManager] = None) -> None:
        self.notification_mgr = notification_mgr or NotificationManager()

    def create_monitor(self, req: MonitorCreate) -> MonitorItem:
        m_id = f"mon_{uuid.uuid4().hex[:10]}"
        now = _utc_now_iso()

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO assistant_monitors
                (id, name, monitor_type, target_identifier, threshold_seconds, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    m_id,
                    req.name,
                    req.monitor_type,
                    req.target_identifier or "*",
                    req.threshold_seconds or 3600,
                    now,
                ),
            )
            conn.commit()

        logger.info(f"[MonitorManager] Created monitor {m_id}: {req.name} ({req.monitor_type})")
        return MonitorItem(
            id=m_id,
            name=req.name,
            monitor_type=req.monitor_type,
            target_identifier=req.target_identifier or "*",
            threshold_seconds=req.threshold_seconds or 3600,
            enabled=True,
            created_at=now,
        )

    def list_monitors(self, enabled_only: bool = False) -> List[MonitorItem]:
        with get_db() as conn:
            cursor = conn.cursor()
            if enabled_only:
                cursor.execute("SELECT * FROM assistant_monitors WHERE enabled = 1 ORDER BY created_at ASC")
            else:
                cursor.execute("SELECT * FROM assistant_monitors ORDER BY created_at ASC")
            rows = cursor.fetchall()
            return [
                MonitorItem(
                    id=r["id"],
                    name=r["name"],
                    monitor_type=r["monitor_type"],
                    target_identifier=r["target_identifier"],
                    threshold_seconds=r["threshold_seconds"],
                    enabled=bool(r["enabled"]),
                    last_checked_at=r["last_checked_at"],
                    last_alert_at=r["last_alert_at"],
                )
                for r in rows
            ]

    def toggle_monitor(self, monitor_id: str, enabled: Optional[bool] = None) -> Optional[MonitorItem]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT enabled FROM assistant_monitors WHERE id = ?", (monitor_id,))
            row = cursor.fetchone()
            if not row:
                return None
            new_enabled = enabled if enabled is not None else not bool(row["enabled"])
            cursor.execute(
                "UPDATE assistant_monitors SET enabled = ? WHERE id = ?",
                (1 if new_enabled else 0, monitor_id),
            )
            conn.commit()

        return self.get_monitor(monitor_id)

    def get_monitor(self, monitor_id: str) -> Optional[MonitorItem]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assistant_monitors WHERE id = ?", (monitor_id,))
            r = cursor.fetchone()
            if not r:
                return None
            return MonitorItem(
                id=r["id"],
                name=r["name"],
                monitor_type=r["monitor_type"],
                target_identifier=r["target_identifier"],
                threshold_seconds=r["threshold_seconds"],
                enabled=bool(r["enabled"]),
                last_checked_at=r["last_checked_at"],
                last_alert_at=r["last_alert_at"],
            )

    def delete_monitor(self, monitor_id: str) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM assistant_monitors WHERE id = ?", (monitor_id,))
            conn.commit()
            return cursor.rowcount > 0

    def evaluate_monitors(self) -> List[Dict[str, Any]]:
        """
        Called during scheduler tick.
        Evaluates all enabled monitors in bounded execution time.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        alerts: List[Dict[str, Any]] = []

        monitors = self.list_monitors(enabled_only=True)
        if not monitors:
            return alerts

        with get_db() as conn:
            cursor = conn.cursor()

            for mon in monitors:
                triggered = False
                alert_title = ""
                alert_msg = ""
                severity = "warning"
                new_state: Dict[str, Any] = {}

                try:
                    # 1. TASK OVERDUE
                    if mon.monitor_type == "task_overdue":
                        cursor.execute(
                            """
                            SELECT id, title, deadline FROM tasks
                            WHERE status NOT IN ('completed', 'cancelled')
                              AND deadline IS NOT NULL
                              AND deadline < ?
                            """,
                            (now_iso,),
                        )
                        overdue = cursor.fetchall()
                        if overdue:
                            triggered = True
                            alert_title = f"Task Overdue Alert ({len(overdue)} task{'s' if len(overdue) > 1 else ''})"
                            sample = overdue[0]
                            alert_msg = f"Task '{sample['title']}' is past its deadline ({sample['deadline']})."
                            severity = "warning"

                    # 2. SCHEDULER FAILURE
                    elif mon.monitor_type == "scheduler_failure":
                        cursor.execute(
                            """
                            SELECT sr.id, sr.schedule_id, st.task_name, sr.error, sr.triggered_at
                            FROM schedule_runs sr
                            JOIN scheduled_tasks st ON sr.schedule_id = st.id
                            WHERE sr.status = 'failed'
                            ORDER BY sr.triggered_at DESC
                            LIMIT 1
                            """
                        )
                        failed_run = cursor.fetchone()
                        if failed_run:
                            # Check if alert was already sent for this run
                            run_time = _parse_iso(failed_run["triggered_at"])
                            if (now - run_time).total_seconds() <= mon.threshold_seconds:
                                triggered = True
                                alert_title = f"Scheduler Failure: {failed_run['task_name']}"
                                alert_msg = f"Automation '{failed_run['task_name']}' failed at {failed_run['triggered_at']}. Error: {failed_run['error'] or 'unknown'}"
                                severity = "error"

                    # 3. PENDING APPROVAL AGE
                    elif mon.monitor_type == "pending_approval":
                        threshold_delta = timedelta(seconds=mon.threshold_seconds)
                        cutoff_iso = (now - threshold_delta).isoformat()
                        cursor.execute(
                            """
                            SELECT id, tool_name, risk, created_at FROM approvals
                            WHERE status = 'pending' AND created_at < ?
                            ORDER BY created_at ASC
                            """,
                            (cutoff_iso,),
                        )
                        stale_approvals = cursor.fetchall()
                        if stale_approvals:
                            triggered = True
                            alert_title = f"Pending Approvals Awaiting Decision ({len(stale_approvals)})"
                            oldest = stale_approvals[0]
                            alert_msg = f"Operation '{oldest['tool_name']}' has been pending approval since {oldest['created_at']}."
                            severity = "warning"

                    # 4. FILE CHANGE MONITOR
                    elif mon.monitor_type == "file_change":
                        target = mon.target_identifier
                        if target and target != "*" and os.path.exists(target):
                            mtime = os.path.getmtime(target)
                            cursor.execute("SELECT last_state_json FROM assistant_monitors WHERE id = ?", (mon.id,))
                            state_row = cursor.fetchone()
                            old_state = json.loads(state_row["last_state_json"]) if state_row and state_row["last_state_json"] else {}
                            old_mtime = old_state.get("mtime")
                            if old_mtime is not None and mtime > old_mtime:
                                triggered = True
                                alert_title = f"File Modified: {os.path.basename(target)}"
                                alert_msg = f"Monitored file or directory was modified at {datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()}."
                                severity = "info"
                            new_state = {"mtime": mtime}

                    # 5. RECURRING DUE
                    elif mon.monitor_type == "recurring_due":
                        threshold_delta = timedelta(seconds=mon.threshold_seconds)
                        target_iso = (now + threshold_delta).isoformat()
                        cursor.execute(
                            """
                            SELECT id, task_name, next_run_at FROM scheduled_tasks
                            WHERE enabled = 1 AND next_run_at <= ? AND next_run_at >= ?
                            """,
                            (target_iso, now_iso),
                        )
                        nearing = cursor.fetchall()
                        if nearing:
                            triggered = True
                            alert_title = f"Scheduled Task Approaching: {nearing[0]['task_name']}"
                            alert_msg = f"Task '{nearing[0]['task_name']}' is scheduled to run at {nearing[0]['next_run_at']}."
                            severity = "info"

                    # Update monitor check state
                    state_json = json.dumps(new_state) if new_state else None
                    if triggered:
                        notif = self.notification_mgr.create_notification(
                            type="monitor_alert",
                            title=alert_title,
                            message=alert_msg,
                            severity=severity,
                            source_id=mon.id,
                            metadata={"monitor_id": mon.id, "monitor_name": mon.name, "type": mon.monitor_type},
                        )
                        cursor.execute(
                            """
                            UPDATE assistant_monitors
                            SET last_checked_at = ?, last_alert_at = ?, last_state_json = COALESCE(?, last_state_json)
                            WHERE id = ?
                            """,
                            (now_iso, now_iso, state_json, mon.id),
                        )
                        alerts.append({
                            "monitor_id": mon.id,
                            "name": mon.name,
                            "type": mon.monitor_type,
                            "notification_id": notif.id,
                            "title": alert_title,
                        })
                    else:
                        cursor.execute(
                            """
                            UPDATE assistant_monitors
                            SET last_checked_at = ?, last_state_json = COALESCE(?, last_state_json)
                            WHERE id = ?
                            """,
                            (now_iso, state_json, mon.id),
                        )

                except Exception as e:
                    logger.error(f"[MonitorManager] Error evaluating monitor {mon.id} ({mon.name}): {e}")

            conn.commit()

        if alerts:
            logger.info(f"[MonitorManager] Evaluated monitors, generated {len(alerts)} alert(s)")
        return alerts

