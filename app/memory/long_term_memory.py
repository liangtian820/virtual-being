"""长期记忆（M3）：SQLite 持久化，跨会话"记得用户"。

记忆类型：
- fact: 用户事实（姓名/喜好/烦恼/身份）——画像记忆
- topic: 话题/事件（聊过什么）

设计：轻量可靠（SQLite 持久化 + 关键词检索），离线可跑；
线程模型：每次操作独立短连接（连接只在创建它的线程内使用，天然线程安全，
适配 FastAPI 同步端点跑在线程池 + 模块级单例 Agent 的模型）；
后续可由数据/知识工程师（A-03e）升级为向量库 + 记忆治理（含检索升级 jieba/向量、uuid 碰撞治理）。
"""
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from typing import Dict, List, Optional

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "memory.db",
)


class LongTermMemory:
    """长期记忆：跨会话持久化，写入/检索用户事实与话题。

    线程安全说明：本类不持有跨线程连接。每个公开方法都在调用线程内
    打开独立短连接、用完即关，因此可以在 FastAPI 线程池中被并发调用。
    """

    def __init__(self, db_path: str = DB_PATH) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        content TEXT NOT NULL,
                        source_session TEXT,
                        created_at TEXT NOT NULL
                    )"""
                )

    def _connect(self) -> sqlite3.Connection:
        """打开一个短连接（调用线程内创建/使用/关闭）。

        timeout=5 秒避免并发写时立即抛 "database is locked"（单用户低频足够）。
        """
        return sqlite3.connect(self._db_path, timeout=5)

    def add(self, kind: str, content: str, source_session: Optional[str] = None) -> str:
        """写入一条记忆，返回记忆 id。

        去重（P3-1）：同 (kind, content) 已存在时不重复新增，直接返回已有 id。
        并发安全（M4 补丁）：查重 + 插入放进 BEGIN IMMEDIATE 写事务，串行化
        check-then-insert，避免多线程同时写同内容时偶发重复插入（TOCTOU 竞态，
        曾被 test_cross_thread_usage 偶发命中 assert 11 == 9）。
        """
        content = content.strip()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")  # 获取写锁（timeout=5 兜底）
            row = conn.execute(
                "SELECT id FROM memories WHERE kind = ? AND content = ?",
                (kind, content),
            ).fetchone()
            if row is not None:
                conn.commit()
                return row[0]
            mid = uuid.uuid4().hex[:8]
            conn.execute(
                "INSERT INTO memories VALUES (?,?,?,?,?)",
                (mid, kind, content, source_session, datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return mid

    def retrieve(self, query: str, limit: int = 5, days: int = 90) -> List[Dict[str, object]]:
        """按关键词检索相关记忆（简单打分，时间窗内）。"""
        tokens = [t for t in re.split(r"[\s，。？、！]+", query.lower()) if len(t) >= 2]
        if not tokens and query.strip():
            tokens = [query.strip()]  # 短查询（如单字"猫"）整体作为 token
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, kind, content, source_session, created_at FROM memories "
                "WHERE created_at >= ? ORDER BY created_at DESC, rowid DESC",
                (cutoff,),
            ).fetchall()
        scored: List[Dict[str, object]] = []
        for r in rows:
            hay = (r[2] + " " + r[1]).lower()
            score = sum(1 for t in tokens if t in hay)
            if score > 0:
                scored.append({
                    "id": r[0], "kind": r[1], "content": r[2],
                    "source": r[3], "created_at": r[4], "score": score,
                })
        scored.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
        return scored[:limit]

    def recent(self, limit: int = 3) -> List[Dict[str, object]]:
        """最近记忆（新会话注入兜底用）。"""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, kind, content, source_session, created_at FROM memories "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "kind": r[1], "content": r[2], "source": r[3], "created_at": r[4]} for r in rows
        ]

    def count(self) -> int:
        """记忆条数（统计/测试用）。"""
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def close(self) -> None:
        """兼容旧 API：短连接模型下无持久连接，无需关闭。"""
