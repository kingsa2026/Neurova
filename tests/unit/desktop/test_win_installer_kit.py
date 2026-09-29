# -*- coding: utf-8 -*-
"""打包机一键上机包的契约守卫（Issue #332）。

**为什么要有本守卫（这一轮实测到的真实死链）**：
自定义界面壳是 WPF(net48)，`csc.exe` 与 `robocopy` 是 Windows 自带件，
WPF 不是可交叉编译的 native 目标 —— 容器里加什么工具链都补不上这两个。
于是「怎么在一台 Windows 机器上从零出包」这件事，此前**只存在于人的步骤记忆里**：
脚本没有、守卫没有、失败形态是「换个环境就没人知道该装什么」。

本守卫钉住的是「可复算」而不是「有文件」：

  1. 工具链清单必须**逐件点名**（`csc.exe` / `robocopy` 单独探测，不在 `which` 名单里）；
  2. 版本只能读事实源 `tauri.conf.json`，且与 `package.json` 咬合 —— 脚本里不得出现
     版本字面量（出现了就是第二份定义，改版本时必然漂移且不会有任何红）；
  3. 构建链只有一处定义：脚本必须调用仓内既有 `package_installer_zip.py`，
     不得手抄第二份构建命令；
  4. 发布链同理：必须调用仓内既有 `cnb_release_assets.py`；
  5. 体积红线与 sha256 必须落在脚本里（产物体积塌成空壳要有红，不是靠人眼）。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_KIT = _REPO / "scripts" / "desktop" / "win_installer_kit.py"
_TAURI_CONF = _REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"
_PKG = _REPO / "NeurUI" / "package.json"

# 「产品版本」这一族的形态：主版本号是 1（本产品 1.0.0 系列）。
# **不能写成 `\d+\.\d+\.\d+` 的宽匹配** —— 那会把 .NET Framework 的
# 就地版本目录 `v4.0.30319` 一并判成产品版本字面量（实测踩过：守卫对着
# `_NETFX_INPLACE = "v4.0.30319"` 报红，而那是环境事实、不是产品版本）。
# 判据写宽了会逼着实现去改结构躲判据，那是判据错、不是实现错。
# 与 `test_installer_version_single_source.py` 的 `_VERSION_LITERAL` 同源同形。
_VERSION_LITERAL = re.compile(r"\bv?1\.0\.0(?:-[\w.]+)?\b")
# 注释里的说明文字不算「写死版本」——判据看的是**活的表达式**，
# 不是散文。注释会被摘掉再判。
_HASHLINE = re.compile(r"(?m)^\s*#.*$")


def _kit_source() -> str:
    return _KIT.read_text(encoding="utf-8")


def _kit_ast() -> ast.Module:
    return ast.parse(_kit_source())


def _raises_runtime_error(fn: ast.FunctionDef) -> bool:
    """该函数体里是否有 `raise RuntimeError(...)`（看结构，不看措辞）。"""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Raise):
            continue
        exc = node.exc
        name = ""
        if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
            name = exc.func.id
        elif isinstance(exc, ast.Name):
            name = exc.id
        if name == "RuntimeError":
            return True
    return False


def _functions() -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in ast.walk(_kit_ast()) if isinstance(n, ast.FunctionDef)}


def testToolchainIsNamedItemByItem():
    """工具链必须逐件点名：csc.exe / robocopy 走独立探测，且缺席即失败。"""
    src = _kit_source()
    assert "csc.exe" in src, "必须显式探测 csc.exe（WPF 壳的唯一编译器）"
    assert "robocopy" in src, "必须显式探测 robocopy（后端资源暂存依赖它）"
    funcs = _functions()
    assert "probe_toolchain" in funcs, "必须有一个逐件点名的工具链探测函数"
    assert "csc_path" in funcs, "csc.exe 的探测必须独立成函数（Windows 自带件，不在 PATH）"

    # 判据看**结构**：缺席判定必须与探测同链 —— 即 probe_toolchain 自己会抛。
    # 不写「if missing:\n raise」这种按措辞匹配的正则：缩进、变量名、注释
    # 一变就假红，而假红会逼着实现去改结构躲判据（判据错，不是实现错）。
    assert _raises_runtime_error(funcs["probe_toolchain"]), \
        "probe_toolchain 必须自己把缺席抛出来（判据与动作同链，调用点不各写一份）"
    for node in ast.walk(funcs["probe_toolchain"]):
        if isinstance(node, ast.Return) and node.value is not None:
            assert isinstance(node.value, ast.Name), \
                "probe_toolchain 只应原样返回缺席清单，不得在返回处丢掉判据"


def testVersionHasNoLiteralInKit():
    """脚本里不得写死产品版本 —— 版本只能读自 tauri.conf.json。

    只判**活的表达式**：先摘掉注释。注释里写 `v4.0.30319`（.NET 运行时版本）
    或复述产品版本，都不是第二份定义，不该红。
    """
    code = _HASHLINE.sub("", _kit_source())
    offenders = [
        line.strip()
        for line in code.splitlines()
        if _VERSION_LITERAL.search(line) and "tauri.conf" not in line
    ]
    assert offenders == [], (
        "打包机脚本里写死了产品版本字面量（版本事实源是 tauri.conf.json）：\n"
        + "\n".join(offenders)
    )


def testKitReadsVersionFromSingleSource():
    """版本必须读事实源，且事实源两侧咬合。"""
    src = _kit_source()
    assert "tauri.conf.json" in src, "版本必须读自 NeurUI/src-tauri/tauri.conf.json"
    tauri_ver = json.loads(_TAURI_CONF.read_text(encoding="utf-8"))["version"]
    pkg_ver = json.loads(_PKG.read_text(encoding="utf-8"))["version"]
    assert tauri_ver == pkg_ver, (
        f"版本事实源分叉：tauri.conf.json={tauri_ver} / package.json={pkg_ver}"
    )


def testBuildChainHasSingleDefinition():
    """构建链只有一处定义：必须调用仓内既有打包脚本，不手抄第二份。"""
    src = _kit_source()
    assert "package_installer_zip.py" in src, \
        "必须复用 scripts/desktop/package_installer_zip.py（不得手抄第二份构建命令）"
    # 不得在本脚本里自己调 tauri build / csc —— 那正是要收口掉的第二份定义
    assert "tauri build" not in src, "构建命令不得在打包机脚本里再造一份（收口到打包脚本）"


def testPublishChainReusesRepoScript():
    """发布链同理：复用仓内既有 Release 上传脚本。"""
    assert "cnb_release_assets.py" in _kit_source(), \
        "必须复用 scripts/desktop/cnb_release_assets.py 上传附件"


def testArtifactSizeFloorAndChecksumAreEnforced():
    """体积红线与 sha256 必须落在脚本里（塌成空壳要有红）。"""
    src = _kit_source()
    assert "300" in src and "sha256" in src.lower(), \
        "必须校验体积红线并落 sha256 校验文件"
    assert re.search(r"raise RuntimeError\(f?\"?产物体积异常偏小", src), \
        "体积低于红线必须抛错，不得只打印警告"


def testKitRefreshesMachinePathBeforeProbe():
    """打包机脚本也要刷新机器 PATH —— 与流水线同一根因（Issue #332 实机踩到）。

    实机证据（2026-09-30，节点 orange-connector）：Runner 以服务常驻，进程环境在
    服务启动那刻冻结。此后 `choco install python312` / `nsis` 写进机器 PATH 的条目
    读不到 —— `python.exe` 与 `makensis.exe` 都在盘上，`Get-Command` 却 MISSING。

    人手工在打包机上跑 `install` 之后**重开 PowerShell 才生效**（脚本结尾就是这么
    提示的），但 `run` 一旦被自动化调用（本仓流水线、或任何 CI 包装），就落在冻结的
    环境里。故 `run` 的工具链探测之前必须自行合并机器/用户 PATH —— 与 `.cnb.yml`
    的同名修法同源（教义第 5 条：同一根因全命中点扫荡）。
    """
    src = _kit_source()
    # 判据看「有没有去读机器级 PATH」，不绑定语言习语：本脚本是 Python，
    # 走 winreg 读 HKLM\...\Environment 才是自然写法；`.cnb.yml` 那边是
    # PowerShell，用 GetEnvironmentVariable —— 两处同根因、不同形态，
    # 把判据写成某一种习语的字面量会在另一边假红（实测踩过）。
    assert "refresh_machine_path" in src, (
        "缺机器 PATH 刷新入口函数：工具链探测会读到冻结的进程环境，"
        "后装的 python/makensis 在盘上却查不到"
    )
    assert "Session Manager\\Environment" in src or "HKEY_LOCAL_MACHINE" in src, (
        "刷新必须真去读机器级注册表 PATH（HKLM），而不是只读进程环境凑数"
    )
    funcs = _functions()
    assert "refresh_machine_path" in funcs, "刷新必须独立成函数，调用点不各写一份"
    # 必须发生在探测之前：run 里 refresh 调用点先于 probe_toolchain 调用点。
    run_src = src[src.find("def cmd_run"):src.find("def newest_installer")]
    assert run_src.find("refresh_machine_path()") != -1, "cmd_run 里没有刷新调用"
    assert run_src.find("refresh_machine_path()") < run_src.find("probe_toolchain()"), (
        "刷新必须在工具链探测之前 —— 探测读的就是刷新后的 PATH"
    )
