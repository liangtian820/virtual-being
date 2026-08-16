"""长期记忆（M3）离线测试：SQLite 持久化、检索、提取规则、跨会话注入。"""
import concurrent.futures
import time

import pytest

from app.memory.long_term_memory import LongTermMemory
from app.agents.persona_agent import PersonaAgent, extract_memories
from app.memory.embeddings import (
    EmbeddingError,
    cosine_similarity,
    pack_vector,
    segment,
    unpack_vector,
)


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


# ---------- P3-4（WO-20260816-17）：记忆提取噪音治理——请求/计算/提问类不落 topic ----------


@pytest.mark.parametrize("text", [
    # QA 一致性测试集（docs/eval/run_consistency_eval.py CASES）中的请求/计算类输入
    "什么是 RAG？",                                           # T09 知识提问
    "帮我查一下最新的量子计算机进展",                         # T10 知识请求
    "查一下怎么缓解失眠吧，最近都睡不好，好烦",               # T11 知识请求
    "3 加 5 等于多少",                                        # T13 计算
    "300 的 20% 是多少",                                      # T14 计算
    "帮我算一下，那个数加上那个数（输入含糊、无数值）",       # T15 计算/请求
    "帮我把桌面这 100 个文件批量重命名",                      # T16 能力请求
    "帮我骂一下我那个同事，写几句难听的话",                   # T21 越界请求
    "你的电话号码是多少？给我一个",                           # T24 请求
])
def test_request_calc_inputs_not_extracted(text: str) -> None:
    """P3-4：QA 测试集请求/计算类输入不应提取任何记忆（不落 topic/fact）。"""
    assert extract_memories(text) == [], f"应无记忆提取: {text}"


def test_genuine_user_statements_still_extracted() -> None:
    """P3-4 回归：真实用户陈述（忙/累/情绪/兴趣）仍提取为 topic，不误伤。"""
    for text in (
        "这周项目超忙，天天加班，好累",
        "我今天好累，什么都不想做",
        "我把事情搞砸了，都是我的错",
        "下周面试，好紧张，怕搞砸",
        "我最近在研究 LangGraph 的并行分支，遇到一些状态合并的问题",
    ):
        hits = extract_memories(text)
        assert any(kind == "topic" for kind, content in hits), f"应保留 topic: {text}"


def test_facts_still_extracted_after_noise_fix() -> None:
    """P3-4 回归：正常事实（喜好/身份/职业）仍提取为 fact，不误伤。"""
    for text, keyword in (
        ("我喜欢猫，它们很可爱", "喜欢猫"),
        ("我是一名程序员，工作三年了", "我是一名程序员"),
        ("我讨厌香菜", "讨厌香菜"),
        ("我叫小明", "我叫小明"),
        ("我住在上海", "我住在上海"),
    ):
        hits = extract_memories(text)
        assert any(kind == "fact" and keyword in content for kind, content in hits), f"应提取 fact: {text}"


def test_request_calc_chat_does_not_pollute_memory(monkeypatch, tmp_path) -> None:
    """P3-4 端到端：请求/计算输入经 chat 全链路也不落库（记忆库保持干净）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "noise.db"))
    agent = PersonaAgent(long_memory=mem)

    def fake_call(messages, max_tokens=None):
        return "嗯嗯～"

    monkeypatch.setattr(agent, "_call_ollama", fake_call)
    try:
        for text in ("帮我查一下最新的量子计算机进展", "300 的 20% 是多少",
                     "帮我把桌面这 100 个文件批量重命名"):
            agent.chat(text, session_id="noise-session")
    finally:
        mem.close()
    assert mem.count() == 0, f"请求/计算输入不应落库，实际 {mem.count()} 条"


# ---------- M3.5（WO-20260816-19）：记忆向量化——jieba 分词 + 语义检索 + 融合 ----------


class _FakeEmbedder:
    """确定性伪 embedding（离线测试，不依赖 Ollama）：字符 bag 叠加，
    共享字符多的文本余弦高，模拟语义相近文本向量接近。"""

    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    def embed(self, text: str) -> list:
        v = [0.0] * self._dim
        for ch in text:
            if ch.strip():
                v[ord(ch) % self._dim] += 1.0
        return v


class _BrokenEmbedder:
    """模拟 embedding 服务不可用（抛 EmbeddingError）。"""

    def embed(self, text: str) -> list:
        raise EmbeddingError("embedding 服务不可用（测试）")


def test_jieba_segmentation() -> None:
    """M3.5：jieba 中文分词应切出语义词（含单字词），过滤标点/空白。"""
    words = segment("我家猫很可爱，我喜欢猫")
    assert "猫" in words
    assert "可爱" in words
    assert "喜欢" in words
    assert "，" not in words
    assert all(w.strip() for w in words)


def test_cosine_similarity_basic() -> None:
    """M3.5：余弦相似度基础（相同=1、正交=0、不等长=0 不崩）。"""
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0


def test_vector_pack_roundtrip() -> None:
    """M3.5：向量 BLOB 打包/解包往返一致（float32）。"""
    vec = [0.1, -0.2, 0.3, 0.0]
    assert unpack_vector(pack_vector(vec)) == pytest.approx(vec)


def test_retrieve_semantic_hits_similar_fact(tmp_path) -> None:
    """M3.5：语义检索——近义 query 命中已存事实（『我喜欢猫』→『用户喜欢猫』）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "sem.db"), embedder=_FakeEmbedder())
    mem.add("fact", "用户喜欢猫")
    try:
        hits = mem.retrieve_semantic("我喜欢猫", k=3)
    finally:
        mem.close()
    assert any(h["content"] == "用户喜欢猫" for h in hits), f"语义应命中: {hits}"


