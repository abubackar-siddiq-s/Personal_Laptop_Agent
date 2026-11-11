"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE: CORE COORDINATOR
Centralized orchestrator for desktop state, telemetry, and action auditing.
"""
from __future__ import annotations
import collections
import datetime
import logging
from typing import Optional, List, Dict, Any

from app.desktop.security import is_desktop_locked, is_emergency_stopped, ensure_default_desktop
from app.desktop.windows import get_active_window, list_windows, focus_window
from app.desktop.screenshots import capture_screenshot, list_screenshots, get_screenshot_thumbnail
from app.desktop.ui_inspection import inspect_ui
from app.desktop.actions import get_screen_dimensions, mouse_click, mouse_scroll, keyboard_type, keyboard_press
from app.tools.native import launch_app, APPROVED_APPS

logger = logging.getLogger("laptop_ai.desktop.engine")


class DesktopEngine:
    def __init__(self, max_history: int = 50):
        self._action_history: collections.deque = collections.deque(maxlen=max_history)

    def record_action(self, action_type: str, details: dict, success: bool, error: Optional[str] = None):
        """Record an action in the recent desktop audit log."""
        record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "action_type": action_type,
            "details": details,
            "success": success,
            "error": error,
        }
        self._action_history.appendleft(record)

    def get_status(self) -> dict:
        """Get comprehensive desktop status for the UI dashboard."""
        ensure_default_desktop()
        locked = is_desktop_locked()
        stopped = is_emergency_stopped()
        sw, sh = get_screen_dimensions()
        active = get_active_window()
        open_wins = list_windows(limit=50)

        return {
            "available": not locked and not stopped,
            "is_locked": locked,
            "is_emergency_stopped": stopped,
            "display": {
                "width": sw,
                "height": sh,
                "aspect_ratio": f"{round(sw/sh, 2)}:1" if sh else "16:9",
            },
            "active_window": active if active.get("has_active_window") else None,
            "open_windows_count": len(open_wins),
            "approved_applications": list(APPROVED_APPS.keys()),
        }

    def get_action_history(self, limit: int = 30) -> list[dict]:
        """Return recent desktop actions."""
        return list(self._action_history)[:limit]


desktop_engine = DesktopEngine()

