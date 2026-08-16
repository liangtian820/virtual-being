# Virtual Being — AI 虚拟人物

一个**能沟通的专属 Agent**：温柔治愈的二次元角色，通过连接多个 Agent 构建，既能陪伴聊天、也能当助手干活。

> **GitHub 仓库**：`https://github.com/liangtian820/virtual-being`
> 当前为本地 git 仓库，等待首次推送（README 徽章在推送后补充）。

## 当前状态：M6（打磨与展示）

- ✅ M1 文本灵魂：Ollama 本地推理（qwen2.5:7b）+ 人格 Agent + 会话内记忆
- ✅ M2 能力扩展：知识查询 + 计算能力 Agent（意图路由、人设包装）；M2.1 追加规划助手 + 日程备忘（WO-20260816-20）
- ✅ M3 专属记忆：SQLite 跨会话长期记忆（fact + topic）
- ✅ M3.5 记忆向量化：Ollama all-minilm 语义检索 + jieba 中文分词 + 语义/关键词融合（`app/memory/`）
- ✅ M4 语音：ASR（Whisper 本地识别，中文）+ TTS（edge-tts 中文女声）+ 语音对话链路（说→听→回→播）
- ✅ M5 形象：Web 聊天界面（程序化原创立绘 + 表情状态 + 语音控件）
- 🚧 M6 打磨展示：README 架构图与演示脚本（进行中）、角色一致性评测（`docs/consistency_testset.md`）、GitHub 仓库准备

## 功能清单

| 能力 | 里程碑 | 说明 | 入口 |
| --- | --- | --- | --- |
| 文本对话（人格） | M1 | 温柔治愈二次元人设，Ollama qwen2.5:7b 本地推理 | `POST /chat`、`scripts/run_demo.py` |
| 能力扩展 | M2 | 知识查询 + 计算 + 规划 + 日程备忘能力 Agent（意图路由、人设包装） | `app/agents/knowledge_agent.py`、`calculator_agent.py`、`planning_agent.py`、`schedule_agent.py` |
| 规划助手 | M2.1 | 模糊目标 → 结构化步骤清单（目标/带序号步骤/预估优先级，LLM 生成、输出 JSON） | `app/agents/planning_agent.py`、`app/tools/planning.py` |
| 日程备忘 | M2.1 | 自然语言提醒 → 日程条目（时间/事项）+ SQLite 持久化（`data/`，gitignored）+ 今日/明日查询 | `app/agents/schedule_agent.py`、`app/tools/schedule.py` |
| 专属记忆 | M3/M3.5 | SQLite 跨会话长期记忆（fact/topic 抽取、去重、线程安全）+ 向量语义检索与关键词融合 | `app/memory/long_term_memory.py`、`app/memory/embeddings.py` |
| 语音对话 | M4 | 说→听→回→播：Whisper ASR（本地识别）+ edge-tts TTS（中文女声） | `POST /chat/voice`、`scripts/run_voice_demo.py` |
| 形象（Web 界面） | M5 | 程序化原创立绘 + 4 表情状态 + 按住说话语音控件 | `GET /`、`web/` |
| 延迟优化 | M4.1/M4.2 | Ollama keep_alive、回复截断、TTS LRU 缓存、ASR 启动预加载 | 证据 `data/m4_voice/evidence_m4{1,2}.json` |

## 快速开始

```powershell
pip install -r requirements.txt
python -m scripts.run_demo                # CLI 文本对话
python -m scripts.run_voice_demo --self-test   # CLI 语音对话（自动生成中文输入 → 全链路）
uvicorn app.main:app --port 8000         # Web 服务
```

