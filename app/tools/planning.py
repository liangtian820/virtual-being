"""规划工具（M2.1）：模糊目标 → 结构化步骤清单。

设计要点（对齐能力 Agent 模式：工具层做实事，Agent 层轻封装）：
- LLM 生成：构造固定 JSON 结构的提示词（few-shot 示例保证结构稳定），输出严格 JSON；
- 容错解析：容忍 Markdown 代码围栏 / 前后多余文本 / 序号错乱 / 优先级写法不一
  （高/中/低、1/2/3、high/medium/low 等统一归一化），并自动重排步骤序号；
- 失败降级：解析失败或 LLM 调用失败一律返回结构化错误（error 字段），绝不抛异常、
  绝不编造步骤；
- 可测试性：`plan(goal, llm_call=...)` 支持注入 LLM 调用函数，离线测试 mock 它即可。
"""
import json
import re
from typing import Callable, Dict, List, Optional

from app.tools.llm import chat

# 规划系统提示词：只允许输出一个 JSON 对象，结构固定，便于下游路由/前端直接消费
SYSTEM_PROMPT = (
    "你是一位温柔耐心的规划助手，负责把用户的模糊目标拆解成清晰、可执行的步骤清单。\n"
    "要求：\n"
    "1. 只输出一个 JSON 对象，不要输出任何其他文字、注释或 Markdown 代码围栏；\n"
    "2. JSON 结构固定为：\n"
    '{"goal": "目标简述", "steps": [{"no": 1, "title": "步骤标题", '
    '"priority": "高", "detail": "一句话说明怎么做"}]}\n'
    "3. steps 数量 3~8 个，按先后顺序排列，no 从 1 开始连续编号；\n"
    "4. priority 只能是 \"高\" / \"中\" / \"低\" 三者之一，表示该步骤的优先级；\n"
    "5. 全程使用简体中文，steps 不能为空。"
)

# 优先级归一化：LLM 可能输出中文/数字/英文，统一映射为 高/中/低
_PRIORITY_HIGH = {"高", "高优先级", "最高", "紧急", "high", "1"}
_PRIORITY_LOW = {"低", "低优先级", "最低", "low", "3"}

# 代码围栏（```json ... ``` 等）
_FENCE_PATTERN = re.compile(r"^```[a-zA-Z]*\s*$|^```\s*$", re.MULTILINE)
# Markdown 有序列表行：1. / 1、/ 1）等
_NUMBERED_PATTERN = re.compile(r"^\s*\d+\s*[.、．)]\s*(.+)$")
# Markdown 无序列表行
_BULLET_PATTERN = re.compile(r"^\s*[-*•]\s*(.+)$")


def _normalize_priority(value: object) -> str:
    """把各种优先级写法归一化为 高/中/低（无法识别一律归"中"，不报错）。"""
    if isinstance(value, int):
        return "高" if value == 1 else ("低" if value == 3 else "中")
    text = str(value or "").strip().lower()
    if text in _PRIORITY_HIGH:
        return "高"
    if text in _PRIORITY_LOW:
        return "低"
    return "中"


def _normalize_steps(raw_steps: object) -> List[Dict[str, str]]:
    """校验/修复 steps：跳过无效项、重排序号、归一化优先级、补齐 detail。"""
    steps: List[Dict[str, str]] = []
    if not isinstance(raw_steps, list):
        return steps
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        detail = str(item.get("detail") or "").strip()
        steps.append({
            "no": len(steps) + 1,
            "title": title,
            "priority": _normalize_priority(item.get("priority")),
            "detail": detail,
        })
    return steps


def _strip_code_fence(text: str) -> str:
    """去掉 ```json ... ``` 代码围栏与首尾空行。"""
    return _FENCE_PATTERN.sub("", text).strip()


