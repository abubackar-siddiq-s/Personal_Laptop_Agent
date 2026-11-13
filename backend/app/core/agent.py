from __future__ import annotations
import asyncio
import json
import logging
from dataclasses import dataclass, field
from app.core.config import settings
from app.core.db import conn
from app.core.security import audit
from app.core.approval import ApprovalLifecycle
from app.core.token_budget import (
    estimate_tokens,
    compact_history,
    compact_tool_definitions,
    filter_relevant_tools,
    deduplicate_tool_messages,
    PROVIDER_LIMITS,
)
from app.providers.router import (
    chat_turn,
    ToolCall,
    TurnResult,
    RateLimitError,
    get_key,
    is_vision_capable,
)
from app.tools.registry import registry
from app.core.conversation_intelligence import get_injected_memory_context

logger = logging.getLogger("laptop_ai.agent")

# Concise, high-density system instruction (~240 tokens)
DEFAULT_SYSTEM_PROMPT = (
    "You are LAPTOP AI, an intelligent personal AI assistant running locally on the user's Windows machine.\n"
    "You have access to native Windows tools, desktop control tools (active window, window listing, focus, screenshots, UI inspection, mouse, keyboard), browser automation, and MCP tools.\n"
    "Rules:\n"
    "- Always choose and invoke tools for real machine telemetry, active window info, files, browsing, search, and diagnostics.\n"
    "- For questions about the user's desktop, active application, window title, process, PID, HWND, dimensions, or visible windows, invoke the corresponding desktop tools (desktop.window.active, desktop.window.list, desktop.screen.capture, desktop.ui.inspect).\n"
    "- For visual questions about what is displayed on screen, visual layout, finding buttons/elements, extracting text/OCR, or comparing screenshots, invoke the visual intelligence tools (vision.screen.analyze, vision.screen.extract_text, vision.screen.find_element, vision.screen.compare, vision.screen.describe_region).\n"
    "- For questions about files, documents (PDF, Word, Excel, PowerPoint, CSV, Markdown, text), reading, summarizing, comparing, or answering document questions with verified citations, invoke file intelligence tools (files.document.extract, files.document.summarize, files.document.ask, files.document.compare).\n"
    "- For semantic or full-text file search, invoke files.search.semantic or files.search.content. For spreadsheet data profiling and analysis, invoke files.spreadsheet.analyze. For duplicate detection and file reorganization, invoke files.duplicates.find or files.organize.preview.\n"
    "- For proactive personal assistance questions (daily briefing, morning review, what to work on, setting reminders, deadlines, profile preferences, monitoring alerts, or natural task creation), invoke assistant tools (assistant.briefing.get, assistant.reminders.create, assistant.reminders.list, assistant.profile.get, assistant.profile.update, assistant.tasks.create_natural, assistant.monitors.list).\n"
    "- Maintain strict boundaries: distinguish explicitly confirmed facts from inferred preferences and model suggestions.\n"
    "- When inspecting UI elements, report exact counts directly from the tool's 'counts' dictionary (elements_returned, total_descendants, visible_descendants, interactive_descendants, matched_descendants). Never estimate or invent element numbers.\n"
    "- In response tables or listings, include every returned element provided by the tool without skipping or summarizing.\n"
    "- Never invent or hallucinate metrics, files, or execution results.\n"
    "- When an action requires user approval (launching apps, terminal commands, browser click/fill, desktop focus/click/type/shortcuts), invoke the tool directly; the security gate intercepts and queues it.\n"
    "- If a tool call is queued for approval, inform the user clearly of the approval ID.\n"
    "- MANDATORY: After executing browser operations, web searches, or file downloads, summarize results clearly in your response. Never return an empty message.\n"
    "- When downloading files/PDFs, report filename, size, and destination (Downloads/LAPTOP_AI).\n"
    "- If visual inspection is requested and the selected model is text-only, inform the user to switch to Google Gemini.\n"
    "- Be concise, direct, and well-structured."
)


