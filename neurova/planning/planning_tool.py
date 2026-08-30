"""PlanningTool —— 计划即工具（对比文档 P5）

对标 OpenManus PlanningTool 的 7 命令语义（create/update/list/get/set_active/
mark_step/delete），关键差异：计划持久化到 SQLite（OpenManus 是进程内 dict，
重启即失），跨会话/重启后计划与活跃指针自动还原。

安全：SQL 以字面量内联在 execute 调用处，数据全部走参数绑定（?）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 计划步骤状态（对标 OpenManus PlanStepStatus）
STEP_STATUS_NOT_STARTED = "not_started"
STEP_STATUS_IN_PROGRESS = "in_progress"
STEP_STATUS_COMPLETED = "completed"
STEP_STATUS_BLOCKED = "blocked"
VALID_STEP_STATUSES = (
    STEP_STATUS_NOT_STARTED,
    STEP_STATUS_IN_PROGRESS,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_BLOCKED,
)

# 状态渲染符号（get 文本里直观展示进度）
STATUS_MARKS = {
    STEP_STATUS_COMPLETED: "[✓]",
    STEP_STATUS_IN_PROGRESS: "[→]",
    STEP_STATUS_BLOCKED: "[!]",
    STEP_STATUS_NOT_STARTED: "[ ]",
}

_VALID_COMMANDS = ("create", "update", "list", "get", "set_active", "mark_step", "delete")


class PlanStore:
    """计划 SQLite 存储层（SQL 内联 execute 调用 + 参数绑定；RLock 保护跨线程访问）"""

    def __init__(self, db_path: str = "data/plans.db"):
        self.db_path = db_path
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()
        logger.info("PlanStore initialized with db_path=%s", db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    step_statuses TEXT NOT NULL,
                    step_notes TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    def upsert(
        self,
        plan_id: str,
        title: str,
        steps: List[str],
        step_statuses: List[str],
        step_notes: List[str],
    ) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock, self._get_conn() as conn:
            conn.execute(
                """INSERT INTO plans (plan_id, title, steps, step_statuses, step_notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(plan_id) DO UPDATE SET
                        title = excluded.title,
                        steps = excluded.steps,
                        step_statuses = excluded.step_statuses,
                        step_notes = excluded.step_notes,
                        updated_at = excluded.updated_at""",
                (plan_id, title, json.dumps(steps), json.dumps(step_statuses), json.dumps(step_notes), now, now),
            )

    def delete(self, plan_id: str) -> None:
        with self._lock, self._get_conn() as conn:
            conn.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,))

    def clear_active(self) -> None:
        with self._lock, self._get_conn() as conn:
            conn.execute("UPDATE plans SET is_active = 0 WHERE is_active = 1")

    def set_active(self, plan_id: str) -> None:
        with self._lock, self._get_conn() as conn:
            conn.execute("UPDATE plans SET is_active = 0 WHERE is_active = 1")
            conn.execute("UPDATE plans SET is_active = 1 WHERE plan_id = ?", (plan_id,))

    def get(self, plan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._get_conn() as conn:
            row = conn.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def get_active(self) -> Optional[Dict[str, Any]]:
        with self._lock, self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM plans WHERE is_active = ?", (1,)).fetchall()
        # 活跃计划至多一条（set_active 先清后设）；防御性取首条
        return self._row_to_dict(rows[0]) if rows else None

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock, self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM plans").fetchall()
        plans = [self._row_to_dict(r) for r in rows]
        # 最近更新优先（排序在应用层完成）
        plans.sort(key=lambda p: p["updated_at"], reverse=True)
        return plans

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "plan_id": row["plan_id"],
            "title": row["title"],
            "steps": json.loads(row["steps"]),
            "step_statuses": json.loads(row["step_statuses"]),
            "step_notes": json.loads(row["step_notes"]),
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


class PlanningTool:
    """计划即工具：LLM 通过 7 个子命令创建、推进、查询结构化计划"""

    name = "planning"

    def __init__(self, db_path: str = "data/plans.db", store: Optional[PlanStore] = None):
        self._store = store or PlanStore(db_path)

    async def run_command(self, *, command: str, plan_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        if command not in _VALID_COMMANDS:
            return {"success": False, "error": "未知命令，可用命令: create / update / list / get / set_active / mark_step / delete"}

        try:
            if command == "create":
                return self._create(plan_id, kwargs.get("title"), kwargs.get("steps"))
            if command == "update":
                return self._update(plan_id, kwargs.get("title"), kwargs.get("steps"))
            if command == "list":
                return self._list()
            if command == "get":
                return self._get(plan_id)
            if command == "set_active":
                return self._set_active(plan_id)
            if command == "mark_step":
                return self._mark_step(plan_id, kwargs.get("step_index"), kwargs.get("step_status"), kwargs.get("step_notes"))
            if command == "delete":
                return self._delete(plan_id)
            return {"success": False, "error": "未知命令，可用命令: create / update / list / get / set_active / mark_step / delete"}  # pragma: no cover
        except Exception as e:  # noqa: BLE001 - 工具层兜底：错误以结果返回而非中断对话
            logger.error("planning 命令 %s 执行失败: %s", command, e)
            return {"success": False, "error": f"计划命令执行失败: {e}"}

    # ── 命令实现 ──

    def _create(self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]) -> Dict[str, Any]:
        if not plan_id or not title or not steps:
            return {"success": False, "error": "create 需要 plan_id、title、steps（非空）"}
        if self._store.get(plan_id):
            return {"success": False, "error": f"计划已存在: {plan_id}（用 update 修改或换 plan_id）"}
        statuses = [STEP_STATUS_NOT_STARTED] * len(steps)
        self._store.upsert(plan_id, title, list(steps), statuses, [""] * len(steps))
        return {"success": True, "data": {"plan_id": plan_id, "text": self._render(self._store.get(plan_id))}}

    def _update(self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]) -> Dict[str, Any]:
        plan = self._require(plan_id)
        if isinstance(plan, dict) and plan.get("success") is False:
            return plan
        new_steps = list(steps) if steps else plan["steps"]
        new_statuses = [
            plan["step_statuses"][i] if i < len(plan["step_statuses"]) else STEP_STATUS_NOT_STARTED
            for i in range(len(new_steps))
        ]
        new_notes = [plan["step_notes"][i] if i < len(plan["step_notes"]) else "" for i in range(len(new_steps))]
        self._store.upsert(plan_id, title or plan["title"], new_steps, new_statuses, new_notes)
        return {"success": True, "data": {"plan_id": plan_id, "text": self._render(self._store.get(plan_id))}}

    def _list(self) -> Dict[str, Any]:
        plans = self._store.list_all()
        data = [
            {
                "plan_id": p["plan_id"],
                "title": p["title"],
                "total_steps": len(p["steps"]),
                "completed": sum(1 for s in p["step_statuses"] if s == STEP_STATUS_COMPLETED),
                "is_active": p["is_active"],
            }
            for p in plans
        ]
        return {"success": True, "data": data}

    def _get(self, plan_id: Optional[str]) -> Dict[str, Any]:
        plan = self._store.get(plan_id) if plan_id else self._store.get_active()
        if not plan:
            return {"success": False, "error": f"计划不存在: {plan_id or '<无活跃计划>'}"}
        return {"success": True, "data": {"plan_id": plan["plan_id"], "text": self._render(plan)}}

    def _set_active(self, plan_id: Optional[str]) -> Dict[str, Any]:
        if not plan_id or not self._store.get(plan_id):
            return {"success": False, "error": f"计划不存在: {plan_id}"}
        self._store.set_active(plan_id)
        return {"success": True, "data": {"active_plan_id": plan_id}}

    def _mark_step(
        self,
        plan_id: Optional[str],
        step_index: Optional[int],
        step_status: Optional[str],
        step_notes: Optional[str],
    ) -> Dict[str, Any]:
        plan = self._require(plan_id)
        if isinstance(plan, dict) and plan.get("success") is False:
            return plan
        if step_index is None or not (0 <= step_index < len(plan["steps"])):
            return {"success": False, "error": f"step_index 越界（0..{len(plan['steps']) - 1}）"}
        if step_status not in VALID_STEP_STATUSES:
            return {"success": False, "error": f"非法状态: {step_status}（可用: {'/'.join(VALID_STEP_STATUSES)}）"}
        plan["step_statuses"][step_index] = step_status
        if step_notes is not None:
            plan["step_notes"][step_index] = str(step_notes)
        self._store.upsert(plan["plan_id"], plan["title"], plan["steps"], plan["step_statuses"], plan["step_notes"])
        return {"success": True, "data": {"plan_id": plan["plan_id"], "text": self._render(plan)}}

    def _delete(self, plan_id: Optional[str]) -> Dict[str, Any]:
        if not plan_id or not self._store.get(plan_id):
            return {"success": False, "error": f"计划不存在: {plan_id}"}
        was_active = bool(self._store.get(plan_id).get("is_active"))
        self._store.delete(plan_id)
        if was_active:
            self._store.clear_active()
        return {"success": True, "data": {"deleted": plan_id}}

    # ── 辅助 ──

    def _require(self, plan_id: Optional[str]) -> Any:
        """取计划或返回错误 dict（调用方检查 success 字段）"""
        plan = self._store.get(plan_id) if plan_id else self._store.get_active()
        if not plan:
            return {"success": False, "error": f"计划不存在: {plan_id or '<无活跃计划>'}"}
        return plan

    @staticmethod
    def _render(plan: Dict[str, Any]) -> str:
        lines = [f"计划: {plan['title']} (id={plan['plan_id']}){' [活跃]' if plan['is_active'] else ''}"]
        for i, step in enumerate(plan["steps"]):
            status = plan["step_statuses"][i] if i < len(plan["step_statuses"]) else STEP_STATUS_NOT_STARTED
            mark = STATUS_MARKS.get(status, "[ ]")
            note = plan["step_notes"][i] if i < len(plan["step_notes"]) else ""
            lines.append(f"{mark} {step}" + (f" | {note}" if note else ""))
        done = sum(1 for s in plan["step_statuses"] if s == STEP_STATUS_COMPLETED)
        lines.append(f"进度: {done}/{len(plan['steps'])} 已完成")
        return "\n".join(lines)


# 工厂函数（单例；db 路径来自 data/ 惯例）
_store_instance: Optional[PlanStore] = None
_store_lock = threading.Lock()


def get_planning_store(db_path: str = "data/plans.db") -> PlanStore:
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = PlanStore(db_path)
    return _store_instance


def reset_planning_store() -> None:
    global _store_instance
    with _store_lock:
        _store_instance = None
