"""能力 Agent：规划助手（M2.1）。

只负责"规划"，不负责"说"——人设包装由人格 Agent 完成（能力 Agent 不抢人设）。
"""
from typing import Callable, Dict, Optional

from app.tools.planning import plan as _plan


class PlanningAgent:
    """规划能力 Agent：模糊目标 → 结构化步骤清单（LLM 生成、输出 JSON 化）。"""

    def plan(self, goal: str, llm_call: Optional[Callable[[str], str]] = None) -> Dict[str, object]:
        """执行规划，返回 {goal, steps, error, raw}。

        - goal: 目标简述
        - steps: [{"no", "title", "priority", "detail"}, ...]（带序号与预估优先级）
        - error: 成功为 None，失败为明确错误信息（不抛异常）
        - raw: LLM 原始输出（便于排查）
        :param llm_call: 可选注入的 LLM 调用函数（离线测试用），默认走本地 Ollama
        """
        return _plan(goal, llm_call=llm_call)
