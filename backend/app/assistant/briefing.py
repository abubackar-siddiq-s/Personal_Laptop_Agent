from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from app.core.db import get_db
from app.assistant.schemas import DailyBriefing
from app.assistant.profile import ProfileManager

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DailyBriefingGenerator:
    """
    Synthesizes daily briefings strictly from database state.
    Includes tasks, deadlines, overdue items, pending approvals,
    scheduled automations, reminders, and concrete next steps.
    """

    def __init__(self, profile_mgr: Optional[ProfileManager] = None) -> None:
        self.profile_mgr = profile_mgr or ProfileManager()

    def generate_briefing(self) -> DailyBriefing:
        now = _utc_now()
        now_iso = now.isoformat()
        today_date = now.strftime("%Y-%m-%d")
        tomorrow_iso = (now + timedelta(days=1)).isoformat()
        in_72h_iso = (now + timedelta(days=3)).isoformat()

        # Determine greeting
        hour = datetime.now().hour  # Local hour for friendly greeting
        if 5 <= hour < 12:
            time_greet = "Good morning"
        elif 12 <= hour < 18:
            time_greet = "Good afternoon"
        else:
            time_greet = "Good evening"

        profile = self.profile_mgr.get_full_profile()
        user_name = profile.preferences.get("name") or profile.preferences.get("user_name") or "there"
        greeting = f"{time_greet}, {user_name}!"

        # 1. Fetch pending approvals
        pending_approvals: List[Dict[str, Any]] = []
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, tool_name, args, risk, created_at
                FROM approvals
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            )
            for r in cursor.fetchall():
                pending_approvals.append({
                    "id": r["id"],
                    "tool_name": r["tool_name"],
                    "risk": r["risk"],
                    "created_at": r["created_at"],
                })

        # 2. Fetch tasks
        todays_tasks: List[Dict[str, Any]] = []
        overdue_tasks: List[Dict[str, Any]] = []
        upcoming_deadlines: List[Dict[str, Any]] = []
        project_map: Dict[str, Dict[str, Any]] = {}

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, title, user_request, status, priority, priority_reason,
                       deadline, estimated_duration_minutes, project_name, created_at
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
            tasks = cursor.fetchall()

        for t in tasks:
            task_data = {
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "priority": t["priority"] or "medium",
                "deadline": t["deadline"],
                "estimated_duration_minutes": t["estimated_duration_minutes"] or 30,
                "project_name": t["project_name"],
            }
            deadline = t["deadline"]
            if deadline:
                if deadline < now_iso:
                    overdue_tasks.append(task_data)
                elif deadline <= in_72h_iso:
                    upcoming_deadlines.append(task_data)

            # Check if task is today or in-progress
            if t["status"] in ("in_progress", "running") or (deadline and deadline.startswith(today_date)) or not deadline:
                todays_tasks.append(task_data)

            # Group by project
            p_name = t["project_name"] or "General"
            if p_name not in project_map:
                project_map[p_name] = {"project": p_name, "total_open": 0, "tasks": []}
            project_map[p_name]["total_open"] += 1
            project_map[p_name]["tasks"].append(t["title"])

        # 3. Scheduled automations
        scheduled_automations: List[Dict[str, Any]] = []
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, task_name, schedule_type, next_run_at, risk_level
                FROM scheduled_tasks
                WHERE enabled = 1
                ORDER BY next_run_at ASC
                LIMIT 10
                """
            )
            for r in cursor.fetchall():
                scheduled_automations.append({
                    "id": r["id"],
                    "task_name": r["task_name"],
                    "schedule_type": r["schedule_type"],
                    "next_run_at": r["next_run_at"],
                })

        # 4. Active reminders
        active_reminders: List[Dict[str, Any]] = []
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, title, reminder_type, due_at, status, snoozed_until
                FROM assistant_reminders
                WHERE status IN ('pending', 'snoozed')
                ORDER BY due_at ASC
                LIMIT 10
                """
            )
            for r in cursor.fetchall():
                active_reminders.append({
                    "id": r["id"],
                    "title": r["title"],
                    "reminder_type": r["reminder_type"],
                    "due_at": r["due_at"],
                    "status": r["status"],
                    "snoozed_until": r["snoozed_until"],
                })

        # 5. Synthesize Actionable Next Steps
        next_steps: List[str] = []
        if pending_approvals:
            next_steps.append(f"Review and approve {len(pending_approvals)} pending sensitive operation(s).")
        if overdue_tasks:
            top_overdue = overdue_tasks[0]['title']
            next_steps.append(f"Address overdue task: '{top_overdue}' (total overdue: {len(overdue_tasks)}).")
        if upcoming_deadlines:
            next_deadline = upcoming_deadlines[0]
            next_steps.append(f"Prepare for upcoming deadline: '{next_deadline['title']}' due {next_deadline['deadline']}.")
        if todays_tasks and not overdue_tasks:
            top_today = todays_tasks[0]['title']
            next_steps.append(f"Focus on top active task: '{top_today}'.")
        if not next_steps:
            next_steps.append("All scheduled items and tasks are up to date. Ready for new instructions.")

        # Summary narrative
        summary_parts = []
        if overdue_tasks:
            summary_parts.append(f"{len(overdue_tasks)} overdue task(s)")
        if pending_approvals:
            summary_parts.append(f"{len(pending_approvals)} pending approval(s)")
        summary_parts.append(f"{len(todays_tasks)} active task(s) for today")
        summary_parts.append(f"{len(active_reminders)} active reminder(s)")
        summary_parts.append(f"{len(scheduled_automations)} active automation(s)")
        summary = "Today's Status: " + ", ".join(summary_parts) + "."

        project_updates = list(project_map.values())

        return DailyBriefing(
            date=today_date,
            greeting=greeting,
            summary=summary,
            todays_tasks=todays_tasks,
            overdue_tasks=overdue_tasks,
            upcoming_deadlines=upcoming_deadlines,
            pending_approvals=pending_approvals,
            scheduled_automations=scheduled_automations,
            active_reminders=active_reminders,
            project_updates=project_updates,
            actionable_next_steps=next_steps,
        )

    def to_markdown(self, briefing: Optional[DailyBriefing] = None) -> str:
        b = briefing or self.generate_briefing()
        lines = [
            f"# Daily Briefing — {b.date}",
            f"**{b.greeting}**",
            f"\n{b.summary}\n",
            "## Actionable Next Steps",
        ]
        for step in b.actionable_next_steps:
            lines.append(f"- {step}")

        if b.pending_approvals:
            lines.append("\n## Pending Approvals Requires Attention")
            for a in b.pending_approvals:
                lines.append(f"- Approval #{a['id']}: `{a['tool_name']}` (risk: {a['risk']})")

        if b.overdue_tasks:
            lines.append("\n## Overdue Tasks")
            for ot in b.overdue_tasks:
                lines.append(f"- **{ot['title']}** (Priority: {ot['priority']}, Due: {ot['deadline']})")

        if b.upcoming_deadlines:
            lines.append("\n## Upcoming Deadlines (Next 72h)")
            for ud in b.upcoming_deadlines:
                lines.append(f"- **{ud['title']}** (Due: {ud['deadline']}, Priority: {ud['priority']})")

        if b.todays_tasks:
            lines.append("\n## Active & Today's Tasks")
            for t in b.todays_tasks[:5]:
                lines.append(f"- [{t['status'].upper()}] **{t['title']}** (Priority: {t['priority']})")

        if b.active_reminders:
            lines.append("\n## Active Reminders")
            for r in b.active_reminders[:5]:
                lines.append(f"- {r['title']} (Due: {r['due_at']}, Status: {r['status']})")

        if b.scheduled_automations:
            lines.append("\n## Scheduled Automations")
            for sa in b.scheduled_automations[:5]:
                lines.append(f"- {sa['task_name']} (Next: {sa['next_run_at']})")

        return "\n".join(lines)
