"""长期记忆（M3/M3.5）：SQLite 持久化，跨会话"记得用户"。

记忆类型：
- fact: 用户事实（姓名/喜好/烦恼/身份）——画像记忆
- topic: 话题/事件（聊过什么）

设计：轻量可靠（SQLite 持久化 + 关键词检索），离线可跑；
M3.5（WO-20260816-19）：向量检索升级——独立新表 memory_embeddings 存 embedding（不改
既有 memories 表结构，旧数据按需 lazy 补向量），新增 retrieve_semantic（余弦相似度）与
retrieve_fused（语义+关键词加权融合，权重可配置），既有关键词检索接口行为不变；
线程模型：每次操作独立短连接（连接只在创建它的线程内使用，天然线程安全，
适配 FastAPI 同步端点跑在线程池 + 模块级单例 Agent 的模型）。
"""
import logging
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.config import CONFIG
from app.memory.embeddings import (
    EmbeddingError,
    OllamaEmbedder,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "memory.db",
)

# M3.5：单次语义检索 lazy 补向量上限（避免大库离线迁移卡死在线检索）
_BACKFILL_LIMIT = 50


class LongTermMemory:
    """长期记忆：跨会话持久化，写入/检索用户事实与话题。

    线程安全说明：本类不持有跨线程连接。每个公开方法都在调用线程内
    打开独立短连接、用完即关，因此可以在 FastAPI 线程池中被并发调用。
    """

    def __init__(self, db_path: str = DB_PATH,
                 embedder: Optional[OllamaEmbedder] = None,
                 auto_backfill: Optional[bool] = None,
                 semantic_threshold: Optional[float] = None) -> None:
        """长期记忆存储。

        :param db_path: SQLite 文件路径（默认 data/memory.db）
        :param embedder: 向量生成器（None=不向量化，语义检索/融合自动降级为关键词；
            由总控后续在 Agent 注入层统一挂载 OllamaEmbedder）
        :param auto_backfill: 语义检索时对无向量旧数据 lazy 补向量（默认取配置）
        :param semantic_threshold: 语义相似度阈值（默认取配置 0.35）
        """
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self._embedder = embedder
        self._auto_backfill = CONFIG.memory_auto_backfill if auto_backfill is None else auto_backfill
        self._semantic_threshold = (
            semantic_threshold if semantic_threshold is not None else CONFIG.memory_semantic_threshold
        )
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
                # M3.5：向量存储——独立新表，不改既有 memories 表结构；
                # 旧数据无向量，按需 lazy 补（见 retrieve_semantic）。
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS memory_embeddings (
                        memory_id TEXT PRIMARY KEY,
                        embedding BLOB NOT NULL,
                        model TEXT NOT NULL,
                        updated_at TEXT NOT NULL
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
        # M3.5：落库后尽力生成向量（失败不阻断记忆写入，语义检索时按需 lazy 补）
        if self._embedder is not None:
            try:
                self._store_embedding(mid, self._embedder.embed(content))
            except EmbeddingError as exc:
                logger.warning("记忆已落库，但 embedding 生成失败（无向量，可 lazy 补）: %s", exc)
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

    def clear(self) -> int:
        """清空全部记忆（memories 与 memory_embeddings 表），保留表结构，返回删除条数。

        M5.1（WO-20260816-22）：供 DELETE /memory 调用；不触碰任何检索逻辑。
        """
        with closing(self._connect()) as conn:
            with conn:
                n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                conn.execute("DELETE FROM memories")
                conn.execute("DELETE FROM memory_embeddings")
                return int(n)

    # ---------- M3.5：向量存储（独立新表，不改 memories 结构） ----------

    def _store_embedding(self, memory_id: str, vector: List[float]) -> None:
        """写入/覆盖一条记忆的 embedding（float32 BLOB）。"""
        model = getattr(self._embedder, "model", "unknown") if self._embedder else "unknown"
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO memory_embeddings (memory_id, embedding, model, updated_at) "
                    "VALUES (?,?,?,?) "
                    "ON CONFLICT(memory_id) DO UPDATE SET "
                    "embedding=excluded.embedding, model=excluded.model, updated_at=excluded.updated_at",
                    (memory_id, pack_vector(vector), model,
                     datetime.now().isoformat(timespec="seconds")),
                )

    def _get_embedding(self, memory_id: str) -> Optional[List[float]]:
        """读取一条记忆的 embedding；无则返回 None。"""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT embedding FROM memory_embeddings WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return unpack_vector(row[0]) if row else None

    # ---------- M3.5：语义检索（余弦相似度） ----------

    def retrieve_semantic(self, query: str, k: int = 5, days: int = 90,
                          threshold: Optional[float] = None) -> List[Dict[str, object]]:
        """语义检索：query embedding 与库内记忆向量余弦相似度，返回 top-k。

        - 无 embedder 或 query 向量生成失败：记警告并返回 []（调用方降级为关键词检索）；
        - 旧数据无向量：auto_backfill 开启时逐个 lazy 补向量（上限 _BACKFILL_LIMIT 条），
          避免全量离线迁移；超过上限的剩余旧记忆跳过；
        - 返回结构与 retrieve 一致（score=余弦相似度，低于 threshold 不返回）。
        """
        thr = threshold if threshold is not None else self._semantic_threshold
        if self._embedder is None:
            logger.warning("retrieve_semantic 无 embedder，返回空（请用 retrieve/retrieve_fused 兜底）")
            return []
        try:
            qv = self._embedder.embed(query)
        except EmbeddingError as exc:
            logger.warning("query embedding 生成失败，语义检索降级为空: %s", exc)
            return []
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, kind, content, source_session, created_at FROM memories "
                "WHERE created_at >= ? ORDER BY created_at DESC, rowid DESC",
                (cutoff,),
            ).fetchall()
            emb_rows = conn.execute(
                "SELECT e.memory_id, e.embedding FROM memory_embeddings e "
                "JOIN memories m ON m.id = e.memory_id WHERE m.created_at >= ?",
                (cutoff,),
            ).fetchall()
        emb_map = {eid: unpack_vector(blob) for eid, blob in emb_rows}
        scored: List[Dict[str, object]] = []
        backfilled = 0
        for r in rows:
            mid = r[0]
            vec = emb_map.get(mid)
            if vec is None:
                if not (self._auto_backfill and backfilled < _BACKFILL_LIMIT):
                    continue  # 无向量且不允许/超上限：跳过（不崩，旧数据兼容）
                try:
                    vec = self._embedder.embed(r[2])
                    self._store_embedding(mid, vec)
                    backfilled += 1
                except EmbeddingError as exc:
                    logger.warning("lazy 补向量失败，跳过该记忆: %s", exc)
                    continue
            sim = cosine_similarity(qv, vec)
            if sim >= thr:
                scored.append({
                    "id": mid, "kind": r[1], "content": r[2],
                    "source": r[3], "created_at": r[4], "score": sim,
                })
        scored.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
        return scored[:k]

    # ---------- M3.5：检索融合（语义 + 关键词，权重可配置） ----------

    def retrieve_fused(self, query: str, limit: int = 5, days: int = 90,
                       semantic_weight: Optional[float] = None,
                       keyword_weight: Optional[float] = None) -> List[Dict[str, object]]:
        """检索融合：关键词结果 + 语义结果合并去重、加权排序（默认语义 0.6 / 关键词 0.4）。

        - 关键词分按窗口内最大值归一化；语义分取 max(0, 相似度)；
        - 无 embedder 时退化为纯关键词检索（行为与 retrieve 一致，向后兼容）；
        - 返回结构与 retrieve 一致。
        """
        sem_w = semantic_weight if semantic_weight is not None else CONFIG.memory_fusion_semantic_weight
        kw_w = keyword_weight if keyword_weight is not None else CONFIG.memory_fusion_keyword_weight
        kw_hits = self.retrieve(query, limit=limit * 2, days=days)
        if self._embedder is None:
            return kw_hits[:limit]
        sem_hits = self.retrieve_semantic(query, k=limit * 2, days=days)
        kw_max = max((float(h["score"]) for h in kw_hits), default=0.0) or 1.0
        merged: Dict[str, Dict[str, object]] = {}
        for h in kw_hits:
            d = dict(h)
            d["score"] = kw_w * (float(h["score"]) / kw_max)
            d["_sem"] = 0.0
            merged[h["id"]] = d
        for h in sem_hits:
            d = merged.get(h["id"])
            if d is None:
                d = dict(h)
                d["score"] = 0.0
                merged[h["id"]] = d
            d["_sem"] = float(h["score"])
            d["score"] = float(d["score"]) + sem_w * max(0.0, float(h["score"]))
        results = list(merged.values())
        results.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
        for d in results:
            d.pop("_sem", None)
        return results[:limit]

    def close(self) -> None:
        """兼容旧 API：短连接模型下无持久连接，无需关闭。"""
