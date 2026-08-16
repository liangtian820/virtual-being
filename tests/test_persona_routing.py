"""M5.1（WO-20260816-22）意图路由离线测试：规划/日程/记忆问答。

- 意图检测：命中/不命中（不抢知识/计算分支、误判不硬路由）
- 路由注入：mock LLM，断言 system 消息含规划/日程/记忆列表等结构化上下文
- 记忆融合检索：断言 chat 走 retrieve_fused；中文口语规则追加到系统提示词
全部不调用 Ollama。
"""
import pytest

from app.agents.persona_agent import (
    PersonaAgent,
    is_memory_list_query,
    is_memory_query,
    is_planning_query,
    is_schedule_lookup,
    is_schedule_query,
)
from app.memory.long_term_memory import LongTermMemory

# ---------------------------------------------------------------- 意图检测


def test_planning_intent_hit() -> None:
    """规划意图应被识别（行动导向强词）。"""
    for text in ("帮我规划周末学做饭", "我想学 Python，怎么开始", "帮我做个计划",
                 "制定一个学习计划", "从哪开始学吉他", "帮我安排一下这个项目", "列个计划吧"):
        assert is_planning_query(text), f"{text!r} 应命中规划意图"


def test_planning_intent_miss() -> None:
    """非规划输入不应命中（不抢日程/知识/计算/日常）。"""
    for text in ("我今天有什么安排", "提醒我明天下午 3 点喝水", "你今天心情怎么样",
                 "什么是 RAG", "3 加 5 等于多少", "我喜欢猫"):
        assert not is_planning_query(text), f"{text!r} 不应命中规划意图"


def test_schedule_intent_hit() -> None:
    """日程意图应被识别（添加与查询）。"""
    for text in ("提醒我明天下午 3 点喝水", "帮我记一下明天开会", "我今天有什么安排",
                 "我的日程", "待办有哪些", "下午 3 点提醒我喝水", "明天早上 8 点叫我起床"):
        assert is_schedule_query(text), f"{text!r} 应命中日程意图"


def test_schedule_lookup_detection() -> None:
    """查询 vs 添加应可区分。"""
    assert is_schedule_lookup("我今天有什么安排")
    assert is_schedule_lookup("我的日程")
    assert is_schedule_lookup("待办有哪些")
    assert not is_schedule_lookup("提醒我明天下午 3 点喝水")
    assert not is_schedule_lookup("帮我记一下明天开会")


def test_memory_intent_hit() -> None:
    """记忆问答意图应被识别。"""
    for text in ("你记得我喜欢什么吗", "我上次说的计划", "你还记得我跟你说的吗",
                 "我的记忆有哪些", "你了解我吗", "我说过什么", "我喜欢什么来着"):
        assert is_memory_query(text), f"{text!r} 应命中记忆问答意图"


def test_memory_intent_miss() -> None:
    """非记忆问答不应命中（尤其『记得提醒我』是日程不是回忆）。"""
    assert not is_memory_query("你记得提醒我明天下午 3 点喝水")
    assert not is_memory_query("帮我规划周末学做饭")
    assert not is_memory_query("我今天有什么安排")
    assert not is_memory_query("我喜欢猫")  # 陈述事实 → 普通对话 + fact 提取，不触发问答
    assert not is_memory_query("3 加 5 等于多少")


def test_memory_list_detection() -> None:
    """记忆列示 vs 单点回忆应可区分。"""
    assert is_memory_list_query("我的记忆有哪些")
    assert is_memory_list_query("你都记得什么")
    assert not is_memory_list_query("你记得我喜欢什么吗")


# ---------------------------------------------------------------- 路由注入（mock LLM）


class _FakePlanner:
    """假规划 Agent：固定结构化输出。"""

    def plan(self, goal: str) -> dict:
        return {"goal": goal, "steps": [
            {"no": 1, "title": "准备食材", "priority": "高", "detail": "去超市买菜"},
            {"no": 2, "title": "动手做菜", "priority": "中", "detail": ""},
        ], "error": None}


class _FakeScheduler:
    """假日程 Agent：固定添加/查询结果。"""

    def add(self, text: str) -> dict:
        return {"id": 1, "date": "2026-08-17", "time": "15:00", "event": "喝水", "error": None}

    def today(self) -> dict:
        return {"date": "2026-08-16", "entries": [{"id": 1, "time": "15:00", "event": "喝水"}], "count": 1}

    def tomorrow(self) -> dict:
        return {"date": "2026-08-17", "entries": [], "count": 0}


