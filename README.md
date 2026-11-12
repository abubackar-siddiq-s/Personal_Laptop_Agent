# LAPTOP AI — Personal Windows AI Assistant
### Complete Technical & User Guide (Phase 6 Production Release)

LAPTOP AI is an intelligent, local-first Windows personal AI assistant engineered for lightweight execution on Windows 10/11 workstations (optimized for dual-core Intel Core i5-6300U, 8 GB RAM, and SSD storage).

It integrates React 18, TypeScript, and Vite with a high-performance Python FastAPI backend, local SQLite persistence (WAL mode), multi-provider cloud inference (Google Gemini, Groq, OpenRouter), and deep Windows desktop automation, visual intelligence, file intelligence, and proactive assistance subsystems.

---

## 1. System Architecture & Hardware Footprint

```mermaid
flowchart TD
    UI[React + Vite Frontend (localhost:5173)] <-->|HTTP + Session Token| API[FastAPI Backend (127.0.0.1:8000)]
    
    subgraph CoreEngine [Core Backend Engine]
        API <--> ApprovalGate[Cryptographic Approval Lifecycle]
        API <--> EmerStop[Global Emergency Stop Barrier]
        API <--> TokenBudget[Preflight Token Budget & Scoper]
        API <--> Agent[Multi-Turn Agent Execution Engine]
    end

    subgraph Subsystems [Subsystems (Phase 1 - 6)]
        Agent <--> DesktopEngine[Desktop Control & UI Automation]
        Agent <--> VisionEngine[Visual Intelligence & WinRT OCR]
        Agent <--> FileEngine[Document & FTS5 Semantic Search]
        Agent <--> AssistantEngine[Proactive Personal Assistance]
        Agent <--> BrowserEngine[Playwright Browser Automation]
        Agent <--> NativeTools[Native Windows Telemetry & Tools]
        Agent <--> MCPEngine[Model Context Protocol SDK]
        Agent <--> TaskPlanner[Intelligent Task Planner & Scheduler]
    end

    subgraph InferenceProviders [External Cloud Inference]
        Agent <--> Gemini[Google Gemini 2.5 Flash]
        Agent <--> Groq[Groq Llama 3.3 / GPT-OSS 20B]
        Agent <--> OpenRouter[OpenRouter Auto Router]
    end

    subgraph Storage [Local Persistence (WAL Mode)]
        API <--> DB[(SQLite database: laptop_ai.db)]
    end
```

### Verified Target Hardware Measurements
- **Target Workstation**: Intel Core i5-6300U @ 2.40GHz (2 Cores, 4 Threads), 8 GB RAM, Windows 10 Pro
- **Backend Idle Memory**: **52.1 MB** RSS
- **Active Memory (OCR + Indexing)**: **63.5 MB** RSS
- **Idle CPU Usage**: **0.0%**
- **Startup Time**: **1.19 seconds**
- **Database Size**: **2.28 MB** (WAL: ~8 KB)
- **Local Neural Model Dependency**: **Zero** (no Docker, no Ollama, no LM Studio)

---

## 2. Installation & Quickstart

