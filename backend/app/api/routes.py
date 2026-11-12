from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dotenv import set_key
from app.core.config import BASE, settings
from app.core.db import conn
from app.core.security import audit
from app.core.agent import agent_engine
from app.core.approval import ApprovalLifecycle, ApprovalError
from app.providers.router import status
from app.tools.registry import registry
from app.tools.mcp_manager import mcp
from app.browser import browser, search_web
from app.memory import memory_engine, MemoryCreate, MemoryUpdate
from app.planner import task_planner, task_executor, task_scheduler, TaskPlanCreate, TaskPlanUpdate
import asyncio
from app.core.emergency import is_emergency_stopped, trigger_emergency_stop, clear_emergency_stop, get_emergency_status
from app.core.conversation_intelligence import (
    maybe_summarize_conversation,
    generate_conversation_title,
    summarize_conversation,
    get_historical_decisions,
    get_project_context,
)

def verify_local_origin(request: Request):
    """Enforce strict access control: Loopback client only and local origin to prevent CSRF/remote execution."""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(
            403,
            f"Security Violation: Remote access from host '{client_host}' is blocked for approval operations.",
        )
    origin = request.headers.get("origin")
    if origin:
        allowed = ("http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000", "http://localhost:8000")
        if not any(origin.startswith(a) for a in allowed):
            raise HTTPException(403, f"Security Violation: Cross-origin request from '{origin}' is forbidden.")


r = APIRouter(dependencies=[Depends(verify_local_origin)])


class Chat(BaseModel):
    message: str
    conversation_id: int | None = None
    provider: str = "groq"
    model: str = "openai/gpt-oss-20b"


class Key(BaseModel):
    provider: str
    api_key: str


