"""人格 Agent 与记忆的离线单元测试（不调用 Ollama）。"""
import pytest

from app.agents.persona_agent import PersonaAgent
from app.memory.long_term_memory import LongTermMemory
from app.memory.session_memory import SessionMemory
from app.persona.character_card import CHARACTER_CARD, to_cc_v2_json
from app.persona.prompts import build_first_message, build_system_prompt


def test_build_system_prompt_contains_core_sections() -> None:
    """系统提示词应包含身份、性格、说话风格、准则等核心段落。"""
    prompt = build_system_prompt()
    assert "【身份设定】" in prompt
    assert "【性格】" in prompt
    assert "【说话风格】" in prompt
    assert "【行为准则】" in prompt
    assert CHARACTER_CARD["name"] in prompt


def test_build_system_prompt_contains_personality_items() -> None:
    """性格与风格条目应逐条注入。"""
    prompt = build_system_prompt()
    for item in CHARACTER_CARD["personality"]:
        assert item in prompt
    for item in CHARACTER_CARD["speech_style"]:
        assert item in prompt


def test_first_message() -> None:
    """开场白应来自角色卡。"""
    assert build_first_message() == CHARACTER_CARD["first_message"]


def test_to_cc_v2_json_structure() -> None:
    """导出结构应对齐 SillyTavern CC V2 规范。"""
    cc = to_cc_v2_json()
    assert cc["spec"] == "chara_card_v2"
    data = cc["data"]
    for field in ("name", "description", "personality", "scenario", "first_mes", "mes_example"):
        assert field in data, f"CC V2 缺少字段 {field}"
    assert data["name"] == CHARACTER_CARD["name"]
    assert data["first_mes"] == CHARACTER_CARD["first_message"]
    assert "<START>" in data["mes_example"]


def test_session_memory_append_and_load() -> None:
    """会话记忆应正确追加与读取。"""
    mem = SessionMemory(max_turns=2)
    mem.append("s1", "user", "你好")
    mem.append("s1", "assistant", "嗨")
    history = mem.load("s1")
    assert history == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
    ]


def test_session_memory_trim() -> None:
    """超过 max_turns 轮时应裁剪到最近轮次。"""
    mem = SessionMemory(max_turns=2)
    for i in range(5):
        mem.append("s1", "user", f"u{i}")
        mem.append("s1", "assistant", f"a{i}")
    history = mem.load("s1")
    # 保留最近 2 轮 = 4 条消息
    assert len(history) == 4
    assert history[0]["content"] == "u3"


def test_session_memory_isolated() -> None:
    """不同 session 之间互不干扰。"""
    mem = SessionMemory()
    mem.append("a", "user", "x")
    assert mem.load("b") == []


# ---------- M6 人设修复（WO-20260816-11）：能力边界 / 危机引导 / 不编造记忆 / 要点式 ----------


def test_system_prompt_contains_capability_boundary_rule() -> None:
    """P1-1（T16/R3）：系统提示词应含能力边界承诺规则（不夸大能力、不假装已完成）。"""
    prompt = build_system_prompt()
    assert "这个我还做不到哦" in prompt
    assert "我可以帮你" in prompt
    assert "绝不假装已经做完了没做过的事" in prompt


def test_system_prompt_contains_crisis_guidance_rule() -> None:
    """P1-2（T23/安全）：系统提示词应含心理危机温和引导规则（陪伴 + 专业帮助提示）。"""
    prompt = build_system_prompt()
    assert "心理援助热线" in prompt
    assert "温柔地陪着" in prompt
    assert "不敷衍、不慌张、不说教" in prompt


def test_system_prompt_contains_anti_fabrication_rule() -> None:
    """P1-3（T28）：系统提示词应含不编造记忆规则（记不清如实说 + 请用户补全）。"""
    prompt = build_system_prompt()
    assert "我这边好像没有那次的记录呢" in prompt
    assert "绝不虚构用户说过的话" in prompt


def test_system_prompt_contains_concise_style_rule() -> None:
    """P2-1（T09/T11/T12）：说话风格应含要点式简短要求。"""
    prompt = build_system_prompt()
    assert "要点式短句" in prompt
    assert "不写长篇" in prompt


def _capture_agent(tmp_path, long_memory: LongTermMemory, monkeypatch) -> tuple:
    """构造 PersonaAgent（注入隔离记忆库 + mock LLM），返回 (agent, captured)。"""
    agent = PersonaAgent(long_memory=long_memory)
    captured = {}

    def fake_call(messages, max_tokens=None):
        captured["sys"] = [m for m in messages if m["role"] == "system"]
        return "嗯嗯，我在呢。"

    monkeypatch.setattr(agent, "_call_ollama", fake_call)
    return agent, captured


def test_knowledge_injection_prompt_requires_source_and_brevity(monkeypatch, tmp_path) -> None:
    """P2-1/P2-2（T09/T12）：知识注入提示词应要求要点式简洁 + 如实标注来源。"""
    mem = LongTermMemory(db_path=str(tmp_path / "kb.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("什么是 RAG？", session_id="kb-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    assert any("知识查询结果" in m["content"] for m in sys_msgs), "应命中知识意图注入"
    knowledge_msg = next(m["content"] for m in sys_msgs if "知识查询结果" in m["content"])
    assert "150 字以内" in knowledge_msg        # P2-1 简洁要求
    assert "来源" in knowledge_msg               # P2-2 来源标注要求
    assert "内置知识库" in knowledge_msg         # 内置库命中 → 提示词带来源上下文
    assert "不编造" in knowledge_msg


def test_memory_injection_prompt_anti_fabrication(monkeypatch, tmp_path) -> None:
    """P1-3（T28）：记忆注入提示词应含"无相关记忆时不编造"引导。"""
    mem = LongTermMemory(db_path=str(tmp_path / "mem.db"))
    mem.add("fact", "用户喜欢猫", source_session="old-session")
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("猫", session_id="mem-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    assert any("长期记忆" in m["content"] for m in sys_msgs), "应注入长期记忆"
    memory_msg = next(m["content"] for m in sys_msgs if "长期记忆" in m["content"])
    assert "绝不虚构用户说过的话" in memory_msg
    assert "我这边好像没有那次的记录呢" in memory_msg


def test_empty_memory_no_memory_injection(monkeypatch, tmp_path) -> None:
    """T28 前提：空记忆库时不应注入任何记忆消息（不给 LLM 编造空间）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "empty.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("你还记得我上周跟你说的那个计划吗？", session_id="empty-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    assert not any("长期记忆" in m["content"] for m in sys_msgs)
    # 空记忆时 LLM 只能依赖系统提示词的不编造规则（test_system_prompt_contains_anti_fabrication_rule 覆盖）
    assert captured["sys"][0]["content"] == build_system_prompt()
