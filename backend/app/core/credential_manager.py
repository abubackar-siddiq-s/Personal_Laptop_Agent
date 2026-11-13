"""
LAPTOP AI — MULTI-KEY PROVIDER CREDENTIAL MANAGER
Provides Windows DPAPI-encrypted credential persistence, intelligent automatic rotation,
health telemetry, and provider rate-limit / error classification for Google Gemini, Groq, and OpenRouter.
"""
from __future__ import annotations
import asyncio
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from typing import Optional, List, Dict, Any, Tuple

import httpx

from app.core.db import conn
from app.core.config import settings
from app.core.security import audit, sanitize_sensitive_strings

logger = logging.getLogger("laptop_ai.credential_manager")

SUPPORTED_PROVIDERS = ("gemini", "groq", "openrouter")
APPLICATION_ENTROPY = b"LAPTOP_AI_DPAPI_ENTROPY_V1"


class DPAPIError(RuntimeError):
    """Raised when Windows DPAPI encryption or decryption fails."""
    pass


# -------------------------------------------------------------
# WINDOWS DPAPI BINDINGS (CryptProtectData / CryptUnprotectData)
# -------------------------------------------------------------
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


_CRYPT_PROTECT = None
_CRYPT_UNPROTECT = None
_LOCAL_FREE = None

if sys.platform == "win32":
    try:
        _crypt32 = ctypes.windll.crypt32
        _kernel32 = ctypes.windll.kernel32

        _CRYPT_PROTECT = _crypt32.CryptProtectData
        _CRYPT_PROTECT.argtypes = [
            ctypes.POINTER(DATA_BLOB),          # pDataIn
            wintypes.LPCWSTR,                   # szDataDescr
            ctypes.POINTER(DATA_BLOB),          # pOptionalEntropy
            ctypes.c_void_p,                    # pvReserved
            ctypes.c_void_p,                    # pPromptStruct
            wintypes.DWORD,                     # dwFlags
            ctypes.POINTER(DATA_BLOB),          # pDataOut
        ]
        _CRYPT_PROTECT.restype = wintypes.BOOL

        _CRYPT_UNPROTECT = _crypt32.CryptUnprotectData
        _CRYPT_UNPROTECT.argtypes = [
            ctypes.POINTER(DATA_BLOB),          # pDataIn
            ctypes.POINTER(wintypes.LPWSTR),    # ppszDataDescr
            ctypes.POINTER(DATA_BLOB),          # pOptionalEntropy
            ctypes.c_void_p,                    # pvReserved
            ctypes.c_void_p,                    # pPromptStruct
            wintypes.DWORD,                     # dwFlags
            ctypes.POINTER(DATA_BLOB),          # pDataOut
        ]
        _CRYPT_UNPROTECT.restype = wintypes.BOOL

        _LOCAL_FREE = _kernel32.LocalFree
        _LOCAL_FREE.argtypes = [wintypes.HLOCAL]
    except Exception as e:
        logger.error("Failed to initialize Windows DPAPI functions: %s", e)


