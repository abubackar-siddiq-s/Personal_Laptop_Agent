import sys
import os
from fastapi.testclient import TestClient

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.main import app
from app.core.security import get_test_session_token

def main():
    token = get_test_session_token()
    with TestClient(app) as client:
        payload = {
            "message": "Identify my currently active Windows application. Return its window title, process name, PID, HWND, dimensions, and minimized status.",
            "provider": "groq",
            "model": "openai/gpt-oss-20b"
        }

        print("Sending /api/chat request...")
        response = client.post(
            "/api/chat",
            json=payload,
            headers={"origin": "http://127.0.0.1:5173", "X-Session-Token": token}
        )
        print("Status code:", response.status_code)
        data = response.json()
        print("\n=== ASSISTANT REPLY ===")
        print(data.get("reply"))
        print("\n=== TOOL EXECUTIONS ===")
        for te in data.get("tool_executions", []):
            print(f"Tool: {te.get('tool_name')} | Success: {te.get('success')}")
            print(f"Result: {te.get('result')}")

if __name__ == "__main__":
    main()
