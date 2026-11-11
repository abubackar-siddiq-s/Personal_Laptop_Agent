from __future__ import annotations
import re
import sqlite3
from typing import Optional, List, Dict, Any
from app.core.db import conn
from app.core.security import audit
from app.core.token_budget import estimate_tokens
from app.memory.models import MemoryCategory, MemorySource

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z-_]{28,}"),  # Google API key
    re.compile(r"gsk_[a-zA-Z0-9]{20,}"),   # Groq API key
    re.compile(r"sk-or-[a-zA-Z0-9_-]{20,}"), # OpenRouter API key
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),    # General OpenAI-style key
    re.compile(r"(?i)\bbearer\s+[a-zA-Z0-9_.-]{10,}"), # Bearer token
    re.compile(r"(?i)\b(api[_-]?key|secret|password|bearer|auth[_-]?token)\s*[:=]\s*['\"]?[a-zA-Z0-9_.-]{4,}['\"]?"),
]

def sanitize_and_validate_memory(content: str) -> None:
    """Ensure sensitive credentials or secrets are never saved in persistent memory."""
    for pattern in SECRET_PATTERNS:
        if pattern.search(content):
            audit("memory.rejected_secret", "Attempted to store secret or credentials in persistent memory")
            raise ValueError("Security violation: Memory content cannot contain API keys, passwords, or authentication secrets.")

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she",
    "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "you", "your", "yours", "yourself",
}

def normalize_text(text: str) -> str:
    """Normalize text for duplicate detection."""
    t = re.sub(r"\s+", " ", text.strip().lower())
    return t.strip(".!?,:; ")

