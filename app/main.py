"""FastAPI 服务入口：虚拟人物的对话 API（M1-M4）。

- POST /chat          文本对话（M1）
- POST /chat/voice    语音对话：上传音频 → 返回回复音频（M4）
- GET  /voice/replies/{filename}  下载/播放回复音频（M4）
"""
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agents.persona_agent import PersonaAgent
from app.voice.pipeline import VoicePipeline

app = FastAPI(title="Virtual Being", version="0.5.0", description="AI 虚拟人物 · M5 形象")

# M5 形象：Web 聊天界面静态资源目录（index.html / css / js）
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_agent = PersonaAgent()

# 语音链路单例：测试可用假对象覆盖（app.main._voice_pipeline = FakePipeline()）
_voice_pipeline: Optional[VoicePipeline] = None


def get_voice_pipeline() -> VoicePipeline:
    """获取语音链路单例（惰性创建）。"""
    global _voice_pipeline
    if _voice_pipeline is None:
        _voice_pipeline = VoicePipeline()
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
