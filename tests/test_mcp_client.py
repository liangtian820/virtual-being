"""MCP 客户端（M6.3）离线测试：握手/tools/list/tools/call 解析、schema 映射、桥接注册。
M6.4 补充（WO-20260816-32）：text/event-stream 无 charset 时的 UTF-8 解码（中文不乱码）。

mock requests.post 模拟 streamable-HTTP 响应（SSE data 行 + mcp-session-id 头）。
_FakeResp 复刻 requests 的编码行为：text 为按 self.encoding 动态解码的 property，
encoding 从响应头推导（text/* 无 charset → ISO-8859-1，application/json → utf-8）。
"""
import json

import pytest
import requests

from app.mcp_client import MCPClient, mcp_tool_to_schema, register_mcp_server
from app.plugins.registry import ToolRegistry


def _encoding_from_headers(headers: dict) -> str:
    """复刻 requests.get_encoding_from_headers：charset 优先；text/* 无 charset → ISO-8859-1；
    application/json 无 charset → utf-8；其余兜底 utf-8。"""
    ct = headers.get("content-type") or ""
    if "charset=" in ct:
        return ct.split("charset=")[-1].strip().strip('"')
    if "text" in ct:
        return "ISO-8859-1"
    if "application/json" in ct:
        return "utf-8"
    return "utf-8"


class _FakeResp:
    def __init__(self, content: bytes, headers: dict = None) -> None:
        self.content = content
        self.headers = headers or {}
        self.status_code = 200
        self.encoding = _encoding_from_headers(self.headers)

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

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
                                 "capabilities": {}, "serverInfo": {"name": "obsidian"}}}).encode("utf-8"),
                headers={"mcp-session-id": "sess-123", "content-type": "text/event-stream"},
            )
        if method == "tools/list":
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 2, "result": {"tools": [
                {"name": "vault_list", "description": "列出目录",
                 "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                                 "required": ["path"]}},
            ]}}).encode("utf-8"),
                headers={"mcp-session-id": "sess-123", "content-type": "text/event-stream"})
        return _FakeResp(_sse({"jsonrpc": "2.0", "id": 3, "result": {"content": [
            {"type": "text", "text": "['10 · 协作规划与方向/', 'AGENTS.md']"}]}}).encode("utf-8"),
            headers={"mcp-session-id": "sess-123", "content-type": "text/event-stream"})

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
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}).encode("utf-8"),
                             headers={"mcp-session-id": "s1", "content-type": "text/event-stream"})
        if method == "tools/list":
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 2, "result": {"tools": [
                {"name": "tag_list", "description": "列出标签",
                 "inputSchema": {"type": "object", "properties": {}}},
            ]}}).encode("utf-8"),
                headers={"mcp-session-id": "s1", "content-type": "text/event-stream"})
        return _FakeResp(_sse({"jsonrpc": "2.0", "id": 3, "result": {"content": [
            {"type": "text", "text": "[]"}]}}).encode("utf-8"),
            headers={"mcp-session-id": "s1", "content-type": "text/event-stream"})

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


def test_mcp_chinese_not_mojibake(monkeypatch):
    """M6.4 补充（WO-20260816-32）：text/event-stream 无 charset 时，requests 默认按
    ISO-8859-1 解码导致中文乱码；客户端硬设 UTF-8 后中文内容不乱码。"""
    def fake_post(url, json=None, headers=None, timeout=None):
        method = json.get("method")
        if method == "initialize":
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}).encode("utf-8"),
                             headers={"mcp-session-id": "s1", "content-type": "text/event-stream"})
        if method == "tools/list":
            return _FakeResp(_sse({"jsonrpc": "2.0", "id": 2, "result": {"tools": [
                {"name": "vault_list", "description": "列出目录",
                 "inputSchema": {"type": "object", "properties": {}}},
            ]}}).encode("utf-8"),
                headers={"mcp-session-id": "s1", "content-type": "text/event-stream"})
        return _FakeResp(_sse({"jsonrpc": "2.0", "id": 3, "result": {"content": [
            {"type": "text", "text": "['30 · 项目/', 'AI虚拟人物/']"}]}}).encode("utf-8"),
            headers={"mcp-session-id": "s1", "content-type": "text/event-stream"})

    monkeypatch.setattr(requests, "post", fake_post)
    client = MCPClient("obsidian", "http://127.0.0.1:27123/mcp/")
    assert client.connect()
    # 修复前：text/event-stream 无 charset → ISO-8859-1 解码 → 中文乱码；
    # 修复后（_post 硬设 resp.encoding="utf-8"）→ 以下中文断言全部通过
    tools = client.list_tools()
    assert tools[0]["description"] == "列出目录"          # 中文描述不乱码
    out = client.call_tool("vault_list", {"path": "/"})
    assert "AI虚拟人物" in out and "30 · 项目" in out       # 中文内容不乱码


def test_fake_resp_simulates_latin1_mojibake():
    """_FakeResp 复刻 requests 行为：text/event-stream 无 charset → ISO-8859-1 解码乱码
    （中文 UTF-8 字节被逐字节当 Latin-1 字符），保证 test_mcp_chinese_not_mojibake 有效。"""
    resp = _FakeResp(_sse({"jsonrpc": "2.0", "id": 3, "result": {"content": [
        {"type": "text", "text": "AI虚拟人物/"}]}}).encode("utf-8"),
        headers={"mcp-session-id": "s1", "content-type": "text/event-stream"})
    # ISO-8859-1 解码：正确中文必然缺失（具体乱码形态随码表而异，不断言具体字符）
    assert "AI虚拟人物" not in resp.text and "虚拟" not in resp.text
    # 修复路径：设 encoding=utf-8 后 text 重新解码 → 中文正常
    resp.encoding = "utf-8"
    assert "AI虚拟人物" in resp.text
