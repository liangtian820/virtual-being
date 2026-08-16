"""语音模块（M4）离线单元测试：mock ASR/TTS，不依赖网络与模型下载。

覆盖：ASR 识别、TTS 合成、语音链路、/chat/voice API、回复音频下载与防路径穿越。
"""
import os

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.voice.asr import WhisperASR
from app.voice.pipeline import VoicePipeline
from app.voice.tts import EdgeTTS


class FakeWhisperModel:
    """假 Whisper 模型：固定返回一段文本。"""

    def __init__(self, text: str = "你好，今天过得怎么样？") -> None:
        self.text = text
        self.transcribed = False

    def transcribe(self, audio_path, language=None, vad_filter=True):
        self.transcribed = True
        seg = type("Segment", (), {"text": self.text})()
        return iter([seg]), object()


class FakeCommunicate:
    """假 edge-tts 合成器：把占位字节写入目标文件。"""

    def __init__(self, text: str, voice: str, rate: str = "+0%") -> None:
        self.text = text
        self.voice = voice

    async def save(self, path: str) -> None:
        with open(path, "wb") as fh:
            fh.write(b"FAKE_MP3_BYTES")


class FakeAgent:
    """假人格 Agent：返回固定回复。"""

    def __init__(self, reply: str = "嗯嗯，我在呢，陪你聊聊～") -> None:
        self.reply = reply

    def chat(self, user_input: str, session_id=None):
        return self.reply, session_id or "fake-sid-0001"


# ---------- ASR ----------


def test_asr_uses_injected_model_and_returns_text(tmp_path) -> None:
    """ASR 应调用注入模型并返回识别文本，且记录耗时。"""
    model = FakeWhisperModel("今天天气怎么样？")
    asr = WhisperASR(model=model)
    audio = tmp_path / "in.wav"
    audio.write_bytes(b"x")
    assert asr.transcribe(str(audio)) == "今天天气怎么样？"
    assert model.transcribed
    assert asr.last_latency_ms >= 0


def test_asr_returns_empty_on_inference_error(tmp_path) -> None:
    """识别异常（如音频损坏）应返回空串而非抛错，由上层按无效语音处理。"""

    class BoomModel:
        def transcribe(self, audio_path, language=None, vad_filter=True):
            raise RuntimeError("boom")

    asr = WhisperASR(model=BoomModel(), device="cpu")
    assert asr.transcribe("no-such-file.wav") == ""


def test_asr_default_language_is_chinese() -> None:
    """默认识别语言应为中文（zh），保证中文支持。"""
    assert WhisperASR()._language == "zh"


def test_asr_cpu_fallback_on_inference_failure() -> None:
    """GPU 推理失败（如缺 cuBLAS）时应回退 CPU 重试一次并如实标记降级。"""

    class GpuFailModel:
        def transcribe(self, audio_path, language=None, vad_filter=True):
            raise RuntimeError("cublas64_12.dll is not found")

    asr = WhisperASR(model=GpuFailModel(), device="cuda")

    def _fake_reload_as_cpu() -> None:
        asr._model = FakeWhisperModel("回退成功")
        asr._used_cpu_fallback = True

    asr._reload_as_cpu = _fake_reload_as_cpu  # type: ignore[method-assign]
    text = asr.transcribe("x.wav")
    assert text == "回退成功"
    assert asr.used_cpu_fallback


def test_asr_cpu_fallback_on_load_failure(monkeypatch) -> None:
    """GPU 模型加载失败（缺 CUDA 运行时）时应回退 CPU 加载。"""
    import sys
    import types

    calls = []

    class Factory:
        def __new__(cls, size, device="auto", compute_type="auto", **kwargs):
            calls.append((size, device, compute_type))
            if device in ("auto", "cuda"):
                raise RuntimeError("cublas not found")
            return FakeWhisperModel("降级识别成功")

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = Factory
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    asr = WhisperASR(device="auto")
    assert asr.transcribe("x.wav") == "降级识别成功"
    assert asr.used_cpu_fallback
    assert calls[-1][1] == "cpu"


# ---------- TTS ----------


