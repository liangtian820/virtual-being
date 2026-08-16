"""能力 Agent（日程备忘）的离线测试：规则解析 + mock LLM 兜底 + 临时库持久化。

不调用 Ollama；数据库用 tmp_path 临时目录，不动 data/ 下的真实库。
M2.2（WO-20260816-23）追加：周几解析边界（今天周几/跨周）、删除、完成标记、重复提醒。
"""
from datetime import date, datetime, timedelta

import pytest

from app.agents.schedule_agent import ScheduleAgent
from app.tools.schedule import (
    ScheduleStore,
    add,
    delete,
    list_on,
    mark_done,
    parse_request,
    parse_weekday,
    today,
    tomorrow,
)


def _d(offset: int) -> str:
    """今天 + offset 天的 ISO 日期。"""
    return (date.today() + timedelta(days=offset)).isoformat()


# ---------------------------------------------------------------- 规则解析（输入 → 结构化输出）

def test_parse_tomorrow_afternoon() -> None:
    """『提醒我明天下午 3 点喝水』→ 明日 15:00 喝水。"""
    r = parse_request("提醒我明天下午 3 点喝水")
    assert r["error"] is None
    assert r["date"] == _d(1)
    assert r["time"] == "15:00"
    assert r["event"] == "喝水"


def test_parse_today_morning() -> None:
    """『今天早上 8 点开会』→ 今日 08:00 开会。"""
    r = parse_request("今天早上 8 点开会")
    assert r["error"] is None
    assert r["date"] == _d(0)
    assert r["time"] == "08:00"
    assert r["event"] == "开会"


def test_parse_day_after_tomorrow_half_hour() -> None:
    """『后天上午 9 点半交报告』→ 后日 09:30。"""
    r = parse_request("后天上午 9 点半交报告")
    assert r["error"] is None
    assert r["date"] == _d(2)
    assert r["time"] == "09:30"
    assert r["event"] == "交报告"


def test_parse_tonight_period_hint() -> None:
    """『明晚 7 点给妈妈打电话吧』→ 明日 19:00（日期词自带时段）。"""
    r = parse_request("明晚 7 点给妈妈打电话吧")
    assert r["error"] is None
    assert r["date"] == _d(1)
    assert r["time"] == "19:00"
    assert r["event"] == "给妈妈打电话"


def test_parse_explicit_hhmm() -> None:
    """显式 24 小时制时间：『明天 15:30 健身』。"""
    r = parse_request("明天 15:30 健身")
    assert r["error"] is None
    assert r["date"] == _d(1)
    assert r["time"] == "15:30"
    assert r["event"] == "健身"


def test_parse_noon_midnight() -> None:
    """『中午 12 点吃饭』→ 12:00；『凌晨 12 点睡觉』→ 00:00。"""
    assert parse_request("中午 12 点吃饭")["time"] == "12:00"
    assert parse_request("凌晨 12 点睡觉")["time"] == "00:00"


def test_parse_iso_date() -> None:
    """具体日期：『2026-08-20 上午 10 点体检』。"""
    r = parse_request("2026-08-20 上午 10 点体检")
    assert r["error"] is None
    assert r["date"] == "2026-08-20"
    assert r["time"] == "10:00"
    assert r["event"] == "体检"


def test_parse_llm_fallback() -> None:
    """规则无法覆盖（无日期时间）→ LLM 兜底提取。"""
    r = parse_request(
        "提醒我多喝水",
        llm_call=lambda prompt: '{"date": "明天", "time": "09:00", "event": "多喝水"}',
    )
    assert r["error"] is None
    assert r["date"] == _d(1)
    assert r["time"] == "09:00"
    assert r["event"] == "多喝水"


def test_parse_llm_fills_missing_only() -> None:
    """规则已给出时间/事项，LLM 只补日期。"""
    r = parse_request(
        "下午 3 点锻炼",
        llm_call=lambda prompt: '{"date": "今天", "time": "15:00", "event": "锻炼"}',
    )
    assert r["error"] is None
    assert r["date"] == _d(0)
    assert r["time"] == "15:00"
    assert r["event"] == "锻炼"


def test_parse_incomplete_without_llm() -> None:
    """无 LLM 且信息不完整 → 结构化错误（保留已解析字段），不抛异常。"""
    r = parse_request("明天下午 3 点")
    assert r["error"] is not None
    assert r["date"] == _d(1)
    assert r["time"] == "15:00"
    assert r["event"] is None


