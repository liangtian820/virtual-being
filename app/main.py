"""FastAPI 服务入口：虚拟人物的对话 API。"""
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.agents.persona_agent import PersonaAgent

app = FastAPI(title="Virtual Being", version="0.1.0", description="AI 虚拟人物 · M1 文本灵魂")

_agent = PersonaAgent()


class ChatRequest(BaseModel):
    """聊天请求体。"""

    query: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """聊天响应体。"""

    reply: str
    session_id: str


@app.get("/health")
def health() -> dict:
    """健康检查。"""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """与虚拟人物对话。"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")
    try:
        reply, sid = _agent.chat(req.query, req.session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatResponse(reply=reply, session_id=sid)
