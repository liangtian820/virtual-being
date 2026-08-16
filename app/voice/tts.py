"""语音合成模块（TTS）：edge-tts 现成音色，默认中文女声（晓晓 zh-CN-XiaoxiaoNeural）。

说明：
- edge-tts 是微软 Edge 在线朗读服务（免费），合成时需联网；网络不可用时由上层如实上报，
  不假装成功（可降级为本地 TTS 或文本回退）。
- 惰性加载 edge_tts：模块顶层不 import，离线测试注入假合成器即可。
- 只输出合成音频文件，不保存/不记忆用户语音原始数据；不使用任何未授权音色（禁止声音克隆）。
"""
import asyncio
import os
import threading
import time
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
    """edge-tts 封装：文本合成中文女声音频（MP3 格式）。"""

    def __init__(self, voice: Optional[str] = None, rate: Optional[str] = None, tts_cls=None) -> None:
        """初始化合成器。

        :param voice: edge-tts 音色名（默认中文女声 zh-CN-XiaoxiaoNeural）
        :param rate: 语速（如 "+0%" / "-10%"）
        :param tts_cls: 合成器类（测试注入假实现；None 时惰性加载 edge_tts.Communicate）
        """
        self._voice = voice or CONFIG.tts_voice
        self._rate = rate or CONFIG.tts_rate
        self._tts_cls = tts_cls
        self._last_latency_ms: float = 0.0

    def synthesize(self, text: str, out_path: str) -> str:
        """把文本合成为 MP3 写入 out_path，返回 out_path。

        :raises ValueError: 文本为空
        :raises RuntimeError: edge-tts 合成失败（多为网络不可用）
        """
        text = text.strip()
        if not text:
            raise ValueError("合成文本不能为空")
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        start = time.perf_counter()
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
        self._last_latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return out_path

    @property
    def last_latency_ms(self) -> float:
        """最近一次合成的耗时（毫秒），供延迟基线统计。"""
        return self._last_latency_ms
