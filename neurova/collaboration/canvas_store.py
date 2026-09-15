"""
协作画布存储 (CanvasStore)。

为 CanvasDesignerPage 提供画布快照的持久化能力：
- 布局: <base>/canvases/<canvas_id>.json  画布快照

设计约束（AGENTS.md）:
- 线程安全: threading.RLock 保护共享索引
- 单例生命周期: get_canvas_store() / reset_canvas_store()
- 容错: 单个损坏文件跳过，不影响其余数据读取

运行语义说明:
画布执行由 neurflow 工作流引擎负责（见 collaboration_api.run_canvas_workflow：
画布快照经 canvas_bridge 编译为 WorkflowDefinition 后交引擎执行，
执行记录持久化在 neurflow SQLite 中）。本存储只管画布数据本身。
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = Path("data") / "collaboration"


class CanvasVersionConflict(Exception):
    """乐观锁冲突：调用方携带的 base_version 落后于画布当前版本。

    实时抢占语义的地基——用户手动保存与 agent op 并发时，
    过期写入被拒绝（而非静默覆盖），调用方重读后重试。
    """

    def __init__(self, message: str, current_version: int = 0):
        super().__init__(message)
        self.current_version = current_version


class CanvasStore:
    """画布快照的文件持久化存储。"""

    def __init__(self, base_dir: Optional[Path] = None):
        self._base = Path(base_dir) if base_dir else _DEFAULT_BASE_DIR
        self._canvas_dir = self._base / "canvases"
        self._lock = threading.RLock()
        self._canvas_dir.mkdir(parents=True, exist_ok=True)

    # ── 内部工具 ────────────────────────────────────────────────

    def _canvas_path(self, canvas_id: str) -> Path:
        return self._canvas_dir / f"{canvas_id}.json"

    def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - 单文件损坏不拖垮整体
            logger.warning("画布文件读取失败，已跳过 %s: %s", path.name, e)
            return None

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _validate_id(value: str) -> bool:
        # 防路径穿越：只允许安全 id 字符
        return bool(value) and all(c.isalnum() or c in "-_" for c in value)

    # ── 属主判定（B0，对齐 neurflow storage P0-1 语义）────────────

    @staticmethod
    def _owner_of(record: Dict[str, Any]) -> str:
        """存量文件无 user_id → 懒归 'default'（不重写旧文件）。"""
        return record.get("user_id") or "default"

    def _can_read(self, record: Dict[str, Any], requester_id: str,
                  is_admin: bool, project_ids: Optional[set]) -> bool:
        if is_admin or requester_id == self._owner_of(record):
            return True
        pid = record.get("project_id")
        return bool(pid) and pid in (project_ids or set())

    def _can_write(self, record: Dict[str, Any], requester_id: str, is_admin: bool) -> bool:
        # 项目成员只读；写（改/删/op）仅属主或 admin
        return is_admin or requester_id == self._owner_of(record)

    # ── 画布快照 CRUD ───────────────────────────────────────────

    def create(self, snapshot: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
        now = time.time()
        record = {
            **snapshot,
            "id": f"canvas_{uuid.uuid4().hex[:12]}",
            "version": 1,
            "created_at": now,
            "updated_at": now,
            # 属主以调用方（JWT）为准，防快照内伪造 user_id；缺省归 default
            "user_id": user_id or snapshot.get("user_id") or "default",
        }
        record.setdefault("origin", "manual")
        with self._lock:
            self._write_json(self._canvas_path(record["id"]), record)
        logger.info("画布已创建: %s (%s, owner=%s)", record["id"], record.get("name", ""), record["user_id"])
        return record

    def get(
        self,
        canvas_id: str,
        requester_id: Optional[str] = None,
        is_admin: bool = False,
        project_ids: Optional[set] = None,
    ) -> Optional[Dict[str, Any]]:
        """读取画布快照。

        requester_id=None → 系统内部路径（agent op/项目统计）不受限；
        传 ID 时 owner/admin/项目成员可读，其余返回 None（与不存在同构）。
        """
        if not self._validate_id(canvas_id):
            return None
        with self._lock:
            if not self._canvas_path(canvas_id).exists():
                return None
            record = self._read_json(self._canvas_path(canvas_id))
            if record is None:
                return None
            if requester_id is not None and not self._can_read(
                record, requester_id, is_admin, project_ids
            ):
                return None
            return record

    def update(
        self,
        canvas_id: str,
        snapshot: Dict[str, Any],
        base_version: Optional[int] = None,
        requester_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """全量替换画布快照。

        Args:
            canvas_id: 画布 ID
            snapshot: 新快照（整体替换 nodes/edges 等）
            base_version: 乐观锁基版本；提供且与当前版本不符时抛
                CanvasVersionConflict，不产生任何写入。
            requester_id: 请求者（B0）。None=系统内部路径不受限；
                非 owner/admin → None（与不存在同构，项目成员亦不可写）。

        Returns:
            更新后的记录（含递增的 version），画布不存在或无权返回 None。
        """
        if not self._validate_id(canvas_id):
            return None
        with self._lock:
            existing = self.get(canvas_id)
            if existing is None:
                return None
            if requester_id is not None and not self._can_write(existing, requester_id, is_admin):
                return None
            current_version = int(existing.get("version", 1))
            if base_version is not None and int(base_version) != current_version:
                raise CanvasVersionConflict(
                    f"画布版本冲突: base_version={base_version} 落后于当前版本 {current_version}",
                    current_version=current_version,
                )
            record = {
                **snapshot,
                "id": canvas_id,
                "version": current_version + 1,
                "created_at": existing.get("created_at", time.time()),
                "updated_at": time.time(),
                # 属主/来源不可被更新篡改
                "user_id": self._owner_of(existing),
                "origin": existing.get("origin") or snapshot.get("origin") or "manual",
            }
            # project_id/agent_id：快照未显式提供时保留既有归属（改名/局部保存不丢归属）；
            # 显式提供（含 null）则以快照为准，支持主动改/解除归属。
            for owner_key in ("project_id", "agent_id"):
                if owner_key not in snapshot:
                    record[owner_key] = existing.get(owner_key)
            self._write_json(self._canvas_path(canvas_id), record)
        logger.info("画布已更新: %s (v%s)", canvas_id, record["version"])
        return record

    def mutate(
        self,
        canvas_id: str,
        fn: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
        base_version: Optional[int] = None,
        requester_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """原子 read-modify-write：锁内读取、应用 fn、版本递增、落盘。

        op 层（canvas_ops.py）的唯一写入通道，保证并发 op 不丢更新。

        Args:
            canvas_id: 画布 ID
            fn: 接收记录深拷贝、返回修改后记录的纯函数；返回 None 表示
                中止（不写入、版本不变，返回当前记录）
            base_version: 乐观锁基版本，语义同 update()
            requester_id: 请求者（B0），语义同 update()（写=owner/admin）

        Returns:
            写入后的新记录（中止时为当前记录），画布不存在或无权返回 None。
        """
        if not self._validate_id(canvas_id):
            return None
        with self._lock:
            existing = self.get(canvas_id)
            if existing is None:
                return None
            if requester_id is not None and not self._can_write(existing, requester_id, is_admin):
                return None
            current_version = int(existing.get("version", 1))
            if base_version is not None and int(base_version) != current_version:
                raise CanvasVersionConflict(
                    f"画布版本冲突: base_version={base_version} 落后于当前版本 {current_version}",
                    current_version=current_version,
                )
            mutated = fn(copy.deepcopy(existing))
            if mutated is None:
                return existing
            record = {
                **mutated,
                "id": canvas_id,
                "version": current_version + 1,
                "created_at": existing.get("created_at", time.time()),
                "updated_at": time.time(),
                "user_id": self._owner_of(existing),
            }
            self._write_json(self._canvas_path(canvas_id), record)
        logger.info("画布已变更: %s (v%s)", canvas_id, record["version"])
        return record

    def writable(self, canvas_id: str, requester_id: str, is_admin: bool = False) -> bool:
        """HTTP op 端点前置校验：请求者是否可写该画布（owner/admin）。不存在=False。"""
        record = self.get(canvas_id)
        return record is not None and self._can_write(record, requester_id, is_admin)

    def list(
        self,
        requester_id: Optional[str] = None,
        is_admin: bool = False,
        project_ids: Optional[set] = None,
        view: Optional[str] = None,
        project_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        """返回画布摘要（不含 nodes/edges 大对象），按 updated_at 倒序。

        requester_id=None → 系统全量（项目统计等内部路径）。传 ID 时只见
        自己的 + 项目成员可见 + admin 全量（B0）。view 三视图过滤（B1）：
        personal=无项目无 agent 归属；project=project_id 非空；agent=agent_id 非空。
        """
        items: list[Dict[str, Any]] = []
        with self._lock:
            for path in self._canvas_dir.glob("*.json"):
                data = self._read_json(path)
                if not isinstance(data, dict) or not data.get("id"):
                    continue
                if requester_id is not None and not self._can_read(
                    data, requester_id, is_admin, project_ids
                ):
                    continue
                items.append(
                    {
                        "id": data["id"],
                        "name": data.get("name", ""),
                        "user_id": self._owner_of(data),
                        "project_id": data.get("project_id"),
                        "agent_id": data.get("agent_id"),
                        "origin": data.get("origin"),
                        "node_count": len(data.get("nodes", []) or []),
                        "edge_count": len(data.get("edges", []) or []),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                    }
                )
        if view == "personal":
            items = [i for i in items if not i.get("project_id") and not i.get("agent_id")]
        elif view == "project":
            items = [i for i in items if i.get("project_id")]
        elif view == "agent":
            items = [i for i in items if i.get("agent_id")]
        if project_id:
            items = [i for i in items if i.get("project_id") == project_id]
        if agent_id:
            items = [i for i in items if i.get("agent_id") == agent_id]
        items.sort(key=lambda i: i.get("updated_at") or 0, reverse=True)
        return items

    def delete(self, canvas_id: str, requester_id: Optional[str] = None,
               is_admin: bool = False) -> bool:
        """删除画布快照；存在且有权返回 True，否则 False（同构语义）。"""
        if not self._validate_id(canvas_id):
            return False
        with self._lock:
            path = self._canvas_path(canvas_id)
            if not path.exists():
                return False
            if requester_id is not None:
                record = self._read_json(path)
                if record is None or not self._can_write(record, requester_id, is_admin):
                    return False
            path.unlink()
        logger.info("画布已删除: %s", canvas_id)
        return True


# ── 单例生命周期 ────────────────────────────────────────────────

_canvas_store_instance: Optional[CanvasStore] = None


def get_canvas_store() -> CanvasStore:
    global _canvas_store_instance
    if _canvas_store_instance is None:
        _canvas_store_instance = CanvasStore()
    return _canvas_store_instance


def reset_canvas_store() -> None:
    global _canvas_store_instance
    _canvas_store_instance = None


__all__ = ["CanvasStore", "CanvasVersionConflict", "get_canvas_store", "reset_canvas_store"]
