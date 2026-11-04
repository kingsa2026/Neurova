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


def test_existingProfileIsReusedInsteadOfFailing(monkeypatch, caplog):
    """P3-6：清理残留的同名 profile 命中 ERROR_ALREADY_EXISTS 时派生 SID 复用。"""

    class _FakeUserenv:
        @staticmethod
        def CreateAppContainerProfile(*args):
            return 0x800700B7

        @staticmethod
        def DeriveAppContainerSidFromAppContainerName(name, psid_ptr):
            psid_ptr._obj.value = 0x1234
            return 0

    monkeypatch.setattr(appcontainer_module._DLL, "userenv", _FakeUserenv, raising=False)
    sandbox = appcontainer_module.AppContainerSandbox()
    with caplog.at_level(logging.DEBUG, logger="neurova.sandbox.appcontainer"):
        name, psid = sandbox._create_profile_fresh()
    assert psid == 0x1234, "已存在 profile 的 SID 没有被复用"
    assert any("复用已存在" in str(r.getMessage()) for r in caplog.records)
