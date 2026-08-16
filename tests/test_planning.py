"""能力 Agent（规划助手）的离线测试：mock LLM 输出，不调用 Ollama。"""
import pytest

from app.agents.planning_agent import PlanningAgent
from app.tools.planning import parse_plan, plan

# ---------------------------------------------------------------- 解析层

VALID_JSON = (
    '{"goal": "学会 Python", "steps": ['
    '{"no": 1, "title": "安装环境", "priority": "高", "detail": "下载并安装 Python"}, '
    '{"no": 2, "title": "学语法", "priority": "中", "detail": "变量与函数"}]}'
)


def test_parse_plan_valid_json() -> None:
    """合法 JSON → 结构化步骤清单（带序号与优先级）。"""
    result = parse_plan(VALID_JSON, fallback_goal="学会 Python")
    assert result["error"] is None
    assert result["goal"] == "学会 Python"
    assert [s["no"] for s in result["steps"]] == [1, 2]
    assert result["steps"][0]["title"] == "安装环境"
    assert result["steps"][0]["priority"] == "高"
    assert result["steps"][0]["detail"] == "下载并安装 Python"


def test_parse_plan_code_fence() -> None:
    """带 ```json 代码围栏的输出应被容忍。"""
    fenced = "```json\n" + VALID_JSON + "\n```"
    result = parse_plan(fenced)
    assert result["error"] is None
    assert len(result["steps"]) == 2


def test_parse_plan_priority_normalized() -> None:
    """优先级写法归一化：1/2/3、high/low、缺失 → 高/中/低。"""
    raw = (
        '{"goal": "g", "steps": ['
        '{"no": 1, "title": "a", "priority": 1}, '
        '{"no": 2, "title": "b", "priority": "high"}, '
        '{"no": 3, "title": "c", "priority": "3"}, '
        '{"no": 4, "title": "d", "priority": "medium"}, '
        '{"no": 5, "title": "e"}, '
        '{"no": 6, "title": "f", "priority": "紧急"}]}'
    )
    result = parse_plan(raw)
    assert [s["priority"] for s in result["steps"]] == ["高", "高", "低", "中", "中", "高"]


def test_parse_plan_renumbered() -> None:
    """LLM 给出错乱序号时应按顺序重排为 1..n。"""
    raw = '{"goal": "g", "steps": [{"no": 3, "title": "a"}, {"no": 1, "title": "b"}]}'
    result = parse_plan(raw)
    assert [s["no"] for s in result["steps"]] == [1, 2]
    assert [s["title"] for s in result["steps"]] == ["a", "b"]


def test_parse_plan_invalid_steps_skipped() -> None:
    """steps 中无效项（空标题/非 dict）应被跳过。"""
    raw = '{"goal": "g", "steps": [{"no": 1, "title": ""}, 42, {"no": 2, "title": "ok"}]}'
    result = parse_plan(raw)
    assert [s["title"] for s in result["steps"]] == ["ok"]


def test_parse_plan_markdown_fallback() -> None:
    """非 JSON 的 Markdown 清单应降级解析。"""
    md = "目标：学做饭\n1. 买菜：去超市采购食材\n2. 学切菜\n- 练习颠勺\n"
    result = parse_plan(md, fallback_goal="学做饭")
    assert result["error"] is None
    assert result["goal"] == "学做饭"
    assert [s["no"] for s in result["steps"]] == [1, 2, 3]
    assert result["steps"][0]["title"] == "买菜"
    assert result["steps"][0]["detail"] == "去超市采购食材"
    assert all(s["priority"] == "中" for s in result["steps"])


def test_parse_plan_garbage() -> None:
    """完全无法解析的输出 → 结构化错误，不抛异常。"""
    result = parse_plan("今天天气不错哈哈哈")
    assert result["error"] is not None
    assert result["steps"] == []


def test_parse_plan_empty() -> None:
    """空输出 → 结构化错误。"""
    result = parse_plan("   ")
    assert result["error"] is not None


# ---------------------------------------------------------------- 工具主入口（mock LLM）

def test_plan_with_mock_llm() -> None:
    """注入 mock LLM：输入目标 → 结构化步骤清单。"""
    result = plan("我想学 Python", llm_call=lambda prompt: VALID_JSON)
    assert result["error"] is None
    assert result["goal"] == "我想学 Python" or result["goal"] == "学会 Python"
    assert len(result["steps"]) == 2
    assert result["steps"][0]["no"] == 1


def test_plan_llm_returns_garbage() -> None:
    """LLM 输出垃圾 → 结构化错误 + 原始输出保留，不抛异常。"""
    result = plan("学做饭", llm_call=lambda prompt: "我也不知道要输出啥")
    assert result["error"] is not None
    assert result["steps"] == []
    assert result["raw"] == "我也不知道要输出啥"


def test_plan_llm_raises() -> None:
    """LLM 调用抛异常（如 Ollama 未启动）→ 结构化错误，不抛异常。"""
    def boom(prompt: str) -> str:
        raise RuntimeError("Ollama 调用失败")

    result = plan("学做饭", llm_call=boom)
    assert result["error"] is not None
    assert "规划生成失败" in result["error"]
    assert result["steps"] == []


def test_plan_empty_goal_no_llm_call() -> None:
    """空目标：不调用 LLM，直接返回结构化错误。"""
    called = []

    def spy(prompt: str) -> str:
        called.append(prompt)
        return VALID_JSON

    result = plan("   ", llm_call=spy)
    assert result["error"] is not None
    assert called == []


def test_plan_never_raises() -> None:
    """任意输入 + mock LLM 都不抛异常，返回含 error 字段的 dict。"""
    for llm in (lambda p: VALID_JSON, lambda p: "", lambda p: "{{{", lambda p: "1. 买菜\n2. 做饭"):
        result = plan("学做饭", llm_call=llm)
        assert isinstance(result, dict)
        assert "goal" in result and "steps" in result and "error" in result


# ---------------------------------------------------------------- 能力 Agent 封装

def test_planning_agent_with_mock() -> None:
    """PlanningAgent 注入 mock LLM 应产出结构化计划。"""
    agent = PlanningAgent()
    result = agent.plan("周末去爬山", llm_call=lambda prompt: (
        '{"goal": "周末去爬山", "steps": ['
        '{"no": 1, "title": "选路线", "priority": "高", "detail": "查攻略选路线"}, '
        '{"no": 2, "title": "备装备", "priority": "中", "detail": "水与登山鞋"}]}'
    ))
    assert result["error"] is None
    assert len(result["steps"]) == 2
    assert result["steps"][0]["no"] == 1
    assert result["steps"][1]["priority"] == "中"


@pytest.mark.parametrize("goal", ["", None, "  "])
def test_planning_agent_bad_goal(goal) -> None:
    """空目标经 Agent 也应返回结构化错误而非异常。"""
    result = PlanningAgent().plan(goal)  # type: ignore[arg-type]
    assert result["error"] is not None
