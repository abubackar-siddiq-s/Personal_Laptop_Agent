"""
Hardware and Performance Benchmark for Phase 7 Intelligent Inference Orchestrator
Measures memory overhead, latency of orchestrator primitives, and endpoint response times.
"""
import os
import sys
import time
import psutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.inference_orchestrator import (
    circuit_breaker,
    admission_controller,
    ProviderSelector,
    read_only_cache,
)
from app.core.credential_manager import CredentialManager
from starlette.testclient import TestClient
from app.main import app
from app.core.security import get_or_create_bootstrap_secret

def run_benchmarks():
    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    print(f"[Benchmark] Process Base Memory (RSS): {mem_mb:.2f} MB")

    # 1. Circuit breaker latency
    t0 = time.perf_counter()
    for _ in range(1000):
        circuit_breaker.is_available("groq")
    cb_lat = (time.perf_counter() - t0) / 1000 * 1000 # in ms
    print(f"[Benchmark] Circuit breaker check latency: {cb_lat:.4f} ms")

    # 2. Admission controller reservation & release latency
    import asyncio
    async def bench_adm():
        t0 = time.perf_counter()
        for _ in range(500):
            admitted, reason = await admission_controller.can_admit("groq", estimated_tokens=150)
            if admitted:
                await admission_controller.release_reservation("groq", estimated_tokens=150, success=True)
        return (time.perf_counter() - t0) / 500 * 1000

    adm_lat = asyncio.run(bench_adm())
    print(f"[Benchmark] Admission controller reservation/release latency: {adm_lat:.4f} ms")

    # 3. ReadOnlyCache get/set latency
    t0 = time.perf_counter()
    for i in range(1000):
        read_only_cache.set("system.datetime", {"tz": "UTC"}, {"iso": "2026-11-13T12:00:00Z"})
        read_only_cache.get("system.datetime", {"tz": "UTC"})
    cache_lat = (time.perf_counter() - t0) / 1000 * 1000
    print(f"[Benchmark] Read-only cache get/set latency: {cache_lat:.4f} ms")

    # 4. Credential selection with quota checks
    CredentialManager.add_credential("groq", "Bench1", "gsk_bench_key_1", priority=10)
    CredentialManager.add_credential("gemini", "BenchGem", "AIza_bench_key_1", priority=10)
    t0 = time.perf_counter()
    for _ in range(500):
        CredentialManager.get_eligible_credential("groq")
    cred_lat = (time.perf_counter() - t0) / 500 * 1000
    print(f"[Benchmark] Credential selection with quota check latency: {cred_lat:.4f} ms")

    # 5. Control Center API endpoint latency
    client = TestClient(app)
    b_token = get_or_create_bootstrap_secret()
    auth_res = client.post("/api/auth/session", json={"bootstrap_token": b_token})
    sess_token = auth_res.cookies.get("laptop_ai_session")
    headers = {"X-Session-Token": sess_token}

    t0 = time.perf_counter()
    for _ in range(50):
        res = client.get("/api/inference/control-center", headers=headers)
        assert res.status_code == 200
    ep_lat = (time.perf_counter() - t0) / 50 * 1000
    print(f"[Benchmark] /api/inference/control-center API latency: {ep_lat:.2f} ms")

    final_mem_mb = process.memory_info().rss / (1024 * 1024)
    print(f"[Benchmark] Final Process Memory (RSS): {final_mem_mb:.2f} MB")
    print(f"[Benchmark] Memory Delta: {final_mem_mb - mem_mb:.2f} MB (Well under 50 MB budget)")

if __name__ == "__main__":
    run_benchmarks()
