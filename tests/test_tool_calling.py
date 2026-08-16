"""M6.1 工具调用（LLM function calling）离线测试（WO-20260816-29）。

覆盖：工具选择→执行→回填→最终回复循环、工具失败反馈、危机分支不经工具、
未用工具且意图命中时回退关键词路由、工具 schema 完整性、_execute_tool 各工具薄封装。
M6.4（WO-20260816-32）：阶段 1 只带候选组 schema（意图预筛，≤8）、指引按候选裁剪。
全部 mock LLM 与能力 Agent（不依赖 Ollama/网络）。
"""
import pytest

from app.agents.persona_agent import PersonaAgent
from app.config import CONFIG
from app.tools.tool_groups import TOOL_GROUPS
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
        "web_search",
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


def test_execute_web_search(monkeypatch):
    agent = _make_agent()
    monkeypatch.setattr(
        "app.tools.web_search.search_text",
        lambda q, timeout=10: "1. 测试标题\n   链接：https://example.com\n   摘要：这是摘要",
    )
    out = agent._execute_tool("web_search", {"query": "DeepSeek 新闻"})
    assert "测试标题" in out and "https://example.com" in out


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
    captured = {}

    def record(messages, max_tokens=None):
        captured["sys"] = [m["content"] for m in messages if m["role"] == "system"]
        return "（知识路由兜底回复）"

    monkeypatch.setattr(agent, "_call_ollama", record)
    reply, _ = agent.chat("什么是LangGraph？")
    assert reply == "（知识路由兜底回复）"  # 走了关键词路由（_call_ollama），未用工具路径回复
    # WO-20260816-34：知识路由兜底真实注入（原 if/elif 死代码下该注入不执行）
    assert any("知识查询结果" in c for c in captured["sys"])


def test_no_tool_no_intent_uses_llm_reply(monkeypatch):
    agent = _make_agent()
    # "你好呀" 不命中任何可服务意图 → 不进入工具路径，走默认分支（_call_ollama）
    # （mock 回复用自然语，避免含模板短语被 M6.7 代码层删除）
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "嗯嗯，我在呢，想聊点什么呀？")
    reply, _ = agent.chat("你好呀")
    assert reply == "嗯嗯，我在呢，想聊点什么呀？"


def test_tool_path_exception_falls_back(monkeypatch):
    agent = _make_agent()

    def boom(*a, **k):
        raise RuntimeError("Ollama 挂了")

    monkeypatch.setattr(agent, "_call_ollama_with_tools", boom)
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "（异常兜底回复）")
    reply, _ = agent.chat("明天下午3点提醒我喝水")
    assert reply == "（异常兜底回复）"


# ---------- WO-20260816-34（QA C03 P1）：工具路径未用工具 → 关键词路由兜底真实执行 ----------


def test_tool_no_call_schedule_still_recorded(monkeypatch):
    """WO-20260816-34：工具路径无 tool_calls 时，关键词路由兜底真实执行（日程落库副作用），
    上下文注入 [日程已添加]——修复 if/elif 死代码（原行为 add 不调用、模型假完成承诺）。"""
    agent = _make_agent()
    monkeypatch.setattr(agent, "_call_ollama_with_tools",
                        lambda *a, **k: {"content": "", "tool_calls": None})
    captured = {}

    def record(messages, max_tokens=None):
        captured["sys"] = [m["content"] for m in messages if m["role"] == "system"]
        return "好呀，明天下午3点提醒你喝水，我记下啦～"

    monkeypatch.setattr(agent, "_call_ollama", record)
    reply, _ = agent.chat("明天下午3点提醒我喝水", session_id="no-tool-sched")
    assert agent._scheduler.added == ["明天下午3点提醒我喝水"]  # 日程真实落库（副作用发生）
    assert any("[日程已添加]" in c for c in captured["sys"])    # 兜底上下文真实注入
    assert "好呀" in reply


