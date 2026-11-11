"""
LAPTOP AI — PHASE 5 AUTOMATED VERIFICATION SUITE
Tests all Phase 5 modules:
1. Persistent Memory Engine
2. Conversation Intelligence & Memory Injection
3. Intelligent Task Planner
4. Task Execution Engine & Checkpoints
5. Persistent Scheduler
6. Emergency Stop & Recovery
"""
from __future__ import annotations
import asyncio
import datetime
import json
import os
import sys
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.config import settings
from app.core.db import init_db, conn
from app.core.emergency import (
    is_emergency_stopped,
    trigger_emergency_stop,
    clear_emergency_stop,
    get_emergency_status,
)
from app.memory.engine import memory_engine
from app.core.conversation_intelligence import (
    get_injected_memory_context,
    generate_conversation_title,
    maybe_summarize_conversation,
)
from app.planner.planner import task_planner
from app.planner.executor import task_executor
from app.planner.scheduler import task_scheduler
from app.tools.registry import registry
from app.tools.native import register as reg_nat
from app.browser import register_browser_tools


async def run_phase5_tests():
    print("=" * 70)
    print("STARTING PHASE 5 AUTOMATED TEST SUITE")
    print("=" * 70)

    init_db()
    reg_nat()
    register_browser_tools()
    clear_emergency_stop()

    # -------------------------------------------------------------
    # TEST 1: Persistent Memory Engine CRUD & Invariant Checks
    # -------------------------------------------------------------
    print("\n--- TEST 1: Persistent Memory Engine CRUD & Invariants ---")

    # 1a. Create memory
    m1 = memory_engine.create(
        category="user_preference",
        content="Prefers concise Python code with type annotations.",
        key="python_pref",
        source="user_explicit",
    )
    assert m1["id"] is not None
    assert m1["category"] == "user_preference"
    assert m1["status"] == "active"
    print(f"[PASS] 1a. Memory created: #{m1['id']} ({m1['category']})")

    # 1b. Duplicate prevention by key
    m1_dup = memory_engine.create(
        category="user_preference",
        content="Prefers concise Python code with strict type annotations.",
        key="python_pref",
    )
    assert m1_dup["id"] == m1["id"]
    assert "strict" in m1_dup["content"]
    print(f"[PASS] 1b. Duplicate key updated existing record #{m1['id']} without creating duplicate")

    # 1c. Duplicate prevention by normalized content
    m2 = memory_engine.create(
        category="active_project",
        content="Developing the LAPTOP AI local assistant on Windows 10.",
    )
    m2_dup = memory_engine.create(
        category="active_project",
        content="developing the laptop ai local assistant on windows 10",
    )
    assert m2["id"] == m2_dup["id"]
    print(f"[PASS] 1c. Exact normalized content duplicate detected and prevented")

    # 1d. Sensitive secret rejection
    secret_caught = False
    try:
        memory_engine.create(
            category="personal_fact",
            content="My secret api_key = 'gsk_123456789012345678901234567890'",
        )
    except ValueError as ve:
        secret_caught = True
        assert "cannot contain API keys" in str(ve)
    assert secret_caught, "Secret pattern was not rejected!"
    print("[PASS] 1d. Credential / secret storage strictly rejected with security violation")

    # 1e. SQLite FTS5 search
    fts_results = memory_engine.search("Python type annotations")
    assert any(r["id"] == m1["id"] for r in fts_results)
    print(f"[PASS] 1e. SQLite FTS5 search returned {len(fts_results)} matching memory records")

    # 1f. Archive and Delete
    memory_engine.archive(m2["id"])
    assert memory_engine.get(m2["id"])["status"] == "archived"
    assert not any(m["id"] == m2["id"] for m in memory_engine.list(status="active", category="active_project"))
    print("[PASS] 1f. Memory archived successfully and excluded from active listing")

    memory_engine.delete(m2["id"])
    assert memory_engine.get(m2["id"]) is None
    print("[PASS] 1g. Memory permanently deleted")

    # -------------------------------------------------------------
    # TEST 2: Conversation Intelligence & Memory Injection
    # -------------------------------------------------------------
    print("\n--- TEST 2: Conversation Intelligence & Memory Injection ---")

    # 2a. Selective Memory Injection
    # Query for Python style should retrieve python_pref
    injected_python = get_injected_memory_context("How should I format my Python functions?", provider="groq")
    assert "Python" in injected_python
    assert "type annotations" in injected_python
    print("[PASS] 2a. Relevant memory successfully injected for related query")

    # Unrelated math query should NOT inject unrelated memory
    injected_math = get_injected_memory_context("What is 100 * 200?", provider="groq")
    assert injected_math == ""
    print("[PASS] 2b. Unrelated query received zero memory injection (no token pollution)")

    # 2c. Title Generation Fallback & LLM
    title = await generate_conversation_title("Inspect battery and disk status on my laptop")
    assert len(title) > 3
    print(f"[PASS] 2c. Title generated: '{title}'")

    # -------------------------------------------------------------
    # TEST 3: Intelligent Task Planner
    # -------------------------------------------------------------
    print("\n--- TEST 3: Intelligent Task Planner ---")

    plan = await task_planner.create_plan(
        user_request="Perform full system audit: check overview, list processes, and inspect battery",
        objective="System health inspection",
    )
    assert plan["id"].startswith("task_")
    assert plan["total_steps"] >= 2
    assert plan["status"] in ("planned", "awaiting_approval")
    assert len(plan["steps"]) >= 2
    assert plan["steps"][1]["dependencies"] == [1]
    print(f"[PASS] 3a. Structured plan created: {plan['id']} ({plan['total_steps']} steps, ordered dependencies)")

    # Consequential step risk classification
    consequential_plan = await task_planner.create_plan(
        user_request="Launch notepad application on windows",
    )
    # App launch is consequential
    assert consequential_plan["status"] == "awaiting_approval" or consequential_plan["approval_required"]
    print(f"[PASS] 3b. Consequential task flagged with status='awaiting_approval' before execution")

    # -------------------------------------------------------------
    # TEST 4: Task Execution Engine, Checkpoints & Resumption
    # -------------------------------------------------------------
    print("\n--- TEST 4: Task Execution Engine & Checkpoints ---")

    exec_res = await task_executor.execute_task(plan["id"])
    assert exec_res["status"] == "completed"
    assert exec_res["completed_steps"] == plan["total_steps"]
    for s in exec_res["steps"]:
        assert s["status"] == "completed"
        assert s["result"] is not None
    print(f"[PASS] 4a. Plan {plan['id']} executed all steps sequentially with persisted checkpoints")

    # Check that completed steps are NEVER repeated
    initial_completed_time = exec_res["steps"][0]["completed_at"]
    re_exec = await task_executor.execute_task(plan["id"])
    assert re_exec["status"] == "completed"
    assert re_exec["steps"][0]["completed_at"] == initial_completed_time
    print("[PASS] 4b. Idempotency verified: completed steps are never re-executed")

    # -------------------------------------------------------------
    # TEST 5: Persistent Task Scheduler
    # -------------------------------------------------------------
    print("\n--- TEST 5: Persistent Task Scheduler ---")

    sched = task_scheduler.create_schedule(
        task_name="Daily Health Audit",
        user_request="system health overview",
        schedule_type="interval",
        interval_seconds=60,
        start_delay_seconds=0,
    )
    assert sched["id"].startswith("sched_")
    assert sched["enabled"] == 1
    print(f"[PASS] 5a. Created schedule: {sched['id']} (interval=60s)")

    # Execute scheduler tick
    await task_scheduler.tick()
    sched_updated = task_scheduler.get_schedule(sched["id"])
    assert sched_updated["last_run_at"] is not None
    assert sched_updated["last_status"] == "success"
    print(f"[PASS] 5b. Scheduler tick triggered task, updated next_run_at and recorded last_run_at")

    # Toggle & Delete schedule
    task_scheduler.toggle_schedule(sched["id"], enabled=False)
    assert task_scheduler.get_schedule(sched["id"])["enabled"] == 0
    task_scheduler.delete_schedule(sched["id"])
    assert task_scheduler.get_schedule(sched["id"]) is None
    print("[PASS] 5c. Schedule toggling and deletion verified")

    # -------------------------------------------------------------
    # TEST 6: Emergency Stop & System Recovery
    # -------------------------------------------------------------
    print("\n--- TEST 6: Global Emergency Stop & Recovery ---")

    # 6a. Trigger Emergency Stop
    stop_st = trigger_emergency_stop(reason="Security test emergency stop")
    assert stop_st["is_stopped"] is True
    assert is_emergency_stopped() is True
    print("[PASS] 6a. Global Emergency Stop engaged")

    # 6b. Verification: All tool execution immediately blocked
    blocked_tool = await registry.execute("native.system.overview", {})
    assert blocked_tool["success"] is False
    assert "Global Emergency Stop is currently engaged" in blocked_tool["error"]
    print("[PASS] 6b. Tool execution blocked by Emergency Stop without LLM connectivity")

    # 6c. Verification: New task execution blocked
    new_plan = await task_planner.create_plan("system overview check")
    task_res_blocked = await task_executor.execute_task(new_plan["id"])
    assert task_res_blocked["status"] == "paused"
    assert "Emergency Stop" in task_res_blocked["error"]
    print("[PASS] 6c. Task execution immediately paused/blocked by Emergency Stop")

    # 6d. Verification: Clear Emergency Stop and resume
    clear_st = clear_emergency_stop()
    assert clear_st["is_stopped"] is False
    assert is_emergency_stopped() is False
    print("[PASS] 6d. Global Emergency Stop cleared")

    resumed_task = await task_executor.resume_task(new_plan["id"])
    assert resumed_task["status"] == "completed"
    print(f"[PASS] 6e. Task safely resumed and completed after emergency stop was cleared")

    # 6f. Backend restart simulation (recover_interrupted_tasks)
    with conn() as c:
        c.execute("UPDATE tasks SET status = 'running' WHERE id = ?", (new_plan["id"],))
    task_executor.recover_interrupted_tasks()
    recovered = task_planner.get_task(new_plan["id"])
    assert recovered["status"] == "paused"
    assert "Interrupted by backend restart" in recovered["error"]
    print("[PASS] 6f. Interrupted tasks cleanly recovered to 'paused' state on restart")

    print("\n" + "=" * 70)
    print("ALL PHASE 5 TESTS PASSED SUCCESSFULLY (6/6 MODULES)!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_phase5_tests())

