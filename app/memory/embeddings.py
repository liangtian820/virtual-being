"""记忆向量化（M3.5，WO-20260816-19）：Ollama embedding + jieba 中文分词 + 余弦相似度。

- OllamaEmbedder：本地 all-minilm 生成文本 embedding（HTTP 调用，带超时；兼容新旧端点）。
- segment()：jieba 中文分词（用于 query/文本预处理，过滤标点/空白）。
- cosine_similarity()：余弦相似度。
- pack_vector()/unpack_vector()：float32 BLOB 打包（SQLite 向量列存储用）。

设计：全部离线可降级——embedding 服务不可用时抛 EmbeddingError，由调用方（记忆层）捕获后
降级为纯关键词检索，不阻断记忆读写。
"""
import logging
import math
import re
import struct
import time
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# 标点/空白/符号（\W 在 Unicode 模式下含中文标点；汉字属于 \w 不被过滤）
_PUNCT_RE = re.compile(r"^[\s\W_]+$")

# jieba 首次加载需建前缀词典（约 0.6s），懒加载 + 结果缓存避免无关路径被拖慢
_seg_cache: dict = {}


def segment(text: str) -> List[str]:
    """jieba 中文分词：返回过滤标点/空白后的词列表（含单字词，如『猫』）。

    分词结果用于 query/文本预处理；语义 embedding 仍用原句（all-minilm 为句子模型）。
    """
    import jieba  # 懒加载：仅记忆向量路径使用

    if text not in _seg_cache:
        _seg_cache[text] = [w for w in jieba.lcut(text) if w.strip() and not _PUNCT_RE.match(w)]
    return list(_seg_cache[text])


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """余弦相似度（[0, 1] 归一后的 [-1, 1]）。向量为空/不等长返回 0.0，不抛异常。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def pack_vector(vector: List[float]) -> bytes:
    """float32 小端 BLOB 打包（4 字节/维；384 维 ≈ 1.5KB），供 SQLite 存储。"""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> List[float]:
    """解包 float32 BLOB → float 列表。"""
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


class EmbeddingError(RuntimeError):
    """Embedding 服务不可用/生成失败（调用方负责降级）。"""


def _is_retryable(exc: EmbeddingError) -> bool:
    """网络/超时类失败可重试（HTTP 业务错误不重试）。"""
    cause = exc.__cause__
    return isinstance(cause, requests.RequestException)


class OllamaEmbedder:
    """Ollama 本地 embedding 客户端（默认 all-minilm:latest，384 维）。

    端点兼容：优先 /api/embeddings（Ollama <0.5），404 时回退 /api/embed（新端点）。
    失败抛 EmbeddingError（超时/网络/HTTP 错误），不静默。
    """

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "all-minilm:latest", timeout: float = 10.0,
                 retries: int = 1) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._retries = retries

    @property
    def model(self) -> str:
        return self._model

    def embed(self, text: str) -> List[float]:
        """生成文本 embedding；失败抛 EmbeddingError。

        网络/超时类失败重试一次（Ollama 冷启动/瞬时超时常见，0.5s 退避），
        HTTP 业务错误（4xx/5xx）不重试。
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self._retries + 1):
            try:
                return self._embed_once(text)
            except EmbeddingError as exc:
                last_exc = exc
                if attempt < self._retries and _is_retryable(exc):
                    time.sleep(0.5 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def _embed_once(self, text: str) -> List[float]:
        """单次 embedding 调用（优先旧端点，404 回退新端点）。"""
        if not text.strip():
            raise EmbeddingError("空文本无法生成 embedding")
        try:
            resp = requests.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise EmbeddingError(f"Ollama embeddings 调用失败: {exc}") from exc
        if resp.status_code == 404:
            return self._embed_via_new_endpoint(text)
        if resp.status_code >= 400:
            raise EmbeddingError(f"Ollama embeddings HTTP {resp.status_code}: {resp.text[:200]}")
        emb = resp.json().get("embedding")
        if not emb:
            raise EmbeddingError("Ollama /api/embeddings 返回空 embedding")
        return list(emb)

    def _embed_via_new_endpoint(self, text: str) -> List[float]:
        """Ollama >=0.5 新端点 /api/embed（input 数组）。"""
        try:
            resp = requests.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": text},
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                raise EmbeddingError(f"Ollama /api/embed HTTP {resp.status_code}: {resp.text[:200]}")
            embs = resp.json().get("embeddings") or []
        except requests.RequestException as exc:
            raise EmbeddingError(f"Ollama /api/embed 调用失败: {exc}") from exc
        if not embs:
            raise EmbeddingError("Ollama /api/embed 返回空 embeddings")
        return list(embs[0])
