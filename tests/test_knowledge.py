"""能力 Agent（知识查询）与意图路由的离线测试（不调用 Ollama，联网已 mock/降级）。"""
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.persona_agent import is_knowledge_query
from app.tools.knowledge import KNOWLEDGE_BASE, search_local


def test_search_local_hit() -> None:
    """内置知识库应能命中相关查询。"""
    result = search_local("Hello-Agents 是什么")
    assert result is not None
    assert "Hello-Agents" in result["title"]


def test_search_local_miss() -> None:
    """无关查询应返回 None（不编造）。"""
    assert search_local("量子引力理论详解") is None


def test_knowledge_agent_local() -> None:
    """能力 Agent 本地命中时 origin=local 且有来源。"""
    result = KnowledgeAgent().query("查一下 LangGraph")
    assert result["origin"] == "local"
    assert result["source"] == "内置知识库"
    assert "LangGraph" in result["answer"]


def test_intent_detection_hit() -> None:
    """知识查询意图应被识别。"""
    assert is_knowledge_query("查一下 Hello-Agents 是什么")
    assert is_knowledge_query("介绍一下 RAG")


def test_intent_detection_miss() -> None:
    """日常情感对话不应触发知识查询。"""
    assert not is_knowledge_query("我今天好累")
    assert not is_knowledge_query("嗯嗯，随便聊聊")


def test_knowledge_base_populated() -> None:
    """内置知识库不应为空。"""
    assert len(KNOWLEDGE_BASE) >= 3
