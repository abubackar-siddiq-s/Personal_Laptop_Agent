import os
import sys
import time
import psutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def benchmark_hardware():
    process = psutil.Process(os.getpid())
    
    # 1. Startup & import latency
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

    # 2. Idle RAM & CPU
    time.sleep(0.5)
    idle_mem_mb = process.memory_info().rss / (1024 * 1024)
    idle_cpu = process.cpu_percent(interval=0.5)

    # 3. Active RAM & CPU during OCR & Indexing
    t1 = time.perf_counter()
    from app.vision.engine import vision_engine
    ocr_res = vision_engine.extract_text(target="desktop")
    ocr_duration = time.perf_counter() - t1
    ocr_mem_mb = process.memory_info().rss / (1024 * 1024)

    t2 = time.perf_counter()
    from app.files.engine import engine as file_engine
    downloads_path = str(Path.home() / "Downloads")
    idx_res = file_engine.refresh_index(downloads_path, max_files=15)
    idx_duration = time.perf_counter() - t2
    active_mem_mb = process.memory_info().rss / (1024 * 1024)

    # 4. Storage measurements
    db_size_kb = os.path.getsize(str(DB)) / 1024 if os.path.exists(str(DB)) else 0
    wal_path = str(DB) + "-wal"
    wal_size_kb = os.path.getsize(wal_path) / 1024 if os.path.exists(wal_path) else 0

    shots_dir = Path.home() / "Downloads" / "LAPTOP_AI" / "screenshots"
    shots_count = len(list(shots_dir.glob("*.png"))) if shots_dir.exists() else 0
    shots_size_mb = sum(f.stat().st_size for f in shots_dir.glob("*.png")) / (1024 * 1024) if shots_dir.exists() else 0

    print("--- REAL HARDWARE BENCHMARK RESULTS ---")
    print(f"Target CPU: Intel Core i5-6300U @ 2.40GHz (2 Cores, 4 Threads)")
    print(f"Installed RAM: {round(psutil.virtual_memory().total / (1024**3), 1)} GB (Windows 10 Pro)")
    print(f"Startup & Subsystems Init: {startup_time * 1000:.1f} ms")
    print(f"Backend Idle Memory (RSS): {idle_mem_mb:.2f} MB")
    print(f"Backend Active Memory (RSS during OCR/Index): {active_mem_mb:.2f} MB")
    print(f"Idle CPU Usage: {idle_cpu:.1f}%")
    print(f"Live OCR Extraction Duration: {ocr_duration:.2f}s (Engine: {ocr_res.engine_used})")
    indexed_cnt = idx_res.get('indexed', 0) if isinstance(idx_res, dict) else getattr(idx_res, 'indexed', 0)
    print(f"FTS5 Incremental Index Duration: {idx_duration:.2f}s ({indexed_cnt} docs indexed)")
    print(f"SQLite DB Size: {db_size_kb:.1f} KB (WAL: {wal_size_kb:.1f} KB)")
    print(f"Screenshot Storage: {shots_count} files ({shots_size_mb:.2f} MB)")

if __name__ == "__main__":
    benchmark_hardware()
