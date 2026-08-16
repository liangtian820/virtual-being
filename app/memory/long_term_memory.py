"""长期记忆（M3）：SQLite 持久化，跨会话"记得用户"。

记忆类型：
- fact: 用户事实（姓名/喜好/烦恼/身份）——画像记忆
- topic: 话题/事件（聊过什么）

设计：轻量可靠（SQLite 持久化 + 关键词检索），离线可跑；
后续可由数据/知识工程师（A-03e）升级为向量库 + 记忆治理。
"""
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "memory.db",
)


class LongTermMemory:
    """长期记忆：跨会话持久化，写入/检索用户事实与话题。"""

    def __init__(self, db_path: str = DB_PATH) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                source_session TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def add(self, kind: str, content: str, source_session: Optional[str] = None) -> str:
        """写入一条记忆，返回记忆 id。"""
        mid = uuid.uuid4().hex[:8]
        self._conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?)",
            (mid, kind, content.strip(), source_session, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()
        return mid

    def retrieve(self, query: str, limit: int = 5, days: int = 90) -> List[Dict[str, object]]:
        """按关键词检索相关记忆（简单打分，时间窗内）。"""
        tokens = [t for t in re.split(r"[\s，。？、！]+", query.lower()) if len(t) >= 2]
        if not tokens and query.strip():
            tokens = [query.strip()]  # 短查询（如单字"猫"）整体作为 token
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
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
        rows = self._conn.execute(
            "SELECT id, kind, content, source_session, created_at FROM memories "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"id": r[0], "kind": r[1], "content": r[2], "source": r[3], "created_at": r[4]} for r in rows
        ]

    def count(self) -> int:
        """记忆条数（统计/测试用）。"""
        return self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def close(self) -> None:
        """关闭连接。"""
        self._conn.close()
