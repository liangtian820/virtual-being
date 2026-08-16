"""语音识别模块（ASR）：基于 faster-whisper 的本地 Whisper 识别，支持中文。

设计要点：
- 惰性加载 faster_whisper：模块顶层不 import 重型库，离线测试可注入假模型实例，无需下载模型文件。
- 模型文件缓存在本机（HuggingFace 缓存或 ASR_MODEL_DIR 指定目录）；只返回文本，不保存/不记忆用户语音原始数据。
- 模型大小 / 设备 / 计算精度 / 语言均可通过环境变量覆盖（ASR_MODEL_SIZE / ASR_DEVICE /
  ASR_COMPUTE_TYPE / ASR_LANGUAGE / ASR_MODEL_DIR），默认 small（RTX 3060 6GB 可跑，int8）。
"""
import os
import time
from typing import Optional

from app.config import CONFIG


class WhisperASR:
    """本地 Whisper 语音识别器（faster-whisper 封装）。

    用法::

        asr = WhisperASR()
        text = asr.transcribe("input.mp3")   # -> "你好呀"
    """

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        language: Optional[str] = None,
        model_dir: Optional[str] = None,
        model=None,
    ) -> None:
        """初始化识别器；传入 model 实例可跳过真实加载（测试/注入用）。

        :param model_size: Whisper 模型大小（tiny/base/small/medium/large-v3）
        :param device: 设备（auto/cuda/cpu）
        :param compute_type: 计算精度（auto/int8/float16/int8_float16）
        :param language: 识别语言（"zh"/"en"/None=自动检测）
        :param model_dir: 模型本地缓存目录（faster-whisper download_root）
        :param model: 已加载的模型实例（注入用）
        """
        self._model_size = model_size or CONFIG.asr_model_size
        self._device = device or CONFIG.asr_device
        self._compute_type = compute_type or CONFIG.asr_compute_type
        self._language = language if language is not None else CONFIG.asr_language
        self._model_dir = model_dir or CONFIG.asr_model_dir
        self._model = model
        self._load_error: Optional[str] = None
        self._last_latency_ms: float = 0.0
        # GPU 不可用（如缺 cuBLAS）时是否已回退 CPU：如实降级，不假装 GPU 可用
        self._used_cpu_fallback: bool = False

    def _local_snapshot_path(self) -> Optional[str]:
        """定位本地模型快照目录（M4.2：直接按路径加载，跳过 huggingface_hub 联网校验）。

        支持两种布局（均无需网络）：
        1. HF 缓存布局：<model_dir>/models--Systran--faster-whisper-<size>/snapshots/*/
        2. 扁平目录：<model_dir> 下直接含 model.bin（手动拷贝/断点续传的目录）
        """
        candidates = []
        if self._model_dir:
            candidates.append(os.path.join(self._model_dir, f"models--Systran--faster-whisper-{self._model_size}"))
            candidates.append(self._model_dir)
        for base in candidates:
            snap_dir = os.path.join(base, "snapshots")
            if os.path.isdir(snap_dir):
                for entry in sorted(os.listdir(snap_dir)):
                    full = os.path.join(snap_dir, entry)
                    if os.path.isfile(os.path.join(full, "model.bin")):
                        return full
            elif os.path.isfile(os.path.join(base, "model.bin")):
                return base
        return None

    def _build_model(self, device: str, compute_type: str):
        """构建 Whisper 模型：优先加载本地快照路径（纯离线秒级），否则走标准下载路径。

        本地快照存在时传入目录路径，faster-whisper 直接读盘，不做任何联网校验——
        避免 huggingface_hub 在直连被墙环境下的超时卡顿（实测预加载被拖到 43s）。
        """
        from faster_whisper import WhisperModel

        snapshot = self._local_snapshot_path()
        if snapshot is not None:
            return WhisperModel(snapshot, device=device, compute_type=compute_type)
        kwargs = {"download_root": self._model_dir} if self._model_dir else {}
        return WhisperModel(self._model_size, device=device, compute_type=compute_type, **kwargs)

    def _ensure_model(self) -> None:
        """确保底层 Whisper 模型已加载（惰性，仅首次识别时执行）。

        device=auto/cuda 但本机缺 CUDA 运行时（如 cublas64_12.dll）时，
        自动回退 CPU + int8 继续识别（降级方案，见 _used_cpu_fallback）。
        """
        if self._model is not None:
            return
        if self._load_error:
            raise RuntimeError(self._load_error)
        try:
            from faster_whisper import WhisperModel  # noqa: F401 - 提前暴露依赖缺失
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            self._load_error = "faster-whisper 未安装，请先执行 pip install faster-whisper"
            raise RuntimeError(self._load_error) from exc
        first_error: Optional[Exception] = None
        try:
            self._model = self._build_model(self._device, self._compute_type)
        except Exception as exc:
            first_error = exc
            # 请求了 GPU（auto/cuda）但加载失败（常见：缺 CUDA/cuBLAS）→ 回退 CPU int8
            if self._device in ("auto", "cuda"):
                try:
                    self._model = self._build_model("cpu", "int8")
                    self._used_cpu_fallback = True
                    return
                except Exception:
                    pass
        if self._model is None:
            self._load_error = (
                "Whisper 模型加载失败（本地模型目录不存在或首次使用需联网下载；"
                "网络受限时可设 HF_ENDPOINT=https://hf-mirror.com）: " + str(first_error or "")
            )
            raise RuntimeError(self._load_error) from first_error

    @property
    def used_cpu_fallback(self) -> bool:
        """是否已回退到 CPU（GPU 不可用的如实降级标记）。"""
        return self._used_cpu_fallback

    def _reload_as_cpu(self) -> None:
        """把模型重载为 CPU + int8（GPU 推理不可用时的如实降级）。"""
        try:
            self._model = self._build_model("cpu", "int8")
            self._used_cpu_fallback = True
        except Exception:
            pass

    def _transcribe_once(self, audio_path: str) -> str:
        """执行一次识别；异常向上抛出（由上层决定是否降级重试）。"""
        segments, _info = self._model.transcribe(
            audio_path,
            language=self._language,
            vad_filter=True,
        )
        return "".join(seg.text.strip() for seg in segments).strip()

    def transcribe(self, audio_path: str) -> str:
        """识别音频文件，返回文本（去除首尾空白；识别失败返回空串不抛错）。

        :param audio_path: 音频文件路径（wav/mp3/m4a 等，由 PyAV 解码）
        """
        self._ensure_model()
        start = time.perf_counter()
        text = ""
        try:
            text = self._transcribe_once(audio_path)
        except Exception:
            # GPU 推理失败（如加载成功但缺 cuBLAS 运行时）→ 回退 CPU int8 重试一次
            if self._device in ("auto", "cuda") and not self._used_cpu_fallback:
                self._reload_as_cpu()
                if self._used_cpu_fallback:
                    try:
                        text = self._transcribe_once(audio_path)
                    except Exception:
                        text = ""
        self._last_latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return text

    @property
    def last_latency_ms(self) -> float:
        """最近一次识别的耗时（毫秒），供延迟基线统计。"""
        return self._last_latency_ms
