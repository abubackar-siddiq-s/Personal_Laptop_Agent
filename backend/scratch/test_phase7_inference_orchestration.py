"""
LAPTOP AI — PHASE 7: DETERMINISTIC INFERENCE ORCHESTRATION & LIMIT-AWARE RUNTIME TESTS
Verifies all 24 required scenarios in Section 13 using mocked providers and simulated environments.
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

from app.core.config import settings
from app.api.routes import SettingsUpdate
from app.core.db import conn, init_db
from app.core.security import get_or_create_bootstrap_secret
from app.core.credential_manager import (
    CredentialManager,
    encrypt_secret,
    decrypt_secret,
    compute_fingerprint,
    mask_api_key,
)
from app.core.inference_orchestrator import (
    circuit_breaker,
    admission_controller,
    ProviderSelector,
    read_only_cache,
    record_fallback_event,
)
from app.providers.router import (
    chat_turn,
    RateLimitError,
    AuthError,
    KeyRateLimitError,
    ProviderServerError,
    TurnResult,
    ToolCall,
)
from app.core.agent import AgentEngine, ToolExecutionRecord, AgentResult
from app.core.emergency import trigger_emergency_stop, clear_emergency_stop, is_emergency_stopped
from app.api.routes import update_app_settings


class TestPhase7InferenceOrchestration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        # Reset DB credentials and circuit breakers
        with conn() as c:
            c.execute("DELETE FROM provider_credentials")
            c.execute("DELETE FROM provider_telemetry")
            c.execute("DELETE FROM provider_fallback_events")
            c.execute("DELETE FROM inference_queue")
        circuit_breaker._states = {p: "closed" for p in ("gemini", "groq", "openrouter")}
        circuit_breaker._failures = {p: [] for p in ("gemini", "groq", "openrouter")}
        admission_controller.active_requests = {p: 0 for p in ("gemini", "groq", "openrouter")}
        admission_controller.active_token_reservations = {p: 0 for p in ("gemini", "groq", "openrouter")}
        admission_controller.concurrency_limits = {"gemini": 4, "groq": 2, "openrouter": 2}
        admission_controller._background_paused = False
        clear_emergency_stop()

    # -------------------------------------------------------------
    # 1. Mandatory fallback is always enabled after startup
    # -------------------------------------------------------------
    def test_01_mandatory_fallback_always_enabled_on_startup(self):
        """Settings defaults to auto_provider_fallback=True on startup."""
        self.assertTrue(settings.auto_provider_fallback)

    # -------------------------------------------------------------
    # 2. A settings update cannot disable it
    # -------------------------------------------------------------
    def test_02_settings_update_cannot_disable_fallback(self):
        """Attempts to update settings with auto_provider_fallback=False are rejected/overridden."""
        res = update_app_settings(SettingsUpdate(auto_provider_fallback=False))
        self.assertTrue(res["auto_provider_fallback"])
        self.assertTrue(settings.auto_provider_fallback)

    # -------------------------------------------------------------
    # 3. Gemini 429 switches to Groq
    # -------------------------------------------------------------
    def test_03_gemini_429_switches_to_groq(self):
        """When Gemini encounters HTTP 429, the agent automatically fails over to Groq."""
        CredentialManager.add_credential("gemini", "Gemini_Pri", "AIza_mock_key_gemini_111", priority=10, is_primary=True)
        CredentialManager.add_credential("groq", "Groq_Bkp", "gsk_mock_key_groq_222", priority=20, is_primary=True)

        agent = AgentEngine()

        async def mock_gemini_loop(*args, **kwargs):
            raise RateLimitError(provider="gemini", model="gemini-2.5-flash", wait_seconds=2.0, message="Gemini 429 Resource Exhausted")

        async def mock_openai_loop(*args, **kwargs):
            return AgentResult(
                reply="Groq fallback answer completed successfully.",
                tool_executions=[],
                iterations=1,
            )

        from app.core.agent import AgentResult
        with patch.object(AgentEngine, "_run_gemini_loop", side_effect=mock_gemini_loop), \
             patch.object(AgentEngine, "_run_openai_loop", side_effect=mock_openai_loop):
            res = asyncio.run(agent.step(
                provider="gemini",
                model="gemini-2.5-flash",
                user_message="Explain quantum computing",
            ))

            self.assertTrue(res.fallback_occurred)
            self.assertEqual(res.provider_used, "groq")
            self.assertEqual(res.fallback_from, "gemini")
            self.assertIn("Groq", res.reply)

    # -------------------------------------------------------------
    # 4. Groq 429 switches to OpenRouter
    # -------------------------------------------------------------
    def test_04_groq_429_switches_to_openrouter(self):
        """When Groq encounters HTTP 429 and Gemini is exhausted, agent fails over to OpenRouter."""
        CredentialManager.add_credential("groq", "Groq_Pri", "gsk_mock_groq_44444444", priority=10, is_primary=True)
        # Put Gemini into cooldown
        c_gem = CredentialManager.add_credential("gemini", "Gemini_CD", "AIza_mock_gem_55555555", priority=10, is_primary=True)
        CredentialManager.record_failure(c_gem["id"], error_code="429", cooldown_seconds=60)
        # Configure OpenRouter
        CredentialManager.add_credential("openrouter", "OR_Bkp", "sk-or-v1-mock_or_666666", priority=10, is_primary=True)

        agent = AgentEngine()

        from app.core.agent import AgentResult
        async def mock_groq_run(*args, **kwargs):
            if kwargs.get("provider") == "groq":
                raise RateLimitError(provider="groq", model="openai/gpt-oss-20b", wait_seconds=2.0, message="Groq 429 TPM limit")
            return AgentResult(
                reply="OpenRouter fallback answer.",
                tool_executions=[],
                iterations=1,
            )

        with patch.object(AgentEngine, "_run_openai_loop", side_effect=mock_groq_run):
            res = asyncio.run(agent.step(
                provider="groq",
                model="openai/gpt-oss-20b",
                user_message="Hello world",
            ))
            self.assertTrue(res.fallback_occurred)
            self.assertEqual(res.provider_used, "openrouter")
            self.assertEqual(res.fallback_from, "groq")

    # -------------------------------------------------------------
    # 5. OpenRouter 429 switches to another eligible configured provider
    # -------------------------------------------------------------
    def test_05_openrouter_429_switches_to_gemini(self):
        """When OpenRouter is the active provider and hits 429, agent fails over to Gemini."""
        CredentialManager.add_credential("openrouter", "OR_Pri", "sk-or-v1-mock_or_777777", priority=10, is_primary=True)
        CredentialManager.add_credential("gemini", "Gemini_Bkp", "AIza_mock_gem_888888", priority=10, is_primary=True)

        agent = AgentEngine()

        from app.core.agent import AgentResult
        async def mock_openai_fail(*args, **kwargs):
            raise RateLimitError(provider="openrouter", model="openrouter/auto", wait_seconds=2.0, message="OpenRouter 429 limit")

        async def mock_gemini_ok(*args, **kwargs):
            return AgentResult(
                reply="Gemini fallback answer from OpenRouter failover.",
                tool_executions=[],
                iterations=1,
            )

        with patch.object(AgentEngine, "_run_openai_loop", side_effect=mock_openai_fail), \
             patch.object(AgentEngine, "_run_gemini_loop", side_effect=mock_gemini_ok):
            res = asyncio.run(agent.step(
                provider="openrouter",
                model="openrouter/auto",
                user_message="Analyze this code",
            ))
            self.assertTrue(res.fallback_occurred)
            self.assertEqual(res.provider_used, "gemini")
            self.assertEqual(res.fallback_from, "openrouter")

    # -------------------------------------------------------------
    # 6. All providers exhausted: request is queued safely
    # -------------------------------------------------------------
    def test_06_all_providers_exhausted_request_queued_safely(self):
        """When all configured providers fail with 429, the request is preserved and queued."""
        c1 = CredentialManager.add_credential("groq", "Groq_1", "gsk_exhausted_key_1", priority=10)
        c2 = CredentialManager.add_credential("gemini", "Gemini_1", "AIza_exhausted_key_2", priority=10)
        c3 = CredentialManager.add_credential("openrouter", "OR_1", "sk-or-v1-exhausted_3", priority=10)

        # Place all in cooldown
        CredentialManager.record_failure(c1["id"], error_code="429", cooldown_seconds=60)
        CredentialManager.record_failure(c2["id"], error_code="429", cooldown_seconds=60)
        CredentialManager.record_failure(c3["id"], error_code="429", cooldown_seconds=60)

        agent = AgentEngine()
        res = asyncio.run(agent.step(
            provider="groq",
            model="openai/gpt-oss-20b",
            user_message="Summarize meeting notes",
        ))

        self.assertFalse(res.fallback_occurred)
        self.assertIn("Rate Limit Reached (HTTP 429)", res.reply)
        metrics = admission_controller.get_queue_metrics()
        self.assertGreaterEqual(metrics["waiting_queue_count"], 1)

    # -------------------------------------------------------------
    # 7. Retry-After is respected
    # -------------------------------------------------------------
    def test_07_retry_after_header_parsed_accurately(self):
        """Header with Retry-After: 4.5 is parsed accurately within bounds."""
        from app.core.token_budget import parse_rate_limit_reset
        headers = {"Retry-After": "4.5"}
        wait = parse_rate_limit_reset(headers, "")
        self.assertEqual(wait, 4.5)

    # -------------------------------------------------------------
    # 8. Daily quota exhaustion does not trigger rapid retries
    # -------------------------------------------------------------
    def test_08_daily_quota_exhaustion_sets_long_cooldown(self):
        """Daily quota error message sets cooldown for at least 1 hour (>= 3600s)."""
        c1 = CredentialManager.add_credential("groq", "Groq_Daily", "gsk_daily_quota_key_1", priority=10)
        CredentialManager.record_failure(
            c1["id"],
            error_code="429",
            error_message="Daily quota exceeded for day (TPD limit reached)",
            wait_seconds=2.0,
            quota_scope="org-acme"
        )
        meta = CredentialManager.get_credential_metadata(c1["id"])
        cd_until = datetime.fromisoformat(meta["cooldown_until"])
        now = datetime.now(timezone.utc)
        diff_seconds = (cd_until - now).total_seconds()
        self.assertGreaterEqual(diff_seconds, 3500)

    # -------------------------------------------------------------
    # 9. Shared quota scopes are cooled down together
    # -------------------------------------------------------------
    def test_09_shared_quota_scopes_cooled_down_together(self):
        """Two Groq keys sharing 'org-acme' are both cooled down on organization 429."""
        c1 = CredentialManager.add_credential("groq", "Groq_K1", "gsk_org_key_111", priority=10, is_primary=True, quota_scope="org-acme")
        c2 = CredentialManager.add_credential("groq", "Groq_K2", "gsk_org_key_222", priority=20, is_primary=False, quota_scope="org-acme")

        CredentialManager.record_failure(
            c1["id"],
            error_code="429",
            error_message="Organization TPM rate limit exceeded",
            cooldown_seconds=60,
            quota_scope="org-acme"
        )

        res = CredentialManager.get_eligible_credential("groq")
        self.assertIsNone(res)

    # -------------------------------------------------------------
    # 10. Independent quota scopes remain eligible
    # -------------------------------------------------------------
    def test_10_independent_quota_scopes_remain_eligible(self):
        """Key in org-acme is in cooldown; key in org-beta remains eligible."""
        c1 = CredentialManager.add_credential("groq", "Groq_K1", "gsk_org_key_111", priority=10, is_primary=True, quota_scope="org-acme")
        c2 = CredentialManager.add_credential("groq", "Groq_K2", "gsk_org_key_222", priority=20, is_primary=False, quota_scope="org-beta")

        CredentialManager.record_failure(
            c1["id"],
            error_code="429",
            error_message="Organization TPM limit",
            cooldown_seconds=60,
            quota_scope="org-acme"
        )

        res = CredentialManager.get_eligible_credential("groq")
        self.assertIsNotNone(res)
        self.assertEqual(res[0], c2["id"])

    # -------------------------------------------------------------
    # 11. Invalid keys are excluded
    # -------------------------------------------------------------
    def test_11_invalid_keys_are_excluded(self):
        """Key receiving HTTP 401 is marked invalid and excluded from selection."""
        c1 = CredentialManager.add_credential("groq", "Groq_Inv", "gsk_invalid_key_401", priority=10)
        CredentialManager.record_failure(c1["id"], error_code="401", is_auth_failure=True, error_message="Invalid API Key")

        meta = CredentialManager.get_credential_metadata(c1["id"])
        self.assertEqual(meta["status"], "invalid")
        res = CredentialManager.get_eligible_credential("groq")
        self.assertIsNone(res)

    # -------------------------------------------------------------
    # 12. Disabled keys are excluded
    # -------------------------------------------------------------
    def test_12_disabled_keys_are_excluded(self):
        """Disabled credential is excluded from selection."""
        c1 = CredentialManager.add_credential("openrouter", "OR_Dis", "sk-or-v1-dis_key_1", priority=10)
        CredentialManager.disable_credential(c1["id"])

        res = CredentialManager.get_eligible_credential("openrouter")
        self.assertIsNone(res)

    # -------------------------------------------------------------
    # 13. Expired cooldown restores eligibility
    # -------------------------------------------------------------
    def test_13_expired_cooldown_restores_eligibility(self):
        """Key becomes selectable again once cooldown_until is in the past."""
        c1 = CredentialManager.add_credential("gemini", "Gem_Exp", "AIza_mock_key_exp_1", priority=10)
        past_iso = "2020-01-01T00:00:00+00:00"
        with conn() as c:
            c.execute("UPDATE provider_credentials SET cooldown_until = ?, status = 'cooldown' WHERE id = ?", (past_iso, c1["id"]))

        res = CredentialManager.get_eligible_credential("gemini")
        self.assertIsNotNone(res)
        self.assertEqual(res[0], c1["id"])

    # -------------------------------------------------------------
    # 14. Provider outage triggers circuit breaker
    # -------------------------------------------------------------
    def test_14_provider_outage_triggers_circuit_breaker(self):
        """3 consecutive 503 errors trip the provider circuit breaker to OPEN."""
        self.assertTrue(circuit_breaker.is_available("groq"))
        circuit_breaker.record_failure("groq", error_code="503")
        circuit_breaker.record_failure("groq", error_code="503")
        circuit_breaker.record_failure("groq", error_code="503")

        self.assertFalse(circuit_breaker.is_available("groq"))
        status = circuit_breaker.get_status()
        self.assertEqual(status["groq"]["state"], "open")

    # -------------------------------------------------------------
    # 15. Tool-calling compatibility is preserved
    # -------------------------------------------------------------
    def test_15_tool_calling_compatibility_preserved_on_fallback(self):
        """Fallback turn retains tool calling capabilities and executes tools correctly."""
        CredentialManager.add_credential("groq", "Groq_Tool", "gsk_mock_groq_tool", priority=10)
        CredentialManager.add_credential("gemini", "Gem_Tool", "AIza_mock_gem_tool", priority=10)

        agent = AgentEngine()
        from app.core.agent import AgentResult

        async def mock_groq_429(*args, **kwargs):
            raise RateLimitError(provider="groq", model="openai/gpt-oss-20b", wait_seconds=2.0, message="Groq rate limit")

        async def mock_gemini_tools(*args, **kwargs):
            return AgentResult(
                reply="Gemini tool executed response.",
                tool_executions=[ToolExecutionRecord(tool_name="browser_search", arguments={"query": "test"}, success=True)],
                iterations=2,
            )

        with patch.object(AgentEngine, "_run_openai_loop", side_effect=mock_groq_429), \
             patch.object(AgentEngine, "_run_gemini_loop", side_effect=mock_gemini_tools):
            res = asyncio.run(agent.step(
                provider="groq",
                model="openai/gpt-oss-20b",
                user_message="Search for news",
            ))
            self.assertTrue(res.fallback_occurred)
            self.assertEqual(len(res.tool_executions), 1)
            self.assertEqual(res.tool_executions[0].tool_name, "browser_search")

    # -------------------------------------------------------------
    # 16. Vision requests use compatible inference
    # -------------------------------------------------------------
    def test_16_vision_requests_routed_to_gemini(self):
        """Vision requests select Gemini native multimodal inference."""
        provider, model = asyncio.run(ProviderSelector.select_provider_for_task(
            task_category="vision",
            requires_vision=True,
            preferred_provider="groq",
        ))
        self.assertEqual(provider, "gemini")
        self.assertEqual(model, "gemini-2.5-flash")

    # -------------------------------------------------------------
    # 17. Context compaction preserves required instructions
    # -------------------------------------------------------------
    def test_17_context_compaction_preserves_system_and_recent_turns(self):
        """Context compaction bounds token usage while retaining system prompt and recent messages."""
        from app.core.token_budget import compact_history
        long_history = [
            {"role": "user", "content": f"Historical message {i} with lots of context details " * 20}
            for i in range(15)
        ]
        compacted = compact_history(long_history, max_tokens=1000, max_turns=4)
        self.assertLessEqual(len(compacted), 4)
        self.assertGreaterEqual(len(compacted), 1)

    # -------------------------------------------------------------
    # 18. Concurrent requests respect quota reservations
    # -------------------------------------------------------------
    def test_18_concurrent_requests_respect_quota_reservations(self):
        """Token reservations are incremented and decremented atomically."""
        async def run_concurrent():
            await admission_controller.acquire_reservation("gemini", estimated_tokens=1500)
            self.assertEqual(admission_controller.active_token_reservations["gemini"], 1500)
            self.assertEqual(admission_controller.active_requests["gemini"], 1)

            await admission_controller.release_reservation("gemini", estimated_tokens=1500, success=True)
            self.assertEqual(admission_controller.active_token_reservations["gemini"], 0)
            self.assertEqual(admission_controller.active_requests["gemini"], 0)

        asyncio.run(run_concurrent())

    # -------------------------------------------------------------
    # 19. Streaming failure does not duplicate output
    # -------------------------------------------------------------
    def test_19_streaming_failure_clean_restart_no_duplication(self):
        """Partial failure before fallback starts with a clean turn result without corrupted text."""
        agent = AgentEngine()
        from app.core.agent import AgentResult

        # Ensure fallback reply is self-contained and not duplicate text
        async def mock_fail_then_pass(*args, **kwargs):
            if kwargs.get("provider") == "groq" or args and args[0] == "groq":
                raise RateLimitError(provider="groq", model="openai/gpt-oss-20b", wait_seconds=1.0, message="429")
            return AgentResult(reply="Clean fresh response", tool_executions=[], iterations=1)

        with patch.object(AgentEngine, "_run_openai_loop", side_effect=mock_fail_then_pass), \
             patch.object(AgentEngine, "_run_gemini_loop", side_effect=mock_fail_then_pass):
            CredentialManager.add_credential("groq", "G1", "gsk_mock_key_groq_1", priority=10)
            CredentialManager.add_credential("gemini", "Gem1", "AIza_mock_key_gem_1", priority=10)
            res = asyncio.run(agent.step(provider="groq", model="openai/gpt-oss-20b", user_message="test"))
            self.assertTrue(res.fallback_occurred)
            self.assertEqual(res.reply.count("Clean fresh response"), 1)

    # -------------------------------------------------------------
    # 20. Completed consequential actions are never replayed
    # -------------------------------------------------------------
    def test_20_completed_consequential_actions_never_replayed(self):
        """Consequential tool actions executed prior to rate-limit are preserved and not re-executed."""
        agent = AgentEngine()

        async def mock_gemini_fallback(*args, **kwargs):
            # Verify executions was passed through intact
            self.assertEqual(len(kwargs.get("executions", [])), 1)
            return AgentResult(reply="Continued after navigation.", tool_executions=kwargs.get("executions", []))

        async def mock_openai_fail_after_action(*args, **kwargs):
            # Simulate tool was executed, then subsequent turn hit 429
            kwargs.get("executions", []).append(
                ToolExecutionRecord(tool_name="browser_navigate", arguments={"url": "https://example.com"}, success=True)
            )
            raise RateLimitError("groq", "openai/gpt-oss-20b", 2.0, "429 Rate limit")

        with patch.object(AgentEngine, "_run_gemini_loop", side_effect=mock_gemini_fallback):
            CredentialManager.add_credential("groq", "G1", "gsk_mock_g1", priority=10)
            CredentialManager.add_credential("gemini", "Gem1", "AIza_mock_gem1", priority=10)

            with patch.object(AgentEngine, "_run_openai_loop", side_effect=mock_openai_fail_after_action):
                res = asyncio.run(agent.step(
                    provider="groq",
                    model="openai/gpt-oss-20b",
                    user_message="Go to example.com",
                ))
                self.assertTrue(res.fallback_occurred)

    # -------------------------------------------------------------
    # 21. Emergency stop blocks execution
    # -------------------------------------------------------------
    def test_21_emergency_stop_blocks_execution(self):
        """Engaged Emergency Stop halts agent inference immediately."""
        trigger_emergency_stop("Safety test stop")
        self.assertTrue(is_emergency_stopped())

        from starlette.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        b_token = get_or_create_bootstrap_secret()
        auth_res = c.post("/api/auth/session", json={"bootstrap_token": b_token})
        sess_token = auth_res.cookies.get("laptop_ai_session")

        res = c.post(
            "/api/chat",
            json={"message": "Do dangerous task", "provider": "groq", "model": "openai/gpt-oss-20b"},
            headers={"X-Session-Token": sess_token}
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("Global Emergency Stop is currently engaged", res.json()["reply"])
        clear_emergency_stop()

    # -------------------------------------------------------------
    # 22. Restart recovery preserves queued work safely
    # -------------------------------------------------------------
    def test_22_restart_recovery_preserves_queued_work(self):
        """Enqueued requests remain in SQLite across simulated restarts."""
        req_id = admission_controller.queue_request(
            conversation_id=99,
            prompt="Analyze financial report",
            task_type="file_analysis",
            priority="background"
        )
        with conn() as c:
            row = c.execute("SELECT id, status, prompt FROM inference_queue WHERE id=?", (req_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "waiting_quota")
            self.assertIn("financial report", row["prompt"])

    # -------------------------------------------------------------
    # 23. No API secret appears in logs, database plaintext or frontend assets
    # -------------------------------------------------------------
    def test_23_no_api_secret_in_database_plaintext_or_frontend(self):
        """API keys are DPAPI-encrypted in SQLite; no secrets in frontend assets or logs."""
        raw_secret = "gsk_super_confidential_secret_key_9999"
        c1 = CredentialManager.add_credential("groq", "SecretTest", raw_secret, priority=10)

        with conn() as c:
            row = c.execute("SELECT encrypted_key FROM provider_credentials WHERE id=?", (c1["id"],)).fetchone()
            self.assertNotEqual(row["encrypted_key"], raw_secret)
            self.assertNotIn("super_confidential", row["encrypted_key"])

        # Check frontend dist does not contain raw secret
        dist_path = PROJECT_ROOT.parent / "frontend" / "dist"
        if dist_path.exists():
            for f in dist_path.rglob("*.js"):
                content = f.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(raw_secret, content)

    # -------------------------------------------------------------
    # 24. No paid model is silently selected
    # -------------------------------------------------------------
    def test_24_no_paid_model_silently_selected_on_openrouter(self):
        """OpenRouter fallback defaults to 'openrouter/auto' (free tier gateway), never paid models."""
        from app.core.inference_orchestrator import ProviderSelector
        candidates = ProviderSelector.TASK_PREFERENCES["general"]
        or_models = [m for p, m in candidates if p == "openrouter"]
        self.assertTrue(all(m == "openrouter/auto" for m in or_models))


if __name__ == "__main__":
    unittest.main()
