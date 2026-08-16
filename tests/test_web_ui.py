"""Web 聊天界面（M5 形象 + M5.2 能力面板）离线测试：静态挂载、首页路由、新 API 路由。

不依赖网络/模型：GET / 与 /static 直接验证；/schedule、/plans 用假工具桩
（避免污染 data/ 下真实库），/chat 用假 Agent 桩。
"""
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


class FakeAgent:
    """假人格 Agent：固定回复，验证 /chat 路由未被改动。"""

    def __init__(self, reply: str = "嗯嗯，我在呢，陪你聊聊～") -> None:
        self.reply = reply

    def chat(self, user_input: str, session_id=None):
        return self.reply, session_id or "fake-sid-web"


class FakeScheduleTools:
    """假日程工具：内存实现（临时库，避免污染真实 data/schedule.db）。"""

    def __init__(self) -> None:
        self.items: list = []
        self._next_id = 1

    def today(self) -> dict:
        entries = [dict(e) for e in self.items if e["date"] == "TODAY"]
        return {"date": "TODAY", "entries": entries, "count": len(entries)}

    def tomorrow(self) -> dict:
        entries = [dict(e) for e in self.items if e["date"] == "TOMORROW"]
        return {"date": "TOMORROW", "entries": entries, "count": len(entries)}

    def add(self, text: str) -> dict:
        if "喝水" in text:
            item = {"id": self._next_id, "date": "TOMORROW", "time": "15:00",
                    "event": "喝水", "done": False, "repeat": None}
            self._next_id += 1
            self.items.append(item)
            return {"id": item["id"], "date": item["date"], "time": item["time"],
                    "event": item["event"], "repeat": None, "error": None}
        return {"id": None, "date": None, "time": None, "event": None,
                "repeat": None, "error": "没看懂时间/事项"}

    def mark_done_by_id(self, item_id: int) -> dict:
        for e in self.items:
            if e["id"] == item_id:
                updated = 0 if e["done"] else 1
                e["done"] = True
                return {"updated": updated, "entry": dict(e), "error": None}
        return {"updated": 0, "entry": None, "error": f"没有找到 id={item_id} 的日程"}

    def delete_by_id(self, item_id: int) -> dict:
        for i, e in enumerate(self.items):
            if e["id"] == item_id:
                removed = self.items.pop(i)
                return {"deleted": True, "entry": dict(removed), "error": None}
        return {"deleted": False, "entry": None, "error": f"没有找到 id={item_id} 的日程"}


class FakePlanningTools:
    """假规划工具：内存实现。"""

    def __init__(self) -> None:
        self.plans: list = []
        self._next_id = 1

    def list_plans(self) -> dict:
        return {"plans": [dict(p) for p in self.plans], "count": len(self.plans), "error": None}

    def plan(self, goal: str) -> dict:
        """假规划生成：目标含『做饭』返回固定步骤，否则结构化错误。"""
        if "做饭" in goal:
            return {
                "goal": goal,
                "steps": [
                    {"no": 1, "title": "挑选菜谱", "priority": "中", "detail": "选几道简单菜"},
                    {"no": 2, "title": "采购食材", "priority": "高", "detail": "去市场买齐材料"},
                ],
                "error": None,
            }
        return {"goal": goal, "steps": [], "error": "规划生成失败"}

    def delete_plan(self, plan_id: int) -> dict:
        for i, p in enumerate(self.plans):
            if p["id"] == plan_id:
                self.plans.pop(i)
                return {"deleted": True, "error": None}
        return {"deleted": False, "error": f"没有找到 id={plan_id} 的计划"}


@pytest.fixture()
def fake_tools(monkeypatch):
    """把 app.main 的日程/规划工具替换为假实现（避免碰真实 data/ 库）。"""
    sched = FakeScheduleTools()
    plans = FakePlanningTools()
    monkeypatch.setattr(main_module, "_schedule_tools", sched)
    monkeypatch.setattr(main_module, "_planning_tools", plans)
    return sched, plans


def test_index_serves_chat_page() -> None:
    """GET / 应返回聊天页 HTML，且包含立绘/对话窗/输入框/语音按钮关键元素。"""
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    # 立绘区（含表情状态容器）
    assert 'id="portrait"' in html
    assert 'data-state="default"' in html
    # 对话窗与输入区
    assert 'id="messages"' in html
    assert 'id="chat-form"' in html
    assert 'id="input"' in html
    # 语音控件
    assert 'id="voice-btn"' in html
    # 引用本地静态资源（不依赖任何外部 CDN/素材）
    assert "/static/css/style.css" in html
    assert "/static/js/app.js" in html


def test_index_has_capability_panels() -> None:
    """GET / 应包含 M5.2 三个能力面板入口（日程/规划/记忆）。"""
    html = TestClient(app).get("/").text
    assert 'data-panel="schedule"' in html
    assert 'data-panel="plans"' in html
    assert 'data-panel="memory"' in html
    assert 'id="panel-schedule"' in html
    assert 'id="panel-plans"' in html
    assert 'id="panel-memory"' in html
    assert 'id="schedule-form"' in html
    assert 'id="memory-clear"' in html


# ---------------------------------------------------------------- M5.2 日程 API


def test_schedule_list_today_and_tomorrow(fake_tools) -> None:
    """GET /schedule?date=today|tomorrow 应返回对应日期的日程列表。"""
    sched, _ = fake_tools
    sched.add("明天下午 3 点提醒我喝水")
    client = TestClient(app)
    today = client.get("/schedule", params={"date": "today"})
    assert today.status_code == 200
    assert today.json()["date"] == "TODAY"
    assert today.json()["count"] == 0
    tomorrow = client.get("/schedule", params={"date": "tomorrow"})
    assert tomorrow.status_code == 200
    data = tomorrow.json()
    assert data["count"] == 1
    assert data["entries"][0]["event"] == "喝水"
    assert data["entries"][0]["time"] == "15:00"


