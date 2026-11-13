import os
import sys
import httpx
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import (
    BOOTSTRAP_FILE_PATH,
    create_setup_ticket,
)

BASE_URL = "http://127.0.0.1:8000"
ORIGIN = "http://127.0.0.1:5173"

def run_live_tests():
    print("=" * 60)
    print("LAPTOP AI — LIVE SERVER HTTP AUTHENTICATION ACCEPTANCE TEST")
    print("=" * 60)
    
    # 1. Health check
    with httpx.Client(base_url=BASE_URL) as client:
        r = client.get("/api/health")
        print(f"\n[1] GET /api/health -> HTTP {r.status_code}")
        print(f"    Body: {r.json()}")
        assert r.status_code == 200
        assert r.json().get("ok") is True or r.json().get("status") == "ok"
        print("    [PASS] Health check verified.")

    # 2. Unauthenticated session check
    client = httpx.Client(base_url=BASE_URL)
    r = client.get("/api/auth/session")
    print(f"\n[2] GET /api/auth/session (no cookie) -> HTTP {r.status_code}")
    print(f"    Body: {r.json()}")
    assert r.status_code == 200
    assert r.json().get("authenticated") is False
    print("    [PASS] Unauthenticated status confirmed.")

    # 3. Read bootstrap secret
    assert BOOTSTRAP_FILE_PATH.exists(), f"Bootstrap file not found at {BOOTSTRAP_FILE_PATH}"
    bootstrap_secret = BOOTSTRAP_FILE_PATH.read_text(encoding="utf-8").strip()
    assert len(bootstrap_secret) == 64
    print(f"\n[3] Bootstrap Secret located at: {BOOTSTRAP_FILE_PATH}")
    print("    [PASS] Secret exists and format verified (length 64, not displayed).")

    # 4. Invalid bootstrap secret rejection
    r = client.post(
        "/api/auth/session",
        json={"bootstrap_token": "invalid_bogus_token_1234567890"},
        headers={"Origin": ORIGIN, "X-Requested-With": "LAPTOP_AI"},
    )
    print(f"\n[4] POST /api/auth/session (invalid secret) -> HTTP {r.status_code}")
    print(f"    Body: {r.json()}")
    assert r.status_code == 401
    print("    [PASS] Invalid secret correctly rejected.")

    # 5. Valid bootstrap authentication and cookie inspection
    r = client.post(
        "/api/auth/session",
        json={"bootstrap_token": bootstrap_secret},
        headers={"Origin": ORIGIN, "X-Requested-With": "LAPTOP_AI"},
    )
    print(f"\n[5] POST /api/auth/session (valid secret) -> HTTP {r.status_code}")
    print(f"    Body: {r.json()}")
    assert r.status_code == 200
    assert "session_token" not in r.json(), "CRITICAL: session_token must NOT be in JSON body!"
    assert r.json().get("status") == "active"

    # Inspect Set-Cookie header
    set_cookie_header = r.headers.get("set-cookie", "")
    print(f"    Raw Set-Cookie: {set_cookie_header}")
    assert "laptop_ai_session=" in set_cookie_header
    assert "httponly" in set_cookie_header.lower(), "HttpOnly flag missing!"
    assert "samesite=lax" in set_cookie_header.lower(), "SameSite=Lax missing!"
    assert "path=/" in set_cookie_header.lower(), "Path=/ missing!"
    assert "secure" not in set_cookie_header.lower(), "Secure must NOT be set on plain HTTP loopback!"
    print("    [PASS] Cookie attributes verified: HttpOnly=True, SameSite=Lax, Path=/, Secure=False (HTTP).")
    print("    [PASS] Token non-leakage in JSON verified.")

    # 6. Verify session status with cookie
    r = client.get("/api/auth/session")
    print(f"\n[6] GET /api/auth/session (with cookie) -> HTTP {r.status_code}")
    print(f"    Body: {r.json()}")
    assert r.status_code == 200
    assert r.json().get("authenticated") is True
    print("    [PASS] Persistent cookie session active.")

    # 7. Load conversations
    r = client.get("/api/conversations")
    print(f"\n[7] GET /api/conversations -> HTTP {r.status_code}")
    convs = r.json()
    print(f"    Conversations loaded: {len(convs)}")
    assert r.status_code == 200
    print("    [PASS] Existing conversations loaded without NetworkError.")

    # 8. Send chat message
    r = client.post(
        "/api/chat",
        json={"message": "Respond with 'AUTHENTICATION_LIVE_OK' to verify live execution.", "provider": "groq", "model": "openai/gpt-oss-20b"},
        headers={"Origin": ORIGIN, "X-Requested-With": "LAPTOP_AI"},
    )
    print(f"\n[8] POST /api/chat -> HTTP {r.status_code}")
    chat_resp = r.json()
    reply = chat_resp.get("reply", "")
    print(f"    Reply (truncated): {reply[:100]}...")
    assert r.status_code == 200
    print("    [PASS] Live chat inference succeeded.")

    # 9. Security boundary tests: Origin & Host validation
    # 9a. Unauthorized external origin
    r = client.post(
        "/api/settings",
        json={"theme": "dark"},
        headers={"Origin": "https://malicious-attacker.com"},
    )
    print(f"\n[9a] Mutating request with external Origin -> HTTP {r.status_code}")
    assert r.status_code == 403
    print("     [PASS] Malicious external origin blocked (HTTP 403).")

    # 9b. Unauthorized localhost port
    r = client.post(
        "/api/settings",
        json={"theme": "dark"},
        headers={"Origin": "http://localhost:3000"},
    )
    print(f"[9b] Mutating request with unauthorized localhost:3000 Origin -> HTTP {r.status_code}")
    assert r.status_code == 403
    print("     [PASS] Unauthorized port blocked (HTTP 403).")

    # 9c. DNS rebinding host header attack
    r = client.post(
        "/api/settings",
        json={"theme": "dark"},
        headers={"Host": "attacker-dns-rebind.com", "Origin": ORIGIN},
    )
    print(f"[9c] Mutating request with forged Host header -> HTTP {r.status_code}")
    assert r.status_code == 400
    print("     [PASS] DNS rebinding Host header blocked (HTTP 400).")

    # 10. Test one-time setup ticket lifecycle
    ticket = create_setup_ticket(120)
    print(f"\n[10] Created one-time setup ticket (length {len(ticket)})")
    
    # 10a. Consume ticket via fresh session
    fresh_client = httpx.Client(base_url=BASE_URL)
    r = fresh_client.post(
        "/api/auth/setup",
        json={"setup_ticket": ticket},
        headers={"Origin": ORIGIN, "X-Requested-With": "LAPTOP_AI"},
    )
    print(f"     POST /api/auth/setup -> HTTP {r.status_code}")
    assert r.status_code == 200
    assert "session_token" not in r.json()
    assert r.json().get("status") == "active"
    assert "laptop_ai_session=" in r.headers.get("set-cookie", "")
    print("     [PASS] One-time setup ticket successfully exchanged for session cookie.")

    # 10b. Attempt replay of the SAME ticket
    r_replay = fresh_client.post(
        "/api/auth/setup",
        json={"setup_ticket": ticket},
        headers={"Origin": ORIGIN, "X-Requested-With": "LAPTOP_AI"},
    )
    print(f"     Replay POST /api/auth/setup -> HTTP {r_replay.status_code}")
    assert r_replay.status_code == 401
    print("     [PASS] Single-use ticket replay rejected (HTTP 401).")

    # 11. Lock / Revoke Session
    r = client.post(
        "/api/auth/revoke",
        headers={"Origin": ORIGIN, "X-Requested-With": "LAPTOP_AI"},
    )
    print(f"\n[11] POST /api/auth/revoke (Lock session) -> HTTP {r.status_code}")
    print(f"     Body: {r.json()}")
    assert r.status_code == 200
    assert r.json().get("status") == "revoked"
    print("     [PASS] Session revocation confirmed.")

    # 12. Verify revoked session cannot be reused
    r = client.get("/api/auth/session")
    print(f"\n[12] GET /api/auth/session (after revoke) -> HTTP {r.status_code}")
    print(f"     Body: {r.json()}")
    assert r.status_code == 200
    assert r.json().get("authenticated") is False
    print("     [PASS] Revoked session cookie rejected by backend.")

    # 12b. Attempt mutating action with revoked session
    r = client.post(
        "/api/settings",
        json={"theme": "dark"},
        headers={"Origin": ORIGIN, "X-Requested-With": "LAPTOP_AI"},
    )
    print(f"     POST /api/settings with revoked cookie -> HTTP {r.status_code}")
    assert r.status_code == 401
    print("     [PASS] Mutating request with revoked cookie blocked (HTTP 401).")

    print("\n" + "=" * 60)
    print("ALL LIVE HTTP ACCEPTANCE TESTS PASSED (12/12)!")
    print("=" * 60)

if __name__ == "__main__":
    run_live_tests()
