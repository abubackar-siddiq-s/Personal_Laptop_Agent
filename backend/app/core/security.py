from __future__ import annotations
import os
from pathlib import Path
from app.core.db import conn

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
    with conn() as c:
        c.execute("INSERT INTO audit(event, detail) VALUES (?, ?)", (event, str(detail)[:3000]))
