"""pytest 共享配置（tests/conftest.py）。

通用离线测试套件保持确定性：默认关闭 LLM 工具调用路径（M6.1 function calling），
使既有 mock _call_ollama 的测试不受真实 Ollama 工具回复干扰。
工具调用专项测试（tests/test_tool_calling.py）用模块级 fixture 显式开启。
"""
import pytest

from app.config import CONFIG


@pytest.fixture(autouse=True)
def _disable_tool_calling_for_offline_tests():
    """默认关闭工具调用；工具专项测试通过模块级 fixture 重新开启。"""
    original = CONFIG.tool_calling_enabled
    object.__setattr__(CONFIG, "tool_calling_enabled", False)
    yield
    object.__setattr__(CONFIG, "tool_calling_enabled", original)
