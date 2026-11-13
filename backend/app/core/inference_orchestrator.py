"""
LAPTOP AI — PHASE 7: INTELLIGENT INFERENCE ORCHESTRATION & LIMIT-AWARE AGENT RUNTIME
Provides:
- Circuit Breaker per provider (Gemini, Groq, OpenRouter) for 5xx/outage fail-fast.
- Quota-aware request scheduler & admission controller with token reservation & adaptive concurrency.
- Capability-aware provider selection (vision, tools, context budget).
- Durable fallback event logging and control center metrics.
- Bounded read-only deterministic cache.
- Interactive vs background prioritization with pause/resume controls.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.db import conn
from app.core.security import audit
from app.core.token_budget import estimate_tokens

logger = logging.getLogger("laptop_ai.orchestrator")

SUPPORTED_PROVIDERS = ("gemini", "groq", "openrouter")


# -------------------------------------------------------------
# 1. PROVIDER CIRCUIT BREAKER
# -------------------------------------------------------------
class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderCircuitBreaker:
    """
    Protects the runtime from hanging or repeating requests to degraded providers (5xx / timeouts).
    Trips to OPEN after 3 failures within 60s. Auto-recovers to HALF_OPEN after 30s.
    """
    def __init__(self, failure_threshold: int = 3, reset_timeout_seconds: float = 30.0):
        self.threshold = failure_threshold
        self.reset_timeout = reset_timeout_seconds
        self._states: dict[str, str] = {p: CircuitState.CLOSED for p in SUPPORTED_PROVIDERS}
        self._failures: dict[str, list[float]] = {p: [] for p in SUPPORTED_PROVIDERS}
        self._opened_at: dict[str, float] = {p: 0.0 for p in SUPPORTED_PROVIDERS}

    def is_available(self, provider: str) -> bool:
        p = provider.lower().strip()
        state = self._states.get(p, CircuitState.CLOSED)
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            # Check if reset timeout elapsed
            if time.time() - self._opened_at[p] >= self.reset_timeout:
                self._states[p] = CircuitState.HALF_OPEN
                logger.info("Circuit breaker for %s transitioned to HALF_OPEN (probing)", p)
                return True
            return False
        # HALF_OPEN allows single probe
        return True

    def record_success(self, provider: str):
        p = provider.lower().strip()
        if p not in self._states:
            return
        if self._states[p] != CircuitState.CLOSED:
            logger.info("Circuit breaker for %s reset to CLOSED after successful response", p)
        self._states[p] = CircuitState.CLOSED
        self._failures[p] = []
        self._opened_at[p] = 0.0

    def record_failure(self, provider: str, error_code: str = ""):
        p = provider.lower().strip()
        if p not in self._states:
            return
        now = time.time()
        # Clean older failures outside 60s window
        self._failures[p] = [t for t in self._failures[p] if now - t <= 60.0]
        self._failures[p].append(now)

        if len(self._failures[p]) >= self.threshold or self._states[p] == CircuitState.HALF_OPEN:
            self._states[p] = CircuitState.OPEN
            self._opened_at[p] = now
            logger.warning(
                "Circuit breaker for %s TRIPPED to OPEN (%d failures in 60s, error=%s). Cooldown %.1fs",
                p, len(self._failures[p]), error_code, self.reset_timeout
            )
            audit("circuit_breaker.tripped", f"{p} OPEN for {self.reset_timeout}s after {error_code}")

    def get_status(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        res = {}
        for p in SUPPORTED_PROVIDERS:
            state = self._states[p]
            remaining_cooldown = 0.0
            if state == CircuitState.OPEN:
                remaining_cooldown = max(0.0, round(self.reset_timeout - (now - self._opened_at[p]), 1))
                if remaining_cooldown <= 0:
                    state = CircuitState.HALF_OPEN
            res[p] = {
                "state": state,
                "consecutive_failures": len(self._failures[p]) if isinstance(self._failures[p], list) else int(self._failures[p]),
                "cooldown_remaining_seconds": remaining_cooldown,
            }
        return res


circuit_breaker = ProviderCircuitBreaker()


# -------------------------------------------------------------
# 2. QUOTA-AWARE ADMISSION CONTROLLER & REQUEST SCHEDULER
# -------------------------------------------------------------
class AdmissionController:
    """
    Lightweight admission controller tracking RPM, TPM, active reservations,
    adaptive concurrency limits, and request priorities on 8GB ThinkPad.
    """
    def __init__(self):
        self._lock = asyncio.Lock()
        self._default_concurrency = {"gemini": 4, "groq": 2, "openrouter": 2}
        self.concurrency_limits = {"gemini": 4, "groq": 2, "openrouter": 2}
        self.active_requests: dict[str, int] = {p: 0 for p in SUPPORTED_PROVIDERS}
        self.active_token_reservations: dict[str, int] = {p: 0 for p in SUPPORTED_PROVIDERS}
        self.consecutive_successes: dict[str, int] = {p: 0 for p in SUPPORTED_PROVIDERS}
        self._background_paused: bool = False
        self._queued_requests: list[dict] = []
        self._max_queue_size: int = 50

    def is_background_paused(self) -> bool:
        return self._background_paused

    def pause_background(self):
        self._background_paused = True
        audit("scheduler.background_paused", "Background task execution paused by user/system")
        logger.info("AdmissionController: background work paused")

    def resume_background(self):
        self._background_paused = False
        audit("scheduler.background_resumed", "Background task execution resumed by user/system")
        logger.info("AdmissionController: background work resumed")

    async def can_admit(
        self,
        provider: str,
        estimated_tokens: int = 500,
        priority: str = "chat",
    ) -> Tuple[bool, str]:
        """
        Evaluate admission for provider request.
        Returns (allowed: bool, reason: str).
        """
        p = provider.lower().strip()
        if p not in SUPPORTED_PROVIDERS:
            return False, f"Unsupported provider '{provider}'"

        # 1. Background task gating
        if priority == "background" and self._background_paused:
            return False, "Background inference is currently paused."

        # 2. Circuit breaker check
        if not circuit_breaker.is_available(p):
            return False, f"Provider {p} circuit breaker is OPEN due to recent outages."

        # 3. Concurrency check
        current_active = self.active_requests.get(p, 0)
        max_allowed = self.concurrency_limits.get(p, self._default_concurrency[p])
        if current_active >= max_allowed:
            return False, f"Provider {p} at active concurrency limit ({current_active}/{max_allowed})."

        # 4. Check known quota exhaustion from DB
        from app.core.credential_manager import CredentialManager
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn() as c:
            rows = c.execute(
                """
                SELECT id, requests_remaining, tokens_remaining, quota_reset_at, cooldown_until
                FROM provider_credentials
                WHERE provider = ? AND enabled = 1 AND status != 'invalid'
                """,
                (p,),
            ).fetchall()

            if rows:
                all_exhausted = True
                for r in rows:
                    cd = r["cooldown_until"]
                    if cd and cd > now_iso:
                        continue
                    q_res = r["quota_reset_at"]
                    req_rem = r["requests_remaining"]
                    tok_rem = r["tokens_remaining"]

                    # If remaining requests known and zero, and reset in future
                    if req_rem is not None and req_rem <= 0 and q_res and q_res > now_iso:
                        continue
                    # If remaining tokens known and less than estimated tokens
                    if tok_rem is not None and tok_rem < estimated_tokens and q_res and q_res > now_iso:
                        continue

                    all_exhausted = False
                    break

                if all_exhausted:
                    return False, f"All healthy credentials for {p} have exhausted quota in active window."

        return True, "Admitted"

    async def acquire_reservation(self, provider: str, estimated_tokens: int = 500):
        """Reserve token and concurrency slot for active inference."""
        p = provider.lower().strip()
        async with self._lock:
            self.active_requests[p] = self.active_requests.get(p, 0) + 1
            self.active_token_reservations[p] = self.active_token_reservations.get(p, 0) + estimated_tokens

    async def release_reservation(
        self,
        provider: str,
        estimated_tokens: int = 500,
        success: bool = True,
        is_rate_limit: bool = False,
        error_code: str = "",
    ):
        """Release reservation and update adaptive concurrency metrics."""
        p = provider.lower().strip()
        async with self._lock:
            self.active_requests[p] = max(0, self.active_requests.get(p, 1) - 1)
            self.active_token_reservations[p] = max(0, self.active_token_reservations.get(p, estimated_tokens) - estimated_tokens)

            if success:
                self.consecutive_successes[p] = self.consecutive_successes.get(p, 0) + 1
                circuit_breaker.record_success(p)
                # Gradually restore concurrency after 5 consecutive successes
                if self.consecutive_successes[p] >= 5:
                    current = self.concurrency_limits.get(p, self._default_concurrency[p])
                    maximum = self._default_concurrency[p]
                    if current < maximum:
                        self.concurrency_limits[p] = current + 1
                        logger.info("Adaptive concurrency for %s restored to %d", p, self.concurrency_limits[p])
                    self.consecutive_successes[p] = 0
            else:
                self.consecutive_successes[p] = 0
                if is_rate_limit:
                    # Drop concurrency on 429
                    current = self.concurrency_limits.get(p, self._default_concurrency[p])
                    self.concurrency_limits[p] = max(1, current - 1)
                    logger.info("Adaptive concurrency for %s reduced to %d due to rate limit", p, self.concurrency_limits[p])
                elif error_code.startswith("5") or "timeout" in error_code.lower():
                    circuit_breaker.record_failure(p, error_code=error_code)

    def queue_request(
        self,
        conversation_id: int | None,
        prompt: str,
        task_type: str = "chat",
        priority: str = "chat",
        provider_attempted: str | None = None,
        checkpoint_data: str | list | dict | None = None,
    ) -> str:
        """Enqueue request when all providers are temporarily exhausted, enforcing bounded queue size."""
        req_id = f"qreq_{uuid.uuid4().hex[:10]}"
        est = estimate_tokens(prompt)
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn() as c:
            # Enforce bounded queue (evict oldest non-chat if at limit)
            waiting_cnt = c.execute("SELECT COUNT(*) FROM inference_queue WHERE status='waiting_quota'").fetchone()[0]
            if waiting_cnt >= self._max_queue_size:
                c.execute(
                    """
                    DELETE FROM inference_queue
                    WHERE id = (
                        SELECT id FROM inference_queue
                        WHERE status = 'waiting_quota' AND priority != 'chat'
                        ORDER BY created_at ASC LIMIT 1
                    )
                    """
                )

            cp_str = None
            if checkpoint_data is not None:
                if isinstance(checkpoint_data, str):
                    cp_str = checkpoint_data
                else:
                    try:
                        cp_str = json.dumps(checkpoint_data, default=str)
                    except Exception:
                        cp_str = str(checkpoint_data)

            c.execute(
                """
                INSERT INTO inference_queue (
                    id, conversation_id, task_type, priority, prompt, estimated_tokens,
                    provider_attempted, status, checkpoint_data, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting_quota', ?, ?, ?)
                """,
                (req_id, conversation_id, task_type, priority, prompt[:1000], est, provider_attempted, cp_str, now_iso, now_iso),
            )
        logger.info("Enqueued inference request '%s' (priority=%s, est_tokens=%d)", req_id, priority, est)
        return req_id

    def cancel_request(self, request_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a waiting or claimed request."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn() as c:
            res = c.execute(
                """
                UPDATE inference_queue
                SET status = 'cancelled', error_message = ?, updated_at = ?
                WHERE id = ? AND status IN ('waiting_quota', 'claimed')
                """,
                (reason, now_iso, request_id),
            )
            affected = res.rowcount > 0
        if affected:
            audit("inference_queue.cancelled", f"Request {request_id} cancelled: {reason}")
            logger.info("Inference request '%s' cancelled: %s", request_id, reason)
        return affected

    def get_queue_metrics(self) -> dict[str, Any]:
        with conn() as c:
            total_waiting = c.execute("SELECT COUNT(*) FROM inference_queue WHERE status='waiting_quota'").fetchone()[0]
            total_completed = c.execute("SELECT COUNT(*) FROM inference_queue WHERE status='completed'").fetchone()[0]
            total_manual_review = c.execute("SELECT COUNT(*) FROM inference_queue WHERE status='manual_review'").fetchone()[0]
            recent = c.execute(
                "SELECT id, conversation_id, priority, task_type, status, delivery_status, result, estimated_tokens, created_at, updated_at FROM inference_queue ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        return {
            "background_paused": self._background_paused,
            "active_requests": dict(self.active_requests),
            "concurrency_limits": dict(self.concurrency_limits),
            "active_token_reservations": dict(self.active_token_reservations),
            "waiting_queue_count": total_waiting,
            "completed_queue_count": total_completed,
            "manual_review_queue_count": total_manual_review,
            "recent_queued": [dict(r) for r in recent],
        }


admission_controller = AdmissionController()


# -------------------------------------------------------------
# 2B. AUTONOMOUS DURABLE INFERENCE QUEUE DISPATCHER
# -------------------------------------------------------------
class InferenceQueueDispatcher:
    """
    Lightweight, autonomous background worker that evaluates the persistent SQLite
    inference_queue and dispatches requests when provider quota and concurrency allow.
    Features:
    - Atomic SQLite claiming (preventing duplicate processing across concurrent workers).
    - Safe restart recovery (transitioning uncertain operations to manual_review).
    - Priority-based scheduling (interactive chat preempts background tasks).
    - Idempotency preservation (reconstructing completed tool executions).
    - Bounded execution concurrency and clean cancellation support.
    """
    def __init__(self, polling_interval: float = 5.0, worker_id: str | None = None):
        self.polling_interval = max(2.0, min(polling_interval, 30.0))
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:6]}"
        self._running = False
        self._task_handle: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(1)

    def start(self):
        if self._running:
            return
        self._running = True
        self._task_handle = asyncio.create_task(self._dispatch_loop())
        logger.info("InferenceQueueDispatcher started (worker=%s, interval=%.1fs)", self.worker_id, self.polling_interval)

    def stop(self):
        self._running = False
        if self._task_handle:
            self._task_handle.cancel()
            self._task_handle = None
        logger.info("InferenceQueueDispatcher stopped")

    async def _dispatch_loop(self):
        consecutive_empty = 0
        while self._running:
            try:
                res = await self.tick()
                if res.get("dispatched", 0) > 0:
                    consecutive_empty = 0
                    sleep_time = 1.0  # Fast-follow pending items
                else:
                    consecutive_empty += 1
                    sleep_time = min(20.0, self.polling_interval + (consecutive_empty * 2.0))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in inference dispatcher loop: %s", e)
                sleep_time = self.polling_interval

            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break

    def recover_stale_claims(self) -> dict[str, int]:
        """
        Recover orphaned claims and executing items across backend crashes / restarts.
        Safety Guarantee:
        - If checkpoint indicates an uncertain consequential operation, transition to 'manual_review'.
        - If safe, return to 'waiting_quota' with incremented retry_count.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        recovered = 0
        manual_reviews = 0
        failed = 0

        with conn() as c:
            stale_rows = c.execute(
                """
                SELECT id, checkpoint_data, retry_count
                FROM inference_queue
                WHERE status IN ('claimed', 'executing')
                """
            ).fetchall()

            for r in stale_rows:
                rid = r["id"]
                cp = r["checkpoint_data"] or ""
                retries = r["retry_count"] or 0
                is_uncertain = False

                # If message was already delivered to conversation before restart, finalize row!
                already_delivered = c.execute("SELECT id FROM messages WHERE queue_request_id = ?", (rid,)).fetchone()
                if already_delivered:
                    c.execute(
                        """
                        UPDATE inference_queue
                        SET status = 'completed',
                            delivery_status = 'delivered',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now_iso, rid),
                    )
                    recovered += 1
                    continue

                if cp:
                    try:
                        parsed = json.loads(cp)
                        if isinstance(parsed, list):
                            for item in parsed:
                                t_name = item.get("tool_name", "") if isinstance(item, dict) else ""
                                if any(act in t_name.lower() for act in ("write", "delete", "shell", "browser", "click", "key", "mouse")):
                                    is_uncertain = True
                                    break
                        elif isinstance(parsed, dict) and "approval" in parsed.get("status", ""):
                            is_uncertain = True
                    except Exception:
                        is_uncertain = True

                if is_uncertain:
                    c.execute(
                        """
                        UPDATE inference_queue
                        SET status = 'manual_review',
                            error_message = 'Interrupted during execution across backend restart. State uncertain; manual review required.',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now_iso, rid),
                    )
                    audit("inference_queue.recovery_manual_review", f"Stale request {rid} marked manual_review")
                    manual_reviews += 1
                elif retries >= 3:
                    c.execute(
                        """
                        UPDATE inference_queue
                        SET status = 'failed',
                            error_message = 'Exceeded maximum recovery attempts after restart.',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now_iso, rid),
                    )
                    failed += 1
                else:
                    c.execute(
                        """
                        UPDATE inference_queue
                        SET status = 'waiting_quota',
                            worker_id = NULL,
                            claimed_at = NULL,
                            retry_count = retry_count + 1,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now_iso, rid),
                    )
                    audit("inference_queue.recovered", f"Stale request {rid} reset to waiting_quota")
                    recovered += 1

        logger.info(
            "InferenceQueueDispatcher recovered stale requests: %d waiting, %d manual_review, %d failed",
            recovered, manual_reviews, failed
        )
        return {"recovered": recovered, "manual_review": manual_reviews, "failed": failed}

    async def tick(self) -> dict[str, Any]:
        """
        Evaluate and atomically dispatch eligible queued inference requests.
        """
        from app.core.emergency import is_emergency_stopped
        if is_emergency_stopped():
            return {"dispatched": 0, "emergency_stopped": True}

        async with self._semaphore:
            now_ts = time.time()
            now_iso = datetime.now(timezone.utc).isoformat()

            # 1. Atomic claim of highest-priority eligible request
            with conn() as c:
                row = c.execute(
                    """
                    UPDATE inference_queue
                    SET status = 'claimed',
                        worker_id = ?,
                        claimed_at = ?,
                        updated_at = ?
                    WHERE id = (
                        SELECT id FROM inference_queue
                        WHERE status = 'waiting_quota'
                          AND (retry_after_ts IS NULL OR retry_after_ts <= ?)
                        ORDER BY CASE priority WHEN 'chat' THEN 1 WHEN 'high' THEN 2 ELSE 3 END, created_at ASC
                        LIMIT 1
                    )
                    RETURNING id, conversation_id, task_type, priority, prompt, estimated_tokens,
                              provider_attempted, checkpoint_data, retry_count
                    """,
                    (self.worker_id, now_iso, now_iso, now_ts),
                ).fetchone()

            if not row:
                return {"dispatched": 0, "reason": "empty_or_cooling_down"}

            req_id = row["id"]
            conv_id = row["conversation_id"]
            prompt = row["prompt"]
            est_tokens = row["estimated_tokens"] or 500
            priority = row["priority"]
            prev_provider = row["provider_attempted"]
            checkpoint_data = row["checkpoint_data"]

            # 2. Check if background paused
            if priority == "background" and admission_controller.is_background_paused():
                with conn() as c:
                    c.execute(
                        "UPDATE inference_queue SET status = 'waiting_quota', worker_id = NULL, claimed_at = NULL, updated_at = ? WHERE id = ?",
                        (now_iso, req_id),
                    )
                return {"dispatched": 0, "reason": "background_paused", "request_id": req_id}

            # 3. Find eligible provider
            candidates = ProviderSelector.get_fallback_order(prev_provider or "gemini")
            if prev_provider and prev_provider not in candidates:
                candidates.append(prev_provider)

            selected_provider = None
            selected_model = None
            from app.core.credential_manager import CredentialManager

            for cand in candidates:
                if not circuit_breaker.is_available(cand):
                    continue
                admitted, _ = await admission_controller.can_admit(cand, estimated_tokens=est_tokens, priority=priority)
                if not admitted:
                    continue
                cred = CredentialManager.get_eligible_credential(cand)
                if cred:
                    selected_provider = cand
                    if cand == "gemini":
                        selected_model = settings.fallback_model or "gemini-2.5-flash"
                    elif cand == "groq":
                        selected_model = "openai/gpt-oss-20b"
                    else:
                        selected_model = "openrouter/auto"
                    break

            if not selected_provider:
                # All providers temporarily unavailable: return to waiting with 10s backoff
                retry_after = now_ts + 10.0
                with conn() as c:
                    c.execute(
                        """
                        UPDATE inference_queue
                        SET status = 'waiting_quota',
                            worker_id = NULL,
                            claimed_at = NULL,
                            retry_after_ts = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (retry_after, now_iso, req_id),
                    )
                return {"dispatched": 0, "reason": "no_eligible_provider", "request_id": req_id}

            # 4. Check if cancelled before executing
            with conn() as c:
                cur = c.execute("SELECT status FROM inference_queue WHERE id = ?", (req_id,)).fetchone()
                if not cur or cur["status"] == "cancelled":
                    return {"dispatched": 0, "reason": "cancelled_before_execution", "request_id": req_id}
                c.execute(
                    "UPDATE inference_queue SET status = 'executing', updated_at = ? WHERE id = ? AND status = 'claimed'",
                    (now_iso, req_id),
                )

            # 5. Execute turn safely preserving prior checkpoints and tool records
            from app.core.agent import agent_engine, ToolExecutionRecord
            executions = []
            if checkpoint_data:
                try:
                    cp_list = json.loads(checkpoint_data)
                    if isinstance(cp_list, list):
                        for item in cp_list:
                            if isinstance(item, dict):
                                executions.append(ToolExecutionRecord(
                                    tool_name=item.get("tool_name", "unknown"),
                                    arguments=item.get("arguments", {}),
                                    success=item.get("success", False),
                                    result=item.get("result"),
                                    error=item.get("error"),
                                    approval_id=item.get("approval_id"),
                                ))
                except Exception as e:
                    logger.warning("Could not reconstruct executions from checkpoint: %s", e)

            # Reconstruct conversation history context for turn
            history = []
            if conv_id is not None:
                with conn() as c:
                    rows = c.execute(
                        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 10",
                        (conv_id,),
                    ).fetchall()
                    history = [
                        dict(r)
                        for r in reversed(rows)
                        if not (r["role"] == "assistant" and "Rate Limit Reached (HTTP 429)" in (r["content"] or ""))
                    ]

            try:
                res = await agent_engine.run(
                    provider=selected_provider,
                    model=selected_model,
                    user_message=prompt,
                    conversation_history=history,
                    conversation_id=conv_id,
                    checkpoint_executions=executions if executions else None,
                )

                reply_text = getattr(res, "reply", str(res))

                # If rate-limited again during execution, do not treat as final answer (Requirement 9)
                if reply_text.startswith("⚠️") and "Rate Limit Reached" in reply_text:
                    logger.warning("Queued request %s encountered rate limit during execution; returning to waiting_quota", req_id)
                    with conn() as c:
                        c.execute(
                            """
                            UPDATE inference_queue
                            SET status = 'waiting_quota',
                                worker_id = NULL,
                                claimed_at = NULL,
                                retry_after_ts = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (time.time() + 15.0, datetime.now(timezone.utc).isoformat(), req_id),
                        )
                    return {"dispatched": 0, "reason": "rate_limited_during_execution", "request_id": req_id}

                # Check if cancelled before delivery (Requirement 13)
                with conn() as c:
                    cur = c.execute("SELECT status FROM inference_queue WHERE id = ?", (req_id,)).fetchone()
                    if cur and cur["status"] == "cancelled":
                        logger.info("Queued request %s was cancelled before delivery; discarding response.", req_id)
                        return {"dispatched": 0, "reason": "cancelled_before_delivery", "request_id": req_id}

                    # Check conversation existence (Requirement 11)
                    conv_exists = False
                    if conv_id is not None:
                        row = c.execute("SELECT id FROM conversations WHERE id = ?", (conv_id,)).fetchone()
                        if row:
                            conv_exists = True

                    now_iso = datetime.now(timezone.utc).isoformat()
                    if not conv_exists:
                        # Missing conversation: preserve result in queue, mark delivery as requiring attention
                        c.execute(
                            """
                            UPDATE inference_queue
                            SET status = 'completed',
                                delivery_status = 'requires_attention',
                                result = ?,
                                error_message = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                reply_text[:4000],
                                f"Conversation #{conv_id} no longer exists. Delivery requires attention.",
                                now_iso,
                                req_id,
                            ),
                        )
                        audit("inference_queue.delivery_attention", f"Request {req_id} completed but conversation #{conv_id} is missing")
                        return {
                            "dispatched": 1,
                            "status": "completed",
                            "delivery_status": "requires_attention",
                            "request_id": req_id,
                            "provider": selected_provider,
                        }

                    # Atomic transaction for message delivery and queue completion (Requirements 4, 5, 6, 7, 8, 10)
                    c.execute("BEGIN IMMEDIATE;")
                    try:
                        existing_msg = c.execute(
                            "SELECT id FROM messages WHERE queue_request_id = ?",
                            (req_id,),
                        ).fetchone()

                        if not existing_msg:
                            c.execute(
                                """
                                INSERT INTO messages (conversation_id, role, content, queue_request_id)
                                VALUES (?, 'assistant', ?, ?)
                                """,
                                (conv_id, reply_text, req_id),
                            )

                        c.execute(
                            """
                            UPDATE inference_queue
                            SET status = 'completed',
                                delivery_status = 'delivered',
                                result = ?,
                                error_message = NULL,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (reply_text[:4000], now_iso, req_id),
                        )
                        c.execute("COMMIT;")
                    except Exception:
                        c.execute("ROLLBACK;")
                        raise

                audit("inference_queue.dispatched_success", f"Request {req_id} completed and delivered to conversation #{conv_id} via {selected_provider}")
                return {
                    "dispatched": 1,
                    "status": "completed",
                    "delivery_status": "delivered",
                    "request_id": req_id,
                    "provider": selected_provider,
                }

            except Exception as exc:
                logger.error("Execution failed for queued request '%s': %s", req_id, exc)
                with conn() as c:
                    c.execute(
                        """
                        UPDATE inference_queue
                        SET status = 'failed',
                            error_message = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (str(exc)[:500], datetime.now(timezone.utc).isoformat(), req_id),
                    )
                audit("inference_queue.dispatched_failure", f"Request {req_id} failed: {exc}")
                return {"dispatched": 0, "status": "failed", "request_id": req_id, "error": str(exc)}

    def purge_old_requests(self, max_age_days: int = 7) -> int:
        """Purge completed/failed/cancelled records older than max_age_days."""
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        with conn() as c:
            res = c.execute(
                """
                DELETE FROM inference_queue
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND updated_at < ?
                """,
                (cutoff_iso,),
            )
            deleted = res.rowcount
        if deleted:
            logger.info("Purged %d archived inference_queue records older than %d days", deleted, max_age_days)
        return deleted


inference_dispatcher = InferenceQueueDispatcher()


# -------------------------------------------------------------
# 3. CAPABILITY-AWARE PROVIDER SELECTOR
# -------------------------------------------------------------
class ProviderSelector:
    """
    Selects the optimal eligible provider and model based on requested capabilities:
    - Vision: Gemini 2.5 Flash native (or text-only fallback with UI tree/OCR).
    - Complex coding/reasoning: Gemini or OpenRouter with generous context.
    - Fast tool execution / low latency: Groq or Gemini.
    - Free tier enforcement: strictly restricts OpenRouter to free/configured models.
    """
    TASK_PREFERENCES = {
        "vision": [("gemini", "gemini-2.5-flash")],
        "coding": [("gemini", "gemini-2.5-flash"), ("groq", "openai/gpt-oss-20b"), ("openrouter", "openrouter/auto")],
        "reasoning": [("gemini", "gemini-2.5-flash"), ("groq", "openai/gpt-oss-20b"), ("openrouter", "openrouter/auto")],
        "file_analysis": [("gemini", "gemini-2.5-flash"), ("openrouter", "openrouter/auto"), ("groq", "openai/gpt-oss-20b")],
        "browser_research": [("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-2.5-flash"), ("openrouter", "openrouter/auto")],
        "general": [("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-2.5-flash"), ("openrouter", "openrouter/auto")],
    }

    @classmethod
    def get_fallback_order(cls, initial_provider: str) -> list[str]:
        """Return fallback provider order excluding the currently exhausted provider."""
        init = initial_provider.lower().strip()
        all_provs = ["gemini", "groq", "openrouter"]
        # Prioritize Gemini for robust capacity and multimodal support
        order = [p for p in ["gemini", "groq", "openrouter"] if p != init]
        return order

    @classmethod
    async def select_provider_for_task(
        cls,
        task_category: str = "general",
        requires_vision: bool = False,
        preferred_provider: str | None = None,
        estimated_tokens: int = 500,
    ) -> Tuple[str, str]:
        """
        Returns (provider, model) that is admitted, healthy, and capability-compatible.
        """
        # If vision is explicitly required, Gemini is the premier native multimodal choice
        if requires_vision:
            admitted, _ = await admission_controller.can_admit("gemini", estimated_tokens=estimated_tokens)
            if admitted and circuit_breaker.is_available("gemini"):
                return ("gemini", "gemini-2.5-flash")

        pref = (preferred_provider or settings.default_provider).lower().strip()
        candidates = cls.TASK_PREFERENCES.get(task_category, cls.TASK_PREFERENCES["general"])

        # Try preferred candidate first if compatible
        if not requires_vision:
            admitted, _ = await admission_controller.can_admit(pref, estimated_tokens=estimated_tokens)
            if admitted and circuit_breaker.is_available(pref):
                for p, m in candidates:
                    if p == pref:
                        return (p, m)
                return (pref, settings.default_model)

        # Fall back to other candidates in preference order
        for p, m in candidates:
            admitted, _ = await admission_controller.can_admit(p, estimated_tokens=estimated_tokens)
            if admitted and circuit_breaker.is_available(p):
                return (p, m)

        # Default fallback to Gemini if available
        return ("gemini", "gemini-2.5-flash")


# -------------------------------------------------------------
# 4. DURABLE FALLBACK EVENT TRACKER
# -------------------------------------------------------------
def record_fallback_event(
    from_provider: str,
    to_provider: str,
    from_model: str = "",
    to_model: str = "",
    reason: str = "",
    credential_id: str | None = None,
    quota_scope: str | None = None,
    wait_seconds: float = 0.0,
    success: bool = True,
):
    """Log an automatic provider fallback event with timestamp and root cause."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with conn() as c:
        c.execute(
            """
            INSERT INTO provider_fallback_events
            (from_provider, to_provider, from_model, to_model, reason, credential_id, quota_scope, wait_seconds, success, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (from_provider, to_provider, from_model, to_model, reason[:400], credential_id, quota_scope, wait_seconds, 1 if success else 0, now_iso),
        )
    audit(
        "provider.fallback_event",
        f"Fallback: {from_provider}({from_model}) -> {to_provider}({to_model}) | Reason: {reason[:120]} | Success={success}"
    )
    logger.info("Recorded fallback: %s -> %s (reason: %s)", from_provider, to_provider, reason)


# -------------------------------------------------------------
# 5. SAFE BOUNDED READ-ONLY DETERMINISTIC CACHE
# -------------------------------------------------------------
class ReadOnlyCache:
    """
    Lightweight, bounded LRU cache (max 100 entries, TTL 300s) for deterministic,
    read-only operations. Never caches sensitive data, approvals, or dynamic screens.
    """
    def __init__(self, max_entries: int = 100, ttl_seconds: float = 300.0):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._cache: dict[str, Tuple[float, Any]] = {}

    def _hash_key(self, tool_name: str, args: dict) -> str:
        raw = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, tool_name: str, args: dict) -> Any | None:
        # Exclude dynamic or sensitive tools from caching
        if any(term in tool_name.lower() for term in ("screenshot", "active", "mouse", "keyboard", "auth", "session", "key", "password")):
            return None

        k = self._hash_key(tool_name, args)
        if k in self._cache:
            ts, val = self._cache[k]
            if time.time() - ts < self._ttl:
                return val
            del self._cache[k]
        return None

    def set(self, tool_name: str, args: dict, result: Any):
        if any(term in tool_name.lower() for term in ("screenshot", "active", "mouse", "keyboard", "auth", "session", "key", "password")):
            return
        if len(self._cache) >= self._max:
            # Pop oldest entry
            oldest_key = min(self._cache.keys(), key=lambda x: self._cache[x][0])
            del self._cache[oldest_key]
        k = self._hash_key(tool_name, args)
        self._cache[k] = (time.time(), result)


read_only_cache = ReadOnlyCache()
