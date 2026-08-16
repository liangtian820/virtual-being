"""能力 Agent：日程备忘（M2.1 + M2.2）。

只负责"记"，不负责"说"——人设包装由人格 Agent 完成（能力 Agent 不抢人设）。
M2.2（WO-20260816-23）新增：周几解析 / 删除 / 完成标记 / 重复提醒。
"""
from datetime import datetime
from typing import Callable, Dict, Optional

from app.tools.schedule import DB_PATH as _DEFAULT_DB
from app.tools.schedule import add as _add
from app.tools.schedule import delete as _delete
from app.tools.schedule import mark_done as _mark_done
from app.tools.schedule import parse_weekday as _parse_weekday
from app.tools.schedule import tomorrow as _tomorrow
from app.tools.schedule import today as _today


class ScheduleAgent:
    """日程备忘能力 Agent：提醒话术 → 结构化日程条目，SQLite 持久化 + 查询/删除/完成/重复。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB

    def add(self, text: str, llm_call: Optional[Callable[[str], str]] = None,
            now: Optional[datetime] = None) -> Dict[str, object]:
        """添加一条日程提醒，返回 {id, date, time, event, repeat, error}。

        :param llm_call: 可选注入的 LLM 调用函数（离线测试用），默认走本地 Ollama 兜底
        :param now: 可选注入当前时间（离线测试用，影响重复提醒起始日期），默认 datetime.now()
        """
        return _add(text, llm_call=llm_call, db_path=self._db_path, now=now)

    def today(self) -> Dict[str, object]:
        """查询今日日程，返回 {date, entries, count}。"""
        return _today(db_path=self._db_path)

    def tomorrow(self) -> Dict[str, object]:
        """查询明日日程，返回 {date, entries, count}。"""
        return _tomorrow(db_path=self._db_path)

    def parse_weekday(self, text: str, now: Optional[datetime] = None) -> Optional[str]:
        """周几表达 → 最近一个该周几的日期（YYYY-MM-DD）；无周几表达返回 None。

        跨周边界由 datetime 处理（『周三』周五说 → 下周三；周三当天 → 今天）。
        :param now: 可选注入当前时间（离线测试用），默认 datetime.now()
        """
        return _parse_weekday(text, now=now)

    def delete(self, text: str, now: Optional[datetime] = None) -> Dict[str, object]:
        """删除提醒：『删掉明天下午的提醒』→ 返回 {deleted, entries, error}。

        :param now: 可选注入当前时间（离线测试用，解析周几/相对日期用）
        """
        return _delete(text, db_path=self._db_path, now=now)

    def mark_done(self, text: str, now: Optional[datetime] = None) -> Dict[str, object]:
        """完成标记：『今天喝水的提醒完成了』→ 返回 {updated, entries, error}。

        :param now: 可选注入当前时间（离线测试用，解析周几/相对日期用）
        """
        return _mark_done(text, db_path=self._db_path, now=now)