### Prerequisites
1. Windows 10 (version 1903+) or Windows 11.
2. Python 3.11 or 3.12 (64-bit).
3. Node.js 20+ and npm.
4. Active API key from at least one supported provider:
   - Google Gemini: [Google AI Studio](https://aistudio.google.com/)
   - Groq: [Groq Console](https://console.groq.com/)
   - OpenRouter: [OpenRouter Keys](https://openrouter.ai/keys)

### One-Click Installation
Open PowerShell as an Administrator or regular user:
```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
```
This automatically configures the Python virtual environment (`backend/.venv`), installs dependencies, sets up Playwright Chromium, and installs frontend npm packages.

### Starting LAPTOP AI
```powershell
.\scripts\start.ps1
```
The startup script launches:
- **FastAPI Backend**: `http://127.0.0.1:8000` (Swagger docs: `http://127.0.0.1:8000/docs`)
- **Vite React UI**: `http://127.0.0.1:5173`

---

## 3. Configuration & Inference Setup

LAPTOP AI persists environment configuration in `backend/.env`. You can configure keys directly in the dashboard **Models** tab or by editing `backend/.env`:

```ini
# Primary Inference Providers
GEMINI_API_KEY=AIzaSy...
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-v1-...

# Rate-Limit & Fallback Configuration
AUTO_PROVIDER_FALLBACK=true
FALLBACK_PROVIDER=gemini
FALLBACK_MODEL=gemini-2.5-flash
```

### Supported Models & Providers
1. **Google Gemini**:
   - `gemini-2.5-flash` (Recommended for multimodal screen analysis, document questions, and complex tasks)
   - `gemini-2.5-pro`
2. **Groq**:
   - `llama-3.3-70b-versatile` (High speed text reasoning)
   - `openai/gpt-oss-20b` (Bounded TPM usage)
3. **OpenRouter**:
   - `openrouter/auto` (Flexible multi-model fallback)

---

## 4. Complete Feature Guide (14 Dashboard Tabs)

### 1. Overview
High-level control cockpit displaying current system status, quick actions, local engine connectivity, and active alerts.

### 2. Assistant (Proactive Personal Assistance — Queue 4)
- **Daily Briefing**: Synthesizes today's tasks, approaching deadlines (next 72h), overdue items, pending approvals, and actionable next steps strictly grounded in SQLite database state without hallucinating events.
- **Natural Language Task Quick-Add**: Parses requests like *"Finish quarterly budget by 5pm tomorrow #finance"* with automated priority reasoning (critical, high, medium, low) and conflict warnings if scheduled outside working hours.
- **Intelligent Reminders**: Schedule one-time, daily, weekly, interval, or deadline reminders with snooze (+15m, +1h), dismiss, and startup recovery (notifies of reminders that passed while the backend was offline).
- **Continuous Monitors**: User-configurable background watchers for task overdues, scheduler failures, pending approvals (>1h), and file changes.
- **Profile & Preferences**: Manages working hours, goals, and communication styles. Enforces strict visual distinction between **Confirmed Facts** and **Inferred Preferences**, screening out passwords and API keys.
- **Notification Center**: Persistent notifications with read/unread tracking and duplicate suppression.

### 3. Chat
- Multi-turn conversational interface with auto-scoping of relevant tools.
- Real-time tool execution logs and streaming telemetry.
- Seamless provider fallback when rate limits occur.

### 4. Desktop (Windows Desktop Control — Queue 1)
- **Active Window Telemetry**: Foreground HWND, title, process name, PID, coordinates, minimized/maximized status.
- **Window Enumeration**: Filtered listing of all top-level desktop windows.
- **Desktop Screenshots**: High-resolution desktop captures saved to `Downloads/LAPTOP_AI/screenshots/`.
- **UI Automation Inspection**: Traverses the Windows UI Automation tree, calculating exact descendant counts (total, visible, interactive).
- **Keyboard & Mouse Control**: Validated keystrokes, allowlisted shortcuts (`ctrl+c`, `ctrl+v`, `alt+tab`), and coordinate bounds-checking. Dangerous shortcuts (`win+l`, `ctrl+alt+del`) are strictly blocked.

### 5. Visual AI (Visual Desktop Intelligence — Queue 2)
- **Screen Analysis**: Multimodal visual scene understanding powered by Gemini 2.5 Flash.
- **Hardware-Accelerated OCR**: Native Windows 10 `winrt_native` OCR extraction (1.21s latency, 0 MB neural weight footprint).
- **Prompt Injection Defense**: Sanitizes extracted OCR text and neutralizes prompt-injection attempts before passing to LLM context.
- **Visual Compare**: Highlights pixel diffs between two application states.
- **Visual Element Detection**: Locates buttons, text fields, and menus visually with coordinate bounding boxes.

### 6. Files (Advanced File Intelligence — Queue 3)
- **Universal Document Comprehension**: Parses PDF, DOCX, XLSX, PPTX, CSV, TXT, MD, JSON, XML, HTML, RTF.
- **FTS5 Semantic Content Search**: SQLite FTS5 full-text indexing with BM25 ranking.
- **Spreadsheet Analytics**: Header detection, statistical profiling, interactive column filtering, and formula extraction.
- **Duplicate Detection**: Fast SHA-256 content deduplication with wasted disk space calculation.
- **Smart Organizer & Quarantine**: Preview-driven file cleanup with isolated quarantine and atomic rollback token.

### 7. Tasks
- Multi-step structured planning engine.
- Sequential dependency-ordered execution with step checkpoints.
- Restart recovery: interrupted tasks cleanly enter paused status without blindly re-running side effects.

### 8. Memory
- Persistent episodic and semantic memory engine with FTS5 search.
- Categorization (`user_preference`, `system_rule`, `project_context`).
- Automatic prompt injection of relevant memories; zero injection for unrelated queries.

### 9. Browser
- Headless / visible Chromium automation driven by Playwright.
- Multi-tab management and web search.
- Strict SSRF protection: blocks private IPs, loopback, file://, and cloud metadata.
- PDF download validation with `%PDF-` magic header checks.

### 10. Tool Registry
- Central inventory of all 48 tools.
- Granular risk classification (`read` vs `approval`).
- Schema validation and test harness.

### 11. Models
- Provider connectivity indicators, API key editors, and token budget gauges.
- Automatic provider fallback toggles.

### 12. Activity Log & Approvals
- Cryptographic Approval Lifecycle: Single-use approvals with SHA-256 argument binding and TTL expiration.
- Real-time audit log of all executed and blocked operations.

### 13. Settings
- User preferences, working hours, and engine toggles.

### 14. System
- Hardware utilization gauges (CPU, RAM, Disks, Battery).
- Allowlisted terminal diagnostic utility.

---

## 5. Security Architecture & Controls

1. **Local API Session Security**:
   - Backend requires requests to originate from loopback (`127.0.0.1`, `::1`).
   - Web requests must match allowed local origins (`http://127.0.0.1:5173`, `http://127.0.0.1:8000`).
   - State-changing requests enforce a 64-character session token (`X-Session-Token` or `laptop_ai_session` HttpOnly cookie) issued exclusively via `/api/auth/session`.
2. **Approval Gate for Consequential Operations**:
   - Operations that modify the system (process launch, terminal diagnostics, desktop clicks, keystrokes, browser clicks, file moves, quarantines) are classified as `risk="approval"`.
   - Requires explicit user confirmation in the dashboard.
   - Approvals are single-use, expire after 15 minutes, and verify SHA-256 argument hashes against tampering.
3. **Global Emergency Stop**:
   - Immediate halt of all native tools, desktop automation, browser actions, MCP calls, file operations, tasks, scheduler ticks, and reminders.
   - Operates strictly offline via SQLite without requiring any LLM connection.
   - Resuming requires explicit user action and does not automatically re-run blocked operations.
4. **Filesystem Jailing & Path Traversal Prevention**:
   - File actions are restricted strictly to user folders: `Documents`, `Downloads`, `Desktop`.
   - Directory traversal attempts (`../`) and Windows system folders (`C:\Windows`, `C:\Program Files`) are rejected.
5. **Prompt Injection & External Untrusted Data Containment**:
   - External text from OCR, downloaded files, and browser pages is treated as untrusted and screened for instruction injection patterns before ingestion.
6. **Credential Hygiene**:
   - Audit logs, tool outputs, and assistant profiles automatically redact API keys, tokens, and credentials.

---

## 6. Troubleshooting & Operations

### Database Backup & Restore
The SQLite database is located at `backend/laptop_ai.db`.
- **Backup**:
  ```powershell
  Copy-Item "backend/laptop_ai.db" "backend/laptop_ai_backup.db"
  ```
- **Restore**:
  Stop the backend process (`Stop-Process -Name python`), copy the backup file back to `backend/laptop_ai.db`, and restart.

### Resetting Emergency Stop via CLI
If the backend is in an emergency stop state and the dashboard is inaccessible:
```powershell
backend\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'backend'); from app.core.emergency import clear_emergency_stop; clear_emergency_stop()"
```

### Common Issues
- **Port 8000 or 5173 in use**: Check running processes with `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess` and terminate if stale.
- **Provider Rate Limits (HTTP 429)**: Enable **Auto Provider Fallback** in Settings to automatically route queries to Google Gemini 2.5 Flash when Groq hits its 8,000 TPM limit.
- **COM Initialization Warnings on Windows**: `pywinauto` STA COM threading warnings are normal during UI Automation discovery and do not impact reliability.
