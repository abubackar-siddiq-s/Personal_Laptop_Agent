from __future__ import annotations
import base64
import datetime
import json
import os
import platform
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import psutil
from PIL import ImageGrab
from app.tools.registry import registry, Spec
from app.core.security import allowed, audit, resolve_user_path, ROOTS, FOLDER_ALIASES


def format_size(size_bytes: int) -> str:
    """Format byte sizes into human-readable strings."""
    val = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if val < 1024.0:
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} TB"


# =====================================================================
# 1. SYSTEM & HARDWARE TELEMETRY
# =====================================================================

def overview() -> dict:
    return {
        "platform": platform.platform(),
        "cpu_percent": psutil.cpu_percent(0.2),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_total_gb": round(psutil.virtual_memory().total / 1024**3, 1),
        "disk_percent": psutil.disk_usage(Path.home().anchor).percent,
    }


def battery() -> dict:
    b = psutil.sensors_battery()
    if not b:
        return {"has_battery": False, "message": "No battery detected or running on desktop AC power."}
    return {
        "has_battery": True,
        "percent": b.percent,
        "power_plugged": b.power_plugged,
        "seconds_left": b.secsleft if b.secsleft != psutil.POWER_TIME_UNLIMITED else None,
    }


def network() -> dict:
    interfaces = {}
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    for iface, addr_list in addrs.items():
        if iface.startswith("Loopback"):
            continue
        stat = stats.get(iface)
        is_up = stat.isup if stat else False
        ipv4_list = [a.address for a in addr_list if a.family.name == "AF_INET"]
        if ipv4_list:
            interfaces[iface] = {
                "is_up": is_up,
                "speed_mbps": stat.speed if stat else 0,
                "ipv4": ipv4_list,
            }
    return {"interfaces": interfaces, "count": len(interfaces)}


def disks() -> dict:
    parts = []
    for p in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(p.mountpoint)
            parts.append({
                "device": p.device,
                "mountpoint": p.mountpoint,
                "fstype": p.fstype,
                "total_gb": round(usage.total / 1024**3, 1),
                "used_gb": round(usage.used / 1024**3, 1),
                "free_gb": round(usage.free / 1024**3, 1),
                "percent_used": usage.percent,
            })
        except (PermissionError, OSError):
            continue
    return {"partitions": parts, "count": len(parts)}


# =====================================================================
# 2. PROCESS MANAGEMENT & SECURITY CONTROLS
# =====================================================================

CRITICAL_PROCESS_NAMES = {
    "system", "system idle process", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "svchost.exe", "winlogon.exe", "explorer.exe",
    "dwm.exe", "fontdrvhost.exe", "runtimebroker.exe"
}
CRITICAL_PIDS = {0, 4}


