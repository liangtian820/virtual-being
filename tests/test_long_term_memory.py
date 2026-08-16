"""长期记忆（M3）离线测试：SQLite 持久化、检索、提取规则、跨会话注入。"""
import pytest

from app.memory.long_term_memory import LongTermMemory
from app.agents.persona_agent import PersonaAgent, extract_memories


@pytest.fixture()
def mem(tmp_path):
    m = LongTermMemory(db_path=str(tmp_path / "test_memory.db"))
    yield m
    m.close()


def test_add_and_retrieve(mem) -> None:
    """写入后可检索命中。"""
    mem.add("fact", "用户喜欢猫")
    results = mem.retrieve("猫")
    assert len(results) >= 1
    assert results[0]["content"] == "用户喜欢猫"


def test_retrieve_unrelated_empty(mem) -> None:
    """无关查询不返回记忆（不编造）。"""
    mem.add("fact", "用户喜欢猫")
    assert mem.retrieve("量子物理") == []


def test_recent_ordering(mem) -> None:
    """recent 返回最新记忆。"""
    mem.add("topic", "第一条")
    mem.add("topic", "第二条")
    recent = mem.recent(limit=2)
    assert recent[0]["content"] == "第二条"


def test_persistence_across_instances(tmp_path) -> None:
    """跨实例持久化（模拟跨会话/重启）。"""
    db = str(tmp_path / "persist.db")
    m1 = LongTermMemory(db_path=db)
    m1.add("fact", "用户喜欢编程")
    m1.close()
    m2 = LongTermMemory(db_path=db)
    assert m2.retrieve("编程")[0]["content"] == "用户喜欢编程"
    m2.close()


def test_fact_extraction_rule() -> None:
    """用户事实提取规则应捕获喜好/身份。"""
    hits = extract_memories("我喜欢猫，它们很可爱")
    assert any(kind == "fact" and "喜欢猫" in content for kind, content in hits)


def test_topic_extraction_rule() -> None:
    """较长陈述句应提取为话题。"""
    hits = extract_memories("我最近在研究 LangGraph 的并行分支，遇到一些状态合并的问题")
    assert any(kind == "topic" for kind, content in hits)


def test_memory_injection_in_chat(monkeypatch, tmp_path) -> None:
    """长期记忆应注入到对话消息中（monkeypatch LLM，离线）。"""
    db = str(tmp_path / "inject.db")
    mem = LongTermMemory(db_path=db)
    mem.add("fact", "用户喜欢猫", source_session="old-session")
    agent = PersonaAgent(long_memory=mem)

    captured = {}

    def fake_call(messages):
        captured["sys"] = [m for m in messages if m["role"] == "system"]
        return "嗯嗯，我记得你喜欢猫呢。"
    monkeypatch.setattr(agent, "_call_ollama", fake_call)

    reply, _ = agent.chat("猫", session_id="new-session")
    assert reply == "嗯嗯，我记得你喜欢猫呢。"
    # 注入的长期记忆出现在 system 消息中
    assert any("长期记忆" in m["content"] for m in captured["sys"])
    mem.close()