def test_parse_llm_garbage() -> None:
    """LLM 兜底输出垃圾 → 结构化错误，不抛异常。"""
    r = parse_request("提醒我多喝水", llm_call=lambda prompt: "我也不知道")
    assert r["error"] is not None


def test_parse_empty() -> None:
    """空输入 → 结构化错误。"""
    r = parse_request("   ")
    assert r["error"] is not None


def test_parse_never_raises() -> None:
    """各种奇怪输入都不抛异常，返回含 error 字段的 dict。"""
    for text in ("", "随便聊聊", "啊？", "12345", "明天", "下午 3 点", "提醒我 晚上 吃饭"):
        r = parse_request(text)
        assert isinstance(r, dict)
        assert "error" in r


# ---------------------------------------------------------------- 持久化（临时库）

def test_add_and_query(tmp_path) -> None:
    """add 持久化 + 按日期查询（时间升序）。"""
    db = str(tmp_path / "schedule.db")
    r1 = add("明天上午 9 点开会", db_path=db)
    r2 = add("明天下午 3 点喝水", db_path=db)
    assert r1["error"] is None and r1["time"] == "09:00"
    assert r2["error"] is None and r2["time"] == "15:00"
    assert r1["id"] != r2["id"]

    lst = list_on(_d(1), db_path=db)
    assert lst["count"] == 2
    assert [e["time"] for e in lst["entries"]] == ["09:00", "15:00"]
    assert lst["entries"][0]["event"] == "开会"


def test_add_invalid_not_persisted(tmp_path) -> None:
    """解析失败的提醒不应落库。"""
    db = str(tmp_path / "schedule.db")
    r = add("随便聊聊", db_path=db)
    assert r["error"] is not None
    assert r["id"] is None
    assert ScheduleStore(db).count() == 0


def test_today_tomorrow_queries(tmp_path) -> None:
    """今日/明日查询只返回对应日期的日程。"""
    db = str(tmp_path / "schedule.db")
    add("今天下午 2 点开会", db_path=db)
    add("明天上午 8 点体检", db_path=db)
    assert today(db_path=db)["count"] == 1
    assert today(db_path=db)["entries"][0]["event"] == "开会"
    assert tomorrow(db_path=db)["count"] == 1
    assert tomorrow(db_path=db)["entries"][0]["event"] == "体检"
    assert list_on(_d(5), db_path=db)["count"] == 0


# ---------------------------------------------------------------- 能力 Agent 封装

def test_schedule_agent_roundtrip(tmp_path) -> None:
    """ScheduleAgent：add → today/tomorrow 全链路（临时库）。"""
    agent = ScheduleAgent(db_path=str(tmp_path / "agent.db"))
    r = agent.add("提醒我明天下午 3 点喝水")
    assert r["error"] is None
    assert r["date"] == _d(1) and r["time"] == "15:00" and r["event"] == "喝水"
    lst = agent.tomorrow()
    assert lst["count"] == 1
    assert lst["entries"][0]["event"] == "喝水"
    assert agent.today()["count"] == 0


def test_schedule_agent_llm_fallback(tmp_path) -> None:
    """ScheduleAgent 注入 mock LLM：规则无法覆盖时兜底解析。"""
    agent = ScheduleAgent(db_path=str(tmp_path / "agent2.db"))
    r = agent.add("记得周三下午吃药", llm_call=lambda prompt: '{"date": "明天", "time": "14:00", "event": "吃药"}')
    assert r["error"] is None
    assert r["time"] == "14:00"
    assert r["event"] == "吃药"


@pytest.mark.parametrize("text", ["", None, "随便聊聊", "？？？"])
def test_schedule_agent_never_raises(tmp_path, text) -> None:
    """任意输入经 Agent 都不抛异常，返回含 error 字段的 dict。"""
    agent = ScheduleAgent(db_path=str(tmp_path / "agent3.db"))
    r = agent.add(text)  # type: ignore[arg-type]
    assert isinstance(r, dict)
    assert "error" in r


# ---------------------------------------------------------------- M2.2 周几解析

def test_parse_weekday_today_is_that_day() -> None:
    """今天是周三 → 『周三』= 今天。"""
    now = datetime(2026, 8, 19, 9, 0)  # 2026-08-19 是周三
    assert now.date().weekday() == 2
    assert parse_weekday("周三", now=now) == "2026-08-19"


