"""长期记忆（M3）离线测试：SQLite 持久化、检索、提取规则、跨会话注入。"""
import concurrent.futures
import time

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

    def fake_call(messages, max_tokens=None):
        captured["sys"] = [m for m in messages if m["role"] == "system"]
        return "嗯嗯，我记得你喜欢猫呢。"
    monkeypatch.setattr(agent, "_call_ollama", fake_call)

    reply, _ = agent.chat("猫", session_id="new-session")
    assert reply == "嗯嗯，我记得你喜欢猫呢。"
    # 注入的长期记忆出现在 system 消息中
    assert any("长期记忆" in m["content"] for m in captured["sys"])
    mem.close()


def test_cross_thread_usage(tmp_path) -> None:
    """P1 回归：主线程建 LongTermMemory，线程池线程中 retrieve/add 不抛异常。

    模拟 FastAPI 模块级 _agent 在主线程建连、同步端点跑在线程池的线程模型。
    若连接被跨线程复用（旧实现 sqlite3.connect 默认 check_same_thread=True），
    此处会抛 sqlite3.ProgrammingError。
    """
    db = str(tmp_path / "threadsafe.db")
    mem = LongTermMemory(db_path=db)

    def worker(i: int) -> int:
        mem.add("fact", f"用户喜欢猫{i}")
        mem.retrieve("猫")
        mem.add("topic", "聊过线程安全")
        return mem.count()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        # 任何 worker 内异常都会在此处冒泡，使测试失败
        list(ex.map(worker, range(8)))
    # 确定性加固（M4）：所有 worker 已 join，再轮询等待 count 连续两次读一致
    # （最长 2s），覆盖最后一个写事务落定的极窄窗口，避免全量并发下偶发误报。
    prev = -1
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        cur = mem.count()
        if cur == prev:
            break
        prev = cur
        time.sleep(0.05)
    # 严格断言（不放宽）：8 条唯一 fact + 1 条去重后的 topic = 9；
    # 若业务去重竞态仍存在（多插重复），此处稳定失败暴露问题，而非偶发。
    assert prev == 9
    mem.close()


def test_add_dedup_same_content(mem) -> None:
    """P3-1：同 (kind, content) 重复 add 不新增，返回同一 id。"""
    id1 = mem.add("fact", "用户喜欢猫")
    id2 = mem.add("fact", "用户喜欢猫")
    assert id1 == id2
    assert mem.count() == 1
    # 不同 kind 不视为重复
    id3 = mem.add("topic", "用户喜欢猫")
    assert id3 != id1
    assert mem.count() == 2


def test_fact_rule_excludes_verb_noise() -> None:
    """P3-3：'我是觉得/我在想/我在看/我是说' 等动作表述不提取为 fact。"""
    for text in ("我是觉得这个方案不错", "我在想一个问题", "我在看这个视频", "我是说真的"):
        assert not any(kind == "fact" for kind, _ in extract_memories(text)), f"误报: {text}"


def test_fact_rule_keeps_identity_and_place() -> None:
    """P3-3 收窄后：真实身份/地点陈述仍保留为 fact。"""
    hits = extract_memories("我是学生，我在上海")
    assert any(kind == "fact" and "我是学生" in content for kind, content in hits)
    assert any(kind == "fact" and "我在上海" in content for kind, content in hits)


def test_memory_persisted_when_ollama_fails(monkeypatch, tmp_path) -> None:
    """P3-4 回归：Ollama 抛异常时，本次用户事实仍应落库（不丢记忆）。"""
    db = str(tmp_path / "fail.db")
    mem = LongTermMemory(db_path=db)
    agent = PersonaAgent(long_memory=mem)

    def boom(messages, max_tokens=None):
        raise RuntimeError("Ollama 调用失败")

    monkeypatch.setattr(agent, "_call_ollama", boom)
    with pytest.raises(RuntimeError):
        agent.chat("我喜欢猫")
    hits = mem.retrieve("猫")
    assert len(hits) >= 1
    assert hits[0]["content"] == "我喜欢猫"
    mem.close()
