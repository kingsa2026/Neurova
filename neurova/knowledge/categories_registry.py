"""知识库自定义分类注册表（specs/2026-11-07 批 A）：受控分类清单的单一事实源。

分组白名单（`allowed_categories`）、前端分类下拉、导入分类选择全部引用本表；
注册表只管"有哪些分类"，不做租户/部门切分——部门级开放由分组白名单表达
（设计 §2.1：写入面第一阶段不强制校验，登记为后续收紧项）。

存储：foundation 库（knowledge_facts.db）v38 建表；读写走 KnowledgeFactStore
的同一把锁与连接（与事实/本体同库同纪律）。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

_SCHEMA_V38_CATEGORIES = """
CREATE TABLE IF NOT EXISTS knowledge_categories (
    category_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def normalizeCategoryId(raw: str) -> str:
    """分类标识规范化：去首尾空白、小写。分组白名单与注册表同规。"""
    return str(raw or "").strip().lower()


class CategoryRegistry:
    """`knowledge_categories` 的唯一读写面（create/get/list/update/delete 五动词）。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from .foundation.foundation_schema import applyTo  # 惰性：注册处反向依赖本域模块

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    @staticmethod
    def _rowToDict(row: Any) -> Dict[str, Any]:
        return {
            "category_id": row["category_id"],
            "name": row["name"],
            "description": row["description"],
            "is_active": bool(row["is_active"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }

    def create(self, categoryId: str, name: str, description: str = "", actor: str = "") -> Dict[str, Any]:
        cid = normalizeCategoryId(categoryId)
        if not cid:
            raise ValueError("分类标识不能为空")
        if not str(name or "").strip():
            raise ValueError("分类名称不能为空")
        with self._store._lock, self._store._conn:
            exists = self._store._conn.execute(
                "SELECT 1 FROM knowledge_categories WHERE category_id = ?", (cid,)
            ).fetchone()
            if exists:
                raise ValueError(f"分类 '{cid}' 已注册")
            self._store._conn.execute(
                "INSERT INTO knowledge_categories (category_id, name, description, is_active,"
                " created_by, created_at, updated_by, updated_at) VALUES (?,?,?,1,?,?,?,?)",
                (cid, str(name).strip(), str(description or ""), str(actor or ""), _now(), str(actor or ""), _now()),
            )
        return self.get(cid)

    def get(self, categoryId: str) -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM knowledge_categories WHERE category_id = ?",
                (normalizeCategoryId(categoryId),),
            ).fetchone()
        return self._rowToDict(row) if row is not None else None

    def list(self, activeOnly: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM knowledge_categories"
        if activeOnly:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY category_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql).fetchall()
        return [self._rowToDict(r) for r in rows]

    def update(
        self,
        categoryId: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        actor: str = "",
    ) -> Dict[str, Any]:
        cid = normalizeCategoryId(categoryId)
        if self.get(cid) is None:
            raise ValueError(f"分类 '{cid}' 未注册")
        fields: List[str] = []
        params: List[Any] = []
        if name is not None:
            if not str(name).strip():
                raise ValueError("分类名称不能为空")
            fields.append("name = ?")
            params.append(str(name).strip())
        if description is not None:
            fields.append("description = ?")
            params.append(str(description))
        if is_active is not None:
            fields.append("is_active = ?")
            params.append(1 if is_active else 0)
        fields.append("updated_by = ?")
        params.append(str(actor or ""))
        fields.append("updated_at = ?")
        params.append(_now())
        params.append(cid)
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                f"UPDATE knowledge_categories SET {', '.join(fields)} WHERE category_id = ?", params
            )
        return self.get(cid)

    def delete(self, categoryId: str) -> bool:
        cid = normalizeCategoryId(categoryId)
        with self._store._lock, self._store._conn:
            cursor = self._store._conn.execute(
                "DELETE FROM knowledge_categories WHERE category_id = ?", (cid,)
            )
            deleted = cursor.rowcount > 0
        return deleted
