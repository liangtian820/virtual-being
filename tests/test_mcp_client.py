"""MCP 客户端（M6.3）离线测试：握手/tools/list/tools/call 解析、schema 映射、桥接注册。

mock requests.post 模拟 streamable-HTTP 响应（SSE data 行 + mcp-session-id 头）。
"""
import json

import pytest
import requests

from app.mcp_client import MCPClient, mcp_tool_to_schema, register_mcp_server
from app.plugins.registry import ToolRegistry


class _FakeResp:
    def __init__(self, text: str, headers: dict = None) -> None:
        self.text = text
        self.headers = headers or {}
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


def _sse(obj) -> str:
    return "event: message\ndata: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def test_connect_and_list_tools(monkeypatch):
    """握手 + tools/list 解析 + schema 映射（前缀防冲突）。"""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((json.get("method"), json.get("id")))
        method = json.get("method")
        if method == "initialize":
            return _FakeResp(
                _sse({"jsonrpc": "2.0", "id": 1,
                      "result": {"protocolVersion": "2025-03-26",
                                 "capabilities": {}, "serverInfo": {"name": "obsidian"}}}),
                headers={"mcp-session-id": "sess-123"},
            )
        if method == "tools/list":
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 2, "result": {"tools": [
                {"name": "vault_list", "description": "列出目录",
                 "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                                 "required": ["path"]}},
            ]}}))
        return _FakeResp(_sse({"jsonrpc": "2.0", "id": 3, "result": {"content": [
            {"type": "text", "text": "['10 · 协作规划与方向/', 'AGENTS.md']"}]}}))

    monkeypatch.setattr(requests, "post", fake_post)
    client = MCPClient("obsidian", "http://127.0.0.1:27123/mcp/")
    assert client.connect()
    assert client._session_id == "sess-123"
    tools = client.list_tools()
    assert len(tools) == 1 and tools[0]["name"] == "vault_list"
    out = client.call_tool("vault_list", {"path": "/"})
    assert "AGENTS.md" in out
    # 握手顺序：initialize → notifications/initialized → tools/list → tools/call
    assert calls[0] == ("initialize", 1)
    assert calls[1] == ("notifications/initialized", None)


def test_schema_mapping_prefix():
    schema = mcp_tool_to_schema("obsidian", {"name": "vault_read", "description": "读文件",
                                             "inputSchema": {"type": "object", "properties": {}}})
    assert schema["function"]["name"] == "obsidian_vault_read"
    assert schema["function"]["description"] == "读文件"


def test_register_mcp_server_into_registry(monkeypatch):
    """桥接：MCP 工具注册进注册表并可执行（可插拔）。"""
    def fake_post(url, json=None, headers=None, timeout=None):
        method = json.get("method")
        if method == "initialize":
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}),
                             headers={"mcp-session-id": "s1"})
        if method == "tools/list":
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 2, "result": {"tools": [
                {"name": "tag_list", "description": "列出标签",
                 "inputSchema": {"type": "object", "properties": {}}},
            ]}}))
        return _FakeResp(_sse({"jsonrpc": "2.0", "id": 3, "result": {"content": [
            {"type": "text", "text": "[]"}]}}))

    monkeypatch.setattr(requests, "post", fake_post)
    reg = ToolRegistry()
    n = register_mcp_server(reg, "obsidian", "http://127.0.0.1:27123/mcp/")
    assert n == 1
    assert reg.has("obsidian_tag_list")
    assert reg.call("obsidian_tag_list", {}) == "[]"


def test_connect_failure_returns_zero(monkeypatch):
    """服务器不可达 → 注册 0，不抛异常（failOnStartupError: false 语义）。"""
    def boom(*a, **k):
        raise requests.ConnectionError("拒绝连接")

    monkeypatch.setattr(requests, "post", boom)
    reg = ToolRegistry()
    n = register_mcp_server(reg, "down-server", "http://127.0.0.1:9/mcp/")
    assert n == 0
    assert reg.names() == []