def test_tool_no_call_web_fallback_runs(monkeypatch):
    """WO-20260816-34：工具路径无 tool_calls 时，联网搜索确定性兜底真实执行（非死代码）。"""
    agent = _make_agent()
    monkeypatch.setattr(agent, "_call_ollama_with_tools",
                        lambda *a, **k: {"content": "", "tool_calls": None})
    calls = []
    monkeypatch.setattr("app.tools.web_search.search_text",
                        lambda q, timeout=10: calls.append(q) or "1. 测试标题\n   链接：https://example.com")
    captured = {}

    def record(messages, max_tokens=None):
        captured["sys"] = [m["content"] for m in messages if m["role"] == "system"]
        return "好的～"

    monkeypatch.setattr(agent, "_call_ollama", record)
    agent.chat("帮我搜一下 DeepSeek 最新新闻", session_id="no-tool-web")
    assert calls == ["DeepSeek 最新新闻"]                          # 搜索真实执行（关键词正确提取）
    assert any("[搜索结果]" in c for c in captured["sys"])         # 搜索结果真实注入


def test_tool_no_call_obsidian_fallback_runs(monkeypatch):
    """WO-20260816-34：工具路径无 tool_calls 时，知识库确定性兜底真实执行（非死代码）。"""
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: "['30 · 项目/', 'AGENTS.md']",
    )
    try:
        agent = _make_agent()
        monkeypatch.setattr(agent, "_call_ollama_with_tools",
                            lambda *a, **k: {"content": "", "tool_calls": None})
        captured = {}

        def record(messages, max_tokens=None):
            captured["sys"] = [m["content"] for m in messages if m["role"] == "system"]
            return "好的～"

        monkeypatch.setattr(agent, "_call_ollama", record)
        agent.chat("列出知识库里 30 项目的文档", session_id="no-tool-obs")
        assert any("知识库根目录" in c and "30 · 项目" in c for c in captured["sys"])  # 兜底真实注入
    finally:
        global_registry.unregister("obsidian_vault_list")


# ---------- M6.2：防重复执行 / 历史注入 / 防假完成指引 ----------


def test_tool_used_but_stage2_fails_no_double_execute(monkeypatch):
    """M6.2：工具已执行（如已添加日程）但阶段 2 人设回复异常 → 用安全兜底文案，
    绝不回退关键词路由重复执行（scheduler.add 只调用一次）。"""
    agent = _make_agent()
    script = iter([
        {"content": "", "tool_calls": [
            {"function": {"name": "add_schedule", "arguments": {"text": "明天下午3点提醒我喝水"}}}]},
        {"content": "", "tool_calls": None},
    ])
    monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))

    def boom(*a, **k):
        raise RuntimeError("阶段2 Ollama 挂了")

    monkeypatch.setattr(agent, "_call_ollama", boom)
    reply, _ = agent.chat("明天下午3点提醒我喝水")
    assert reply == agent._TOOL_DONE_FALLBACK
    assert agent._scheduler.added == ["明天下午3点提醒我喝水"]  # 仅执行一次


def test_tool_decision_injects_recent_history(monkeypatch):
    """M6.2：阶段 1 工具决策注入最近会话历史（支持多轮指代）。"""
    agent = _make_agent()
    captured = {}

    def record(messages, tools, max_tokens=None):
        captured["stage1"] = [m for m in messages]
        return {"content": "", "tool_calls": None}

    monkeypatch.setattr(agent, "_call_ollama_with_tools", record)
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "好的～")
    # 第一轮：工具未用（record 返回无 tool_calls）→ 回退关键词路由，留下会话历史
    agent.chat("明天下午3点提醒我喝水", session_id="hist-session")
    captured.pop("stage1", None)
    # 第二轮（同会话新日程请求）：验证阶段 1 注入历史（含上一轮用户输入）
    agent.chat("后天下午4点提醒我吃药", session_id="hist-session")
    stage1 = captured.get("stage1", [])
    roles = [m["role"] for m in stage1]
    assert "user" in roles
    contents = " ".join(m.get("content", "") for m in stage1)
    assert "提醒我喝水" in contents  # 上一轮用户输入出现在阶段 1 历史中


