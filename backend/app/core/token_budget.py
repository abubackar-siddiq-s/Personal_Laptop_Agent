from __future__ import annotations
import json
import re
from typing import Any

# Provider token limits and context budgets
PROVIDER_LIMITS: dict[str, dict[str, int]] = {
    "groq": {
        "max_context_tokens": 4096,      # Token budget staying safely within Groq TPM limits
        "max_output_tokens": 1024,       # Limits reserved completion tokens against TPM
        "max_tool_chars": 8000,          # Bound tool output: 8,000 chars comfortably fits 30-45 UI elements without clipping
        "max_history_turns": 4,          # Retain up to 4 recent message turns
    },
    "gemini": {
        "max_context_tokens": 64000,     # Generous context (Gemini 2.5 Flash has 1M TPM)
        "max_output_tokens": 2048,
        "max_tool_chars": 16000,
        "max_history_turns": 10,
    },
    "openrouter": {
        "max_context_tokens": 10000,
        "max_output_tokens": 1500,
        "max_tool_chars": 8000,
        "max_history_turns": 6,
    },
}


def estimate_tokens(content: Any) -> int:
    """
    Estimate token count for strings, dicts, lists, or structured messages.
    Uses calibrated ratios: ~3.0 chars/token for JSON/code/schemas, ~3.8 chars/token for prose.
    Adds 4 tokens framing overhead per message object.
    """
    if content is None:
        return 0
    if isinstance(content, (dict, list)):
        raw = json.dumps(content, separators=(",", ":"), default=str)
        return max(1, len(raw) // 3) + 4
    if isinstance(content, str):
        if not content:
            return 0
        # If text looks like JSON, code, or dense structure
        if content.startswith(("{", "[", "http", "data:")) or "\n" in content:
            return max(1, len(content) // 3)
        return max(1, int(len(content) / 3.8))
    return max(1, len(str(content)) // 4)


def parse_rate_limit_reset(headers: Any, error_body: str | dict | None) -> float:
    """
    Extract rate limit reset wait time in seconds from HTTP headers or response body.
    Supports:
      - 'Retry-After' header (integer seconds, float, or HTTP-date)
      - 'x-ratelimit-reset-tokens' / 'x-ratelimit-reset-requests' (e.g. '2.84s', '750ms')
      - Body error text patterns (e.g. 'Please try again in 2.84s', 'try again in 500ms')
    Returns wait seconds (bounded between 0.5s and 15.0s).
    """
    wait_sec: float | None = None

    # 1. Inspect HTTP Headers
    if headers:
        # Check standard Retry-After
        retry_after = None
        if hasattr(headers, "get"):
            retry_after = headers.get("retry-after") or headers.get("Retry-After")
        elif isinstance(headers, dict):
            retry_after = headers.get("retry-after") or headers.get("Retry-After")

        if retry_after:
            try:
                wait_sec = float(str(retry_after).strip())
            except ValueError:
                pass

        # Check Groq-specific reset headers
        if wait_sec is None:
            reset_h = None
            if hasattr(headers, "get"):
                reset_h = headers.get("x-ratelimit-reset-tokens") or headers.get("x-ratelimit-reset-requests")
            elif isinstance(headers, dict):
                reset_h = headers.get("x-ratelimit-reset-tokens") or headers.get("x-ratelimit-reset-requests")

            if reset_h:
                m = re.search(r"(\d+(?:\.\d+)?)\s*(s|ms|m)?", str(reset_h))
                if m:
                    val = float(m.group(1))
                    unit = (m.group(2) or "s").lower()
                    if unit == "ms":
                        wait_sec = val / 1000.0
                    elif unit == "m":
                        wait_sec = val * 60.0
                    else:
                        wait_sec = val

    # 2. Inspect error body text if header not found
    if wait_sec is None and error_body:
        body_str = error_body if isinstance(error_body, str) else json.dumps(error_body)
        m = re.search(r"try again in (\d+(?:\.\d+)?)\s*(s|ms|m)?", body_str, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            unit = (m.group(2) or "s").lower()
            if unit == "ms":
                wait_sec = val / 1000.0
            elif unit == "m":
                wait_sec = val * 60.0
            else:
                wait_sec = val

    if wait_sec is None:
        wait_sec = 2.0  # Safe default if reset window cannot be parsed

    # Bound wait seconds to reasonable range (0.5s to 15.0s)
    return max(0.5, min(wait_sec, 15.0))


def compact_tool_definitions(tools: list[dict], max_tools_tokens: int = 2000) -> list[dict]:
    """
    Minify and streamline tool definitions for token-constrained providers (like Groq).
    Removes verbose repetitive wording and strips empty metadata fields.
    """
    compacted = []
    for t in tools:
        if t.get("type") == "function":
            fn = t.get("function", {})
            desc = fn.get("description", "")
            # Shorten description to first sentence or max 120 chars
            if desc and len(desc) > 120:
                first_sent = desc.split(". ")[0].strip()
                desc = first_sent + "." if not first_sent.endswith(".") else first_sent
                if len(desc) > 120:
                    desc = desc[:117] + "..."

            params = fn.get("parameters", {})
            clean_params: dict[str, Any] = {"type": "object", "properties": {}}
            if "properties" in params and isinstance(params["properties"], dict):
                for p_name, p_spec in params["properties"].items():
                    clean_p = {"type": p_spec.get("type", "string")}
                    if "description" in p_spec:
                        p_desc = p_spec["description"]
                        if len(p_desc) > 80:
                            p_desc = p_desc[:77] + "..."
                        clean_p["description"] = p_desc
                    if "enum" in p_spec:
                        clean_p["enum"] = p_spec["enum"]
                    clean_params["properties"][p_name] = clean_p

            if "required" in params and params["required"]:
                clean_params["required"] = params["required"]

            compacted.append({
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "description": desc,
                    "parameters": clean_params,
                },
            })
        else:
            compacted.append(t)
    return compacted


def compact_history(
    history: list[dict],
    max_tokens: int = 1500,
    max_turns: int = 6,
) -> list[dict]:
    """
    Prune and compact conversation history:
    - Retains only the most recent N turns.
    - Summarizes or truncates oversized prior tool results / dumps.
    - Ensures total token usage stays strictly within budget.
    """
    if not history:
        return []

    recent = history[-max_turns:]
    compacted = []
    for m in recent:
        role = m.get("role", "user")
        content = m.get("content", "")
        if not content:
            continue

        # If previous assistant reply or tool output was huge, compact it
        if role == "assistant" and len(content) > 600:
            content = content[:500] + "\n... [Earlier response compacted for context efficiency]"

        compacted.append({"role": role, "content": content})

    # Check token budget from newest to oldest
    budgeted = []
    curr_tokens = 0
    for m in reversed(compacted):
        m_tok = estimate_tokens(m)
        if curr_tokens + m_tok <= max_tokens:
            budgeted.append(m)
            curr_tokens += m_tok
        else:
            break

    return list(reversed(budgeted))


def filter_relevant_tools(
    tools: list[dict],
    user_prompt: str,
    recent_messages: list[dict] | None = None,
    provider: str = "groq",
) -> list[dict]:
    """
    Select high-signal, relevant tools for the active turn when using token-constrained models.
    For high-capacity models (Gemini), returns all registered tools.
    For Groq, selectively scopes tools to avoid exceeding the strict 8,000 TPM limit.
    """
    if provider.lower().strip() not in ("groq",):
        return tools

    text_corpus = (user_prompt or "").lower()
    if recent_messages:
        for m in recent_messages[-2:]:
            text_corpus += " " + str(m.get("content", "")).lower()

    words = set(re.findall(r"\b[a-zA-Z0-9_.-]+\b", text_corpus))

    browser_keywords = {
        "http", "https", "url", "web", "site", "page", "browser", "search",
        "tab", "click", "fill", "type", "link", "download", "pdf", "html",
        "navigate", "google", "duckduckgo", "button", "screenshot", "scroll"
    }
    desktop_keywords = {
        "window", "windows", "hwnd", "application", "active", "foreground",
        "minimized", "maximized", "dimensions", "title", "focus", "switch",
        "desktop", "screen", "screenshot", "ui", "element", "button", "controls",
        "click", "scroll", "type", "press", "shortcut", "shortcuts", "hotkey", "mouse", "keyboard"
    }
    vision_keywords = {
        "screen", "display", "visual", "vision", "see", "look", "watch",
        "ocr", "text", "read", "button", "find", "locate", "where",
        "compare", "difference", "changed", "change", "region", "error",
        "warning", "dialog", "address", "bar", "what is displayed", "what is on"
    }
    files_keywords = {
        "file", "files", "document", "documents", "pdf", "docx", "doc", "xlsx", "xls",
        "pptx", "ppt", "csv", "txt", "markdown", "md", "json", "xml", "html", "rtf",
        "spreadsheet", "spreadsheets", "excel", "sheets", "summarize", "summary",
        "ask", "compare", "search", "semantic", "index", "duplicate", "duplicates",
        "organize", "cleanup", "quarantine", "extract", "profile"
    }
    assistant_keywords = {
        "assistant", "profile", "preference", "preferences", "goal", "goals", "project",
        "projects", "routine", "routines", "working", "hours", "remind", "reminder", "reminders",
        "snooze", "briefing", "brief", "daily", "today", "overdue", "deadline", "deadlines",
        "monitor", "monitors", "alert", "alerts", "notification", "notifications",
        "prioritize", "priority", "what should i work on", "plan", "morning"
    }
    system_keywords = {
        "cpu", "ram", "memory", "battery", "disk", "hardware", "process",
        "processes", "kill", "terminate", "inspect", "file", "folder",
        "documents", "downloads", "notepad", "calc", "launch",
        "terminal", "diagnostic", "whoami", "ipconfig"
    }
    mcp_keywords = {"mcp", "server", "servers"}
    approval_keywords = {"approval", "approve", "pending", "permission"}

    wants_browser = bool(words & browser_keywords) or any(k in text_corpus for k in ("http://", "https://"))
    wants_desktop = bool(words & desktop_keywords)
    wants_vision = bool(words & vision_keywords) or any(
        k in text_corpus for k in (
            "what is on my screen", "what is displayed", "where is", "find the",
            "locate", "extract text", "compare screenshot", "explain what is happening"
        )
    )
    wants_files = bool(words & files_keywords)
    wants_assistant = bool(words & assistant_keywords) or any(
        k in text_corpus for k in (
            "what should i work on", "daily briefing", "remind me", "my profile",
            "working hours", "set a reminder", "what are my deadlines"
        )
    )
    wants_system = bool(words & system_keywords)
    wants_mcp = bool(words & mcp_keywords)
    wants_approval = bool(words & approval_keywords)

    selected = []
    for t in tools:
        fn_name = t.get("function", {}).get("name", "") if t.get("type") == "function" else t.get("name", "")

        # Always include search if browser is needed
        if fn_name == "browser_search" and wants_browser:
            selected.append(t)
            continue
        if fn_name == "native_mcp_list_servers" and wants_mcp:
            selected.append(t)
            continue
        if fn_name == "native_approvals_check" and wants_approval:
            selected.append(t)
            continue

        # Vision Tools Scoping
        if fn_name.startswith("vision_screen_"):
            if wants_vision or wants_desktop:
                if fn_name == "vision_screen_analyze" and any(k in text_corpus for k in ("what", "display", "screen", "see", "look", "analyze", "describe", "happen", "explain", "using")):
                    selected.append(t)
                    continue
                if fn_name == "vision_screen_extract_text" and any(k in text_corpus for k in ("text", "ocr", "read", "extract", "words", "label")):
                    selected.append(t)
                    continue
                if fn_name == "vision_screen_find_element" and any(k in text_corpus for k in ("find", "locate", "where", "button", "bar", "dialog", "element")):
                    selected.append(t)
                    continue
                if fn_name == "vision_screen_compare" and any(k in text_corpus for k in ("compare", "diff", "difference", "change", "changed", "previous")):
                    selected.append(t)
                    continue
                if fn_name == "vision_screen_describe_region" and any(k in text_corpus for k in ("region", "area", "box", "portion", "part")):
                    selected.append(t)
                    continue
                if wants_vision:
                    selected.append(t)
                    continue

        # Files & Document Intelligence Scoping
        if fn_name.startswith("files_"):
            if wants_files:
                if fn_name == "files_document_extract" and any(k in text_corpus for k in ("extract", "read", "content", "open", "text", "doc", "pdf", "file")):
                    selected.append(t)
                    continue
                if fn_name == "files_document_summarize" and any(k in text_corpus for k in ("summary", "summarize", "key", "points", "takeaways", "overview")):
                    selected.append(t)
                    continue
                if fn_name == "files_document_ask" and any(k in text_corpus for k in ("ask", "question", "what", "where", "how", "citation", "reference")):
                    selected.append(t)
                    continue
                if fn_name == "files_document_compare" and any(k in text_corpus for k in ("compare", "diff", "difference", "versus", "vs")):
                    selected.append(t)
                    continue
                if fn_name in ("files_search_semantic", "files_search_content") and any(k in text_corpus for k in ("search", "find", "locate", "query", "mention")):
                    selected.append(t)
                    continue
                if fn_name in ("files_index_status", "files_index_refresh") and any(k in text_corpus for k in ("index", "refresh", "status", "reindex")):
                    selected.append(t)
                    continue
                if fn_name == "files_spreadsheet_analyze" and any(k in text_corpus for k in ("spreadsheet", "excel", "sheets", "xlsx", "csv", "table", "profile", "formula", "stats")):
                    selected.append(t)
                    continue
                if fn_name == "files_duplicates_find" and any(k in text_corpus for k in ("duplicate", "duplicates", "clone", "wasted")):
                    selected.append(t)
                    continue
                if fn_name in ("files_organize_preview", "files_organize_execute") and any(k in text_corpus for k in ("organize", "cleanup", "quarantine", "move", "large", "old", "empty")):
                    selected.append(t)
                    continue
                selected.append(t)
                continue

        # Proactive Assistant Tools Scoping
        if fn_name.startswith("assistant_") or fn_name.startswith("assistant."):
            if wants_assistant:
                selected.append(t)
                continue

        # Desktop Tools Scoping
        if wants_desktop:
            # Core inspection tools for active window and window telemetry
            if fn_name == "desktop_window_active" and (
                any(k in text_corpus for k in ("active", "current", "foreground", "title", "hwnd", "pid", "dimension", "minimized", "window", "application", "app"))
                or not wants_browser
            ):
                selected.append(t)
                continue
            if fn_name == "desktop_window_list" and any(k in text_corpus for k in ("list", "windows", "open", "all", "running", "visible", "apps", "applications", "switch", "focus")):
                selected.append(t)
                continue
            if fn_name == "desktop_window_focus" and any(k in text_corpus for k in ("focus", "switch", "bring", "activate", "foreground")):
                selected.append(t)
                continue
            if fn_name == "desktop_screen_capture" and any(k in text_corpus for k in ("screen", "screenshot", "capture", "display", "image", "look", "see", "vision")):
                selected.append(t)
                continue
            if fn_name == "desktop_ui_inspect" and any(k in text_corpus for k in ("ui", "element", "inspect", "control", "button", "find", "menu", "tab")):
                selected.append(t)
                continue
            if fn_name == "desktop_mouse_click" and "click" in text_corpus and not wants_browser:
                selected.append(t)
                continue
            if fn_name == "desktop_mouse_scroll" and "scroll" in text_corpus and not wants_browser:
                selected.append(t)
                continue
            if fn_name == "desktop_keyboard_type" and any(k in text_corpus for k in ("type", "write", "input", "enter text")) and not wants_browser:
                selected.append(t)
                continue
            if fn_name == "desktop_keyboard_press" and any(k in text_corpus for k in ("press", "key", "shortcut", "hotkey")) and not wants_browser:
                selected.append(t)
                continue

        if wants_browser and not wants_system and not (wants_desktop and any(k in text_corpus for k in ("window", "windows", "desktop", "hwnd", "active"))):
            # High-priority core browser suite
            core_browser = {
                "browser_open", "browser_navigate", "browser_click", "browser_fill",
                "browser_type", "browser_get_text", "browser_get_links", "browser_get_url",
                "browser_get_title", "browser_screenshot"
            }
            if fn_name in core_browser:
                selected.append(t)
            elif "tab" in text_corpus and fn_name in ("browser_list_tabs", "browser_close_tab", "browser_analyze_tab"):
                selected.append(t)
            elif any(k in text_corpus for k in ("scroll", "down", "up")) and fn_name == "browser_scroll":
                selected.append(t)
            elif any(k in text_corpus for k in ("download", "pdf", "file")) and fn_name == "browser_download_file":
                selected.append(t)
            elif any(k in text_corpus for k in ("select", "dropdown", "option")) and fn_name == "browser_select":
                selected.append(t)
            elif any(k in text_corpus for k in ("key", "enter", "press")) and fn_name == "browser_press_key":
                selected.append(t)
            elif any(k in text_corpus for k in ("back", "forward", "refresh", "reload")) and fn_name in ("browser_back", "browser_forward", "browser_refresh"):
                selected.append(t)
            elif any(k in text_corpus for k in ("vision", "analyze", "image", "look")) and fn_name in ("browser_analyze_tab", "native_screen_analyze"):
                selected.append(t)
            elif "find" in text_corpus and fn_name == "browser_find_element":
                selected.append(t)
        elif wants_system and not wants_browser:
            # System operations
            core_system = {
                "native_system_overview", "native_system_processes", "native_files_search",
                "native_files_read", "native_app_launch", "native_terminal_diagnostic",
                "native_screen_capture"
            }
            if fn_name in core_system:
                selected.append(t)
            elif any(k in text_corpus for k in ("kill", "terminate", "stop")) and fn_name == "native_system_kill_process":
                selected.append(t)
            elif any(k in text_corpus for k in ("vision", "analyze", "image", "look")) and fn_name == "native_screen_analyze":
                selected.append(t)
        else:
            # Mixed or ambiguous query: provide balanced top-utility subset
            balanced_subset = {
                "desktop_window_active", "desktop_window_list", "desktop_screen_capture",
                "browser_open", "browser_navigate", "browser_get_text", "browser_click",
                "browser_screenshot", "browser_search",
                "native_system_overview", "native_system_processes", "native_files_search",
                "native_files_read", "native_app_launch", "native_terminal_diagnostic"
            }
            if fn_name in balanced_subset:
                selected.append(t)
            elif fn_name.startswith("mcp_") and wants_mcp:
                selected.append(t)

    # Fallback to compacted tools if selection is too small
    if len(selected) < 4:
        return compact_tool_definitions(tools)

    return compact_tool_definitions(selected)


def deduplicate_tool_messages(messages: list[dict]) -> list[dict]:
    """
    Deduplicate and compact tool results within an active multi-turn agent loop.
    If the same tool was called with identical arguments or superseded by a newer call,
    compact the earlier message to save prompt tokens.
    """
    seen_calls: dict[str, int] = {}
    cleaned = []

    for idx, m in enumerate(messages):
        role = m.get("role")
        if role == "tool":
            tool_name = m.get("name", "")
            # If tool is a read/query tool that was repeated (e.g. browser.get_url, browser.get_title)
            if tool_name in ("browser_get_url", "browser_get_title", "browser_list_tabs"):
                if tool_name in seen_calls:
                    # Compact previous duplicate
                    prev_idx = seen_calls[tool_name]
                    if prev_idx < len(cleaned):
                        cleaned[prev_idx]["content"] = f"[Superseded by later {tool_name} call]"
                seen_calls[tool_name] = len(cleaned)

        cleaned.append(m)
    return cleaned