def _capture(monkeypatch, tmp_path) -> tuple:
    """构造 PersonaAgent（注入隔离记忆库 + mock LLM），返回 (agent, store, captured)。"""
    store = LongTermMemory(db_path=str(tmp_path / "route.db"))
    agent = PersonaAgent(long_memory=store)
    captured: dict = {}

    def fake_call(messages, max_tokens=None):
        captured["sys"] = [m for m in messages if m["role"] == "system"]
        return "好的呀～"

    monkeypatch.setattr(agent, "_call_ollama", fake_call)
    return agent, store, captured


def test_planning_route_injects_steps(monkeypatch, tmp_path) -> None:
    """『帮我规划周末学做饭』→ 注入 [规划结果] 步骤清单（人设化由 LLM 完成）。"""
    agent, store, captured = _capture(monkeypatch, tmp_path)
    agent._planner = _FakePlanner()
    try:
        agent.chat("帮我规划周末学做饭", session_id="plan-session")
    finally:
        store.close()
    sys_msgs = captured["sys"]
    assert any("[规划结果]" in m["content"] for m in sys_msgs), "应命中规划意图注入"
    plan_msg = next(m["content"] for m in sys_msgs if "[规划结果]" in m["content"])
    assert "目标：帮我规划周末学做饭" in plan_msg
    assert "1. 准备食材" in plan_msg and "优先级：高" in plan_msg
    assert "不要额外编造步骤" in plan_msg


def test_planning_route_failure(monkeypatch, tmp_path) -> None:
    """规划失败 → 注入失败上下文而非编造步骤。"""
    agent, store, captured = _capture(monkeypatch, tmp_path)

    class _FailingPlanner:
        def plan(self, goal: str) -> dict:
            return {"goal": goal, "steps": [], "error": "规划生成失败：Ollama 未启动"}

    agent._planner = _FailingPlanner()
    try:
        agent.chat("帮我规划周末学做饭", session_id="plan-fail")
    finally:
        store.close()
    sys_msgs = captured["sys"]
    assert any("[规划结果：失败]" in m["content"] for m in sys_msgs)
    assert any("不要编造步骤" in m["content"] for m in sys_msgs)


def test_schedule_add_route_confirms(monkeypatch, tmp_path) -> None:
    """『明天下午 3 点提醒我喝水』→ 注入 [日程已添加] 并回显日期/时间/事项。"""
    agent, store, captured = _capture(monkeypatch, tmp_path)
    agent._scheduler = _FakeScheduler()
    try:
        agent.chat("明天下午 3 点提醒我喝水", session_id="sched-add")
    finally:
        store.close()
    sys_msgs = captured["sys"]
    assert any("[日程已添加]" in m["content"] for m in sys_msgs), "应命中日程添加注入"
    sched_msg = next(m["content"] for m in sys_msgs if "[日程已添加]" in m["content"])
    assert "日期：2026-08-17" in sched_msg
    assert "时间：15:00" in sched_msg
    assert "事项：喝水" in sched_msg
    assert "回显日期、时间、事项" in sched_msg


def test_schedule_lookup_route_lists(monkeypatch, tmp_path) -> None:
    """『我今天有什么安排』→ 注入 [今日日程] 列表。"""
    agent, store, captured = _capture(monkeypatch, tmp_path)
    agent._scheduler = _FakeScheduler()
    try:
        agent.chat("我今天有什么安排", session_id="sched-lookup")
    finally:
        store.close()
    sys_msgs = captured["sys"]
    assert any("[今日日程]" in m["content"] for m in sys_msgs), "应命中日程查询注入"
    lookup_msg = next(m["content"] for m in sys_msgs if "[今日日程]" in m["content"])
    assert "- 15:00 喝水" in lookup_msg


def test_memory_list_route_injects_memories(monkeypatch, tmp_path) -> None:
    """『我的记忆有哪些』→ 注入 [记忆列表]（摘要级）。"""
    agent, store, captured = _capture(monkeypatch, tmp_path)
    store.add("fact", "用户喜欢猫，家里养了一只橘猫", source_session="s1")
    store.add("topic", "周末想去爬山", source_session="s2")
    try:
        agent.chat("我的记忆有哪些", session_id="mem-list")
    finally:
        store.close()
    sys_msgs = captured["sys"]
    assert any("[记忆列表]" in m["content"] for m in sys_msgs), "应注入记忆列表"
    list_msg = next(m["content"] for m in sys_msgs if "[记忆列表]" in m["content"])
    assert "喜欢猫" in list_msg
    assert "爬山" in list_msg
    assert "不要编造没有的记忆" in list_msg