def test_guidance_contains_no_fake_completion_rule():
    """M6.2/M6.4：工具指引含『不得未调用工具即声称已完成』防假完成规则；
    指引按候选组裁剪后，日程/规划工具的触发规则仍在对应候选组指引里。"""
    agent = _make_agent()
    g = agent._build_tool_guidance(list(TOOL_GROUPS["schedule"]) + list(TOOL_GROUPS["planning"]))
    assert "不要在没有调用工具" in g and "声称" in g
    assert "mark_schedule_done" in g and "delete_schedule" in g and "save_plan" in g


# ---------- M6.4（WO-20260816-32）：候选组裁剪 ----------


def test_tool_path_passes_only_candidate_schemas(monkeypatch):
    """M6.4：阶段 1 只带候选组 schema（不再全量 26 个），资讯意图含 web_search。"""
    agent = _make_agent()
    captured = {}

    def record(messages, tools, max_tokens=None):
        captured["names"] = [t["function"]["name"] for t in tools]
        captured["guidance"] = messages[0]["content"]
        return {"content": "", "tool_calls": None}

    monkeypatch.setattr(agent, "_call_ollama_with_tools", record)
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "好的～")
    agent.chat("帮我搜一下 DeepSeek 最新新闻", session_id="cand-session")
    assert "web_search" in captured["names"]
    assert len(captured["names"]) <= 8
    assert "add_schedule" not in captured["names"]  # 日程工具不在资讯候选里
    assert "web_search" in captured["guidance"]


def test_web_intent_deterministic_fallback(monkeypatch):
    """M6.4：工具路径未用工具（或关闭）时，『帮我搜一下 X 新闻』确定性执行 web_search，
    回复基于真实搜索结果（不编造）。"""
    object.__setattr__(CONFIG, "tool_calling_enabled", False)  # 强制走确定性兜底分支（本模块默认开启）
    agent = _make_agent()
    calls = []

    def fake_search(q, timeout=10):
        calls.append(q)
        return "1. DeepSeek 发布新版本\n   链接：https://example.com/ds\n   摘要：摘要"

    monkeypatch.setattr("app.tools.web_search.search_text", fake_search)
    monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "（搜索兜底回复）")
    # 工具路径关闭 → 直接走关键词路由链的联网搜索兜底分支
    reply, _ = agent.chat("帮我搜一下 DeepSeek 最新新闻")
    assert reply == "（搜索兜底回复）"  # 注入的是真实搜索结果，由 mock LLM 人设化
    assert calls == ["DeepSeek 最新新闻"]  # 搜索关键词正确提取且真实执行了搜索


def test_obsidian_intent_deterministic_fallback(monkeypatch):
    """M6.4：工具路径未用工具时，『列出知识库…』确定性调用 obsidian_vault_list（保底真实）。"""
    object.__setattr__(CONFIG, "tool_calling_enabled", False)  # 强制走确定性兜底分支
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: "['00 · 收件箱与想法/', '30 · 项目/', 'AGENTS.md']",
    )
    try:
        agent = _make_agent()
        monkeypatch.setattr(agent, "_call_ollama", lambda *a, **k: "（知识库兜底回复）")
        reply, _ = agent.chat("列出知识库里 30 项目的文档")
        assert reply == "（知识库兜底回复）"
    finally:
        global_registry.unregister("obsidian_vault_list")


