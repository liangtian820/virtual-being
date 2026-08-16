"""能力 Agent（计算）与意图路由的离线测试（不调用 Ollama，联网已 mock）。"""
import pytest

from app.agents.calculator_agent import CalculatorAgent
from app.agents.persona_agent import PersonaAgent, is_calculator_query
from app.tools.calculator import calculate

# ---------------------------------------------------------------- 四则运算


def test_add() -> None:
    result = calculate("3+5")
    assert result["error"] is None
    assert result["result"] == 8


def test_subtract() -> None:
    assert calculate("10-3")["result"] == 7


def test_multiply() -> None:
    assert calculate("6*7")["result"] == 42


def test_divide() -> None:
    assert calculate("10/4")["result"] == 2.5


def test_precedence() -> None:
    """运算符优先级：先乘除后加减。"""
    assert calculate("2+3*4")["result"] == 14


def test_float_precision() -> None:
    """浮点噪声应被消除。"""
    assert calculate("0.1+0.2")["result"] == 0.3


def test_parentheses() -> None:
    assert calculate("(2+3)*4")["result"] == 20


def test_chinese_operators() -> None:
    """中文运算符（加/减/乘/除）应能解析。"""
    assert calculate("3 加 5")["result"] == 8
    assert calculate("10 减 3")["result"] == 7
    assert calculate("5 乘以 6")["result"] == 30
    assert calculate("12 除以 4")["result"] == 3
    assert calculate("3 加 5 乘以 2")["result"] == 13


# ---------------------------------------------------------------- 百分比


def test_percent_of() -> None:
    """"300 的 20%" 应等于 60。"""
    result = calculate("300 的 20%")
    assert result["error"] is None
    assert result["result"] == 60


def test_percent_of_chinese() -> None:
    """"300 的百分之20" 应等于 60。"""
    assert calculate("300 的百分之20")["result"] == 60


def test_percent_standalone() -> None:
    """单独的"百分之 Y" / "Y%" 表示 Y/100。"""
    assert calculate("百分之20")["result"] == 0.2
    assert calculate("20%")["result"] == 0.2


def test_intent_words_cleaned() -> None:
    """意图词（算一下/等于多少）应被清洗且不影响结果。"""
    assert calculate("算一下 300 的 20% 等于多少")["result"] == 60


# ---------------------------------------------------------------- 错误输入


def test_division_by_zero() -> None:
    """除零应返回明确错误而非崩溃。"""
    result = calculate("3/0")
    assert result["result"] is None
    assert result["error"] is not None
    assert "0" in result["error"]


def test_invalid_input() -> None:
    """无算式/非法算式应返回明确错误。"""
    for bad in ("你好呀", "3+", "1+", "abc", "", "（（"):  # type: ignore[arg-type]
        result = calculate(bad)
        assert result["result"] is None, f"{bad!r} 应失败"
        assert result["error"], f"{bad!r} 应返回错误信息"


def test_injection_blocked() -> None:
    """注入尝试应被拒绝（AST 白名单），绝不执行。"""
    for evil in ("__import__('os').system('dir')", "1; import os", "os.system('ls')",
                 "1**9**9", "True+1", "[1,2,3][0]", "(1).__class__"):
        result = calculate(evil)
        assert result["result"] is None, f"{evil!r} 应被拒绝"
        assert result["error"], f"{evil!r} 应返回错误信息"


@pytest.mark.parametrize("weird", ["！@#￥%……", "abc def ghi", "一二三", "(((((", "1 2 3", "3 的 的 5"])
def test_calculate_never_raises(weird: str) -> None:
    """任何奇怪输入都返回 dict（含 error），不抛异常。"""
    result = calculate(weird)
    assert isinstance(result, dict)
    assert "result" in result and "expression" in result and "error" in result


# ---------------------------------------------------------------- 能力 Agent 封装


def test_calculator_agent_success() -> None:
    result = CalculatorAgent().calculate("300 的 20%")
    assert result["result"] == 60
    assert result["expression"] == "300 的 20%"
    assert result["error"] is None


def test_calculator_agent_error() -> None:
    result = CalculatorAgent().calculate("3/0")
    assert result["result"] is None
    assert result["error"] is not None


# ---------------------------------------------------------------- 意图路由


def test_intent_detection_hit() -> None:
    """计算意图应被识别。"""
    for text in ("算一下 300 的 20%", "计算 3+5", "300 的 20%", "3 加 5",
                 "帮我算 5 乘以 6", "百分之 30 是多少", "12 除以 4 等于多少"):
        assert is_calculator_query(text), f"{text!r} 应命中计算意图"


def test_intent_detection_miss() -> None:
    """日常闲聊不应触发计算意图（避免"加"误伤"加油"等）。"""
    for text in ("我今天心情不错", "随便聊聊", "加油", "今天好累", "嗯嗯", "你好呀"):
        assert not is_calculator_query(text), f"{text!r} 不应命中计算意图"


# ---------------------------------------------------------------- 人格 Agent 路由集成（mock Ollama）


def test_persona_routes_calc_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """命中计算意图时，人格 Agent 应注入计算结果上下文（不调用 Ollama）。"""
    agent = PersonaAgent()
    captured: dict = {}

    def fake_call(messages: list, max_tokens=None) -> str:
        captured["messages"] = messages
        return "好的呀，300 的 20% 是 60 哦～"

    monkeypatch.setattr(agent, "_call_ollama", fake_call)
    reply, _ = agent.chat("算一下 300 的 20%")
    assert reply == "好的呀，300 的 20% 是 60 哦～"
    system_contents = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    assert any("[计算结果]" in c and "300 的 20% = 60" in c for c in system_contents)


def test_persona_routes_calc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """算式失败时，人格 Agent 应注入失败上下文而不是编造结果。"""
    agent = PersonaAgent()
    captured: dict = {}

    def fake_call(messages: list, max_tokens=None) -> str:
        captured["messages"] = messages
        return "唔…这个我没算明白，能再说清楚一点嘛？"

    monkeypatch.setattr(agent, "_call_ollama", fake_call)
    agent.chat("算一下 你好呀")
    system_contents = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    assert any("[计算结果：失败]" in c for c in system_contents)


def test_persona_not_route_casual(monkeypatch: pytest.MonkeyPatch) -> None:
    """日常闲聊不应注入计算上下文。"""
    agent = PersonaAgent()
    captured: dict = {}

    def fake_call(messages: list, max_tokens=None) -> str:
        captured["messages"] = messages
        return "今天也要开开心心的呀～"

    monkeypatch.setattr(agent, "_call_ollama", fake_call)
    agent.chat("我今天心情不错")
    system_contents = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    assert not any("[计算结果]" in c for c in system_contents)