def test_memory_qa_route_guides_from_memories(monkeypatch, tmp_path) -> None:
    """『你记得我喜欢什么吗』→ 记忆融合检索注入 + 回忆引导指令（有相关记忆时正常走，不短路）。

    M6.9（WO-20260816-40）：记忆问答短路判定基于"相关检索 fused_memories"（M6.8 曾用
    recent 兜底，无关 topic 会让 7B 编造『你喜欢猫』）。本测试用无 embedder 的记忆库
    （关键词检索退化，『我喜欢什么吗』检索不到『用户喜欢猫』）→ monkeypatch retrieve_fused
    模拟语义命中，验证有相关记忆时不短路、注入回忆引导。
    """
    agent, store, captured = _capture(monkeypatch, tmp_path)
    store.add("fact", "用户喜欢猫，家里养了一只橘猫", source_session="s1")

    def fused_hit(query, limit=5, days=90, **kwargs):
        return [{"id": "1", "kind": "fact", "content": "用户喜欢猫，家里养了一只橘猫",
                 "source": "s", "created_at": "2026-08-16 10:00:00", "score": 1.0}]

    monkeypatch.setattr(agent._memory_long, "retrieve_fused", fused_hit)
    try:
        agent.chat("你记得我喜欢什么吗", session_id="mem-qa")
    finally:
        store.close()
    sys_msgs = captured["sys"]
    # 通用记忆注入（retrieve_fused 命中）＋ 回忆引导指令
    assert any("长期记忆" in m["content"] for m in sys_msgs)
    assert any("优先基于上面注入的长期记忆回答" in m["content"] for m in sys_msgs)
    assert any("绝不编造用户说过的话" in m["content"] for m in sys_msgs)


# ---------------------------------------------------------------- 记忆融合检索 / 中文规则


class _SpyMemory:
    """假记忆库：记录检索调用方式（验证走 retrieve_fused）。"""

    def __init__(self) -> None:
        self.calls: list = []

    def retrieve_fused(self, query: str, limit: int = 5, days: int = 90) -> list:
        self.calls.append(("fused", query))
        return [{"id": "1", "kind": "fact", "content": "用户喜欢猫",
                 "source": "s", "created_at": "2026-08-16 10:00:00", "score": 1.0}]

    def recent(self, limit: int = 2) -> list:
        return []


def test_chat_uses_fused_retrieval(monkeypatch) -> None:
    """对话记忆注入应走 retrieve_fused（语义+关键词融合，M3.5 交付）。"""
    spy = _SpyMemory()
    agent = PersonaAgent(long_memory=spy)  # type: ignore[arg-type]

    def fake_call(messages, max_tokens=None) -> str:
        return "嗯嗯，我在呢。"

    monkeypatch.setattr(agent, "_call_ollama", fake_call)
    agent.chat("今天天气不错", session_id="fused-session")
    assert spy.calls, "应调用 retrieve_fused"
    assert spy.calls[0][0] == "fused"


def test_system_prompt_contains_zh_language_rule(monkeypatch, tmp_path) -> None:
    """M5.1 中文口语优化：系统提示词应含『禁止夹英文』语言规则。"""
    store = LongTermMemory(db_path=str(tmp_path / "zh.db"))
    try:
        agent = PersonaAgent(long_memory=store)
        assert "【语言】" in agent.system_prompt
        assert "禁止夹带英文" in agent.system_prompt
        assert "简体中文口语" in agent.system_prompt
    finally:
        store.close()


def test_capability_boundary_no_longer_says_schedule_impossible(monkeypatch, tmp_path) -> None:
    """M5.1：能力边界提示不再把『记录日程』列为做不到（日程已集成）。"""
    agent, store, captured = _capture(monkeypatch, tmp_path)
    try:
        agent.chat("今天好累", session_id="boundary-m51")
    finally:
        store.close()
    sys_msgs = captured["sys"]
    hint = next(m["content"] for m in sys_msgs if "记住你的能力边界" in m["content"])
    assert "记日程" in hint or "做规划" in hint  # 新能力已列入
    assert "记录日程" not in hint  # 旧文案不再把日程列为做不到
    assert "这个我还做不到哦" in hint