def test_stage2_prompt_conveys_tool_results(monkeypatch):
    """WO-20260816-33 QA P1②：阶段 2 消息必须如实回显真实工具结果（可读标签 + 内容），
    结果指令在用户输入之前，且明确要求逐条念出、禁止『做不到/没查到/没有记录』式回避。"""
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: '{"files": ["AI虚拟人物/"]}',
    )
    try:
        agent = _make_agent()
        script = iter([
            {"content": "", "tool_calls": [
                {"function": {"name": "obsidian_vault_list", "arguments": {"path": "30 · 项目"}}}]},
            {"content": "", "tool_calls": None},
        ])
        captured = {}

        def record_stage2(messages, max_tokens=None):
            captured["msgs"] = messages
            return "知识库里有 AI虚拟人物 文件夹哦"  # 含真实条目，不触发 M6.7 编造重写

        monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
        monkeypatch.setattr(agent, "_call_ollama", record_stage2)
        agent.chat("列出知识库里 30 项目的文档", session_id="stage2-fidelity")
        sys_msgs = [m for m in captured["msgs"] if m["role"] == "system"]
        result_msg = sys_msgs[-1]  # 结果指令是阶段 2 追加的最后一个 system 消息
        assert "AI虚拟人物" in result_msg["content"]        # 工具结果内容真实传入阶段 2
        assert "知识库目录列表" in result_msg["content"]     # 结果以人类可读标签呈现
        # QA P1②：明确禁止『做不到/没查到/没有记录』式回避 + 要求逐条念出（如实回显）
        assert "不要说自己做不到" in result_msg["content"]
        assert "没有记录" in result_msg["content"] or "查不到" in result_msg["content"]
        assert "念出来" in result_msg["content"] and "如实" in result_msg["content"]
        # 结果指令在用户输入之前（system→user 顺序，QA 建议）
        idx_sys = captured["msgs"].index(result_msg)
        idx_user = next(i for i, m in enumerate(captured["msgs"]) if m["role"] == "user")
        assert idx_sys < idx_user
    finally:
        global_registry.unregister("obsidian_vault_list")


# ---------- WO-20260816-35（M6.5）：空结果防编造 + 工具参数精确 ----------


def test_is_empty_tool_result():
    """WO-20260816-35：空结果判定覆盖空串/空 JSON/内置『（…没有…）』文案。"""
    from app.agents.persona_agent import PersonaAgent

    empty = ["", "   ", "[]", "{}", '{"files": []}', '{"items":[]}',
             "（今天没有日程安排）", "（记忆里没有相关内容）", "（未查询到相关资料）",
             "（还没有保存过规划）", "（没有搜到相关结果）"]
    non_empty = ['{"files": ["AI虚拟人物/"]}', "已记录：日期 2026-08-17 时间 15:00 事项 喝水",
                 "3+5 = 8", "1. DeepSeek 官网\n   链接：https://deepseek.com"]
    for r in empty:
        assert PersonaAgent._is_empty_tool_result(r), f"{r!r} 应为空结果"
    for r in non_empty:
        assert not PersonaAgent._is_empty_tool_result(r), f"{r!r} 应为非空结果"


def test_stage2_empty_result_prompt_no_fabrication(monkeypatch):
    """WO-20260816-35：工具结果为空时阶段 2 进入空结果模式——提示词含『没有找到
    相关内容』硬规则与编造禁令；LLM 仍编造（如编造项目名）时由兜底话术兜住，零编造。"""
    from app.agents.persona_agent import _EMPTY_RESULT_FALLBACK
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: '{"files": []}',  # 空结果（如参数传错 path='30' 时的真实返回）
    )
    try:
        agent = _make_agent()
        script = iter([
            {"content": "", "tool_calls": [
                {"function": {"name": "obsidian_vault_list", "arguments": {"path": "30"}}}]},
            {"content": "", "tool_calls": None},
        ])
        captured = {}

        def record_stage2(messages, max_tokens=None):
            captured["msgs"] = messages
            return "我帮你列出了 30 项目下的文档：写作提升计划、睡眠改善计划、饮食调整指南…"

        monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
        monkeypatch.setattr(agent, "_call_ollama", record_stage2)
        reply, _ = agent.chat("列出知识库里 30 项目的文档", session_id="empty-result")
        sys_msgs = [m for m in captured["msgs"] if m["role"] == "system"]
        result_msg = sys_msgs[-1]
        # 空结果模式：提示词含『没有找到相关内容』+ 编造禁令
        assert "没有找到相关内容" in result_msg["content"]
        assert "禁止编造" in result_msg["content"] or "禁止列出" in result_msg["content"]
        assert "AI虚拟人物" not in result_msg["content"]  # 空结果不该有真实内容
        # 代码层兜底：LLM 编造（未说没找到）→ 固定话术兜住，回复零编造
        assert reply == _EMPTY_RESULT_FALLBACK
        assert "写作提升计划" not in reply and "睡眠改善" not in reply
    finally:
        global_registry.unregister("obsidian_vault_list")


