import os
import sys
import unittest
import sqlite3
from pathlib import Path

# Setup path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.db import conn, init_db
from app.memory.models import MemoryCategory, MemorySource
from app.memory.engine import memory_engine, sanitize_and_validate_memory, normalize_text
from app.core.conversation_intelligence import get_injected_memory_context


class TestPersistentMemoryEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_01_create_and_restart_survival(self):
        """Test that memory persists and survives restart simulation."""
        mem = memory_engine.create(
            category="user_preference",
            content="User prefers TypeScript with strict mode enabled and 2-space indentation.",
            source="user_explicit",
            key="ts_preferences_test",
            confidence=0.98,
        )
        self.assertIsNotNone(mem)
        mem_id = mem["id"]
        self.assertEqual(mem["category"], "user_preference")
        self.assertEqual(mem["key"], "ts_preferences_test")
        self.assertEqual(mem["confidence"], 0.98)

        # Simulate restart by establishing a fresh raw sqlite3 connection
        with conn() as c:
            row = c.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["key"], "ts_preferences_test")
            self.assertIn("TypeScript", row["content"])

    def test_02_fts5_search_and_ranking(self):
        """Test that FTS5 indexing searches and ranks memories accurately."""
        # Create distinct memories
        mem1 = memory_engine.create(
            category="active_project",
            content="Working on LAPTOP_AI Phase 5 memory subsystem and task planning architecture.",
            source="user_explicit",
            key="proj_laptop_ai",
        )
        mem2 = memory_engine.create(
            category="project_decision",
            content="Selected SQLite with WAL mode and FTS5 instead of heavy external vector databases.",
            source="user_explicit",
            key="decision_vector_db",
        )

        # Search for 'vector'
        results = memory_engine.search("vector databases")
        self.assertTrue(len(results) >= 1)
        self.assertTrue(any("vector" in r["content"].lower() for r in results))

        # Search for 'LAPTOP_AI'
        results_proj = memory_engine.search("LAPTOP_AI planning")
        self.assertTrue(len(results_proj) >= 1)
        self.assertTrue(any("LAPTOP_AI" in r["content"] for r in results_proj))

    def test_03_credential_and_secret_rejection(self):
        """Test that secrets (API keys, tokens, passwords) are strictly rejected."""
        dangerous_payloads = [
            "My OpenAI API key is sk-abcdef12345678901234567890",
            "Here is the secret Google key: AIzaSyD9839482934892348239482348293",
            "Groq key: gsk_1234567890abcdefghijklmnopqrstuv",
            "Authorization: Bearer my_secret_token_12345",
            "api_key = 'super_secret_production_key'",
            "Password: secret_user_password_999",
        ]

        for payload in dangerous_payloads:
            with self.assertRaises(ValueError, msg=f"Payload was unexpectedly accepted: {payload}"):
                memory_engine.create(
                    category="personal_fact",
                    content=payload,
                )

    def test_04_duplicate_prevention_key_and_content(self):
        """Test that duplicate keys and normalized content are detected and handled without creating duplicate rows."""
        # 1. Key-based deduplication
        m1 = memory_engine.create(
            category="user_preference",
            content="Prefers dark mode UI theme.",
            key="unique_theme_key",
        )
        # Attempt to create again with same key but updated content
        m2 = memory_engine.create(
            category="user_preference",
            content="Prefers midnight dark mode UI theme.",
            key="unique_theme_key",
        )
        self.assertEqual(m1["id"], m2["id"], "Key duplicate should update the existing row, not create a new ID")
        self.assertIn("midnight", m2["content"])

        # 2. Content-based deduplication with punctuation/case normalization
        c1 = memory_engine.create(
            category="personal_fact",
            content="User lives in Chennai, India.",
        )
        c2 = memory_engine.create(
            category="personal_fact",
            content="  user lives in chennai, india!  ",
        )
        self.assertEqual(c1["id"], c2["id"], "Content duplicate should match normalized content and return existing ID")

    def test_05_update_archive_delete_lifecycle(self):
        """Test the full user-controlled lifecycle: update, archive, delete."""
        mem = memory_engine.create(
            category="frequently_used_workflow",
            content="Run npm run build then restart the FastAPI service.",
            key="deploy_workflow",
        )
        mid = mem["id"]

        # Update
        updated = memory_engine.update(
            memory_id=mid,
            content="Run npm --prefix frontend run build then restart backend.",
            confidence=0.99,
        )
        self.assertIsNotNone(updated)
        self.assertIn("frontend run build", updated["content"])
        self.assertEqual(updated["confidence"], 0.99)

        # Archive
        archived = memory_engine.archive(mid)
        self.assertTrue(archived)
        archived_mem = memory_engine.get(mid)
        self.assertEqual(archived_mem["status"], "archived")

        # Delete
        deleted = memory_engine.delete(mid)
        self.assertTrue(deleted)
        self.assertIsNone(memory_engine.get(mid))

    def test_06_token_budgeted_selective_injection(self):
        """Test that memories are selectively injected without token bloat."""
        # Add test memories
        memory_engine.create(
            category="user_preference",
            content="Always format code with Black and Flake8.",
            key="code_formatter_pref",
        )

        # Query asking for formatting style should inject relevant preference
        ctx_pref = get_injected_memory_context("What is my preferred code formatter?", provider="groq", model="openai/gpt-oss-20b")
        self.assertIn("code_formatter_pref", ctx_pref)
        self.assertIn("Black and Flake8", ctx_pref)

        # Unrelated query (e.g. calculation) should NOT inject memory tokens
        ctx_math = get_injected_memory_context("What is 15 * 12?", provider="groq", model="openai/gpt-oss-20b")
        self.assertEqual(ctx_math.strip(), "", "Unrelated math query must receive zero injected memory tokens")

    def test_07_provenance_and_access_tracking(self):
        """Test that provenance source and access counters are recorded and updated."""
        mem = memory_engine.create(
            category="conversation_summary",
            content="Agreed on using SQLite WAL mode for performance without extra infrastructure.",
            source="conversation_summary",
            conversation_id=42,
            confidence=0.95,
        )
        mid = mem["id"]
        self.assertEqual(mem["source"], "conversation_summary")
        self.assertEqual(mem["conversation_id"], 42)
        initial_access = mem["access_count"]

        # Trigger relevance retrieval
        memory_engine.get_relevant_memories("SQLite WAL mode performance", max_tokens=200)

        # Verify access count incremented
        refreshed = memory_engine.get(mid)
        self.assertGreater(refreshed["access_count"], initial_access)


if __name__ == "__main__":
    unittest.main()
