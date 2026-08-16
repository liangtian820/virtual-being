"""人格 Agent（M2/M3）：温柔治愈人设对话 + 意图路由到能力 Agent。

M2 编排：
- 意图路由：用户输入命中知识查询意图 → 调用能力 Agent（知识查询）→ 结果作为上下文注入，
  仍由本 Agent（LLM + 人设 prompt）用人设语气组织回复（能力 Agent 不抢人设）。
- 未命中 → 原对话逻辑。

M3 编排：
- 新增计算意图：命中 → 调用能力 Agent（CalculatorAgent）→ 计算结果注入上下文，
  人设包装仍由本 Agent 完成。
"""
import re
import uuid
from typing import List, Optional

import requests

from app.agents.calculator_agent import CalculatorAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.config import CONFIG
from app.memory.long_term_memory import LongTermMemory
from app.memory.session_memory import SessionMemory
from app.persona.prompts import build_system_prompt

# 知识查询意图关键词（起步版简单规则；后续可换模型判断）
_KNOWLEDGE_PATTERN = re.compile(r"(查一下|什么是|是什么|介绍一下|查找|搜索|查询|帮我查|了解)", re.IGNORECASE)

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
    if is_calculator_query(user_input) or is_knowledge_query(user_input):
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


class PersonaAgent:
    """人格 Agent：人设注入 + 会话记忆 + 意图路由 + Ollama 推理。"""

    def __init__(self, memory: Optional[SessionMemory] = None, model: Optional[str] = None,
                 base_url: Optional[str] = None, temperature: Optional[float] = None,
                 long_memory: Optional[LongTermMemory] = None) -> None:
        self._memory = memory or SessionMemory(max_turns=CONFIG.max_history_turns)
        self._memory_long = long_memory or LongTermMemory()
        self._model = model or CONFIG.ollama_model
        self._base_url = base_url or CONFIG.ollama_base_url
        self._temperature = temperature if temperature is not None else CONFIG.temperature
        self._system_prompt = build_system_prompt()
        self._knowledge = KnowledgeAgent()
        self._calculator = CalculatorAgent()

    def chat(self, user_input: str, session_id: Optional[str] = None,
             max_tokens: Optional[int] = None) -> tuple:
        """一次对话：返回 (回复文本, session_id)。

        :param max_tokens: Ollama num_predict 上限（M4.2：语音链路按回复长度约束
            从源头限制生成，文本 API 不传则不限；None=沿用模型默认）
        """
        sid = session_id or uuid.uuid4().hex
        self._memory.append(sid, "user", user_input)
        messages = [{"role": "system", "content": self._system_prompt}]
        # M3 长期记忆注入：检索与该输入相关的过往记忆（新会话也能"记得用户"）
        memories = self._memory_long.retrieve(user_input)
        if not memories:
            memories = self._memory_long.recent(limit=2)
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
        # M2 意图路由：知识查询 → 能力 Agent 取结果注入（人设包装仍由本 Agent）
        elif is_knowledge_query(user_input):
            result = self._knowledge.query(user_input)
            context = f"[知识查询结果，来源：{result['source'] or '无'}]\n{result['answer']}"
            if result.get("origin") == "none" or not result.get("source"):
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
        # M6 v3（WO-20260816-15，T03/T08）：普通对话路径（非危机/知识/计算）注入长度约束提示
        else:
            messages.append({
                "role": "system",
                "content": "回复尽量简短：日常聊天一两句话就好（60 字内），情绪安抚也尽量控制在 80 字内；"
                           "说完就停下来，不要继续展开。",
            })
            # M6 v2（WO-20260816-13，T16/R3）：能力边界强提示（普通对话路径常驻注入）
            messages.append({
                "role": "system",
                "content": "记住你的能力边界：你现在只能在对话里帮忙——查资料、算一算、陪你聊天、给建议。"
                           "如果用户要求你操作电脑、处理文件、记录日程、控制系统，或做现实世界里的事，"
                           "就温柔地说『这个我还做不到哦』，说明你只能在对话里帮忙，再转向你能做的小事；"
                           "绝不答应『我帮你操作/直接搞定』，也绝不假装已经做完了没做过的事。",
            })
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
        self._memory.append(sid, "assistant", reply)
        return reply, sid

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

    @property
    def system_prompt(self) -> str:
        """当前系统提示词（调试用）。"""
        return self._system_prompt
