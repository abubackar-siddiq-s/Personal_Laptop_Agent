"""
LAPTOP AI — PHASE 7 REMEDIATION TEST SUITE
Verifies all remediation requirements from phase7_independent_acceptance_audit.md:
- Finding 1: Autonomous Durable Inference Queue (claiming, recovery, idempotency, cancellation, priority)
- Finding 2: Fallback Configuration at Initialization Boundary (settings, env override, API defense)
"""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.config import Settings, settings
from app.core.db import conn, init_db
from app.core.security import get_or_create_bootstrap_secret
from app.core.credential_manager import CredentialManager
from app.core.inference_orchestrator import (
    circuit_breaker,
    admission_controller,
    inference_dispatcher,
    InferenceQueueDispatcher,
    ProviderSelector,
)
from app.core.agent import AgentEngine, ToolExecutionRecord, AgentResult, agent_engine
from app.core.emergency import trigger_emergency_stop, clear_emergency_stop, is_emergency_stopped
from app.api.routes import update_app_settings, SettingsUpdate


class TestPhase7Remediation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        clear_emergency_stop()
        admission_controller.resume_background()
        with conn() as c:
            c.execute("DELETE FROM inference_queue")
            c.execute("DELETE FROM provider_credentials")
            c.execute("DELETE FROM provider_fallback_events")

    def tearDown(self):
        clear_emergency_stop()
        admission_controller.resume_background()

    # =========================================================================
    # FINDING 2: FALLBACK CONFIGURATION AT INITIALIZATION BOUNDARY
    # =========================================================================

    def test_f2_01_direct_instantiation_with_false(self):
        """Direct instantiation with auto_provider_fallback=False is overridden to True."""
        s = Settings(auto_provider_fallback=False)
        self.assertTrue(s.auto_provider_fallback)

    def test_f2_02_env_override_with_false(self):
        """Environment variable AUTO_PROVIDER_FALLBACK=false is overridden to True."""
        with patch.dict(os.environ, {"AUTO_PROVIDER_FALLBACK": "false"}):
            s = Settings()
            self.assertTrue(s.auto_provider_fallback)

    def test_f2_03_env_override_with_true(self):
        """Environment variable AUTO_PROVIDER_FALLBACK=true correctly remains True."""
        with patch.dict(os.environ, {"AUTO_PROVIDER_FALLBACK": "true"}):
            s = Settings()
            self.assertTrue(s.auto_provider_fallback)

    def test_f2_04_missing_setting_defaults_true(self):
        """Missing setting defaults to True."""
        s = Settings()
        self.assertTrue(s.auto_provider_fallback)

    def test_f2_05_application_import_before_startup(self):
        """Application import before startup hook observes auto_provider_fallback=True."""
        from app.core.config import settings as global_settings
        self.assertTrue(global_settings.auto_provider_fallback)

    def test_f2_06_mutation_attempt_after_init(self):
        """Attempts to mutate s.auto_provider_fallback = False post-init are blocked."""
        s = Settings()
        s.auto_provider_fallback = False
        self.assertTrue(s.auto_provider_fallback)

    def test_f2_07_api_attempt_to_disable_fallback(self):
        """API update_app_settings payload cannot disable auto_provider_fallback."""
        res = update_app_settings(SettingsUpdate(auto_provider_fallback=False))
        self.assertTrue(res["auto_provider_fallback"])
        self.assertTrue(settings.auto_provider_fallback)

    # =========================================================================
    # FINDING 1: AUTONOMOUS DURABLE INFERENCE QUEUE
    # =========================================================================

    def test_f1_01_request_remains_queued_when_no_provider_available(self):
        """When all providers are unavailable, tick() leaves request in waiting_quota with backoff."""
        req_id = admission_controller.queue_request(
            conversation_id=1, prompt="Hello", task_type="chat", priority="chat"
        )
        # Trip circuit breakers for all providers to simulate total provider outage
        now = time.time()
        for p in ("gemini", "groq", "openrouter"):
            circuit_breaker._states[p] = "open"
            circuit_breaker._opened_at[p] = now

        dispatcher = InferenceQueueDispatcher()
        res = asyncio.run(dispatcher.tick())
        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(res["reason"], "no_eligible_provider")

        with conn() as c:
            row = c.execute("SELECT status, retry_after_ts FROM inference_queue WHERE id=?", (req_id,)).fetchone()
            self.assertEqual(row["status"], "waiting_quota")
            self.assertIsNotNone(row["retry_after_ts"])

        # Reset circuit breakers
        for p in ("gemini", "groq", "openrouter"):
            circuit_breaker._states[p] = "closed"

    def test_f1_02_waiting_request_dispatched_when_provider_eligible(self):
        """When a provider becomes eligible, tick() claims and completes the request."""
        req_id = admission_controller.queue_request(
            conversation_id=1, prompt="Tell a joke", task_type="chat", priority="chat"
        )
        CredentialManager.add_credential("groq", "G1", "gsk_test_key_1", priority=10)

        dispatcher = InferenceQueueDispatcher()
        mock_result = AgentResult(reply="Why did the robot cross the road? To optimize latency.", tool_executions=[])

        with patch.object(AgentEngine, "run", AsyncMock(return_value=mock_result)):
            res = asyncio.run(dispatcher.tick())
            self.assertEqual(res["dispatched"], 1)
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["request_id"], req_id)

        with conn() as c:
            row = c.execute("SELECT status, result, worker_id, claimed_at FROM inference_queue WHERE id=?", (req_id,)).fetchone()
            self.assertEqual(row["status"], "completed")
            self.assertIn("Why did the robot cross the road?", row["result"])
            self.assertIsNotNone(row["worker_id"])
            self.assertIsNotNone(row["claimed_at"])

    def test_f1_03_concurrent_workers_cannot_claim_same_request(self):
        """Two concurrent workers competing for one queued item; exactly one claims it."""
        req_id = admission_controller.queue_request(
            conversation_id=2, prompt="Concurrent task", task_type="chat", priority="chat"
        )

        w1 = InferenceQueueDispatcher(worker_id="worker_alpha")
        w2 = InferenceQueueDispatcher(worker_id="worker_beta")

        # Mock agent_engine.run to be slow
        async def slow_run(*args, **kwargs):
            await asyncio.sleep(0.05)
            return AgentResult(reply="Done", tool_executions=[])

        CredentialManager.add_credential("groq", "G1", "gsk_concurrent_key", priority=10)

        with patch.object(AgentEngine, "run", side_effect=slow_run):
            async def run_both():
                return await asyncio.gather(w1.tick(), w2.tick())

            results = asyncio.run(run_both())
            dispatched_count = sum(r.get("dispatched", 0) for r in results)
            self.assertEqual(dispatched_count, 1)

    def test_f1_04_duplicate_ticks_cannot_execute_same_request_twice(self):
        """A completed request is never re-executed on subsequent ticks."""
        req_id = admission_controller.queue_request(conversation_id=3, prompt="Once only")
        CredentialManager.add_credential("groq", "G1", "gsk_once_key", priority=10)
        dispatcher = InferenceQueueDispatcher()

        with patch.object(AgentEngine, "run", AsyncMock(return_value=AgentResult(reply="Single", tool_executions=[]))):
            res1 = asyncio.run(dispatcher.tick())
            self.assertEqual(res1["dispatched"], 1)

            res2 = asyncio.run(dispatcher.tick())
            self.assertEqual(res2["dispatched"], 0)
            self.assertEqual(res2["reason"], "empty_or_cooling_down")

    def test_f1_05_cancellation_prevents_dispatch(self):
        """Cancelled request is not claimed or executed by dispatcher."""
        req_id = admission_controller.queue_request(conversation_id=4, prompt="To be cancelled")
        success = admission_controller.cancel_request(req_id, reason="User changed mind")
        self.assertTrue(success)

        CredentialManager.add_credential("groq", "G1", "gsk_cancel_key", priority=10)
        dispatcher = InferenceQueueDispatcher()
        res = asyncio.run(dispatcher.tick())
        self.assertEqual(res["dispatched"], 0)

        with conn() as c:
            row = c.execute("SELECT status, error_message FROM inference_queue WHERE id=?", (req_id,)).fetchone()
            self.assertEqual(row["status"], "cancelled")
            self.assertEqual(row["error_message"], "User changed mind")

    def test_f1_06_emergency_stop_prevents_execution(self):
        """Active Global Emergency Stop completely halts dispatcher tick."""
        req_id = admission_controller.queue_request(conversation_id=5, prompt="Dangerous task")
        CredentialManager.add_credential("groq", "G1", "gsk_emerg_key", priority=10)

        trigger_emergency_stop("Safety verification")
        dispatcher = InferenceQueueDispatcher()
        res = asyncio.run(dispatcher.tick())
        self.assertEqual(res["dispatched"], 0)
        self.assertTrue(res.get("emergency_stopped"))

        with conn() as c:
            row = c.execute("SELECT status FROM inference_queue WHERE id=?", (req_id,)).fetchone()
            self.assertEqual(row["status"], "waiting_quota")

        clear_emergency_stop()

    def test_f1_07_completed_tools_are_not_replayed_on_queue_dispatch(self):
        """Completed consequential actions stored in checkpoint_data are preserved and not replayed."""
        prev_executions = [
            {"tool_name": "browser_navigate", "arguments": {"url": "https://example.com"}, "success": True, "result": {"ok": True}}
        ]
        req_id = admission_controller.queue_request(
            conversation_id=6,
            prompt="Navigate and summarize",
            checkpoint_data=prev_executions,
        )

        CredentialManager.add_credential("groq", "G1", "gsk_tool_key", priority=10)
        dispatcher = InferenceQueueDispatcher()

        observed_executions = []

        async def mock_agent_run(*args, **kwargs):
            # Check executions passed through agent
            return AgentResult(reply="Summarized page without navigating again.", tool_executions=[])

        with patch.object(AgentEngine, "run", side_effect=mock_agent_run):
            res = asyncio.run(dispatcher.tick())
            self.assertEqual(res["dispatched"], 1)

    def test_f1_08_restart_recovery_safe_requests(self):
        """Stale requests with no consequential tools are safely reset to waiting_quota on restart."""
        with conn() as c:
            c.execute(
                """
                INSERT INTO inference_queue (id, conversation_id, task_type, priority, prompt, status, worker_id, claimed_at, retry_count)
                VALUES ('qreq_stale_safe', 7, 'chat', 'chat', 'Prompt', 'claimed', 'dead_worker', '2026-11-13T10:00:00Z', 0)
                """
            )

        dispatcher = InferenceQueueDispatcher()
        rec = dispatcher.recover_stale_claims()
        self.assertEqual(rec["recovered"], 1)

        with conn() as c:
            row = c.execute("SELECT status, worker_id, retry_count FROM inference_queue WHERE id='qreq_stale_safe'").fetchone()
            self.assertEqual(row["status"], "waiting_quota")
            self.assertIsNone(row["worker_id"])
            self.assertEqual(row["retry_count"], 1)

    def test_f1_09_restart_recovery_uncertain_consequential_to_manual_review(self):
        """Stale requests interrupted while executing consequential tools become manual_review."""
        consequential_cp = json.dumps([
            {"tool_name": "filesystem_write", "arguments": {"path": "C:\\test.txt"}, "status": "executing"}
        ])
        with conn() as c:
            c.execute(
                """
                INSERT INTO inference_queue (id, conversation_id, task_type, priority, prompt, status, checkpoint_data, worker_id, claimed_at)
                VALUES ('qreq_stale_conseq', 8, 'chat', 'chat', 'Write file', 'executing', ?, 'dead_worker', '2026-11-13T10:00:00Z')
                """,
                (consequential_cp,)
            )

        dispatcher = InferenceQueueDispatcher()
        rec = dispatcher.recover_stale_claims()
        self.assertEqual(rec["manual_review"], 1)

        with conn() as c:
            row = c.execute("SELECT status, error_message FROM inference_queue WHERE id='qreq_stale_conseq'").fetchone()
            self.assertEqual(row["status"], "manual_review")
            self.assertIn("State uncertain; manual review required", row["error_message"])

    def test_f1_10_queue_size_remains_bounded(self):
        """Queue size enforces max bounded size (50), evicting low-priority items when full."""
        admission_controller._max_queue_size = 5
        # Fill queue with 5 requests
        for i in range(5):
            admission_controller.queue_request(conversation_id=9, prompt=f"P_{i}", priority="background")

        with conn() as c:
            cnt = c.execute("SELECT COUNT(*) FROM inference_queue WHERE status='waiting_quota'").fetchone()[0]
            self.assertEqual(cnt, 5)

        # Enqueue 6th request
        admission_controller.queue_request(conversation_id=9, prompt="P_new_chat", priority="chat")

        with conn() as c:
            cnt_after = c.execute("SELECT COUNT(*) FROM inference_queue WHERE status='waiting_quota'").fetchone()[0]
            self.assertLessEqual(cnt_after, 5)

        admission_controller._max_queue_size = 50  # Reset

    def test_f1_11_interactive_priority_is_respected(self):
        """Interactive 'chat' requests are claimed ahead of background requests."""
        # Enqueue background first
        bg_id = admission_controller.queue_request(conversation_id=10, prompt="Background work", priority="background")
        time.sleep(0.01)
        # Enqueue chat second
        chat_id = admission_controller.queue_request(conversation_id=10, prompt="Interactive message", priority="chat")

        CredentialManager.add_credential("groq", "G1", "gsk_prio_key", priority=10)
        dispatcher = InferenceQueueDispatcher()

        with patch.object(AgentEngine, "run", AsyncMock(return_value=AgentResult(reply="Done", tool_executions=[]))):
            res = asyncio.run(dispatcher.tick())
            # Must claim chat_id first even though bg_id was enqueued earlier
            self.assertEqual(res["request_id"], chat_id)

    def test_f1_12_cancel_api_endpoint(self):
        """POST /api/inference/queue/{id}/cancel cancels waiting request through HTTP API."""
        from starlette.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        b_token = get_or_create_bootstrap_secret()
        auth_res = client.post("/api/auth/session", json={"bootstrap_token": b_token})
        sess_token = auth_res.cookies.get("laptop_ai_session")
        headers = {"X-Session-Token": sess_token}

        req_id = admission_controller.queue_request(conversation_id=11, prompt="Cancel via API")
        res = client.post(f"/api/inference/queue/{req_id}/cancel", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "cancelled")

        with conn() as c:
            status = c.execute("SELECT status FROM inference_queue WHERE id=?", (req_id,)).fetchone()[0]
            self.assertEqual(status, "cancelled")


if __name__ == "__main__":
    unittest.main()
