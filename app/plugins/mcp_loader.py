"""MCP 服务器注册桥接（迭代 5，M6.3）：把配置的 MCP 服务器工具注册进插件注册表。

配置来源：CONFIG.mcp_servers（环境变量 MCP_SERVERS 的 JSON，格式）：
[
  {"serverName": "obsidian", "url": "http://127.0.0.1:27123/mcp/",
   "headers": {"Authorization": "Bearer <token>"}, "prefix": "obsidian"}
]
单服务器失败不阻断（failOnStartupError: false 语义），返回成功注册总数。
"""
import logging

logger = logging.getLogger(__name__)


def register_configured_mcp_servers(registry) -> int:
    """连接并注册全部配置的 MCP 服务器工具；返回注册工具总数。"""
    from app.config import CONFIG
    from app.mcp_client import register_mcp_server

    total = 0
    for cfg in CONFIG.mcp_servers or []:
        name = cfg.get("serverName", "")
        url = cfg.get("url", "")
        if not name or not url:
            logger.warning("MCP 配置缺 serverName/url，跳过: %s", cfg)
            continue
        try:
            n = register_mcp_server(
                registry,
                server_name=name,
                url=url,
                headers=cfg.get("headers"),
                prefix=cfg.get("prefix"),
            )
            total += n
        except Exception as exc:
            logger.warning("MCP 服务器 %s 注册失败（跳过）: %s", name, exc)
    return total
