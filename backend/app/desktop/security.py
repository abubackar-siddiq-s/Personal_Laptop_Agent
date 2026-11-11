"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE: SECURITY & ACCESS CONTROL
Enforces desktop session validity, keyboard allowlisting, emergency stop gates,
approval lifecycle classification, and anti-keylogging protections.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import logging
from typing import Set

from app.core.emergency import is_emergency_stopped
from app.core.security import audit

logger = logging.getLogger("laptop_ai.desktop.security")

# =====================================================================
# 1. DESKTOP SESSION & ATTACHMENT
# =====================================================================

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None

DESKTOP_ACCESS_ALL = 0x01FF


def ensure_default_desktop() -> bool:
    """
    Ensure the calling thread is attached to the interactive user desktop (WinSta0\\default).
    In service or sandbox environments, threads may start detached from the interactive desktop.
    """
    if not user32:
        return False
    try:
        hdesk = user32.OpenDesktopW("default", 0, False, DESKTOP_ACCESS_ALL)
        if hdesk:
            res = user32.SetThreadDesktop(hdesk)
            return bool(res)
        return False
    except Exception as e:
        logger.debug("Failed to attach to default desktop: %s", e)
        return False


def is_desktop_locked() -> bool:
    """
    Check if the user's Windows desktop session is currently locked or inaccessible.
    Returns True if the workstation is locked (e.g. Winlogon / Lock Screen active).
    """
    if not user32:
        return False
    try:
        # OpenInputDesktop returns NULL if the input desktop is locked or switch desktop is active
        hdesk = user32.OpenInputDesktop(0, False, DESKTOP_ACCESS_ALL)
        if not hdesk:
            return True
        user32.CloseDesktop(hdesk)
        return False
    except Exception:
        return False


def verify_desktop_available():
    """Verify that Global Emergency Stop is clear and desktop session is interactive."""
    if is_emergency_stopped():
        raise PermissionError("Desktop operation blocked: Global Emergency Stop is currently engaged.")
    if is_desktop_locked():
        raise PermissionError("Desktop operation blocked: Windows desktop session is currently locked or unavailable.")


# =====================================================================
# 2. KEYBOARD ALLOWLIST & SECURITY BOUNDARIES
# =====================================================================

# Allowed individual keys
ALLOWED_STANDALONE_KEYS: Set[str] = {
    # Alphanumeric
    *(chr(c) for c in range(ord('a'), ord('z') + 1)),
    *(str(i) for i in range(10)),
    # Navigation & control
    "enter", "return", "tab", "space", "backspace", "delete", "escape", "esc",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "insert",
    # Function keys
    *(f"f{i}" for i in range(1, 13)),
    # Punctuation / symbols
    "period", "comma", "minus", "plus", "slash", "backslash", "semicolon",
    "quote", "bracketleft", "bracketright", "equal"
}

# Modifiers allowed in shortcuts
ALLOWED_MODIFIERS: Set[str] = {"ctrl", "control", "alt", "shift", "win"}

# Allowed combination shortcuts (normalized lowercase)
ALLOWED_SHORTCUTS: Set[str] = {
    # Standard editing & clipboard
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a",
    # Document operations
    "ctrl+s", "ctrl+f", "ctrl+p", "ctrl+o", "ctrl+n", "ctrl+h",
    # Browser & app tab navigation
    "ctrl+t", "ctrl+w", "ctrl+r", "ctrl+tab", "ctrl+shift+t", "ctrl+shift+tab", "ctrl+shift+n",
    "ctrl+l", "ctrl+k", "ctrl+d",
    # Window & app navigation
    "alt+tab", "alt+left", "alt+right", "alt+up", "alt+down", "alt+enter",
    "win+r", "win+e", "win+s", "win+m", "win+d",
    # Menu access
    "alt+f", "alt+e", "alt+v", "alt+t", "alt+h", "alt+w",
    # Function key combos
    "ctrl+f4", "ctrl+f5", "shift+f10", "alt+f4"
}

# Strictly blocked combinations that violate OS boundaries or terminate sessions
STRICTLY_BLOCKED_COMBINATIONS: Set[str] = {
    "ctrl+alt+del",
    "ctrl+alt+delete",
    "win+l",       # Lock workstation
    "win+x",       # Admin quick link
    "win+u",       # Ease of access
    "ctrl+shift+esc", # Task manager
}

# Sensitive window title patterns (credential prompts, UAC, password dialogs)
SENSITIVE_WINDOW_PATTERNS = [
    "windows security",
    "user account control",
    "enter network password",
    "credential manager",
    "sign in to your account",
    "smart screen",
    "bitlocker",
    "administrator: cmd",
    "administrator: powershell",
    "administrator: windows powershell",
]


def normalize_combination(keys: list[str] | str) -> str:
    """Normalize a combination like ['ctrl', 'Shift', 'T'] or 'Ctrl+V' to 'ctrl+shift+t'."""
    if isinstance(keys, str):
        parts = [p.strip().lower() for p in keys.replace("-", "+").split("+")]
    else:
        parts = [str(k).strip().lower() for k in keys]
    
    # Sort modifiers first: win, ctrl, alt, shift, then the final key
    mods = []
    regular = []
    order = {"win": 0, "ctrl": 1, "control": 1, "alt": 2, "shift": 3}
    for p in parts:
        if p in order:
            norm_mod = "ctrl" if p == "control" else p
            if norm_mod not in mods:
                mods.append(norm_mod)
        else:
            regular.append(p)
    mods.sort(key=lambda m: order.get(m, 99))
    return "+".join(mods + regular)


def validate_keyboard_action(key: str | None = None, keys: list[str] | None = None, modifiers: list[str] | None = None) -> tuple[bool, str, str | None]:
    """
    Validate requested keyboard key or shortcut.
    Returns: (is_valid: bool, normalized_key: str, error_message: str | None)
    """
    if keys:
        combo = normalize_combination(keys)
    elif key and modifiers:
        combo = normalize_combination(list(modifiers) + [key])
    elif key:
        combo = normalize_combination(key)
    else:
        return False, "", "No key or combination specified."

    # Check blocked combinations
    if combo in STRICTLY_BLOCKED_COMBINATIONS:
        audit("desktop.security_block", f"Blocked dangerous key combination: {combo}")
        return False, combo, f"Security Violation: Key combination '{combo}' is strictly blocked for system safety."

    # Single key check
    if "+" not in combo:
        if combo in ALLOWED_STANDALONE_KEYS or len(combo) == 1:
            return True, combo, None
        return False, combo, f"Key '{combo}' is not in the allowed standalone keys list."

    # Combination check
    if combo in ALLOWED_SHORTCUTS:
        return True, combo, None

    audit("desktop.security_block", f"Rejected unauthorized key shortcut: {combo}")
    return False, combo, f"Keyboard shortcut '{combo}' is not in the approved shortcut allowlist."


def is_sensitive_window(title: str, process_name: str = "") -> bool:
    """Check if the target window is a credential prompt, administrative shell, or security boundary."""
    combined = f"{title.lower()} {process_name.lower()}"
    for pat in SENSITIVE_WINDOW_PATTERNS:
        if pat in combined:
            return True
    return False

