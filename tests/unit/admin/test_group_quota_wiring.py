# -*- coding: utf-8 -*-
"""组级 ResourceQuota 接通资源判额闸（2026-11-14）。

此前 user_group_model 的组级 ResourceQuota 与 enhanced_user_model 的按用户
配额都**不连通**判额闸——LLM 闸只读 resource_quota_manager 的硬编码默认/
运营设置。本批：组级配额作为**最具体的额度事实**接进 get_user_quota 的
覆盖链（硬编码默认 < 运营设置 < custom_limits < group_limits < 用户所属组），
同时退役 enhanced_user_model 的按用户配额（零消费死面）。

组解析口径与 resolveUserDepartment 同源：组员名册按 username 记账，取该
用户的 **CUSTOM 主组**（T-A 单主组），沿 parent_group_id 向部门根取
**第一个非默认**配额（子组覆盖、未配置继承父组）。
"""
import pytest

from neurova.admin.resource_quota_manager import ResourceQuotaManager
from neurova.auth.user_group_model import ResourceQuota, UserGroupManager


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """隔离组树 + 配额管理器；user_id→username 的身份缝钉成 3→admin。"""
    groups = UserGroupManager(str(tmp_path / "groups"))
    import neurova.auth.user_group_model as ugm

    monkeypatch.setattr(ugm, "get_user_group_manager", lambda: groups)
    import neurova.admin.resource_quota_manager as rqm

    monkeypatch.setattr(
        rqm, "_username_for_user", lambda user_id: "admin" if str(user_id) == "3" else None
    )
    mgr = ResourceQuotaManager(str(tmp_path / "quota"))
    return mgr, groups


class TestGroupQuotaWiring:
    def test_group_quota_overrides_calls_and_tokens(self, wired):
        mgr, groups = wired
        g = groups.create_group(
            name="研发部",
            description="d",
            resource_quota=ResourceQuota(max_llm_calls_per_day=7, max_tokens_per_day=7777),
        )
        groups.add_user_to_group("admin", g.group_id)
        q = mgr.get_user_quota("3")
        assert q["max_llm_calls_per_day"] == 7
        assert q["max_llm_tokens_per_day"] == 7777
        assert mgr.check_llm_call_quota("3")["limit"] == 7

    def test_child_group_wins_over_parent(self, wired):
        mgr, groups = wired
        parent = groups.create_group(
            name="总部", description="d", resource_quota=ResourceQuota(max_llm_calls_per_day=50)
        )
        child = groups.create_group(
            name="子部门",
            description="d",
            parent_group_id=parent.group_id,
            resource_quota=ResourceQuota(max_llm_calls_per_day=7),
        )
        groups.add_user_to_group("admin", child.group_id)
        assert mgr.get_user_quota("3")["max_llm_calls_per_day"] == 7

    def test_parent_quota_inherited_when_child_default(self, wired):
        mgr, groups = wired
        parent = groups.create_group(
            name="总部", description="d", resource_quota=ResourceQuota(max_llm_calls_per_day=50)
        )
        child = groups.create_group(
            name="子部门", description="d", parent_group_id=parent.group_id
        )
        groups.add_user_to_group("admin", child.group_id)
        assert mgr.get_user_quota("3")["max_llm_calls_per_day"] == 50

    def test_user_without_group_uses_defaults(self, wired):
        mgr, _ = wired
        assert mgr.get_user_quota("3")["max_llm_calls_per_day"] == 100

    def test_non_numeric_user_id_fail_soft(self, wired):
        mgr, _ = wired
        assert mgr.get_user_quota("anonymous")["max_llm_calls_per_day"] == 100

    def test_group_beats_app_settings(self, wired, monkeypatch):
        from neurova.core import app_settings as APPS

        monkeypatch.setattr(
            APPS,
            "get_quota_settings",
            lambda path=None: {**APPS.QUOTA_DEFAULTS, "max_llm_calls_per_day": 500},
        )
        mgr, groups = wired
        g = groups.create_group(
            name="研发部", description="d", resource_quota=ResourceQuota(max_llm_calls_per_day=7)
        )
        groups.add_user_to_group("admin", g.group_id)
        assert mgr.get_user_quota("3")["max_llm_calls_per_day"] == 7

    def test_storage_mb_maps_to_bytes(self, wired):
        mgr, groups = wired
        g = groups.create_group(
            name="研发部", description="d", resource_quota=ResourceQuota(max_storage_mb=1)
        )
        groups.add_user_to_group("admin", g.group_id)
        assert mgr.get_user_quota("3")["max_storage_bytes"] == 1024 * 1024

    def test_enhanced_user_model_quota_retired(self):
        """按用户配额是零消费死面（判额闸只认 resource_quota_manager）——退役。"""
        from neurova.auth.enhanced_user_model import EnhancedUserModel

        for method in ("get_user_quota", "get_user_usage", "get_user_quota_status", "_build_quota"):
            assert not hasattr(EnhancedUserModel, method), f"{method} 应已退役"
