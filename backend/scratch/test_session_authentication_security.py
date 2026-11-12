import os
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from starlette.testclient import TestClient
from starlette.requests import Request
from fastapi import HTTPException

from app.main import app
from app.api.routes import r, verify_local_origin, ALLOWED_ORIGINS
from app.core.security import (
    get_or_create_bootstrap_secret,
    validate_bootstrap_token,
    create_session_token,
    validate_session_token,
    rotate_session_token,
    revoke_session_token,
    get_test_session_token,
    _SESSIONS,
)


class TestSessionAuthenticationSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url="http://127.0.0.1:8000")
        cls.bootstrap_secret = get_or_create_bootstrap_secret()

    def setUp(self):
        # Clear client cookies between tests to ensure test isolation
        self.client.cookies.clear()
        # Generate a fresh valid session token for tests that need it
        self.session = create_session_token(ttl_seconds=3600, client_info="test_runner")
        self.valid_token = self.session.token

    # 1. Missing Token Rejection
    def test_01_missing_token_rejection(self):
        """Mutating state-modifying requests without token must return HTTP 401."""
        res = self.client.post("/api/settings", json={"theme": "dark"}, headers={"origin": "http://127.0.0.1:5173"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Session Security Violation", res.json().get("detail", ""))

    # 2. Invalid Token Rejection
    def test_02_invalid_token_rejection(self):
        """Mutating requests with malformed or invalid token must return HTTP 401."""
        headers = {"X-Session-Token": "bad_token_12345", "origin": "http://127.0.0.1:5173"}
        res = self.client.post("/api/settings", json={"theme": "dark"}, headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Session Security Violation", res.json().get("detail", ""))

    # 3. Expired Token Rejection
    def test_03_expired_token_rejection(self):
        """Tokens past their TTL must be rejected with HTTP 401."""
        expired_session = create_session_token(ttl_seconds=-10, client_info="expired_test")
        headers = {"X-Session-Token": expired_session.token, "origin": "http://127.0.0.1:5173"}
        res = self.client.post("/api/settings", json={"theme": "dark"}, headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertFalse(validate_session_token(expired_session.token))

    # 4. Revoked Token Rejection
    def test_04_revoked_token_rejection(self):
        """Revoked tokens must be rejected with HTTP 401."""
        to_revoke = create_session_token(ttl_seconds=3600, client_info="revocation_test")
        self.assertTrue(validate_session_token(to_revoke.token))

        # Revoke the token
        self.assertTrue(revoke_session_token(to_revoke.token))
        self.assertFalse(validate_session_token(to_revoke.token))

        headers = {"X-Session-Token": to_revoke.token, "origin": "http://127.0.0.1:5173"}
        res = self.client.post("/api/settings", json={"theme": "dark"}, headers=headers)
        self.assertEqual(res.status_code, 401)

    # 5. Valid Token Acceptance
    def test_05_valid_token_acceptance(self):
        """Requests with an active valid token must be accepted through verify_local_origin."""
        headers = {"X-Session-Token": self.valid_token, "origin": "http://127.0.0.1:5173"}
        res = self.client.post("/api/settings", json={"theme": "dark"}, headers=headers)
        self.assertEqual(res.status_code, 200)

    # 6. Token Rotation Lifecycle
    def test_06_token_rotation_lifecycle(self):
        """Token rotation must invalidate old token and issue a functioning new token."""
        initial = create_session_token(ttl_seconds=3600, client_info="rotate_test")
        old_token = initial.token
        self.assertTrue(validate_session_token(old_token))

        # Perform rotation via API
        headers = {"X-Session-Token": old_token, "origin": "http://127.0.0.1:5173"}
        res = self.client.post("/api/auth/rotate", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        new_token = data.get("session_token")
        self.assertIsNotNone(new_token)
        self.assertNotEqual(old_token, new_token)

        # Old token is now revoked
        self.assertFalse(validate_session_token(old_token))

        # New token is active
        self.assertTrue(validate_session_token(new_token))
        new_headers = {"X-Session-Token": new_token, "origin": "http://127.0.0.1:5173"}
        res2 = self.client.post("/api/settings", json={"theme": "dark"}, headers=new_headers)
        self.assertEqual(res2.status_code, 200)

    # 7. Unauthorized Session Bootstrap Rejection
    def test_07_unauthorized_bootstrap_rejection(self):
        """Calling /api/auth/session with invalid bootstrap secret must return HTTP 401."""
        res = self.client.post(
            "/api/auth/session",
            json={"bootstrap_token": "wrong_secret_abcdef"},
            headers={"origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Bootstrap Security Violation", res.json().get("detail", ""))

    # 8. Authorized Session Bootstrap Success
    def test_08_authorized_bootstrap_success(self):
        """Calling /api/auth/session with valid bootstrap secret issues a session token & cookie."""
        res = self.client.post(
            "/api/auth/session",
            json={"bootstrap_token": self.bootstrap_secret},
            headers={"origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        issued_token = data.get("session_token")
        self.assertIsNotNone(issued_token)
        self.assertEqual(len(issued_token), 64)
        self.assertTrue(validate_session_token(issued_token))

        # Check that cookie was set
        cookies = res.cookies
        self.assertEqual(cookies.get("laptop_ai_session"), issued_token)

    # 9. Unauthorized Localhost Origin / Port Rejection
    def test_09_unauthorized_localhost_port_rejection(self):
        """Origins with unauthorized localhost ports (e.g. 3000, 8080) must be rejected with HTTP 403."""
        for port in [3000, 8080, 8888, 9000]:
            evil_origin = f"http://localhost:{port}"
            res = self.client.post(
                "/api/settings",
                json={"theme": "dark"},
                headers={"X-Session-Token": self.valid_token, "origin": evil_origin},
            )
            self.assertEqual(res.status_code, 403, f"Origin {evil_origin} should be blocked with 403")
            self.assertIn("Cross-origin request", res.json().get("detail", ""))

    # 10. Unauthorized Cross-Origin Rejection
    def test_10_unauthorized_cross_origin_rejection(self):
        """External web origins must be strictly rejected with HTTP 403."""
        res = self.client.post(
            "/api/settings",
            json={"theme": "dark"},
            headers={"X-Session-Token": self.valid_token, "origin": "https://malicious-website.com"},
        )
        self.assertEqual(res.status_code, 403)

    # 11. Host Header DNS Rebinding Defense
    def test_11_host_header_dns_rebinding_defense(self):
        """Requests with unauthorized host headers must be rejected with HTTP 400."""
        res = self.client.post(
            "/api/settings",
            json={"theme": "dark"},
            headers={"host": "attacker-dns-rebind.com", "X-Session-Token": self.valid_token},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Host Header Security Violation", res.json().get("detail", ""))

    # 12. Verification of ALL Mutating Routes
    def test_12_all_mutating_routes_protected(self):
        """Verify that every mutating route in the application rejects unauthenticated requests."""
        tested_count = 0
        for route in r.routes:
            methods = getattr(route, "methods", set())
            path = getattr(route, "path", "")
            mutating = [m for m in methods if m in ("POST", "PUT", "DELETE", "PATCH")]
            if not mutating:
                continue

            full_path = "/api" + path
            if full_path.endswith("/emergency/stop") or full_path.endswith("/auth/session"):
                continue

            test_path = (
                full_path.replace("{cid}", "1")
                .replace("{aid}", "1")
                .replace("{sid}", "1")
                .replace("{index}", "0")
                .replace("{mid}", "1")
                .replace("{tid}", "task_test")
                .replace("{reminder_id}", "rem_1")
                .replace("{monitor_id}", "mon_1")
                .replace("{notification_id}", "notif_1")
                .replace("{task_id}", "task_1")
                .replace("{rid}", "1")
            )

            for method in mutating:
                tested_count += 1
                res = self.client.request(
                    method=method,
                    url=test_path,
                    headers={"origin": "http://127.0.0.1:5173"},  # Valid origin but NO token
                )
                self.assertEqual(
                    res.status_code,
                    401,
                    f"Route {method} {test_path} must require session authentication (got {res.status_code})",
                )

        self.assertGreaterEqual(tested_count, 70, "Expected at least 70 mutating endpoints protected.")

    # 13. Emergency Stop Remains Accessible Without Token
    def test_13_emergency_stop_remains_available_unauthenticated(self):
        """POST /api/emergency/stop must remain accessible without session token for safety."""
        res = self.client.post(
            "/api/emergency/stop",
            json={"reason": "Unauthenticated safety stop verification"},
            headers={"origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res.status_code, 200)

        # Clear it
        from app.core.emergency import clear_emergency_stop
        clear_emergency_stop()

    # 14. Confirmation that NO testclient bypass exists
    def test_14_no_testclient_bypass_exists(self):
        """Explicitly verify that testclient cannot bypass session token requirement."""
        # Using mock scope with client_host == 'testclient'
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/settings",
            "headers": [(b"host", b"testclient"), (b"origin", b"http://127.0.0.1:5173")],
            "client": ("testclient", 50000),
        }
        req = Request(scope)
        with self.assertRaises(HTTPException) as ctx:
            verify_local_origin(req)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Session Security Violation", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
