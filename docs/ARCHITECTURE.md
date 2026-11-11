# Architecture
The UI talks only to the loopback FastAPI backend. Provider adapters handle Google Gemini REST and OpenAI-compatible Groq/OpenRouter APIs. SQLite stores conversations, approvals and audit events.

## Agent Execution Engine (Phase 1)
- **Agent Loop (`AgentEngine`)**: Multi-turn agent loop with iteration limit (`max_iterations=6`) and per-tool timeout (`tool_timeout=30s`).
- **Provider Adapters (`chat_turn`)**:
  - **Google Gemini**: Uses `generateContent` with `functionDeclarations` and returns `functionResponse` turns.
  - **Groq & OpenRouter**: Uses OpenAI-compatible `/chat/completions` with `tools` schema, parsing `tool_calls` and returning `role: "tool"` responses.
- **Unified Tool Registry (`ToolRegistry`)**:
  - Bi-directional name mapping (`.` in registry namespaces to `_` for provider-safe function names).
  - Strict JSON Schema validation using `jsonschema` before handler invocation.
  - Automatic formatters: `get_openai_tools()` and `get_gemini_tools()`.
  - Structured execution returning `{"success": bool, "result" | "error"}`.

## Native Windows Tools (Phase 2)
- **System & Hardware Telemetry** (`risk="read"`):
  - `native.system.overview`: CPU, RAM, OS, primary disk telemetry.
  - `native.system.battery`: Battery percentage, AC charging status, discharge estimate.
  - `native.system.network`: Active network adapters, link speeds, IPv4 addresses.
  - `native.system.disks`: Partitions, volume mount points, filesystem types, storage usage.
- **Process Management**:
  - `native.system.processes` (`risk="read"`): Top processes sorted by memory consumption.
  - `native.process.inspect` (`risk="read"`): Detailed telemetry for specific PID (threads, CPU%, start time, username).
  - `native.process.terminate` (`risk="approval"`): Process termination with immutable system-critical denylist (PID 0, 4, `csrss.exe`, `lsass.exe`, `smss.exe`, `wininit.exe`, `services.exe`, `winlogon.exe`, `explorer.exe`, `dwm.exe`).
- **Safe File & Folder Operations**:
  - `native.files.search` (`risk="read"`): Fast recursive filename search within approved roots.
  - `native.files.list_dir` (`risk="read"`): Directory listing with file metadata.
  - `native.files.read` (`risk="read"`): Read text files up to 64KB within approved roots (`security.allowed()`).
  - `native.files.write` (`risk="approval"`): Overwrite or append files within approved user folders with explicit approval.
- **Application Launching**:
  - `native.app.launch` (`risk="approval"`): Launch approved Windows desktop apps (notepad, calc, paint, code, explorer) without shell execution (`shell=False`).
- **Observability & Diagnostics**:
  - `native.screen.capture` (`risk="read"`): Display screen grab saved to user Downloads/Screenshots.
  - `native.terminal.diagnostic` (`risk="approval"`): Allowlisted safe diagnostics (`whoami`, `ipconfig`, `python-version`, `git-version`, `node-version`).
  - `native.approvals.check` (`risk="read"`): Closed-loop verification of pending or completed approval output.

## Model Context Protocol (MCP) Ecosystem (Phase 3)
- **MCP Server Management (`MCPManager`)**:
  - Persistent SQLite backing via `mcp_servers` table (`id`, `name`, `transport`, `command`, `args`, `env`, `url`, `enabled`, `status`, `tool_count`, `error`, `last_connected_at`).
  - Supports `stdio` and `streamable-http` transports using the official MCP Python SDK (`mcp.client.stdio` and `mcp.client.streamable_http`).
  - Startup auto-reconnect (`load_all_enabled`) connects all enabled servers when the backend initializes.
  - Bounded reconnection retries with exponential backoff.
- **Dynamic Tool Discovery & Namespacing**:
  - Discovers tool definitions via `session.list_tools()`.
  - Namespaces tools as `mcp.{server_id}.{tool_name}`, mapped bi-directionally to `mcp_{server_id}_{tool_name}` for provider function-calling compatibility.
  - Preserves JSON Schemas (`inputSchema`) and registers tools into `ToolRegistry`.
  - Tool unregistration on server disconnect / deletion to prevent stale invocations.
