"""日程备忘工具（M2.1）：自然语言提醒 → 结构化日程条目 + SQLite 持久化。

设计要点（对齐能力 Agent 模式：工具层做实事，Agent 层轻封装）：
- 解析：规则优先（今天/明天/后天、早上/下午/晚上、X点X分/半点/HH:MM 等，
  离线可测、结果确定），规则无法完整覆盖时用 LLM 提取兜底（可注入 mock）；
- 持久化：SQLite（默认 `data/schedule.db`，data/ 已在 .gitignore 中），
  短连接模型（连接只在创建它的线程内使用），适配 FastAPI 线程池并发；
- 查询：今日 / 明日日程（按时间升序）；
- 失败降级：解析失败 / 落库失败一律返回结构化错误（error 字段），绝不抛异常。
"""
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

from app.tools.llm import chat

# 默认 SQLite 路径：项目根/data/schedule.db（data/ 已 gitignore）
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "schedule.db",
)

# ---------------------------------------------------------------- 规则解析

# 日期词 → 相对今天偏移（大后天在前，避免"后天"先匹配到"大后天"）
_DATE_TOKENS = (
    ("大后天", 3), ("后天", 2), ("明天", 1), ("明日", 1), ("明晚", 1),
    ("今天", 0), ("今日", 0), ("今晚", 0), ("昨天", -1), ("昨晚", -1),
)
# 日期词自带的时段语义（"明晚 7 点"= 19:00 而非 07:00）
_PERIOD_HINT = {"今晚": "晚上", "明晚": "晚上", "昨晚": "晚上"}