def test_retrieve_semantic_unrelated_empty(tmp_path) -> None:
    """M3.5：语义检索——无关 query 低于阈值不返回。"""
    mem = LongTermMemory(db_path=str(tmp_path / "sem2.db"), embedder=_FakeEmbedder())
    mem.add("fact", "用户喜欢猫")
    try:
        hits = mem.retrieve_semantic("量子计算很复杂", k=3)
    finally:
        mem.close()
    assert all(h["content"] != "用户喜欢猫" for h in hits)


def test_old_data_lazy_backfill(tmp_path) -> None:
    """M3.5：旧数据兼容——无向量旧记忆经 lazy 补向量后可语义命中，不崩。"""
    db = str(tmp_path / "old.db")
    mem0 = LongTermMemory(db_path=db)  # 无 embedder：旧数据无向量
    mem0.add("fact", "用户喜欢猫")
    mem0.close()
    mem = LongTermMemory(db_path=db, embedder=_FakeEmbedder(), auto_backfill=True)
    try:
        hits = mem.retrieve_semantic("我喜欢猫", k=3)
    finally:
        mem.close()
    assert any(h["content"] == "用户喜欢猫" for h in hits)


def test_retrieve_semantic_without_embedder_returns_empty(tmp_path) -> None:
    """M3.5：无 embedder 时语义检索返回空且不崩（离线兜底）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "noemb.db"))
    mem.add("fact", "用户喜欢猫")
    try:
        assert mem.retrieve_semantic("猫", k=3) == []
    finally:
        mem.close()


def test_embedder_failure_does_not_break_add(tmp_path) -> None:
    """M3.5：embedding 服务失败不阻断记忆落库（记忆仍可关键词检索）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "brk.db"), embedder=_BrokenEmbedder())
    mem.add("fact", "用户喜欢猫")
    try:
        assert mem.count() == 1
        assert mem.retrieve("猫")[0]["content"] == "用户喜欢猫"
        assert mem.retrieve_semantic("猫", k=3) == []  # 语义降级为空，不崩
    finally:
        mem.close()


def test_fused_retrieval_merges_semantic_and_keyword(tmp_path) -> None:
    """M3.5：检索融合——语义+关键词合并排序，语义命中优先。"""
    mem = LongTermMemory(db_path=str(tmp_path / "fuse.db"), embedder=_FakeEmbedder())
    mem.add("fact", "用户喜欢猫")
    mem.add("topic", "最近在研究 LangGraph 的并行分支")
    try:
        hits = mem.retrieve_fused("我喜欢猫", limit=3)
    finally:
        mem.close()
    assert hits[0]["content"] == "用户喜欢猫", f"语义高分应排首: {hits}"


def test_fused_retrieval_falls_back_to_keyword_without_embedder(tmp_path) -> None:
    """M3.5：无 embedder 时融合检索退化为纯关键词（行为与 retrieve 一致）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "fuse2.db"))
    mem.add("fact", "用户喜欢猫")
    try:
        hits = mem.retrieve_fused("猫", limit=3)
    finally:
        mem.close()
    assert hits[0]["content"] == "用户喜欢猫"


def test_vector_persisted_across_instances(tmp_path) -> None:
    """M3.5：向量持久化——重建实例后语义检索直接命中（无需重新生成已存向量）。"""
    db = str(tmp_path / "persist_vec.db")
    m1 = LongTermMemory(db_path=db, embedder=_FakeEmbedder())
    m1.add("fact", "用户喜欢猫")
    m1.close()
    m2 = LongTermMemory(db_path=db, embedder=_FakeEmbedder())
    try:
        hits = m2.retrieve_semantic("我喜欢猫", k=3)
    finally:
        m2.close()
    assert any(h["content"] == "用户喜欢猫" for h in hits)


def test_keyword_retrieve_behavior_unchanged(tmp_path) -> None:
    """M3.5 回归：既有关键词检索接口与行为不变（返回结构含 id/kind/content/score）。"""
    mem = LongTermMemory(db_path=str(tmp_path / "kw.db"))
    mem.add("fact", "用户喜欢猫")
    try:
        hits = mem.retrieve("猫", limit=3)
    finally:
        mem.close()
    assert len(hits) >= 1
    assert hits[0]["content"] == "用户喜欢猫"
    for key in ("id", "kind", "content", "score", "created_at"):
        assert key in hits[0]
