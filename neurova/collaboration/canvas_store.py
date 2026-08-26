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

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = Path("data") / "collaboration"


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

    # ── 画布快照 CRUD ───────────────────────────────────────────

    def create(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        record = {
            **snapshot,
            "id": f"canvas_{uuid.uuid4().hex[:12]}",
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._write_json(self._canvas_path(record["id"]), record)
        logger.info("画布已创建: %s (%s)", record["id"], record.get("name", ""))
        return record

    def get(self, canvas_id: str) -> Optional[Dict[str, Any]]:
        if not self._validate_id(canvas_id):
            return None
        with self._lock:
            if not self._canvas_path(canvas_id).exists():
                return None
            return self._read_json(self._canvas_path(canvas_id))

    def update(self, canvas_id: str, snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._validate_id(canvas_id):
            return None
        with self._lock:
            existing = self.get(canvas_id)
            if existing is None:
                return None
            record = {
                **snapshot,
                "id": canvas_id,
                "created_at": existing.get("created_at", time.time()),
                "updated_at": time.time(),
            }
            self._write_json(self._canvas_path(canvas_id), record)
        logger.info("画布已更新: %s", canvas_id)
        return record

    def list(self) -> list[Dict[str, Any]]:
        """返回全部画布摘要（不含 nodes/edges 大对象），按 updated_at 倒序。

        供前端"我的画布"列表找回已保存内容；单个损坏文件跳过。
        """
        items: list[Dict[str, Any]] = []
        with self._lock:
            for path in self._canvas_dir.glob("*.json"):
                data = self._read_json(path)
                if not isinstance(data, dict) or not data.get("id"):
                    continue
                items.append(
                    {
                        "id": data["id"],
                        "name": data.get("name", ""),
                        "project_id": data.get("project_id"),
                        "node_count": len(data.get("nodes", []) or []),
                        "edge_count": len(data.get("edges", []) or []),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                    }
                )
        items.sort(key=lambda i: i.get("updated_at") or 0, reverse=True)
        return items

    def delete(self, canvas_id: str) -> bool:
        """删除画布快照；存在返回 True，不存在返回 False。"""
        if not self._validate_id(canvas_id):
            return False
        with self._lock:
            path = self._canvas_path(canvas_id)
            if not path.exists():
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


__all__ = ["CanvasStore", "get_canvas_store", "reset_canvas_store"]
