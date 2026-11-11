from __future__ import annotations
import asyncio
import datetime
import httpx
import ipaddress
import json
import logging
import os
import socket
import urllib.parse
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from app.core.db import conn
from app.core.security import audit
from app.tools.registry import registry, Spec

logger = logging.getLogger("laptop_ai.mcp")

# Security Allowlist for stdio executables
APPROVED_STDIO_EXECUTABLES = {
    "python", "python.exe", "py", "py.exe",
    "node", "node.exe", "npx", "npx.cmd",
    "uvx", "uvx.exe", "uv", "uv.exe",
    "deno", "deno.exe", "git", "git.exe",
}

MAX_TOOL_OUTPUT_CHARS = 64_000
DEFAULT_TIMEOUT_SECONDS = 30.0


def validate_stdio_command(command: str):
    """Validate that the stdio executable is in the approved allowlist."""
    cmd = command.strip()
    if not cmd:
        raise ValueError("Command cannot be empty.")
    
    # Extract base executable name
    cmd_name = Path(cmd).name.lower()
    
    # Check if executable name is in approved set
    if cmd_name not in APPROVED_STDIO_EXECUTABLES:
        # Also check without extension (e.g. 'npx' on Windows)
        stem = Path(cmd).stem.lower()
        if stem not in APPROVED_STDIO_EXECUTABLES:
            raise PermissionError(
                f"Security Violation: Command '{cmd}' ({cmd_name}) is not in the approved MCP executable allowlist. "
                f"Permitted: {sorted(list(APPROVED_STDIO_EXECUTABLES))}"
            )


def validate_http_url(url: str):
    """Validate Streamable HTTP endpoint for SSRF protection."""
    u = url.strip()
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use HTTP or HTTPS.")
    
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Invalid URL: Missing hostname.")
    
    # SSRF Protection: Block cloud metadata service IP
    if host in ("169.254.169.254", "metadata.google.internal", "metadata"):
        raise PermissionError(f"Security Violation: Access to metadata service '{host}' is forbidden.")
    
    # Non-localhost must use HTTPS
    if parsed.scheme == "http" and host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"Insecure HTTP endpoint '{host}' rejected. External endpoints must use HTTPS.")

    # DNS rebinding SSRF protection for remote endpoints
    is_test_env = os.environ.get("LAPTOP_AI_TEST_MODE") == "1"
    if host not in ("127.0.0.1", "localhost", "::1") and not is_test_env:
        try:
            resolved_ips = socket.getaddrinfo(host, None)
            for _, _, _, _, sockaddr in resolved_ips:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_loopback:
                    raise PermissionError(
                        f"Security Violation: Host '{host}' resolves to restricted internal IP '{ip_str}'."
                    )
        except socket.gaierror:
            pass


def get_safe_environment(custom_env: dict | None = None) -> dict:
    """Build a sanitized environment excluding host API secrets."""
    safe_keys = [
        "PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
        "USERNAME", "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT",
    ]
    env = {k: os.environ[k] for k in safe_keys if k in os.environ}
    if custom_env:
        for k, v in custom_env.items():
            # Block injecting or overriding with host secrets
            if k.upper() in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
                continue
            env[str(k)] = str(v)
    return env


