"""MCP（Model Context Protocol）客户端（迭代 5，M6.3——对标 DSH 的 mcp-client）。

轻量 streamable-HTTP 客户端：initialize → notifications/initialized → tools/list → tools/call。
- 只做协议层：发现 MCP 服务器工具并调用，schema 映射为 Ollama 工具格式；
- 服务器不可达/失败 → 连接失败返回空工具集，不阻断应用（failOnStartupError: false 语义）；
- 工具调用结果取 text 内容；失败返回错误说明（不编造）。
"""
import json
import logging
import re
import uuid
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "2025-03-26"


def _parse_sse_id(data_text: str, want_id: int) -> Optional[dict]:
    """解析 SSE 响应，返回 id 匹配的 data JSON（支持多行 data 与 event 行混排）。"""
    for line in data_text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            if obj.get("id") == want_id:
                return obj
    return None


class MCPClient:
    """单个 MCP 服务器的 streamable-HTTP 客户端。"""

    def __init__(self, server_name: str, url: str, headers: Optional[dict] = None,
                 timeout: int = 30) -> None:
        self.server_name = server_name
        self.url = url.rstrip("/") + "/"
        self.headers = {"Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"}
        if headers:
            self.headers.update(headers)
        self.timeout = timeout
        self._session_id: Optional[str] = None
        self._connected = False

    # ---------- 连接 ----------

    def _post(self, payload: dict, want_id: Optional[int] = None) -> dict:
        headers = dict(self.headers)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        resp = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        if want_id is None:
            return {}
        return _parse_sse_id(resp.text, want_id) or {}

    def connect(self) -> bool:
        """握手：initialize + notifications/initialized。失败返回 False（不抛异常）。"""
        try:
            init = self._post({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": _PROTOCOL_VERSION, "capabilities": {},
                           "clientInfo": {"name": "virtual-being", "version": "1.0"}},
            }, want_id=1)
            if not init or "result" not in init:
                return False
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._connected = True
            return True
        except requests.RequestException as exc:
            logger.warning("MCP %s 连接失败: %s", self.server_name, exc)
            return False

    # ---------- 工具 ----------

    def list_tools(self) -> List[dict]:
        """tools/list → [{name, description, inputSchema}]；失败返回 []。"""
        try:
            resp = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, want_id=2)
            return resp.get("result", {}).get("tools", []) or []
        except requests.RequestException as exc:
            logger.warning("MCP %s tools/list 失败: %s", self.server_name, exc)
            return []

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> str:
        """tools/call → 文本结果；失败返回错误说明（不抛异常）。"""
        try:
            resp = self._post({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }, want_id=3)
            result = resp.get("result") or {}
            if resp.get("error") or result.get("isError"):
                err = resp.get("error") or result.get("error") or "MCP 工具调用失败"
                return f"错误：{err}"
            content = result.get("content") or []
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else "（MCP 工具无文本返回）"
        except requests.RequestException as exc:
            logger.warning("MCP %s tools/call 失败: %s", self.server_name, exc)
            return f"错误：MCP 调用失败 {exc}"


def mcp_tool_to_schema(server_name: str, tool: dict) -> dict:
    """把 MCP 工具定义映射为 Ollama 工具 schema（工具名加服务器前缀防冲突）。"""
    name = f"{server_name}_{tool['name']}"
    params = tool.get("inputSchema") or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": tool.get("description") or f"{server_name} 提供的工具",
            "parameters": params,
        },
    }


def register_mcp_server(registry, server_name: str, url: str,
                        headers: Optional[dict] = None,
                        prefix: Optional[str] = None) -> int:
    """连接一个 MCP 服务器并把其工具注册进注册表；返回注册数量（0=失败/无工具）。

    :param prefix: 工具名前缀（默认 server_name，避免与内置工具冲突）
    """
    client = MCPClient(server_name, url, headers=headers)
    if not client.connect():
        logger.warning("MCP 服务器 %s 未连接，跳过注册", server_name)
        return 0
    tools = client.list_tools()
    if not tools:
        return 0
    name_prefix = prefix or server_name
    for t in tools:
        tool_name = f"{name_prefix}_{t['name']}"
        registry.register(
            tool_name,
            mcp_tool_to_schema(name_prefix, t),
            lambda args, _n=t["name"], _c=client: _c.call_tool(_n, args),
        )
    logger.info("MCP 服务器 %s 注册 %d 个工具", server_name, len(tools))
    return len(tools)
