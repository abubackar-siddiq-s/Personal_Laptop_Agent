import asyncio
import io
import json
import os
import sys
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

sys.path.insert(0, "backend")
os.environ["LAPTOP_AI_TEST_MODE"] = "1"

from app.core.config import BASE
from app.core.db import init_db, conn
from app.core.approval import ApprovalLifecycle
from app.core.agent import sanitize_tool_result_for_llm, AgentEngine
from app.browser import browser, register_browser_tools, search_web
from app.tools.registry import registry
from app.tools.native import register as register_native

TEST_PORT = 8940
DOWNLOADS_DIR = Path(os.environ.get("USERPROFILE", "C:\\Users\\Abubackar Siddiq S")) / "Downloads" / "LAPTOP_AI"

# Minimal valid PDF file bytes for testing (%PDF-1.4 header and minimal xref)
SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
    b"4 0 obj\n<< /Length 21 >>\nstream\nBT /F1 12 Tf ET\nendstream\nendobj\n"
    b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000214 00000 n \n"
    b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n285\n%%EOF\n"
)


class MockServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/multi_h1":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                "<!DOCTYPE html><html><head><title>Multi Heading Page</title></head><body>"
                "<h1>First Primary Heading</h1>"
                "<h1>Second Section Heading</h1>"
                "<h1>Third Subsection Heading</h1>"
                "<p>Some description paragraph text.</p>"
                "<button id='action-btn'>Click Me</button>"
                "</body></html>"
            )
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/sample.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="sample_document.pdf"')
            self.end_headers()
            self.wfile.write(SAMPLE_PDF_BYTES)
        elif self.path == "/fake.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            self.wfile.write(b"<html><body>This is an HTML fake file posing as PDF</body></html>")
        elif self.path == "/page2":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<!DOCTYPE html><html><head><title>Second Tab Page</title></head><body><h2>Second Page Content</h2></body></html>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_server():
    httpd = HTTPServer(("127.0.0.1", TEST_PORT), MockServer)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


