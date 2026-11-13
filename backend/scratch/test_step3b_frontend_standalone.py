import os
import sys
import time
import subprocess
import httpx
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

print("==========================================================")
print("STEP 3B: INDEPENDENT FRONTEND VERIFICATION")
print("==========================================================")

# 1. Start frontend process via cmd.exe npm run dev
cmd = ["cmd.exe", "/c", "npm run dev -- --host 127.0.0.1"]
print(f"Launching Vite frontend dev server in {FRONTEND_DIR}...")
proc = subprocess.Popen(
    cmd,
    cwd=str(FRONTEND_DIR),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
print(f"Frontend launcher started with PID: {proc.pid}")

# 2. Poll port 5173 with max 30s timeout
start_time = time.time()
max_timeout = 30.0
poll_interval = 0.5
frontend_ok = False
status_code = None
html_content = ""

while time.time() - start_time < max_timeout:
    try:
        r = httpx.get("http://127.0.0.1:5173", timeout=2.0)
        status_code = r.status_code
        if r.status_code == 200 and "<html" in r.text.lower():
            frontend_ok = True
            html_content = r.text[:200]
            break
    except Exception:
        pass
    time.sleep(poll_interval)

elapsed = time.time() - start_time

if frontend_ok:
    print(f"\n[SUCCESS] Frontend became ready after {elapsed:.2f} seconds!")
    print(f"HTTP Status: {status_code}")
    print(f"HTML Preview:\n{html_content}...")
else:
    print(f"\n[FAILED] Frontend failed to respond within {max_timeout}s.")
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        print("Exit code:", proc.returncode)
        print("Stdout:", stdout.decode(errors="replace")[-500:])
        print("Stderr:", stderr.decode(errors="replace")[-500:])

# 3. Stop the frontend cleanly
print(f"\nStopping frontend launcher process PID {proc.pid}...")
# On Windows, cmd /c spawns node child processes; use taskkill /F /T /PID to terminate the whole tree
try:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    print("Frontend process tree terminated cleanly.")
except Exception as e:
    print("Taskkill error:", e)

# 4. Verify port 5173 is released
time.sleep(1)
port_free = True
try:
    httpx.get("http://127.0.0.1:5173", timeout=1.0)
    port_free = False
except Exception:
    port_free = True

print(f"Port 5173 released: {port_free}")
assert frontend_ok, "Frontend failed to respond within 30 seconds!"
assert port_free, "Port 5173 was not cleanly released!"
print("\nSTEP 3B PASSED: Frontend independently verified!\n")

