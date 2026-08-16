"""人格 Agent 与记忆的离线单元测试（不调用 Ollama）。"""
import pytest

from app.memory.session_memory import SessionMemory
from app.persona.character_card import CHARACTER_CARD, to_cc_v2_json
from app.persona.prompts import build_first_message, build_system_prompt


def test_build_system_prompt_contains_core_sections() -> None:
    """系统提示词应包含身份、性格、说话风格、准则等核心段落。"""
    prompt = build_system_prompt()
    assert "【身份设定】" in prompt
    assert "【性格】" in prompt
    assert "【说话风格】" in prompt
    assert "【行为准则】" in prompt
    assert CHARACTER_CARD["name"] in prompt


def test_build_system_prompt_contains_personality_items() -> None:
    """性格与风格条目应逐条注入。"""
    prompt = build_system_prompt()
    for item in CHARACTER_CARD["personality"]:
        assert item in prompt
    for item in CHARACTER_CARD["speech_style"]:
        assert item in prompt


def test_first_message() -> None:
    """开场白应来自角色卡。"""
    assert build_first_message() == CHARACTER_CARD["first_message"]


def test_to_cc_v2_json_structure() -> None:
    """导出结构应对齐 SillyTavern CC V2 规范。"""
    cc = to_cc_v2_json()
    assert cc["spec"] == "chara_card_v2"
    data = cc["data"]
    for field in ("name", "description", "personality", "scenario", "first_mes", "mes_example"):
        assert field in data, f"CC V2 缺少字段 {field}"
    assert data["name"] == CHARACTER_CARD["name"]
    assert data["first_mes"] == CHARACTER_CARD["first_message"]
    assert "<START>" in data["mes_example"]


def test_session_memory_append_and_load() -> None:
    """会话记忆应正确追加与读取。"""
    mem = SessionMemory(max_turns=2)
    mem.append("s1", "user", "你好")
    mem.append("s1", "assistant", "嗨")
    history = mem.load("s1")
    assert history == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
    ]


def test_session_memory_trim() -> None:
    """超过 max_turns 轮时应裁剪到最近轮次。"""
    mem = SessionMemory(max_turns=2)
    for i in range(5):
        mem.append("s1", "user", f"u{i}")
        mem.append("s1", "assistant", f"a{i}")
    history = mem.load("s1")
    # 保留最近 2 轮 = 4 条消息
    assert len(history) == 4
    assert history[0]["content"] == "u3"


def test_session_memory_isolated() -> None:
    """不同 session 之间互不干扰。"""
    mem = SessionMemory()
    mem.append("a", "user", "x")
    assert mem.load("b") == []
