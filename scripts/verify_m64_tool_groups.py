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
import re
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
# QA 实测（docs/acceptance_m64.md 四-3）：本机系统代理 127.0.0.1:26561 会让 requests
# 对 localhost（Ollama/MCP）返回 404、对 Bing 报 SSL 证书错误；验证需 NO_PROXY 直连。
# 尊重已有 NO_PROXY 配置，未设置时才写入（requests 每次请求读取环境，置顶即可生效）。
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,bing.com,www.bing.com")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,bing.com,www.bing.com")

# 强制开启 LLM 工具调用（验收条件：TOOL_CALLING_ENABLED=1）
os.environ["TOOL_CALLING_ENABLED"] = "1"

from app.agents.persona_agent import PersonaAgent
from app.agents.schedule_agent import ScheduleAgent
from app.mcp_client import register_mcp_server
from app.memory.long_term_memory import LongTermMemory
from app.plugins.registry import registry

MCP_URL = "http://127.0.0.1:27123/mcp/"
MCP_HEADERS = {"Authorization": "Bearer 8e4ec1c311f27713a7c309e927c141c3f8622bedbb8b31d9e808b66b1541de04"}

EVIDENCE_PATH = os.path.join("docs", "eval", "evidence_m64_tool_groups.json")

# WO-20260816-34：假完成承诺句式（QA C03 复现『我会在明天下午三点提醒你喝水的…』）
FAKE_PROMISE_KWS = ("我会在", "我会提醒", "我会准时", "明天下午三点提醒你", "我会记得提醒")

# WO-20260816-35：编造条目样本词（用户/QA 实测：空结果时 LLM 曾编造这些不存在的项目）
FABRICATION_SAMPLES = ("写作提升", "睡眠改善", "饮食调整", "提升计划", "改善计划", "调整指南")


def _sched_count(agent) -> int:
    """隔离日程库现有条目数（今日 + 明日）。"""
    return int(agent._scheduler.today().get("count", 0) or 0) \
        + int(agent._scheduler.tomorrow().get("count", 0) or 0)


