# -*- coding: utf-8 -*-
"""沙箱后端必须实现完整接口——缺一个方法就是一台机器上的崩（T-16）。

## 病灶（2026-09-30 本机实证）

`code_sandbox.resolveBackend()` 无条件调 `platform_backend.enforced()`，
而 `AppContainerSandbox` **不继承 `ExecSandbox`**、也没实现 `enforced()`：

```
选中后端 = AppContainerSandbox | backend_name = appcontainer | 有 enforced 方法 = False
AttributeError: 'AppContainerSandbox' object has no attribute 'enforced'
```

`get_exec_sandbox(NETWORK_OFF)` 在这台 Windows 上正选到它，于是代码执行工具在
**装了 AppContainer API 的 Windows 机器上直接崩**，而 Linux CI 选不到这个后端 ⇒ 看不见。
这与 T-15 是同一病形：结果由机器决定，门禁却只在一台机器上跑。

## 判据取向

- 不做"给 AppContainer 补一个方法"就完事（那是修被点名的那一条链，教义第 5 条禁）：
  判据扫**所有**沙箱后端类，缺接口成员即红——下一个后端再漏也一样被拦；
- 后端集合按"定义了 `backend_name`"自动发现，不手抄类名清单（手抄的清单本身就是第二份事实源）；
- 正对照：造一个缺 `enforced` 的假后端，判据必须点出来（否则本守卫是空转的）。
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

from neurova.sandbox.appcontainer import AppContainerSandbox
from neurova.sandbox.exec_sandbox import SandboxSeverity

# 调用方（code_sandbox.resolveBackend / execute）实际用到的接口面
REQUIRED_MEMBERS = ("backend_name", "available", "enforced", "execute")


def discoverBackends() -> dict:
    """自动发现沙箱后端类：凡定义了 `backend_name` 的非抽象类都算。"""
    import neurova.sandbox as pkg

    found = {}
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            ns = importlib.import_module(f"neurova.sandbox.{mod.name}")
        except Exception:  # noqa: BLE001 - 可选依赖缺失的模块不参与本判据
            continue
        for _, obj in inspect.getmembers(ns, inspect.isclass):
            if obj.__module__.startswith("neurova.sandbox") and hasattr(obj, "backend_name"):
                found[obj.__name__] = obj
    return found


def missingMembers(cls) -> tuple:
    return tuple(m for m in REQUIRED_MEMBERS if not callable(getattr(cls, m, None)))


class TestBackendInterfaceContract:
    def test_discoveryIsNotEmpty(self):
        """前提对照：自动发现必须真找到东西，否则整条判据在空转。"""
        assert len(discoverBackends()) >= 2, discoverBackends()

    def test_everyBackendImplementsTheContract(self):
        gaps = {
            name: missingMembers(cls)
            for name, cls in discoverBackends().items()
            if missingMembers(cls)
        }
        assert not gaps, (
            f"沙箱后端缺接口成员 {gaps}——调用方无条件调用它们，"
            "选到该后端的机器会直接崩"
        )

    def test_incompleteBackendIsDetected(self):
        """正对照：判据必须能咬住一个漏方法的后端。

        刻意**不继承** `ExecSandbox`——真实故障就是这个形状（AppContainer/RestrictedToken
        都是独立类，靠鸭子类型冒充接口）；继承基类的话 `enforced` 会自动拿到，
        那条对照就成了摆设。
        """

        class _HalfBaked:
            def backend_name(self) -> str:  # noqa: D102
                return "halfbaked"

            def available(self) -> bool:  # noqa: D102
                return True

            def execute(self, command, timeout=30.0, cwd=None, env=None):  # noqa: D102
                return {}

            # 故意漏掉 enforced

        assert missingMembers(_HalfBaked) == ("enforced",)

    def test_appContainerEnforcedReflectsItsOwnFacts(self):
        """补齐的那条不能是恒真：未声称档位时必须 False。"""
        assert isinstance(
            AppContainerSandbox(severity=SandboxSeverity.NETWORK_OFF).enforced(), bool)
        assert AppContainerSandbox().enforced() is False, (
            "severity 未指定却声称已隔离 = 把未知说成事实"
        )
