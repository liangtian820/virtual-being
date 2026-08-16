"""记忆 API（M5.1，WO-20260816-22）离线测试：GET /memory 列示、DELETE /memory 清空。

不依赖网络/模型：记忆库用临时文件，Agent 用带 _memory_long 的假桩。
"""
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.memory.long_term_memory import LongTermMemory


class _FakeAgentWithMemory:
    """假人格 Agent：只提供 _memory_long，验证记忆 API 契约。"""

    def __init__(self, store: LongTermMemory) -> None:
        self._memory_long = store

    def chat(self, user_input: str, session_id=None):
        return "ok", session_id or "sid"


def test_memory_list_api(monkeypatch, tmp_path) -> None:
    """GET /memory 应列示全部记忆（摘要级：含 id/kind/content/created_at）。"""
    store = LongTermMemory(db_path=str(tmp_path / "mem1.db"))
    store.add("fact", "用户喜欢猫，家里养了一只橘猫", source_session="s1")
    store.add("topic", "周末想去爬山", source_session="s2")
    monkeypatch.setattr(main_module, "_agent", _FakeAgentWithMemory(store))
    try:
        resp = TestClient(app).get("/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        kinds = {m["kind"] for m in data["memories"]}
        assert kinds == {"fact", "topic"}
        for m in data["memories"]:
            assert "id" in m and "content" in m and "created_at" in m
            assert "source" not in m  # 不暴露内部元数据
        assert all(len(m["content"]) <= 60 for m in data["memories"])  # 摘要级截断
    finally:
        store.close()


def test_memory_list_limit(monkeypatch, tmp_path) -> None:
    """GET /memory?limit=N 应限制返回条数。"""
    store = LongTermMemory(db_path=str(tmp_path / "mem2.db"))
    for i in range(5):
        store.add("topic", f"内容{i}", source_session="s")
    monkeypatch.setattr(main_module, "_agent", _FakeAgentWithMemory(store))
    try:
        resp = TestClient(app).get("/memory", params={"limit": 3})
        assert resp.status_code == 200
        assert resp.json()["count"] == 3
    finally:
        store.close()


def test_memory_delete_requires_confirm(monkeypatch, tmp_path) -> None:
    """DELETE /memory 不带 confirm=1 应拒绝（400），记忆不被清空。"""
    store = LongTermMemory(db_path=str(tmp_path / "mem3.db"))
    store.add("fact", "用户喜欢猫", source_session="s")
    monkeypatch.setattr(main_module, "_agent", _FakeAgentWithMemory(store))
    try:
        resp = TestClient(app).delete("/memory")
        assert resp.status_code == 400
        assert "confirm" in resp.json()["detail"]
        assert store.count() == 1  # 未被清空
    finally:
        store.close()


def test_memory_delete_with_confirm(monkeypatch, tmp_path) -> None:
    """DELETE /memory?confirm=1 应清空并返回删除条数（留痕）。"""
    store = LongTermMemory(db_path=str(tmp_path / "mem4.db"))
    store.add("fact", "用户喜欢猫", source_session="s")
    store.add("topic", "周末想去爬山", source_session="s")
    monkeypatch.setattr(main_module, "_agent", _FakeAgentWithMemory(store))
    try:
        resp = TestClient(app).delete("/memory", params={"confirm": "1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["deleted"] == 2
        assert store.count() == 0
        # 清空后再次列示应为空
        resp2 = TestClient(app).get("/memory")
        assert resp2.json()["count"] == 0
    finally:
        store.close()
