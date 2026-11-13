from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import time
import json
import logging
import random
import uuid
import httpx
from pydantic import BaseModel
from app.core.config import settings
from app.core.security import audit
from app.core.token_budget import parse_rate_limit_reset, PROVIDER_LIMITS, estimate_tokens
from app.core.credential_manager import CredentialManager

logger = logging.getLogger("laptop_ai.providers")


class RateLimitError(RuntimeError):
    def __init__(self, provider: str, model: str, wait_seconds: float, message: str):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.wait_seconds = wait_seconds


class AuthError(RuntimeError):
    """Raised when an API key fails authentication (HTTP 401)."""
    def __init__(self, provider: str, message: str):
        super().__init__(message)
        self.provider = provider


class KeyRateLimitError(RateLimitError):
    """Raised when a specific API key encounters a 429 rate limit."""
    def __init__(self, provider: str, model: str, wait_seconds: float, is_shared_quota: bool, message: str):
        super().__init__(provider=provider, model=model, wait_seconds=wait_seconds, message=message)
        self.is_shared_quota = is_shared_quota


class ProviderServerError(RuntimeError):
    """Raised when provider returns HTTP 5xx or server-side error."""
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def get_key(provider: str) -> str:
    """Get active API key for provider from CredentialManager, falling back to environment settings."""
    try:
        from app.core.credential_manager import CredentialManager
        cred = CredentialManager.get_eligible_credential(provider)
        if cred:
            return cred[1]
    except Exception:
        pass

    key = {
        "gemini": settings.gemini_api_key,
        "groq": settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
    }.get(provider, "")
    return key.strip("'\" \t\r\n")


def status() -> dict:
    st = {}
    try:
        from app.core.credential_manager import CredentialManager
        for k in ["gemini", "groq", "openrouter"]:
            active_key = get_key(k)
            creds = CredentialManager.list_credentials(k)
            primary = next((c for c in creds if c["is_primary"]), None)
            active_count = sum(1 for c in creds if c["enabled"] and c["status"] == "active")
            st[k] = {
                "configured": bool(active_key),
                "masked_key": primary["masked_key"] if primary else ("••••" + active_key[-4:] if len(active_key) >= 4 else ""),
                "configured_keys_count": len(creds),
                "active_keys_count": active_count,
                "has_backup_keys": active_count > 1,
                "primary_label": primary["key_name"] if primary else ("Environment Variable" if active_key else None),
            }
        return st
    except Exception:
        return {
            k: {
                "configured": bool(get_key(k)),
                "masked_key": ("••••" + get_key(k)[-4:] if len(get_key(k)) >= 4 else ""),
            }
            for k in ["gemini", "groq", "openrouter"]
        }


def is_vision_capable(provider: str, model: str) -> bool:
    """Detect whether the selected model and provider support image/visual inputs."""
    p = provider.lower().strip()
    m = model.lower().strip()
    if p == "gemini":
        return True
    if p == "groq":
        return any(v in m for v in ("vision", "llama-3.2-11b-vision", "llama-3.2-90b-vision"))
    if p == "openrouter":
        return any(v in m for v in ("vision", "vl", "4o", "gemini", "claude", "pixtral", "minicpm"))
    return False


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict


class TurnResult(BaseModel):
    content: str
    tool_calls: list[ToolCall] = []
    raw_message: dict | None = None


async def complete(provider: str, model: str, messages: list[dict]) -> str:
    """Basic text completion for backward compatibility."""
    res = await chat_turn(provider, model, messages, tools=None)
    return res.content


