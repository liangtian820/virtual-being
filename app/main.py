"""FastAPI 服务入口：虚拟人物的对话 API（M1-M4.2）。

- POST /chat          文本对话（M1）
- POST /chat/voice    语音对话：上传音频 → 返回回复音频（M4）
- GET  /voice/replies/{filename}  下载/播放回复音频（M4）
- 启动生命周期（M4.2）：预加载 ASR 模型 + 后台预热 Ollama，消除首次语音请求的加载等待
"""
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agents.persona_agent import PersonaAgent
from app.config import CONFIG
from app.voice.asr import WhisperASR
from app.voice.pipeline import VoicePipeline

# M5 形象：Web 聊天界面静态资源目录（index.html / css / js）
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_agent = PersonaAgent()

# 语音链路单例：测试可用假对象覆盖（app.main._voice_pipeline = FakePipeline()）
_voice_pipeline: Optional[VoicePipeline] = None
# M4.2：启动时预加载的 ASR 实例（复用给 pipeline，避免二次加载）
_asr_singleton: Optional[WhisperASR] = None


def _prewarm_ollama() -> None:
    """后台预热 Ollama：keep_alive 一次最小生成，让模型常驻，避免首个语音请求冷启动 LLM。

    失败静默：预热失败不影响服务，首个请求会按需加载。
    """
    try:
        import requests

        requests.post(
            f"{CONFIG.ollama_base_url.rstrip('/')}/api/chat",
            json={
                "model": CONFIG.ollama_model,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "keep_alive": CONFIG.ollama_keep_alive,
                "options": {"temperature": 0.0, "num_predict": 1},
            },
            timeout=120,
        )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动生命周期（M4.2）：预加载 ASR 模型 + 后台预热 Ollama。

    - ASR 同步预加载（本地模型数秒）：保证首个 /chat/voice 无模型加载等待；
      失败不阻塞启动（首次请求按需加载兜底）。
    - Ollama 后台线程预热（非阻塞）。
    """
    global _asr_singleton
    t0 = time.perf_counter()
    if CONFIG.asr_preload:
        try:
            asr = WhisperASR()
            asr._ensure_model()
            _asr_singleton = asr
            dev = "cpu(降级)" if asr.used_cpu_fallback else asr._device
            print(f"[startup] ASR 模型预加载完成（{time.perf_counter() - t0:.1f}s, "
                  f"size={asr._model_size}, device={dev}）")
        except Exception as exc:
            print(f"[startup] ASR 预加载失败（首个请求将按需加载）: {exc}")
    threading.Thread(target=_prewarm_ollama, daemon=True, name="ollama-prewarm").start()
    yield


app = FastAPI(title="Virtual Being", version="0.6.0",
              description="AI 虚拟人物 · M4.2 语音优化", lifespan=lifespan)


def get_voice_pipeline() -> VoicePipeline:
    """获取语音链路单例（惰性创建；复用启动时预加载的 ASR 实例）。"""
    global _voice_pipeline
    if _voice_pipeline is None:
        _voice_pipeline = VoicePipeline(asr=_asr_singleton)
    return _voice_pipeline


class ChatRequest(BaseModel):
    """聊天请求体。"""

    query: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """聊天响应体。"""

    reply: str
    session_id: str


class VoiceChatResponse(BaseModel):
    """语音对话响应体（M4）。"""

    text: str
    reply: str
    session_id: str
    audio_url: str
    latencies_ms: Dict[str, float]


@app.get("/health")
def health() -> dict:
    """健康检查。"""
    return {"status": "ok"}


# ---------- M5.1（WO-20260816-22）：记忆 API（供对话与后续 Web 使用） ----------


@app.get("/memory")
def list_memories(limit: int = Query(50, ge=1, le=200)) -> dict:
    """列示长期记忆（摘要级：content 截断，不含内部元数据）。"""
    items = [
        {"id": m["id"], "kind": m["kind"], "content": m["content"][:60],
         "created_at": m["created_at"]}
        for m in _agent._memory_long.recent(limit=limit)
    ]
    return {"memories": items, "count": len(items)}


@app.delete("/memory")
def clear_memories(confirm: str = Query("")) -> dict:
    """清空长期记忆（需 confirm=1 确认；保留表结构，清空后留痕日志）。"""
    if confirm != "1":
        raise HTTPException(status_code=400, detail="清空记忆需要确认：DELETE /memory?confirm=1")
    store = _agent._memory_long
    deleted = store.clear()
    print(f"[memory] 已清空 {deleted} 条记忆（{time.strftime('%Y-%m-%d %H:%M:%S')}）")
    return {"ok": True, "deleted": deleted}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """与虚拟人物对话（文本）。"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")
    try:
        reply, sid = _agent.chat(req.query, req.session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatResponse(reply=reply, session_id=sid)


@app.post("/chat/voice", response_model=VoiceChatResponse)
def chat_voice(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
) -> VoiceChatResponse:
    """语音对话：接收用户音频（wav/mp3/m4a 等），返回 TA 的回复音频。

    同步端点：FastAPI 自动放入线程池执行，避免阻塞事件循环，
    也让语音链路内的 asyncio.run（edge-tts）可正常工作。
    响应中的 audio_url 指向 GET /voice/replies/{filename}，可直接播放。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少音频文件")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="音频内容为空")
    suffix = Path(file.filename).suffix or ".wav"
    # 写入临时文件后交给链路（Whisper/PyAV 自行解码），处理完即删，不落库用户原始语音
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        result = get_voice_pipeline().handle_audio(tmp_path, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return VoiceChatResponse(
        text=result["text"],
        reply=result["reply"],
        session_id=result["session_id"],
        audio_url=result["audio_url"],
        latencies_ms=result["latencies_ms"],
    )


@app.get("/voice/replies/{filename}")
def voice_reply(filename: str) -> FileResponse:
    """下载/播放回复音频文件（仅限回复目录内，防路径穿越）。"""
    base = Path(get_voice_pipeline()._reply_dir).resolve()
    target = (base / Path(filename).name).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(status_code=404, detail="音频不存在")
    return FileResponse(target, media_type="audio/mpeg")


# ---------- M5 形象：Web 聊天界面（静态挂载，不改动任何已有 API 逻辑） ----------

# 挂载 web/ 目录为 /static，提供 index.html 之外的 css/js 等静态资源
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="web_static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """返回 Web 聊天界面首页（立绘 + 对话窗 + 语音控件）。"""
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")
