# Virtual Being — AI 虚拟人物

一个**能沟通的专属 Agent**：温柔治愈的二次元角色，通过连接多个 Agent 构建，既能陪伴聊天、也能当助手干活。

## 当前状态：M1（文本灵魂）

- ✅ Ollama 本地推理（qwen2.5:7b）
- ✅ 人格 Agent：温柔治愈人设角色卡 + 提示词注入
- ✅ 会话内记忆（最近 N 轮）
- ✅ FastAPI 服务 + CLI 演示
- ⏳ M2：连接能力 Agent（多 Agent）

## 快速开始

```powershell
pip install -r requirements.txt
python -m scripts.run_demo          # CLI 对话
uvicorn app.main:app --port 8000    # Web API
```

要求：本机已安装并启动 [Ollama](https://ollama.com)，已拉取 `qwen2.5:7b`。

## API

- `POST /chat` — `{"query": "你好", "session_id": "可选"}` → `{"reply": "...", "session_id": "..."}`
- `GET /health` — 健康检查

## 架构（M1）

```
用户输入 → 会话记忆(最近N轮) → 人格Agent(角色卡+提示词) → Ollama qwen2.5:7b → 回复
```

## 相关文档（知识库）

- 产品定义 / 技术选型 / 里程碑计划：`30 · 项目/AI虚拟人物/`
- 领域知识：`20 · 工作领域/`
