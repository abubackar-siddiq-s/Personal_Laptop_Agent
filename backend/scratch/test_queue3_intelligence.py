import os
import sys
import unittest
import asyncio
from pathlib import Path

# Setup path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.db import conn, init_db
from app.memory.engine import memory_engine
from app.core.conversation_intelligence import (
    get_injected_memory_context,
    generate_conversation_title,
    summarize_conversation,
    maybe_summarize_conversation,
    get_historical_decisions,
    get_project_context,
    get_conversation_history,
)


class TestConversationIntelligence(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    async def test_01_summary_persistence_and_restart(self):
        """Test automatic and explicit conversation summarization persistence and restart survival."""
        # Create a mock conversation with messages
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Architecture Discussion')").lastrowid
            c.execute("INSERT INTO messages(conversation_id, role, content) VALUES (?, 'user', 'What database should we use for LAPTOP AI memory?')", (cid,))
            c.execute("INSERT INTO messages(conversation_id, role, content) VALUES (?, 'assistant', 'We decided to use SQLite WAL mode with FTS5 virtual tables to eliminate external dependencies.')", (cid,))
            c.execute("INSERT INTO messages(conversation_id, role, content) VALUES (?, 'user', 'Does that satisfy the 8GB RAM target?')", (cid,))
            c.execute("INSERT INTO messages(conversation_id, role, content) VALUES (?, 'assistant', 'Yes, SQLite runs in-process with minimal RAM overhead.')", (cid,))

        # Explicitly summarize
        sum_mem = await summarize_conversation(cid, provider="groq")
        self.assertIsNotNone(sum_mem)
        self.assertEqual(sum_mem["category"], "conversation_summary")
        self.assertEqual(sum_mem["conversation_id"], cid)
        self.assertIn("SQLite", sum_mem["content"])

        # Verify restart survival via raw database connection
        with conn() as c:
            row = c.execute(
                "SELECT * FROM memories WHERE category='conversation_summary' AND conversation_id=?",
                (cid,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["key"], f"conv_sum_{cid}")

    def test_02_historical_decision_retrieval(self):
        """Test retrieving historical technical decisions and approved instructions."""
        # Store a decision
        memory_engine.create(
            category="project_decision",
            content="Architecture decision: Native tools must run with shell=False and strict parameter validation.",
            key="decision_shell_false",
            confidence=1.0,
        )

        decisions = get_historical_decisions(query="shell validation", limit=5)
        self.assertTrue(len(decisions) >= 1)
        self.assertTrue(any("shell=False" in d["content"] for d in decisions))

    def test_03_relevant_memory_injection(self):
        """Test that relevant user preferences and project facts are injected into system prompts."""
        memory_engine.create(
            category="user_preference",
            content="Prefers detailed commit messages following Conventional Commits format.",
            key="commit_msg_style",
        )

        # Relevant query
        context = get_injected_memory_context("What style should I use for git commits?", provider="groq")
        self.assertIn("[RECALLED PERSISTENT MEMORY", context)
        self.assertIn("Conventional Commits", context)
        self.assertIn("commit_msg_style", context)

    def test_04_irrelevant_memory_exclusion(self):
        """Test that irrelevant questions (math, generic tool usage) receive 0 memory tokens."""
        # Math query
        ctx_math = get_injected_memory_context("Calculate 450 divided by 9", provider="groq")
        self.assertEqual(ctx_math.strip(), "", "Generic math question must exclude persistent memories")

        # Generic date query
        ctx_date = get_injected_memory_context("What day is today?", provider="groq")
        self.assertEqual(ctx_date.strip(), "", "Generic query must not inject unrelated memories")

    def test_05_token_budget_enforcement(self):
        """Test that memory context injection strictly respects provider and model token budgets."""
        # Groq budget is 200-250 tokens; Gemini is 500 tokens
        from app.core.token_budget import estimate_tokens

        query = "Tell me about my active projects and user preferences"
        groq_ctx = get_injected_memory_context(query, provider="groq", model="openai/gpt-oss-20b")
        groq_tokens = estimate_tokens({"content": groq_ctx})
        self.assertLessEqual(groq_tokens, 250, "Groq memory context must remain under 250 tokens")

        gemini_ctx = get_injected_memory_context(query, provider="gemini", model="gemini-2.5-flash")
        gemini_tokens = estimate_tokens({"content": gemini_ctx})
        self.assertLessEqual(gemini_tokens, 600, "Gemini memory context must remain under budget")

    def test_06_recent_message_retention_and_compaction(self):
        """Test that conversation history sliding window preserves recent turns while dropping stale distant messages."""
        with conn() as c:
            cid = c.execute("INSERT INTO conversations(title) VALUES ('Long Chat Session')").lastrowid
            for i in range(20):
                c.execute("INSERT INTO messages(conversation_id, role, content) VALUES (?, 'user', ?)", (cid, f"User message turn {i}"))
                c.execute("INSERT INTO messages(conversation_id, role, content) VALUES (?, 'assistant', ?)", (cid, f"Assistant reply turn {i}"))

        # Retrieve history with max 6 turns
        history = get_conversation_history(cid, max_turns=6, max_tokens=1000)
        self.assertLessEqual(len(history), 12, "Should retain at most 12 messages for 6 turns")
        # Ensure the most recent turn is retained
        self.assertTrue(any("turn 19" in m["content"] for m in history), "Most recent turn 19 must be preserved")
        # Ensure oldest turn 0 is dropped
        self.assertFalse(any("turn 0" in m["content"] for m in history), "Old turn 0 must be compacted away")

    async def test_07_conversation_title_generation(self):
        """Test that conversation title generator creates concise, clean 3-5 word titles."""
        msg = "I need to configure Playwright browser automation for web searching on Windows 10."
        title = await generate_conversation_title(msg, provider="groq")
        self.assertIsNotNone(title)
        self.assertLessEqual(len(title.split()), 8)
        self.assertNotIn("\n", title)


if __name__ == "__main__":
    unittest.main()
