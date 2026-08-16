"""能力 Agent（日程备忘）的离线测试：规则解析 + mock LLM 兜底 + 临时库持久化。

不调用 Ollama；数据库用 tmp_path 临时目录，不动 data/ 下的真实库。
"""
from datetime import date, timedelta

import pytest

from app.agents.schedule_agent import ScheduleAgent
from app.tools.schedule import ScheduleStore, add, list_on, parse_request, today, tomorrow


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
