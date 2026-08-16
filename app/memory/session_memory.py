"""会话内记忆（M1）：按 session 保存最近 N 轮消息，简单可用。"""
from typing import Dict, List


class SessionMemory:
    """进程内会话记忆：维护每个 session 的消息历史（最近 max_turns 轮）。"""

    def __init__(self, max_turns: int = 10) -> None:
        self._max_turns = max_turns
        self._sessions: Dict[str, List[dict]] = {}

    def load(self, session_id: str) -> List[dict]:
        """取某个会话的历史消息（不含 system）。"""
        return list(self._sessions.get(session_id, []))

    def append(self, session_id: str, role: str, content: str) -> None:
        """追加一条消息并裁剪到最近 max_turns 轮（user+assistant 各计一轮）。"""
        history = self._sessions.setdefault(session_id, [])
        history.append({"role": role, "content": content})
        # 裁剪：保留最近 max_turns 轮对话（2 * max_turns 条消息）
        max_messages = self._max_turns * 2
        if len(history) > max_messages:
            del history[: len(history) - max_messages]

    def clear(self, session_id: str) -> None:
        """清空指定会话。"""
        self._sessions.pop(session_id, None)

    def all_sessions(self) -> List[str]:
        """列出所有会话 id。"""
        return list(self._sessions.keys())