async def chat_turn(
    provider: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    system_instruction: str = "",
    timeout: float = 60.0,
) -> TurnResult:
    """Execute a single conversational turn with automatic multi-key rotation and provider error classification."""
    p = provider.lower().strip()
    if p not in ("gemini", "groq", "openrouter"):
        raise ValueError(f"Unsupported provider: '{provider}'")

    from app.core.credential_manager import CredentialManager
    from app.core.inference_orchestrator import admission_controller, circuit_breaker

    est_tokens = estimate_tokens(messages)
    can_admit, admit_reason = await admission_controller.can_admit(p, estimated_tokens=est_tokens)
    if not can_admit:
        raise RateLimitError(provider=p, model=model, wait_seconds=30.0, message=admit_reason)

    await admission_controller.acquire_reservation(p, estimated_tokens=est_tokens)

    tried_credential_ids: list[str] = []
    max_key_attempts = 4

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            while len(tried_credential_ids) < max_key_attempts:
                cred_selection = CredentialManager.get_eligible_credential(p, exclude_ids=tried_credential_ids)
                if not cred_selection:
                    if not tried_credential_ids:
                        prov_creds = CredentialManager.list_credentials(p)
                        if prov_creds:
                            now_iso = datetime.now(timezone.utc).isoformat()
                            has_cooldown = any(
                                (c.get("cooldown_until") and c["cooldown_until"] > now_iso) or c.get("status") == "cooldown"
                                for c in prov_creds
                            )
                            if has_cooldown:
                                raise RateLimitError(
                                    provider=p,
                                    model=model,
                                    wait_seconds=30.0,
                                    message=f"All configured credentials for {provider.capitalize()} are temporarily in cooldown.",
                                )
                        raise RuntimeError(f"{provider.capitalize()} API key is not configured in backend/.env or credential store.")
                    break

                cred_id, key = cred_selection
                t0 = time.perf_counter()

                try:
                    if p == "gemini":
                        try:
                            res = await _gemini_turn(client, model, key, messages, tools, system_instruction, cred_id=cred_id)
                        except TypeError as te:
                            if "unexpected keyword argument 'cred_id'" in str(te):
                                res = await _gemini_turn(client, model, key, messages, tools, system_instruction)
                            else:
                                raise
                    else:
                        try:
                            res = await _openai_compatible_turn(client, p, model, key, messages, tools, system_instruction, cred_id=cred_id)
                        except TypeError as te:
                            if "unexpected keyword argument 'cred_id'" in str(te):
                                res = await _openai_compatible_turn(client, p, model, key, messages, tools, system_instruction)
                            else:
                                raise

                    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                    CredentialManager.record_success(cred_id, model=model, latency_ms=latency_ms)
                    await admission_controller.release_reservation(p, estimated_tokens=est_tokens, success=True)
                    return res

                except AuthError as e:
                    logger.warning("Provider %s key '%s' failed authentication (401). Rotating to next key...", p, cred_id)
                    audit("credential.auth_failed_rotation", f"{p} {cred_id} failed 401, rotating to backup")
                    CredentialManager.record_failure(cred_id, error_code="401", is_auth_failure=True, model=model, error_message=str(e))
                    tried_credential_ids.append(cred_id)
                    continue

                except KeyRateLimitError as e:
                    wait_sec = e.wait_seconds
                    is_shared = e.is_shared_quota
                    logger.warning(
                        "Provider %s key '%s' rate-limited (429, wait=%.1fs, shared=%s). Evaluating backup keys...",
                        p, cred_id, wait_sec, is_shared
                    )
                    CredentialManager.record_failure(
                        cred_id, error_code="429", wait_seconds=wait_sec,
                        quota_scope_cooldown=is_shared, model=model, error_message=str(e)
                    )
                    tried_credential_ids.append(cred_id)

                    # Check if independent backup key exists that is not in cooldown
                    next_cand = CredentialManager.get_eligible_credential(p, exclude_ids=tried_credential_ids)
                    if next_cand and not is_shared:
                        logger.info("Rotating to backup key '%s' for %s...", next_cand[0], p)
                        audit("credential.rate_limit_rotation", f"{p} rotated from {cred_id} to {next_cand[0]}")
                        continue
                    else:
                        await admission_controller.release_reservation(p, estimated_tokens=est_tokens, success=False, is_rate_limit=True)
                        raise RateLimitError(provider=p, model=model, wait_seconds=wait_sec, message=str(e))

                except ProviderServerError as e:
                    logger.warning("Provider %s key '%s' server error: %s", p, cred_id, e)
                    CredentialManager.record_failure(cred_id, error_code=str(e.status_code), model=model, error_message=str(e))
                    tried_credential_ids.append(cred_id)
                    next_cand = CredentialManager.get_eligible_credential(p, exclude_ids=tried_credential_ids)
                    if next_cand:
                        continue
                    await admission_controller.release_reservation(p, estimated_tokens=est_tokens, success=False, error_code=str(e.status_code))
                    raise RuntimeError(str(e))

                except Exception:
                    await admission_controller.release_reservation(p, estimated_tokens=est_tokens, success=False)
                    raise

        raise RuntimeError(f"All configured credentials for {provider.capitalize()} were exhausted or unavailable.")
    except Exception:
        # Guarantee reservation release if exception escapes
        await admission_controller.release_reservation(p, estimated_tokens=est_tokens, success=False)
        raise


