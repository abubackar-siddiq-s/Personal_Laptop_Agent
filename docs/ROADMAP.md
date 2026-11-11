# Roadmap

## Phase 1 — Agent Execution Engine (COMPLETED)
- [x] Structured agent loop with multi-turn support (`AgentEngine`).
- [x] Provider-specific function/tool calling for Google Gemini, Groq, and OpenRouter.
- [x] Unified tool registry with JSON Schema argument validation (`jsonschema`).
- [x] Provider tool name mapping (handling periods and schema sanitization).
- [x] Execution limits, per-tool timeouts, and graceful error recovery.
- [x] Support for multiple sequential tool calls in a single user request.
- [x] Server-side atomic approval lifecycle (`ApprovalLifecycle`).

## Phase 2 — Native Windows Tools (COMPLETED)
- [x] Expanded system information: detailed battery status, active network adapters, disk partitions.
- [x] Windows process management: inspect PID telemetry and safe process termination with critical system denylist.
- [x] Safe file and folder operations: path jailing to Documents, Desktop, Downloads; read file (up to 64KB), write file (approval required), directory listing.
- [x] Automatic user directory resolution: `FOLDER_ALIASES` for Downloads, Documents, Desktop without asking for Windows username.
- [x] Recursive file search with extension filtering, file sizes, and modification timestamps.
- [x] Multi-format file reading: text files, PDF extraction (`pypdf`), Word documents (`.docx` XML parser), and binary format detection.
- [x] MCP Server discovery tool: `native.mcp.list_servers` returning sanitized connection metadata with zero secret exposure.
- [x] Multimodal screen understanding: `native.screen.analyze` with vision capability detection avoiding false claims on text-only models.
- [x] Originating conversation binding and automatic completion notification for approved actions.
- [x] Application launching via approved Windows executable allowlist (`shell=False`, approval required).
- [x] Command execution with allowlist diagnostics and approval gating.
- [x] Windows display screen capture saved to `Downloads/Screenshots`.
- [x] Closed-loop chat reporting with `native.approvals.check`.

## Phase 3 — MCP Ecosystem (COMPLETED)
- [x] Stdio and Streamable HTTP transport support (`MCPManager`).
- [x] Persistent server configuration and state management in SQLite (`mcp_servers`).
- [x] Dynamic tool discovery and registration into the unified registry (`mcp.{server_id}.{tool_name}`).
- [x] Executable allowlists for stdio (`python`, `node`, `npx`, `uvx`, `uv`, `deno`, `git`).
- [x] SSRF protection (blocking `169.254.169.254` and requiring HTTPS for remote endpoints).
- [x] Environment variable sanitization preventing LLM secret leakage (`GEMINI_API_KEY`, `GROQ_API_KEY`, etc.).
- [x] Pre-flight connection probes preventing AnyIO generator cancellation collisions on offline endpoints.
- [x] Output truncation at 64KB (`MAX_TOOL_OUTPUT_CHARS`).
- [x] Server-side approval gating for all external MCP tool invocations (`risk="approval"`).
- [x] Automatic startup reconnection for all enabled MCP servers (`load_all_enabled`).
- [x] Full UI dashboard integration with server cards, tool counts, live status badges, connect/disconnect controls, and discovered tool tags.

## Phase 4 — Browser & Web Automation (COMPLETED)
- [x] Lightweight asynchronous Playwright engine with Chromium and lazy startup.
- [x] Persistent browser sessions and profile isolation in `backend/data/browser_profile`.
- [x] Multi-tab management: `browser.open`, `browser.close_tab`, `browser.list_tabs`, active tab switching.
- [x] Browser intelligence tools: navigation, back/forward/refresh, title/url inspection, text and link extraction.
- [x] Semantic element inspection and interaction: `browser.find_element`, `browser.click`, `browser.fill`, `browser.type`, `browser.select`, `browser.press_key`, `browser.scroll`.
- [x] Screenshot capture (`browser.screenshot`) saving to `Downloads/LAPTOP_AI/screenshots` with UI preview.
- [x] Legitimate web search subsystem (`browser.search`) using DuckDuckGo with ranking, snippets, and page content extraction.
- [x] Safe file download manager with duplicate protection and SQLite tracking in `Downloads/LAPTOP_AI`.
- [x] Browser security layer: scheme restrictions, private network and SSRF barrier (`127.0.0.1`, `169.254.169.254`), domain allowlists, and anti-prompt-injection isolation tags.
- [x] Server-side approval gating for consequential browser actions (`browser.click`, `browser.fill`, `browser.type`, `browser.select`, `browser.press_key`).
- [x] Professional React dashboard Browser workspace with interactive URL bar, live tabs, viewport preview, search, download history, and security rules management.

## Phase 5 — Memory, Planning & Autonomous Tasks (COMPLETED)
- [x] Persistent SQLite memory store with FTS5 full-text indexing and porter tokenization (`memories`, `memories_fts`).
- [x] Memory categorisation: user preferences, personal facts, active projects, project decisions, conversation summaries, workflows, and approved instructions.
- [x] Zero-leak credential filter: regex sanitizer rejecting API keys (OpenAI, Google, GitHub, AWS, private keys) before storage.
- [x] Case-insensitive text normalization, whitespace stripping, and duplicate memory rejection.
- [x] Access tracking: access count, provenance attribution, and `last_accessed_at` timestamps.
- [x] Conversation intelligence: selective, token-budgeted memory context injection into system prompts based on provider/model quotas.
- [x] Conversation summarization preserving decisions and automatic conversation title generation.
- [x] Intelligent task planner decomposing natural language requests into structured, dependency-ordered plans (`tasks`, `task_steps`).
- [x] Risk classification (`low`, `moderate`, `consequential`, `critical`) and approval gating for task steps.
- [x] Task execution engine with step-by-step execution, checkpoints, and idempotency (completed steps never re-run).
- [x] Task execution controls: pause, resume, cancel, and per-step retry.
- [x] Safe restart crash recovery for tasks and steps interrupted in progress.
- [x] Persistent SQLite task scheduler supporting interval, daily, and weekly schedules (`scheduled_tasks`) surviving restarts.
- [x] Universal offline Emergency Stop mechanism (`system_state`) immediately halting all tools, planner steps, and chat offline without LLM connectivity.
- [x] Premium React dashboard integration: top-bar emergency stop with modal & pulsing alert banner, dedicated Memory management tab with FTS5 search, and interactive Tasks & Automation timeline.

## Phase 6 — Security Hardening & Advanced Autonomy (PLANNED - AWAITING USER APPROVAL)
- [ ] Windows Credential Manager / DPAPI key encryption.
- [ ] Granular permission profiles and per-tool rate limiting.
- [ ] Advanced autonomous workflow loops.
