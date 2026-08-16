"""语音合成模块（TTS）：edge-tts 现成音色，默认中文女声（晓晓 zh-CN-XiaoxiaoNeural）。

说明：
- edge-tts 是微软 Edge 在线朗读服务（免费），合成时需联网；网络不可用时由上层如实上报，
  不假装成功（可降级为本地 TTS 或文本回退）。
- 惰性加载 edge_tts：模块顶层不 import，离线测试注入假合成器即可。
- 只输出合成音频文件，不保存/不记忆用户语音原始数据；不使用任何未授权音色（禁止声音克隆）。
- M4.1：LRU 合成缓存。key = 文本 + 音色 + 语速（sha1），命中磁盘缓存直接复用音频，
  跳过在线合成（延迟从 ~1.5s 降到毫秒级）；内存 LRU 控制热条目，磁盘文件保留可复用。
"""
import asyncio
import hashlib
import os
import shutil
import threading
import time
from collections import OrderedDict
from typing import Optional

from app.config import CONFIG


def _run_coroutine(coro_factory):
    """执行异步协程：无运行中事件循环时直接 asyncio.run；
    已有运行中事件循环（如 FastAPI async 端点内）时在新线程跑独立循环，避免
    "asyncio.run() cannot be called from a running event loop"。

    :param coro_factory: 返回协程对象的零参函数
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    box: dict = {}

    def _target() -> None:
        try:
            box["value"] = asyncio.run(coro_factory())
        except BaseException as exc:  # noqa: BLE001 - 跨线程回传异常
            box["error"] = exc

    thread = threading.Thread(target=_target, name="edge-tts-synth")
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


class EdgeTTS:
    """edge-tts 封装：文本合成中文女声音频（MP3），带 LRU 磁盘缓存。"""

    def __init__(
        self,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        tts_cls=None,
        cache_dir: Optional[str] = None,
        cache_size: Optional[int] = None,
    ) -> None:
        """初始化合成器。

        :param voice: edge-tts 音色名（默认中文女声 zh-CN-XiaoxiaoNeural）
        :param rate: 语速（如 "+0%" / "-10%"）
        :param tts_cls: 合成器类（测试注入假实现；None 时惰性加载 edge_tts.Communicate）
        :param cache_dir: 合成缓存目录（默认 CONFIG.tts_cache_dir）
        :param cache_size: 内存 LRU 热条目上限（默认 CONFIG.tts_cache_size）
        """
        self._voice = voice or CONFIG.tts_voice
        self._rate = rate or CONFIG.tts_rate
        self._tts_cls = tts_cls
        self._cache_dir = cache_dir or CONFIG.tts_cache_dir
        self._cache_size = cache_size if cache_size is not None else CONFIG.tts_cache_size
        # LRU：key(sha1) -> 缓存文件绝对路径；最近使用放末尾，超限淘汰最久未用
        self._lru: "OrderedDict[str, str]" = OrderedDict()
        self._last_latency_ms: float = 0.0
        self._last_cached_hit: bool = False

    # ---------- 缓存 ----------

    def _cache_key(self, text: str) -> str:
        """缓存 key：文本 + 音色 + 语速 的 sha1（文本本身可含任意字符，key 保证安全文件名）。"""
        raw = f"{text}|{self._voice}|{self._rate}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def _cache_path(self, key: str) -> str:
        """缓存文件绝对路径（目录 + key.mp3）。"""
        return os.path.join(os.path.abspath(self._cache_dir), f"{key}.mp3")

    def _cache_get(self, key: str) -> Optional[str]:
        """命中返回缓存文件路径并更新 LRU 顺序；未命中返回 None。"""
        path = self._cache_path(key)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            self._lru.pop(key, None)
            self._lru[key] = path
            return path
        return None

    def _cache_put(self, key: str, src_path: str) -> str:
        """把合成结果复制进缓存目录并维护 LRU，返回缓存文件路径。"""
        os.makedirs(self._cache_dir, exist_ok=True)
        dst = self._cache_path(key)
        shutil.copyfile(src_path, dst)
        self._lru[key] = dst
        while len(self._lru) > self._cache_size:
            self._lru.popitem(last=False)  # 淘汰最久未用（磁盘文件保留，再次命中仍复用）
        return dst

    # ---------- 合成 ----------

    def synthesize(self, text: str, out_path: str) -> str:
        """把文本合成为 MP3 写入 out_path，返回 out_path。

        同文本（同音色/语速）再次合成时命中缓存：直接复制缓存音频，跳过在线合成。

        :raises ValueError: 文本为空
        :raises RuntimeError: edge-tts 合成失败（多为网络不可用）
        """
        text = text.strip()
        if not text:
            raise ValueError("合成文本不能为空")
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        start = time.perf_counter()

        key = self._cache_key(text)
        cached = self._cache_get(key)
        if cached is not None:
            shutil.copyfile(cached, out_path)
            self._last_latency_ms = round((time.perf_counter() - start) * 1000, 1)
            self._last_cached_hit = True
            return out_path

        try:
            if self._tts_cls is None:
                import edge_tts

                tts_cls = edge_tts.Communicate
            else:
                tts_cls = self._tts_cls

            def _save():
                communicate = tts_cls(text, self._voice, rate=self._rate)
                return communicate.save(out_path)

            _run_coroutine(_save)
        except Exception as exc:
            raise RuntimeError(f"edge-tts 合成失败（需联网访问微软 Edge 朗读服务）: {exc}") from exc
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("edge-tts 合成失败：未生成有效音频文件")
        self._cache_put(key, out_path)
        self._last_latency_ms = round((time.perf_counter() - start) * 1000, 1)
        self._last_cached_hit = False
        return out_path

    @property
    def last_latency_ms(self) -> float:
        """最近一次合成的耗时（毫秒），供延迟基线统计。"""
        return self._last_latency_ms

    @property
    def last_cached_hit(self) -> bool:
        """最近一次合成是否命中缓存（跳过在线合成）。"""
        return self._last_cached_hit


class PiperTTS:
    """本地离线 TTS（M4.3）：piper 中文音色，无网络依赖、稳定。

    - 模型：data/models/piper/zh_CN-huayan-medium.onnx（+ .onnx.json），
      由 piper-tts 包 + espeak-ng 数据驱动（piper 库首次运行自动准备）。
    - 实测：40 字内合成约 0.3-0.4s（CPU），远快于 edge-tts 在线（1.6s+ 且可能断连）。
    - 惰性加载：构造时才加载模型（不拖慢 import）；测试可注入假 voice。
    """

    def __init__(self, model_path: str = "data/models/piper/zh_CN-huayan-medium.onnx",
                 voice=None) -> None:
        """初始化；voice 为已加载的 piper 语音对象（测试注入用）。"""
        self._model_path = model_path
        self._voice = voice
        self._last_latency_ms: float = 0.0

    def _ensure_voice(self):
        """惰性加载 piper 语音（首次合成时）。"""
        if self._voice is None:
            from piper import PiperVoice

            self._voice = PiperVoice.load(self._model_path, config_path=self._model_path + ".json")

    def synthesize(self, text: str, out_path: str) -> str:
        """把文本合成为 WAV 写入 out_path，返回 out_path。"""
        import wave

        text = text.strip()
        if not text:
            raise ValueError("合成文本不能为空")
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        start = time.perf_counter()
        try:
            self._ensure_voice()
            with wave.open(out_path, "wb") as wf:
                self._voice.synthesize_wav(text, wf)
        except Exception as exc:
            raise RuntimeError(f"piper 本地合成失败（检查模型 data/models/piper）: {exc}") from exc
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("piper 合成失败：未生成有效音频文件")
        self._last_latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return out_path

    @property
    def last_latency_ms(self) -> float:
        """最近一次合成的耗时（毫秒），供延迟基线统计。"""
        return self._last_latency_ms

    @property
    def last_cached_hit(self) -> bool:
        """piper 后端无缓存（本地合成已足够快）。"""
        return False
