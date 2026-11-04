# -*- coding: utf-8 -*-
"""P3-6（审计 2026-11-04）：AppContainer profile 删除失败不得静默。

残留 profile 会让下次同名创建报错，形成「清理失败 → 创建失败」连锁，
而第一现场（删除失败原因）完全不可见。
"""
import logging

from neurova.sandbox import appcontainer as appcontainer_module


def test_deleteProfileFailureIsLogged(monkeypatch, caplog):
    class _FakeUserenv:
        @staticmethod
        def DeleteAppContainerProfile(name):
            raise OSError("access denied")

    monkeypatch.setattr(appcontainer_module._DLL, "userenv", _FakeUserenv, raising=False)
    sandbox = appcontainer_module.AppContainerSandbox()
    with caplog.at_level(logging.DEBUG, logger="neurova.sandbox.appcontainer"):
        sandbox._delete_profile("probe-profile")
    assert any("probe-profile" in str(r.getMessage()) for r in caplog.records), (
        "profile 删除失败无痕：残留原因不可见，后续同名创建只会再报一次错"
    )