class MemoryEngine:
    def __init__(self):
        pass

    def create(
        self,
        category: MemoryCategory,
        content: str,
        source: MemorySource = "user_explicit",
        key: Optional[str] = None,
        conversation_id: Optional[int] = None,
        confidence: float = 1.0,
    ) -> dict:
        content_clean = content.strip()
        if not content_clean:
            raise ValueError("Memory content cannot be empty.")

        sanitize_and_validate_memory(content_clean)

        norm_content = normalize_text(content_clean)
        norm_key = key.strip().lower() if key else None

        with conn() as c:
            # Check for duplicate in the same category
            if norm_key:
                row = c.execute(
                    "SELECT * FROM memories WHERE category = ? AND LOWER(key) = ? AND status = 'active'",
                    (category, norm_key),
                ).fetchone()
                if row:
                    # Update content and bump last_accessed_at
                    c.execute(
                        """
                        UPDATE memories
                        SET content = ?, updated_at = CURRENT_TIMESTAMP, last_accessed_at = CURRENT_TIMESTAMP,
                            access_count = access_count + 1, confidence = ?
                        WHERE id = ?
                        """,
                        (content_clean, confidence, row["id"]),
                    )
                    audit("memory.updated_duplicate", f"Updated existing memory #{row['id']} with key '{norm_key}'")
                    return self.get(row["id"])

            # Content-based duplicate check
            rows = c.execute(
                "SELECT id, content FROM memories WHERE category = ? AND status = 'active'",
                (category,),
            ).fetchall()
            for r in rows:
                if normalize_text(r["content"]) == norm_content:
                    # Duplicate found
                    c.execute(
                        "UPDATE memories SET last_accessed_at = CURRENT_TIMESTAMP, access_count = access_count + 1 WHERE id = ?",
                        (r["id"],),
                    )
                    audit("memory.duplicate_prevented", f"Prevented duplicate memory creation, matched #{r['id']}")
                    return self.get(r["id"])

            # Insert new memory
            cur = c.execute(
                """
                INSERT INTO memories (category, key, content, source, conversation_id, confidence, status)
                VALUES (?, ?, ?, ?, ?, ?, 'active')
                """,
                (category, key.strip() if key else None, content_clean, source, conversation_id, confidence),
            )
            mem_id = cur.lastrowid
            audit("memory.created", f"Created memory #{mem_id} in category '{category}' from source '{source}'")
            return self.get(mem_id)

    def get(self, memory_id: int) -> Optional[dict]:
        with conn() as c:
            row = c.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if not row:
                return None
            return dict(row)

    def list(
        self,
        category: Optional[str] = None,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        with conn() as c:
            query = "SELECT * FROM memories WHERE status = ?"
            params: list = [status]
            if category:
                query += " AND category = ?"
                params.append(category)
            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = c.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def search(
        self,
        query_text: str,
        category: Optional[str] = None,
        status: str = "active",
        limit: int = 20,
    ) -> List[dict]:
        clean_q = query_text.strip()
        if not clean_q:
            return self.list(category=category, status=status, limit=limit)

        with conn() as c:
            # First try SQLite FTS5 MATCH
            fts_query = re.sub(r"[^\w\s]", " ", clean_q).strip()
            meaningful_words = [
                w for w in fts_query.split()
                if len(w) > 1 and w.lower() not in STOP_WORDS and not w.isdigit()
            ]
            if not meaningful_words:
                return []
            terms = [f'"{w}"*' for w in meaningful_words]
            fts_expression = " OR ".join(terms)

            results = []
            try:
                fts_sql = """
                SELECT m.* FROM memories m
                JOIN memories_fts f ON m.id = f.rowid
                WHERE memories_fts MATCH ? AND m.status = ?
                """
                params: list = [fts_expression, status]
                if category:
                    fts_sql += " AND m.category = ?"
                    params.append(category)
                fts_sql += " ORDER BY bm25(memories_fts) LIMIT ?"
                params.append(limit)

                rows = c.execute(fts_sql, params).fetchall()
                results = [dict(r) for r in rows]
            except sqlite3.OperationalError:
                results = []

            # Fallback to LIKE if FTS yielded no results
            if not results and meaningful_words:
                like_sql = "SELECT * FROM memories WHERE ("
                like_conds = []
                params = []
                for w in meaningful_words[:3]:
                    like_conds.append("(content LIKE ? OR key LIKE ?)")
                    params.extend([f"%{w}%", f"%{w}%"])
                like_sql += " OR ".join(like_conds) + ") AND status = ?"
                params.append(status)
                if category:
                    like_sql += " AND category = ?"
                    params.append(category)
                like_sql += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)
                rows = c.execute(like_sql, params).fetchall()
                results = [dict(r) for r in rows]

            return results

    def update(
        self,
        memory_id: int,
        content: Optional[str] = None,
        category: Optional[MemoryCategory] = None,
        key: Optional[str] = None,
        status: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> Optional[dict]:
        existing = self.get(memory_id)
        if not existing:
            return None

        updates = []
        params = []

        if content is not None:
            c_clean = content.strip()
            sanitize_and_validate_memory(c_clean)
            updates.append("content = ?")
            params.append(c_clean)

        if category is not None:
            updates.append("category = ?")
            params.append(category)

        if key is not None:
            updates.append("key = ?")
            params.append(key.strip() if key else None)

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)

        if not updates:
            return existing

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(memory_id)

        with conn() as c:
            sql = f"UPDATE memories SET {', '.join(updates)} WHERE id = ?"
            c.execute(sql, params)
            audit("memory.updated", f"Updated memory #{memory_id}")
            return self.get(memory_id)

    def archive(self, memory_id: int) -> bool:
        with conn() as c:
            cur = c.execute(
                "UPDATE memories SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (memory_id,),
            )
            audit("memory.archived", f"Archived memory #{memory_id}")
            return cur.rowcount > 0

    def delete(self, memory_id: int) -> bool:
        with conn() as c:
            cur = c.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            audit("memory.deleted", f"Permanently deleted memory #{memory_id}")
            return cur.rowcount > 0

    def get_relevant_memories(
        self,
        query: str,
        max_tokens: int = 350,
        limit: int = 5,
    ) -> List[dict]:
        """
        Retrieve high-signal memories relevant to the user's prompt.
        Always factors in user_preferences and active_project, plus contextual search.
        Updates access counters for retrieved memories.
        """
        if not query or not query.strip():
            return []

        clean_q = query.strip()
        candidates: dict[int, dict] = {}

        # 1. Search relevant content via FTS
        matched = self.search(clean_q, status="active", limit=limit)
        for m in matched:
            candidates[m["id"]] = m

        # 2. Check if query explicitly asks about preferences, style, user info, or active projects
        q_lower = clean_q.lower()
        wants_preferences = any(k in q_lower for k in ("preference", "prefer", "theme", "settings", "style", "format", "mode", "color"))
        wants_project = any(k in q_lower for k in ("project", "task", "roadmap", "plan", "codebase", "architecture", "build", "laptop ai"))
        wants_user_info = any(k in q_lower for k in ("who am i", "my name", "about me", "remember", "memory", "recall", "user"))

        if wants_preferences and len(candidates) < limit:
            prefs = self.list(category="user_preference", status="active", limit=3)
            for p in prefs:
                if p["id"] not in candidates:
                    candidates[p["id"]] = p

        if wants_project and len(candidates) < limit:
            projects = self.list(category="active_project", status="active", limit=2)
            for pr in projects:
                if pr["id"] not in candidates:
                    candidates[pr["id"]] = pr

        if wants_user_info and len(candidates) < limit:
            facts = self.list(category="personal_fact", status="active", limit=3)
            for f in facts:
                if f["id"] not in candidates:
                    candidates[f["id"]] = f

        selected = list(candidates.values())[:limit]
        if not selected:
            return []

        # Token budget enforcement
        budgeted = []
        total_tokens = 0
        accessed_ids = []

        for m in selected:
            mem_repr = f"[{m['category']}] {m['content']}"
            t_count = estimate_tokens({"content": mem_repr})
            if total_tokens + t_count <= max_tokens:
                budgeted.append(m)
                total_tokens += t_count
                accessed_ids.append(m["id"])
            else:
                break

        # Update last_accessed_at and access_count
        if accessed_ids:
            with conn() as c:
                placeholders = ",".join("?" for _ in accessed_ids)
                c.execute(
                    f"UPDATE memories SET last_accessed_at = CURRENT_TIMESTAMP, access_count = access_count + 1 WHERE id IN ({placeholders})",
                    accessed_ids,
                )

        return budgeted

memory_engine = MemoryEngine()
