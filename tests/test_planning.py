"""能力 Agent（规划助手）的离线测试：mock LLM 输出，不调用 Ollama。

M2.2（WO-20260816-23）追加：规划结果保存（SQLite）/ 列表 / 删除（临时库）。
"""
import pytest

from app.agents.planning_agent import PlanningAgent
from app.tools.planning import (
    PlanStore,
    delete_plan,
    get_plan,
    list_plans,
    parse_plan,
    plan,
    save_plan,
)

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


# ---------------------------------------------------------------- M2.2 规划结果保存

def _sample_plan() -> dict:
    return {
        "goal": "学会 Python",
        "steps": [
            {"no": 1, "title": "安装环境", "priority": "高", "detail": "下载并安装 Python"},
            {"no": 2, "title": "学语法", "priority": "中", "detail": "变量与函数"},
        ],
        "error": None,
        "raw": "{\"goal\": \"学会 Python\", \"steps\": [...]}",
    }


def test_save_plan_roundtrip(tmp_path) -> None:
    """保存 → 列表/读取，步骤完整还原（额外字段 error/raw 被忽略）。"""
    db = str(tmp_path / "plans.db")
    r = save_plan(_sample_plan(), db_path=db)
    assert r["error"] is None and r["id"] == 1

    lst = list_plans(db_path=db)
    assert lst["error"] is None and lst["count"] == 1
    assert lst["plans"][0]["goal"] == "学会 Python"
    assert lst["plans"][0]["step_count"] == 2
    assert lst["plans"][0]["id"] == 1

    g = get_plan(1, db_path=db)
    assert g["error"] is None
    assert [s["title"] for s in g["plan"]["steps"]] == ["安装环境", "学语法"]
    assert g["plan"]["steps"][0]["priority"] == "高"


def test_save_plan_persists_across_connections(tmp_path) -> None:
    """保存后新建 PlanStore 实例仍可读到（跨短连接持久化）。"""
    db = str(tmp_path / "plans2.db")
    assert save_plan(_sample_plan(), db_path=db)["id"] == 1
    store = PlanStore(db)
    assert store.list()[0]["goal"] == "学会 Python"


def test_save_plan_invalid(tmp_path) -> None:
    """非法规划结果 → 结构化错误，不落库。"""
    db = str(tmp_path / "plans3.db")
    assert save_plan("不是 dict", db_path=db)["error"] is not None
    assert save_plan({}, db_path=db)["error"] is not None
    assert save_plan({"goal": "g", "steps": []}, db_path=db)["error"] is not None
    assert save_plan({"goal": "g", "steps": [{"title": ""}]}, db_path=db)["error"] is not None
    assert PlanStore(db).list() == []


def test_save_plan_skips_invalid_steps(tmp_path) -> None:
    """steps 中无效项被跳过，有效项照常保存。"""
    db = str(tmp_path / "plans4.db")
    plan = {"goal": "g", "steps": [42, {"title": "ok", "priority": "高"}, {"title": ""}]}
    r = save_plan(plan, db_path=db)
    assert r["error"] is None and r["id"] == 1
    got = get_plan(1, db_path=db)
    assert [s["title"] for s in got["plan"]["steps"]] == ["ok"]


def test_list_plans_empty(tmp_path) -> None:
    """空库列表：count=0、error=None（空结果不是失败）。"""
    db = str(tmp_path / "plans5.db")
    lst = list_plans(db_path=db)
    assert lst["count"] == 0 and lst["error"] is None


def test_delete_plan(tmp_path) -> None:
    """删除计划：存在 → True；再删/删不存在 → False + 结构化错误。"""
    db = str(tmp_path / "plans6.db")
    id1 = save_plan(_sample_plan(), db_path=db)["id"]
    id2 = save_plan({"goal": "学做饭", "steps": [{"title": "买菜"}]}, db_path=db)["id"]
    assert id2 != id1
    assert delete_plan(id1, db_path=db)["deleted"] is True
    assert list_plans(db_path=db)["count"] == 1
    assert delete_plan(id1, db_path=db)["deleted"] is False
    assert delete_plan(id1, db_path=db)["error"] is not None
    assert delete_plan(9999, db_path=db)["deleted"] is False
    assert get_plan(id1, db_path=db)["error"] is not None


def test_planning_agent_save_list_delete(tmp_path) -> None:
    """PlanningAgent：plan（mock LLM）→ save → list → delete 全链路。"""
    agent = PlanningAgent(db_path=str(tmp_path / "agent_plans.db"))
    result = agent.plan("周末去爬山", llm_call=lambda prompt: (
        '{"goal": "周末去爬山", "steps": ['
        '{"no": 1, "title": "选路线", "priority": "高", "detail": "查攻略选路线"}, '
        '{"no": 2, "title": "备装备", "priority": "中", "detail": "水与登山鞋"}]}'
    ))
    assert result["error"] is None
    saved = agent.save(result)
    assert saved["error"] is None and saved["id"] == 1
    lst = agent.list_plans()
    assert lst["count"] == 1 and lst["plans"][0]["goal"] == "周末去爬山"
    assert agent.delete_plan(saved["id"])["deleted"] is True
    assert agent.list_plans()["count"] == 0


def test_planning_agent_save_invalid(tmp_path) -> None:
    """Agent 保存非法结果 → 结构化错误，不抛异常。"""
    agent = PlanningAgent(db_path=str(tmp_path / "agent_plans2.db"))
    r = agent.save({"goal": "g", "steps": []})
    assert r["error"] is not None
    r2 = agent.save({})
    assert r2["error"] is not None
    assert agent.list_plans()["count"] == 0
