"""知识查询工具：内置知识库优先，联网兜底。

M2 起步版：内置知识库为预置条目（简单关键词检索），后续可扩展为向量库 RAG。
联网兜底：Wikipedia 摘要 API（免费、无需 key）+ Bing 全网搜索（M6.9 并行取先返回），失败自动降级。

M6.9（WO-20260816-39）：
- Wikipedia 超时 8s→3s，Bing 超时 10s→(3s,6s)，均按 query 缓存 ~10 分钟（data/search_cache）；
- 内置无命中 → Wikipedia 与 Bing **并行**（基线串行 8s+10s=18s → 并行 ≤ ~6s，通常 3s 内先返回）。
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import requests

from app.tools.search_cache import search_cache
from app.tools.web_search import search as search_bing

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
# M6.9：Wikipedia 超时 8s→3s（快速降级）
_WIKI_TIMEOUT = 3


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


def search_web(query: str, timeout: int = None) -> Optional[Dict[str, str]]:
    """联网兜底①：Wikipedia 摘要 API（免费、无需 key）。失败/无结果返回 None（降级）。

    M6.9：超时 8s→3s；按 query 缓存 ~10 分钟（重复查询命中缓存直接返回）。
    """
    if timeout is None:
        timeout = _WIKI_TIMEOUT
    cached = search_cache.get(f"wiki:{query}")
    if cached is not None:
        return cached
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
        result = {"title": title, "content": extract, "source": f"Wikipedia{(': ' + page_url) if page_url else ''}"}
        search_cache.set(f"wiki:{query}", result)
        return result
    except requests.RequestException:
        return None


def _search_bing_summary(query: str) -> Optional[Dict[str, str]]:
    """联网兜底②：Bing 全网搜索（M6.9 新增，覆盖内置库/Wikipedia 查不到的内容）。"""
    items = search_bing(query)
    if not items:
        return None
    first = items[0]
    content = f"{first['title']}：{first['snippet']}（{first['url']}）"
    if len(items) > 1:
        content += "\n另见：" + "；".join(f"{it['title']}（{it['url']}）" for it in items[1:])
    return {"title": first["title"], "content": content, "source": "Bing 联网搜索"}


def retrieve(query: str) -> Dict[str, str]:
    """主入口：本地优先 →（M6.9）Wikipedia 与 Bing 并行取先返回 → 均无结果明确说明（不编造）。

    基线：内置→Wikipedia(8s)→Bing(10s) 串行（知识查询 38.4s）；M6.9 并行后内置无命中时
    Wikipedia 与 Bing 同时发起，先返回的成功者即用（≤ ~6s，通常 3s 内）。
    """
    local = search_local(query)
    if local:
        return {"answer": f"{local['title']}：{local['content']}", "source": local["source"], "origin": "local"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(search_web, query): "wiki",
            executor.submit(_search_bing_summary, query): "bing",
        }
        for fut in as_completed(futures):
            web = fut.result()
            if web:
                origin = futures[fut]
                return {
                    "answer": f"{web['title']}：{web['content']}",
                    "source": web["source"],
                    "origin": origin,
                }
    return {"answer": "没有找到相关资料哦，换个问法试试，或者让我换个方式找找。", "source": "", "origin": "none"}
