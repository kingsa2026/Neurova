# -*- coding: utf-8 -*-
"""P2-14 / P3-9（审计 2026-11-04）：脚本可移植性。

P2-14：expand_nsi_template.py 把输出目录与验证用假路径写死成
        C:\\Users\\xccoo\\...，任何非本机账户运行必挂，且 docstring
        自称 /tmp/nsis_verify 与实现不符。
P3-9：cnb_release_assets.py 用 `os.popen("git remote get-url cnb 2>nul")`，
        Windows 专用重定向，非 Windows 下静默取不到 remote。
"""
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]


def test_expandNsiTemplateHasNoMachineSpecificPaths():
    src = (_REPO / "scripts" / "desktop" / "expand_nsi_template.py").read_text(encoding="utf-8")
    assert "C:\\Users\\" not in src, "仍有写死本机账户的临时路径"
    assert "tempfile.gettempdir()" in src, "输出目录未走系统临时目录推导"


def test_cnbReleaseAssetsUsesCrossPlatformSubprocess():
    src = (_REPO / "scripts" / "desktop" / "cnb_release_assets.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
    assert "os.popen" not in code, "仍用 Windows 专用 2>nul 的 os.popen 取 remote"
    assert "subprocess.run" in code, "remote 读取未改走跨平台 subprocess"
