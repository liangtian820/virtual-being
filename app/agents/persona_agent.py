"""人格 Agent（M2/M3）：温柔治愈人设对话 + 意图路由到能力 Agent。

M2 编排：
- 意图路由：用户输入命中知识查询意图 → 调用能力 Agent（知识查询）→ 结果作为上下文注入，
  仍由本 Agent（LLM + 人设 prompt）用人设语气组织回复（能力 Agent 不抢人设）。
- 未命中 → 原对话逻辑。

M3 编排：
- 新增计算意图：命中 → 调用能力 Agent（CalculatorAgent）→ 计算结果注入上下文，
  人设包装仍由本 Agent 完成。
"""
import json
import re
import uuid
from typing import List, Optional

import requests

from app.agents.calculator_agent import CalculatorAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.planning_agent import PlanningAgent
from app.agents.schedule_agent import ScheduleAgent
from app.config import CONFIG
from app.memory.embeddings import OllamaEmbedder
from app.memory.long_term_memory import LongTermMemory
from app.memory.session_memory import SessionMemory
from app.persona.prompts import build_system_prompt
from app.plugins.registry import registry as tool_registry
from app.tools.tool_groups import TOOL_GROUPS, TOOL_RULE_HINTS, select_candidate_tool_names
from app.tools.tool_specs import get_tool_specs

# 知识查询意图关键词（起步版简单规则；后续可换模型判断）
# M6.6（WO-20260816-36）：补全口语问法『是干嘛的/是做什么的/是什么东西/有什么用/怎么用』——
# 用户实测『DeepSeek Harness 是干嘛的？』因不在触发词内，工具未触发，7B 含糊编造。
_KNOWLEDGE_PATTERN = re.compile(
    r"(查一下|什么是|是什么|介绍一下|查找|搜索|查询|帮我查|了解|"
    r"是干嘛的|是做什么的|干什么的|干啥的|是什么东西|有什么用|怎么用|咋用)",
    re.IGNORECASE,
)

# 计算意图强关键词（起步版简单规则；后续可换模型判断）
_CALC_STRONG_PATTERN = re.compile(
    r"(算一下|帮我算|帮我计算|算一算|算算|计算|百分之|百分比|多少的|等于多少)",
    re.IGNORECASE,
)
# 数字式子形态：数字 + 运算符（中文运算符/的/%/符号）+ 数字，如 "3 加 5"、"300 的 20%"
_CALC_FORMULA_PATTERN = re.compile(
    r"\d\s*(乘以|除以|加|减|乘|除|[+\-*/×xX]|的|%)\s*\d",
    re.IGNORECASE,
)

# M3：用户事实提取规则（名字/喜好/身份/地点等）
# P3-3 收窄：含糊前缀"我是/我在"后接动作动词（说/想/看/觉得…）不是事实，排除误报，
# 如"我是觉得…/我在想…/我在看…/我是说…"；"我是学生/我在上海"仍保留。
_VERB_FOLLOW = r"(?:说|想|看|觉得|认为|打算|准备|等|听|做|写|读|问|找|用|玩|讲|聊|感觉)"
_FACT_PATTERN = re.compile(
    r"(?:(?:我喜欢|我爱|我不喜欢|我讨厌|我的名字是|我叫|我的生日|我住在|我家在|我今年|我喜欢吃)"
    r"|(?:我是|我在)(?!{})).{{0,30}}".format(_VERB_FOLLOW),
    re.IGNORECASE,
)

# M6 v3（WO-20260816-15，总控批准的路由分支）：心理危机关键词——安全优先，宽松匹配。
# 命中即强制注入危机引导句式（不依赖模型遵循 few-shot），不影响其他意图分支。
CRISIS_KEYWORDS = (
    "不想活", "不想活了", "活不下去", "活着没意思", "活着好累", "活得没意思",
    "撑不下去", "坚持不下去", "伤害自己", "自残", "自杀", "轻生",
    "想消失", "了结自己", "离开这个世界", "不想醒过来",
)


# P3-4（WO-20260816-17）：topic 提取噪音治理——请求/计算/提问/命令类输入不落 topic。
# 原规则"长度≥10 且无？"会把"帮我查一下…""300 的 20% 是多少"等请求/计算/提问误记为话题
# （QA 四轮评测：T01-T24 空记忆库落 14 条 topic 噪音）。现叠加三重排除，只记用户
# 事实/偏好/关系类陈述：① 请求/命令前缀；② 提问句式（疑问词/A不A/句尾语气词/问号）；
# ③ 计算与知识意图（复用下方意图检测，运行时解析，顺序无碍）。
_REQUEST_PREFIX_PATTERN = re.compile(
    r"^\s*(帮我|帮|请|给我|麻烦|求你|替我|拜托|建议|推荐|教我|教教|帮个忙|"
    r"打开|关闭|播放|暂停|安装|卸载|下载|上传|启动|停止|连接|断开|保存|发送|切换|重启|清空)",
    re.IGNORECASE,
)
_QUESTION_PATTERN = re.compile(
    r"(是多少|等于多少|为什么|怎么回事|怎么|如何|哪些|哪个|哪里|什么时候|"
    r"有没有|会不会|能不能|可不可以|是不是|要不要|好不好|行不行|可以吗|好吗|"
    r"吗|呢$|吧$|呀$|啊$|？|\?$)",
    re.IGNORECASE,
)


def _is_topic_worthy(user_input: str) -> bool:
    """判断输入是否值得记为长期话题：排除请求/命令/提问/计算/知识意图，只留用户陈述。"""
    if len(user_input) < 10:
        return False
    # M6.4（WO-20260816-32，QA P2）：联网搜索/知识库查询意图同样不落 topic——
    # 『帮我搜一下 X 新闻』『列出知识库里 30 项目的文档』是请求不是用户事实陈述
    if (is_calculator_query(user_input) or is_knowledge_query(user_input)
            or is_web_search_query(user_input) or is_obsidian_query(user_input)):
        return False
    if _REQUEST_PREFIX_PATTERN.match(user_input):
        return False
    if _QUESTION_PATTERN.search(user_input):
        return False
    return True


def extract_memories(user_input: str) -> List[tuple]:
    """从用户输入提取长期记忆：返回 [(kind, content), ...]（fact / topic）。

    fact 规则锚定用户自称短语（我喜欢/我是/我叫/我住在…），请求/计算类输入天然不命中；
    topic 规则由 _is_topic_worthy 把关，只记用户真实陈述（P3-4 噪音治理）。
    """
    hits: List[tuple] = []
    for m in _FACT_PATTERN.findall(user_input):
        content = m.strip().strip("，。！？")
        if len(content) >= 2:
            hits.append(("fact", content))
    if _is_topic_worthy(user_input):
        hits.append(("topic", user_input[:40]))
    return hits


def is_knowledge_query(text: str) -> bool:
    """判断输入是否为知识查询意图。"""
    return bool(_KNOWLEDGE_PATTERN.search(text))


def is_calculator_query(text: str) -> bool:
    """判断输入是否为计算意图：命中强关键词（算一下/百分之…）或数字式子形态。"""
    return bool(_CALC_STRONG_PATTERN.search(text) or _CALC_FORMULA_PATTERN.search(text))


def is_crisis_query(text: str) -> bool:
    """判断输入是否含心理危机信号（安全优先，宽松匹配；总控批准的路由分支，M6 v3）。"""
    return any(kw in text for kw in CRISIS_KEYWORDS)


