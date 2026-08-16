"""插件加载器（迭代 5，M6.3 插件化）。

从插件目录发现插件模块并注册到全局注册表。插件模块约定：
- 位于 `app/plugins/autoload/`（或经 MCP 客户端运行时注册）；
- 每个插件模块导出 `register(registry)` 函数，内部调用 registry.register(...)；
- 插件亦可导出 `PLUGIN_META = {"name": ..., "version": ...}`（可选，供审计/启停）。

加载策略：启动时调用 load_plugins() 扫描目录并逐个注册；单个插件失败不阻断
（记录告警继续），保证"可插拔不炸"。
"""
import importlib
import logging
import pkgutil
from typing import List

logger = logging.getLogger(__name__)

_PLUGIN_PACKAGE = "app.plugins.autoload"


def discover_plugin_modules() -> List[str]:
    """列出 autoload 包下的插件模块名（不含 __init__）。"""
    try:
        pkg = importlib.import_module(_PLUGIN_PACKAGE)
    except ImportError:
        return []
    return [
        m.name for m in pkgutil.iter_modules(pkg.__path__)
        if not m.name.startswith("_")
    ]


def load_plugins() -> List[str]:
    """加载全部插件并注册；返回成功加载的插件名。单插件失败不阻断。"""
    loaded: List[str] = []
    for mod_name in discover_plugin_modules():
        try:
            mod = importlib.import_module(f"{_PLUGIN_PACKAGE}.{mod_name}")
            if hasattr(mod, "register"):
                mod.register(__import__("app.plugins.registry", fromlist=["registry"]).registry)
                loaded.append(mod_name)
                logger.info("插件已加载: %s", mod_name)
            else:
                logger.warning("插件 %s 无 register() 函数，跳过", mod_name)
        except Exception as exc:  # 单插件失败不阻断整体
            logger.warning("插件 %s 加载失败: %s", mod_name, exc)
    return loaded
