from __future__ import annotations
import hmac
import os
import re
import secrets
from pathlib import Path
from app.core.db import conn

# Session-bound authentication token for local API access
_SESSION_TOKEN: str | None = None

SENSITIVE_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z-_]{28,}"),
    re.compile(r"gsk_[a-zA-Z0-9]{20,}"),
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"(?i)\b(bearer\s+[a-zA-Z0-9_\-\.]{12,})"),
]


def sanitize_sensitive_strings(text: any) -> str:
    """Redact sensitive keys, tokens, and authorization strings from logs and output."""
    s = str(text)
    for p in SENSITIVE_PATTERNS:
        s = p.sub("[REDACTED_SECRET]", s)
    return s


def get_or_create_session_token() -> str:
    """Generate or retrieve the process-bound local session token."""
    global _SESSION_TOKEN
    if _SESSION_TOKEN is None:
        _SESSION_TOKEN = secrets.token_hex(32)
    return _SESSION_TOKEN


def validate_session_token(token: str | None) -> bool:
    """Validate session token using constant-time comparison."""
    if not token:
        return False
    current = get_or_create_session_token()
    return hmac.compare_digest(str(token).strip(), current)


# Standard approved user directory roots
APPROVED_ROOT_NAMES = ("Documents", "Desktop", "Downloads")
ROOTS = [(Path.home() / x).resolve() for x in APPROVED_ROOT_NAMES]

FOLDER_ALIASES: dict[str, Path] = {
    "downloads": (Path.home() / "Downloads").resolve(),
    "download": (Path.home() / "Downloads").resolve(),
    "documents": (Path.home() / "Documents").resolve(),
    "document": (Path.home() / "Documents").resolve(),
    "desktop": (Path.home() / "Desktop").resolve(),
}


def resolve_user_path(path: str | Path | None) -> Path:
    """
    Automatically resolve user directories and aliases without asking for the Windows username.
    Supports folder aliases: 'Downloads', 'Documents', 'Desktop', '~', or relative paths.
    """
    if not path or str(path).strip().lower() in ("", ".", "downloads", "download"):
        return FOLDER_ALIASES["downloads"]

    p_str = str(path).strip()
    p_lower = p_str.lower().replace("\\", "/")

    # Check direct folder aliases
    first_part = p_lower.split("/")[0]
    if first_part in FOLDER_ALIASES:
        base = FOLDER_ALIASES[first_part]
        parts = p_str.replace("\\", "/").split("/")[1:]
        if parts:
            return (base / Path(*parts)).resolve()
        return base

    # Expand tilde (~) or environment variables
    expanded = Path(os.path.expandvars(p_str)).expanduser()
    if not expanded.is_absolute():
        # Default relative paths to Downloads folder
        return (FOLDER_ALIASES["downloads"] / expanded).resolve()

    return expanded.resolve()


def allowed(path: str | Path) -> bool:
    """
    Check if the resolved path is located within approved user folders (Documents, Desktop, Downloads).
    Enforces path jailing and prevents path traversal out of user areas.
    """
    try:
        resolved = resolve_user_path(path)
        for r in ROOTS:
            try:
                resolved.relative_to(r)
                return True
            except (ValueError, OSError):
                pass
    except Exception:
        return False
    return False


def audit(event: str, detail: any):
    safe_detail = sanitize_sensitive_strings(detail)[:3000]
    with conn() as c:
        c.execute("INSERT INTO audit(event, detail) VALUES (?, ?)", (event, safe_detail))