async def _openai_compatible_turn(
    client: httpx.AsyncClient,
    provider: str,
    model: str,
    key: str,
    messages: list[dict],
    tools: list[dict] | None,
    system_instruction: str,
    cred_id: str = "",
) -> TurnResult:
    url = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        headers.update({
            "HTTP-Referer": "http://127.0.0.1:5173",
            "X-Title": "LAPTOP AI",
        })

    formatted_messages = []
    for m in messages:
        if m.get("image_base64"):
            if not is_vision_capable(provider, model):
                raise RuntimeError(
                    f"Model '{model}' on '{provider}' does not support visual/image inputs. "
                    f"Please select Google Gemini (gemini-2.5-flash) or a vision-capable model to analyze images."
                )
            formatted_messages.append({
                "role": m.get("role", "user"),
                "content": [
                    {"type": "text", "text": m.get("content", "")},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{m.get('image_mime', 'image/png')};base64,{m['image_base64']}"
                        },
                    },
                ],
            })
        else:
            formatted_messages.append(m)

    if system_instruction and not any(m.get("role") == "system" for m in formatted_messages):
        formatted_messages.insert(0, {"role": "system", "content": system_instruction})

    max_tokens = PROVIDER_LIMITS.get(provider, {}).get("max_output_tokens", 1024)
    payload: dict = {
        "model": model,
        "messages": formatted_messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    max_retries = settings.max_rate_limit_retries
    data = None

    for attempt in range(max_retries + 1):
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code == 401:
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass
            raise AuthError(provider=provider, message=f"Authentication failed (HTTP 401): {err_msg}")

        if r.status_code == 429:
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass

            wait_sec = parse_rate_limit_reset(r.headers, r.text)
            CredentialManager.record_quota_headers(cred_id, r.headers)
            if attempt < max_retries and wait_sec <= 2.0:
                jitter = random.uniform(0.1, 0.4)
                actual_sleep = wait_sec + jitter
                logger.warning(
                    "Provider %s rate-limited (429). Waiting %.2fs before retry (attempt %d/%d)...",
                    provider, actual_sleep, attempt + 1, max_retries
                )
                audit("provider.rate_limit_backoff", f"{provider} 429: backing off {actual_sleep:.2f}s (attempt {attempt + 1})")
                await asyncio.sleep(actual_sleep)
                continue
            else:
                audit("provider.rate_limit_exhausted", f"{provider} 429 limit reached: {err_msg}")
                is_shared = any(term in err_msg.lower() for term in ("organization", "project", "tier limit", "org_id", "project_quota", "account limit"))
                raise KeyRateLimitError(provider=provider, model=model, wait_seconds=wait_sec, is_shared_quota=is_shared, message=err_msg)

        if r.status_code in (500, 502, 503, 504):
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass
            raise ProviderServerError(status_code=r.status_code, message=f"{provider.capitalize()} server error ({r.status_code}): {err_msg}")

        if r.status_code != 200:
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass
            raise RuntimeError(f"{provider.capitalize()} API error ({r.status_code}): {err_msg}")

        data = r.json()
        CredentialManager.record_quota_headers(cred_id, r.headers)
        break

    if not data or "choices" not in data or not data["choices"]:
        raise RuntimeError(f"{provider.capitalize()} returned empty completion choices")

    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""

    tool_calls: list[ToolCall] = []
    if "tool_calls" in msg and msg["tool_calls"]:
        for tc in msg["tool_calls"]:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            else:
                args = raw_args or {}
            tool_calls.append(ToolCall(
                id=tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                name=fn.get("name", ""),
                args=args,
            ))

    return TurnResult(content=content, tool_calls=tool_calls, raw_message=msg)


async def _gemini_turn(
    client: httpx.AsyncClient,
    model: str,
    key: str,
    contents: list[dict],
    tools: list[dict] | None,
    system_instruction: str,
    cred_id: str = "",
) -> TurnResult:
    # Use model name directly (e.g. gemini-2.5-flash or gemini-2.0-flash)
    clean_model = model.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={key}"

    # Prepare contents in Gemini format
    gemini_contents = []
    for item in contents:
        # If already formatted as a Gemini content object (has 'parts' and 'role')
        if "parts" in item and "role" in item:
            gemini_contents.append(item)
        else:
            role = "model" if item.get("role") == "assistant" else "user"
            parts = [{"text": item.get("content", "")}]
            if item.get("image_base64"):
                parts.append({
                    "inline_data": {
                        "mime_type": item.get("image_mime", "image/png"),
                        "data": item["image_base64"],
                    }
                })
            gemini_contents.append({
                "role": role,
                "parts": parts,
            })

    payload: dict = {
        "contents": gemini_contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if tools:
        payload["tools"] = tools

    max_retries = settings.max_rate_limit_retries
    data = None

    for attempt in range(max_retries + 1):
        r = await client.post(url, json=payload)
        if r.status_code == 401 or (r.status_code in (400, 403) and any(term in r.text for term in ("API_KEY_INVALID", "API key not valid", "PERMISSION_DENIED"))):
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass
            raise AuthError(provider="gemini", message=f"Gemini authentication failed (HTTP {r.status_code}): {err_msg}")

        if r.status_code == 429:
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass

            wait_sec = parse_rate_limit_reset(r.headers, r.text)
            CredentialManager.record_quota_headers(cred_id, r.headers)
            if attempt < max_retries and wait_sec <= 2.0:
                jitter = random.uniform(0.1, 0.4)
                actual_sleep = wait_sec + jitter
                logger.warning(
                    "Gemini rate-limited (429). Waiting %.2fs before retry (attempt %d/%d)...",
                    actual_sleep, attempt + 1, max_retries
                )
                audit("provider.rate_limit_backoff", f"gemini 429: backing off {actual_sleep:.2f}s (attempt {attempt + 1})")
                await asyncio.sleep(actual_sleep)
                continue
            else:
                audit("provider.rate_limit_exhausted", f"gemini 429 limit reached: {err_msg}")
                is_shared = any(term in err_msg.lower() for term in ("project", "quota exceeded for project", "tier limit"))
                raise KeyRateLimitError(provider="gemini", model=clean_model, wait_seconds=wait_sec, is_shared_quota=is_shared, message=err_msg)

        if r.status_code in (500, 502, 503, 504):
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass
            raise ProviderServerError(status_code=r.status_code, message=f"Gemini server error ({r.status_code}): {err_msg}")

        if r.status_code != 200:
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass
            raise RuntimeError(f"Gemini API error ({r.status_code}): {err_msg}")

        data = r.json()
        CredentialManager.record_quota_headers(cred_id, r.headers)
        break

    if not data:
        raise RuntimeError("Gemini returned empty response")
    candidates = data.get("candidates", [])
    if not candidates:
        return TurnResult(content="", tool_calls=[], raw_message=None)

    cand_content = candidates[0].get("content", {})
    parts = cand_content.get("parts", [])

    text_parts = []
    tool_calls: list[ToolCall] = []

    for p in parts:
        if "text" in p and p["text"]:
            text_parts.append(p["text"])
        if "functionCall" in p:
            fc = p["functionCall"]
            call_id = f"gemini_call_{uuid.uuid4().hex[:8]}"
            tool_calls.append(ToolCall(
                id=call_id,
                name=fc.get("name", ""),
                args=fc.get("args", {}) or {},
            ))

    combined_text = "\n".join(text_parts).strip()
    return TurnResult(content=combined_text, tool_calls=tool_calls, raw_message=cand_content)
