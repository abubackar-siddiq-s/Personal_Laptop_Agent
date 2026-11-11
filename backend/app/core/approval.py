from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from app.core.db import conn
from app.core.security import audit
from app.tools.registry import registry


def canonical_json(obj: any) -> str:
    """Return deterministic JSON representation for strict cryptographic hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ApprovalLifecycle:
    DEFAULT_TTL_SECONDS = 900  # 15 minutes
    VALID_STATUSES = {"pending", "executing", "executed", "rejected", "failed", "expired"}

    @classmethod
    def recover_interrupted_executions(cls) -> int:
        """
        Called on backend startup.
        Detects any records stuck in 'executing' status from an interrupted server shutdown or crash.
        Never automatically reruns potentially destructive operations.
        Marks them as 'failed' with explicit manual review required.
        Preserves the full audit trail.
        """
        now = utc_now_iso()
        recovered_count = 0
        with conn() as c:
            stuck_rows = c.execute("SELECT id, tool_name, created_at FROM approvals WHERE status='executing'").fetchall()
            for row in stuck_rows:
                aid = row["id"]
                tool_name = row["tool_name"]
                c.execute(
                    """
                    UPDATE approvals 
                    SET status='failed',
                        executed_at=?,
                        error='Interrupted: Server terminated while executing. Operation state uncertain; manual review required. Potentially destructive action was not automatically rerun.'
                    WHERE id=? AND status='executing'
                    """,
                    (now, aid),
                )
                audit("approval.interrupted_recovered", f"ID {aid} ({tool_name}): Marked failed due to interrupted execution")
                recovered_count += 1
        return recovered_count

    @staticmethod
    def _expire_stale(c, aid: int | None = None):
        """Atomically transition any expired pending approvals to 'expired'."""
        now = utc_now_iso()
        if aid is not None:
            c.execute(
                "UPDATE approvals SET status='expired' WHERE id=? AND status='pending' AND expires_at IS NOT NULL AND expires_at < ?",
                (aid, now),
            )
        else:
            c.execute(
                "UPDATE approvals SET status='expired' WHERE status='pending' AND expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )

    @classmethod
    def create_request(
        cls,
        tool_name: str,
        args: dict,
        risk: str = "approval",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        conversation_id: int | None = None,
    ) -> dict:
        """Create a new pending approval record bound to exact tool name, hashed arguments, and originating conversation."""
        clean_args_str = canonical_json(args)
        args_hash = hashlib.sha256(clean_args_str.encode("utf-8")).hexdigest()
        token = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        created_at = now.isoformat()

        with conn() as c:
            cursor = c.execute(
                """
                INSERT INTO approvals(
                    tool_name, args, status, created_at, approval_token, args_hash, risk, expires_at, conversation_id
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (tool_name, clean_args_str, created_at, token, args_hash, risk, expires_at, conversation_id),
            )
            aid = cursor.lastrowid

        audit("approval.created", f"ID {aid}: {tool_name} (token: {token[:8]}...) conv_id={conversation_id}")
        return {
            "id": aid,
            "approval_token": token,
            "tool_name": tool_name,
            "args": args,
            "status": "pending",
            "risk": risk,
            "created_at": created_at,
            "expires_at": expires_at,
            "conversation_id": conversation_id,
        }

    @classmethod
    def get_approval(cls, aid: int) -> dict | None:
        with conn() as c:
            cls._expire_stale(c, aid)
            row = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
            if not row:
                return None
            return dict(row)

    @classmethod
    def list_approvals(cls, status_filter: str | None = None, limit: int = 50) -> list[dict]:
        with conn() as c:
            cls._expire_stale(c)
            if status_filter:
                rows = c.execute(
                    "SELECT * FROM approvals WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status_filter, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM approvals ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    @classmethod
    def reject_approval(cls, aid: int, decision_by: str = "user:local") -> dict:
        now = utc_now_iso()
        with conn() as c:
            cls._expire_stale(c, aid)
            row = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
            if not row:
                raise ApprovalError(f"Approval #{aid} not found", 404)

            current_status = row["status"]
            if current_status == "expired":
                raise ApprovalError(f"Approval #{aid} has already expired", 400)
            if current_status == "rejected":
                return {"id": aid, "status": "rejected", "message": "Already rejected"}
            if current_status in ("executing", "executed"):
                raise ApprovalError(f"Approval #{aid} cannot be rejected; already {current_status}", 409)

            cursor = c.execute(
                """
                UPDATE approvals 
                SET status='rejected', decision_by=?, decision_at=?
                WHERE id=? AND status='pending'
                """,
                (decision_by, now, aid),
            )
            if cursor.rowcount == 0:
                raise ApprovalError(f"Approval #{aid} was concurrently updated or is no longer pending", 409)

        audit("approval.rejected", f"ID {aid} by {decision_by}")
        return {"id": aid, "status": "rejected", "decision_by": decision_by, "decision_at": now}

    @classmethod
    async def approve_and_execute(
        cls,
        aid: int,
        expected_args: dict | None = None,
        decision_by: str = "user:local",
    ) -> dict:
        """
        Atomically transition approval from 'pending' -> 'executing' -> 'executed' or 'failed'.
        Enforces tamper checks, expiration, and replay protection.
        """
        from app.core.emergency import is_emergency_stopped
        if is_emergency_stopped():
            raise ApprovalError("Execution blocked: Global Emergency Stop is currently engaged.", 400)

        now = utc_now_iso()
        with conn() as c:
            cls._expire_stale(c, aid)
            row = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
            if not row:
                raise ApprovalError(f"Approval #{aid} not found", 404)

            current_status = row["status"]
            if current_status == "expired":
                raise ApprovalError(f"Approval #{aid} has expired and cannot be executed", 400)
            if current_status == "rejected":
                raise ApprovalError(f"Approval #{aid} was rejected and cannot be executed", 400)
            if current_status in ("executing", "executed"):
                raise ApprovalError(f"Approval #{aid} has already been executed (replay prevented)", 409)
            if current_status != "pending":
                raise ApprovalError(f"Approval #{aid} is in invalid status '{current_status}'", 400)

            # Atomic transition to 'executing'
            cursor = c.execute(
                """
                UPDATE approvals 
                SET status='executing', decision_by=?, decision_at=?
                WHERE id=? AND status='pending'
                """,
                (decision_by, now, aid),
            )
            if cursor.rowcount == 0:
                raise ApprovalError(f"Approval #{aid} is already executing or no longer pending", 409)

        # Retrieve the locked execution record
        tool_name = row["tool_name"]
        stored_args_str = row["args"]
        stored_hash = row["args_hash"]

        # Tamper verification
        if expected_args is not None:
            expected_hash = hashlib.sha256(canonical_json(expected_args).encode("utf-8")).hexdigest()
            if expected_hash != stored_hash:
                with conn() as c:
                    c.execute(
                        "UPDATE approvals SET status='failed', error='Argument tampering detected' WHERE id=?",
                        (aid,),
                    )
                audit("approval.tampered", f"ID {aid}: expected {expected_hash} vs stored {stored_hash}")
                raise ApprovalError("Security violation: Submitted arguments do not match approved request", 403)

        try:
            parsed_args = json.loads(stored_args_str)
        except Exception as e:
            with conn() as c:
                c.execute(
                    "UPDATE approvals SET status='failed', error=? WHERE id=?",
                    (f"Corrupted args JSON: {str(e)}", aid),
                )
            raise ApprovalError(f"Invalid arguments in approval #{aid}: {str(e)}", 400)

        # Execute tool via registry with timeout isolation
        audit("approval.executing", f"ID {aid}: {tool_name}")
        exec_start = utc_now_iso()
        exec_res = await registry.execute(tool_name, parsed_args, timeout=30.0)
        exec_end = utc_now_iso()

        result_json = None
        error_str = None
        final_status = "executed" if exec_res.get("success") else "failed"

        conv_id = row["conversation_id"] if "conversation_id" in row.keys() else None

        if exec_res.get("success"):
            result_json = json.dumps(exec_res.get("result"), default=str)
            with conn() as c:
                c.execute(
                    """
                    UPDATE approvals 
                    SET status='executed', executed_at=?, result=?, error=NULL 
                    WHERE id=?
                    """,
                    (exec_end, result_json, aid),
                )
                if conv_id:
                    res_snippet = json.dumps(exec_res.get("result"), indent=2, default=str)
                    if len(res_snippet) > 800:
                        res_snippet = res_snippet[:800] + "\n... [truncated]"
                    c.execute(
                        "INSERT INTO messages(conversation_id, role, content) VALUES (?, 'assistant', ?)",
                        (
                            conv_id,
                            f"⚡ **Approved Action Completed (Approval #{aid})**\n\n"
                            f"- **Tool:** `{tool_name}`\n"
                            f"- **Arguments:** `{stored_args_str}`\n"
                            f"- **Status:** `executed`\n"
                            f"- **Result:**\n```json\n{res_snippet}\n```"
                        ),
                    )
            audit("approval.executed", f"ID {aid}: {tool_name}")
        else:
            error_str = exec_res.get("error", "Execution failed")
            with conn() as c:
                c.execute(
                    """
                    UPDATE approvals 
                    SET status='failed', executed_at=?, error=? 
                    WHERE id=?
                    """,
                    (exec_end, error_str, aid),
                )
                if conv_id:
                    c.execute(
                        "INSERT INTO messages(conversation_id, role, content) VALUES (?, 'assistant', ?)",
                        (
                            conv_id,
                            f"❌ **Approved Action Failed (Approval #{aid})**\n\n"
                            f"- **Tool:** `{tool_name}`\n"
                            f"- **Status:** `failed`\n"
                            f"- **Error:** `{error_str}`"
                        ),
                    )
            audit("approval.failed", f"ID {aid}: {error_str}")

        return {
            "id": aid,
            "tool_name": tool_name,
            "status": final_status,
            "decision_by": decision_by,
            "executed_at": exec_end,
            "result": exec_res.get("result") if exec_res.get("success") else None,
            "error": error_str,
        }

