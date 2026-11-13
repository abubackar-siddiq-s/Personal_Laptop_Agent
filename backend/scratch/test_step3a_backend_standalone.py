import os
import sys
import time
import subprocess
import httpx
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON_EXE = PROJECT_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
BACKEND_DIR = PROJECT_ROOT / "backend"

print("==========================================================")
print("STEP 3A: INDEPENDENT BACKEND VERIFICATION")
print("==========================================================")

# 1. Start backend process
cmd = [
    str(PYTHON_EXE),
    "-m", "uvicorn", "app.main:app",
    "--host", "127.0.0.1",
    "--port", "8000",
]
print(f"Launching Uvicorn backend process: {' '.join(cmd)}")
proc = subprocess.Popen(
    cmd,
    cwd=str(BACKEND_DIR),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
print(f"Backend started with PID: {proc.pid}")

# 2. Poll GET /api/health with 30-second timeout
start_time = time.time()
max_timeout = 30.0
poll_interval = 0.5
health_ok = False
health_data = None
status_code = None

while time.time() - start_time < max_timeout:
    try:
        r = httpx.get("http://127.0.0.1:8000/api/health", timeout=2.0)
        status_code = r.status_code
        if r.status_code == 200:
            health_data = r.json()
            if health_data.get("ok") is True or health_data.get("status") == "ok":
                health_ok = True
                break
    except Exception:
        pass
    time.sleep(poll_interval)

elapsed = time.time() - start_time

if health_ok:
    print(f"\n[SUCCESS] Backend became healthy after {elapsed:.2f} seconds!")
    print(f"HTTP Status: {status_code}")
    print(f"Response Body: {health_data}")
else:
    print(f"\n[FAILED] Backend failed to respond within {max_timeout}s.")
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        print(f"Process exited early with return code: {proc.returncode}")
        print("Stderr:", stderr.decode(errors="replace"))

# 3. Stop the backend cleanly
print(f"\nStopping backend process PID {proc.pid} cleanly...")
proc.terminate()
try:
    proc.wait(timeout=5)
    print("Backend process terminated cleanly.")
except subprocess.TimeoutExpired:
    print("Process did not exit within 5s, forcing kill...")
    proc.kill()
    proc.wait()
    print("Backend killed.")

# 4. Verify port 8000 is released
time.sleep(1)
port_free = True
try:
    httpx.get("http://127.0.0.1:8000/api/health", timeout=1.0)
    port_free = False
except Exception:
    port_free = True

print(f"Port 8000 released: {port_free}")
assert health_ok, "Backend failed to become healthy!"
assert port_free, "Port 8000 was not cleanly released!"
print("\nSTEP 3A PASSED: Backend independently verified!\n")

