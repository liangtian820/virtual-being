"""Web 聊天界面（M5 形象）离线测试：静态挂载与首页路由。

不依赖网络/模型：仅验证 GET / 返回聊天页、/static 静态资源可达，
以及已有 API（/health、/chat）未被 M5 改动破坏（/chat 用假 Agent 桩）。
"""
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


class FakeAgent:
    """假人格 Agent：固定回复，验证 /chat 路由未被改动。"""

    def __init__(self, reply: str = "嗯嗯，我在呢，陪你聊聊～") -> None:
        self.reply = reply

    def chat(self, user_input: str, session_id=None):
        return self.reply, session_id or "fake-sid-web"


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
