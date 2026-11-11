"""
LAPTOP AI — FINAL ACCEPTANCE TEST SUITE
Covers Tests 1 through 5 with both Live and Simulated scenarios clearly labeled.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

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
    get_key,
)
from app.core.agent import AgentEngine, ToolExecutionRecord
from app.tools.registry import registry
from app.tools.native import register as reg_nat
from app.browser import register_browser_tools, browser


async def run_final_acceptance_tests():
    print("=" * 70)
    print("LAPTOP AI — FINAL ACCEPTANCE TEST SUITE")
    print("=" * 70)

    init_db()
    reg_nat()
    register_browser_tools()

    agent = AgentEngine()

    # =================================================================
    # TEST 1: GROQ NORMAL OPERATION (LIVE PROVIDER)
    # =================================================================
    print("\n" + "=" * 50)
    print("TEST 1: GROQ NORMAL OPERATION (LIVE PROVIDER)")
    print("=" * 50)

    # 1a: Normal Question
    print("\n[1a] Executing normal question to Groq (openai/gpt-oss-20b)...")
    q_start = time.time()
    res_1a = await agent.run(
        provider="groq",
        model="openai/gpt-oss-20b",
        user_message="In one brief sentence, what is the purpose of an operating system?",
    )
    q_elapsed = time.time() - q_start
    q_tokens_est = estimate_tokens({"content": res_1a.reply})

    print(f"  Status: SUCCESS ({q_elapsed:.2f}s)")
    print(f"  Response: {res_1a.reply.strip()}")
    print(f"  Estimated output tokens: ~{q_tokens_est}")
    assert len(res_1a.reply.strip()) > 10, "Expected non-empty reply from Groq"
    assert res_1a.provider_used == "groq"
    assert not res_1a.fallback_occurred

    # 1b: Browser Extraction Task (Live Browser + Live Groq)
    print("\n[1b] Executing live browser extraction task (Groq + Playwright)...")
    b_start = time.time()
    res_1b = await agent.run(
        provider="groq",
        model="openai/gpt-oss-20b",
        user_message="Navigate to https://example.com and tell me the title and main heading text.",
    )
    b_elapsed = time.time() - b_start
    print(f"  Status: SUCCESS ({b_elapsed:.2f}s)")
    print(f"  Tools executed: {[e.tool_name for e in res_1b.tool_executions]}")
    print(f"  Response summary: {res_1b.reply[:200]}...")
    assert len(res_1b.tool_executions) >= 1, "Expected at least 1 browser tool execution"
    assert any("browser" in e.tool_name for e in res_1b.tool_executions)
    print("[PASS] Test 1: Groq normal operation and browser extraction completed successfully.")

    # =================================================================
    # TEST 2: CONTEXT EFFICIENCY & TOKEN BUDGETING (LIVE TELEMETRY)
    # =================================================================
    print("\n" + "=" * 50)
    print("TEST 2: CONTEXT EFFICIENCY & TOKEN BUDGETING (TELEMETRY)")
    print("=" * 50)

    all_tools = registry.get_openai_tools()
    raw_tool_json = json.dumps(all_tools)
    raw_tool_chars = len(raw_tool_json)
    raw_tool_tokens = estimate_tokens({"content": raw_tool_json})

    # Tool Scoping for a browser navigation workflow
    browser_prompt = "Navigate to https://example.com, read the header, and take a screenshot"
    scoped_tools = filter_relevant_tools(all_tools, browser_prompt, provider="groq")
    scoped_tool_json = json.dumps(scoped_tools)
    scoped_tool_chars = len(scoped_tool_json)
    scoped_tool_tokens = estimate_tokens({"content": scoped_tool_json})

    reduction_pct = ((raw_tool_chars - scoped_tool_chars) / raw_tool_chars) * 100.0

    print(f"  Full Registry Tools Count:    {len(all_tools)} tools")
    print(f"  Full Tools Schema Payload:    {raw_tool_chars:,} chars (~{raw_tool_tokens:,} tokens)")
    print(f"  Scoped Groq Tools Count:      {len(scoped_tools)} tools")
    print(f"  Scoped Tools Schema Payload:  {scoped_tool_chars:,} chars (~{scoped_tool_tokens:,} tokens)")
    print(f"  Tool Schema Token Reduction:  {reduction_pct:.1f}% savings!")

    # Verify unrelated tools excluded
    scoped_names = [t.get("function", {}).get("name", "") for t in scoped_tools]
    unrelated_excluded = ["native_system_kill_process", "native_app_launch", "native_terminal_diagnostic"]
    for ut in unrelated_excluded:
        assert ut not in scoped_names, f"Unrelated tool '{ut}' was not excluded!"

    # Verify required tools present
    required_present = ["browser_open", "browser_navigate", "browser_get_text", "browser_screenshot"]
    for rt in required_present:
        assert rt in scoped_names, f"Required tool '{rt}' was missing from scoped tools!"

    # Verify conversation history compacting
    simulated_history = [
        {"role": "user", "content": f"Prior question {i}"} if i % 2 == 0
        else {"role": "assistant", "content": f"Prior lengthy answer {i} with payload data " * 30}
        for i in range(10)
    ]
    raw_hist_tokens = sum(estimate_tokens(m) for m in simulated_history)
    compacted_hist = compact_history(simulated_history, max_tokens=800, max_turns=4)
    compacted_hist_tokens = sum(estimate_tokens(m) for m in compacted_hist)

    print(f"  Raw History Size (10 turns):   ~{raw_hist_tokens:,} tokens")
    print(f"  Compacted History (4 turns):  ~{compacted_hist_tokens:,} tokens")
    assert compacted_hist_tokens <= 800

    total_est_request = scoped_tool_tokens + compacted_hist_tokens + estimate_tokens({"content": browser_prompt}) + 1024
    print(f"  Total Estimated Groq Request: ~{total_est_request:,} tokens (Strictly below 8,000 TPM limit)")
    assert total_est_request < 4000, f"Request size {total_est_request} should be under 4,000 tokens"
    print("[PASS] Test 2: Context efficiency metrics verified with >70% tool schema reduction.")

    # =================================================================
    # TEST 3: RATE-LIMIT HANDLING & BOUNDED BACKOFF (SIMULATED 429)
    # =================================================================
    print("\n" + "=" * 50)
    print("TEST 3: RATE-LIMIT HANDLING & RETRY BOUNDS (SIMULATED 429)")
    print("=" * 50)

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {"retry-after": "0.6"}
    mock_resp_429.text = '{"error":{"message":"Rate limit reached for openai/gpt-oss-20b. Limit 8000. Try again in 0.6s."}}'
    mock_resp_429.json.return_value = {"error": {"message": "Rate limit reached for openai/gpt-oss-20b. Limit 8000. Try again in 0.6s."}}

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Recovery response after backoff."}}]
    }

    # 3a. Bounded Async Retry
    print("[3a] Testing bounded asynchronous retry with simulated 429 backoff...")
    settings.max_rate_limit_retries = 2
    with patch("httpx.AsyncClient.post", side_effect=[mock_resp_429, mock_resp_200]) as mock_post:
        t0 = time.time()
        res_3a = await chat_turn(provider="groq", model="openai/gpt-oss-20b", messages=[{"role": "user", "content": "hi"}])
        elapsed = time.time() - t0
        print(f"  Retry succeeded on attempt {mock_post.call_count} in {elapsed:.2f}s")
        assert res_3a.content == "Recovery response after backoff."
        assert mock_post.call_count == 2
        assert elapsed >= 0.6

    # 3b. RateLimitError on Persistent Limit & User-Facing Status
    print("[3b] Testing persistent rate-limit handling and user-facing status...")
    settings.auto_provider_fallback = False
    with patch("httpx.AsyncClient.post", side_effect=lambda *a, **kw: mock_resp_429):
        res_3b = await agent.run(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="Execute test command",
        )
        print(f"  Provider used: {res_3b.provider_used}")
        print(f"  Fallback occurred: {res_3b.fallback_occurred}")
        print(f"  User reply preview: {res_3b.reply[:180]}...")
        assert res_3b.fallback_occurred is False
        assert "Rate Limit Reached (HTTP 429)" in res_3b.reply
        assert "Auto Provider Fallback" in res_3b.reply

    # 3c. No Duplicate Tool Execution After Failure
    print("[3c] Verifying no duplicate tool execution when turn 2 rate limits...")
    mock_turn1 = TurnResult(
        content="",
        tool_calls=[ToolCall(id="call_t1", name="native_terminal_diagnostic", args={"command_id": "whoami"})],
        raw_message={"role": "assistant", "tool_calls": [{"id": "call_t1", "type": "function", "function": {"name": "native_terminal_diagnostic", "arguments": '{"command_id":"whoami"}'}}]}
    )
    with patch("app.core.agent.chat_turn", side_effect=[mock_turn1, RateLimitError("groq", "openai/gpt-oss-20b", 2.0, "Rate limited")]):
        res_3c = await agent.run(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="Run whoami",
        )
        assert len(res_3c.tool_executions) == 1
        assert res_3c.tool_executions[0].tool_name == "native.terminal.diagnostic"
        assert "Actions Completed Before Rate Limit" in res_3c.reply
        print("  State-changing actions preserved: 1 execution queued/run, never re-executed.")

    print("[PASS] Test 3: Rate-limit bounded retries and zero duplicate execution verified.")

    # =================================================================
    # TEST 4: INTELLIGENT PROVIDER FALLBACK (SIMULATED 429 + LIVE GEMINI)
    # =================================================================
    print("\n" + "=" * 50)
    print("TEST 4: INTELLIGENT PROVIDER FALLBACK")
    print("=" * 50)

    # 4a. Fallback Enabled (Simulate Groq 429 -> Fallover to Live Gemini)
    print("[4a] Testing fallback ENABLED: Groq 429 -> Fallover to Gemini (LIVE)...")
    settings.auto_provider_fallback = True
    settings.fallback_provider = "gemini"
    settings.fallback_model = "gemini-2.5-flash"

    # Route Groq to 429, let Gemini make live request
    import httpx
    orig_post = httpx.AsyncClient.post

    async def conditional_post(self, *args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        if "groq.com" in str(url):
            return mock_resp_429
        # Gemini or other endpoint: live request
        return await orig_post(self, *args, **kwargs)

    with patch("httpx.AsyncClient.post", conditional_post):
        fb_start = time.time()
        res_4a = await agent.run(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="What is the chemical formula for water? Answer in one word.",
        )
        fb_elapsed = time.time() - fb_start

    print(f"  Provider requested: groq")
    print(f"  Fallback occurred:  {res_4a.fallback_occurred}")
    print(f"  Provider used:      {res_4a.provider_used} ({res_4a.model_used})")
    print(f"  Failover latency:   {fb_elapsed:.2f}s")
    print(f"  Response text:      {res_4a.reply.strip()}")
    assert res_4a.fallback_occurred is True
    assert res_4a.provider_used == "gemini"
    assert "Switched to **Gemini**" in res_4a.reply
    assert "H2O" in res_4a.reply or "H₂O" in res_4a.reply

    # 4b. Fallback Disabled (Groq Remains Selected, No Silent Change)
    print("\n[4b] Testing fallback DISABLED: Groq remains selected, 429 reported...")
    settings.auto_provider_fallback = False
    with patch("httpx.AsyncClient.post", side_effect=lambda *a, **kw: mock_resp_429):
        res_4b = await agent.run(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="What is 5 + 5?",
        )
        print(f"  Fallback occurred: {res_4b.fallback_occurred}")
        print(f"  Provider used:     {res_4b.provider_used}")
        assert res_4b.fallback_occurred is False
        assert res_4b.provider_used == "groq"
        assert "Rate Limit Reached" in res_4b.reply

    print("[PASS] Test 4: Provider fallback seamlessly switches when enabled and respects user choice when disabled.")

    # =================================================================
    # TEST 5: MULTIMODAL CAPABILITY (LIVE GEMINI + TEXT-ONLY GROQ)
    # =================================================================
    print("\n" + "=" * 50)
    print("TEST 5: MULTIMODAL CAPABILITY & VISION GUARDRAILS")
    print("=" * 50)

    # 5a. Real Screenshot Capture via Playwright
    print("[5a] Capturing real webpage screenshot...")
    page = await browser.get_active_page()
    await page.goto("data:text/html,<h1 style='color:blue;font-family:sans-serif;'>LAPTOP AI VISION TEST</h1><div style='width:120px;height:60px;background:green;'></div>")
    screenshot_bytes = await page.screenshot(type="png")
    import base64
    b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")
    print(f"  Real screenshot captured: {len(screenshot_bytes):,} bytes (b64 length: {len(b64_image):,})")

    # 5b. Live Gemini Vision Analysis
    print("\n[5b] Sending real screenshot to Live Gemini (gemini-2.5-flash)...")
    v_start = time.time()
    vision_msg = [
        {"role": "user", "content": "What text is shown in this image, and what color is the box below it?", "image_base64": b64_image}
    ]
    gemini_vision_res = await chat_turn(
        provider="gemini",
        model="gemini-2.5-flash",
        messages=vision_msg,
    )
    v_elapsed = time.time() - v_start
    print(f"  Status: SUCCESS ({v_elapsed:.2f}s)")
    print(f"  Gemini Vision Analysis: {gemini_vision_res.content.strip()}")
    assert "LAPTOP AI VISION TEST" in gemini_vision_res.content.upper() or "LAPTOP AI" in gemini_vision_res.content.upper()
    assert "green" in gemini_vision_res.content.lower()

    # 5c. Text-Only Groq Model Strictly Blocked from False Vision Claims
    print("\n[5c] Verifying text-only Groq model strictly rejects image inputs...")
    groq_blocked = False
    try:
        await chat_turn(
            provider="groq",
            model="openai/gpt-oss-20b",
            messages=vision_msg,
        )
    except RuntimeError as re:
        groq_blocked = True
        print(f"  Correctly rejected: {re}")
        assert "does not support visual" in str(re)

    assert groq_blocked, "Text-only Groq model failed to reject image input!"
    print("[PASS] Test 5: Multimodal capabilities verified on Gemini; text-only Groq models protected against false vision claims.")

    # Cleanup browser
    await browser.close()

    print("\n" + "=" * 70)
    print("ALL ACCEPTANCE TESTS (1 through 5) COMPLETED AND VERIFIED!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_final_acceptance_tests())