def test_parse_weekday_cross_week() -> None:
    """周五说『周三』→ 跨周边界：下周三（2026-08-26）。"""
    now = datetime(2026, 8, 21, 9, 0)  # 周五
    assert now.date().weekday() == 4
    assert parse_weekday("周三", now=now) == "2026-08-26"


def test_parse_weekday_sunday_says_monday() -> None:
    """周日说『周一』→ 明天（跨周边界：本周一已过）。"""
    now = datetime(2026, 8, 23, 9, 0)  # 周日
    assert now.date().weekday() == 6
    assert parse_weekday("周一", now=now) == "2026-08-24"


def test_parse_weekday_next_this_week() -> None:
    """『下周三』→ 下周；『这周三/本周三』→ 本周（可能已过）。"""
    now = datetime(2026, 8, 21, 9, 0)  # 周五
    assert parse_weekday("下周三", now=now) == "2026-08-26"
    assert parse_weekday("这周三", now=now) == "2026-08-19"
    assert parse_weekday("本周三", now=now) == "2026-08-19"
    assert parse_weekday("星期三", now=now) == "2026-08-26"


def test_parse_weekday_none() -> None:
    """没有周几表达 → None。"""
    assert parse_weekday("明天下午 3 点喝水") is None
    assert parse_weekday("   ") is None
    assert parse_weekday("") is None


def test_parse_request_weekday_with_llm_time() -> None:
    """『周三下午吃药』（周二说）→ 最近一个周三的具体日期；时间缺项由 LLM 补。"""
    r = parse_request(
        "周三下午吃药",
        llm_call=lambda prompt: '{"date": null, "time": "15:00", "event": "吃药"}',
        now=datetime(2026, 8, 18, 9, 0),  # 周二
    )
    assert r["error"] is None
    assert r["date"] == "2026-08-19"
    assert r["time"] == "15:00"
    assert r["event"] == "吃药"


def test_add_weekday_rule_only(tmp_path) -> None:
    """『周三下午 3 点吃药』无 LLM 也能解析出周几日期（规则完整覆盖）。"""
    db = str(tmp_path / "weekday.db")
    r = add("周三下午 3 点吃药", db_path=db, now=datetime(2026, 8, 18, 9, 0))
    assert r["error"] is None
    assert r["date"] == "2026-08-19"
    assert r["time"] == "15:00"
    assert r["event"] == "吃药"
    assert r["repeat"] is None
    assert list_on("2026-08-19", db_path=db)["count"] == 1


# ---------------------------------------------------------------- M2.2 删除

def test_delete_by_date_and_period(tmp_path) -> None:
    """『删掉明天下午的提醒』→ 只删明天的下午时段条目。"""
    db = str(tmp_path / "del1.db")
    add("明天下午 3 点开会", db_path=db)
    add("明天上午 9 点体检", db_path=db)
    r = delete("删掉明天下午的提醒", db_path=db)
    assert r["error"] is None
    assert r["deleted"] == 1
    assert r["entries"][0]["event"] == "开会"
    assert list_on(_d(1), db_path=db)["count"] == 1
    assert list_on(_d(1), db_path=db)["entries"][0]["event"] == "体检"


def test_delete_all_on_date(tmp_path) -> None:
    """『删掉明天的提醒』→ 删除明天全部条目。"""
    db = str(tmp_path / "del2.db")
    add("明天上午 9 点体检", db_path=db)
    add("明天下午 3 点开会", db_path=db)
    add("后天上午 9 点培训", db_path=db)
    r = delete("删掉明天的提醒", db_path=db)
    assert r["error"] is None and r["deleted"] == 2
    assert list_on(_d(1), db_path=db)["count"] == 0
    assert list_on(_d(2), db_path=db)["count"] == 1


def test_delete_exact_time(tmp_path) -> None:
    """『删掉明天 15:30 的提醒』→ 精确时刻匹配。"""
    db = str(tmp_path / "del3.db")
    add("明天 15:30 健身", db_path=db)
    add("明天 16:00 开会", db_path=db)
    r = delete("删掉明天 15:30 的提醒", db_path=db)
    assert r["error"] is None and r["deleted"] == 1
    assert r["entries"][0]["event"] == "健身"


