"""副作用动作审计与原子防重放（SQLite）。"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTION_AUDIT_DB = os.getenv(
    "ACTION_AUDIT_DB_PATH", str(_PROJECT_ROOT / "data" / "action_audit.db")
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_arguments(arguments: dict) -> str:
    """稳定哈希参数；审计库只保存哈希，不保存完整参数。"""
    canonical = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _sha256(canonical)


class ActionAuditStore:
    """短连接 SQLite 审计账本；pending→running 是唯一执行 claim。"""

    def __init__(self, db_path: str = DEFAULT_ACTION_AUDIT_DB) -> None:
        self.db_path = str(db_path)
        self._uri = False
        self._anchor: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self.db_path = f"file:action-audit-{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._uri = True
            self._anchor = self._open()

    @staticmethod
    def session_hash(session_id: str) -> str:
        return _sha256(session_id)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5, uri=self._uri)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _connect(self) -> sqlite3.Connection:
        if not self._uri:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        return self._open()

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS action_audit (
                action_id TEXT PRIMARY KEY,
                session_hash TEXT NOT NULL,
                source TEXT NOT NULL,
                tool TEXT NOT NULL,
                args_hash TEXT NOT NULL,
                target_summary TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            )
            """
        )

    def stage(self, session_id: str, source: str, tool: str, arguments: dict,
              target_summary: str, ttl_seconds: int = 120) -> dict:
        """登记待确认动作；数据库/写入失败直接抛出，由调用方关闭执行。"""
        now = time.time()
        record = {
            "action_id": uuid.uuid4().hex,
            "session_hash": self.session_hash(session_id),
            "source": source,
            "tool": tool,
            "args_hash": hash_arguments(arguments),
            "target_summary": target_summary,
            "status": "pending",
            "created_at": now,
            "expires_at": now + ttl_seconds,
        }
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO action_audit (
                    action_id, session_hash, source, tool, args_hash, target_summary,
                    status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(record[k] for k in (
                    "action_id", "session_hash", "source", "tool", "args_hash",
                    "target_summary", "status", "created_at", "expires_at"
                )),
            )
        return record

    def claim(self, action_id: str, session_id: str, tool: str,
              arguments: dict, now: Optional[float] = None) -> bool:
        """原子领取一次 pending；过期或身份/参数不匹配均关闭该动作。"""
        claimed_at = time.time() if now is None else now
        expected = (self.session_hash(session_id), tool, hash_arguments(arguments))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT session_hash, tool, args_hash, status, expires_at "
                "FROM action_audit WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None or row["status"] != "pending":
                return False
            if row["expires_at"] < claimed_at:
                conn.execute(
                    "UPDATE action_audit SET status='expired', finished_at=? "
                    "WHERE action_id=? AND status='pending'", (claimed_at, action_id)
                )
                return False
            if (row["session_hash"], row["tool"], row["args_hash"]) != expected:
                conn.execute(
                    "UPDATE action_audit SET status='failed', finished_at=? "
                    "WHERE action_id=? AND status='pending'", (claimed_at, action_id)
                )
                return False
            updated = conn.execute(
                "UPDATE action_audit SET status='running', started_at=? "
                "WHERE action_id=? AND status='pending'", (claimed_at, action_id)
            ).rowcount
            return updated == 1

    def finish(self, action_id: str, succeeded: bool,
               now: Optional[float] = None) -> bool:
        """只允许 running 结束；running 不会被重新 claim。"""
        finished_at = time.time() if now is None else now
        status = "succeeded" if succeeded else "failed"
        with self._connect() as conn:
            return conn.execute(
                "UPDATE action_audit SET status=?, finished_at=? "
                "WHERE action_id=? AND status='running'",
                (status, finished_at, action_id),
            ).rowcount == 1

    def cancel(self, action_id: str, now: Optional[float] = None) -> bool:
        finished_at = time.time() if now is None else now
        with self._connect() as conn:
            return conn.execute(
                "UPDATE action_audit SET status='canceled', finished_at=? "
                "WHERE action_id=? AND status='pending'", (finished_at, action_id)
            ).rowcount == 1

    def expire(self, action_id: str, now: Optional[float] = None) -> bool:
        finished_at = time.time() if now is None else now
        with self._connect() as conn:
            return conn.execute(
                "UPDATE action_audit SET status='expired', finished_at=? "
                "WHERE action_id=? AND status='pending'", (finished_at, action_id)
            ).rowcount == 1

    def get(self, action_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM action_audit WHERE action_id=?", (action_id,)
            ).fetchone()
        return dict(row) if row else None
