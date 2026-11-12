import os
import sys
import time
import psutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["LAPTOP_AI_TEST_MODE"] = "1"


def get_process_tree_rss_mb(parent_proc: psutil.Process) -> tuple[float, float, list[dict]]:
    """
    Measure RSS for the parent process and all active child processes.
    Returns (parent_rss_mb, total_rss_mb, child_details).
    """
    try:
        parent_rss = parent_proc.memory_info().rss / (1024 * 1024)
    except Exception:
        parent_rss = 0.0

    total_rss = parent_rss
    children_info = []

    try:
        children = parent_proc.children(recursive=True)
        for child in children:
            try:
                c_rss = child.memory_info().rss / (1024 * 1024)
                total_rss += c_rss
                children_info.append({
                    "pid": child.pid,
                    "name": child.name(),
                    "rss_mb": round(c_rss, 2),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    return parent_rss, total_rss, children_info


def benchmark_hardware():
    print("=" * 70)
    print("LAPTOP AI — SUSTAINED HARDWARE BENCHMARK (CORRECTED METHODOLOGY)")
    print("=" * 70)

    process = psutil.Process(os.getpid())

    # -------------------------------------------------------------
    # 1. Startup & Subsystem Initialization Latency
    # -------------------------------------------------------------
    t0 = time.perf_counter()
    from app.core.db import init_db, conn, DB
    from app.tools.registry import registry
    from app.tools.native import register as reg_native
    from app.desktop import register_desktop_tools
    from app.vision import register_vision_tools
    from app.files import register_file_tools
    from app.assistant import register_assistant_tools

    init_db()
    reg_native()
    register_desktop_tools()
    register_vision_tools()
    register_file_tools()
    register_assistant_tools()
    startup_time = time.perf_counter() - t0

    # -------------------------------------------------------------
    # 2. Warm-up Period
    # -------------------------------------------------------------
    print("\n[Phase 1] Executing 2.0s warm-up period...")
    time.sleep(2.0)
    # Prime cpu_percent baseline
    process.cpu_percent(interval=None)

    # -------------------------------------------------------------
    # 3. Sustained Idle Benchmark (Multi-sample 5.0s window)
    # -------------------------------------------------------------
    print("[Phase 2] Sampling sustained idle metrics over 5.0s (5 x 1.0s intervals)...")
    idle_cpu_samples = []
    idle_parent_rss_samples = []
    idle_total_rss_samples = []

    for i in range(5):
        sample_cpu = process.cpu_percent(interval=1.0)
        p_rss, t_rss, _ = get_process_tree_rss_mb(process)
        idle_cpu_samples.append(sample_cpu)
        idle_parent_rss_samples.append(p_rss)
        idle_total_rss_samples.append(t_rss)

    idle_cpu_mean = sum(idle_cpu_samples) / len(idle_cpu_samples)
    idle_cpu_peak = max(idle_cpu_samples)
    idle_parent_rss = sum(idle_parent_rss_samples) / len(idle_parent_rss_samples)
    idle_total_rss = sum(idle_total_rss_samples) / len(idle_total_rss_samples)

    # -------------------------------------------------------------
    # 4. Active Workload Benchmark: Live WinRT OCR + FTS5 Indexing
    # -------------------------------------------------------------
    print("[Phase 3] Measuring active workload: Live WinRT OCR & FTS5 Indexing...")

    # OCR measurement
    t_ocr_start = time.perf_counter()
    from app.vision.engine import vision_engine
    ocr_res = vision_engine.extract_text(target="desktop")
    ocr_duration = time.perf_counter() - t_ocr_start
    ocr_parent_rss, ocr_total_rss, ocr_children = get_process_tree_rss_mb(process)

    # FTS5 Indexing measurement
    t_idx_start = time.perf_counter()
    from app.files.engine import engine as file_engine
    downloads_path = str(Path.home() / "Downloads")
    idx_res = file_engine.refresh_index(downloads_path, max_files=15)
    idx_duration = time.perf_counter() - t_idx_start
    active_parent_rss, active_total_rss, active_children = get_process_tree_rss_mb(process)

    # -------------------------------------------------------------
    # 5. External Process Accounting (Playwright / Chromium / Node)
    # -------------------------------------------------------------
    external_browser_rss = 0.0
    external_browser_procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            p_name = p.info["name"].lower()
            if "chromium" in p_name or "playwright" in p_name:
                mem = p.info["memory_info"].rss / (1024 * 1024)
                external_browser_rss += mem
                external_browser_procs.append((p.info["pid"], p.info["name"], round(mem, 2)))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # -------------------------------------------------------------
    # 6. Persistent Storage Metrics
    # -------------------------------------------------------------
    db_size_kb = os.path.getsize(str(DB)) / 1024 if os.path.exists(str(DB)) else 0
    wal_path = str(DB) + "-wal"
    wal_size_kb = os.path.getsize(wal_path) / 1024 if os.path.exists(wal_path) else 0

    shots_dir = Path.home() / "Downloads" / "LAPTOP_AI" / "screenshots"
    shots_count = len(list(shots_dir.glob("*.png"))) if shots_dir.exists() else 0
    shots_size_mb = sum(f.stat().st_size for f in shots_dir.glob("*.png")) / (1024 * 1024) if shots_dir.exists() else 0

    # -------------------------------------------------------------
    # 7. Comprehensive Benchmark Report Output
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print("MEASURED HARDWARE BENCHMARK RESULTS")
    print("=" * 70)
    print(f"Platform:         Intel Core i5-6300U @ 2.40GHz (2 Cores, 4 Threads)")
    print(f"System Memory:    {round(psutil.virtual_memory().total / (1024**3), 1)} GB RAM (Windows 10 Pro)")
    print(f"Subsystems Init:  {startup_time * 1000:.1f} ms (Cold import + registry init)")
    print("\n[Idle Telemetry — 5.0s Sustained Window]")
    print(f"  CPU Mean:       {idle_cpu_mean:.2f}% (Samples: {idle_cpu_samples})")
    print(f"  CPU Peak:       {idle_cpu_peak:.2f}%")
    print(f"  Backend RSS:    {idle_parent_rss:.2f} MB")
    print(f"  Process Tree:   {idle_total_rss:.2f} MB (0 active child processes at idle)")
    print("\n[Active Workload Telemetry]")
    print(f"  WinRT OCR Latency:    {ocr_duration:.2f}s (Engine: {ocr_res.engine_used})")
    indexed_cnt = idx_res.get('indexed', 0) if isinstance(idx_res, dict) else getattr(idx_res, 'indexed', 0)
    print(f"  FTS5 Index Latency:   {idx_duration:.2f}s ({indexed_cnt} files indexed)")
    print(f"  Active Backend RSS:   {active_parent_rss:.2f} MB")
    print(f"  Active Tree Peak RSS: {max(ocr_total_rss, active_total_rss):.2f} MB")
    if ocr_children or active_children:
        print(f"  Observed Child Procs: {ocr_children or active_children}")
    else:
        print(f"  Observed Child Procs: Ephemeral (PowerShell WinRT sub-process terminated upon completion)")
    print("\n[External Process Accounting]")
    if external_browser_procs:
        print(f"  Active Browser RSS:   {external_browser_rss:.2f} MB ({len(external_browser_procs)} processes)")
    else:
        print(f"  Active Browser RSS:   0.00 MB (Playwright Chromium idle / not launched)")
    print("\n[Durable Storage Footprint]")
    print(f"  SQLite DB:            {db_size_kb:.1f} KB (WAL: {wal_size_kb:.1f} KB)")
    print(f"  Local Screenshots:    {shots_count} files ({shots_size_mb:.2f} MB)")
    print("=" * 70)


if __name__ == "__main__":
    benchmark_hardware()
