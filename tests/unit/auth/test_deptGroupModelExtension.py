# -*- coding: utf-8 -*-
"""用户分组部门化模型扩展契约（specs/2026-11-07 批 A）。

红灯判据（设计 §4 批 A）：
- `UserGroup` 新字段（parent_group_id/allowed_categories/default_category）持久化往返；
- 层级禁环（自指/两环）与"层级只挂在 custom（部门）组之间"；
- 单主组校验（一个用户至多属于一个 custom 部门组；系统组不受限）；
- 死端点 `/v1/user-groups` 退役（模块删除＋注册表摘除）。
"""

import importlib

import pytest

from neurova.auth.user_group_model import UserGroup, UserGroupType


def _tmp_manager(tmp_path):
    from neurova.auth.user_group_model import UserGroupManager

    return UserGroupManager(data_dir=str(tmp_path))


def testUserGroupNewFieldsRoundTrip():
    group = UserGroup(
        group_id="g1",
        name="研发",
        description="",
        group_type=UserGroupType.CUSTOM,
        permissions=[],
        resource_quota=None,
        parent_group_id="root",
        allowed_categories=["rnd", "arch"],
        default_category="rnd",
    )
    data = group.to_dict()
    assert data["parent_group_id"] == "root"
    assert data["allowed_categories"] == ["rnd", "arch"]
    assert data["default_category"] == "rnd"
    restored = UserGroup.from_dict(data)
    assert restored.parent_group_id == "root"
    assert restored.allowed_categories == ["rnd", "arch"]
    assert restored.default_category == "rnd"


def testUserGroupLegacyDictWithoutNewFieldsNormalizes():
    restored = UserGroup.from_dict(
        {"group_id": "g1", "name": "旧组", "description": "", "group_type": "custom", "permissions": []}
    )
    assert restored.allowed_categories == []
    assert restored.parent_group_id is None
    assert restored.default_category is None


def testParentCycleRejected(tmp_path):
    mgr = _tmp_manager(tmp_path)
    root = mgr.create_group("研发中心", "", group_type="custom")
    child = mgr.create_group("前端组", "", group_type="custom", parent_group_id=root.group_id)
    assert child.parent_group_id == root.group_id
    # 两环：把根的父设为子 → 拒绝
    with pytest.raises(ValueError):
        mgr.set_parent_group(root.group_id, child.group_id)
    # 自指：拒绝
    with pytest.raises(ValueError):
        mgr.set_parent_group(root.group_id, root.group_id)


def testParentMustBeCustomAndExist(tmp_path):
    mgr = _tmp_manager(tmp_path)
    dev = mgr.create_group("研发", "", group_type="custom")
    with pytest.raises(ValueError):
        mgr.set_parent_group(dev.group_id, "group_not_exists")
    # 系统组不能当父（部门层级只在 custom 组之间）
    admin_group = mgr.get_group_by_type(UserGroupType.ADMIN)
    with pytest.raises(ValueError):
        mgr.set_parent_group(dev.group_id, admin_group.group_id)
    # 系统组自身不能挂父
    with pytest.raises(ValueError):
        mgr.set_parent_group(admin_group.group_id, dev.group_id)


def testDetachParentAllowed(tmp_path):
    mgr = _tmp_manager(tmp_path)
    root = mgr.create_group("研发中心", "", group_type="custom")
    child = mgr.create_group("前端组", "", group_type="custom", parent_group_id=root.group_id)
    mgr.set_parent_group(child.group_id, None)
    assert child.parent_group_id is None


def testSinglePrimaryGroupEnforced(tmp_path):
    mgr = _tmp_manager(tmp_path)
    dept_a = mgr.create_group("研发部", "", group_type="custom")
    dept_b = mgr.create_group("客服部", "", group_type="custom")
    assert mgr.add_user_to_group("alice", dept_a.group_id) is True
    # 已在部门 A，加入部门 B → 拒绝（T-A 单主组）
    with pytest.raises(ValueError):
        mgr.add_user_to_group("alice", dept_b.group_id)
    # 同组重复添加幂等不受影响
    assert mgr.add_user_to_group("alice", dept_a.group_id) is True
    # 系统组不受单主组限制
    user_group = mgr.get_group_by_type(UserGroupType.USER)
    assert mgr.add_user_to_group("alice", user_group.group_id) is True


def testGroupCreateWithDeptFieldsPersists(tmp_path):
    mgr = _tmp_manager(tmp_path)
    root = mgr.create_group(
        "研发中心",
        "部门根",
        group_type="custom",
        allowed_categories=["RnD", "arch"],
        default_category="rnd",
    )
    reloaded_mgr = type(mgr)(data_dir=mgr.data_dir and str(mgr.data_dir))
    restored = reloaded_mgr.get_group(root.group_id)
    # 白名单标识与注册表同规（小写规范化）
    assert restored.allowed_categories == ["rnd", "arch"]
    assert restored.default_category == "rnd"
    assert restored.parent_group_id is None


def testDeadUserGroupsEndpointRetired():
    # 死面模块已删除（内存 dict 假组，零消费方，教义第 6 条收口）
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("neurova.api.endpoints.user_group_api")
    from neurova.api.endpoints import ENDPOINT_MODULES

    assert all("user_group_api" not in entry[0] for entry in ENDPOINT_MODULES)