要求：本机已安装并启动 [Ollama](https://ollama.com)，已拉取 `qwen2.5:7b`。

### Web 聊天界面（M5）

启动服务后，浏览器打开 **http://127.0.0.1:8000/** 即可与 TA 面对面聊天：

- **立绘形象**：程序化原创 SVG 二次元立绘（温柔治愈风，无版权风险），带轻微浮动/呼吸动态
- **表情状态**：默认 / 思考 / 说话 / 开心，随对话自动切换（发送时思考、回复时说话、收到后开心）
- **文本对话**：走真实 `POST /chat` API（不造假数据）
- **语音对话**：按住 🎙 说话 → 浏览器录音（MediaRecorder）→ `POST /chat/voice` → 自动播放回复音频
- 页面轻量：原生 HTML/CSS/JS 单页，无框架依赖，支持减弱动画（`prefers-reduced-motion`）

### 语音说明（M4，含 M4.2 默认调优）

- **ASR**：faster-whisper 本地识别，默认 `base` 模型 + CPU(int8)（`ASR_MODEL_SIZE`/`ASR_DEVICE`/`ASR_COMPUTE_TYPE`），
  链上稳定约 0.9s 且不占用 Ollama 显存。
- **ASR 模型本地路径**：默认从项目 `data/models` 加载（`ASR_MODEL_DIR` 可指定；支持 HF 缓存布局
  `models--Systran--faster-whisper-{size}` 或扁平目录）。**首次使用无本地模型时**需联网下载一次：
  网络直连不稳时设置 `HF_ENDPOINT=https://hf-mirror.com` 走国内镜像。
- **TTS**：edge-tts 现成音色（微软在线服务，免费），默认中文女声「晓晓」`zh-CN-XiaoxiaoNeural`；合成需联网，
  同文本命中 LRU 缓存（`TTS_CACHE_DIR`，默认 `data/tts_cache`）时仅约 8ms。
- **环境变量**：`ASR_MODEL_SIZE`（base/small/medium）、`ASR_DEVICE`（auto/cuda/cpu）、`ASR_LANGUAGE`（zh/auto）、
  `ASR_PRELOAD`（1/0，默认启动预加载）、`OLLAMA_KEEP_ALIVE`（默认 `60m` 长驻）、`VOICE_MAX_REPLY_CHARS`（默认 `60`）、
  `TTS_VOICE`、`TTS_RATE`、`VOICE_REPLY_DIR` 等，见 `app/config.py`。
- **隐私**：不保存用户语音原始数据（API 上传音频处理完即删）；不使用任何未授权音色（禁止声音克隆）。

### 长期记忆（M3 / M3.5）

- **存储**：SQLite 双表——`memories`（fact/topic 文本，既有结构不变）+ `memory_embeddings`（向量，
  独立新表，旧数据按需 lazy 补向量，不迁移不破坏）。
- **检索三接口**（`app/memory/long_term_memory.py`）：
  - `retrieve(query, limit, days)` — 关键词检索（既有行为不变，向后兼容）
  - `retrieve_semantic(query, k, days)` — 向量语义检索（Ollama all-minilm 余弦相似度，近义可命中）
  - `retrieve_fused(query, limit, days)` — 语义 + 关键词加权融合（默认 0.6/0.4，可配置）
- **中文分词**：jieba（`app/memory/embeddings.py#segment`）用于 query/文本预处理。
- **embedding**：Ollama 本地 `all-minilm:latest`（HTTP `http://127.0.0.1:11434`，带超时；服务不可用时
  语义/融合自动降级为关键词检索，记忆读写不受影响）。
- **环境变量**：`EMBEDDING_MODEL`（默认 `all-minilm:latest`）、`EMBEDDING_BASE_URL`、
  `EMBEDDING_DIM`（默认 384）、`MEMORY_SEMANTIC_THRESHOLD`（默认 0.35）、
  `MEMORY_FUSION_SEMANTIC_WEIGHT`/`MEMORY_FUSION_KEYWORD_WEIGHT`（默认 0.6/0.4）、
  `MEMORY_AUTO_BACKFILL`（默认 1，语义检索时对旧数据 lazy 补向量），见 `app/config.py`。

## API

- `GET /` — Web 聊天界面首页（立绘 + 对话窗 + 语音控件）
- `GET /static/*` — 前端静态资源（css/js，来自 `web/` 目录）
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

### 全链路总览（M1-M5）

```
┌─────────────────────────────── 用户层 ───────────────────────────────┐
│  Web 聊天界面（M5）                       CLI 演示                   │
│  立绘 + 4 表情状态机    按住说话(录音)     scripts/run_demo.py       │
└───────────────┬───────────────────────────────┬──────────────────────┘
                │ POST /chat (JSON 文本)        │ POST /chat/voice (音频)
                ▼                               ▼
┌────────────────────────── 服务层（FastAPI, app/main.py）──────────────────────┐
│  /chat         会话记忆(M1) + 长期记忆检索(M3) → 人格对话                       │
│  /chat/voice   ASR(M4) → 人格对话 → 回复截断(M4.1) → TTS(M4)                   │
│  /voice/replies/{filename} 回复音频下载（防路径穿越）                           │
│  /static、/     Web 静态资源与聊天页（M5）                                     │
└───────────────┬───────────────────────────────▲───────────────────────────────┘
                │ 注入工具结果 / 记忆            │ 回复音频
                ▼                               │
┌────────────────────────────── Agent 层 ───────────────────────────────────────┐
│  人格 Agent（角色卡 + 提示词，温柔治愈人设）                                    │
│    ├─ 意图路由 → 知识查询 Agent（M2）/ 计算能力 Agent（M2）                     │
│    └─ 长期记忆：fact/topic 抽取、去重、SQLite 持久化（M3）                      │
└──────────────────────────────┬─────────────────────────────────────────────────┘
                               ▼
              Ollama qwen2.5:7b（本地 LLM，keep_alive 长驻）
```

分链路细节见下。

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

### 形象链路（M5）

```
浏览器(立绘+表情状态机) → POST /chat(文本) / POST /chat/voice(MediaRecorder 录音)
      → 后端真实链路 → 回复文本逐字"说话"+回复音频自动播放 → 表情:思考→说话→开心
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

## M4.1 延迟优化（实测对比，证据 `data/m4_voice/evidence_m41.json`）

| 分段 | 优化前（M4 基线） | 优化后（M4.1） | 变化 |
| --- | --- | --- | --- |
| LLM 冷启动（首调） | 17.3s | 3.4s | keep_alive 长驻生效（-80%） |
| LLM（热态对话） | 4.5s | 4.1s | 稳定 <5s |
| TTS（未命中缓存） | 1.7s | 1.5~2.5s | — |
| TTS（缓存命中） | — | **7.7ms** | 跳过在线合成 |
| 端到端（热态） | 9.7s | 8.3s | 下降 14%（受 ASR 波动影响） |
| 长回复场景 | 22.1s（425 字全文合成） | 43 字截断后合成 | 语音时长大幅缩短 |

M4.1 三项优化：

1. **Ollama keep_alive 长驻**（`OLLAMA_KEEP_ALIVE`，默认 `60m`）：模型常驻显存/内存，
   冷启动 17.3s → 3.4s，热态对话稳定 <5s（`ollama ps` 可见 UNTIL 59min）。
2. **语音回复长度约束**（`VOICE_MAX_REPLY_CHARS`，默认 `60`）：pipeline 在 TTS 前截断到句末标点；
   真实链路 425 字长回复 → 43 字语音（完整回复保留在 `reply_full`，会话记忆与文本 API 不受影响）。
3. **TTS LRU 缓存**（`TTS_CACHE_DIR`/`TTS_CACHE_SIZE`，默认 `data/tts_cache`/128）：
   key = 文本+音色+语速（sha1），命中直接复用音频（实测 7.7ms vs 未命中 1.4s）。

**ASR 权衡实测**（同输入 4.03s 中文，3 次中位数，准确率均 1.0，证据 `data/m4_voice/asr_bench.json`）：

| 配置 | 延迟 | 建议 |
| --- | --- | --- |
| base/CPU（int8） | 937ms | **M4.2 当前默认**：稳定且不抢 Ollama 的 6GB 显存 |
| base/GPU（int8_float16） | 228ms | 显存充裕/延迟敏感首选 |
| small/GPU（int8_float16） | 324ms | 需 cuBLAS + PATH（会与 LLM 争显存） |
| small/CPU（int8） | 2523ms | 需要更大模型精度时可选 |

**遗留风险**：链路上 ASR 实测 2.6~9.3s 波动（首次 GPU 推理初始化 + 与 Ollama 争抢 6GB 显存），
单独基准仅约 0.3s；建议语音服务常驻时 ASR 固定 CPU 或换 base/GPU、并让 Ollama 与 ASR 显存错峰。

## M4.2 加载/延迟冲刺（实测对比，证据 `data/m4_voice/evidence_m42.json`）

| 指标 | 优化前（用户反馈/M4.1） | 优化后（M4.2） |
| --- | --- | --- |
| 首次 /chat/voice 模型加载 | ~90s（用户感知"加载太久"） | **启动预加载 0.7s**，首次请求 ASR 仅 1.0s |
| 服务启动到可服务 | 预加载卡 43s（HF 联网校验超时） | **0.7s**（本地快照直读，跳过 HF 校验） |
| 热态端到端 | 8.3~9.7s | 6.2~7.0s |
| 长回复 LLM 生成 | 14.3s / 425 字 | 9.3s / 52 字（-35% / -88%） |

M4.2 四项优化：

1. **ASR 启动预加载**（`ASR_PRELOAD=1` 默认开）：FastAPI lifespan 启动时加载 ASR 模型 +
   后台预热 Ollama（keep_alive），首次语音请求零模型加载等待（启动日志 `[startup] ASR 模型预加载完成`）。
2. **本地快照直读**：模型在 `data/models`（HF 缓存布局或扁平目录均可）时直接按路径加载，
   跳过 huggingface_hub 联网校验——修复直连被墙时的启动卡顿（实测预加载 43.2s → 0.7s）。
3. **ASR 默认调优**：默认 `ASR_MODEL_SIZE=base` + `ASR_DEVICE=cpu` + `ASR_COMPUTE_TYPE=int8`
   （链上实测 ASR 稳定 ~0.9s，且不占用 Ollama 的显存）。
4. **LLM 生成长度源头限制**：voice 路径按 `max_reply_chars` 映射 Ollama `num_predict`
   （60 字 → 162 tokens），不再"先生成几百字再截断"（长回复 LLM 14.3s → 9.3s）。

UI（web/）语音处理中分阶段提示：识别中 → TA 正在思考 → 正在合成回复，避免用户误判卡死。

**热态端到端仍未达标（<5s）**：实测 6.2~7.0s，瓶颈为 LLM 生成（3.6~4.5s）与 TTS 在线合成（1.6~1.8s）；
后续候选：LLM 换 qwen2.5:3b/llama3.2:3b、TTS 本地化/流式首包、回复 ≤40 字。

## M4.3 语音 <5s 冲刺（实测，证据 `data/m4_voice/evidence_m43.json` / `evidence_m43_persona.json`）

**实测矩阵**（进程内 pipeline：ASR base/CPU + Ollama keep_alive + edge-tts 在线，热态 3 次中位）：

| 组合 | LLM 中位 | 端到端中位 |
| --- | --- | --- |
| qwen2.5:7b / 60字 | 4.1s | 8.5s |
| qwen2.5:7b / 40字 | 3.6s | 8.3s |
| llama3.2:3b / 60字 | 3.1s | 7.5s |
| llama3.2:3b / 40字 + piper 本地 TTS | **2.9s** | **4.2s** ✅ |

**达标结论（如实）**：
- ✅ **热态端到端 <5s 达成（有条件）**：`VOICE_LLM_MODEL=llama3.2:3b` + `TTS_BACKEND=piper` + 40 字默认，
  3 次实测 4.62/4.18/4.19s（中位 **4.19s**，3/3 达标；分项 ASR 0.96s + LLM 2.88s + piper 0.36s）。
- ⚠️ **默认组合（7b + edge-tts）未达标**（7.5~8.5s），瓶颈 LLM 3.6-4.1s + edge-tts 在线 1.6-2.5s
  （本次实测期间 edge-tts 服务多次断连，`speech.platform.bing.com` 不可达——在线 TTS 稳定性风险）。
- M4.3 落地：`VOICE_LLM_MODEL`（语音专用模型，文本链路不受影响）、`TTS_BACKEND=edge_tts|piper`
  （piper 本地离线中文音色 `data/models/piper/zh_CN-huayan-medium.onnx`，40 字合成约 0.3-0.4s）、
  `VOICE_MAX_REPLY_CHARS` 默认 60→40。

**3b 人设不退化验证**（llama3.2:3b，consistency_testset 关键 8 条：T01/T03/T05/T07/T16/T18/T23/T28）：
**5 PASS + 3 WARN（0 FAIL、无红线触发）**——M6 代码层注入（能力边界/身份/空记忆防编造/危机陪伴）在 3b 下全部生效；
WARN 项为英文词夹杂（"just/talk"）与 T23 危机回复未主动提示专业求助——建议生产用 3b 时在系统提示词补一句
"禁止夹英文、危机场景主动提示专业帮助"。

**部署建议（用户已决策，M4.4 落地）**：默认语音组合已切 **`llama3.2:3b + piper 本地 TTS`**（<5s 优先，人设 WARN 可接受）。
如需回切：`VOICE_LLM_MODEL=qwen2.5:7b` / `TTS_BACKEND=edge_tts`（在线晓晓音质好但实测多次断连）。

## M4.4 危机安全补丁 + 默认组合（WO-20260816-21，证据 `data/m4_voice/evidence_m44_crisis.json`）

1. **危机求助引导代码层强制**（不依赖 3b 遵循提示词）：`persona_agent` 危机分支（`is_crisis_query` 命中）在 LLM 回复后
   强制检查——回复未含求助线索（热线/12356/专业帮助/家人朋友等）则追加人设口吻求助句
   「如果你愿意，也可以找信任的家人或朋友聊聊，或拨打心理援助热线（如 12356），我一直在。」；
   LLM 已含则跳过（防重复，单测覆盖两情况）。
2. **危机语音回复不截断**：pipeline 对危机路径跳过 40 字截断，保证求助句完整输出（安全优先于延迟）。
3. **默认组合变更**：`VOICE_LLM_MODEL` 默认 `llama3.2:3b`、`TTS_BACKEND` 默认 `piper`。
4. **3b 危机真实 smoke（llama3.2:3b，3 条）**：全部含专业求助引导——LLM 已含（12356/家人朋友）→ 不重复；
   LLM 未含 → 代码层追加。证据见 `data/m4_voice/evidence_m44_crisis.json`。

**piper 中文模型下载（gitignored，新克隆需手动准备）**：

```powershell
pip install piper-tts
New-Item -ItemType Directory -Force -Path data/models/piper | Out-Null
curl -L -o data/models/piper/zh_CN-huayan-medium.onnx "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
curl -L -o data/models/piper/zh_CN-huayan-medium.onnx.json "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json"
```

> 已知项（如实）：3b 中文人设偶发夹英文（如 "cool/talked-through"）且风格略飘——危机安全不受影响（代码层兜底），
> 日常口语质量建议后续用 qwen2.5:3b（待网络环境补拉）或提示词补"禁止夹英文"。

## 测试

```powershell
python -m pytest -q        # 全部离线：mock ASR/TTS 与外部服务（规划/日程 Agent 亦 mock LLM）
```

- Web 界面（M5）：`tests/test_web_ui.py`（首页路由 / 静态挂载 / 既有 API 回归护栏）。
- 演示流程：见 `docs/演示脚本.md`（可照做的 6 步演示 + 预期效果 + 截图指引）。

## 相关文档

- 演示脚本：`docs/演示脚本.md`；角色一致性评测：`docs/consistency_testset.md`（M6）
- 产品定义 / 技术选型 / 里程碑计划：`30 · 项目/AI虚拟人物/`（知识库）
- 领域知识：`20 · 工作领域/`（知识库）
