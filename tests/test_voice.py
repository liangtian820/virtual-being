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
from app.voice.tts import EdgeTTS, PiperTTS


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

    def chat(self, user_input: str, session_id=None, max_tokens=None):
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


def test_asr_local_snapshot_detection(tmp_path) -> None:
    """本地快照探测：HF 缓存布局与扁平目录都应命中（跳过联网校验）。"""
    # HF 缓存布局：<model_dir>/models--Systran--faster-whisper-base/snapshots/<hash>/
    snap = tmp_path / "models--Systran--faster-whisper-base" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x")
    asr = WhisperASR(model_size="base", model_dir=str(tmp_path))
    assert asr._local_snapshot_path() == str(snap)
    # 扁平目录：model_dir 下直接含 model.bin
    flat = tmp_path / "flat-model"
    flat.mkdir()
    (flat / "model.bin").write_bytes(b"x")
    asr2 = WhisperASR(model_size="base", model_dir=str(flat))
    assert asr2._local_snapshot_path() == str(flat)
    # 无模型目录/文件 → None（走标准下载路径）
    asr3 = WhisperASR(model_size="base", model_dir=str(tmp_path / "empty"))
    assert asr3._local_snapshot_path() is None


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


# ---------- M4.2：ASR 默认调优 / max_tokens / UI 状态提示 ----------


def test_config_m42_asr_defaults() -> None:
    """M4.2 默认 ASR 配置：base + CPU(int8)，避免与 Ollama 争抢显存。"""
    from app.config import CONFIG

    assert CONFIG.asr_model_size == "base"
    assert CONFIG.asr_device == "cpu"
    assert CONFIG.asr_compute_type == "int8"


def test_pipeline_max_tokens_mapping() -> None:
    """max_reply_chars 应映射为 Ollama num_predict 上限（60 字 → 162，40 字 → 108）。"""
    assert VoicePipeline._derive_max_tokens(60) == 162
    assert VoicePipeline._derive_max_tokens(40) == 108
    assert VoicePipeline._derive_max_tokens(0) == 64  # 下限保护
    assert VoicePipeline._derive_max_tokens(None) is None  # 不限长不限制
    pipe = VoicePipeline(max_reply_chars=60, max_tokens=None)
    assert pipe._max_tokens == 162
    pipe2 = VoicePipeline(max_reply_chars=60, max_tokens=999)
    assert pipe2._max_tokens == 999  # 显式传入优先


def test_config_m43_voice_defaults() -> None:
    """M4.3 默认：语音回复 ≤40 字；voice_llm_model 默认 None（跟随 ollama_model）。"""
    from app.config import CONFIG

    assert CONFIG.voice_max_reply_chars == 40
    assert CONFIG.voice_llm_model is None


def test_pipeline_uses_voice_llm_model() -> None:
    """pipeline 应把 llm_model 传给 PersonaAgent（voice 专用模型覆盖，文本链路不受影响）。"""
    from app.config import CONFIG

    pipe = VoicePipeline(llm_model="qwen2.5:3b")
    assert pipe._agent._model == "qwen2.5:3b"
    pipe_default = VoicePipeline()
    assert pipe_default._agent._model == CONFIG.ollama_model


def test_pipeline_passes_max_tokens_to_agent(tmp_path) -> None:
    """pipeline 应把推导出的 max_tokens 传给人格 Agent（源头限制生成）。"""
    captured: dict = {}

    class SpyAgent(FakeAgent):
        def chat(self, user_input: str, session_id=None, max_tokens=None):
            captured["max_tokens"] = max_tokens
            return super().chat(user_input, session_id, max_tokens)

    fake_asr = WhisperASR(model=FakeWhisperModel("你好"))
    pipe = VoicePipeline(
        asr=fake_asr,
        tts=EdgeTTS(tts_cls=FakeCommunicate, cache_dir=str(tmp_path / "tts_cache")),
        agent=SpyAgent(),
        reply_dir=str(tmp_path / "replies"),
        max_reply_chars=60,
    )
    audio = tmp_path / "user.mp3"
    audio.write_bytes(b"audio")
    pipe.handle_audio(str(audio), session_id="sid-mt")
    assert captured["max_tokens"] == 162


def test_agent_chat_passes_max_tokens_to_ollama(tmp_path, monkeypatch) -> None:
    """chat(max_tokens=..) 应在 Ollama payload 的 options 里带 num_predict。"""
    import requests

    from app.agents.persona_agent import PersonaAgent
    from app.memory.long_term_memory import LongTermMemory
    from app.memory.session_memory import SessionMemory

    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"message": {"content": "短回复"}}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    agent = PersonaAgent(
        memory=SessionMemory(),
        long_memory=LongTermMemory(db_path=str(tmp_path / "mt.db")),
    )
    agent.chat("你好", session_id="s1", max_tokens=162)
    assert captured["payload"]["options"]["num_predict"] == 162
    # 文本 API 不传 max_tokens → 不限制生成（无 num_predict）
    agent.chat("你好", session_id="s2")
    assert "num_predict" not in captured["payload"]["options"]


def test_web_voice_status_ui_hints() -> None:
    """web/ 应含语音处理中状态提示（识别中/思考中/回复中），避免误判卡死。"""
    import app.main as main_module

    html = (main_module.WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (main_module.WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")
    css = (main_module.WEB_DIR / "css" / "style.css").read_text(encoding="utf-8")
    assert 'id="voice-status"' in html
    assert "正在识别你的声音" in js
    assert "TA 正在思考" in js
    assert "正在合成回复" in js
    assert ".voice-status" in css


# ---------- M4.3：piper 本地 TTS 后端 ----------


def test_piper_tts_synthesize_with_fake_voice(tmp_path) -> None:
    """piper 后端应写入 WAV 音频并记录耗时（注入假 voice，不依赖本地模型）。"""

    class FakePiperVoice:
        def synthesize_wav(self, text: str, wf) -> None:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x00" * 100)

    tts = PiperTTS(voice=FakePiperVoice())
    out = tmp_path / "p.wav"
    tts.synthesize("你好", str(out))
    assert out.stat().st_size > 0
    assert tts.last_latency_ms >= 0
    assert tts.last_cached_hit is False


def test_piper_tts_empty_text_raises(tmp_path) -> None:
    """piper 后端空文本同样拒绝。"""
    tts = PiperTTS(voice=object())
    with pytest.raises(ValueError):
        tts.synthesize("   ", str(tmp_path / "p.wav"))
