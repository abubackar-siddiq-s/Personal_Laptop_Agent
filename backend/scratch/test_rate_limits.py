import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.config import settings
from app.core.db import init_db, conn
from app.core.token_budget import (
    estimate_tokens,
    parse_rate_limit_reset,
    compact_history,
    compact_tool_definitions,
    filter_relevant_tools,
    deduplicate_tool_messages,
    PROVIDER_LIMITS,
)
from app.providers.router import (
    chat_turn,
    RateLimitError,
    TurnResult,
    ToolCall,
    is_vision_capable,
)
from app.core.agent import AgentEngine, ToolExecutionRecord
from app.tools.registry import registry
from app.tools.native import register as reg_nat
from app.browser import register_browser_tools


async def run_all_tests():
    print("=" * 65)
    print("STARTING GROQ RATE LIMIT & PROVIDER RESILIENCE TEST SUITE")
    print("=" * 65)

    init_db()
    reg_nat()
    register_browser_tools()

    # -------------------------------------------------------------
    # TEST 1: Retry-After & Rate Limit Header/Body Parsing
    # -------------------------------------------------------------
    print("\n--- TEST 1: Rate Limit Reset Parsing ---")
    # Standard header
    assert parse_rate_limit_reset({"retry-after": "3"}, None) == 3.0
    # Groq-specific token reset header
    assert parse_rate_limit_reset({"x-ratelimit-reset-tokens": "2.84s"}, None) == 2.84
    # Groq-specific requests reset header in milliseconds
    assert parse_rate_limit_reset({"x-ratelimit-reset-requests": "750ms"}, None) == 0.75
    # From body text when headers are absent
    groq_err_body = (
        '{"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org`: '
        'Limit 8000, Used 7302, Requested 3171. Please try again in 2.84s.","type":"tokens"}}'
    )
    assert parse_rate_limit_reset({}, groq_err_body) == 2.84
    # Clamping tests: lower bound 0.5s, upper bound 15.0s
    assert parse_rate_limit_reset({"retry-after": "0.1"}, None) == 0.5
    assert parse_rate_limit_reset({"retry-after": "60"}, None) == 15.0
    print("[PASS] 1. Retry-After & reset headers parsed accurately with safe bounds [0.5s, 15.0s]")

    # -------------------------------------------------------------
    # TEST 2: Context Trimming & Token Budgeting
    # -------------------------------------------------------------
    print("\n--- TEST 2: Context Trimming & Token Budgeting ---")
    # 2a. Token estimation accuracy
    tok_count = estimate_tokens("Hello world, this is a test prompt for token estimation.")
    assert 10 <= tok_count <= 20, f"Unexpected token count: {tok_count}"

    # 2b. Compacting history
    large_history = [
        {"role": "user", "content": f"User question {i}"} if i % 2 == 0
        else {"role": "assistant", "content": f"A very long response {i} " + "data " * 200}
        for i in range(12)
    ]
    compacted = compact_history(large_history, max_tokens=600, max_turns=4)
    assert len(compacted) <= 4, f"Expected at most 4 turns, got {len(compacted)}"
    total_tokens = sum(estimate_tokens(m) for m in compacted)
    assert total_tokens <= 600, f"History tokens {total_tokens} exceeded budget 600"
    print(f"[PASS] 2a. History compacted from 12 turns to {len(compacted)} turns ({total_tokens} tokens <= budget 600)")

    # 2c. Tool scoping for Groq
    all_tools = registry.get_openai_tools()
    browser_tools = filter_relevant_tools(all_tools, "Navigate to https://example.com and click the login button", provider="groq")
    assert len(browser_tools) < len(all_tools), "Browser tools should be scoped for Groq"
    assert any("browser" in t["function"]["name"] for t in browser_tools)
    raw_size = len(json.dumps(all_tools))
    scoped_size = len(json.dumps(browser_tools))
    assert scoped_size < raw_size * 0.6, f"Scoped tools {scoped_size} not reduced by >40% of {raw_size}"
    print(f"[PASS] 2b. Tool scoping reduced tool schema payload from {raw_size} to {scoped_size} chars (>40% savings)")

    # -------------------------------------------------------------
    # TEST 3: Duplicate Tool Result Removal
    # -------------------------------------------------------------
    print("\n--- TEST 3: Duplicate Tool Result Removal ---")
    messages = [
        {"role": "user", "content": "Check tabs"},
        {"role": "tool", "name": "browser_get_url", "content": "https://example.com/page1"},
        {"role": "assistant", "content": "Navigating to page 2..."},
        {"role": "tool", "name": "browser_get_url", "content": "https://example.com/page2"},
        {"role": "assistant", "content": "Current URL is page 2."},
    ]
    deduped = deduplicate_tool_messages(messages)
    # The first browser_get_url should be marked superseded
    assert "Superseded" in deduped[1]["content"]
    assert "https://example.com/page2" in deduped[3]["content"]
    print("[PASS] 3. Duplicate tool results compacted; earlier redundant calls marked superseded")

    # -------------------------------------------------------------
    # TEST 4: Exponential Backoff & Retry Handling
    # -------------------------------------------------------------
    print("\n--- TEST 4: Exponential Backoff & Maximum Retries ---")
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {"retry-after": "0.5"}
    mock_resp_429.text = '{"error":{"message":"Rate limit exceeded. Please try again in 500ms."}}'
    mock_resp_429.json.return_value = {"error": {"message": "Rate limit exceeded. Please try again in 500ms."}}

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Retry succeeded!"}}]
    }

    # 4a. Backoff recovery on attempt 2
    settings.max_rate_limit_retries = 2
    with patch("httpx.AsyncClient.post", side_effect=[mock_resp_429, mock_resp_200]) as mock_post:
        t0 = time.time()
        res = await chat_turn(provider="groq", model="openai/gpt-oss-20b", messages=[{"role": "user", "content": "hi"}])
        elapsed = time.time() - t0
        assert res.content == "Retry succeeded!", f"Expected recovery, got: {res.content}"
        assert mock_post.call_count == 2, f"Expected 2 attempts, got {mock_post.call_count}"
        assert elapsed >= 0.5, f"Expected backoff sleep >= 0.5s, took {elapsed}s"
    print(f"[PASS] 4a. Backoff retry succeeded on attempt 2 after {elapsed:.2f}s backoff")

    # 4b. Maximum retry enforcement (raises RateLimitError when 429 persists)
    with patch("httpx.AsyncClient.post", side_effect=[mock_resp_429, mock_resp_429, mock_resp_429]) as mock_post:
        rate_limit_raised = False
        try:
            await chat_turn(provider="groq", model="openai/gpt-oss-20b", messages=[{"role": "user", "content": "hi"}])
        except RateLimitError as rle:
            rate_limit_raised = True
            assert rle.provider == "groq"
            assert rle.wait_seconds == 0.5
        assert rate_limit_raised, "RateLimitError was not raised after exceeding retries"
        assert mock_post.call_count == 3, f"Expected 3 attempts (1 initial + 2 retries), got {mock_post.call_count}"
    print("[PASS] 4b. Maximum retry limit (2 retries) strictly enforced; RateLimitError raised")

    # -------------------------------------------------------------
    # TEST 5: Fallback Disabled Behavior
    # -------------------------------------------------------------
    print("\n--- TEST 5: Fallback Disabled Behavior ---")
    settings.auto_provider_fallback = False
    agent = AgentEngine()

    with patch("httpx.AsyncClient.post", side_effect=lambda *a, **kw: mock_resp_429):
        agent_res = await agent.run(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="Hello LAPTOP AI",
        )
        assert agent_res.fallback_occurred == False
        assert "Rate Limit Reached (HTTP 429)" in agent_res.reply
        assert "Please wait ~1s before continuing" in agent_res.reply or "Please wait ~2s" in agent_res.reply
        assert "Auto Provider Fallback" in agent_res.reply
    print("[PASS] 5. Fallback disabled: clear 429 explanation returned without silently changing provider")

    # -------------------------------------------------------------
    # TEST 6: Fallback Enabled Behavior
    # -------------------------------------------------------------
    print("\n--- TEST 6: Fallback Enabled Behavior ---")
    settings.auto_provider_fallback = True
    settings.fallback_provider = "gemini"
    settings.fallback_model = "gemini-2.5-flash"
    settings.gemini_api_key = "test_gemini_api_key_valid_len_12345"

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.status_code = 200
    mock_gemini_resp.json.return_value = {
        "candidates": [{
            "content": {"parts": [{"text": "Hello from Gemini fallback!"}], "role": "model"}
        }]
    }

    # Simulate Groq 429 followed by Gemini success
    with patch("httpx.AsyncClient.post") as mock_client_post:
        def post_router(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "groq.com" in str(url):
                return mock_resp_429
            return mock_gemini_resp

        mock_client_post.side_effect = post_router

        fb_res = await agent.run(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="Hello LAPTOP AI with fallback",
        )
        assert fb_res.fallback_occurred == True, "Fallback should have occurred"
        assert fb_res.provider_used == "gemini", f"Expected provider 'gemini', got '{fb_res.provider_used}'"
        assert "Hello from Gemini fallback!" in fb_res.reply
        assert "Switched to **Gemini**" in fb_res.reply
    print("[PASS] 6. Fallback enabled: seamlessly failover to Gemini preserving context and notification")

    # -------------------------------------------------------------
    # TEST 7: Vision Capability Preservation During Fallback
    # -------------------------------------------------------------
    print("\n--- TEST 7: Vision Capability Preservation ---")
    # Verify vision capability helper
    assert is_vision_capable("gemini", "gemini-2.5-flash") == True
    assert is_vision_capable("groq", "openai/gpt-oss-20b") == False
    assert is_vision_capable("openrouter", "openai/gpt-4o") == True

    # Attempting to send an image to a text-only model must be rejected with a clear message
    image_msg = [{"role": "user", "content": "Look at this", "image_base64": "fake_b64"}]
    rejected = False
    try:
        await chat_turn(provider="groq", model="openai/gpt-oss-20b", messages=image_msg)
    except RuntimeError as re:
        rejected = True
        assert "does not support visual" in str(re)
    assert rejected, "Text-only model accepted image input without error"
    print("[PASS] 7. Multimodal input strictly blocked on text-only models; vision models verified")

    # -------------------------------------------------------------
    # TEST 8: State-Changing Tools Never Repeated After Inference Failure
    # -------------------------------------------------------------
    print("\n--- TEST 8: State-Changing Action Preservation ---")
    settings.auto_provider_fallback = False

    # Simulate: Turn 1 requests launch of Notepad (state-changing), Turn 2 rate limits
    mock_turn1 = TurnResult(
        content="",
        tool_calls=[ToolCall(id="call_diag", name="native_terminal_diagnostic", args={"command_id": "whoami"})],
        raw_message={"role": "assistant", "tool_calls": [{"id": "call_diag", "type": "function", "function": {"name": "native_terminal_diagnostic", "arguments": '{"command_id":"whoami"}'}}]}
    )

    with patch("app.core.agent.chat_turn", side_effect=[mock_turn1, RateLimitError("groq", "openai/gpt-oss-20b", 3.0, "Rate limit reached")]):
        state_res = await agent.run(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="Run whoami",
        )
        # Check that whoami was executed in Turn 1
        assert len(state_res.tool_executions) == 1, "Expected 1 tool execution record"
        assert state_res.tool_executions[0].tool_name == "native.terminal.diagnostic"
        assert state_res.tool_executions[0].success == False  # requires approval
        assert "Pending user approval" in state_res.tool_executions[0].error
        # Verify reply clearly reports what was done before rate limit occurred
        assert "Rate Limit Reached" in state_res.reply
        assert "Actions Completed Before Rate Limit" in state_res.reply
        assert "native.terminal.diagnostic" in state_res.reply
    print("[PASS] 8. Completed/queued tool actions preserved; never repeated because inference failed afterward")

    # -------------------------------------------------------------
    # CLEANUP & SUMMARY
    # -------------------------------------------------------------
    settings.auto_provider_fallback = False
    print("\n" + "=" * 65)
    print("ALL RATE LIMIT & PROVIDER RESILIENCE TESTS PASSED (8/8)!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
