"""M5.1（WO-20260816-22）真实 Ollama 证据脚本（对话实测）。

- 意图检测：is_planning_query / is_schedule_query / is_memory_query（真实文本）
- 记忆向量检索：Ollama all-minilm 真实 embedding，retrieve_fused 语义命中证据
- 人格对话实测：qwen2.5:7b（文本链路）——规划 / 日程添加回显 / 日程查询 / 记忆问答 / 记忆列示
- 记忆 API：GET /memory、DELETE /memory?confirm=1（TestClient）

全部使用临时 SQLite（不污染 data/），embedder 指向真实 Ollama。
输出：data/m5_1/evidence_m51.json
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 项目根入 sys.path（脚本以 python scripts/m51_evidence.py 运行时需要）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import app.main as main_module
from app.agents.persona_agent import (
    PersonaAgent,
    is_memory_list_query,
    is_memory_query,
    is_planning_query,
    is_schedule_lookup,
    is_schedule_query,
)
from app.agents.schedule_agent import ScheduleAgent
from app.config import CONFIG
from app.memory.embeddings import OllamaEmbedder
from app.memory.long_term_memory import LongTermMemory

OUT = Path("data/m5_1/evidence_m51.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

evidence = {
    "task": "WO-20260816-22",
    "milestone": "M5.1 intent routing + memory QA + zh prompt",
    "models": {"llm": CONFIG.ollama_model, "embedding": CONFIG.embedding_model},
    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    "sections": {},
}


def section(name: str) -> None:
    evidence["sections"][name] = {"at": time.strftime("%H:%M:%S")}
    print(f"\n===== {name} =====")


def rec(name: str, key: str, value) -> None:
    evidence["sections"][name][key] = value


# ---------------------------------------------------------------- 1. 意图检测
section("intent_detection")
intent_cases = {
    "帮我规划周末学做饭": ("planning", is_planning_query),
    "我想学 Python，怎么开始": ("planning", is_planning_query),
    "明天下午3点提醒我喝水": ("schedule_add", is_schedule_query),
    "明天早上 8 点叫我起床": ("schedule_add", is_schedule_query),
    "我今天有什么安排": ("schedule_lookup", is_schedule_query),
    "你记得我喜欢什么吗": ("memory_qa", is_memory_query),
    "我上次说的计划": ("memory_qa", is_memory_query),
    "我的记忆有哪些": ("memory_list", is_memory_query),
}
intent_results = {}
for text, (label, fn) in intent_cases.items():
    hit = bool(fn(text))
    intent_results[text] = {"expected": label, "hit": hit}
    print(f"  {text!r} -> {label}: {'HIT' if hit else 'miss'}")
rec("intent_detection", "cases", intent_results)
rec("intent_detection", "schedule_lookup_明天下午3点提醒我喝水", is_schedule_lookup("明天下午3点提醒我喝水"))
rec("intent_detection", "memory_list_我的记忆有哪些", is_memory_list_query("我的记忆有哪些"))

# ---------------------------------------------------------------- 2. 向量检索
section("vector_retrieval")
tmp = tempfile.mkdtemp(prefix="m51-evidence-")
mem_db = os.path.join(tmp, "mem.db")
embedder = OllamaEmbedder(base_url=CONFIG.embedding_base_url, model=CONFIG.embedding_model,
                          timeout=CONFIG.embedding_timeout)
store = LongTermMemory(db_path=mem_db, embedder=embedder)
facts = [
    ("fact", "用户喜欢猫，家里养了一只橘猫", "s-fact-1"),
    ("topic", "用户上次说周末想去爬山", "s-topic-1"),
    ("fact", "用户想学做饭，想从家常菜开始", "s-fact-2"),
]
for kind, content, src in facts:
    store.add(kind, content, source_session=src)

# 语义查询：与"猫"无关键词重叠，验证纯语义命中（真实 all-minilm 余弦）
t0 = time.perf_counter()
hits = store.retrieve_fused("你记得我喜欢什么动物吗", limit=3)
sem_elapsed = round(time.perf_counter() - t0, 2)
rec("vector_retrieval", "fused_hits_for_动物", [
    {"content": h["content"], "score": round(float(h["score"]), 3)} for h in hits
])
rec("vector_retrieval", "semantic_elapsed_s", sem_elapsed)
print(f"  retrieve_fused('你记得我喜欢什么动物吗') = {[h['content'] for h in hits]} ({sem_elapsed}s)")

# 验证 embedding 真实落库（memory_embeddings 表有向量）
import sqlite3
with sqlite3.connect(mem_db) as conn:
    emb_count = conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
    mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
rec("vector_retrieval", "memories_in_db", mem_count)
rec("vector_retrieval", "embeddings_in_db", emb_count)
print(f"  memories={mem_count}, embeddings={emb_count}")

# ---------------------------------------------------------------- 3. 人格对话实测（qwen2.5:7b）
section("persona_dialogue")
agent = PersonaAgent(long_memory=store)
# 日程走临时库（不污染 data/schedule.db）
agent._scheduler = ScheduleAgent(db_path=os.path.join(tmp, "sched.db"))

chat_cases = [
    ("planning", "帮我规划周末学做饭"),
    ("schedule_add", "明天下午3点提醒我喝水"),
    ("schedule_lookup", "我今天有什么安排"),
    ("memory_qa", "你记得我喜欢什么吗"),
    ("memory_list", "我的记忆有哪些"),
]
chat_results = {}
for label, text in chat_cases:
    t0 = time.perf_counter()
    try:
        reply, sid = agent.chat(text, session_id=f"m51-{label}")
        elapsed = round(time.perf_counter() - t0, 2)
        chat_results[label] = {"input": text, "reply": reply, "elapsed_s": elapsed}
        print(f"  [{label}] {text}\n    -> {reply}  ({elapsed}s)")
    except Exception as exc:  # noqa: BLE001
        chat_results[label] = {"input": text, "error": str(exc)}
        print(f"  [{label}] ERROR: {exc}")
rec("persona_dialogue", "cases", chat_results)
store.close()

# ---------------------------------------------------------------- 4. 记忆 API
section("memory_api")
api_store = LongTermMemory(db_path=os.path.join(tmp, "api.db"))
api_store.add("fact", "用户喜欢猫", source_session="api-s1")
api_store.add("topic", "用户周末想去爬山", source_session="api-s2")


class _FakeAgentWithMemory:
    def __init__(self, s):
        self._memory_long = s

    def chat(self, user_input, session_id=None):
        return "ok", session_id or "sid"


main_module._agent = _FakeAgentWithMemory(api_store)
client = TestClient(main_module.app)
get_resp = client.get("/memory")
rec("memory_api", "GET_status", get_resp.status_code)
rec("memory_api", "GET_body", get_resp.json())
print(f"  GET /memory -> {get_resp.status_code} {get_resp.json()}")

no_confirm = client.delete("/memory")
rec("memory_api", "DELETE_no_confirm_status", no_confirm.status_code)
rec("memory_api", "DELETE_no_confirm_detail", no_confirm.json().get("detail"))
print(f"  DELETE /memory (无 confirm) -> {no_confirm.status_code}")

del_resp = client.delete("/memory", params={"confirm": "1"})
rec("memory_api", "DELETE_confirm_status", del_resp.status_code)
rec("memory_api", "DELETE_confirm_body", del_resp.json())
print(f"  DELETE /memory?confirm=1 -> {del_resp.status_code} {del_resp.json()}")
after = client.get("/memory")
rec("memory_api", "GET_after_clear", after.json())
print(f"  GET /memory (清空后) -> {after.json()}")
api_store.close()

# ---------------------------------------------------------------- 汇总
evidence["summary"] = {
    "llm_reply_samples": {k: v.get("reply", v.get("error")) for k, v in chat_results.items()},
    "vector_retrieval_semantic_hit": bool(hits) and hits[0]["content"].startswith("用户喜欢猫"),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(evidence, f, ensure_ascii=False, indent=2)
print(f"\n证据已写入 {OUT.resolve()}")
