"""CLI 对话演示：终端里与虚拟人物聊天。

用法：python -m scripts.run_demo
"""
from app.agents.persona_agent import PersonaAgent


def main() -> None:
    """启动终端对话。输入 exit/quit 退出。"""
    agent = PersonaAgent()
    print("=" * 50)
    print("Virtual Being · M1 文本灵魂（CLI 演示）")
    print("输入 exit 或 quit 退出")
    print("=" * 50)
    session_id = None
    while True:
        try:
            user_input = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见～")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("TA> 嗯嗯，那先这样哦，我一直在。")
            break
        try:
            reply, session_id = agent.chat(user_input, session_id)
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            continue
        print(f"TA> {reply}")


if __name__ == "__main__":
    main()