def test_delete_by_event_keyword(tmp_path) -> None:
    """『删掉明天的开会提醒』→ 按事项子串匹配。"""
    db = str(tmp_path / "del4.db")
    add("明天上午 9 点开会", db_path=db)
    add("明天下午 3 点喝水", db_path=db)
    r = delete("删掉明天的开会提醒", db_path=db)
    assert r["error"] is None and r["deleted"] == 1
    assert r["entries"][0]["event"] == "开会"
    assert list_on(_d(1), db_path=db)["count"] == 1


def test_delete_weekday_target(tmp_path) -> None:
    """『删掉周三下午的提醒』→ 解析出最近周三并删除（与添加同基准日期）。"""
    db = str(tmp_path / "del5.db")
    now = datetime(2026, 8, 18, 10, 0)  # 周二
    add("周三下午 3 点开会", db_path=db, now=now)
    assert list_on(parse_weekday("周三", now=now), db_path=db)["count"] == 1  # type: ignore[arg-type]
    r = delete("删掉周三下午的提醒", db_path=db, now=now)
    assert r["error"] is None and r["deleted"] == 1
    assert r["entries"][0]["event"] == "开会"
    assert list_on("2026-08-19", db_path=db)["count"] == 0


def test_delete_not_found(tmp_path) -> None:
    """无匹配 → deleted=0 + 结构化错误，不抛异常。"""
    db = str(tmp_path / "del6.db")
    add("明天上午 9 点体检", db_path=db)
    r = delete("删掉明天下午的提醒", db_path=db)
    assert r["deleted"] == 0
    assert r["error"] is not None
    assert list_on(_d(1), db_path=db)["count"] == 1  # 未误删


def test_delete_invalid_target(tmp_path) -> None:
    """没有日期 → 结构化错误，不抛异常。"""
    db = str(tmp_path / "del7.db")
    r = delete("随便说说", db_path=db)
    assert r["deleted"] == 0 and r["error"] is not None
    r2 = delete("删掉下午的提醒", db_path=db)
    assert r2["deleted"] == 0 and r2["error"] is not None


# ---------------------------------------------------------------- M2.2 完成标记

def test_mark_done_today_event(tmp_path) -> None:
    """『今天喝水的提醒完成了』→ 匹配条目 done=True。"""
    db = str(tmp_path / "done1.db")
    add("今天上午 9 点喝水", db_path=db)
    add("今天上午 10 点开会", db_path=db)
    r = mark_done("今天喝水的提醒完成了", db_path=db)
    assert r["error"] is None
    assert r["updated"] == 1
    assert r["entries"][0]["event"] == "喝水"
    entries = today(db_path=db)["entries"]
    by_event = {e["event"]: e for e in entries}
    assert by_event["喝水"]["done"] is True
    assert by_event["开会"]["done"] is False


def test_mark_done_already_done(tmp_path) -> None:
    """重复标记已完成 → updated=0 但不报错。"""
    db = str(tmp_path / "done2.db")
    add("今天上午 9 点喝水", db_path=db)
    first = mark_done("今天喝水的提醒完成了", db_path=db)
    assert first["error"] is None and first["updated"] == 1
    second = mark_done("今天喝水的提醒完成了", db_path=db)
    assert second["error"] is None
    assert second["updated"] == 0
    assert len(second["entries"]) == 1  # 条目仍在


def test_mark_done_not_found(tmp_path) -> None:
    """无匹配 → updated=0 + 结构化错误。"""
    db = str(tmp_path / "done3.db")
    r = mark_done("今天喝水的提醒完成了", db_path=db)
    assert r["updated"] == 0 and r["error"] is not None


# ---------------------------------------------------------------- M2.2 重复提醒

def test_add_daily_repeat_before_time(tmp_path) -> None:
    """『每天早上 8 点提醒我喝水』（06:00 说）→ 今天 08:00，repeat=daily。"""
    db = str(tmp_path / "rep1.db")
    r = add("每天早上 8 点提醒我喝水", db_path=db, now=datetime(2026, 8, 16, 6, 0))
    assert r["error"] is None
    assert r["repeat"] == "daily"
    assert r["date"] == "2026-08-16"
    assert r["time"] == "08:00"
    assert r["event"] == "喝水"


def test_add_daily_repeat_after_time(tmp_path) -> None:
    """『每天早上 8 点提醒我喝水』（09:00 说，已过 8 点）→ 明天 08:00。"""
    db = str(tmp_path / "rep2.db")
    r = add("每天早上 8 点提醒我喝水", db_path=db, now=datetime(2026, 8, 16, 9, 0))
    assert r["error"] is None
    assert r["repeat"] == "daily"
    assert r["date"] == "2026-08-17"
    assert r["time"] == "08:00"


