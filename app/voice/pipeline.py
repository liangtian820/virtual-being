"""语音对话链路（M4）：音频输入 → ASR → 人格 Agent 对话 → TTS → 回复音频。

即「说 → 听 → 回 → 播」：
- 听：ASR（Whisper 本地识别）把用户语音转文字
- 回：人格 Agent（PersonaAgent + Ollama qwen2.5:7b）按人设回复
- 说/播：TTS（edge-tts 中文女声）把回复合成音频文件

每段耗时（ASR / LLM / TTS / 总时长，毫秒）随结果返回，供延迟基线与降级评估；
延迟明显不可接受时由上层如实上报并提供降级方案（换小模型 / 缓存 / 预合成）。
"""
import os
import time
import uuid
from typing import Dict, Optional

from app.agents.persona_agent import PersonaAgent
from app.config import CONFIG
from app.voice.asr import WhisperASR
from app.voice.tts import EdgeTTS


class VoicePipeline:
    """端到端语音对话链路（说→听→回→播）。"""

    def __init__(self, asr=None, tts=None, agent: Optional[PersonaAgent] = None,
                 reply_dir: Optional[str] = None) -> None:
        """初始化链路；各组件可注入（测试/替换用）。

        :param asr: ASR 实例（默认 WhisperASR）
        :param tts: TTS 实例（默认 EdgeTTS）
        :param agent: 人格 Agent（默认 PersonaAgent）
        :param reply_dir: 回复音频落盘目录（默认 CONFIG.voice_reply_dir）
        """
        self._asr = asr or WhisperASR()
        self._tts = tts or EdgeTTS()
        self._agent = agent or PersonaAgent()
        self._reply_dir = reply_dir or CONFIG.voice_reply_dir

    def handle_audio(self, audio_path: str, session_id: Optional[str] = None) -> Dict:
        """处理一段用户语音，返回结构化结果。

        :param audio_path: 用户语音音频文件路径
        :param session_id: 会话 id（可选，沿用旧会话记忆）
        :return: {
            "text": ASR 识别文本,
            "reply": 人格 Agent 回复文本,
            "session_id": 会话 id,
            "audio_url": 回复音频访问路径（相对 API 根）,
            "audio_path": 回复音频落盘绝对路径,
            "latencies_ms": {"asr": .., "llm": .., "tts": .., "total": ..},
        }
        :raises ValueError: 未能识别到有效语音
        """
        t0 = time.perf_counter()
        text = self._asr.transcribe(audio_path)
        t1 = time.perf_counter()
        if not text.strip():
            raise ValueError("未能识别到有效语音，请靠近麦克风再说一次")
        reply, sid = self._agent.chat(text, session_id)
        t2 = time.perf_counter()

        os.makedirs(self._reply_dir, exist_ok=True)
        filename = f"{sid[:8]}-{uuid.uuid4().hex[:8]}.mp3"
        out_path = os.path.join(self._reply_dir, filename)
        self._tts.synthesize(reply, out_path)
        t3 = time.perf_counter()

        def _ms(a: float, b: float) -> float:
            return round((b - a) * 1000, 1)

        return {
            "text": text,
            "reply": reply,
            "session_id": sid,
            "audio_url": f"/voice/replies/{filename}",
            "audio_path": out_path,
            "latencies_ms": {
                "asr": _ms(t0, t1),
                "llm": _ms(t1, t2),
                "tts": _ms(t2, t3),
                "total": _ms(t0, t3),
            },
        }
