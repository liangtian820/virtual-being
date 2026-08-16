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
    # M4 语音配置（ASR）：Whisper 本地识别，中文支持
    asr_model_size: str = field(default_factory=lambda: os.getenv("ASR_MODEL_SIZE", "small"))
    asr_device: str = field(default_factory=lambda: os.getenv("ASR_DEVICE", "auto"))
    asr_compute_type: str = field(default_factory=lambda: os.getenv("ASR_COMPUTE_TYPE", "auto"))
    # ASR_LANGUAGE=auto 表示 Whisper 自动检测语言；默认中文优先
    asr_language: Optional[str] = field(
        default_factory=lambda: None if os.getenv("ASR_LANGUAGE", "zh") == "auto" else os.getenv("ASR_LANGUAGE", "zh")
    )
    asr_model_dir: Optional[str] = field(default_factory=lambda: os.getenv("ASR_MODEL_DIR") or None)
    # M4 语音配置（TTS）：edge-tts 现成音色，默认中文女声「晓晓」
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural"))
    tts_rate: str = field(default_factory=lambda: os.getenv("TTS_RATE", "+0%"))
    # M4 回复音频落盘目录（相对项目根）
    voice_reply_dir: str = field(default_factory=lambda: os.getenv("VOICE_REPLY_DIR", "data/voice_replies"))


CONFIG = Config()
