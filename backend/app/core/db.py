from __future__ import annotations
import sqlite3
from pathlib import Path
from .config import BASE, settings

DB = (BASE / settings.database_path).resolve()
DB.parent.mkdir(parents=True, exist_ok=True)


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=20.0, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    return c


def init_db():
    with conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS conversations(
            id INTEGER PRIMARY KEY,
            title TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS approvals(
            id INTEGER PRIMARY KEY,
            tool_name TEXT NOT NULL,
            args TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            approval_token TEXT,
            args_hash TEXT,
            risk TEXT DEFAULT 'approval',
            expires_at TEXT,
            decision_by TEXT,
            decision_at TEXT,
            executed_at TEXT,
            result TEXT,
            error TEXT,
            conversation_id INTEGER
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY,
            event TEXT NOT NULL,
            detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS mcp_servers(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            transport TEXT NOT NULL,
            command TEXT,
            args TEXT,
            env TEXT,
            url TEXT,
            enabled INTEGER DEFAULT 1,
            status TEXT DEFAULT 'disconnected',
            error TEXT,
            tool_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_connected_at TEXT
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS browser_downloads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            url TEXT,
            mime_type TEXT,
            size_bytes INTEGER DEFAULT 0,
            downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS browser_security_rules(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_type TEXT NOT NULL,
            pattern TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Module 1: Persistent Memory
        c.execute("""
        CREATE TABLE IF NOT EXISTS memories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT,
            content TEXT NOT NULL,
            source TEXT NOT NULL,
            conversation_id INTEGER,
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            access_count INTEGER DEFAULT 0
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_memories_cat_status ON memories(category, status);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_memories_accessed ON memories(last_accessed_at);")

        # FTS5 virtual table for memories
        c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content,
            category,
            key,
            content='memories',
            content_rowid='id'
        );
        """)

        # Triggers to keep memories_fts in sync with memories
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, category, key) VALUES (new.id, new.content, new.category, new.key);
        END;
        """)
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category, key) VALUES('delete', old.id, old.content, old.category, old.key);
        END;
        """)
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category, key) VALUES('delete', old.id, old.content, old.category, old.key);
            INSERT INTO memories_fts(rowid, content, category, key) VALUES (new.id, new.content, new.category, new.key);
        END;
        """)

        # Module 3 & 4: Tasks & Plans
        c.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            user_request TEXT NOT NULL,
            objective TEXT NOT NULL,
            description TEXT,
            risk_level TEXT DEFAULT 'low',
            status TEXT DEFAULT 'draft',
            approval_required INTEGER DEFAULT 0,
            expected_output TEXT,
            completion_criteria TEXT,
            total_steps INTEGER DEFAULT 0,
            completed_steps INTEGER DEFAULT 0,
            result TEXT,
            error TEXT,
            conversation_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            completed_at TEXT
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")

        c.execute("""
        CREATE TABLE IF NOT EXISTS task_steps(
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            tool_name TEXT NOT NULL,
            arguments TEXT NOT NULL,
            dependencies TEXT,
            risk TEXT DEFAULT 'low',
            requires_approval INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            result TEXT,
            error TEXT,
            started_at TEXT,
            completed_at TEXT,
            retry_count INTEGER DEFAULT 0,
            checkpoint_data TEXT,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id, step_index);")

        # Module 5: Persistent Scheduler
        c.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks(
            id TEXT PRIMARY KEY,
            task_name TEXT NOT NULL,
            user_request TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            cron_expression TEXT,
            interval_seconds INTEGER,
            next_run_at TEXT NOT NULL,
            last_run_at TEXT,
            enabled INTEGER DEFAULT 1,
            risk_level TEXT DEFAULT 'low',
            requires_approval INTEGER DEFAULT 0,
            last_status TEXT,
            last_error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_next ON scheduled_tasks(enabled, next_run_at);")

        c.execute("""
        CREATE TABLE IF NOT EXISTS schedule_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id TEXT NOT NULL,
            task_id TEXT,
            triggered_at TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            FOREIGN KEY(schedule_id) REFERENCES scheduled_tasks(id) ON DELETE CASCADE
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_runs_sid ON schedule_runs(schedule_id);")

        # Module 6: System State & Emergency Stop
        c.execute("""
        CREATE TABLE IF NOT EXISTS system_state(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # Initialize emergency_stop if not present
        c.execute("""
        INSERT OR IGNORE INTO system_state(key, value) VALUES('emergency_stop', '0');
        """)

        # Phase 6 Queue 3: Advanced File Intelligence Index
        c.execute("""
        CREATE TABLE IF NOT EXISTS file_documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            format TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha256 TEXT NOT NULL,
            title TEXT,
            author TEXT,
            page_count INTEGER DEFAULT 0,
            metadata_json TEXT,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_file_docs_path ON file_documents(path);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_file_docs_sha ON file_documents(sha256);")

        c.execute("""
        CREATE TABLE IF NOT EXISTS file_chunks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            section_title TEXT,
            page_number INTEGER,
            sheet_name TEXT,
            slide_number INTEGER,
            content TEXT NOT NULL,
            token_estimate INTEGER DEFAULT 0,
            FOREIGN KEY(document_id) REFERENCES file_documents(id) ON DELETE CASCADE
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_file_chunks_doc ON file_chunks(document_id, chunk_index);")

        # FTS5 virtual table for document chunk search
        c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts USING fts5(
            content,
            section_title,
            content='file_chunks',
            content_rowid='id'
        );
        """)

        # FTS5 sync triggers
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS file_chunks_ai AFTER INSERT ON file_chunks BEGIN
            INSERT INTO file_chunks_fts(rowid, content, section_title)
            VALUES (new.id, new.content, new.section_title);
        END;
        """)
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS file_chunks_ad AFTER DELETE ON file_chunks BEGIN
            INSERT INTO file_chunks_fts(file_chunks_fts, rowid, content, section_title)
            VALUES('delete', old.id, old.content, old.section_title);
        END;
        """)
        c.execute("""
        CREATE TRIGGER IF NOT EXISTS file_chunks_au AFTER UPDATE ON file_chunks BEGIN
            INSERT INTO file_chunks_fts(file_chunks_fts, rowid, content, section_title)
            VALUES('delete', old.id, old.content, old.section_title);
            INSERT INTO file_chunks_fts(rowid, content, section_title)
            VALUES (new.id, new.content, new.section_title);
        END;
        """)

        # File Organize History for rollback and auditing
        c.execute("""
        CREATE TABLE IF NOT EXISTS file_organize_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            source_path TEXT NOT NULL,
            target_path TEXT,
            backup_path TEXT,
            status TEXT DEFAULT 'completed',
            details_json TEXT,
            executed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            rolled_back_at TEXT
        );
        """)

        # Migration: Ensure all columns exist
        cursor = c.execute("PRAGMA table_info(approvals)")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        new_cols = {
            "approval_token": "TEXT",
            "args_hash": "TEXT",
            "risk": "TEXT DEFAULT 'approval'",
            "expires_at": "TEXT",
            "decision_by": "TEXT",
            "decision_at": "TEXT",
            "executed_at": "TEXT",
            "result": "TEXT",
            "error": "TEXT",
            "conversation_id": "INTEGER",
        }

        for col, col_type in new_cols.items():
            if col not in existing_cols:
                c.execute(f"ALTER TABLE approvals ADD COLUMN {col} {col_type};")

        # Migration: Normalize legacy 'approved' status records to standard lifecycle states
        # Any historical record with results -> 'executed'; any without -> 'expired'
        c.execute("""
        UPDATE approvals 
        SET status = 'executed' 
        WHERE status = 'approved' AND (executed_at IS NOT NULL OR result IS NOT NULL);
        """)
        c.execute("""
        UPDATE approvals 
        SET status = 'expired' 
        WHERE status = 'approved' AND executed_at IS NULL AND result IS NULL;
        """)