def test_tts_synthesize_writes_audio(tmp_path) -> None:
    """TTS 应生成非空音频文件并记录耗时。"""
    tts = EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    out = tmp_path / "reply.mp3"
    tts.synthesize("你好", str(out))
    assert out.read_bytes() == b"FAKE_MP3_BYTES"
    assert tts.last_latency_ms >= 0
    assert tts.last_cached_hit is False


def test_tts_empty_text_raises(tmp_path) -> None:
    """空文本应拒绝合成。"""
    tts = EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    with pytest.raises(ValueError):
        tts.synthesize("   ", str(tmp_path / "a.mp3"))


def test_tts_default_voice_is_chinese_female() -> None:
    """默认音色应为中文女声（zh-CN 前缀）。"""
    assert EdgeTTS()._voice.startswith("zh-CN-")


def test_tts_failure_raises_runtime_error(tmp_path) -> None:
    """合成失败（如网络不可用）应抛 RuntimeError 并说明需联网。"""

    class BoomCommunicate:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def save(self, path: str) -> None:
            raise OSError("network down")

    tts = EdgeTTS(tts_cls=BoomCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    with pytest.raises(RuntimeError, match="edge-tts"):
        tts.synthesize("你好", str(tmp_path / "a.mp3"))


def test_tts_works_inside_running_event_loop(tmp_path) -> None:
    """运行中的事件循环内调用合成（async 端点场景）也应成功（线程兜底，回归 bug）。"""
    import asyncio

    tts = EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    out = tmp_path / "in_loop.mp3"

    async def _task() -> None:
        tts.synthesize("你好", str(out))  # 在运行中的事件循环里同步调用

    asyncio.run(_task())
    assert out.read_bytes() == b"FAKE_MP3_BYTES"


# ---------- TTS 缓存（M4.1） ----------


def test_tts_cache_hit_skips_synthesis(tmp_path) -> None:
    """相同文本二次合成应命中缓存：跳过合成器，输出内容一致。"""
    calls: list = []

    class CountingCommunicate:
        def __init__(self, text, voice, rate="+0%"):
            calls.append(text)

        async def save(self, path: str) -> None:
            with open(path, "wb") as fh:
                fh.write(b"FAKE_MP3_BYTES")

    tts = EdgeTTS(tts_cls=CountingCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    out1 = tmp_path / "a.mp3"
    out2 = tmp_path / "b.mp3"
    tts.synthesize("你好呀，今天怎么样？", str(out1))
    assert len(calls) == 1
    assert tts.last_cached_hit is False
    tts.synthesize("你好呀，今天怎么样？", str(out2))
    assert len(calls) == 1, "命中缓存不应再次调用合成器"
    assert out2.read_bytes() == b"FAKE_MP3_BYTES"
    assert tts.last_cached_hit is True


def test_tts_cache_miss_on_different_text(tmp_path) -> None:
    """不同文本应各自合成（不误命中缓存）。"""
    calls: list = []

    class CountingCommunicate:
        def __init__(self, text, voice, rate="+0%"):
            calls.append(text)

        async def save(self, path: str) -> None:
            with open(path, "wb") as fh:
                fh.write(b"FAKE_MP3_BYTES")

    tts = EdgeTTS(tts_cls=CountingCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    tts.synthesize("第一句", str(tmp_path / "a.mp3"))
    tts.synthesize("第二句", str(tmp_path / "b.mp3"))
    assert len(calls) == 2


def test_tts_cache_lru_bounded(tmp_path) -> None:
    """内存 LRU 热条目数不超过上限（磁盘缓存文件保留，命中仍可复用）。"""
    tts = EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache"), cache_size=2)
    for i in range(5):
        tts.synthesize(f"文本{i}", str(tmp_path / f"{i}.mp3"))
    assert len(tts._lru) <= 2
    # 被 LRU 淘汰的 key 因磁盘文件仍在，二次合成依然命中缓存（跳过合成器）
    tts.synthesize("文本0", str(tmp_path / "again.mp3"))
    assert tts.last_cached_hit is True


# ---------- 语音链路 ----------


def test_pipeline_end_to_end(tmp_path) -> None:
    """全链路：音频 → ASR 文本 → 回复 → 回复音频文件，延迟分项齐全。"""
    fake_asr = WhisperASR(model=FakeWhisperModel("今天好累呀"))
    fake_tts = EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    agent = FakeAgent("抱抱你，辛苦了～")
    pipe = VoicePipeline(asr=fake_asr, tts=fake_tts, agent=agent, reply_dir=str(tmp_path / "replies"))
    audio = tmp_path / "user.mp3"
    audio.write_bytes(b"audio")
    result = pipe.handle_audio(str(audio), session_id="sid-abc")

    assert result["text"] == "今天好累呀"
    assert result["reply"] == "抱抱你，辛苦了～"
    assert result["session_id"] == "sid-abc"
    assert result["audio_url"].startswith("/voice/replies/")
    assert os.path.isfile(result["audio_path"])
    lat = result["latencies_ms"]
    for key in ("asr", "llm", "tts", "total"):
        assert key in lat and lat[key] >= 0
    assert lat["total"] >= lat["asr"]


def test_pipeline_empty_transcript_raises(tmp_path) -> None:
    """识别不到有效语音应抛 ValueError（供 API 转 400）。"""
    fake_asr = WhisperASR(model=FakeWhisperModel(""))
    pipe = VoicePipeline(
        asr=fake_asr,
        tts=EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache")),
        agent=FakeAgent(),
        reply_dir=str(tmp_path / "r"),
    )
    audio = tmp_path / "silence.wav"
    audio.write_bytes(b"audio")
    with pytest.raises(ValueError):
        pipe.handle_audio(str(audio))


# ---------- M4.1：回复长度约束 ----------


def test_trim_reply_short_and_none() -> None:
    """短回复与不限长时应原样返回。"""
    assert VoicePipeline._trim_reply("短回复", None) == "短回复"
    assert VoicePipeline._trim_reply("短回复", 100) == "短回复"


def test_trim_reply_keeps_sentence_boundary() -> None:
    """截断应优先保留句末标点（完整句），不硬切。"""
    long_text = "你好呀！后面还有很长很长的内容在这里哦。"
    assert VoicePipeline._trim_reply(long_text, 4) == "你好呀！"
    # 上限内无句末标点时，硬切并补省略号
    assert VoicePipeline._trim_reply("abcdefgh", 4) == "abcd…"


def test_pipeline_trims_long_reply(tmp_path) -> None:
    """语音链路应对长回复做长度约束，且保留完整回复在 reply_full。"""
    long_reply = "嗯嗯，我在这里呢。今天过得怎么样呀？要不要跟我聊聊你最近的想法和感受？"
    fake_asr = WhisperASR(model=FakeWhisperModel("你好"))
    pipe = VoicePipeline(
        asr=fake_asr,
        tts=EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache")),
        agent=FakeAgent(long_reply),
        reply_dir=str(tmp_path / "replies"),
        max_reply_chars=20,
    )
    audio = tmp_path / "user.mp3"
    audio.write_bytes(b"audio")
    result = pipe.handle_audio(str(audio), session_id="sid-trim")
    assert len(result["reply"]) <= 20
    assert result["reply"].endswith(("。", "？", "！"))  # 截断在句末标点
    assert result["reply_full"] == long_reply


def test_pipeline_tts_cache_hit_reuses_audio(tmp_path) -> None:
    """同一回复文本二次合成应命中 TTS 缓存（音频复用，跳过合成）。"""
    fake_asr = WhisperASR(model=FakeWhisperModel("你好"))
    fake_tts = EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache"))
    pipe = VoicePipeline(
        asr=fake_asr,
        tts=fake_tts,
        agent=FakeAgent("嗯嗯，我在呢～"),
        reply_dir=str(tmp_path / "replies"),
    )
    audio = tmp_path / "user.mp3"
    audio.write_bytes(b"audio")
    r1 = pipe.handle_audio(str(audio), session_id="sid-cache")
    assert fake_tts.last_cached_hit is False
    r2 = pipe.handle_audio(str(audio), session_id="sid-cache")
    assert fake_tts.last_cached_hit is True
    assert os.path.isfile(r1["audio_path"]) and os.path.isfile(r2["audio_path"])


# ---------- M4.1：Ollama keep_alive ----------


def test_ollama_payload_has_keep_alive(tmp_path, monkeypatch) -> None:
    """Ollama 调用 payload 应带 keep_alive（长驻配置），消除冷启动。"""
    import requests

    from app.agents.persona_agent import PersonaAgent
    from app.config import CONFIG
    from app.memory.long_term_memory import LongTermMemory
    from app.memory.session_memory import SessionMemory

    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"message": {"content": "你好呀"}}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    agent = PersonaAgent(
        memory=SessionMemory(),
        long_memory=LongTermMemory(db_path=str(tmp_path / "keepalive.db")),
    )
    assert agent._call_ollama([{"role": "user", "content": "hi"}]) == "你好呀"
    assert captured["payload"]["keep_alive"] == CONFIG.ollama_keep_alive == "60m"


# ---------- API ----------


class FakePipeline:
    """假语音链路：固定返回结构化结果。"""

    def __init__(self) -> None:
        self._reply_dir = ""
        self.result = {
            "text": "你好呀",
            "reply": "嗨，我在呢～",
            "session_id": "sid-api-1",
            "audio_url": "/voice/replies/api-1.mp3",
            "audio_path": "",
            "latencies_ms": {"asr": 100.0, "llm": 800.0, "tts": 500.0, "total": 1400.0},
        }

    def handle_audio(self, audio_path: str, session_id=None) -> dict:
        return self.result


@pytest.fixture()
def fake_pipeline(monkeypatch, tmp_path) -> FakePipeline:
    """把 app.main 的语音链路单例替换为假实现。"""
    fake = FakePipeline()
    fake._reply_dir = str(tmp_path / "replies")
    os.makedirs(fake._reply_dir, exist_ok=True)
    reply_file = os.path.join(fake._reply_dir, "api-1.mp3")
    with open(reply_file, "wb") as fh:
        fh.write(b"FAKE_MP3_BYTES")
    fake.result["audio_path"] = reply_file
    monkeypatch.setattr(main_module, "_voice_pipeline", fake)
    return fake


def test_voice_chat_api_returns_reply_audio(fake_pipeline) -> None:
    """POST /chat/voice 应收音频、返回回复文本与可下载的回复音频。"""
    client = TestClient(app)
    resp = client.post(
        "/chat/voice",
        files={"file": ("user.mp3", b"audio-bytes", "audio/mpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "你好呀"
    assert data["reply"] == "嗨，我在呢～"
    assert data["audio_url"] == "/voice/replies/api-1.mp3"
    assert data["latencies_ms"]["total"] == 1400.0

    audio = client.get("/voice/replies/api-1.mp3")
    assert audio.status_code == 200
    assert audio.content == b"FAKE_MP3_BYTES"


def test_voice_chat_api_empty_file_400(fake_pipeline) -> None:
    """空音频文件应返回 400。"""
    client = TestClient(app)
    resp = client.post("/chat/voice", files={"file": ("empty.mp3", b"", "audio/mpeg")})
    assert resp.status_code == 400


def test_voice_chat_api_unrecognized_speech_400(monkeypatch) -> None:
    """识别不到语音应返回 400（不是 500）。"""

    class EmptyPipeline(FakePipeline):
        def handle_audio(self, audio_path: str, session_id=None) -> dict:
            raise ValueError("未能识别到有效语音")

    monkeypatch.setattr(main_module, "_voice_pipeline", EmptyPipeline())
    client = TestClient(app)
    resp = client.post("/chat/voice", files={"file": ("user.mp3", b"x", "audio/mpeg")})
    assert resp.status_code == 400


def test_voice_reply_path_traversal_blocked(fake_pipeline) -> None:
    """回复音频接口应拦截路径穿越，不读取目录外文件。"""
    client = TestClient(app)
    resp = client.get("/voice/replies/..%2F..%2FREADME.md")
    assert resp.status_code in (400, 404)
