"""A2 动作审计账本：最小字段、状态机与并发 claim。"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.tools.action_audit import ActionAuditStore, hash_arguments


def test_default_audit_path_is_project_rooted(monkeypatch):
    import app.tools.action_audit as module

    expected = Path(module.__file__).resolve().parents[2] / "data" / "action_audit.db"
    assert Path(module.DEFAULT_ACTION_AUDIT_DB) == expected
    monkeypatch.chdir(Path(module.__file__).resolve().parents[2].parent)
    store = ActionAuditStore()
    assert Path(store.db_path) == expected


def test_stage_stores_hashes_not_full_arguments(tmp_path):
    db = tmp_path / "audit.db"
    store = ActionAuditStore(str(db))
    args = {"path": "30 · 项目/目标.md", "content": "敏感测试正文-不可入账本"}

    staged = store.stage("private-session", "llm", "obsidian_vault_write", args, "目标.md")
    record = store.get(staged["action_id"])

    assert record is not None
    assert record["session_hash"] == store.session_hash("private-session")
    assert record["args_hash"] == hash_arguments(args)
    assert "private-session" not in record.values()
    assert "content" not in record and "arguments" not in record
    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(action_audit)")}
    assert columns == {
        "action_id", "session_hash", "source", "tool", "args_hash",
        "target_summary", "status", "created_at", "expires_at",
        "started_at", "finished_at",
    }
    assert "敏感测试正文-不可入账本".encode("utf-8") not in db.read_bytes()


def test_lifecycle_and_hash_mismatch_are_reviewable(tmp_path):
    store = ActionAuditStore(str(tmp_path / "audit.db"))
    args = {"text": "提醒我喝水"}

    bad = store.stage("s1", "deterministic", "add_schedule", args, "喝水")
    assert not store.claim(bad["action_id"], "s1", "add_schedule", {"text": "篡改"})
    assert store.get(bad["action_id"])["status"] == "failed"

    ok = store.stage("s1", "deterministic", "add_schedule", args, "喝水")
    assert store.claim(ok["action_id"], "s1", "add_schedule", args)
    assert not store.claim(ok["action_id"], "s1", "add_schedule", args)
    assert store.finish(ok["action_id"], succeeded=True)
    assert store.get(ok["action_id"])["status"] == "succeeded"

    canceled = store.stage("s1", "llm", "save_plan", {"goal": "g"}, "g")
    assert store.cancel(canceled["action_id"])
    assert store.get(canceled["action_id"])["status"] == "canceled"

    expired = store.stage("s1", "llm", "save_plan", {"goal": "g"}, "g")
    assert store.expire(expired["action_id"])
    assert store.get(expired["action_id"])["status"] == "expired"

    failed = store.stage("s1", "llm", "save_plan", {"goal": "g"}, "g")
    assert store.claim(failed["action_id"], "s1", "save_plan", {"goal": "g"})
    assert store.finish(failed["action_id"], succeeded=False)
    assert store.get(failed["action_id"])["status"] == "failed"


def test_two_concurrent_claims_only_one_wins(tmp_path):
    store = ActionAuditStore(str(tmp_path / "audit.db"))
    args = {"text": "提醒我喝水"}
    staged = store.stage("same", "deterministic", "add_schedule", args, "喝水")

    def claim_once(_):
        return store.claim(staged["action_id"], "same", "add_schedule", args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim_once, range(2)))

    assert sorted(results) == [False, True]
    assert store.get(staged["action_id"])["status"] == "running"
    assert not store.claim(staged["action_id"], "same", "add_schedule", args)
