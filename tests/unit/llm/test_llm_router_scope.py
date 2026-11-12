# -*- coding: utf-8 -*-
"""P1-15 llm_router 作用域选型红测（全库断点审计 2026-11-12）。

缺陷：select_model_for_request/sync_llm_router 只同步全局 admin 注册表
（get_provider_manager 无参＝admin scope）——普通用户 agent 的多模态路由
看不见自己的 provider，静默兜底回当前模型。

修复口径（审计开方）：两函数加 scope 参数（按 get_provider_manager(scope)
同策略取表），agent_core 传 owner scope（scope_for_owner）；候选空再回全局。
"""
from types import SimpleNamespace

import pytest

from neurova.llm import llm_router
from neurova.llm.llm_router import RequestType, select_model_for_request

ADMIN_MODEL = "gpt-test-vision"
USER_MODEL = "my-vision-model"


def _conf(name, models):
    return SimpleNamespace(name=name, models=models, model_metadata={})


@pytest.fixture
def reset_router():
    router = llm_router.get_llm_router()
    router._providers.clear()
    llm_router._synced_scopes = {"admin"}
    yield
    router._providers.clear()
    llm_router._synced_scopes = {"admin"}


def _patch_managers(monkeypatch, admin_providers, user_providers):
    import neurova.llm.provider_manager as pm

    admin_mgr = SimpleNamespace(_providers=admin_providers)
    user_mgr = SimpleNamespace(_providers=user_providers)
    monkeypatch.setattr(
        pm, "get_provider_manager",
        lambda scope=None, config_path=None: (
            user_mgr if (scope or "").startswith("user:") else admin_mgr
        ),
    )
    return admin_mgr, user_mgr


class TestScopedModelSelection:
    def test_user_scope_provider_visible(self, monkeypatch, reset_router):
        _patch_managers(
            monkeypatch,
            {"openai": _conf("OpenAI", [ADMIN_MODEL])},
            {"myprov": _conf("MyProv", [USER_MODEL])},
        )
        got = select_model_for_request(RequestType.IMAGE_UNDERSTANDING, scope="user:u1")
        assert got is not None and got.model == USER_MODEL, (
            "普通用户 agent 的多模态路由必须看得见自己域内的 provider"
        )

    def test_empty_user_scope_falls_back_to_global(self, monkeypatch, reset_router):
        _patch_managers(
            monkeypatch,
            {"openai": _conf("OpenAI", [ADMIN_MODEL])},
            {},  # 用户域没配任何 provider
        )
        got = select_model_for_request(RequestType.IMAGE_UNDERSTANDING, scope="user:u1")
        assert got is not None and got.model == ADMIN_MODEL, "候选空必须回全局兜底"

    def test_default_no_scope_uses_global(self, monkeypatch, reset_router):
        _patch_managers(
            monkeypatch,
            {"openai": _conf("OpenAI", [ADMIN_MODEL])},
            {"myprov": _conf("MyProv", [USER_MODEL])},
        )
        got = select_model_for_request(RequestType.IMAGE_UNDERSTANDING)
        assert got is not None and got.model == ADMIN_MODEL, "缺省（无 scope）保持全局表存量行为"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
