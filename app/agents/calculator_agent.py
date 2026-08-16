"""能力 Agent：计算（M3 起步）。

只负责"算"，不负责"说"——人设包装由人格 Agent 完成（能力 Agent 不抢人设）。
"""
from typing import Dict, Optional, Union

from app.tools.calculator import calculate as _calculate


class CalculatorAgent:
    """计算能力 Agent：安全解析四则运算与百分比。"""

    def calculate(self, expr: str) -> Dict[str, Optional[Union[float, int, str]]]:
        """执行计算，返回 {result, expression, error?}。

        - result: 计算结果（失败为 None）
        - expression: 原始算式
        - error: 成功为 None，失败为明确错误信息
        """
        return _calculate(expr)
