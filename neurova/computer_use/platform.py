"""桌面平台探测与三平台后端可用性（AD-6 单一事实源）。

Windows=UIA（已实证）；macOS=AX（预留骨架）；Linux=AT-SPI（预留骨架）。
对齐 agent-desktop 的 PlatformAdapter 思路：平台差异收拢到探测/选择一处，
manager 与治理面只读本模块的三态结果，不自判平台。
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, Dict


def desktopPlatform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _probe(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:  # noqa: BLE001 — 缺库/平台不符都是读数，不是崩溃
        return False


def _state(available: bool, platform: str, reason: str) -> Dict[str, Any]:
    from neurova.computer_use.capability_state import CAP_AVAILABLE, CAP_NOT_CONFIGURED

    return {
        "available": bool(available),
        "state": CAP_AVAILABLE if available else CAP_NOT_CONFIGURED,
        "platform": platform,
        "reason": reason,
    }


def desktopBackendAvailability() -> Dict[str, Dict[str, Any]]:
    """三平台桌面语义后端三态（available/not_configured + 具名原因）。

    预留平台（macOS AX / Linux AT-SPI）即便依赖库存在也如实报 not_configured——
    后端实现未落地（AD-6 骨架），不得因「库可导入」谎称可用。
    """
    platform = desktopPlatform()
    return {
        "windows": _windows_state(platform == "windows"),
        "macos": _macos_state(platform == "macos"),
        "linux": _linux_state(platform == "linux"),
    }


def _windows_state(on_platform: bool) -> Dict[str, Any]:
    if not on_platform:
        return _state(False, "windows",
                      "Windows UIA 后端仅在 Windows 平台有意义（当前平台非 windows）")
    if _probe("uiautomation"):
        return _state(True, "windows", "uiautomation 可导入且平台匹配")
    return _state(False, "windows", "缺 uiautomation 库：pip install uiautomation")


def _macos_state(on_platform: bool) -> Dict[str, Any]:
    if not on_platform:
        return _state(False, "macos",
                      "macOS AX 后端仅在 macOS 平台有意义（当前平台非 macos）")
    if not _probe("ApplicationServices"):
        return _state(False, "macos",
                      "macOS AX 后端为预留骨架（AD-6）：缺 pyobjc-framework-ApplicationServices；"
                      "真机适配待三平台批次（档 C）")
    return _state(False, "macos",
                  "macOS AX 后端为预留骨架（AD-6）：依赖可导入但实现未落地，待三平台批次")


def _linux_state(on_platform: bool) -> Dict[str, Any]:
    if not on_platform:
        return _state(False, "linux",
                      "Linux AT-SPI 后端仅在 Linux 平台有意义（当前平台非 linux）")
    if not _probe("pyatspi"):
        return _state(False, "linux",
                      "Linux AT-SPI 后端为预留骨架（AD-6）：缺 pyatspi；"
                      "真机适配待三平台批次（档 C）")
    return _state(False, "linux",
                  "Linux AT-SPI 后端为预留骨架（AD-6）：依赖可导入但实现未落地，待三平台批次")