# 具体日期：2026年8月17日 / 2026-08-17 / 8月17日
_ISO_DATE_PATTERN = re.compile(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?")
_MD_DATE_PATTERN = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")

# 时间段词（顺序敏感：长的在前）
_PERIOD_PATTERN = re.compile(r"(凌晨|清晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|夜晚|深夜|半夜)")

# 时间：15:30 / 15：30 / 15点30分 / 15时30分
_TIME_PATTERN = re.compile(r"(\d{1,2})\s*[:：点时]\s*(\d{1,2})\s*分?")
# 时间：3点半 / 3点 / 15时
_HOUR_PATTERN = re.compile(r"(\d{1,2})\s*点半?|(\d{1,2})\s*时")

# 意图/语气词清洗
_INTENT_PREFIX_PATTERN = re.compile(
    r"^(提醒我|帮我记|帮我记住|记一下|记下|记住|记得|提醒|帮我|请帮我|请|安排|定个|设个|设置|"
    r"闹钟|定闹钟|备注|记着|给我|需要我)"
)
_TRAILING_PATTERN = re.compile(r"(哦|吧|呀|呢|哈|啦|嘛|呗|啊|～|~|！|!|。|，|,|、|\s)+$")
_SEP_PATTERN = re.compile(r"^[\s，,。、：:]+|[\s，,。、：:]+$")

_TIME_FORMAT = re.compile(r"^\d{2}:\d{2}$")


def _resolve_period(period: Optional[str], hour: int) -> int:
    """按时间段调整 24 小时制小时数（12 小时制表达 → 24 小时制）。"""
    if period in ("凌晨", "清晨"):
        return 0 if hour == 12 else hour  # 凌晨12点=0点
    if period in ("早上", "早晨", "上午", "中午"):
        return hour  # 中午11点=11:00、中午12点=12:00
    if period == "下午":
        return hour if hour >= 12 else hour + 12
    if period in ("晚上", "傍晚", "夜里", "夜晚", "深夜", "半夜"):
        if hour == 12:
            return 0  # 半夜12点=0点
        return hour if hour >= 12 else hour + 12
    return hour


def _parse_by_rules(text: str) -> Dict[str, Optional[str]]:
    """规则解析：尽量提取 {date, time, event}；缺项为 None（交 LLM 兜底）。"""
    work = text.strip()
    result: Dict[str, Optional[str]] = {"date": None, "time": None, "event": None}

    # --- 日期
    period_hint: Optional[str] = None
    for token, offset in _DATE_TOKENS:
        if token in work:
            result["date"] = (date.today() + timedelta(days=offset)).isoformat()
            period_hint = _PERIOD_HINT.get(token)
            work = work.replace(token, " ", 1)
            break
    if result["date"] is None:
        m = _ISO_DATE_PATTERN.search(work)
        if m:
            result["date"] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            work = work[:m.start()] + " " + work[m.end():]
        else:
            m = _MD_DATE_PATTERN.search(work)
            if m:
                result["date"] = f"{date.today().year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
                work = work[:m.start()] + " " + work[m.end():]

    # --- 时间（先取时间段词，再取时刻；显式时段优先于日期词自带时段）
    period: Optional[str] = None
    pm = _PERIOD_PATTERN.search(work)
    if pm:
        period = pm.group(1)
        work = work[:pm.start()] + " " + work[pm.end():]
    elif period_hint:
        period = period_hint
    tm = _TIME_PATTERN.search(work)
    if tm:
        hour, minute = int(tm.group(1)), int(tm.group(2))
        work = work[:tm.start()] + " " + work[tm.end():]
    else:
        hm = _HOUR_PATTERN.search(work)
        if hm:
            if hm.group(1) is not None:
                hour = int(hm.group(1))
                minute = 30 if "半" in hm.group(0) else 0
            else:
                hour, minute = int(hm.group(2)), 0
            work = work[:hm.start()] + " " + work[hm.end():]
        else:
            hour, minute = None, None
    if hour is not None:
        hour24 = _resolve_period(period, hour)
        result["time"] = f"{hour24:02d}:{minute:02d}"

    # --- 事项（剩余文本清洗）
    event = _SEP_PATTERN.sub("", work)
    event = _INTENT_PREFIX_PATTERN.sub("", event)
    event = _TRAILING_PATTERN.sub("", event)
    event = event.strip()
    result["event"] = event or None
    return result


# ---------------------------------------------------------------- LLM 兜底

_LLM_SYSTEM_PROMPT = (
    "你是一个日程解析助手。请从用户的提醒话术中提取结构化日程信息，"
    "只输出一个 JSON 对象，不要输出任何其他文字或代码围栏：\n"
    '{"date": "今天/明天/后天 或 YYYY-MM-DD", "time": "HH:MM（24小时制）", "event": "事项"}\n'
    "如果某字段在话术中没有出现，该字段输出 null。"
)


def _parse_llm_json(text: str) -> Dict[str, Optional[str]]:
    """解析 LLM 提取结果：容忍代码围栏/多余文本，字段缺失置 None。"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {"date": None, "time": None, "event": None}
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {"date": None, "time": None, "event": None}
    if not isinstance(obj, dict):
        return {"date": None, "time": None, "event": None}
    return {
        "date": (str(obj.get("date") or "").strip() or None),
        "time": (str(obj.get("time") or "").strip() or None),
        "event": (str(obj.get("event") or "").strip() or None),
    }


def _resolve_date(value: str) -> Optional[str]:
    """把日期表达归一化为 YYYY-MM-DD（今天/明天/后天/具体日期）；非法返回 None。"""
    value = (value or "").strip()
    if not value:
        return None
    for token, offset in _DATE_TOKENS:
        if value == token:
            return (date.today() + timedelta(days=offset)).isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _resolve_time(value: str) -> Optional[str]:
    """把时间表达归一化为 HH:MM（24 小时制）；非法返回 None。"""
    value = (value or "").strip()
    if not value:
        return None
    m = re.fullmatch(r"(\d{1,2})\s*[:：点时]\s*(\d{1,2})?\s*分?", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
    else:
        m = re.fullmatch(r"(\d{1,2})\s*点半?", value)
        if not m:
            return None
        hour = int(m.group(1))
        minute = 30 if "半" in value else 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_request(text: str, llm_call: Optional[Callable[[str], str]] = None) -> Dict[str, object]:
    """提醒话术 → 结构化日程条目 {date, time, event, error}。

    规则优先；缺项时用 LLM 兜底（未提供 llm_call 则返回部分结果 + error）。
    """
    text = (text or "").strip()
    if not text:
        return {"date": None, "time": None, "event": None, "error": "请告诉我提醒内容，比如『提醒我明天下午 3 点喝水』"}
    parsed = _parse_by_rules(text)
    missing = [k for k in ("date", "time", "event") if not parsed[k]]
    if missing:
        if llm_call is None:
            return {**parsed, "error": f"没看懂时间/事项（缺：{'、'.join(missing)}），请说得更具体一些，或提供 LLM 解析能力"}
        try:
            raw = llm_call(
                "请从以下提醒中提取日程信息，只输出一个 JSON 对象，不要输出任何其他文字或代码围栏：\n"
                '{"date": "今天/明天/后天 或 YYYY-MM-DD（话术中没出现则 null）", '
                '"time": "HH:MM（24小时制，没出现则 null）", '
                '"event": "事项（没出现则 null）"}\n'
                "提醒内容：" + text
            )
        except Exception as exc:
            return {**parsed, "error": f"日程解析失败（LLM 调用异常）：{exc}"}
        llm_fields = _parse_llm_json(raw)
        if not parsed["date"]:
            parsed["date"] = llm_fields["date"]
        if not parsed["time"]:
            parsed["time"] = llm_fields["time"]
        # 事项以 LLM 为准：规则未识别的日期碎片（如"周三"）会污染规则提取的事项，
        # 而 LLM 看到全文、能给出干净的事项；LLM 未给出时才退回规则结果
        if llm_fields["event"]:
            parsed["event"] = llm_fields["event"]
    # 归一化 + 校验
    parsed["date"] = _resolve_date(parsed["date"] or "")
    parsed["time"] = _resolve_time(parsed["time"] or "")
    parsed["event"] = (parsed["event"] or "").strip() or None
    missing = [k for k in ("date", "time", "event") if not parsed[k]]
    if missing:
        return {**parsed, "error": f"日程信息不完整（缺：{'、'.join(missing)}），请补充后再试"}
    parsed["error"] = None
    return parsed


# ---------------------------------------------------------------- 持久化

class ScheduleStore:
    """日程存储：SQLite 持久化，短连接模型（每次操作独立短连接，线程安全）。"""

    def __init__(self, db_path: str = DB_PATH) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS schedules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        time TEXT NOT NULL,
                        event TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )"""
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(date)"
                )

    def _connect(self) -> sqlite3.Connection:
        """打开短连接（调用线程内创建/使用/关闭；timeout 兜底并发写锁）。"""
        return sqlite3.connect(self._db_path, timeout=5)

    def add(self, day: str, time: str, event: str) -> int:
        """写入一条日程，返回自增 id。"""
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute(
                    "INSERT INTO schedules (date, time, event, created_at) VALUES (?,?,?,?)",
                    (day, time, event, datetime.now().isoformat(timespec="seconds")),
                )
                return int(cur.lastrowid)

    def list_on(self, day: str) -> List[Dict[str, object]]:
        """查询某天的日程（按时间升序）。"""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, time, event FROM schedules WHERE date = ? ORDER BY time, id",
                (day,),
            ).fetchall()
        return [{"id": r[0], "time": r[1], "event": r[2]} for r in rows]

    def count(self) -> int:
        """日程总数（统计/测试用）。"""
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]


