"""日程备忘工具（M2.1 + M2.2）：自然语言提醒 → 结构化日程条目 + SQLite 持久化。

M2.2（WO-20260816-23）新增能力：
- 周几解析：『周三下午吃药』→ 最近一个周三的具体日期（datetime 处理跨周边界）；
- 删除：『删掉明天下午的提醒』→ 按 日期/时段/事项 匹配删除；
- 完成标记：『今天喝水的提醒完成了』→ 标记 done=1；
- 重复提醒：『每天早上提醒我喝水』→ repeat=daily/weekly/monthly，起始日期=下次触发日。

设计要点（对齐能力 Agent 模式：工具层做实事，Agent 层轻封装）：
- 解析：规则优先（今天/明天/后天、早上/下午/晚上、X点X分/半点/HH:MM、周几、每天/每周 等，
  离线可测、结果确定），规则无法完整覆盖时用 LLM 提取兜底（可注入 mock）；
- 持久化：SQLite（默认 `data/schedule.db`，data/ 已在 .gitignore 中），
  短连接模型（连接只在创建它的线程内使用），适配 FastAPI 线程池并发；
- 查询：今日 / 明日日程（按时间升序）；
- 失败降级：解析失败 / 落库失败一律返回结构化错误（error 字段），绝不抛异常。
"""
import calendar
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

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

# ---------------------------------------------------------------- 周几 / 重复（M2.2）

# 周几表达：周三 / 星期三 / 礼拜三，可带 每 / 下 / 这 / 本 前缀（"每周三""下周三""这周三"）。
# 前缀与"周X"之间允许夹"星期/礼拜"（"每个星期三"），正则回溯可正确切分。
_WEEKDAY_PATTERN = re.compile(
    r"((?:每|大?下|这|本)(?:个)?(?:周|星期|礼拜)?)?(?:周|星期|礼拜)([一二三四五六日天])"
)
_WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

# 重复提醒：每天/每日/天天 → daily；每周/每星期 → weekly；每月/每个月 → monthly
_REPEAT_DAILY_PATTERN = re.compile(r"每(?:天|日)|天天")
_REPEAT_WEEKLY_PATTERN = re.compile(r"每(?:个)?(?:星期|周)")
_REPEAT_MONTHLY_PATTERN = re.compile(r"每(?:个)?月")
_REPEAT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (_REPEAT_MONTHLY_PATTERN, "monthly"),
    (_REPEAT_WEEKLY_PATTERN, "weekly"),
    (_REPEAT_DAILY_PATTERN, "daily"),
]

# 删除/完成目标的意图词（在文本任意位置剔除一次；顺序敏感：长的在前）
_DELETE_MARKER_PATTERN = re.compile(r"(删掉|删除|帮我删(?:掉)?|取消|移除|去掉|清掉|清空)")
_DONE_MARKER_PATTERN = re.compile(
    r"(标记(?:为)?(?:已)?完成|已完成|完成了|完成|做完(?:了)?|搞定(?:了)?|已做完|好了)"
)
_TARGET_TRAILING_PATTERN = re.compile(
    r"(的提醒|提醒|的任务|的日程|日程|的事情|的事|的安排|安排|事项)?[\s，,。、！!？?]*$"
)

# 时段 → 小时区间（半开区间 [start, end)，用于"删掉下午的提醒"这类模糊匹配）
_PERIOD_RANGE = {
    "凌晨": (0, 8), "清晨": (0, 8),
    "早上": (6, 11), "早晨": (6, 11),
    "上午": (8, 12), "中午": (11, 14),
    "下午": (12, 19),
    "傍晚": (17, 21), "晚上": (17, 24), "夜里": (19, 24),
    "夜晚": (19, 24), "深夜": (22, 24), "半夜": (22, 24),
}


