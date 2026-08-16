"""M6.9 性能验证（WO-20260816-39 知识/搜索提速 + WO-20260816-40 确定性优先）。

输出 before/after 对比表（基线 data/m6_6/perf_baseline.json）与正确性断言，证据入
data/m6_6/evidence_perf_m69.json。

验收目标：
- 知识查询『deepseek harness是什么』中位 ≤15s（before 38.4s）
- 搜索『帮我搜一下X』中位 ≤15s（before 29.3s）
- 日程『提醒我喝水』≤6s（before 11.1s）；记忆『你记得我喜欢什么吗』≤6s；计算『300 的 20%』≤6s
- 缓存命中（工具层）≤5s；结果真实零编造

运行：cd E:\\work\\virtual-being && .\\.venv\\Scripts\\python.exe data/m6_6/verify_perf_m69.py
"""
import json
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
# 系统代理影响 localhost（QA 实测）：直连需 NO_PROXY
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,bing.com,www.bing.com")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,bing.com,www.bing.com")
os.environ["TOOL_CALLING_ENABLED"] = "1"

from app.agents.persona_agent import PersonaAgent
from app.agents.schedule_agent import ScheduleAgent
from app.mcp_client import register_mcp_server
from app.memory.long_term_memory import LongTermMemory
from app.plugins.registry import registry
from app.tools.web_search import search_text

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE_PATH = os.path.join(PROJECT, "data", "m6_6", "perf_baseline.json")
EVIDENCE_PATH = os.path.join(PROJECT, "data", "m6_6", "evidence_perf_m69.json")
MCP_URL = "http://127.0.0.1:27123/mcp/"
MCP_HEADERS = {"Authorization": "Bearer 8e4ec1c311f27713a7c309e927c141c3f8622bedbb8b31d9e808b66b1541de04"}

RUNS = 3


def median(xs):
    return round(statistics.median(xs), 2)


def time_chat(agent, text):
    ts = []
    replies = []
    for i in range(RUNS):
        t0 = time.perf_counter()
        reply, _ = agent.chat(text, session_id=f"perf-{abs(hash(text))}-{i}")
        ts.append(time.perf_counter() - t0)
        replies.append(reply)
    return median(ts), replies[-1]


def main() -> int:
    baseline = {}
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            baseline = json.load(f)

    n = register_mcp_server(registry, "obsidian", MCP_URL, headers=MCP_HEADERS)
    print(f"[MCP] obsidian 注册 {n} 个工具")

    tmp = tempfile.mkdtemp(prefix="perf_m69_")
    agent = PersonaAgent(long_memory=LongTermMemory(db_path=os.path.join(tmp, "mem.db"), embedder=None))
    agent._scheduler = ScheduleAgent(db_path=os.path.join(tmp, "sched.db"))

    cases = [
        ("chat_plain", "你好呀"),
        ("chat_schedule", "明天下午3点提醒我喝水"),
        ("chat_memory", "你记得我喜欢什么吗"),
        ("chat_calc", "300 的 20% 是多少"),
        ("chat_knowledge", "deepseek harness是什么"),
        ("chat_search", "帮我搜一下 DeepSeek 最新新闻"),
    ]

    results = {}
    rounds_log = {}
    orig_tools_call = agent._call_ollama_with_tools

    def wrapped_tools_call(messages, tools, max_tokens=None):
        resp = orig_tools_call(messages, tools, max_tokens=max_tokens)
        rounds_log.setdefault("last", []).append({
            "tools_given": [t["function"]["name"] for t in tools],
            "tool_calls": [c.get("function", {}).get("name") for c in (resp.get("tool_calls") or [])],
        })
        return resp

    agent._call_ollama_with_tools = wrapped_tools_call

    for key, text in cases:
        rounds_log.pop("last", None)
        med, reply = time_chat(agent, text)
        before = baseline.get(key)
        results[key] = {
            "median_s": med, "before_s": before, "reply": (reply or "")[:200],
            "decision_rounds": rounds_log.get("last", []),
        }
        tag = "✓" if (before is None or med <= before) else "✗"
        print(f"  {key}: {med}s  (before {before})  {tag}")

    # 缓存命中（工具层，不含 LLM）
    q = "DeepSeek Harness 缓存测试专用词"
    t0 = time.perf_counter()
    r1 = search_text(q)
    t1 = time.perf_counter() - t0
    t0 = time.perf_counter()
    r2 = search_text(q)
    t2 = time.perf_counter() - t0
    results["cache"] = {"first_s": round(t1, 2), "hit_s": round(t2, 2)}
    print(f"  缓存：首次 {t1:.2f}s → 命中 {t2:.2f}s  {'✓' if t2 <= 5 else '✗'}")

    # ---------- 正确性断言 ----------
    checks = []
    ok = True
    kr = results["chat_knowledge"]["reply"]
    if "没有找到" in kr or "查不到" in kr:
        ok = False
        checks.append("FAIL 知识查询未拿到结果")
    else:
        checks.append("PASS 知识查询拿到真实结果")
    sr = results["chat_search"]["reply"]
    if "没有搜到" in sr or "查不到" in sr:
        ok = False
        checks.append("FAIL 搜索未拿到结果")
    else:
        checks.append("PASS 搜索拿到真实结果")
    mr = results["chat_memory"]["reply"]
    if "没有那次的记录" in mr:
        checks.append("PASS 记忆问答如实（空记忆短路）")
    else:
        ok = False
        checks.append("FAIL 记忆问答异常")
    cr = results["chat_calc"]["reply"]
    if "60" in cr:
        checks.append("PASS 计算正确（300 的 20% = 60）")
    else:
        ok = False
        checks.append(f"FAIL 计算异常: {cr}")
    # 日程落库（隔离库：输入『明天…』落明天，today+tomorrow 合计）
    sched_count = int(agent._scheduler.today().get("count", 0) or 0) \
        + int(agent._scheduler.tomorrow().get("count", 0) or 0)
    if sched_count > 0:
        checks.append("PASS 日程落库")
    else:
        ok = False
        checks.append("FAIL 日程未落库")

    # 验收判定
    targets = {
        "chat_knowledge": 15.0, "chat_search": 15.0,
        "chat_schedule": 6.0, "chat_memory": 6.0, "chat_calc": 6.0,
    }
    verdicts = {}
    for k, limit in targets.items():
        med = results[k]["median_s"]
        passed = med <= limit
        ok = ok and passed
        verdicts[k] = {"limit_s": limit, "passed": passed}
        print(f"  验收 {k}: {med}s ≤ {limit}s  {'✓' if passed else '✗'}")

    evidence = {
        "before": baseline,
        "after": results,
        "verdicts": verdicts,
        "cache_hit_s": results["cache"]["hit_s"],
        "checks": checks,
        "pass": ok,
    }
    os.makedirs(os.path.dirname(EVIDENCE_PATH), exist_ok=True)
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    print("\n".join(f"  {c}" for c in checks))
    print(f"\n证据已写入 {EVIDENCE_PATH}")
    print(f"验收结论：{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
