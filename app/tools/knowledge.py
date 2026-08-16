"""知识查询工具：内置知识库优先，联网兜底。

M2 起步版：内置知识库为预置条目（简单关键词检索），后续可扩展为向量库 RAG。
联网兜底：Wikipedia 摘要 API（免费、无需 key），失败自动降级。
"""
import re
from typing import Dict, List, Optional

import requests

# 内置知识库（M2 起步版：预置条目；后续可向量化扩展为 RAG）
KNOWLEDGE_BASE: List[Dict[str, str]] = [
    {
        "title": "Hello-Agents",
        "content": "Hello-Agents 是 Datawhale 的开源教程《Hello-Agents》，从零开始构建智能体，"
                   "覆盖 Agent 原理与实践章节（如构建自己的 Agent 框架）。",
        "source": "内置知识库",
    },
    {
        "title": "本项目（AI 虚拟人物）",
        "content": "AI 虚拟人物项目（virtual-being）：温柔治愈的二次元专属 Agent，通过连接多个 Agent 构建"
                   "（人格 Agent + 能力 Agent），支持陪伴聊天与任务助手。",
        "source": "内置知识库",
    },
    {
        "title": "人设",
        "content": "虚拟人物叫小暖（暂定），温柔治愈的二次元 AI 伙伴：轻声细语、包容体贴、日常口语、"
                   "记住用户的重要信息，不冒充真人。",
        "source": "内置知识库",
    },
    {
        "title": "Ollama",
        "content": "Ollama 是本地大模型运行工具，本项目用它跑 qwen2.5:7b 作为对话模型，all-minilm 作为嵌入模型。",
        "source": "内置知识库",
    },
    {
        "title": "LangGraph",
        "content": "LangGraph 是 LangChain 的多 Agent 编排框架，本项目用它编排人格 Agent 与能力 Agent 的协作。",
        "source": "内置知识库",
    },
    {
        "title": "RAG",
        "content": "RAG（检索增强生成）：先检索相关资料，再让模型基于资料生成答案，减少幻觉。本项目用于知识查询。",
        "source": "内置知识库",
    },
]

_WIKI_API = "https://zh.wikipedia.org/api/rest_v1/page/summary/{}"


def search_local(query: str) -> Optional[Dict[str, str]]:
    """内置知识库检索：关键词打分，返回最相关条目；无命中返回 None。"""
    tokens = [t for t in re.split(r"[\s，。？、！]+", query.lower()) if len(t) >= 2]
    best: Optional[Dict[str, str]] = None
    best_score = 0
    for item in KNOWLEDGE_BASE:
        hay = (item["title"] + item["content"]).lower()
        score = sum(1 for t in tokens if t in hay)
        if score > best_score:
            best, best_score = item, score
    return best if best_score > 0 else None


def search_web(query: str, timeout: int = 8) -> Optional[Dict[str, str]]:
    """联网兜底：Wikipedia 摘要 API（免费、无需 key）。失败/无结果返回 None（降级）。"""
    try:
        resp = requests.get(_WIKI_API.format(requests.utils.quote(query)), timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        title = data.get("title", "")
        extract = data.get("extract", "")
        if not title or not extract:
            return None
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
        return {"title": title, "content": extract, "source": f"Wikipedia{(': ' + page_url) if page_url else ''}"}
    except requests.RequestException:
        return None


def retrieve(query: str) -> Dict[str, str]:
    """主入口：本地优先 → 联网兜底 → 均无结果则明确说明（不编造）。"""
    local = search_local(query)
    if local:
        return {"answer": f"{local['title']}：{local['content']}", "source": local["source"], "origin": "local"}
    web = search_web(query)
    if web:
        return {"answer": f"{web['title']}：{web['content']}", "source": web["source"], "origin": "web"}
    return {"answer": "没有找到相关资料哦，换个问法试试，或者让我换个方式找找。", "source": "", "origin": "none"}
