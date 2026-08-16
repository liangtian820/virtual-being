"""插件化框架（M6.3）离线测试：注册表/启停/分发 + 人格 Agent 集成。

不依赖 Ollama/网络：handler 用纯函数，LLM 调用 mock。
"""
import pytest

from app.agents.persona_agent import PersonaAgent
from app.plugins.loader import load_plugins
from app.plugins.registry import ToolRegistry


def _make_handler(prefix="插件结果"):
    def handler(args: dict) -> str:
        q = (args or {}).get("q", "")
        return f"{prefix}：{q}"
    return handler


# ---------- 注册表 ----------


def test_register_call_unregister():
    reg = ToolRegistry()
    schema = {"type": "function", "function": {"name": "fake_tool", "description": "x",
                                               "parameters": {"type": "object", "properties": {}}}}
    reg.register("fake_tool", schema, _make_handler())
    assert reg.names() == ["fake_tool"]
    assert reg.call("fake_tool", {"q": "你好"}) == "插件结果：你好"
    reg.unregister("fake_tool")
    assert reg.names() == []
    assert "未知" in reg.call("fake_tool", {})


def test_enable_disable():
    reg = ToolRegistry()
    reg.register("t", {"type": "function", "function": {"name": "t", "description": "x",
                                                        "parameters": {"type": "object", "properties": {}}}},
                 _make_handler())
    assert reg.has("t")
    assert reg.schemas()
    reg.set_enabled("t", False)
    assert not reg.has("t")
    assert reg.schemas() == []
    assert "未启用" in reg.call("t", {})
    reg.set_enabled("t", True)
    assert reg.has("t")


def test_handler_exception_returns_error():
    def boom(args):
        raise RuntimeError("内部炸了")

    reg = ToolRegistry()
    reg.register("t", {"type": "function", "function": {"name": "t", "description": "x",
                                                        "parameters": {"type": "object", "properties": {}}}},
                 boom)
    out = reg.call("t", {})
    assert "错误" in out and "内部炸了" in out


def test_loader_empty_autoload():
    # autoload 包当前无插件模块 → 加载返回空列表且不抛异常
    assert load_plugins() == []


# ---------- 人格 Agent 集成 ----------


def test_persona_agent_dispatches_registry_tool(monkeypatch):
    """注册表工具经 _execute_tool 分发执行（插件可插拔生效）。"""
    from app.plugins.registry import registry as global_registry
    from app.tools.tool_specs import get_tool_specs

    name = "fake_plugin_tool"
    global_registry.register(
        name,
        {"type": "function", "function": {"name": name, "description": "测试插件工具",
                                          "parameters": {"type": "object",
                                                         "properties": {"q": {"type": "string"}},
                                                         "required": ["q"]}}},
        _make_handler("插件"),
    )
    try:
        from app.config import CONFIG
        orig = CONFIG.tool_calling_enabled
        object.__setattr__(CONFIG, "tool_calling_enabled", True)
        agent = PersonaAgent()
        out = agent._execute_tool(name, {"q": "插上了"})
        assert out == "插件：插上了"
        # 工具路径的 schema 聚合应包含插件工具
        captured = {}

        def record(messages, tools, max_tokens=None):
            captured["names"] = [t["function"]["name"] for t in tools]
            return {"content": "", "tool_calls": None}

        monkeypatch.setattr(agent, "_call_ollama_with_tools", record)
        monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "好的～")
        agent.chat("提醒我明天喝水", session_id="plug-session")
        assert name in captured["names"]
        assert "add_schedule" in captured["names"]  # 内置工具仍在
        assert len(captured["names"]) == len(get_tool_specs()) + 1
        object.__setattr__(CONFIG, "tool_calling_enabled", orig)
    finally:
        from app.config import CONFIG
        object.__setattr__(CONFIG, "tool_calling_enabled", False)
        global_registry.unregister(name)
