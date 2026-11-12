from __future__ import annotations
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from app.core.db import conn

# Sensitive pattern detection for credential redaction
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


# -------------------------------------------------------------
# SECURE BOOTSTRAP CREDENTIAL LIFECYCLE
# -------------------------------------------------------------
_BOOTSTRAP_SECRET: str | None = None
BOOTSTRAP_FILE_PATH = Path.home() / ".laptop_ai" / "bootstrap.token"


def get_or_create_bootstrap_secret() -> str:
    """
    Generate or retrieve the local bootstrap secret.
    Stored exclusively in backend-protected storage (%USERPROFILE%/.laptop_ai/bootstrap.token)
    with restricted permissions (0o600).
    Never copied to public frontend assets or exposed via unauthenticated endpoints.
    """
    global _BOOTSTRAP_SECRET
    if _BOOTSTRAP_SECRET is not None:
        return _BOOTSTRAP_SECRET

    # Check environment variable first if operator configured explicit credential
    env_secret = os.getenv("LAPTOP_AI_BOOTSTRAP_SECRET", "").strip()
    if len(env_secret) >= 32:
        _BOOTSTRAP_SECRET = env_secret
        return _BOOTSTRAP_SECRET

    # Check if existing token file exists and is non-empty
    if BOOTSTRAP_FILE_PATH.is_file():
        try:
            content = BOOTSTRAP_FILE_PATH.read_text(encoding="utf-8").strip()
            if len(content) >= 32:
                _BOOTSTRAP_SECRET = content
        except Exception:
            pass

    if _BOOTSTRAP_SECRET is None:
        _BOOTSTRAP_SECRET = secrets.token_hex(32)
        try:
            BOOTSTRAP_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            BOOTSTRAP_FILE_PATH.write_text(_BOOTSTRAP_SECRET, encoding="utf-8")
            try:
                os.chmod(BOOTSTRAP_FILE_PATH, 0o600)
            except Exception:
                pass
        except Exception:
            pass

    return _BOOTSTRAP_SECRET


def validate_bootstrap_token(token: str | None) -> bool:
    """Validate submitted bootstrap credential using constant-time comparison."""
    if not token:
        return False
    current = get_or_create_bootstrap_secret()
    return hmac.compare_digest(str(token).strip(), current)


# -------------------------------------------------------------
# SESSION TOKEN REGISTRY & ROTATION LIFECYCLE
# -------------------------------------------------------------
@dataclass
class SessionRecord:
    token: str
    created_at: float
    expires_at: float
    revoked: bool = False
    client_info: str = "local"


_SESSIONS: dict[str, SessionRecord] = {}


def create_session_token(ttl_seconds: int = 86400, client_info: str = "local") -> SessionRecord:
    """Issue a new process-bound session token with cryptographic randomness and TTL."""
    token = secrets.token_hex(32)
    now = time.time()
    record = SessionRecord(
        token=token,
        created_at=now,
        expires_at=now + ttl_seconds,
        revoked=False,
        client_info=client_info,
    )
    _SESSIONS[token] = record
    return record


def validate_session_token(token: str | None) -> bool:
    """
    Validate session token using constant-time comparison, checking expiration and revocation.
    Rejects missing, invalid, expired, or revoked tokens.
    """
    if not token:
        return False
    token_str = str(token).strip()
    record = _SESSIONS.get(token_str)
    if not record:
        return False
    if record.revoked:
        return False
    if record.expires_at <= time.time():
        return False
    return hmac.compare_digest(token_str, record.token)


def rotate_session_token(old_token: str | None, ttl_seconds: int = 86400) -> SessionRecord | None:
    """Rotate an existing valid session token. Revokes the old token and issues a new active token."""
    if not old_token or not validate_session_token(old_token):
        return None
    token_str = str(old_token).strip()
    _SESSIONS[token_str].revoked = True
    return create_session_token(ttl_seconds=ttl_seconds, client_info=_SESSIONS[token_str].client_info)


def revoke_session_token(token: str | None) -> bool:
    """Explicitly revoke an active session token."""
    if not token:
        return False
    token_str = str(token).strip()
    if token_str in _SESSIONS:
        _SESSIONS[token_str].revoked = True
        return True
    return False


def get_test_session_token() -> str:
    """Generate or retrieve a verified session token for test suites."""
    # Find any active unexpired test session or create one
    now = time.time()
    for tok, rec in _SESSIONS.items():
        if rec.client_info == "test_suite" and not rec.revoked and rec.expires_at > now:
            return tok
    rec = create_session_token(ttl_seconds=86400, client_info="test_suite")
    return rec.token


def get_or_create_session_token() -> str:
    """Backward compatibility helper: retrieves or creates an active session token."""
    return get_test_session_token()


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
