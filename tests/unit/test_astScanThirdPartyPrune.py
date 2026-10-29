# -*- coding: utf-8 -*-
"""前置守卫修复（A3a 的开工拦路虎）：`tests/ast_scan.py` 的扫描面被第三方代码淹没。

实测（2026-10-08，本机）：`filesUnder(Path('.'))` 返回 **35965** 个 `.py`，其中
**32711 个落在 `.venv` / `node_modules`** 里；`sourceRefsUnder()` 的文本预筛必须先把
每个文件读一遍，实测**全量读文本 49.68s**，直接越过 pyproject 的全局 `timeout = 30`。
后果不是慢，是**整个 `tests/unit/cognitive_layers/` 目录在开发机上不可跑**
（`test_temperature_single_source.py::test_no_duplicate_decay_curve_definition` 被击杀）——
与台账 §6-43（`tests/unit/computer_use` 单跑超墙钟）同族：**判据成本绑在仓库外的代码量上**。

为什么在 CI 上看不出来：仓外只读 worktree 或干净检出里没有 `.venv`，实测同一判据在
`E:/tmp/a1base`（detached HEAD 的精简检出，仅 3220 个 .py）5.87s 通过。也就是说这条
判据的绿灯与否取决于**跑它的那台机器装了什么**，这正是要消除的形态。

修法边界（关键取舍）：只跳过第三方/构建产物目录，**不缩小仓内代码面**——
`neurova/`、`tests/`、`scripts/`、`docs/` 一个文件都不放过。判据强度不降反升：
修复前"扫 3 万个第三方文件"根本不可能命中本仓违规，纯粹是烧时间。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

import ast_scan  # noqa: E402

THIRD_PARTY_MARKERS = (".venv", "node_modules", "site-packages", ".git")


def _partsHit(path: Path, markers=THIRD_PARTY_MARKERS) -> bool:
    return any(part in markers for part in path.parts)


def testFilesUnderExcludesThirdPartyTrees():
    """扫描面不得包含第三方代码目录（否则判据成本取决于本机装了什么）。"""
    files = ast_scan.filesUnder(REPO_ROOT)
    hits = sorted({str(p.relative_to(REPO_ROOT)) for p in files if _partsHit(p)})
    assert not hits, (
        f"`filesUnder` 仍把第三方树算进扫描面（命中 {len(hits)} 类，示例 {hits[:3]}）——"
        "实测本仓 35965 个 .py 里 32711 个来自 .venv/node_modules，"
        "全量读文本 49.68s 越过 30s 墙钟"
    )


def testFilesUnderStillCoversRepoCode():
    """反向一格：排除第三方不等于漏掉仓内代码（判据强度只增不减）。"""
    files = ast_scan.filesUnder(REPO_ROOT)
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in files}

    assert any(r.startswith("neurova/") for r in rels), "生产代码面被误删出扫描范围"
    assert any(r.startswith("tests/") for r in rels), "测试面被误删出扫描范围"
    assert any(r.startswith("scripts/") for r in rels), "脚本面被误删出扫描范围"
    # 数量级下界：仓内 tracked .py 远多于 1000，真被砍窄会在这里露出来
    assert len(files) > 1000, f"扫描面只剩 {len(files)} 个文件，判据已被砍窄"


def testSourceRefsWithHintDoesNotReadThirdParty():
    """行为一格：带文本预筛的取数只读仓内文件，命中面里不得出现第三方路径。"""
    refs = ast_scan.sourceRefsUnder(REPO_ROOT, hints=("def ",))
    offenders = [str(r.path.relative_to(REPO_ROOT)) for r in refs if _partsHit(r.path)]
    assert not offenders, f"预筛结果混入第三方文件（示例 {offenders[:3]}）"


def testPlantedViolationInsideRepoIsStillFound(tmp_path, monkeypatch):
    """正向自证：往仓内目录种一条违规，判据必须抓到（防止"排除"写成"什么都不扫"）。

    用 monkeypatch 把扫描根指向 tmp_path 的镜像结构不合适（会把仓内文件也排除掉），
    这里直接验 `filesUnder` 对新文件的包含性——它才是"排除第三方不排仓内"的落点。
    """
    planted = REPO_ROOT / "neurova" / "_ast_scan_probe_tmp.py"
    planted.write_text("def _calculate_curve_factor(x):\n    return x\n", encoding="utf-8")
    try:
        files = ast_scan.filesUnder(REPO_ROOT)
        assert any(p.name == planted.name for p in files), (
            "新建的仓内文件没被扫到——排除规则写得过宽"
        )
    finally:
        planted.unlink()


#: ── 同一把尺的第二段（2026-10-29）：本仓自己的**构建产物副本**与**仓根在途散件**──────────
#: 上面那些表剪的是"仓外第三方"。同日实测两类**仓内**的本地产物把三条存量比对判据读成了
#: 仓库缺陷（CI 那棵干净检出里它们根本不红）：
#: ① `NeurUI/src-tauri/resources/backend/**` 与 `NeurUI/src-tauri/target/release/backend/**`
#:    各是一棵**完整后端源码的副本**（`git check-ignore -v` 分别命中 `.gitignore:367` 与
#:    `NeurUI/src-tauri/.gitignore:3`；`git ls-files` 两棵都 0 条），于是
#:    「全仓只剩一处 `class EventBus`」量到 3 处、「`SkillSource` 只定义在 `models.py`」量到 3 个档；
#: ② 仓根躺着别人在途的 `.tmp_*.py`／`_*.py`（`.gitignore:378`／`:135`，都是根锚定模式），
#:    其中一份语法不通时「退役后无人导入」当场红，报错还点名一个不存在的文件。
#: 判据的**牙齿探针**会把样本档现种进仓内（上面那格就是），所以这两张表按**位置**剪，
#: 不按 gitignore 状态剪——后者实测一把滤掉三处牙齿，且白名单只要按进程缓存，
#: 跑测中途新建的档就永久不可见。
def testBuildProductBackendCopiesStayOutOfTheFace():
    """行为一格：真身在面里，两棵构建产物副本不在（撤剪枝时这一格必须红）。"""
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in ast_scan.filesUnder(REPO_ROOT)}
    assert "neurova/core/event_bus.py" in rels, "生产根那份真身都不在面里＝扫描面塌了"
    copies = sorted(r for r in rels if r.startswith("NeurUI/src-tauri/"))
    assert not copies, (
        f"Tauri 构建产物副本进了扫描面（{len(copies)} 档，示例 {copies[:3]}）——"
        "「全仓只剩一处 `class EventBus`」这类判据会把它读成第二份实装"
    )


def testRepoRootScratchStaysOutOfTheFace():
    """行为一格：仓根当层的在途散件不进面；下限格先立住"确实扫到了"。"""
    files = ast_scan.filesUnder(REPO_ROOT)
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    scratch = sorted(r for r in rels if "/" not in r and (
        r.startswith(".tmp_") or (r.startswith("_") and r.endswith(".py"))))
    assert not scratch, (
        f"仓根在途散件进了扫描面（示例 {scratch[:4]}）——其中一份语法不通时，"
        "「退役后无人导入」这类存量比对会红在一个不存在的文件上"
    )
    assert len(files) > 3000, (
        f"扫描面只剩 {len(files)} 个 .py，地板 3000 被打破＝剪枝把仓内代码也剪没了")

