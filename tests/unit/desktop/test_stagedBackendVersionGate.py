# -*- coding: utf-8 -*-
"""出包这一步必须核对内嵌后端的自陈版本（beta8 出包实测的坑）。

断裂形态（不是假设，是这一次真实发生的）：源码四处版本已经升到 beta8，
`resources/backend/` 那份副本还停在 beta7 —— 因为那份是 `bundle_backend.py`
单独一步灌进去的，与 `package_installer_zip.py` 之间没有任何咬合。
包名取自 NSIS 内核文件名（源头 tauri.conf.json），于是产物叫
`Neurova_Setup_1.0.0-beta8_*.exe`，装上后 `/health` 自报 beta7。
整条链一句错都不报：构建 exit 0、体积红线过、文件名对、界面正常。

所以判据只能长在"出包"这一步，且必须能红：本档同时验放行态与拒止态，
拒止态用临时文件造，不去动仓内真 staging。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
STAGED_INIT = REPO / "NeurUI" / "src-tauri" / "resources" / "backend" / "neurova" / "__init__.py"


def _pkg():
    spec = importlib.util.spec_from_file_location(
        "package_installer_zip", REPO / "scripts" / "desktop" / "package_installer_zip.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("package_installer_zip", module)
    spec.loader.exec_module(module)
    return module


def testGateExistsAndIsCalledByPackaging():
    """判据得真长在出包流程里，不是摆在旁边等人自觉调。"""
    pkg = _pkg()
    assert hasattr(pkg, "validate_staged_backend_version"), "出包链没有版本核对这道闸"
    source = (REPO / "scripts" / "desktop" / "package_installer_zip.py").read_text(
        encoding="utf-8")
    assert "validate_staged_backend_version(ver)" in source, (
        "函数写了但没被 package() 调用——等于没有判据"
    )


def testStagedBackendAgreesWithDeclaredVersion():
    """仓内现态：staged 自陈版本 == tauri.conf.json 的版本事实源。"""
    import json

    pkg = _pkg()
    declared = json.loads(
        (REPO / "NeurUI" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    assert STAGED_INIT.is_file(), f"内嵌后端缺席：{STAGED_INIT}"
    pkg.validate_staged_backend_version(declared)  # 不符即抛


def testStaleStagingIsRefused(tmp_path):
    """拒止态：staged 比包名旧一格就必须抛，且把补救动作写进错误里。"""
    pkg = _pkg()
    stale = tmp_path / "__init__.py"
    stale.write_text('__version__ = "1.0.0-beta0"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="bundle_backend"):
        pkg.validate_staged_backend_version("1.0.0-beta9", initPath=stale)


def testMissingStagingIsRefused(tmp_path):
    pkg = _pkg()
    with pytest.raises(RuntimeError, match="内嵌后端缺席"):
        pkg.validate_staged_backend_version("1.0.0-beta9",
                                            initPath=tmp_path / "absent" / "__init__.py")
