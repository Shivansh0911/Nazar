"""MCP hub: Nazar as an MCP *client*.

Reads `mcp.servers.json` (same `mcpServers` shape as Claude Desktop / Cursor, so any server config can be pasted in),
connects to every configured server (stdio subprocess or Streamable HTTP) on one background event loop, and offers
their tools to the investigator as function tools named `mcp__<server>__<tool>`.

Safety:
- `${VAR}` in a config is filled from the environment / the repo .env; a server whose variables are empty is listed
  as "needs_config" and never started.
- A tool runs without the owner's approval ONLY when the server marks it read-only (MCP `readOnlyHint`) or the
  config lists it under `auto_approve`. Everything else is queued as a pending action for the owner.
- Only text goes out: the investigator never hands raw footage to an external tool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import ENV_FILE, REPO_ROOT, get_settings

log = logging.getLogger("nazar.mcp")
PREFIX = "mcp__"
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NAME_OK = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass
class Server:
    name: str
    cfg: dict
    state: str = "idle"  # idle | disabled | needs_config | connecting | connected | error
    error: str | None = None
    missing: list[str] = field(default_factory=list)
    tools: list[Any] = field(default_factory=list)
    client: Any = None
    ready: threading.Event = field(default_factory=threading.Event)
    stop: Any = None  # asyncio.Event, created on the hub loop

    @property
    def transport(self) -> str:
        return "http" if self.cfg.get("url") else "stdio"


def _env_lookup() -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        from dotenv import dotenv_values

        env.update({k: v for k, v in dotenv_values(ENV_FILE).items() if v})
    except Exception:
        pass
    env.update({k: v for k, v in os.environ.items() if v})
    s = get_settings()
    env.setdefault("NAZAR_DATA_DIR", str(s.data_dir))
    env.setdefault("NAZAR_EXPORT_DIR", str(s.data_dir / "exports"))
    try:
        (s.data_dir / "exports").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    env.setdefault("NAZAR_REPO", str(REPO_ROOT))
    return env


def expand(value: Any, env: dict[str, str], missing: list[str]) -> Any:
    """Fill ${VAR} everywhere in a config value; names with no value are collected in `missing`."""
    if isinstance(value, str):
        def sub(m: re.Match) -> str:
            v = env.get(m.group(1), "")
            if not v and m.group(1) not in missing:
                missing.append(m.group(1))
            return v

        return _VAR.sub(sub, value)
    if isinstance(value, list):
        return [expand(v, env, missing) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, env, missing) for k, v in value.items()}
    return value


def config_path() -> Path:
    p = get_settings().MCP_CONFIG
    return Path(p) if p else REPO_ROOT / "mcp.servers.json"


def load_config(path: Path | None = None) -> dict[str, dict]:
    path = path or config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("cannot read %s: %s", path, e)
        return {}
    servers = data.get("mcpServers") or data.get("servers") or {}
    return {k: v for k, v in servers.items() if isinstance(v, dict)}


def tool_fn_name(server: str, tool: str) -> str:
    return (PREFIX + _NAME_OK.sub("_", server) + "__" + _NAME_OK.sub("_", tool))[:64]


def _schema(tool: Any) -> dict:
    s = dict(getattr(tool, "input_schema", None) or {})
    s.pop("$schema", None)
    if s.get("type") != "object":
        s = {"type": "object", "properties": {}}
    s.setdefault("properties", {})
    return s


def result_view(res: Any, limit: int = 6000) -> dict:
    """An MCP CallToolResult as a small JSON-able dict for the model (text only; binary content is only counted)."""
    texts, other = [], 0
    for c in getattr(res, "content", None) or []:
        if getattr(c, "type", "") == "text":
            texts.append(getattr(c, "text", "") or "")
        else:
            other += 1
    out: dict[str, Any] = {"text": "\n".join(texts)[:limit]}
    sc = getattr(res, "structured_content", None)
    if sc and not out["text"]:
        out["data"] = json.loads(json.dumps(sc, default=str)[:limit]) if len(json.dumps(sc, default=str)) <= limit \
            else json.dumps(sc, default=str)[:limit]
    if other:
        out["non_text_items"] = other
    if getattr(res, "is_error", False):
        out["error"] = out.get("text") or "the tool reported an error"
    return out


class Hub:
    def __init__(self, servers: dict[str, dict] | None = None, connect_timeout: float = 45.0, call_timeout: float = 60.0):
        self._cfg = servers
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.servers: dict[str, Server] = {}
        self._index: dict[str, tuple[str, str]] = {}  # function name -> (server, tool)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started = False

    # ---- lifecycle -------------------------------------------------------------------------------------------
    def start(self, wait: bool = True) -> "Hub":
        with self._lock:
            if self._started:
                return self
            self._started = True
            cfg = self._cfg if self._cfg is not None else load_config()
            env = _env_lookup()
            for name, raw in cfg.items():
                srv = Server(name=name, cfg=raw)
                self.servers[name] = srv
                if raw.get("enabled") is False:
                    srv.state = "disabled"
                    continue
                missing: list[str] = []
                srv.cfg = expand(raw, env, missing)
                if missing:
                    srv.state, srv.missing = "needs_config", missing
                    continue
                srv.state = "connecting"
            todo = [s for s in self.servers.values() if s.state == "connecting"]
            if todo:
                # stdio servers need subprocess support: the Proactor loop on Windows
                self._loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever, name="nazar-mcp", daemon=True)
                self._thread.start()
                for s in todo:
                    asyncio.run_coroutine_threadsafe(self._serve(s), self._loop)
        if wait:
            for s in todo:
                if not s.ready.wait(self.connect_timeout) and s.state == "connecting":
                    s.error = f"still starting after {self.connect_timeout:.0f} s (first run downloads the server)"
        self._reindex()
        return self

    async def _serve(self, srv: Server) -> None:
        from contextlib import AsyncExitStack

        from mcp import Client, StdioServerParameters

        srv.stop = asyncio.Event()
        try:
            async with AsyncExitStack() as stack:
                if srv.transport == "http":
                    target: Any = srv.cfg["url"]
                    if srv.cfg.get("headers"):
                        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

                        http = await stack.enter_async_context(create_mcp_http_client(headers=dict(srv.cfg["headers"])))
                        target = streamable_http_client(srv.cfg["url"], http_client=http)
                else:
                    cmd = str(srv.cfg.get("command") or "")
                    if cmd in ("python", "python3"):
                        cmd = sys.executable
                    from mcp.client.stdio import get_default_environment

                    # a server gets the basic environment (PATH, HOME, ...) plus ONLY what its config names:
                    # third-party servers never inherit Nazar's own keys
                    target = StdioServerParameters(command=shutil.which(cmd) or cmd,
                                                   args=[str(a) for a in srv.cfg.get("args") or []],
                                                   env={**get_default_environment(),
                                                        **{k: str(v) for k, v in (srv.cfg.get("env") or {}).items()}},
                                                   cwd=srv.cfg.get("cwd") or None)
                client = await stack.enter_async_context(Client(target, read_timeout_seconds=self.call_timeout))
                tools, cursor = [], None
                for _ in range(20):
                    page = await client.list_tools(cursor=cursor)
                    tools.extend(page.tools)
                    cursor = getattr(page, "next_cursor", None)
                    if not cursor:
                        break
                srv.client, srv.tools, srv.state, srv.error = client, tools, "connected", None
                self._reindex()
                log.info("mcp server %s connected: %d tools", srv.name, len(tools))
                srv.ready.set()
                await srv.stop.wait()
        except BaseException as e:  # incl. ExceptionGroup from the transport's task group
            if srv.state != "stopped":
                inner: BaseException = e
                while isinstance(inner, BaseExceptionGroup) and inner.exceptions:
                    inner = inner.exceptions[0]
                hint = " - the server process stopped while starting; run its command by hand to see why"                     if srv.transport == "stdio" and not isinstance(inner, FileNotFoundError) else ""
                srv.state, srv.error = "error", f"{type(inner).__name__}: {str(inner)[:200]}{hint}"
                log.warning("mcp server %s failed: %s", srv.name, srv.error)
        finally:
            srv.client = None
            srv.ready.set()

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return
        for s in self.servers.values():
            if s.stop is not None:
                s.state = "stopped" if s.state == "connected" else s.state
                loop.call_soon_threadsafe(s.stop.set)
        if self._thread is not None:
            deadline = 5.0
            for s in self.servers.values():
                while s.client is not None and deadline > 0:
                    threading.Event().wait(0.05)
                    deadline -= 0.05
            loop.call_soon_threadsafe(loop.stop)
            self._thread.join(timeout=3)
        self._loop = None

    # ---- tools ---------------------------------------------------------------------------------------------------
    def _allowed(self, srv: Server, tool_name: str) -> bool:
        only = srv.cfg.get("tools")
        return not only or tool_name in only

    def _reindex(self) -> None:
        self._index = {}
        for s in self.servers.values():
            if s.state != "connected":
                continue
            for t in s.tools:
                if self._allowed(s, t.name):
                    self._index[tool_fn_name(s.name, t.name)] = (s.name, t.name)

    def read_only(self, fn_name: str) -> bool:
        """True only when the server says so (readOnlyHint) or the owner's config auto-approves the tool."""
        ref = self._index.get(fn_name)
        if not ref:
            return False
        srv = self.servers[ref[0]]
        if ref[1] in (srv.cfg.get("auto_approve") or []):
            return True
        if ref[1] in (srv.cfg.get("require_approval") or []):
            return False
        tool = next((t for t in srv.tools if t.name == ref[1]), None)
        ann = getattr(tool, "annotations", None)
        return bool(ann is not None and getattr(ann, "read_only_hint", None) is True)

    def has(self, fn_name: str) -> bool:
        return fn_name in self._index

    def label(self, fn_name: str) -> str:
        ref = self._index.get(fn_name)
        return f"{ref[0]} · {ref[1]}" if ref else fn_name

    def function_tools(self, max_tools: int | None = None) -> list[dict]:
        """Tools in the Responses API function format (not strict: MCP schemas are free-form JSON Schema)."""
        cap = max_tools if max_tools is not None else get_settings().MCP_MAX_TOOLS
        out = []
        for fn, (sname, tname) in self._index.items():
            srv = self.servers[sname]
            t = next(x for x in srv.tools if x.name == tname)
            gate = "" if self.read_only(fn) else " [needs the owner's approval: it is queued, not run]"
            desc = f"[{sname}] {(t.description or t.name).strip()}"[:400] + gate
            out.append({"type": "function", "name": fn, "description": desc, "strict": False, "parameters": _schema(t)})
        if len(out) > cap:
            log.warning("%d MCP tools available; offering the first %d (raise MCP_MAX_TOOLS or set \"tools\" per server)",
                        len(out), cap)
        return out[:cap]

    def call(self, fn_name: str, args: dict | None) -> dict:
        ref = self._index.get(fn_name)
        if not ref:
            return {"error": f"unknown MCP tool {fn_name}"}
        srv = self.servers[ref[0]]
        if srv.client is None or self._loop is None:
            return {"error": f"MCP server {srv.name} is not connected"}
        fut = asyncio.run_coroutine_threadsafe(srv.client.call_tool(ref[1], args or {}), self._loop)
        try:
            return result_view(fut.result(self.call_timeout + 5))
        except Exception as e:
            fut.cancel()
            return {"error": f"{type(e).__name__}: {str(e)[:300]}"}

    def status(self) -> list[dict]:
        out = []
        for s in self.servers.values():
            tools = [{"name": t.name, "fn": tool_fn_name(s.name, t.name),
                      "description": (t.description or "").strip()[:160],
                      "needs_approval": not self.read_only(tool_fn_name(s.name, t.name))}
                     for t in s.tools if self._allowed(s, t.name)] if s.state == "connected" else []
            out.append({"name": s.name, "state": s.state, "transport": s.transport, "error": s.error,
                        "missing": s.missing, "description": s.cfg.get("description"), "tools": tools})
        return out


_hub: Hub | None = None
_hub_lock = threading.Lock()


def get_hub(wait: bool = True) -> Hub:
    """The process-wide hub. Connecting is lazy (first investigation / first status call) and never raises."""
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = Hub({} if not get_settings().MCP_ENABLED else None)
    return _hub.start(wait=wait)


def set_hub(hub: Hub | None) -> None:
    global _hub
    _hub = hub


def close_hub() -> None:
    global _hub
    if _hub is not None:
        _hub.close()
        _hub = None