def _resolve_weekday(rel: Optional[str], day_char: str, base: date) -> Optional[date]:
    """周几 → 具体日期。

    - 无前缀 / "每"：今天起最近一次（今天是该周几则今天；否则跨周边界找下一次）；
    - "下"：下一个 ISO 周的该周几；
    - "这"/"本"：当前 ISO 周的该周几（可能已过）。
    """
    target = _WEEKDAY_INDEX.get(day_char)
    if target is None:
        return None
    week_start = base - timedelta(days=base.weekday())  # 本周一
    if rel and rel.startswith("下"):
        return week_start + timedelta(days=7 + target)
    if rel and (rel.startswith("这") or rel.startswith("本")):
        return week_start + timedelta(days=target)
    # 最近一次（今天起算；(target - weekday) % 7 自动处理跨周边界）
    return base + timedelta(days=(target - base.weekday()) % 7)


def parse_weekday(text: str, now: Optional[datetime] = None) -> Optional[str]:
    """周几表达 → 最近一个该周几的日期（YYYY-MM-DD）；没有周几表达返回 None。

    - 『周三』：今天起最近一个周三（今天是周三则今天，否则跨周边界到下周）；
    - 『下周三』：下周的周三；『这周三/本周三』：本周的周三；
    - 『每周三』：最近一个周三（重复提醒的起始日期，repeat 由调用方另行判定）。
    :param now: 注入当前时间（离线测试用），默认 datetime.now()
    """
    m = _WEEKDAY_PATTERN.search((text or "").strip())
    if not m:
        return None
    day = _resolve_weekday(m.group(1), m.group(2), (now or datetime.now()).date())
    return day.isoformat() if day else None


def _parse_repeat(text: str) -> Optional[str]:
    """识别重复提醒（每天/每周/每月），未识别返回 None。"""
    for pat, value in _REPEAT_PATTERNS:
        if pat.search(text):
            return value
    return None


