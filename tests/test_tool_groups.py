"""M6.4 意图→候选工具组 离线测试（WO-20260816-32）。

覆盖：候选组判定正确性（web_search/obsidian 工具必在候选集）、每组 schema ≤8、
26 工具全量覆盖（10 内置 + 16 Obsidian，只裁剪不丢失）、意图优先级、回退不破坏。
全部离线：不依赖 Ollama/网络/Obsidian MCP。
"""
import pytest

from app.agents.persona_agent import (
    extract_search_query,
    is_obsidian_query,
    is_obsidian_write_query,
    is_web_search_query,
)
from app.tools.tool_groups import (
    ALL_GROUP_TOOL_NAMES,
    OBSIDIAN_TOOL_NAMES,
    TOOL_GROUPS,
    select_candidate_tool_names,
)
from app.tools.tool_specs import get_tool_specs

# Obsidian MCP 实际 16 个工具名（与注册表/本地服务器一致）
EXPECTED_OBSIDIAN_TOOLS = {
    "obsidian_vault_list", "obsidian_vault_read",
    "obsidian_vault_write", "obsidian_vault_append", "obsidian_vault_patch",
    "obsidian_vault_delete", "obsidian_vault_move", "obsidian_vault_copy",
    "obsidian_vault_get_document_map", "obsidian_active_file_get_path",
    "obsidian_search_query", "obsidian_search_simple",
    "obsidian_tag_list", "obsidian_command_list", "obsidian_command_execute",
    "obsidian_open_file",
}


# ---------- 每组 ≤8 ----------


def test_every_group_size_leq_8():
    for group, names in TOOL_GROUPS.items():
        assert len(names) <= 8, f"候选组 {group} 工具数 {len(names)} 超过 8"


# ---------- 26 工具全量覆盖（可插拔不丢，只是决策时裁剪） ----------


def test_all_26_tools_covered_by_groups():
    builtin = {s["function"]["name"] for s in get_tool_specs()}
    assert len(builtin) == 10
    assert len(EXPECTED_OBSIDIAN_TOOLS) == 16
    covered = set(ALL_GROUP_TOOL_NAMES)
    assert builtin <= covered, f"内置工具缺组内覆盖: {builtin - covered}"
    assert EXPECTED_OBSIDIAN_TOOLS <= covered, f"Obsidian 工具缺组内覆盖: {EXPECTED_OBSIDIAN_TOOLS - covered}"
    # 组内无多余/无遗漏：正好 26
    assert covered == builtin | EXPECTED_OBSIDIAN_TOOLS


def test_obsidian_tool_names_match_mcp():
    """组内 Obsidian 工具名与本地 Obsidian MCP 服务器实际工具一致（16 个）。"""
    assert set(OBSIDIAN_TOOL_NAMES) == EXPECTED_OBSIDIAN_TOOLS


# ---------- 候选组判定正确性 ----------


@pytest.mark.parametrize("text", [
    "帮我搜一下 DeepSeek 最新新闻",
    "查一下 DeepSeek 最新新闻",
    "帮我搜索一下最近的 AI 资讯",
    "最近有什么热点新闻吗",
])
def test_web_search_intent_has_web_search(text):
    names = select_candidate_tool_names(text)
    assert "web_search" in names, f"{text!r} 候选集应含 web_search: {names}"
    assert len(names) <= 8


@pytest.mark.parametrize("text", [
    "列出知识库里 30 项目的文档",
    "查一下知识库里的笔记",
    "帮我看看笔记库有哪些文档",
    "搜一下 Obsidian 里的资料",
])
def test_obsidian_intent_has_obsidian_tools(text):
    names = select_candidate_tool_names(text)
    assert "obsidian_vault_list" in names, f"{text!r} 候选集应含 obsidian_vault_list: {names}"
    assert "obsidian_search_simple" in names, f"{text!r} 候选集应含 obsidian_search_simple: {names}"
    assert len(names) <= 8


def test_obsidian_write_intent_has_write_tools():
    names = select_candidate_tool_names("把这段笔记保存到知识库")
    assert "obsidian_vault_write" in names
    assert "obsidian_vault_patch" in names
    assert len(names) <= 8
    # 写意图命中（与读意图区分）
    assert is_obsidian_write_query("把这段笔记保存到知识库")


def test_knowledge_intent_candidates():
    names = select_candidate_tool_names("什么是 LangGraph？")
    assert "query_knowledge" in names and "web_search" in names
    assert len(names) <= 8


def test_schedule_intent_candidates():
    names = select_candidate_tool_names("明天下午3点提醒我喝水")
    assert set(names) == {"get_schedule", "add_schedule", "mark_schedule_done", "delete_schedule"}


def test_memory_intent_candidates():
    assert select_candidate_tool_names("你记得我喜欢什么吗") == ["query_memory"]


def test_calculate_intent_candidates():
    assert select_candidate_tool_names("300 的 20% 是多少") == ["calculate"]


def test_planning_intent_candidates():
    names = select_candidate_tool_names("帮我规划周末学做饭")
    assert "list_plans" in names and "save_plan" in names
    assert len(names) <= 8


def test_default_intent_candidates():
    names = select_candidate_tool_names("你好呀")
    assert len(names) == 8
    assert "query_knowledge" in names and "web_search" in names
    # 默认组不含写操作工具（保守暴露）
    assert not any(n.startswith("obsidian_") for n in names)


# ---------- 意图检测（保守） ----------


@pytest.mark.parametrize("text", [
    "帮我搜一下 DeepSeek 最新新闻",
    "最近有什么热点新闻",
    "查一下最新的 AI 消息",
])
def test_is_web_search_query_hits(text):
    assert is_web_search_query(text)


@pytest.mark.parametrize("text", [
    "我今天好累",
    "你好呀",
    "什么是 RAG？",
])
def test_is_web_search_query_misses(text):
    assert not is_web_search_query(text)


def test_extract_search_query():
    assert extract_search_query("帮我搜一下 DeepSeek 最新新闻") == "DeepSeek 最新新闻"
    assert extract_search_query("搜索 AI 教程") == "AI 教程"
    assert extract_search_query("今天有什么新闻") == "今天有什么新闻"  # 剥不动回退原文


@pytest.mark.parametrize("text", [
    "列出知识库里 30 项目的文档",
    "查一下知识库里的笔记",
    "把这段笔记保存到知识库",
])
def test_is_obsidian_query_hits(text):
    assert is_obsidian_query(text)


@pytest.mark.parametrize("text", [
    "什么是 RAG？",
    "帮我算一下 3 加 5",
    "今天天气不错",
])
def test_is_obsidian_query_misses(text):
    assert not is_obsidian_query(text)


# ---------- QA P2：新意图不落 topic（记忆噪音回归） ----------


@pytest.mark.parametrize("text", [
    "帮我搜一下 DeepSeek 最新新闻",
    "列出知识库里 30 项目的文档",
])
def test_web_obsidian_intents_not_recorded_as_topic(text):
    """QA P2：联网搜索/知识库查询是请求不是用户陈述，不应记为长期话题（回归自 M6.4）。"""
    from app.agents.persona_agent import extract_memories

    hits = extract_memories(text)
    assert not any(k == "topic" for k, _ in hits), f"{text!r} 不应记为 topic: {hits}"
