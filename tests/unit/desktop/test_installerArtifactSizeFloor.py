# -*- coding: utf-8 -*-
"""产物体积红线必须与「路线 B 不内嵌运行时」同向（beta6/beta7 缺校验和的根因）。

这条闸本意是防"NSIS 内核没被内嵌、壳成空壳"，但它写的是 beta4 时代
（内嵌 Python/Node，477 MB 量级）的读数 300 MiB。路线 B 切下去之后
（`package_installer_zip.py::validate_lean_backend` 明确禁止 backend/ 里出现
python/、node/），每一个**合法**产物都是 139 MiB 量级，于是这条闸把它自己
判成故障，`report_artifact` 直接抛——而它是仓内**唯一**产出 SHA256SUMS.txt
的地方。后果是发布物没有校验和：beta7 附件里就没有 sums，beta6 那份的格式
（sha 与文件名之间单空格）与本函数写的（双空格）不同，说明另有手工来源。
用户下载到一个 139 MB 的 exe，却没有任何可核对的哈希。

判据三条：阈值的定数依据、闸真的会拒空壳、合法量级能过并真的落盘 sums。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# 实测合法读数（路线 B）：beta6 138.9 MiB / beta8 139.0 MiB
LEAN_ARTIFACT_MIB = 138
# 空壳形态：只剩 WPF 壳（几 MB），留一个数量级的余量
SHELL_ONLY_MIB = 4


def _kit():
    spec = importlib.util.spec_from_file_location(
        "win_installer_kit", REPO / "scripts" / "desktop" / "win_installer_kit.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("win_installer_kit", module)
    spec.loader.exec_module(module)
    return module


def testFloorSitsBetweenShellOnlyAndLeanArtifact():
    """阈值要同时满足两头：合法包过得了，空壳过不了。"""
    kit = _kit()
    floor = kit.ARTIFACT_MIN_BYTES
    assert floor <= LEAN_ARTIFACT_MIB * 1024 * 1024, (
        f"下限 {floor / 1048576:.0f} MiB 高于实测合法读数 {LEAN_ARTIFACT_MIB} MiB——"
        "这条闸会把每一个合法的路线 B 包判成故障，sums 步骤永远跑不到")
    assert floor >= SHELL_ONLY_MIB * 1024 * 1024, (
        f"下限 {floor / 1048576:.0f} MiB 低到空壳也能过——闸失去意义")


def testReportRefusesShellSizedArtifact(tmp_path):
    kit = _kit()
    shell = tmp_path / "Neurova_Setup_9.9.9_x64_unsigned.exe"
    shell.write_bytes(b"MZ" + b"\0" * (8 * 1024 * 1024))       # 8 MiB：空壳量级

    try:
        kit.report_artifact(shell, "9.9.9")
    except RuntimeError as e:
        assert "偏小" in str(e)
    else:
        raise AssertionError("空壳量级的产物没被拒——这条闸不咬")
    assert not (tmp_path / "SHA256SUMS.txt").exists(), \
        "拒止态还把 sums 写了，等于告诉下游这包可信"


def testReportAcceptsLeanSizedArtifactAndWritesSums(tmp_path):
    """合法量级必须走到底并落 sums——beta6/beta7 缺校验和就是这一步从未执行。"""
    kit = _kit()
    lean = tmp_path / "Neurova_Setup_9.9.9_x64_unsigned.exe"
    with lean.open("wb") as fh:                                # 稀疏文件：只定尺寸不写满
        fh.write(b"MZ")
        fh.truncate(139 * 1024 * 1024)

    assert kit.report_artifact(lean, "9.9.9") == 0

    sums = (tmp_path / "SHA256SUMS.txt").read_text(encoding="ascii").strip()
    assert sums.endswith(lean.name), sums
    assert "  " in sums, "sums 用双空格分隔（与发布附件里那份手工版一致口径）"
