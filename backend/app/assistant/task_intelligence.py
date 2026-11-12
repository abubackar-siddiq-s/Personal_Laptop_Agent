from __future__ import annotations
import json
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_db
from app.assistant.schemas import TaskNaturalCreate, TaskPrioritization, WorkingHours
from app.assistant.profile import ProfileManager

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(iso_str: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class TaskIntelligenceEngine:
    """
    Intelligent task analysis:
    - Natural language task creation
    - Priority classification with reasoning
    - Deadline extraction & conflict detection
    - Working hours & capacity awareness
    - Daily and weekly planning synthesis
    """

    def __init__(self, profile_mgr: Optional[ProfileManager] = None) -> None:
        self.profile_mgr = profile_mgr or ProfileManager()

    def parse_natural_task(self, text: str) -> Dict[str, Any]:
        """
        Extracts title, objective, deadline, priority, project, and estimated duration
        from natural language.
        """
        lower = text.lower().strip()

        # Extract title (first line or first sentence)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        first_line = lines[0] if lines else text
        title = first_line[:80].strip()

        # Deadline extraction
        now = _utc_now()
        deadline: Optional[str] = None
        if "today" in lower:
            deadline = now.replace(hour=18, minute=0, second=0).isoformat()
        elif "tomorrow" in lower:
            deadline = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0).isoformat()
        elif "next week" in lower:
            deadline = (now + timedelta(days=7)).replace(hour=18, minute=0, second=0).isoformat()
        elif "in 2 days" in lower or "in two days" in lower:
            deadline = (now + timedelta(days=2)).replace(hour=18, minute=0, second=0).isoformat()
        else:
            # Check for YYYY-MM-DD pattern
            date_match = re.search(r"\b(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2})?)\b", text)
            if date_match:
                deadline = date_match.group(1)
                if "T" not in deadline:
                    deadline += "T18:00:00"

        # Duration extraction (e.g. 30 min, 1 hour, 45 minutes)
        duration_minutes = 30
        dur_match = re.search(r"(\d+)\s*(?:m|min|mins|minutes)", lower)
        if dur_match:
            duration_minutes = int(dur_match.group(1))
        else:
            hr_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)", lower)
            if hr_match:
                duration_minutes = int(float(hr_match.group(1)) * 60)

        # Priority and transparent reasoning
        priority = "medium"
        priority_reason = "Standard priority based on general task scope."

        if any(w in lower for w in ["urgent", "asap", "critical", "broken", "emergency", "fail", "immediately"]):
            priority = "critical"
            priority_reason = "Classified as critical due to urgent/emergency keywords."
        elif any(w in lower for w in ["important", "milestone", "priority", "finish today", "must do", "high priority"]):
            priority = "high"
            priority_reason = "Classified as high due to priority markers or target milestones."
        elif any(w in lower for w in ["eventually", "someday", "optional", "minor", "cleanup", "low priority", "when free"]):
            priority = "low"
            priority_reason = "Classified as low priority due to non-urgent exploration or optional keywords."
        elif deadline:
            # Check deadline urgency
            dt = _parse_iso(deadline)
            if dt:
                diff_hours = (dt - now).total_seconds() / 3600.0
                if diff_hours <= 24:
                    priority = "high"
                    priority_reason = f"Classified as high priority because deadline is within {int(diff_hours)} hours."
                elif diff_hours <= 72:
                    priority = "medium"
                    priority_reason = f"Classified as medium priority with upcoming deadline in {int(diff_hours // 24)} days."

        # Project extraction (looks for #project or "project: XYZ" or profile match)
        project_name: Optional[str] = None
        proj_match = re.search(r"(?:project[:\s]+|#)([\w\-]+)", text, re.IGNORECASE)
        if proj_match:
            project_name = proj_match.group(1)
        else:
            profile = self.profile_mgr.get_full_profile()
            for p in profile.projects:
                p_name = p.get("name") if isinstance(p, dict) else str(p)
                if p_name and p_name.lower() in lower:
                    project_name = p_name
                    break

        return {
            "title": title,
            "user_request": text,
            "objective": f"Complete {title}",
            "priority": priority,
            "priority_reason": priority_reason,
            "deadline": deadline,
            "estimated_duration_minutes": duration_minutes,
            "project_name": project_name,
        }

    def create_natural_task(self, req: TaskNaturalCreate) -> Dict[str, Any]:
        """
        Creates a new task with inferred or overridden properties.
        """
        parsed = self.parse_natural_task(req.user_request)

        # Overrides from req if explicitly passed
        final_priority = req.priority or parsed["priority"]
        final_reason = parsed["priority_reason"]
        if req.priority:
            final_reason = f"Explicitly set by user to {req.priority}."
        final_deadline = req.deadline or parsed["deadline"]
        final_project = req.project_name or parsed["project_name"]
        final_duration = req.estimated_duration_minutes or parsed["estimated_duration_minutes"]

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()

        # Check conflict
        conflict_warning = self._check_single_task_conflict(final_deadline, final_duration)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO tasks
                (id, title, user_request, objective, description, risk_level, status,
                 priority, priority_reason, deadline, estimated_duration_minutes, project_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'low', 'draft', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    parsed["title"],
                    req.user_request,
                    parsed["objective"],
                    req.user_request,
                    final_priority,
                    final_reason,
                    final_deadline,
                    final_duration,
                    final_project,
                    now,
                    now,
                ),
            )
            conn.commit()

        logger.info(f"[TaskIntelligenceEngine] Created natural task {task_id}: {parsed['title']} (Priority: {final_priority})")
        return {
            "id": task_id,
            "title": parsed["title"],
            "user_request": req.user_request,
            "priority": final_priority,
            "priority_reason": final_reason,
            "deadline": final_deadline,
            "estimated_duration_minutes": final_duration,
            "project_name": final_project,
            "conflict_warning": conflict_warning,
            "status": "draft",
            "created_at": now,
        }

    def prioritize_task(self, task_id: str, priority: str, reason: str) -> Optional[Dict[str, Any]]:
        now = _utc_now_iso()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE tasks
                SET priority = ?, priority_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (priority, reason, now, task_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None

            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row)

    def _check_single_task_conflict(self, deadline: Optional[str], duration_minutes: int) -> Optional[str]:
        if not deadline:
            return None
        dt = _parse_iso(deadline)
        if not dt:
            return None

        profile = self.profile_mgr.get_full_profile()
        wh: WorkingHours = profile.working_hours

        # Check work days
        weekday = dt.weekday()
        if weekday not in wh.work_days:
            day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][weekday]
            return f"Deadline falls on a non-working day ({day_name}). Configured work days: {wh.work_days}."

        # Check working hours
        try:
            start_h, start_m = map(int, wh.start_time.split(":"))
            end_h, end_m = map(int, wh.end_time.split(":"))
            task_time_minutes = dt.hour * 60 + dt.minute
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            if task_time_minutes < start_minutes or task_time_minutes > end_minutes:
                return f"Deadline ({dt.strftime('%H:%M')}) is outside preferred working hours ({wh.start_time} - {wh.end_time})."
        except Exception:
            pass

        return None

    def detect_conflicts(self) -> List[Dict[str, Any]]:
        """
        Scans all open tasks and detects schedule conflicts or overcapacity.
        """
        conflicts = []
        profile = self.profile_mgr.get_full_profile()
        wh: WorkingHours = profile.working_hours

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, title, deadline, estimated_duration_minutes, priority
                FROM tasks
                WHERE status NOT IN ('completed', 'cancelled') AND deadline IS NOT NULL
                ORDER BY deadline ASC
                """
            )
            tasks = cursor.fetchall()

        deadline_groups: Dict[str, List[Any]] = {}
        for t in tasks:
            warn = self._check_single_task_conflict(t["deadline"], t["estimated_duration_minutes"] or 30)
            if warn:
                conflicts.append({
                    "task_id": t["id"],
                    "title": t["title"],
                    "conflict_type": "outside_working_hours",
                    "details": warn,
                })

            date_str = t["deadline"][:10]
            if date_str not in deadline_groups:
                deadline_groups[date_str] = []
            deadline_groups[date_str].append(t)

        # Check daily duration overload (> 8 hours / 480 minutes)
        for date_str, group in deadline_groups.items():
            total_duration = sum((t["estimated_duration_minutes"] or 30) for t in group)
            if total_duration > 480:
                conflicts.append({
                    "date": date_str,
                    "conflict_type": "capacity_exceeded",
                    "details": f"Total estimated task workload ({total_duration} mins) exceeds 8-hour workday capacity on {date_str}.",
                    "task_count": len(group),
                })

        return conflicts

    def generate_daily_plan(self) -> Dict[str, Any]:
        """
        Creates an ordered sequence of tasks for today prioritized by urgency and dependencies.
        """
        now = _utc_now()
        today_date = now.strftime("%Y-%m-%d")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, title, status, priority, priority_reason, deadline,
                       estimated_duration_minutes, project_name
                FROM tasks
                WHERE status NOT IN ('completed', 'cancelled')
                ORDER BY 
                    CASE priority
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                        ELSE 5
                    END,
                    deadline ASC
                """
            )
            rows = cursor.fetchall()

        plan_items = []
        cumulative_minutes = 0
        for r in rows:
            dur = r["estimated_duration_minutes"] or 30
            cumulative_minutes += dur
            plan_items.append({
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "priority": r["priority"],
                "deadline": r["deadline"],
                "duration_minutes": dur,
                "project": r["project_name"] or "General",
                "cumulative_minutes": cumulative_minutes,
            })

        return {
            "date": today_date,
            "total_tasks": len(plan_items),
            "total_estimated_hours": round(cumulative_minutes / 60.0, 1),
            "plan": plan_items,
            "conflicts": self.detect_conflicts(),
        }

    def generate_weekly_plan(self) -> Dict[str, Any]:
        """
        Groups tasks across the current week.
        """
        now = _utc_now()
        start_of_week = now - timedelta(days=now.weekday())

        days = {}
        for i in range(7):
            d = (start_of_week + timedelta(days=i)).strftime("%Y-%m-%d")
            days[d] = []

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, title, priority, deadline, estimated_duration_minutes, project_name
                FROM tasks
                WHERE status NOT IN ('completed', 'cancelled')
                ORDER BY deadline ASC
                """
            )
            rows = cursor.fetchall()

        unassigned = []
        for r in rows:
            item = {
                "id": r["id"],
                "title": r["title"],
                "priority": r["priority"],
                "deadline": r["deadline"],
                "duration_minutes": r["estimated_duration_minutes"] or 30,
                "project": r["project_name"] or "General",
            }
            if r["deadline"] and r["deadline"][:10] in days:
                days[r["deadline"][:10]].append(item)
            else:
                unassigned.append(item)

        return {
            "week_start": start_of_week.strftime("%Y-%m-%d"),
            "schedule_by_day": days,
            "unassigned_tasks": unassigned,
        }