def _try_json(text: str) -> Optional[dict]:
    """从文本中提取 JSON 对象（容忍前后多余文本）；失败返回 None。"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _parse_markdown_steps(text: str) -> List[Dict[str, str]]:
    """降级解析：Markdown 有序/无序列表 → 步骤清单（无优先级信息时默认"中"）。

    行内若含"："，前半作标题、后半作 detail（如"安装环境：下载并安装 Python"）。
    """
    steps: List[Dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _NUMBERED_PATTERN.match(line) or _BULLET_PATTERN.match(line)
        if not m:
            continue
        title = m.group(1).strip()
        if not title:
            continue
        detail = ""
        if "：" in title:
            title, _, detail = title.partition("：")
            title, detail = title.strip(), detail.strip()
        steps.append({"no": len(steps) + 1, "title": title, "priority": "中", "detail": detail})
    return steps


def _guess_goal(text: str) -> str:
    """降级解析时猜目标：取第一条不是步骤列表行的非空行。"""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _NUMBERED_PATTERN.match(line) or _BULLET_PATTERN.match(line):
            continue
        return line[:60]
    return ""


def parse_plan(text: str, fallback_goal: str = "") -> Dict[str, object]:
    """把 LLM 输出文本解析为结构化计划。

    返回 {"goal", "steps", "error"}：
    - goal: 目标简述（str）
    - steps: [{"no": int, "title": str, "priority": "高|中|低", "detail": str}, ...]
    - error: 解析失败时为原因描述，成功为 None
    """
    text = (text or "").strip()
    if not text:
        return {"goal": fallback_goal, "steps": [], "error": "规划助手没有返回内容"}
    cleaned = _strip_code_fence(text)
    obj = _try_json(cleaned)
    if obj is not None:
        steps = _normalize_steps(obj.get("steps"))
        goal = str(obj.get("goal") or fallback_goal or "").strip()
        if steps:
            return {"goal": goal, "steps": steps, "error": None}
    md_steps = _parse_markdown_steps(cleaned)
    if md_steps:
        return {"goal": fallback_goal or _guess_goal(cleaned), "steps": md_steps, "error": None}
    return {"goal": fallback_goal, "steps": [], "error": "无法解析为结构化计划（LLM 输出不符合 JSON/清单格式）"}


def _build_user_prompt(goal: str) -> str:
    """构造规划请求（含 JSON 示例，提高 LLM 输出结构稳定性）。"""
    example = (
        '示例（严格按此结构，仅作格式参考，不要照搬内容）：\n'
        '{"goal": "学会 Python 编程", "steps": ['
        '{"no": 1, "title": "安装 Python 环境", "priority": "高", "detail": "下载并安装 Python，配置 PATH"}, '
        '{"no": 2, "title": "学习基础语法", "priority": "高", "detail": "变量/循环/函数等核心语法"}]}\n'
    )
    return f"请为以下目标制定执行步骤：\n目标：{goal}\n\n{example}只输出 JSON。"


def _default_llm_call(prompt: str) -> str:
    """默认 LLM 调用：走本地 Ollama（可被 llm_call 参数替换以便测试）。"""
    return chat(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        temperature=0.3,
    )


def plan(goal: str, llm_call: Optional[Callable[[str], str]] = None) -> Dict[str, object]:
    """主入口：模糊目标 → 结构化步骤清单。

    返回 {"goal", "steps", "error", "raw"}：
    - steps: [{"no", "title", "priority", "detail"}, ...]
    - error: 失败为原因描述（空目标 / LLM 调用失败 / 解析失败），成功为 None
    - raw: LLM 原始输出（便于排查；未调用时为 ""）
    """
    goal = (goal or "").strip()
    if not goal:
        return {"goal": "", "steps": [], "error": "请先告诉我一个目标，比如『我想学 Python』", "raw": ""}
    caller = llm_call or _default_llm_call
    try:
        raw = caller(_build_user_prompt(goal))
    except Exception as exc:  # LLM 调用失败：降级为结构化错误，不抛异常
        return {"goal": goal, "steps": [], "error": f"规划生成失败：{exc}", "raw": ""}
    result = parse_plan(raw, fallback_goal=goal)
    result["raw"] = raw
    return result
