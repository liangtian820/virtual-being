"""人格 Agent（M2/M3）：温柔治愈人设对话 + 意图路由到能力 Agent。

M2 编排：
- 意图路由：用户输入命中知识查询意图 → 调用能力 Agent（知识查询）→ 结果作为上下文注入，
  仍由本 Agent（LLM + 人设 prompt）用人设语气组织回复（能力 Agent 不抢人设）。
- 未命中 → 原对话逻辑。

M3 编排：
- 新增计算意图：命中 → 调用能力 Agent（CalculatorAgent）→ 计算结果注入上下文，
  人设包装仍由本 Agent 完成。
"""
import re
import uuid
from typing import List, Optional

import requests

from app.agents.calculator_agent import CalculatorAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.config import CONFIG
from app.memory.session_memory import SessionMemory
from app.persona.prompts import build_system_prompt

# 知识查询意图关键词（起步版简单规则；后续可换模型判断）
_KNOWLEDGE_PATTERN = re.compile(r"(查一下|什么是|是什么|介绍一下|查找|搜索|查询|帮我查|了解)", re.IGNORECASE)

# 计算意图强关键词（起步版简单规则；后续可换模型判断）
_CALC_STRONG_PATTERN = re.compile(
    r"(算一下|帮我算|帮我计算|算一算|算算|计算|百分之|百分比|多少的|等于多少)",
    re.IGNORECASE,
)
# 数字式子形态：数字 + 运算符（中文运算符/的/%/符号）+ 数字，如 "3 加 5"、"300 的 20%"
_CALC_FORMULA_PATTERN = re.compile(
    r"\d\s*(乘以|除以|加|减|乘|除|[+\-*/×xX]|的|%)\s*\d",
    re.IGNORECASE,
)


def is_knowledge_query(text: str) -> bool:
    """判断输入是否为知识查询意图。"""
    return bool(_KNOWLEDGE_PATTERN.search(text))


def is_calculator_query(text: str) -> bool:
    """判断输入是否为计算意图：命中强关键词（算一下/百分之…）或数字式子形态。"""
    return bool(_CALC_STRONG_PATTERN.search(text) or _CALC_FORMULA_PATTERN.search(text))


class PersonaAgent:
    """人格 Agent：人设注入 + 会话记忆 + 意图路由 + Ollama 推理。"""

    def __init__(self, memory: Optional[SessionMemory] = None, model: Optional[str] = None,
                 base_url: Optional[str] = None, temperature: Optional[float] = None) -> None:
        self._memory = memory or SessionMemory(max_turns=CONFIG.max_history_turns)
        self._model = model or CONFIG.ollama_model
        self._base_url = base_url or CONFIG.ollama_base_url
        self._temperature = temperature if temperature is not None else CONFIG.temperature
        self._system_prompt = build_system_prompt()
        self._knowledge = KnowledgeAgent()
        self._calculator = CalculatorAgent()

    def chat(self, user_input: str, session_id: Optional[str] = None) -> tuple:
        """一次对话：返回 (回复文本, session_id)。"""
        sid = session_id or uuid.uuid4().hex
        self._memory.append(sid, "user", user_input)
        messages = [{"role": "system", "content": self._system_prompt}]
        # M2 意图路由：知识查询 → 能力 Agent 取结果注入（人设包装仍由本 Agent）
        if is_knowledge_query(user_input):
            result = self._knowledge.query(user_input)
            context = f"[知识查询结果，来源：{result['source'] or '无'}]\n{result['answer']}"
            messages.append({
                "role": "system",
                "content": "用户问了知识类问题。请基于以下知识查询结果回答，"
                           "用温柔治愈的语气（符合你的人设），如实说明信息来源，不编造：\n" + context,
            })
        # M3 意图路由：计算 → 能力 Agent（CalculatorAgent）取结果注入（人设包装仍由本 Agent）
        elif is_calculator_query(user_input):
            calc = self._calculator.calculate(user_input)
            if calc["error"]:
                context = f"[计算结果：失败]\n{calc['error']}"
                messages.append({
                    "role": "system",
                    "content": "用户问了计算问题，但算式没有识别清楚。请用温柔治愈的语气（符合你的人设）"
                               "告诉用户没算出来，并提示提供更清晰的算式（如“3+5”或“300 的 20%”），"
                               "不要编造结果：\n" + context,
                })
            else:
                context = f"[计算结果]\n{calc['expression']} = {calc['result']}"
                messages.append({
                    "role": "system",
                    "content": "用户问了计算问题。请基于以下计算结果回答，用温柔治愈的语气（符合你的人设），"
                               "把算式和结果自然地说出来：\n" + context,
                })
        messages.extend(self._memory.load(sid))
        reply = self._call_ollama(messages)
        self._memory.append(sid, "assistant", reply)
        return reply, sid

    def _call_ollama(self, messages: List[dict]) -> str:
        """调用 Ollama /api/chat（非流式）。"""
        url = f"{self._base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama 调用失败（请确认 Ollama 已启动、模型 {self._model} 已拉取）: {exc}") from exc
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()

    @property
    def system_prompt(self) -> str:
        """当前系统提示词（调试用）。"""
        return self._system_prompt
