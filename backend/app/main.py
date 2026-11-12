from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.db import init_db
from app.core.security import get_or_create_bootstrap_secret
from app.core.approval import ApprovalLifecycle
from app.planner import task_executor, task_scheduler
from app.tools.native import register
from app.tools.mcp_manager import mcp
from app.browser import browser, register_browser_tools
from app.desktop import register_desktop_tools
from app.vision import register_vision_tools
from app.files import register_file_tools
from app.assistant import register_assistant_tools, assistant_engine
from app.api.routes import r

app = FastAPI(title="LAPTOP AI API", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(r, prefix="/api")


@app.on_event("startup")
async def start():
    init_db()
    get_or_create_bootstrap_secret()
    ApprovalLifecycle.recover_interrupted_executions()
    task_executor.recover_interrupted_tasks()
    task_scheduler.recover_interrupted_schedules()
    register()
    register_browser_tools()
    register_desktop_tools()
    register_vision_tools()
    register_file_tools()
    register_assistant_tools()
    assistant_engine.recover_on_startup()
    await mcp.load_all_enabled()
    task_scheduler.start()


@app.on_event("shutdown")
async def stop():
    task_scheduler.stop()
    await browser.close()
