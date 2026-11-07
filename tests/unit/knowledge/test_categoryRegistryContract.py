# -*- coding: utf-8 -*-
"""分类注册表契约（specs/2026-11-07 批 A）：自定义分类的受控清单，单一事实源。

红灯判据（设计 §4 批 A）：
- 注册表 CRUD 语义（标识规范化小写、重复拒绝、停用过滤、删除）；
- foundation v38 迁移建表（:memory: 真库链路，与事实/本体同域）。
"""

import pytest

from neurova.knowledge.categories_registry import CategoryRegistry, normalizeCategoryId
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


def _registry() -> CategoryRegistry:
    return CategoryRegistry(KnowledgeFactStore(":memory:"))


def testCategoryCreateAndListRoundTrip():
    reg = _registry()
    reg.create(categoryId="RnD", name="研发文档", actor="admin")
    reg.create(categoryId="support", name="客服文档", actor="admin")
    ids = [c["category_id"] for c in reg.list()]
    # 标识规范化为小写，列表按 id 排序
    assert ids == ["rnd", "support"]


def testCategoryDuplicateRejected():
    reg = _registry()
    reg.create(categoryId="rnd", name="研发文档", actor="admin")
    with pytest.raises(ValueError):
        reg.create(categoryId="RND", name="重复标识", actor="admin")


def testCategoryDeactivateFiltersFromActiveListing():
    reg = _registry()
    reg.create(categoryId="rnd", name="研发文档", actor="admin")
    reg.update(categoryId="rnd", is_active=False, actor="admin")
    # 停用后活跃清单不含（白名单解析据此如实剔除）
    assert [c["category_id"] for c in reg.list()] == []
    assert [c["category_id"] for c in reg.list(activeOnly=False)] == ["rnd"]


def testCategoryDeleteRemovesRow():
    reg = _registry()
    reg.create(categoryId="rnd", name="研发文档", actor="admin")
    assert reg.delete("rnd") is True
    assert reg.get("rnd") is None
    assert reg.delete("rnd") is False


def testCategoryUpdateFields():
    reg = _registry()
    reg.create(categoryId="rnd", name="研发文档", description="研发部门知识", actor="admin")
    updated = reg.update(categoryId="rnd", name="研发知识库", description="新描述", actor="admin2")
    assert updated["name"] == "研发知识库"
    assert updated["description"] == "新描述"
    assert updated["updated_by"] == "admin2"
    # 更新不存在的分类 → 拒绝
    with pytest.raises(ValueError):
        reg.update(categoryId="missing", name="x", actor="admin")


def testCategoryIdNormalization():
    assert normalizeCategoryId("  RnD ") == "rnd"
    assert normalizeCategoryId("") == ""
    reg = _registry()
    with pytest.raises(ValueError):
        reg.create(categoryId="  ", name="空标识", actor="admin")
    with pytest.raises(ValueError):
        reg.create(categoryId="ok", name=" ", actor="admin")