def processes(limit: int = 15) -> list[dict]:
    out = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            out.append({
                "pid": p.info["pid"],
                "name": p.info["name"],
                "memory_mb": round(p.info["memory_info"].rss / 1048576, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(out, key=lambda x: x["memory_mb"], reverse=True)[: max(1, min(limit, 50))]


def inspect_process(pid: int) -> dict:
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            mem = p.memory_info()
            return {
                "pid": p.pid,
                "name": p.name(),
                "status": p.status(),
                "cpu_percent": p.cpu_percent(0.1),
                "memory_mb": round(mem.rss / 1048576, 1),
                "num_threads": p.num_threads(),
                "create_time": datetime.datetime.fromtimestamp(p.create_time()).isoformat(),
                "username": p.username() if hasattr(p, "username") else None,
            }
    except psutil.NoSuchProcess:
        raise ValueError(f"Process with PID {pid} does not exist.")
    except psutil.AccessDenied:
        raise PermissionError(f"Access denied to inspect process PID {pid}.")


def terminate_process(pid: int, force: bool = False) -> dict:
    if pid in CRITICAL_PIDS:
        raise PermissionError(f"Security Violation: Refusing to terminate critical system process PID {pid}.")
    try:
        p = psutil.Process(pid)
        name = p.name().lower()
        if name in CRITICAL_PROCESS_NAMES:
            raise PermissionError(f"Security Violation: Refusing to terminate critical system process '{name}'.")

        audit("process.terminate_requested", f"PID {pid} ({name}) force={force}")
        if force:
            p.kill()
        else:
            p.terminate()
        return {"terminated": True, "pid": pid, "name": name, "force": force}
    except psutil.NoSuchProcess:
        raise ValueError(f"Process with PID {pid} is no longer running.")
    except psutil.AccessDenied:
        raise PermissionError(f"Access denied: Insufficient privileges to terminate PID {pid}.")


# =====================================================================
# 3. FILE AND FOLDER OPERATIONS (AUTOMATIC ALIAS RESOLUTION & PARSING)
# =====================================================================

def search_files(
    query: str,
    folder: str | None = None,
    extension: str | None = None,
    limit: int = 50,
) -> dict:
    """
    Search filenames recursively in approved user folders with automatic directory resolution.
    Returns filenames, full paths, byte sizes, human-readable sizes, and modification timestamps.
    """
    clean_query = query.strip()
    clean_ext = (extension.strip().lower() if extension else "").lstrip(".")

    # Determine target directories
    if not folder or str(folder).strip().lower() in ("", "all", ".", "user", "home"):
        search_dirs = ROOTS
        display_folder = "All user folders (Downloads, Documents, Desktop)"
    else:
        target = resolve_user_path(folder)
        if not allowed(target):
            raise PermissionError("Path violation: Search limited to approved user folders (Documents, Desktop, Downloads).")
        if not target.exists() or not target.is_dir():
            raise ValueError(f"Directory '{folder}' does not exist.")
        search_dirs = [target]
        display_folder = str(target)

    matches = []
    for root in search_dirs:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if len(matches) >= max(1, min(limit, 200)):
                    break
                if not p.is_file():
                    continue
                # Check extension filter
                if clean_ext and p.suffix.lower().lstrip(".") != clean_ext:
                    continue
                # Check filename query match
                if not clean_query or clean_query.casefold() in p.name.casefold():
                    try:
                        st = p.stat()
                        matches.append({
                            "filename": p.name,
                            "path": str(p),
                            "size_bytes": st.st_size,
                            "size_formatted": format_size(st.st_size),
                            "modified_at": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
                            "extension": p.suffix.lower(),
                        })
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            continue

    return {
        "query": clean_query,
        "folder": display_folder,
        "extension_filter": f".{clean_ext}" if clean_ext else None,
        "matches": matches,
        "count": len(matches),
    }


def list_directory(folder: str | None = None, limit: int = 50) -> dict:
    """List files and folders in an approved directory with automatic alias resolution."""
    target = resolve_user_path(folder)
    if not allowed(target):
        raise PermissionError("Path violation: Directory listing restricted to Documents, Desktop, Downloads.")
    if not target.exists() or not target.is_dir():
        raise ValueError(f"Directory '{target}' does not exist.")

    items = []
    try:
        entries = sorted(list(target.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
    except (PermissionError, OSError) as e:
        raise PermissionError(f"Cannot read directory '{target}': {e}")

    for entry in entries[: max(1, min(limit, 200))]:
        try:
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size_bytes": stat.st_size if entry.is_file() else None,
                "size_formatted": format_size(stat.st_size) if entry.is_file() else None,
                "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except (PermissionError, OSError):
            continue
    return {"folder": str(target), "items": items, "count": len(items)}


def read_file(path: str, max_bytes: int = 65536) -> dict:
    """
    Read file content from approved user folders.
    Supports text files, PDF (.pdf via pypdf), and Word documents (.docx via XML extraction).
    Detects and rejects unsupported binary files.
    """
    target = resolve_user_path(path)
    if not allowed(target):
        raise PermissionError(f"Path violation: Reading files restricted to Documents, Desktop, Downloads (attempted: '{path}').")
    if not target.exists() or not target.is_file():
        raise ValueError(f"File '{path}' does not exist or is not a regular file.")

    ext = target.suffix.lower()
    size = target.stat().st_size
    mtime = datetime.datetime.fromtimestamp(target.stat().st_mtime).isoformat()

    # 1. PDF Parser
    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(target))
            pages = []
            for i, p in enumerate(reader.pages[:30]):
                txt = p.extract_text() or ""
                if txt.strip():
                    pages.append(f"--- Page {i+1} ---\n{txt.strip()}")
            content = "\n\n".join(pages)
            if len(content) > max_bytes:
                content = content[:max_bytes] + f"\n\n[Content truncated at {max_bytes} bytes]"
            return {
                "path": str(target),
                "filename": target.name,
                "format": "pdf",
                "page_count": len(reader.pages),
                "size_bytes": size,
                "size_formatted": format_size(size),
                "modified_at": mtime,
                "content": content,
            }
        except Exception as e:
            raise RuntimeError(f"Failed to extract text from PDF '{target.name}': {str(e)}")

    # 2. DOCX Parser
    if ext == ".docx":
        try:
            with zipfile.ZipFile(target) as z:
                xml_content = z.read("word/document.xml")
            root = ET.fromstring(xml_content)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for p in root.iter(f"{{{ns['w']}}}p"):
                texts = [node.text for node in p.iter(f"{{{ns['w']}}}t") if node.text]
                if texts:
                    paragraphs.append("".join(texts))
            content = "\n\n".join(paragraphs)
            if len(content) > max_bytes:
                content = content[:max_bytes] + f"\n\n[Content truncated at {max_bytes} bytes]"
            return {
                "path": str(target),
                "filename": target.name,
                "format": "docx",
                "size_bytes": size,
                "size_formatted": format_size(size),
                "modified_at": mtime,
                "content": content,
            }
        except Exception as e:
            raise RuntimeError(f"Failed to extract text from DOCX '{target.name}': {str(e)}")

    # 3. Binary Detection Check
    text_exts = {
        ".txt", ".md", ".json", ".csv", ".log", ".py", ".js", ".ts",
        ".html", ".css", ".xml", ".yaml", ".yml", ".ini", ".env",
        ".toml", ".bat", ".ps1", ".sh", ".c", ".cpp", ".h", ".sql"
    }
    if ext not in text_exts:
        with open(target, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                raise ValueError(
                    f"Unsupported binary file '{target.name}' ({ext or 'unknown'}). "
                    f"LAPTOP AI can read text files, PDF (.pdf), and Word documents (.docx)."
                )

    # 4. Standard Text File
    read_len = min(size, max_bytes)
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(read_len)

    return {
        "path": str(target),
        "filename": target.name,
        "format": "text",
        "size_bytes": size,
        "size_formatted": format_size(size),
        "modified_at": mtime,
        "truncated": size > max_bytes,
        "content": content,
    }


def write_file(path: str, content: str, mode: str = "write") -> dict:
    """Create or update a file in approved user folders with explicit approval."""
    target = resolve_user_path(path)
    if not allowed(target):
        raise PermissionError(f"Path violation: Writing files restricted to Documents, Desktop, Downloads (attempted: '{path}').")

    target.parent.mkdir(parents=True, exist_ok=True)
    file_mode = "a" if mode == "append" else "w"
    with open(target, file_mode, encoding="utf-8") as f:
        f.write(content)

    audit("file.written", f"{target} ({mode}, {len(content)} chars)")
    return {
        "path": str(target),
        "filename": target.name,
        "bytes_written": len(content.encode("utf-8")),
        "mode": mode,
        "status": "success",
    }


# =====================================================================
# 4. APPLICATION LAUNCHING (STRICT ALLOWLIST)
# =====================================================================

APPROVED_APPS = {
    "notepad": ["notepad.exe"],
    "calc": ["calc.exe"],
    "calculator": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "mspaint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "edge": ["msedge.exe"],
    "code": ["code.cmd"],
    "vscode": ["code.cmd"],
}


def launch_app(app_name: str, arguments: list[str] | None = None) -> dict:
    app_key = app_name.strip().lower()
    if app_key not in APPROVED_APPS:
        raise PermissionError(
            f"Security violation: Application '{app_name}' is not in the approved application allowlist. "
            f"Approved apps: {list(APPROVED_APPS.keys())}"
        )
    cmd = list(APPROVED_APPS[app_key])
    if arguments:
        cmd.extend([str(a) for a in arguments])

    proc = subprocess.Popen(cmd, shell=False)
    audit("app.launched", f"{app_name} (PID: {proc.pid})")
    return {
        "launched": True,
        "app_name": app_name,
        "pid": proc.pid,
    }


# =====================================================================
# 5. DIAGNOSTICS, SCREEN CAPTURE & MULTIMODAL VISION
# =====================================================================

SAFE = {
    "whoami": ["whoami"],
    "ipconfig": ["ipconfig"],
    "python-version": ["py", "--version"],
    "git-version": ["git", "--version"],
    "node-version": ["node", "--version"],
}


def diagnostic(command_id: str) -> dict:
    if command_id not in SAFE:
        raise PermissionError("Command not allowlisted")
    r = subprocess.run(SAFE[command_id], capture_output=True, text=True, timeout=10, shell=False)
    audit("terminal.command", command_id)
    return {"returncode": r.returncode, "stdout": r.stdout[-6000:], "stderr": r.stderr[-2000:]}


def capture_screenshot() -> dict:
    """Capture a screenshot of the primary Windows display and save to Downloads/Screenshots."""
    downloads_dir = Path.home() / "Downloads" / "Screenshots"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = downloads_dir / f"screenshot_{timestamp}.png"

    try:
        shot = ImageGrab.grab()
        shot.save(str(out_path))
        audit("screen.captured", str(out_path))
        return {
            "success": True,
            "path": str(out_path),
            "filename": out_path.name,
            "width": shot.size[0],
            "height": shot.size[1],
            "file_size_bytes": out_path.stat().st_size,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Screen grab unavailable: {type(e).__name__}: {str(e)}.",
        }


async def analyze_screen(
    prompt: str = "Describe what is currently visible on the screen",
    image_path: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """
    Capture or inspect a screen image using the active cloud model's multimodal vision capabilities.
    Validates model capability and avoids false claims if the model is text-only.
    """
    from app.providers.router import is_vision_capable, chat_turn
    from app.core.config import settings

    # Determine provider and model
    active_prov = (provider or ("gemini" if settings.gemini_api_key else ("groq" if settings.groq_api_key else "openrouter"))).lower().strip()
    active_mod = model or ("gemini-2.5-flash" if active_prov == "gemini" else ("openai/gpt-oss-20b" if active_prov == "groq" else "openrouter/auto"))

    # Check model vision capability first to prevent false claims
    can_see = is_vision_capable(active_prov, active_mod)
    if not can_see:
        return {
            "success": False,
            "visual_understanding": False,
            "image_path": str(image_path) if image_path else None,
            "provider": active_prov,
            "model": active_mod,
            "message": (
                f"Selected model '{active_mod}' on '{active_prov}' is text-only and lacks vision capabilities. "
                f"Please switch to a multimodal model (e.g. Google Gemini 2.5 Flash) to enable visual understanding."
            ),
        }

    # Determine or capture image path
    if not image_path:
        cap = capture_screenshot()
        if not cap.get("success"):
            return {
                "success": False,
                "visual_understanding": can_see,
                "error": f"Screen grab unavailable: {cap.get('error')}",
                "provider": active_prov,
                "model": active_mod,
            }
        img_file = Path(cap["path"])
    else:
        img_file = resolve_user_path(image_path)
        if not allowed(img_file) or not img_file.exists():
            raise FileNotFoundError(f"Image '{image_path}' not found in approved user folders.")

    with open(img_file, "rb") as f:
        img_bytes = f.read()
    b64_str = base64.b64encode(img_bytes).decode("utf-8")

    # Call multimodal API
    messages = [
        {
            "role": "user",
            "content": prompt,
            "image_base64": b64_str,
            "image_mime": "image/png",
        }
    ]
    try:
        turn = await chat_turn(provider=active_prov, model=active_mod, messages=messages)
        return {
            "success": True,
            "visual_understanding": True,
            "image_path": str(img_file),
            "provider": active_prov,
            "model": active_mod,
            "analysis": turn.content,
        }
    except Exception as e:
        return {
            "success": False,
            "visual_understanding": can_see,
            "error": f"Multimodal analysis failed: {str(e)}",
            "image_path": str(img_file),
            "provider": active_prov,
            "model": active_mod,
        }


def check_approval(approval_id: int) -> dict:
    from app.core.approval import ApprovalLifecycle
    appr = ApprovalLifecycle.get_approval(approval_id)
    if not appr:
        return {"found": False, "message": f"Approval request #{approval_id} does not exist."}
    res = {
        "found": True,
        "id": appr["id"],
        "tool_name": appr["tool_name"],
        "status": appr["status"],
        "created_at": appr["created_at"],
        "decision_by": appr.get("decision_by"),
        "executed_at": appr.get("executed_at"),
    }
    if appr.get("result"):
        try:
            res["result"] = json.loads(appr["result"])
        except Exception:
            res["result"] = appr["result"]
    if appr.get("error"):
        res["error"] = appr["error"]
    return res


# =====================================================================
# 6. MCP SERVER DISCOVERY (BUG 2)
# =====================================================================

def mcp_list_servers() -> list[dict]:
    """
    List all configured and connected MCP servers with connection status and available tools.
    Never exposes credentials, environment secrets, or authentication tokens.
    """
    from app.tools.mcp_manager import mcp
    raw = mcp.list_servers()
    sanitized = []
    for s in raw:
        sanitized.append({
            "id": s["id"],
            "name": s["name"],
            "transport": s["transport"],
            "status": s["status"],
            "is_live": s.get("is_live", False),
            "tool_count": s.get("tool_count", 0),
            "available_tools": [
                {"name": t["name"], "description": t["description"]}
                for t in s.get("tools", [])
            ],
            "last_connected_at": s.get("last_connected_at"),
            "error": s.get("error"),
        })
    return sanitized


# =====================================================================
# UNIFIED REGISTRATION
# =====================================================================

def register():
    # 1. System Telemetry (Read)
    registry.add(Spec(
        "native.system.overview",
        "Read CPU, RAM, disk and OS telemetry",
        "native",
        "read",
        {"type": "object", "properties": {}},
        overview,
    ))
    registry.add(Spec(
        "native.system.battery",
        "Check laptop battery percentage and AC power status",
        "native",
        "read",
        {"type": "object", "properties": {}},
        battery,
    ))
    registry.add(Spec(
        "native.system.network",
        "Inspect active network interfaces, IPv4 addresses, and link status",
        "native",
        "read",
        {"type": "object", "properties": {}},
        network,
    ))
    registry.add(Spec(
        "native.system.disks",
        "List storage volumes, partitions, mount points, and free space",
        "native",
        "read",
        {"type": "object", "properties": {}},
        disks,
    ))

    # 2. Process Management
    registry.add(Spec(
        "native.system.processes",
        "List top running processes by memory usage",
        "native",
        "read",
        {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}}},
        processes,
    ))
    registry.add(Spec(
        "native.process.inspect",
        "Inspect detailed telemetry for a specific process PID",
        "native",
        "read",
        {"type": "object", "required": ["pid"], "properties": {"pid": {"type": "integer", "description": "Process ID"}}},
        inspect_process,
    ))
    registry.add(Spec(
        "native.process.terminate",
        "Terminate or kill a process by PID (Protected: critical system processes cannot be killed)",
        "native",
        "approval",
        {
            "type": "object",
            "required": ["pid"],
            "properties": {
                "pid": {"type": "integer", "description": "Process ID to terminate"},
                "force": {"type": "boolean", "default": False, "description": "Force kill immediately"},
            },
        },
        terminate_process,
    ))

    # 3. File Operations (BUG 1 & BUG 5)
    registry.add(Spec(
        "native.files.search",
        "Search filenames recursively in approved user folders (Downloads, Documents, Desktop) with automatic folder resolution and optional extension filtering",
        "native",
        "read",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filename keyword or query to search for"},
                "folder": {"type": "string", "description": "Optional folder or alias ('Downloads', 'Documents', 'Desktop', or 'all'). Automatically defaults to user folders."},
                "extension": {"type": "string", "description": "Optional file extension to filter by (e.g. '.pdf', '.docx', '.txt')"},
                "limit": {"type": "integer", "description": "Maximum number of search matches to return (default: 50)"},
            },
            "required": ["query"],
        },
        search_files,
    ))
    registry.add(Spec(
        "native.files.list_dir",
        "List files and subfolders in an approved user folder with automatic folder alias resolution (Downloads, Documents, Desktop)",
        "native",
        "read",
        {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder path or alias ('Downloads', 'Documents', 'Desktop'). Defaults to Downloads."},
                "limit": {"type": "integer", "description": "Maximum number of directory items to list (default: 50)"},
            },
        },
        list_directory,
    ))
    registry.add(Spec(
        "native.files.read",
        "Read file content from approved user folders. Supports text, PDF documents (.pdf), and Word documents (.docx). Rejects unsupported binaries.",
        "native",
        "read",
        {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "File path or alias (e.g. 'Downloads/report.pdf')"},
                "max_bytes": {"type": "integer", "description": "Maximum bytes/characters to read (default: 65536)"},
            },
        },
        read_file,
    ))
    registry.add(Spec(
        "native.files.write",
        "Create or update a file in approved user folders (approval required)",
        "native",
        "approval",
        {
            "type": "object",
            "required": ["path", "content"],
            "properties": {
                "path": {"type": "string", "description": "Destination file path or alias (e.g. 'Downloads/summary.txt')"},
                "content": {"type": "string", "description": "Content to write"},
                "mode": {"type": "string", "enum": ["write", "append"], "default": "write"},
            },
        },
        write_file,
    ))

    # 4. App Launching & Terminal Diagnostics
    registry.add(Spec(
        "native.app.launch",
        "Launch an approved Windows desktop application (e.g. notepad, calc, paint, code)",
        "native",
        "approval",
        {
            "type": "object",
            "required": ["app_name"],
            "properties": {
                "app_name": {"type": "string", "enum": list(APPROVED_APPS.keys()), "description": "Approved application name"},
                "arguments": {"type": "array", "items": {"type": "string"}, "description": "Optional command-line arguments"},
            },
        },
        launch_app,
    ))
    registry.add(Spec(
        "native.terminal.diagnostic",
        "Run a predefined diagnostic command",
        "native",
        "approval",
        {"type": "object", "required": ["command_id"], "properties": {"command_id": {"type": "string", "enum": list(SAFE)}}},
        diagnostic,
    ))

    # 5. Screen Capture, Multimodal Vision & Approvals Check (BUG 3)
    registry.add(Spec(
        "native.screen.capture",
        "Capture a screenshot of the primary Windows display and save to Downloads/Screenshots",
        "native",
        "read",
        {"type": "object", "properties": {}},
        capture_screenshot,
    ))
    registry.add(Spec(
        "native.screen.analyze",
        "Analyze the active Windows screen using multimodal vision capabilities (with model capability detection)",
        "native",
        "read",
        {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Inspection instructions or question about what is on screen"},
                "image_path": {"type": "string", "description": "Optional path to an existing screenshot in approved folders"},
            },
        },
        analyze_screen,
    ))
    registry.add(Spec(
        "native.approvals.check",
        "Check the real-time status and execution result of an approval request",
        "native",
        "read",
        {"type": "object", "required": ["approval_id"], "properties": {"approval_id": {"type": "integer", "description": "The approval ID to inspect"}}},
        check_approval,
    ))

    # 6. MCP Discovery (BUG 2)
    registry.add(Spec(
        "native.mcp.list_servers",
        "List all configured and connected MCP servers with connection status and available tools (credentials are never exposed)",
        "native",
        "read",
        {"type": "object", "properties": {}},
        mcp_list_servers,
    ))
