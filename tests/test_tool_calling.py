"""M6.1 工具调用（LLM function calling）离线测试（WO-20260816-29）。

覆盖：工具选择→执行→回填→最终回复循环、工具失败反馈、危机分支不经工具、
未用工具且意图命中时回退关键词路由、工具 schema 完整性、_execute_tool 各工具薄封装。
全部 mock LLM 与能力 Agent（不依赖 Ollama/网络）。
"""
import pytest

from app.agents.persona_agent import PersonaAgent
from app.config import CONFIG
from app.tools.tool_specs import get_tool_specs


@pytest.fixture(autouse=True)
def _enable_tool_calling():
    """本模块为工具调用专项测试：显式开启（覆盖 conftest 的默认关闭）。"""
    original = CONFIG.tool_calling_enabled
    object.__setattr__(CONFIG, "tool_calling_enabled", True)
    yield
    object.__setattr__(CONFIG, "tool_calling_enabled", original)


class FakeMemoryLong:
    """假长期记忆：检索空、add 记录。"""

    def __init__(self) -> None:
        self.added = []

    def retrieve_fused(self, query, limit=5, days=90, **kwargs):
        return []

    def recent(self, limit=2):
        return []

    def add(self, kind, content, source_session=None):
        self.added.append((kind, content))


class FakeScheduler:
    """假日程 Agent：记录 add/delete/mark_done 调用，today/tomorrow 空。"""

    def __init__(self) -> None:
        self.added = []
        self.marked = []
        self.deleted = []

    def add(self, text):
        self.added.append(text)
        return {"date": "2026-08-17", "time": "15:00", "event": text, "error": None}

    def mark_done(self, text):
        self.marked.append(text)
        return {"updated": 1, "entries": [{"time": "15:00", "event": "喝水"}], "error": None}

    def delete(self, text):
        self.deleted.append(text)
        return {"deleted": 1, "entries": [{"time": "15:00", "event": "喝水"}], "error": None}

    def today(self):
        return {"entries": [], "count": 0}

    def tomorrow(self):
        return {"entries": [], "count": 0}


class FakePlanner:
    def __init__(self) -> None:
        self.saved = []

    def list_plans(self):
        return {"plans": [{"goal": "学做饭", "step_count": 6}], "count": 1, "error": None}

    def save(self, plan):
        self.saved.append(plan)
        return {"id": 7, "error": None}


class FakeKnowledge:
    def query(self, q):
        return {"answer": "LangGraph 是多 Agent 编排框架", "source": "内置知识库", "origin": "kb"}


class FakeCalculator:
    def calculate(self, expr):
        return {"expression": "3+5", "result": "8", "error": None}


def _make_agent(**overrides) -> PersonaAgent:
    agent = PersonaAgent()
    agent._memory_long = overrides.get("memory_long", FakeMemoryLong())
    agent._scheduler = overrides.get("scheduler", FakeScheduler())
    agent._planner = overrides.get("planner", FakePlanner())
    agent._knowledge = overrides.get("knowledge", FakeKnowledge())
    agent._calculator = overrides.get("calculator", FakeCalculator())
    return agent


# ---------- 工具 schema ----------


def test_tool_specs_complete():
    specs = get_tool_specs()
    names = {s["function"]["name"] for s in specs}
    assert names == {
        "get_schedule", "add_schedule", "mark_schedule_done", "delete_schedule",
        "list_plans", "save_plan", "query_memory", "query_knowledge", "calculate",
    }
    for s in specs:
        assert s["type"] == "function"
        assert s["function"]["description"]
        assert isinstance(s["function"]["parameters"].get("properties"), dict)
        # 必填参数已标注（required 字段存在）
        assert "required" in s["function"]["parameters"]


# ---------- _execute_tool 薄封装 ----------


def test_execute_add_schedule():
    agent = _make_agent()
    out = agent._execute_tool("add_schedule", {"text": "明天下午3点提醒我喝水"})
    assert "已记录" in out and "15:00" in out
    assert agent._scheduler.added == ["明天下午3点提醒我喝水"]


def test_execute_get_schedule_empty():
    agent = _make_agent()
    out = agent._execute_tool("get_schedule", {"date": "today"})
    assert "没有日程" in out


def test_execute_mark_schedule_done():
    agent = _make_agent()
    out = agent._execute_tool("mark_schedule_done", {"text": "今天喝水的提醒完成了"})
    assert "已标记完成" in out
    assert agent._scheduler.marked == ["今天喝水的提醒完成了"]


