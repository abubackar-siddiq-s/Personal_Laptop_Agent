"""
LAPTOP AI — PHASE 7 QUEUE-TO-CONVERSATION INTEGRATION TEST SUITE
Verifies all requirements for delivering completed queued inference requests into conversation history:
1. Queued request completes and appears in the original conversation.
2. Exactly one assistant message is created.
3. Duplicate dispatcher execution does not duplicate messages.
4. Backend restart does not lose delivery.
5. Database transaction failure does not mark a request completed prematurely.
6. Missing conversation preserves the queue result and marks delivery as requiring attention.
7. Cancellation prevents subsequent delivery.
8. Completed consequential actions are not replayed.
9. Rate limit notification is not treated as final answer.
10. Conversation messages API returns queue_request_id.
11. Inference Control Center displays queue history and results.
12. Emergency stop halts dispatcher ticks immediately.
"""
import asyncio
from datetime import datetime, timezone
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
from app.core.db import conn, init_db
from app.core.security import get_or_create_bootstrap_secret
from app.core.credential_manager import CredentialManager
from app.core.inference_orchestrator import (
    circuit_breaker,
    admission_controller,
    inference_dispatcher,
)
from app.core.agent import agent_engine, AgentResult, ToolExecutionRecord
from app.core.emergency import trigger_emergency_stop, clear_emergency_stop, is_emergency_stopped
from starlette.testclient import TestClient
from app.main import app


class TestQueueConversationDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        clear_emergency_stop()
        admission_controller.resume_background()
        # Reset circuit breakers
        for p in ("gemini", "groq", "openrouter"):
            circuit_breaker._states[p] = "closed"
            circuit_breaker._failures[p] = []
            circuit_breaker._opened_at[p] = 0.0
        with conn() as c:
            c.execute("DELETE FROM inference_queue")
            c.execute("DELETE FROM messages")
            c.execute("DELETE FROM conversations")

    def tearDown(self):
        clear_emergency_stop()

    def test_01_queued_request_completes_and_delivers_to_conversation(self):
        """1. Queued request completes and appears in the original conversation's messages table."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Delivery Test 1')").lastrowid
            c.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', 'What is 5*5?')", (cid,))

        req_id = admission_controller.queue_request(
            conversation_id=cid,
            prompt="What is 5*5?",
            priority="chat",
            provider_attempted="gemini",
        )

        expected_answer = "5 * 5 is 25."
        mock_run = AsyncMock(return_value=AgentResult(
            reply=expected_answer,
            provider_used="gemini",
            model_used="gemini-2.5-flash",
        ))

        with patch.object(agent_engine, "run", mock_run):
            with patch("app.core.credential_manager.CredentialManager.get_eligible_credential", return_value={"id": "c1", "key": "k"}):
                res = asyncio.run(inference_dispatcher.tick())

        self.assertEqual(res["dispatched"], 1)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["delivery_status"], "delivered")

        with conn() as c:
            q_row = c.execute("SELECT status, delivery_status, result FROM inference_queue WHERE id = ?", (req_id,)).fetchone()
            self.assertEqual(q_row["status"], "completed")
            self.assertEqual(q_row["delivery_status"], "delivered")
            self.assertEqual(q_row["result"], expected_answer)

            msg_rows = c.execute(
                "SELECT role, content, queue_request_id FROM messages WHERE conversation_id = ? AND role = 'assistant'",
                (cid,),
            ).fetchall()
            self.assertEqual(len(msg_rows), 1)
            self.assertEqual(msg_rows[0]["content"], expected_answer)
            self.assertEqual(msg_rows[0]["queue_request_id"], req_id)

    def test_02_exactly_one_assistant_message_created(self):
        """2. Exactly one assistant message is created for the queued turn."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Single Message Test')").lastrowid
            c.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', 'Hello') ", (cid,))

        req_id = admission_controller.queue_request(
            conversation_id=cid,
            prompt="Hello",
            priority="chat",
        )

        mock_run = AsyncMock(return_value=AgentResult(reply="Hello there!"))
        with patch.object(agent_engine, "run", mock_run):
            with patch("app.core.credential_manager.CredentialManager.get_eligible_credential", return_value={"id": "c1"}):
                asyncio.run(inference_dispatcher.tick())

        with conn() as c:
            msgs = c.execute("SELECT id FROM messages WHERE conversation_id = ? AND queue_request_id = ?", (cid, req_id)).fetchall()
            self.assertEqual(len(msgs), 1)

    def test_03_duplicate_dispatcher_execution_idempotency(self):
        """3. Duplicate dispatcher execution does not duplicate messages (idempotent via unique constraint)."""
        import sqlite3
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Idempotency Test')").lastrowid

        req_id = admission_controller.queue_request(
            conversation_id=cid,
            prompt="Tell me a joke",
            priority="chat",
        )

        mock_run = AsyncMock(return_value=AgentResult(reply="A funny joke."))
        with patch.object(agent_engine, "run", mock_run):
            with patch("app.core.credential_manager.CredentialManager.get_eligible_credential", return_value={"id": "c1"}):
                asyncio.run(inference_dispatcher.tick())

        # Attempt a second duplicate insertion directly with the same queue_request_id
        with conn() as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute(
                    "INSERT INTO messages (conversation_id, role, content, queue_request_id) VALUES (?, 'assistant', 'Duplicate!', ?)",
                    (cid, req_id),
                )

            count = c.execute("SELECT COUNT(*) FROM messages WHERE queue_request_id = ?", (req_id,)).fetchone()[0]
            self.assertEqual(count, 1)

    def test_04_backend_restart_stale_claim_recovery_with_delivery(self):
        """4. Backend restart does not lose delivery; already delivered stale requests finalize to completed."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Restart Test')").lastrowid
            req_id = "qreq_test_stale_delivered"
            c.execute(
                """
                INSERT INTO inference_queue (id, conversation_id, task_type, priority, prompt, status, worker_id, claimed_at)
                VALUES (?, ?, 'chat', 'chat', 'Prompt', 'executing', 'worker_old', '2026-01-01T00:00:00')
                """,
                (req_id, cid),
            )
            c.execute(
                "INSERT INTO messages (conversation_id, role, content, queue_request_id) VALUES (?, 'assistant', 'Saved answer', ?)",
                (cid, req_id),
            )

        inference_dispatcher.recover_stale_claims()

        with conn() as c:
            row = c.execute("SELECT status, delivery_status FROM inference_queue WHERE id = ?", (req_id,)).fetchone()
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["delivery_status"], "delivered")

    def test_05_database_transaction_failure_does_not_mark_completed(self):
        """5. Database transaction failure does not mark a request completed prematurely."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Tx Failure Test')").lastrowid
            # Create a native SQLite trigger that fails any INSERT into messages
            c.execute("""
            CREATE TRIGGER fail_msg_insert BEFORE INSERT ON messages
            BEGIN
                SELECT RAISE(FAIL, 'Simulated disk I/O error');
            END;
            """)

        req_id = admission_controller.queue_request(
            conversation_id=cid,
            prompt="Fail my db",
            priority="chat",
        )

        mock_run = AsyncMock(return_value=AgentResult(reply="Answer"))

        try:
            with patch.object(agent_engine, "run", mock_run):
                with patch("app.core.credential_manager.CredentialManager.get_eligible_credential", return_value={"id": "c1"}):
                    res = asyncio.run(inference_dispatcher.tick())

            self.assertEqual(res["status"], "failed")

            with conn() as c:
                q_row = c.execute("SELECT status, delivery_status FROM inference_queue WHERE id = ?", (req_id,)).fetchone()
                self.assertEqual(q_row["status"], "failed")
                self.assertNotEqual(q_row["delivery_status"], "delivered")
                msgs = c.execute("SELECT id FROM messages WHERE queue_request_id = ?", (req_id,)).fetchall()
                self.assertEqual(len(msgs), 0)
        finally:
            with conn() as c:
                c.execute("DROP TRIGGER IF EXISTS fail_msg_insert")

    def test_06_missing_conversation_preserves_queue_result(self):
        """6. Missing conversation preserves the queue result and marks delivery requiring attention."""
        missing_cid = 999999
        req_id = admission_controller.queue_request(
            conversation_id=missing_cid,
            prompt="Where is my conversation?",
            priority="chat",
        )

        mock_run = AsyncMock(return_value=AgentResult(reply="Orphaned answer."))
        with patch.object(agent_engine, "run", mock_run):
            with patch("app.core.credential_manager.CredentialManager.get_eligible_credential", return_value={"id": "c1"}):
                res = asyncio.run(inference_dispatcher.tick())

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["delivery_status"], "requires_attention")

        with conn() as c:
            q_row = c.execute("SELECT status, delivery_status, result, error_message FROM inference_queue WHERE id = ?", (req_id,)).fetchone()
            self.assertEqual(q_row["status"], "completed")
            self.assertEqual(q_row["delivery_status"], "requires_attention")
            self.assertEqual(q_row["result"], "Orphaned answer.")
            self.assertIn("no longer exists", q_row["error_message"])

    def test_07_cancellation_prevents_subsequent_delivery(self):
        """7. Cancellation prevents subsequent execution and delivery."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Cancel Test')").lastrowid

        req_id = admission_controller.queue_request(
            conversation_id=cid,
            prompt="Cancel me",
            priority="chat",
        )

        cancelled = admission_controller.cancel_request(req_id, reason="User cancelled")
        self.assertTrue(cancelled)

        mock_run = AsyncMock(return_value=AgentResult(reply="Should never run."))
        with patch.object(agent_engine, "run", mock_run):
            res = asyncio.run(inference_dispatcher.tick())

        self.assertEqual(res["dispatched"], 0)

        with conn() as c:
            msgs = c.execute("SELECT id FROM messages WHERE queue_request_id = ?", (req_id,)).fetchall()
            self.assertEqual(len(msgs), 0)

    def test_08_completed_consequential_actions_not_replayed(self):
        """8. Completed consequential actions from checkpoints are passed and not replayed."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Checkpoint Test')").lastrowid

        prior_execution = {
            "tool_name": "desktop.app.launch",
            "arguments": {"app_name": "notepad"},
            "success": True,
            "result": {"pid": 1234},
            "error": None,
            "approval_id": "appr_123",
        }

        req_id = admission_controller.queue_request(
            conversation_id=cid,
            prompt="Open notepad and tell me the time",
            priority="chat",
            checkpoint_data=[prior_execution],
        )

        passed_checkpoints = []

        async def mock_agent_run(*args, **kwargs):
            passed_checkpoints.extend(kwargs.get("checkpoint_executions") or [])
            return AgentResult(reply="Notepad was already launched. The time is 12:00.")

        with patch.object(agent_engine, "run", side_effect=mock_agent_run):
            with patch("app.core.credential_manager.CredentialManager.get_eligible_credential", return_value={"id": "c1"}):
                res = asyncio.run(inference_dispatcher.tick())

        self.assertEqual(res["dispatched"], 1)
        self.assertEqual(len(passed_checkpoints), 1)
        self.assertEqual(passed_checkpoints[0].tool_name, "desktop.app.launch")
        self.assertEqual(passed_checkpoints[0].arguments, {"app_name": "notepad"})

    def test_09_rate_limit_during_dispatch_not_treated_as_final_answer(self):
        """9. Rate limit notification returned during execution is not treated as final answer."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('429 Notice Test')").lastrowid

        req_id = admission_controller.queue_request(
            conversation_id=cid,
            prompt="Trigger 429",
            priority="chat",
        )

        rate_limit_notice = "⚠️ **Groq Rate Limit Reached (HTTP 429)**\n\nThe 8,000 tokens-per-minute quota..."
        mock_run = AsyncMock(return_value=AgentResult(reply=rate_limit_notice))

        with patch.object(agent_engine, "run", mock_run):
            with patch("app.core.credential_manager.CredentialManager.get_eligible_credential", return_value={"id": "c1"}):
                res = asyncio.run(inference_dispatcher.tick())

        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(res["reason"], "rate_limited_during_execution")

        with conn() as c:
            q_row = c.execute("SELECT status, retry_after_ts FROM inference_queue WHERE id = ?", (req_id,)).fetchone()
            self.assertEqual(q_row["status"], "waiting_quota")
            self.assertIsNotNone(q_row["retry_after_ts"])

            msgs = c.execute("SELECT id FROM messages WHERE queue_request_id = ?", (req_id,)).fetchall()
            self.assertEqual(len(msgs), 0)

    def test_10_conversation_messages_api_returns_queue_request_id(self):
        """10. Endpoint GET /api/conversations/{cid}/messages returns queue_request_id."""
        client = TestClient(app)
        b_token = get_or_create_bootstrap_secret()
        auth_res = client.post("/api/auth/session", json={"bootstrap_token": b_token})
        sess_token = auth_res.json()["session_token"]
        headers = {"X-Session-Token": sess_token}

        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('API Messages Test')").lastrowid
            c.execute(
                "INSERT INTO messages (conversation_id, role, content, queue_request_id) VALUES (?, 'assistant', 'Delivered answer', 'qreq_api_test')",
                (cid,),
            )

        response = client.get(f"/api/conversations/{cid}/messages", headers=headers)
        self.assertEqual(response.status_code, 200)
        msgs = response.json()
        self.assertGreaterEqual(len(msgs), 1)
        delivered = next(m for m in msgs if m.get("queue_request_id") == "qreq_api_test")
        self.assertEqual(delivered["content"], "Delivered answer")

    def test_11_emergency_stop_halts_queue_dispatcher(self):
        """11. Emergency stop universally halts queue dispatcher ticks."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('E-Stop Test')").lastrowid

        admission_controller.queue_request(
            conversation_id=cid,
            prompt="Halt me",
            priority="chat",
        )

        trigger_emergency_stop("Safety test stop")

        res = asyncio.run(inference_dispatcher.tick())
        self.assertEqual(res["dispatched"], 0)
        self.assertTrue(res.get("emergency_stopped"))

        clear_emergency_stop()

    def test_12_control_center_shows_queue_history_and_results(self):
        """12. Inference Control Center displays queue history and results."""
        client = TestClient(app)
        b_token = get_or_create_bootstrap_secret()
        auth_res = client.post("/api/auth/session", json={"bootstrap_token": b_token})
        sess_token = auth_res.json()["session_token"]
        headers = {"X-Session-Token": sess_token}

        with conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO inference_queue (id, conversation_id, task_type, priority, prompt, status, delivery_status, result)
                VALUES ('qreq_ctrl_test', 1, 'chat', 'chat', 'Prompt', 'completed', 'delivered', 'Result for control center')
                """
            )

        response = client.get("/api/inference/control-center", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("queue", data)
        recent = data["queue"]["recent_queued"]
        match = next((q for q in recent if q["id"] == "qreq_ctrl_test"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["status"], "completed")
        self.assertEqual(match["delivery_status"], "delivered")
        self.assertEqual(match["result"], "Result for control center")


if __name__ == "__main__":
    unittest.main()
