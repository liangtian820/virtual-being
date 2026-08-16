"""插件注册表（迭代 5，M6.3 插件化——对标 DSH 插件概念）。

工具注册表：任何工具（内置/插件/MCP）统一注册为 {schema, handler, enabled}，
人格 Agent 的工具调用（function calling）从注册表聚合 schema 并分发执行。

设计要点（Agent架构师 A-03a 角色流程评审口径）：
- 注册表是唯一工具来源（schemas() 聚合给 Ollama tools 参数；call() 分发执行）；
- 插件可动态注册/注销/启停（set_enabled），实现"可插拔"；
- 内置工具（tool_specs 9+1 个）保持既有分发，插件注册表承接外部工具
  （插件模块、MCP 服务器等），两者由 persona_agent 合并调用。
"""
import logging
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# handler 签名：def handler(arguments: dict) -> str（返回结果字符串，失败返回错误说明）
Handler = Callable[[dict], str]


class ToolRegistry:
    """工具注册表：schema + handler + enabled 的集合。"""

    def __init__(self) -> None:
        self._tools: Dict[str, dict] = {}

    def register(self, name: str, schema: dict, handler: Handler, enabled: bool = True) -> None:
        """注册一个工具。name 冲突时覆盖并告警（后注册优先，便于插件覆盖内置）。"""
        if name in self._tools:
            logger.warning("工具 %s 重复注册，已覆盖（后注册优先）", name)
        self._tools[name] = {"schema": schema, "handler": handler, "enabled": enabled}

    def unregister(self, name: str) -> None:
        """注销工具（可插拔）。"""
        self._tools.pop(name, None)

    def set_enabled(self, name: str, enabled: bool) -> None:
        """启停工具（运行时热切换）。"""
        if name in self._tools:
            self._tools[name]["enabled"] = enabled

    def names(self) -> List[str]:
        """全部已注册工具名。"""
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        return name in self._tools and self._tools[name]["enabled"]

    def schemas(self) -> list:
        """聚合启用工具的 schema（供 Ollama /api/chat tools 参数）。"""
        return [t["schema"] for t in self._tools.values() if t["enabled"]]

    def call(self, name: str, arguments: dict) -> str:
        """执行工具：未注册/未启用/执行异常 → 返回错误说明（不抛异常，交 LLM 处理）。"""
        tool = self._tools.get(name)
        if not tool or not tool["enabled"]:
            return f"错误：未知或未启用的工具 {name}"
        try:
            result = tool["handler"](arguments or {})
            return result if isinstance(result, str) else str(result)
        except Exception as exc:  # 任何执行异常如实返回
            logger.warning("插件工具 %s 执行失败: %s", name, exc)
            return f"错误：工具执行失败 {exc}"


# 全局单例：全应用共享（内置工具在 persona_agent 内分发的同时，外部工具统一走注册表）
registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """获取全局工具注册表单例。"""
    return registry