def test_execute_delete_schedule():
    agent = _make_agent()
    out = agent._execute_tool("delete_schedule", {"text": "删掉明天下午的提醒"})
    assert "已删除" in out
    assert agent._scheduler.deleted == ["删掉明天下午的提醒"]


def test_execute_save_plan():
    agent = _make_agent()
    out = agent._execute_tool("save_plan", {"goal": "学会弹吉他", "steps": [{"title": "买一把吉他"}]})
    assert "已保存计划" in out and "学会弹吉他" in out
    assert agent._planner.saved == [{"goal": "学会弹吉他", "steps": [{"title": "买一把吉他"}]}]


def test_execute_query_memory_empty():
    agent = _make_agent()
    out = agent._execute_tool("query_memory", {"question": "我喜欢什么"})
    assert "没有相关内容" in out


def test_execute_query_knowledge():
    agent = _make_agent()
    out = agent._execute_tool("query_knowledge", {"question": "什么是LangGraph"})
    assert "LangGraph" in out and "来源" in out


def test_execute_calculate():
    agent = _make_agent()
    out = agent._execute_tool("calculate", {"expression": "3加5"})
    assert "3+5 = 8" in out


def test_execute_list_plans():
    agent = _make_agent()
    out = agent._execute_tool("list_plans", {})
    assert "学做饭" in out


def test_execute_unknown_tool():
    agent = _make_agent()
    out = agent._execute_tool("no_such_tool", {})
    assert "未知工具" in out


# ---------- 工具调用循环 ----------


def test_tool_loop_executes_and_final_reply(monkeypatch):
    agent = _make_agent()
    script = iter([
        {"content": "", "tool_calls": [
            {"function": {"name": "add_schedule", "arguments": {"text": "明天下午3点提醒我喝水"}}}]},
        {"content": "", "tool_calls": None},  # 工具已用过，本轮无更多调用 → 阶段 2
    ])
    monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "好呀，明天下午3点提醒你喝水，我记下啦～")
    reply, sid = agent.chat("明天下午3点提醒我喝水")
    assert reply == "好呀，明天下午3点提醒你喝水，我记下啦～"
    assert agent._scheduler.added == ["明天下午3点提醒我喝水"]


def test_tool_loop_feeds_error_back(monkeypatch):
    agent = _make_agent()

    def boom(text):
        return {"date": None, "time": None, "event": None, "error": "解析失败：缺少时间"}

    agent._scheduler = FakeScheduler()
    agent._scheduler.add = boom
    script = iter([
        {"content": "", "tool_calls": [
            {"function": {"name": "add_schedule", "arguments": {"text": "提醒我喝水"}}}]},
        {"content": "", "tool_calls": None},
    ])
    monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "嗯嗯，这个我好像没记上呢，你能告诉我具体几点吗？")
    reply, _ = agent.chat("提醒我喝水")
    assert "没记上" in reply


# ---------- 危机分支不经工具 ----------


def test_crisis_never_uses_tools(monkeypatch):
    agent = _make_agent()

    def boom(*a, **k):
        raise AssertionError("危机分支不应调用工具路径")

    monkeypatch.setattr(agent, "_call_ollama_with_tools", boom)
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "我在呢，你很重要")
    reply, _ = agent.chat("活着好没意思，感觉撑不下去了")
    assert "12356" in reply or "热线" in reply  # ensure_crisis_help 代码层兜底


# ---------- 回退关键词路由 ----------


def test_no_tool_but_intent_falls_back_to_keyword_route(monkeypatch):
    agent = _make_agent()
    script = iter([
        {"content": "我帮你查一下！", "tool_calls": None},  # 模型未用工具
    ])
    monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "（知识路由兜底回复）")
    reply, _ = agent.chat("什么是LangGraph？")
    assert reply == "（知识路由兜底回复）"  # 走了关键词路由（_call_ollama），未用工具路径回复


def test_no_tool_no_intent_uses_llm_reply(monkeypatch):
    agent = _make_agent()
    # "你好呀" 不命中任何可服务意图 → 不进入工具路径，走默认分支（_call_ollama）
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "嗯嗯，我在呢，今天过得怎么样？")
    reply, _ = agent.chat("你好呀")
    assert reply == "嗯嗯，我在呢，今天过得怎么样？"


def test_tool_path_exception_falls_back(monkeypatch):
    agent = _make_agent()

    def boom(*a, **k):
        raise RuntimeError("Ollama 挂了")

    monkeypatch.setattr(agent, "_call_ollama_with_tools", boom)
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "（异常兜底回复）")
    reply, _ = agent.chat("明天下午3点提醒我喝水")
    assert reply == "（异常兜底回复）"