async def run_audit_suite():
    print("=" * 60)
    print("STARTING PHASE 4 BROWSER AUDIT & REMEDIATION SUITE")
    print("=" * 60)

    init_db()
    register_native()
    register_browser_tools()
    server = start_server()

    # ---------------------------------------------------------
    # TEST 1: Kwarg Resilience & Strict Mode Resolution (Issue 1)
    # ---------------------------------------------------------
    print("\n--- TEST 1: Kwarg Resilience & Strict Mode Resolution ---")
    await browser.open_tab(f"http://127.0.0.1:{TEST_PORT}/multi_h1")

    # 1a. get_title with extra kwargs (tab_index=0)
    title_res = await registry.execute("browser.get_title", {"tab_index": 0, "extra_flag": True})
    assert title_res["success"], f"get_title failed with kwargs: {title_res}"
    assert "Multi Heading Page" in str(title_res["result"]), f"Unexpected title: {title_res['result']}"
    print("[PASS] 1a. browser.get_title cleanly absorbs extra kwargs without TypeError")

    # 1b. get_text with multi-h1 selector (verifies strict mode resolution)
    text_res = await registry.execute("browser.get_text", {"selector": "h1", "tab_index": 0})
    assert text_res["success"], f"get_text failed on multi h1: {text_res}"
    assert "First Primary Heading" in text_res["result"], "Missing first h1"
    assert "Second Section Heading" in text_res["result"], "Missing second h1"
    assert "Third Subsection Heading" in text_res["result"], "Missing third h1"
    print("[PASS] 1b. browser.get_text extracts all matching elements without strict mode crash")

    # ---------------------------------------------------------
    # TEST 2: Search Quality & Canonical Documentation (Issue 2)
    # ---------------------------------------------------------
    print("\n--- TEST 2: Search Quality & Canonical Documentation ---")
    ddg_res = await search_web("official FastAPI documentation", max_results=5)
    assert len(ddg_res) > 0, "No search results returned"
    top_result = ddg_res[0]
    print(f"Top result: [{top_result['source_type'].upper()}] {top_result['title']} -> {top_result['url']}")
    assert top_result["is_canonical"] == True, "Top result must be canonical official docs"
    assert "fastapi.tiangolo.com" in top_result["url"], "Top URL must be fastapi.tiangolo.com"

    for r in ddg_res:
        if "devdocs.io" in r["url"]:
            assert r["source_type"] == "third_party"
            assert "[Third-Party]" in r["title"]
    print("[PASS] 2. Official documentation ranked #1; third-party mirrors demoted/filtered")

    # ---------------------------------------------------------
    # TEST 3: Multiple Tabs, Screenshot & Vision Guardrails (Issue 3)
    # ---------------------------------------------------------
    print("\n--- TEST 3: Multiple Tabs, Screenshot & Vision Guardrails ---")
    # 3a. Open second tab
    tab2 = await browser.open_tab(f"http://127.0.0.1:{TEST_PORT}/page2")
    tabs = await browser.list_tabs()
    assert len(tabs) >= 2, f"Expected at least 2 open tabs, found {len(tabs)}"
    print(f"[PASS] 3a. Successfully opened multiple tabs: {len(tabs)} tabs active")

    # 3b. Screenshot summary for LLM context (avoids massive base64)
    ss_summary = await registry.execute("browser.screenshot", {"full_page": False})
    assert ss_summary["success"], f"Screenshot failed: {ss_summary}"
    assert "base64" not in ss_summary["result"], "Screenshot tool for LLM must NOT contain massive base64 payload"
    assert Path(ss_summary["result"]["filepath"]).exists(), "Screenshot file was not saved on disk"
    print(f"[PASS] 3b. Screenshot saved to disk ({ss_summary['result']['filepath']}); massive base64 omitted from tool output")

    # 3c. Large payload sanitization in agent loop
    fake_huge_res = {"status": "ok", "base64": "A" * 150_000, "meta": "test"}
    sanitized = sanitize_tool_result_for_llm(fake_huge_res)
    assert len(sanitized) < 1_000, f"Sanitized payload unexpectedly long: {len(sanitized)}"
    assert "<base64" in sanitized, "Base64 placeholder missing"
    print("[PASS] 3c. Large tool results sanitized; base64 payload stripped to protect model token limits")

    # 3d. Vision analysis model detection (text-only model guardrail)
    vision_res = await browser.analyze_active_tab(provider="groq", model="openai/gpt-oss-20b")
    assert vision_res["success"] == False, "Text-only model should not claim visual understanding"
    assert vision_res["visual_understanding"] == False, "visual_understanding must be False"
    assert "text-only" in vision_res["message"].lower(), "Expected polite notice about text-only model"
    print("[PASS] 3d. Non-multimodal model correctly identified; clear explanation returned without hallucination")

    # ---------------------------------------------------------
    # TEST 4: Approval-to-Browser-Action Workflow (Issue 4)
    # ---------------------------------------------------------
    print("\n--- TEST 4: Approval-to-Browser-Action Workflow ---")
    conv_id = 999
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO conversations (id, title) VALUES (?, ?)", (conv_id, "Audit Test Conversation"))

    # Switch back to tab 0 or navigate to page with #action-btn
    await browser.navigate(f"http://127.0.0.1:{TEST_PORT}/multi_h1")

    req = ApprovalLifecycle.create_request("browser.click", {"selector": "#action-btn"}, risk="approval", conversation_id=conv_id)
    aid = req["id"]
    assert req["status"] == "pending"

    # Execute approval
    exec_res = await ApprovalLifecycle.approve_and_execute(aid, decision_by="user:test")
    assert exec_res["status"] == "executed", f"Approval execution failed: {exec_res}"
    assert exec_res["result"]["status"] == "success", "browser.click did not report success"

    # Verify message insertion in conversation
    with conn() as c:
        msg = c.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1", (conv_id,)).fetchone()
        assert msg is not None, "Notification message was not inserted into conversation"
        assert f"Approval #{aid}" in msg["content"], "Message did not reference approval ID"
        assert "browser.click" in msg["content"], "Message did not reference tool name"
        assert "executed" in msg["content"], "Message did not reference executed status"
    print(f"[PASS] 4. Approval #{aid} executed cleanly and notified conversation #{conv_id}")

    # ---------------------------------------------------------
    # TEST 5: PDF Download & Format Validation (Issue 3 & Point E)
    # ---------------------------------------------------------
    print("\n--- TEST 5: PDF Download & Format Validation ---")
    # 5a. Valid PDF download
    pdf_url = f"http://127.0.0.1:{TEST_PORT}/sample.pdf"
    dl_res = await browser.download_file(url=pdf_url, expected_type="pdf")
    assert dl_res["status"] == "success", f"Download failed: {dl_res}"
    assert dl_res["magic_bytes_valid"] == True, "PDF magic bytes were not verified"
    assert dl_res["pages"] == 1, f"Expected 1 PDF page, got {dl_res['pages']}"
    saved_file = Path(dl_res["filepath"])
    assert saved_file.exists(), "Downloaded file does not exist on disk"
    assert saved_file.stat().st_size > 0, "Downloaded file is 0 bytes"
    assert saved_file.parent == DOWNLOADS_DIR, f"File saved in wrong directory: {saved_file.parent}"

    # Verify record in browser_downloads SQLite table
    with conn() as c:
        row = c.execute("SELECT * FROM browser_downloads WHERE filename=?", (saved_file.name,)).fetchone()
        assert row is not None, "Download not recorded in browser_downloads DB table"
    print(f"[PASS] 5a. Downloaded valid PDF '{saved_file.name}' ({dl_res['size_formatted']}), verified %PDF- header and pypdf structure")

    # 5b. Invalid / fake PDF rejection
    fake_pdf_url = f"http://127.0.0.1:{TEST_PORT}/fake.pdf"
    rejected = False
    try:
        await browser.download_file(url=fake_pdf_url, expected_type="pdf")
    except ValueError as ve:
        rejected = True
        assert "magic bytes" in str(ve).lower(), f"Unexpected error: {ve}"
    assert rejected, "Fake PDF without %PDF- magic bytes was not rejected!"
    print("[PASS] 5b. Fake PDF without %PDF- magic bytes successfully rejected; untrusted execution blocked")

    # ---------------------------------------------------------
    # CLEANUP
    # ---------------------------------------------------------
    await browser.close()
    server.shutdown()
    print("\n" + "=" * 60)
    print("ALL 5/5 PHASE 4 BROWSER AUDIT TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_audit_suite())