def test_stage2_empty_result_honest_reply_kept(monkeypatch):
    """WO-20260816-35：空结果但 LLM 如实说『没找到』→ 保留如实回复（不误伤兜底）。"""
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: "[]",
    )
    try:
        agent = _make_agent()
        script = iter([
            {"content": "", "tool_calls": [
                {"function": {"name": "obsidian_vault_list", "arguments": {"path": "30"}}}]},
            {"content": "", "tool_calls": None},
        ])
        monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
        monkeypatch.setattr(agent, "_call_ollama",
                            lambda *a, **k: "嗯嗯，我这边没有找到相关内容呢，换个问法我再帮你看看～")
        reply, _ = agent.chat("列出知识库里 30 项目的文档", session_id="empty-honest")
        assert "没有找到" in reply  # 如实回复被保留（未触发兜底替换）
    finally:
        global_registry.unregister("obsidian_vault_list")


def test_candidate_schemas_obsidian_path_hint(monkeypatch):
    """WO-20260816-35：候选 schema 中 obsidian 工具的 path 参数描述含『完整目录名』
    提示（深拷贝增强，不污染注册表原 schema）。"""
    from app.plugins.registry import registry as global_registry

    schema = {"type": "function",
              "function": {"name": "obsidian_vault_list", "description": "列目录",
                           "parameters": {"type": "object",
                                          "properties": {"path": {"type": "string", "description": "目录路径"}},
                                          "required": ["path"]}}}
    global_registry.register("obsidian_vault_list", schema, lambda args: "[]")
    try:
        agent = _make_agent()
        schemas = agent._candidate_tool_schemas(["obsidian_vault_list"])
        assert len(schemas) == 1
        path_desc = schemas[0]["function"]["parameters"]["properties"]["path"]["description"]
        assert "完整目录名" in path_desc and "30 · 项目" in path_desc  # schema 描述增强生效
        # 注册表原 schema 未被污染（深拷贝）
        assert "完整目录名" not in (global_registry.schema("obsidian_vault_list")
                                    ["function"]["parameters"]["properties"]["path"]["description"])
    finally:
        global_registry.unregister("obsidian_vault_list")


# ---------- M6.6（WO-20260816-36）：知识三级兜底 + 语句自然化 ----------


class _EmptyKnowledge:
    """假知识 Agent：内置库+Wikipedia 均无结果（origin=none）。"""

    def query(self, q):
        return {"answer": "没有找到相关资料哦", "source": "", "origin": "none"}


def test_query_knowledge_web_3tier_fallback(monkeypatch):
    """M6.6：query_knowledge 内置库+Wikipedia 无结果时，自动降级 Bing 联网搜索，
    返回真实搜索结果（用户『deepseek harness是什么』曾只得到『查不到』）。"""
    agent = _make_agent(knowledge=_EmptyKnowledge())
    monkeypatch.setattr(
        "app.tools.web_search.search_text",
        lambda q, timeout=10: "1. DeepSeek Harness 文档\n   链接：https://example.com/dsh\n   摘要：DeepSeek Harness 是智能体开发框架",
    )
    out = agent._execute_tool("query_knowledge", {"question": "deepseek harness是什么"})
    assert "联网搜索结果" in out and "DeepSeek Harness" in out
    assert "example.com" in out  # 真实来源链接


