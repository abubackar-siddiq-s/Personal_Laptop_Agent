import os
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from starlette.testclient import TestClient
from app.main import app
from app.core.db import conn, init_db
from app.core.emergency import clear_emergency_stop
from app.core.security import (
    create_session_token,
    validate_session_token,
    revoke_session_token,
    create_setup_ticket,
    consume_setup_ticket,
    _SESSIONS,
)


class TestPersonalSessionAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        clear_emergency_stop()
        cls.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def setUp(self):
        clear_emergency_stop()
        self.client.cookies.clear()

    def test_01_session_persisted_to_sqlite(self):
        """Creating a session must persist it to local_sessions SQLite table."""
        session = create_session_token(ttl_seconds=30 * 86400, client_info="sqlite_test")
        token = session.token

        with conn() as db:
            row = db.execute("SELECT * FROM local_sessions WHERE token = ?", (token,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["revoked"], 0)
            self.assertEqual(row["client_info"], "sqlite_test")
            self.assertGreater(row["expires_at"], time.time() + 29 * 86400)

    def test_02_session_survives_backend_restart(self):
        """Simulating a restart by wiping in-memory cache must load session from SQLite."""
        session = create_session_token(ttl_seconds=30 * 86400, client_info="restart_test")
        token = session.token

        # Confirm token is currently in memory
        self.assertIn(token, _SESSIONS)

        # Simulate backend shutdown/restart by clearing in-memory cache
        _SESSIONS.clear()
        self.assertNotIn(token, _SESSIONS)

        # Validate token - should recover seamlessly from SQLite
        self.assertTrue(validate_session_token(token))
        # After successful validation, in-memory cache is repopulated
        self.assertIn(token, _SESSIONS)

        # Also test API call with this token
        res = self.client.post(
            "/api/settings",
            json={"theme": "dark"},
            headers={"X-Session-Token": token, "origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res.status_code, 200)

    def test_03_session_revocation_in_sqlite(self):
        """Revoking a session must update SQLite and reject subsequent usage."""
        session = create_session_token(ttl_seconds=30 * 86400, client_info="revoke_sqlite_test")
        token = session.token

        self.assertTrue(validate_session_token(token))

        # Revoke via API
        res = self.client.post(
            "/api/auth/revoke",
            headers={"X-Session-Token": token, "origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "revoked")

        # In-memory must reflect revoked
        self.assertTrue(_SESSIONS[token].revoked)

        # SQLite must reflect revoked = 1
        with conn() as db:
            row = db.execute("SELECT revoked FROM local_sessions WHERE token = ?", (token,)).fetchone()
            self.assertEqual(row["revoked"], 1)

        # validate_session_token must return False even after cache clear
        _SESSIONS.clear()
        self.assertFalse(validate_session_token(token))

        # API call with revoked token must be rejected with 401
        res2 = self.client.post(
            "/api/settings",
            json={"theme": "dark"},
            headers={"X-Session-Token": token, "origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res2.status_code, 401)

    def test_04_setup_ticket_lifecycle_and_single_use(self):
        """One-time setup tickets can be created, exchanged via API, and cannot be reused."""
        ticket = create_setup_ticket(ttl_seconds=120)
        self.assertIsNotNone(ticket)
        self.assertGreaterEqual(len(ticket), 32)

        # Verify ticket in DB
        with conn() as db:
            row = db.execute("SELECT * FROM one_time_setup_tickets WHERE ticket = ?", (ticket,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["used"], 0)

        # Exchange setup ticket via API
        res = self.client.post(
            "/api/auth/setup",
            json={"setup_ticket": ticket},
            headers={"origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertNotIn("session_token", data)
        self.assertEqual(data.get("status"), "active")
        session_token = res.cookies.get("laptop_ai_session")
        self.assertIsNotNone(session_token)
        self.assertEqual(len(session_token), 64)
        self.assertTrue(validate_session_token(session_token))

        # Attempt to reuse the SAME setup ticket - MUST FAIL (single-use!)
        res_reuse = self.client.post(
            "/api/auth/setup",
            json={"setup_ticket": ticket},
            headers={"origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res_reuse.status_code, 401)
        self.assertIn("Setup Security Violation", res_reuse.json().get("detail", ""))

        # Verify ticket in DB is marked used
        with conn() as db:
            row = db.execute("SELECT used FROM one_time_setup_tickets WHERE ticket = ?", (ticket,)).fetchone()
            self.assertEqual(row["used"], 1)

    def test_05_invalid_setup_ticket_rejected(self):
        """Invalid setup ticket must be rejected with HTTP 401."""
        res = self.client.post(
            "/api/auth/setup",
            json={"setup_ticket": "bogus_ticket_000000000000000000000000000000000000000000000000000000000000"},
            headers={"origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Setup Security Violation", res.json().get("detail", ""))

    def test_06_rolling_session_renewal(self):
        """If session has less than 7 days left, validation must renew its TTL to 30 days."""
        # Create a session that expires in 3 days
        three_days = 3 * 86400
        session = create_session_token(ttl_seconds=three_days, client_info="rolling_test")
        token = session.token

        # Clear cache to force DB read
        _SESSIONS.clear()

        # Validate token - should trigger rolling refresh
        self.assertTrue(validate_session_token(token))

        # Check in DB that expires_at was pushed to > 20 days into the future
        with conn() as db:
            row = db.execute("SELECT expires_at FROM local_sessions WHERE token = ?", (token,)).fetchone()
            self.assertGreater(row["expires_at"], time.time() + 20 * 86400)


if __name__ == "__main__":
    unittest.main()