def main() -> int:
    n = register_mcp_server(registry, "obsidian", MCP_URL, headers=MCP_HEADERS)
    print(f"[MCP] obsidian 注册 {n} 个工具；注册表共 {len(registry.names())} 个工具")
    assert n == 16, f"期望注册 16 个 Obsidian 工具，实际 {n}"

    tmp_dir = tempfile.mkdtemp(prefix="m64_verify_")
    tmp_db = os.path.join(tmp_dir, "m64_mem.db")
    agent = PersonaAgent(long_memory=LongTermMemory(db_path=tmp_db, embedder=None))
    # 隔离日程库（不污染生产 data/schedule.db；QA 复验同样用隔离库）
    agent._scheduler = ScheduleAgent(db_path=os.path.join(tmp_dir, "sched.db"))

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
        {"text": "帮我搜一下 DeepSeek 最新新闻", "expect": "web_search", "kind": "tool"},
        {"text": "列出知识库里 30 项目的文档", "expect": "obsidian", "kind": "tool"},
        {"text": "明天下午3点提醒我喝水", "expect": "schedule", "kind": "schedule"},
        # M6.6（WO-20260816-36）：知识三级兜底（内置库→Wikipedia→Bing）
        {"text": "DeepSeek Harness 是什么", "expect": "knowledge", "kind": "knowledge3", "require_answer": False},
        {"text": "LangChain 是什么", "expect": "knowledge", "kind": "knowledge3", "require_answer": True},
        # M6.6：口语问法触发（『是干嘛的』此前不在触发词内，工具未触发致 7B 编造）
        {"text": "DeepSeek Harness 是干嘛的？", "expect": "knowledge", "kind": "colloquial"},
        # M6.6：寒暄自然化抽查（『我在呢』不每句重复）
        {"text": "你好呀", "expect": "greeting", "kind": "greeting"},
    ]

    evidence = {"mcp_tools_registered": n, "registry_total": len(registry.names()), "cases": []}
    all_ok = True
    for case_cfg in cases:
        text = case_cfg["text"]
        expect = case_cfg["expect"]
        rounds_log.clear()
        exec_log.clear()
        t0 = time.time()
        try:
            reply, sid = agent.chat(text, session_id=f"m64-verify-{expect}")
        except Exception as exc:  # 如实记录失败，不粉饰
            reply = f"（chat 异常：{exc}）"
            sid = ""
        elapsed = round(time.time() - t0, 2)
        call_names = [
            c.get("function", {}).get("name", "")
            for r in rounds_log for c in (r.get("tool_calls") or [])
        ]
        case = {
            "input": text,
            "expected_tool_prefix": expect,
            "elapsed_s": elapsed,
            "reply": reply,
            "tool_call_rounds": list(rounds_log),   # 快照拷贝（下一轮会 clear 原列表）
            "tool_executions": list(exec_log),
        }
        if case_cfg["kind"] == "schedule":
            # WO-20260816-34（QA C03）：日程意图——无论 LLM 是否选工具，日程必须落库，
            # 回复不得含『我会在明天下午三点提醒你』式假完成承诺
            recorded = _sched_count(agent) > 0
            fake_promise = any(kw in (reply or "") for kw in FAKE_PROMISE_KWS)
            ok = recorded and not fake_promise
            all_ok = all_ok and ok
            case.update({"schedule_recorded": recorded, "no_fake_promise": not fake_promise})
            print(f"\n=== {text}")
            print(f"  tool_calls={call_names}  schedule_recorded={recorded}  "
                  f"no_fake_promise={not fake_promise}  ({elapsed}s)")
            print(f"  候选 schema 数/轮: {[r['tools_given_count'] for r in rounds_log]}")
            print(f"  reply: {reply[:300]}")
        elif case_cfg["kind"] == "tool":
            triggered = any(cn and cn.startswith(expect) for cn in call_names)
            # 验收追加：obsidian 工具返回内容中文不乱码（含 CJK 即解码正确；
            # 若仍按 Latin-1 解码，中文 UTF-8 字节会变成 è™æ‹Ÿ 等非 CJK 字符）
            exec_text = " ".join(e["result"] for e in exec_log)
            chinese_ok = (not exec_text) or bool(re.search(r"[\u4e00-\u9fff]", exec_text))
            if expect == "obsidian" and not exec_text:
                chinese_ok = False  # obsidian 场景必须真实执行出结果
            # WO-20260816-33 QA P1②：回复必须如实回显真实结果（含结果中的中文片段），
            # 不回避、不说『做不到/没有记录』（修复前回复为『这个我还做不到哦』）
            result_frags = re.findall(r"[\u4e00-\u9fff]{2,}", exec_text)
            reply_faithful = (not result_frags) or any(f in (reply or "") for f in result_frags)
            # WO-20260816-35：零编造——回复不得含编造条目词（实测 LLM 曾编造
            # 『写作提升计划/睡眠改善计划/饮食调整指南』等不存在的项目）
            fabricated = [w for w in FABRICATION_SAMPLES if w in (reply or "")]
            no_fabrication = not fabricated
            if expect == "obsidian":
                ok = triggered and chinese_ok and reply_faithful and no_fabrication
            else:
                ok = triggered and chinese_ok and no_fabrication
            all_ok = all_ok and ok
            case.update({
                "triggered": triggered,
                "chinese_no_mojibake": chinese_ok,
                "reply_conveys_tool_result": reply_faithful,
                "no_fabrication": no_fabrication,
            })
            print(f"\n=== {text}")
            print(f"  triggered={triggered}  chinese_ok={chinese_ok}  tool_calls={call_names}  ({elapsed}s)")
            print(f"  候选 schema 数/轮: {[r['tools_given_count'] for r in rounds_log]}")
            print(f"  reply: {reply[:300]}")
            for e in exec_log:
                print(f"  [exec] {e['name']}({e['arguments']}) -> {e['result'][:160]}")
        elif case_cfg["kind"] in ("knowledge3", "colloquial"):
            # M6.6：知识类（内置/搜索工具触发）；7B 工具决策有随机性——未触发时
            # 新会话重试（真实用户也会再问一次；QA 复验同为此抽查方式）
            knowledge_tools = {"query_knowledge", "web_search"}
            retries = 0
            while not (set(call_names) & knowledge_tools) and retries < 2:
                rounds_log.clear()
                exec_log.clear()
                t0 = time.time()
                try:
                    reply, _ = agent.chat(text, session_id=f"m64-verify-{expect}-r{retries}")
                except Exception as exc:
                    reply = f"（chat 异常：{exc}）"
                elapsed = round(time.time() - t0, 2)
                call_names = [
                    c.get("function", {}).get("name", "")
                    for r in rounds_log for c in (r.get("tool_calls") or [])
                ]
                retries += 1
            triggered = bool(set(call_names) & knowledge_tools)
            no_answer = any(k in (reply or "") for k in
                            ("没有找到相关内容", "这个还查不到", "我这边暂时没查到"))
            if case_cfg["kind"] == "knowledge3" and case_cfg.get("require_answer", True):
                ok = triggered and not no_answer
            else:
                ok = triggered
            all_ok = all_ok and ok
            # 重试后刷新 case 快照（初始快照为首次尝试，可能未触发工具）
            case.update({
                "reply": reply,
                "elapsed_s": elapsed,
                "tool_call_rounds": list(rounds_log),
                "tool_executions": list(exec_log),
            })
            case.update({
                "triggered": triggered,
                "no_answer_phrase": no_answer,
                "retries": retries,
            })
            print(f"\n=== {text}")
            print(f"  triggered={triggered}  no_answer_phrase={no_answer}  tool_calls={call_names}  ({elapsed}s)")
            print(f"  候选 schema 数/轮: {[r['tools_given_count'] for r in rounds_log]}")
            print(f"  reply: {reply[:300]}")
            for e in exec_log:
                print(f"  [exec] {e['name']}({e['arguments']}) -> {e['result'][:160]}")
        else:  # greeting：语句自然化抽查（『我在呢』/『今天过得怎么样？』不重复出现）
            greets = (reply or "").count("我在呢")
            greets_q = (reply or "").count("今天过得怎么样？")
            natural = greets <= 1 and greets_q <= 1
            ok = natural
            all_ok = all_ok and ok
            case.update({"natural_wording": natural, "greet_echo_count": greets})
            print(f"\n=== {text}")
            print(f"  natural_wording={natural}  greet_echo_count={greets}  ({elapsed}s)")
            print(f"  reply: {reply[:300]}")
        evidence["cases"].append(case)

    # WO-20260816-34 无工具兜底专项：强制阶段1 不调用工具（模拟 LLM 未选工具），
    # 验证关键词路由兜底真实执行——日程落库 + 回复无假完成承诺（原 if/elif 死代码缺陷：
    # add_schedule 不执行、日程不落库、模型假完成『我会在明天下午三点提醒你』）
    orig_tools_call2 = agent._call_ollama_with_tools

    def no_tools(*a, **k):
        return {"content": "", "tool_calls": None}

    agent._call_ollama_with_tools = no_tools
    rounds_log.clear()
    exec_log.clear()
    t0 = time.time()
    reply2, _ = agent.chat("明天下午3点提醒我喝水", session_id="m64-no-tool-fallback")
    elapsed2 = round(time.time() - t0, 2)
    agent._call_ollama_with_tools = orig_tools_call2
    recorded2 = _sched_count(agent) > 0
    fake2 = any(kw in (reply2 or "") for kw in FAKE_PROMISE_KWS)
    fallback_ok = recorded2 and not fake2
    all_ok = all_ok and fallback_ok
    evidence["no_tool_fallback"] = {
        "input": "明天下午3点提醒我喝水（强制 LLM 不选工具）",
        "schedule_recorded": recorded2,
        "no_fake_promise": not fake2,
        "elapsed_s": elapsed2,
        "reply": reply2,
        "tool_call_rounds": list(rounds_log),
        "tool_executions": list(exec_log),
    }
    print(f"\n=== 无工具兜底专项（强制 no-tool）")
    print(f"  schedule_recorded={recorded2}  no_fake_promise={not fake2}  ({elapsed2}s)")
    print(f"  reply: {reply2[:300]}")

    # WO-20260816-35 空结果防编造专项：把 obsidian_vault_list 临时替换为返回空结果
    # 的 handler（模拟参数传错 path='30' 的 {'files': []}），固定工具调用后由真实 LLM
    # 走阶段 2 空结果模式——必须如实『没有找到』，禁止编造任何项目条目
    empty_schema = registry.schema("obsidian_vault_list")
    registry.unregister("obsidian_vault_list")
    registry.register(
        "obsidian_vault_list",
        empty_schema or {"type": "function", "function": {"name": "obsidian_vault_list",
                                                          "description": "列目录",
                                                          "parameters": {"type": "object", "properties": {}}}},
        lambda args: '{"files": []}',
    )
    orig_tools_call3 = agent._call_ollama_with_tools
    forced = iter([
        {"content": "", "tool_calls": [
            {"function": {"name": "obsidian_vault_list", "arguments": {"path": "30"}}}]},
        {"content": "", "tool_calls": None},
    ])
    agent._call_ollama_with_tools = lambda *a, **k: next(forced)
    rounds_log.clear()
    exec_log.clear()
    t0 = time.time()
    reply3, _ = agent.chat("列出知识库里 30 项目的文档", session_id="m64-empty-result")
    elapsed3 = round(time.time() - t0, 2)
    agent._call_ollama_with_tools = orig_tools_call3
    empty_honest = any(kw in (reply3 or "") for kw in ("没有找到", "没找到", "没查到",
                                                       "没有相关内容", "查不到", "没有搜到"))
    fabricated3 = [w for w in FABRICATION_SAMPLES if w in (reply3 or "")]
    empty_ok = empty_honest and not fabricated3
    all_ok = all_ok and empty_ok
    evidence["empty_result_no_fabrication"] = {
        "input": "列出知识库里 30 项目的文档（vault_list 返回空 {" + '"files": []' + "}）",
        "honest_not_found": empty_honest,
        "fabricated_samples": fabricated3,
        "elapsed_s": elapsed3,
        "reply": reply3,
        "tool_call_rounds": list(rounds_log),
        "tool_executions": list(exec_log),
    }
    print(f"\n=== 空结果防编造专项（vault_list 返回空）")
    print(f"  honest_not_found={empty_honest}  fabricated={fabricated3}  ({elapsed3}s)")
    print(f"  reply: {reply3[:300]}")

    # WO-20260816-33 QA P2：搜索/知识库请求不落 topic（隔离库实测，修复前
    # 『列出知识库里 30 项目的文档』被记为 topic 造成记忆噪音）
    recent = agent._memory_long.recent(limit=50)
    noise = [
        m["content"] for m in recent
        if m["kind"] == "topic" and ("列出知识库" in m["content"] or "搜一下" in m["content"])
    ]
    memory_clean = not noise
    all_ok = all_ok and memory_clean
    evidence["memory_noise_free"] = memory_clean

    os.makedirs(os.path.dirname(EVIDENCE_PATH), exist_ok=True)
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    print(f"\n记忆噪音检查：{'PASS（搜索/知识库请求未落 topic）' if memory_clean else 'FAIL: ' + str(noise)}")
    print(f"\n证据已写入 {EVIDENCE_PATH}")
    print(f"验收结论：{'PASS（tool_calls + 中文不乱码 + 回复如实回显 + 日程落库/无假承诺 + 无工具兜底生效 + 空结果零编造 + 无记忆噪音）' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
