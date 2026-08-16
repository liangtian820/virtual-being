"""意图→候选工具组（迭代 6，M6.4，WO-20260816-32）。

问题：工具集从 10 扩到 26（10 内置 + 16 Obsidian MCP）后，qwen2.5:7b 面对过长的
tools schema 列表干脆不调用任何工具（复现确认：无 tool_calls）。
方案：意图预筛 + 候选工具子集——按用户输入用轻量规则判定候选工具组，
只把候选组的 schema 交给 LLM 决策（每组 ≤8），候选未命中 → 回退现有关键词路由。

设计原则（总控修复方向 + 角色必守规则）：
- 不删除/不降级任何工具：26 个工具全部保留在注册表，只是决策时按组裁剪；
- 预筛保守：组选择只决定"本轮能给 LLM 看哪些工具"，最终是否调用仍由 LLM 决定，
  误判宁可回退关键词路由，不硬路由；
- 写操作工具（obsidian_vault_write 等）只进写组，默认不暴露；
- 意图判定函数在 persona_agent（与既有 is_knowledge_query 等一致），本模块
  运行时延迟导入避免循环依赖。
"""
from typing import List

# ---------- 候选工具组（每组 ≤8） ----------

# 日程组：增删查/完成
_SCHEDULE_TOOLS = ("get_schedule", "add_schedule", "mark_schedule_done", "delete_schedule")
# 记忆组
_MEMORY_TOOLS = ("query_memory",)
# 计算组
_CALC_TOOLS = ("calculate",)
# 规划组
_PLANNING_TOOLS = ("list_plans", "save_plan")
# 知识/资讯组（任务单示例组）：内置知识 + 联网搜索 + 知识库检索
_KNOWLEDGE_TOOLS = ("query_knowledge", "web_search", "obsidian_search_simple", "obsidian_vault_list")
# 默认常用组（无明确意图时的兜底能力子集，≤8）
_DEFAULT_TOOLS = ("query_knowledge", "web_search", "calculate", "query_memory",
                  "add_schedule", "get_schedule", "list_plans", "save_plan")

# Obsidian MCP 工具组（前缀 obsidian_，16 个按读/写分类全量覆盖）
_OBSIDIAN_READ_TOOLS = (
    "obsidian_vault_list", "obsidian_vault_read",
    "obsidian_search_simple", "obsidian_search_query",
    "obsidian_vault_get_document_map", "obsidian_active_file_get_path",
    "obsidian_tag_list", "obsidian_open_file",
)
_OBSIDIAN_WRITE_TOOLS = (
    "obsidian_vault_write", "obsidian_vault_append", "obsidian_vault_patch",
    "obsidian_vault_delete", "obsidian_vault_move", "obsidian_vault_copy",
    "obsidian_command_list", "obsidian_command_execute",
)

# 组名 → 工具名元组（LLM 候选集 = 命中的组；每组 ≤8）
TOOL_GROUPS: dict = {
    "schedule": _SCHEDULE_TOOLS,
    "memory": _MEMORY_TOOLS,
    "calculate": _CALC_TOOLS,
    "planning": _PLANNING_TOOLS,
    "knowledge": _KNOWLEDGE_TOOLS,
    "obsidian_read": _OBSIDIAN_READ_TOOLS,
    "obsidian_write": _OBSIDIAN_WRITE_TOOLS,
    "default": _DEFAULT_TOOLS,
}

# 全部组内工具名（供全量覆盖校验：26 = 10 内置 + 16 Obsidian）
ALL_GROUP_TOOL_NAMES = frozenset(n for names in TOOL_GROUPS.values() for n in names)

# 候选上限（LLM 决策 schema 数；组定义保证 ≤8，此处防御性兜底）
MAX_CANDIDATES = 8


def _select_groups(text: str) -> List[str]:
    """意图 → 候选工具组（优先级判定，返回单一主组，保证候选 ≤8）。

    优先级：计算/记忆/日程/规划（强特定词）→ 知识库写 → 知识库读 → 知识/资讯 → 默认。
    与 persona_agent 的关键词路由链一致地保守：多意图时主意图优先，次意图由
    关键词路由兜底（不硬路由）。
    """
    from app.agents.persona_agent import (  # 延迟导入避免循环依赖
        is_calculator_query, is_memory_query, is_schedule_query, is_planning_query,
        is_obsidian_write_query, is_obsidian_query, is_knowledge_query, is_web_search_query,
    )
    if is_calculator_query(text):
        return ["calculate"]
    if is_memory_query(text):
        return ["memory"]
    if is_schedule_query(text):
        return ["schedule"]
    if is_planning_query(text):
        return ["planning"]
    if is_obsidian_write_query(text):
        return ["obsidian_write"]
    if is_obsidian_query(text):
        return ["obsidian_read"]
    if is_knowledge_query(text) or is_web_search_query(text):
        return ["knowledge"]
    return ["default"]


