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

2026-11-14 二次断流（同链新形态）：kai 的 owner_user_id="1" 指向的用户行已从
users.db 删除（enhanced-users 迁移误删陈旧行），角色判定查无此人 → 按普通用户
落 `user:1` scope → providers.user-1.json 十一个服务商**全无 key** → kai 每轮
"No client available"，并把 nex-n2.6 的失败喂进让位闸自适应节流（成功率 0% →
全部回合"并发额度让位中"重试 10 次后挂起）。根修：悬空 owner（查无此人）与
空 owner 同落点——回落全局；"库不可达"维持走窄不变。
"""
from __future__ import annotations

import pytest

from neurova.llm import multi_model_client as mm


@pytest.fixture()
def owner_lookup(monkeypatch):
    """替换 owner 探针（单元层面不摸真用户库），可钉 admin/normal/missing。"""
    holder = {"state": "normal"}

    def _set(state: str):
        holder["state"] = state

    monkeypatch.setattr(mm, "_ownerLookupState", lambda uid: holder["state"])
    return _set


class TestScopeForOwnerAdminFallback:
    def test_admin_owner_uses_global_scope(self, owner_lookup):
        owner_lookup("admin")
        assert mm.scope_for_owner("1") is None, (
            "admin 名下 agent 被切到 user scope＝拿不到管理员配置的服务商")

    def test_normal_owner_keeps_user_scope(self, owner_lookup):
        owner_lookup("normal")
        assert mm.scope_for_owner("7") == "user:7", "普通用户的隔离语义被破坏"

    def test_dangling_owner_uses_global_scope(self, owner_lookup):
        owner_lookup("missing")
        assert mm.scope_for_owner("1") is None, (
            "悬空 owner 被切到 user scope＝恒空注册表，agent 永远 No client available")

    def test_empty_owner_still_global(self, owner_lookup):
        owner_lookup("normal")
        assert mm.scope_for_owner("") is None
        assert mm.scope_for_owner(None) is None

    def test_lookup_failure_falls_back_to_user_scope(self, monkeypatch):
        """用户库不可达＝判不了角色＝按普通用户走 user scope（fail-soft 不越权）。
        打在取数口（_ownerUserModel）上，测真实故障层。"""
        def _boom():
            raise RuntimeError("users db unavailable")

        monkeypatch.setattr(mm, "_ownerUserModel", _boom)
        assert mm.scope_for_owner("1") == "user:1"

    def test_dangling_owner_falls_back_to_global(self, monkeypatch):
        """owner 指向已删除用户（查无此人）→ 回落全局 scope。

        user scope 对一个不存在的用户**永远是空注册表**（该用户不可能配过
        key）——悬空引用判成普通用户＝agent 恒 "No client available"。
        2026-11-14 kai 实测：owner_user_id="1" 的用户行已删，
        providers.user-1.json 十一个服务商全无 key，kai 每轮 chat_error，
        并把 nex-n2.6 的失败喂进让位闸自适应节流（成功率 0% → 全部回合
        "并发额度让位中" 重试 10 次后挂起）。空 owner 本就回落全局
        （scope_for_owner(None) → None），悬空 owner 与空 owner 同属
        "没有可归属的在册用户"，同一落点。
        """
        class _Stub:
            def get_user_by_id(self, uid):
                return None

        monkeypatch.setattr(mm, "_ownerUserModel", lambda: _Stub())
        assert mm.scope_for_owner("1") is None, (
            "悬空 owner 落 user scope＝恒空注册表，agent 永远 No client available")


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