def test_add_daily_repeat_llm_time(tmp_path) -> None:
    """『每天早上提醒我喝水』无时刻 → LLM 补时间，repeat 仍由规则识别为 daily。"""
    db = str(tmp_path / "rep3.db")
    r = add(
        "每天早上提醒我喝水",
        llm_call=lambda prompt: '{"date": null, "time": "08:00", "event": "喝水"}',
        db_path=db, now=datetime(2026, 8, 16, 6, 0),
    )
    assert r["error"] is None
    assert r["repeat"] == "daily"
    assert r["date"] == "2026-08-16"
    assert r["time"] == "08:00"
    assert r["event"] == "喝水"


def test_add_weekly_repeat_same_day_before_time(tmp_path) -> None:
    """『每周三上午 9 点开会』（周三 08:00 说）→ 今天 09:00，repeat=weekly。"""
    db = str(tmp_path / "rep4.db")
    r = add("每周三上午 9 点开会", db_path=db, now=datetime(2026, 8, 19, 8, 0))
    assert r["error"] is None
    assert r["repeat"] == "weekly"
    assert r["date"] == "2026-08-19"
    assert r["time"] == "09:00"
    assert r["event"] == "开会"


def test_add_weekly_repeat_after_time(tmp_path) -> None:
    """『每周三上午 9 点开会』（周三 10:00 说，已过 9 点）→ 下周三。"""
    db = str(tmp_path / "rep5.db")
    r = add("每周三上午 9 点开会", db_path=db, now=datetime(2026, 8, 19, 10, 0))
    assert r["error"] is None
    assert r["repeat"] == "weekly"
    assert r["date"] == "2026-08-26"


def test_plain_add_has_no_repeat(tmp_path) -> None:
    """既有 add 行为不变（回归）：普通提醒 repeat=None，字段兼容。"""
    db = str(tmp_path / "rep6.db")
    r = add("提醒我明天下午 3 点喝水", db_path=db)
    assert r["error"] is None
    assert r["date"] == _d(1) and r["time"] == "15:00" and r["event"] == "喝水"
    assert r["repeat"] is None
    assert r["id"] is not None


# ---------------------------------------------------------------- M2.2 能力 Agent 封装

def test_schedule_agent_weekday_delete_mark_done(tmp_path) -> None:
    """ScheduleAgent 新接口全链路：parse_weekday → add → mark_done → delete。

    M6.9 稳定性修复：today()/tomorrow() 使用真实系统日期，原固定 now=2026-08-16 在
    系统日期跨天后（2026-08-17 起）不再与落库日期匹配 → 改为基于运行时日期构造 now，
    add 落真实『今天』，today() 可命中，测试与系统日期解耦。
    """
    agent = ScheduleAgent(db_path=str(tmp_path / "agent4.db"))
    now_d = datetime.now()
    assert agent.parse_weekday("周三", now=datetime(2026, 8, 21, 9, 0)) == "2026-08-26"
    r = agent.add("今天上午 9 点喝水", now=now_d.replace(hour=8, minute=0))
    assert r["error"] is None
    done = agent.mark_done("今天喝水的提醒完成了", now=now_d.replace(hour=10, minute=0))
    assert done["error"] is None and done["updated"] == 1
    assert agent.today()["entries"][0]["done"] is True
    agent.add("明天下午 3 点开会", now=now_d.replace(hour=8, minute=0))
    d = agent.delete("删掉明天下午的提醒", now=now_d.replace(hour=8, minute=0))
    assert d["error"] is None and d["deleted"] == 1
    assert agent.tomorrow()["count"] == 0


def test_schedule_agent_delete_never_raises(tmp_path) -> None:
    """任意输入经 Agent 删除/完成都不抛异常，返回含 error 的 dict。"""
    agent = ScheduleAgent(db_path=str(tmp_path / "agent5.db"))
    for text in ("", None, "随便聊聊", "？？？"):
        r = agent.delete(text)  # type: ignore[arg-type]
        assert isinstance(r, dict) and "error" in r
        m = agent.mark_done(text)  # type: ignore[arg-type]
        assert isinstance(m, dict) and "error" in m
