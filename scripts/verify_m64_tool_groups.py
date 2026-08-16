"""M6.4 真实对话验证（WO-20260816-32）：意图预筛候选工具组修复验收证据。

验证 qwen2.5:7b（真实 Ollama）+ Obsidian MCP（16 工具）下：
- 『帮我搜一下 DeepSeek 最新新闻』 → LLM 调用 web_search（候选组 ≤8 schema）
- 『列出知识库里 30 项目的文档』 → LLM 调用 obsidian_* 工具（真实知识库数据）

记录每个工具决策轮的 tools_given（候选 schema 数）与 LLM 实际 tool_calls，
以及工具执行的真实结果 → 证据 JSON：docs/eval/evidence_m64_tool_groups.json

运行：cd E:\\work\\virtual-being && .\\.venv\\Scripts\\python.exe scripts/verify_m64_tool_groups.py
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 控制台 GBK 无法编码部分搜索结果字符（如 \u2002），统一 UTF-8 输出（替换不可编码字符）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 强制开启 LLM 工具调用（验收条件：TOOL_CALLING_ENABLED=1）
os.environ["TOOL_CALLING_ENABLED"] = "1"

from app.agents.persona_agent import PersonaAgent
from app.mcp_client import register_mcp_server
from app.memory.long_term_memory import LongTermMemory
from app.plugins.registry import registry

MCP_URL = "http://127.0.0.1:27123/mcp/"
MCP_HEADERS = {"Authorization": "Bearer 8e4ec1c311f27713a7c309e927c141c3f8622bedbb8b31d9e808b66b1541de04"}

EVIDENCE_PATH = os.path.join("docs", "eval", "evidence_m64_tool_groups.json")


def main() -> int:
    n = register_mcp_server(registry, "obsidian", MCP_URL, headers=MCP_HEADERS)
    print(f"[MCP] obsidian 注册 {n} 个工具；注册表共 {len(registry.names())} 个工具")
    assert n == 16, f"期望注册 16 个 Obsidian 工具，实际 {n}"

    tmp_db = os.path.join(tempfile.mkdtemp(prefix="m64_mem_"), "m64_mem.db")
    agent = PersonaAgent(long_memory=LongTermMemory(db_path=tmp_db, embedder=None))

    # —— 工具调用证据采集（不改变行为，仅记录）——
    rounds_log = []          # 每轮传给 LLM 的候选 tools + LLM 返回的 tool_calls
    exec_log = []            # 实际执行的工具与真实结果

    orig_tools_call = agent._call_ollama_with_tools

    def wrapped_tools_call(messages, tools, max_tokens=None):
        resp = orig_tools_call(messages, tools, max_tokens=max_tokens)
        rounds_log.append({
            "round": len(rounds_log) + 1,
            "tools_given_count": len(tools),
            "tools_given": [t["function"]["name"] for t in tools],
            "tool_calls": resp.get("tool_calls") or [],
        })
        return resp

    agent._call_ollama_with_tools = wrapped_tools_call

    orig_exec = agent._execute_tool

    def wrapped_exec(name, arguments):
        result = orig_exec(name, arguments)
        exec_log.append({"name": name, "arguments": arguments, "result": (result or "")[:600]})
        return result

    agent._execute_tool = wrapped_exec

    cases = [
        ("帮我搜一下 DeepSeek 最新新闻", "web_search"),
        ("列出知识库里 30 项目的文档", "obsidian"),
    ]

    evidence = {"mcp_tools_registered": n, "registry_total": len(registry.names()), "cases": []}
    all_ok = True
    for text, expected_prefix in cases:
        rounds_log.clear()
        exec_log.clear()
        t0 = time.time()
        try:
            reply, sid = agent.chat(text, session_id=f"m64-verify-{expected_prefix}")
        except Exception as exc:  # 如实记录失败，不粉饰
            reply = f"（chat 异常：{exc}）"
            sid = ""
        elapsed = round(time.time() - t0, 2)
        call_names = [
            c.get("function", {}).get("name", "")
            for r in rounds_log for c in (r.get("tool_calls") or [])
        ]
        triggered = any(cn and cn.startswith(expected_prefix) for cn in call_names)
        all_ok = all_ok and triggered
        case = {
            "input": text,
            "expected_tool_prefix": expected_prefix,
            "triggered": triggered,
            "elapsed_s": elapsed,
            "reply": reply,
            "tool_call_rounds": list(rounds_log),   # 快照拷贝（下一轮会 clear 原列表）
            "tool_executions": list(exec_log),
        }
        evidence["cases"].append(case)
        print(f"\n=== {text}")
        print(f"  triggered={triggered}  tool_calls={call_names}  ({elapsed}s)")
        print(f"  候选 schema 数/轮: {[r['tools_given_count'] for r in rounds_log]}")
        print(f"  reply: {reply[:300]}")
        for e in exec_log:
            print(f"  [exec] {e['name']}({e['arguments']}) -> {e['result'][:160]}")

    os.makedirs(os.path.dirname(EVIDENCE_PATH), exist_ok=True)
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    print(f"\n证据已写入 {EVIDENCE_PATH}")
    print(f"验收结论：{'PASS（两个场景均有 tool_calls 证据）' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
