from __future__ import annotations
import asyncio
import copy
from dataclasses import dataclass
from typing import Any, Callable, Coroutine
from jsonschema import validate, ValidationError


@dataclass
class Spec:
    name: str
    description: str
    source: str
    risk: str
    schema: dict
    handler: Callable[..., Any]
    server_id: str | None = None


def sanitize_schema(schema: dict) -> dict:
    """Normalize and sanitize JSON Schema for strict LLM providers."""
    s = copy.deepcopy(schema) if schema else {}
    if not isinstance(s, dict):
        s = {"type": "object", "properties": {}}
    if s.get("type") != "object":
        s["type"] = "object"
    if "properties" not in s or not isinstance(s["properties"], dict):
        s["properties"] = {}
    # Remove metadata keys unsupported by some providers
    for k in ["$schema", "$id", "title"]:
        s.pop(k, None)
    return s


class Registry:
    def __init__(self):
        self.items: dict[str, Spec] = {}
        self._provider_to_reg: dict[str, str] = {}
        self._reg_to_provider: dict[str, str] = {}

    def _sync_name_map(self):
        self._provider_to_reg.clear()
        self._reg_to_provider.clear()
        for reg_name in self.items:
            # Replace characters that violate provider regex ^[a-zA-Z0-9_-]+$
            p_name = reg_name.replace(".", "_").replace(":", "_").replace("-", "_")
            # Avoid collisions by appending suffix if needed
            base = p_name
            counter = 1
            while p_name in self._provider_to_reg and self._provider_to_reg[p_name] != reg_name:
                p_name = f"{base}_{counter}"
                counter += 1
            self._provider_to_reg[p_name] = reg_name
            self._reg_to_provider[reg_name] = p_name

    def add(self, s: Spec):
        self.items[s.name] = s
        self._sync_name_map()

    def remove_prefix(self, p: str):
        self.items = {k: v for k, v in self.items.items() if not k.startswith(p)}
        self._sync_name_map()

    def list_all(self) -> list[Spec]:
        return list(self.items.values())

    def invoke(self, name: str, args: dict = None) -> any:
        """Direct invocation helper."""
        s = self.items.get(name)
        if not s:
            raise KeyError(f"Tool not found: {name}")
        args = args or {}
        res = s.handler(**args)
        if asyncio.iscoroutine(res):
            return asyncio.run(res)
        return res

    def list(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "source": s.source,
                "risk": s.risk,
                "input_schema": s.schema,
                "server_id": s.server_id,
            }
            for s in self.items.values()
        ]

    def to_provider_name(self, reg_name: str) -> str:
        return self._reg_to_provider.get(reg_name, reg_name.replace(".", "_"))

    def from_provider_name(self, provider_name: str) -> str | None:
        if provider_name in self._provider_to_reg:
            return self._provider_to_reg[provider_name]
        if provider_name in self.items:
            return provider_name
        # Attempt fallback
        candidate = provider_name.replace("_", ".")
        if candidate in self.items:
            return candidate
        return None

    def get_openai_tools(self) -> list[dict]:
        """Format registered tools for OpenAI / Groq / OpenRouter tool calling."""
        tools = []
        for s in self.items.values():
            p_name = self.to_provider_name(s.name)
            tools.append({
                "type": "function",
                "function": {
                    "name": p_name,
                    "description": s.description or f"Tool {s.name}",
                    "parameters": sanitize_schema(s.schema),
                },
            })
        return tools

    def get_gemini_tools(self) -> list[dict]:
        """Format registered tools for Google Gemini function declarations."""
        declarations = []
        for s in self.items.values():
            p_name = self.to_provider_name(s.name)
            declarations.append({
                "name": p_name,
                "description": s.description or f"Tool {s.name}",
                "parameters": sanitize_schema(s.schema),
            })
        if not declarations:
            return []
        return [{"functionDeclarations": declarations}]

    def validate_args(self, spec: Spec, args: dict) -> tuple[bool, str | None]:
        schema = sanitize_schema(spec.schema)
        try:
            validate(instance=args, schema=schema)
            return True, None
        except ValidationError as e:
            return False, f"Invalid arguments for {spec.name}: {e.message}"
        except Exception as e:
            return False, f"Schema validation error for {spec.name}: {str(e)}"

    async def run(self, name: str, args: dict):
        """Original handler caller for backward compatibility."""
        from app.core.emergency import is_emergency_stopped
        if is_emergency_stopped():
            raise RuntimeError("Execution blocked: Global Emergency Stop is currently engaged.")

        s = self.items.get(name)
        if not s:
            raise KeyError(f"Tool not found: {name}")
        valid, err = self.validate_args(s, args)
        if not valid:
            raise ValueError(err)
        result = s.handler(**args)
        return await result if asyncio.iscoroutine(result) else result

    async def execute(self, name: str, args: dict, timeout: float = 30.0) -> dict:
        """Structured execution with timeout, validation, and error recovery."""
        from app.core.emergency import is_emergency_stopped
        if is_emergency_stopped():
            return {"success": False, "error": "Execution blocked: Global Emergency Stop is currently engaged."}

        s = self.items.get(name)
        if not s:
            return {"success": False, "error": f"Tool '{name}' is not registered."}

        valid, err = self.validate_args(s, args)
        if not valid:
            return {"success": False, "error": err}

        try:
            res_obj = s.handler(**args)
            if asyncio.iscoroutine(res_obj):
                result = await asyncio.wait_for(res_obj, timeout=timeout)
            else:
                result = await asyncio.wait_for(asyncio.to_thread(lambda: res_obj), timeout=timeout)
            return {"success": True, "result": result}
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Tool '{name}' timed out after {timeout} seconds."}
        except Exception as e:
            return {"success": False, "error": f"Tool '{name}' execution failed: {type(e).__name__}: {str(e)}"}


registry = Registry()