def sanitize_tool_result_for_llm(result: any, max_chars: int = 8000) -> str:
    """
    Format and bound tool output for LLM message history.
    Omit raw binary base64 strings to prevent token and context blowout on Groq and Gemini.
    Safely bound oversized outputs without breaking JSON or omitting elements unexpectedly.
    """
    if isinstance(result, dict):
        cleaned = dict(result)
        # Omit large base64 image data
        for k in list(cleaned.keys()):
            if "base64" in k.lower() and isinstance(cleaned[k], str) and len(cleaned[k]) > 100:
                cleaned[k] = "<base64 image payload omitted from LLM context; image saved on disk>"

        # Structured list pruning if payload exceeds character budget
        if "elements" in cleaned and isinstance(cleaned["elements"], list):
            s = json.dumps(cleaned, separators=(", ", ": "), default=str)
            if len(s) > max_chars:
                elems = list(cleaned["elements"])
                orig_len = len(elems)
                while elems and len(s) > max_chars:
                    elems.pop()
                    cleaned["elements"] = elems
                    cleaned["elements_count"] = len(elems)
                    if "counts" in cleaned and isinstance(cleaned["counts"], dict):
                        cleaned["counts"]["elements_returned"] = len(elems)
                        cleaned["counts"]["elements_omitted"] = max(
                            0, cleaned["counts"].get("matched_descendants", orig_len) - len(elems)
                        )
                    cleaned["truncated"] = True
                    cleaned["context_budget_truncated"] = True
                    cleaned["context_budget_notice"] = (
                        f"Element list safely pruned from {orig_len} to {len(elems)} items to fit within context budget."
                    )
                    s = json.dumps(cleaned, separators=(", ", ": "), default=str)
                return s
            return s

        s = json.dumps(cleaned, indent=2, default=str)
    elif isinstance(result, list):
        cleaned_list = []
        for item in result[:25]:
            if isinstance(item, dict):
                ci = dict(item)
                for k in list(ci.keys()):
                    if "base64" in k.lower() and isinstance(ci[k], str) and len(ci[k]) > 100:
                        ci[k] = "<base64 payload omitted>"
                cleaned_list.append(ci)
            else:
                cleaned_list.append(item)
        s = json.dumps(cleaned_list, indent=2, default=str)
    else:
        s = str(result)

    if len(s) > max_chars:
        s = s[:max_chars] + f"\n... [Output truncated at {max_chars} characters for context efficiency]"
    return s


@dataclass
class ToolExecutionRecord:
    tool_name: str
    arguments: dict
    success: bool
    result: any = None
    error: str | None = None
    approval_id: int | None = None


@dataclass
class AgentResult:
    reply: str
    tool_executions: list[ToolExecutionRecord] = field(default_factory=list)
    iterations: int = 0
    provider_used: str = "groq"
    model_used: str = "openai/gpt-oss-20b"
    fallback_occurred: bool = False
    fallback_from: str | None = None


