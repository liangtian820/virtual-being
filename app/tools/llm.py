"""能力 Agent 共用 LLM 调用助手（M2.1）。

与人格 Agent 的 `_call_ollama` 同构（非流式、keep_alive 长驻、可选 num_predict），
供能力 Agent 的工具实现按需调用本地 Ollama；工具层一律支持注入 `llm_call`，
以便离线测试 mock（不依赖 Ollama）。
"""
from typing import List, Optional

import requests

from app.config import CONFIG


def chat(
    messages: List[dict],
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """调用 Ollama /api/chat（非流式），返回回复文本。

    :param messages: OpenAI 风格消息列表 [{"role": ..., "content": ...}, ...]
    :param max_tokens: Ollama num_predict 上限（None=沿用模型默认）
    :raises RuntimeError: 网络失败 / 非 200 时抛出（由调用方降级为结构化错误）
    """
    url = f"{(base_url or CONFIG.ollama_base_url).rstrip('/')}/api/chat"
    options: dict = {"temperature": temperature if temperature is not None else CONFIG.temperature}
    if max_tokens is not None and max_tokens > 0:
        options["num_predict"] = max_tokens
    payload = {
        "model": model or CONFIG.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": CONFIG.ollama_keep_alive,
        "options": options,
    }
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Ollama 调用失败（请确认 Ollama 已启动、模型 {(model or CONFIG.ollama_model)} 已拉取）: {exc}"
        ) from exc
    data = resp.json()
    return data.get("message", {}).get("content", "").strip()
