"""人设提示词构建：把角色卡渲染成系统提示词。"""
from app.persona.character_card import CHARACTER_CARD, IDENTITY_STATEMENT


def _render_examples(examples: list) -> list:
    """把对话示例渲染为系统提示词段落（few-shot 示范语气与应对方式）。"""
    if not examples:
        return []
    lines = []
    for i, turn in enumerate(examples, start=1):
        lines.append(f"<示例{i}>")
        lines.append(f"用户：{turn['user']}")
        lines.append(f"你：{turn['assistant']}")
        lines.append("")
    return lines[:-1]  # 去掉末尾空行（外层已有空行分隔）


def build_system_prompt(card: dict = None) -> str:
    """根据角色卡生成完整系统提示词。

    :param card: 角色卡字典，默认使用内置 CHARACTER_CARD
    :return: 系统提示词文本
    """
    card = card or CHARACTER_CARD
    lines = [
        IDENTITY_STATEMENT.format(name=card["name"]),
        "",
        f"【身份设定】{card['identity']}",
        "",
        "【性格】",
        *[f"- {item}" for item in card["personality"]],
        "",
        "【说话风格】",
        *[f"- {item}" for item in card["speech_style"]],
        "",
        f"【场景】{card['scenario']}",
        "",
        "【行为准则】",
        *[f"- {item}" for item in card["rules"]],
        "",
        "【对话示例】（参考其中的语气与应对方式，但不要照抄）",
        *_render_examples(card.get("example_dialogue", [])),
    ]
    return "\n".join(lines)


def build_first_message(card: dict = None) -> str:
    """获取开场白（首次对话时使用）。"""
    card = card or CHARACTER_CARD
    return card["first_message"]
