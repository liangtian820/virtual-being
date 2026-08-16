"""LLM 工具定义（M6.1 工具调用，WO-20260816-29）。

为 Ollama /api/chat 的 tools 参数提供 OpenAI 兼容的 JSON schema。
每个工具都是对既有能力 Agent / 记忆接口的薄封装（不重复实现业务），
由人格 Agent（persona_agent）在对话中让 LLM 自主决定调用。

原则：
- 覆盖既有能力全集（日程增删查/完成、计划列表/保存、记忆、知识、计算），参数简单；
- 描述用中文，参数必填标注；
- 工具只返回结果字符串；失败返回错误说明（由 LLM 决定如何向用户转述，绝不编造）。
"""

TOOL_SPECS: list = [
    {
        "type": "function",
        "function": {
            "name": "get_schedule",
            "description": "查询 TA（虚拟人物）为当前用户记录的日程安排。用户在问『今天/明天有什么安排』『我的日程』时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "enum": ["today", "tomorrow"],
                        "description": "查询哪一天的安排：today=今天，tomorrow=明天。",
                    }
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_schedule",
            "description": "为用户添加一条日程提醒（如『明天下午3点提醒我喝水』『每天早上提醒我吃药』）。用户在要求记一个提醒/日程/闹钟/待办时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "用户原始的提醒/日程描述（原样传入，含时间与事项，如『明天下午3点提醒我喝水』）。",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_schedule_done",
            "description": "把一条日程提醒标记为已完成。用户说『今天喝水的提醒完成了』『下午的提醒做完了』等表示某条提醒已办完时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要标记完成的目标描述（含日期/时间/事项线索），如『今天喝水的提醒完成了』。",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_schedule",
            "description": "删除一条日程提醒。用户说『删掉明天下午的提醒』『取消今晚的闹钟』『移除某条待办』等要删除提醒时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要删除的目标描述（含日期/时间/事项线索），如『删掉明天下午的提醒』。",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_memory",
            "description": "检索 TA 长期记忆里关于用户的过往信息（用户说过的话、喜好、名字、计划等）。用户在问『你记得我喜欢什么吗』『我说过…』『我的记忆』时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "用户想问的记忆相关内容（原样传入）。",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge",
            "description": "查询内置知识库或联网资料回答事实类问题（如『什么是LangGraph』『帮我查一下…』）。用户在问知识、资讯、概念解释时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "用户的知识类问题（原样传入）。",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算数学算式（如『300 的 20% 是多少』『3 加 5』）。用户在要求算数、算百分比时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "用户的计算请求（原样传入，含数字与运算符）。",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_plans",
            "description": "列出用户保存过的规划（步骤清单）。用户在问『我存过哪些计划』『我的计划』时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_plan",
            "description": "把一份规划（目标+步骤清单）保存到用户的计划库。用户说『把这个计划存下来』『帮我保存这个计划』『记下这个计划』时调用；步骤来自对话中已生成的计划内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "计划的目标简述，如『学会弹吉他』。",
                    },
                    "steps": {
                        "type": "array",
                        "description": "计划的步骤清单（至少 1 步），每步含标题与可选说明。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "no": {
                                    "type": "integer",
                                    "description": "步骤序号（从 1 开始，可选）。",
                                },
                                "title": {
                                    "type": "string",
                                    "description": "步骤标题，如『买一把吉他』。",
                                },
                                "priority": {
                                    "type": "string",
                                    "description": "优先级：高/中/低（可选）。",
                                    "enum": ["高", "中", "低"],
                                },
                                "detail": {
                                    "type": "string",
                                    "description": "该步骤的一句话说明（可选）。",
                                },
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["goal", "steps"],
            },
        },
    },
]

# 工具名 → 说明映射（错误提示用）
TOOL_NAMES = {s["function"]["name"]: s["function"]["description"] for s in TOOL_SPECS}


def get_tool_specs() -> list:
    """返回工具 schema 列表（供 Ollama /api/chat tools 参数使用）。"""
    return TOOL_SPECS
