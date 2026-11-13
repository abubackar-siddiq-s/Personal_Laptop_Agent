import os
import sys
import time
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.db import conn
from app.core.credential_manager import (
    CredentialManager,
    encrypt_secret,
    decrypt_secret,
    mask_api_key,
)
from app.providers.router import (
    chat_turn,
    RateLimitError,
    AuthError,
    KeyRateLimitError,
    ProviderServerError,
    TurnResult,
)
from app.core.approval import ApprovalLifecycle
from app.core.config import settings


class AuditAcceptanceVerification(unittest.TestCase):
    def setUp(self):
        with conn() as c:
            c.execute("DELETE FROM provider_credentials WHERE key_name LIKE 'AUDIT_%'")
            c.execute("DELETE FROM provider_telemetry")
            c.execute("DELETE FROM approvals WHERE operation_id LIKE 'audit_op_%'")

    def tearDown(self):
        with conn() as c:
            c.execute("DELETE FROM provider_credentials WHERE key_name LIKE 'AUDIT_%'")
            c.execute("DELETE FROM provider_telemetry")
            c.execute("DELETE FROM approvals WHERE operation_id LIKE 'audit_op_%'")

    # =========================================================================
    # SECTION 3: Quota Scope Correctness Tests
    # =========================================================================

    def test_quota_scope_gemini_shared_project(self):
        """Gemini: Multiple keys belonging to the same project share quota. When one is exhausted, all are cooled down without redundant cycling."""
        k1 = CredentialManager.add_credential("gemini", "AUDIT_Gem_P1", "AIza_audit_gem_p1_1111", priority=10, is_primary=True, quota_scope="project-gemini-alpha")
        k2 = CredentialManager.add_credential("gemini", "AUDIT_Gem_P2", "AIza_audit_gem_p2_2222", priority=20, is_primary=False, quota_scope="project-gemini-alpha")
        k3 = CredentialManager.add_credential("gemini", "AUDIT_Gem_P3", "AIza_audit_gem_p3_3333", priority=30, is_primary=False, quota_scope="project-gemini-beta")

        # Simulate shared project limit 429
        CredentialManager.record_failure(k1["id"], error_code="429", error_message="Resource has been exhausted: quota exceeded for project project-gemini-alpha", cooldown_seconds=60, quota_scope="project-gemini-alpha")

        m1 = CredentialManager.get_credential_metadata(k1["id"])
        m2 = CredentialManager.get_credential_metadata(k2["id"])
        m3 = CredentialManager.get_credential_metadata(k3["id"])

        # k1 and k2 must both be in cooldown
        self.assertEqual(m1["status"], "cooldown")
        self.assertEqual(m2["status"], "cooldown")
        # k3 in project-gemini-beta must remain active
        self.assertEqual(m3["status"], "active")

        # Next eligible credential must skip k2 directly to k3
        selected = CredentialManager.get_eligible_credential("gemini")
        self.assertEqual(selected[0], k3["id"])

    def test_quota_scope_groq_shared_org(self):
        """Groq: Multiple keys belonging to same organization share TPM quota. Shared 429 triggers scope cooldown; individual key 401 only invalidates that single key."""
        k1 = CredentialManager.add_credential("groq", "AUDIT_Groq_OrgA_1", "gsk_audit_orga_1111111", priority=10, is_primary=True, quota_scope="org-acme-corp")
        k2 = CredentialManager.add_credential("groq", "AUDIT_Groq_OrgA_2", "gsk_audit_orga_2222222", priority=20, is_primary=False, quota_scope="org-acme-corp")

        # 1. Key 1 fails with 401: only k1 invalidated, k2 remains active
        CredentialManager.record_failure(k1["id"], error_code="401", is_auth_failure=True, error_message="Invalid API Key")
        self.assertEqual(CredentialManager.get_credential_metadata(k1["id"])["status"], "invalid")
        self.assertEqual(CredentialManager.get_credential_metadata(k2["id"])["status"], "active")

        # 2. Key 2 hits org rate limit: sets cooldown on org-acme-corp
        CredentialManager.record_failure(k2["id"], error_code="429", error_message="Organization TPM rate limit exceeded", cooldown_seconds=60, quota_scope="org-acme-corp")
        self.assertEqual(CredentialManager.get_credential_metadata(k2["id"])["status"], "cooldown")

        # 3. No unnecessary cycling: router raises RateLimitError rather than trying cooled-down keys
        selected = CredentialManager.get_eligible_credential("groq")
        self.assertIsNone(selected)

    def test_quota_scope_openrouter_shared_account(self):
        """OpenRouter: Account-level free-model limits cool down keys sharing account scope; individual auth failure only affects one credential."""
        k1 = CredentialManager.add_credential("openrouter", "AUDIT_OR_Acc1_Key1", "sk-or-v1-audit_acc1_1", priority=10, is_primary=True, quota_scope="account-dev-team")
        k2 = CredentialManager.add_credential("openrouter", "AUDIT_OR_Acc1_Key2", "sk-or-v1-audit_acc1_2", priority=20, is_primary=False, quota_scope="account-dev-team")
        k3 = CredentialManager.add_credential("openrouter", "AUDIT_OR_Acc2_Key1", "sk-or-v1-audit_acc2_1", priority=30, is_primary=False, quota_scope="account-personal")

        # Shared account limit
        CredentialManager.record_failure(k1["id"], error_code="429", error_message="Account limit reached on free models", cooldown_seconds=120, quota_scope="account-dev-team")
        self.assertEqual(CredentialManager.get_credential_metadata(k1["id"])["status"], "cooldown")
        self.assertEqual(CredentialManager.get_credential_metadata(k2["id"])["status"], "cooldown")
        self.assertEqual(CredentialManager.get_credential_metadata(k3["id"])["status"], "active")

        # k3 is selected directly
        selected = CredentialManager.get_eligible_credential("openrouter")
        self.assertEqual(selected[0], k3["id"])

    # =========================================================================
    # SECTION 4: Error Classification & Rotation Trigger Tests
    # =========================================================================

    def test_error_classification_401_triggers_rotation(self):
        """HTTP 401 triggers credential rotation and marks key invalid."""
        k1 = CredentialManager.add_credential("groq", "AUDIT_Groq_401", "gsk_audit_401_key", priority=10, is_primary=True)
        k2 = CredentialManager.add_credential("groq", "AUDIT_Groq_200", "gsk_audit_200_key", priority=20, is_primary=False)

        attempts = []
        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            attempts.append(key)
            if key == "gsk_audit_401_key":
                raise AuthError(provider="groq", message="HTTP 401 Invalid Key")
            return TurnResult(content="OK_FROM_KEY_2")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            res = asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "hi"}]))

        self.assertEqual(res.content, "OK_FROM_KEY_2")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(CredentialManager.get_credential_metadata(k1["id"])["status"], "invalid")

    def test_error_classification_429_triggers_rotation_to_independent_backup(self):
        """HTTP 429 triggers credential rotation to backup key with independent quota."""
        k1 = CredentialManager.add_credential("groq", "AUDIT_Groq_429_A", "gsk_audit_429_key_a", priority=10, is_primary=True, quota_scope="org-a")
        k2 = CredentialManager.add_credential("groq", "AUDIT_Groq_429_B", "gsk_audit_429_key_b", priority=20, is_primary=False, quota_scope="org-b")

        attempts = []
        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            attempts.append(key)
            if key == "gsk_audit_429_key_a":
                raise KeyRateLimitError(provider="groq", model="openai/gpt-oss-20b", wait_seconds=30.0, is_shared_quota=False, message="HTTP 429 TPM limit")
            return TurnResult(content="OK_FROM_INDEPENDENT_ORG_B")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            res = asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "hi"}]))

        self.assertEqual(res.content, "OK_FROM_INDEPENDENT_ORG_B")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(CredentialManager.get_credential_metadata(k1["id"])["status"], "cooldown")

    def test_error_classification_500_502_503_504_server_errors(self):
        """HTTP 5xx server errors record consecutive failures and rotate after threshold."""
        k1 = CredentialManager.add_credential("groq", "AUDIT_Groq_500", "gsk_audit_500_key", priority=10, is_primary=True)
        k2 = CredentialManager.add_credential("groq", "AUDIT_Groq_500_B", "gsk_audit_500_key_b", priority=20, is_primary=False)

        attempts = []
        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            attempts.append(key)
            if key == "gsk_audit_500_key":
                raise ProviderServerError(status_code=503, message="Groq Service Unavailable (503)")
            return TurnResult(content="OK_FROM_FAILOVER_KEY")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            res = asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "hi"}]))

        self.assertEqual(res.content, "OK_FROM_FAILOVER_KEY")
        self.assertEqual(len(attempts), 2)

    def test_error_classification_invalid_model_does_NOT_rotate_key(self):
        """Non-credential errors (e.g. invalid model, HTTP 404, unsupported model) must NOT rotate API keys."""
        k1 = CredentialManager.add_credential("groq", "AUDIT_Groq_Model", "gsk_audit_good_key", priority=10, is_primary=True)
        k2 = CredentialManager.add_credential("groq", "AUDIT_Groq_Backup", "gsk_audit_backup_key", priority=20, is_primary=False)

        attempts = []
        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            attempts.append(key)
            # Provider returns 404 model not found as generic RuntimeError
            raise RuntimeError("Groq API error (404): Model 'non-existent-model' not found")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            with self.assertRaises(RuntimeError):
                asyncio.run(chat_turn("groq", "non-existent-model", [{"role": "user", "content": "hi"}]))

        # Must have stopped after first attempt without cycling to backup keys
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0], "gsk_audit_good_key")
        # Key status must remain active (NOT marked invalid or in cooldown)
        self.assertEqual(CredentialManager.get_credential_metadata(k1["id"])["status"], "active")

    def test_error_classification_invalid_request_does_NOT_rotate_key(self):
        """Malformed requests (e.g. bad schema, prompt violation, HTTP 400) must NOT rotate API keys."""
        k1 = CredentialManager.add_credential("groq", "AUDIT_Groq_Req", "gsk_audit_good_key_req", priority=10, is_primary=True)

        attempts = []
        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            attempts.append(key)
            raise RuntimeError("Groq API error (400): Invalid json body in function calling arguments")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            with self.assertRaises(RuntimeError):
                asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "hi"}]))

        self.assertEqual(len(attempts), 1)
        self.assertEqual(CredentialManager.get_credential_metadata(k1["id"])["status"], "active")

    # =========================================================================
    # SECTION 5: Metadata Testing Behavior
    # =========================================================================

    def test_metadata_testing_distinguishes_outcomes(self):
        """Metadata testing distinguishes auth validity, 429 quota exhaustion, and outages without claiming inference availability."""
        # Test simulated 200 OK
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": [{"id": "llama-3.3-70b-versatile"}]}
            mock_get.return_value = mock_resp

            res = asyncio.run(CredentialManager.test_raw_key("groq", "gsk_valid_test_key_12345"))
            self.assertTrue(res["ok"])
            self.assertEqual(res["status"], "valid")
            self.assertIn("latency_ms", res)

        # Test simulated 429 Quota Exhausted on control plane
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 429
            mock_resp.text = "Rate limit exceeded"
            mock_get.return_value = mock_resp

            res = asyncio.run(CredentialManager.test_raw_key("groq", "gsk_rate_limited_key"))
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "quota_exhausted")

        # Test simulated 503 Provider Outage
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 503
            mock_resp.text = "Service Unavailable"
            mock_get.return_value = mock_resp

            res = asyncio.run(CredentialManager.test_raw_key("groq", "gsk_outage_key"))
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "provider_unavailable")

    # =========================================================================
    # SECTION 6: Consequential Operation Safety
    # =========================================================================

    def test_consequential_operation_safety_before_tool_execution(self):
        """Failure before tool execution: operation is still pending/draft and not executed."""
        op_id = f"audit_op_{int(time.time()*1000)}_before"
        req = ApprovalLifecycle.create_request("windows_cmd", {"cmd": "del temp.txt"}, operation_id=op_id)
        self.assertEqual(req["status"], "pending")

        # Re-requesting returns the same pending record without executing
        req2 = ApprovalLifecycle.create_request("windows_cmd", {"cmd": "del temp.txt"}, operation_id=op_id)
        self.assertEqual(req2["status"], "pending")
        self.assertTrue(req2.get("deduplicated"))

    def test_consequential_operation_safety_during_execution_crash_recovery(self):
        """Failure during tool execution: operation in 'executing' is recovered to 'failed' on restart and NOT re-executed."""
        op_id = f"audit_op_{int(time.time()*1000)}_during"
        req = ApprovalLifecycle.create_request("windows_cmd", {"cmd": "format C:"}, operation_id=op_id)
        aid = req["id"]

        # Simulate execution started but server crashed
        with conn() as c:
            c.execute("UPDATE approvals SET status='executing' WHERE id=?", (aid,))

        # Startup recovery
        recovered = ApprovalLifecycle.recover_interrupted_executions()
        self.assertGreaterEqual(recovered, 1)

        # Record is now marked 'failed' requiring manual review
        appr = ApprovalLifecycle.get_approval(aid)
        self.assertEqual(appr["status"], "failed")
        self.assertIn("Interrupted", appr["error"])

    def test_consequential_operation_safety_after_execution_key_rotation(self):
        """Failure after tool execution (e.g. key rotation during summary generation): completed action is NEVER re-executed."""
        op_id = f"audit_op_{int(time.time()*1000)}_after"
        req = ApprovalLifecycle.create_request("desktop_mouse_click", {"x": 500, "y": 300}, operation_id=op_id)
        aid = req["id"]

        # Mark executed with result
        with conn() as c:
            c.execute("UPDATE approvals SET status='executed', result='\"Clicked successfully\"' WHERE id=?", (aid,))

        # When the agent loop retries inference with backup key, re-evaluating the tool returns cached result
        req_retry = ApprovalLifecycle.create_request("desktop_mouse_click", {"x": 500, "y": 300}, operation_id=op_id)
        self.assertEqual(req_retry["status"], "executed")
        self.assertTrue(req_retry.get("reused"))
        self.assertEqual(req_retry.get("result"), "Clicked successfully")


if __name__ == "__main__":
    unittest.main()

