"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE: WINDOW INSPECTION & MANAGEMENT
Provides robust Win32-level window enumeration, active window telemetry,
focus switching, and geometry tracking.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import logging
from typing import Optional
import psutil

from app.desktop.security import ensure_default_desktop, is_sensitive_window
from app.core.security import audit

logger = logging.getLogger("laptop_ai.desktop.windows")

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None

SW_RESTORE = 9
SW_SHOW = 5
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080


def get_window_text(hwnd: int) -> str:
    """Retrieve window title text safely using Unicode API."""
    if not user32 or not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def get_window_process_info(hwnd: int) -> tuple[int, str]:
    """Retrieve PID and process executable name for a given HWND."""
    if not user32 or not hwnd:
        return 0, "unknown"
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    pid_val = pid.value
    if pid_val <= 0:
        return 0, "system"
    try:
        proc = psutil.Process(pid_val)
        return pid_val, proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return pid_val, "unknown"
    except Exception:
        return pid_val, "unknown"


def get_window_rect(hwnd: int) -> dict:
    """Retrieve window bounding rectangle and dimensions."""
    if not user32 or not hwnd:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = max(0, rect.right - rect.left)
    h = max(0, rect.bottom - rect.top)
    return {
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
        "width": w,
        "height": h,
    }


def get_active_window() -> dict:
    """
    Get detailed inspection data for the currently focused foreground window.
    Detects title, process name, PID, HWND, geometry, and minimization state.
    """
    ensure_default_desktop()
    if not user32:
        return {"success": False, "error": "Windows user32 library unavailable on this system."}

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {
            "success": True,
            "has_active_window": False,
            "hwnd": 0,
            "title": "",
            "process": "",
            "pid": 0,
            "message": "No active foreground window detected (desktop may be idle or locked).",
        }

    title = get_window_text(hwnd)
    pid, proc_name = get_window_process_info(hwnd)
    rect = get_window_rect(hwnd)
    is_min = bool(user32.IsIconic(hwnd))
    is_max = bool(user32.IsZoomed(hwnd))
    is_vis = bool(user32.IsWindowVisible(hwnd))

    return {
        "success": True,
        "has_active_window": True,
        "hwnd": hwnd,
        "title": title,
        "process": proc_name,
        "pid": pid,
        "rect": rect,
        "is_minimized": is_min,
        "is_maximized": is_max,
        "is_visible": is_vis,
        "is_sensitive": is_sensitive_window(title, proc_name),
    }


def list_windows(limit: int = 25, only_visible: bool = True) -> list[dict]:
    """
    List top-level application windows with titles, processes, and bounding boxes.
    Filters out toolbars, zero-sized invisible helpers, and empty handles.
    """
    ensure_default_desktop()
    if not user32:
        return []

    windows: list[dict] = []
    limit = max(1, min(limit, 100))

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enum_cb(hwnd, lparam):
        if only_visible and not user32.IsWindowVisible(hwnd):
            return True

        # Filter out tool windows
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & WS_EX_TOOLWINDOW:
            return True

        title = get_window_text(hwnd)
        if not title:
            return True

        rect = get_window_rect(hwnd)
        # Filter out offscreen or zero-sized windows
        if rect["width"] < 20 or rect["height"] < 20:
            return True

        pid, proc_name = get_window_process_info(hwnd)
        is_min = bool(user32.IsIconic(hwnd))
        is_max = bool(user32.IsZoomed(hwnd))

        windows.append({
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "pid": pid,
            "rect": rect,
            "is_minimized": is_min,
            "is_maximized": is_max,
            "is_sensitive": is_sensitive_window(title, proc_name),
        })

        if len(windows) >= limit:
            return False  # Stop enumeration
        return True

    cb = WNDENUMPROC(enum_cb)
    user32.EnumWindows(cb, 0)
    return windows


def focus_window(hwnd: Optional[int] = None, title: Optional[str] = None) -> dict:
    """
    Switch focus and bring the specified window to the foreground.
    Restores the window if it was minimized.
    Can identify window by exact HWND or substring title match.
    """
    ensure_default_desktop()
    if not user32:
        return {"success": False, "error": "user32 unavailable"}

    target_hwnd = hwnd
    target_title = title or ""

    if not target_hwnd and target_title:
        # Search by title
        open_windows = list_windows(limit=50, only_visible=False)
        query = target_title.lower().strip()
        matched = [w for w in open_windows if query in w["title"].lower() or query in w["process"].lower()]
        if not matched:
            return {
                "success": False,
                "error": f"No open window found matching '{target_title}'. Use desktop.window.list to view available windows.",
            }
        target_hwnd = matched[0]["hwnd"]
        target_title = matched[0]["title"]

    if not target_hwnd:
        return {"success": False, "error": "Either 'hwnd' or 'title' must be provided to focus a window."}

    if not user32.IsWindow(target_hwnd):
        return {"success": False, "error": f"Invalid or closed window handle: HWND {target_hwnd}."}

    # Restore if minimized
    if user32.IsIconic(target_hwnd):
        user32.ShowWindow(target_hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(target_hwnd, SW_SHOW)

    # Windows focus-stealing bypass: attach thread inputs
    cur_tid = kernel32.GetCurrentThreadId() if kernel32 else 0
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_tid))

    try:
        if fg_tid.value and fg_tid.value != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid.value, True)
            user32.SetForegroundWindow(target_hwnd)
            user32.BringWindowToTop(target_hwnd)
            user32.AttachThreadInput(cur_tid, fg_tid.value, False)
        else:
            user32.SetForegroundWindow(target_hwnd)
            user32.BringWindowToTop(target_hwnd)
    except Exception as e:
        logger.warning("Focus attach error: %s", e)
        user32.SetForegroundWindow(target_hwnd)

    resolved_title = get_window_text(target_hwnd) or target_title
    pid, proc_name = get_window_process_info(target_hwnd)

    audit("desktop.window_focused", f"Focused HWND {target_hwnd} ({resolved_title})")
    return {
        "success": True,
        "hwnd": target_hwnd,
        "title": resolved_title,
        "process": proc_name,
        "pid": pid,
        "message": f"Window '{resolved_title}' is now in the foreground.",
    }

