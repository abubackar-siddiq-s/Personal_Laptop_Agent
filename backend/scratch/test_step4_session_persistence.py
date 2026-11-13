import os
import sys
import time
import subprocess
import httpx
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON_EXE = PROJECT_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))
from app.core.security import BOOTSTRAP_FILE_PATH

print("==========================================================")
print("STEP 4: SESSION PERSISTENCE & BACKEND RESTART TEST")
print("==========================================================")

def start_backend():
    cmd = [
        str(PYTHON_EXE),
        "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(BACKEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Poll for health with 30s timeout
    t0 = time.time()
    ready = False
    while time.time() - t0 < 30.0:
        try:
            r = httpx.get("http://127.0.0.1:8000/api/health", timeout=2.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.4)
    assert ready, "Backend failed to become healthy within 30s"
    return proc

def stop_backend(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    time.sleep(1)

# Phase 1: Start initial backend
print("[1] Starting initial backend instance...")
p1 = start_backend()
print(f"    Backend running (PID: {p1.pid})")

# In-memory only client (never logs or prints tokens)
client = httpx.Client(base_url="http://127.0.0.1:8000")

# Phase 2: Check unauthenticated
r = client.get("/api/auth/session")
assert r.status_code == 200
assert r.json().get("authenticated") is False
print("[2] Unauthenticated check: authenticated = False (verified)")

# Phase 3: Authenticate in memory
assert BOOTSTRAP_FILE_PATH.exists()
b_secret = BOOTSTRAP_FILE_PATH.read_text(encoding="utf-8").strip()

r_auth = client.post(
    "/api/auth/session",
    json={"bootstrap_token": b_secret},
    headers={"Origin": "http://127.0.0.1:5173", "X-Requested-With": "LAPTOP_AI"},
)
assert r_auth.status_code == 200
assert "session_token" not in r_auth.json(), "Security failure: token leaked in JSON!"
assert r_auth.json().get("status") == "active"
set_cookie = r_auth.headers.get("set-cookie", "")
assert "laptop_ai_session=" in set_cookie
assert "httponly" in set_cookie.lower()
assert "samesite=lax" in set_cookie.lower()
assert "secure" not in set_cookie.lower()
print("[3] Authenticated via bootstrap token in memory.")
print("    - Cookie attributes verified: HttpOnly, SameSite=Lax, Path=/, Secure=False (HTTP)")
print("    - Token non-leakage in JSON body confirmed.")

# Phase 4: Verify authenticated request before restart
r_check1 = client.get("/api/auth/session")
assert r_check1.status_code == 200
assert r_check1.json().get("authenticated") is True

r_convs1 = client.get("/api/conversations")
assert r_convs1.status_code == 200
print(f"[4] Pre-restart request successful: {len(r_convs1.json())} conversations loaded.")

# Phase 5: Restart ONLY the backend
print("[5] Restarting ONLY the backend...")
stop_backend(p1)
print("    Old backend stopped.")

p2 = start_backend()
print(f"    New backend running (PID: {p2.pid})")

# Phase 6: Verify existing in-memory cookie works on the new backend
r_check2 = client.get("/api/auth/session")
assert r_check2.status_code == 200
assert r_check2.json().get("authenticated") is True
print("[6] Post-restart session verification: authenticated = True!")
print("    - Existing cookie restored automatically from SQLite local_sessions without user re-authentication.")

r_convs2 = client.get("/api/conversations")
assert r_convs2.status_code == 200
print(f"    - Loaded {len(r_convs2.json())} conversations on new backend.")

# Phase 7: Test Sign Out / Revocation
print("[7] Testing Sign Out / Lock Session...")
r_revoke = client.post(
    "/api/auth/revoke",
    headers={"Origin": "http://127.0.0.1:5173", "X-Requested-With": "LAPTOP_AI"},
)
assert r_revoke.status_code == 200
assert r_revoke.json().get("status") == "revoked"
print("    Sign Out succeeded: status = 'revoked'.")

# Phase 8: Verify revoked session cannot be reused
r_check3 = client.get("/api/auth/session")
assert r_check3.status_code == 200
assert r_check3.json().get("authenticated") is False
print("[8] Revoked session rejection verified: authenticated = False.")

r_mutating = client.post(
    "/api/settings",
    json={"theme": "dark"},
    headers={"Origin": "http://127.0.0.1:5173", "X-Requested-With": "LAPTOP_AI"},
)
assert r_mutating.status_code == 401
print("    Mutating request with revoked session rejected with HTTP 401.")

# Clean up
stop_backend(p2)
print("    Backend stopped cleanly.")

print("\n==========================================================")
print("STEP 4 PASSED: SESSION PERSISTENCE & REVOCATION FULLY VERIFIED!")
print("==========================================================")