- **MCP Security Architecture**:
  - **Executable Allowlist**: `stdio` transport commands must be in the approved allowlist (`python`, `node`, `npx`, `uvx`, `uv`, `deno`, `git`).
  - **Environment Sanitization**: Spawns stdio processes with a minimal safe environment (`PATH`, `SYSTEMROOT`, etc.), explicitly stripping sensitive LLM keys (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`).
  - **SSRF Protection**: Prohibits cloud metadata addresses (`169.254.169.254`, `metadata.google.internal`) and requires HTTPS for all external non-loopback endpoints.
  - **Pre-Flight Network Probe**: Validates HTTP socket reachability via `httpx` before entering the streamable HTTP async generator, preventing AnyIO generator cancellation conflicts.
  - **Payload Size Limits**: Truncates MCP tool outputs at 64,000 characters with an explicit truncation indicator.
  - **Execution Timeouts**: Enforces a 30-second default timeout on all MCP tool calls.
  - **Approval Gating**: All discovered MCP tools default to `risk="approval"`, ensuring untrusted third-party tool executions require explicit user approval.

## Browser & Web Automation (Phase 4)
- **Browser Engine (`BrowserEngine`)**:
  - Uses Playwright's Python asynchronous API with Chromium.
  - **Lazy Initialization**: Chromium launches only upon the first browser tool request and releases resources cleanly via `browser.close()` on backend shutdown.
  - **Persistent Session Profile**: Stores session cookies, localStorage, and logins in `backend/data/browser_profile`.
  - **Tab Management**: Tracks and switches up to 10 concurrent tabs (`browser.open`, `browser.close_tab`, `browser.list_tabs`, `browser.switch_tab`).
  - **Download Detection**: Event-driven download handling saving to `Downloads/LAPTOP_AI` with duplicate filename protection (`file (1).ext`) and SQLite logging in `browser_downloads`. Never automatically executes downloaded files.
  - **Screenshot Capture**: Saves viewport and full-page screenshots to `Downloads/LAPTOP_AI/screenshots` and returns base64 images for UI preview.
- **Browser Intelligence Tools**:
  - Navigation: `browser.navigate`, `browser.back`, `browser.forward`, `browser.refresh`, `browser.get_url`, `browser.get_title`.
  - Content Extraction: `browser.get_text` (anti-prompt-injection isolated), `browser.get_links` (hyperlinks with text and URLs).
  - Semantic Interaction: `browser.find_element`, `browser.click`, `browser.fill`, `browser.type`, `browser.select`, `browser.press_key`, `browser.scroll`.
- **Web Search Subsystem**:
  - Legitimate search querying via DuckDuckGo public interface (`search_web`).
  - Extracts ranked results with titles, source URLs, and snippet summaries without brittle scraping.
- **Browser Security Architecture**:
  - **Scheme Restrictions**: Only `http://` and `https://` permitted; `file://`, `javascript:`, `data:`, `chrome://` blocked.
  - **Private Network & SSRF Barrier**: Blocks loopback (`127.0.0.1`, `::1`), private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and metadata services (`169.254.169.254`).
  - **Domain Allowlists & Blocklists**: Configurable rules stored in `browser_security_rules` table.
  - **Anti-Prompt Injection Wrapping**: External webpage text is strictly framed in `[UNTRUSTED WEBPAGE CONTENT START ... END]` headers.
  - **Approval Gating**: Consequential actions (`browser.click`, `browser.fill`, `browser.type`, `browser.select`, `browser.press_key`) require explicit user approval (`risk="approval"`). Read-only browsing (`get_text`, `navigate`, `screenshot`, `search`) runs without approval within security boundaries.

## Persistent Memory, Planning & Autonomous Task Management (Phase 5)
- **Persistent Memory Engine (`MemoryEngine`)**:
  - Local SQLite storage using `memories` table and `memories_fts` FTS5 virtual table with Porter tokenization.
  - Categories: `user_preference`, `personal_fact`, `active_project`, `project_decision`, `conversation_summary`, `workflow`, and `approved_instruction`.
  - Zero-credential-leak sanitization rejecting API tokens (`sk-`, `AIza...`, `ghp_`, AWS, private keys) before persistence.
  - Case-insensitive text normalization, whitespace stripping, and duplicate rejection.
  - Provenance attribution and access tracking (`access_count`, `last_accessed_at`).
- **Conversation Intelligence (`conversation_intelligence`)**:
  - Provider-aware selective memory injection into system prompts based on provider/model token budgets (e.g., 250 tokens for Groq `gpt-oss-20b`, up to 1,200 for Gemini 2.5 Flash).
  - Memory injection is keyword- and topic-filtered; zero memory tokens are injected on generic or unrelated tasks.
  - Automatic conversation title generation (concise 3–6 word phrases).
  - Decision-preserving conversation summarization for long dialogues.
- **Intelligent Task Planner (`TaskPlanner`)**:
  - Natural language plan decomposition with step dependency ordering (`depends_on`).
  - Risk classification (`low`, `moderate`, `consequential`, `critical`) and automatic identification of approval-gated tools.
  - LLM plan generation with deterministic regex-heuristic fallback.
- **Task Execution Engine (`TaskExecutor`)**:
  - Sequential step execution respecting topological dependencies.
  - Step-by-step SQLite checkpointing: completed steps (`status="completed"`) are idempotent and never re-executed.
  - Approval binding: steps requiring approval create an approval request and suspend execution until the approval state transitions to `executed`.
  - Crash recovery on backend startup: interrupted steps in `in_progress` are marked `failed` to prevent unmonitored reruns.
- **Task Scheduler (`TaskScheduler`)**:
  - SQLite-backed scheduled automation supporting `once`, `daily`, `weekly`, and `interval` triggers.
  - Background 10-second polling loop within FastAPI lifecycle.
  - Immediate `next_run_at` advancement preventing double execution across restarts.
- **Offline Emergency Stop System (`emergency.py`)**:
  - Backed by SQLite table `system_state`.
  - Functions completely offline without LLM connectivity.
  - Universal enforcement: blocks tool executions in `ToolRegistry.run` and `ToolRegistry.execute`, suspends task executor steps, and halts `/chat` API requests with explanatory messaging.

## Strict Server-Side Approval Lifecycle (`ApprovalLifecycle`)
Sensitive operations (`risk != "read"`) enforce an atomic server-side state machine:
- **Lifecycle States**:
  - `pending`: Request created, assigned a cryptographically random UUID token, bound to an immutable SHA-256 argument hash, and assigned a 15-minute expiration timestamp (`expires_at`). Execution is blocked.
  - `executing`: Atomic transition `UPDATE ... WHERE id=? AND status='pending'`. Guarantees exactly-once execution under concurrent requests.
  - `executed`: Operation completed; output timestamp and full execution result JSON persisted in SQLite.
  - `rejected`: Explicit user refusal; permanently blocked from execution.
  - `failed`: Execution failed, argument tampering detected, or execution interrupted by shutdown; failure reason logged.
  - `expired`: Approval request exceeded TTL; automatically rejected upon evaluation.
- **Security Guarantees**:
  - **Zero Trust on Model/Client Decisions**: The model cannot approve actions. The client cannot bypass approvals by sending `approved=True` to `/tools/run`.
  - **Replay Protection**: Completed, rejected, or expired approvals cannot be executed again (HTTP 409 Conflict).
  - **Tamper Protection**: Argument hash (`args_hash`) is verified prior to execution.
  - **Concurrency Safety**: SQLite atomic conditional updates prevent race conditions and double execution.
  - **Interrupted Recovery**: Stuck `executing` records are marked `failed` on startup; dangerous operations are never automatically rerun.

## Security Boundary
The model has no direct OS access. Tools are explicit backend capabilities. Filesystem access is strictly jailed to Documents, Desktop and Downloads. Terminal commands use a fixed allowlist and `shell=False`. Process termination protects core operating system processes. Sensitive operations require user approval.
