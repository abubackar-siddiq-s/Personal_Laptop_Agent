from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class ProfileItem(BaseModel):
    key: str
    value: Any
    category: str
    is_confirmed: bool = True
    confidence: float = 1.0
    source: str = "user_explicit"
    updated_at: Optional[str] = None


class ProfileUpdateReq(BaseModel):
    key: str
    value: Any
    category: str = "preferences"
    is_confirmed: bool = True
    confidence: float = 1.0
    source: str = "user_explicit"


class WorkingHours(BaseModel):
    start_time: str = "09:00"
    end_time: str = "18:00"
    work_days: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # Monday=0, Friday=4
    timezone: str = "local"


class PersonalProfile(BaseModel):
    preferences: Dict[str, Any] = Field(default_factory=dict)
    communication_style: str = "concise"
    goals: List[Dict[str, Any]] = Field(default_factory=list)
    projects: List[Dict[str, Any]] = Field(default_factory=list)
    frequent_apps: List[str] = Field(default_factory=list)
    working_hours: WorkingHours = Field(default_factory=WorkingHours)
    routines: List[Dict[str, Any]] = Field(default_factory=list)
    priorities: List[str] = Field(default_factory=list)
    important_deadlines: List[Dict[str, Any]] = Field(default_factory=list)
    items: List[ProfileItem] = Field(default_factory=list)


class ReminderCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    reminder_type: Literal["one_time", "daily", "weekly", "interval", "deadline", "follow_up"] = "one_time"
    due_at: str  # ISO timestamp
    interval_seconds: Optional[int] = None
    recurrence_rule: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReminderItem(BaseModel):
    id: str
    title: str
    description: Optional[str] = ""
    reminder_type: str
    due_at: str
    interval_seconds: Optional[int] = None
    recurrence_rule: Optional[str] = None
    status: str
    snoozed_until: Optional[str] = None
    last_triggered_at: Optional[str] = None
    created_at: str


class ReminderSnoozeReq(BaseModel):
    snooze_minutes: int = 15
    snooze_until: Optional[str] = None


class MonitorCreate(BaseModel):
    name: str
    monitor_type: Literal["task_overdue", "scheduler_failure", "pending_approval", "file_change", "recurring_due"]
    target_identifier: Optional[str] = "*"
    threshold_seconds: int = 3600


class MonitorItem(BaseModel):
    id: str
    name: str
    monitor_type: str
    target_identifier: Optional[str] = "*"
    threshold_seconds: int = 3600
    enabled: bool = True
    last_checked_at: Optional[str] = None
    last_alert_at: Optional[str] = None


class NotificationItem(BaseModel):
    id: str
    type: str
    title: str
    message: str
    severity: str = "info"
    source_id: Optional[str] = None
    read_status: bool = False
    dismissed: bool = False
    created_at: str


class DailyBriefing(BaseModel):
    date: str
    greeting: str
    summary: str
    todays_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    overdue_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    upcoming_deadlines: List[Dict[str, Any]] = Field(default_factory=list)
    pending_approvals: List[Dict[str, Any]] = Field(default_factory=list)
    scheduled_automations: List[Dict[str, Any]] = Field(default_factory=list)
    active_reminders: List[Dict[str, Any]] = Field(default_factory=list)
    project_updates: List[Dict[str, Any]] = Field(default_factory=list)
    actionable_next_steps: List[str] = Field(default_factory=list)


class TaskNaturalCreate(BaseModel):
    user_request: str
    project_name: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[Literal["critical", "high", "medium", "low"]] = None
    estimated_duration_minutes: Optional[int] = 30


class TaskPrioritization(BaseModel):
    task_id: str
    priority: str
    priority_reason: str
    deadline: Optional[str] = None
    estimated_duration_minutes: int = 30
    conflict_warning: Optional[str] = None

