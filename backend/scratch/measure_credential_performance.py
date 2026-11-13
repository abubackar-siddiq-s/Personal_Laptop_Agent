import os
import sys
import time
import statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.credential_manager import (
    CredentialManager,
    encrypt_secret,
    decrypt_secret,
    compute_fingerprint,
    mask_api_key,
)
from app.core.db import conn

def run_performance_benchmarks():
    print("=" * 65)
    print("LAPTOP AI — MULTI-KEY CREDENTIAL MANAGER PERFORMANCE BENCHMARKS")
    print("Target Platform: Intel Core i5-6300U @ 2.40GHz, Windows 10 Pro, 8GB RAM")
    print("=" * 65)

    # 1. DPAPI Encryption Benchmark
    secret = "gsk_benchmarking_secret_key_1234567890abcdefghijklmnopqrstuvwxyz"
    enc_times = []
    for _ in range(500):
        t0 = time.perf_counter()
        enc = encrypt_secret(secret)
        enc_times.append((time.perf_counter() - t0) * 1000)

    avg_enc = statistics.mean(enc_times)
    p95_enc = statistics.quantiles(enc_times, n=20)[18]
    min_enc = min(enc_times)
    max_enc = max(enc_times)

    print(f"\n[1. Windows DPAPI Encryption (CryptProtectData)] (500 samples)")
    print(f"  Mean Latency: {avg_enc:.3f} ms")
    print(f"  P95 Latency:  {p95_enc:.3f} ms")
    print(f"  Min / Max:    {min_enc:.3f} ms / {max_enc:.3f} ms")

    # 2. DPAPI Decryption Benchmark
    ciphertext = encrypt_secret(secret)
    dec_times = []
    for _ in range(500):
        t0 = time.perf_counter()
        dec = decrypt_secret(ciphertext)
        dec_times.append((time.perf_counter() - t0) * 1000)

    avg_dec = statistics.mean(dec_times)
    p95_dec = statistics.quantiles(dec_times, n=20)[18]
    min_dec = min(dec_times)
    max_dec = max(dec_times)

    print(f"\n[2. Windows DPAPI Decryption (CryptUnprotectData)] (500 samples)")
    print(f"  Mean Latency: {avg_dec:.3f} ms")
    print(f"  P95 Latency:  {p95_dec:.3f} ms")
    print(f"  Min / Max:    {min_dec:.3f} ms / {max_dec:.3f} ms")

    # Clean & Insert Test Credentials for DB & Selection Benchmarks
    with conn() as c:
        c.execute("DELETE FROM provider_credentials WHERE key_name LIKE 'BENCH_%'")

    c1 = CredentialManager.add_credential("groq", "BENCH_Groq_Primary", "gsk_bench_p_1111111111111", priority=10, is_primary=True)
    c2 = CredentialManager.add_credential("groq", "BENCH_Groq_Backup1", "gsk_bench_b1_2222222222222", priority=20, is_primary=False)
    c3 = CredentialManager.add_credential("groq", "BENCH_Groq_Backup2", "gsk_bench_b2_3333333333333", priority=30, is_primary=False)

    # 3. Direct SQLite Read Latency
    db_times = []
    for _ in range(500):
        t0 = time.perf_counter()
        with conn() as c:
            row = c.execute("SELECT id, encrypted_key, is_primary, priority FROM provider_credentials WHERE provider='groq' AND enabled=1").fetchall()
        db_times.append((time.perf_counter() - t0) * 1000)

    avg_db = statistics.mean(db_times)
    p95_db = statistics.quantiles(db_times, n=20)[18]
    min_db = min(db_times)
    max_db = max(db_times)

    print(f"\n[3. SQLite Credential Query Latency (WAL Mode)] (500 samples)")
    print(f"  Mean Latency: {avg_db:.3f} ms")
    print(f"  P95 Latency:  {p95_db:.3f} ms")
    print(f"  Min / Max:    {min_db:.3f} ms / {max_db:.3f} ms")

    # 4. Total Credential Selection Overhead (get_eligible_credential)
    sel_times = []
    for _ in range(500):
        t0 = time.perf_counter()
        cred = CredentialManager.get_eligible_credential("groq")
        sel_times.append((time.perf_counter() - t0) * 1000)

    avg_sel = statistics.mean(sel_times)
    p95_sel = statistics.quantiles(sel_times, n=20)[18]
    min_sel = min(sel_times)
    max_sel = max(sel_times)

    print(f"\n[4. Total Credential Selection + DPAPI Decrypt Overhead] (500 samples)")
    print(f"  Mean Latency: {avg_sel:.3f} ms")
    print(f"  P95 Latency:  {p95_sel:.3f} ms")
    print(f"  Min / Max:    {min_sel:.3f} ms / {max_sel:.3f} ms")

    # 5. Key Rotation Selection with Exclusion (Failover overhead)
    failover_times = []
    for _ in range(500):
        t0 = time.perf_counter()
        cred = CredentialManager.get_eligible_credential("groq", exclude_ids=[c1["id"]])
        failover_times.append((time.perf_counter() - t0) * 1000)

    avg_fo = statistics.mean(failover_times)
    p95_fo = statistics.quantiles(failover_times, n=20)[18]

    print(f"\n[5. Failover Candidate Selection + Backup Decrypt Overhead] (500 samples)")
    print(f"  Mean Latency: {avg_fo:.3f} ms")
    print(f"  P95 Latency:  {p95_fo:.3f} ms")

    # Cleanup
    with conn() as c:
        c.execute("DELETE FROM provider_credentials WHERE key_name LIKE 'BENCH_%'")

    print("\n" + "=" * 65)
    print(f"OVERALL PERFORMANCE SUMMARY:")
    print(f"Total end-to-end credential resolution adds {avg_sel:.3f} ms to inference requests.")
    print(f"This represents less than {avg_sel / 500 * 100:.2f}% of typical 500ms cloud inference latency.")
    print("=" * 65)

if __name__ == "__main__":
    run_performance_benchmarks()