# M5.1（WO-20260816-22）：规划 / 日程 / 记忆问答意图检测。
# 设计原则：强关键词保守匹配，误判宁可交人格自由发挥（不硬路由、保持人设）；
# 不抢知识/计算分支（路由顺序：危机 → 知识 → 计算 → 记忆 → 规划 → 日程 → 普通）。
_PLANNING_PATTERN = re.compile(
    r"(帮我规划|帮我做个计划|帮我制定|做个计划|制定计划|规划一下|计划一下|"
    r"帮我安排|安排一下|列个计划|立个计划|帮我计划|怎么学|怎么开始|从哪开始|从哪儿开始|"
    r"怎么做|怎么准备|怎么入门|帮我拆分|拆分一下|目标拆解|学习计划|行动方案|制定.*方案)",
    re.IGNORECASE,
)
_SCHEDULE_PATTERN = re.compile(
    r"(提醒我|记得提醒|帮我记|记一下|日程|闹钟|待办|几点|"
    r"有什么安排|啥安排|什么安排|安排查询|我的安排|安排列表|安排都有|"
    r"今天有|明天有|后天有|今天的安排|明天的安排|安排一下|"
    r"叫我起床|叫醒我|喊我起床|叫我起来)",
    re.IGNORECASE,
)
_SCHEDULE_LOOKUP_PATTERN = re.compile(
    r"(有什么安排|啥安排|什么安排|安排查询|我的安排|我的日程|安排列表|安排都有|"
    r"今天有|明天有|后天有|今天的安排|明天的安排|待办|日程查询|查一下.*日程|日程.*是什么)",
    re.IGNORECASE,
)
# 记忆问答：询问"你记得我…/我说过…/我的记忆…"（回忆 ≠ 提醒，见 is_memory_query 排除规则）
_MEMORY_PATTERN = re.compile(
    r"(你(还)?记得我|记不记得我|还记得我吗|你记得吗|你还记得|你记得不|"
    r"我的记忆|记忆里|记忆有|我记得|之前说的|上次说的|我说过|我跟你说过|我给你说过|"
    r"我之前|我上次|你了解我吗|你了解我|我的喜好|我的爱好|我喜欢什么|喜欢什么来着|"
    r"我的计划是什么|我说过什么|我跟你讲过|我提过)",
    re.IGNORECASE,
)
# 记忆列示："我的记忆有哪些"（摘要级列示，不含内部元数据）
_MEMORY_LIST_PATTERN = re.compile(
    r"(我的记忆有哪些|我的记忆列表|记忆列表|你有什么记忆|你都记得什么|"
    r"我记得什么|我有哪些记忆|记忆都有|你记得我什么)",
    re.IGNORECASE,
)


def is_planning_query(text: str) -> bool:
    """判断输入是否为规划意图（目标 → 步骤清单；行动导向强词）。"""
    return bool(_PLANNING_PATTERN.search(text))


def is_schedule_query(text: str) -> bool:
    """判断输入是否为日程意图（添加提醒 / 查询安排）。"""
    return bool(_SCHEDULE_PATTERN.search(text))


def is_schedule_lookup(text: str) -> bool:
    """判断日程意图是否为"查询安排"（区别于"添加提醒"）。"""
    return bool(_SCHEDULE_LOOKUP_PATTERN.search(text))


def is_memory_query(text: str) -> bool:
    """判断输入是否为记忆问答意图（回忆用户说过/喜欢的事）。

    '你记得提醒我…' 是日程添加（记得=别忘了），不是回忆记忆——先排除日程意图。
    """
    if not text:
        return False
    if is_schedule_query(text):
        return False
    return bool(_MEMORY_PATTERN.search(text))


def is_memory_list_query(text: str) -> bool:
    """判断输入是否为记忆列示意图（『我的记忆有哪些』）。"""
    return bool(_MEMORY_LIST_PATTERN.search(text))


# M6.4（WO-20260816-32）：联网搜索意图——强词保守匹配（搜一下/新闻/资讯/热点等）。
# 与 _KNOWLEDGE_PATTERN 的"搜索/查询"部分重叠（两者都进知识/资讯候选组），
# 本检测专门覆盖不含知识关键词的搜索表达（『帮我搜一下 X 新闻』）。
_WEB_SEARCH_PATTERN = re.compile(
    r"(帮我搜|搜一下|搜一搜|搜搜|上网查|网上查|联网查|"
    r"查一下.*(新闻|资讯|消息|动态|最新)|"
    r"(新闻|资讯|热点|最新消息|实时信息|新鲜事|有什么新消息|最近.*(新闻|消息))|"
    r"网上.*(有没有|是什么|怎么样))",
    re.IGNORECASE,
)


def is_web_search_query(text: str) -> bool:
    """判断输入是否为联网搜索意图（搜一下/新闻/资讯/热点…）。"""
    return bool(_WEB_SEARCH_PATTERN.search(text))


def extract_search_query(text: str) -> str:
    """从搜索类输入提取搜索关键词（用于确定性兜底搜索）。

    去掉"帮我/请/麻烦"前缀与搜索动词（搜一下/搜索/查一下…），保留关键词；
    剥不动则回退原文。
    """
    q = re.sub(
        r"^\s*(?:帮我|请|麻烦|给我)?\s*(?:搜一下|搜一搜|搜搜|搜索|上网查|网上查|查一下|查查|搜)\s*",
        "", text, count=1,
    )
    q = q.strip(" ，。！？;；、")
    return q or (text or "").strip()


# M6.4（WO-20260816-32）：知识库/笔记领域意图（Obsidian MCP 工具）。
# 名词强词（知识库/笔记库/vault…）+ 查看类动词短语（列出/打开/读取…文档/文件）。
# 保守匹配：误判宁可回退关键词路由，不硬路由。
_OBSIDIAN_PATTERN = re.compile(
    r"(知识库|笔记库|资料库|我的笔记|vault|obsidian|Obsidian)",
    re.IGNORECASE,
)
_OBSIDIAN_LOOKUP_PATTERN = re.compile(
    r"(列出|打开|读取|查看|搜索|找一下|查一下|看看|浏览|有哪些).{0,10}(笔记|文档|文件|目录|知识库)",
    re.IGNORECASE,
)
# 写入/管理意图：写动词 + 知识库/笔记/文档/文件 名词（如『把这段笔记保存到知识库』）
_OBSIDIAN_WRITE_PATTERN = re.compile(
    r"(保存到|写入|写进|存到|记到|追加|修改|更新|删掉|删除|移除|移动|重命名|复制|新建|保存).{0,8}(知识库|笔记|文档|文件|vault)",
    re.IGNORECASE,
)


def is_obsidian_query(text: str) -> bool:
    """判断输入是否为知识库/笔记查询意图（Obsidian MCP 领域）。"""
    if not text:
        return False
    return bool(_OBSIDIAN_PATTERN.search(text) or _OBSIDIAN_LOOKUP_PATTERN.search(text))


def is_obsidian_write_query(text: str) -> bool:
    """判断知识库意图是否为写入/管理（区别于只读查询）。"""
    if not text:
        return False
    return bool(_OBSIDIAN_WRITE_PATTERN.search(text))


# M5.1（WO-20260816-22）：中文口语优化——追加在系统提示词后的语言规则。
# 不动 app/persona/ 渲染层与角色卡（人设治理另管），仅在人格 Agent 组装时补充。
_ZH_LANGUAGE_SUFFIX = (
    "\n\n【语言】\n"
    "- 回复全程使用简体中文口语，禁止夹带英文单词（除非是必要的专有名词或术语，如 Python、API、SQL）；\n"
    "- 数字与时间用中文习惯表达（如『下午三点』而不是『3:00 PM』），避免翻译腔与生硬书面语。"
)


# M4.4（WO-20260816-21）：危机安全补丁——代码层强制专业求助引导句。
# 不依赖模型（尤其 3b）是否遵循提示词：LLM 回复后若不含求助线索则强制追加，
# 保证危机命中输出必有专业求助引导（安全红线，人设口吻温柔不突兀）。
_CRISIS_HELP_SUFFIX = (
    "如果你愿意，也可以找信任的家人或朋友聊聊，或拨打心理援助热线（如 12356），我一直在。"
)
# 求助线索关键词（LLM 已含任一 → 视为已引导，不重复追加）
_CRISIS_HELP_HINTS = (
    "心理援助", "援助热线", "热线", "12356", "专业帮助", "专业人士",
    "家人或朋友", "家人朋友", "找家人", "找朋友", "告诉家人",
)


def ensure_crisis_help(reply: str) -> str:
    """危机路径：确保回复含专业求助引导（代码层强制，防重复追加）。

    :param reply: LLM 原始回复
    :return: 已含求助线索则原样返回；否则在末尾追加人设口吻的求助句
    """
    if any(hint in reply for hint in _CRISIS_HELP_HINTS):
        return reply
    return f"{reply}\n{_CRISIS_HELP_SUFFIX}"


# M6.5（WO-20260816-35）：空工具结果防编造——阶段 2 空结果模式下，回复必须含
# 『没找到/没查到』语义（不含则代码层兜底替换）；兜底话术固定人设口吻，绝对零编造。
_EMPTY_RESULT_HINTS = (
    "没有找到", "没找到", "没查到", "没有相关内容", "查不到",
    "没有搜到", "没搜到", "这个还查不到", "还没有", "没有记录",
)
_EMPTY_RESULT_FALLBACK = "嗯嗯，我这边没有找到相关内容呢，换个说法我再帮你看看～"

# M6.7（WO-20260816-37，QA P1）：非空结果仍编造时（重写后依然）的固定如实话术——
# 只含真实条目，绝不把编造条目给用户。
_FABRICATION_FALLBACK = "嗯嗯，我帮你查到了：{items}，就这些哦。"