def test_schedule_list_invalid_date_422(fake_tools) -> None:
    """date 参数只允许 today|tomorrow，其他值应 422。"""
    resp = TestClient(app).get("/schedule", params={"date": "yesterday"})
    assert resp.status_code == 422


def test_schedule_add_ok(fake_tools) -> None:
    """POST /schedule 自然语言提醒 → 201 + 结构化条目。"""
    sched, _ = fake_tools
    resp = TestClient(app).post("/schedule", json={"text": "明天下午 3 点提醒我喝水"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == 1
    assert data["date"] == "TOMORROW" and data["time"] == "15:00" and data["event"] == "喝水"
    assert sched.tomorrow()["count"] == 1


def test_schedule_add_parse_fail_400(fake_tools) -> None:
    """解析失败 → 400 + 明确错误，不落库。"""
    sched, _ = fake_tools
    resp = TestClient(app).post("/schedule", json={"text": "随便聊聊"})
    assert resp.status_code == 400
    assert "没看懂" in resp.json()["detail"]
    assert sched.tomorrow()["count"] == 0


def test_schedule_add_empty_400(fake_tools) -> None:
    """空提醒内容 → 400。"""
    resp = TestClient(app).post("/schedule", json={"text": "   "})
    assert resp.status_code == 400


def test_schedule_mark_done(fake_tools) -> None:
    """POST /schedule/{id}/done 标记完成；不存在 → 404。"""
    sched, _ = fake_tools
    sched.add("明天下午 3 点提醒我喝水")
    resp = TestClient(app).post("/schedule/1/done")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True and data["updated"] == 1
    assert sched.items[0]["done"] is True
    # 再次标记：updated=0（幂等）
    resp2 = TestClient(app).post("/schedule/1/done")
    assert resp2.json()["updated"] == 0
    # 不存在
    resp3 = TestClient(app).post("/schedule/999/done")
    assert resp3.status_code == 404


def test_schedule_delete(fake_tools) -> None:
    """DELETE /schedule/{id} 删除；不存在 → 404。"""
    sched, _ = fake_tools
    sched.add("明天下午 3 点提醒我喝水")
    resp = TestClient(app).delete("/schedule/1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert sched.tomorrow()["count"] == 0
    resp2 = TestClient(app).delete("/schedule/1")
    assert resp2.status_code == 404


# ---------------------------------------------------------------- M5.2 规划 API


def test_plans_list_and_delete(fake_tools) -> None:
    """GET /plans 列表 + DELETE /plans/{id}；不存在 → 404。"""
    _, plans = fake_tools
    plans.plans.append({"id": 1, "goal": "周末学做饭", "step_count": 4, "created_at": "2026-08-16T12:00:00"})
    client = TestClient(app)
    resp = client.get("/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["plans"][0]["goal"] == "周末学做饭"
    assert data["plans"][0]["step_count"] == 4
    resp2 = client.delete("/plans/1")
    assert resp2.status_code == 200
    assert resp2.json()["deleted"] is True
    assert client.get("/plans").json()["count"] == 0
    resp3 = client.delete("/plans/1")
    assert resp3.status_code == 404


def test_plans_generate_ok(fake_tools) -> None:
    """POST /plans 生成规划（不落库）→ 201 + 结构化步骤清单。"""
    _, plans = fake_tools
    client = TestClient(app)
    resp = client.post("/plans", json={"goal": "帮我规划周末学做饭"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["steps"][0]["title"] == "挑选菜谱"
    assert data["steps"][0]["priority"] == "中"
    assert len(data["steps"]) == 2
    assert plans.plans == []  # 生成不落库


def test_plans_generate_fail_400(fake_tools) -> None:
    """规划生成失败 → 400 + 错误信息。"""
    client = TestClient(app)
    resp = client.post("/plans", json={"goal": "随便聊聊"})
    assert resp.status_code == 400
    assert "规划" in resp.json()["detail"]


def test_plans_generate_empty_400(fake_tools) -> None:
    """空目标 → 400。"""
    resp = TestClient(app).post("/plans", json={"goal": "   "})
    assert resp.status_code == 400


def test_static_css_served() -> None:
    """/static 下的样式表应可访问。"""
    client = TestClient(app)
    resp = client.get("/static/css/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_static_js_served() -> None:
    """/static 下的前端脚本应可访问。"""
    client = TestClient(app)
    resp = client.get("/static/js/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_static_missing_file_404() -> None:
    """不存在的静态资源应返回 404（静态挂载无越权）。"""
    client = TestClient(app)
    resp = client.get("/static/not-exist.js")
    assert resp.status_code == 404


def test_health_unchanged() -> None:
    """既有健康检查不受 M5 改动影响。"""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_api_unchanged(monkeypatch) -> None:
    """POST /chat 逻辑未被 M5 改动（假 Agent 桩验证契约不变）。"""
    monkeypatch.setattr(main_module, "_agent", FakeAgent())
    client = TestClient(app)
    resp = client.post("/chat", json={"query": "你好呀"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "嗯嗯，我在呢，陪你聊聊～"
    assert data["session_id"] == "fake-sid-web"


def test_chat_api_empty_query_still_400(monkeypatch) -> None:
    """/chat 的空 query 校验保持不变。"""
    monkeypatch.setattr(main_module, "_agent", FakeAgent())
    client = TestClient(app)
    resp = client.post("/chat", json={"query": "   "})
    assert resp.status_code == 400
