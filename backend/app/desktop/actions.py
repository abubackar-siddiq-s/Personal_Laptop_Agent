"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE: MOUSE & KEYBOARD ACTIONS
Executes validated mouse and keyboard actions with accessibility priority,
bounds checking, allowlist enforcement, and emergency stop gates.
"""
from __future__ import annotations
import ctypes
import logging
import time
from typing import Optional, List
import pyautogui
import pyperclip

from app.desktop.security import (
    ensure_default_desktop,
    verify_desktop_available,
    validate_keyboard_action,
    is_sensitive_window,
)
from app.desktop.windows import get_active_window
from app.desktop.ui_inspection import inspect_ui
from app.core.security import audit

logger = logging.getLogger("laptop_ai.desktop.actions")

# Configure pyautogui safety
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

MAX_TYPE_LENGTH = 1000


def get_screen_dimensions() -> tuple[int, int]:
    """Return primary display resolution (width, height)."""
    try:
        w, h = pyautogui.size()
        return int(w), int(h)
    except Exception:
        return 1366, 768


def mouse_click(
    element_query: Optional[str] = None,
    control_type: Optional[str] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
) -> dict:
    """
    Click an accessible UI element by name/role, or click specific screen coordinates.
    Accessibility identification is prioritized over blind coordinates.
    """
    try:
        verify_desktop_available()
        ensure_default_desktop()
    except Exception as e:
        return {"success": False, "error": str(e)}

    btn = button.lower().strip()
    if btn not in ("left", "right", "middle"):
        btn = "left"
    clicks = max(1, min(clicks, 3))

    active = get_active_window()
    if active.get("is_sensitive"):
        audit("desktop.security_block", f"Blocked click on sensitive window: {active.get('title')}")
        return {
            "success": False,
            "error": f"Security restriction: Active window '{active.get('title')}' is a sensitive boundary. Interaction blocked.",
        }

    target_x = x
    target_y = y
    element_matched = None

    # Priority 1: Locate accessible element in active window if query specified
    if element_query or control_type:
        ui_res = inspect_ui(hwnd=active.get("hwnd"), max_depth=3, max_elements=50)
        if ui_res.get("success") and ui_res.get("elements"):
            query_lower = (element_query or "").lower().strip()
            ctype_lower = (control_type or "").lower().strip()

            candidates = []
            for el in ui_res["elements"]:
                name_match = query_lower in el["name"].lower() if query_lower else True
                type_match = ctype_lower == el["control_type"].lower() if ctype_lower else True
                if name_match and type_match:
                    candidates.append(el)

            if candidates:
                # Prefer exact name matches if possible
                exact = [c for c in candidates if c["name"].lower() == query_lower]
                element_matched = exact[0] if exact else candidates[0]
                target_x = element_matched["center"]["x"]
                target_y = element_matched["center"]["y"]
            else:
                return {
                    "success": False,
                    "error": (
                        f"Accessible UI element matching query='{element_query}' "
                        f"control_type='{control_type}' not found in active window '{active.get('title')}'."
                    ),
                }
        else:
            if target_x is None or target_y is None:
                return {
                    "success": False,
                    "error": (
                        f"Accessible UI element matching query='{element_query}' "
                        f"control_type='{control_type}' not found (application UI tree is not accessible via Windows UIAutomation: {ui_res.get('reason') or ui_res.get('error')})."
                    ),
                }

    # Validate coordinates
    if target_x is None or target_y is None:
        return {
            "success": False,
            "error": "Either element_query/control_type or (x, y) coordinates must be provided for mouse click.",
        }

    sw, sh = get_screen_dimensions()
    if not (0 <= target_x <= sw and 0 <= target_y <= sh):
        return {
            "success": False,
            "error": f"Coordinates ({target_x}, {target_y}) are outside the active screen bounds (0..{sw}, 0..{sh}).",
        }

    try:
        pyautogui.moveTo(target_x, target_y)
        pyautogui.click(x=target_x, y=target_y, clicks=clicks, button=btn)
        audit("desktop.mouse_click", f"Clicked ({target_x}, {target_y}) btn={btn} clicks={clicks} element={element_matched.get('name') if element_matched else None}")

        res = {
            "success": True,
            "clicked_at": {"x": target_x, "y": target_y},
            "button": btn,
            "clicks": clicks,
        }
        if element_matched:
            res["matched_element"] = {
                "name": element_matched["name"],
                "control_type": element_matched["control_type"],
                "patterns": element_matched.get("patterns", []),
            }
        return res

    except Exception as e:
        logger.error("Mouse click failed: %s", e)
        return {"success": False, "error": f"Mouse click failed: {type(e).__name__}: {str(e)}"}


def mouse_scroll(
    clicks: int = 3,
    direction: str = "down",
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> dict:
    """Scroll vertically or horizontally."""
    try:
        verify_desktop_available()
        ensure_default_desktop()
    except Exception as e:
        return {"success": False, "error": str(e)}

    dir_norm = direction.lower().strip()
    if dir_norm not in ("up", "down", "left", "right"):
        dir_norm = "down"

    clicks = max(1, min(clicks, 20))

    if x is not None and y is not None:
        sw, sh = get_screen_dimensions()
        if 0 <= x <= sw and 0 <= y <= sh:
            pyautogui.moveTo(x, y)
    else:
        # Check if cursor is parked in failsafe corner (0, 0)
        try:
            cur_pos = pyautogui.position()
            if cur_pos[0] == 0 and cur_pos[1] == 0:
                sw, sh = get_screen_dimensions()
                pyautogui.moveTo(sw // 2, sh // 2)
        except Exception:
            pass

    amount = clicks * 120
    try:
        if dir_norm == "down":
            pyautogui.scroll(-amount)
        elif dir_norm == "up":
            pyautogui.scroll(amount)
        elif dir_norm == "right":
            if hasattr(pyautogui, "hscroll"):
                pyautogui.hscroll(amount)
            else:
                pyautogui.scroll(-amount)
        elif dir_norm == "left":
            if hasattr(pyautogui, "hscroll"):
                pyautogui.hscroll(-amount)
            else:
                pyautogui.scroll(amount)

        audit("desktop.mouse_scroll", f"Scrolled {dir_norm} by {clicks} notches")
        return {"success": True, "direction": dir_norm, "clicks": clicks}

    except Exception as e:
        logger.error("Mouse scroll failed: %s", e)
        return {"success": False, "error": f"Mouse scroll failed: {type(e).__name__}: {str(e)}"}


def keyboard_type(text: str, press_enter: bool = False) -> dict:
    """
    Type text into the active application control.
    Enforces maximum length bounds and uses clipboard paste for Unicode reliability.
    """
    try:
        verify_desktop_available()
        ensure_default_desktop()
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not text:
        return {"success": False, "error": "No text provided to type."}

    if len(text) > MAX_TYPE_LENGTH:
        return {
            "success": False,
            "error": f"Text length ({len(text)} chars) exceeds maximum allowed safe limit ({MAX_TYPE_LENGTH} chars).",
        }

    active = get_active_window()
    if active.get("is_sensitive"):
        audit("desktop.security_block", f"Blocked typing into sensitive window: {active.get('title')}")
        return {
            "success": False,
            "error": f"Security restriction: Active window '{active.get('title')}' is a sensitive credential boundary. Typing blocked.",
        }

    try:
        # Check if text contains non-ASCII characters; if so, paste via clipboard for reliable Unicode transfer
        has_unicode = any(ord(c) > 127 for c in text)
        if has_unicode:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.05)
        else:
            pyautogui.write(text, interval=0.01)

        if press_enter:
            pyautogui.press("enter")

        audit("desktop.keyboard_typed", f"Typed {len(text)} chars into window: {active.get('title')}")
        return {
            "success": True,
            "characters_typed": len(text),
            "pressed_enter": press_enter,
            "active_window": active.get("title", ""),
        }

    except Exception as e:
        logger.error("Keyboard type failed: %s", e)
        return {"success": False, "error": f"Keyboard typing failed: {type(e).__name__}: {str(e)}"}


def keyboard_press(
    key: Optional[str] = None,
    keys: Optional[List[str]] = None,
    modifiers: Optional[List[str]] = None,
) -> dict:
    """
    Execute an individual key press or approved shortcut combination.
    Enforces the strict security allowlist and blocks destructive system shortcuts.
    """
    try:
        verify_desktop_available()
        ensure_default_desktop()
    except Exception as e:
        return {"success": False, "error": str(e)}

    is_valid, combo, err = validate_keyboard_action(key=key, keys=keys, modifiers=modifiers)
    if not is_valid:
        return {"success": False, "error": err}

    active = get_active_window()
    if active.get("is_sensitive"):
        audit("desktop.security_block", f"Blocked shortcut on sensitive window: {active.get('title')}")
        return {
            "success": False,
            "error": f"Security restriction: Active window '{active.get('title')}' is a sensitive boundary. Shortcut blocked.",
        }

    try:
        parts = combo.split("+")
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)

        audit("desktop.keyboard_pressed", f"Executed key combination: {combo} on window: {active.get('title')}")
        return {
            "success": True,
            "executed_combination": combo,
            "active_window": active.get("title", ""),
        }

    except Exception as e:
        logger.error("Keyboard shortcut failed: %s", e)
        return {"success": False, "error": f"Keyboard shortcut execution failed: {type(e).__name__}: {str(e)}"}