def _next_occurrence_date(base: date, repeat: str) -> date:
    """重复提醒的下一次触发日期（base 的该次已过时）。"""
    if repeat == "daily":
        return base + timedelta(days=1)
    if repeat == "weekly":
        return base + timedelta(days=7)
    if repeat == "monthly":
        month = base.month + 1
        year = base.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(base.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    return base


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


def _parse_by_rules(text: str, now: Optional[datetime] = None) -> Dict[str, Optional[str]]:
    """规则解析：尽量提取 {date, time, event, repeat}；缺项为 None（交 LLM 兜底）。"""
    work = text.strip()
    now = now or datetime.now()
    base_date = now.date()
    result: Dict[str, Optional[str]] = {"date": None, "time": None, "event": None, "repeat": None}

    # --- 重复（M2.2）：先识别并记录；"每周X"前缀会被下方周几解析整体消费
    result["repeat"] = _parse_repeat(work)

    # --- 日期
    period_hint: Optional[str] = None
    for token, offset in _DATE_TOKENS:
        if token in work:
            result["date"] = (base_date + timedelta(days=offset)).isoformat()
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
                result["date"] = f"{base_date.year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
                work = work[:m.start()] + " " + work[m.end():]
    if result["date"] is None:
        wm = _WEEKDAY_PATTERN.search(work)
        if wm:
            day = _resolve_weekday(wm.group(1), wm.group(2), base_date)
            if day is not None:
                result["date"] = day.isoformat()
                work = work[:wm.start()] + " " + work[wm.end():]
    # 重复提醒且无明确日期：先占位今天，时间解析后按下一次触发推进
    if result["date"] is None and result["repeat"] is not None:
        result["date"] = base_date.isoformat()

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

    # 重复提醒：起始日期 = 下次触发日（今天该时刻已过 → 推下一次）
    if result["repeat"] is not None and result["date"] and result["time"]:
        if result["date"] == base_date.isoformat() and result["time"] <= now.strftime("%H:%M"):
            result["date"] = _next_occurrence_date(base_date, result["repeat"]).isoformat()

    # 重复词若未被周几解析消费（如"每天"），从文本剔除，避免污染事项
    if result["repeat"] is not None:
        for pat, _ in _REPEAT_PATTERNS:
            rm = pat.search(work)
            if rm:
                work = work[:rm.start()] + " " + work[rm.end():]
                break

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


def parse_request(text: str, llm_call: Optional[Callable[[str], str]] = None,
                  now: Optional[datetime] = None) -> Dict[str, object]:
    """提醒话术 → 结构化日程条目 {date, time, event, repeat, error}。

    规则优先；缺项时用 LLM 兜底（未提供 llm_call 则返回部分结果 + error）。
    :param now: 注入当前时间（离线测试用），默认 datetime.now()
    """
    text = (text or "").strip()
    if not text:
        return {"date": None, "time": None, "event": None, "repeat": None,
                "error": "请告诉我提醒内容，比如『提醒我明天下午 3 点喝水』"}
    parsed = _parse_by_rules(text, now=now)
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


# ---------------------------------------------------------------- 删除 / 完成目标解析（M2.2）

def _clean_target_text(text: str, done: bool) -> str:
    """剔除删除/完成意图词（任意位置一次），并去掉句首"帮我/把"等衬词。"""
    work = (text or "").strip()
    work = re.sub(r"^帮我把|^帮我|^把", "", work)
    m = (_DONE_MARKER_PATTERN if done else _DELETE_MARKER_PATTERN).search(work)
    if m:
        work = work[:m.start()] + " " + work[m.end():]
    return work


def _resolve_target(text: str, done: bool,
                    now: Optional[datetime] = None) -> Dict[str, object]:
    """解析 删除/完成 的目标：{date, time, time_range, event, error}。

    - date: YYYY-MM-DD（今天/明天/后天/周几/具体日期），必填；
    - time: 精确时刻 HH:MM（可选，精确匹配）；
    - time_range: 时段小时区间 (start, end)（可选，"下午"这类模糊时段）；
    - event: 事项子串（可选，LIKE 匹配）。
    """
    work = _clean_target_text(text, done=done)
    if not work:
        return {"date": None, "time": None, "time_range": None, "event": None,
                "error": "请告诉我要处理哪条提醒，比如『删掉明天下午的提醒』或『今天喝水的提醒完成了』"}
    base_date = (now or datetime.now()).date()

    # --- 日期（相对词 → 周几 → 具体日期）
    date_val: Optional[str] = None
    for token, offset in _DATE_TOKENS:
        if token in work:
            date_val = (base_date + timedelta(days=offset)).isoformat()
            work = work.replace(token, " ", 1)
            break
    if date_val is None:
        m = _ISO_DATE_PATTERN.search(work)
        if m:
            date_val = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            work = work[:m.start()] + " " + work[m.end():]
        else:
            m = _MD_DATE_PATTERN.search(work)
            if m:
                date_val = f"{base_date.year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
                work = work[:m.start()] + " " + work[m.end():]
    if date_val is None:
        wm = _WEEKDAY_PATTERN.search(work)
        if wm:
            day = _resolve_weekday(wm.group(1), wm.group(2), base_date)
            if day is not None:
                date_val = day.isoformat()
                work = work[:wm.start()] + " " + work[wm.end():]
    if date_val is None:
        return {"date": None, "time": None, "time_range": None, "event": None,
                "error": "没听懂要处理哪天的提醒，请带上日期，比如『删掉明天下午的提醒』"}

    # --- 时间（精确时刻 或 时段区间）
    time_val: Optional[str] = None
    time_range: Optional[Tuple[int, int]] = None
    period: Optional[str] = None
    pm = _PERIOD_PATTERN.search(work)
    if pm:
        period = pm.group(1)
        work = work[:pm.start()] + " " + work[pm.end():]
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
        time_val = f"{hour24:02d}:{minute:02d}"
        time_range = (hour24, hour24 + 1)
    elif period:
        time_range = _PERIOD_RANGE.get(period)

    # --- 事项（剩余文本清洗：去掉"的提醒/提醒/任务"等尾缀与句首"的"衬字）
    event = _SEP_PATTERN.sub("", work)
    event = _TARGET_TRAILING_PATTERN.sub("", event)
    event = re.sub(r"^[的]+", "", event)
    event = event.strip() or None
    return {"date": date_val, "time": time_val, "time_range": time_range,
            "event": event, "error": None}


# ---------------------------------------------------------------- 持久化

class ScheduleStore:
    """日程存储：SQLite 持久化，短连接模型（每次操作独立短连接，线程安全）。

    M2.2 起表结构含 done（完成标记）与 repeat（重复类型）列，老库自动迁移。
    """

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
                        created_at TEXT NOT NULL,
                        done INTEGER NOT NULL DEFAULT 0,
                        repeat TEXT
                    )"""
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(date)"
                )
                self._ensure_columns(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        """老库迁移：补 done / repeat 列（幂等，已有列则跳过）。"""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(schedules)").fetchall()}
        if "done" not in cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN done INTEGER NOT NULL DEFAULT 0")
        if "repeat" not in cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN repeat TEXT")

    def _connect(self) -> sqlite3.Connection:
        """打开短连接（调用线程内创建/使用/关闭；timeout 兜底并发写锁）。"""
        return sqlite3.connect(self._db_path, timeout=5)

    def add(self, day: str, time: str, event: str, repeat: Optional[str] = None) -> int:
        """写入一条日程，返回自增 id。"""
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute(
                    "INSERT INTO schedules (date, time, event, created_at, done, repeat) "
                    "VALUES (?,?,?,?,0,?)",
                    (day, time, event, datetime.now().isoformat(timespec="seconds"), repeat),
                )
                return int(cur.lastrowid)

    def list_on(self, day: str) -> List[Dict[str, object]]:
        """查询某天的日程（按时间升序）。"""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, time, event, done, repeat FROM schedules "
                "WHERE date = ? ORDER BY time, id",
                (day,),
            ).fetchall()
        return [{"id": r[0], "time": r[1], "event": r[2],
                 "done": bool(r[3]), "repeat": r[4]} for r in rows]

    def count(self) -> int:
        """日程总数（统计/测试用）。"""
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]

    def _matching_clause(self, day: str, time: Optional[str] = None,
                         time_range: Optional[Tuple[int, int]] = None,
                         event: Optional[str] = None) -> Tuple[str, List[object]]:
        """构造删除/完成标记的 WHERE 子句与参数（精确时刻 > 时段区间 > 全时段）。"""
        clauses = ["date = ?"]
        params: List[object] = [day]
        if time is not None:
            clauses.append("time = ?")
            params.append(time)
        elif time_range is not None:
            start, end = time_range
            clauses.append("time >= ? AND time < ?")
            params.extend([f"{start:02d}:00", f"{end:02d}:00"])
        if event:
            clauses.append("event LIKE ?")
            params.append(f"%{event}%")
        return " AND ".join(clauses), params

    def delete_matching(self, day: str, time: Optional[str] = None,
                        time_range: Optional[Tuple[int, int]] = None,
                        event: Optional[str] = None) -> List[Dict[str, object]]:
        """删除匹配条目，返回被删除条目列表（空列表 = 无匹配）。"""
        where, params = self._matching_clause(day, time, time_range, event)
        with closing(self._connect()) as conn:
            with conn:
                rows = conn.execute(
                    "SELECT id, time, event, done, repeat FROM schedules "
                    "WHERE " + where + " ORDER BY time, id", params,
                ).fetchall()
                conn.execute("DELETE FROM schedules WHERE " + where, params)
        return [{"id": r[0], "time": r[1], "event": r[2],
                 "done": bool(r[3]), "repeat": r[4]} for r in rows]

    def mark_done_matching(self, day: str, time: Optional[str] = None,
                           time_range: Optional[Tuple[int, int]] = None,
                           event: Optional[str] = None) -> Tuple[List[Dict[str, object]], int]:
        """标记匹配条目完成，返回 (匹配条目列表, 本次实际更新条数)。"""
        where, params = self._matching_clause(day, time, time_range, event)
        with closing(self._connect()) as conn:
            with conn:
                rows = conn.execute(
                    "SELECT id, time, event, done, repeat FROM schedules "
                    "WHERE " + where + " ORDER BY time, id", params,
                ).fetchall()
                cur = conn.execute(
                    "UPDATE schedules SET done = 1 WHERE " + where + " AND done = 0", params,
                )
                updated = cur.rowcount
        return ([{"id": r[0], "time": r[1], "event": r[2],
                  "done": bool(r[3]), "repeat": r[4]} for r in rows], updated)


# ---------------------------------------------------------------- 主入口

def add(text: str, llm_call: Optional[Callable[[str], str]] = None,
        db_path: str = DB_PATH, now: Optional[datetime] = None) -> Dict[str, object]:
    """主入口：提醒话术 → 结构化日程条目并持久化。

    返回 {"id, date, time, event, repeat, error"}：成功时 error=None 且 id 为自增 id。
    :param now: 注入当前时间（离线测试用，影响重复提醒的起始日期），默认 datetime.now()
    """
    parsed = parse_request(text, llm_call, now=now)
    if parsed["error"]:
        return {"id": None, "date": parsed["date"], "time": parsed["time"],
                "event": parsed["event"], "repeat": parsed.get("repeat"),
                "error": parsed["error"]}
    try:
        sid = ScheduleStore(db_path).add(
            parsed["date"], parsed["time"], parsed["event"], parsed.get("repeat"))
    except Exception as exc:  # 落库失败：降级为结构化错误，不抛异常
        return {"id": None, "date": parsed["date"], "time": parsed["time"],
                "event": parsed["event"], "repeat": parsed.get("repeat"),
                "error": f"日程保存失败：{exc}"}
    return {"id": sid, "date": parsed["date"], "time": parsed["time"],
            "event": parsed["event"], "repeat": parsed.get("repeat"), "error": None}


def delete(text: str, db_path: str = DB_PATH,
           now: Optional[datetime] = None) -> Dict[str, object]:
    """删除提醒：『删掉明天下午的提醒』→ 按 日期/时段/事项 匹配删除。

    返回 {"deleted", "entries", "error"}：
    - deleted: 实际删除条数；entries: 被删除条目列表；
    - 无匹配时 deleted=0 且 error 为提示（不抛异常）。
    """
    target = _resolve_target(text, done=False, now=now)
    if target["error"]:
        return {"deleted": 0, "entries": [], "error": target["error"]}
    try:
        rows = ScheduleStore(db_path).delete_matching(
            target["date"], time=target["time"],
            time_range=target["time_range"], event=target["event"])
    except Exception as exc:  # 落库失败：降级为结构化错误，不抛异常
        return {"deleted": 0, "entries": [], "error": f"删除失败：{exc}"}
    if not rows:
        return {"deleted": 0, "entries": [], "error": "没有找到匹配的提醒（可能已经删掉了）"}
    return {"deleted": len(rows), "entries": rows, "error": None}


def mark_done(text: str, db_path: str = DB_PATH,
              now: Optional[datetime] = None) -> Dict[str, object]:
    """完成标记：『今天喝水的提醒完成了』→ 匹配条目 done=1。

    返回 {"updated", "entries", "error"}：
    - updated: 本次从未完成改为完成的条数；entries: 匹配到的条目列表；
    - 无匹配时 updated=0 且 error 为提示；已完成的重复标记 updated=0 但不报错。
    """
    target = _resolve_target(text, done=True, now=now)
    if target["error"]:
        return {"updated": 0, "entries": [], "error": target["error"]}
    try:
        rows, updated = ScheduleStore(db_path).mark_done_matching(
            target["date"], time=target["time"],
            time_range=target["time_range"], event=target["event"])
    except Exception as exc:  # 落库失败：降级为结构化错误，不抛异常
        return {"updated": 0, "entries": [], "error": f"标记完成失败：{exc}"}
    if not rows:
        return {"updated": 0, "entries": [], "error": "没有找到匹配的提醒"}
    return {"updated": updated, "entries": rows, "error": None}


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
