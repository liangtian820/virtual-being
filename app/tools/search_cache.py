"""搜索结果缓存（迭代 6，M6.9，WO-20260816-39）：LRU + TTL + JSON 文件持久化。

背景（总控实测基线 data/m6_6/perf_baseline.json）：
- 知识查询『deepseek harness是什么』中位 38.4s（内置→Wikipedia(8s)→Bing(10s) 串行 + 两阶段 LLM）
- 搜索『帮我搜一下X』中位 29.3s

对 web_search / Wikipedia 按 query 缓存 ~10 分钟（默认 TTL 可配），
重复/近似查询命中缓存 ≤5s；缓存写失败不影响功能（降级为不缓存）。
数据落 data/search_cache/（data/ 已 gitignore）。
"""
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

# 缓存目录：项目根/data/search_cache
_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "search_cache",
)
DEFAULT_CACHE_FILE = os.path.join(_CACHE_DIR, "search_cache.json")
DEFAULT_TTL = 600      # 10 分钟
DEFAULT_MAX_ENTRIES = 200

_lock = threading.Lock()


class SearchCache:
    """LRU + TTL 缓存（内存 OrderedDict + JSON 落盘；线程安全）。"""

    def __init__(self, ttl: int = DEFAULT_TTL, max_entries: int = DEFAULT_MAX_ENTRIES,
                 cache_file: str = DEFAULT_CACHE_FILE) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self.cache_file = cache_file
        self._data: "OrderedDict[str, dict]" = OrderedDict()
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = OrderedDict(raw)
        except Exception:
            self._data = OrderedDict()

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(dict(self._data), f, ensure_ascii=False)
        except Exception:
            pass  # 缓存写失败不影响功能

    # ---------- 读写 ----------

    def get(self, key: str) -> Optional[Any]:
        """命中且未过期 → 返回缓存值；未命中/过期返回 None。"""
        with _lock:
            item = self._data.get(key)
            if item is None:
                return None
            if time.time() - item.get("ts", 0) > self.ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)  # LRU 触达
            return item.get("value")

    def set(self, key: str, value: Any) -> None:
        with _lock:
            self._data[key] = {"ts": time.time(), "value": value}
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
            self._save()

    def clear(self) -> None:
        with _lock:
            self._data = OrderedDict()
            try:
                if os.path.exists(self.cache_file):
                    os.remove(self.cache_file)
            except Exception:
                pass


# 全局单例（与 tool registry 同模式）
search_cache = SearchCache()
