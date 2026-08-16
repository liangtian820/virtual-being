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

from app.agents.persona_agent import PersonaAgent, is_crisis_query
from app.config import CONFIG
from app.voice.asr import WhisperASR
from app.voice.tts import EdgeTTS, PiperTTS


def _make_tts():
    """按 CONFIG.tts_backend 构造默认 TTS（edge_tts=在线 / piper=本地离线）。"""
    if CONFIG.tts_backend == "piper":
        return PiperTTS()
    return EdgeTTS()


class VoicePipeline:
    """端到端语音对话链路（说→听→回→播）。"""

    def __init__(self, asr=None, tts=None, agent: Optional[PersonaAgent] = None,
                 reply_dir: Optional[str] = None, max_reply_chars: Optional[int] = None,
                 max_tokens: Optional[int] = None, llm_model: Optional[str] = None) -> None:
        """初始化链路；各组件可注入（测试/替换用）。

        :param asr: ASR 实例（默认 WhisperASR）
        :param tts: TTS 实例（默认 EdgeTTS）
        :param agent: 人格 Agent（默认 PersonaAgent）
        :param reply_dir: 回复音频落盘目录（默认 CONFIG.voice_reply_dir）
        :param max_reply_chars: 语音回复最大字符数（默认 CONFIG.voice_max_reply_chars；
            仅影响语音链路的 TTS/返回文本，不改会话记忆与文本 API；None=不限制）
        :param max_tokens: Ollama num_predict 上限；None 时按 max_reply_chars 推导
            （M4.2：从源头限制生成长度，避免先生成再截断）
        :param llm_model: 语音链路专用 Ollama 模型（M4.3；默认 CONFIG.voice_llm_model，
            未设置时跟随 CONFIG.ollama_model —— 文本链路不受影响）
        """
        self._asr = asr or WhisperASR()
        self._tts = tts if tts is not None else _make_tts()
        if agent is None:
            llm_model = llm_model if llm_model is not None else CONFIG.voice_llm_model
            self._agent = PersonaAgent(model=llm_model or CONFIG.ollama_model)
        else:
            self._agent = agent
        self._reply_dir = reply_dir or CONFIG.voice_reply_dir
        if max_reply_chars is None:
            max_reply_chars = CONFIG.voice_max_reply_chars
        self._max_reply_chars = max_reply_chars
        self._max_tokens = max_tokens if max_tokens is not None else self._derive_max_tokens(max_reply_chars)

    @staticmethod
    def _derive_max_tokens(max_reply_chars: Optional[int]) -> Optional[int]:
        """按回复字符数推导 Ollama num_predict 上限（M4.2）。

        中文约 1 字 ≈ 1-2 token，取 2.7 系数并留安全余量：60 字 → 162；
        不限长（None）时返回 None（不限制生成）。
        """
        if max_reply_chars is None:
            return None
        return max(64, int(max_reply_chars * 2.7))

    @staticmethod
    def _trim_reply(reply: str, max_chars: Optional[int]) -> str:
        """把回复截断到 max_chars 字符：优先在句末标点（。！？…）处截断，保留语义完整性。

        :param reply: 原始回复
        :param max_chars: 上限字符数；None 或已达标时原样返回
        """
        if max_chars is None or len(reply) <= max_chars:
            return reply
        # 从上限位置向前找最后一个句末标点，截到那里（保留完整句）
        for idx in range(max_chars - 1, -1, -1):
            if reply[idx] in "。！？!?…":
                return reply[: idx + 1]
        return reply[:max_chars] + "…"

    def handle_audio(self, audio_path: str, session_id: Optional[str] = None) -> Dict:
        """处理一段用户语音，返回结构化结果。

        :param audio_path: 用户语音音频文件路径
        :param session_id: 会话 id（可选，沿用旧会话记忆）
        :return: {
            "text": ASR 识别文本,
            "reply": 语音回复文本（M4.1 起为长度约束后的截断版）,
            "reply_full": 人格 Agent 完整回复（未截断）,
            "session_id": 会话 id,
            "audio_url": 回复音频访问路径（相对 API 根）,
            "audio_path": 回复音频落盘绝对路径,
            "latencies_ms": {"asr": .., "llm": .., "trim": .., "tts": .., "total": ..},
        }
        :raises ValueError: 未能识别到有效语音
        """
        t0 = time.perf_counter()
        text = self._asr.transcribe(audio_path)
        t1 = time.perf_counter()
        if not text.strip():
            raise ValueError("未能识别到有效语音，请靠近麦克风再说一次")
        reply, sid = self._agent.chat(text, session_id, max_tokens=self._max_tokens)
        t2 = time.perf_counter()
        # M4.1：语音回复长度约束（截断只影响本次 TTS/返回文本，会话记忆保持完整回复）
        # M4.4：危机路径安全优先——不截断，保证代码层强制追加的专业求助句完整输出
        if is_crisis_query(text):
            reply_trimmed = reply
        else:
            reply_trimmed = self._trim_reply(reply, self._max_reply_chars)
        t2b = time.perf_counter()

        os.makedirs(self._reply_dir, exist_ok=True)
        filename = f"{sid[:8]}-{uuid.uuid4().hex[:8]}.mp3"
        out_path = os.path.join(self._reply_dir, filename)
        self._tts.synthesize(reply_trimmed, out_path)
        t3 = time.perf_counter()

        def _ms(a: float, b: float) -> float:
            return round((b - a) * 1000, 1)

        return {
            "text": text,
            # M4.1：返回截断后的语音回复（语义完整句）；完整回复见 reply_full
            "reply": reply_trimmed,
            "reply_full": reply,
            "session_id": sid,
            "audio_url": f"/voice/replies/{filename}",
            "audio_path": out_path,
            "latencies_ms": {
                "asr": _ms(t0, t1),
                "llm": _ms(t1, t2),
                "trim": _ms(t2, t2b),
                "tts": _ms(t2, t3),
                "total": _ms(t0, t3),
            },
        }
