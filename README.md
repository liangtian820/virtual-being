# Virtual Being — AI 虚拟人物

一个**能沟通的专属 Agent**：温柔治愈的二次元角色，通过连接多个 Agent 构建，既能陪伴聊天、也能当助手干活。

## 当前状态：M4（语音）

- ✅ M1 文本灵魂：Ollama 本地推理（qwen2.5:7b）+ 人格 Agent + 会话内记忆
- ✅ M2 能力扩展：知识查询 + 计算能力 Agent（意图路由、人设包装）
- ✅ M3 专属记忆：SQLite 跨会话长期记忆（fact + topic）
- ✅ M4 语音：ASR（Whisper 本地识别，中文）+ TTS（edge-tts 中文女声）+ 语音对话链路（说→听→回→播）
- ⏳ M5：形象（Live2D / 立绘）

## 快速开始

```powershell
pip install -r requirements.txt
python -m scripts.run_demo                # CLI 文本对话
python -m scripts.run_voice_demo --self-test   # CLI 语音对话（自动生成中文输入 → 全链路）
uvicorn app.main:app --port 8000         # Web API
```

要求：本机已安装并启动 [Ollama](https://ollama.com)，已拉取 `qwen2.5:7b`。

### 语音说明（M4）

- **ASR**：faster-whisper 本地识别，默认 `small` 模型（RTX 3060 6GB 可跑），首次使用需联网下载一次模型；
  网络受限时设置 `HF_ENDPOINT=https://hf-mirror.com` 走镜像。
- **TTS**：edge-tts 现成音色（微软在线服务，免费），默认中文女声「晓晓」`zh-CN-XiaoxiaoNeural`；合成需联网。
- **环境变量**：`ASR_MODEL_SIZE`（small/base/medium）、`ASR_DEVICE`（auto/cuda/cpu）、`ASR_LANGUAGE`（zh/auto）、
  `TTS_VOICE`、`TTS_RATE`、`VOICE_REPLY_DIR` 等，见 `app/config.py`。
- **隐私**：不保存用户语音原始数据（API 上传音频处理完即删）；不使用任何未授权音色（禁止声音克隆）。

## API

- `POST /chat` — `{"query": "你好", "session_id": "可选"}` → `{"reply": "...", "session_id": "..."}`
- `POST /chat/voice` — multipart 上传音频（字段 `file`，可选 `session_id`）→
  `{"text", "reply", "session_id", "audio_url", "latencies_ms"}`；`audio_url` 指向
  `GET /voice/replies/{filename}` 可直接播放
- `GET /voice/replies/{filename}` — 下载/播放回复音频（MP3）
- `GET /health` — 健康检查

```powershell
# 语音对话示例（curl）
curl -F "file=@user.mp3" http://127.0.0.1:8000/chat/voice
```

## 架构

### 文本链路（M1-M3）

```
用户输入 → 会话记忆(最近N轮) + 长期记忆检索 → 人格Agent(角色卡+提示词)
         → 意图路由(知识/计算能力Agent注入结果) → Ollama qwen2.5:7b → 回复
```

### 语音链路（M4）

```
用户语音音频 → ASR(Whisper 本地识别) → 人格Agent 对话 → TTS(edge-tts 中文女声) → 回复音频
   （说）            （听）                    （回）                      （说/播）
```

## 延迟基线（M4 实测，本机：RTX 3060 Laptop 6GB + Ollama qwen2.5:7b GPU 82% offload）

真实链路验证（`data/m4_voice/evidence.json`）：输入 4.03s 中文语音 → 识别 → Ollama 对话 → 回复音频 12.1s。

| 分段 | 链路 1（冷启动/长回复） | 链路 2（Ollama 热/中等回复） | 说明 |
| --- | --- | --- | --- |
| ASR（Whisper small） | 3.3s | 5.2s | 与 LLM 争抢 6GB 显存时波动 |
| LLM（qwen2.5:7b） | 17.3s | 4.0s | 单次短回复约 1.3s；长回复 + 冷启动明显变慢 |
| TTS（edge-tts 在线） | 1.5s | 1.8s | 12s 音频 |
| **端到端** | **22.1s** | **11.1s** | 功能可用，距"流畅"（<5s）未达标 |

**结论（如实上报）**：M4 链路功能完整、可运行，但端到端延迟未达"流畅对话"标准，需按下面降级方案优化后才算体验达标。

**降级方案（按优先级）**：
1. **显存争抢**：ASR 与 LLM 共用 6GB 显存是 LLM 变慢主因 → ASR 固定 `ASR_DEVICE=cpu`（已内置自动回退）或换 base/tiny；Ollama `OLLAMA_CONTEXT_LENGTH` 调小。
2. **回复长度约束**：人设提示词加"回复 ≤ 30 字、口语短句"，直接砍掉 TTS 时长与 LLM 生成时间（本次回复 12s 音频偏长）。
3. **LLM 换小模型**：`OLLAMA_MODEL=qwen2.5:3b` 或 `llama3.2:3b`（本机已拉取），生成提速数倍。
4. **ASR 换小模型**：`ASR_MODEL_SIZE=base`（约 1-2s）或 tiny。
5. **TTS 缓存**：相同回复文本复用合成结果；常用开场白预合成；回复前先截断。
6. **常驻进程**：API 模式单例长驻（模型只加载一次），避免每次请求冷启动。

**GPU 加速说明**：本机无 CUDA Toolkit，Whisper 走 GPU 需 `pip install nvidia-cublas-cu12` 并把
`<venv>\Lib\site-packages\nvidia\cublas\bin` 加入 PATH；未配置时 ASR 自动回退 CPU int8（如实降级，不假装 GPU 可用）。

## 测试

```powershell
python -m pytest -q        # 全部离线：mock ASR/TTS 与外部服务
```

## 相关文档（知识库）

- 产品定义 / 技术选型 / 里程碑计划：`30 · 项目/AI虚拟人物/`
- 领域知识：`20 · 工作领域/`
