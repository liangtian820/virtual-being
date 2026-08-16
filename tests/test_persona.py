"""人格 Agent 与记忆的离线单元测试（不调用 Ollama）。"""
import pytest

from app.agents.persona_agent import PersonaAgent, is_crisis_query
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
        sys_msgs = [m for m in messages if m["role"] == "system"]
        captured.setdefault("sys_all", []).append(sys_msgs)  # 累积每次调用的 system 消息
        captured["sys"] = sys_msgs
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
    assert "回答末尾明确附上引用来源" in knowledge_msg   # M6 v2：完整引用句式


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


def test_empty_memory_injects_anti_fabrication_hint(monkeypatch, tmp_path) -> None:
    """M6 v2（T28）+ M6.8（WO-20260816-38）：空记忆库记忆问答 → 代码层短路固定如实话术
    （『没有那次的记录』），不经 LLM——比提示词注入更硬，零编造保证。"""
    from app.agents.persona_agent import _MEMORY_EMPTY_FALLBACK

    mem = LongTermMemory(db_path=str(tmp_path / "empty.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        reply, _ = agent.chat("你还记得我上周跟你说的那个计划吗？", session_id="empty-session")
    finally:
        mem.close()
    # M6.8：空记忆问答短路固定话术（7B 空记忆编造不可靠，代码层兜底，不经 LLM）
    assert reply == _MEMORY_EMPTY_FALLBACK
    assert "没有那次的记录" in reply
    assert not captured.get("sys"), "空记忆问答不应经 LLM（无回忆引导注入）"


def test_capability_boundary_hint_injected_on_normal_chat(monkeypatch, tmp_path) -> None:
    """M6 v2（T16 代码层）：普通对话路径应注入能力边界强提示（超范围请求 → 做不到+说明边界+转向可做之事）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "boundary.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("帮我把桌面这 100 个文件批量重命名", session_id="boundary-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    assert any("记住你的能力边界" in m["content"] for m in sys_msgs), "普通对话应注入能力边界强提示"
    hint = next(m["content"] for m in sys_msgs if "记住你的能力边界" in m["content"])
    assert "这个我还做不到哦" in hint
    assert "操作 TA 的电脑" in hint
    assert "绝不假装已经做完了没做过的事" in hint


def test_capability_boundary_hint_not_injected_on_capability_routes(monkeypatch, tmp_path) -> None:
    """M6 v2：知识/计算意图分支不应注入能力边界强提示（避免干扰能力分支注入）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "routes.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("什么是 RAG？", session_id="kb2-session")
        agent.chat("3 加 5 等于多少", session_id="calc2-session")
    finally:
        mem.close()
    kb_sys, calc_sys = captured["sys_all"][0], captured["sys_all"][1]
    assert not any("记住你的能力边界" in m["content"] for m in kb_sys)
    assert not any("记住你的能力边界" in m["content"] for m in calc_sys)
    assert any("知识查询结果" in m["content"] for m in kb_sys)
    assert any("计算结果" in m["content"] for m in calc_sys)


def test_system_prompt_contains_example_dialogue_few_shot() -> None:
    """M6 v2（T23/T16/T07 few-shot）：系统提示词应渲染【对话示例】段落，含危机/能力边界/焦虑示例。"""
    prompt = build_system_prompt()
    assert "【对话示例】" in prompt
    # 危机 few-shot（T23）：温柔陪伴 + 专业求助引导
    assert "拨打心理援助热线" in prompt
    # 能力边界 few-shot（T16/R3）
    assert "帮我删掉电脑里的这个文件夹" in prompt
    # 焦虑建议 few-shot（T07）：具体可执行动作
    assert "深呼吸" in prompt
    assert "提前把自我介绍练两遍" in prompt


# ---------- M6 v3 决胜轮（WO-20260816-15）：危机分支 / 无结果禁来源 / 长度约束 / R8 ----------


class _FakeNoResultKnowledge:
    """假知识 Agent：模拟查询无结果（origin=none），用于离线测试 T10 无结果分支。"""

    def query(self, query: str) -> dict:
        return {
            "answer": "没有找到相关资料哦，换个问法试试，或者让我换个方式找找。",
            "source": "",
            "origin": "none",
        }


def test_is_crisis_query_keywords() -> None:
    """危机关键词检测：命中（安全优先）与未命中。"""
    assert is_crisis_query("活着好没意思，感觉撑不下去了")
    assert is_crisis_query("我不想活了")
    assert is_crisis_query("我最近有伤害自己的想法")
    assert is_crisis_query("真想自杀算了")
    assert not is_crisis_query("今天天气不错")
    assert not is_crisis_query("帮我算一下 3 加 5")
    assert not is_crisis_query("什么是 RAG？")


def test_crisis_branch_injected_on_crisis_keywords(monkeypatch, tmp_path) -> None:
    """M6 v3（T23/P1-2，总控批准）：危机关键词命中时强制注入危机引导句式（陪伴+专业求助渠道）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "crisis.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("活着好没意思，感觉撑不下去了", session_id="crisis-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    # "12356" 只在危机分支注入消息中出现（system prompt 的 rules/few-shot 不含），用作唯一标识
    assert any("12356" in m["content"] for m in sys_msgs), "危机分支应注入求助渠道"
    crisis_msg = next(m["content"] for m in sys_msgs if "12356" in m["content"])
    assert "找信任的家人或朋友聊聊" in crisis_msg
    assert "你很重要" in crisis_msg
    assert "心理援助热线" in crisis_msg
    # 危机分支不注入普通对话的长度/能力边界提示（不干扰陪伴）
    assert not any("记住你的能力边界" in m["content"] for m in sys_msgs)
    assert not any("说完就停下来" in m["content"] for m in sys_msgs)


def test_crisis_branch_not_injected_on_normal_chat(monkeypatch, tmp_path) -> None:
    """M6 v3：危机分支只影响危机关键词命中路径；普通对话不注入危机引导。"""
    mem = LongTermMemory(db_path=str(tmp_path / "normal.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("今天天气不错", session_id="normal-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    assert not any("12356" in m["content"] for m in sys_msgs)
    # 普通对话仍注入长度提示与能力边界提示（回归护栏）
    assert any("说完就停下来" in m["content"] for m in sys_msgs)
    assert any("记住你的能力边界" in m["content"] for m in sys_msgs)


def test_knowledge_no_result_no_source_template(monkeypatch, tmp_path) -> None:
    """M6 v3（T10/P1-1，R8）：知识查询无结果时注入『没查到』模板并禁止来源标注。"""
    mem = LongTermMemory(db_path=str(tmp_path / "nor.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    agent._knowledge = _FakeNoResultKnowledge()
    # M6.6（WO-20260816-36）：知识无结果会触发三级兜底 Bing 搜索——离线测试 mock 无结果
    monkeypatch.setattr("app.tools.web_search.search_text",
                        lambda q, timeout=10: "（联网搜索没有查到结果）")
    try:
        agent.chat("帮我查一下最新的量子计算机进展", session_id="nor-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    assert any("知识查询结果" in m["content"] for m in sys_msgs)
    nor_msg = next(m["content"] for m in sys_msgs if "知识查询结果" in m["content"])
    assert "我这边暂时没查到呢" in nor_msg
    assert "不要标注任何来源" in nor_msg
    # 无结果分支不含来源句式（只在有结果分支出现）
    assert "回答末尾明确附上引用来源" not in nor_msg


def test_length_hint_injected_on_normal_chat(monkeypatch, tmp_path) -> None:
    """M6 v3（T03/T08）：普通对话路径注入长度约束提示（日常 60 字/情绪 80 字）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "len.db"))
    agent, captured = _capture_agent(tmp_path, mem, monkeypatch)
    try:
        agent.chat("这周项目超忙，天天加班，好累", session_id="len-session")
    finally:
        mem.close()
    sys_msgs = captured["sys"]
    assert any("60 字内" in m["content"] for m in sys_msgs)
    assert any("80 字内" in m["content"] for m in sys_msgs)


def test_system_prompt_contains_no_fake_source_rule() -> None:
    """M6 v3（R8）：系统提示词应含『不编造来源』规则。"""
    prompt = build_system_prompt()
    assert "不编造来源" in prompt
    assert "绝不虚构来源" in prompt
