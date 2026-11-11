# LAPTOP AI
A local-first Windows personal AI workspace. React/Vite dashboard + FastAPI + SQLite. Cloud inference via Gemini, Groq and OpenRouter. Native Python tools and external MCP (stdio + Streamable HTTP).

## Install
Requirements: Windows 10/11, Python 3.11+, Node.js 20+.
```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
.\scripts\start.ps1
```
Open http://127.0.0.1:5173. API docs: http://127.0.0.1:8000/docs.

Configure API keys in Settings. Keys are stored in `backend/.env`; restart backend after saving. Never paste keys into chat.

## Included
- Premium responsive dark dashboard with multi-provider chat, system telemetry, browser automation workspace, memory management, task planner & scheduler, MCP server controls, and approval audit feed.
- Gemini REST integration; Groq/OpenRouter OpenAI-compatible API integration with token budgeting, rate-limit resilience, and automatic fallback.
- SQLite persistence (WAL mode) for chat history, memories, tasks, schedules, and approvals.
- Native Windows system telemetry, battery stats, network interfaces, disk storage, process listing, restricted file operations, document reading (PDF, DOCX, TXT), and allowlisted diagnostic commands.
- Browser automation engine powered by Playwright with tab management, web search, page navigation, semantic interaction, and screenshot capture.
- Persistent Memory Engine with SQLite FTS5 full-text indexing, categorized memories, zero-credential-leak sanitization, duplicate prevention, and token-budgeted prompt injection.
- Intelligent Task Planner & Execution Engine with dependency-ordered multi-step plans, checkpointing, idempotency, and restart recovery.
- SQLite-backed Task Scheduler for one-time and recurring automated jobs.
- Universal Offline Emergency Stop mechanism immediately halting all tools, planner steps, and chat without LLM connectivity.
- MCP stdio and Streamable HTTP client using the official MCP Python SDK with dynamic tool discovery and approval gating.

## Safety
MCP servers are third-party executable code. Only connect trusted servers. Local backend binds to 127.0.0.1. Filesystem search is limited to Documents/Desktop/Downloads. PowerShell is not unrestricted: only named diagnostic commands are allowed. Model output never becomes shell input. This is a working starter release, not unrestricted computer control.

No Docker, OpenClaw or LM Studio. See docs/ARCHITECTURE.md and docs/ROADMAP.md.
