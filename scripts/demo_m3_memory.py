"""M3 专属记忆演示：跨会话"记得用户"（使用独立演示库，不污染正式记忆）。"""
import os

DB = os.path.abspath("data/demo_m3.db")

from app.agents.persona_agent import PersonaAgent
from app.memory.long_term_memory import LongTermMemory


def main() -> None:
    if os.path.exists(DB):
        os.remove(DB)
    mem = LongTermMemory(db_path=DB)
    agent = PersonaAgent(long_memory=mem)

    print("=== 会话 A（告诉 TA 一个事实）===")
    print("你> 我喜欢猫，它们很可爱")
    reply, sid_a = agent.chat("我喜欢猫，它们很可爱", None)
    print(f"TA> {reply}")
    print()

    print("=== 会话 B（全新会话，模拟隔天再来）===")
    agent2 = PersonaAgent(long_memory=LongTermMemory(db_path=DB))
    print("你> 你还记得我喜欢什么吗？")
    reply2, _ = agent2.chat("你还记得我喜欢什么吗？", None)
    print(f"TA> {reply2}")
    print()

    print(f"长期记忆条数: {mem.count()}")
    for m in mem.recent(5):
        kind, content = m["kind"], m["content"]
        print(f"  [{kind}] {content}")
    mem.close()


if __name__ == "__main__":
    main()
