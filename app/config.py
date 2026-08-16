"""应用配置。

从环境变量读取，支持 .env 文件（通过 python-dotenv 或手动加载）。
"""
from dataclasses import dataclass, field
import os
from typing import Optional


def _load_dotenv() -> None:
    """极简 .env 加载器，避免额外依赖。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@dataclass(frozen=True)
class Config:
    """项目配置（从环境变量读取）。"""

    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen2.5:7b"))
    app_host: str = field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    app_port: int = field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    temperature: float = field(default_factory=lambda: float(os.getenv("PERSONA_TEMPERATURE", "0.8")))
    max_history_turns: int = field(default_factory=lambda: int(os.getenv("PERSONA_MAX_HISTORY_TURNS", "10")))
    # M4.1 延迟优化：Ollama keep_alive 长驻（如 "60m"），消除每次对话的模型冷启动
    ollama_keep_alive: str = field(default_factory=lambda: os.getenv("OLLAMA_KEEP_ALIVE", "60m"))
    # M4.3：语音链路专用 LLM 模型覆盖（None=跟随 ollama_model；可设 VOICE_LLM_MODEL=qwen2.5:3b 等
    # 小模型降低生成延迟，文本链路不受影响）
    voice_llm_model: Optional[str] = field(default_factory=lambda: os.getenv("VOICE_LLM_MODEL") or None)
    # M4 语音配置（ASR）：Whisper 本地识别，中文支持
    # M4.2 默认调优：base + CPU(int8) —— 基准实测 base/CPU 937ms 稳定，
    # 且不占用 Ollama 需要的 6GB 显存（避免争抢导致 ASR/LLM 双双变慢）
    asr_model_size: str = field(default_factory=lambda: os.getenv("ASR_MODEL_SIZE", "base"))
    asr_device: str = field(default_factory=lambda: os.getenv("ASR_DEVICE", "cpu"))
    asr_compute_type: str = field(default_factory=lambda: os.getenv("ASR_COMPUTE_TYPE", "int8"))
    # ASR_LANGUAGE=auto 表示 Whisper 自动检测语言；默认中文优先
    asr_language: Optional[str] = field(
        default_factory=lambda: None if os.getenv("ASR_LANGUAGE", "zh") == "auto" else os.getenv("ASR_LANGUAGE", "zh")
    )
    # 模型本地缓存目录（HF 缓存布局：models--Systran--faster-whisper-{size}），默认项目 data/models
    asr_model_dir: Optional[str] = field(default_factory=lambda: os.getenv("ASR_MODEL_DIR") or "data/models")
    # M4.2：启动时预加载 ASR 模型（ASR_PRELOAD=0 可关闭）
    asr_preload: bool = field(default_factory=lambda: os.getenv("ASR_PRELOAD", "1") != "0")
    # M4 语音配置（TTS）：edge-tts 现成音色，默认中文女声「晓晓」
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural"))
    tts_rate: str = field(default_factory=lambda: os.getenv("TTS_RATE", "+0%"))
    # M4.3：TTS 后端（edge_tts=在线晓晓音质好/需联网；piper=本地离线/稳定，模型 data/models/piper）
    tts_backend: str = field(default_factory=lambda: os.getenv("TTS_BACKEND", "edge_tts"))
    # M4 回复音频落盘目录（相对项目根）
    voice_reply_dir: str = field(default_factory=lambda: os.getenv("VOICE_REPLY_DIR", "data/voice_replies"))
    # M4.1 延迟优化：语音回复长度约束（字符数，仅语音链路生效；None=不限制）
    # M4.3：默认 60 → 40（缩短音频时长与生成量，配合 <5s 冲刺）
    voice_max_reply_chars: Optional[int] = field(
        default_factory=lambda: int(os.getenv("VOICE_MAX_REPLY_CHARS", "40"))
    )
    # M4.1 延迟优化：TTS 合成结果 LRU 缓存（key=文本+音色；目录 + 内存 LRU 容量）
    tts_cache_dir: str = field(default_factory=lambda: os.getenv("TTS_CACHE_DIR", "data/tts_cache"))
    tts_cache_size: int = field(default_factory=lambda: int(os.getenv("TTS_CACHE_SIZE", "128")))
    # M3.5（WO-20260816-19）：记忆向量化——embedding 模型/维度/超时（Ollama 本地 all-minilm）
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "all-minilm:latest"))
    embedding_base_url: str = field(default_factory=lambda: os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:11434"))
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "384")))
    embedding_timeout: float = field(default_factory=lambda: float(os.getenv("EMBEDDING_TIMEOUT", "10")))
    # 语义检索相似度阈值（低于该值的语义结果不返回；可调低放宽、调高收紧）
    memory_semantic_threshold: float = field(
        default_factory=lambda: float(os.getenv("MEMORY_SEMANTIC_THRESHOLD", "0.35"))
    )
    # 检索融合权重（语义 + 关键词，建议和为 1）
    memory_fusion_semantic_weight: float = field(
        default_factory=lambda: float(os.getenv("MEMORY_FUSION_SEMANTIC_WEIGHT", "0.6"))
    )
    memory_fusion_keyword_weight: float = field(
        default_factory=lambda: float(os.getenv("MEMORY_FUSION_KEYWORD_WEIGHT", "0.4"))
    )
    # 语义检索时对无向量旧数据 lazy 补向量（1=开，避免全量离线迁移；0=关）
    memory_auto_backfill: bool = field(default_factory=lambda: os.getenv("MEMORY_AUTO_BACKFILL", "1") != "0")


CONFIG = Config()