def test_query_knowledge_web_fallback_empty_stays_honest(monkeypatch):
    """M6.6：三级兜底全空时仍如实『未查询到』，不编造。"""
    agent = _make_agent(knowledge=_EmptyKnowledge())
    monkeypatch.setattr("app.tools.web_search.search_text", lambda q, timeout=10: "")
    out = agent._execute_tool("query_knowledge", {"question": "完全不存在的东西xyz"})
    assert "未查询到相关资料" in out


def test_knowledge_route_3tier_fallback_injects_web(monkeypatch, tmp_path):
    """M6.6：无工具路径下知识无结果 → 注入 Bing 联网搜索结果（_route_by_keywords 三级兜底）。

    M6.8 追加（QA 最终报告）：本模块 fixture 开启工具路径，若 _call_ollama_with_tools 未 mock，
    chat() 会走真实 Ollama 工具决策（随机）——LLM 一旦调了 query_knowledge 便不落关键词路由，
    断言不稳定（连跑 3 次失败）。此处强制 mock 无 tool_calls，确定性验证路由兜底注入。
    """
    from app.memory.long_term_memory import LongTermMemory

    mem = LongTermMemory(db_path=str(tmp_path / "kb3.db"))
    agent = PersonaAgent(long_memory=mem)
    agent._knowledge = _EmptyKnowledge()
    captured = {}

    def record(messages, max_tokens=None):
        captured["sys"] = [m["content"] for m in messages if m["role"] == "system"]
        return "好的～"

    # 强制工具决策不产生 tool_calls → 确定性走关键词路由（不经真实 Ollama，避免随机失败）
    monkeypatch.setattr(agent, "_call_ollama_with_tools",
                        lambda *a, **k: {"content": "", "tool_calls": None})
    monkeypatch.setattr(agent, "_call_ollama", record)
    monkeypatch.setattr("app.tools.web_search.search_text",
                        lambda q, timeout=10: "1. DeepSeek Harness 文档\n   链接：https://example.com/dsh\n   摘要：摘要")
    try:
        agent.chat("deepseek harness是什么", session_id="kb3-tier")
        assert any("联网搜索结果" in c and "example.com" in c for c in captured["sys"])
    finally:
        mem.close()


def test_stage2_prompt_requires_natural_wording(monkeypatch):
    """M6.6：阶段 2 非空回显提示含自然化要求（不念清单、不套模板开头）。"""
    agent = _make_agent()
    script = iter([
        {"content": "", "tool_calls": [
            {"function": {"name": "query_knowledge", "arguments": {"question": "LangChain 是什么"}}}]},
        {"content": "", "tool_calls": None},
    ])
    captured = {}

    def record_stage2(messages, max_tokens=None):
        captured["msgs"] = messages
        return "好的～"

    monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
    monkeypatch.setattr(agent, "_call_ollama", record_stage2)
    agent.chat("LangChain 是什么", session_id="natural-wording")
    result_msg = [m["content"] for m in captured["msgs"] if m["role"] == "system"][-1]
    assert "不要念清单" in result_msg and "模板" in result_msg  # 自然化要求
    assert "句式有变化" in result_msg


def test_character_card_natural_wording():
    """M6.6：人设卡说话风格不再鼓励每句『我在呢』，要求安抚词轮换与句式有变化。"""
    from app.persona.character_card import CHARACTER_CARD

    speech = " ".join(CHARACTER_CARD["speech_style"])
    assert "轮换使用" in speech and "不套模板" in speech
    assert "句式有变化" in speech


# ---------- M6.7（WO-20260816-37）：非空结果防填充 + 模板句消除 ----------


