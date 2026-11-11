from __future__ import annotations
import asyncio
import json
import logging
import random
import uuid
import httpx
from pydantic import BaseModel
from app.core.config import settings
from app.core.security import audit
from app.core.token_budget import parse_rate_limit_reset, PROVIDER_LIMITS

logger = logging.getLogger("laptop_ai.providers")


class RateLimitError(RuntimeError):
    def __init__(self, provider: str, model: str, wait_seconds: float, message: str):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.wait_seconds = wait_seconds


def get_key(provider: str) -> str:
    key = {
        "gemini": settings.gemini_api_key,
        "groq": settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
    }.get(provider, "")
    return key.strip("'\" \t\r\n")


def status() -> dict:
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
    """Execute a single conversational turn supporting tools across all 3 providers."""
    key = get_key(provider)
    if not key:
        raise RuntimeError(f"{provider.capitalize()} API key is not configured in backend/.env")

    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider == "gemini":
            return await _gemini_turn(client, model, key, messages, tools, system_instruction)
        elif provider in ("groq", "openrouter"):
            return await _openai_compatible_turn(client, provider, model, key, messages, tools, system_instruction)
        else:
            raise ValueError(f"Unsupported provider: '{provider}'")


async def _openai_compatible_turn(
    client: httpx.AsyncClient,
    provider: str,
    model: str,
    key: str,
    messages: list[dict],
    tools: list[dict] | None,
    system_instruction: str,
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
        if r.status_code == 429:
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass

            wait_sec = parse_rate_limit_reset(r.headers, r.text)
            if attempt < max_retries and wait_sec <= 10.0:
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
                raise RateLimitError(provider=provider, model=model, wait_seconds=wait_sec, message=err_msg)

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
        if r.status_code == 429:
            err_msg = r.text
            try:
                err_json = r.json()
                if "error" in err_json and isinstance(err_json["error"], dict):
                    err_msg = err_json["error"].get("message", r.text)
            except Exception:
                pass

            wait_sec = parse_rate_limit_reset(r.headers, r.text)
            if attempt < max_retries and wait_sec <= 10.0:
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
                raise RateLimitError(provider="gemini", model=clean_model, wait_seconds=wait_sec, message=err_msg)

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