# M6.8（WO-20260816-38，QA P1）：记忆问答且检索为空（空记忆库）时的固定如实话术——
# 7B 空记忆编造不可靠（实测空库问『你记得我喜欢什么吗』编造『你喜欢喝咖啡』），
# 与空结果模式同思路：代码层短路，不经 LLM。
_MEMORY_EMPTY_FALLBACK = "我这边好像没有那次的记录呢，你可以跟我说说～"


class PersonaAgent:
    """人格 Agent：人设注入 + 会话记忆 + 意图路由 + Ollama 推理。"""

    def __init__(self, memory: Optional[SessionMemory] = None, model: Optional[str] = None,
                 base_url: Optional[str] = None, temperature: Optional[float] = None,
                 long_memory: Optional[LongTermMemory] = None) -> None:
        self._memory = memory or SessionMemory(max_turns=CONFIG.max_history_turns)
        # M3.5/M5.1：长期记忆挂 OllamaEmbedder（语义检索/融合检索可用；
        # 嵌入服务不可用时 retrieve_fused 自动降级为关键词，向后兼容）
        self._memory_long = long_memory or LongTermMemory(
            embedder=OllamaEmbedder(
                base_url=CONFIG.embedding_base_url,
                model=CONFIG.embedding_model,
                timeout=CONFIG.embedding_timeout,
            )
        )
        self._model = model or CONFIG.ollama_model
        self._base_url = base_url or CONFIG.ollama_base_url
        self._temperature = temperature if temperature is not None else CONFIG.temperature
        # M5.1：系统提示词 = 人设渲染 + 中文口语语言规则
        self._system_prompt = build_system_prompt() + _ZH_LANGUAGE_SUFFIX
        self._knowledge = KnowledgeAgent()
        self._calculator = CalculatorAgent()
        self._planner = PlanningAgent()      # M5.1：规划助手（WO-20 交付，复用其接口）
        self._scheduler = ScheduleAgent()    # M5.1：日程备忘（WO-20 交付，复用其接口）
        # M6.1（WO-20260816-29）：LLM 工具调用开关（默认开；通用测试套件关闭保持确定性）
        self._tools_enabled = CONFIG.tool_calling_enabled

    def chat(self, user_input: str, session_id: Optional[str] = None,
             max_tokens: Optional[int] = None) -> tuple:
        """一次对话：返回 (回复文本, session_id)。

        :param max_tokens: Ollama num_predict 上限（M4.2：语音链路按回复长度约束
            从源头限制生成，文本 API 不传则不限；None=沿用模型默认）
        """
        sid = session_id or uuid.uuid4().hex
        self._memory.append(sid, "user", user_input)
        messages = [{"role": "system", "content": self._system_prompt}]
        # M3/M3.5/M5.1 长期记忆注入：检索与该输入相关的过往记忆（新会话也能"记得用户"）。
        # M5.1：由关键词检索升级为融合检索（语义 + 关键词，Ollama all-minilm；
        # 无 embedder/服务不可用时自动退化为关键词，行为不变）
        # M6.9（WO-20260816-40）：保留融合检索原始结果——记忆问答（『你记得我…』）短路
        # 判定基于"相关检索"而非 recent 兜底（无关 topic 兜底注入会让 7B 编造
        # 『你喜欢猫』，QA r6 实测；M6.8 短路曾被 recent 兜底绕过）。
        fused_memories = self._memory_long.retrieve_fused(user_input)
        memories = fused_memories or self._memory_long.recent(limit=2)
        if memories:
            lines = "\n".join(f"- [{m['kind']}] {m['content']}" for m in memories)
            messages.append({
                "role": "system",
                "content": "以下是用户过往对话中的长期记忆（供你自然地体现『记得用户』）：\n" + lines
                           + "\n当话题相关时，可以直接自然地引用记忆，比如『你之前不是说过喜欢猫嘛』『我记得你叫小明』；"
                             "不要用『如果你喜欢…』这种条件式替代。"
                             "如果这些记忆与当前话题无关，或你其实并没有相关的记忆，"
                             "就如实告诉用户「我这边好像没有那次的记录呢」，再请 TA 再说说看；"
                             "绝不虚构用户说过的话、做过的计划或发生过的事。",
            })
        else:
            # M6 v2（WO-20260816-13，T28）：空记忆时也注入防编造指引（原指引只在 if 块内、
            # 空记忆不注入导致模型仅靠 system rules 压不住编造倾向）
            messages.append({
                "role": "system",
                "content": "目前还没有这个用户的历史记忆记录。如果用户问起你们之前聊过的事，"
                           "就如实告诉 TA『我这边好像没有那次的记录呢』，再请 TA 再说说看；"
                           "绝不虚构用户说过的话、做过的计划或发生过的事。",
            })
        # M6 v3（WO-20260816-15，T23/P1-2，总控批准）：心理危机意图分支——安全优先，
        # 命中关键词即强制注入危机引导句式（不依赖模型遵循 few-shot）。
        if is_crisis_query(user_input):
            messages.append({
                "role": "system",
                "content": "用户可能正处在非常痛苦的时刻。请温柔地陪伴 TA（如「我在呢」「你很重要」），"
                           "认真倾听、不评判；并温和但明确地建议 TA：找信任的家人或朋友聊聊，"
                           "或者拨打心理援助热线（如 12356 或当地心理援助热线），都会有人认真听 TA 说。"
                           "用平时的温柔口吻，不敷衍、不慌张、不说教。",
            })
        # M6.8（WO-20260816-38，QA P1）：记忆问答且检索为空（retrieve_fused 与 recent 均空，
        # 空记忆库）→ 代码层短路直接返回固定如实话术，不经 LLM——7B 空记忆编造不可靠
        # （QA 实测：空库问『你记得我喜欢什么吗』编造『你喜欢喝咖啡，还喜欢看科幻电影』，
        # 用户从未说过；与空结果模式同思路：代码层保证零编造）。有记忆时正常走（自然引用）。
        # M6.9（WO-20260816-40）：短路判定用"相关检索 fused_memories"而非 recent 兜底——
        # 无关 topic 兜底注入（如脚本环境前面落库的『明天下午3点提醒我喝水』）会让 7B
        # 仍编造『你喜欢猫』；无相关记忆即如实『没有那次的记录』。
        if (is_memory_query(user_input) and not is_memory_list_query(user_input)
                and not fused_memories and not is_crisis_query(user_input)):
            for kind, content in extract_memories(user_input):
                self._memory_long.add(kind, content, source_session=sid)
            self._memory.append(sid, "assistant", _MEMORY_EMPTY_FALLBACK)
            return _MEMORY_EMPTY_FALLBACK, sid
        # M6.1（WO-20260816-29）：工具调用路径（非危机分支）——让 LLM 自主决定是否调用工具。
        # 返回语义：tool_reply 非 None 且（用了工具 或 无需关键词路由）→ 直接采用；
        # 其余情况（工具路径失败 / 未用工具但意图命中需确定性操作）→ 落到下方关键词路由链。
        # M6.1（WO-20260816-29）：工具调用路径（非危机、开启、且命中可服务意图时尝试）。
        # 两阶段：LLM 工具决策 → 人设包装回复；未用工具/失败 → 落到下方关键词路由链。
        # M6.2：注入最近会话历史（多轮指代）；工具已执行后阶段 2 失败 → 安全兜底文案，
        # 绝不回退关键词路由（避免重复执行工具）。
        # M6.9（WO-20260816-40 确定性优先）：强关键词意图（日程/记忆/计算）不进 LLM 工具
        # 决策——选型确定，直接走 _route_by_keywords 确定性执行（基线『提醒我喝水』11.1s → ≤6s）；
        # 模糊意图（知识/搜索/知识库）保留两阶段 LLM 决策（选工具/精确参数）。
        if (not is_crisis_query(user_input) and self._tools_enabled
                and self._needs_llm_tool_decision(user_input)):
            history = self._memory.load(sid)[:-1][-6:]  # 最近 6 轮（不含当前输入）
            tool_reply, tool_used, tool_failed = self._try_tool_calling(
                user_input, messages, history=history, max_tokens=max_tokens)
            if tool_used:
                reply = tool_reply if tool_reply is not None else self._TOOL_DONE_FALLBACK
                # M6.7（WO-20260816-37，QA P2）：工具回复也做模板句消除
                reply = self._strip_template_phrases(reply) or reply
                for kind, content in extract_memories(user_input):
                    self._memory_long.add(kind, content, source_session=sid)
                self._memory.append(sid, "assistant", reply)
                return reply, sid
        # WO-20260816-34（QA C03 P1 结构性修复）：工具路径进入但 LLM 未用工具/未执行时，
        # 显式执行关键词路由链——原 if/elif 结构下（if 条件为真 → elif 整体跳过）确定性兜底
        # 是死代码：『明天下午3点提醒我喝水』在 LLM 未选工具时 add_schedule 不执行、
        # 日程不落库、模型假完成承诺『我会在明天下午三点提醒你』（突破防假完成红线）。
        # 非危机 / 未开工具 / 无意图时同样进入（保持原 else 分支行为）。
        self._route_by_keywords(messages, user_input)
        messages.extend(self._memory.load(sid))
        # M3 长期记忆提取（P3-4）：先提取、再落库（finally），即使 Ollama 抛异常，
        # 本次用户事实/话题也不丢失。
        extracted = extract_memories(user_input)
        try:
            reply = self._call_ollama(messages, max_tokens)
        finally:
            for kind, content in extracted:
                self._memory_long.add(kind, content, source_session=sid)
        # M4.4（WO-20260816-21）：危机路径代码层强制专业求助引导——
        # 不依赖 3b 是否遵循提示词；LLM 已含求助线索则跳过（防重复）。
        if is_crisis_query(user_input):
            reply = ensure_crisis_help(reply)
        else:
            # M6.7（WO-20260816-37，QA P2）：普通对话回复做模板句消除
            # （『今天过得怎么样？我在呢』类组合模板，7B 未完全遵循提示词时代码层兜底）
            reply = self._strip_template_phrases(reply) or reply
        self._memory.append(sid, "assistant", reply)
        return reply, sid

    def _route_by_keywords(self, messages: List[dict], user_input: str) -> None:
        """关键词路由链（M2/M3/M5.1/M6.4）：按意图注入确定性上下文/执行确定性操作。

        仅注入（或执行落库等副作用），不生成回复——回复由 chat() 统一调用 _call_ollama。

        WO-20260816-34（QA C03 P1 结构性修复）：自 chat() 的 elif 链抽出。原 if/elif
        结构下，工具路径进入（意图命中）但 LLM 未用工具/未执行时，if 条件为真 → 整个
        elif 链被跳过，确定性兜底（日程落库/联网搜索/知识库目录）成为死代码，模型只能
        自由发挥（如『我会在明天下午三点提醒你』假完成承诺）。抽出后由 chat() 显式调用，
        保证兜底真实生效。

        分支互斥（if/elif）：命中第一个意图分支即注入，与既有路由顺序一致：
        知识库/笔记 → 知识 → 联网搜索 → 计算 → 记忆 → 规划 → 日程 → 普通对话。
        """
        # M6.4 意图路由：知识库/笔记（Obsidian MCP 领域）——确定性兜底：
        # 列知识库根目录注入真实数据（保底真实，不编造）。
        if is_obsidian_query(user_input):
            if tool_registry.has("obsidian_vault_list"):
                try:
                    listing = tool_registry.call("obsidian_vault_list", {"path": "/"})
                except Exception as exc:
                    listing = f"（知识库读取失败：{exc}）"
            else:
                listing = "（知识库工具未连接）"
            messages.append({
                "role": "system",
                "content": "用户在问知识库/笔记相关内容。请基于以下知识库根目录的真实内容回答，"
                           "用温柔治愈的语气（符合你的人设），要点式简短；"
                           "只讲真实存在的目录/文件，不要编造；知识库不可用就如实说明：\n"
                           "[知识库根目录]\n" + listing,
            })
        # M2 意图路由：知识查询 → 能力 Agent 取结果注入（人设包装仍由本 Agent）
        elif is_knowledge_query(user_input):
            result = self._knowledge.query(user_input)
            context = f"[知识查询结果，来源：{result['source'] or '无'}]\n{result['answer']}"
            if result.get("origin") == "none" or not result.get("source"):
                # M6.6（WO-20260816-36）：三级兜底——内置库+Wikipedia 无结果时降级 Bing
                # 联网搜索注入真实结果（用户『deepseek harness是什么』曾只得到『查不到』）
                try:
                    from app.tools.web_search import search_text
                    web = search_text(user_input)
                except Exception:
                    web = ""
                # search_text 无结果时返回『（联网搜索没有查到结果）』，需排除（视为空）
                if web and web.strip() and not self._is_empty_tool_result(web):
                    messages.append({
                        "role": "system",
                        "content": "用户问了知识类问题，内置知识库与百科没有查到，以下为联网搜索到的"
                                   "真实结果。请如实转述，要点式简短并附上结果来源链接；"
                                   "只依据搜索结果讲，不编造：\n[联网搜索结果]\n" + web,
                    })
                else:
                    # M6 v3（WO-20260816-15，T10/P1-1）：无结果时禁止来源句式（R8 不编造来源），
                    # 强制"没查到"模板；可给常识建议但不得假装查过/标注来源
                    messages.append({
                        "role": "system",
                        "content": "用户问了知识类问题，但本次没有查询到相关资料。请如实告诉用户"
                                   "『我这边暂时没查到呢，换个问法我再试试』，保持温柔治愈的语气；"
                                   "如果用户还带有情绪，先安抚再说话。"
                                   "你可以基于常识温柔地给一些通用建议，但不要假装查过资料，"
                                   "也不要标注任何来源（如「（来源：内置知识库）」）：\n" + context,
                    })
            else:
                messages.append({
                    "role": "system",
                    "content": "用户问了知识类问题。请基于以下知识查询结果回答，用温柔治愈的语气（符合你的人设）："
                               "① 要点式简洁回答，两三句讲完（150 字以内），不展开长篇；"
                               "② 在回答末尾明确附上引用来源（如「（来源：内置知识库）」「（来自维基百科）」，"
                               "按查询结果如实写）；"
                               "③ 专业术语拼写要准确，不编造：\n" + context,
                })
        # M6.4 意图路由：联网搜索——确定性兜底：直接执行 web_search 注入真实结果
        # （保底真实资讯，不编造）。
        elif is_web_search_query(user_input):
            query = extract_search_query(user_input)
            try:
                from app.tools.web_search import search_text
                result = search_text(query)
            except Exception as exc:
                result = f"（联网搜索失败：{exc}）"
            if not (result or "").strip():
                result = "（没有搜到相关结果）"
            messages.append({
                "role": "system",
                "content": "用户要求联网搜索。请基于以下真实搜索结果回答，用温柔治愈的语气（符合你的人设），"
                           "要点式简洁并附上结果来源链接；只依据搜索结果如实讲，"
                           "不要编造搜索里没有的内容；没搜到就如实说明：\n[搜索结果]\n" + result,
            })
        # M3 意图路由：计算 → 能力 Agent（CalculatorAgent）取结果注入（人设包装仍由本 Agent）
        elif is_calculator_query(user_input):
            calc = self._calculator.calculate(user_input)
            if calc["error"]:
                context = f"[计算结果：失败]\n{calc['error']}"
                messages.append({
                    "role": "system",
                    "content": "用户问了计算问题，但算式没有识别清楚。请用温柔治愈的语气（符合你的人设）"
                               "告诉用户没算出来，并提示提供更清晰的算式（如“3+5”或“300 的 20%”），"
                               "不要编造结果：\n" + context,
                })
            else:
                context = f"[计算结果]\n{calc['expression']} = {calc['result']}"
                messages.append({
                    "role": "system",
                    "content": "用户问了计算问题。请基于以下计算结果回答，用温柔治愈的语气（符合你的人设），"
                               "把算式和结果自然地说出来：\n" + context,
                })
        # M5.1 意图路由：记忆问答 → 记忆融合检索已注入上方；此处补充回忆引导 / 记忆列示
        elif is_memory_query(user_input):
            if is_memory_list_query(user_input):
                items = self._memory_long.recent(limit=20)
                if items:
                    lines = "\n".join(
                        f"- [{m['kind']}] {m['content'][:40]}" for m in items
                    )
                    messages.append({
                        "role": "system",
                        "content": "用户想看看你记住了 TA 的哪些事。请用温柔治愈的语气把记忆要点自然地讲给 TA"
                                   "（每条一两句话即可，口语化，不要照抄内部记录格式，不要编造没有的记忆）；"
                                   "如果记忆很少，就如实说只记得这些。你记住的内容如下：\n[记忆列表]\n" + lines,
                    })
                else:
                    messages.append({
                        "role": "system",
                        "content": "用户想看看你记住了什么，但你目前还没有 TA 的任何记忆。请温柔地告诉 TA"
                                   "你还在慢慢了解 TA，请 TA 多跟你聊聊；绝不编造记忆。",
                    })
            else:
                messages.append({
                    "role": "system",
                    "content": "用户在询问关于 TA 自己的记忆或过往对话（比如『你记得我喜欢什么吗』"
                               "『我上次说的计划』）。请优先基于上面注入的长期记忆回答，自然地引用相关记忆"
                               "（如『我记得你之前说过喜欢猫』）；如果确实没有相关记忆，就如实说"
                               "『我这边好像没有那次的记录呢』，再请 TA 说说看；绝不编造用户说过的话。",
                })
        # M5.1 意图路由：规划 → 能力 Agent（PlanningAgent）取步骤清单注入（人设包装仍由本 Agent）
        elif is_planning_query(user_input):
            plan = self._planner.plan(user_input)
            if plan["error"]:
                context = f"[规划结果：失败]\n{plan['error']}"
                messages.append({
                    "role": "system",
                    "content": "用户提出了一个目标希望做规划，但这次没能生成步骤清单。请用温柔治愈的语气"
                               "告诉 TA 这次没规划出来，请 TA 把目标说得再清楚一点（比如『帮我规划周末学做饭』），"
                               "不要编造步骤：\n" + context,
                })
            else:
                steps = "\n".join(
                    f"{s['no']}. {s['title']}（优先级：{s['priority']}）"
                    + (f"——{s['detail']}" if s.get("detail") else "")
                    for s in plan["steps"]
                )
                context = f"[规划结果]\n目标：{plan['goal']}\n步骤：\n{steps}"
                messages.append({
                    "role": "system",
                    "content": "用户请帮忙做规划。请基于以下规划结果，用温柔治愈的语气（符合你的人设）"
                               "把步骤清单自然地讲给 TA：按顺序列出步骤（口语化一点，不必照抄格式），"
                               "并在最后温柔地问 TA 想从哪一步开始；不要额外编造步骤：\n" + context,
                })
        # M5.1 意图路由：日程 → 能力 Agent（ScheduleAgent）添加/查询，注入结构化结果
        elif is_schedule_query(user_input):
            if is_schedule_lookup(user_input):
                today_entries = self._scheduler.today()
                if today_entries["count"]:
                    lines = "\n".join(
                        f"- {e['time']} {e['event']}" for e in today_entries["entries"]
                    )
                    messages.append({
                        "role": "system",
                        "content": "用户在问今天的安排。请用温柔治愈的语气把今日日程列给 TA"
                                   "（时间 + 事项，口语化）：\n[今日日程]\n" + lines,
                    })
                else:
                    messages.append({
                        "role": "system",
                        "content": "用户在问今天的安排，但今天还没有日程。请温柔地告诉 TA"
                                   "『今天还没有安排哦』，可以问问 TA 想做什么。",
                    })
            else:
                sched = self._scheduler.add(user_input)
                if sched["error"]:
                    messages.append({
                        "role": "system",
                        "content": "用户想添加一条日程提醒，但没有解析成功。请用温柔治愈的语气告诉 TA 没记上，"
                                   "并提示说得更具体（比如『明天下午 3 点提醒我喝水』）；不要假装已经记住了：\n"
                                   + f"[日程添加：失败]\n{sched['error']}",
                    })
                else:
                    messages.append({
                        "role": "system",
                        "content": "用户想添加一条日程提醒，已经成功记下了。请用温柔治愈的语气向 TA 确认，"
                                   "回显日期、时间、事项（如『好呀，明天下午 3 点提醒你喝水，我记下啦～』）：\n"
                                   + f"[日程已添加]\n日期：{sched['date']} 时间：{sched['time']} 事项：{sched['event']}",
                    })
        # M6 v3（WO-20260816-15，T03/T08）：普通对话路径（非危机/知识/计算/记忆/规划/日程）
        # 注入长度约束提示。M6.1：危机分支（工具路径 if 绑定后 else 也会走到）不注入默认提示。
        else:
            if not is_crisis_query(user_input):
                messages.append({
                    "role": "system",
                    "content": "回复尽量简短：日常聊天一两句话就好（60 字内），情绪安抚也尽量控制在 80 字内；"
                               "说完就停下来，不要继续展开。",
                })
                # M6 v2（WO-20260816-13，T16/R3）：能力边界强提示（普通对话路径常驻注入）。
                # M5.1：日程提醒已能做，从"做不到"清单移除（避免与日程路由自相矛盾）
                messages.append({
                    "role": "system",
                    "content": "记住你的能力边界：你现在能在对话里帮忙——查资料、算一算、做规划、记日程、"
                               "陪你聊天、给建议。如果用户要求你操作 TA 的电脑、读写 TA 的文件、"
                               "控制系统或设备，或做现实世界里的事，就温柔地说『这个我还做不到哦』，"
                               "说明你只能在对话里帮忙，再转向你能做的小事；"
                               "绝不答应『我帮你操作/直接搞定』，也绝不假装已经做完了没做过的事。",
                })

    def _call_ollama(self, messages: List[dict], max_tokens: Optional[int] = None) -> str:
        """调用 Ollama /api/chat（非流式）。

        M4.1：带 keep_alive 长驻参数（默认 60m），让模型常驻显存/内存，
        消除连续对话间的模型冷启动（实测 17s → 数次秒内）。
        M4.2：可选 num_predict（max_tokens）从源头限制生成长度，
        避免"先生成几百字再截断"的浪费。
        """
        url = f"{self._base_url.rstrip('/')}/api/chat"
        options: dict = {"temperature": self._temperature}
        if max_tokens is not None and max_tokens > 0:
            options["num_predict"] = max_tokens
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "keep_alive": CONFIG.ollama_keep_alive,
            "options": options,
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama 调用失败（请确认 Ollama 已启动、模型 {self._model} 已拉取）: {exc}") from exc
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()

    # ---------- M6.1（WO-20260816-29）：LLM 工具调用（function calling） ----------

    def _call_ollama_with_tools(self, messages: List[dict], tools: list,
                                max_tokens: Optional[int] = None) -> dict:
        """调用 Ollama /api/chat 并携带 tools 参数，返回完整 message（含 content/tool_calls）。

        :return: {"content": str, "tool_calls": list|None}；失败抛 RuntimeError（由上层回退）
        """
        url = f"{self._base_url.rstrip('/')}/api/chat"
        options: dict = {"temperature": self._temperature}
        if max_tokens is not None and max_tokens > 0:
            options["num_predict"] = max_tokens
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "keep_alive": CONFIG.ollama_keep_alive,
            "tools": tools,
            "options": options,
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama 工具调用失败: {exc}") from exc
        msg = resp.json().get("message", {})
        return {
            "content": (msg.get("content") or "").strip(),
            "tool_calls": msg.get("tool_calls"),
        }

    def _execute_tool(self, name: str, arguments: dict) -> str:
        """执行工具（对既有能力 Agent / 记忆接口的薄封装），返回结果字符串或错误说明。

        只调用既有接口，不重复实现业务；任何失败返回错误说明（不抛异常，交由 LLM 处理）。
        """
        try:
            if name == "get_schedule":
                date = (arguments.get("date") or "today").lower()
                entries = self._scheduler.today() if date == "today" else self._scheduler.tomorrow()
                if entries.get("count"):
                    return "\n".join(f"- {e['time']} {e['event']}" for e in entries["entries"])
                return "（今天没有日程安排）" if date == "today" else "（明天没有日程安排）"
            if name == "add_schedule":
                text = (arguments.get("text") or "").strip()
                if not text:
                    return "错误：缺少提醒内容描述"
                sched = self._scheduler.add(text)
                if sched.get("error"):
                    return f"错误：{sched['error']}"
                return f"已记录：日期 {sched.get('date')} 时间 {sched.get('time')} 事项 {sched.get('event')}"
            if name == "mark_schedule_done":
                text = (arguments.get("text") or "").strip()
                if not text:
                    return "错误：缺少目标描述"
                sched = self._scheduler.mark_done(text)
                if sched.get("error"):
                    return f"错误：{sched['error']}"
                lines = "\n".join(f"- {e['time']} {e['event']}" for e in sched.get("entries", []))
                return f"已标记完成 {sched.get('updated', 0)} 条：\n{lines}" if lines else "已标记完成"
            if name == "delete_schedule":
                text = (arguments.get("text") or "").strip()
                if not text:
                    return "错误：缺少目标描述"
                sched = self._scheduler.delete(text)
                if sched.get("error"):
                    return f"错误：{sched['error']}"
                lines = "\n".join(f"- {e['time']} {e['event']}" for e in sched.get("entries", []))
                return f"已删除 {sched.get('deleted', 0)} 条：\n{lines}" if lines else "已删除"
            if name == "query_memory":
                question = (arguments.get("question") or "").strip()
                items = self._memory_long.retrieve_fused(question, limit=3)
                if not items:
                    return "（记忆里没有相关内容）"
                return "\n".join(f"- [{m['kind']}] {m['content']}" for m in items)
            if name == "query_knowledge":
                question = (arguments.get("question") or "").strip()
                result = self._knowledge.query(question)
                if result.get("origin") == "none" or not result.get("source"):
                    # M6.6（WO-20260816-36）：知识三级兜底——内置库+Wikipedia 均无结果时，
                    # 自动降级 Bing 联网搜索，把真实搜索结果交阶段 2 转述
                    # （用户实测『deepseek harness是什么』曾只得到『查不到』，拿不到答案）。
                    try:
                        from app.tools.web_search import search_text
                        web = search_text(question)
                    except Exception:
                        web = ""
                    # search_text 无结果时返回『（联网搜索没有查到结果）』，需排除（视为空）
                    if web and web.strip() and not self._is_empty_tool_result(web):
                        return f"（内置知识库未查到，以下为联网搜索结果）\n{web}"
                    return "（未查询到相关资料）"
                return f"{result['answer']}\n（来源：{result.get('source')}）"
            if name == "calculate":
                expr = (arguments.get("expression") or "").strip()
                calc = self._calculator.calculate(expr)
                if calc.get("error"):
                    return f"错误：{calc['error']}"
                return f"{calc.get('expression')} = {calc.get('result')}"
            if name == "list_plans":
                plans = (self._planner.list_plans() or {}).get("plans") or []
                if not plans:
                    return "（还没有保存过规划）"
                return "\n".join(f"- {p['goal']}（{p.get('step_count', '?')} 步）" for p in plans)
            if name == "save_plan":
                goal = (arguments.get("goal") or "").strip()
                steps = arguments.get("steps") or []
                result = self._planner.save({"goal": goal, "steps": steps})
                if result.get("error"):
                    return f"错误：{result['error']}"
                return f"已保存计划（id={result.get('id')}）：{goal}（{len(steps)} 步）"
            if name == "web_search":
                query = (arguments.get("query") or "").strip()
                if not query:
                    return "错误：缺少搜索关键词"
                from app.tools.web_search import search_text
                return search_text(query)
            # 插件/MCP 工具：未命中的内置名交由注册表分发（可插拔工具来源）
            if tool_registry.has(name):
                return tool_registry.call(name, arguments)
            return f"错误：未知工具 {name}"
        except Exception as exc:  # 任何工具执行异常都如实返回，不编造结果
            return f"错误：工具执行失败 {exc}"

    # M6.1（WO-20260816-29）：阶段 1 工具决策指引（无人设、仅规则）——实测 qwen2.5:7b
    # 在带人设系统提示词（含 few-shot 对话示例）时不主动调用工具，去掉人设后正常触发。
    # 因此工具决策与人设回复分两阶段：决策用本指引，回复用人设系统提示词。
    # M6.4（WO-20260816-32）：通用规则保留在此（防假完成红线）；具体"工具→触发词"
    # 规则按候选组裁剪（_build_tool_guidance，只讲本轮可用的工具，帮助 7B 聚焦）。
    _TOOL_USE_GUIDANCE = (
        "你可以调用工具来更好地帮助用户。规则：\n"
        "- 只有用户请求确实对应某个工具时才调用；闲聊、情绪陪伴等不需要工具时直接温柔回复即可。\n"
        "- 重要：绝对不要在没有调用工具并确认工具返回成功的情况下，声称『已经记下了/已删除/已标记完成/已保存/已查到』；"
        "工具未执行或返回错误时，如实告诉用户没能办成（如『这个我还没帮你弄好呢』）。"
    )

    # M6.2（WO-20260816-31）：工具已执行但最终人设回复失败时的安全兜底文案。
    # 不能回退关键词路由（会重复执行工具，如二次添加日程），改用中性确认语。
    _TOOL_DONE_FALLBACK = "嗯嗯，已经帮你处理好啦～有需要再找我哦。"

    def _build_tool_guidance(self, candidate_names: List[str]) -> str:
        """按候选工具裁剪的阶段 1 指引：通用规则 + 仅本轮可用工具的触发规则。

        26 工具时 7B 面对整表规则+整表 schema 选型失效；候选组 ≤8 后，
        指引也只讲这 ≤8 个工具，显著降低 7B 的遵循负担。
        """
        lines = ["你可以调用下面这些工具来更好地帮助用户。规则："]
        for n in candidate_names:
            hint = TOOL_RULE_HINTS.get(n)
            if hint:
                lines.append("- " + hint)
        obsidian_in_cand = [n for n in candidate_names if n.startswith("obsidian_")]
        if obsidian_in_cand:
            lines.append(
                "- obsidian_* 工具读写你的 Obsidian 知识库（真实笔记数据）："
                "用户要看知识库目录/文件用 obsidian_vault_list / obsidian_vault_read，"
                "要在知识库里搜索用 obsidian_search_simple，要保存/修改笔记用 obsidian_vault_write / obsidian_vault_patch 等；"
                "不要凭空编造知识库内容，一律用工具拿真实数据。"
            )
            # WO-20260816-35：路径参数精确提示（LLM 曾把 path 传成 '30' 而非 '30 · 项目' 导致空结果）
            lines.append(
                "- obsidian 路径参数要用完整目录名（如 '30 · 项目'，含中文空格与序号前缀，"
                "不要缩写为 '30'）；'/' 表示知识库根目录。"
            )
        lines.append("- 只有用户请求确实对应某个工具时才调用；闲聊、情绪陪伴等不需要工具时直接温柔回复即可。")
        lines.append("- 重要：绝对不要在没有调用工具并确认工具返回成功的情况下，"
                     "声称『已经记下了/已删除/已标记完成/已保存/已查到』；"
                     "工具未执行或返回错误时，如实告诉用户没能办成（如『这个我还没帮你弄好呢』）。")
        return "\n".join(lines)

    @staticmethod
    def _candidate_tool_schemas(candidate_names: List[str]) -> list:
        """按候选工具名裁剪 schema：内置集 + 注册表（含插件/MCP）按名取，缺失跳过。

        26 个工具仍全部在注册表（可插拔不丢），只是本轮只把候选组 schema 交给 LLM。
        WO-20260816-35：外部（Obsidian）工具 schema 深拷贝增强——给 path/query 参数
        描述补充『完整目录名』提示（服务器原始描述缺失，LLM 曾传短名 '30' 导致空结果）。
        """
        by_name = {s["function"]["name"]: s for s in get_tool_specs()}
        schemas = []
        for n in candidate_names:
            if n in by_name:
                schemas.append(by_name[n])
            else:
                ext = tool_registry.schema(n)
                if ext:
                    schemas.append(PersonaAgent._enhance_ext_schema(n, ext))
        return schemas

    @staticmethod
    def _enhance_ext_schema(name: str, schema: dict) -> dict:
        """深拷贝外部工具 schema 并给 path/query 参数追加精确提示（不污染注册表原对象）。"""
        import copy

        s = copy.deepcopy(schema)
        fn = s.get("function", {})
        props = (fn.get("parameters") or {}).get("properties") or {}
        hints = PersonaAgent._OBSIDIAN_ARG_HINTS
        for pname, prop in props.items():
            if not isinstance(prop, dict):
                continue
            if pname == "path" and "path" in hints:
                prop["description"] = (prop.get("description") or "") + hints["path"]
            elif pname in ("query", "q", "query_string", "queryText") and "query" in hints:
                prop["description"] = (prop.get("description") or "") + hints["query"]
        return s

    def _try_tool_calling(self, user_input: str, messages: List[dict],
                          history: Optional[List[dict]] = None,
                          max_tokens: Optional[int] = None):
        """两阶段 LLM 工具调用（≤3 轮工具决策，随后人设包装回复）。

        M6.4（WO-20260816-32）：阶段 1 只带候选工具组 schema（意图预筛，每组 ≤8，
        含插件/MCP 工具）；候选为空 → 回退关键词路由（保底确定性）。

        阶段 1（工具决策）：按候选组的规则指引 + 最近会话历史 + 用户输入
        （不带人设系统提示词，实测 7B 在无人设下才会调用工具）；执行工具并回填。
        阶段 2（人设回复）：完整人设系统提示词 + 记忆 + 用户输入 + 工具结果 →
        人设化最终回复（不传 tools，避免压制）。

        返回 (reply, used_tool, failed)：
        - used_tool=True：工具被执行；reply 为人设化最终回复（阶段 2 失败时为 None，
          调用方必须用 _TOOL_DONE_FALLBACK，不得回退重执行）；
        - used_tool=False：阶段 1 未产生工具调用（或未执行任何工具即失败），
          调用方回退关键词路由（无副作用，安全）。
        """
        try:
            candidate_names = select_candidate_tool_names(user_input)
            if not candidate_names:
                candidate_names = list(TOOL_GROUPS["default"])
            tools = self._candidate_tool_schemas(candidate_names)
            if not tools:
                # 候选组无可用工具（如 Obsidian 未连接）→ 回退关键词路由（无副作用）
                return None, False, False
            stage1 = [
                {"role": "system", "content": self._build_tool_guidance(candidate_names)},
            ]
            # M6.3/M6.4：外部 MCP/插件工具提示（仅候选内存在外部工具时注入）
            cand_ext = [n for n in candidate_names if tool_registry.has(n)]
            if any(n.startswith("obsidian_") for n in cand_ext):
                stage1.append({
                    "role": "system",
                    "content": ("另有来自外部服务器的工具（前缀 obsidian_）："
                                "当用户提到知识库/笔记/Obsidian 文档，或要求列出/搜索/保存笔记时，"
                                "优先调用这些工具获取真实数据，不要凭空编造。"),
                })
            if history:
                # M6.2：注入最近会话历史（不含当前输入），支持多轮指代（如『那明天呢』）
                stage1.extend(history)
            stage1.append({"role": "user", "content": user_input})
            used_any = False
            for _ in range(3):
                # M6.9（WO-20260816-39）：决策轮只输出 tool_calls/简短判断，num_predict 收紧
                # ≤40 显著降低决策生成耗时（基线『搜新闻』29.3s → ≤15s 目标）
                resp = self._call_ollama_with_tools(stage1, tools, max_tokens=40)
                tool_calls = resp.get("tool_calls")
                if not tool_calls:
                    if not used_any:
                        return None, False, False  # 未用工具 → 回退关键词路由
                    break  # 工具已用过，本轮无更多调用 → 进入阶段 2
                used_any = True
                stage1.append({
                    "role": "assistant",
                    "content": resp.get("content") or "",
                    "tool_calls": tool_calls,
                })
                for call in tool_calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    try:
                        arguments = fn.get("arguments") or {}
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments or "{}")
                    except Exception:
                        arguments = {}
                    result = self._execute_tool(name, arguments)
                    stage1.append({"role": "tool", "name": name, "content": result})
            if not used_any:
                return None, False, False
            # 阶段 2：人设包装（完整系统提示词 + 记忆 + 工具结果指令 + 用户输入）
            # WO-20260816-33（QA P1②）：工具结果必须以人类可读标签呈现并如实回显——
            # 原『用户请求已通过内部能力处理，处理结果为…』指令 + user→system 顺序下，
            # 7B 面对 JSON 结果仍回复『这个我还做不到哦/我这边好像没有那次的记录呢』，
            # 用户看不到 vault 真实内容。改为：结果指令在前（声明结果已真实拿到、
            # 逐条念出目录/文件名、禁止『做不到/没查到/没有记录』式回避），用户输入在后。
            # WO-20260816-35：工具结果为空时切换『空结果模式』——如实『没查到』零编造
            # （实测：参数传错返回 {"files": []} 时，阶段 2 曾编造 11 条不存在的项目，
            # 违反 R8 不编造红线）。
            tool_results = self._format_tool_results(stage1)
            tool_msgs = [m for m in stage1 if m["role"] == "tool"]
            empty_results = bool(tool_msgs) and all(
                self._is_empty_tool_result(m["content"]) for m in tool_msgs
            )
            # WO-20260816-37（QA P1）：非空结果防填充——解析工具真实条目数 N，
            # 阶段 2 提示词明确『只有 N 条』；回复生成后做条目比对，编造则重写/固定话术
            true_items: list = []
            if not empty_results:
                for m in tool_msgs:
                    true_items.extend(self._extract_true_items(m["content"]))
                true_items = [it for it in true_items if it and it.strip()]
            item_count_hint = (f"工具结果只有 {len(true_items)} 条，逐条念出即可，"
                               f"绝对禁止补充任何额外条目/文档/内容。\n") if true_items else ""
            if empty_results:
                msgs2 = list(messages) + [
                    {
                        "role": "system",
                        "content": "用户刚才的请求已经执行，但【执行结果】为空——没有查到相关内容。\n"
                                   "回复规则：\n"
                                   "① 必须如实告诉用户『没有找到相关内容』或『这个还查不到哦』，"
                                   "可以温柔地请 TA 换个说法再试；\n"
                                   "② 绝对禁止列出任何具体的项目、文件名、条目、标题或内容，"
                                   "禁止编造填充，禁止假装已查到；\n"
                                   "③ 用温柔治愈的口吻，简短口语，不要提『工具』『函数』『系统』『内部』等词。\n"
                                   "【执行结果】\n" + tool_results,
                    },
                    {"role": "user", "content": user_input},
                ]
            else:
                msgs2 = list(messages) + [
                    {
                        "role": "system",
                        "content": "用户刚才的请求已经通过内部能力成功执行，真实结果见下方【执行结果】。\n"
                                   "请直接把结果内容讲给用户，规则：\n"
                                   "① 结果里有目录/文件名/列表/条目时，逐条如实念出来（如『30 · 项目 里有 AI虚拟人物 文件夹』）；\n"
                                   "② 结果就是真实答案，绝对不要说自己做不到、不要说『我这边没有记录/查不到』、"
                                   "不要回避、不要编造结果之外的内容；\n"
                                   + item_count_hint +
                                   "③ 用温柔治愈的口吻，简短口语，不要提『工具』『函数』『系统』『内部』等词；\n"
                                   "④ 用自然的话转述（如『我帮你查到了，XX 是……』），不要念清单、"
                                   "不要用『今天过得怎么样？我在呢』这类模板开头，句式有变化。\n"
                                   "【执行结果】\n" + tool_results,
                    },
                    {"role": "user", "content": user_input},
                ]
            try:
                # M6.9（WO-20260816-39）：阶段 2 人设回复默认 num_predict 上限 150
                # （文本链路不传 max_tokens 时，防止 7B 长回复拖慢全链路；
                # 零编造由代码层兜底保证，不依赖生成长度）
                reply = self._call_ollama(msgs2, max_tokens if max_tokens else 150)
            except Exception:
                # M6.2：工具已执行，阶段 2 回复失败——返回 (None, True, True)，
                # 调用方用安全兜底文案，绝不回退关键词路由（避免重复执行）。
                return None, True, True
            if empty_results and not any(kw in reply for kw in _EMPTY_RESULT_HINTS):
                # WO-20260816-35 代码层兜底：空结果时 LLM 未如实『没找到』
                # （编造填充/回避）→ 固定话术兜住，绝对零编造
                reply = _EMPTY_RESULT_FALLBACK
            elif true_items and self._stage2_has_fabrication(reply, true_items):
                # WO-20260816-37 代码层兜底：非空结果但回复含结果外条目
                # （QA 实测：真实仅 1 条『AI虚拟人物/』，回复编造 5 条）——
                # ① 强制重写一次（只依据真实条目）；② 仍编造 → 固定如实话术截断
                rewrite_msg = (
                    "你上一条回复里列出了工具结果中没有的条目。工具真实结果只有以下 "
                    f"{len(true_items)} 条，请严格只依据这些重写回复（逐条念出即可，"
                    "删除所有额外条目），保持温柔治愈口吻、简短口语：\n"
                    + "；".join(true_items)
                )
                try:
                    msgs_rewrite = list(messages) + [
                        {"role": "user", "content": user_input},
                        {"role": "assistant", "content": reply},
                        {"role": "system", "content": rewrite_msg},
                    ]
                    reply2 = self._call_ollama(msgs_rewrite, max_tokens if max_tokens else 150)
                except Exception:
                    reply2 = ""
                if not reply2 or self._stage2_has_fabrication(reply2, true_items):
                    reply = _FABRICATION_FALLBACK.format(items="、".join(true_items))
                else:
                    reply = reply2
            return reply, True, False
        except Exception:
            # 阶段 1 尚未执行工具即异常 → 回退关键词路由安全（无副作用）
            return None, False, True

    # WO-20260816-35：空结果判定——工具结果为空串/空 JSON 容器/内置『（…没有…）』文案
    @staticmethod
    def _is_empty_tool_result(result: str) -> bool:
        """工具结果是否为空/无内容（阶段 2 据此切换空结果模式，防编造填充）。"""
        r = (result or "").strip()
        if not r:
            return True
        if r in ("[]", "{}", "(空)", "（空）", "null", "None", "无"):
            return True
        # 内置工具空结果文案：『（今天没有日程安排）』『（记忆里没有相关内容）』
        # 『（未查询到相关资料）』『（还没有保存过规划）』『（没有搜到相关结果）』
        if r.startswith("（") and ("没有" in r or "未查询" in r or "未找到" in r):
            return True
        # 空 JSON 容器：{"files": []} / {"items": []} 等
        if re.search(r'"[A-Za-z_]+"\s*:\s*\[\s*\]', r):
            return True
        if "0 条" in r or "0条" in r:
            return True
        return False

    # WO-20260816-37（QA P1）：非空结果防填充——解析工具真实条目
    @staticmethod
    def _extract_true_items(result_text: str) -> list:
        """解析工具结果中的真实条目（列表型 JSON 键优先：files/entries/items/results；
        其次编号文本行：`1. xxx` / `- xxx`）；解析失败返回空列表（回退纯提示词约束）。"""
        r = (result_text or "").strip()
        if not r:
            return []
        # 列表型 JSON 键（Obsidian vault_list / search 等）
        for key in ("files", "entries", "items", "results", "documents", "paths", "matches"):
            m = re.search(rf'"{key}"\s*:\s*\[(.*?)\]', r, re.DOTALL)
            if m:
                items = [v.strip() for v in re.findall(r'"([^"]+)"', m.group(1))]
                if items:
                    return items
        # 编号文本行：1. xxx / 2、xxx / - xxx（web_search 结果等）
        items = []
        for line in r.splitlines():
            line = line.strip()
            m = re.match(r"^\d+[.、)]\s*(.+)$", line)
            if m:
                item = m.group(1).strip()
                if item and "链接：" not in item and "摘要：" not in item:
                    items.append(item)
            elif line.startswith("- ") and len(line) > 2:
                items.append(line[2:].strip())
        return items

    @staticmethod
    def _count_reply_list_items(reply: str) -> int:
        """统计回复中列出的条目数（`1. ` / `2、` / `- ` 开头行）。"""
        n = 0
        for line in (reply or "").splitlines():
            line = line.strip()
            if re.match(r"^\d+[.、)]", line) or line.startswith("- "):
                n += 1
        return n

    @staticmethod
    def _normalize_for_match(s: str) -> str:
        """条目比对归一化：去首尾空白/内部空白/尾斜杠、全角→半角、小写。

        M6.8（WO-20260816-38，QA C02-2 误判）：真实条目 'AI虚拟人物/' 在回复中被合理改写
        （如『AI 虚拟人物』插空格、『AI 虚拟人物/』尾斜杠、全角空格、大小写）时必须识别为真实。
        """
        if not s:
            return ""
        s = s.strip().replace("　", " ").replace("\u3000", " ")
        # 常用全角 → 半角（中文/数字/字母不受影响）
        s = s.translate(str.maketrans("，。！？（）；：", ",.!?();:"))
        return re.sub(r"\s+", "", s).strip("/").lower()

    def _stage2_has_fabrication(self, reply: str, true_items: list) -> bool:
        """非空结果下判断回复是否编造填充：
        - 回复含真实条目（归一化宽松比对）→ 比对列表项数（> 真实条数 = 编造）；
        - 回复不含真实条目且非『没找到』 → 编造/回避（如 QA 实测编造 5 条全为结果外）。
        """
        if not true_items or not (reply or "").strip():
            return False
        if any(kw in reply for kw in _EMPTY_RESULT_HINTS):
            return False  # 如实没找到，不判
        reply_flat = self._normalize_for_match(reply)
        norm_items = [self._normalize_for_match(it) for it in true_items]
        if any(ni and ni in reply_flat for ni in norm_items):
            return self._count_reply_list_items(reply) > len(true_items)
        return True  # 声称列出但回复中无任何真实条目

    # WO-20260816-37（QA P2）：模板短语表（代码层检测/删除，7B 未完全遵循提示词时兜底）
    _TEMPLATE_PHRASES = (
        "今天过得怎么样？我在呢",
        "今天过得怎么样?我在呢",
        "今天过得怎么样？",
        "今天过得怎么样?",
        "有想聊的就叫我哦",
        "有想聊的就叫我",
        "有事儿随时跟我说哦",
        "有事随时跟我说哦",
    )

    def _strip_template_phrases(self, reply: str) -> str:
        """删除回复中高频模板短语（WO-36 提示词约束 7B 未完全遵循，代码层兜底）。

        仅在实际删除了模板短语时才清理残留标点；无模板的回复原样返回（不误伤正常标点）。
        """
        r = reply or ""
        removed = False
        for p in self._TEMPLATE_PHRASES:
            if p in r:
                r = r.replace(p, "")
                removed = True
        if not removed:
            return r
        r = re.sub(r"[～~。！？]{2,}", "～", r)
        r = re.sub(r"[，,。]{2,}", "，", r)
        r = re.sub(r"\s{2,}", " ", r).strip(" ，。！？～")
        if not r:
            return "嗯嗯，我在呢～"  # 极端保底（回复全为模板时）
        return r

    # WO-20260816-35：Obsidian 工具参数精确提示（LLM 曾把 path 传成 '30' 而非 '30 · 项目'
    # 导致返回空结果；schema 描述补充完整目录名提示，增强进候选 schema 的深拷贝副本）
    _OBSIDIAN_ARG_HINTS = {
        "path": "（path 必须用完整目录名，如 '30 · 项目'——注意中文空格与序号前缀，"
                "不要缩写为 '30'，也不要加前导斜杠（'/' 单独表示根目录，如 '/30 · 项目' 是错误写法））",
        "query": "（query 用简洁关键词；如需限定目录，配合完整目录名，如 '30 · 项目'）",
    }

    # M6.4（WO-20260816-33，QA P1②）：工具结果人类可读标签——把原始 JSON/结果按工具
    # 语义标注成中文说明（如 obsidian_vault_list → 知识库目录列表），帮助 7B 理解结果
    # 并如实转述，避免把技术化结果误当『做不到/没查到』而回避。
    _TOOL_RESULT_LABELS = {
        "get_schedule": "日程安排",
        "add_schedule": "日程添加结果",
        "mark_schedule_done": "日程完成标记结果",
        "delete_schedule": "日程删除结果",
        "query_memory": "记忆检索结果",
        "query_knowledge": "知识查询结果",
        "calculate": "计算结果",
        "list_plans": "计划列表",
        "save_plan": "计划保存结果",
        "web_search": "联网搜索结果",
        "obsidian_vault_list": "知识库目录列表",
        "obsidian_vault_read": "知识库文件内容",
        "obsidian_search_simple": "知识库搜索结果",
        "obsidian_search_query": "知识库检索结果",
        "obsidian_vault_get_document_map": "知识库文档结构",
        "obsidian_active_file_get_path": "当前打开的文件",
        "obsidian_tag_list": "知识库标签列表",
        "obsidian_open_file": "打开文件结果",
        "obsidian_vault_write": "知识库写入结果",
        "obsidian_vault_append": "知识库追加结果",
        "obsidian_vault_patch": "知识库修改结果",
        "obsidian_vault_delete": "知识库删除结果",
        "obsidian_vault_move": "知识库移动结果",
        "obsidian_vault_copy": "知识库复制结果",
        "obsidian_command_list": "可用命令列表",
        "obsidian_command_execute": "命令执行结果",
    }

    def _format_tool_results(self, stage1: List[dict]) -> str:
        """把阶段 1 的工具结果格式化为人类可读呈现（工具名 → 中文标签 + 内容）。"""
        lines = []
        for m in stage1:
            if m["role"] != "tool":
                continue
            label = self._TOOL_RESULT_LABELS.get(m.get("name", ""), m.get("name", "工具"))
            lines.append(f"[{label}] {m['content']}")
        return "\n".join(lines)

    @staticmethod
    def _needs_keyword_route(text: str) -> bool:
        """工具路径未使用工具时，是否仍需走关键词路由（保证确定性操作发生）。"""
        return (
            is_knowledge_query(text)
            or is_calculator_query(text)
            or is_memory_query(text)
            or is_planning_query(text)
            or is_schedule_query(text)
            or is_web_search_query(text)     # M6.4：联网搜索（『帮我搜一下 X 新闻』）
            or is_obsidian_query(text)       # M6.4：知识库/笔记（Obsidian MCP）
        )

    @staticmethod
    def _needs_llm_tool_decision(text: str) -> bool:
        """是否需要两阶段 LLM 工具决策（M6.9，WO-20260816-40 确定性优先）：

        强关键词意图（日程/记忆/计算/规划）选型确定——直接走 _route_by_keywords 确定性执行，
        跳过阶段 1 LLM 决策（基线『提醒我喝水』11.1s → ≤6s 目标，正确性不降）；
        模糊意图（知识/搜索/知识库）保留 LLM 决策（需选工具，或精确参数如 obsidian path）。
        """
        return (is_knowledge_query(text) or is_web_search_query(text) or is_obsidian_query(text))

    @property
    def system_prompt(self) -> str:
        """当前系统提示词（调试用）。"""
        return self._system_prompt
