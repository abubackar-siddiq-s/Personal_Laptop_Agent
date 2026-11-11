"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE (PHASE 6, QUEUE 1)
Exports desktop engine, security controls, window management,
screenshot routines, UI inspection, actions, and tool registration.
"""
from app.desktop.engine import desktop_engine, DesktopEngine
from app.desktop.security import (
    ensure_default_desktop,
    is_desktop_locked,
    verify_desktop_available,
    validate_keyboard_action,
    ALLOWED_STANDALONE_KEYS,
    ALLOWED_SHORTCUTS,
    STRICTLY_BLOCKED_COMBINATIONS,
)
from app.desktop.windows import get_active_window, list_windows, focus_window
from app.desktop.screenshots import capture_screenshot, list_screenshots, get_screenshot_thumbnail
from app.desktop.ui_inspection import inspect_ui
from app.desktop.actions import mouse_click, mouse_scroll, keyboard_type, keyboard_press
from app.desktop.tools import register_desktop_tools

__all__ = [
    "desktop_engine",
    "DesktopEngine",
    "ensure_default_desktop",
    "is_desktop_locked",
    "verify_desktop_available",
    "validate_keyboard_action",
    "ALLOWED_STANDALONE_KEYS",
    "ALLOWED_SHORTCUTS",
    "STRICTLY_BLOCKED_COMBINATIONS",
    "get_active_window",
    "list_windows",
    "focus_window",
    "capture_screenshot",
    "list_screenshots",
    "get_screenshot_thumbnail",
    "inspect_ui",
    "mouse_click",
    "mouse_scroll",
    "keyboard_type",
    "keyboard_press",
    "register_desktop_tools",
]

