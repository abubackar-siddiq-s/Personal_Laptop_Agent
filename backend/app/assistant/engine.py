from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from app.core.emergency import is_emergency_stopped
from app.assistant.profile import ProfileManager
from app.assistant.notifications import NotificationManager
from app.assistant.reminders import ReminderManager
from app.assistant.briefing import DailyBriefingGenerator
from app.assistant.monitors import MonitorManager
from app.assistant.task_intelligence import TaskIntelligenceEngine

logger = logging.getLogger(__name__)


class PersonalAssistantEngine:
    """
    Central orchestration engine for LAPTOP AI Proactive Personal Assistance:
    - Coordinates profile, reminders, briefing, monitors, notifications, and task intelligence.
    - Runs periodic evaluations during scheduler ticks respecting emergency stop.
    - Recovers missed reminders on system startup.
    - Answers context-aware queries distinguishing facts, evidence, and suggestions.
    """

    def __init__(
        self,
        profile_mgr: Optional[ProfileManager] = None,
        notification_mgr: Optional[NotificationManager] = None,
        reminder_mgr: Optional[ReminderManager] = None,
        briefing_gen: Optional[DailyBriefingGenerator] = None,
        monitor_mgr: Optional[MonitorManager] = None,
        task_intel: Optional[TaskIntelligenceEngine] = None,
    ) -> None:
        self.profile_mgr = profile_mgr or ProfileManager()
        self.notification_mgr = notification_mgr or NotificationManager()
        self.reminder_mgr = reminder_mgr or ReminderManager(notification_mgr=self.notification_mgr)
        self.briefing_gen = briefing_gen or DailyBriefingGenerator(profile_mgr=self.profile_mgr)
        self.monitor_mgr = monitor_mgr or MonitorManager(notification_mgr=self.notification_mgr)
        self.task_intel = task_intel or TaskIntelligenceEngine(profile_mgr=self.profile_mgr)

    def recover_on_startup(self) -> Dict[str, Any]:
        """
        Executed when the backend server launches.
        Recovers reminders that passed while the application was offline.
        """
        logger.info("[PersonalAssistantEngine] Initializing assistant engine & recovering state...")
        missed = self.reminder_mgr.recover_missed_reminders()
        return {
            "status": "ready",
            "recovered_reminders_count": len(missed),
            "recovered_reminders": missed,
        }

    def tick(self) -> Dict[str, Any]:
        """
        Periodic tick executed alongside the scheduler loop.
        Aborts immediately if Global Emergency Stop is active.
        """
        if is_emergency_stopped():
            logger.debug("[PersonalAssistantEngine] Tick skipped: Global Emergency Stop active.")
            return {"status": "skipped", "reason": "emergency_stop"}

        triggered_reminders = self.reminder_mgr.evaluate_due_reminders()
        triggered_monitors = self.monitor_mgr.evaluate_monitors()

        return {
            "status": "ok",
            "triggered_reminders": len(triggered_reminders),
            "triggered_monitors": len(triggered_monitors),
            "reminders": triggered_reminders,
            "monitors": triggered_monitors,
        }

    def answer_context_query(self, query: str) -> Dict[str, Any]:
        """
        Synthesizes structured context to answer user questions such as:
        - 'What should I work on today?'
        - 'What deadlines are approaching?'
        - 'What are my current priorities?'
        Strictly partitions confirmed facts, retrieved evidence, and assistant suggestions.
        """
        query_lower = query.lower()
        briefing = self.briefing_gen.generate_briefing()
        daily_plan = self.task_intel.generate_daily_plan()
        profile = self.profile_mgr.get_full_profile()

        # 1. Stored Facts (user preferences, confirmed items, projects)
        stored_facts = {
            "user_preferences": profile.preferences,
            "communication_style": profile.communication_style,
            "working_hours": profile.working_hours.model_dump(),
            "confirmed_projects": [p.get("name") if isinstance(p, dict) else str(p) for p in profile.projects],
            "confirmed_goals": profile.goals,
            "explicit_priorities": profile.priorities,
        }

        # 2. Retrieved Evidence (real DB records: active tasks, reminders, deadlines, approvals)
        retrieved_evidence = {
            "active_tasks_count": len(briefing.todays_tasks),
            "overdue_tasks_count": len(briefing.overdue_tasks),
            "upcoming_deadlines_count": len(briefing.upcoming_deadlines),
            "pending_approvals_count": len(briefing.pending_approvals),
            "active_reminders_count": len(briefing.active_reminders),
            "top_tasks": briefing.todays_tasks[:5],
            "deadlines": briefing.upcoming_deadlines[:5],
            "overdue": briefing.overdue_tasks,
            "approvals": briefing.pending_approvals,
            "conflicts": daily_plan.get("conflicts", []),
        }

        # 3. Model Suggestions (actionable next steps, recommended focus)
        suggestions: List[str] = list(briefing.actionable_next_steps)
        if "deadline" in query_lower:
            if briefing.upcoming_deadlines:
                suggestions.insert(0, f"Next critical deadline: '{briefing.upcoming_deadlines[0]['title']}' due at {briefing.upcoming_deadlines[0]['deadline']}.")
            else:
                suggestions.insert(0, "No pressing deadlines found within the next 72 hours.")

        if "what should i work on" in query_lower or "focus" in query_lower:
            if briefing.overdue_tasks:
                suggestions.insert(0, f"Immediate priority: Resolve overdue task '{briefing.overdue_tasks[0]['title']}'.")
            elif briefing.todays_tasks:
                top = briefing.todays_tasks[0]
                suggestions.insert(0, f"Top scheduled task: '{top['title']}' (Priority: {top['priority']}).")

        # Formulate a natural text response
        response_text = f"**{briefing.greeting}**\n\n{briefing.summary}\n\n**Recommended Focus:**\n"
        for idx, s in enumerate(suggestions[:4], 1):
            response_text += f"{idx}. {s}\n"

        return {
            "query": query,
            "response": response_text,
            "stored_facts": stored_facts,
            "retrieved_evidence": retrieved_evidence,
            "assistant_suggestions": suggestions,
        }


assistant_engine = PersonalAssistantEngine()
