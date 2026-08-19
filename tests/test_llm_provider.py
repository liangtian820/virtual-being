"""M7.1（WO-20260816-41）LLM provider 双适配测试：ollama（默认）| openai（云端）。

覆盖：OpenAI /chat/completions 文本调用格式（Bearer/消息/max_tokens）、工具调用格式
（tool_calls 带 id）、工具结果消息按 provider 区分（tool_call_id vs name）、
OpenAI 工具调用完整循环的 tool_call_id 回填；Ollama 默认行为零回归（既有测试覆盖）。
全部 mock requests.post / LLM 调用，不依赖真实云端。
"""
import json

import pytest

from app.agents.persona_agent import PersonaAgent
from app.config import CONFIG


class _FakeResp:
    def __init__(self, data: dict) -> None:
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self) -> None:
        pass


class _FakeMemoryLong:
    def retrieve_fused(self, query, limit=5, days=90, **kwargs):
        return []

    def recent(self, limit=2):
        return []

    def add(self, kind, content, source_session=None):
        pass


def _make_agent(**overrides) -> PersonaAgent:
    """构造完全隔离的 Agent；fake 在初始化时注入，禁止创建默认 data/memory.db。"""
    return PersonaAgent(long_memory=overrides.get("memory_long", _FakeMemoryLong()))


@pytest.fixture
def _openai_provider():
    """临时切到 openai provider + 开启工具路径，测试后恢复。"""
    keys = ("llm_provider", "openai_base_url", "openai_api_key", "openai_model", "tool_calling_enabled")
    orig = {k: getattr(CONFIG, k) for k in keys}
    object.__setattr__(CONFIG, "llm_provider", "openai")
    object.__setattr__(CONFIG, "openai_base_url", "https://api.deepseek.com/v1")
    object.__setattr__(CONFIG, "openai_api_key", "sk-test-123")
    object.__setattr__(CONFIG, "openai_model", "deepseek-chat")
    object.__setattr__(CONFIG, "tool_calling_enabled", True)
    yield
    for k, v in orig.items():
        object.__setattr__(CONFIG, k, v)


# ---------- OpenAI 文本调用 ----------


def test_openai_text_call_format(monkeypatch, _openai_provider):
    """M7.1：openai provider 下文本走 /chat/completions（Bearer + OpenAI 消息格式 + max_tokens）。"""
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        return _FakeResp({"choices": [{"message": {"content": "你好呀，我在呢～"}}]})

    monkeypatch.setattr("requests.post", fake_post)
    agent = _make_agent()
    reply = agent._call_llm([{"role": "user", "content": "你好"}], max_tokens=50)
    assert reply == "你好呀，我在呢～"
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test-123"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["payload"]["max_tokens"] == 50
    assert captured["payload"]["messages"][0]["role"] == "user"


# ---------- OpenAI 配置安全 ----------


def test_openai_text_missing_key_fails_before_network(monkeypatch, _openai_provider):
    object.__setattr__(CONFIG, "openai_api_key", "")
    called = []
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: called.append(1))
    agent = _make_agent()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        agent._call_openai([{"role": "user", "content": "你好"}])
    assert called == []


def test_openai_tools_missing_key_fails_before_network(monkeypatch, _openai_provider):
    object.__setattr__(CONFIG, "openai_api_key", "")
    called = []
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: called.append(1))
    agent = _make_agent()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        agent._call_openai_with_tools([], [])
    assert called == []


# ---------- OpenAI 工具调用 ----------


def test_openai_with_tools_call_format(monkeypatch, _openai_provider):
    """M7.1：openai 工具调用携带 tools；tool_calls 带 id（与 Ollama 差异）。"""
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _FakeResp({"choices": [{"message": {
            "content": "",
            "tool_calls": [{"id": "call_abc", "type": "function",
                            "function": {"name": "web_search", "arguments": '{"query": "X"}'}}],
        }}]})

    monkeypatch.setattr("requests.post", fake_post)
    agent = _make_agent()
    resp = agent._call_llm_with_tools(
        [{"role": "user", "content": "查一下"}],
        [{"type": "function", "function": {"name": "web_search"}}],
        max_tokens=30,
    )
    assert captured["payload"]["tools"] is not None
    assert captured["payload"]["max_tokens"] == 30
    assert resp["tool_calls"][0]["id"] == "call_abc"
    assert resp["tool_calls"][0]["function"]["name"] == "web_search"


# ---------- 工具结果消息按 provider 区分 ----------


def test_tool_result_message_provider(_openai_provider):
    """M7.1：openai → {role:'tool', tool_call_id, content}；ollama → {role:'tool', name, content}。"""
    assert PersonaAgent._tool_result_message("call_x", "web_search", "结果") == {
        "role": "tool", "tool_call_id": "call_x", "content": "结果"}
    keys = ("llm_provider",)
    orig = CONFIG.llm_provider
    object.__setattr__(CONFIG, "llm_provider", "ollama")
    try:
        assert PersonaAgent._tool_result_message("call_x", "web_search", "结果") == {
            "role": "tool", "name": "web_search", "content": "结果"}
    finally:
        object.__setattr__(CONFIG, "llm_provider", orig)


# ---------- OpenAI 工具调用：tool_call_id 适配 + 单轮决策 ----------


def test_try_tool_calling_openai_uses_one_tool_decision_round(monkeypatch, _openai_provider):
    """A1：保留 OpenAI tool_call_id 解析，但结果只进入无工具阶段 2，不能再决策工具。"""
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: '{"files": ["AI虚拟人物/"]}',
    )
    try:
        agent = _make_agent()
        response = {"content": "", "tool_calls": [
            {"id": "call_xyz", "type": "function",
             "function": {"name": "obsidian_vault_list", "arguments": '{"path": "30 · 项目"}'}}]}
        captured = {"decisions": []}

        def record_llm(messages, tools, max_tokens=None):
            captured["decisions"].append({"messages": list(messages), "tools": list(tools)})
            return response

        def record_stage2(messages, max_tokens=None):
            captured["stage2"] = messages
            return "知识库里有 AI虚拟人物 文件夹哦"

        monkeypatch.setattr(agent, "_call_llm_with_tools", record_llm)
        monkeypatch.setattr(agent, "_call_llm", record_stage2)
        agent.chat("列出知识库里 30 项目的文档", session_id="oa-roundtrip")
        assert len(captured["decisions"]) == 1
        assert captured["decisions"][0]["tools"]
        assert not any(m["role"] == "tool" for m in captured["decisions"][0]["messages"])
        assert any("AI虚拟人物" in m.get("content", "") for m in captured["stage2"]
                   if m["role"] == "user")
        assert all("AI虚拟人物" not in m.get("content", "") for m in captured["stage2"]
                   if m["role"] == "system")
    finally:
        global_registry.unregister("obsidian_vault_list")


# ---------- openai provider 下 chat() 全链路（文本，mock _call_openai） ----------


def test_chat_plain_under_openai_provider(monkeypatch, _openai_provider):
    """M7.1：LLM_PROVIDER=openai 时普通对话走云端文本调用（_call_llm → _call_openai）。"""
    agent = _make_agent()
    calls = []

    def fake_openai(messages, max_tokens=None):
        calls.append(max_tokens)
        return "你好呀～今天想聊点什么？"

    monkeypatch.setattr(agent, "_call_openai", fake_openai)
    reply, _ = agent.chat("你好呀", session_id="oa-plain")
    assert reply == "你好呀～今天想聊点什么？"
    assert calls  # 走了云端文本调用
