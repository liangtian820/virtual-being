"""能力 Agent：知识查询（M2）。

只负责"查"，不负责"说"——人设包装由人格 Agent 完成（能力 Agent 不抢人设）。
"""
from typing import Dict

from app.tools.knowledge import retrieve


class KnowledgeAgent:
    """知识查询能力 Agent：内置知识库优先，联网兜底。"""

    def query(self, query: str) -> Dict[str, str]:
        """执行知识查询，返回 {answer, source, origin}。"""
        return retrieve(query)