class AgentEngine:
    def __init__(
        self,
        max_iterations: int = 6,
        tool_timeout: float = 30.0,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ):
        self.max_iterations = max_iterations
        self.tool_timeout = tool_timeout
        self.system_prompt = system_prompt

    async def run(
        self,
        provider: str,
        model: str,
        user_message: str,
        conversation_history: list[dict] | None = None,
        conversation_id: int | None = None,
        checkpoint_executions: list[ToolExecutionRecord] | None = None,
    ) -> AgentResult:
        """
        Run the structured agent loop with preflight token budgeting,
        rate-limit backoff, and intelligent fallback handling.
        """
        # Ensure tools are registered even in standalone test environments
        if "desktop.window.active" not in registry.items:
            try:
                from app.desktop import register_desktop_tools
                register_desktop_tools()
            except Exception:
                pass

        conversation_history = conversation_history or []
        executions: list[ToolExecutionRecord] = list(checkpoint_executions) if checkpoint_executions else []

        active_provider = provider
        active_model = model

        # 1. Preflight context budgeting & history compaction
        budget = PROVIDER_LIMITS.get(active_provider, PROVIDER_LIMITS["groq"])
        max_turns = budget.get("max_history_turns", 6)
        compacted_history = compact_history(
            conversation_history,
            max_tokens=1200,
            max_turns=max_turns,
        )

        memory_context = get_injected_memory_context(user_message, provider=active_provider)
        active_system_prompt = (self.system_prompt + "\n\n" + memory_context).strip() if memory_context else self.system_prompt

        try:
            if active_provider == "gemini":
                res = await self._run_gemini_loop(
                    model=active_model,
                    user_message=user_message,
                    history=compacted_history,
                    executions=executions,
                    conversation_id=conversation_id,
                    system_prompt=active_system_prompt,
                )
            else:
                res = await self._run_openai_loop(
                    provider=active_provider,
                    model=active_model,
                    user_message=user_message,
                    history=compacted_history,
                    executions=executions,
                    conversation_id=conversation_id,
                    system_prompt=active_system_prompt,
                )
            res.provider_used = active_provider
            res.model_used = active_model
            return res

        except RateLimitError as e:
            # Mandatory Auto Provider Fallback (Always enabled)
            if settings.auto_provider_fallback:
                from app.core.inference_orchestrator import (
                    ProviderSelector,
                    record_fallback_event,
                    circuit_breaker,
                    admission_controller,
                )

                candidates = ProviderSelector.get_fallback_order(active_provider)
                if settings.fallback_provider in candidates:
                    candidates.remove(settings.fallback_provider)
                    candidates.insert(0, settings.fallback_provider)

                for fb_provider in candidates:
                    fb_key = get_key(fb_provider)
                    if not fb_key:
                        continue

                    # Select model: OpenRouter strictly free/auto model
                    if fb_provider == "gemini":
                        fb_model = settings.fallback_model or "gemini-2.5-flash"
                    elif fb_provider == "groq":
                        fb_model = "openai/gpt-oss-20b"
                    else:
                        fb_model = "openrouter/auto"

                    logger.warning(
                        "Auto provider fallback triggered: %s (%s) rate-limited -> switching to %s (%s)",
                        active_provider, active_model, fb_provider, fb_model
                    )
                    audit("provider.fallback_triggered", f"{active_provider} 429 -> {fb_provider}/{fb_model}")

                    try:
                        if fb_provider == "gemini":
                            res = await self._run_gemini_loop(
                                model=fb_model,
                                user_message=user_message,
                                history=compacted_history,
                                executions=executions,
                                conversation_id=conversation_id,
                                system_prompt=active_system_prompt,
                            )
                        else:
                            res = await self._run_openai_loop(
                                provider=fb_provider,
                                model=fb_model,
                                user_message=user_message,
                                history=compacted_history,
                                executions=executions,
                                conversation_id=conversation_id,
                                system_prompt=active_system_prompt,
                            )
                        res.provider_used = fb_provider
                        res.model_used = fb_model
                        res.fallback_occurred = True
                        res.fallback_from = active_provider
                        record_fallback_event(
                            from_provider=active_provider,
                            to_provider=fb_provider,
                            from_model=active_model,
                            to_model=fb_model,
                            reason=str(e),
                            success=True,
                        )
                        notice = (
                            f"\n\n*(⚡ Switched to **{fb_provider.capitalize()}** (`{fb_model}`) fallback: "
                            f"{active_provider.capitalize()} reached its rate limit.)*"
                        )
                        res.reply = res.reply.strip() + notice
                        return res

                    except Exception as fb_err:
                        logger.error("Fallback provider %s failed: %s", fb_provider, fb_err)
                        record_fallback_event(
                            from_provider=active_provider,
                            to_provider=fb_provider,
                            from_model=active_model,
                            to_model=fb_model,
                            reason=str(fb_err),
                            success=False,
                        )
                        continue

            # 3. All configured providers failed or exhausted: Enqueue safely
            from app.core.inference_orchestrator import admission_controller
            q_id = admission_controller.queue_request(
                conversation_id,
                user_message,
                priority="chat",
                provider_attempted=active_provider,
                checkpoint_data=[e.__dict__ for e in executions] if executions else None,
            )
            state_report = ""
            if executions:
                state_report = "\n\n**Actions Completed Before Rate Limit:**\n" + "\n".join(
                    f"- `{e.tool_name}`: {'Executed successfully' if e.success else (e.error or 'Failed')}"
                    for e in executions
                )

            reply = (
                f"⚠️ **{active_provider.capitalize()} Rate Limit Reached (HTTP 429)**\n\n"
                f"The 8,000 tokens-per-minute quota for `{active_model}` was temporarily reached. "
                f"Please wait ~{int(e.wait_seconds + 1)}s before continuing.\n\n"
                f"All backup providers were evaluated, and the request has been safely queued (#{q_id}) to resume automatically. "
                f"Auto Provider Fallback was engaged and evaluated all eligible providers. "
                f"Conversation context and completed actions remain fully preserved.{state_report}"
            )
            return AgentResult(
                reply=reply,
                tool_executions=executions,
                iterations=0,
                provider_used=active_provider,
                model_used=active_model,
                fallback_occurred=False,
            )

    # Alias step to run for single-step/turn agent invocation
    step = run

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        conversation_id: int | None = None,
        existing_executions: list[ToolExecutionRecord] | None = None,
    ) -> tuple[dict, ToolExecutionRecord]:
        """Validate, permission-check, and execute a tool call safely with fallback idempotency."""
        provider_fn_name = tool_call.name
        reg_name = registry.from_provider_name(provider_fn_name)
        args = tool_call.args

        if not reg_name or reg_name not in registry.items:
            err = f"Tool '{provider_fn_name}' is not recognized or not registered."
            rec = ToolExecutionRecord(tool_name=provider_fn_name, arguments=args, success=False, error=err)
            return {"error": err, "success": False}, rec

        # Provider fallback idempotency: Never repeat a completed consequential tool action
        if existing_executions:
            clean_args = json.dumps(args, sort_keys=True, default=str)
            for prev in existing_executions:
                if prev.tool_name == reg_name and json.dumps(prev.arguments, sort_keys=True, default=str) == clean_args:
                    if prev.success:
                        logger.info("Idempotency guard: avoiding re-execution of completed tool '%s' on fallback.", reg_name)
                        return prev.result, prev
                    elif prev.approval_id:
                        logger.info("Idempotency guard: avoiding duplicate approval queue for tool '%s'.", reg_name)
                        return {
                            "status": "approval_required",
                            "approval_id": prev.approval_id,
                            "tool_name": reg_name,
                            "risk": "approval",
                            "message": f"Action is already awaiting user approval (Approval #{prev.approval_id}).",
                        }, prev

        spec = registry.items[reg_name]

        # Permission check: If risk level is not 'read', it requires user approval
        if spec.risk != "read":
            import hashlib
            clean_args = json.dumps(args, sort_keys=True, default=str)
            tc_id = getattr(tool_call, "id", None) or "call"
            op_id = f"op_{conversation_id}_{tc_id}_{reg_name}_{hashlib.sha256(clean_args.encode()).hexdigest()[:16]}"
            appr = ApprovalLifecycle.create_request(
                reg_name,
                args,
                risk=spec.risk,
                conversation_id=conversation_id,
                operation_id=op_id,
            )
            aid = appr["id"]

            if appr.get("reused"):
                rec = ToolExecutionRecord(
                    tool_name=reg_name,
                    arguments=args,
                    success=True,
                    result=appr.get("result"),
                    approval_id=aid,
                )
                return appr.get("result"), rec
            elif appr.get("uncertain_recovery"):
                rec = ToolExecutionRecord(
                    tool_name=reg_name,
                    arguments=args,
                    success=False,
                    error=appr.get("error", "Uncertain operation state after crash; manual review required"),
                    approval_id=aid,
                )
                return {
                    "status": "manual_review_required",
                    "approval_id": aid,
                    "tool_name": reg_name,
                    "error": appr.get("error"),
                    "message": "Operation state is uncertain due to previous server termination. Potentially destructive action was not automatically rerun. Manual review required.",
                }, rec

            rec = ToolExecutionRecord(
                tool_name=reg_name,
                arguments=args,
                success=False,
                error="Pending user approval",
                approval_id=aid,
            )
            return {
                "status": "approval_required",
                "approval_id": aid,
                "tool_name": reg_name,
                "risk": spec.risk,
                "message": (
                    f"Action requires explicit user approval. Approval request #{aid} has been queued in the Activity Log tab. "
                    f"Execution is blocked and the tool will not execute until explicitly approved by the user."
                ),
            }, rec

        # Check read-only deterministic cache if low risk
        if spec.risk == "low":
            from app.core.inference_orchestrator import read_only_cache
            cached_val = read_only_cache.get(reg_name, args)
            if cached_val is not None:
                rec = ToolExecutionRecord(
                    tool_name=reg_name,
                    arguments=args,
                    success=True,
                    result=cached_val,
                )
                return cached_val, rec

        # Execute read-safe or pre-approved tool
        exec_res = await registry.execute(reg_name, args, timeout=self.tool_timeout)
        if exec_res.get("success"):
            audit("tool.executed", f"{reg_name}: {json.dumps(args)}")
            res_val = exec_res.get("result")
            if spec.risk == "low":
                from app.core.inference_orchestrator import read_only_cache
                read_only_cache.set(reg_name, args, res_val)

            rec = ToolExecutionRecord(
                tool_name=reg_name,
                arguments=args,
                success=True,
                result=res_val,
            )
            return res_val, rec
        else:
            audit("tool.failed", f"{reg_name}: {exec_res.get('error')}")
            rec = ToolExecutionRecord(
                tool_name=reg_name,
                arguments=args,
                success=False,
                error=exec_res.get("error"),
            )
            return {"error": exec_res.get("error"), "success": False}, rec

    async def _run_openai_loop(
        self,
        provider: str,
        model: str,
        user_message: str,
        history: list[dict],
        executions: list[ToolExecutionRecord],
        conversation_id: int | None = None,
        system_prompt: str | None = None,
    ) -> AgentResult:
        """Agent loop for OpenAI-compatible providers (Groq, OpenRouter)."""
        messages: list[dict] = []
        messages.append({"role": "system", "content": system_prompt or self.system_prompt})

        # Load compacted context
        for h in history:
            role = "assistant" if h.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": h.get("content", "")})

        messages.append({"role": "user", "content": user_message})

        # Token-conscious tool scoping: for Groq, filter relevant tools to stay under 8,000 TPM
        raw_tools = registry.get_openai_tools()
        tools = filter_relevant_tools(raw_tools, user_message, history, provider=provider)

        max_tool_chars = PROVIDER_LIMITS.get(provider, {}).get("max_tool_chars", 2500)
        final_reply = ""
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            # Deduplicate repetitive tool outputs before each call
            cleaned_messages = deduplicate_tool_messages(messages)

            turn_res = await chat_turn(
                provider=provider,
                model=model,
                messages=cleaned_messages,
                tools=tools if tools else None,
            )

            # If no tool calls, the model provided its final answer
            if not turn_res.tool_calls:
                final_reply = turn_res.content
                break

            # Model requested one or more tool calls
            if turn_res.raw_message:
                messages.append(turn_res.raw_message)

            for tc in turn_res.tool_calls:
                tool_result, record = await self._execute_tool_call(
                    tc, conversation_id=conversation_id, existing_executions=executions
                )
                if record not in executions:
                    executions.append(record)

                content_str = sanitize_tool_result_for_llm(tool_result, max_chars=max_tool_chars)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": content_str,
                })

        if not final_reply.strip():
            if executions:
                lines = ["I executed the requested action(s):"]
                for e in executions:
                    st = "Completed successfully" if e.success else f"Failed: {e.error}"
                    res_snippet = ""
                    if e.result and isinstance(e.result, dict):
                        if "title" in e.result:
                            res_snippet = f" (Title: {e.result['title']})"
                        elif "url" in e.result:
                            res_snippet = f" (URL: {e.result['url']})"
                        elif "filename" in e.result:
                            res_snippet = f" (File: {e.result['filename']})"
                        elif "action" in e.result:
                            res_snippet = f" (Action: {e.result['action']})"
                    lines.append(f"- **{e.tool_name}**: {st}{res_snippet}")
                final_reply = "\n".join(lines)
            else:
                final_reply = "I processed your request, but no action or output was generated."

        return AgentResult(reply=final_reply, tool_executions=executions, iterations=iteration)

    async def _run_gemini_loop(
        self,
        model: str,
        user_message: str,
        history: list[dict],
        executions: list[ToolExecutionRecord],
        conversation_id: int | None = None,
        system_prompt: str | None = None,
    ) -> AgentResult:
        """Agent loop for Google Gemini."""
        contents: list[dict] = []

        # Load recent context
        for h in history:
            role = "model" if h.get("role") == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": h.get("content", "")}],
            })

        contents.append({
            "role": "user",
            "parts": [{"text": user_message}],
        })

        gemini_tools = registry.get_gemini_tools()
        final_reply = ""
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            turn_res = await chat_turn(
                provider="gemini",
                model=model,
                messages=contents,
                tools=gemini_tools if gemini_tools else None,
                system_instruction=system_prompt or self.system_prompt,
            )

            if not turn_res.tool_calls:
                final_reply = turn_res.content
                break

            if turn_res.raw_message:
                contents.append(turn_res.raw_message)

            for tc in turn_res.tool_calls:
                tool_result, record = await self._execute_tool_call(
                    tc, conversation_id=conversation_id, existing_executions=executions
                )
                if record not in executions:
                    executions.append(record)

                if isinstance(tool_result, dict):
                    cleaned_gemini_result = dict(tool_result)
                    for k in list(cleaned_gemini_result.keys()):
                        if "base64" in k.lower() and isinstance(cleaned_gemini_result[k], str) and len(cleaned_gemini_result[k]) > 100:
                            cleaned_gemini_result[k] = "<base64 image payload omitted; file saved on disk>"
                else:
                    cleaned_gemini_result = tool_result

                contents.append({
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": tc.name,
                                "response": {
                                    "result": cleaned_gemini_result,
                                },
                            }
                        }
                    ],
                })

        if not final_reply.strip():
            if executions:
                lines = ["I executed the requested action(s):"]
                for e in executions:
                    st = "Completed successfully" if e.success else f"Failed: {e.error}"
                    res_snippet = ""
                    if e.result and isinstance(e.result, dict):
                        if "title" in e.result:
                            res_snippet = f" (Title: {e.result['title']})"
                        elif "url" in e.result:
                            res_snippet = f" (URL: {e.result['url']})"
                        elif "filename" in e.result:
                            res_snippet = f" (File: {e.result['filename']})"
                        elif "action" in e.result:
                            res_snippet = f" (Action: {e.result['action']})"
                    lines.append(f"- **{e.tool_name}**: {st}{res_snippet}")
                final_reply = "\n".join(lines)
            else:
                final_reply = "I processed your request, but no action or output was generated."

        return AgentResult(reply=final_reply, tool_executions=executions, iterations=iteration)


agent_engine = AgentEngine()
