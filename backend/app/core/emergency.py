from __future__ import annotations
import logging
from app.core.db import conn
from app.core.security import audit

logger = logging.getLogger("laptop_ai.emergency")

def is_emergency_stopped() -> bool:
    """Return True if the system is currently under Global Emergency Stop."""
    try:
        with conn() as c:
            row = c.execute("SELECT value FROM system_state WHERE key = 'emergency_stop'").fetchone()
            return bool(row and row["value"] == "1")
    except Exception as e:
        logger.error("Failed to query emergency stop status: %s", e)
        return False


def get_emergency_status() -> dict:
    """Get full emergency state including timestamp and reason."""
    with conn() as c:
        rows = c.execute("SELECT key, value FROM system_state WHERE key IN ('emergency_stop', 'emergency_reason', 'emergency_stopped_at')").fetchall()
        st = {r["key"]: r["value"] for r in rows}
        return {
            "is_stopped": st.get("emergency_stop") == "1",
            "reason": st.get("emergency_reason", ""),
            "stopped_at": st.get("emergency_stopped_at", ""),
        }


def trigger_emergency_stop(reason: str = "User initiated emergency stop") -> dict:
    """
    Trigger immediate Global Emergency Stop.
    - Prevents all new task execution, browser actions, native tools, and MCP calls.
    - Pauses running cancellable tasks.
    - Operates purely through local SQLite without requiring LLM provider connectivity.
    """
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO system_state(key, value, updated_at) VALUES ('emergency_stop', '1', CURRENT_TIMESTAMP)")
        c.execute("INSERT OR REPLACE INTO system_state(key, value, updated_at) VALUES ('emergency_reason', ?, CURRENT_TIMESTAMP)", (reason,))
        c.execute("INSERT OR REPLACE INTO system_state(key, value, updated_at) VALUES ('emergency_stopped_at', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")

        # Mark any running tasks as paused due to emergency stop
        c.execute("""
        UPDATE tasks
        SET status = 'paused', error = 'Paused by Global Emergency Stop: ' || ?, updated_at = CURRENT_TIMESTAMP
        WHERE status = 'running'
        """, (reason,))

        c.execute("""
        UPDATE task_steps
        SET status = 'failed',
            error = 'Interrupted by Emergency Stop: Operation state uncertain; manual review required.',
            checkpoint_data = CASE 
                WHEN checkpoint_data LIKE '%approval:%' THEN 'emergency_stop_manual_review:' || checkpoint_data 
                ELSE 'emergency_stop_manual_review' 
            END
        WHERE status = 'running'
        """)

    audit("system.emergency_stop_triggered", f"Global Emergency Stop engaged. Reason: {reason}")
    logger.warning("GLOBAL EMERGENCY STOP ENGAGED: %s", reason)
    return get_emergency_status()


def clear_emergency_stop() -> dict:
    """Clear Global Emergency Stop and allow tasks and tool execution to resume."""
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO system_state(key, value, updated_at) VALUES ('emergency_stop', '0', CURRENT_TIMESTAMP)")
        c.execute("INSERT OR REPLACE INTO system_state(key, value, updated_at) VALUES ('emergency_reason', '', CURRENT_TIMESTAMP)")

    audit("system.emergency_stop_cleared", "Global Emergency Stop disengaged by user.")
    logger.info("Global Emergency Stop cleared. Normal operations resumed.")
    return get_emergency_status()

