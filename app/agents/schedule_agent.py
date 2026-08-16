"""能力 Agent：日程备忘（M2.1）。

只负责"记"，不负责"说"——人设包装由人格 Agent 完成（能力 Agent 不抢人设）。
"""
from typing import Callable, Dict, Optional

from app.tools.schedule import DB_PATH as _DEFAULT_DB
from app.tools.schedule import add as _add
from app.tools.schedule import tomorrow as _tomorrow
from app.tools.schedule import today as _today


class ScheduleAgent:
    """日程备忘能力 Agent：提醒话术 → 结构化日程条目，SQLite 持久化 + 今日/明日查询。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB

    def add(self, text: str, llm_call: Optional[Callable[[str], str]] = None) -> Dict[str, object]:
        """添加一条日程提醒，返回 {id, date, time, event, error}。

        :param llm_call: 可选注入的 LLM 调用函数（离线测试用），默认走本地 Ollama 兜底
        """
        return _add(text, llm_call=llm_call, db_path=self._db_path)

    def today(self) -> Dict[str, object]:
        """查询今日日程，返回 {date, entries, count}。"""
        return _today(db_path=self._db_path)

    def tomorrow(self) -> Dict[str, object]:
        """查询明日日程，返回 {date, entries, count}。"""
        return _tomorrow(db_path=self._db_path)