class Stdio(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class Http(BaseModel):
    name: str
    url: str


class Run(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


@r.get("/health")
def health():
    return {"ok": True, "name": "LAPTOP AI", "version": "0.2.0"}


@r.get("/providers")
def providers():
    st = status()
    st["settings"] = {
        "auto_provider_fallback": settings.auto_provider_fallback,
        "fallback_provider": settings.fallback_provider,
        "fallback_model": settings.fallback_model,
    }
    return st


class SettingsUpdate(BaseModel):
    auto_provider_fallback: bool | None = None
    fallback_provider: str | None = None
    fallback_model: str | None = None


@r.get("/settings")
def get_app_settings():
    return {
        "auto_provider_fallback": settings.auto_provider_fallback,
        "fallback_provider": settings.fallback_provider,
        "fallback_model": settings.fallback_model,
        "max_history_turns": settings.max_history_turns,
        "max_context_tokens_groq": settings.max_context_tokens_groq,
        "max_rate_limit_retries": settings.max_rate_limit_retries,
    }


@r.post("/settings")
def update_app_settings(b: SettingsUpdate):
    if b.auto_provider_fallback is not None:
        settings.auto_provider_fallback = b.auto_provider_fallback
    if b.fallback_provider is not None:
        if b.fallback_provider not in ("gemini", "groq", "openrouter"):
            raise HTTPException(400, "Invalid fallback provider. Supported: gemini, groq, openrouter")
        settings.fallback_provider = b.fallback_provider
    if b.fallback_model is not None:
        settings.fallback_model = b.fallback_model.strip()
    audit("settings.updated", f"auto_fallback={settings.auto_provider_fallback}, fallback={settings.fallback_provider}/{settings.fallback_model}")
    return get_app_settings()


@r.post("/providers/key")
def save_key(b: Key):
    field = {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(b.provider)
    if not field or len(b.api_key.strip()) < 12:
        raise HTTPException(400, "Invalid provider or key")

    clean_key = b.api_key.strip("'\" \t\r\n")
    p = BASE / ".env"
    p.touch(exist_ok=True)
    set_key(str(p), field, clean_key)

    if b.provider == "gemini":
        settings.gemini_api_key = clean_key
    elif b.provider == "groq":
        settings.groq_api_key = clean_key
    elif b.provider == "openrouter":
        settings.openrouter_api_key = clean_key

    audit("provider.key_saved", b.provider)
    return {"ok": True, "message": "Saved locally and activated."}


@r.post("/chat")
async def chat(b: Chat):
    if is_emergency_stopped():
        return {
            "conversation_id": b.conversation_id,
            "reply": "⚠️ **Execution Blocked: Global Emergency Stop is currently engaged.**\n\nAll tools, automated browser actions, and task execution loops are paused for system safety. To resume operations, clear the Emergency Stop in the dashboard header or settings.",
            "provider_used": b.provider,
            "model_used": b.model,
            "fallback_occurred": False,
        }

    is_new = b.conversation_id is None
    with conn() as db:
        cid = b.conversation_id
        if cid is None:
            cid = db.execute("INSERT INTO conversations(title) VALUES (?)", (b.message[:50],)).lastrowid
        db.execute("INSERT INTO messages(conversation_id,role,content) VALUES (?,?,?)", (cid, "user", b.message))
        rows = db.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? AND id < (SELECT MAX(id) FROM messages WHERE conversation_id=?) ORDER BY id DESC LIMIT 10",
            (cid, cid),
        ).fetchall()

    history = [dict(x) for x in reversed(rows)]

    # Generate title asynchronously if new conversation
    if is_new:
        async def _set_title(conv_id: int, msg: str, prov: str, mod: str):
            try:
                t = await generate_conversation_title(msg, provider=prov, model=mod)
                with conn() as d:
                    d.execute("UPDATE conversations SET title = ? WHERE id = ?", (t, conv_id))
            except Exception:
                pass
        asyncio.create_task(_set_title(cid, b.message, b.provider, b.model))

    try:
        agent_res = await agent_engine.run(
            provider=b.provider,
            model=b.model,
            user_message=b.message,
            conversation_history=history,
            conversation_id=cid,
        )
        answer = agent_res.reply
        prov_used = agent_res.provider_used
        mod_used = agent_res.model_used
        fb_occ = agent_res.fallback_occurred
        fb_from = agent_res.fallback_from
    except Exception as e:
        err_msg = f"⚠️ **Execution error:** {type(e).__name__}: {str(e)}"
        with conn() as db:
            db.execute("INSERT INTO messages(conversation_id,role,content) VALUES (?,?,?)", (cid, "assistant", err_msg))
        return {
            "conversation_id": cid,
            "reply": err_msg,
            "provider_used": b.provider,
            "model_used": b.model,
            "fallback_occurred": False,
        }

    with conn() as db:
        db.execute("INSERT INTO messages(conversation_id,role,content) VALUES (?,?,?)", (cid, "assistant", answer))

    # Automatic non-blocking conversation summarization check
    asyncio.create_task(maybe_summarize_conversation(cid, provider=prov_used, model=mod_used))

    return {
        "conversation_id": cid,
        "reply": answer,
        "provider_used": prov_used,
        "model_used": mod_used,
        "fallback_occurred": fb_occ,
        "fallback_from": fb_from,
    }


@r.get("/conversations")
def list_conversations(limit: int = 50):
    with conn() as db:
        rows = db.execute(
            """
            SELECT c.id, c.title, c.created_at, COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            GROUP BY c.id
            ORDER BY c.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(x) for x in rows]


@r.get("/conversations/{cid}/messages")
def get_conversation_messages(cid: int):
    with conn() as db:
        rows = db.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id=? ORDER BY id ASC",
            (cid,),
        ).fetchall()
        return [dict(x) for x in rows]


@r.post("/conversations/{cid}/summarize")
async def summarize_conversation_endpoint(cid: int, provider: str = "groq", model: str = ""):
    try:
        summary_mem = await summarize_conversation(cid, provider=provider, model=model)
        return summary_mem
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Summarization failed: {e}")


@r.get("/conversations/{cid}/summary")
def get_conversation_summary_endpoint(cid: int):
    with conn() as db:
        row = db.execute(
            "SELECT * FROM memories WHERE category='conversation_summary' AND conversation_id=? AND status='active' ORDER BY id DESC LIMIT 1",
            (cid,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"No summary found for conversation #{cid}")
        return dict(row)


@r.get("/intelligence/decisions")
def get_decisions_endpoint(q: str | None = None, limit: int = 10):
    return get_historical_decisions(query=q, limit=limit)


@r.get("/intelligence/project_context")
def get_project_context_endpoint(project: str | None = None, limit: int = 3):
    return {"context": get_project_context(project_name=project, limit=limit)}


@r.get("/tools")
def tools():
    return registry.list()


@r.post("/tools/run", dependencies=[Depends(verify_local_origin)])
async def run_tool(b: Run):
    s = next((x for x in registry.list() if x["name"] == b.name), None)
    if not s:
        raise HTTPException(404, "Tool not found")

    # Strict server-side security: Never allow client or LLM to bypass approvals
    if s["risk"] != "read":
        appr = ApprovalLifecycle.create_request(b.name, b.arguments, risk=s["risk"])
        return {
            "status": "approval_required",
            "approval_id": appr["id"],
            "message": f"Action requires user approval. Approval request #{appr['id']} has been created in the Activity Log.",
        }

    try:
        result = await registry.run(b.name, b.arguments)
        audit("tool.executed", b.name)
        return {"status": "completed", "result": result}
    except Exception as e:
        raise HTTPException(400, str(e))


@r.get("/approvals")
def approvals(status_filter: str | None = Query(default=None, alias="status"), limit: int = 50):
    return ApprovalLifecycle.list_approvals(status_filter=status_filter, limit=limit)


@r.get("/approvals/{aid}")
def get_approval(aid: int):
    appr = ApprovalLifecycle.get_approval(aid)
    if not appr:
        raise HTTPException(404, f"Approval #{aid} not found")
    return appr


class DecisionBody(BaseModel):
    expected_args: dict | None = None
    approval_token: str | None = None


@r.post("/approvals/{aid}/decision", dependencies=[Depends(verify_local_origin)])
async def decision(
    aid: int,
    approve: bool,
    body: DecisionBody | None = None,
    approval_token: str | None = Query(default=None),
):
    try:
        token = (body.approval_token if body else None) or approval_token
        if approve:
            expected_args = body.expected_args if body else None
            return await ApprovalLifecycle.approve_and_execute(
                aid=aid,
                expected_args=expected_args,
                decision_by="user:dashboard",
            )
        else:
            return ApprovalLifecycle.reject_approval(
                aid=aid,
                decision_by="user:dashboard",
            )
    except ApprovalError as e:
        raise HTTPException(e.status_code, str(e))
    except Exception as e:
        raise HTTPException(500, f"Approval processing error: {str(e)}")


class ServerCreate(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    enabled: bool = True


class ServerUpdate(BaseModel):
    name: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    enabled: bool | None = None


@r.get("/mcp/servers")
def get_servers():
    return mcp.list_servers()


@r.get("/mcp/servers/{sid}")
def get_server_detail(sid: str):
    srv = mcp.get_server(sid)
    if not srv:
        raise HTTPException(404, f"MCP server '{sid}' not found")
    return srv


@r.post("/mcp/servers")
async def create_server(b: ServerCreate):
    try:
        return await mcp.add_server(
            name=b.name,
            transport=b.transport,
            command=b.command,
            args=b.args,
            env=b.env,
            url=b.url,
            enabled=b.enabled,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@r.put("/mcp/servers/{sid}")
async def update_server_config(sid: str, b: ServerUpdate):
    try:
        return await mcp.edit_server(
            sid=sid,
            name=b.name,
            command=b.command,
            args=b.args,
            env=b.env,
            url=b.url,
            enabled=b.enabled,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/mcp/servers/{sid}/connect")
async def connect_mcp_server(sid: str):
    try:
        return await mcp.connect(sid)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/mcp/servers/{sid}/disconnect")
async def disconnect_mcp_server(sid: str):
    return await mcp.disconnect(sid)


@r.post("/mcp/servers/{sid}/toggle")
async def toggle_mcp_server(sid: str, enabled: bool = Query(...)):
    try:
        return await mcp.set_enabled(sid, enabled)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/mcp/stdio")
async def add_stdio(b: Stdio):
    try:
        return await mcp.add_server(
            name=b.name,
            transport="stdio",
            command=b.command,
            args=b.args,
            env=b.env,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/mcp/http")
async def add_http(b: Http):
    try:
        return await mcp.add_server(
            name=b.name,
            transport="streamable-http",
            url=b.url,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@r.delete("/mcp/servers/{sid}")
async def remove_mcp_server(sid: str):
    return await mcp.remove_server(sid)


@r.get("/audit")
def logs():
    with conn() as db:
        return [dict(x) for x in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]


@r.get("/system")
def system():
    from app.tools.native import overview
    return overview()


# --- Phase 4 Browser Automation Endpoints ---

class NavigateRequest(BaseModel):
    url: str

class TabOpenRequest(BaseModel):
    url: str | None = None

class RuleRequest(BaseModel):
    rule_type: str = Field(..., description="allowlist_domain or blocklist_domain")
    pattern: str = Field(..., description="Domain or pattern, e.g. 'wikipedia.org'")

class SearchRequest(BaseModel):
    query: str
    max_results: int = 5


@r.get("/browser/status")
async def browser_status():
    stat = browser.get_status()
    if stat["is_running"]:
        try:
            stat["active_url"] = await browser.get_url()
            stat["active_title"] = await browser.get_title()
        except Exception:
            stat["active_url"] = "about:blank"
            stat["active_title"] = ""
    return stat


@r.get("/browser/tabs")
async def browser_tabs():
    try:
        return await browser.list_tabs()
    except Exception as e:
        return []


@r.post("/browser/tabs/open")
async def browser_tab_open(b: TabOpenRequest):
    try:
        return await browser.open_tab(url=b.url)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.delete("/browser/tabs/{index}")
async def browser_tab_close(index: int):
    try:
        return await browser.close_tab(index=index)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/browser/tabs/{index}/switch")
async def browser_tab_switch(index: int):
    try:
        return await browser.switch_tab(index=index)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/browser/navigate")
async def browser_navigate(b: NavigateRequest):
    try:
        return await browser.navigate(url=b.url)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/browser/back")
async def browser_back():
    try:
        return await browser.back()
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/browser/forward")
async def browser_forward():
    try:
        return await browser.forward()
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/browser/refresh")
async def browser_refresh():
    try:
        return await browser.refresh()
    except Exception as e:
        raise HTTPException(400, str(e))


@r.get("/browser/screenshot")
async def browser_screenshot(full_page: bool = False):
    try:
        return await browser.screenshot(full_page=full_page)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.get("/browser/downloads")
def browser_downloads():
    with conn() as db:
        rows = db.execute("SELECT * FROM browser_downloads ORDER BY id DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]


@r.post("/browser/clear-data")
async def browser_clear_data():
    return await browser.clear_browsing_data()


@r.get("/browser/rules")
def browser_rules():
    with conn() as db:
        rows = db.execute("SELECT * FROM browser_security_rules ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


@r.post("/browser/rules")
def browser_add_rule(b: RuleRequest):
    rtype = b.rule_type.strip().lower()
    if rtype not in ("allowlist_domain", "blocklist_domain"):
        raise HTTPException(400, "rule_type must be 'allowlist_domain' or 'blocklist_domain'")
    pat = b.pattern.strip().lower()
    if not pat:
        raise HTTPException(400, "pattern cannot be empty")
    
    with conn() as db:
        cur = db.execute(
            "INSERT INTO browser_security_rules (rule_type, pattern) VALUES (?, ?)",
            (rtype, pat),
        )
        new_id = cur.lastrowid
    audit("browser.rule_added", f"{rtype}: {pat}")
    return {"id": new_id, "rule_type": rtype, "pattern": pat}


@r.delete("/browser/rules/{rid}")
def browser_delete_rule(rid: int):
    with conn() as db:
        db.execute("DELETE FROM browser_security_rules WHERE id=?", (rid,))
    audit("browser.rule_deleted", f"ID {rid}")
    return {"id": rid, "deleted": True}


class DownloadRequest(BaseModel):
    url: str
    expected_type: str | None = None
    filename: str | None = None


@r.post("/browser/download")
async def browser_download_endpoint(b: DownloadRequest):
    try:
        return await browser.download_file(url=b.url, expected_type=b.expected_type, filename=b.filename)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/browser/search")
async def browser_web_search(b: SearchRequest):
    try:
        return await search_web(query=b.query, max_results=b.max_results)
    except Exception as e:
        raise HTTPException(400, str(e))


# -------------------------------------------------------------
# MEMORY API ENDPOINTS
# -------------------------------------------------------------
@r.get("/memories")
def get_memories(
    category: str | None = None,
    query: str | None = None,
    status: str = "active",
    limit: int = 50,
):
    if query:
        return memory_engine.search(query_text=query, category=category, status=status, limit=limit)
    return memory_engine.list(category=category, status=status, limit=limit)


@r.post("/memories")
def create_memory_endpoint(b: MemoryCreate):
    try:
        return memory_engine.create(
            category=b.category,
            content=b.content,
            key=b.key,
            source=b.source,
            conversation_id=b.conversation_id,
            confidence=b.confidence,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@r.get("/memories/{mid}")
def get_single_memory(mid: int):
    mem = memory_engine.get(mid)
    if not mem:
        raise HTTPException(404, f"Memory #{mid} not found.")
    return mem


@r.put("/memories/{mid}")
def update_memory_endpoint(mid: int, b: MemoryUpdate):
    try:
        updated = memory_engine.update(
            memory_id=mid,
            content=b.content,
            category=b.category,
            key=b.key,
            status=b.status,
            confidence=b.confidence,
        )
        if not updated:
            raise HTTPException(404, f"Memory #{mid} not found.")
        return updated
    except ValueError as e:
        raise HTTPException(400, str(e))


@r.delete("/memories/{mid}")
def delete_memory_endpoint(mid: int):
    success = memory_engine.delete(mid)
    if not success:
        raise HTTPException(404, f"Memory #{mid} not found.")
    return {"id": mid, "deleted": True}


@r.post("/memories/{mid}/archive")
def archive_memory_endpoint(mid: int):
    success = memory_engine.archive(mid)
    if not success:
        raise HTTPException(404, f"Memory #{mid} not found.")
    return {"id": mid, "status": "archived"}


# -------------------------------------------------------------
# TASK PLANNER & EXECUTOR ENDPOINTS
# -------------------------------------------------------------
@r.get("/tasks")
def list_tasks_endpoint(status: str | None = None, limit: int = 50):
    return task_planner.list_tasks(status=status, limit=limit)


@r.post("/tasks/plan", dependencies=[Depends(verify_local_origin)])
async def create_plan_endpoint(b: TaskPlanCreate):
    try:
        plan = await task_planner.create_plan(
            user_request=b.user_request,
            objective=b.objective,
            conversation_id=b.conversation_id,
        )
        if b.auto_execute and plan.get("status") != "awaiting_approval":
            import asyncio
            asyncio.create_task(task_executor.execute_task(plan["id"]))
        return plan
    except Exception as e:
        raise HTTPException(400, str(e))


@r.get("/tasks/{tid}")
def get_task_endpoint(tid: str):
    t = task_planner.get_task(tid)
    if not t:
        raise HTTPException(404, f"Task '{tid}' not found.")
    return t


@r.put("/tasks/{tid}", dependencies=[Depends(verify_local_origin)])
def update_task_endpoint(tid: str, b: TaskPlanUpdate):
    try:
        updated = task_planner.edit_plan(
            task_id=tid,
            title=b.title,
            objective=b.objective,
            description=b.description,
            steps=b.steps,
        )
        return updated
    except ValueError as e:
        raise HTTPException(400, str(e))


@r.post("/tasks/{tid}/execute", dependencies=[Depends(verify_local_origin)])
async def execute_task_endpoint(tid: str):
    try:
        return await task_executor.execute_task(tid)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/tasks/{tid}/pause", dependencies=[Depends(verify_local_origin)])
def pause_task_endpoint(tid: str):
    try:
        return task_executor.pause_task(tid)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/tasks/{tid}/resume", dependencies=[Depends(verify_local_origin)])
async def resume_task_endpoint(tid: str):
    try:
        return await task_executor.resume_task(tid)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/tasks/{tid}/cancel", dependencies=[Depends(verify_local_origin)])
def cancel_task_endpoint(tid: str):
    try:
        return task_executor.cancel_task(tid)
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/tasks/{tid}/steps/{sid}/retry", dependencies=[Depends(verify_local_origin)])
async def retry_step_endpoint(tid: str, sid: str):
    try:
        return await task_executor.retry_step(task_id=tid, step_id=sid)
    except Exception as e:
        raise HTTPException(400, str(e))


class StepRecoverRequest(BaseModel):
    resolution: str = "resolve"  # resolve, skip, retry
    notes: str = ""


@r.post("/tasks/{tid}/steps/{sid}/recover", dependencies=[Depends(verify_local_origin)])
def recover_step_endpoint(tid: str, sid: str, b: StepRecoverRequest | None = None):
    try:
        resolution = b.resolution if b else "resolve"
        notes = b.notes if b else ""
        return task_executor.manual_recover_step(task_id=tid, step_id=sid, resolution=resolution, notes=notes)
    except Exception as e:
        raise HTTPException(400, str(e))


# -------------------------------------------------------------
# SCHEDULER ENDPOINTS
# -------------------------------------------------------------
class ScheduleCreate(BaseModel):
    task_name: str
    user_request: str
    schedule_type: str = "daily"  # once, daily, weekly, interval
    interval_seconds: int | None = None
    start_delay_seconds: int = 0


@r.get("/schedules")
def list_schedules_endpoint(enabled_only: bool = False):
    return task_scheduler.list_schedules(enabled_only=enabled_only)


@r.post("/schedules", dependencies=[Depends(verify_local_origin)])
def create_schedule_endpoint(b: ScheduleCreate):
    try:
        return task_scheduler.create_schedule(
            task_name=b.task_name,
            user_request=b.user_request,
            schedule_type=b.schedule_type,
            interval_seconds=b.interval_seconds,
            start_delay_seconds=b.start_delay_seconds,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@r.post("/schedules/{sid}/toggle", dependencies=[Depends(verify_local_origin)])
def toggle_schedule_endpoint(sid: str, enabled: bool | None = None):
    res = task_scheduler.toggle_schedule(sid, enabled=enabled)
    if not res:
        raise HTTPException(404, f"Schedule '{sid}' not found.")
    return res


@r.delete("/schedules/{sid}", dependencies=[Depends(verify_local_origin)])
def delete_schedule_endpoint(sid: str):
    success = task_scheduler.delete_schedule(sid)
    if not success:
        raise HTTPException(404, f"Schedule '{sid}' not found.")
    return {"id": sid, "deleted": True}


@r.get("/schedules/{sid}/history")
def get_schedule_history_endpoint(sid: str, limit: int = 20):
    return task_scheduler.get_schedule_history(sid, limit=limit)


# -------------------------------------------------------------
# EMERGENCY STOP ENDPOINTS
# -------------------------------------------------------------
class EmergencyStopRequest(BaseModel):
    reason: str = "User initiated emergency stop from dashboard"


@r.get("/emergency/status")
def get_emergency_stop_status():
    return get_emergency_status()


@r.post("/emergency/stop", dependencies=[Depends(verify_local_origin)])
def trigger_emergency_stop_endpoint(b: EmergencyStopRequest | None = None):
    reason = b.reason if b else "User initiated emergency stop from dashboard"
    return trigger_emergency_stop(reason=reason)


@r.post("/emergency/resume", dependencies=[Depends(verify_local_origin)])
def clear_emergency_stop_endpoint():
    return clear_emergency_stop()


# -------------------------------------------------------------
# PHASE 6, QUEUE 1: WINDOWS DESKTOP CONTROL ENDPOINTS
# -------------------------------------------------------------
from app.desktop import (
    desktop_engine,
    get_active_window,
    list_windows,
    focus_window,
    capture_screenshot,
    list_screenshots,
    get_screenshot_thumbnail,
    inspect_ui,
    mouse_click,
    mouse_scroll,
    keyboard_type,
    keyboard_press,
)
from pathlib import Path


class DesktopFocusRequest(BaseModel):
    hwnd: int | None = None
    title: str | None = None


class DesktopScreenshotRequest(BaseModel):
    target: str = "desktop"
    hwnd: int | None = None


class DesktopInspectRequest(BaseModel):
    hwnd: int | None = None
    max_depth: int = 3
    max_elements: int = 40
    filter_types: list[str] | None = None
    interactive_only: bool = False


class DesktopActionRequest(BaseModel):
    action_type: str  # "click", "scroll", "type", "press"
    params: dict = Field(default_factory=dict)


@r.get("/desktop/status")
def get_desktop_status_endpoint():
    return desktop_engine.get_status()


@r.get("/desktop/windows")
def get_desktop_windows_endpoint(limit: int = 25, only_visible: bool = True):
    return list_windows(limit=limit, only_visible=only_visible)


@r.post("/desktop/windows/focus", dependencies=[Depends(verify_local_origin)])
def focus_desktop_window_endpoint(b: DesktopFocusRequest):
    res = focus_window(hwnd=b.hwnd, title=b.title)
    desktop_engine.record_action("window.focus", b.dict(), res.get("success", False), res.get("error"))
    if not res.get("success"):
        raise HTTPException(400, res.get("error", "Failed to focus window."))
    return res


@r.post("/desktop/screenshot", dependencies=[Depends(verify_local_origin)])
def capture_desktop_screenshot_endpoint(b: DesktopScreenshotRequest | None = None):
    target = b.target if b else "desktop"
    hwnd = b.hwnd if b else None
    res = capture_screenshot(target=target, hwnd=hwnd)
    desktop_engine.record_action("screen.capture", {"target": target, "hwnd": hwnd}, res.get("success", False), res.get("error"))
    if not res.get("success"):
        raise HTTPException(400, res.get("error", "Failed to capture screenshot."))
    return res


@r.get("/desktop/screenshots")
def list_desktop_screenshots_endpoint(limit: int = 20):
    return list_screenshots(limit=limit)


@r.get("/desktop/screenshot/view")
def view_desktop_screenshot_endpoint(path: str):
    """Serve local screenshot securely, validating path is within Downloads/LAPTOP_AI/Screenshots."""
    file_path = Path(path).resolve()
    allowed_dir = (Path.home() / "Downloads" / "LAPTOP_AI" / "Screenshots").resolve()
    if not str(file_path).startswith(str(allowed_dir)):
        raise HTTPException(403, "Access denied: Image path outside authorized Screenshots folder.")
    if not file_path.is_file():
        raise HTTPException(404, "Screenshot file not found.")
    return FileResponse(str(file_path), media_type="image/png")


@r.post("/desktop/inspect", dependencies=[Depends(verify_local_origin)])
def inspect_desktop_ui_endpoint(b: DesktopInspectRequest | None = None):
    req = b or DesktopInspectRequest()
    res = inspect_ui(
        hwnd=req.hwnd,
        max_depth=req.max_depth,
        max_elements=req.max_elements,
        filter_types=req.filter_types,
        interactive_only=req.interactive_only,
    )
    desktop_engine.record_action("ui.inspect", req.dict(), res.get("success", False), res.get("error"))
    return res


@r.post("/desktop/action", dependencies=[Depends(verify_local_origin)])
def execute_desktop_action_endpoint(b: DesktopActionRequest):
    a_type = b.action_type.lower().strip()
    params = b.params
    res = {"success": False, "error": f"Unknown action type: {a_type}"}

    if a_type == "click":
        res = mouse_click(
            element_query=params.get("element_query"),
            control_type=params.get("control_type"),
            x=params.get("x"),
            y=params.get("y"),
            button=params.get("button", "left"),
            clicks=params.get("clicks", 1),
        )
    elif a_type == "scroll":
        res = mouse_scroll(
            clicks=params.get("clicks", 3),
            direction=params.get("direction", "down"),
            x=params.get("x"),
            y=params.get("y"),
        )
    elif a_type == "type":
        text = params.get("text", "")
        press_enter = params.get("press_enter", False)
        res = keyboard_type(text=text, press_enter=press_enter)
    elif a_type == "press":
        key = params.get("key")
        keys = params.get("keys")
        modifiers = params.get("modifiers")
        res = keyboard_press(key=key, keys=keys, modifiers=modifiers)

    desktop_engine.record_action(f"action.{a_type}", params, res.get("success", False), res.get("error"))
    if not res.get("success"):
        raise HTTPException(400, res.get("error", "Action failed."))
    return res


@r.get("/desktop/history")
def get_desktop_history_endpoint(limit: int = 30):
    return desktop_engine.get_action_history(limit=limit)


# =====================================================================
# VISUAL DESKTOP INTELLIGENCE ENDPOINTS (QUEUE 2)
# =====================================================================

class VisionAnalyzeReq(BaseModel):
    target: str = "desktop"
    prompt: Optional[str] = None
    hwnd: Optional[int] = None
    use_multimodal: bool = True


class VisionOcrReq(BaseModel):
    target: str = "desktop"
    hwnd: Optional[int] = None


class VisionFindReq(BaseModel):
    query: str
    target: str = "desktop"
    hwnd: Optional[int] = None


class VisionCompareReq(BaseModel):
    image_path_1: str
    image_path_2: str


class VisionCleanupReq(BaseModel):
    max_age_hours: int = 24
    keep_latest: int = 20


@r.post("/vision/analyze", dependencies=[Depends(verify_local_origin)])
async def vision_analyze_endpoint(req: VisionAnalyzeReq):
    from app.vision import vision_engine
    try:
        res = await vision_engine.analyze_screen(
            target=req.target,
            prompt=req.prompt,
            hwnd=req.hwnd,
            use_multimodal=req.use_multimodal,
        )
        return res.model_dump()
    except Exception as e:
        logger.error("Vision analyze endpoint failed: %s", e)
        raise HTTPException(500, f"Vision analysis failed: {str(e)}")


@r.post("/vision/ocr", dependencies=[Depends(verify_local_origin)])
def vision_ocr_endpoint(req: VisionOcrReq):
    from app.vision import vision_engine
    try:
        res = vision_engine.extract_text(target=req.target, hwnd=req.hwnd)
        return res.model_dump()
    except Exception as e:
        logger.error("Vision OCR endpoint failed: %s", e)
        raise HTTPException(500, f"Vision OCR failed: {str(e)}")


@r.post("/vision/find", dependencies=[Depends(verify_local_origin)])
def vision_find_endpoint(req: VisionFindReq):
    from app.vision import vision_engine
    try:
        res = vision_engine.find_element(query=req.query, target=req.target, hwnd=req.hwnd)
        return res.model_dump()
    except Exception as e:
        logger.error("Vision find endpoint failed: %s", e)
        raise HTTPException(500, f"Visual grounding failed: {str(e)}")


@r.post("/vision/compare", dependencies=[Depends(verify_local_origin)])
def vision_compare_endpoint(req: VisionCompareReq):
    from app.vision import vision_engine
    try:
        res = vision_engine.compare_screens(image_path_1=req.image_path_1, image_path_2=req.image_path_2)
        return res.model_dump()
    except Exception as e:
        logger.error("Vision compare endpoint failed: %s", e)
        raise HTTPException(500, f"Screen comparison failed: {str(e)}")


@r.get("/vision/history")
def vision_history_endpoint(limit: int = 20):
    from app.vision import vision_engine
    return vision_engine.get_history(limit=limit)


@r.post("/vision/history/clear", dependencies=[Depends(verify_local_origin)])
def vision_clear_history_endpoint():
    from app.vision import vision_engine
    vision_engine.clear_history()
    return {"success": True, "message": "Visual analysis history cleared."}


@r.post("/vision/cleanup", dependencies=[Depends(verify_local_origin)])
def vision_cleanup_endpoint(req: VisionCleanupReq):
    from app.vision import cleanup_old_screenshots
    deleted = cleanup_old_screenshots(max_age_hours=req.max_age_hours, keep_latest=req.keep_latest)
    return {"success": True, "deleted_count": deleted}


# -------------------------------------------------------------
# PHASE 6 QUEUE 3: ADVANCED FILE INTELLIGENCE ENDPOINTS
# -------------------------------------------------------------

class FileExtractReq(BaseModel):
    path: str

class FileSummarizeReq(BaseModel):
    path: str
    max_sentences: int = 5

class FileAskReq(BaseModel):
    path: str
    question: str

class FileCompareReq(BaseModel):
    file_a: str
    file_b: str

class FileIndexRefreshReq(BaseModel):
    path: str
    recursive: bool = True
    max_files: int = 100

class FileSpreadsheetAnalyzeReq(BaseModel):
    path: str
    sheet_name: Optional[str] = None

class FileSpreadsheetQueryReq(BaseModel):
    path: str
    filter_col: Optional[str] = None
    filter_val: Optional[str] = None
    sort_by: Optional[str] = None
    descending: bool = False
    sheet_name: Optional[str] = None
    limit: int = 50

class FileDuplicatesReq(BaseModel):
    folder_path: str
    max_files: int = 300

class FileOrgPreviewReq(BaseModel):
    folder_path: str

class FileOrgExecuteReq(BaseModel):
    action_items: List[Dict[str, Any]]
    quarantine_root: Optional[str] = None

class FileOrgRollbackReq(BaseModel):
    rollback_token: str


@r.post("/files/extract", dependencies=[Depends(verify_local_origin)])
def files_extract_endpoint(req: FileExtractReq):
    from app.files.engine import engine
    try:
        doc = engine.extract_document(req.path)
        return doc.model_dump()
    except Exception as e:
        logger.error("File extraction failed: %s", e)
        raise HTTPException(400, f"Document extraction failed: {str(e)}")


@r.post("/files/summarize", dependencies=[Depends(verify_local_origin)])
def files_summarize_endpoint(req: FileSummarizeReq):
    from app.files.engine import engine
    try:
        return engine.summarize_document(req.path, max_sentences=req.max_sentences)
    except Exception as e:
        logger.error("File summarization failed: %s", e)
        raise HTTPException(400, f"Document summarization failed: {str(e)}")


@r.post("/files/ask", dependencies=[Depends(verify_local_origin)])
def files_ask_endpoint(req: FileAskReq):
    from app.files.engine import engine
    try:
        res = engine.ask_document(req.path, req.question)
        return res.model_dump()
    except Exception as e:
        logger.error("File ask failed: %s", e)
        raise HTTPException(400, f"Document Q&A failed: {str(e)}")


@r.post("/files/compare", dependencies=[Depends(verify_local_origin)])
def files_compare_endpoint(req: FileCompareReq):
    from app.files.engine import engine
    try:
        res = engine.compare_documents(req.file_a, req.file_b)
        return res.model_dump()
    except Exception as e:
        logger.error("File comparison failed: %s", e)
        raise HTTPException(400, f"Document comparison failed: {str(e)}")


@r.get("/files/search")
def files_search_endpoint(query: str, limit: int = 10, format_filter: Optional[str] = None):
    from app.files.engine import engine
    try:
        res = engine.search_index(query, limit=limit, format_filter=format_filter)
        return res.model_dump()
    except Exception as e:
        logger.error("File search failed: %s", e)
        raise HTTPException(400, f"Document search failed: {str(e)}")


@r.get("/files/index/status")
def files_index_status_endpoint():
    from app.files.engine import engine
    return engine.get_index_status().model_dump()


@r.post("/files/index/refresh", dependencies=[Depends(verify_local_origin)])
def files_index_refresh_endpoint(req: FileIndexRefreshReq):
    from app.files.engine import engine
    try:
        return engine.refresh_index(req.path, recursive=req.recursive, max_files=req.max_files)
    except Exception as e:
        logger.error("File index refresh failed: %s", e)
        raise HTTPException(400, f"Index refresh failed: {str(e)}")


@r.post("/files/index/clear", dependencies=[Depends(verify_local_origin)])
def files_index_clear_endpoint():
    from app.files.engine import engine
    return engine.clear_index()


@r.post("/files/spreadsheet/analyze", dependencies=[Depends(verify_local_origin)])
def files_spreadsheet_analyze_endpoint(req: FileSpreadsheetAnalyzeReq):
    from app.files.engine import engine
    try:
        return engine.profile_spreadsheet(req.path, sheet_name=req.sheet_name).model_dump()
    except Exception as e:
        logger.error("Spreadsheet analysis failed: %s", e)
        raise HTTPException(400, f"Spreadsheet analysis failed: {str(e)}")


@r.post("/files/spreadsheet/query", dependencies=[Depends(verify_local_origin)])
def files_spreadsheet_query_endpoint(req: FileSpreadsheetQueryReq):
    from app.files.engine import engine
    try:
        return engine.query_spreadsheet(
            req.path,
            filter_col=req.filter_col,
            filter_val=req.filter_val,
            sort_by=req.sort_by,
            descending=req.descending,
            sheet_name=req.sheet_name,
            limit=req.limit,
        )
    except Exception as e:
        logger.error("Spreadsheet query failed: %s", e)
        raise HTTPException(400, f"Spreadsheet query failed: {str(e)}")


@r.post("/files/duplicates", dependencies=[Depends(verify_local_origin)])
def files_duplicates_endpoint(req: FileDuplicatesReq):
    from app.files.engine import engine
    try:
        return engine.find_duplicates(req.folder_path, max_files=req.max_files)
    except Exception as e:
        logger.error("Duplicate search failed: %s", e)
        raise HTTPException(400, f"Duplicate search failed: {str(e)}")


@r.post("/files/organize/preview", dependencies=[Depends(verify_local_origin)])
def files_organize_preview_endpoint(req: FileOrgPreviewReq):
    from app.files.engine import engine
    try:
        return engine.preview_organization(req.folder_path)
    except Exception as e:
        logger.error("File organization preview failed: %s", e)
        raise HTTPException(400, f"Organization preview failed: {str(e)}")


@r.post("/files/organize/execute", dependencies=[Depends(verify_local_origin)])
def files_organize_execute_endpoint(req: FileOrgExecuteReq):
    from app.files.engine import engine
    try:
        return engine.execute_organization(req.action_items, quarantine_root=req.quarantine_root)
    except Exception as e:
        logger.error("File organization execution failed: %s", e)
        raise HTTPException(400, f"Organization execution failed: {str(e)}")


@r.post("/files/organize/rollback", dependencies=[Depends(verify_local_origin)])
def files_organize_rollback_endpoint(req: FileOrgRollbackReq):
    from app.files.engine import engine
    try:
        return engine.rollback_organization(req.rollback_token)
    except Exception as e:
        logger.error("File organization rollback failed: %s", e)
        raise HTTPException(400, f"Organization rollback failed: {str(e)}")


# ---------------------------------------------------------
# Phase 6 Queue 4: Proactive Personal Assistance Endpoints
# ---------------------------------------------------------

class ContextQueryReq(BaseModel):
    query: str


class TaskPrioritizeReq(BaseModel):
    priority: str
    reason: str


class MonitorToggleReq(BaseModel):
    enabled: Optional[bool] = None


@r.get("/assistant/profile")
def assistant_profile_get():
    from app.assistant import assistant_engine
    try:
        return assistant_engine.profile_mgr.get_full_profile().model_dump()
    except Exception as e:
        logger.error("Failed to fetch profile: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/profile")
def assistant_profile_update(req: dict):
    from app.assistant import assistant_engine, ProfileItem
    from app.assistant.schemas import ProfileUpdateReq
    try:
        update_req = ProfileUpdateReq(
            key=req.get("key", ""),
            value=req.get("value"),
            category=req.get("category", "preferences"),
            is_confirmed=req.get("is_confirmed", True),
            confidence=float(req.get("confidence", 1.0)),
            source=req.get("source", "user_explicit"),
        )
        return assistant_engine.profile_mgr.update_profile_item(update_req).model_dump()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Failed to update profile: %s", e)
        raise HTTPException(500, str(e))


@r.get("/assistant/briefing")
def assistant_briefing_get():
    from app.assistant import assistant_engine
    try:
        return assistant_engine.briefing_gen.generate_briefing().model_dump()
    except Exception as e:
        logger.error("Failed to generate briefing: %s", e)
        raise HTTPException(500, str(e))


@r.get("/assistant/briefing/markdown")
def assistant_briefing_markdown():
    from app.assistant import assistant_engine
    try:
        return {"markdown": assistant_engine.briefing_gen.to_markdown()}
    except Exception as e:
        logger.error("Failed to generate markdown briefing: %s", e)
        raise HTTPException(500, str(e))


@r.get("/assistant/reminders")
def assistant_reminders_list(status: Optional[str] = None, limit: int = 50):
    from app.assistant import assistant_engine
    try:
        return [r.model_dump() for r in assistant_engine.reminder_mgr.list_reminders(status=status, limit=limit)]
    except Exception as e:
        logger.error("Failed to list reminders: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/reminders")
def assistant_reminders_create(req: dict):
    from app.assistant import assistant_engine
    from app.assistant.schemas import ReminderCreate
    try:
        create_req = ReminderCreate(**req)
        return assistant_engine.reminder_mgr.create_reminder(create_req).model_dump()
    except Exception as e:
        logger.error("Failed to create reminder: %s", e)
        raise HTTPException(400, str(e))


@r.post("/assistant/reminders/{reminder_id}/snooze")
def assistant_reminders_snooze(reminder_id: str, req: dict = None):
    from app.assistant import assistant_engine
    try:
        req = req or {}
        snooze_minutes = int(req.get("snooze_minutes", 15))
        snooze_until = req.get("snooze_until")
        item = assistant_engine.reminder_mgr.snooze_reminder(reminder_id, snooze_minutes=snooze_minutes, snooze_until=snooze_until)
        if not item:
            raise HTTPException(404, "Reminder not found")
        return item.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to snooze reminder: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/reminders/{reminder_id}/dismiss")
def assistant_reminders_dismiss(reminder_id: str):
    from app.assistant import assistant_engine
    try:
        success = assistant_engine.reminder_mgr.dismiss_reminder(reminder_id)
        if not success:
            raise HTTPException(404, "Reminder not found")
        return {"status": "dismissed", "reminder_id": reminder_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to dismiss reminder: %s", e)
        raise HTTPException(500, str(e))


@r.get("/assistant/monitors")
def assistant_monitors_list(enabled_only: bool = False):
    from app.assistant import assistant_engine
    try:
        return [m.model_dump() for m in assistant_engine.monitor_mgr.list_monitors(enabled_only=enabled_only)]
    except Exception as e:
        logger.error("Failed to list monitors: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/monitors")
def assistant_monitors_create(req: dict):
    from app.assistant import assistant_engine
    from app.assistant.schemas import MonitorCreate
    try:
        create_req = MonitorCreate(**req)
        return assistant_engine.monitor_mgr.create_monitor(create_req).model_dump()
    except Exception as e:
        logger.error("Failed to create monitor: %s", e)
        raise HTTPException(400, str(e))


@r.post("/assistant/monitors/{monitor_id}/toggle")
def assistant_monitors_toggle(monitor_id: str, req: MonitorToggleReq = None):
    from app.assistant import assistant_engine
    try:
        enabled = req.enabled if req else None
        item = assistant_engine.monitor_mgr.toggle_monitor(monitor_id, enabled=enabled)
        if not item:
            raise HTTPException(404, "Monitor not found")
        return item.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to toggle monitor: %s", e)
        raise HTTPException(500, str(e))


@r.delete("/assistant/monitors/{monitor_id}")
def assistant_monitors_delete(monitor_id: str):
    from app.assistant import assistant_engine
    try:
        deleted = assistant_engine.monitor_mgr.delete_monitor(monitor_id)
        if not deleted:
            raise HTTPException(404, "Monitor not found")
        return {"status": "deleted", "monitor_id": monitor_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete monitor: %s", e)
        raise HTTPException(500, str(e))


@r.get("/assistant/notifications")
def assistant_notifications_list(unread_only: bool = False, limit: int = 50):
    from app.assistant import assistant_engine
    try:
        return [n.model_dump() for n in assistant_engine.notification_mgr.list_notifications(unread_only=unread_only, limit=limit)]
    except Exception as e:
        logger.error("Failed to list notifications: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/notifications/{notification_id}/read")
def assistant_notifications_mark_read(notification_id: str):
    from app.assistant import assistant_engine
    try:
        success = assistant_engine.notification_mgr.mark_read(notification_id)
        if not success:
            raise HTTPException(404, "Notification not found")
        return {"status": "read", "notification_id": notification_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to mark notification read: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/notifications/{notification_id}/dismiss")
def assistant_notifications_dismiss(notification_id: str):
    from app.assistant import assistant_engine
    try:
        success = assistant_engine.notification_mgr.dismiss_notification(notification_id)
        if not success:
            raise HTTPException(404, "Notification not found")
        return {"status": "dismissed", "notification_id": notification_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to dismiss notification: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/tasks/natural")
def assistant_tasks_create_natural(req: dict):
    from app.assistant import assistant_engine
    from app.assistant.schemas import TaskNaturalCreate
    try:
        create_req = TaskNaturalCreate(**req)
        return assistant_engine.task_intel.create_natural_task(create_req)
    except Exception as e:
        logger.error("Failed to create natural task: %s", e)
        raise HTTPException(400, str(e))


@r.post("/assistant/tasks/{task_id}/prioritize")
def assistant_tasks_prioritize(task_id: str, req: TaskPrioritizeReq):
    from app.assistant import assistant_engine
    try:
        result = assistant_engine.task_intel.prioritize_task(task_id, req.priority, req.reason)
        if not result:
            raise HTTPException(404, "Task not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to prioritize task: %s", e)
        raise HTTPException(500, str(e))


@r.get("/assistant/plan/daily")
def assistant_plan_daily():
    from app.assistant import assistant_engine
    try:
        return assistant_engine.task_intel.generate_daily_plan()
    except Exception as e:
        logger.error("Failed to generate daily plan: %s", e)
        raise HTTPException(500, str(e))


@r.get("/assistant/plan/weekly")
def assistant_plan_weekly():
    from app.assistant import assistant_engine
    try:
        return assistant_engine.task_intel.generate_weekly_plan()
    except Exception as e:
        logger.error("Failed to generate weekly plan: %s", e)
        raise HTTPException(500, str(e))


@r.post("/assistant/context-query")
def assistant_context_query(req: ContextQueryReq):
    from app.assistant import assistant_engine
    try:
        return assistant_engine.answer_context_query(req.query)
    except Exception as e:
        logger.error("Failed to answer context query: %s", e)
        raise HTTPException(500, str(e))





