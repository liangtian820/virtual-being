"""人设提示词构建：把角色卡渲染成系统提示词。"""
from app.persona.character_card import CHARACTER_CARD, IDENTITY_STATEMENT


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
    ]
    return "\n".join(lines)


def build_first_message(card: dict = None) -> str:
    """获取开场白（首次对话时使用）。"""
    card = card or CHARACTER_CARD
    return card["first_message"]
