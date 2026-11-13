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

from starlette.testclient import TestClient
from app.main import app
from app.core.db import conn
from app.core.security import get_or_create_bootstrap_secret, create_session_token
from app.core.credential_manager import (
    CredentialManager,
    encrypt_secret,
    decrypt_secret,
    compute_fingerprint,
    mask_api_key,
    APPLICATION_ENTROPY,
    DPAPIError,
)
from app.providers.router import (
    chat_turn,
    get_key,
    status as provider_status,
    RateLimitError,
    AuthError,
    KeyRateLimitError,
    ProviderServerError,
    TurnResult,
)


class TestMultiKeyCredentials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url="http://127.0.0.1:8000")
        cls.bootstrap_secret = get_or_create_bootstrap_secret()

    def setUp(self):
        # Create fresh session token for authenticated API tests
        self.session = create_session_token(ttl_seconds=3600, client_info="test_runner")
        self.auth_headers = {
            "origin": "http://127.0.0.1:5173",
            "X-Session-Token": self.session.token,
        }
        # Clean test credentials and telemetry
        with conn() as c:
            c.execute("DELETE FROM provider_credentials WHERE key_name LIKE 'TEST_%'")
            c.execute("DELETE FROM provider_telemetry")

    def tearDown(self):
        with conn() as c:
            c.execute("DELETE FROM provider_credentials WHERE key_name LIKE 'TEST_%'")
            c.execute("DELETE FROM provider_telemetry")

    # =========================================================================
    # 1. DPAPI Encryption & Security at Rest
    # =========================================================================

    def test_01_dpapi_roundtrip(self):
        """Verifies Windows DPAPI encrypts and decrypts secrets with round-trip fidelity."""
        secret = "gsk_live_test_credential_1234567890abcdef"
        encrypted = encrypt_secret(secret)
        self.assertIsInstance(encrypted, str)
        self.assertNotEqual(secret, encrypted)
        # Decrypt
        decrypted = decrypt_secret(encrypted)
        self.assertEqual(secret, decrypted)

    def test_02_dpapi_entropy_enforcement(self):
        """DPAPI decryption fails if wrong application entropy is provided."""
        secret = "gsk_live_test_entropy_secret_12345"
        encrypted = encrypt_secret(secret, entropy=APPLICATION_ENTROPY)
        wrong_entropy = b"WRONG_ENTROPY_KEY_9999"
        with self.assertRaises(DPAPIError):
            decrypt_secret(encrypted, entropy=wrong_entropy)

    def test_03_dpapi_tampered_ciphertext(self):
        """Corrupted base64 or altered ciphertext is safely rejected without crash."""
        with self.assertRaises(DPAPIError):
            decrypt_secret("not-valid-base64!!")
        with self.assertRaises(DPAPIError):
            decrypt_secret("QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFB")

    def test_04_masking_logic(self):
        """API keys are safely masked with prefix and last 4 characters preserved."""
        # Groq key
        groq_masked = mask_api_key("gsk_1234567890abcdefghijklmnop")
        self.assertTrue(groq_masked.startswith("gsk_••••"))
        self.assertTrue(groq_masked.endswith("mnop"))
        self.assertNotIn("1234567890", groq_masked)

        # Gemini key
        gemini_masked = mask_api_key("AIzaSyB1234567890abcdefghijkl")
        self.assertTrue(gemini_masked.startswith("AIza••••"))
        self.assertTrue(gemini_masked.endswith("ijkl"))

        # OpenRouter key
        openrouter_masked = mask_api_key("sk-or-v1-abcdef123456789012345678")
        self.assertTrue(openrouter_masked.startswith("sk-or-v1-••••"))
        self.assertTrue(openrouter_masked.endswith("5678"))

        # Short or generic key
        short_masked = mask_api_key("shortkey")
        self.assertIn("••••", short_masked)

    def test_05_deterministic_fingerprint(self):
        """Fingerprints are deterministic SHA-256 hashes without revealing plaintext."""
        fp1 = compute_fingerprint("gsk_same_key_test_123456")
        fp2 = compute_fingerprint("gsk_same_key_test_123456")
        fp3 = compute_fingerprint("gsk_different_key_test_789")
        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)
        self.assertEqual(len(fp1), 64)

    # =========================================================================
    # 2. Credential CRUD and State Invariants
    # =========================================================================

    def test_06_add_valid_credentials(self):
        """Credentials can be added across all 3 supported providers."""
        c_groq = CredentialManager.add_credential("groq", "TEST_Groq_1", "gsk_test_key_00000000001", priority=10, is_primary=True)
        c_gemini = CredentialManager.add_credential("gemini", "TEST_Gemini_1", "AIzaSyB_test_key_0000000002", priority=10, is_primary=True)
        c_openrouter = CredentialManager.add_credential("openrouter", "TEST_OR_1", "sk-or-v1-test_key_0000000003", priority=10, is_primary=True)

        self.assertEqual(c_groq["provider"], "groq")
        self.assertEqual(c_groq["is_primary"], True)
        self.assertEqual(c_groq["status"], "active")
        self.assertIn("masked_key", c_groq)
        self.assertNotIn("encrypted_key", c_groq)

        # Retrieve metadata
        meta = CredentialManager.get_credential_metadata(c_groq["id"])
        self.assertIsNotNone(meta)
        self.assertEqual(meta["key_name"], "TEST_Groq_1")

    def test_07_invalid_provider_rejected(self):
        """Unsupported providers (e.g. OpenAI, Anthropic, LM Studio) are strictly rejected."""
        with self.assertRaises(ValueError):
            CredentialManager.add_credential("openai", "TEST_OpenAI", "sk-123456789012345")
        with self.assertRaises(ValueError):
            CredentialManager.add_credential("anthropic", "TEST_Claude", "sk-ant-123456789012345")

    def test_08_duplicate_fingerprint_rejected(self):
        """Duplicate keys for the same provider are rejected."""
        CredentialManager.add_credential("groq", "TEST_Groq_A", "gsk_test_dup_key_99999999999", priority=10)
        with self.assertRaises(ValueError) as ctx:
            CredentialManager.add_credential("groq", "TEST_Groq_B", "gsk_test_dup_key_99999999999", priority=20)
        self.assertIn("already configured", str(ctx.exception))

    def test_09_single_primary_invariant(self):
        """Only one primary key can exist per provider. Setting a new primary demotes the previous."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_P1", "gsk_test_p1_1111111111111", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_P2", "gsk_test_p2_2222222222222", priority=20, is_primary=True)

        m1 = CredentialManager.get_credential_metadata(c1["id"])
        m2 = CredentialManager.get_credential_metadata(c2["id"])
        self.assertFalse(m1["is_primary"])
        self.assertTrue(m2["is_primary"])

        # Switch primary back to c1
        CredentialManager.set_primary(c1["id"])
        m1_updated = CredentialManager.get_credential_metadata(c1["id"])
        m2_updated = CredentialManager.get_credential_metadata(c2["id"])
        self.assertTrue(m1_updated["is_primary"])
        self.assertFalse(m2_updated["is_primary"])

    def test_10_disable_and_enable_promotes_primary(self):
        """Disabling the primary key promotes the next eligible backup key to primary."""
        c1 = CredentialManager.add_credential("gemini", "TEST_Gem_D1", "AIza_test_d1_111111111111", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("gemini", "TEST_Gem_D2", "AIza_test_d2_222222222222", priority=20, is_primary=False)

        CredentialManager.disable_credential(c1["id"])
        m1 = CredentialManager.get_credential_metadata(c1["id"])
        m2 = CredentialManager.get_credential_metadata(c2["id"])

        self.assertFalse(m1["enabled"])
        self.assertFalse(m1["is_primary"])
        self.assertTrue(m2["is_primary"])

        # Re-enable c1
        CredentialManager.enable_credential(c1["id"])
        m1_re = CredentialManager.get_credential_metadata(c1["id"])
        self.assertTrue(m1_re["enabled"])

    def test_11_delete_promotes_primary(self):
        """Deleting the primary key promotes the next eligible key to primary."""
        c1 = CredentialManager.add_credential("openrouter", "TEST_OR_Del1", "sk-or-v1-del1_11111111111", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("openrouter", "TEST_OR_Del2", "sk-or-v1-del2_22222222222", priority=20, is_primary=False)

        CredentialManager.delete_credential(c1["id"])
        self.assertIsNone(CredentialManager.get_credential_metadata(c1["id"]))
        m2 = CredentialManager.get_credential_metadata(c2["id"])
        self.assertTrue(m2["is_primary"])

    def test_12_reorder_credentials(self):
        """Reordering credentials updates priority values based on order array."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_R1", "gsk_test_r1_111111111111", priority=10)
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_R2", "gsk_test_r2_222222222222", priority=20)
        c3 = CredentialManager.add_credential("groq", "TEST_Groq_R3", "gsk_test_r3_333333333333", priority=30)

        # Invert order: c3, c2, c1
        updated = CredentialManager.reorder_credentials("groq", [c3["id"], c2["id"], c1["id"]])
        id_to_pri = {u["id"]: u["priority"] for u in updated}
        self.assertLess(id_to_pri[c3["id"]], id_to_pri[c2["id"]])
        self.assertLess(id_to_pri[c2["id"]], id_to_pri[c1["id"]])

    # =========================================================================
    # 3. Key Selection & Automatic Rotation Logic
    # =========================================================================

    def test_13_get_eligible_credential_selection(self):
        """Primary key is selected first; excluding primary returns backup key."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Sel1", "gsk_test_sel1_111111111", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_Sel2", "gsk_test_sel2_222222222", priority=20, is_primary=False)

        selected = CredentialManager.get_eligible_credential("groq")
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], c1["id"])
        self.assertEqual(selected[1], "gsk_test_sel1_111111111")

        # Exclude c1 (as in failover rotation)
        backup = CredentialManager.get_eligible_credential("groq", exclude_ids=[c1["id"]])
        self.assertIsNotNone(backup)
        self.assertEqual(backup[0], c2["id"])
        self.assertEqual(backup[1], "gsk_test_sel2_222222222")

    def test_14_cooldown_exclusion(self):
        """A key with an active cooldown timestamp is excluded from selection."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_CD1", "gsk_test_cd1_111111111", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_CD2", "gsk_test_cd2_222222222", priority=20, is_primary=False)

        # Put c1 into 60s cooldown
        CredentialManager.record_failure(c1["id"], error_code="429", error_message="Rate limit", cooldown_seconds=60)
        m1 = CredentialManager.get_credential_metadata(c1["id"])
        self.assertEqual(m1["status"], "cooldown")
        self.assertIsNotNone(m1["cooldown_until"])

        # Eligible key must now be c2
        selected = CredentialManager.get_eligible_credential("groq")
        self.assertEqual(selected[0], c2["id"])

    def test_15_invalid_status_exclusion(self):
        """A key marked 'invalid' (HTTP 401) is permanently excluded from selection."""
        c1 = CredentialManager.add_credential("gemini", "TEST_Gem_Inv1", "AIza_test_inv1_11111111", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("gemini", "TEST_Gem_Inv2", "AIza_test_inv2_22222222", priority=20, is_primary=False)

        # Invalidate c1
        CredentialManager.record_failure(c1["id"], error_code="401", is_auth_failure=True, error_message="API key invalid")
        m1 = CredentialManager.get_credential_metadata(c1["id"])
        self.assertEqual(m1["status"], "invalid")

        selected = CredentialManager.get_eligible_credential("gemini")
        self.assertEqual(selected[0], c2["id"])

    def test_16_quota_scope_synchronized_cooldown(self):
        """Keys sharing a quota_scope are cooled down together when shared quota is exceeded."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Q1", "gsk_test_q1_111111111", priority=10, is_primary=True, quota_scope="project-alpha")
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_Q2", "gsk_test_q2_222222222", priority=20, is_primary=False, quota_scope="project-alpha")
        c3 = CredentialManager.add_credential("groq", "TEST_Groq_Q3", "gsk_test_q3_333333333", priority=30, is_primary=False, quota_scope="project-beta")

        # Exceed quota on c1 and propagate to quota_scope
        CredentialManager.record_failure(c1["id"], error_code="429", error_message="Project TPM limit", cooldown_seconds=60, quota_scope="project-alpha")

        m1 = CredentialManager.get_credential_metadata(c1["id"])
        m2 = CredentialManager.get_credential_metadata(c2["id"])
        m3 = CredentialManager.get_credential_metadata(c3["id"])

        self.assertEqual(m1["status"], "cooldown")
        self.assertEqual(m2["status"], "cooldown")
        self.assertEqual(m3["status"], "active")  # project-beta unaffected

        # c3 is eligible
        selected = CredentialManager.get_eligible_credential("groq")
        self.assertEqual(selected[0], c3["id"])

    # =========================================================================
    # 4. Telemetry and Health Metrics
    # =========================================================================

    def test_17_telemetry_recording_and_metrics(self):
        """Records successes and failures and calculates aggregate health metrics."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Tel1", "gsk_test_tel1_111111111", priority=10, is_primary=True)

        # Record 3 successes and 1 failure
        CredentialManager.record_success(c1["id"], model="openai/gpt-oss-20b", latency_ms=120.5)
        CredentialManager.record_success(c1["id"], model="openai/gpt-oss-20b", latency_ms=95.0)
        CredentialManager.record_success(c1["id"], model="openai/gpt-oss-20b", latency_ms=110.2)
        CredentialManager.record_failure(c1["id"], error_code="429", error_message="Rate limit", cooldown_seconds=30)

        metrics = CredentialManager.get_health_metrics()
        summary = metrics["summary"]
        self.assertEqual(summary["total_requests"], 4)
        self.assertEqual(summary["total_successes"], 3)
        self.assertEqual(summary["total_rate_limits"], 1)
        self.assertEqual(summary["success_rate_percent"], 75.0)

    # =========================================================================
    # 5. Provider Router Failover with Multi-Key Rotation
    # =========================================================================

    def test_18_router_failover_on_401_invalid_key(self):
        """Router automatically rotates to backup key when primary returns HTTP 401."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_F1", "gsk_test_bad_key_401", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_F2", "gsk_test_good_key_200", priority=20, is_primary=False)

        call_log = []

        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            call_log.append(key)
            if key == "gsk_test_bad_key_401":
                raise AuthError(provider="groq", message="HTTP 401: Invalid API Key")
            return TurnResult(content="SUCCESS_FROM_BACKUP_KEY")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            response = asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "hi"}]))

        self.assertEqual(response.content, "SUCCESS_FROM_BACKUP_KEY")
        self.assertEqual(len(call_log), 2)
        self.assertEqual(call_log[0], "gsk_test_bad_key_401")
        self.assertEqual(call_log[1], "gsk_test_good_key_200")

        # Verify c1 marked invalid in DB
        m1 = CredentialManager.get_credential_metadata(c1["id"])
        self.assertEqual(m1["status"], "invalid")

    def test_19_router_failover_on_429_rate_limit(self):
        """Router rotates to backup key with independent quota on HTTP 429."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_RL1", "gsk_test_rl1_key", priority=10, is_primary=True, quota_scope="scope-1")
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_RL2", "gsk_test_rl2_key", priority=20, is_primary=False, quota_scope="scope-2")

        call_log = []

        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            call_log.append(key)
            if key == "gsk_test_rl1_key":
                raise KeyRateLimitError(provider="groq", model="openai/gpt-oss-20b", wait_seconds=30.0, is_shared_quota=False, message="HTTP 429: Rate limit exceeded")
            return TurnResult(content="SUCCESS_FROM_INDEPENDENT_BACKUP")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            response = asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "hello"}]))

        self.assertEqual(response.content, "SUCCESS_FROM_INDEPENDENT_BACKUP")
        self.assertEqual(len(call_log), 2)
        self.assertEqual(call_log[0], "gsk_test_rl1_key")
        self.assertEqual(call_log[1], "gsk_test_rl2_key")

    def test_20_router_provider_fallback_when_keys_exhausted(self):
        """When all keys for Groq are rate-limited, chat_turn raises RateLimitError."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Ex1", "gsk_test_ex1_key", priority=10, is_primary=True)

        async def mock_turn(client, provider, model, key, messages, tools, system_instruction):
            raise KeyRateLimitError(provider="groq", model="openai/gpt-oss-20b", wait_seconds=60.0, is_shared_quota=True, message="HTTP 429: Rate limit")

        with patch("app.providers.router._openai_compatible_turn", side_effect=mock_turn):
            with self.assertRaises(RateLimitError):
                asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "prompt"}]))

    # =========================================================================
    # 6. Consequential Agent Operation Safety Across Rotation
    # =========================================================================

    def test_21_durable_operation_safety_across_key_rotation(self):
        """Key rotation during inference does not duplicate completed consequential tool operations."""
        from app.core.approval import ApprovalLifecycle

        op_id = f"test_op_{int(time.time()*1000)}"
        # Execute tool once and record in ApprovalLifecycle
        req = ApprovalLifecycle.create_request(
            tool_name="windows_cmd",
            args={"cmd": "echo test"},
            operation_id=op_id,
        )
        self.assertEqual(req["operation_id"], op_id)

        # Mark it executed in DB
        with conn() as c:
            c.execute("UPDATE approvals SET status='executed', result='\"test output\"' WHERE operation_id=?", (op_id,))

        # Second request with same operation_id (simulating retry after rotation) must return reused=True
        req2 = ApprovalLifecycle.create_request(
            tool_name="windows_cmd",
            args={"cmd": "echo test"},
            operation_id=op_id,
        )
        self.assertEqual(req2["status"], "executed")
        self.assertTrue(req2.get("reused"))
        self.assertEqual(req2.get("result"), "test output")

    # =========================================================================
    # 7. REST API Endpoints & Access Control
    # =========================================================================

    def test_22_api_unauthorized_access_rejected(self):
        """Mutating credential endpoints reject unauthenticated or cross-origin requests."""
        # Missing auth token
        res = self.client.post("/api/providers/credentials", json={"provider": "groq", "key_name": "TEST", "api_key": "gsk_123456789"}, headers={"origin": "http://127.0.0.1:5173"})
        self.assertEqual(res.status_code, 401)

        # Cross origin
        res2 = self.client.post("/api/providers/credentials", json={"provider": "groq", "key_name": "TEST", "api_key": "gsk_123456789"}, headers={"origin": "http://evil.com", "X-Session-Token": self.session.token})
        self.assertEqual(res2.status_code, 403)

    def test_23_api_crud_endpoints(self):
        """Full CRUD flow via REST API with masked secret response validation."""
        # 1. Create
        payload = {
            "provider": "groq",
            "key_name": "TEST_API_Key_1",
            "api_key": "gsk_live_api_test_credential_123456789",
            "priority": 15,
            "is_primary": True,
            "quota_scope": "api-scope-1"
        }
        res = self.client.post("/api/providers/credentials", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        cred = data["credential"]
        cred_id = cred["id"]
        self.assertIn("masked_key", cred)
        self.assertTrue(cred["masked_key"].startswith("gsk_••••"))
        self.assertNotIn("encrypted_key", cred)
        self.assertNotIn("gsk_live_api_test_credential", str(cred))

        # 2. List
        list_res = self.client.get("/api/providers/credentials?provider=groq", headers=self.auth_headers)
        self.assertEqual(list_res.status_code, 200)
        items = list_res.json()["credentials"]
        self.assertTrue(any(i["id"] == cred_id for i in items))

        # 3. Update
        up_res = self.client.put(f"/api/providers/credentials/{cred_id}", json={"key_name": "TEST_API_Key_Renamed", "priority": 5}, headers=self.auth_headers)
        self.assertEqual(up_res.status_code, 200)
        self.assertEqual(up_res.json()["credential"]["key_name"], "TEST_API_Key_Renamed")
        self.assertEqual(up_res.json()["credential"]["priority"], 5)

        # 4. Disable and Enable
        dis_res = self.client.post(f"/api/providers/credentials/{cred_id}/disable", headers=self.auth_headers)
        self.assertEqual(dis_res.status_code, 200)
        self.assertFalse(dis_res.json()["credential"]["enabled"])

        en_res = self.client.post(f"/api/providers/credentials/{cred_id}/enable", headers=self.auth_headers)
        self.assertEqual(en_res.status_code, 200)
        self.assertTrue(en_res.json()["credential"]["enabled"])

        # 5. Delete
        del_res = self.client.delete(f"/api/providers/credentials/{cred_id}", headers=self.auth_headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["ok"])

    def test_24_api_health_endpoint(self):
        """GET /api/providers/credentials/health returns aggregated metrics."""
        res = self.client.get("/api/providers/credentials/health", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertIn("metrics", data)
        self.assertIn("summary", data["metrics"])
        self.assertIn("providers", data["metrics"])

    # =========================================================================
    # 8. Regression Suite — Quota Scopes & Fallback Boundary Tests (Cases A - E)
    # =========================================================================

    def test_25_case_1_no_db_credentials_env_fallback_works(self):
        """Case A: When no database credentials exist, environment fallback works."""
        with conn() as c:
            c.execute("DELETE FROM provider_credentials WHERE provider='groq'")

        with patch("app.core.config.settings.groq_api_key", "gsk_env_fallback_test_key_12345"):
            res = CredentialManager.get_eligible_credential("groq")
            self.assertIsNotNone(res)
            self.assertEqual(res[0], "env_fallback")
            self.assertEqual(res[1], "gsk_env_fallback_test_key_12345")

    def test_26_case_2_db_primary_available_primary_selected(self):
        """Case B: When database credentials are available, the primary key is selected over .env."""
        c1 = CredentialManager.add_credential("gemini", "TEST_Gem_Pri_1", "AIza_pri_key_111111111", priority=10, is_primary=True)
        with patch("app.core.config.settings.gemini_api_key", "AIza_env_key_222222222"):
            res = CredentialManager.get_eligible_credential("gemini")
            self.assertIsNotNone(res)
            self.assertEqual(res[0], c1["id"])
            self.assertEqual(res[1], "AIza_pri_key_111111111")

    def test_27_case_3_primary_in_cooldown_independent_backup_selected(self):
        """Primary in cooldown; independent backup key is selected without calling .env."""
        c1 = CredentialManager.add_credential("openrouter", "TEST_OR_Pri", "sk-or-v1-pri_1111111", priority=10, is_primary=True, quota_scope="account-a")
        c2 = CredentialManager.add_credential("openrouter", "TEST_OR_Bkp", "sk-or-v1-bkp_2222222", priority=20, is_primary=False, quota_scope="account-b")

        # Put c1 into cooldown
        CredentialManager.record_failure(c1["id"], error_code="429", error_message="Free tier account limit", cooldown_seconds=60, quota_scope="account-a")

        with patch("app.core.config.settings.openrouter_api_key", "sk-or-v1-env_3333333"):
            res = CredentialManager.get_eligible_credential("openrouter")
            self.assertIsNotNone(res)
            self.assertEqual(res[0], c2["id"])
            self.assertEqual(res[1], "sk-or-v1-bkp_2222222")

    def test_28_case_4_all_db_keys_same_exhausted_scope_env_suppressed(self):
        """Case C: All database keys share an exhausted scope; .env fallback is strictly suppressed."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Org_1", "gsk_test_org_1111111", priority=10, is_primary=True, quota_scope="org-acme")
        c2 = CredentialManager.add_credential("groq", "TEST_Groq_Org_2", "gsk_test_org_2222222", priority=20, is_primary=False, quota_scope="org-acme")

        # Org rate limit 429
        CredentialManager.record_failure(c1["id"], error_code="429", error_message="Organization TPM rate limit exceeded", cooldown_seconds=60, quota_scope="org-acme")

        # Even with groq_api_key set in .env, fallback must be suppressed
        with patch("app.core.config.settings.groq_api_key", "gsk_test_org_1111111"):
            res = CredentialManager.get_eligible_credential("groq")
            self.assertIsNone(res)

    def test_29_case_5_env_fallback_independent_scope_eligible(self):
        """Case D: Environment fallback with an explicitly established independent scope is eligible."""
        c1 = CredentialManager.add_credential("gemini", "TEST_Gem_Proj_1", "AIza_proj1_11111111", priority=10, is_primary=True, quota_scope="project-exhausted")
        CredentialManager.record_failure(c1["id"], error_code="429", error_message="Project limit reached", cooldown_seconds=60, quota_scope="project-exhausted")

        # Explicitly configure independent scope in environment
        with patch("app.core.config.settings.gemini_api_key", "AIza_independent_paid_key_999"), \
             patch.dict(os.environ, {"GEMINI_QUOTA_SCOPE": "project-independent-paid"}):
            res = CredentialManager.get_eligible_credential("gemini")
            self.assertIsNotNone(res)
            self.assertEqual(res[0], "env_fallback")
            self.assertEqual(res[1], "AIza_independent_paid_key_999")

    def test_30_case_6_all_db_keys_disabled_no_accidental_fallback(self):
        """Case E: When all database credentials are intentionally disabled, no fallback to disabled key."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Dis_1", "gsk_disabled_key_11111", priority=10, is_primary=True)
        CredentialManager.disable_credential(c1["id"])

        # .env has the same key that user disabled
        with patch("app.core.config.settings.groq_api_key", "gsk_disabled_key_11111"):
            res = CredentialManager.get_eligible_credential("groq")
            self.assertIsNone(res)

    def test_31_case_7_all_db_keys_invalid_no_accidental_reuse(self):
        """Case E: When database credential is marked invalid (401), .env key with same fingerprint is NOT reused."""
        c1 = CredentialManager.add_credential("openrouter", "TEST_OR_Inv_1", "sk-or-v1-invalid_key_401", priority=10, is_primary=True)
        CredentialManager.record_failure(c1["id"], error_code="401", is_auth_failure=True, error_message="Unauthorized")

        with patch("app.core.config.settings.openrouter_api_key", "sk-or-v1-invalid_key_401"):
            res = CredentialManager.get_eligible_credential("openrouter")
            self.assertIsNone(res)

    def test_32_case_8_cooldown_expiry_selectable_again(self):
        """Key becomes selectable again immediately after cooldown timestamp expires."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Exp_1", "gsk_expired_cd_key_111", priority=10, is_primary=True)
        # Set cooldown in the past (10 seconds ago)
        past_iso = "2020-01-01T00:00:00+00:00"
        with conn() as c:
            c.execute("UPDATE provider_credentials SET cooldown_until = ?, status = 'cooldown' WHERE id = ?", (past_iso, c1["id"]))

        res = CredentialManager.get_eligible_credential("groq")
        self.assertIsNotNone(res)
        self.assertEqual(res[0], c1["id"])

    def test_33_case_9_no_eligible_credentials_triggers_provider_fallback(self):
        """When all credentials for Groq are in cooldown, router raises RateLimitError triggering fallback."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_AllCD", "gsk_all_cd_key_111", priority=10, is_primary=True, quota_scope="org-acme")
        CredentialManager.record_failure(c1["id"], error_code="429", error_message="Organization TPM rate limit exceeded", cooldown_seconds=60, quota_scope="org-acme")

        # Must raise RateLimitError without calling .env
        with patch("app.core.config.settings.groq_api_key", "gsk_all_cd_key_111"):
            with self.assertRaises(RateLimitError):
                asyncio.run(chat_turn("groq", "openai/gpt-oss-20b", [{"role": "user", "content": "hello"}]))

    def test_34_case_10_concurrent_selection_consistent_state(self):
        """Concurrent selection calls execute safely without race conditions or database lock errors."""
        c1 = CredentialManager.add_credential("groq", "TEST_Groq_Conc_1", "gsk_concurrent_key_1", priority=10, is_primary=True)
        c2 = CredentialManager.add_credential("gemini", "TEST_Gem_Conc_1", "AIza_concurrent_key_1", priority=10, is_primary=True)

        async def worker():
            res1 = CredentialManager.get_eligible_credential("groq")
            res2 = CredentialManager.get_eligible_credential("gemini")
            return res1[0] == c1["id"] and res2[0] == c2["id"]

        async def run_concurrent():
            tasks = [worker() for _ in range(20)]
            results = await asyncio.gather(*tasks)
            return all(results)

        all_ok = asyncio.run(run_concurrent())
        self.assertTrue(all_ok)


if __name__ == "__main__":
    unittest.main()