def test_extract_true_items():
    """M6.7：真实条目解析——列表型 JSON 键优先，其次编号文本行。"""
    from app.agents.persona_agent import PersonaAgent

    assert PersonaAgent._extract_true_items('{"files": ["AI虚拟人物/"]}') == ["AI虚拟人物/"]
    assert PersonaAgent._extract_true_items('{"files": ["a/", "b/"]}') == ["a/", "b/"]
    assert PersonaAgent._extract_true_items(
        "1. DeepSeek 官网\n   链接：https://deepseek.com\n2. 知乎讨论\n   链接：https://zhihu.com"
    ) == ["DeepSeek 官网", "知乎讨论"]
    assert PersonaAgent._extract_true_items("已记录：日期 2026-08-17 时间 15:00 事项 喝水") == []


def test_stage2_nonempty_fabrication_rewritten(monkeypatch):
    """M6.7（QA P1）：非空结果（真实仅 1 条）阶段 2 编造多条 → 强制重写仍编造 →
    固定如实话术（只含真实条目，绝不含编造条目）。"""
    from app.agents.persona_agent import _FABRICATION_FALLBACK
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: '{"files": ["AI虚拟人物/"]}',
    )
    try:
        agent = _make_agent()
        script = iter([
            {"content": "", "tool_calls": [
                {"function": {"name": "obsidian_vault_list", "arguments": {"path": "30 · 项目"}}}]},
            {"content": "", "tool_calls": None},
        ])
        calls = []

        def record(messages, max_tokens=None):
            calls.append(messages)
            if len(calls) == 1:
                return "我帮你查到了，知识库里有以下文档：\n1. AI虚拟人物/\n2. 计算机编程基础/\n3. 心理学入门指南/"
            return "1. AI虚拟人物/\n2. 数据库管理实践/"  # 重写仍编造

        monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
        monkeypatch.setattr(agent, "_call_ollama", record)
        reply, _ = agent.chat("列出知识库里 30 项目的文档", session_id="fab-rewrite")
        assert reply == _FABRICATION_FALLBACK.format(items="AI虚拟人物/")  # 固定话术只含真实条目
        assert "计算机编程基础" not in reply and "数据库管理实践" not in reply
        assert "AI虚拟人物" in reply
        assert len(calls) == 2  # 阶段 2 一次 + 重写一次
    finally:
        global_registry.unregister("obsidian_vault_list")