def select_candidate_tool_names(text: str) -> List[str]:
    """按用户输入判定候选工具组，返回候选工具名列表（≤8，去重保序）。

    :param text: 用户输入
    :return: 候选工具名（内置 + Obsidian 均按名引用；是否可用由注册表/内置集决定）
    """
    names: List[str] = []
    for g in _select_groups(text):
        for n in TOOL_GROUPS[g]:
            if n not in names:
                names.append(n)
    return names[:MAX_CANDIDATES]


# ---------- 工具规则提示（阶段 1 指引用：工具名 → 一句话规则） ----------

TOOL_RULE_HINTS: dict = {
    # 日程
    "get_schedule": "用户问『今天/明天有什么安排/我的日程/我的安排』 → 调用 get_schedule；",
    "add_schedule": "用户说『提醒我/记得提醒/帮我记/记一下/闹钟/待办/几点提醒/叫我起床』等要记录提醒的话 → 必须调用 add_schedule（参数 text 传用户原话）；",
    "mark_schedule_done": "用户表示某条提醒已完成/办完了（『完成了/做完了』『标记完成』）→ 调用 mark_schedule_done；",
    "delete_schedule": "用户要求删除某条提醒（『删掉/取消/移除』）→ 调用 delete_schedule；",
    # 记忆
    "query_memory": "用户问『你记得我…/我说过…/我的记忆/我之前…』 → 调用 query_memory；",
    # 知识 / 资讯
    "query_knowledge": "用户问知识概念（什么是/介绍一下/查一下/帮我查）→ 调用 query_knowledge；",
    "web_search": "用户问最新资讯/新闻/教程/实时信息，或内置知识库查不到的内容 → 调用 web_search（参数 query 传简洁关键词，如『DeepSeek 最新新闻』）。",
    # 计算
    "calculate": "用户要求算数/百分比（算一下/多少的/百分之）→ 调用 calculate；",
    # 规划
    "list_plans": "用户问保存过的计划 → 调用 list_plans；",
    "save_plan": "用户要求把计划保存/存下来（『存下来/保存这个计划』『把计划存起来』）→ 调用 save_plan；",
    # Obsidian 知识库（读取）
    "obsidian_vault_list": "用户要看知识库/笔记的目录或文件夹结构（如『列出知识库…』）→ 调用 obsidian_vault_list（参数 path，如 '/' 或 '30 · 项目'）；",
    "obsidian_vault_read": "用户要看知识库某个文件的内容 → 调用 obsidian_vault_read（参数 file 传文件路径）；",
    "obsidian_search_simple": "用户要在知识库/笔记里搜索内容（如『知识库里有没有…』『搜一下笔记』）→ 调用 obsidian_search_simple（参数 query 传关键词）；",
    "obsidian_search_query": "用户要在知识库里做复杂结构化检索 → 调用 obsidian_search_query；",
    "obsidian_vault_get_document_map": "用户要看知识库文档的结构（标题层级）→ 调用 obsidian_vault_get_document_map；",
    "obsidian_active_file_get_path": "用户问当前打开的笔记文件 → 调用 obsidian_active_file_get_path；",
    "obsidian_tag_list": "用户问知识库有哪些标签 → 调用 obsidian_tag_list；",
    "obsidian_open_file": "用户要打开某个知识库文件 → 调用 obsidian_open_file；",
    # Obsidian 知识库（写入/管理）
    "obsidian_vault_write": "用户要新建/覆盖知识库文件 → 调用 obsidian_vault_write；",
    "obsidian_vault_append": "用户要在知识库文件末尾追加内容 → 调用 obsidian_vault_append；",
    "obsidian_vault_patch": "用户要修改知识库文件的某处内容 → 调用 obsidian_vault_patch；",
    "obsidian_vault_delete": "用户要删除知识库文件 → 调用 obsidian_vault_delete；",
    "obsidian_vault_move": "用户要移动/重命名知识库文件 → 调用 obsidian_vault_move；",
    "obsidian_vault_copy": "用户要复制知识库文件 → 调用 obsidian_vault_copy；",
    "obsidian_command_list": "用户问 Obsidian 有哪些可用命令 → 调用 obsidian_command_list；",
    "obsidian_command_execute": "用户要执行某个 Obsidian 命令 → 调用 obsidian_command_execute；",
}


# ---------- Obsidian 工具名清单（测试/兜底用） ----------

OBSIDIAN_TOOL_NAMES = _OBSIDIAN_READ_TOOLS + _OBSIDIAN_WRITE_TOOLS