class MCPManager:
    def __init__(self):
        self.stacks: dict[str, AsyncExitStack] = {}
        self.sessions: dict[str, ClientSession] = {}
        self.server_tools: dict[str, list[str]] = {}  # server_id -> list of reg tool names

    def _update_db_status(self, sid: str, status: str, tool_count: int | None = None, error: str | None = None):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with conn() as c:
            if status == "connected":
                c.execute(
                    """
                    UPDATE mcp_servers 
                    SET status=?, tool_count=COALESCE(?, tool_count), error=NULL, last_connected_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (status, tool_count, now, now, sid),
                )
            else:
                c.execute(
                    """
                    UPDATE mcp_servers 
                    SET status=?, tool_count=COALESCE(?, 0), error=?, updated_at=?
                    WHERE id=?
                    """,
                    (status, tool_count, error, now, sid),
                )

    async def _load_tools(self, sid: str, session: ClientSession) -> int:
        """Discover tools from MCP session and register them into the unified registry."""
        result = await session.list_tools()
        registered_count = 0
        server_tools_list = []

        # Remove any existing tools for this server to handle capability changes
        registry.remove_prefix(f"mcp.{sid}.")

        for t in result.tools:
            tool_name = t.name
            desc = (t.description or f"MCP tool from server {sid}").strip()[:500]
            schema = t.inputSchema if isinstance(t.inputSchema, dict) else {"type": "object", "properties": {}}

            # Namespace tool: mcp.<server_id>.<tool_name>
            reg_name = f"mcp.{sid}.{tool_name}"

            # Factory for tool execution handler
            def make_handler(_s=session, _n=tool_name, _sid=sid):
                async def call(**kwargs):
                    try:
                        r = await asyncio.wait_for(_s.call_tool(_n, arguments=kwargs), timeout=DEFAULT_TIMEOUT_SECONDS)
                        # Extract content from response
                        texts = []
                        if hasattr(r, "content") and r.content:
                            for item in r.content:
                                text = getattr(item, "text", str(item))
                                texts.append(text)
                        joined = "\n".join(texts)
                        if len(joined) > MAX_TOOL_OUTPUT_CHARS:
                            joined = joined[:MAX_TOOL_OUTPUT_CHARS] + f"\n... [Output truncated at {MAX_TOOL_OUTPUT_CHARS} characters]"
                        return {
                            "content": joined,
                            "is_error": getattr(r, "isError", False),
                            "server_id": _sid,
                        }
                    except asyncio.TimeoutError:
                        return {"content": f"MCP tool call '{_n}' timed out after {DEFAULT_TIMEOUT_SECONDS}s", "is_error": True}
                    except Exception as e:
                        return {"content": f"MCP tool execution failed: {type(e).__name__}: {str(e)}", "is_error": True}
                return call

            # All external MCP tools default to risk="approval"
            registry.add(Spec(
                name=reg_name,
                description=desc,
                source="mcp",
                risk="approval",
                schema=schema,
                handler=make_handler(),
                server_id=sid,
            ))
            server_tools_list.append(reg_name)
            registered_count += 1

        self.server_tools[sid] = server_tools_list
        return registered_count

    async def connect(self, sid: str, max_retries: int = 2) -> dict:
        """Connect to an MCP server by ID with bounded retries."""
        with conn() as c:
            row = c.execute("SELECT * FROM mcp_servers WHERE id=?", (sid,)).fetchone()
            if not row:
                raise ValueError(f"MCP server '{sid}' not found.")
            server = dict(row)

        if not server.get("enabled"):
            raise ValueError(f"MCP server '{server['name']}' is disabled. Enable it before connecting.")

        # If already connected, disconnect first
        await self.disconnect(sid)

        name = server["name"]
        transport = server["transport"]
        attempt = 0
        last_error = None

        self._update_db_status(sid, "connecting")

        while attempt <= max_retries:
            attempt += 1
            stack = AsyncExitStack()
            try:
                if transport == "stdio":
                    command = server.get("command") or ""
                    validate_stdio_command(command)
                    args = json.loads(server.get("args") or "[]")
                    custom_env = json.loads(server.get("env") or "{}")
                    safe_env = get_safe_environment(custom_env)

                    params = StdioServerParameters(command=command, args=args, env=safe_env)
                    rd, wr = await asyncio.wait_for(
                        stack.enter_async_context(stdio_client(params)),
                        timeout=15.0,
                    )
                elif transport in ("streamable-http", "http"):
                    url = server.get("url") or ""
                    validate_http_url(url)
                    
                    # Pre-flight TCP/HTTP probe to verify endpoint is online
                    try:
                        async with httpx.AsyncClient(timeout=3.0) as probe_client:
                            await probe_client.get(url)
                    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, httpx.TimeoutException) as probe_err:
                        raise ConnectionError(f"Cannot reach MCP server at {url}: {probe_err}") from probe_err
                    except httpx.HTTPError:
                        # HTTP error codes (e.g. 404/405/406) indicate server is reachable
                        pass

                    rd, wr, *_ = await asyncio.wait_for(
                        stack.enter_async_context(streamablehttp_client(url)),
                        timeout=15.0,
                    )
                else:
                    raise ValueError(f"Unsupported transport: '{transport}'")

                # Initialize MCP session
                session = await stack.enter_async_context(ClientSession(rd, wr))
                await asyncio.wait_for(session.initialize(), timeout=15.0)

                # Discover and register tools
                tool_count = await self._load_tools(sid, session)

                self.stacks[sid] = stack
                self.sessions[sid] = session
                self._update_db_status(sid, "connected", tool_count=tool_count)

                audit("mcp.connected", f"{name} ({sid}): {tool_count} tools discovered via {transport}")
                logger.info("Connected MCP server '%s' (%s) with %d tools", name, sid, tool_count)

                return {
                    "id": sid,
                    "name": name,
                    "transport": transport,
                    "status": "connected",
                    "tool_count": tool_count,
                }
            except (Exception, asyncio.CancelledError) as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                try:
                    await stack.aclose()
                except Exception:
                    pass
                if attempt <= max_retries and not isinstance(e, (PermissionError, ValueError, ConnectionError)):
                    await asyncio.sleep(0.5 * attempt)
                else:
                    break

        # Retries exhausted
        self._update_db_status(sid, "error", tool_count=0, error=last_error)
        audit("mcp.connect_failed", f"{name} ({sid}): {last_error}")
        raise RuntimeError(f"Failed to connect to MCP server '{name}': {last_error}")

    async def disconnect(self, sid: str) -> dict:
        """Disconnect an active MCP session and unregister its tools."""
        if sid in self.stacks:
            try:
                await self.stacks.pop(sid).aclose()
            except Exception as e:
                logger.warning("Error closing MCP stack for '%s': %s", sid, e)

        self.sessions.pop(sid, None)
        self.server_tools.pop(sid, None)
        registry.remove_prefix(f"mcp.{sid}.")

        self._update_db_status(sid, "disconnected", tool_count=0)
        audit("mcp.disconnected", sid)
        return {"id": sid, "status": "disconnected"}

    async def add_server(
        self,
        name: str,
        transport: str,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str | None = None,
        enabled: bool = True,
    ) -> dict:
        """Create and persist a new MCP server configuration in SQLite."""
        name = name.strip()
        if not name:
            raise ValueError("Server name cannot be empty.")
        transport = transport.strip().lower()
        if transport not in ("stdio", "streamable-http", "http"):
            raise ValueError("Transport must be 'stdio' or 'streamable-http'.")

        sid = f"mcp_{uuid.uuid4().hex[:8]}"
        args_json = json.dumps(args or [])
        env_json = json.dumps(env or {})
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if transport == "stdio":
            if not command:
                raise ValueError("Command is required for stdio transport.")
            validate_stdio_command(command)
        else:
            if not url:
                raise ValueError("URL is required for streamable-http transport.")
            validate_http_url(url)

        with conn() as c:
            c.execute(
                """
                INSERT INTO mcp_servers(
                    id, name, transport, command, args, env, url, enabled, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'disconnected', ?, ?)
                """,
                (sid, name, transport, command, args_json, env_json, url, 1 if enabled else 0, now, now),
            )

        audit("mcp.server_added", f"{name} ({sid}) transport={transport}")

        # If enabled, automatically attempt connection
        if enabled:
            try:
                await self.connect(sid)
            except Exception as e:
                logger.warning("Auto-connect after add failed for '%s': %s", sid, e)

        return self.get_server(sid)

    async def edit_server(
        self,
        sid: str,
        name: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str | None = None,
        enabled: bool | None = None,
    ) -> dict:
        """Edit an existing MCP server configuration in SQLite."""
        existing = self.get_server(sid)
        if not existing:
            raise ValueError(f"MCP server '{sid}' not found.")

        was_connected = existing["status"] == "connected"
        if was_connected:
            await self.disconnect(sid)

        new_name = name.strip() if name is not None else existing["name"]
        new_cmd = command.strip() if command is not None else existing["command"]
        new_args = json.dumps(args) if args is not None else existing["args"]
        new_env = json.dumps(env) if env is not None else existing["env"]
        new_url = url.strip() if url is not None else existing["url"]
        new_enabled = (1 if enabled else 0) if enabled is not None else existing["enabled"]
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if existing["transport"] == "stdio" and new_cmd:
            validate_stdio_command(new_cmd)
        elif existing["transport"] in ("streamable-http", "http") and new_url:
            validate_http_url(new_url)

        with conn() as c:
            c.execute(
                """
                UPDATE mcp_servers
                SET name=?, command=?, args=?, env=?, url=?, enabled=?, updated_at=?
                WHERE id=?
                """,
                (new_name, new_cmd, new_args, new_env, new_url, new_enabled, now, sid),
            )

        audit("mcp.server_edited", f"{new_name} ({sid})")

        if new_enabled and was_connected:
            try:
                await self.connect(sid)
            except Exception as e:
                logger.warning("Reconnection after edit failed for '%s': %s", sid, e)

        return self.get_server(sid)

    async def remove_server(self, sid: str) -> dict:
        """Remove an MCP server from SQLite and disconnect active sessions."""
        await self.disconnect(sid)
        with conn() as c:
            c.execute("DELETE FROM mcp_servers WHERE id=?", (sid,))
        audit("mcp.server_removed", sid)
        return {"id": sid, "deleted": True}

    async def set_enabled(self, sid: str, enabled: bool) -> dict:
        """Enable or disable an MCP server."""
        if not enabled:
            await self.disconnect(sid)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with conn() as c:
            c.execute("UPDATE mcp_servers SET enabled=?, updated_at=? WHERE id=?", (1 if enabled else 0, now, sid))
        if enabled:
            try:
                await self.connect(sid)
            except Exception as e:
                logger.warning("Connection failed after enabling '%s': %s", sid, e)
        return self.get_server(sid)

    def get_server(self, sid: str) -> dict | None:
        with conn() as c:
            row = c.execute("SELECT * FROM mcp_servers WHERE id=?", (sid,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["is_live"] = sid in self.sessions
            res["discovered_tools"] = [
                s for s in registry.list() if s.get("server_id") == sid
            ]
            return res

    def list_servers(self) -> list[dict]:
        with conn() as c:
            rows = c.execute("SELECT * FROM mcp_servers ORDER BY created_at DESC").fetchall()
            servers = []
            for r in rows:
                d = dict(r)
                d["is_live"] = d["id"] in self.sessions
                d["tools"] = [
                    {"name": s["name"], "description": s["description"]}
                    for s in registry.list()
                    if s.get("server_id") == d["id"]
                ]
                servers.append(d)
            return servers

    async def load_all_enabled(self):
        """Called on backend startup to connect all enabled MCP servers."""
        with conn() as c:
            rows = c.execute("SELECT id, name FROM mcp_servers WHERE enabled=1").fetchall()
        for r in rows:
            sid = r["id"]
            name = r["name"]
            try:
                await self.connect(sid)
            except Exception as e:
                logger.warning("Startup connection failed for MCP server '%s' (%s): %s", name, sid, e)


mcp = MCPManager()