def test_stage2_nonempty_honest_reply_kept(monkeypatch):
    """M6.7：非空结果且回复如实回显真实条目（列表 ≤ N）→ 保留，不触发重写。"""
    from app.plugins.registry import registry as global_registry

    global_registry.register(
        "obsidian_vault_list",
        {"type": "function", "function": {"name": "obsidian_vault_list", "description": "列目录",
                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: '{"files": ["AI虚拟人物/"]}',
    )
    try:
        agent = _make_agent()
        script = iter([
            {"content": "", "tool_calls": [
                {"function": {"name": "obsidian_vault_list", "arguments": {"path": "30 · 项目"}}}]},
            {"content": "", "tool_calls": None},
        ])
        calls = []

        def record(messages, max_tokens=None):
            calls.append(messages)
            return "知识库里有一个文件夹叫 AI虚拟人物 哦"

        monkeypatch.setattr(agent, "_call_ollama_with_tools", lambda *a, **k: next(script))
        monkeypatch.setattr(agent, "_call_ollama", record)
        reply, _ = agent.chat("列出知识库里 30 项目的文档", session_id="fab-honest")
        assert reply == "知识库里有一个文件夹叫 AI虚拟人物 哦"
        assert len(calls) == 1  # 未触发重写
    finally:
        global_registry.unregister("obsidian_vault_list")


def test_template_phrase_stripped():
    """M6.7（QA P2）：代码层删除高频模板短语（『今天过得怎么样？我在呢』等）。"""
    agent = _make_agent()
    assert "今天过得怎么样？我在呢" not in agent._strip_template_phrases(
        "你好呀，今天过得怎么样？我在呢～")
    assert "有想聊的就叫我" not in agent._strip_template_phrases(
        "嗯嗯～有想聊的就叫我哦。")
    # 非模板内容保留
    out = agent._strip_template_phrases("嗯嗯，辛苦啦，先歇一会儿吧。")
    assert "辛苦啦" in out
    # 全为模板 → 保底自然语
    assert agent._strip_template_phrases("今天过得怎么样？我在呢。")


# ---------- M6.8（WO-20260816-38）：记忆问答空记忆短路 + 条目比对宽松化 ----------


def test_memory_qa_empty_short_circuit(monkeypatch):
    """M6.8（QA P1）：空记忆库问『你记得我喜欢什么吗』→ 代码层短路固定如实话术，
    不经 LLM（7B 空记忆编造不可靠，QA 实测编造『你喜欢喝咖啡』——用户没说过）。"""
    from app.agents.persona_agent import _MEMORY_EMPTY_FALLBACK

    agent = _make_agent()  # FakeMemoryLong：retrieve_fused/recent 均空
    calls = []

    def record(*a, **k):
        calls.append(1)
        return "我记得你喜欢喝咖啡，还特别喜欢看科幻电影哦！"

    monkeypatch.setattr(agent, "_call_ollama", record)
    reply, _ = agent.chat("你记得我喜欢什么吗", session_id="mem-empty")
    assert reply == _MEMORY_EMPTY_FALLBACK
    assert not calls  # 不经 LLM（零编造保证）


class _FakeMemoryLongWithMem:
    """假记忆库：检索有内容（用户说过）。"""

    def __init__(self) -> None:
        self.items = [{"id": "1", "kind": "fact", "content": "用户喜欢喝咖啡",
                       "source": "s", "created_at": "2026-08-16 10:00:00", "score": 1.0}]

    def retrieve_fused(self, query, limit=5, days=90, **kwargs):
        return self.items

    def recent(self, limit=2):
        return []

    def add(self, kind, content, source_session=None):
        pass


def test_memory_qa_with_memory_not_shortcircuited(monkeypatch):
    """M6.8：有记忆时记忆问答正常走 LLM（自然引用记忆），不短路。"""
    agent = _make_agent(memory_long=_FakeMemoryLongWithMem())
    calls = []

    def record(messages, max_tokens=None):
        calls.append(1)
        sys_text = " ".join(m["content"] for m in messages if m["role"] == "system")
        assert "喜欢喝咖啡" in sys_text  # 真实记忆已注入
        return "我记得你喜欢喝咖啡呢～"

    monkeypatch.setattr(agent, "_call_ollama", record)
    reply, _ = agent.chat("你记得我喜欢什么吗", session_id="mem-has")
    assert calls  # 走了 LLM
    assert "咖啡" in reply


def test_item_match_lenient_normalization():
    """M6.8（QA C02-2 误判）：条目比对宽松化——空格/尾斜杠/全角/大小写变体识别为真实。"""
    agent = _make_agent()
    # 归一化
    assert agent._normalize_for_match("AI 虚拟人物 ") == "ai虚拟人物"
    assert agent._normalize_for_match("AI虚拟人物/") == "ai虚拟人物"
    assert agent._normalize_for_match("　AI虚拟人物/　") == "ai虚拟人物"
    assert agent._normalize_for_match("Ai虚拟人物") == "ai虚拟人物"
    # 空格改写变体不误判为编造
    assert not agent._stage2_has_fabrication("知识库里有 AI 虚拟人物 文件夹", ["AI虚拟人物/"])
    assert not agent._stage2_has_fabrication("知识库里有：AI 虚拟人物 / 文件夹", ["AI虚拟人物/"])
    # 真实编造仍判出
    assert agent._stage2_has_fabrication("知识库里有 计算机编程基础 文件夹", ["AI虚拟人物/"])
