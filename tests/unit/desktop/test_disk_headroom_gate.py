# -*- coding: utf-8 -*-
r"""构建前磁盘余量闸守卫：多 GB 级 target 写入之前必须先证明放得下。

为什么要有本守卫（2026-10-08 取证，根因不在 rustc 也不在 tauri）：

1. **盘满不以 ENOSPC 露面**。2026-09-05 E: 打到 100%（当日读数最低 28 MB）时，
   Ubuntu 的根文件系统正是 `E:\wsl\Ubuntu\ext4.vhdx`——宿主无余量 → 无法分配新块 →
   VM 内表现为 **EIO**，rustc 的 mmap 页无法后备 → **SIGBUS(7)**，7 个崩溃转储
   （2.18 GB）又落进 C 盘 Temp 反过来再吃 C 盘。全程没有任何一处**提前**说过"盘不够"。

2. **命中点不止一个入口**。`npx tauri build` 走 `beforeBuildCommand`，`tauri dev` 走
   `beforeDevCommand`（也写 debug target），而 CI 自托管 Windows 节点的脚本**直接跑在
   宿主机上**、经 `scripts/desktop/package_installer_zip.py::build_tauri` 串起来。
   只闸其中一个，另外两个照样把盘写穿。

3. **阈值不能有两份**。闸值写在建置里（`tauri.conf.json`）和写在模块里会各自漂移；
   事实源只允许 `scripts/desktop/disk_headroom.py` 一处，配置只负责引用它。

判据形态说明：① 全部用**真实盘读数**，靠两个方向的阈值（一个必然满足、一个物理上
不可能满足）逼出两侧行为，不注入假读数——假的 `disk_usage` 会替生产代码算出结论。
② 接线用静态断言（读源码/读 JSON），与 `test_docker_image_pipeline_wiring.py` 同形态；
因为"真跑一次 tauri build"要十几分钟且会改盘，不是判据该付的代价。
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from tests.ast_scan import parseSource

_REPO = Path(__file__).resolve().parents[3]
_GATE = _REPO / "scripts" / "desktop" / "disk_headroom.py"

#: 闸脚本子进程的预算唯一出处（§6-402 批 K 口径）。实测这条只读盘一次、毫秒级——120s 是把
#: 安全感写进代码，而 120s 子墙配缺省 30s 父墙时先到点的是父墙：Windows 侧 thread 法超时
#: 即终止整个进程。收成**低于全局墙**的 20s，整档因此不必抬父墙。
GATE_WALL_S = 20
_TAURI_CONF = _REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"
_INSTALLER = _REPO / "scripts" / "desktop" / "package_installer_zip.py"


def _loadGate():
    """按本仓既有形态加载脚本模块（`scripts/desktop` 没有 `__init__.py`）。"""
    spec = importlib.util.spec_from_file_location("disk_headroom", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _runGate(args, cwd=None):
    # 被调的闸脚本是本仓 Python 件 ⇒ 两头钉死（子端 PYTHONIOENCODING=utf-8、父端按 utf-8 解）。
    # 闸的读数里带仓库路径（含「项目」二字），只补父端 encoding 会把那条路径读成 U+FFFD。
    return subprocess.run([sys.executable, str(_GATE), *[str(a) for a in args]],
                          capture_output=True, text=True, cwd=str(cwd or _REPO),
                          timeout=GATE_WALL_S,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                          encoding="utf-8", errors="replace")


def test_gateModuleIsTheSingleSourceOfTheThreshold():
    assert _GATE.is_file(), "闸值没有事实源文件"

    assert _loadGate().MIN_FREE_GB > 0


def test_gatePassesWhenRealHeadroomIsEnough(tmp_path):
    result = _runGate([tmp_path, "--min-gb", "0.0001"])

    assert result.returncode == 0, result.stdout + result.stderr


def test_gateFailsHonestWhenThresholdIsImpossible(tmp_path):
    result = _runGate([tmp_path, "--min-gb", "1000000"])

    assert result.returncode != 0, "盘余量不足必须响亮失败，不能静默放行"
    combined = (result.stdout + result.stderr).lower()
    # 诚实形态：点名闸的是什么位置、实测还剩多少、要求多少
    assert str(tmp_path).lower() in combined or str(tmp_path.drive).lower() in combined, \
        "失败信息没点名被检查的盘/路径：" + result.stdout + result.stderr
    assert "1000000" in combined, "失败信息没点名闸值"


def test_gateDerivesDriveFromTheTargetDirNotFromACurrentLetter():
    """target 目录还不存在时（干净机首次构建）也要能判——必须退到最近的存在祖先。"""
    disk_headroom = _loadGate()

    notYet = _REPO / "NeurUI" / "src-tauri" / "target" / "release" / "never-created-yet"
    assert not notYet.exists()

    freeBytes = disk_headroom.freeBytesAt(notYet)

    assert freeBytes > 0, "路径不存在时应回退到最近的已存在祖先取读数，而不是报错"


def test_tauriConfWiresGateAtBothBuildAndDev(tmp_path):
    """dev 也往 target 写 debug 产物，只闸 build 会漏一半命中点。"""
    conf = json.loads(_TAURI_CONF.read_text(encoding="utf-8"))
    buildCmd = conf["build"]["beforeBuildCommand"]
    devCmd = conf["build"]["beforeDevCommand"]

    assert "disk_headroom" in buildCmd, "tauri build 入口没接空间闸：" + buildCmd
    assert "disk_headroom" in devCmd, "tauri dev 入口没接空间闸：" + devCmd
    # 单一事实源：阈值不得在配置里再抄一份字面量
    assert "min-gb" not in buildCmd and "--min-gb" not in devCmd, \
        "阈值被抄进了建置，形成第二份定义"


def test_installerPipelineGatesBeforeFrontendAndRustBuild():
    """CI 自托管节点经 build_tauri 串构建，这里也必须先过闸。

    顺序判定取 **AST 调用节点的行号**，不取源码子串位置：子串会命中函数文档串里那句
    "npm run build:desktop + npx tauri build"，于是闸明明在两个真实写盘动作之前，
    却被判成"排在后面"。文档串不会被 walk 成 Call，假命中因此消失。
    """
    source = _INSTALLER.read_text(encoding="utf-8")
    tree = parseSource(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "build_tauri")
    callSegments = [(n.lineno, ast.get_source_segment(source, n) or "")
                    for n in ast.walk(fn) if isinstance(n, ast.Call)]

    def firstLine(needle):
        hits = sorted(ln for ln, seg in callSegments if needle in seg)
        return hits[0] if hits else None

    gateLine = firstLine("disk_headroom.assertHeadroom")
    npmLine = firstLine("npm run build:desktop")
    rustLine = firstLine('"tauri", "build"')

    assert gateLine is not None, "build_tauri 没接空间闸"
    assert npmLine is not None and rustLine is not None, "构建调用点变了，本判据的观测对象失效"
    assert gateLine < npmLine, "闸必须早于前端构建，而不是失败之后再补"
    assert gateLine < rustLine, "闸必须早于 Rust release 构建"
