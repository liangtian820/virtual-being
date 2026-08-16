"""能力 Agent：规划助手（M2.1 + M2.2）。

只负责"规划"，不负责"说"——人设包装由人格 Agent 完成（能力 Agent 不抢人设）。
M2.2（WO-20260816-23）新增：规划结果保存到 SQLite（『把这个计划存下来』），支持列表/删除。
"""
from typing import Callable, Dict, Optional

from app.tools.planning import PLANS_DB_PATH as _DEFAULT_PLANS_DB
from app.tools.planning import delete_plan as _delete_plan
from app.tools.planning import list_plans as _list_plans
from app.tools.planning import plan as _plan
from app.tools.planning import save_plan as _save_plan


class PlanningAgent:
    """规划能力 Agent：模糊目标 → 结构化步骤清单（LLM 生成、输出 JSON 化）；规划结果可保存。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_PLANS_DB

    def plan(self, goal: str, llm_call: Optional[Callable[[str], str]] = None) -> Dict[str, object]:
        """执行规划，返回 {goal, steps, error, raw}。

        - goal: 目标简述
        - steps: [{"no", "title", "priority", "detail"}, ...]（带序号与预估优先级）
        - error: 成功为 None，失败为明确错误信息（不抛异常）
        - raw: LLM 原始输出（便于排查）
        :param llm_call: 可选注入的 LLM 调用函数（离线测试用），默认走本地 Ollama
        """
        return _plan(goal, llm_call=llm_call)

    def save(self, plan_result: Dict[str, object]) -> Dict[str, object]:
        """保存一份规划结果（『把这个计划存下来』→ SQLite），返回 {"id", "error"}。

        :param plan_result: plan() 的返回结构 {"goal", "steps": [...]}，额外字段忽略
        """
        return _save_plan(plan_result, db_path=self._db_path)

    def list_plans(self) -> Dict[str, object]:
        """列出已保存的计划：{"plans": [{id, goal, step_count, created_at}], "count", "error"}。"""
        return _list_plans(db_path=self._db_path)

    def delete_plan(self, plan_id: int) -> Dict[str, object]:
        """删除一份已保存的计划：{"deleted": bool, "error"}。"""
        return _delete_plan(plan_id, db_path=self._db_path)
