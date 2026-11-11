# -*- coding: utf-8 -*-
"""owner→scope 策略的 admin 回退（kai "No client available" 根修）。

病灶时间线（2026-11-12 实测）：部门迁移把 kai 归属给用户 1（kingsa，admin）→
`scope_for_owner("1")` 切到 `user:1` scope → 独立 provider 注册表
（providers.user-1.json）不含 kai 配置的上海人工智能实验室、无任何有 key 的
服务商 → 三条解析路径（注册表/懒加载/兜底）全空 → kai 每轮对话
"No client available"。kai 在归属变更前（11-10）对话正常——归属切换就是断点。

策略依据：`get_provider_manager_for_user` 已有同一不对称——admin 角色一律走
全局 admin scope（管理员在模型管理页配的服务商写的就是全局注册表）。owner→scope
映射应对齐该策略：admin 名下的 agent 用全局，普通用户名下保持 user 隔离。
角色判定 fail-soft：用户库不可达时按普通用户处理（保持既有隔离语义，宁可
走窄不越权）。
"""
from __future__ import annotations

import pytest

from neurova.llm import multi_model_client as mm


@pytest.fixture()
def owner_lookup(monkeypatch):
    """替换 owner 角色判定（单元层面不摸真用户库）。"""
    state = {"admin": False}

    def _set(is_admin: bool):
        state["admin"] = is_admin

    monkeypatch.setattr(mm, "_ownerIsAdmin", lambda uid: state["admin"])
    return _set


class TestScopeForOwnerAdminFallback:
    def test_admin_owner_uses_global_scope(self, owner_lookup):
        owner_lookup(True)
        assert mm.scope_for_owner("1") is None, (
            "admin 名下 agent 被切到 user scope＝拿不到管理员配置的服务商")

    def test_normal_owner_keeps_user_scope(self, owner_lookup):
        owner_lookup(False)
        assert mm.scope_for_owner("7") == "user:7", "普通用户的隔离语义被破坏"

    def test_empty_owner_still_global(self, owner_lookup):
        owner_lookup(False)
        assert mm.scope_for_owner("") is None
        assert mm.scope_for_owner(None) is None

    def test_lookup_failure_falls_back_to_user_scope(self, monkeypatch):
        """用户库不可达＝判不了角色＝按普通用户走 user scope（fail-soft 不越权）。
        打在取数口（_ownerUserModel）上，测真实故障层。"""
        def _boom():
            raise RuntimeError("users db unavailable")

        monkeypatch.setattr(mm, "_ownerUserModel", _boom)
        assert mm.scope_for_owner("1") == "user:1"


class TestOwnerIsAdminProbe:
    """角色探针自身的边界：非数字 id、查无此人、库异常都不得抛。"""

    def test_non_numeric_id_is_not_admin(self):
        assert mm._ownerIsAdmin("not-a-number") is False

    def test_missing_user_is_not_admin(self, monkeypatch):
        from neurova.auth.user_model import UserModel

        class _Stub:
            def get_user_by_id(self, uid):
                return None

        monkeypatch.setattr(mm, "_ownerUserModel", lambda: _Stub())
        assert mm._ownerIsAdmin("999") is False

    def test_admin_role_detected(self, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            mm, "_ownerUserModel",
            lambda: SimpleNamespace(get_user_by_id=lambda uid: SimpleNamespace(role="admin")))
        assert mm._ownerIsAdmin("1") is True
