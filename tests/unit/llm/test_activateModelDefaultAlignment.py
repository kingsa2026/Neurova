# -*- coding: utf-8 -*-
"""激活模型读/写不对称回归（用户报障：保存成功，刷新后系统默认模型显示不是保存的结果）。

根因（修复前）：`activate_model(provider_id, model_id)` 只改被指名 provider 的
`default_model`，而读回 `get_active_model()` 走 `get_default_provider()`——
`_default_provider_id` 指向别的 provider（或未设时回落"第一个 enabled"）时，
读回的是**另一个 provider** 的默认模型。写与读各执一半，合起来失效。

判据（读写对称）：激活的模型在哪个 provider，系统默认就该读回哪一对
(provider, model)——`activate_model` 后 `get_active_model()` 必须逐值等于
刚保存的二元组；跨进程（落盘→新实例读回）同样成立。
"""

import pytest

from neurova.llm.provider_manager import get_provider_manager


@pytest.fixture
def manager(tmp_path):
    reset = getattr(__import__("neurova.llm.provider_manager", fromlist=["reset_provider_manager"]),
                    "reset_provider_manager")
    reset()
    mgr = get_provider_manager(config_path=str(tmp_path / "providers.json"))
    yield mgr
    reset()


def _two_providers(mgr):
    """A 排第一且是当前默认；B 是另一个 enabled provider。"""
    a = mgr.add_provider(name="Alpha", provider="openai", base_url="https://a.example",
                         default_model="a-base", models=["a-base", "a-alt"])
    b = mgr.add_provider(name="Beta", provider="openai", base_url="https://b.example",
                         default_model="b-base", models=["b-base", "b-alt"])
    # 默认 provider 显式钉 A（get_default_provider 的第一分支）
    mgr.set_default_provider(a.id)
    return a, b


class TestActivateModelReadWriteSymmetry:
    def test_activate_on_non_default_provider_reads_back_the_saved_pair(self, manager):
        """红灯判据本体：在非默认 provider 上激活 → 读回必须是刚保存的那对。"""
        a, b = _two_providers(manager)
        assert manager.get_active_model()["model"] == "a-base"

        assert manager.activate_model(b.id, "b-alt") is True

        active = manager.get_active_model()
        assert active["provider_id"] == b.id, (
            f"激活落在 {b.id}，读回却是 {active['provider_id']}——读/写各执一半")
        assert active["model"] == "b-alt", (
            f"保存的是 b-alt，读回却是 {active['model']}——保存成功但显示不对（用户报障形态）")

    def test_activate_on_default_provider_still_reads_back(self, manager):
        """默认 provider 上激活：行为保持（读回同 provider 的新模型）。"""
        a, _b = _two_providers(manager)
        assert manager.activate_model(a.id, "a-alt") is True
        active = manager.get_active_model()
        assert active["provider_id"] == a.id
        assert active["model"] == "a-alt"

    def test_no_default_set_falls_back_then_activation_fixes_it(self, manager):
        """未设默认（回落第一个 enabled）时激活第二个 provider：读回跟随激活。"""
        mgr = manager
        a = mgr.add_provider(name="Alpha", provider="openai", base_url="https://a.example",
                             default_model="a-base", models=["a-base"])
        b = mgr.add_provider(name="Beta", provider="openai", base_url="https://b.example",
                             default_model="b-base", models=["b-base", "b-alt"])
        assert mgr._default_provider_id is None
        # manager 装载内置预设 provider——回落分支取的是**全部** provider 里
        # 第一个 enabled（不保证是测试新加的），期望值从 list_providers 现取。
        fallback = mgr.list_providers(enabled_only=True)[0]
        assert mgr.get_active_model()["model"] == fallback.default_model

        assert mgr.activate_model(b.id, "b-alt") is True
        active = mgr.get_active_model()
        assert active["provider_id"] == b.id and active["model"] == "b-alt"

    def test_activation_survives_process_restart(self, manager, tmp_path):
        """跨进程对称：落盘后新实例读回同一对（刷新页面＝新读回，重启＝新实例）。"""
        _a, b = _two_providers(manager)
        assert manager.activate_model(b.id, "b-alt") is True

        from neurova.llm import provider_manager as pm_module

        fresh = pm_module.LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
        active = fresh.get_active_model()
        assert active["provider_id"] == b.id
        assert active["model"] == "b-alt", (
            f"落盘后读回 {active}——持久化面丢了激活结果")

    def test_set_default_provider_semantics_preserved(self, manager):
        """放大视角反证：显式设默认 provider 的既有能力不被本修复抹掉。"""
        a, b = _two_providers(manager)
        manager.activate_model(b.id, "b-alt")
        manager.set_default_provider(a.id)
        active = manager.get_active_model()
        assert active["provider_id"] == a.id
        assert active["model"] == "a-base"  # A 的默认模型未被动过
