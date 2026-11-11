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

# Concise, high-density system instruction (~200 tokens)
DEFAULT_SYSTEM_PROMPT = (
    "You are LAPTOP AI, an intelligent personal AI assistant running locally on the user's Windows machine.\n"
    "You have access to native Windows tools, browser automation, and MCP tools.\n"
    "Rules:\n"
    "- Always choose and invoke tools for real machine telemetry, process info, files, browsing, search, and diagnostics.\n"
    "- Never invent or hallucinate metrics, files, or execution results.\n"
    "- When an action requires user approval (launching apps, terminal commands, browser click/fill), invoke the tool directly; the security gate intercepts and queues it.\n"
    "- If a tool call is queued for approval, inform the user clearly of the approval ID.\n"
    "- MANDATORY: After executing browser operations, web searches, or file downloads, summarize results clearly in your response. Never return an empty message.\n"
    "- When downloading files/PDFs, report filename, size, and destination (Downloads/LAPTOP_AI).\n"
    "- If visual inspection is requested and the selected model is text-only, inform the user to switch to Google Gemini.\n"
    "- Be concise, direct, and well-structured."
)


def sanitize_tool_result_for_llm(result: any, max_chars: int = 2500) -> str:
    """
    Format and bound tool output for LLM message history.
    Omit raw binary base64 strings to prevent token and context blowout on Groq and Gemini.
    Truncate oversized outputs cleanly with notices.
    """
    if isinstance(result, dict):
        cleaned = dict(result)
        for k in list(cleaned.keys()):
            if "base64" in k.lower() and isinstance(cleaned[k], str) and len(cleaned[k]) > 100:
                cleaned[k] = "<base64 image payload omitted from LLM context; image saved on disk>"
        s = json.dumps(cleaned, indent=2, default=str)
    elif isinstance(result, list):
        cleaned_list = []
        for item in result[:15]:
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
    ) -> AgentResult:
        """
        Run the structured agent loop with preflight token budgeting,
        rate-limit backoff, and intelligent fallback handling.
        """
        conversation_history = conversation_history or []
        executions: list[ToolExecutionRecord] = []

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
            # 2. Rate Limit Handling: Check if auto-fallback is enabled in settings
            if settings.auto_provider_fallback:
                fb_provider = settings.fallback_provider
                fb_model = settings.fallback_model
                fb_key = get_key(fb_provider)

                if fb_key and fb_provider != active_provider:
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
                            )
                        else:
                            res = await self._run_openai_loop(
                                provider=fb_provider,
                                model=fb_model,
                                user_message=user_message,
                                history=compacted_history,
                                executions=executions,
                                conversation_id=conversation_id,
                            )
                        res.provider_used = fb_provider
                        res.model_used = fb_model
                        res.fallback_occurred = True
                        res.fallback_from = active_provider
                        notice = (
                            f"\n\n*(⚡ Switched to **{fb_provider.capitalize()}** (`{fb_model}`) fallback: "
                            f"{active_provider.capitalize()} reached its rate limit.)*"
                        )
                        res.reply = res.reply.strip() + notice
                        return res
                    except Exception as fb_err:
                        logger.error("Fallback provider %s failed: %s", fb_provider, fb_err)

            # 3. Fallback disabled or fallback failed: craft clear, non-destructive user notification
            state_report = ""
            if executions:
                state_report = "\n\n**Actions Completed Before Rate Limit:**\n" + "\n".join(
                    f"- `{e.tool_name}`: {'Executed successfully' if e.success else (e.error or 'Failed')}"
                    for e in executions
                )

            reply = (
                f"⚠️ **{active_provider.capitalize()} Rate Limit Reached (HTTP 429)**\n\n"
                f"The 8,000 tokens-per-minute quota for `{active_model}` was temporarily reached. "
                f"Please wait ~{int(e.wait_seconds + 1)}s before continuing."
                f"{state_report}\n\n"
                f"*Tip: You can enable 'Auto Provider Fallback' in dashboard settings to automatically continue with Google Gemini when Groq is rate-limited.*"
            )
            return AgentResult(
                reply=reply,
                tool_executions=executions,
                iterations=0,
                provider_used=active_provider,
                model_used=active_model,
                fallback_occurred=False,
            )

    async def _execute_tool_call(self, tool_call: ToolCall, conversation_id: int | None = None) -> tuple[dict, ToolExecutionRecord]:
        """Validate, permission-check, and execute a tool call safely."""
        provider_fn_name = tool_call.name
        reg_name = registry.from_provider_name(provider_fn_name)
        args = tool_call.args

        if not reg_name or reg_name not in registry.items:
            err = f"Tool '{provider_fn_name}' is not recognized or not registered."
            rec = ToolExecutionRecord(tool_name=provider_fn_name, arguments=args, success=False, error=err)
            return {"error": err, "success": False}, rec

        spec = registry.items[reg_name]

        # Permission check: If risk level is not 'read', it requires user approval
        if spec.risk != "read":
            appr = ApprovalLifecycle.create_request(reg_name, args, risk=spec.risk, conversation_id=conversation_id)
            aid = appr["id"]
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

        # Execute read-safe or pre-approved tool
        exec_res = await registry.execute(reg_name, args, timeout=self.tool_timeout)
        if exec_res.get("success"):
            audit("tool.executed", f"{reg_name}: {json.dumps(args)}")
            rec = ToolExecutionRecord(
                tool_name=reg_name,
                arguments=args,
                success=True,
                result=exec_res.get("result"),
            )
            return exec_res.get("result"), rec
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
                tool_result, record = await self._execute_tool_call(tc, conversation_id=conversation_id)
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
                tool_result, record = await self._execute_tool_call(tc, conversation_id=conversation_id)
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
