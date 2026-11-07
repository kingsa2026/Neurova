# -*- coding: utf-8 -*-
"""部门归属解析单源契约（specs/2026-11-07 批 B）。

红灯判据（设计 §2.3/§2.4）：
- 无部门组 → default/不受限（与今天行为一致）；
- 子组用户 tenant＝部门根，白名单＝路径并集（排序去重）；
- 路径全空白名单 → 不受限（restricted=False）；
- 白名单引用已停用/已删除分类 → 与注册表对表如实剔除，但**仍受限**（空列表 = 全不可见，
  不许静默 fail-open 成"什么都能看"）；
- 解析异常一律回落 default（不猜部门）；
- 登录身份声明带部门 tenant claim；无部门不签该 claim。
"""

import pytest

from neurova.auth.user_group_model import UserGroupManager, resolveUserDepartment


class _FakeRegistry:
    """测试用注册表替身：只暴露 list(activeOnly)。"""

    def __init__(self, active):
        self._active = list(active)

    def list(self, activeOnly=True):
        return [{"category_id": cid, "is_active": True} for cid in self._active]


def _mgr(tmp_path):
    return UserGroupManager(data_dir=str(tmp_path))


def testNoDeptFallsBackToDefault(tmp_path):
    mgr = _mgr(tmp_path)
    dept = resolveUserDepartment("nobody", manager=mgr, registry=_FakeRegistry([]))
    assert dept == {
        "tenant_id": "default",
        "group_id": None,
        "allowed_categories": [],
        "restricted": False,
    }


def testChildInheritsRootTenantAndUnionWhitelist(tmp_path):
    mgr = _mgr(tmp_path)
    root = mgr.create_group("研发中心", "", group_type="custom", allowed_categories=["rnd", "arch"])
    child = mgr.create_group(
        "前端组", "", group_type="custom", parent_group_id=root.group_id, allowed_categories=["frontend"]
    )
    mgr.add_user_to_group("alice", child.group_id)
    dept = resolveUserDepartment("alice", manager=mgr, registry=_FakeRegistry(["rnd", "arch", "frontend"]))
    assert dept["tenant_id"] == root.group_id
    assert dept["group_id"] == child.group_id
    # 路径并集：父共享（rnd/arch）＋子专属（frontend），排序去重
    assert dept["allowed_categories"] == ["arch", "frontend", "rnd"]
    assert dept["restricted"] is True


def testEmptyWhitelistOnPathMeansUnrestricted(tmp_path):
    mgr = _mgr(tmp_path)
    root = mgr.create_group("研发中心", "", group_type="custom")  # 未配置白名单
    child = mgr.create_group("前端组", "", group_type="custom", parent_group_id=root.group_id)
    mgr.add_user_to_group("alice", child.group_id)
    dept = resolveUserDepartment("alice", manager=mgr, registry=_FakeRegistry([]))
    assert dept["tenant_id"] == root.group_id
    assert dept["restricted"] is False
    assert dept["allowed_categories"] == []


def testStaleCategoryIdsFilteredButStayRestricted(tmp_path):
    mgr = _mgr(tmp_path)
    root = mgr.create_group("研发中心", "", group_type="custom", allowed_categories=["gone"])
    mgr.add_user_to_group("bob", root.group_id)
    # 注册表已无 gone（被删/停用）→ 对表剔除，但 restricted 保持 True（空列表 = 全不可见）
    dept = resolveUserDepartment("bob", manager=mgr, registry=_FakeRegistry([]))
    assert dept["restricted"] is True
    assert dept["allowed_categories"] == []


def testResolverNeverRaises(tmp_path):
    class _Boom:
        def get_groups_for_user(self, username):
            raise RuntimeError("boom")

    dept = resolveUserDepartment("x", manager=_Boom(), registry=_FakeRegistry([]))
    assert dept["tenant_id"] == "default"
    assert dept["restricted"] is False


def testLoginClaimsCarryDeptTenant(monkeypatch):
    from neurova.api.endpoints.auth import buildIdentityClaims

    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment",
        lambda username, **kw: {
            "tenant_id": "group_root",
            "group_id": "group_root",
            "allowed_categories": [],
            "restricted": False,
        },
    )
    claims = buildIdentityClaims({"id": 7, "username": "alice"})
    assert claims["tenant_id"] == "group_root"
    assert claims["sub"] == "7"
    assert claims["user_id"] == "7"


def testLoginClaimsOmitTenantWhenNoDept(monkeypatch):
    from neurova.api.endpoints.auth import buildIdentityClaims

    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment",
        lambda username, **kw: {
            "tenant_id": "default",
            "group_id": None,
            "allowed_categories": [],
            "restricted": False,
        },
    )
    claims = buildIdentityClaims({"id": 7, "username": "alice"})
    assert "tenant_id" not in claims