def encrypt_secret(plaintext: str, entropy: bytes = APPLICATION_ENTROPY) -> str:
    """
    Encrypt plaintext using Windows DPAPI under the CurrentUser security scope.
    Returns base64-encoded ciphertext.
    Never stores encryption keys alongside the ciphertext.
    """
    if sys.platform != "win32" or not _CRYPT_PROTECT or not _LOCAL_FREE:
        raise DPAPIError("Windows DPAPI is not available on this platform. Plaintext fallback is strictly prohibited.")

    if not plaintext:
        raise ValueError("Cannot encrypt empty secret.")

    b_data = plaintext.encode("utf-8")
    in_blob = DATA_BLOB(len(b_data), ctypes.cast(ctypes.c_char_p(b_data), ctypes.POINTER(ctypes.c_char)))
    ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ctypes.c_char_p(entropy), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    # dwFlags = 0x01 (CRYPTPROTECT_UI_FORBIDDEN)
    success = _CRYPT_PROTECT(
        ctypes.byref(in_blob),
        "LAPTOP_AI_CREDENTIAL",
        ctypes.byref(ent_blob),
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not success:
        err_code = ctypes.GetLastError()
        raise DPAPIError(f"Windows DPAPI encryption failed (WinError {err_code}).")

    try:
        ciphertext_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(ciphertext_bytes).decode("ascii")
    finally:
        _LOCAL_FREE(out_blob.pbData)


def decrypt_secret(ciphertext_b64: str, entropy: bytes = APPLICATION_ENTROPY) -> str:
    """
    Decrypt base64-encoded ciphertext using Windows DPAPI under CurrentUser security scope.
    """
    if sys.platform != "win32" or not _CRYPT_UNPROTECT or not _LOCAL_FREE:
        raise DPAPIError("Windows DPAPI is not available on this platform.")

    if not ciphertext_b64:
        raise ValueError("Cannot decrypt empty ciphertext.")

    try:
        cipher_bytes = base64.b64decode(ciphertext_b64.encode("ascii"))
    except Exception as e:
        raise DPAPIError(f"Malformed ciphertext encoding: {e}")

    in_blob = DATA_BLOB(len(cipher_bytes), ctypes.cast(ctypes.c_char_p(cipher_bytes), ctypes.POINTER(ctypes.c_char)))
    ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ctypes.c_char_p(entropy), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    success = _CRYPT_UNPROTECT(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(ent_blob),
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not success:
        err_code = ctypes.GetLastError()
        raise DPAPIError(f"Windows DPAPI decryption failed (WinError {err_code}). Check user context or data integrity.")

    try:
        plaintext_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return plaintext_bytes.decode("utf-8")
    finally:
        _LOCAL_FREE(out_blob.pbData)


# -------------------------------------------------------------
# CREDENTIAL MASKING & FINGERPRINTING
# -------------------------------------------------------------
def compute_fingerprint(api_key: str) -> str:
    """Compute deterministic SHA-256 fingerprint for duplicate detection without storing plaintext."""
    clean = api_key.strip()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def mask_api_key(api_key: str) -> str:
    """
    Format a safe masked identifier such as 'gsk_••••abcd' or 'AIza••••1234'.
    Never reveals the complete secret.
    """
    key = api_key.strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "••••" + key[-2:]

    prefix = ""
    for p in ("gsk_", "sk-or-v1-", "sk-or-", "sk-", "AIza"):
        if key.startswith(p):
            prefix = p
            break

    suffix = key[-4:]
    return f"{prefix}••••{suffix}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -------------------------------------------------------------
# CREDENTIAL MANAGER ENGINE
# -------------------------------------------------------------
class CredentialManager:
    """
    Manages multi-key credential lifecycle, automatic rotation, DPAPI encryption,
    and provider error classification for Google Gemini, Groq, and OpenRouter.
    """

    @classmethod
    def add_credential(
        cls,
        provider: str,
        key_name: str,
        api_key: str,
        priority: int = 1,
        is_primary: bool = False,
        quota_scope: str = "",
    ) -> dict:
        """Add a new encrypted credential for a provider."""
        p = provider.lower().strip()
        if p not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'. Must be one of: {SUPPORTED_PROVIDERS}")

        clean_key = api_key.strip()
        if not clean_key or len(clean_key) < 8:
            raise ValueError("API key is too short or empty.")

        name = key_name.strip() or f"{p.capitalize()} Key"
        fingerprint = compute_fingerprint(clean_key)
        masked = mask_api_key(clean_key)
        encrypted = encrypt_secret(clean_key)
        cred_id = f"cred_{p}_{uuid.uuid4().hex[:10]}"
        now = utc_now_iso()

        with conn() as c:
            # Check for duplicate key under the same provider
            existing = c.execute(
                "SELECT id, key_name FROM provider_credentials WHERE provider=? AND key_fingerprint=?",
                (p, fingerprint),
            ).fetchone()
            if existing:
                raise ValueError(f"This API key is already configured under {p.capitalize()} as '{existing['key_name']}'.")

            # Check if this is the first enabled key for the provider
            enabled_count = c.execute(
                "SELECT COUNT(*) FROM provider_credentials WHERE provider=? AND enabled=1",
                (p,),
            ).fetchone()[0]

            should_be_primary = is_primary or (enabled_count == 0)

            if should_be_primary:
                c.execute(
                    "UPDATE provider_credentials SET is_primary=0, updated_at=? WHERE provider=?",
                    (now, p),
                )

            c.execute(
                """
                INSERT INTO provider_credentials (
                    id, provider, key_name, encrypted_key, key_fingerprint, masked_key,
                    priority, is_primary, enabled, status, quota_scope, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?)
                """,
                (
                    cred_id,
                    p,
                    name,
                    encrypted,
                    fingerprint,
                    masked,
                    max(1, int(priority)),
                    1 if should_be_primary else 0,
                    quota_scope.strip() or None,
                    now,
                    now,
                ),
            )

        audit("credential.added", f"Added {p} credential '{name}' ({masked}), primary={should_be_primary}")
        logger.info("Added new %s credential '%s' (%s)", p, name, masked)
        return cls.get_credential_metadata(cred_id)

    @classmethod
    def get_credential_metadata(cls, credential_id: str) -> dict | None:
        """Retrieve credential public metadata (never exposes encrypted or decrypted keys)."""
        with conn() as c:
            row = c.execute(
                """
                SELECT id, provider, key_name, key_fingerprint, masked_key, priority,
                       is_primary, enabled, status, last_used_at, last_success_at,
                       last_error_at, consecutive_failures, cooldown_until, last_error_code,
                       quota_scope, created_at, updated_at
                FROM provider_credentials
                WHERE id=?
                """,
                (credential_id,),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    @classmethod
    def list_credentials(cls, provider: str | None = None) -> list[dict]:
        """List public metadata for all credentials or filtered by provider."""
        with conn() as c:
            query = """
                SELECT id, provider, key_name, key_fingerprint, masked_key, priority,
                       is_primary, enabled, status, last_used_at, last_success_at,
                       last_error_at, consecutive_failures, cooldown_until, last_error_code,
                       quota_scope, created_at, updated_at
                FROM provider_credentials
            """
            params = []
            if provider:
                query += " WHERE provider=?"
                params.append(provider.lower().strip())

            query += " ORDER BY provider ASC, is_primary DESC, priority ASC, created_at ASC"
            rows = c.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    @classmethod
    def update_credential(
        cls,
        credential_id: str,
        key_name: str | None = None,
        priority: int | None = None,
        quota_scope: str | None = None,
    ) -> dict:
        """Update metadata for an existing credential."""
        meta = cls.get_credential_metadata(credential_id)
        if not meta:
            raise ValueError(f"Credential '{credential_id}' not found.")

        now = utc_now_iso()
        updates = ["updated_at = ?"]
        params = [now]

        if key_name is not None and key_name.strip():
            updates.append("key_name = ?")
            params.append(key_name.strip())

        if priority is not None:
            updates.append("priority = ?")
            params.append(max(1, int(priority)))

        if quota_scope is not None:
            updates.append("quota_scope = ?")
            params.append(quota_scope.strip() or None)

        params.append(credential_id)
        with conn() as c:
            c.execute(f"UPDATE provider_credentials SET {', '.join(updates)} WHERE id = ?", params)

        audit("credential.updated", f"Updated credential {credential_id}")
        return cls.get_credential_metadata(credential_id)

    @classmethod
    def set_primary(cls, credential_id: str) -> dict:
        """Designate a credential as the primary key for its provider."""
        meta = cls.get_credential_metadata(credential_id)
        if not meta:
            raise ValueError(f"Credential '{credential_id}' not found.")

        p = meta["provider"]
        now = utc_now_iso()

        with conn() as c:
            # Demote existing primary keys for this provider
            c.execute("UPDATE provider_credentials SET is_primary = 0, updated_at = ? WHERE provider = ?", (now, p))
            # Promote this key and ensure it is enabled
            c.execute(
                "UPDATE provider_credentials SET is_primary = 1, enabled = 1, updated_at = ? WHERE id = ?",
                (now, credential_id),
            )

        audit("credential.set_primary", f"Set {credential_id} as primary for {p}")
        return cls.get_credential_metadata(credential_id)

    @classmethod
    def enable_credential(cls, credential_id: str) -> dict:
        """Enable a credential. If no primary exists for the provider, make this primary."""
        meta = cls.get_credential_metadata(credential_id)
        if not meta:
            raise ValueError(f"Credential '{credential_id}' not found.")

        p = meta["provider"]
        now = utc_now_iso()

        with conn() as c:
            primary_exists = c.execute(
                "SELECT COUNT(*) FROM provider_credentials WHERE provider=? AND is_primary=1 AND enabled=1",
                (p,),
            ).fetchone()[0]

            should_be_primary = primary_exists == 0

            c.execute(
                """
                UPDATE provider_credentials
                SET enabled = 1, status = 'active', is_primary = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if should_be_primary else meta["is_primary"], now, credential_id),
            )

        audit("credential.enabled", f"Enabled {credential_id} (primary={should_be_primary})")
        return cls.get_credential_metadata(credential_id)

    @classmethod
    def disable_credential(cls, credential_id: str) -> dict:
        """Disable a credential. If it was primary, promote next highest-priority enabled key."""
        meta = cls.get_credential_metadata(credential_id)
        if not meta:
            raise ValueError(f"Credential '{credential_id}' not found.")

        p = meta["provider"]
        was_primary = bool(meta["is_primary"])
        now = utc_now_iso()

        with conn() as c:
            c.execute(
                "UPDATE provider_credentials SET enabled = 0, is_primary = 0, updated_at = ? WHERE id = ?",
                (now, credential_id),
            )

            # If it was primary, find the next eligible enabled key to promote
            if was_primary:
                next_key = c.execute(
                    """
                    SELECT id FROM provider_credentials
                    WHERE provider=? AND enabled=1 AND id != ?
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    """,
                    (p, credential_id),
                ).fetchone()
                if next_key:
                    c.execute(
                        "UPDATE provider_credentials SET is_primary = 1, updated_at = ? WHERE id = ?",
                        (now, next_key["id"]),
                    )

        audit("credential.disabled", f"Disabled {credential_id} (was_primary={was_primary})")
        return cls.get_credential_metadata(credential_id)

    @classmethod
    def delete_credential(cls, credential_id: str) -> dict:
        """Securely remove a credential from SQLite. Promotes new primary if needed."""
        meta = cls.get_credential_metadata(credential_id)
        if not meta:
            raise ValueError(f"Credential '{credential_id}' not found.")

        p = meta["provider"]
        was_primary = bool(meta["is_primary"])
        now = utc_now_iso()

        with conn() as c:
            c.execute("DELETE FROM provider_credentials WHERE id = ?", (credential_id,))

            # Promote next key if primary was deleted
            if was_primary:
                next_key = c.execute(
                    """
                    SELECT id FROM provider_credentials
                    WHERE provider=? AND enabled=1
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    """,
                    (p,),
                ).fetchone()
                if next_key:
                    c.execute(
                        "UPDATE provider_credentials SET is_primary = 1, updated_at = ? WHERE id = ?",
                        (now, next_key["id"]),
                    )

        audit("credential.deleted", f"Deleted {credential_id} from {p} (was_primary={was_primary})")
        return {"id": credential_id, "deleted": True, "provider": p}

    @classmethod
    def reorder_credentials(cls, provider: str, ordered_ids: list[str]) -> list[dict]:
        """Update priorities based on an ordered list of credential IDs."""
        p = provider.lower().strip()
        now = utc_now_iso()
        with conn() as c:
            for idx, cid in enumerate(ordered_ids):
                c.execute(
                    "UPDATE provider_credentials SET priority = ?, updated_at = ? WHERE id = ? AND provider = ?",
                    (idx + 1, now, cid, p),
                )
        audit("credential.reordered", f"Reordered credentials for {p}")
        return cls.list_credentials(p)

    # -------------------------------------------------------------
    # AUTOMATIC ELIGIBLE KEY SELECTION
    # -------------------------------------------------------------
    @classmethod
    def get_eligible_credential(
        cls,
        provider: str,
        exclude_ids: list[str] | None = None,
    ) -> Tuple[str, str] | None:
        """
        Select an eligible credential for making an inference request.
        Returns (credential_id, decrypted_key) or None if no keys eligible.
        
        Selection order:
        1. User-selected primary key (if not excluded and not in cooldown)
        2. Other enabled keys ordered by priority ASC, consecutive_failures ASC
        3. Excludes keys in active cooldown or marked 'invalid'
        4. Excludes keys matching rate-limited quota scopes
        5. Falls back to environment variable if no DB keys are configured
        """
        p = provider.lower().strip()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        exclude = set(exclude_ids or [])

        with conn() as c:
            # 1. Check active quota scope cooldowns
            cooldown_scopes = set()
            scope_rows = c.execute(
                """
                SELECT DISTINCT quota_scope FROM provider_credentials
                WHERE provider=? AND quota_scope IS NOT NULL AND cooldown_until > ?
                """,
                (p, now_iso),
            ).fetchall()
            for r in scope_rows:
                if r["quota_scope"]:
                    cooldown_scopes.add(r["quota_scope"])

            # 2. Query candidates
            rows = c.execute(
                """
                SELECT id, encrypted_key, is_primary, priority, consecutive_failures,
                       cooldown_until, quota_scope, status
                FROM provider_credentials
                WHERE provider=? AND enabled=1 AND status != 'invalid'
                ORDER BY is_primary DESC, priority ASC, consecutive_failures ASC, last_used_at ASC
                """,
                (p,),
            ).fetchall()

            for row in rows:
                cid = row["id"]
                if cid in exclude:
                    continue

                # Check key-level cooldown
                cd = row["cooldown_until"]
                if cd and cd > now_iso:
                    continue

                # Check shared quota scope cooldown
                q_scope = row["quota_scope"]
                if q_scope and q_scope in cooldown_scopes:
                    continue

                # Candidate found: decrypt via DPAPI internally
                try:
                    decrypted = decrypt_secret(row["encrypted_key"])
                    return (cid, decrypted)
                except Exception as e:
                    logger.error("Failed to decrypt credential %s: %s", cid, e)
                    # Mark corrupted key as invalid
                    c.execute(
                        "UPDATE provider_credentials SET status='invalid', last_error_code='DPAPI_DECRYPT_FAIL' WHERE id=?",
                        (cid,),
                    )
                    continue

        # 3. Environment variable fallback compatibility
        if "env_fallback" not in exclude:
            env_key = {
                "gemini": settings.gemini_api_key,
                "groq": settings.groq_api_key,
                "openrouter": settings.openrouter_api_key,
            }.get(p, "")
            clean_env = env_key.strip("'\" \t\r\n")
            if clean_env:
                return ("env_fallback", clean_env)

        return None

    # -------------------------------------------------------------
    # HEALTH, SUCCESS & FAILURE CLASSIFICATION
    # -------------------------------------------------------------
    @classmethod
    def record_success(cls, credential_id: str, model: str = "", latency_ms: float = 0.0):
        """Record successful inference response."""
        if credential_id == "env_fallback":
            return

        now = utc_now_iso()
        with conn() as c:
            meta = c.execute("SELECT provider FROM provider_credentials WHERE id=?", (credential_id,)).fetchone()
            prov = meta["provider"] if meta else "unknown"

            c.execute(
                """
                UPDATE provider_credentials
                SET last_used_at = ?,
                    last_success_at = ?,
                    consecutive_failures = 0,
                    status = 'active',
                    cooldown_until = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, now, credential_id),
            )

            c.execute(
                """
                INSERT INTO provider_telemetry (provider, credential_id, event_type, model, latency_ms)
                VALUES (?, ?, 'request_success', ?, ?)
                """,
                (prov, credential_id, model, latency_ms),
            )

    @classmethod
    def record_failure(
        cls,
        credential_id: str,
        error_code: str | int = "0",
        wait_seconds: float = 0.0,
        is_auth_failure: bool = False,
        quota_scope_cooldown: bool = False,
        model: str = "",
        error_message: str = "",
        cooldown_seconds: float | None = None,
        quota_scope: str | None = None,
    ):
        """
        Record provider failure with intelligent error classification.
        - HTTP 401: mark invalid; requires user intervention
        - HTTP 429: set cooldown; propagate to quota scope if shared
        - HTTP 5xx / timeout: bounded retry, cooldown after consecutive failures
        """
        if credential_id == "env_fallback":
            return

        if cooldown_seconds is not None:
            wait_seconds = cooldown_seconds
        error_code = str(error_code)

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        redacted_msg = sanitize_sensitive_strings(error_message)[:500]

        with conn() as c:
            row = c.execute(
                "SELECT provider, quota_scope, consecutive_failures FROM provider_credentials WHERE id=?",
                (credential_id,),
            ).fetchone()
            if not row:
                return

            prov = row["provider"]
            q_scope = quota_scope or row["quota_scope"]
            curr_fail = (row["consecutive_failures"] or 0) + 1

            new_status = "active"
            cd_until = None

            if is_auth_failure or error_code == "401":
                new_status = "invalid"
                event_type = "auth_failure_401"
            elif error_code == "429":
                new_status = "cooldown"
                event_type = "rate_limit_429"
                safe_wait = max(wait_seconds, 2.0)
                cd_until = (now + timedelta(seconds=safe_wait)).isoformat()

                # If quota is shared across organization or project, put entire scope into cooldown
                if (quota_scope_cooldown or quota_scope is not None) and q_scope:
                    c.execute(
                        """
                        UPDATE provider_credentials
                        SET cooldown_until = ?, status = 'cooldown', updated_at = ?
                        WHERE provider = ? AND quota_scope = ? AND status != 'invalid'
                        """,
                        (cd_until, now_iso, prov, q_scope),
                    )
            elif error_code.startswith("5") or "timeout" in error_code.lower():
                event_type = "error_5xx" if error_code.startswith("5") else "network_timeout"
                if curr_fail >= 3:
                    new_status = "cooldown"
                    cd_until = (now + timedelta(seconds=15.0)).isoformat()
            else:
                event_type = f"error_{error_code}"

            c.execute(
                """
                UPDATE provider_credentials
                SET last_used_at = ?,
                    last_error_at = ?,
                    last_error_code = ?,
                    consecutive_failures = ?,
                    status = ?,
                    cooldown_until = COALESCE(?, cooldown_until),
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso, now_iso, error_code, curr_fail, new_status, cd_until, now_iso, credential_id),
            )

            c.execute(
                """
                INSERT INTO provider_telemetry (provider, credential_id, event_type, model, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (prov, credential_id, event_type, model, redacted_msg),
            )

    # -------------------------------------------------------------
    # LIGHTWEIGHT CONNECTION TESTING
    # -------------------------------------------------------------
    @classmethod
    async def test_credential(cls, credential_id: str) -> dict:
        """
        Perform lightweight non-inference connection test.
        Distinguishes valid, invalid (401), rate-limited (429), and provider offline states.
        Does not consume generative tokens.
        """
        with conn() as c:
            row = c.execute("SELECT provider, encrypted_key FROM provider_credentials WHERE id=?", (credential_id,)).fetchone()
            if not row:
                raise ValueError(f"Credential '{credential_id}' not found.")
            prov = row["provider"]
            enc_key = row["encrypted_key"]

        try:
            api_key = decrypt_secret(enc_key)
        except Exception as e:
            return {
                "success": False,
                "status": "invalid",
                "error": f"Decryption failed: {e}",
                "latency_ms": 0.0,
            }

        return await cls.test_raw_key(prov, api_key, credential_id=credential_id)

    @classmethod
    async def test_raw_key(cls, provider: str, api_key: str, credential_id: str | None = None) -> dict:
        """Test a raw unpersisted or persisted API key using lightweight metadata endpoints."""
        p = provider.lower().strip()
        t0 = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if p == "groq":
                    url = "https://api.groq.com/openai/v1/models"
                    headers = {"Authorization": f"Bearer {api_key}"}
                    r = await client.get(url, headers=headers)
                elif p == "openrouter":
                    url = "https://openrouter.ai/api/v1/auth/key"
                    headers = {"Authorization": f"Bearer {api_key}"}
                    r = await client.get(url, headers=headers)
                elif p == "gemini":
                    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                    r = await client.get(url)
                else:
                    return {"success": False, "status": "invalid", "error": f"Unsupported provider: {provider}"}

            latency_ms = round((time.perf_counter() - t0) * 1000, 2)

            if r.status_code == 200:
                models_found = []
                data = {}
                try:
                    data = r.json()
                    if "data" in data and isinstance(data["data"], list):
                        models_found = [m.get("id", "") for m in data["data"][:5]]
                    elif "models" in data and isinstance(data["models"], list):
                        models_found = [m.get("name", "").replace("models/", "") for m in data["models"][:5]]
                except Exception:
                    pass

                if credential_id:
                    cls.record_success(credential_id, latency_ms=latency_ms)

                return {
                    "ok": True,
                    "success": True,
                    "status": "valid",
                    "latency_ms": latency_ms,
                    "provider": p,
                    "models_sample": models_found,
                    "tested_at": utc_now_iso(),
                }

            elif r.status_code == 401 or (p == "gemini" and r.status_code in (400, 403)):
                err_text = sanitize_sensitive_strings(r.text)
                if credential_id:
                    cls.record_failure(credential_id, "401", is_auth_failure=True, error_message=err_text)
                return {
                    "ok": False,
                    "success": False,
                    "status": "invalid",
                    "latency_ms": latency_ms,
                    "error": "Authentication failed: API key was rejected by provider (HTTP 401/403).",
                    "tested_at": utc_now_iso(),
                }

            elif r.status_code == 429:
                if credential_id:
                    cls.record_failure(credential_id, "429", wait_seconds=5.0, error_message=r.text)
                return {
                    "ok": False,
                    "success": False,
                    "status": "quota_exhausted",
                    "latency_ms": latency_ms,
                    "error": "Rate limit / quota exhausted on provider (HTTP 429).",
                    "tested_at": utc_now_iso(),
                }

            else:
                if credential_id:
                    cls.record_failure(credential_id, str(r.status_code), error_message=r.text)
                return {
                    "ok": False,
                    "success": False,
                    "status": "provider_unavailable",
                    "latency_ms": latency_ms,
                    "error": f"Provider responded with error HTTP {r.status_code}.",
                    "tested_at": utc_now_iso(),
                }

        except httpx.TimeoutException:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            if credential_id:
                cls.record_failure(credential_id, "TIMEOUT", error_message="Network request timed out.")
            return {
                "ok": False,
                "success": False,
                "status": "network_error",
                "latency_ms": latency_ms,
                "error": "Network timeout: could not reach provider endpoint.",
                "tested_at": utc_now_iso(),
            }
        except Exception as e:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            if credential_id:
                cls.record_failure(credential_id, "CONN_ERROR", error_message=str(e))
            return {
                "ok": False,
                "success": False,
                "status": "network_error",
                "latency_ms": latency_ms,
                "error": f"Connection error: {sanitize_sensitive_strings(str(e))}",
                "tested_at": utc_now_iso(),
            }

    # -------------------------------------------------------------
    # ENVIRONMENT VARIABLE IMPORT / MIGRATION
    # -------------------------------------------------------------
    @classmethod
    def import_env_credentials(cls) -> dict:
        """
        Detect environment variable credentials in settings (GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY)
        and migrate them into the encrypted database store if not already present.
        """
        env_map = {
            "gemini": settings.gemini_api_key,
            "groq": settings.groq_api_key,
            "openrouter": settings.openrouter_api_key,
        }
        imported = []
        skipped = []

        for prov, raw_key in env_map.items():
            clean = raw_key.strip("'\" \t\r\n")
            if not clean:
                continue

            fp = compute_fingerprint(clean)
            with conn() as c:
                exists = c.execute(
                    "SELECT id, key_name FROM provider_credentials WHERE provider=? AND key_fingerprint=?",
                    (prov, fp),
                ).fetchone()

            if exists:
                skipped.append({"provider": prov, "reason": "already_exists", "id": exists["id"]})
                continue

            try:
                rec = cls.add_credential(
                    provider=prov,
                    key_name=f"Imported {prov.capitalize()} Key (Env)",
                    api_key=clean,
                    priority=1,
                    is_primary=True,
                )
                imported.append(rec)
            except Exception as e:
                logger.warning("Could not import env credential for %s: %s", prov, e)

        return {"imported": imported, "skipped": skipped, "count": len(imported)}

    # -------------------------------------------------------------
    # AGGREGATED HEALTH & USAGE DASHBOARD METRICS
    # -------------------------------------------------------------
    @classmethod
    def get_health_metrics(cls, provider: str | None = None) -> dict:
        """Return comprehensive health metrics for providers and credentials."""
        now_iso = utc_now_iso()
        metrics: dict[str, Any] = {
            "providers": {},
            "total_keys": 0,
            "active_keys": 0,
            "cooldown_keys": 0,
            "invalid_keys": 0,
            "telemetry": {},
            "note": "Locally measured request telemetry. Does not reflect external provider quota exhaustion unless reported via HTTP 429.",
        }

        with conn() as c:
            for p in SUPPORTED_PROVIDERS:
                creds = c.execute(
                    """
                    SELECT id, key_name, masked_key, priority, is_primary, enabled,
                           status, consecutive_failures, cooldown_until, last_used_at,
                           last_success_at, last_error_at, last_error_code, quota_scope
                    FROM provider_credentials
                    WHERE provider=?
                    ORDER BY is_primary DESC, priority ASC, created_at ASC
                    """,
                    (p,),
                ).fetchall()

                p_creds = [dict(r) for r in creds]
                p_active = sum(1 for r in p_creds if r["enabled"] and r["status"] == "active")
                p_cooldown = sum(1 for r in p_creds if r["enabled"] and r["status"] == "cooldown")
                p_invalid = sum(1 for r in p_creds if r["status"] == "invalid")
                primary_key = next((r for r in p_creds if r["is_primary"]), None)

                # Check if environment fallback is available
                env_key = {
                    "gemini": settings.gemini_api_key,
                    "groq": settings.groq_api_key,
                    "openrouter": settings.openrouter_api_key,
                }.get(p, "").strip("'\" \t\r\n")

                # Telemetry stats for last 24h
                telem_rows = c.execute(
                    """
                    SELECT event_type, COUNT(*) as cnt
                    FROM provider_telemetry
                    WHERE provider=?
                    GROUP BY event_type
                    """,
                    (p,),
                ).fetchall()
                event_counts = {r["event_type"]: r["cnt"] for r in telem_rows}
                total_reqs = sum(event_counts.values())

                metrics["providers"][p] = {
                    "configured_keys_count": len(p_creds),
                    "active_keys_count": p_active,
                    "cooldown_keys_count": p_cooldown,
                    "invalid_keys_count": p_invalid,
                    "primary_key": primary_key,
                    "credentials": p_creds,
                    "env_fallback_available": bool(env_key),
                    "requests_total": total_reqs,
                    "requests_success": event_counts.get("request_success", 0),
                    "rate_limits_429": event_counts.get("rate_limit_429", 0),
                    "auth_failures_401": event_counts.get("auth_failure_401", 0),
                    "server_errors_5xx": event_counts.get("error_5xx", 0),
                }

                metrics["total_keys"] += len(p_creds)
                metrics["active_keys"] += p_active
                metrics["cooldown_keys"] += p_cooldown
                metrics["invalid_keys"] += p_invalid

        total_requests = sum(p["requests_total"] for p in metrics["providers"].values())
        total_successes = sum(p["requests_success"] for p in metrics["providers"].values())
        total_429s = sum(p["rate_limits_429"] for p in metrics["providers"].values())
        total_401s = sum(p["auth_failures_401"] for p in metrics["providers"].values())
        total_5xxs = sum(p["server_errors_5xx"] for p in metrics["providers"].values())

        metrics["summary"] = {
            "total_credentials": metrics["total_keys"],
            "active_credentials": metrics["active_keys"],
            "cooldown_credentials": metrics["cooldown_keys"],
            "invalid_credentials": metrics["invalid_keys"],
            "total_requests": total_requests,
            "total_successes": total_successes,
            "total_rate_limits": total_429s,
            "total_auth_failures": total_401s,
            "total_server_errors": total_5xxs,
            "success_rate_percent": round((total_successes / total_requests * 100), 1) if total_requests else 100.0,
        }

        if provider and provider in metrics["providers"]:
            metrics["provider"] = metrics["providers"][provider]

        return metrics