def add(text: str, llm_call: Optional[Callable[[str], str]] = None,
        db_path: str = DB_PATH) -> Dict[str, object]:
    """主入口：提醒话术 → 结构化日程条目并持久化。

    返回 {"id, date, time, event, error"}：成功时 error=None 且 id 为自增 id。
    """
    parsed = parse_request(text, llm_call)
    if parsed["error"]:
        return {"id": None, "date": parsed["date"], "time": parsed["time"],
                "event": parsed["event"], "error": parsed["error"]}
    try:
        sid = ScheduleStore(db_path).add(parsed["date"], parsed["time"], parsed["event"])
    except Exception as exc:  # 落库失败：降级为结构化错误，不抛异常
        return {"id": None, "date": parsed["date"], "time": parsed["time"],
                "event": parsed["event"], "error": f"日程保存失败：{exc}"}
    return {"id": sid, "date": parsed["date"], "time": parsed["time"],
            "event": parsed["event"], "error": None}


def list_on(day: str, db_path: str = DB_PATH) -> Dict[str, object]:
    """查询指定日期（YYYY-MM-DD）的日程。"""
    entries = ScheduleStore(db_path).list_on(day)
    return {"date": day, "entries": entries, "count": len(entries)}


def today(db_path: str = DB_PATH) -> Dict[str, object]:
    """查询今日日程。"""
    return list_on(date.today().isoformat(), db_path)


def tomorrow(db_path: str = DB_PATH) -> Dict[str, object]:
    """查询明日日程。"""
    return list_on((date.today() + timedelta(days=1)).isoformat(), db_path)
