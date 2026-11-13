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


def rotate_bootstrap_secret() -> str:
    """
    Generate and overwrite with a brand-new cryptographic bootstrap secret.
    Stored exclusively in backend-protected storage (%USERPROFILE%/.laptop_ai/bootstrap.token).
    Never logged or exposed.
    """
    global _BOOTSTRAP_SECRET
    _BOOTSTRAP_SECRET = secrets.token_hex(32)
    BOOTSTRAP_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOOTSTRAP_FILE_PATH.write_text(_BOOTSTRAP_SECRET, encoding="utf-8")
    try:
        os.chmod(BOOTSTRAP_FILE_PATH, 0o600)
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
# SESSION TOKEN REGISTRY & ROTATION LIFECYCLE (DURABLE SQLITE)
# -------------------------------------------------------------
@dataclass
class SessionRecord:
    token: str
    created_at: float
    expires_at: float
    revoked: bool = False
    client_info: str = "local"


_SESSIONS: dict[str, SessionRecord] = {}


def create_session_token(ttl_seconds: int = 30 * 86400, client_info: str = "local") -> SessionRecord:
    """Issue a new durable session token with cryptographic randomness and 30-day default TTL."""
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
    try:
        with conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO local_sessions (token, created_at, expires_at, revoked, client_info, last_active_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token, now, now + ttl_seconds, 0, client_info, now),
            )
    except Exception:
        pass
    return record


def validate_session_token(token: str | None) -> bool:
    """
    Validate session token using constant-time comparison, checking expiration and revocation.
    Backed by SQLite local_sessions to persist across backend restarts and browser sessions.
    """
    if not token:
        return False
    token_str = str(token).strip()
    now = time.time()

    # 1. Fast path: check in-memory cache
    record = _SESSIONS.get(token_str)
    if record:
        if record.revoked or record.expires_at <= now:
            return False
        return hmac.compare_digest(token_str, record.token)

    # 2. Database path: check persistent SQLite local_sessions
    try:
        with conn() as c:
            row = c.execute(
                "SELECT token, created_at, expires_at, revoked, client_info, last_active_at FROM local_sessions WHERE token = ?",
                (token_str,),
            ).fetchone()
            if not row:
                return False
            if bool(row["revoked"]) or row["expires_at"] <= now:
                return False

            record = SessionRecord(
                token=row["token"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                revoked=bool(row["revoked"]),
                client_info=row["client_info"] or "local",
            )
            _SESSIONS[token_str] = record

            # Rolling extension if within 7 days of expiry
            if row["expires_at"] - now < 7 * 86400:
                new_expiry = now + 30 * 86400
                record.expires_at = new_expiry
                c.execute(
                    "UPDATE local_sessions SET last_active_at = ?, expires_at = ? WHERE token = ?",
                    (now, new_expiry, token_str),
                )
            else:
                c.execute("UPDATE local_sessions SET last_active_at = ? WHERE token = ?", (now, token_str))

            return hmac.compare_digest(token_str, record.token)
    except Exception:
        return False


def rotate_session_token(old_token: str | None, ttl_seconds: int = 30 * 86400) -> SessionRecord | None:
    """Rotate an existing valid session token. Revokes the old token and issues a new active token."""
    if not old_token or not validate_session_token(old_token):
        return None
    token_str = str(old_token).strip()
    client_info = _SESSIONS[token_str].client_info if token_str in _SESSIONS else "local"
    revoke_session_token(token_str)
    return create_session_token(ttl_seconds=ttl_seconds, client_info=client_info)


def revoke_session_token(token: str | None) -> bool:
    """Explicitly revoke an active session token both in memory and in SQLite."""
    if not token:
        return False
    token_str = str(token).strip()
    if token_str in _SESSIONS:
        _SESSIONS[token_str].revoked = True
    try:
        with conn() as c:
            res = c.execute("UPDATE local_sessions SET revoked = 1 WHERE token = ?", (token_str,))
            return res.rowcount > 0 or token_str in _SESSIONS
    except Exception:
        return token_str in _SESSIONS


def create_setup_ticket(ttl_seconds: int = 120) -> str:
    """Generate a single-use, short-lived setup ticket for trusted local first-run onboarding."""
    ticket = secrets.token_urlsafe(32)
    now = time.time()
    try:
        with conn() as c:
            c.execute("DELETE FROM one_time_setup_tickets WHERE expires_at < ? OR used = 1", (now,))
            c.execute(
                "INSERT INTO one_time_setup_tickets (ticket, created_at, expires_at, used) VALUES (?, ?, ?, 0)",
                (ticket, now, now + ttl_seconds),
            )
    except Exception:
        pass
    return ticket


def consume_setup_ticket(ticket: str | None) -> bool:
    """Atomically consume a single-use setup ticket."""
    if not ticket:
        return False
    t_str = str(ticket).strip()
    now = time.time()
    try:
        with conn() as c:
            c.execute("BEGIN IMMEDIATE;")
            row = c.execute(
                "SELECT ticket FROM one_time_setup_tickets WHERE ticket = ? AND used = 0 AND expires_at > ?",
                (t_str, now),
            ).fetchone()
            if not row:
                c.execute("ROLLBACK;")
                return False
            c.execute("UPDATE one_time_setup_tickets SET used = 1 WHERE ticket = ?", (t_str,))
            c.execute("COMMIT;")
            return True
    except Exception:
        return False


def get_test_session_token() -> str:
    """Generate or retrieve a verified session token for test suites."""
    now = time.time()
    for tok, rec in list(_SESSIONS.items()):
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
