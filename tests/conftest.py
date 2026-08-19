"""pytest 共享配置（tests/conftest.py）。

通用离线测试套件保持确定性：默认关闭 LLM 工具调用路径（M6.1 function calling），
使既有 mock _call_ollama 的测试不受真实 Ollama 工具回复干扰。
工具调用专项测试（tests/test_tool_calling.py）用模块级 fixture 显式开启。
"""
import pytest

from app.config import CONFIG
from app.memory.long_term_memory import LongTermMemory


@pytest.fixture(autouse=True)
def _isolate_default_persona_memory(monkeypatch, tmp_path):
    """让默认 PersonaAgent 使用测试临时库，禁止测试污染项目 data/。"""
    import app.agents.persona_agent as persona_agent_module

    original = persona_agent_module.LongTermMemory

    def isolated_memory(*args, **kwargs):
        kwargs["db_path"] = str(tmp_path / "memory.db")
        return LongTermMemory(*args, **kwargs)

    monkeypatch.setattr(persona_agent_module, "LongTermMemory", isolated_memory)
    yield
    monkeypatch.setattr(persona_agent_module, "LongTermMemory", original)


@pytest.fixture(autouse=True)
def _disable_tool_calling_for_offline_tests():
    """默认关闭工具调用；工具专项测试通过模块级 fixture 重新开启。"""
    original = CONFIG.tool_calling_enabled
    object.__setattr__(CONFIG, "tool_calling_enabled", False)
    yield
    object.__setattr__(CONFIG, "tool_calling_enabled", original)
