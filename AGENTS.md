# AGENTS.md — AI 虚拟人物项目（virtual-being）

## 项目一句话

一个能沟通的专属 Agent——温柔治愈的二次元角色，通过连接多个 Agent 构建（人格 Agent + 能力 Agent），支持陪伴聊天、任务助手、创作与咨询。

## 技术栈

- Python 3.9+，FastAPI + Uvicorn，Pydantic v2
- 本地 LLM：Ollama `qwen2.5:7b`（本地主力），云端 API 兜底（复杂任务）
- Agent 编排：LangGraph（M2 起引入多 Agent）
- 记忆：会话内（M1）→ 向量库长期（M3）
- 语音：Whisper ASR + 现成 TTS（M4）；形象：Live2D/立绘 Web 前端（M5）

## 目录结构

- `app/persona/` — 角色卡与人设提示词（灵魂之魂）
- `app/agents/` — Agent 层（人格 Agent，M2 加能力 Agent）
- `app/memory/` — 记忆模块（会话内 → 长期）
- `app/main.py` — FastAPI 服务入口
- `scripts/run_demo.py` — CLI 对话演示
- `tests/` — pytest 测试（离线，mock 外部服务）

## 开发命令

- 安装：`pip install -r requirements.txt`
- 运行服务：`uvicorn app.main:app --reload --port 8000`
- CLI 演示：`python -m scripts.run_demo`
- 测试：`python -m pytest -q`（离线）

## 编码规范

- Python 3.9+、PEP 8、4 空格缩进、UTF-8 无 BOM
- 公共签名加类型注解；模块 docstring 用中文
- 人名/字段用 snake_case

## 协作约定（AI 与我）

- 任务四要素：背景 + 目标 + 约束 + 验收标准；缺验收先反问
- 需求变更先 3 行清单（内容/影响/是否值得），确认后动手
- 描述问题"给现象不给诊断"
- 本地 git commit 可自主；重要 push 先询问
- 删除/覆盖重要文件先确认并确保可回溯
- 完成标准：可运行 + 测试通过 + 文档 + 证据（截图/日志）
- 小步快跑，阶段汇报，卡住求助

## 产品定义与里程碑

- 产品定义：`30 · 项目/AI虚拟人物/产品定义.md`（知识库）
- 里程碑：M1 文本灵魂 → M2 能力扩展 → M3 专属记忆 → M4 语音 → M5 形象 → M6 打磨展示
- 当前阶段：M1（文本灵魂：能聊天、人设稳定）

## 人设速览（详见 app/persona/character_card.py）

温柔治愈 · 二次元 · 轻设定 · 日常口语 · 专属 AI 伙伴
